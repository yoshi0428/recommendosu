import numpy as np
from beatmap_recommender.content_similarity.core_modules.ability import get_ability_score_weight
from beatmap_recommender.content_similarity.core_modules.cnn_xgboost_influence import calculate_classifier_score, get_candidate_classifier_predictions
from .pp_potential import weighted_mean_and_std, calculate_pp_potential
from .mod_preferences import canonicalize_mods
import time
from beatmap_recommender.cancellation import check_cancelled


def get_player_played_variants(conn, player_id, cancel_event=None):
    """
    Get the actual beatmap variants represented in the player's scores.
    We fetch the player's scores first, then fetch all variants for the relevant beatmaps in one query.
    This avoids relying on SQL equality between potentially non-canonical mod strings such as:

        DTHD
        HDDT

    Both are canonicalized to:

        HDDT

    Score-specific information such as source, PP, and created_at comes from the scores table.
    Variant-specific information such as star rating, AR, OD, and BPM comes from beatmap_variants.
    """
    check_cancelled(cancel_event)

    # ------------------------------------------------------------------
    # Fetch player's scores.
    # ------------------------------------------------------------------
    score_rows = conn.execute(
        """
        SELECT
            beatmap_id,
            mods,
            source,
            pp,
            created_at
        FROM scores
        WHERE player_id = ?
        """,
        (player_id,),
    ).fetchall()

    check_cancelled(cancel_event)
    if not score_rows:
        return []

    # ------------------------------------------------------------------
    # Get all beatmap IDs represented in the player's scores.
    # ------------------------------------------------------------------
    beatmap_ids = sorted({
        str(row[0])
        for row in score_rows
    })

    check_cancelled(cancel_event)
    placeholders = ",".join("?" for _ in beatmap_ids)

    # ------------------------------------------------------------------
    # Fetch all variants for those beatmaps.
    # ------------------------------------------------------------------
    variant_rows = conn.execute(
        f"""
        SELECT
            variant_id,
            beatmap_id,
            mods,
            star_rating,
            ar,
            od,
            bpm
        FROM beatmap_variants
        WHERE beatmap_id IN ({placeholders})
        """,
        beatmap_ids,
    ).fetchall()

    check_cancelled(cancel_event)
    variants_by_key = {}

    for row in variant_rows:
        (
            variant_id,
            beatmap_id,
            mods,
            star_rating,
            ar,
            od,
            bpm,
        ) = row

        canonical_mods = canonicalize_mods(mods)
        key = (str(beatmap_id), canonical_mods)

        # If the database contains duplicate representations such as DTHD and HDDT, keep the first one for now.
        if key not in variants_by_key:
            variants_by_key[key] = {
                "variant_id": variant_id,
                "beatmap_id": str(beatmap_id),
                "mods": canonical_mods,
                "star_rating": star_rating,
                "ar": ar,
                "od": od,
                "bpm": bpm,
            }

    check_cancelled(cancel_event)

    # ------------------------------------------------------------------
    # Combine score-specific information with variant information.
    # ------------------------------------------------------------------
    played_variants = []

    for (
        beatmap_id,
        mods,
        source,
        pp,
        created_at,
    ) in score_rows:

        beatmap_id = str(beatmap_id)
        mods = canonicalize_mods(mods)
        variant = variants_by_key.get((beatmap_id, mods))

        if variant is None:
            continue

        played_variants.append({
            **variant,
            "source": source,
            "pp": pp,
            "created_at": created_at,
        })

    check_cancelled(cancel_event)
    return played_variants


def get_player_difficulty_profile(
    conn,
    player_id,
    difficulty_std_floors,
    recency_half_life_days,
    ability_top_weight,
    ability_recent_weight,
    ability_pp_weight,
    cancel_event=None,
):
    """
    Calculate the player's current difficulty profile.

    The profile is based on the actual variants they played, rather than converting everything to NM.

    Therefore:

        6.5★ NM
        7.2★ HR
        8.0★ DT

    are treated as different difficulty experiences.

    Unlike mod preferences, this profile uses recency-aware ability weighting:
        - recent scores receive more weight
        - newer scores naturally decay less
        - older scores gradually lose influence
        - PP provides a small additional weighting factor

    The score timestamp comes from:
        scores.created_at
    """
    check_cancelled(cancel_event)
    played_variants = get_player_played_variants(conn, player_id, cancel_event=cancel_event)
    check_cancelled(cancel_event)

    if not played_variants:
        return {}

    features = [
        "star_rating",
        "ar",
        "od",
        "bpm",
    ]

    profile = {}
    for feature_index, feature in enumerate(features):
        check_cancelled(cancel_event)

        values = []
        weights = []
        for index, variant in enumerate(played_variants):

            if index % 1024 == 0:
                check_cancelled(cancel_event)

            value = variant.get(feature)

            if value is None:
                continue

            try:
                value = float(value)
            except (TypeError, ValueError):
                continue

            # ----------------------------------------------------------
            # Score-specific ability weight.
            #
            # created_at comes from the scores table and was attached
            # to the variant by get_player_played_variants().
            # ----------------------------------------------------------
            weight = get_ability_score_weight(
                variant["source"],
                variant["pp"],
                variant["created_at"],
                recency_half_life_days, ability_top_weight, ability_recent_weight, ability_pp_weight
            )
            values.append(value)
            weights.append(weight)

        check_cancelled(cancel_event)

        if not values:
            continue

        mean, std = weighted_mean_and_std(values, weights)
        std = max(std, difficulty_std_floors[feature])
        profile[f"{feature}_mean"] = mean
        profile[f"{feature}_std"] = std

    check_cancelled(cancel_event)
    return profile


def get_candidate_variants(
    conn,
    beatmap_ids,
    requested_mods=None,
    min_stars=None,
    max_stars=None,
    min_bpm=None,
    max_bpm=None,
    min_pp=None,
    max_pp=None,
    min_ar=None,
    max_ar=None,
    min_od=None,
    max_od=None,
    min_length=None,
    max_length=None,
    min_combo=None,
    max_combo=None,
    cancel_event=None,
):
    """
    Fetch candidate variants belonging to the supplied base beatmaps.

    Numeric filters are pushed into SQLite so that variants which
    cannot possibly be recommended are never loaded into Python.
    """

    if not beatmap_ids:
        return []

    placeholders = ",".join("?" for _ in beatmap_ids)
    params = list(beatmap_ids)
    conditions = [
        f"bv.beatmap_id IN ({placeholders})"
    ]

    # --------------------------------------------------------------
    # Mod filter
    # --------------------------------------------------------------

    if requested_mods is not None:
        requested_mods = canonicalize_mods(requested_mods)
        conditions.append("bv.mods = ?")
        params.append(requested_mods)

    # --------------------------------------------------------------
    # Numeric filters
    # --------------------------------------------------------------
    if min_stars is not None:
        conditions.append("bv.star_rating >= ?")
        params.append(min_stars)

    if max_stars is not None:
        conditions.append("bv.star_rating <= ?")
        params.append(max_stars)

    if min_bpm is not None:
        conditions.append("bv.bpm >= ?")
        params.append(min_bpm)

    if max_bpm is not None:
        conditions.append("bv.bpm <= ?")
        params.append(max_bpm)

    if min_pp is not None:
        conditions.append("bv.pp >= ?")
        params.append(min_pp)

    if max_pp is not None:
        conditions.append("bv.pp <= ?")
        params.append(max_pp)

    if min_ar is not None:
        conditions.append("bv.ar >= ?")
        params.append(min_ar)

    if max_ar is not None:
        conditions.append("bv.ar <= ?")
        params.append(max_ar)

    if min_od is not None:
        conditions.append("bv.od >= ?")
        params.append(min_od)

    if max_od is not None:
        conditions.append("bv.od <= ?")
        params.append(max_od)

    if min_length is not None:
        conditions.append("bv.length_seconds >= ?")
        params.append(min_length)

    if max_length is not None:
        conditions.append("bv.length_seconds <= ?")
        params.append(max_length)

    if min_combo is not None:
        conditions.append("bv.max_combo >= ?")
        params.append(min_combo)

    if max_combo is not None:
        conditions.append("bv.max_combo <= ?")
        params.append(max_combo)

    # --------------------------------------------------------------
    # Query
    # --------------------------------------------------------------
    check_cancelled(cancel_event)
    start = time.perf_counter()
    rows = conn.execute(
        f"""
        SELECT
            bv.variant_id,
            bv.beatmap_id,
            bv.beatmapset_id,
            bv.mods,
            b.title,
            b.artist,
            b.creator,
            b.version,
            bv.hp_drain,
            bv.circle_size,
            bv.od,
            bv.ar,
            bv.star_rating,
            bv.max_combo,
            bv.bpm,
            bv.length_seconds,
            bv.object_count,
            bv.pp,
            bv.pp_aim,
            bv.pp_speed,
            bv.pp_acc,
            bv.pp_flashlight

        FROM beatmap_variants AS bv
        JOIN beatmaps AS b
            ON b.beatmap_id = bv.beatmap_id

        WHERE {" AND ".join(conditions)}
        """,
        params,
    ).fetchall()

    check_cancelled(cancel_event)

    print(
        f"[get_candidate_variants] SQLite query: "
        f"{time.perf_counter() - start:.4f}s "
        f"({len(rows)} rows)"
    )

    columns = [
        "variant_id",
        "beatmap_id",
        "beatmapset_id",
        "mods",

        "title",
        "artist",
        "creator",
        "version",

        "hp_drain",
        "circle_size",
        "od",
        "ar",
        "star_rating",
        "max_combo",
        "bpm",
        "length_seconds",
        "object_count",
        "pp",
        "pp_aim",
        "pp_speed",
        "pp_acc",
        "pp_flashlight",
    ]

    start = time.perf_counter()

    variants = []

    for index, row in enumerate(rows):
        if index % 1024 == 0:
            check_cancelled(cancel_event)

        variants.append(dict(zip(columns, row)))

    check_cancelled(cancel_event)

    print(
        f"[get_candidate_variants] Python conversion: "
        f"{time.perf_counter() - start:.4f}s "
        f"({len(variants)} variants)"
    )

    return variants


def calculate_difficulty_scores(
    variants,
    difficulty_profile,
    difficulty_std_floors,
    difficulty_feature_weights,
    cancel_event=None,
):
    """
    Calculate how well each variant's difficulty matches the player's current difficulty profile.

    Returns approximately [0, 1] for each variant:

        1.0 = very close to player's typical difficulty
        0.5 = moderate difference
        0.0 = very far from player's typical difficulty

    Star rating receives the strongest weight.

    The calculation is vectorized across all variants.
    """
    check_cancelled(cancel_event)

    if not variants:
        return np.empty(0, dtype=np.float32)

    if not difficulty_profile:
        return np.full(len(variants), 0.5,dtype=np.float32,)

    # ------------------------------------------------------------------
    # Build weighted feature matrix.
    # ------------------------------------------------------------------
    feature_values = []
    feature_weights = []

    for feature, feature_weight in difficulty_feature_weights.items():
        check_cancelled(cancel_event)

        mean = difficulty_profile.get(f"{feature}_mean")
        std = difficulty_profile.get(f"{feature}_std")

        if mean is None or std is None:
            continue

        try:
            mean = float(mean)
            std = float(std)
        except (TypeError, ValueError):
            continue

        if std <= 0:
            std = difficulty_std_floors[feature]

        values = np.asarray(
            [
                float(variant[feature])
                if variant.get(feature) is not None else np.nan
                for variant in variants
            ],
            dtype=np.float32,
        )

        check_cancelled(cancel_event)

        z = (values - mean) / std
        valid = np.isfinite(z)
        feature_values.append(np.where(valid, z ** 2, 0.0))
        feature_weights.append(np.where(valid, feature_weight, 0.0))

    check_cancelled(cancel_event)
    if not feature_values:
        return np.full(len(variants), 0.5, dtype=np.float32)

    # ------------------------------------------------------------------
    # Stack:
    #
    #     rows    = variants
    #     columns = difficulty features
    # ------------------------------------------------------------------
    squared_z_matrix = np.stack(feature_values, axis=1)
    weight_matrix = np.stack(feature_weights, axis=1)

    check_cancelled(cancel_event)

    # ------------------------------------------------------------------
    # Weighted squared distance.
    # ------------------------------------------------------------------
    weighted_squared_distance = (squared_z_matrix * weight_matrix)
    total_weight = weight_matrix.sum(axis=1)

    # Avoid division by zero for variants where every feature was missing/invalid.
    valid_variants = total_weight > 0

    scores = np.full(len(variants), 0.5, dtype=np.float32)

    if np.any(valid_variants):
        distance = np.sqrt(
            weighted_squared_distance[valid_variants].sum(axis=1)
            / total_weight[valid_variants]
        )

        check_cancelled(cancel_event)

        # --------------------------------------------------------------
        # Gaussian-like falloff.
        #
        # distance = 0 -> 1.0
        # distance = 1 -> ~0.61
        # distance = 2 -> ~0.14
        # distance = 3 -> ~0.01
        # --------------------------------------------------------------
        scores[valid_variants] = np.exp(-0.5 * distance ** 2)

    check_cancelled(cancel_event)
    return scores


def score_variant(
    content_similarity,
    mod_preference,
    difficulty_score,
    classifier_score=0.5,
    pp_potential=0.5,
    recommendation_goal="balanced",
    recommendation_config=None,
):
    """
    Combine all recommendation signals for one variant.

    content_similarity:
        How similar the BASE beatmap is to the player's liked maps.

    mod_preference:
        How much the player tends to play this exact mod combination.

    difficulty_score:
        How appropriate the actual modded difficulty is for the player.
    """
    if recommendation_goal not in recommendation_config:
        raise ValueError(
            f"Unknown recommendation goal: {recommendation_goal!r}. "
            f"Expected one of {sorted(recommendation_config)}"
        )

    config = recommendation_config[recommendation_goal]
    weights = config["weights"]

    return (
        weights["content"] * content_similarity
        + weights["mod_preference"] * mod_preference
        + weights["difficulty"] * difficulty_score
        + weights["classifier"] * classifier_score
        + weights["pp_potential"] * pp_potential
    )


def rank_variants(
    conn,
    similarity_index,
    mod_preferences,
    difficulty_profile,
    category_preferences=None,
    top_k=None,
    requested_mods=None,
    min_stars=None,
    max_stars=None,
    min_bpm=None,
    max_bpm=None,
    min_pp=None,
    max_pp=None,
    min_ar=None,
    max_ar=None,
    min_od=None,
    max_od=None,
    min_length=None,
    max_length=None,
    min_combo=None,
    max_combo=None,
    recommendation_goal="balanced",
    recommendation_config=None,
    difficulty_std_floors=None,
    difficulty_feature_weights=None,
    pp_push_target_z=None,
    pp_push_max_z=None,
    cancel_event=None,
):
    """
    Rank variants for all candidate base maps.
    similarity_index format:

        {
            seed_beatmap_id: [
                (candidate_beatmap_id, similarity),
                ...
            ]
        }

    The same candidate beatmap can appear for multiple seed maps.
    We keep the BEST content similarity that candidate receives.

    Optional filters are hard constraints:

        requested_mods
        min_stars / max_stars
        min_bpm / max_bpm
        min_pp / max_pp
        min_length / max_length

    Filtering happens before variant scoring.

    Then:

        1. collapse seed -> candidates into best similarity
        2. load candidate variants
        3. apply numeric filters
        4. calculate variant-specific difficulty
        5. calculate mod preference
        6. calculate final score
        7. keep the best variant for each base beatmap
        8. sort globally
        9. return top_k
    """
    check_cancelled(cancel_event)
    total_start = time.perf_counter()

    if not similarity_index:
        return []

    config = recommendation_config[recommendation_goal]
    weights = config["weights"]
    classifier_weight = weights["classifier"]
    pp_potential_weight = weights["pp_potential"]

    # ------------------------------------------------------------------
    # Validate filters
    # ------------------------------------------------------------------
    if min_stars is not None and max_stars is not None and min_stars > max_stars:
        raise ValueError(f"min_stars ({min_stars}) cannot be greater than max_stars ({max_stars})")

    if min_bpm is not None and max_bpm is not None and min_bpm > max_bpm:
        raise ValueError(f"min_bpm ({min_bpm}) cannot be greater than max_bpm ({max_bpm})")

    if min_pp is not None and max_pp is not None and min_pp > max_pp:
        raise ValueError(f"min_pp ({min_pp}) cannot be greater than max_pp ({max_pp})")

    if min_ar is not None and max_ar is not None and min_ar > max_ar:
        raise ValueError(f"min_ar ({min_ar}) cannot be greater than max_ar ({max_ar})")

    if min_od is not None and max_od is not None and min_od > max_od:
        raise ValueError(f"min_od ({min_od}) cannot be greater than max_od ({max_od})")

    if min_length is not None and max_length is not None and min_length > max_length:
        raise ValueError(f"min_length ({min_length}) cannot be greater than max_length ({max_length})")

    if min_combo is not None and max_combo is not None and min_combo > max_combo:
        raise ValueError(f"min_combo ({min_combo}) cannot be greater than max_combo ({max_combo})")

    # ------------------------------------------------------------------
    # Collapse seed -> candidates into:
    # beatmap_id -> best similarity
    # ------------------------------------------------------------------
    start = time.perf_counter()

    candidate_similarity = {}
    for seed_index, (seed_beatmap_id, similar_maps) in enumerate(similarity_index.items()):
        check_cancelled(cancel_event)
        for beatmap_id, similarity in similar_maps:
            beatmap_id = str(beatmap_id)
            similarity = float(similarity)
            previous = candidate_similarity.get(beatmap_id)

            if previous is None or similarity > previous:
                candidate_similarity[beatmap_id] = similarity

    check_cancelled(cancel_event)

    print(
        f"\n[rank_variants] Collapse similarities: "
        f"{time.perf_counter() - start:.4f}s "
        f"({len(candidate_similarity)} candidate beatmaps)"
    )

    if not candidate_similarity:
        return []

    # ------------------------------------------------------------------
    # Load all variants.
    # ------------------------------------------------------------------
    start = time.perf_counter()

    if requested_mods is not None:
        requested_mods = canonicalize_mods(requested_mods)

    variants = get_candidate_variants(
        conn,
        candidate_similarity.keys(),
        requested_mods=requested_mods,
        min_stars=min_stars,
        max_stars=max_stars,
        min_bpm=min_bpm,
        max_bpm=max_bpm,
        min_pp=min_pp,
        max_pp=max_pp,
        min_ar=min_ar,
        max_ar=max_ar,
        min_od=min_od,
        max_od=max_od,
        min_length=min_length,
        max_length=max_length,
        min_combo=min_combo,
        max_combo=max_combo,
        cancel_event=cancel_event,
    )

    check_cancelled(cancel_event)

    print(
        f"[rank_variants] Load candidate variants: "
        f"{time.perf_counter() - start:.4f}s "
        f"({len(variants)} variants)"
    )

    if not variants:
        return []

    # ------------------------------------------------------------------
    # Classifier predictions.
    # ------------------------------------------------------------------
    check_cancelled(cancel_event)
    start = time.perf_counter()

    classifier_predictions = {}

    if classifier_weight > 0 and category_preferences:
        classifier_variant_ids = [
            variant["variant_id"]
            for variant in variants
            if variant["mods"] == "NM"
        ]

        if classifier_variant_ids:
            classifier_predictions = get_candidate_classifier_predictions(
                conn,
                classifier_variant_ids,
            )

    check_cancelled(cancel_event)

    print(
        f"[rank_variants] Classifier predictions: "
        f"{time.perf_counter() - start:.4f}s "
        f"({len(classifier_predictions)} predictions)"
    )

    # ------------------------------------------------------------------
    # Difficulty scores
    # ------------------------------------------------------------------
    start = time.perf_counter()

    difficulty_weight = weights["difficulty"]

    if difficulty_weight > 0:
        difficulty_scores = calculate_difficulty_scores(
            variants,
            difficulty_profile,
            difficulty_std_floors,
            difficulty_feature_weights,
            cancel_event=cancel_event
        )
    else:
        difficulty_scores = np.full(
            len(variants),
            0.5,
            dtype=np.float32,
        )

    check_cancelled(cancel_event)

    print(
        f"[rank_variants] Difficulty scores: "
        f"{time.perf_counter() - start:.4f}s "
        f"({len(variants)} variants)"
    )

    # ------------------------------------------------------------------
    # Score variants.
    # ------------------------------------------------------------------
    start = time.perf_counter()

    scored_variants = []

    for index, variant in enumerate(variants):
        if index % 1024 == 0:
            check_cancelled(cancel_event)

        beatmap_id = variant["beatmap_id"]
        content_similarity = candidate_similarity[beatmap_id]
        mods = variant["mods"]
        mod_preference = mod_preferences.get(mods, 0.0)

        difficulty_score = float(difficulty_scores[index])

        # --------------------------------------------------------------
        # Classifier score
        # --------------------------------------------------------------
        if classifier_weight <= 0:
            classifier_score = 0.5
        elif mods == "NM" and category_preferences:
            probabilities = classifier_predictions.get(variant["variant_id"])
            classifier_score = calculate_classifier_score(
                probabilities,
                category_preferences,
            )
        else:
            classifier_score = 0.5

        # --------------------------------------------------------------
        # PP potential
        # --------------------------------------------------------------
        if pp_potential_weight > 0:
            pp_potential = calculate_pp_potential(
                variant,
                difficulty_profile,
                difficulty_std_floors,
                difficulty_feature_weights,
                pp_push_target_z,
                pp_push_max_z,
            )
        else:
            pp_potential = 0.5

        # --------------------------------------------------------------
        # Final score
        # --------------------------------------------------------------
        final_score = score_variant(
            content_similarity,
            mod_preference,
            difficulty_score,
            classifier_score,
            pp_potential,
            recommendation_goal,
            recommendation_config,
        )

        scored_variants.append({
            **variant,
            "content_similarity": content_similarity,
            "mod_preference": mod_preference,
            "difficulty_score": difficulty_score,
            "classifier_score": classifier_score,
            "pp_potential": pp_potential,
            "final_score": final_score,
        })

    check_cancelled(cancel_event)

    print(
        f"[rank_variants] Score variants: "
        f"{time.perf_counter() - start:.4f}s "
        f"({len(variants)} variants)"
    )

    # ------------------------------------------------------------------
    # Keep only the best variant for each base beatmap.
    # ------------------------------------------------------------------
    start = time.perf_counter()

    best_by_beatmap = {}

    for index, variant in enumerate(scored_variants):
        if index % 1024 == 0:
            check_cancelled(cancel_event)

        beatmap_id = variant["beatmap_id"]
        previous = best_by_beatmap.get(beatmap_id)

        if previous is None or variant["final_score"] > previous["final_score"]:
            best_by_beatmap[beatmap_id] = variant

    check_cancelled(cancel_event)

    print(
        f"[rank_variants] Best variants: "
        f"{time.perf_counter() - start:.4f}s "
        f"({len(best_by_beatmap)} beatmaps)"
    )

    # ------------------------------------------------------------------
    # Sort globally.
    # ------------------------------------------------------------------
    check_cancelled(cancel_event)
    start = time.perf_counter()

    config = recommendation_config[recommendation_goal]
    ranked = list(best_by_beatmap.values())

    sort_keys = config["sort_keys"]

    ranked.sort(
        key=lambda variant: tuple(
            variant[key]
            for key in sort_keys
        ),
        reverse=True,
    )

    check_cancelled(cancel_event)

    if top_k is not None:
        ranked = ranked[:top_k]

    print(
        f"[rank_variants] Sort and truncate: "
        f"{time.perf_counter() - start:.4f}s "
        f"({len(ranked)} results)"
    )

    # ------------------------------------------------------------------
    # Total time.
    # ------------------------------------------------------------------
    print(
        f"[rank_variants] TOTAL: "
        f"{time.perf_counter() - total_start:.4f}s"
    )

    return ranked