import math
from collections import defaultdict
from utils import safe_float
from variant import convert_plays_to_variants

FEATURE_COLUMNS = [
    "star_rating",
    "aim_difficulty",
    "speed_difficulty",
    "flashlight_difficulty",
    "ar",
    "cs",
    "od",
    "hp",
    "bpm",
    "bpm_min",
    "bpm_max",
    "effective_bpm",
    "length",
    "object_count",
    "objects_per_second",
    "circle_ratio",
    "slider_ratio",
    "spinner_ratio",
    "delta_mean",
    "delta_median",
    "delta_std",
    "delta_p25",
    "delta_p75",
    "delta_min",
    "delta_max",
    "spacing_mean",
    "spacing_median",
    "spacing_std",
    "spacing_p25",
    "spacing_p75",
    "spacing_max",
    "movement_speed_mean",
    "movement_speed_median",
    "movement_speed_std",
    "movement_speed_p75",
    "rhythm_ratio_mean",
    "rhythm_ratio_std",
    "rhythm_ratio_p25",
    "rhythm_ratio_p75",
]

def generate_recommendations(
    conn,
    seed_variant_ids,
    already_played_variant_ids=None,
    num_recommendations=20
):
    """
    Basic item-item recommender.

    Every seed contributes its nearest neighbors.
    """

    if already_played_variant_ids is None:
        already_played_variant_ids = set()

    scores = defaultdict(float)

    for seed_id in seed_variant_ids:

        rows = conn.execute(
            """
            SELECT
                neighbor_variant_id,
                similarity,
                rank

            FROM variant_neighbors

            WHERE variant_id = ?

            ORDER BY rank
            """,
            (seed_id,)
        ).fetchall()

        for (
            neighbor_id,
            similarity,
            rank
        ) in rows:

            if (
                neighbor_id
                in already_played_variant_ids
            ):
                continue

            # Rank decay.
            rank_weight = (
                1.0 /
                math.log2(rank + 1)
            )

            scores[
                neighbor_id
            ] += (
                similarity *
                rank_weight
            )

    ranked = sorted(
        scores.items(),
        key=lambda x: x[1],
        reverse=True
    )

    return ranked[
        :num_recommendations
    ]


def build_seed_weights(
    top_plays,
    recent_plays
):
    """
    Create a weight for every seed.

    top_plays / recent_plays should contain:

        {
            "variant_id": ...,
            "pp": ...
        }

    Top plays receive stronger weight.

    Recent plays are also included because they are a
    better representation of what the player currently wants.
    """

    weights = defaultdict(float)

    # --------------------------------------------------------
    # Top plays
    # --------------------------------------------------------

    for play in top_plays:

        variant_id = play[
            "variant_id"
        ]

        pp = safe_float(
            play.get("pp"),
            default=0.0
        )

        pp_weight = min(
            pp / 300.0,
            1.5
        )

        weights[
            variant_id
        ] += (
            1.0 +
            pp_weight
        )

    # --------------------------------------------------------
    # Recent plays
    # --------------------------------------------------------

    for play in recent_plays:

        variant_id = play[
            "variant_id"
        ]

        weights[
            variant_id
        ] += 0.75

    return weights


def generate_weighted_recommendations(
    conn,
    seed_weights,
    already_played_variant_ids,
    num_recommendations=20
):
    """
    Item-item recommendation with seed weighting.
    """

    scores = defaultdict(float)

    for (
        seed_id,
        seed_weight
    ) in seed_weights.items():

        rows = conn.execute(
            """
            SELECT
                neighbor_variant_id,
                similarity,
                rank

            FROM variant_neighbors

            WHERE variant_id = ?
            """,
            (seed_id,)
        ).fetchall()

        for (
            neighbor_id,
            similarity,
            rank
        ) in rows:

            if (
                neighbor_id
                in already_played_variant_ids
            ):
                continue

            rank_weight = (
                1.0 /
                math.log2(rank + 1)
            )

            scores[
                neighbor_id
            ] += (
                seed_weight *
                similarity *
                rank_weight
            )

    ranked = sorted(
        scores.items(),
        key=lambda x: x[1],
        reverse=True
    )

    return ranked[
        :num_recommendations
    ]


def get_recommendation_details(
    conn,
    recommendations
):
    """
    Convert variant IDs into useful beatmap information.
    """

    results = []

    for (
        variant_id,
        recommendation_score
    ) in recommendations:

        row = conn.execute(
            """
            SELECT
                v.variant_id,
                v.beatmap_id,
                v.mods,

                b.beatmapset_id,
                b.artist,
                b.title,
                b.version

            FROM beatmap_variants v

            JOIN beatmaps b
                ON b.beatmap_id =
                   v.beatmap_id

            WHERE v.variant_id = ?
            """,
            (variant_id,)
        ).fetchone()

        if row is None:
            continue

        results.append({

            "variant_id":
                row[0],

            "beatmap_id":
                row[1],

            "mods":
                row[2],

            "beatmapset_id":
                row[3],

            "artist":
                row[4],

            "title":
                row[5],

            "version":
                row[6],

            "recommendation_score":
                recommendation_score,
        })

    return results


# ============================================================
# Example recommendation pipeline
# ============================================================

def recommend_for_player(
    conn,
    top_plays,
    recent_plays,
    num_recommendations=20
):
    """
    Full recommendation pipeline.

    top_plays and recent_plays are expected to contain:

        {
            "beatmap_id": ...,
            "mods": [...],
            "pp": ...
        }
    """

    # --------------------------------------------------------
    # Convert plays to variants
    # --------------------------------------------------------

    top_variants = (
        convert_plays_to_variants(
            conn,
            top_plays
        )
    )

    recent_variants = (
        convert_plays_to_variants(
            conn,
            recent_plays
        )
    )

    # --------------------------------------------------------
    # Everything the player has already played
    # --------------------------------------------------------

    already_played = set()

    for play in (
        top_variants +
        recent_variants
    ):
        already_played.add(
            play["variant_id"]
        )

    # --------------------------------------------------------
    # Build seed weights
    # --------------------------------------------------------

    seed_weights = (
        build_seed_weights(
            top_variants,
            recent_variants
        )
    )

    # --------------------------------------------------------
    # Generate recommendations
    # --------------------------------------------------------

    recommendations = (
        generate_weighted_recommendations(
            conn,
            seed_weights,
            already_played,
            num_recommendations
        )
    )

    # --------------------------------------------------------
    # Convert IDs into metadata
    # --------------------------------------------------------

    return get_recommendation_details(
        conn,
        recommendations
    )
