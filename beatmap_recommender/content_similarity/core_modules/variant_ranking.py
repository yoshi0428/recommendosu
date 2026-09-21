import time
import numpy as np
from beatmap_recommender.cancellation import check_cancelled
from beatmap_recommender.content_similarity.core_modules.ability import (
    get_ability_score_weight,
)
from beatmap_recommender.content_similarity.core_modules.cnn_xgboost_influence import (
    calculate_classifier_score,
    get_candidate_classifier_predictions,
)
from .mod_preferences import canonicalize_mods
from .pp_potential import calculate_pp_potential, weighted_mean_and_std


MOD_ORDER = ["EZ", "NF", "HT", "HD", "HR", "DT", "NC", "FL"]


def get_player_played_variants(
    conn,
    player_id,
    exclude_recent_plays=False,
    cancel_event=None,
):
    """
    Get the actual beatmap variants represented in the player's scores.

    Score-specific data comes from scores. Variant-specific data comes
    from beatmap_variants. Mod strings are canonicalized before matching
    so representations such as DTHD and HDDT resolve to the same variant.
    """
    check_cancelled(cancel_event)

    # ── Fetch scores ────────────────────────────────────────────
    score_rows = conn.execute(
        """
        SELECT beatmap_id, mods, source, pp, created_at
        FROM scores
        WHERE player_id = ?
        """,
        (player_id,),
    ).fetchall()

    check_cancelled(cancel_event)
    if not score_rows:
        return []

    beatmap_ids = sorted({str(row[0]) for row in score_rows})
    check_cancelled(cancel_event)

    # ── Fetch variants ─────────────────────────────────────────
    placeholders = ",".join("?" for _ in beatmap_ids)

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
        variant_id, beatmap_id, mods, star_rating, ar, od, bpm = row
        canonical_mods = canonicalize_mods(mods)
        key = (str(beatmap_id), canonical_mods)

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

    # ── Combine score + variant data ───────────────────────────
    played_variants = []

    for beatmap_id, mods, source, pp, created_at in score_rows:
        beatmap_id = str(beatmap_id)
        mods = canonicalize_mods(mods)
        variant = variants_by_key.get((beatmap_id, mods))

        if variant is None:
            continue

        # this is the target if you'd like to exclude recent plays...
        # really trippy logic that is worth commenting here
        #
        # True True -> False True which would append top plays
        # True False -> False False which would not append recent plays
        # False True -> True True which would append top plays
        # False False -> True False which would append recent plays
        if not exclude_recent_plays or source == "top":
            played_variants.append({
                **variant,
                "source": source,
                "pp": pp,
                "created_at": created_at,
            })

    check_cancelled(cancel_event)
    return played_variants


def get_player_difficulty_profiles(
    conn,
    player_id,
    difficulty_std_floors,
    recency_half_life_days,
    ability_top_weight,
    ability_recent_weight,
    ability_pp_weight,
    exclude_recent_plays,
    min_profile_plays=5,
    cancel_event=None,
):
    """
    Calculate the player's global and exact-mod difficulty profiles.

    The global profile is used by recommendation ranking as the player's
    overall demonstrated difficulty level. Exact-mod profiles are retained
    for future mod-specific difficulty refinement.
    """
    check_cancelled(cancel_event)

    played_variants = get_player_played_variants(
        conn,
        player_id,
        exclude_recent_plays=exclude_recent_plays,
        cancel_event=cancel_event,
    )

    check_cancelled(cancel_event)

    if not played_variants:
        return {}, {}

    features = ("star_rating", "ar", "od", "bpm")

    def build_profile(variants):
        profile = {}

        for feature in features:
            check_cancelled(cancel_event)

            values = []
            weights = []

            for index, variant in enumerate(variants):
                if index % 1024 == 0:
                    check_cancelled(cancel_event)

                value = variant.get(feature)

                if value is None:
                    continue

                try:
                    value = float(value)
                except (TypeError, ValueError):
                    continue

                weight = get_ability_score_weight(
                    variant["source"],
                    variant["pp"],
                    variant["created_at"],
                    recency_half_life_days,
                    ability_top_weight,
                    ability_recent_weight,
                    ability_pp_weight,
                )

                values.append(value)
                weights.append(weight)

            if not values:
                continue

            mean, std = weighted_mean_and_std(values, weights)
            std = max(std, difficulty_std_floors[feature])

            profile[f"{feature}_mean"] = mean
            profile[f"{feature}_std"] = std

        return profile

    # ── Global profile ─────────────────────────────────────────
    global_profile = build_profile(played_variants)

    # ── Group by exact mod combination ─────────────────────────
    variants_by_mod = {}

    for variant in played_variants:
        variants_by_mod.setdefault(
            variant["mods"],
            [],
        ).append(variant)

    # ── Exact-mod profiles ─────────────────────────────────────
    mod_profiles = {}

    for mods, variants in variants_by_mod.items():
        check_cancelled(cancel_event)

        if len(variants) < min_profile_plays:
            continue

        profile = build_profile(variants)

        if profile:
            mod_profiles[mods] = profile

    check_cancelled(cancel_event)

    return global_profile, mod_profiles


def get_candidate_variants(
    conn,
    beatmap_ids,
    requested_mods=None,
    excluded_mods=None,
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
    min_cs=None,
    max_cs=None,
    cancel_event=None,
):
    """Fetch candidate variants and apply SQL-level filters."""
    if not beatmap_ids:
        return []

    placeholders = ",".join("?" for _ in beatmap_ids)
    params = list(beatmap_ids)
    conditions = [f"bv.beatmap_id IN ({placeholders})"]

    # ── Mod filters ────────────────────────────────────────────
    if requested_mods:
        requested_mods = {
            mod.strip().upper()
            for mod in requested_mods
        }

        gameplay_mods = [
            mod
            for mod in MOD_ORDER
            if mod in requested_mods
        ]

        valid_variants = ["NM"] if "NM" in requested_mods else []

        for mask in range(1, 1 << len(gameplay_mods)):
            combination = [
                gameplay_mods[index]
                for index in range(len(gameplay_mods))
                if mask & (1 << index)
            ]
            valid_variants.append("".join(combination))

        mod_placeholders = ",".join("?" for _ in valid_variants)
        conditions.append(f"bv.mods IN ({mod_placeholders})")
        params.extend(valid_variants)

    if excluded_mods:
        for mod in excluded_mods:
            if mod == "NM":
                conditions.append("bv.mods != 'NM'")
            else:
                conditions.append("bv.mods NOT LIKE ?")
                params.append(f"%{mod}%")

    # ── Numeric filters ────────────────────────────────────────
    numeric_filters = (
        ("bv.star_rating", min_stars, max_stars),
        ("bv.bpm", min_bpm, max_bpm),
        ("bv.pp", min_pp, max_pp),
        ("bv.ar", min_ar, max_ar),
        ("bv.od", min_od, max_od),
        ("bv.length_seconds", min_length, max_length),
        ("bv.max_combo", min_combo, max_combo),
        ("bv.circle_size", min_cs, max_cs),
    )

    for column, minimum, maximum in numeric_filters:
        if minimum is not None:
            conditions.append(f"{column} >= ?")
            params.append(minimum)

        if maximum is not None:
            conditions.append(f"{column} <= ?")
            params.append(maximum)

    # ── Query ──────────────────────────────────────────────────
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

    print(f"[get_candidate_variants] SQLite query: {time.perf_counter() - start:.4f}s ({len(rows)} rows)")

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

    variants = [
        dict(zip(columns, row))
        for row in rows
    ]

    check_cancelled(cancel_event)
    print(f"[get_candidate_variants] Python conversion: {time.perf_counter() - start:.4f}s ({len(variants)} variants)")
    return variants


def calculate_difficulty_scores(
    variants,
    difficulty_profile,
    difficulty_std_floors,
    difficulty_feature_weights,
    cancel_event=None,
):
    """
    Calculate how closely each variant matches the player's difficulty.

    This score is used for ranking candidates after the hard star-rating
    constraint has been applied.

    Returns scores approximately in [0, 1]:
        1.0 = very close
        0.5 = moderate difference
        0.0 = very far
    """
    check_cancelled(cancel_event)

    if not variants:
        return np.empty(0, dtype=np.float32)

    if not difficulty_profile:
        return np.full(len(variants), 0.5, dtype=np.float32)

    # ── Build weighted feature matrix ──────────────────────────
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

        std = max(std, difficulty_std_floors[feature])

        values = np.asarray(
            [
                float(variant[feature])
                if variant.get(feature) is not None
                else np.nan
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

    # ── Weighted distance ──────────────────────────────────────
    squared_z_matrix = np.stack(feature_values, axis=1)
    weight_matrix = np.stack(feature_weights, axis=1)

    check_cancelled(cancel_event)

    weighted_squared_distance = squared_z_matrix * weight_matrix
    total_weight = weight_matrix.sum(axis=1)
    valid_variants = total_weight > 0

    scores = np.full(
        len(variants),
        0.5,
        dtype=np.float32,
    )

    if np.any(valid_variants):
        distance = np.sqrt(
            weighted_squared_distance[valid_variants].sum(axis=1)
            / total_weight[valid_variants]
        )
        check_cancelled(cancel_event)
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
    """Combine recommendation signals for one variant."""
    if recommendation_goal not in recommendation_config:
        raise ValueError(f"Unknown recommendation goal: {recommendation_goal!r}. Expected one of {sorted(recommendation_config)}")

    weights = recommendation_config[recommendation_goal]["weights"]

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
    difficulty_star_std_multiplier=0.50,
    category_preferences=None,
    top_k=None,
    requested_mods=None,
    excluded_mods=None,
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
    min_cs=None,
    max_cs=None,
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

    Candidate processing:
        1. Keep the best similarity per beatmap.
        2. Load candidate variants.
        3. Apply SQL filters.
        4. Apply the hard star-rating difficulty constraint.
        5. Calculate difficulty scores for eligible candidates.
        6. Calculate recommendation scores.
        7. Keep the best variant per beatmap.
        8. Sort and truncate.
    """
    check_cancelled(cancel_event)
    total_start = time.perf_counter()

    if not similarity_index:
        return []

    config = recommendation_config[recommendation_goal]
    weights = config["weights"]
    classifier_weight = weights["classifier"]
    pp_potential_weight = weights["pp_potential"]

    # ── Player difficulty target ───────────────────────────────
    star_mean = difficulty_profile.get("star_rating_mean")
    star_std = difficulty_profile.get("star_rating_std")

    # if min_stars is explicitly requested, set min_difficulty_stars to it
    if min_stars is not None:
        min_difficulty_stars = float(min_stars)
    elif star_mean is not None and star_std is not None:
        star_mean = float(star_mean)
        star_std = float(star_std)
        min_difficulty_stars = star_mean - difficulty_star_std_multiplier * star_std
    else:
        min_difficulty_stars = None

    # ── Validate filters ───────────────────────────────────────
    filter_ranges = (
        ("min_stars", min_stars, max_stars),
        ("min_bpm", min_bpm, max_bpm),
        ("min_pp", min_pp, max_pp),
        ("min_ar", min_ar, max_ar),
        ("min_od", min_od, max_od),
        ("min_length", min_length, max_length),
        ("min_combo", min_combo, max_combo),
        ("min_cs", min_cs, max_cs),
    )

    for name, minimum, maximum in filter_ranges:
        if minimum is not None and maximum is not None and minimum > maximum:
            raise ValueError(f"{name} ({minimum}) cannot be greater than {name.replace('min_', 'max_')} ({maximum})")

    # ── Collapse similarities ──────────────────────────────────
    start = time.perf_counter()
    candidate_similarity = {}

    for similar_maps in similarity_index.values():
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

    # ── Load candidate variants ────────────────────────────────
    start = time.perf_counter()

    variants = get_candidate_variants(
        conn,
        candidate_similarity.keys(),
        requested_mods=requested_mods,
        excluded_mods=excluded_mods,
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
        min_cs=min_cs,
        max_cs=max_cs,
        cancel_event=cancel_event,
    )

    check_cancelled(cancel_event)
    print(f"[rank_variants] Load candidate variants: {time.perf_counter() - start:.4f}s ({len(variants)} variants)")
    if not variants:
        return []

    # ── Hard star-rating difficulty constraint ──────────────────
    if min_difficulty_stars is not None:
        difficulty_mask = np.array(
            [
                variant["star_rating"] is not None
                and float(variant["star_rating"]) >= min_difficulty_stars
                for variant in variants
            ],
            dtype=bool,
        )
    else:
        difficulty_mask = np.ones(
            len(variants),
            dtype=bool,
        )

    check_cancelled(cancel_event)

    eligible_count = int(difficulty_mask.sum())

    if min_difficulty_stars is not None:
        print(
            f"[rank_variants] Difficulty star floor: "
            f"{min_difficulty_stars:.2f}★ "
            f"(mean={star_mean:.2f}★, "
            f"std={star_std:.2f}, "
            f"multiplier={difficulty_star_std_multiplier:.2f}) "
            f"({eligible_count}/{len(variants)} variants)"
        )
    else:
        print("[rank_variants] Difficulty star floor: disabled (no player star-rating profile)")

    if not difficulty_mask.any():
        print("[rank_variants] No variants passed the difficulty star-rating constraint.")
        return []

    # ── Classifier predictions ─────────────────────────────────
    check_cancelled(cancel_event)
    start = time.perf_counter()
    classifier_predictions = {}

    if classifier_weight > 0 and category_preferences:
        variant_ids = [
            variant["variant_id"]
            for index, variant in enumerate(variants)
            if difficulty_mask[index]
            and variant["mods"] == "NM"
        ]

        if variant_ids:
            classifier_predictions = get_candidate_classifier_predictions(conn, variant_ids)

    check_cancelled(cancel_event)

    print(
        f"[rank_variants] Classifier predictions: "
        f"{time.perf_counter() - start:.4f}s "
        f"({len(classifier_predictions)} predictions)"
    )

    # ── Difficulty scores ──────────────────────────────────────
    start = time.perf_counter()
    difficulty_scores = np.full(
        len(variants),
        0.5,
        dtype=np.float32,
    )

    variant_indices_by_mod = {}

    for index, variant in enumerate(variants):
        if not difficulty_mask[index]:
            continue

        variant_indices_by_mod.setdefault(
            variant["mods"],
            [],
        ).append(index)

    for mods, indices in variant_indices_by_mod.items():
        check_cancelled(cancel_event)

        mod_variants = [
            variants[index]
            for index in indices
        ]

        scores = calculate_difficulty_scores(
            mod_variants,
            difficulty_profile,
            difficulty_std_floors,
            difficulty_feature_weights,
            cancel_event=cancel_event,
        )

        difficulty_scores[indices] = scores

    check_cancelled(cancel_event)

    print(
        f"[rank_variants] Difficulty scores: "
        f"{time.perf_counter() - start:.4f}s "
        f"({eligible_count}/{len(variants)} variants eligible)"
    )

    # ── Score variants ─────────────────────────────────────────
    start = time.perf_counter()
    scored_variants = []

    for index, variant in enumerate(variants):
        if index % 1024 == 0:
            check_cancelled(cancel_event)

        if not difficulty_mask[index]:
            continue

        beatmap_id = variant["beatmap_id"]
        mods = variant["mods"]

        content_similarity = candidate_similarity[beatmap_id]
        mod_preference = mod_preferences.get(mods, 0.0)
        difficulty_score = float(difficulty_scores[index])

        if classifier_weight <= 0:
            classifier_score = 0.5
        elif mods == "NM" and category_preferences:
            probabilities = classifier_predictions.get(variant["variant_id"])
            classifier_score = calculate_classifier_score(probabilities, category_preferences)
        else:
            classifier_score = 0.5

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
        f"({len(scored_variants)} variants)"
    )

    # ── Best variant per beatmap ───────────────────────────────
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

    # ── Sort and truncate ──────────────────────────────────────
    check_cancelled(cancel_event)
    start = time.perf_counter()

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

    print(
        f"[rank_variants] TOTAL: "
        f"{time.perf_counter() - total_start:.4f}s"
    )

    return ranked