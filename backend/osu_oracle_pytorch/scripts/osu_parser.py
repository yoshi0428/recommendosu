import os
import sqlite3
from osu_tools import OsuCalculator
from tqdm import tqdm
import copy

# ============================================================
# Configuration
# ============================================================

DATABASE_PATH = "./beatmaps.db"
ROOT_DIR = "."

MAX_SEQUENCE_LENGTH = 3502
MAX_SLIDER_LENGTH = 500.0
MAX_TIME_DIFF = 1000.0

DEBUG = 0

# ============================================================
# Star Rating Calculator
# ============================================================

# Initialize the star-rating calculator once.
# This avoids repeatedly initializing the .NET runtime for every beatmap.
star_calculator = OsuCalculator()

def calculate_star_rating(file_path):
    """
    Calculate the osu! standard star rating for a beatmap.

    :param file_path: Path to the .osu file.
    :return: Star rating, or None if calculation fails.
    """

    result = star_calculator.calculate(
        file_path=file_path,
        mode=0,
        mods=[]
    )

    if not result.is_success:
        print(f"\nFAILED: {file_path}")
        print(f"Error: {result.error}")
        return None

    return result.stars

# ============================================================
# Beatmap Flipping
# ============================================================

def flip_beatmap(
    beatmap_data,
    horizontal=False,
    vertical=False,
    max_slider_length=MAX_SLIDER_LENGTH,
    max_time_diff=MAX_TIME_DIFF
):
    """
    Create a horizontally/vertically flipped copy of a beatmap.

    The original beatmap is not modified.

    :param beatmap_data: Parsed beatmap dictionary.
    :param horizontal: Flip across the horizontal axis.
    :param vertical: Flip across the vertical axis.
    :return: Flipped beatmap dictionary.
    """

    max_x = 512
    max_y = 384

    # Deep copy because hit_objects contains nested dictionaries.
    flipped_data = copy.deepcopy(beatmap_data)

    # --------------------------------------------------------
    # Flip coordinates
    # --------------------------------------------------------

    for obj in flipped_data["hit_objects"]:

        if horizontal:
            obj["x"] = max_x - obj["x"]

        if vertical:
            obj["y"] = max_y - obj["y"]

    # --------------------------------------------------------
    # Recalculate normalized coordinates
    # --------------------------------------------------------

    for obj in flipped_data["hit_objects"]:
        obj["x_norm"] = obj["x"] / max_x
        obj["y_norm"] = obj["y"] / max_y

    # --------------------------------------------------------
    # Recalculate vectors
    # --------------------------------------------------------

    vectors = []

    for i, obj in enumerate(
        flipped_data["hit_objects"][1:],
        start=1
    ):
        prev_obj = flipped_data["hit_objects"][i - 1]

        x_diff = obj["x_norm"] - prev_obj["x_norm"]
        y_diff = obj["y_norm"] - prev_obj["y_norm"]

        time_diff = obj["time_diff"]
        length = obj["length"]

        vectors.append((
            x_diff,
            y_diff,
            time_diff / max_time_diff,
            length / max_slider_length
        ))

    flipped_data["vectors"] = vectors

    return flipped_data

# ============================================================
# .osu Parser
# ============================================================

def parse_osu_file(
    file_path,
    max_slider_length=MAX_SLIDER_LENGTH,
    max_time_diff=MAX_TIME_DIFF,
    print_info=False
):
    """
    Parse an osu! .osu file.

    Extracts:
        - Beatmap ID
        - Metadata
        - Difficulty settings
        - BPM information
        - Hit objects
        - CNN input vectors

    :param file_path: Path to the .osu file.
    :param max_slider_length: Maximum slider length used for normalization.
    :param max_time_diff: Maximum time difference used for normalization.
    :param print_info: Whether to print basic beatmap information.
    :return: Parsed beatmap dictionary, or None.
    """

    data = {
        "beatmap_id": None,

        # Difficulty
        "hp_drain": None,
        "circle_size": None,
        "od": None,
        "ar": None,
        "slider_multiplier": None,
        "slider_tick": None,

        # Difficulty metadata
        "star_rating": None,

        # BPM
        "bpm": None,
        "min_bpm": None,
        "max_bpm": None,

        # Objects
        "hit_objects": [],

        # Label
        "label": None,
    }

    timing_points = []

    # The label is the parent directory name.
    parent_folder = os.path.dirname(file_path)
    data["label"] = os.path.basename(parent_folder)

    # ========================================================
    # Read file
    # ========================================================

    with open(file_path, "r", encoding="utf-8") as file:
        lines = file.readlines()

    section = None

    for line in lines:
        line = line.strip()

        if not line:
            continue

        # ----------------------------------------------------
        # Section header
        # ----------------------------------------------------

        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            continue

        # ====================================================
        # Metadata
        # ====================================================

        if section == "Metadata":

            if ":" not in line:
                continue

            key, value = line.split(":", maxsplit=1)
            value = value.strip()

            if key == "Title" and print_info:
                print("Title: " + value, end=" ")

            elif key == "Artist" and print_info:
                print("by " + value)

            elif key == "Creator" and print_info:
                print("Mapper: " + value)

            elif key == "Version" and print_info:
                print("Difficulty: " + value)

            elif key == "BeatmapID":
                try:
                    data["beatmap_id"] = int(value)
                except ValueError:
                    return None

        # ====================================================
        # Difficulty
        # ====================================================

        elif section == "Difficulty":

            if ":" not in line:
                continue

            key, value = line.split(":", maxsplit=1)

            try:
                value = float(value)
            except ValueError:
                continue

            if key == "HPDrainRate":
                data["hp_drain"] = value / 10

            elif key == "CircleSize":
                data["circle_size"] = value / 10

            elif key == "OverallDifficulty":
                data["od"] = value / 10

            elif key == "ApproachRate":
                data["ar"] = value / 10

            elif key == "SliderMultiplier":
                data["slider_multiplier"] = value

            elif key == "SliderTickRate":
                data["slider_tick"] = value

        # ====================================================
        # Timing Points
        # ====================================================

        elif section == "TimingPoints":

            obj_data = line.split(",")

            if len(obj_data) < 2:
                continue

            try:
                time = float(obj_data[0])
                beat_length = float(obj_data[1])
            except ValueError:
                continue

            # Positive beat length indicates an uninherited
            # timing point.
            if beat_length > 0:
                bpm = 60000.0 / beat_length
                timing_points.append((time, bpm))

        # ====================================================
        # Hit Objects
        # ====================================================

        elif section == "HitObjects":

            obj_data = line.split(",")

            if len(obj_data) < 4:
                continue

            try:
                x = int(obj_data[0])
                y = int(obj_data[1])
                time = int(obj_data[2])
                hit_object_type = int(obj_data[3])
            except ValueError:
                continue

            hit_circle_flag = 0b00000001
            slider_flag = 0b00000010

            # ------------------------------------------------
            # Circle
            # ------------------------------------------------

            if hit_object_type & hit_circle_flag:

                hit_object = {
                    "x": x,
                    "y": y,
                    "time": time,
                    "length": 0.0,
                }

                data["hit_objects"].append(hit_object)

            # ------------------------------------------------
            # Slider
            # ------------------------------------------------

            elif hit_object_type & slider_flag:

                if len(obj_data) <= 7:
                    continue

                try:
                    slider_length = float(obj_data[7])
                except ValueError:
                    slider_length = 0.0

                hit_object = {
                    "x": x,
                    "y": y,
                    "time": time,

                    # Keep your existing 500 maximum.
                    "length": min(
                        max_slider_length,
                        slider_length
                    ),
                }

                data["hit_objects"].append(hit_object)

    # ========================================================
    # BPM
    # ========================================================

    if timing_points:

        bpms = [
            bpm
            for _, bpm in timing_points
        ]

        data["bpm"] = bpms[0]
        data["min_bpm"] = min(bpms)
        data["max_bpm"] = max(bpms)

    # ========================================================
    # Normalize Coordinates
    # ========================================================

    max_x = 512
    max_y = 384

    for obj in data["hit_objects"]:

        obj["x_norm"] = obj["x"] / max_x
        obj["y_norm"] = obj["y"] / max_y

    # ========================================================
    # Compute Time Differences
    # ========================================================

    if data["hit_objects"]:

        data["hit_objects"][0]["time_diff"] = 0

        for i, obj in enumerate(
            data["hit_objects"][1:],
            start=1
        ):
            obj["time_diff"] = (
                obj["time"]
                - data["hit_objects"][i - 1]["time"]
            )

    # ========================================================
    # Create CNN Vectors
    # ========================================================

    vectors = []

    for i, obj in enumerate(
        data["hit_objects"][1:],
        start=1
    ):
        prev_obj = data["hit_objects"][i - 1]

        x_diff = (
            obj["x_norm"]
            - prev_obj["x_norm"]
        )

        y_diff = (
            obj["y_norm"]
            - prev_obj["y_norm"]
        )

        time_diff = obj["time_diff"]
        length = obj["length"]

        vectors.append((
            x_diff,
            y_diff,
            time_diff / max_time_diff,
            length / max_slider_length
        ))

    data["vectors"] = vectors

    return data

# ============================================================
# Database
# ============================================================

def create_tables(conn):
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS beatmaps (
            id INTEGER PRIMARY KEY,
            beatmap_id INTEGER,
            category TEXT,
            hp_drain REAL,
            circle_size REAL,
            od REAL,
            ar REAL,
            slider_multiplier REAL,
            slider_tick REAL,
            star_rating REAL,
            bpm REAL,
            min_bpm REAL,
            max_bpm REAL
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS beatmap_vectors (
            id INTEGER PRIMARY KEY,
            beatmap_id INTEGER,
            x_diff REAL,
            y_diff REAL,
            time_diff REAL,
            length REAL,
            FOREIGN KEY (beatmap_id) REFERENCES beatmaps (id)
        )
    ''')


    conn.commit()


def insert_beatmap_data(conn, beatmap_data):
    """
    Insert a parsed beatmap and its vectors into SQLite.
    """

    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO beatmaps (
            beatmap_id,
            category,
            hp_drain,
            circle_size,
            od,
            ar,
            slider_multiplier,
            slider_tick,
            star_rating,
            bpm,
            min_bpm,
            max_bpm
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        beatmap_data["beatmap_id"],
        beatmap_data["label"],
        beatmap_data["hp_drain"],
        beatmap_data["circle_size"],
        beatmap_data["od"],
        beatmap_data["ar"],
        beatmap_data["slider_multiplier"],
        beatmap_data["slider_tick"],
        beatmap_data["star_rating"],
        beatmap_data["bpm"],
        beatmap_data["min_bpm"],
        beatmap_data["max_bpm"],
    ))

    # SQLite row ID for this particular augmentation.
    beatmap_row_id = cursor.lastrowid

    cursor.executemany("""
        INSERT INTO beatmap_vectors (
            beatmap_id,
            x_diff,
            y_diff,
            time_diff,
            length
        )
        VALUES (?, ?, ?, ?, ?)
    """, [
        (
            beatmap_row_id,
            vector[0],
            vector[1],
            vector[2],
            vector[3],
        )
        for vector in beatmap_data["vectors"]
    ])

    conn.commit()

# ============================================================
# Main
# ============================================================

def main():
    root_dir = '.'  # Current directory
    beatmaps_data = []

    # Connect to the SQLite database
    conn = sqlite3.connect('./beatmaps.db')

    # Create the necessary tables
    create_tables(conn)

    # Collect all .osu files first
    osu_files = []

    for dirpath, _, filenames in os.walk(ROOT_DIR):
        for filename in filenames:
            if filename.endswith(".osu"):
                osu_files.append(os.path.join(dirpath, filename))

    print(f"Found {len(osu_files)} .osu files.")

    # Now tqdm can show total progress
    for file_path in tqdm(osu_files, desc="Processing beatmaps"):

        beatmap_data = parse_osu_file(file_path)

        if beatmap_data is not None and (len(beatmap_data['vectors']) <= 3502):

            # Calculate the star rating from the original .osu file.
            beatmap_data['star_rating'] = calculate_star_rating(file_path)

            if DEBUG == 1:
                print(
                    f"\n{os.path.basename(file_path)} | "
                    f"Vectors: {beatmap_data['vectors']} | "
                    f"BPM: {beatmap_data['bpm']:.2f} | "
                    f"BPM range: "
                    f"{beatmap_data['min_bpm']:.2f}-"
                    f"{beatmap_data['max_bpm']:.2f} | "
                    f"Stars: {beatmap_data['star_rating']}"
                )

            # Process the data (e.g., insert into the database)
            beatmaps_data.append(beatmap_data)                # Insert the parsed beatmap data into the SQLite database
            insert_beatmap_data(conn, beatmap_data)

            # Horizontal flip
            flipped_horizontal = flip_beatmap(beatmap_data, horizontal=True, vertical=False,
                                              max_slider_length=MAX_SLIDER_LENGTH, max_time_diff=MAX_TIME_DIFF)

            beatmaps_data.append(flipped_horizontal)
            insert_beatmap_data(conn, flipped_horizontal)

            # Vertical flip
            flipped_vertical = flip_beatmap(beatmap_data, horizontal=False, vertical=True,
                                            max_slider_length=MAX_SLIDER_LENGTH, max_time_diff=MAX_TIME_DIFF)
            beatmaps_data.append(flipped_vertical)
            insert_beatmap_data(conn, flipped_vertical)

            # Horizontal + vertical flip
            flipped_both = flip_beatmap(beatmap_data, horizontal=True, vertical=True,
                                        max_slider_length=MAX_SLIDER_LENGTH, max_time_diff=MAX_TIME_DIFF)
            beatmaps_data.append(flipped_both)
            insert_beatmap_data(conn,flipped_both)

            pass

    # Close the SQLite database connection
    conn.close()

if __name__ == '__main__':
    main()