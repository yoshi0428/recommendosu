import logging
import time

import numpy as np

from beatmap_recommender.cancellation import check_cancelled
from beatmap_recommender.content_similarity.core_modules.ability import (
    get_ability_score_weight,
)
from beatmap_recommender.content_similarity.core_modules.cnn_xgboost_influence import (
    calculate_classifier_scores,
)
from beatmap_recommender.content_similarity.core_modules.mod_preferences import (
    canonicalize_mods,
)
from beatmap_recommender.content_similarity.core_modules.pp_potential import (
    calculate_pp_potentials,
    weighted_mean_and_std,
)
from beatmap_recommender.content_similarity.core_modules.variant_table import (
    TEXT_COLUMNS,
    VARIANT_COLUMNS,
    VariantRows,
    get_variant_table,
    sql_like,
)

logger = logging.getLogger(__name__)

MOD_ORDER = ["EZ", "NF", "HT", "HD", "HR", "DT", "NC", "FL"]

# Per-variant scores stored alongside each variant in rank_variants().
SCORE_FIELDS = (
    "content_similarity",
    "mod_preference",
    "difficulty_score",
    "classifier_score",
    "pp_potential",
    "final_score",
)


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
        return {}

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
                logger.info("Global profile PP: mean=%.2f, std=%.2f", mean, std)

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
    beatmap_status="all",
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
    min_year=None,
    max_year=None,
    cancel_event=None,
):
    """
    Select candidate variants and apply the request's filters.

    Returns a VariantRows in table (rowid) order. The filters behave like the
    SQL they replace: NULLs never match, and excluded mods use LIKE '%mod%'.
    """
    if not beatmap_ids:
        return []

    start = time.perf_counter()
    table = get_variant_table(conn)
    check_cancelled(cancel_event)

    allowed_beatmaps = np.zeros(len(table.categories["beatmap_id"]), dtype=bool)
    allowed_beatmaps[table.codes_of("beatmap_id", beatmap_ids)] = True
    mask = allowed_beatmaps[table.columns["beatmap_id"]]

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

            for bits in range(1, 1 << len(gameplay_mods)):
                combination = [
                    gameplay_mods[index]
                    for index in range(len(gameplay_mods))
                    if bits & (1 << index)
                ]
                valid_variants.append("".join(combination))

        valid_variants = set(valid_variants)
    else:
        valid_variants = None

    excluded_mods = list(excluded_mods or [])

    def mods_allowed(mods):
        if mods is None:
            return False

        if valid_variants is not None and mods not in valid_variants:
            return False

        for mod in excluded_mods:
            if mod == "NM" and mods == "NM":
                return False

            if mod != "NM" and sql_like(f"%{mod}%", mods):
                return False

        return True

    if valid_variants is not None or excluded_mods:
        mask &= table.category_mask("mods", mods_allowed)[table.columns["mods"]]

    # ── Status filter ──────────────────────────────────────────
    if beatmap_status != "all":
        mask &= table.category_mask("status", lambda status: status == beatmap_status)[
            table.columns["status"]
        ]

    # ── Numeric filters ────────────────────────────────────────
    numeric_filters = (
        (
            "star_rating",
            difficulty_min_stars if difficulty_min_stars is not None else min_stars,
            difficulty_max_stars if difficulty_max_stars is not None else max_stars,
        ),
        ("bpm", min_bpm, max_bpm),
        ("pp", min_pp, max_pp),
        ("ar", min_ar, max_ar),
        ("od", min_od, max_od),
        ("length_seconds", min_length, max_length),
        ("max_combo", min_combo, max_combo),
        ("circle_size", min_cs, max_cs),
        ("year", min_year, max_year),
    )

    for column, minimum, maximum in numeric_filters:
        values = table.float_columns[column]

        if minimum is not None:
            mask &= values >= minimum

        if maximum is not None:
            mask &= values <= maximum

    check_cancelled(cancel_event)
    variants = VariantRows(table, np.flatnonzero(mask))
    logger.info("Candidate filters: %.4fs (%d variants)", time.perf_counter() - start, len(variants))
    return variants


def _feature_values(variants, feature):
    """One feature of every variant as float32, NaN where it's missing."""
    if isinstance(variants, VariantRows):
        return variants.float_column(feature).astype(np.float32)

    return np.asarray(
        [
            float(variant[feature]) if variant.get(feature) is not None else np.nan
            for variant in variants
        ],
        dtype=np.float32,
    )


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

        values = _feature_values(variants, feature)

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
        raise ValueError(f"Unknown recommendation goal: {recommendation_goal!r}. Expected one of {sorted(recommendation_config)}")

    weights = recommendation_config[recommendation_goal]["weights"]

    return (
        weights["content"] * content_similarity
        + weights["mod_preference"] * mod_preference
        + weights["difficulty"] * difficulty_score
        + weights["classifier"] * classifier_score
        + weights["pp_potential"] * pp_potential
    )


def _descending_order(sort_arrays):
    """
    Row order for sorted(..., key=sort_keys, reverse=True), where
    sort_arrays[0] is the primary key.

    Same order as np.lexsort([-array for array in reversed(sort_arrays)]),
    but sorts the primary key alone and only lexsorts the rows that tie on
    it: a lexsort makes one full pass per key, and ties are rare.
    """
    keys = [-array for array in sort_arrays]
    order = np.argsort(keys[0], kind="stable")

    if len(keys) == 1 or len(order) < 2:
        return order

    primary = keys[0][order]
    # NaN sorts last, and NaNs tie with each other, like in a lexsort.
    tied = (primary[1:] == primary[:-1]) | (np.isnan(primary[1:]) & np.isnan(primary[:-1]))

    if not tied.any():
        return order

    # Positions in `order` that belong to a run of equal primary keys,
    # labelled by run, then sorted by run and the remaining keys. The
    # lexsort is stable, so rows still tied keep their original order.
    in_run = np.zeros(len(order), dtype=bool)
    in_run[1:] |= tied
    in_run[:-1] |= tied
    run_ids = np.cumsum(np.concatenate(([True], ~tied)))[in_run]
    positions = np.flatnonzero(in_run)
    rows = order[positions]

    run_order = np.lexsort([key[rows] for key in reversed(keys[1:])] + [run_ids])
    order[positions] = rows[run_order]
    return order


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
    beatmap_status="all",
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
    min_year=None,
    max_year=None,
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

    similarity_index maps candidate beatmap_id -> best content similarity.

    Candidate processing:
        1. Load candidate variants with SQL-level filters.
        2. Calculate difficulty scores.
        3. Calculate recommendation scores.
        4. Sort and truncate (every variant is kept, so a beatmap can
           appear once per mod variant).
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
        # A one-sided filter leaves the other side open.
        if min_stars is not None or max_stars is not None:
            min_difficulty_stars = float(min_stars) if min_stars is not None else 0.0
            max_difficulty_stars = float(max_stars) if max_stars is not None else float("inf")

        # A min_pp without star filters on the balanced goal means the player
        # is trying to push, so the automatic star ceiling would hide exactly
        # the maps they're asking for. Lift it and keep the lower bound.
        other_filters = (min_stars, max_stars)

        if (
            recommendation_goal == "balanced"
            and min_pp is not None
            and all(value is None for value in other_filters)
        ):
            max_difficulty_stars = float("inf")
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

        logger.info(
            "PP potential range: %.1f - %.1f PP (z=%.2f to %.2f, mean=%.1f, std=%.1f)",
            pp_potential_min,
            pp_potential_max,
            pp_push_target_z,
            pp_push_max_z,
            pp_mean,
            pp_std,
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
        ("min_year", min_year, max_year),
    )

    for name, minimum, maximum in filter_ranges:
        if minimum is not None and maximum is not None and minimum > maximum:
            raise ValueError(f"{name} ({minimum}) cannot be greater than {name.replace('min_', 'max_')} ({maximum})")

    # Goals with pp_push_filter only keep maps inside the PP push range,
    # narrowed further by any explicit pp filters. Applied after validation
    # so a user's own min_pp/max_pp are still checked against each other.
    if config.get("pp_push_filter") and pp_potential_min is not None:
        min_pp = pp_potential_min if min_pp is None else max(float(min_pp), pp_potential_min)
        max_pp = pp_potential_max if max_pp is None else min(float(max_pp), pp_potential_max)

        logger.info("PP push filter: %.1f - %.1f PP", min_pp, max_pp)

        if min_pp > max_pp:
            return []

    # build_seed_similarity_index() already keeps the best similarity per beatmap.
    candidate_similarity = similarity_index

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
        beatmap_status=beatmap_status,
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
        min_year=min_year,
        max_year=max_year,
        cancel_event=cancel_event,
    )

    check_cancelled(cancel_event)
    logger.info("Load candidate variants: %.4fs (%d variants)", time.perf_counter() - start, len(variants))
    if not variants:
        return []

    # get_candidate_variants() already applies the hard difficulty range, so no further star filtering is necessary.
    eligible_count = len(variants)

    if min_difficulty_stars is not None:
        logger.info(
            "Difficulty star range: %.2f★ - %.2f★ (mean=%.2f★, std=%.2f, multiplier=%.2f) (%d variants)",
            min_difficulty_stars,
            max_difficulty_stars,
            star_mean,
            star_std,
            difficulty_star_std_multiplier,
            eligible_count,
        )
    else:
        logger.info("Difficulty star floor: disabled (no player star-rating profile)")

    # ── Classifier predictions ─────────────────────────────────
    check_cancelled(cancel_event)
    start = time.perf_counter()
    table = variants.table
    beatmap_codes = variants.codes("beatmap_id")
    # Per beatmap_id code; beatmaps without a prediction score 0.0.
    beatmap_classifier_scores = np.zeros(len(table.categories["beatmap_id"]))
    prediction_count = 0

    if classifier_weight > 0 and category_preferences:
        # The classifier score only depends on the beatmap, so calculate it
        # once per beatmap instead of once per mod variant.
        beatmap_classifier_scores = np.where(
            table.has_nm_prediction,
            calculate_classifier_scores(table.nm_predictions, category_preferences),
            0.0,
        )
        prediction_count = int(table.has_nm_prediction[np.unique(beatmap_codes)].sum())

    check_cancelled(cancel_event)

    logger.info("Classifier predictions: %.4fs (%d predictions)", time.perf_counter() - start, prediction_count)

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
    logger.info("Difficulty scores: %.4fs (%d variants)", time.perf_counter() - start, eligible_count)

    # ── Score variants ─────────────────────────────────────────
    # Scores are numpy arrays rather than per-variant Python floats, since
    # the worst case (no star bounds, every mod) scores ~3 million variants.
    # Per-beatmap and per-mods values are looked up once per distinct value,
    # then spread to the variants through their codes.
    start = time.perf_counter()
    categories = table.categories

    content_scores = np.array(
        [candidate_similarity.get(beatmap_id, np.nan) for beatmap_id in categories["beatmap_id"]],
        dtype=np.float64,
    )[beatmap_codes]
    mod_scores = np.array(
        [mod_preferences.get(mods, 0.0) for mods in categories["mods"]],
        dtype=np.float64,
    )[variants.codes("mods")]
    difficulty_scores = difficulty_scores.astype(np.float64)

    check_cancelled(cancel_event)

    if category_preferences:
        classifier_scores = beatmap_classifier_scores[beatmap_codes]
    else:
        classifier_scores = np.zeros(eligible_count)

    check_cancelled(cancel_event)

    pp_potential_scores = np.zeros(eligible_count)

    if pp_potential_weight > 0:
        # Only the columns a variant dict has, as calculate_pp_potential() sees them.
        pp_columns = {
            name: variants.float_column(name)
            for name in ("pp", *difficulty_feature_weights)
            if name in VARIANT_COLUMNS and name not in TEXT_COLUMNS
        }
        pp_potential_scores = calculate_pp_potentials(
            pp_columns,
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

    # Same left-to-right float64 arithmetic as score_variant().
    final_scores = (
        w_content * content_scores
        + w_mod * mod_scores
        + w_diff * difficulty_scores
        + w_class * classifier_scores
        + w_pp * pp_potential_scores
    )

    check_cancelled(cancel_event)

    logger.info("Score variants: %.4fs (%d variants)", time.perf_counter() - start, eligible_count)

    # ── Sort and truncate ──────────────────────────────────────
    check_cancelled(cancel_event)
    start = time.perf_counter()

    score_arrays = dict(
        zip(
            SCORE_FIELDS,
            (
                content_scores,
                mod_scores,
                difficulty_scores,
                classifier_scores,
                pp_potential_scores,
                final_scores,
            ),
        )
    )

    sort_arrays = [
        score_arrays[key]
        if key in score_arrays
        else variants.float_column(key)
        for key in config["sort_keys"]
    ]

    order = _descending_order(sort_arrays)

    if top_k is not None:
        order = order[:top_k]

    check_cancelled(cancel_event)

    # Rows only become dicts (variant columns, then SCORE_FIELDS, then
    # title/artist/creator/version) when a page of them is read.
    winners = VariantRows(
        variants.table,
        variants.rows[order],
        extra_columns={field: score_arrays[field][order] for field in SCORE_FIELDS},
        with_metadata=True,
    )

    logger.info("Sort and truncate: %.4fs (%d results)", time.perf_counter() - start, len(winners))
    logger.info("TOTAL: %.4fs", time.perf_counter() - total_start)
    return winners
