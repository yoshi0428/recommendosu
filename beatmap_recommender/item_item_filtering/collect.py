import sqlite3
from pathlib import Path
from beatmap_recommender.recommender_db_setup.db_recommender_insert import insert_score
from beatmap_recommender.recommender_db_setup.osu_api_client import OsuAPIClient

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "beatmap_recommender/item_item_filtering/item-item.db"

MAX_PLAYERS_PER_COUNTRY = 10000
SCORE_PAGE_SIZE = 100
NUM_COUNTRY_CODES = 236

def fetch_country_codes(api):
    """
    Fetch all country codes currently present in the osu! country ranking.
    """

    country_codes = []
    page = 1

    while len(country_codes) < NUM_COUNTRY_CODES:
        data = api.get(
            "/rankings/osu/country",
            params={
                "page": page,
            },
        )

        ranking = data.get("ranking", [])

        if not ranking:
            break

        for entry in ranking:
            country = entry.get("country") or {}

            country_code = country.get("code")

            if country_code and country_code not in country_codes:
                country_codes.append(country_code)

                if len(country_codes) >= 236:
                    break

        page += 1

    return country_codes

def fetch_country_players(
    api,
    country_code,
    max_players=MAX_PLAYERS_PER_COUNTRY,
):
    """
    Fetch up to max_players osu!standard players from a country.
    Uses the performance global ranking filtered by country.
    """

    players = []
    page = 1

    while len(players) < max_players:
        params = {
            "country": country_code,
            "page": page,
            "limit": 50,
        }

        data = api.get(
            "/rankings/osu/performance",
            params=params,
        )

        # DEBUG
        # print("PARAMS:", params)
        # print("RANKING SIZE:", len(data.get("ranking", [])))
        # print("CURSOR RETURNED:", repr(data.get("cursor")))

        ranking = data.get("ranking", [])

        if not ranking:
            break

        for entry in ranking:
            user = entry.get("user") or {}
            player_id = user.get("id")

            if player_id is None:
                continue

            players.append({
                "player_id": int(player_id),
                "username": user.get("username"),
                "country_code": (
                    user.get("country", {}).get("code")
                    or country_code
                ),
                "country_name": (
                    user.get("country", {}).get("name")
                ),
                "global_rank": entry.get("global_rank"),
                "country_rank": len(players) + 1,
            })

            if len(players) >= max_players:
                break

        print(
            f"{country_code}: "
            f"discovered {len(players):,}/{max_players:,}"
        )

        page += 1

    return players

def store_players(conn, players):
    stored = 0

    for player in players:
        conn.execute(
            """
            INSERT INTO players (
                player_id,
                username,
                country_code,
                country_name,
                global_rank,
                country_rank
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(player_id) DO UPDATE SET
                username = excluded.username,
                country_code = excluded.country_code,
                country_name = excluded.country_name,
                global_rank = excluded.global_rank,
                country_rank = excluded.country_rank
            """,
            (
                player["player_id"],
                player["username"],
                player["country_code"],
                player["country_name"],
                player["global_rank"],
                player.get("country_rank"),
            ),
        )

        stored += 1

    conn.commit()

    return stored

def fetch_player_score_type(
    api,
    player_id,
    score_type,
    include_fails=True,
    page_size=SCORE_PAGE_SIZE,
):
    """
    Fetch all available scores of one type for a player.

    score_type:
        "best" or "recent"
    """

    scores = []
    offset = 0

    while True:
        data = api.get(
            f"/users/{player_id}/scores/{score_type}",
            params={
                "limit": page_size,
                "offset": offset,
                "include_fails": int(include_fails),
            },
        )

        if not data:
            break

        scores.extend(data)

        if len(data) < page_size:
            break

        offset += page_size

    return scores

def normalize_score(score, source):
    beatmap = score.get("beatmap") or {}
    player_id = score.get("user_id")

    if player_id is None:
        user = score.get("user") or {}
        player_id = user.get("id")

    if player_id is None:
        raise ValueError(f"Score {score.get('id')} is missing player_id")

    beatmap_id = score.get("beatmap_id")
    if beatmap_id is None:
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
        "mods": ",".join(
            score.get("mods") or []
        ),
        "created_at": score.get("created_at"),
        "source": source,
    }

def store_player_scores(conn, top_scores, recent_scores):
    stored = 0
    skipped = 0

    scores_by_id = {}

    for score in top_scores:
        scores_by_id[str(score["id"])] = (
            score,
            "top",
        )

    for score in recent_scores:
        score_id = str(score["id"])

        if score_id in scores_by_id:
            existing_score, existing_source = scores_by_id[score_id]

            scores_by_id[score_id] = (
                existing_score,
                "top,recent",
            )
        else:
            scores_by_id[score_id] = (
                score,
                "recent",
            )

    for score, source in scores_by_id.values():

        normalized = normalize_score(score, source)

        exists = conn.execute(
            """
            SELECT 1
            FROM beatmaps
            WHERE beatmap_id = ?
            """,
            (normalized["beatmap_id"],),
        ).fetchone()

        if exists is None:
            skipped += 1
            continue

        insert_score(conn, normalized)
        stored += 1

    conn.commit()

    return stored, skipped

def update_player_scores(api, conn, player_id):
    """
    Fetch and store all available top + recent scores
    for one player.
    """

    top_scores = fetch_player_score_type(
        api,
        player_id,
        "best",
    )

    recent_scores = fetch_player_score_type(
        api,
        player_id,
        "recent",
    )

    stored, skipped = store_player_scores(
        conn,
        top_scores,
        recent_scores,
    )

    print(
        f"Player {player_id}: "
        f"{len(top_scores):,} top, "
        f"{len(recent_scores):,} recent, "
        f"{stored:,} stored, "
        f"{skipped:,} skipped"
    )

    return stored

def collect_all_countries(
    api,
    conn,
    countries,
    max_players_per_country=10_000,
):
    """
    Discover up to max_players_per_country players
    from every supplied country and collect their
    top + recent scores.
    """

    total_players = 0
    total_scores = 0

    for country_index, country_code in enumerate(countries, 1):

        print()
        print("=" * 70)
        print(f"[{country_index}/{len(countries)}] COUNTRY: {country_code}")
        print("=" * 70)

        players = fetch_country_players(
            api,
            country_code,
            max_players=max_players_per_country,
        )

        print(f"{country_code}: found {len(players):,} players")

        store_players(conn, players)
        total_players += len(players)

        for player_index, player in enumerate(players, 1):

            player_id = player["player_id"]

            already_collected = conn.execute(
                """
                SELECT scores_collected
                FROM players
                WHERE player_id = ?
                """,
                (player_id,),
            ).fetchone()

            if already_collected and already_collected[0]:
                print(
                    f"[{country_code} {player_index:,}/{len(players):,}] "
                    f"{player['username']} ({player_id}) - already collected"
                )
                continue

            print(
                f"[{country_code} {player_index:,}/{len(players):,}] "
                f"{player['username']} ({player_id})"
            )

            try:
                stored = update_player_scores(
                    api,
                    conn,
                    player_id,
                )

                conn.execute(
                    """
                    UPDATE players
                    SET scores_collected = 1
                    WHERE player_id = ?
                    """,
                    (player_id,),
                )

                conn.commit()

                total_scores += stored

            except Exception as e:
                print(f"ERROR for player {player_id}: {e}")
                continue # Continue with the next player.

    print()
    print("=" * 70)
    print("COLLECTION COMPLETE")
    print("=" * 70)
    print(f"Players discovered: {total_players:,}")
    print(f"Score records stored: {total_scores:,}")

def main():
    conn = sqlite3.connect(DB_PATH)

    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")

    api = OsuAPIClient()

    country_codes = fetch_country_codes(api)

    print()
    print("=" * 70)
    print(f"FOUND {len(country_codes):,} COUNTRY CODES")
    print("=" * 70)
    print(country_codes)

    collect_all_countries(
        api=api,
        conn=conn,
        countries=country_codes,
        max_players_per_country=MAX_PLAYERS_PER_COUNTRY,
    )

    conn.close()

if __name__ == "__main__":
    main()
