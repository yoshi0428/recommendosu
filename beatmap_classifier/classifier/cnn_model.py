import torch
import torch.nn.functional as F
from torch import nn

"""
Residual 1D CNN over a beatmap's hit-object vectors.

Input: [batch, channels, sequence], the 8 channels from get_data() /
normalize_beatmap_vectors(), zero-padded at the end.

Notes:
    - Padding is masked out everywhere, and the sequence is summarized with
      masked mean / max / std pooling, so maps of different lengths are
      treated the same (fixed-size adaptive pooling mostly pooled padding).
    - get_data() leaves the channels on very different scales (time_diff is
      divided by the longest break, ~86s, so typical values are ~0.002).
      transform_inputs() log-scales the time channels and divides every
      channel by its RMS on the training set. The RMS lives in the
      `input_scale` buffer, so it is saved with the state_dict and inference
      can't drift from training.
"""

TIME_DIFF_CHANNEL = 2
TIME_DIFF_CHANGE_CHANNEL = 7

# normalized time_diff * 1000 ~= ms / 86, which puts log1p in a useful range
TIME_LOG_SCALE = 1000.0


def padding_mask(x):
    """[batch, 1, sequence] float mask, 1 where a real hit-object vector is."""
    return (x.abs().sum(dim=1, keepdim=True) > 0).float()


def transform_inputs(x):
    """Log-scale the time channels. Keeps zeros (padding) at zero."""
    x = x.clone()
    x[:, TIME_DIFF_CHANNEL] = torch.log1p(x[:, TIME_DIFF_CHANNEL] * TIME_LOG_SCALE)

    time_diff_change = x[:, TIME_DIFF_CHANGE_CHANNEL]
    x[:, TIME_DIFF_CHANGE_CHANNEL] = torch.sign(time_diff_change) * torch.log1p(
        time_diff_change.abs() * TIME_LOG_SCALE
    )
    return x


def compute_input_scale(X):
    """
    Per-channel RMS of transform_inputs(X) over real (unpadded) positions.

    X: [batch, channels, sequence]. RMS rather than std so there is no mean
    shift, and padding stays exactly zero.
    """
    X = torch.as_tensor(X, dtype=torch.float32)
    channels = X.shape[1]
    sum_squares = torch.zeros(channels, dtype=torch.float64)
    count = 0

    # Chunked, so it doesn't copy the whole training set at once
    for start in range(0, len(X), 512):
        chunk = X[start : start + 512]
        mask = padding_mask(chunk).bool().squeeze(1)  # [batch, sequence]
        values = transform_inputs(chunk).permute(1, 0, 2)[:, mask]  # [channels, n]
        sum_squares += values.double().pow(2).sum(dim=1)
        count += values.shape[1]

    scale = (sum_squares / max(count, 1)).sqrt().float()
    return torch.where(scale > 0, scale, torch.ones_like(scale))


class ResidualBlock(nn.Module):
    def __init__(self, in_channels, out_channels, kernel_size=5, dropout_rate=0.1):
        super().__init__()
        padding = kernel_size // 2

        self.conv1 = nn.Conv1d(
            in_channels, out_channels, kernel_size, padding=padding, bias=False
        )
        self.bn1 = nn.BatchNorm1d(out_channels)
        self.conv2 = nn.Conv1d(
            out_channels, out_channels, kernel_size, padding=padding, bias=False
        )
        self.bn2 = nn.BatchNorm1d(out_channels)

        if in_channels != out_channels:
            self.skip = nn.Sequential(
                nn.Conv1d(in_channels, out_channels, 1, bias=False),
                nn.BatchNorm1d(out_channels),
            )
        else:
            self.skip = nn.Identity()

        self.dropout = nn.Dropout(dropout_rate)

    def forward(self, x, mask):
        h = F.relu(self.bn1(self.conv1(x))) * mask
        h = self.dropout(h)
        h = self.bn2(self.conv2(h))
        return F.relu(h + self.skip(x)) * mask


class CNNModel(nn.Module):
    def __init__(
        self,
        input_channels,
        num_classes,
        max_length=4096,
        dropout_rate=0.3,
        widths=(32, 64, 128),
        block_dropout_rate=0.1,
        input_scale=None,
    ):
        super().__init__()
        # max_length is unused (the model handles any length); kept so
        # existing model_kwargs still work.

        if input_scale is None:
            input_scale = torch.ones(input_channels)
        self.register_buffer(
            "input_scale", torch.as_tensor(input_scale, dtype=torch.float32)
        )

        self.stem = nn.Sequential(
            nn.Conv1d(input_channels, widths[0], kernel_size=7, padding=3, bias=False),
            nn.BatchNorm1d(widths[0]),
            nn.ReLU(),
        )

        blocks = []
        in_channels = widths[0]
        for width in widths:
            blocks.append(
                ResidualBlock(in_channels, width, dropout_rate=block_dropout_rate)
            )
            in_channels = width
        self.blocks = nn.ModuleList(blocks)

        self.pool = nn.MaxPool1d(2)

        # masked mean + max + std
        self.head = nn.Sequential(
            nn.Linear(in_channels * 3, 128),
            nn.ReLU(),
            nn.Dropout(dropout_rate),
            nn.Linear(128, num_classes),
        )

        self._initialize_weights()

    def _initialize_weights(self):
        for module in self.modules():
            if isinstance(module, (nn.Conv1d, nn.Linear)):
                nn.init.kaiming_normal_(
                    module.weight, mode="fan_out", nonlinearity="relu"
                )

                if module.bias is not None:
                    nn.init.zeros_(module.bias)

            elif isinstance(module, nn.BatchNorm1d):
                nn.init.ones_(module.weight)
                nn.init.zeros_(module.bias)

        # Final classifier has no ReLU after it
        nn.init.xavier_uniform_(self.head[-1].weight)
        nn.init.zeros_(self.head[-1].bias)

    def forward(self, x):
        mask = padding_mask(x)
        x = transform_inputs(x) / self.input_scale.view(1, -1, 1)

        x = self.stem(x) * mask

        for i, block in enumerate(self.blocks):
            x = block(x, mask)

            if i < len(self.blocks) - 1:
                x = self.pool(x)
                mask = self.pool(mask)

        # Masked global pooling over real positions only
        count = mask.sum(dim=-1).clamp(min=1)
        mean = (x * mask).sum(dim=-1) / count
        max_pool = (x * mask - (1 - mask) * 1e4).amax(dim=-1)
        variance = ((x - mean.unsqueeze(-1)) ** 2 * mask).sum(dim=-1) / count
        std = variance.clamp(min=1e-6).sqrt()

        x = torch.cat([mean, max_pool, std], dim=1)
        return self.head(x)
