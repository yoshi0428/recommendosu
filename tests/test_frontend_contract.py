"""
Contract tests: the frontend and backend must agree on default settings.

frontend/src/utils/recommendation.js keeps its own copy of the defaults in
beatmap_recommender/api/model.py (feature weights, goal weights, scoring
settings). The frontend sends its copy with every request, so it's what the
site actually uses. Change a weight in model.py and forget the JS file, and
the change silently never reaches users.

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
    assert frontend_defaults["DEFAULT_DIFFICULTY_STD_FLOORS"] == model.DIFFICULTY_STD_FLOORS
    assert frontend_defaults["DEFAULT_DIFFICULTY_FEATURE_WEIGHTS"] == model.DIFFICULTY_FEATURE_WEIGHTS
    assert frontend_defaults["DEFAULT_SIMILARITY_FEATURE_WEIGHTS"] == model.SIMILARITY_FEATURE_WEIGHTS


def test_recommendation_goals_match(frontend_defaults):
    frontend_config = frontend_defaults["DEFAULT_RECOMMENDATION_CONFIG"]

    assert frontend_config.keys() == model.RECOMMENDATION_CONFIG.keys()
    for goal, config in model.RECOMMENDATION_CONFIG.items():
        assert frontend_config[goal]["weights"] == config["weights"], goal
        # Python stores sort keys as a tuple, JSON as a list.
        assert tuple(frontend_config[goal]["sort_keys"]) == config["sort_keys"], goal


# Every scalar default the frontend sends, paired with the backend default.
# (Defaults the frontend doesn't send fall back to the backend's anyway.)
@pytest.mark.parametrize(
    "field",
    [
        "goal", "beatmap_status", "limit",
        "top_weight", "recent_weight", "pp_weight",
        "ability_top_weight", "ability_recent_weight", "ability_pp_weight",
        "recency_half_life_days",
        "pp_push_target_z", "pp_push_max_z", "feature_target_z", "feature_max_z",
    ],
)
def test_default_settings_match(frontend_defaults, field):
    backend_default = model.RecommendationSettings.model_fields[field].default
    assert frontend_defaults["settings"][field] == backend_default


def test_frontend_defaults_pass_backend_validation(frontend_defaults):
    # Whatever the form sends by default must be accepted by the API as-is.
    model.RecommendationSettings(**frontend_defaults["settings"])
