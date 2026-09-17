import sqlite3
from db_recommender import create_recommender_tables
from variant import build_variant_feature_database
from setup_and_k_nearest import load_feature_matrix, scale_features, build_neighbors
from recommender import recommend_for_player

# ============================================================
# Configuration
# ============================================================

DB_PATH = "../beatmaps.db"
NUM_RECOMMENDATIONS = 20
NEIGHBORS_K = 50

# ============================================================
# Mod configuration
# ============================================================

MOD_VARIANTS = {
    "NM": [],
    "HD": ["HD"],
    "HR": ["HR"],
    "DT": ["DT"],
}

MOD_CLOCK_RATES = {
    "NM": 1.0,
    "HD": 1.0,
    "HR": 1.0,
    "DT": 1.5,
    "HT": 0.75,
}

def main():

    print(
        "Opening database..."
    )

    conn = sqlite3.connect(
        DB_PATH
    )

    conn.execute(
        "PRAGMA journal_mode=WAL"
    )

    conn.execute(
        "PRAGMA foreign_keys=ON"
    )

    # --------------------------------------------------------
    # Create recommender tables
    # --------------------------------------------------------

    create_recommender_tables(
        conn
    )

    # --------------------------------------------------------
    # Generate features
    #
    # You only need to run this again when your underlying
    # beatmap/variant data changes.
    # --------------------------------------------------------

    build_variant_feature_database(
        conn
    )

    # --------------------------------------------------------
    # Load matrix
    # --------------------------------------------------------

    print(
        "Loading feature matrix..."
    )

    variant_ids, X = (
        load_feature_matrix(
            conn
        )
    )

    print(
        f"Feature matrix: "
        f"{X.shape}"
    )

    if len(variant_ids) == 0:

        print(
            "No variant features found."
        )

        conn.close()

        return

    # --------------------------------------------------------
    # Scale
    # --------------------------------------------------------

    print(
        "Scaling features..."
    )

    X_scaled, scaler = (
        scale_features(X)
    )

    # --------------------------------------------------------
    # Build neighbors
    # --------------------------------------------------------

    build_neighbors(
        conn,
        variant_ids,
        X_scaled,
        k=NEIGHBORS_K
    )

    # --------------------------------------------------------
    # Test recommendation
    #
    # Replace this with your actual API data.
    # --------------------------------------------------------

    example_top_plays = [
        {
            "beatmap_id": 123456,
            "mods": [],
            "pp": 250.0,
        },
        {
            "beatmap_id": 234567,
            "mods": ["HD"],
            "pp": 275.0,
        },
    ]

    example_recent_plays = [
        {
            "beatmap_id": 345678,
            "mods": ["DT"],
            "pp": 180.0,
        },
    ]

    # --------------------------------------------------------
    # Only run the example if those maps actually exist.
    # --------------------------------------------------------

    recommendations = recommend_for_player(
        conn,
        example_top_plays,
        example_recent_plays,
        num_recommendations=NUM_RECOMMENDATIONS
    )

    print()
    print(
        "Recommendations:"
    )
    print(
        "-" * 80
    )

    for recommendation in recommendations:

        print(
            f"{recommendation['artist']} - "
            f"{recommendation['title']} "
            f"[{recommendation['version']}] "
            f"| "
            f"{recommendation['mods']} "
            f"| score="
            f"{recommendation['recommendation_score']:.4f}"
        )

    conn.close()

    print()
    print(
        "Done."
    )

if __name__ == "__main__":
    main()