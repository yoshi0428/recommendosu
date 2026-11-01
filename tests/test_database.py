"""
Tests for database.py and the variant table cache that depends on it.

Requests query the database file at DB_PATH directly; only the variant
table (every beatmap variant as numpy columns) is kept in memory, and only
for DB_PATH, since tests and scripts use other files that change under them.
"""

import sqlite3

import pytest

from beatmap_recommender import database
from beatmap_recommender.content_similarity.core_modules import variant_table
from beatmap_recommender.content_similarity.core_modules.variant_table import get_variant_table


@pytest.fixture
def db_path(recommender_db, monkeypatch):
    """Point DB_PATH at the test database, with no cached variant table."""
    recommender_db.add_beatmap(1)
    monkeypatch.setattr(database, "DB_PATH", recommender_db.path)
    monkeypatch.setattr(variant_table, "_shared_table", None)
    return recommender_db


def test_read_only_connection_cannot_write(db_path):
    conn = database.connect_db(read_only=True)

    try:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("DELETE FROM scores")
    finally:
        conn.close()


def test_connection_uses_wal_and_foreign_keys(db_path):
    conn = database.connect_db()

    try:
        assert conn.execute("PRAGMA journal_mode").fetchone() == ("wal",)
        assert conn.execute("PRAGMA foreign_keys").fetchone() == (1,)
    finally:
        conn.close()


def test_is_db_path(db_path, tmp_path):
    other = sqlite3.connect(tmp_path / "other.db")

    try:
        assert database.is_db_path(db_path.conn)
        assert not database.is_db_path(other)
        assert not database.is_db_path(sqlite3.connect(":memory:"))
    finally:
        other.close()


def test_variant_table_is_cached_for_db_path_only(db_path, tmp_path):
    assert get_variant_table(db_path.conn) is get_variant_table(db_path.conn)

    other = sqlite3.connect(tmp_path / "other.db")
    try:
        other.executescript("\n".join(db_path.conn.iterdump()))
        assert get_variant_table(other) is not get_variant_table(other)
    finally:
        other.close()


def test_variant_table_reloads_when_db_path_changes(db_path, monkeypatch, tmp_path):
    table = get_variant_table(db_path.conn)

    other_path = tmp_path / "other.db"
    other = sqlite3.connect(other_path)
    try:
        other.executescript("\n".join(db_path.conn.iterdump()))
        monkeypatch.setattr(database, "DB_PATH", other_path)

        assert get_variant_table(other) is not table
        assert get_variant_table(other) is get_variant_table(other)
    finally:
        other.close()
