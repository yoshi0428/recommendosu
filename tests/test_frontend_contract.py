"""
Contract tests: the frontend and backend must agree on default settings.

frontend/src/utils/recommendation.js keeps its own copy of the defaults in
beatmap_recommender/api/model.py, for the settings that the Advanced panel can
change (difficulty tables, scoring weights...). The frontend sends its copy
with each request, so the site uses the copy. If you change a weight in
model.py and forget the JS file, the change never gets to users, and no error
shows.

The settings that the UI cannot change (score weights, similarity weights,
the result limit...) are not copied or sent, so the backend defaults apply.

These tests load the JavaScript module with Node, print its defaults as JSON,
and compare them with the Python values. If Node is not installed, the tests
are skipped.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from beatmap_recommender.api import model

FRONTEND_UTILS = Path(__file__).resolve().parents[1] / "frontend" / "src" / "utils" / "recommendation.js"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


@pytest.fixture(scope="module")
def frontend_defaults():
    # recommendation.js is a plain ES module with no imports, so Node can load
    # it directly. No build step is necessary.
    script = f"""
        const m = await import({json.dumps(FRONTEND_UTILS.as_uri())});
        console.log(JSON.stringify({{
            ...m,
            settings: m.createDefaultSettings(),
        }}));
    """
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True, text=True, check=True, timeout=30,
    )
    return json.loads(result.stdout)


def test_feature_weight_tables_match(frontend_defaults):
    settings = frontend_defaults["settings"]
    assert settings["difficulty_std_floors"] == model.DIFFICULTY_STD_FLOORS
    assert settings["difficulty_feature_weights"] == model.DIFFICULTY_FEATURE_WEIGHTS


# tests/frontend/recommendation.test.js checks that the settings that the UI
# cannot change are not sent. It runs without Node in the Python environment.


# Each scalar default that the frontend sends, with the backend default.
# (For the defaults that the frontend does not send, the backend defaults apply.)
@pytest.mark.parametrize(
    "field",
    [
        "beatmap_status",
        "top_weight", "recent_weight", "pp_weight",
        "ability_top_weight", "ability_recent_weight", "ability_pp_weight",
        "recency_half_life_days",
    ],
)
def test_default_settings_match(frontend_defaults, field):
    backend_default = model.RecommendationSettings.model_fields[field].default
    assert frontend_defaults["settings"][field] == backend_default


def test_frontend_defaults_pass_backend_validation(frontend_defaults):
    # The API must accept the default values of the form as they are.
    model.RecommendationSettings(**frontend_defaults["settings"])
