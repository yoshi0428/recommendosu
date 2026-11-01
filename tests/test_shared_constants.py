"""
Constants copied between the backend, the website and the Discord bot.

The bot ships in its own Docker image with only bot/ in it, and the website
is JavaScript, so neither can import the backend's values. These tests fail
when a copy drifts, e.g. when MAX_BEATMAP_YEAR is bumped in one place only.
"""

import ast
import re
from pathlib import Path

from beatmap_recommender.api import model
from bot import options

PROJECT_ROOT = Path(__file__).resolve().parents[1]
POPULATE = PROJECT_ROOT / "beatmap_recommender/recommender_db_setup/populate.py"
FRONTEND = PROJECT_ROOT / "frontend/src"


def module_constant(path, name):
    """A literal assigned at the top of a Python file, read without importing it."""
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} not found in {path}")


def js_constant(path, name):
    """The source of `const NAME = ...;` in a JavaScript file."""
    match = re.search(rf"const {name} = (.*?);\n", path.read_text(), re.S)
    assert match, f"{name} not found in {path}"
    return match.group(1)


def js_string_lists(source):
    """Every ["A", "B"] list of strings in a piece of JavaScript source."""
    return [re.findall(r'"([^"]*)"', inner) for inner in re.findall(r"\[([^\[\]]*)\]", source)]


# The mod combinations populate.py stores a variant for, besides NM.
STORED_COMBINATIONS = {frozenset(mods) for mods in module_constant(POPULATE, "MOD_VARIANTS").values() if mods}


def test_bot_mod_combinations_match_the_database():
    assert options.MOD_COMBINATIONS == STORED_COMBINATIONS


def test_website_mod_combinations_match_the_database():
    source = js_constant(FRONTEND / "components/ModCheckboxes.jsx", "MOD_COMBINATIONS")
    assert {frozenset(mods) for mods in js_string_lists(source)} == STORED_COMBINATIONS


def test_bot_and_website_show_the_same_mods():
    source = js_constant(FRONTEND / "components/ModCheckboxes.jsx", "INDIVIDUAL_MODS")
    assert tuple(js_string_lists(source)[0]) == options.INDIVIDUAL_MODS


def test_bot_and_website_exclude_the_same_mods_by_default():
    source = js_constant(FRONTEND / "utils/recommendation.js", "DEFAULT_EXCLUDED_MODS")
    assert tuple(js_string_lists(source)[0]) == options.DEFAULT_EXCLUDED_MODS


def test_year_limits_match_the_backend():
    basic_options = FRONTEND / "components/BasicOptions.jsx"
    years = (model.MIN_BEATMAP_YEAR, model.MAX_BEATMAP_YEAR)

    assert (options.MIN_BEATMAP_YEAR, options.MAX_BEATMAP_YEAR) == years
    assert (int(js_constant(basic_options, "MIN_YEAR")), int(js_constant(basic_options, "MAX_YEAR"))) == years
