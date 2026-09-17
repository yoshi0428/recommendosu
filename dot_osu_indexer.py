import hashlib
import os
from beatmap_classifier.dot_osu_db_setup.parser import parse_osu_file

MAX_SLIDER_LENGTH = 500.0

def get_file_content_md5(file_path):
    """
    Calculate the MD5 checksum of the actual file contents.
    The filepath itself has NO effect on the checksum.
    Therefore:

        ./data/2012/map.osu

    and:

        ./beatmap_recommender/data/2012/map.osu

    produce the same MD5 if their contents are identical.
    """

    md5 = hashlib.md5()

    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            md5.update(chunk)

    return md5.hexdigest()


def build_osu_file_index(root_dir):
    """
    Build two local lookup tables:
        by_beatmap_id:
            numeric osu! BeatmapID -> .osu filepath
        by_md5:
            .osu file-content MD5 -> .osu filepath

    This supports both:

        1234567
        abcdef1234567890...

    as beatmap identifiers in the database.
    """

    by_beatmap_id = {}
    by_md5 = {}

    osu_files = []

    for dirpath, _, filenames in os.walk(root_dir):
        for filename in filenames:
            if not filename.lower().endswith(".osu"):
                continue

            file_path = os.path.join(dirpath,filename,)
            osu_files.append(file_path)

    print(f"Found {len(osu_files):,} local .osu files.")

    for i, file_path in enumerate(osu_files, start=1):
        try:
            # Always index by file-content MD5.
            checksum = get_file_content_md5(file_path)
            by_md5[checksum] = file_path

            # Try to extract the numeric BeatmapID as an additional lookup key. This is optional.
            try:
                beatmap_data = parse_osu_file(file_path, max_slider_length=MAX_SLIDER_LENGTH, print_info=False,)
                if beatmap_data is not None:
                    beatmap_id = (beatmap_data.get("beatmap_id"))
                    if beatmap_id is not None:
                        by_beatmap_id[str(beatmap_id)] = file_path
            except Exception as e:
                # The MD5 index is still valid even if parsing fails.
                print(f"Warning: could not parse metadata from {file_path}: {type(e).__name__}: {e}")

        except Exception as e:
            print(f"Warning: failed to index {file_path}: {type(e).__name__}: {e}")

        if i % 5000 == 0:
            print(f"Indexed {i:,}/{len(osu_files):,} files")

    print()
    print("Local file index complete.")
    print(f"  Files scanned:       {len(osu_files):,}")
    print(f"  Numeric Beatmap IDs: {len(by_beatmap_id):,}")
    print(f"  MD5 identifiers:     {len(by_md5):,}")
    print()

    return by_beatmap_id, by_md5