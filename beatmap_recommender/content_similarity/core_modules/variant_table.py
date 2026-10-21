"""
beatmap_variants held as numpy columns, so candidate filtering and ranking
don't create a Python object per row.

The worst-case request (no star bounds, every mod) selects ~3 million
variants. Reading them from SQLite as tuples and turning them into dicts took
longer than ranking them, and a cached result of 3 million dicts held ~6GB.
Instead, the table is loaded once, filters are numpy masks, and rows are only
turned into dicts for the page the frontend asks for (see VariantRows).

Only the shared in-memory database (connect_memory_db) is cached: the
recommender never writes to beatmap_variants or beatmaps, only to scores.
Any other connection, such as a test database, gets a fresh table per call.
"""

import ctypes
import logging
import re
import threading
import time
from collections.abc import Sequence

import numpy as np

from beatmap_recommender.database import connect_memory_db, is_shared_memory_db

logger = logging.getLogger(__name__)

# Columns of each variant dict, in the order get_candidate_variants() has
# always returned them.
VARIANT_COLUMNS = (
    "variant_id",
    "beatmap_id",
    "beatmapset_id",
    "mods",
    "hp_drain",
    "circle_size",
    "od",
    "ar",
    "star_rating",
    "max_combo",
    "bpm",
    "length_seconds",
    "object_count",
    "pp",
    "pp_aim",
    "pp_speed",
    "pp_acc",
    "pp_flashlight",
    "status",
)

# Loaded for filtering, but not part of the variant dicts.
FILTER_ONLY_COLUMNS = ("year",)

TEXT_COLUMNS = ("beatmap_id", "beatmapset_id", "mods", "status")

METADATA_FIELDS = ("title", "artist", "creator", "version")

# variant_predictions columns: the classifier's NM1-NM5 probabilities.
PREDICTION_COLUMNS = ("nm1", "nm2", "nm3", "nm4", "nm5")

# Rows read from SQLite per fetchmany() while loading the table.
LOAD_CHUNK_SIZE = 65_536

# Rows are built in chunks of this many when iterating over a VariantRows.
ITERATION_CHUNK_SIZE = 10_000

_shared_table = None
_shared_table_lock = threading.Lock()


def get_variant_table(conn):
    """Return the variant table for conn, cached for the shared memory database."""
    global _shared_table

    if not is_shared_memory_db(conn):
        return VariantTable.load(conn)

    with _shared_table_lock:
        if _shared_table is None:
            _shared_table = VariantTable.load(conn)

        return _shared_table


def load_variant_table():
    """Build the shared table now, e.g. at startup, instead of on the first request."""
    conn = connect_memory_db()

    try:
        get_variant_table(conn)
    finally:
        conn.close()

    _release_freed_memory()


def _release_freed_memory():
    """
    Hand the memory freed while building the table back to the OS (~440MB).

    Loading reads every row as Python objects, which are freed once they're in
    numpy arrays, but glibc keeps freed memory in its heap instead of returning
    it. With MALLOC_ARENA_MAX=1 (see the Dockerfile) it stays there for the
    life of the process. Not available outside glibc (e.g. macOS), where it's
    skipped.
    """
    try:
        libc = ctypes.CDLL("libc.so.6")
        libc.malloc_trim(0)
    except (OSError, AttributeError):
        pass


def _numeric_array(values):
    """int64 or float64 when every value is that Python type, otherwise object."""
    array = np.array(values)

    if array.dtype == np.int64:
        return array

    # A mix of ints and floats also becomes float64, which would turn ints into floats.
    if array.dtype == np.float64 and not any(type(value) is int for value in values):
        return array

    return np.array(values, dtype=object)


def _concatenate(chunks):
    if len({chunk.dtype for chunk in chunks}) > 1:
        # astype(object) turns numpy ints and floats back into Python ones.
        chunks = [chunk.astype(object) for chunk in chunks]

    return np.concatenate(chunks) if chunks else np.empty(0, dtype=np.int64)


def _float_array(column):
    if column.dtype != object:
        return column.astype(np.float64, copy=False)

    return np.array(
        [value if type(value) in (int, float) else np.nan for value in column],
        dtype=np.float64,
    )


def sql_like(pattern, value):
    """SQLite's `value LIKE pattern`: % and _ wildcards, ASCII case-insensitive."""
    if value is None:
        return None

    regex = "".join(
        ".*" if char == "%" else "." if char == "_" else re.escape(char)
        for char in pattern
    )
    return re.fullmatch(regex, value, flags=re.IGNORECASE | re.DOTALL) is not None


class VariantTable:
    """
    Every row of beatmap_variants, in rowid order (the order a full table scan
    returns them in), plus the beatmaps metadata for each beatmap.

    Numeric columns are int64/float64 arrays when every value has that type,
    so values come back as the same Python ints and floats SQLite returned.
    Text columns are stored as codes into a list of distinct values.
    Anything else (NULLs, mixed types) falls back to an object array.

    nm_predictions holds each beatmap's NM variant classifier probabilities,
    indexed by beatmap_id code: a [beatmaps, 5] float64 array with 0.0 for
    NULL, and has_nm_prediction marks the beatmaps that have a row.
    """

    def __init__(self, columns, categories, float_columns, metadata, nm_predictions, has_nm_prediction):
        self.columns = columns
        self.categories = categories
        # Numeric columns as float64 with NaN for NULL, for filtering. int64
        # columns (which have no NULLs) stay int64; float_column() converts.
        self.float_columns = float_columns
        # Metadata arrays indexed by beatmap_id code.
        self.metadata = metadata
        self.nm_predictions = nm_predictions
        self.has_nm_prediction = has_nm_prediction
        self.row_count = len(columns["variant_id"])

    @classmethod
    def load(cls, conn):
        start = time.perf_counter()
        names = VARIANT_COLUMNS + FILTER_ONLY_COLUMNS
        selects = [f"CAST({name} AS TEXT)" if name == "beatmap_id" else name for name in names]

        # One scan in rowid order, converted chunk by chunk so the whole table
        # never exists as Python objects at once. (ORDER BY rowid matters: a
        # query that only needs indexed columns can return them in index order.)
        cursor = conn.execute(f"SELECT {', '.join(selects)} FROM beatmap_variants ORDER BY rowid")
        chunks = {name: [] for name in names}
        text_indexes = {name: {} for name in TEXT_COLUMNS}

        while rows := cursor.fetchmany(LOAD_CHUNK_SIZE):
            for name, values in zip(names, zip(*rows)):
                if name in TEXT_COLUMNS:
                    index = text_indexes[name]
                    chunks[name].append(
                        np.fromiter(
                            (index.setdefault(value, len(index)) for value in values),
                            dtype=np.int32,
                            count=len(values),
                        )
                    )
                else:
                    chunks[name].append(_numeric_array(values))

        columns = {name: _concatenate(chunks[name]) for name in names}
        categories = {name: list(text_indexes[name]) for name in TEXT_COLUMNS}

        # Like SQLite, NULLs (and text) never pass a numeric filter. int64
        # columns have no NULLs, so they're used as-is instead of a float64
        # copy (~23MB each); comparing them gives the same results.
        float_columns = {
            name: columns[name] if columns[name].dtype == np.int64 else _float_array(columns[name])
            for name in names
            if name not in TEXT_COLUMNS
        }

        beatmap_codes = {beatmap_id: code for code, beatmap_id in enumerate(categories["beatmap_id"])}
        metadata = {field: np.full(len(beatmap_codes), None, dtype=object) for field in METADATA_FIELDS}

        rows = conn.execute(
            "SELECT CAST(beatmap_id AS TEXT), title, artist, creator, version FROM beatmaps"
        )

        for beatmap_id, *fields in rows:
            code = beatmap_codes.get(beatmap_id)

            if code is not None:
                for field, value in zip(METADATA_FIELDS, fields):
                    metadata[field][code] = value

        nm_predictions = np.zeros((len(beatmap_codes), len(PREDICTION_COLUMNS)), dtype=np.float64)
        has_nm_prediction = np.zeros(len(beatmap_codes), dtype=bool)

        rows = conn.execute(
            f"""
            SELECT CAST(bv.beatmap_id AS TEXT), {", ".join(f"vp.{name}" for name in PREDICTION_COLUMNS)}
            FROM beatmap_variants bv
            JOIN variant_predictions vp
                ON vp.variant_id = bv.variant_id
            WHERE bv.mods = 'NM'
            """
        )

        for beatmap_id, *probabilities in rows:
            code = beatmap_codes.get(beatmap_id)

            if code is not None:
                nm_predictions[code] = [0.0 if value is None else value for value in probabilities]
                has_nm_prediction[code] = True

        table = cls(columns, categories, float_columns, metadata, nm_predictions, has_nm_prediction)
        logger.info("Loaded %d variants into columns: %.2fs", table.row_count, time.perf_counter() - start)
        return table

    def category_mask(self, column, predicate):
        """
        Boolean mask over the distinct values of a text column, for use as
        mask[codes]. predicate follows SQL logic: None (NULL) counts as False.
        """
        return np.array([bool(predicate(value)) for value in self.categories[column]], dtype=bool)

    def codes_of(self, column, values):
        """Codes of the given values in a text column; unknown values are skipped."""
        index = {value: code for code, value in enumerate(self.categories[column])}
        return np.array([index[value] for value in values if value in index], dtype=np.int64)


class VariantRows(Sequence):
    """
    A selection of table rows, in order, read as variant dicts.

    Indexing or slicing builds dicts only for the requested rows, so a ranked
    result of millions of variants costs a few numpy arrays until a page of
    it is read. extra_columns (arrays aligned with rows) are added after the
    variant columns, followed by the beatmap metadata when with_metadata is set.
    """

    def __init__(self, table, rows, extra_columns=None, with_metadata=False):
        self.table = table
        self.rows = rows
        self.extra_columns = extra_columns or {}
        self.with_metadata = with_metadata

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, index):
        if isinstance(index, slice):
            return self._build_dicts(index)

        position = range(len(self))[index]
        return self._build_dicts(slice(position, position + 1))[0]

    def __iter__(self):
        for start in range(0, len(self), ITERATION_CHUNK_SIZE):
            yield from self[start : start + ITERATION_CHUNK_SIZE]

    def codes(self, column):
        return self.table.columns[column][self.rows]

    def float_column(self, column):
        return self.table.float_columns[column][self.rows].astype(np.float64, copy=False)

    def _build_dicts(self, selection):
        table = self.table
        rows = self.rows[selection]
        keys = list(VARIANT_COLUMNS)
        values = []

        for column in VARIANT_COLUMNS:
            data = table.columns[column][rows]

            if column in TEXT_COLUMNS:
                categories = table.categories[column]
                values.append([categories[code] for code in data.tolist()])
            else:
                values.append(data.tolist())

        for column, data in self.extra_columns.items():
            keys.append(column)
            values.append(data[selection].tolist())

        if self.with_metadata:
            beatmap_codes = table.columns["beatmap_id"][rows]

            for field in METADATA_FIELDS:
                keys.append(field)
                values.append(table.metadata[field][beatmap_codes].tolist())

        return [dict(zip(keys, row)) for row in zip(*values)]
