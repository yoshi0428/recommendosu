"""
The fusion classifier: one network that reads the hit objects and the map
stats of a beatmap together, and predicts its tournament slots (NM1-NM5).

    rich sequence  [objects, 21] per-object channels from the .osu file (rich_sequence())
                   -> residual 1D CNN -> masked mean / max / std
    map stats      per-mod variant stats + movement features (tabular_row())
                   -> small MLP
    both           -> MLP head -> one logit per slot (multi-label: a map can be in several slots)

Training keeps an exponential moving average (EMA) of the weights, and it
validates and keeps that average. In the experiments, this matched a 5-seed
ensemble. It replaces the earlier two-stage CNN -> XGBoost model, with about
+1 point of top-1 out-of-fold accuracy (see train_fusion.py for the numbers).

train_fusion.py (training) and inference.py (prediction) use it.
"""

import copy
import json
import math
import re
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from torch import nn

from beatmap_classifier.classifier.movement_features import extract_movement_features_from_X

# A map is cut to this many hit objects.
MAX_SEQUENCE_LENGTH = 4096

# ============================================================
# Rich sequence (one row for each object)
# ============================================================
# The channels of object i. The move starts where object i-1 ends (for a slider, its tail):
RICH_CHANNELS = [
    "dx",  # / 512
    "dy",  # / 384
    "distance",  # / 512
    "log_ms_since_previous_head",
    "log_ms_since_previous_end",
    "log2_beats_since_previous_head",
    "is_slider",
    "is_spinner",
    "slider_beats",
    "slider_repeats",
    "slider_travel",  # head -> path end, / 512
    "slider_path_dx",  # / 512
    "slider_path_dy",  # / 384
    "new_combo",
    "cos_turn_angle",
    "x",  # / 512
    "y",  # / 384
    "log_objects_within_1s",
    "slider_velocity",
    "bpm",  # / 200
    "log_px_per_ms",  # from the end of the previous object to this head
]
# Horizontal / vertical flips (augmentation): these channels change sign,
FLIP_X, FLIP_Y = [0, 11], [1, 12]
# and these absolute positions become 1 - value.
MIRROR_X, MIRROR_Y = [15], [16]


def _read_text(path):
    """Return the text of a file: UTF-8, UTF-16 or latin-1."""
    raw = Path(path).read_bytes()
    for encoding in ("utf-8-sig", "utf-16", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeError:
            continue
    return raw.decode("latin-1", "replace")


def rich_sequence(path):
    """
    Return the [objects - 1, 21] rich sequence of an osu!standard .osu file
    (RICH_CHANNELS). Return None for another mode, or for a map with fewer
    than 4 objects or no timing point.
    """
    section, slider_multiplier, mode = None, 1.4, 0
    timing, objects = [], []  # timing: (time, beat_length or None, slider velocity or None)

    for line in _read_text(path).splitlines():
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            continue

        if section == "General" and line.startswith("Mode"):
            try:
                mode = int(line.split(":", 1)[1])
            except ValueError:
                pass
        elif section == "Difficulty" and line.startswith("SliderMultiplier"):
            try:
                slider_multiplier = float(line.split(":", 1)[1])
            except ValueError:
                pass
        elif section == "TimingPoints":
            parts = line.split(",")
            if len(parts) < 2:
                continue
            try:
                t, beat_length = float(parts[0]), float(parts[1])
            except ValueError:
                continue
            uninherited = len(parts) < 7 or parts[6].strip() == "1"
            if uninherited and beat_length > 0:
                timing.append((t, beat_length, None))
            elif beat_length < 0:
                timing.append((t, None, min(10.0, max(0.1, -100.0 / beat_length))))
        elif section == "HitObjects":
            parts = line.split(",")
            if len(parts) < 4:
                continue
            try:
                x, y, t, kind = float(parts[0]), float(parts[1]), float(parts[2]), int(parts[3])
            except ValueError:
                continue
            o = {"x": x, "y": y, "t": t, "nc": 1.0 if kind & 4 else 0.0, "kind": 0, "ex": x, "ey": y,
                 "slides": 0, "length": 0.0, "end_t": t}
            if kind & 2 and len(parts) >= 8:
                points = re.findall(r"(-?\d+(?:\.\d+)?):(-?\d+(?:\.\d+)?)", parts[5])
                last_x, last_y = (float(points[-1][0]), float(points[-1][1])) if points else (x, y)
                try:
                    slides, length = max(1, int(float(parts[6]))), max(0.0, float(parts[7]))
                except ValueError:
                    slides, length = 1, 0.0
                # The path end: the last control point, scaled back to the slider length in that direction.
                dx, dy = last_x - x, last_y - y
                straight = math.hypot(dx, dy)
                if straight > 0 and length > 0 and straight > length:
                    dx, dy = dx * length / straight, dy * length / straight
                o.update(kind=1, slides=slides, length=length, px=dx, py=dy)
                o["ex"], o["ey"] = (x + dx, y + dy) if slides % 2 == 1 else (x, y)
            elif kind & 8:
                o["kind"] = 2
                try:
                    o["end_t"] = float(parts[5])
                except (ValueError, IndexError):
                    pass
                o["ex"], o["ey"] = 256.0, 192.0
            objects.append(o)

    if mode != 0 or len(objects) < 4 or not any(bl for _, bl, _ in timing):
        return None
    objects.sort(key=lambda o: o["t"])
    timing.sort(key=lambda point: point[0])

    # The beat length and the slider velocity at each object.
    beat_length, velocity, k = next(bl for _, bl, _ in timing if bl), 1.0, 0
    for o in objects:
        while k < len(timing) and timing[k][0] <= o["t"] + 1:
            if timing[k][1]:
                beat_length, velocity = timing[k][1], 1.0
            else:
                velocity = timing[k][2]
            k += 1
        o["bl"], o["sv"] = beat_length, velocity
        if o["kind"] == 1:
            o["dur_beats"] = o["length"] * o["slides"] / (slider_multiplier * 100 * velocity)
            o["end_t"] = o["t"] + o["dur_beats"] * beat_length
        else:
            o["dur_beats"] = (o["end_t"] - o["t"]) / beat_length if o["kind"] == 2 else 0.0

    times = np.array([o["t"] for o in objects])
    density = np.searchsorted(times, times + 1000) - np.searchsorted(times, times - 1000)
    rows, previous_move = [], None
    for i in range(1, len(objects)):
        a, o = objects[i - 1], objects[i]
        dx, dy = o["x"] - a["ex"], o["y"] - a["ey"]
        distance = math.hypot(dx, dy)
        dt = max(o["t"] - a["t"], 0.0)
        gap = max(o["t"] - a["end_t"], 0.0)
        cos = 0.0
        if previous_move is not None and distance > 1 and math.hypot(*previous_move) > 1:
            cos = (previous_move[0] * dx + previous_move[1] * dy) / (distance * math.hypot(*previous_move))
        previous_move = (dx, dy)
        is_slider = o["kind"] == 1
        rows.append([
            dx / 512, dy / 384, distance / 512, math.log1p(dt), math.log1p(gap),
            math.log2(max(dt / o["bl"], 1 / 64)), float(is_slider), float(o["kind"] == 2),
            min(o["dur_beats"], 64.0), float(o["slides"]),
            (math.hypot(o.get("px", 0), o.get("py", 0)) if is_slider else 0) / 512,
            o.get("px", 0) / 512, o.get("py", 0) / 384, o["nc"], cos, o["x"] / 512, o["y"] / 384,
            math.log1p(density[i]), o["sv"], 60000 / o["bl"] / 200, math.log1p(distance / max(gap, 10.0)),
        ])
    # Broken maps (absurd BPM or slide counts) can overflow float32, so the values are clipped.
    return np.clip(np.nan_to_num(np.array(rows, np.float64), nan=0.0), -50, 50).astype(np.float32)


# ============================================================
# Map stats (tabular input)
# ============================================================
# The beatmap_variants columns, from the variant row of each of these mods.
VARIANT_STATS = [
    "ar", "od", "circle_size", "star_rating", "bpm", "max_combo",
    "length_seconds", "object_count", "pp", "pp_aim", "pp_speed", "pp_acc",
]
STAT_MODS = ["NM", "HD", "HR", "DT"]
MOVEMENT_FEATURES = [
    "slider_ratio", "slider_length_std", "speed_std", "speed_change_std", "speed_change_max",
    "angle_std", "angle_mean", "rhythm_variance", "distance_mean", "speed_change_95th",
    "angle_90th", "sharp_turn_ratio",
]
TABULAR_FEATURES = [f"{mod}_{stat}" for mod in STAT_MODS for stat in VARIANT_STATS] + [
    f"movement_{name}" for name in MOVEMENT_FEATURES
]


def tabular_row(stats_by_mod, normalized_vectors):
    """
    Return the TABULAR_FEATURES row of one map.

    stats_by_mod: {"NM": {stat: value}, "HD": ..., "HR": ..., "DT": ...},
        for example the beatmap_variants rows of the map. A missing mod or
        value is 0 (as in training).
    normalized_vectors: its 8-channel vectors, scaled as get_data() scales them.
    """
    row = []
    for mod in STAT_MODS:
        stats = stats_by_mod.get(mod) or {}
        row += [stats[name] if stats.get(name) is not None else np.nan for name in VARIANT_STATS]
    vectors = np.asarray(normalized_vectors, np.float32)[:MAX_SEQUENCE_LENGTH]
    row += list(extract_movement_features_from_X(vectors))
    return np.nan_to_num(np.array(row, np.float32))


# ============================================================
# Standardization (fit on the training maps, and saved with the model)
# ============================================================
def fit_normalization(sequences, tabular):
    """Return the mean and std of each channel and feature. Flipped channels keep a zero mean, so a flip is a negation."""
    sample = np.concatenate(sequences[:: max(1, len(sequences) // 4000)])
    seq_mean, seq_std = sample.mean(0), sample.std(0) + 1e-6
    for c in FLIP_X + FLIP_Y:
        seq_mean[c] = 0.0
        seq_std[c] = np.sqrt((sample[:, c] ** 2).mean()) + 1e-6
    tabular = np.asarray(tabular, np.float32)
    return {
        "seq_mean": seq_mean.tolist(),
        "seq_std": seq_std.tolist(),
        "tab_mean": tabular.mean(0).tolist(),
        "tab_std": (tabular.std(0) + 1e-6).tolist(),
    }


class Batcher:
    """Standardize and pad maps into batches: x [B, L, 21], mask [B, L], tab [B, F]."""

    def __init__(self, sequences, tabular, normalization, device):
        self.sequences = [np.asarray(s, np.float32)[:MAX_SEQUENCE_LENGTH] for s in sequences]
        self.device = device
        n = normalization
        self.seq_mean, self.seq_std = np.array(n["seq_mean"], np.float32), np.array(n["seq_std"], np.float32)
        tab_mean, tab_std = np.array(n["tab_mean"], np.float32), np.array(n["tab_std"], np.float32)
        self.tabular = np.clip((np.asarray(tabular, np.float32) - tab_mean) / tab_std, -10, 10)

    def __len__(self):
        return len(self.sequences)

    def batch(self, rows, flips=None):
        """flips: None, or one (flip_x, flip_y) pair for each row (training augmentation)."""
        length = max(1, max(len(self.sequences[i]) for i in rows))
        x = np.zeros((len(rows), length, len(RICH_CHANNELS)), np.float32)
        mask = np.zeros((len(rows), length), np.float32)
        for k, i in enumerate(rows):
            s = self.sequences[i]
            if flips is not None:
                flip_x, flip_y = flips[k]
                s = s.copy()
                if flip_x:
                    s[:, FLIP_X] *= -1
                    s[:, MIRROR_X] = 1 - s[:, MIRROR_X]
                if flip_y:
                    s[:, FLIP_Y] *= -1
                    s[:, MIRROR_Y] = 1 - s[:, MIRROR_Y]
            x[k, : len(s)] = (s - self.seq_mean) / self.seq_std
            mask[k, : len(s)] = 1
        to = lambda a: torch.from_numpy(a).to(self.device)
        return to(x), to(mask), to(self.tabular[list(rows)])


# ============================================================
# Model
# ============================================================
def masked_pool(h, mask):
    """h [B, L, D], mask [B, L] -> mean, max and std over the real positions, joined into [B, 3D]."""
    m = mask.unsqueeze(-1)
    n = m.sum(1).clamp(min=1)
    mean = (h * m).sum(1) / n
    maximum = (h * m - (1 - m) * 1e4).amax(1)
    std = (((h - mean.unsqueeze(1)) ** 2 * m).sum(1) / n).clamp(min=1e-6).sqrt()
    return torch.cat([mean, maximum, std], 1)


class ResBlock(nn.Module):
    """Two masked 1D convolutions with a skip connection."""

    def __init__(self, cin, cout, kernel=5, dropout=0.1):
        super().__init__()
        self.c1 = nn.Conv1d(cin, cout, kernel, padding=kernel // 2, bias=False)
        self.b1 = nn.BatchNorm1d(cout)
        self.c2 = nn.Conv1d(cout, cout, kernel, padding=kernel // 2, bias=False)
        self.b2 = nn.BatchNorm1d(cout)
        self.skip = nn.Identity() if cin == cout else nn.Sequential(nn.Conv1d(cin, cout, 1, bias=False), nn.BatchNorm1d(cout))
        self.drop = nn.Dropout(dropout)

    def forward(self, x, m):
        h = self.drop(F.relu(self.b1(self.c1(x))) * m)
        return F.relu(self.b2(self.c2(h)) + self.skip(x)) * m


class FusionCNN(nn.Module):
    """A residual CNN over the rich sequence (3 stages, with a 2x max-pool between them) + an MLP over the map stats."""

    def __init__(self, num_channels, num_tabular, num_classes, widths=(32, 64, 128), dropout=0.3):
        super().__init__()
        self.stem = nn.Sequential(nn.Conv1d(num_channels, widths[0], 7, padding=3, bias=False),
                                  nn.BatchNorm1d(widths[0]), nn.ReLU())
        self.blocks = nn.ModuleList()
        cin = widths[0]
        for w in widths:
            self.blocks.append(ResBlock(cin, w))
            cin = w
        self.tab_net = nn.Sequential(nn.Linear(num_tabular, 128), nn.ReLU(), nn.Dropout(0.1))
        self.head = nn.Sequential(nn.Linear(3 * cin + 128, 128), nn.ReLU(), nn.Dropout(dropout),
                                  nn.Linear(128, num_classes))

    def forward(self, x, mask, tab):
        m = mask.unsqueeze(1)
        h = self.stem(x.transpose(1, 2)) * m
        for i, block in enumerate(self.blocks):
            h = block(h, m)
            if i < len(self.blocks) - 1:
                h = F.max_pool1d(h, 2, ceil_mode=True)
                m = F.max_pool1d(m, 2, ceil_mode=True)
        pooled = masked_pool(h.transpose(1, 2), m.squeeze(1))
        return self.head(torch.cat([pooled, self.tab_net(tab)], 1))


def new_model(num_classes):
    """Return a new FusionCNN for the current RICH_CHANNELS and TABULAR_FEATURES."""
    return FusionCNN(len(RICH_CHANNELS), len(TABULAR_FEATURES), num_classes)


# ============================================================
# Training and prediction
# ============================================================
def _autocast(device):
    """Use bfloat16 autocast on CUDA. On the CPU, autocast is off."""
    if device.type == "cuda":
        return torch.autocast("cuda", dtype=torch.bfloat16)
    return torch.autocast("cpu", enabled=False)


@torch.no_grad()
def predict_logits(model, batcher, rows, batch_size=64):
    """Return the logits [len(rows), K] of one model."""
    model.eval()
    rows = np.asarray(rows)
    out = np.zeros((len(rows), model.head[-1].out_features), np.float32)
    order = np.argsort([len(batcher.sequences[i]) for i in rows])  # Similar lengths in each batch: less padding
    for s in range(0, len(rows), batch_size):
        idx = order[s : s + batch_size]
        x, mask, tab = batcher.batch(rows[idx])
        with _autocast(batcher.device):
            out[idx] = model(x, mask, tab).float().cpu().numpy()
    return out


def predict(models, batcher, rows):
    """Return the mean sigmoid probability of each slot [len(rows), K] over one or more (bagged) models."""
    return np.mean([1 / (1 + np.exp(-predict_logits(m, batcher, rows))) for m in models], axis=0)


def train(batcher, Y, train_rows, val_rows, epochs=60, patience=12, lr=1e-3, weight_decay=1e-3,
          batch_size=32, ema_decay=0.999, log=""):
    """
    Train one model on train_rows (Y is multi-hot [maps, K]), with an early
    stop on the loss of val_rows. Return the EMA model of the best epoch.
    """
    device = batcher.device
    model = new_model(Y.shape[1]).to(device)
    ema = torch.optim.swa_utils.AveragedModel(
        model, multi_avg_fn=torch.optim.swa_utils.get_ema_multi_avg_fn(ema_decay), use_buffers=True
    )  # use_buffers: the BatchNorm statistics are averaged too
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=weight_decay)
    steps_per_epoch = math.ceil(len(train_rows) / batch_size)
    total_steps = epochs * steps_per_epoch

    def lr_factor(step):  # 1 epoch of warmup, then a cosine decrease to 2%
        if step < steps_per_epoch:
            return (step + 1) / steps_per_epoch
        p = (step - steps_per_epoch) / max(1, total_steps - steps_per_epoch)
        return 0.02 + 0.98 * 0.5 * (1 + math.cos(math.pi * p))

    scheduler = torch.optim.lr_scheduler.LambdaLR(optimizer, lr_factor)
    train_rows, val_rows = np.asarray(train_rows), np.asarray(val_rows)
    Y_train = torch.as_tensor(Y[train_rows], dtype=torch.float32, device=device)
    Y_val = torch.as_tensor(Y[val_rows], dtype=torch.float32)

    best_loss, best_state, bad_epochs = float("inf"), None, 0
    for epoch in range(epochs):
        model.train()
        start, total_loss = time.time(), 0.0
        perm = np.random.permutation(len(train_rows))
        for s in range(0, len(perm), batch_size):
            idx = perm[s : s + batch_size]
            flips = np.random.rand(len(idx), 2) < 0.5
            x, mask, tab = batcher.batch(train_rows[idx], flips=flips)
            with _autocast(device):
                logits = model(x, mask, tab)
            loss = F.binary_cross_entropy_with_logits(logits.float(), Y_train[idx])
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            scheduler.step()
            ema.update_parameters(model)
            total_loss += loss.item() * len(idx)

        val_logits = torch.as_tensor(predict_logits(ema.module, batcher, val_rows))
        val_loss = float(F.binary_cross_entropy_with_logits(val_logits, Y_val))
        top1 = float((Y[val_rows][np.arange(len(val_rows)), val_logits.argmax(1).numpy()] > 0).mean())
        print(f"{log} epoch {epoch + 1:2d}  train {total_loss / len(perm):.4f}  val {val_loss:.4f}  "
              f"top-1 {top1:.4f}  ({time.time() - start:.0f}s)", flush=True)
        if val_loss < best_loss - 1e-4:
            best_loss, best_state, bad_epochs = val_loss, copy.deepcopy(ema.module.state_dict()), 0
        else:
            bad_epochs += 1
            if bad_epochs >= patience:
                break

    final = new_model(Y.shape[1]).to(device)
    final.load_state_dict(best_state)
    return final.eval()


# ============================================================
# Saving and loading
# ============================================================
def save(model_dir, models, classes, normalization, vector_normalization, info=None):
    """Save the models in the models/fusion layout: fusion_config.json + fusion_model_<fold>.pt."""
    model_dir = Path(model_dir)
    model_dir.mkdir(parents=True, exist_ok=True)
    for old in model_dir.glob("fusion_model_*.pt"):
        old.unlink()
    for i, model in enumerate(models):
        torch.save(model.state_dict(), model_dir / f"fusion_model_{i}.pt")
    config = {
        "classes": list(classes),
        "rich_channels": RICH_CHANNELS,
        "tabular_features": TABULAR_FEATURES,
        "normalization": normalization,
        # The scales that get_data() divided time_diff / slider length by. The movement features need them.
        "vector_normalization": vector_normalization,
        "info": info or {},
    }
    (model_dir / "fusion_config.json").write_text(json.dumps(config, indent=2))


def load(model_dir, device):
    """Return the (models, config) that save() saved."""
    model_dir = Path(model_dir)
    config = json.loads((model_dir / "fusion_config.json").read_text())
    if config["rich_channels"] != RICH_CHANNELS or config["tabular_features"] != TABULAR_FEATURES:
        raise ValueError(f"{model_dir} was trained with different inputs than fusion.py builds; retrain it")
    models = []
    for path in sorted(model_dir.glob("fusion_model_*.pt")):
        model = new_model(len(config["classes"]))
        model.load_state_dict(torch.load(path, map_location=device))
        models.append(model.to(device).eval())
    if not models:
        raise FileNotFoundError(f"no fusion_model_*.pt in {model_dir}")
    return models, config
