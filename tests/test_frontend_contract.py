"""
Contract tests: the frontend and backend must agree on default settings.

frontend/src/utils/recommendation.js keeps its own copy of the defaults in
beatmap_recommender/api/model.py for the settings the Advanced panel can
change (difficulty tables, scoring weights...). The frontend sends its copy
with every request, so it's what the site actually uses. Change a weight in
model.py and forget the JS file, and the change silently never reaches users.

Settings the UI can't change (goal weights, similarity weights, the result
limit...) aren't copied or sent at all, so the backend's defaults apply.

These tests load the JavaScript module with Node, print its defaults as JSON,
and compare them with the Python values. They're skipped if Node isn't
installed.
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
    # recommendation.js is a plain ES module with no imports, so Node can
    # load it directly; no build step needed.
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


@pytest.mark.parametrize(
    "field",
    ["limit", "similarity_feature_weights", "recommendation_config", "feature_target_z", "feature_max_z"],
)
def test_settings_the_ui_cant_change_are_left_to_the_backend(frontend_defaults, field):
    # Not sent, so a change in model.py reaches the site without a JS change.
    assert field not in frontend_defaults["settings"]


# Every scalar default the frontend sends, paired with the backend default.
# (Defaults the frontend doesn't send fall back to the backend's anyway.)
@pytest.mark.parametrize(
    "field",
    [
        "goal", "beatmap_status",
        "top_weight", "recent_weight", "pp_weight",
        "ability_top_weight", "ability_recent_weight", "ability_pp_weight",
        "recency_half_life_days",
        "pp_push_target_z", "pp_push_max_z",
    ],
)
def test_default_settings_match(frontend_defaults, field):
    backend_default = model.RecommendationSettings.model_fields[field].default
    assert frontend_defaults["settings"][field] == backend_default


def test_frontend_defaults_pass_backend_validation(frontend_defaults):
    # Whatever the form sends by default must be accepted by the API as-is.
    model.RecommendationSettings(**frontend_defaults["settings"])
