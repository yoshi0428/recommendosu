import time

from beatmap_recommender.auth.db import auth_db

_STATE_EXPIRATION_SECONDS = 600


def store_state(state: str):
    created_at = time.time()
    expiration_time = created_at - _STATE_EXPIRATION_SECONDS

    with auth_db() as conn:
        # Delete the expired states so that they do not collect in the table.
        conn.execute(
            """
            DELETE FROM oauth_states
            WHERE created_at < ?
            """,
            (expiration_time,),
        )

        conn.execute(
            """
            INSERT INTO oauth_states (
                state,
                created_at
            )
            VALUES (?, ?)
            """,
            (
                state,
                created_at,
            ),
        )


def consume_state(state: str) -> bool:
    """
    Use up an OAuth state, if it is valid.

    Return True only if the state exists and did not expire. One DELETE
    statement finds and removes the state, so two requests cannot both use it.
    """
    expiration_time = time.time() - _STATE_EXPIRATION_SECONDS

    with auth_db() as conn:
        cursor = conn.execute(
            """
            DELETE FROM oauth_states
            WHERE state = ?
              AND created_at >= ?
            """,
            (
                state,
                expiration_time,
            ),
        )

        return cursor.rowcount == 1
