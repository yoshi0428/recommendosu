"""
The beatmap_variants table, kept as numpy columns. Thus the candidate filter
and the ranking do not make a Python object for each row.

The worst request (no star limits, all mods) selects about 3 million
variants. To read them from SQLite as tuples and change them into dicts took
longer than to rank them. A cached result of 3 million dicts used about 6GB.
Thus the table loads one time, the filters are numpy masks, and only the rows
of the page that the frontend asks for become dicts (see VariantRows).

Only the table of the recommender database (DB_PATH) is cached. The
recommender writes only to scores, never to beatmap_variants or beatmaps.
Any other connection, such as a test database, gets a new table on each call.
"""

import ctypes
import logging
import re
import threading
import time
from collections.abc import Sequence
from pathlib import Path

import numpy as np

from beatmap_recommender import database

logger = logging.getLogger(__name__)

# The columns of each variant dict, in the order that get_candidate_variants()
# always used.
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

# Columns that the filters use, but that are not in the variant dicts.
FILTER_ONLY_COLUMNS = ("year",)

TEXT_COLUMNS = ("beatmap_id", "beatmapset_id", "mods", "status")

METADATA_FIELDS = ("title", "artist", "creator", "version")

# The variant_predictions columns: the NM1-NM5 probabilities from the classifier.
PREDICTION_COLUMNS = ("nm1", "nm2", "nm3", "nm4", "nm5")

# The number of rows that each fetchmany() reads from SQLite during the load.
LOAD_CHUNK_SIZE = 65_536

# The number of rows that iteration over a VariantRows builds at a time.
ITERATION_CHUNK_SIZE = 10_000

# (database path, table) of the cached table.
_shared_table = None
_shared_table_lock = threading.Lock()


def get_variant_table(conn):
    """Return the variant table for conn. The table of the recommender database (DB_PATH) is cached."""
    global _shared_table

    if not database.is_db_path(conn):
        return VariantTable.load(conn)

    path = Path(database.DB_PATH).resolve()

    with _shared_table_lock:
        if _shared_table is None or _shared_table[0] != path:
            _shared_table = (path, VariantTable.load(conn))

        return _shared_table[1]


def load_variant_table():
    """Build the shared table now (for example, at startup), not on the first request."""
    conn = database.connect_db(read_only=True)

    try:
        get_variant_table(conn)
    finally:
        conn.close()

    _release_freed_memory()


def _release_freed_memory():
    """
    Give back to the OS the memory that the table build freed (about 440MB).

    The load reads each row as Python objects. These objects are freed when
    they are in numpy arrays, but glibc keeps the freed memory in its heap.
    With MALLOC_ARENA_MAX=1 (see the Dockerfile), the memory stays there for
    the life of the process. Systems without glibc (for example, macOS) skip
    this step.
    """
    try:
        libc = ctypes.CDLL("libc.so.6")
        libc.malloc_trim(0)
    except (OSError, AttributeError):
        pass


def _numeric_array(values):
    """Return an int64 or float64 array if all the values have that Python type. If not, return an object array."""
    array = np.array(values)

    if array.dtype == np.int64:
        return array

    # A mix of ints and floats also becomes float64. That would change the ints into floats.
    if array.dtype == np.float64 and not any(type(value) is int for value in values):
        return array

    return np.array(values, dtype=object)


def _concatenate(chunks):
    """Join the chunks of one column. If the chunks have different dtypes, use an object array."""
    if len({chunk.dtype for chunk in chunks}) > 1:
        # astype(object) changes numpy ints and floats back into Python ints and floats.
        chunks = [chunk.astype(object) for chunk in chunks]

    return np.concatenate(chunks) if chunks else np.empty(0, dtype=np.int64)


def _float_array(column):
    """Return the column as float64. A value that is not a number (NULL or text) becomes NaN."""
    if column.dtype != object:
        return column.astype(np.float64, copy=False)

    return np.array(
        [value if type(value) in (int, float) else np.nan for value in column],
        dtype=np.float64,
    )


def sql_like(pattern, value):
    """Do the SQLite `value LIKE pattern`: % and _ are wildcards, and ASCII case does not matter."""
    if value is None:
        return None

    regex = "".join(
        ".*" if char == "%" else "." if char == "_" else re.escape(char)
        for char in pattern
    )
    return re.fullmatch(regex, value, flags=re.IGNORECASE | re.DOTALL) is not None


class VariantTable:
    """
    All the rows of beatmap_variants, in rowid order (the order of a full
    table scan), plus the metadata of each beatmap from the beatmaps table.

    A numeric column is an int64 or float64 array if all its values have that
    type. Thus the values come back as the same Python ints and floats that
    SQLite returned. A text column is stored as codes into a list of its
    distinct values. Other columns (with NULLs or mixed types) are object arrays.

    nm_predictions holds the classifier probabilities of the NM variant of each
    beatmap, indexed by beatmap_id code. It is a [beatmaps, 5] float64 array,
    with 0.0 for NULL. has_nm_prediction marks the beatmaps that have a row.
    """

    def __init__(self, columns, categories, float_columns, metadata, nm_predictions, has_nm_prediction):
        self.columns = columns
        self.categories = categories
        # The numeric columns as float64 with NaN for NULL, for the filters.
        # An int64 column has no NULLs, so it stays int64. float_column() changes it.
        self.float_columns = float_columns
        # The metadata arrays, indexed by beatmap_id code.
        self.metadata = metadata
        self.nm_predictions = nm_predictions
        self.has_nm_prediction = has_nm_prediction
        self.row_count = len(columns["variant_id"])

    @classmethod
    def load(cls, conn):
        """Read the full table from conn into numpy columns."""
        start = time.perf_counter()
        names = VARIANT_COLUMNS + FILTER_ONLY_COLUMNS
        selects = [f"CAST({name} AS TEXT)" if name == "beatmap_id" else name for name in names]

        # Do one scan in rowid order, and change it chunk by chunk. Thus the full
        # table never exists as Python objects at one time. ORDER BY rowid is
        # necessary: a query that needs only indexed columns can use index order.
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

        # As in SQLite, a NULL (or text) never passes a numeric filter. An int64
        # column has no NULLs, so the code uses it directly, not as a float64
        # copy (about 23MB each). The comparisons give the same results.
        float_columns = {
            name: columns[name] if columns[name].dtype == np.int64 else _float_array(columns[name])
            for name in names
            if name not in TEXT_COLUMNS
        }

        beatmap_codes = {beatmap_id: code for code, beatmap_id in enumerate(categories["beatmap_id"])}
        metadata = {field: np.full(len(beatmap_codes), None, dtype=object) for field in METADATA_FIELDS}

        rows = conn.execute("SELECT CAST(beatmap_id AS TEXT), title, artist, creator, version FROM beatmaps")

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
        Return a boolean mask over the distinct values of a text column, to use
        as mask[codes]. predicate follows SQL logic: None (NULL) counts as False.
        """
        return np.array([bool(predicate(value)) for value in self.categories[column]], dtype=bool)

    def codes_of(self, column, values):
        """Return the codes of the values in a text column. Skip the values that the column does not have."""
        index = {value: code for code, value in enumerate(self.categories[column])}
        return np.array([index[value] for value in values if value in index], dtype=np.int64)


class VariantRows(Sequence):
    """
    A selection of table rows, in order, that reads as variant dicts.

    An index or a slice builds dicts only for the rows that it asks for. Thus a
    ranked result of millions of variants is only a few numpy arrays until the
    code reads a page of it. The dicts get the variant columns, then
    extra_columns (arrays in the same order as rows), then the beatmap metadata
    if with_metadata is set.
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
