"""
Tests for recommender_db_setup/star_calculator.py (VersionAwareOsuCalculator).

The wrapper exists because osu-tools-py decodes every .osu file as the latest
format (v14). Old maps (v3-v5) then get modern note stacking instead of the
legacy stacking osu! uses for them, which inflates their star rating.

There's nothing to fake here: the whole point is how the *real* calculator
treats *real* files. So these tests use two real beatmaps from
beatmap_recommender/data and compare against values verified on the osu!
website:

    beatmap 1147  (2007, format v3)   5.06*  (unwrapped osu-tools-py: 6.56*)
    beatmap 4811125 (2024, format v14) 4.56*  (wrapper must change nothing)

They're skipped when osu-tools-py (which needs .NET) or the .osu files
aren't available, e.g. inside the backend Docker image or on a fresh clone.
"""

import hashlib
import sqlite3
from pathlib import Path

import pytest

# importorskip: import the module, or skip this whole file if it's missing.
osu_tools = pytest.importorskip("osu_tools")

from beatmap_recommender.recommender_db_setup.beatmap_mods import calculate_difficulty  # noqa: E402
from beatmap_recommender.recommender_db_setup.star_calculator import (  # noqa: E402
    VersionAwareOsuCalculator,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "beatmap_recommender" / "data" / "Ranked"
DUMMY_DB = PROJECT_ROOT / "beatmap_recommender" / "dummy.db"

OLD_MAP = {
    "beatmap_id": "1147",
    "path": DATA_DIR / "2007" / "IOSYS - Marisa wa Taihen na Mono wo Nusunde Ikimashita (DJPop) [Hard].osu",
    "md5": "7553a13a8c4a518c25e37d1ca6483303",
    "format": "v3",
    # Expected star ratings per mod combination.
    "stars": {(): 5.06, ("HR",): 5.38, ("DT",): 7.78},
}

MODERN_MAP = {
    "beatmap_id": "4811125",
    "path": DATA_DIR / "2024" / "1zm8 - Beyond The Horizon (Wispy) [Insane].osu",
    "md5": "e0fd6d977e17b6f4c7bbcd01cb700031",
    "format": "v14",
    "stars": {(): 4.56},
}


def require_map(beatmap):
    """Skip the test if the .osu file is missing; fail if it's a different file."""
    path = beatmap["path"]
    if not path.exists():
        pytest.skip(f"{path.name} not found in beatmap_recommender/data")

    # Guard against the test silently checking the wrong file (e.g. a map
    # that was updated and re-downloaded under the same name).
    data = path.read_bytes()
    assert hashlib.md5(data).hexdigest() == beatmap["md5"], f"{path.name} changed on disk"
    assert data.startswith(f"osu file format {beatmap['format']}".encode())
    return str(path)


@pytest.fixture(scope="module")
def calculator():
    # One calculator for the whole file: creating it starts the .NET runtime.
    return VersionAwareOsuCalculator()


@pytest.fixture(scope="module")
def plain_calculator():
    return osu_tools.OsuCalculator()


def stars(calc, path, mods=()):
    result = calc.calculate(file_path=path, mode=0, mods=list(mods))
    assert result.is_success, result.error
    return result.stars


@pytest.mark.parametrize("mods", list(OLD_MAP["stars"]))
def test_old_format_map_uses_legacy_stacking(calculator, mods):
    path = require_map(OLD_MAP)
    assert stars(calculator, path, mods) == pytest.approx(OLD_MAP["stars"][mods], abs=0.01)


def test_unwrapped_calculator_still_overestimates_old_maps(calculator, plain_calculator):
    """
    Documents *why* the wrapper exists: plain osu-tools-py gives the old map
    6.56* instead of 5.06*.

    If this test starts failing after upgrading osu-tools-py, it means
    upstream fixed the format-version bug. That's good news: the wrapper may
    no longer be needed, and this test is how you'll find out.
    """
    path = require_map(OLD_MAP)

    plain = stars(plain_calculator, path)
    aware = stars(calculator, path)

    assert plain == pytest.approx(6.56, abs=0.01)
    assert plain - aware > 1.0


def test_modern_map_is_unchanged_by_wrapper(calculator, plain_calculator):
    # For v14 maps the wrapper must be a no-op, so its output should equal
    # osu-tools-py's to the last digit.
    path = require_map(MODERN_MAP)

    assert stars(calculator, path) == stars(plain_calculator, path)
    assert stars(calculator, path) == pytest.approx(MODERN_MAP["stars"][()], abs=0.01)


def test_missing_file_fails_cleanly(calculator):
    # populate.py relies on calculate_difficulty returning None for a bad
    # file (it logs and moves on) instead of crashing the whole run.
    assert calculate_difficulty("/does/not/exist.osu", [], calculator) is None


def test_calculator_can_be_reused(calculator):
    # populate.py keeps one calculator per worker for ~150k files. The
    # wrapper opens a file stream per call and must close it every time;
    # repeated calls on the same file must keep working and agree.
    path = require_map(OLD_MAP)
    results = {stars(calculator, path) for _ in range(20)}
    assert len(results) == 1


@pytest.mark.skipif(not DUMMY_DB.exists(), reason="beatmap_recommender/dummy.db not found")
@pytest.mark.parametrize("beatmap", [OLD_MAP, MODERN_MAP], ids=["v3", "v14"])
def test_database_was_built_with_version_aware_stars(calculator, beatmap):
    """
    The stored star ratings must match what the version-aware calculator
    produces. If the database (or part of it) was ever populated with the
    plain calculator, old maps would show up here with ~1.5* too much.
    """
    path = require_map(beatmap)

    with sqlite3.connect(f"{DUMMY_DB.as_uri()}?mode=ro", uri=True) as conn:
        rows = conn.execute(
            "SELECT mods, star_rating FROM beatmap_variants WHERE beatmap_id = ?",
            (beatmap["beatmap_id"],),
        ).fetchall()
    stored = dict(rows)

    for mods in beatmap["stars"]:
        key = "".join(mods) or "NM"
        assert stored[key] == pytest.approx(stars(calculator, path, mods), abs=1e-6), key
