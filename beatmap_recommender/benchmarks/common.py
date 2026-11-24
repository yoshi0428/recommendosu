"""
The shared setup of the benchmark scripts. Import this module before any
beatmap_recommender module that loads the OAuth module.
"""

import os
from pathlib import Path

# The recommender imports the OAuth module, which refuses to load without
# these values. The benchmarks do not fetch scores, so placeholders are enough.
for name in ("OSU_CLIENT_ID", "OSU_CLIENT_SECRET", "OSU_REDIRECT_URI"):
    os.environ.setdefault(name, "unused")

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Opened read-only (the scores are not updated), so the file never changes.
DEFAULT_DB_PATH = PROJECT_ROOT / "beatmap_recommender/recommender.local.db"
DEFAULT_PLAYER_ID = 10961031
