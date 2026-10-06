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
from beatmap_recommender.content_similarity.core_modules.mod_preferences import (
    canonicalize_mods,
)
from beatmap_recommender.content_similarity.core_modules.pp_potential import (
    calculate_pp_potential,
    weighted_mean_and_std,
)

MOD_ORDER = ["EZ", "NF", "HT", "HD", "HR", "DT", "NC", "FL"]


def get_player_played_variants(
    conn,
    player_id,
    exclude_recent_plays=False,
    cancel_event=None,
):
    """
    Get the actual beatmap variants represented in the player's scores.

    Score-specific data comes from scores. Variant-specific data comes from beatmap_variants. Mod strings are
    canonicalized before matching so representations such as DTHD and HDDT resolve to the same variant.
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

    # ── Fetch variants (Chunked to respect SQLite parameter limits) ─────────
    variant_rows = []
    chunk_size = 900
    for i in range(0, len(beatmap_ids), chunk_size):
        check_cancelled(cancel_event)
        chunk = beatmap_ids[i : i + chunk_size]
        placeholders = ",".join("?" for _ in chunk)

        rows = conn.execute(
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
            chunk,
        ).fetchall()
        variant_rows.extend(rows)

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
        if not exclude_recent_plays or source in ("top", "top,recent"):
            played_variants.append(
                {
                    **variant,
                    "source": source,
                    "pp": pp,
                    "created_at": created_at,
                }
            )

    check_cancelled(cancel_event)
    return played_variants


def get_player_difficulty_profiles(
    conn,
    player_id,
    recency_half_life_days,
    ability_top_weight,
    ability_recent_weight,
    ability_pp_weight,
    exclude_recent_plays,
    cancel_event=None,
):
    """
    Calculate the player's global difficulty profile.
    The global profile is used by recommendation ranking as the player's overall demonstrated difficulty level.
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

    features = ("star_rating", "ar", "od", "bpm", "pp")

    def build_profile(variants):
        profile = {}

        top_plays = sorted(
            (
                variant
                for variant in variants
                if variant["source"] in ("top", "top,recent")
                and variant.get("pp") is not None
            ),
            key=lambda variant: float(variant["pp"]),
            reverse=True,
        )

        # Highest PP top play in this profile.
        top_pp = float(top_plays[0]["pp"]) if top_plays else 0.0

        for feature in features:
            check_cancelled(cancel_event)

            values = []
            weights = []

            if feature == "pp":
                profile_variants = top_plays
            else:
                profile_variants = variants

            for index, variant in enumerate(profile_variants):
                if index % 1024 == 0:
                    check_cancelled(cancel_event)

                value = variant.get(feature)

                if value is None:
                    continue

                try:
                    value = float(value)
                except (TypeError, ValueError):
                    continue

                if feature == "pp":
                    rank = index + 1

                    # #1 = 1.0, with a strong decay toward lower-ranked top plays.
                    weight = 0.80 ** (rank - 1)

                elif feature == "star_rating":
                    ability_weight = get_ability_score_weight(
                        variant["source"],
                        variant["pp"],
                        variant["created_at"],
                        recency_half_life_days,
                        ability_top_weight,
                        ability_recent_weight,
                        ability_pp_weight,
                    )

                    pp = variant.get("pp")

                    if pp is None or top_pp <= 0:
                        continue

                    # Higher-PP performances give more influence to the player's demonstrated star-rating profile.
                    pp_weight = np.sqrt(float(pp) / top_pp)

                    weight = ability_weight * pp_weight

                else:
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
            if feature == "pp":
                print(
                    f"[difficulty_profile] Global Profile --- PP: mean={mean:.2f}, std={std:.2f}"
                )

            profile[f"{feature}_mean"] = mean
            profile[f"{feature}_std"] = std

        return profile

    global_profile = build_profile(played_variants)
    check_cancelled(cancel_event)
    return global_profile


def get_candidate_variants(
    conn,
    beatmap_ids,
    requested_mods=None,
    exact_mods=False,
    excluded_mods=None,
    min_stars=None,
    max_stars=None,
    difficulty_min_stars=None,
    difficulty_max_stars=None,
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

    beatmap_ids = list(beatmap_ids)
    all_rows = []
    chunk_size = 900

    start_query_time = time.perf_counter()

    columns = [
        "variant_id",
        "beatmap_id",
        "beatmapset_id",
        "mods",
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

    for i in range(0, len(beatmap_ids), chunk_size):
        check_cancelled(cancel_event)
        chunk = beatmap_ids[i : i + chunk_size]
        placeholders = ",".join("?" for _ in chunk)
        params = list(chunk)
        conditions = [f"bv.beatmap_id IN ({placeholders})"]

        # ── Mod filters ────────────────────────────────────────────
        if requested_mods:
            requested_mods_set = {mod.strip().upper() for mod in requested_mods}

            if exact_mods:
                valid_variants = [
                    "".join(mod for mod in MOD_ORDER if mod in requested_mods_set)
                ]

                if not valid_variants[0]:
                    valid_variants = ["NM"]
            else:
                gameplay_mods = [mod for mod in MOD_ORDER if mod in requested_mods_set]

                valid_variants = ["NM"] if "NM" in requested_mods_set else []

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
            (
                "bv.star_rating",
                difficulty_min_stars if difficulty_min_stars is not None else min_stars,
                difficulty_max_stars if difficulty_max_stars is not None else max_stars,
            ),
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

        rows = conn.execute(
            f"""
            SELECT
                bv.variant_id,
                CAST(bv.beatmap_id AS TEXT),
                bv.beatmapset_id,
                bv.mods,
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
            WHERE {" AND ".join(conditions)}
            """,
            params,
        ).fetchall()
        all_rows.extend(rows)

    check_cancelled(cancel_event)
    print(
        f"[get_candidate_variants] SQLite query: {time.perf_counter() - start_query_time:.4f}s ({len(all_rows)} rows)"
    )

    start_conv_time = time.perf_counter()

    variants = [dict(zip(columns, row)) for row in all_rows]

    check_cancelled(cancel_event)
    print(
        f"[get_candidate_variants] Python conversion: {time.perf_counter() - start_conv_time:.4f}s ({len(variants)} variants)"
    )
    return variants


def fetch_beatmap_metadata(conn, beatmap_ids):
    """Fetch beatmap string metadata for final selected candidates."""
    if not beatmap_ids:
        return {}

    metadata = {}
    chunk_size = 900
    beatmap_ids = list(beatmap_ids)

    for i in range(0, len(beatmap_ids), chunk_size):
        chunk = beatmap_ids[i : i + chunk_size]
        placeholders = ",".join("?" for _ in chunk)
        rows = conn.execute(
            f"""
            SELECT CAST(beatmap_id AS TEXT), title, artist, creator, version
            FROM beatmaps
            WHERE beatmap_id IN ({placeholders})
            """,
            chunk,
        ).fetchall()
        for b_id, title, artist, creator, version in rows:
            metadata[b_id] = {
                "title": title,
                "artist": artist,
                "creator": creator,
                "version": version,
            }

    return metadata


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
                float(variant[feature]) if variant.get(feature) is not None else np.nan
                for variant in variants
            ],
            dtype=np.float32,
        )

        check_cancelled(cancel_event)

        z = (values - mean) / std
        valid = np.isfinite(z)
        feature_values.append(np.where(valid, z**2, 0.0))
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
        scores[valid_variants] = np.exp(-0.5 * distance**2)

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
        raise ValueError(
            f"Unknown recommendation goal: {recommendation_goal!r}. Expected one of {sorted(recommendation_config)}"
        )

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
    exact_mods=False,
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
    feature_target_z=None,
    feature_max_z=None,
    cancel_event=None,
):
    """
    Rank variants for all candidate base maps.

    Candidate processing:
        1. Keep the best similarity per beatmap.
        2. Load candidate variants with SQL-level filters.
        3. Calculate difficulty scores.
        4. Calculate recommendation scores.
        5. Keep the best variant per beatmap.
        6. Sort and truncate.
    """
    check_cancelled(cancel_event)
    total_start = time.perf_counter()

    if not similarity_index:
        return []

    config = recommendation_config[recommendation_goal]
    weights = config["weights"]
    classifier_weight = weights["classifier"]
    pp_potential_weight = weights["pp_potential"]

    # Local copies of weights to eliminate dict access overhead inside loop
    w_content = weights["content"]
    w_mod = weights["mod_preference"]
    w_diff = weights["difficulty"]
    w_class = weights["classifier"]
    w_pp = weights["pp_potential"]

    # ── Player difficulty target ───────────────────────────────
    star_mean = difficulty_profile.get("star_rating_mean")
    star_std = difficulty_profile.get("star_rating_std")

    if star_mean is not None and star_std is not None:
        star_mean = float(star_mean)
        star_std = float(star_std)

        min_difficulty_stars = star_mean - difficulty_star_std_multiplier * star_std
        max_difficulty_stars = star_mean + difficulty_star_std_multiplier * star_std

        # Explicit star filters override the automatic difficulty bounds.
        if min_stars is not None:
            min_difficulty_stars = float(min_stars)
            max_difficulty_stars = float("inf")

        if max_stars is not None:
            max_difficulty_stars = float(max_stars)
            min_difficulty_stars = 0.0
    else:
        min_difficulty_stars = float(min_stars) if min_stars is not None else None

        max_difficulty_stars = float(max_stars) if max_stars is not None else None

    # ── PP push range ──────────────────────────────────────────
    pp_mean = difficulty_profile.get("pp_mean")
    pp_std = difficulty_profile.get("pp_std")

    pp_potential_min = None
    pp_potential_max = None

    if (
        pp_mean is not None
        and pp_std is not None
        and pp_push_target_z is not None
        and pp_push_max_z is not None
    ):
        pp_mean = float(pp_mean)
        pp_std = float(pp_std)

        pp_potential_min = pp_mean + pp_push_target_z * pp_std
        pp_potential_max = pp_mean + pp_push_max_z * pp_std

        print(
            f"\n[rank_variants] PP potential range: "
            f"{pp_potential_min:.1f} - {pp_potential_max:.1f} PP "
            f"(z={pp_push_target_z:.2f} to {pp_push_max_z:.2f}, "
            f"mean={pp_mean:.1f}, std={pp_std:.1f})"
        )

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
            raise ValueError(
                f"{name} ({minimum}) cannot be greater than {name.replace('min_', 'max_')} ({maximum})"
            )

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
        f"[rank_variants] Collapse similarities: {time.perf_counter() - start:.4f}s ({len(candidate_similarity)} candidate beatmaps)"
    )

    if not candidate_similarity:
        return []

    # ── Load candidate variants ────────────────────────────────
    start = time.perf_counter()

    variants = get_candidate_variants(
        conn,
        candidate_similarity.keys(),
        requested_mods=requested_mods,
        exact_mods=exact_mods,
        excluded_mods=excluded_mods,
        min_stars=min_stars,
        max_stars=max_stars,
        difficulty_min_stars=min_difficulty_stars,
        difficulty_max_stars=max_difficulty_stars,
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
    print(
        f"[rank_variants] Load candidate variants: {time.perf_counter() - start:.4f}s ({len(variants)} variants)"
    )
    if not variants:
        return []

    # get_candidate_variants() now applies the hard difficulty range directly in SQL, so no Python-side star filtering is necessary.
    eligible_count = len(variants)

    if min_difficulty_stars is not None:
        print(
            f"[rank_variants] Difficulty star range: "
            f"{min_difficulty_stars:.2f}★ - "
            f"{max_difficulty_stars:.2f}★ "
            f"(mean={star_mean:.2f}★, "
            f"std={star_std:.2f}, "
            f"multiplier={difficulty_star_std_multiplier:.2f}) "
            f"({eligible_count} variants)"
        )
    else:
        print(
            "[rank_variants] Difficulty star floor: disabled (no player star-rating profile)"
        )

    # ── Classifier predictions ─────────────────────────────────
    check_cancelled(cancel_event)
    start = time.perf_counter()
    classifier_predictions = {}

    if classifier_weight > 0 and category_preferences:
        # Deduplicate because a beatmap can have multiple candidate variants.
        classifier_beatmap_ids = list({variant["beatmap_id"] for variant in variants})

        classifier_predictions = get_candidate_classifier_predictions(
            conn, classifier_beatmap_ids
        )

    check_cancelled(cancel_event)

    print(
        f"[rank_variants] Classifier predictions: {time.perf_counter() - start:.4f}s ({len(classifier_predictions)} predictions)"
    )

    # ── Difficulty scores ──────────────────────────────────────
    # The current ranker uses the global difficulty profile. Therefore, there is no reason to split variants by mod.
    start = time.perf_counter()
    difficulty_scores = calculate_difficulty_scores(
        variants,
        difficulty_profile,
        difficulty_std_floors,
        difficulty_feature_weights,
        cancel_event=cancel_event,
    )

    check_cancelled(cancel_event)
    print(
        f"[rank_variants] Difficulty scores: {time.perf_counter() - start:.4f}s ({eligible_count} variants)"
    )

    # ── Score variants + keep best per beatmap ─────────────────
    start = time.perf_counter()
    best_by_beatmap = {}
    best_scores = {}

    for index, variant in enumerate(variants):
        if index % 1024 == 0:
            check_cancelled(cancel_event)

        beatmap_id = variant["beatmap_id"]
        mods = variant["mods"]

        content_similarity = candidate_similarity[beatmap_id]
        mod_preference = mod_preferences.get(mods, 0.0)
        difficulty_score = float(difficulty_scores[index])

        if category_preferences:
            probabilities = classifier_predictions.get(beatmap_id)
            classifier_score = calculate_classifier_score(
                probabilities, category_preferences
            )
        else:
            classifier_score = 0.0

        if pp_potential_weight > 0:
            pp_potential = calculate_pp_potential(
                variant,
                difficulty_profile,
                difficulty_std_floors,
                difficulty_feature_weights,
                pp_push_target_z,
                pp_push_max_z,
                feature_target_z,
                feature_max_z,
                pp_min=pp_potential_min,
                pp_max=pp_potential_max,
            )
        else:
            pp_potential = 0.0

        final_score = (
            w_content * content_similarity
            + w_mod * mod_preference
            + w_diff * difficulty_score
            + w_class * classifier_score
            + w_pp * pp_potential
        )

        # Avoid creating an intermediate scored_variants list or dict unpacking until a beatmap is replaced.
        previous_score = best_scores.get(beatmap_id)
        if previous_score is None or final_score > previous_score:
            best_scores[beatmap_id] = final_score
            best_by_beatmap[beatmap_id] = (
                variant,
                content_similarity,
                mod_preference,
                difficulty_score,
                classifier_score,
                pp_potential,
                final_score,
            )

    check_cancelled(cancel_event)

    print(
        f"[rank_variants] Score + best variant selection: "
        f"{time.perf_counter() - start:.4f}s "
        f"({eligible_count} variants -> "
        f"{len(best_by_beatmap)} beatmaps)"
    )

    # ── Sort and truncate ──────────────────────────────────────
    check_cancelled(cancel_event)
    start = time.perf_counter()

    # Reconstruct dict items for remaining deduplicated candidates
    ranked_candidates = []
    for (
        variant,
        content_similarity,
        mod_preference,
        difficulty_score,
        classifier_score,
        pp_potential,
        final_score,
    ) in best_by_beatmap.values():
        ranked_candidates.append(
            {
                **variant,
                "content_similarity": content_similarity,
                "mod_preference": mod_preference,
                "difficulty_score": difficulty_score,
                "classifier_score": classifier_score,
                "pp_potential": pp_potential,
                "final_score": final_score,
            }
        )

    sort_keys = config["sort_keys"]

    ranked_candidates.sort(
        key=lambda variant: tuple(variant[key] for key in sort_keys),
        reverse=True,
    )

    check_cancelled(cancel_event)

    if top_k is not None:
        ranked_candidates = ranked_candidates[:top_k]

    # Fetch beatmap string metadata only for top_k maps
    winning_beatmap_ids = [v["beatmap_id"] for v in ranked_candidates]
    metadata_map = fetch_beatmap_metadata(conn, winning_beatmap_ids)

    ranked = []
    for variant in ranked_candidates:
        b_meta = metadata_map.get(variant["beatmap_id"], {})
        ranked.append(
            {
                **variant,
                "title": b_meta.get("title"),
                "artist": b_meta.get("artist"),
                "creator": b_meta.get("creator"),
                "version": b_meta.get("version"),
            }
        )

    print(
        f"[rank_variants] Sort and truncate: {time.perf_counter() - start:.4f}s ({len(ranked)} results)"
    )
    print(f"[rank_variants] TOTAL: {time.perf_counter() - total_start:.4f}s")
    return ranked
