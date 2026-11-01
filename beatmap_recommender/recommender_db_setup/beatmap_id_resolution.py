"""
Resolve the real beatmap ID of every osu!standard .osu file before populating.

A file's own BeatmapID can't always be trusted:

    - missing entirely (old file formats)
    - BeatmapID:0 / -1 (e.g. guest diffs)
    - a real ID shared by several *different* files (every diff of a set
      copying the Normal's ID)

Because beatmap_id is the PRIMARY KEY, inserting under such an ID makes the
files overwrite each other. Resolution order for a problem file:

    1. manual overrides  (fixed_beatmap_rows.csv, keyed by md5)
    2. seed database     (an existing DB's md5 -> beatmap_id, read-only), only
                         when the seed's ID isn't the same bad/shared ID
    3. osu! API          /beatmaps/lookup?checksum=<md5>, cached in a JSON file

Files whose AR line is missing (pre-AR formats) also take AR from those
sources; if none has it, AR falls back to OD, which is what osu! does.

Files that can't be resolved are not inserted; they are logged instead.
"""

import csv
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

from tqdm import tqdm

from beatmap_recommender.recommender_db_setup.parser import decode_osu_bytes

BAD_IDS = {"0", "-1"}
MD5_PATTERN = re.compile(r"^[0-9a-f]{32}$")

MODE_PATTERN = re.compile(r"^\s*Mode\s*:\s*(\d+)", re.M)
BEATMAP_ID_PATTERN = re.compile(r"^\s*BeatmapID\s*:\s*(-?\d+)", re.M)
BEATMAPSET_ID_PATTERN = re.compile(r"^\s*BeatmapSetID\s*:\s*(-?\d+)", re.M)
AR_PATTERN = re.compile(r"^\s*ApproachRate\s*:", re.M)

DEFAULT_OVERRIDES_PATH = Path(__file__).resolve().parent / "fixed_beatmap_rows.csv"

LOG_FIELDS = [
    "file",
    "md5",
    "file_beatmap_id",
    "problem",
    "source",
    "beatmap_id",
    "beatmapset_id",
    "outcome",
    "note",
]


# ============================================================
# Scanning
# ============================================================
def read_osu_header(path):
    raw = Path(path).read_bytes()
    text = decode_osu_bytes(raw)

    def first(pattern):
        match = pattern.search(text)
        return match.group(1) if match else None

    return {
        "path": str(path),
        "md5": hashlib.md5(raw).hexdigest(),
        "mode": int(first(MODE_PATTERN) or 0),
        "file_beatmap_id": first(BEATMAP_ID_PATTERN),
        "file_beatmapset_id": first(BEATMAPSET_ID_PATTERN),
        "has_ar": AR_PATTERN.search(text) is not None,
    }


def scan_osu_files(root_dir):
    paths = sorted(p for p in Path(root_dir).rglob("*") if p.suffix.lower() == ".osu")
    return [read_osu_header(p) for p in tqdm(paths, desc="Scanning .osu files")]


# ============================================================
# Sources
# ============================================================
def load_overrides(path):
    """
    fixed_beatmap_rows.csv -> {key: resolution}.

    Rows whose old_beatmap_id is an md5 are keyed by that md5 (the file's ID is
    wrong or missing). Rows whose old_beatmap_id is already the right ID only
    correct the set ID / AR; they are keyed as "id:<beatmap_id>".
    """
    overrides = {}
    if path is None:
        return overrides
    if not Path(path).exists():
        raise FileNotFoundError(f"Overrides CSV not found: {path} (pass --overrides to point at it)")

    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        reader.fieldnames = [field.strip() for field in reader.fieldnames]
        for row in reader:
            old_id = row["old_beatmap_id"].strip()
            key = old_id if MD5_PATTERN.match(old_id) else f"id:{old_id}"
            overrides[key] = {
                "beatmap_id": row["beatmap_id"].strip(),
                "beatmapset_id": row["beatmapset_id"].strip() or None,
                "ar": float(row["ar"]) if row["ar"].strip() else None,
            }

    return overrides


def load_seed(conn):
    """md5 -> (beatmap_id, beatmapset_id, ar) from an existing database."""
    if conn is None:
        return {}
    return {
        md5: {"beatmap_id": beatmap_id, "beatmapset_id": beatmapset_id, "ar": ar}
        for md5, beatmap_id, beatmapset_id, ar in conn.execute(
            "SELECT md5, beatmap_id, beatmapset_id, ar FROM beatmaps WHERE md5 IS NOT NULL"
        )
    }


class ChecksumLookup:
    """/beatmaps/lookup?checksum= with a persistent JSON cache. Errors are retried on the next run."""

    def __init__(self, cache_path, client_factory):
        self.cache_path = Path(cache_path)
        self.cache = json.loads(self.cache_path.read_text()) if self.cache_path.exists() else {}
        self.client_factory = client_factory
        self.client = None

    def __call__(self, md5):
        cached = self.cache.get(md5)
        if cached is not None and cached["result"] != "error":
            return cached

        from beatmap_recommender.api.osu_api_client import OsuAPINotFoundError

        if self.client is None:
            self.client = self.client_factory()

        try:
            data = self.client.get("/beatmaps/lookup", params={"checksum": md5})
            result = {
                "result": "found",
                "beatmap_id": str(data["id"]),
                "beatmapset_id": str(data["beatmapset_id"]),
                "mode": data.get("mode"),
                "ar": data.get("ar"),
            }
        except OsuAPINotFoundError:
            result = {"result": "not_found"}
        except Exception as exc:
            result = {"result": "error", "error": f"{type(exc).__name__}: {exc}"}

        self.cache[md5] = result
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps(self.cache, indent=2, sort_keys=True))
        return result


# ============================================================
# Resolution
# ============================================================
def resolve_beatmap_ids(headers, lookup, overrides=None, seed=None):
    """
    headers: read_osu_header() dicts for osu!standard files.

    Returns (resolutions, log_rows):
        resolutions: md5 -> {"beatmap_id", "beatmapset_id", "ar"} for every file
                     that may be inserted. "ar" is None unless the file lacks it.
        log_rows:    md5 -> log dict for every file that needed resolution or
                     was rejected. populate.py fills in the final outcome.
    """
    overrides = overrides or {}
    seed = seed or {}

    first_by_md5 = {}
    for header in headers:
        first_by_md5.setdefault(header["md5"], header)

    md5s_by_file_id = defaultdict(set)
    for header in first_by_md5.values():
        if header["file_beatmap_id"] is not None:
            md5s_by_file_id[header["file_beatmap_id"]].add(header["md5"])

    resolutions = {}
    log_rows = {}
    api_confirmed = set()

    for md5, header in tqdm(first_by_md5.items(), desc="Resolving beatmap IDs"):
        file_id = header["file_beatmap_id"]

        if file_id is None:
            problem = "no BeatmapID"
        elif file_id in BAD_IDS:
            problem = f"BeatmapID:{file_id}"
        elif len(md5s_by_file_id[file_id]) > 1:
            problem = f"BeatmapID shared by {len(md5s_by_file_id[file_id])} different files"
        else:
            problem = None

        # Manual overrides win over everything, including a valid-looking file ID
        # (e.g. an old file version whose BeatmapID points at a different map).
        if problem is None and md5 in overrides and overrides[md5]["beatmap_id"] != file_id:
            problem = "file BeatmapID contradicted by override"

        if problem is None and header["has_ar"]:
            resolutions[md5] = {
                "beatmap_id": file_id,
                "beatmapset_id": header["file_beatmapset_id"],
                "ar": None,
            }
            continue

        row = {
            "file": header["path"],
            "md5": md5,
            "file_beatmap_id": file_id or "",
            "problem": problem or "no ApproachRate",
            "source": "",
            "beatmap_id": "",
            "beatmapset_id": "",
            "outcome": "",
            "note": "",
        }
        log_rows[md5] = row

        # Only the AR is missing: keep the file's ID, find the AR wherever it is cheapest.
        if problem is None:
            ar = (overrides.get(md5) or {}).get("ar")
            source = "override"
            if ar is None:
                ar, source = (seed.get(md5) or {}).get("ar"), "seed"
            if ar is None:
                api = lookup(md5)
                ar, source = (api.get("ar"), "api") if api["result"] == "found" else (None, "")
            resolutions[md5] = {
                "beatmap_id": file_id,
                "beatmapset_id": header["file_beatmapset_id"],
                "ar": ar,
            }
            row.update(source=source or "OD fallback", beatmap_id=file_id, beatmapset_id=header["file_beatmapset_id"] or "")
            continue

        resolved = None
        seed_row = seed.get(md5)

        if md5 in overrides:
            resolved, row["source"] = overrides[md5], "override"
        elif (
            seed_row is not None
            and seed_row["beatmap_id"] != file_id
            and seed_row["beatmap_id"] not in BAD_IDS
            and not MD5_PATTERN.match(seed_row["beatmap_id"])
        ):
            resolved, row["source"] = seed_row, "seed"
        else:
            api = lookup(md5)
            row["source"] = "api"
            if api["result"] == "found" and api["mode"] != "osu":
                row.update(outcome="skipped", note=f"API says mode={api['mode']}")
                continue
            if api["result"] != "found":
                row.update(
                    outcome="skipped",
                    note=api.get("error") or "checksum unknown to osu! (outdated or unsubmitted file)",
                )
                continue
            resolved = api
            api_confirmed.add(md5)

        resolutions[md5] = {
            "beatmap_id": resolved["beatmap_id"],
            "beatmapset_id": resolved["beatmapset_id"],
            "ar": None if header["has_ar"] else resolved.get("ar"),
        }
        row.update(beatmap_id=resolved["beatmap_id"], beatmapset_id=resolved["beatmapset_id"] or "")

    # Fill in set IDs (and AR) that the file left as -1 / missing. Old files and
    # some unsubmitted-at-export diffs carry BeatmapSetID:-1 with a valid BeatmapID.
    for md5, resolution in resolutions.items():
        id_override = overrides.get(f"id:{resolution['beatmap_id']}") or {}
        if resolution["ar"] is None and not first_by_md5[md5]["has_ar"]:
            resolution["ar"] = id_override.get("ar")

        if resolution["beatmapset_id"] not in (None, "", *BAD_IDS):
            continue

        seed_row = seed.get(md5) or {}
        if id_override.get("beatmapset_id"):
            set_id, source = id_override["beatmapset_id"], "override"
        elif seed_row.get("beatmap_id") == resolution["beatmap_id"] and seed_row.get("beatmapset_id") not in (
            None,
            "",
            *BAD_IDS,
        ):
            set_id, source = seed_row["beatmapset_id"], "seed"
        else:
            api = lookup(md5)
            if api["result"] == "found" and api["beatmap_id"] == resolution["beatmap_id"]:
                set_id, source = api["beatmapset_id"], "api"
            else:
                set_id, source = None, "unresolved"

        resolution["beatmapset_id"] = set_id
        header = first_by_md5[md5]
        row = log_rows.setdefault(
            md5,
            {
                "file": header["path"],
                "md5": md5,
                "file_beatmap_id": header["file_beatmap_id"] or "",
                "problem": "",
                "source": "file",
                "beatmap_id": resolution["beatmap_id"],
                "beatmapset_id": "",
                "outcome": "",
                "note": "",
            },
        )
        row["problem"] = "; ".join(p for p in (row["problem"], "BeatmapSetID missing") if p)
        row["beatmapset_id"] = set_id or ""
        row["note"] = "; ".join(n for n in (row["note"], f"set ID from {source}") if n)

    # Two different files must never end up under one ID. Prefer the file the API
    # confirmed, then a file that already owned the ID itself, then path order.
    md5s_by_resolved_id = defaultdict(list)
    for md5, resolution in resolutions.items():
        md5s_by_resolved_id[resolution["beatmap_id"]].append(md5)

    for beatmap_id, md5s in md5s_by_resolved_id.items():
        if len(md5s) == 1:
            continue

        def rank(md5):
            return (
                md5 not in api_confirmed,
                first_by_md5[md5]["file_beatmap_id"] != beatmap_id,
                first_by_md5[md5]["path"],
            )

        keep, *drop = sorted(md5s, key=rank)
        for md5 in drop:
            del resolutions[md5]
            header = first_by_md5[md5]
            row = log_rows.setdefault(
                md5,
                {
                    "file": header["path"],
                    "md5": md5,
                    "file_beatmap_id": header["file_beatmap_id"] or "",
                    "problem": "",
                    "source": "file",
                    "beatmap_id": beatmap_id,
                    "beatmapset_id": "",
                    "outcome": "",
                    "note": "",
                },
            )
            row.update(
                outcome="skipped",
                note=f"resolves to {beatmap_id}, already taken by {first_by_md5[keep]['path']}",
            )

    return resolutions, log_rows


def write_log(log_rows, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=LOG_FIELDS)
        writer.writeheader()
        writer.writerows(sorted(log_rows, key=lambda r: r["file"]))
