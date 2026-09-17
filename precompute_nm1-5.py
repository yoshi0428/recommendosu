import pickle
import sqlite3
import numpy as np
import torch
import osu_tools

from beatmap_classifier.classifier.augment_faster import extract_movement_features_from_X
from beatmap_classifier.classifier_db_setup.parser import parse_osu_file
from beatmap_classifier.classifier.utils_training import pad_sequences_pt, load_pytorch_models
from beatmap_classifier.classifier.cnn_model import CNNModel
from dot_osu_indexer import build_osu_file_index

# ============================================================
# Configuration
# ============================================================

DB_PATH = "./beatmap_recommender/recommender.db"
DATA_ROOT = "./beatmap_recommender/data"

MODEL_FOLDER = "./beatmap_classifier/models/bagged_models"
LABEL_ENCODER_PATH = "./beatmap_classifier/models/label_encoder.pkl"
META_MODEL_PATH = "./beatmap_classifier/models/meta_model.pkl"

MAX_SEQUENCE_LENGTH = 4096
MAX_SLIDER_LENGTH = 500.0
NUM_CLASSES = 5

COMMIT_INTERVAL = 500

# Normally don't retry variants that already have a status.
# Set to True to retry failed variants.
RETRY_FAILED = False

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")

# ============================================================
# Feature configuration
# ============================================================

sql_feature_names = [
    "ar",
    "od",
    "circle_size",
    "star_rating",
    "bpm",
    "max_combo",
    "length_seconds",
    "object_count",
    "pp",
    "pp_aim",
    "pp_speed",
    "pp_acc",
]


movement_feature_names = [
    "slider_ratio",
    "slider_length_std",
    "speed_std",
    "speed_change_std",
    "speed_change_max",
    "angle_std",
    "angle_mean",
    "rhythm_variance",
    "distance_mean",
    "speed_change_95th",
    "angle_90th",
    "sharp_turn_ratio",
]


cnn_feature_names = [
    "CNN_NM1",
    "CNN_NM2",
    "CNN_NM3",
    "CNN_NM4",
    "CNN_NM5",
]


additional_feature_names = (
    sql_feature_names
    + movement_feature_names
)


selected_features = [
    feature
    for feature in additional_feature_names
]


indices = [
    additional_feature_names.index(name)
    for name in selected_features
]

def find_beatmap_file(
    beatmap_id,
    by_beatmap_id,
    by_md5,
):
    """
    Resolve a database beatmap identifier to a local .osu file.
    First tries a normal numeric BeatmapID lookup.
    If that fails, tries the identifier as an MD5 checksum.
    """

    beatmap_id = str(beatmap_id)

    # Normal numeric ID
    file_path = by_beatmap_id.get(beatmap_id)
    if file_path is not None:
        return file_path

    # Orphaned MD5 identifier
    file_path = by_md5.get(beatmap_id)
    if file_path is not None:
        return file_path

    return None


# ============================================================
# Database
# ============================================================

def get_nm_variants(conn):
    """
    Get NM variants that still need classification.

    RETRY_FAILED=False:

        no status row -> process

    RETRY_FAILED=True:

        no status row -> process
        failed status   -> process

    Successful variants are skipped.
    """

    if RETRY_FAILED:
        rows = conn.execute(
            """
            SELECT
                v.variant_id,
                v.beatmap_id,
                v.ar,
                v.od,
                v.circle_size,
                v.star_rating,
                v.bpm,
                v.max_combo,
                v.length_seconds,
                v.object_count,
                v.pp,
                v.pp_aim,
                v.pp_speed,
                v.pp_acc
            FROM beatmap_variants v
            LEFT JOIN classifier_prediction_status s
                ON s.variant_id = v.variant_id
            WHERE v.mods = 'NM'
              AND (
                    s.variant_id IS NULL
                    OR s.status = 'failed'
              )
            ORDER BY v.variant_id
            """
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT
                v.variant_id,
                v.beatmap_id,
                v.ar,
                v.od,
                v.circle_size,
                v.star_rating,
                v.bpm,
                v.max_combo,
                v.length_seconds,
                v.object_count,
                v.pp,
                v.pp_aim,
                v.pp_speed,
                v.pp_acc
            FROM beatmap_variants v
            LEFT JOIN classifier_prediction_status s
                ON s.variant_id = v.variant_id
            WHERE v.mods = 'NM'
              AND s.variant_id IS NULL
            ORDER BY v.variant_id
            """
        ).fetchall()

    return rows


def save_prediction(
    conn,
    variant_id,
    prediction,
):
    """
    Save NM1-NM5 classifier probabilities.
    """

    probabilities = prediction["probabilities"]
    conn.execute(
        """
        INSERT INTO variant_predictions (
            variant_id,
            nm1,
            nm2,
            nm3,
            nm4,
            nm5
        )
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(variant_id) DO UPDATE SET
            nm1 = excluded.nm1,
            nm2 = excluded.nm2,
            nm3 = excluded.nm3,
            nm4 = excluded.nm4,
            nm5 = excluded.nm5
        """,
        (
            variant_id,
            probabilities.get("NM1", 0.0),
            probabilities.get("NM2", 0.0),
            probabilities.get("NM3", 0.0),
            probabilities.get("NM4", 0.0),
            probabilities.get("NM5", 0.0),
        ),
    )


def save_status(
    conn,
    variant_id,
    status,
    error=None,
):
    """
    Insert or update classifier processing status.
    """
    conn.execute(
        """
        INSERT INTO classifier_prediction_status (
            variant_id,
            status,
            error
        )
        VALUES (?, ?, ?)

        ON CONFLICT(variant_id) DO UPDATE SET
            status = excluded.status,
            error = excluded.error
        """,
        (
            variant_id,
            status,
            error,
        ),
    )


# ============================================================
# Metadata features
# ============================================================

# CHANGED:
# Metadata now comes from the NM database variant instead of
# recalculating it from the .osu file.
#
# This means a .osu file does NOT need to contain:
#     BeatmapID
#     AR
#     OD
#     CS
#     etc.
#
# The .osu file is still used for vectors/movement features.

def get_metadata(
    variant,
):
    """
    Build the metadata features used during training.

    Feature order MUST remain:

        AR
        OD
        CS
        star_rating
        BPM
        max_combo
        length_seconds
        object_count
        pp
        pp_aim
        pp_speed
        pp_acc
    """

    features = np.array(
        [
            variant["ar"],
            variant["od"],
            variant["circle_size"],
            variant["star_rating"],
            variant["bpm"],
            variant["max_combo"],
            variant["length_seconds"],
            variant["object_count"],
            variant["pp"],
            variant["pp_aim"],
            variant["pp_speed"],
            variant["pp_acc"],
        ],
        dtype=np.float32,
    )

    return features


# ============================================================
# CNN prediction
# ============================================================

def predict_cnn(
    beatmap_vectors,
    bagged_models,
):
    """
    Run the beatmap through all CNN models and average
    their probability predictions.
    """

    padded = pad_sequences_pt(
        [beatmap_vectors],
        dtype=torch.float32,
        maxlen=MAX_SEQUENCE_LENGTH,
    )

    # [batch, sequence, channels] -> [batch, channels, sequence]
    padded = padded.permute(0, 2, 1,)
    padded = padded.to(DEVICE)

    model_predictions = []
    with torch.no_grad():
        for model in bagged_models:
            model.eval()
            outputs = model(padded)
            probabilities = torch.softmax(outputs, dim=1,)
            model_predictions.append(probabilities.cpu())

    mean_prediction = torch.stack(model_predictions).mean(dim=0)
    return mean_prediction[0].numpy()


# ============================================================
# Full classifier prediction
# ============================================================

# CHANGED:
# Added `variant` so the classifier can use the database
# metadata associated with this exact NM variant.

def predict_beatmap(
    file_path,
    variant,
    bagged_models,
    label_encoder,
    meta_model,
):
    """
    Run the complete CNN + XGBoost classifier on one
    NM beatmap using an existing local .osu file.

    Returns:
        {
            "label": "...",
            "probabilities": {
                "NM1": ...,
                ...
                "NM5": ...
            }
        }

    Raises an exception if anything goes wrong so that the
    caller can save the actual failure reason.
    """

    # --------------------------------------------------------
    # Parse beatmap
    # --------------------------------------------------------
    beatmap_data = parse_osu_file(file_path, max_slider_length=MAX_SLIDER_LENGTH, print_info=False)
    if beatmap_data is None:
        raise ValueError("parse_osu_file returned None")

    beatmap_vectors = beatmap_data.get("vectors")
    if beatmap_vectors is None:
        raise ValueError("Beatmap has no vectors")
    if len(beatmap_vectors) == 0:
        raise ValueError("Beatmap contains zero vectors")

    # CHANGED:
    # This metadata is diagnostic only.
    # A missing BeatmapID/AR/etc. is no longer fatal because
    # classifier metadata comes from the database variant.
    print(
        "  Parsed metadata:",
        {
            "beatmap_id": beatmap_data.get("beatmap_id"),
            "ar": beatmap_data.get("ar"),
            "od": beatmap_data.get("od"),
            "circle_size": beatmap_data.get("circle_size"),
            "bpm": beatmap_data.get("bpm"),
        }
    )

    # --------------------------------------------------------
    # Calculate NM difficulty
    # --------------------------------------------------------
    # difficulty_result = calculate_difficulty(file_path, mods=[], star_calculator=star_calculator,)
    # if difficulty_result is None:
    #     raise ValueError("calculate_difficulty returned None")

    # --------------------------------------------------------
    # CNN prediction
    # --------------------------------------------------------
    cnn_probs = predict_cnn(beatmap_vectors, bagged_models,)
    if cnn_probs is None:
        raise ValueError("CNN prediction returned None")

    movement_features = extract_movement_features_from_X(np.asarray(beatmap_vectors, dtype=np.float32))
    movement_features = np.asarray(movement_features, dtype=np.float32)

    # CHANGED:
    # Metadata comes directly from the database variant.
    metadata_features = get_metadata(variant)

    additional_features = np.hstack([metadata_features, movement_features]).reshape(1, -1)
    meta_features = np.hstack([cnn_probs.reshape(1, -1), additional_features[:, indices]])

    final_probabilities = (meta_model.predict_proba(meta_features)[0])
    final_class_index = int(np.argmax(final_probabilities))
    final_label = label_encoder.inverse_transform([final_class_index])[0]

    probabilities = {
        str(label).upper(): float(probability)
        for label, probability in zip(label_encoder.classes_, final_probabilities)
    }

    return {
        "label": str(final_label).upper(),
        "probabilities": probabilities,
    }

# ============================================================
# Model loading
# ============================================================

def load_classifier():

    print("Loading label encoder...")

    with open(LABEL_ENCODER_PATH, "rb") as f:
        label_encoder = pickle.load(f)

    print("Loading meta model...")

    with open(META_MODEL_PATH, "rb") as f:
        meta_model = pickle.load(f)

    print("Loading CNN models...")

    model_kwargs = {
        "input_channels": 8,
        "num_classes": NUM_CLASSES,
        "max_length": MAX_SEQUENCE_LENGTH,
        "dropout_rate": 0.5,
    }

    bagged_models = load_pytorch_models(MODEL_FOLDER, CNNModel, model_kwargs, DEVICE)
    print(f"Loaded {len(bagged_models)} CNN models")
    print("Creating star calculator...")

    star_calculator = osu_tools.OsuCalculator()

    return bagged_models, label_encoder, meta_model, star_calculator


# ============================================================
# Main precomputation
# ============================================================

def main():

    print(f"Using device: {DEVICE}")
    print(f"Retry failed: {RETRY_FAILED}")

    conn = sqlite3.connect(DB_PATH)

    try:
        print("Building local .osu file index...")
        by_beatmap_id, by_md5 = build_osu_file_index(DATA_ROOT, conn)

        variants = get_nm_variants(conn)

        total = len(variants)
        if total == 0:
            print("No NM variants require classifier prediction.")
            return

        bagged_models, label_encoder, meta_model, star_calculator = load_classifier()

        successful = 0
        failed = 0

        # CHANGED:
        # Unpack the database metadata along with variant_id/beatmap_id.
        for i, (
            variant_id,
            beatmap_id,
            ar,
            od,
            circle_size,
            star_rating,
            bpm,
            max_combo,
            length_seconds,
            object_count,
            pp,
            pp_aim,
            pp_speed,
            pp_acc,
        ) in enumerate(variants, start=1):

            print(f"[{i:,}/{total:,}] variant={variant_id} beatmap={beatmap_id}")

            # CHANGED:
            # Build the exact NM variant metadata from the database.
            variant = {
                "variant_id": variant_id,
                "beatmap_id": beatmap_id,
                "mods": "NM",
                "ar": ar,
                "od": od,
                "circle_size": circle_size,
                "star_rating": star_rating,
                "bpm": bpm,
                "max_combo": max_combo,
                "length_seconds": length_seconds,
                "object_count": object_count,
                "pp": pp,
                "pp_aim": pp_aim,
                "pp_speed": pp_speed,
                "pp_acc": pp_acc,
            }

            try:
                file_path = find_beatmap_file(beatmap_id, by_beatmap_id, by_md5)

                if file_path is None:
                    failed += 1
                    error_message = f"Local .osu file not found for beatmap identifier {beatmap_id}"
                    save_status(conn, variant_id, "failed", error_message,)
                    print("  -> LOCAL FILE NOT FOUND")
                    continue

                print(f"  -> {file_path}")

                # CHANGED:
                # Pass the database variant into the classifier.
                prediction = predict_beatmap(
                    file_path,
                    variant,
                    bagged_models,
                    label_encoder,
                    meta_model,
                )

                save_prediction(conn, variant_id, prediction)
                save_status(conn, variant_id, "success", None)

                successful += 1
                probabilities = prediction["probabilities"]

                print(
                    f"  -> {prediction['label']} ("
                    f"NM1={probabilities.get('NM1', 0.0):.3f}, "
                    f"NM2={probabilities.get('NM2', 0.0):.3f}, "
                    f"NM3={probabilities.get('NM3', 0.0):.3f}, "
                    f"NM4={probabilities.get('NM4', 0.0):.3f}, "
                    f"NM5={probabilities.get('NM5', 0.0):.3f})"
                )

                if i % COMMIT_INTERVAL == 0:
                    conn.commit()
                    print(f"  -> Committed at {i:,}/{total:,}")

            except Exception as e:
                failed += 1
                error_message = f"{type(e).__name__}: {e}"
                save_status(conn, variant_id, "failed", error_message,)
                print(f"  -> ERROR: {error_message}")

            if i % COMMIT_INTERVAL == 0:
                conn.commit()
                print(f"  -> Committed at {i:,}/{total:,}")

        conn.commit()
        print()
        print("=" * 60)
        print("Precomputation complete")
        print("=" * 60)
        print(f"Successful: {successful:,}")
        print(f"Failed:     {failed:,}")
        print(f"Total:      {total:,}")

    finally:
        conn.close()

if __name__ == "__main__":
    main()