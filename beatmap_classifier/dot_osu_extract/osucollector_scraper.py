"""
Scrape an osu!collector user's uploaded tournament-slot collections and sort their beatmap IDs
into one .txt file per slot. downloader_backoff.py then downloads the .osu files from these lists.

    python -m beatmap_classifier.dot_osu_extract.osucollector_scraper
    python -m beatmap_classifier.dot_osu_extract.osucollector_scraper --user 18473778
    python -m beatmap_classifier.dot_osu_extract.osucollector_scraper --collections 18935 18936

Output:

    dot_osu_extract/expanded_collection/{SLOT}.txt     the beatmap IDs in each slot (--ids-dir)
    dot_osu_extract/outputs/expanded_collection_cache/ (--work-dir, gitignored)
        json/{collection_id}.json  raw /api/collections/{id} response, reused unless --refresh
        manifest.csv               one row per (collection, beatmap): slot, skill, ids, checksum

Collection names like "HR2 · Precision" are split into slot "HR2" and skill "Precision".
A beatmap in several collections is listed under each slot.
"""

import argparse
import csv
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

COLLECTOR = "https://osucollector.com"
USER_AGENT = "recommendosu-collection-scraper/1.0"
HERE = Path(__file__).resolve().parent
DEFAULT_IDS_DIR = HERE / "expanded_collection"
DEFAULT_WORK_DIR = HERE / "outputs" / "expanded_collection_cache"
FIELDS = ["slot", "skill", "collection_id", "collection_name", "beatmap_id", "beatmapset_id", "checksum"]


def http_get(url, retries=5):
    """GET with backoff on 429/5xx/network errors. Returns bytes, or None on 404."""
    delay = 2.0
    for attempt in range(retries):
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code != 429 and e.code < 500:
                raise
            retry_after = e.headers.get("Retry-After")
            wait = float(retry_after) if retry_after and retry_after.isdigit() else delay
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            wait = delay
        if attempt == retries - 1:
            raise RuntimeError(f"giving up on {url}")
        time.sleep(wait)
        delay *= 2


def get_json(url, tries=8):
    """osu!collector sometimes answers 200 with an HTML error page when hit quickly; retry those."""
    delay = 3.0
    for _ in range(tries):
        body = http_get(url)
        if body is not None:
            try:
                return json.loads(body)
            except ValueError:
                pass
        time.sleep(delay)
        delay = min(delay * 2, 120)
    raise RuntimeError(f"no JSON from {url}")


def user_collection_ids(user):
    """The collection IDs linked from the user's uploads page (it has no JSON endpoint)."""
    html = http_get(f"{COLLECTOR}/users/{user}/uploads/collections").decode("utf-8", "replace")
    return sorted({int(m) for m in re.findall(r"/collections/(\d+)", html)})


def split_name(name):
    """'HR2 · Precision' -> ('HR2', 'Precision'); a name without '·' is all slot."""
    slot, _, skill = name.partition("·")
    return slot.strip().replace(" ", ""), skill.strip()


def scrape(collection_ids, work_dir, refresh=False):
    """Manifest rows of every beatmap in the collections (JSON cached in work_dir/json)."""
    json_dir = work_dir / "json"
    json_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for cid in collection_ids:
        path = json_dir / f"{cid}.json"
        if path.exists() and not refresh:
            collection = json.loads(path.read_text())
        else:
            collection = get_json(f"{COLLECTOR}/api/collections/{cid}")
            path.write_text(json.dumps(collection))
            time.sleep(1.0)
        slot, skill = split_name(collection["name"])
        before = len(rows)
        for beatmapset in collection["beatmapsets"]:
            for beatmap in beatmapset["beatmaps"]:
                rows.append({
                    "slot": slot,
                    "skill": skill,
                    "collection_id": cid,
                    "collection_name": collection["name"],
                    "beatmap_id": beatmap["id"],
                    "beatmapset_id": beatmapset["id"],
                    "checksum": beatmap.get("checksum") or "",
                })
        found = len(rows) - before
        note = "" if found == collection["beatmapCount"] else f" (site says {collection['beatmapCount']})"
        print(f"  {cid} {collection['name']}: {found} beatmaps{note}")
    return rows


def write_outputs(rows, ids_dir, work_dir):
    """manifest.csv, and one {SLOT}.txt of sorted beatmap IDs per slot (replacing the old lists)."""
    with open(work_dir / "manifest.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    by_slot = {}
    for row in rows:
        by_slot.setdefault(row["slot"], set()).add(int(row["beatmap_id"]))
    ids_dir.mkdir(parents=True, exist_ok=True)
    for old in ids_dir.glob("*.txt"):
        old.unlink()
    for slot, beatmap_ids in sorted(by_slot.items()):
        (ids_dir / f"{slot}.txt").write_text("".join(f"{b}\n" for b in sorted(beatmap_ids)))
    print(f"{len(rows)} rows, {len({r['beatmap_id'] for r in rows})} unique beatmaps in {len(by_slot)} slots; "
          f"ID lists -> {ids_dir}, manifest -> {work_dir}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--user", default="18473778", help="osu!collector user ID whose uploads to scrape")
    parser.add_argument("--collections", type=int, nargs="*", help="collection IDs instead of a user's uploads")
    parser.add_argument("--ids-dir", type=Path, default=DEFAULT_IDS_DIR, help="where the {SLOT}.txt lists go")
    parser.add_argument("--work-dir", type=Path, default=DEFAULT_WORK_DIR, help="collection JSON and manifest.csv")
    parser.add_argument("--refresh", action="store_true", help="re-fetch collection JSON already saved")
    args = parser.parse_args()
    ids_dir, work_dir = args.ids_dir.expanduser(), args.work_dir.expanduser()
    work_dir.mkdir(parents=True, exist_ok=True)

    collection_ids = args.collections or user_collection_ids(args.user)
    print(f"{len(collection_ids)} collections")
    write_outputs(scrape(collection_ids, work_dir, args.refresh), ids_dir, work_dir)


if __name__ == "__main__":
    main()
