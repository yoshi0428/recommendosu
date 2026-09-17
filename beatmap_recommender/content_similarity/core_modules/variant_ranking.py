import numpy as np
from beatmap_recommender.content_similarity.core_modules.ability import get_ability_score_weight
from beatmap_recommender.content_similarity.core_modules.cnn_xgboost_influence import calculate_classifier_score, get_candidate_classifier_predictions
from .pp_potential import weighted_mean_and_std, calculate_pp_potential
from .mod_preferences import canonicalize_mods

def get_player_played_variants(conn, player_id):
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

    if not score_rows:
        return []

    # ------------------------------------------------------------------
    # Get all beatmap IDs represented in the player's scores.
    # ------------------------------------------------------------------
    beatmap_ids = sorted({
        str(row[0])
        for row in score_rows
    })

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

    return played_variants

def get_player_difficulty_profile(conn, player_id, difficulty_std_floors, recency_half_life_days, ability_top_weight, ability_recent_weight, ability_pp_weight):
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

    played_variants = get_player_played_variants(conn, player_id)

    if not played_variants:
        return {}

    features = [
        "star_rating",
        "ar",
        "od",
        "bpm",
    ]

    profile = {}
    for feature in features:

        values = []
        weights = []
        for variant in played_variants:

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

        if not values:
            continue

        mean, std = weighted_mean_and_std(values, weights)
        std = max(std, difficulty_std_floors[feature])
        profile[f"{feature}_mean"] = mean
        profile[f"{feature}_std"] = std

    return profile

def get_candidate_variants(conn, beatmap_ids, requested_mods=None):
    """
    Fetch all variants belonging to the supplied base beatmaps.

    Also loads base beatmap metadata:
        title
        artist
        creator
        version

    Returns a list of dictionaries.

    Mod strings are canonicalized when loaded so that, for example:

        DTHD -> HDDT
        HRDT -> HRDT
        HDHR -> HDHR
    """
    if not beatmap_ids:
        return []

    placeholders = ",".join("?" for _ in beatmap_ids)
    params = list(beatmap_ids)

    mods_clause = ""
    if requested_mods is not None:
        requested_mods = canonicalize_mods(requested_mods)
        mods_clause = "AND bv.mods = ?"
        params.append(requested_mods)

    rows = conn.execute(
        f"""
        SELECT
            bv.variant_id,
            bv.beatmap_id,
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
            bv.min_bpm,
            bv.max_bpm,
            bv.length_seconds,
            bv.object_count,
            bv.pp,
            bv.pp_aim,
            bv.pp_speed,
            bv.pp_acc,
            bv.pp_flashlight

        FROM beatmap_variants bv
        JOIN beatmaps b
            ON b.beatmap_id = bv.beatmap_id

        WHERE bv.beatmap_id IN ({placeholders})
          {mods_clause}
        """,
        params,
    ).fetchall()

    columns = [
        "variant_id",
        "beatmap_id",
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
        "min_bpm",
        "max_bpm",
        "length_seconds",
        "object_count",
        "pp",
        "pp_aim",
        "pp_speed",
        "pp_acc",
        "pp_flashlight",
    ]

    variants = []

    for row in rows:
        variant = dict(zip(columns, row))
        variant["beatmap_id"] = str(variant["beatmap_id"])
        variant["mods"] = canonicalize_mods(variant["mods"])
        variants.append(variant)

    return variants

def calculate_difficulty_score(variant, difficulty_profile, difficulty_std_floors, difficulty_feature_weights):
    """
    Calculate how well a variant's difficulty matches the player's current difficulty profile.

    Returns approximately [0, 1]:

        1.0 = very close to player's typical difficulty
        0.5 = moderate difference
        0.0 = very far from player's typical difficulty

    Star rating receives the strongest weight.
    """

    if not difficulty_profile:
        return 0.5

    weighted_squared_distance = 0.0
    total_weight = 0.0

    for feature, feature_weight in difficulty_feature_weights.items():

        value = variant.get(feature)
        if value is None:
            continue

        mean = difficulty_profile.get(f"{feature}_mean")
        std = difficulty_profile.get(f"{feature}_std")
        if mean is None or std is None:
            continue

        try:
            value = float(value)
            mean = float(mean)
            std = float(std)
        except (TypeError, ValueError):
            continue

        if std <= 0:
            std = difficulty_std_floors[feature]

        z = (value - mean) / std
        weighted_squared_distance += (feature_weight * z ** 2)
        total_weight += feature_weight

    if total_weight <= 0:
        return 0.5

    distance = np.sqrt(weighted_squared_distance / total_weight)

    # Gaussian-like falloff.
    # distance = 0 -> 1.0
    # distance = 1 -> ~0.61
    # distance = 2 -> ~0.14
    # distance = 3 -> ~0.01
    score = np.exp(-0.5 * distance ** 2)
    return float(score)

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
    recommendation_goal="balanced",
    recommendation_config=None,
    difficulty_std_floors=None,
    difficulty_feature_weights=None,
    pp_push_target_z=None,
    pp_push_max_z=None,
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
    if not similarity_index:
        return []

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

    # ------------------------------------------------------------------
    # Collapse seed -> candidates into:
    # beatmap_id -> best similarity
    # ------------------------------------------------------------------
    candidate_similarity = {}
    for seed_beatmap_id, similar_maps in similarity_index.items():
        for beatmap_id, similarity in similar_maps:
            beatmap_id = str(beatmap_id)
            similarity = float(similarity)
            previous = candidate_similarity.get(beatmap_id)

            if previous is None or similarity > previous:
                candidate_similarity[beatmap_id] = similarity

    if not candidate_similarity:
        return []

    # ------------------------------------------------------------------
    # Load all variants.
    # ------------------------------------------------------------------
    if requested_mods is not None:
        requested_mods = canonicalize_mods(requested_mods)

    variants = get_candidate_variants(conn, candidate_similarity.keys(), requested_mods=requested_mods)
    if not variants:
        return []

    # ------------------------------------------------------------------
    # Apply hard numeric filters.
    # ------------------------------------------------------------------
    filtered_variants = []
    for variant in variants:

        # SR
        star_rating = variant.get("star_rating")
        if star_rating is None:
            continue

        try:
            star_rating = float(star_rating)
        except (TypeError, ValueError):
            continue

        if min_stars is not None and star_rating < min_stars:
            continue
        if max_stars is not None and star_rating > max_stars:
            continue

        # BPM
        bpm = variant.get("bpm")
        if bpm is None:
            continue

        try:
            bpm = float(bpm)
        except (TypeError, ValueError):
            continue

        if min_bpm is not None and bpm < min_bpm:
            continue
        if max_bpm is not None and bpm > max_bpm:
            continue

        # PP
        pp = variant.get("pp")
        if min_pp is not None or max_pp is not None:
            if pp is None:
                continue

            try:
                pp = float(pp)
            except (TypeError, ValueError):
                continue

            if min_pp is not None and pp < min_pp:
                continue
            if max_pp is not None and pp > max_pp:
                continue

        # AR
        ar = variant.get("ar")

        if ar is None:
            continue

        try:
            ar = float(ar)
        except (TypeError, ValueError):
            continue

        if min_ar is not None and ar < min_ar:
            continue

        if max_ar is not None and ar > max_ar:
            continue

        # OD
        od = variant.get("od")

        if od is None:
            continue

        try:
            od = float(od)
        except (TypeError, ValueError):
            continue

        if min_od is not None and od < min_od:
            continue

        if max_od is not None and od > max_od:
            continue

        # Length (seconds)
        length_seconds = variant.get("length_seconds")
        if min_length is not None or max_length is not None:
            if length_seconds is None:
                continue

            try:
                length_seconds = float(length_seconds)
            except (TypeError, ValueError):
                continue

            if min_length is not None and length_seconds < min_length:
                continue
            if max_length is not None and length_seconds > max_length:
                continue

        filtered_variants.append(variant)

    variants = filtered_variants
    if not variants:
        return []

    classifier_predictions = get_candidate_classifier_predictions(
        conn,
        [variant["variant_id"] for variant in variants],
    )

    # ------------------------------------------------------------------
    # Score variants.
    # ------------------------------------------------------------------
    scored_variants = []
    for variant in variants:
        beatmap_id = variant["beatmap_id"]
        content_similarity = (candidate_similarity[beatmap_id])
        mods = variant["mods"]
        mod_preference = (mod_preferences.get(mods, 0.0,))

        difficulty_score = calculate_difficulty_score(
            variant,
            difficulty_profile,
            difficulty_std_floors,
            difficulty_feature_weights
        )

        # --------------------------------------------------------------
        # Classifier score
        # --------------------------------------------------------------
        classifier_weight = recommendation_config[recommendation_goal]["weights"]["classifier"]
        if classifier_weight <= 0:
            classifier_score = 0.5
        elif mods == "NM" and category_preferences:
            probabilities = classifier_predictions.get(variant["variant_id"])
            classifier_score = calculate_classifier_score(probabilities, category_preferences)
        else:
            classifier_score = 0.5

        # --------------------------------------------------------------
        # PP potential
        # --------------------------------------------------------------
        pp_potential = calculate_pp_potential(
            variant,
            difficulty_profile,
            difficulty_std_floors,
            difficulty_feature_weights,
            pp_push_target_z,
            pp_push_max_z,
        )

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

    # ------------------------------------------------------------------
    # Keep only the best variant for each base beatmap.
    # ------------------------------------------------------------------

    best_by_beatmap = {}
    for variant in scored_variants:
        beatmap_id = variant["beatmap_id"]
        previous = best_by_beatmap.get(beatmap_id)

        if previous is None or variant["final_score"] > previous["final_score"]:
            best_by_beatmap[beatmap_id] = variant

    # ------------------------------------------------------------------
    # Sort globally.
    # ------------------------------------------------------------------
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

    if top_k is not None:
        ranked = ranked[:top_k]

    return ranked