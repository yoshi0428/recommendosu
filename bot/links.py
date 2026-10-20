import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path


class LinkStore:
    """
    Discord user -> osu! player, set with /link.

    Its own small SQLite file, separate from the backend's databases.
    """

    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        # One connection shared by the event loop's callbacks; the queries
        # are tiny, so they run inline instead of in a thread.
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.Lock()
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
        """(player_id, username), or None if the user hasn't linked."""
        with self.lock:
            return self.conn.execute(
                "SELECT player_id, username FROM links WHERE discord_user_id = ?",
                (discord_user_id,),
            ).fetchone()

    def set(self, discord_user_id, player_id, username):
        with self.lock:
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
        """Remove the user's link. True if there was one."""
        with self.lock:
            cursor = self.conn.execute(
                "DELETE FROM links WHERE discord_user_id = ?",
                (discord_user_id,),
            )
            self.conn.commit()
            return cursor.rowcount > 0

    def close(self):
        self.conn.close()
