import sqlite3
from pathlib import Path
from beatmap_recommender.content_similarity.db_modules.db_recommender import create_recommender_tables

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "beatmap_recommender/recommender.db"

def main():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    create_recommender_tables(conn)
    conn.close()

if __name__ == "__main__":
    main()