import time

from beatmap_recommender.auth.db import auth_db

_STATE_EXPIRATION_SECONDS = 600


def store_state(state: str):
    created_at = time.time()
    expiration_time = created_at - _STATE_EXPIRATION_SECONDS

    with auth_db() as conn:
        # Remove expired states so they do not accumulate.
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
    Atomically validate and consume an OAuth state.

    Returns True only if the state exists and has not expired.
    A valid state is deleted as part of the same atomic operation.
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
