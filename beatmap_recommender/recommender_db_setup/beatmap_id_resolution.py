"""
Find the real beatmap ID of each osu!standard .osu file before the database is filled.

The BeatmapID in a file is not always correct:

    - it is missing (old file formats)
    - BeatmapID:0 / -1 (for example, guest difficulties)
    - a real ID that several *different* files share (each difficulty of a
      set copies the ID of the Normal)

beatmap_id is the PRIMARY KEY, so an insert with such an ID makes the files
overwrite each other. For a problem file, the search uses this order:

    1. manual overrides  (fixed_beatmap_rows.csv, keyed by md5)
    2. seed database     (md5 -> beatmap_id of an existing database, read-only),
                         only if the seed ID is not the same bad or shared ID
    3. osu! API          /beatmaps/lookup?checksum=<md5>, cached in a JSON file

A file without an AR line (formats from before AR) also gets its AR from
these sources. If none has it, AR is the same as OD, as in osu!.

A file without a result is not inserted. It is logged.
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


def new_log_row(header, **fields):
    """Return a log row for one scanned file: its path, md5 and BeatmapID, plus fields, and "" for the rest."""
    row = dict.fromkeys(LOG_FIELDS, "")
    row.update(file=header["path"], md5=header["md5"], file_beatmap_id=header["file_beatmap_id"] or "")
    row.update(fields)
    return row


# ============================================================
# Scan
# ============================================================
def read_osu_header(path):
    """Return the md5, game mode, IDs and AR presence of a .osu file, without a full parse."""
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
    """Return read_osu_header() of each .osu file under root_dir, in path order."""
    paths = sorted(p for p in Path(root_dir).rglob("*") if p.suffix.lower() == ".osu")
    return [read_osu_header(p) for p in tqdm(paths, desc="Scanning .osu files")]


# ============================================================
# Sources
# ============================================================
def load_overrides(path):
    """
    Read fixed_beatmap_rows.csv into {key: resolution}.

    A row with an md5 as old_beatmap_id has that md5 as key (the ID of the
    file is wrong or missing). A row with the right ID as old_beatmap_id only
    corrects the set ID or the AR. Its key is "id:<beatmap_id>".
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
    """Return md5 -> (beatmap_id, beatmapset_id, ar) from an existing database."""
    if conn is None:
        return {}
    return {
        md5: {"beatmap_id": beatmap_id, "beatmapset_id": beatmapset_id, "ar": ar}
        for md5, beatmap_id, beatmapset_id, ar in conn.execute(
            "SELECT md5, beatmap_id, beatmapset_id, ar FROM beatmaps WHERE md5 IS NOT NULL"
        )
    }


class ChecksumLookup:
    """/beatmaps/lookup?checksum= with a JSON cache on disk. The next run tries the errors again."""

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
# ID search
# ============================================================
def resolve_beatmap_ids(headers, lookup, overrides=None, seed=None):
    """
    headers: read_osu_header() dicts for osu!standard files.

    Return (resolutions, log_rows):
        resolutions: md5 -> {"beatmap_id", "beatmapset_id", "ar"} for each file
                     that can be inserted. "ar" is None, unless the file has no AR.
        log_rows:    md5 -> log dict for each file that needed an ID search or
                     was rejected. populate.py adds the final outcome.
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

        # The manual overrides have priority over everything, also over a file ID
        # that looks valid (for example, an old file version with a BeatmapID
        # of a different map).
        if problem is None and md5 in overrides and overrides[md5]["beatmap_id"] != file_id:
            problem = "file BeatmapID contradicted by override"

        if problem is None and header["has_ar"]:
            resolutions[md5] = {
                "beatmap_id": file_id,
                "beatmapset_id": header["file_beatmapset_id"],
                "ar": None,
            }
            continue

        row = new_log_row(header, problem=problem or "no ApproachRate")
        log_rows[md5] = row

        # Only the AR is missing. Keep the ID of the file, and find the AR in the cheapest source.
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

    # Add the set IDs (and AR) that the file has as -1 or missing. Old files, and
    # some difficulties that were not submitted at export, have BeatmapSetID:-1
    # with a valid BeatmapID.
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
        row = log_rows.setdefault(md5, new_log_row(header, source="file", beatmap_id=resolution["beatmap_id"]))
        row["problem"] = "; ".join(p for p in (row["problem"], "BeatmapSetID missing") if p)
        row["beatmapset_id"] = set_id or ""
        row["note"] = "; ".join(n for n in (row["note"], f"set ID from {source}") if n)

    # Two different files must never get the same ID. Prefer the file that the
    # API confirmed, then a file that had the ID itself, then the path order.
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
            row = log_rows.setdefault(md5, new_log_row(header, source="file", beatmap_id=beatmap_id))
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
