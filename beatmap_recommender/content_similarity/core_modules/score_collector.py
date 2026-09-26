from beatmap_recommender.recommender_db_setup.db_insertion import insert_score

def fetch_player_scores(api, player_id, limit=None):
    """
    Fetch a player's top and recent scores from the osu! API.

    Returns:
        tuple[list, list]:
            top_scores, recent_scores
    """
    top_scores = api.get(
        f"/users/{player_id}/scores/best",
        params={
            "limit": limit,
            "include_fails": 1,
        },
    )

    recent_scores = api.get(
        f"/users/{player_id}/scores/recent",
        params={
            "limit": limit,
            "include_fails": 1,
        },
    )

    return top_scores, recent_scores

def normalize_score(score, source):
    """
    Convert an osu! API score response into our database format.

    Args:
        score: Raw score dictionary returned by the osu! API.
        source: "top" or "recent".

    Returns:
        Dictionary suitable for insert_score().
    """
    beatmap = score.get("beatmap") or {}
    player_id = score.get("user_id")

    if player_id is None:
        user = score.get("user") or {}
        player_id = user.get("id")

    if player_id is None:
        raise ValueError(f"Score {score.get('id')} is missing player_id")

    beatmap_id = beatmap.get("id")
    if beatmap_id is None:
        raise ValueError(f"Score {score.get('id')} is missing beatmap_id")

    return {
        "score_id": str(score["id"]),
        "player_id": int(player_id),
        "beatmap_id": str(beatmap_id),
        "status": beatmap.get("status"),
        "score": score.get("score"),
        "max_combo": score.get("max_combo"),
        "accuracy": score.get("accuracy"),
        "pp": score.get("pp"),
        "rank": score.get("rank"),
        "mods": ",".join(score.get("mods") or []),
        "created_at": score.get("created_at"),
        "source": source,
    }

def store_player_scores(conn, top_scores, recent_scores):
    stored = 0
    skipped = 0

    all_scores = ([(score, "top") for score in top_scores] +
                  [(score, "recent") for score in recent_scores])

    for score, source in all_scores:
        normalized = normalize_score(score, source)

        exists = conn.execute(
            """
            SELECT 1
            FROM beatmaps
            WHERE beatmap_id = ?
            """,
            (normalized["beatmap_id"],)
        ).fetchone()

        if exists is None:
            print(f"Skipping score {normalized['score_id']}: beatmap {normalized['beatmap_id']} not found in beatmaps.db")
            skipped += 1
            continue

        insert_score(conn, normalized)
        stored += 1

    conn.commit()
    print(f"Stored: {stored}, Skipped: {skipped}")
    return stored

def update_player_scores(conn, api, player_id, limit=None):
    """
    Fetch and store a player's top and recent scores.

    Returns:
        Number of score records processed.
    """

    top_scores, recent_scores = fetch_player_scores(api, player_id, limit=limit)
    stored = store_player_scores(conn, top_scores, recent_scores)
    print(f"Player {player_id}: {len(top_scores)} top scores, {len(recent_scores)} recent scores, {stored} records processed.")
    return stored