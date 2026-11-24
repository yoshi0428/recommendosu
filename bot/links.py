import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class LinkStore:
    """
    The map from a Discord user to an osu! player, which /link sets.

    It is a small SQLite file of its own, separate from the databases of the backend.
    """

    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        # Only the thread of the event loop uses this one connection. The queries
        # are very small, so they run inline, not in a thread, and need no lock.
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS links (
                discord_user_id INTEGER PRIMARY KEY,
                player_id INTEGER NOT NULL,
                username TEXT NOT NULL,
                linked_at TEXT NOT NULL
            )
            """
        )
        self.conn.commit()

    def get(self, discord_user_id):
        """Return (player_id, username), or None if the user did not link an account."""
        return self.conn.execute(
            "SELECT player_id, username FROM links WHERE discord_user_id = ?", (discord_user_id,)
        ).fetchone()

    def set(self, discord_user_id, player_id, username):
        """Link the user to the osu! player. Replace an earlier link, if there is one."""
        self.conn.execute(
            """
            INSERT INTO links (discord_user_id, player_id, username, linked_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (discord_user_id) DO UPDATE SET
                player_id = excluded.player_id,
                username = excluded.username,
                linked_at = excluded.linked_at
            """,
            (discord_user_id, player_id, username, datetime.now(timezone.utc).isoformat()),
        )
        self.conn.commit()

    def delete(self, discord_user_id):
        """Delete the link of the user. Return True if there was a link."""
        cursor = self.conn.execute("DELETE FROM links WHERE discord_user_id = ?", (discord_user_id,))
        self.conn.commit()
        return cursor.rowcount > 0

    def close(self):
        self.conn.close()
