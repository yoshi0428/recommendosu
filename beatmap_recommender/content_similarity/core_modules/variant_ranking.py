import logging
import time

import numpy as np

from beatmap_recommender.cancellation import check_cancelled
from beatmap_recommender.content_similarity.core_modules.ability import (
    get_ability_score_weight,
    weighted_mean_and_std,
)
from beatmap_recommender.content_similarity.core_modules.classifier_influence import (
    calculate_classifier_scores,
)
from beatmap_recommender.content_similarity.core_modules.mod_preferences import (
    canonicalize_mods,
    parse_mod_string,
)
from beatmap_recommender.content_similarity.core_modules.variant_table import (
    VariantRows,
    get_variant_table,
    sql_like,
)

logger = logging.getLogger(__name__)

# The range filters: the name of each filter (min_<name>/max_<name> in
# RecommendationSettings, for example "min_bpm") and the variant column that it filters.
RANGE_COLUMNS = {
    "stars": "star_rating",
    "bpm": "bpm",
    "pp": "pp",
    "ar": "ar",
    "od": "od",
    "length": "length_seconds",
    "combo": "max_combo",
    "cs": "circle_size",
    "year": "year",
}

# The scores that rank_variants() stores with each variant.
SCORE_FIELDS = (
    "content_similarity",
    "mod_preference",
    "difficulty_score",
    "classifier_score",
    "final_score",
)


def get_player_played_variants(
    conn,
    player_id,
    exclude_recent_plays=False,
    cancel_event=None,
):
    """
    Return the beatmap variants that the scores of the player are on.

    The score data comes from scores. The variant data comes from
    beatmap_variants. The code makes the mod strings canonical before it
    matches them. Thus DTHD and HDDT find the same variant.
    """
    check_cancelled(cancel_event)

    # ── Fetch scores ────────────────────────────────────────────
    score_rows = conn.execute(
        """
        SELECT beatmap_id, mods, source, pp, created_at
        FROM scores
        WHERE player_id = ?
          -- A failed play (rank F) does not show what the player can do.
          AND COALESCE(rank, '') != 'F'
        """,
        (player_id,),
    ).fetchall()

    check_cancelled(cancel_event)
    if not score_rows:
        return []

    beatmap_ids = sorted({str(row[0]) for row in score_rows})
    check_cancelled(cancel_event)

    # ── Fetch variants, in chunks below the SQLite parameter limit ──────────
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

    for variant_id, beatmap_id, mods, star_rating, ar, od, bpm in variant_rows:
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

        # Keep all scores. If exclude_recent_plays is set, keep only the top plays.
        if not exclude_recent_plays or source in ("top", "top,recent"):
            played_variants.append({**variant, "source": source, "pp": pp, "created_at": created_at})

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
    Return the global difficulty profile of the player: the weighted mean and
    std of each feature. The ranking uses it as the overall difficulty level
    that the player showed.
    """
    check_cancelled(cancel_event)

    variants = get_player_played_variants(
        conn,
        player_id,
        exclude_recent_plays=exclude_recent_plays,
        cancel_event=cancel_event,
    )

    check_cancelled(cancel_event)

    if not variants:
        return {}

    profile = {}

    top_plays = sorted(
        (
            variant
            for variant in variants
            if variant["source"] in ("top", "top,recent") and variant.get("pp") is not None
        ),
        key=lambda variant: float(variant["pp"]),
        reverse=True,
    )

    # The highest pp of the top plays.
    top_pp = float(top_plays[0]["pp"]) if top_plays else 0.0

    for feature in ("star_rating", "ar", "od", "bpm", "pp"):
        check_cancelled(cancel_event)

        values = []
        weights = []

        for index, variant in enumerate(top_plays if feature == "pp" else variants):
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
                # The #1 top play gets 1.0. The weight falls fast for lower top plays.
                weight = 0.80**index
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

                if feature == "star_rating":
                    pp = variant.get("pp")

                    if pp is None or top_pp <= 0:
                        continue

                    # A play with more pp has more effect on the star rating profile.
                    weight = weight * np.sqrt(float(pp) / top_pp)

            values.append(value)
            weights.append(weight)

        if not values:
            continue

        mean, std = weighted_mean_and_std(values, weights)
        if feature == "pp":
            logger.info("Global profile PP: mean=%.2f, std=%.2f", mean, std)

        profile[f"{feature}_mean"] = mean
        profile[f"{feature}_std"] = std

    check_cancelled(cancel_event)
    return profile


def get_candidate_variants(
    conn,
    beatmap_ids,
    requested_mods=None,
    exact_mods=False,
    excluded_mods=None,
    beatmap_status="all",
    ranges=None,
    cancel_event=None,
):
    """
    Select the candidate variants and apply the filters of the request.

    Return a VariantRows in table (rowid) order. The filters work like the SQL
    that they replaced: a NULL never matches, and an excluded mod uses
    LIKE '%mod%'.

    requested_mods: the mods to recommend, in uppercase. A variant matches if
    all its mods are requested (NM only if "NM" is requested). With
    exact_mods, its mods must be exactly the requested mods.

    ranges: {name: (minimum, maximum)} for names in RANGE_COLUMNS. A bound of
    None means no limit.
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
    requested = set(requested_mods or ())
    gameplay_requested = requested - {"NM"}

    def mods_requested(mods):
        variant_mods = set() if mods == "NM" else set(parse_mod_string(mods))

        if exact_mods:
            return variant_mods == gameplay_requested

        return "NM" in requested if mods == "NM" else variant_mods <= gameplay_requested

    excluded_mods = list(excluded_mods or [])

    def mods_allowed(mods):
        if mods is None:
            return False

        if requested and not mods_requested(mods):
            return False

        for mod in excluded_mods:
            if mod == "NM" and mods == "NM":
                return False

            if mod != "NM" and sql_like(f"%{mod}%", mods):
                return False

        return True

    if requested or excluded_mods:
        mask &= table.category_mask("mods", mods_allowed)[table.columns["mods"]]

    # ── Status filter ──────────────────────────────────────────
    if beatmap_status != "all":
        mask &= table.category_mask("status", lambda status: status == beatmap_status)[
            table.columns["status"]
        ]

    # ── Range filters ──────────────────────────────────────────
    for name, (minimum, maximum) in (ranges or {}).items():
        values = table.float_columns[RANGE_COLUMNS[name]]

        if minimum is not None:
            mask &= values >= minimum

        if maximum is not None:
            mask &= values <= maximum

    check_cancelled(cancel_event)
    variants = VariantRows(table, np.flatnonzero(mask))
    logger.info("Candidate filters: %.4fs (%d variants)", time.perf_counter() - start, len(variants))
    return variants


def _feature_values(variants, feature):
    """Return one feature of all the variants as float32, with NaN where the value is missing."""
    if isinstance(variants, VariantRows):
        return variants.float_column(feature).astype(np.float32)

    return np.asarray(
        [float(variant[feature]) if variant.get(feature) is not None else np.nan for variant in variants],
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
    Return how closely each variant matches the difficulty of the player.

    The ranking uses this score after the hard star rating limit removed the
    other candidates.

    The scores are approximately in [0, 1]:
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

    scores = np.full(len(variants), 0.5, dtype=np.float32)

    if np.any(valid_variants):
        distance = np.sqrt(weighted_squared_distance[valid_variants].sum(axis=1) / total_weight[valid_variants])
        scores[valid_variants] = np.exp(-0.5 * distance**2)

    check_cancelled(cancel_event)
    return scores


def _descending_order(sort_arrays):
    """
    Return the row order of sorted(..., key=sort_keys, reverse=True), where
    sort_arrays[0] is the primary key.

    The order is the same as np.lexsort([-array for array in reversed(sort_arrays)]).
    But this function sorts by the primary key alone, then does a lexsort only
    on the rows that tie on it. A lexsort makes one full pass for each key,
    and ties are rare.
    """
    keys = [-array for array in sort_arrays]
    order = np.argsort(keys[0], kind="stable")

    if len(keys) == 1 or len(order) < 2:
        return order

    primary = keys[0][order]
    # NaN sorts last, and two NaNs tie, as in a lexsort.
    tied = (primary[1:] == primary[:-1]) | (np.isnan(primary[1:]) & np.isnan(primary[:-1]))

    if not tied.any():
        return order

    # Find the positions in `order` that are in a run of equal primary keys,
    # and label each run. Then sort by run and by the other keys. The lexsort
    # is stable, so the rows that still tie keep their original order.
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
    ranges=None,
    recommendation_config=None,
    difficulty_std_floors=None,
    difficulty_feature_weights=None,
    cancel_event=None,
):
    """
    Rank the variants of all the candidate beatmaps.

    similarity_index maps candidate beatmap_id -> best content similarity.

    The steps:
        1. Load the candidate variants and apply the filters.
        2. Calculate the difficulty scores.
        3. Calculate the recommendation scores.
        4. Sort, and keep the first top_k. All variants stay, so a beatmap
           can show one time for each mod variant.
    """
    check_cancelled(cancel_event)
    total_start = time.perf_counter()

    if not similarity_index:
        return []

    config = recommendation_config
    weights = config["weights"]
    w_content = weights["content"]
    w_mod = weights["mod_preference"]
    w_diff = weights["difficulty"]
    w_class = weights["classifier"]

    ranges = dict(ranges or {})
    min_stars, max_stars = ranges.get("stars", (None, None))
    min_pp, max_pp = ranges.get("pp", (None, None))

    # ── Player difficulty target ───────────────────────────────
    star_mean = difficulty_profile.get("star_rating_mean")
    star_std = difficulty_profile.get("star_rating_std")

    if star_mean is not None and star_std is not None:
        star_mean = float(star_mean)
        star_std = float(star_std)

        min_difficulty_stars = star_mean - difficulty_star_std_multiplier * star_std
        max_difficulty_stars = star_mean + difficulty_star_std_multiplier * star_std

        # Star filters from the user replace the automatic difficulty limits.
        # A filter with one side only leaves the other side open.
        if min_stars is not None or max_stars is not None:
            min_difficulty_stars = float(min_stars) if min_stars is not None else 0.0
            max_difficulty_stars = float(max_stars) if max_stars is not None else float("inf")

        # A min_pp without star filters means that the player wants harder
        # maps. The automatic star maximum would hide exactly those maps. Thus
        # remove the maximum, and keep the minimum.
        if min_pp is not None and min_stars is None and max_stars is None:
            max_difficulty_stars = float("inf")
    else:
        min_difficulty_stars = float(min_stars) if min_stars is not None else None
        max_difficulty_stars = float(max_stars) if max_stars is not None else None

    # ── Validate filters ───────────────────────────────────────
    for name, (minimum, maximum) in ranges.items():
        if minimum is not None and maximum is not None and minimum > maximum:
            raise ValueError(f"min_{name} ({minimum}) cannot be greater than max_{name} ({maximum})")

    # ── Load candidate variants ────────────────────────────────
    start = time.perf_counter()

    variants = get_candidate_variants(
        conn,
        similarity_index.keys(),
        requested_mods=requested_mods,
        exact_mods=exact_mods,
        excluded_mods=excluded_mods,
        beatmap_status=beatmap_status,
        # The difficulty window, or the star filters of the user, which replace it.
        ranges={**ranges, "stars": (min_difficulty_stars, max_difficulty_stars)},
        cancel_event=cancel_event,
    )

    check_cancelled(cancel_event)
    logger.info("Load candidate variants: %.4fs (%d variants)", time.perf_counter() - start, len(variants))
    if not variants:
        return []

    # get_candidate_variants() applied the hard difficulty range, so no more star filter is necessary.
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
    # Indexed by beatmap_id code. A beatmap without a prediction gets 0.0.
    beatmap_classifier_scores = np.zeros(len(table.categories["beatmap_id"]))
    prediction_count = 0

    if w_class > 0 and category_preferences:
        # The classifier score depends only on the beatmap. Thus calculate it
        # one time for each beatmap, not for each mod variant.
        beatmap_classifier_scores = np.where(
            table.has_nm_prediction,
            calculate_classifier_scores(table.nm_predictions, category_preferences),
            0.0,
        )
        prediction_count = int(table.has_nm_prediction[np.unique(beatmap_codes)].sum())

    check_cancelled(cancel_event)

    logger.info("Classifier predictions: %.4fs (%d predictions)", time.perf_counter() - start, prediction_count)

    # ── Difficulty scores ──────────────────────────────────────
    # The ranker uses the global difficulty profile, so it does not split the variants by mod.
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
    # The scores are numpy arrays, not Python floats for each variant, because
    # the worst case (no star limits, all mods) scores about 3 million variants.
    # The code finds each beatmap value and each mods value one time for each
    # distinct value. Then the codes copy the values to the variants.
    start = time.perf_counter()
    categories = table.categories

    content_scores = np.array(
        [similarity_index.get(beatmap_id, np.nan) for beatmap_id in categories["beatmap_id"]],
        dtype=np.float64,
    )[beatmap_codes]
    mod_scores = np.array(
        [mod_preferences.get(mods, 0.0) for mods in categories["mods"]],
        dtype=np.float64,
    )[variants.codes("mods")]
    difficulty_scores = difficulty_scores.astype(np.float64)
    # All zeros if there are no category preferences or the classifier weight is 0.
    classifier_scores = beatmap_classifier_scores[beatmap_codes]

    check_cancelled(cancel_event)

    # The weighted sum of the scores, added left to right.
    final_scores = (
        w_content * content_scores
        + w_mod * mod_scores
        + w_diff * difficulty_scores
        + w_class * classifier_scores
    )

    check_cancelled(cancel_event)

    logger.info("Score variants: %.4fs (%d variants)", time.perf_counter() - start, eligible_count)

    # ── Sort and truncate ──────────────────────────────────────
    start = time.perf_counter()

    score_arrays = dict(
        zip(SCORE_FIELDS, (content_scores, mod_scores, difficulty_scores, classifier_scores, final_scores))
    )
    sort_arrays = [
        score_arrays[key] if key in score_arrays else variants.float_column(key) for key in config["sort_keys"]
    ]

    order = _descending_order(sort_arrays)

    if top_k is not None:
        order = order[:top_k]

    check_cancelled(cancel_event)

    # The rows become dicts (variant columns, then SCORE_FIELDS, then
    # title/artist/creator/version) only when the code reads a page of them.
    winners = VariantRows(
        variants.table,
        variants.rows[order],
        extra_columns={field: score_arrays[field][order] for field in SCORE_FIELDS},
        with_metadata=True,
    )

    logger.info("Sort and truncate: %.4fs (%d results)", time.perf_counter() - start, len(winners))
    logger.info("TOTAL: %.4fs", time.perf_counter() - total_start)
    return winners
