import hashlib
import os
import re
import sqlite3
import zipfile
from pathlib import Path
from tqdm import tqdm


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ROOT_DIR = PROJECT_ROOT / "beatmap_recommender" / "data_audio" / "2026 (osu!)"
OUTPUT_DIR = PROJECT_ROOT / "beatmap_recommender" / "data_audio" / "2026_audio"
DB_PATH = PROJECT_ROOT / "beatmap_recommender" / "dummy.db"


def calculate_md5(data):
    return hashlib.md5(data).hexdigest()


def sanitize_filename(value):
    """
    Make a string safe to use as a filename.
    """
    value = value.strip()

    # Replace characters that are invalid on Windows and problematic elsewhere.
    value = re.sub(r'[<>:"/\\|?*]', "_", value)

    # Remove control characters.
    value = re.sub(r"[\x00-\x1f]", "", value)

    # Avoid trailing periods/spaces.
    value = value.rstrip(". ")

    return value or "Unknown"


def parse_osu_file(data):
    """
    Parse the small amount of .osu metadata we need,
    since we don't know the actual audio file's name
    """
    text = data.decode("utf-8-sig", errors="replace")
    audio_filename = None

    for line in text.splitlines():
        line = line.strip()
        if line.startswith("AudioFilename:"):
            audio_filename = line.split(":", 1)[1].strip()
            break

    return audio_filename


def build_output_filename(artist, title, creator, audio_filename):
    """
    Preserve the original audio extension.
    """
    extension = Path(audio_filename).suffix

    artist = sanitize_filename(artist)
    title = sanitize_filename(title)
    creator = sanitize_filename(creator)

    return f"{artist} - {title} - {creator}{extension}"


def load_beatmaps(db_path):
    """
    Load the MD5 -> beatmap metadata mapping into memory.
    """
    conn = sqlite3.connect(db_path)
    rows = conn.execute("""
        SELECT
            md5,
            beatmap_id,
            artist,
            title,
            creator
        FROM beatmaps
        WHERE md5 IS NOT NULL
    """).fetchall()

    conn.close()

    beatmaps = {}
    for row in rows:
        md5, beatmap_id, artist, title, creator = row
        beatmaps[md5.lower()] = {
            "beatmap_id": beatmap_id,
            "artist": artist,
            "title": title,
            "creator": creator,
        }

    return beatmaps


def extract_audio_files(root_dir, output_dir, db_path):

    os.makedirs(output_dir, exist_ok=True)
    beatmaps = load_beatmaps(db_path)
    print(f"Loaded {len(beatmaps):,} beatmap MD5 hashes from database.")

    osz_files = []

    for dirpath, _, filenames in os.walk(root_dir):
        for filename in filenames:
            if filename.lower().endswith(".osz"):
                osz_files.append(os.path.join(dirpath, filename))

    print(f"Found {len(osz_files):,} .osz archives.")

    extracted_count = 0
    skipped_count = 0
    unmatched_count = 0
    matched_osu_count = 0
    matched_osz_count = 0

    for osz_path in tqdm(osz_files, desc="Extracting audio"):
        try:
            with zipfile.ZipFile(osz_path, "r") as archive:

                # Track audio files already extracted from this beatmapset.
                extracted_audio = set()
                archive_had_match = False

                for member in archive.infolist():

                    if not member.filename.lower().endswith(".osu"):
                        continue

                    with archive.open(member) as source:
                        osu_data = source.read()

                    md5 = calculate_md5(osu_data)
                    beatmap = beatmaps.get(md5.lower())
                    if beatmap is None:
                        unmatched_count += 1
                        continue

                    matched_osu_count += 1
                    archive_had_match = True

                    # we need this to find the audio file itself
                    audio_filename = parse_osu_file(osu_data)
                    if not audio_filename:
                        skipped_count += 1
                        continue

                    audio_path = Path(audio_filename).name

                    # Multiple .osu files in a beatmapset may reference the same audio file.
                    audio_key = audio_path.lower()
                    if audio_key in extracted_audio:
                        continue

                    # Make sure the audio file actually exists in the archive.
                    try:
                        audio_member = archive.getinfo(audio_path)
                    except KeyError:
                        # Some archives may contain paths that differ from the exact AudioFilename value. Try matching by basename.
                        audio_member = None
                        for candidate in archive.infolist():
                            if Path(candidate.filename).name.lower() == audio_path.lower():
                                audio_member = candidate
                                break

                        if audio_member is None:
                            skipped_count += 1
                            continue

                    output_filename = build_output_filename(
                        beatmap["artist"],
                        beatmap["title"],
                        beatmap["creator"],
                        audio_path,
                    )

                    output_path = output_dir / output_filename

                    # Handle collisions between unrelated beatmapsets.
                    if output_path.exists():
                        base = output_path.stem
                        extension = output_path.suffix
                        counter = 1

                        while True:
                            candidate = output_dir / f"{base}_{counter}{extension}"
                            if not candidate.exists():
                                output_path = candidate
                                break

                            counter += 1

                    with archive.open(audio_member) as source, open(output_path, "wb") as target:
                        target.write(source.read())

                    extracted_audio.add(audio_key)
                    extracted_count += 1

                if archive_had_match:
                    matched_osz_count += 1

        except zipfile.BadZipFile:
            print(f"\nInvalid .osz archive: {osz_path}")

        except Exception as e:
            print(f"\nFailed to process {osz_path}: {e}")

    print("\nFinished.")
    print(f"Matched .osz archives:  {matched_osz_count:,}")
    print(f"Matched .osu files:     {matched_osu_count:,}")
    print(f"Extracted audio files:   {extracted_count:,}")
    print(f"Unmatched MD5 hashes:    {unmatched_count:,}")
    print(f"Skipped files:           {skipped_count:,}")


if __name__ == "__main__":
    extract_audio_files(
        ROOT_DIR,
        OUTPUT_DIR,
        DB_PATH,
    )