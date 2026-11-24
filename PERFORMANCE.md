# Performance

Two scripts in `/beatmap_recommender/benchmarks/` run the recommender offline.
They use the scores that the database already has for a player. They do not send osu! API requests.
By default, the two scripts open `beatmap_recommender/recommender.local.db` read-only.
To use a different database, use `--db`. To use a different player, use `--player-id`.

```
### per-stage timings of the worst case (no star bounds, every mod combination: ~3 million variants)
PYTHONPATH=. python beatmap_recommender/benchmarks/profile_recommender.py

### the same request under cProfile, or a typical request (the default settings) instead
PYTHONPATH=. python beatmap_recommender/benchmarks/profile_recommender.py --cprofile
PYTHONPATH=. python beatmap_recommender/benchmarks/profile_recommender.py --typical

### check that a change leaves every recommendation exactly the same
git stash
PYTHONPATH=. python beatmap_recommender/benchmarks/snapshot_recommender.py save before.pkl
git stash pop
PYTHONPATH=. python beatmap_recommender/benchmarks/snapshot_recommender.py save after.pkl
PYTHONPATH=. python beatmap_recommender/benchmarks/snapshot_recommender.py compare before.pkl after.pkl
```

cProfile makes code with millions of small calls slower.
Use cProfile to find where the time goes. Use the plain timings to measure the time.

The snapshot script stops the clock.
This is necessary because the weight of a score decreases with its age.
Without this, two runs some minutes apart give slightly different scores.

### Where the time goes

The table shows the worst-case request on my PC (specifications in the [README](README.md)).
The measurement is the time of `recommend_player_sync` (Python 3.13).
The columns are:

- *Original*: the code before the optimization.
- *Numpy scoring*: the code after the first round of optimization.
- *Columns*: the code after the second round.
- *Cached data*: the current code.

| Stage | Original | Numpy scoring | Columns | Cached data |
|---|---|---|---|---|
| Content similarity (outside `rank_variants`) | | | ~0.9s | 0.27s |
| Load and filter candidates (SQLite query, rows to dicts) | 8.5s | 8.5s | 0.05s | 0.05s |
| Classifier predictions | 0.5s | 0.5s | 0.3s | 0.02s |
| Difficulty scores | 1.7s | 1.7s | 0.24s | 0.24–0.5s |
| Score variants | 7.5s | 0.9s | 0.3s | 0.06s |
| Sort and truncate | 14.0s | 8.5s | 1.1s | 0.58s |
| Total | ~37s | ~21.5s | ~2.8s | ~1.5s |

The last round did not change the difficulty scores. The time of this row changes between measurement sessions.

A typical request uses the default settings (approximately 146,000 variants).
Its time decreased from approximately 3.2 seconds to 1.2 seconds, and then to 0.5 seconds.

These are the changes:

- Scoring uses numpy arrays.
  Some values change only with the beatmap or the mods: the content similarity, the classifier score, and the mod preference.
  The recommender calculates these values one time for each different value, not one time for each variant.
- The candidates come from `beatmap_variants`, which the recommender keeps as numpy columns (`core_modules/variant_table.py`).
  - The filters are numpy masks, not SQL.
  - When the server starts, the recommender makes this table one time. This takes approximately 12 seconds and 0.55 GB of memory.
  - The recommender reads the table directly from the database file. It never writes to `beatmap_variants`.
  - The table build releases approximately 0.5 GB of temporary Python objects. Without action, glibc keeps this memory until the process stops. Thus, `load_variant_table()` releases it with `malloc_trim`.
  - `tests/test_variant_ranking.py` makes sure that the masks give the same rows as the old SQL. The rows must have the same sequence and the same Python types.
- Requests read the database file directly. They do not use a copy of the database in memory.
  - The variant table is the only copy of the data in memory.
  - Each request still sends some SQL queries to `scores`. These queries use indexes and take approximately 1.7 ms for a typical player.
  - This is the same time as from a copy in memory. The reason is that the page cache of the operating system keeps the pages that these queries read.
  - The old copy of the full SQLite file in memory (approximately 560 MB) had `beatmap_variants` two times. Also, the backend had to write each score to the copy and to the file.
  - The resident memory at startup decreased from approximately 1.17 GB to 0.61 GB. The peak decreased from approximately 1.63 GB to 1.06 GB.
  - Requests that do not change scores (for example, the benchmarks) open the file read-only.
- The recommender makes dicts from a result only for the rows that something reads.
  - `rank_variants` returns a `VariantRows` object. This object keeps the ranked row numbers and the score arrays.
  - It makes dicts only for the slice that is read.
  - The result cache keeps this object without a change. Thus, a page of 1,000 rows takes approximately 2 ms to make.
  - A worst-case result in the cache uses approximately 0.12 GB of memory. Before, it used approximately 6 GB for 3 million dicts.
- The recommender reads static data one time, at startup.
  - The NM candidates for content similarity come from the variant table. Before, each request sent a SQLite query of approximately 151,000 rows (`get_maps`).
  - The variant table also keeps the NM1 to NM5 probabilities of each beatmap (approximately 6 MB).
  - Thus, the classifier score is one array calculation. Before, it was approximately 70 SQL queries and a Python loop for each beatmap.
  - `tests/test_content_similarity.py` makes sure that `get_maps` gives the same result as the old SQL.
- Sorting sorts only on `final_score`.
  Then, it sorts again only the rows that have the same `final_score`, with the other keys.
  Before, it did a full `np.lexsort` pass for each key.
  `tests/test_variant_ranking.py` compares it with `np.lexsort` on data with many equal values, NaNs, and signed zeros.
- Content similarity calculates one square root for each candidate, from the smallest squared distance of that candidate.
  Before, it calculated one square root for each pair of seed and candidate.
  The result is the same, because the square root does not change the order.

The output is the same as the output of the original code.
`snapshot_recommender.py` makes sure of this, also with smaller `neighbors_k` values.

### Python version

The backend runs on Python 3.15 with the JIT on (`PYTHON_JIT=1`).
The Dockerfile installs Python with uv, because the official `python:3.15-slim` image does not include the JIT.

The measurements used the Dockerfile of the backend. Only the Python installation changed between them.
The versions were Python 3.13.16 and 3.15.0, with numpy 2.5.4 in all of them.

- *Official* is the `python:3.x-slim` image.
- *uv* is python-build-standalone, installed with uv. This is the only one that has the 3.15 JIT.

Each request time is the mean of 3 worst-case runs or 5 typical runs.
The production site ran on the same PC at the same time. Thus, differences of approximately 5% are noise.
These measurements were before the *cached data* round. Thus, the request times are higher than the current times.

| | 3.13 official | 3.13 uv | 3.15 official | 3.15 uv | 3.15 uv, JIT on |
|---|---|---|---|---|---|
| Worst case, each result freed | 3.07s | 3.11s | 3.09s | 2.93s | 2.97s |
| Worst case, earlier results kept alive (as the result cache does) | 3.12s | 2.91s | 3.10s | 2.99s | 3.21s |
| Typical request (default settings) | 1.35s | 1.27s | 1.34s | 1.29s | 1.26s |
| Building the variant table at startup | 13.0s | 13.0s | 13.0s | 13.4s | 11.3s |

- The Python version and the JIT do not change the request times now.
  The remaining work is in numpy. Numpy runs the same compiled code with all interpreters.
  Garbage collection takes approximately 0.1 seconds for each worst-case request with all versions.
- The JIT makes only the table build at startup faster (approximately 13%).
  This build is the last loop with much Python work, and it occurs only one time at each restart.
  The official image does not have the JIT. `python:3.15-slim` is built without `--enable-experimental-jit`. Thus, `PYTHON_JIT=1` has no effect in it.
- Before, 3.15 was slower.
  - Before the variant table, each request made millions of Python objects, and each cached result kept them in memory.
  - With more objects in memory, the garbage collector of 3.15 took more time.
  - The worst case took 23 seconds on 3.13. On 3.15, it took 26, 31, and then 34 seconds as the number of results increased.
  - Also, the Clang builds of uv were approximately 10% faster than the official images.
  - These differences do not occur now, because the results are numpy arrays.
- Other compilers (Numba, Cython, PyPy) or a different language for some parts also cannot help much. The reason is the same as for the JIT.

### Memory allocator (`MALLOC_ARENA_MAX=1`)

The server runs each request in an `asyncio.to_thread` worker thread.
The benchmark scripts run on the main thread.
Because of this difference, production was 2 to 3 times slower than the benchmarks.

glibc gives each worker thread its own malloc arena.
These arenas give the large numpy temporaries of the recommender back to the operating system after each use.
An example is the 64 MB batches of seed × candidate distances.
Thus, each request must page-fault this memory in again.

The Dockerfile sets `MALLOC_ARENA_MAX=1`. Thus, all threads use the main arena.
The measurements below are from the backend container, through `asyncio.to_thread`, as in the server:

| | Default | `MALLOC_ARENA_MAX=1` |
|---|---|---|
| Content similarity | 1.4-2.1s | 0.23s |
| Typical request | ~1.17s | ~0.48s |
| Worst case | ~2.5s | ~1.33s |

`MALLOC_ARENA_MAX=2` helps only some requests.

With one arena, the threads share the malloc lock. This is not a problem here, for two reasons:

- `RECOMMENDATION_CONCURRENCY` limits the number of requests at the same time.
- The requests use their time in numpy, not in malloc.

On the host (outside Docker), the same slowdown is smaller: approximately 0.5 seconds, not 0.22 seconds, for content similarity.
Thus, to measure the time of the server, do the measurement in the container.
