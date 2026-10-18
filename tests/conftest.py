"""
Shared test setup.

pytest automatically loads every `conftest.py` before running the tests next
to it. Anything defined here with `@pytest.fixture` can be requested by any
test simply by naming it as a function parameter, e.g.

    def test_something(recommender_db):
        ...

pytest sees the parameter name, finds the fixture with that name, runs it, and
passes in whatever it returns (or `yield`s). Code after a `yield` runs once the
test finishes, which is how fixtures clean up after themselves.

The main idea behind the fixtures below: tests must never touch the real
databases, the real osu! API, or your real credentials. Each test gets its own
small, throwaway copy of everything, so tests can't interfere with each other or
with the running site.
"""

import os
import sqlite3

import pytest

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------
# beatmap_recommender/auth/osu_oauth.py raises at *import time* if these are
# missing, and main.py imports it. Setting fake values here (conftest is loaded
# before any test module) lets the app import. No test sends them anywhere:
# every network call is replaced with a fake.
os.environ.setdefault("OSU_CLIENT_ID", "test-client-id")
os.environ.setdefault("OSU_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("OSU_REDIRECT_URI", "http://testserver/api/v1/auth/osu/callback")


# ---------------------------------------------------------------------------
# Process-wide osu! API state
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def reset_osu_api_state(monkeypatch):
    """
    Give every test a fresh shared rate limiter and no remembered score
    refreshes, so one test's API calls can't slow down or skip another's.
    """
    from beatmap_recommender.api import osu_api_client
    from beatmap_recommender.content_similarity.core_modules import score_collector

    monkeypatch.setattr(
        osu_api_client,
        "rate_limiter",
        osu_api_client.RateLimiter(osu_api_client.rate_limiter.burst, osu_api_client.rate_limiter.interval),
    )
    monkeypatch.setattr(score_collector, "_last_refreshed", {})


# ---------------------------------------------------------------------------
# Recommender database
# ---------------------------------------------------------------------------
# This schema is copied from beatmap_recommender/dummy.db (`sqlite3 dummy.db
# .schema`), trimmed to the tables the recommender reads. Using the real
# schema means the SQL in the app runs unchanged against the test data.
RECOMMENDER_SCHEMA = """
CREATE TABLE beatmaps (
    beatmap_id TEXT PRIMARY KEY,
    beatmapset_id TEXT,
    md5 TEXT,
    title TEXT NOT NULL,
    artist TEXT NOT NULL,
    creator TEXT NOT NULL,
    version TEXT NOT NULL,
    preview_time REAL NOT NULL,
    year INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    hp_drain REAL NOT NULL,
    circle_size REAL NOT NULL,
    od REAL NOT NULL,
    ar REAL NOT NULL,
    slider_multiplier REAL,
    slider_tick REAL,
    bpm REAL,
    min_bpm REAL,
    max_bpm REAL,
    length_seconds REAL NOT NULL,
    object_count INTEGER NOT NULL
);

CREATE TABLE beatmap_variants (
    variant_id INTEGER PRIMARY KEY AUTOINCREMENT,
    beatmap_id TEXT NOT NULL,
    beatmapset_id TEXT,
    mods TEXT NOT NULL,
    year INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    hp_drain REAL NOT NULL,
    circle_size REAL NOT NULL,
    od REAL NOT NULL,
    ar REAL NOT NULL,
    star_rating REAL NOT NULL,
    max_combo INTEGER,
    bpm REAL,
    min_bpm REAL,
    max_bpm REAL,
    length_seconds REAL NOT NULL,
    object_count INTEGER NOT NULL,
    pp REAL,
    pp_aim REAL,
    pp_speed REAL,
    pp_acc REAL,
    pp_flashlight REAL,
    FOREIGN KEY (beatmap_id) REFERENCES beatmaps(beatmap_id) ON DELETE CASCADE,
    UNIQUE (beatmap_id, mods)
);

CREATE TABLE variant_predictions (
    variant_id INTEGER PRIMARY KEY,
    nm1 REAL, nm2 REAL, nm3 REAL, nm4 REAL, nm5 REAL,
    FOREIGN KEY (variant_id) REFERENCES beatmap_variants(variant_id) ON DELETE CASCADE
);

CREATE TABLE scores (
    score_id TEXT PRIMARY KEY,
    player_id INTEGER NOT NULL,
    beatmap_id TEXT NOT NULL,
    status TEXT,
    score INTEGER,
    max_combo INTEGER,
    accuracy REAL,
    pp REAL,
    rank TEXT,
    mods TEXT,
    created_at TEXT,
    source TEXT,
    FOREIGN KEY (beatmap_id) REFERENCES beatmaps(beatmap_id) ON DELETE CASCADE
);
"""

# How each mod changes a variant's stats in the fake data. These are rough
# approximations of osu! behaviour; they only need to be *plausible* so that,
# for example, HDDT variants really are harder than NM variants.
_MOD_EFFECTS = {
    # mods: (star multiplier, bpm/clock multiplier, ar, od)
    "NM": (1.00, 1.0, None, None),
    "HD": (1.05, 1.0, None, None),
    "HR": (1.10, 1.0, "hr", "hr"),
    "DT": (1.40, 1.5, "dt", "dt"),
    "HDDT": (1.45, 1.5, "dt", "dt"),
    "HDHR": (1.15, 1.0, "hr", "hr"),
}


class RecommenderDB:
    """
    A tiny helper for building recommender test data.

    Instead of writing raw INSERT statements in every test, tests call
    `db.add_beatmap(...)` and `db.add_score(...)` with only the values they
    care about; everything else gets a sensible default. This keeps each test
    focused on *what is different* about its scenario.
    """

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self._score_counter = 0

    def add_beatmap(
        self,
        beatmap_id,
        stars=5.0,
        bpm=180.0,
        ar=9.0,
        od=8.0,
        cs=4.0,
        status="ranked",
        year=2020,
        mods=("NM", "HD", "HR", "DT", "HDDT", "HDHR"),
        predictions=(0.2, 0.2, 0.2, 0.2, 0.2),
        beatmapset_id=None,
        title=None,
        length_seconds=120.0,
    ):
        beatmap_id = str(beatmap_id)
        beatmapset_id = str(beatmapset_id or f"set{beatmap_id}")

        self.conn.execute(
            """
            INSERT INTO beatmaps (
                beatmap_id, beatmapset_id, md5, title, artist, creator, version,
                preview_time, year, status, hp_drain, circle_size, od, ar,
                bpm, min_bpm, max_bpm, length_seconds, object_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                beatmap_id, beatmapset_id, f"md5-{beatmap_id}",
                title or f"Song {beatmap_id}", "Artist", "Mapper", "Insane",
                -1, year, status, 5.0, cs, od, ar,
                bpm, bpm, bpm, length_seconds, 500,
            ),
        )

        for mod in mods:
            star_mult, clock, ar_kind, od_kind = _MOD_EFFECTS[mod]
            v_ar = {"hr": min(10.0, ar * 1.4), "dt": min(11.0, ar + 1.3)}.get(ar_kind, ar)
            v_od = {"hr": min(10.0, od * 1.4), "dt": min(11.0, od + 1.5)}.get(od_kind, od)
            v_stars = stars * star_mult
            # pp grows faster than stars, roughly like the real data.
            v_pp = 20.0 * v_stars ** 2

            cursor = self.conn.execute(
                """
                INSERT INTO beatmap_variants (
                    beatmap_id, beatmapset_id, mods, year, status,
                    hp_drain, circle_size, od, ar, star_rating, max_combo,
                    bpm, min_bpm, max_bpm, length_seconds, object_count,
                    pp, pp_aim, pp_speed, pp_acc, pp_flashlight
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    beatmap_id, beatmapset_id, mod, year, status,
                    5.0, cs, v_od, v_ar, v_stars, 700,
                    bpm * clock, bpm * clock, bpm * clock, length_seconds / clock, 500,
                    v_pp, v_pp * 0.45, v_pp * 0.35, v_pp * 0.2, 0.0,
                ),
            )

            if mod == "NM" and predictions is not None:
                self.conn.execute(
                    "INSERT INTO variant_predictions VALUES (?, ?, ?, ?, ?, ?)",
                    (cursor.lastrowid, *predictions),
                )

        self.conn.commit()
        return beatmap_id

    def add_score(
        self,
        player_id,
        beatmap_id,
        mods="",
        source="top",
        pp=200.0,
        created_at="2026-10-01T00:00:00Z",
    ):
        # Note: the osu! API gives mods like "HD,DT", and NM is an empty string.
        # That's the format stored in the real scores table, so tests use it too.
        self._score_counter += 1
        self.conn.execute(
            """
            INSERT INTO scores (
                score_id, player_id, beatmap_id, status, score, max_combo,
                accuracy, pp, rank, mods, created_at, source
            ) VALUES (?, ?, ?, 'ranked', 1000000, 700, 0.98, ?, 'S', ?, ?, ?)
            """,
            (
                f"score-{self._score_counter}", player_id, str(beatmap_id),
                pp, mods, created_at, source,
            ),
        )
        self.conn.commit()


def _create_recommender_db(path):
    conn = sqlite3.connect(path)
    conn.executescript(RECOMMENDER_SCHEMA)
    db = RecommenderDB(conn)
    db.path = path
    return db


@pytest.fixture
def recommender_db(tmp_path):
    """
    An empty recommender database with the real schema.

    `tmp_path` is a built-in pytest fixture: a fresh temporary directory that
    is unique to this test. Each test therefore gets its own database file
    and nothing leaks between tests.
    """
    db = _create_recommender_db(tmp_path / "recommender.db")
    yield db
    db.conn.close()


@pytest.fixture
def disk_recommender_db(tmp_path):
    """
    A second, independent recommender database.

    In production, scores are written to both the in-memory database and the
    on-disk file it was loaded from. Tests that check that behaviour use
    `recommender_db` as the "memory" side and this one as the "disk" side.
    """
    db = _create_recommender_db(tmp_path / "recommender_disk.db")
    yield db
    db.conn.close()


PLAYER_ID = 100


@pytest.fixture
def seeded_db(recommender_db):
    """
    A small but realistic world: one player with a handful of plays, plus a
    pool of unplayed candidate maps around (and far away from) their skill.

    Player 100 mostly plays ~5.0-5.5 star maps, likes HD/HDDT, and has one
    old easy recent play.
    """
    db = recommender_db

    # Maps the player has played (these become "seed" maps).
    db.add_beatmap(1, stars=5.0, bpm=180)
    db.add_beatmap(2, stars=4.0, bpm=170)   # Played with HDDT -> ~5.8 stars.
    db.add_beatmap(3, stars=5.4, bpm=200)
    db.add_beatmap(4, stars=2.0, bpm=120)   # An easy warm-up map.

    db.add_score(PLAYER_ID, 1, mods="", source="top", pp=250)
    db.add_score(PLAYER_ID, 2, mods="HD,DT", source="top", pp=300)
    db.add_score(PLAYER_ID, 3, mods="HD", source="top,recent", pp=280)
    db.add_score(PLAYER_ID, 4, mods="", source="recent", pp=30)

    # Unplayed candidate maps.
    db.add_beatmap(10, stars=5.1, bpm=185, predictions=(0.1, 0.1, 0.6, 0.1, 0.1))
    db.add_beatmap(11, stars=5.3, bpm=190, status="loved")
    db.add_beatmap(12, stars=4.8, bpm=175, year=2010)
    db.add_beatmap(13, stars=9.0, bpm=300)  # Way too hard.
    db.add_beatmap(14, stars=1.5, bpm=100)  # Way too easy.

    return db


# ---------------------------------------------------------------------------
# Auth database
# ---------------------------------------------------------------------------


@pytest.fixture
def auth_db(tmp_path, monkeypatch):
    """
    Point all three auth stores at a fresh temporary auth.db and create the
    tables.

    `monkeypatch` is a built-in pytest fixture that temporarily replaces an
    attribute (here, the module-level AUTH_DB_PATH constant) and automatically
    puts the original back after the test. Without it, tests would write
    sessions into your real beatmap_recommender/auth.db.
    """
    from beatmap_recommender.auth import oauth_state, session, token_store

    path = tmp_path / "auth.db"
    for module in (oauth_state, session, token_store):
        monkeypatch.setattr(module, "AUTH_DB_PATH", path)

    # sessions must exist before oauth_tokens because of the foreign key.
    session.initialize_session_store()
    token_store.initialize_token_store()
    oauth_state.initialize_state_store()
    return path
