import sqlite3
from typing import Optional
from osu_api_client import OsuAPIClient

MODE = "osu"
RANKINGS_DB = "rankings.db"

# ============================================================
# Database initialization
# ============================================================

def init_rankings_db(
    db_path: str = RANKINGS_DB,
) -> None:
    """
    Create the rankings table if it does not already exist.

    Schema:

        rank       INTEGER PRIMARY KEY
        player_id  INTEGER NOT NULL
    """

    with sqlite3.connect(db_path) as conn:

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS rankings (
                rank INTEGER PRIMARY KEY,
                player_id INTEGER NOT NULL
            )
            """
        )

        conn.commit()

def update_rankings_db(
    api: OsuAPIClient,
    db_path: str = RANKINGS_DB,
    max_rank: int = 1_000_000,
) -> None:
    """
    Download the global performance rankings and store them
    locally in SQLite.

    The osu! ranking API is traversed using cursor pagination.

    Only (rank, player_id) are stored.

    Existing rankings are replaced once the new ranking snapshot
    has been successfully downloaded.
    """

    print(
        f"Updating rankings database "
        f"(ranks 1-{max_rank:,})..."
    )

    # --------------------------------------------------------
    # Build the new ranking snapshot in memory
    #
    # We collect batches and periodically write them to SQLite.
    # --------------------------------------------------------

    rankings = {}

    cursor: Optional[dict] = None
    last_rank = 0

    while last_rank < max_rank:

        params = {}

        if cursor is not None:
            for key, value in cursor.items():
                params[f"cursor[{key}]"] = value

        data = api.get(
            f"/rankings/{MODE}/performance",
            params=params,
        )

        ranking = data.get("ranking", [])

        if not ranking:
            print("Ranking API returned no more players.")
            break

        for player in ranking:

            rank = player.get("global_rank")

            if rank is None:
                continue

            if rank > max_rank:
                break

            user = player.get("user")

            if not user:
                continue

            player_id = user.get("id")

            if player_id is None:
                continue

            if rank in rankings:
                print(
                    f"Duplicate rank received: #{rank} "
                    f"(existing player={rankings[rank]}, "
                    f"new player={player_id})"
                )

            rankings[rank] = player_id
            last_rank = max(last_rank, rank)

        print(
            f"Downloaded through rank "
            f"#{last_rank:,} / #{max_rank:,}"
        )

        # ----------------------------------------------------
        # Get cursor for next request
        # ----------------------------------------------------

        next_cursor = data.get("cursor")

        if not next_cursor:
            print(
                "No next cursor returned; "
                "ranking download finished."
            )
            break

        cursor = next_cursor

    # --------------------------------------------------------
    # Write the snapshot to SQLite
    # --------------------------------------------------------

    if not rankings:
        raise RuntimeError(
            "No ranking data was downloaded."
        )

    print(
        f"Writing {len(rankings):,} rankings "
        f"to SQLite..."
    )

    ranking_rows = [
        (rank, player_id)
        for rank, player_id in sorted(rankings.items())
    ]

    with sqlite3.connect(db_path) as conn:

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS rankings (
                rank INTEGER PRIMARY KEY,
                player_id INTEGER NOT NULL
            )
            """
        )

        # Replace the dot_osu_extract snapshot.
        conn.execute(
            "DELETE FROM rankings"
        )

        conn.executemany(
            """
            INSERT INTO rankings (
                rank,
                player_id
            )
            VALUES (?, ?)
            """,
            ranking_rows,
        )

        conn.commit()

    print(
        f"Ranking database updated successfully "
        f"through rank #{last_rank:,}."
    )

def main():
    api = OsuAPIClient()
    init_rankings_db()
    update_rankings_db(api, max_rank=12000)


if __name__ == "__main__":
    main()