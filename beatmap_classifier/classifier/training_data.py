"""
Loading a classifier database (classifier_db_setup/populate.py) for training:
each map's parser vectors, scaled, and its tournament slots.
"""

import sqlite3
from collections import defaultdict

import numpy as np

# Tournament label (a tournament_predictions column, named after a data/<SLOT>/
# folder) -> the variant it's played with, in the order label sets list them.
# Freemod and tiebreaker slots are labelled on the NM variant.
TOURNAMENT_MODS = {
    **{f"nm{i}": "NM" for i in range(1, 9)},
    **{f"dt{i}": "DT" for i in range(1, 6)},
    **{f"hr{i}": "HR" for i in range(1, 5)},
    **{f"hd{i}": "HD" for i in range(1, 5)},
    **{f"fm{i}": "NM" for i in range(1, 5)},
    "tb": "NM",
    # Columns of databases built before the osu!collector slots (curated_collection.db).
    "dt2_and_dt3": "DT",
    "tiebreaker": "NM",
}

# DT plays 1.5x faster: time_diff shrinks, speed grows.
DT_RATE = 1.5


def get_tournament_label_sets(cursor):
    """
    beatmap_id -> every tournament label the map has, over all its variants,
    in TOURNAMENT_MODS order. A map has several only in a database built
    with populate.py --keep-multicategory.

        {123: ("nm1",), 456: ("nm3", "nm4"), 789: ("nm1", "hd2")}
    """
    # Only the label columns this database has: older ones use other slot names.
    existing = {row[1] for row in cursor.execute("PRAGMA table_info(tournament_predictions)")}
    columns = [column for column in TOURNAMENT_MODS if column in existing]
    cursor.execute(f"""
        SELECT
            bv.beatmap_id,
            {", ".join(f"tp.{column}" for column in columns)}
        FROM beatmap_variants bv
        JOIN tournament_predictions tp
            ON tp.variant_id = bv.variant_id
    """)

    found = defaultdict(set)
    for beatmap_id, *predictions in cursor.fetchall():
        for column, prediction in zip(columns, predictions):
            if prediction == 1:
                found[beatmap_id].add(column)

    return {beatmap_id: tuple(c for c in columns if c in labels) for beatmap_id, labels in found.items()}


def get_vector_normalization(cursor):
    """
    The scales get_data() divides the time_diff and length vector channels by.

    The model learns on these scaled values, so anything that feeds it later
    (precompute_nm1-5.py, test_model.py) must apply the same scaling;
    train_fusion.py saves them with the model.
    """
    cursor.execute("SELECT MAX(v.time_diff), MAX(v.length) FROM beatmap_vectors v")
    max_time_diff, max_vector_length = cursor.fetchone()

    return {
        "max_time_diff": float(max_time_diff),
        "max_vector_length": float(max_vector_length),
    }


def normalize_beatmap_vectors(vectors, normalization):
    """
    Scale parsed NM vectors (parse_osu_file()["vectors"]) the same way
    get_data() scales training vectors. Returns a new float32 array.
    """
    vectors = np.array(vectors, dtype=np.float32)
    vectors[:, 2] /= normalization["max_time_diff"]
    vectors[:, 3] /= normalization["max_vector_length"]
    vectors[:, 7] /= normalization["max_time_diff"]
    return vectors


def get_data(db_path, chunk_size=50000):
    """
    Load beatmaps: (vectors per map, label set per map, beatmap ids).

    Each label set is a tuple of every slot the map has
    (get_tournament_label_sets()).
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    normalization = get_vector_normalization(cursor)
    max_vector_length = normalization["max_vector_length"]
    max_time_diff = normalization["max_time_diff"]
    print(f"Max Vector Length: {max_vector_length}")
    print(f"Max Time Diff: {max_time_diff}")

    # ========================================================
    # Tournament labels
    # ========================================================
    labels = get_tournament_label_sets(cursor)
    print(f"Tournament-labeled beatmaps: {len(labels)}")

    # DT maps play 1.5x faster. A map in several slots is sped up only if all its slots are DT.
    rates = {
        beatmap_id: DT_RATE if {TOURNAMENT_MODS[label] for label in label_set} == {"DT"} else 1.0
        for beatmap_id, label_set in labels.items()
    }

    # Fetch vectors
    cursor.execute("""
        SELECT
            beatmap_id,
            x_diff,
            y_diff,
            time_diff,
            length,
            distance,
            speed,
            speed_change,
            time_diff_change
        FROM beatmap_vectors
    """)

    X = defaultdict(list)

    # Load database rows
    while True:
        rows = cursor.fetchmany(chunk_size)

        if not rows:
            break

        for (
            beatmap_id,
            x_diff,
            y_diff,
            time_diff,
            length,
            distance,
            speed,
            speed_change,
            time_diff_change,
        ) in rows:
            if beatmap_id not in labels:
                continue

            # Apply mod timing transformation
            rate = rates[beatmap_id]

            # time_diff_change is scaled like time_diff, so the model sees
            # both in the same units.
            X[beatmap_id].append(
                (
                    x_diff,
                    y_diff,
                    time_diff / rate / max_time_diff,
                    length / max_vector_length,
                    distance,
                    speed * rate,
                    speed_change * rate,
                    time_diff_change / rate / max_time_diff,
                )
            )

    conn.close()

    # Convert to aligned lists. Sorted so the order (and so the folds)
    # doesn't depend on SQLite's row scan order, which changes when
    # the DB is rebuilt.
    beatmap_ids = sorted(X)
    original_X = [
        np.array(X[beatmap_id], dtype=np.float32) for beatmap_id in beatmap_ids
    ]
    original_y = [labels[beatmap_id] for beatmap_id in beatmap_ids]

    print(f"Original beatmaps: {len(original_X)}")

    return original_X, original_y, beatmap_ids
