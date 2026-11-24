"""
The shared test setup.

pytest loads each `conftest.py` automatically, before it runs the tests in the
same directory. Any test can use a `@pytest.fixture` from this file: it names
the fixture as a function parameter. For example:

    def test_something(recommender_db):
        ...

pytest finds the fixture with that name, runs it, and passes in the value
that it returns (or `yield`s). The code after a `yield` runs when the test
ends. That is how a fixture cleans up.

The main rule of these fixtures: a test must never use the real databases,
the real osu! API, or your real credentials. Each test gets its own small
temporary copy of everything. Thus the tests cannot affect each other or the
running site.
"""

import os
import sqlite3

import pytest

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------
# beatmap_recommender/auth/osu_oauth.py raises an error at *import time* if
# these are missing, and main.py imports it. With fake values here (conftest
# loads before all test modules), the app can import. No test sends them: a
# fake replaces each network call.
os.environ.setdefault("OSU_CLIENT_ID", "test-client-id")
os.environ.setdefault("OSU_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("OSU_REDIRECT_URI", "http://testserver/api/v1/auth/osu/callback")


# ---------------------------------------------------------------------------
# Process-wide osu! API state
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def reset_osu_api_state(monkeypatch):
    """
    Give each test a new shared rate limiter and no remembered score
    refreshes. Thus the API calls of one test cannot slow down or skip the
    calls of another test.
    """
    from beatmap_recommender.api import osu_api_client
    from beatmap_recommender.content_similarity.core_modules import score_collector

    monkeypatch.setattr(
        osu_api_client,
        "rate_limiter",
        osu_api_client.RateLimiter(osu_api_client.rate_limiter.burst, osu_api_client.rate_limiter.interval),
    )
    monkeypatch.setattr(score_collector, "_last_refreshed", {})


class FakeApiClock:
    """time.monotonic and time.sleep for osu_api_client. A sleep moves the clock forward."""

    def __init__(self):
        self.now = 1000.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def fake_clock(monkeypatch):
    """Replace the clock of osu_api_client, so that rate limit waits are instant and recorded."""
    from beatmap_recommender.api import osu_api_client

    clock = FakeApiClock()
    monkeypatch.setattr(osu_api_client.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(osu_api_client.time, "sleep", clock.sleep)
    return clock


# ---------------------------------------------------------------------------
# Recommender database
# ---------------------------------------------------------------------------
# This schema is a copy from beatmap_recommender/dummy.db (`sqlite3 dummy.db
# .schema`), with only the tables that the recommender reads. Because it is
# the real schema, the SQL of the app runs on the test data without changes.
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

# How each mod changes the stats of a variant in the fake data. These values
# are rough approximations of osu!. They only need to be *plausible*, so that,
# for example, the HDDT variants are really harder than the NM variants.
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
    A small helper that builds recommender test data.

    A test does not write raw INSERT statements. It calls `db.add_beatmap(...)`
    and `db.add_score(...)` with only the values that matter to it. All other
    values get a sensible default. Thus each test shows only *what is
    different* in its scenario.
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
            # pp grows faster than stars, approximately as in the real data.
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
        rank="S",
    ):
        # The osu! API gives mods such as "HD,DT", and NM is an empty string.
        # The real scores table stores that format, so the tests use it too.
        self._score_counter += 1
        self.conn.execute(
            """
            INSERT INTO scores (
                score_id, player_id, beatmap_id, status, score, max_combo,
                accuracy, pp, rank, mods, created_at, source
            ) VALUES (?, ?, ?, 'ranked', 1000000, 700, 0.98, ?, ?, ?, ?, ?)
            """,
            (
                f"score-{self._score_counter}", player_id, str(beatmap_id),
                pp, rank, mods, created_at, source,
            ),
        )
        self.conn.commit()


@pytest.fixture
def recommender_db(tmp_path):
    """
    An empty recommender database with the real schema.

    `tmp_path` is a built-in pytest fixture: a new temporary directory for
    this test only. Thus each test gets its own database file, and no data
    goes from one test to another.
    """
    path = tmp_path / "recommender.db"
    conn = sqlite3.connect(path)
    conn.executescript(RECOMMENDER_SCHEMA)
    db = RecommenderDB(conn)
    db.path = path
    yield db
    db.conn.close()


PLAYER_ID = 100


@pytest.fixture
def seeded_db(recommender_db):
    """
    A small but realistic world: one player with a few plays, plus a pool of
    candidate maps that the player did not play, near the skill of the player
    (and far from it).

    Player 100 mostly plays maps of about 5.0-5.5 stars, likes HD/HDDT, and
    has one old, easy recent play.
    """
    db = recommender_db

    # The maps that the player played (these become the "seed" maps).
    db.add_beatmap(1, stars=5.0, bpm=180)
    db.add_beatmap(2, stars=4.0, bpm=170)   # Played with HDDT -> ~5.8 stars.
    db.add_beatmap(3, stars=5.4, bpm=200)
    db.add_beatmap(4, stars=2.0, bpm=120)   # An easy warm-up map.

    db.add_score(PLAYER_ID, 1, mods="", source="top", pp=250)
    db.add_score(PLAYER_ID, 2, mods="HD,DT", source="top", pp=300)
    db.add_score(PLAYER_ID, 3, mods="HD", source="top,recent", pp=280)
    db.add_score(PLAYER_ID, 4, mods="", source="recent", pp=30)

    # The candidate maps that the player did not play.
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
    Point the auth stores at a new temporary auth.db, and create the tables.

    `monkeypatch` is a built-in pytest fixture. It replaces an attribute for
    the time of the test (here, the AUTH_DB_PATH constant of the module), and
    puts the original back after the test. Without it, the tests would write
    sessions into your real beatmap_recommender/auth.db.
    """
    from beatmap_recommender.auth import db

    path = tmp_path / "auth.db"
    monkeypatch.setattr(db, "AUTH_DB_PATH", path)
    db.initialize_auth_db()
    return path
