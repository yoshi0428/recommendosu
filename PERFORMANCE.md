# Performance

Two scripts in `/beatmap_recommender/benchmarks/` run the recommender offline, using the scores already stored for a player (no osu! API calls). 
Both load `beatmap_recommender/recommender.local.db` into memory read-only by default (`--db` to change it, `--player-id` for another player).

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

cProfile slows down code that makes millions of small calls, so use it to find where the time goes, and the plain timings to measure it. 
The snapshot script freezes the clock, because scores lose weight with age and two runs minutes apart would otherwise score slightly differently.

### Where the time goes

Worst-case request on my PC (specs in the [README](README.md)), timing `recommend_player_sync` (Python 3.13). 
*Original* is the code before any optimization, *numpy scoring* the first round, *columns* the second, and *cached data* the current code:

| Stage | Original | Numpy scoring | Columns | Cached data |
|---|---|---|---|---|
| Content similarity (outside `rank_variants`) | | | ~0.9s | 0.27s |
| Load and filter candidates (SQLite query, rows to dicts) | 8.5s | 8.5s | 0.05s | 0.05s |
| Classifier predictions | 0.5s | 0.5s | 0.3s | 0.02s |
| Difficulty scores | 1.7s | 1.7s | 0.24s | 0.24–0.5s |
| Score variants | 7.5s | 0.9s | 0.3s | 0.06s |
| Sort and truncate | 14.0s | 8.5s | 1.1s | 0.58s |
| **Total** | **~37s** | **~21.5s** | **~2.8s** | **~1.5s** |

Difficulty scores weren't changed in the last round; that row varies between measurement sessions. 
A typical request (the default settings, ~146k variants) went from ~3.2s to ~1.2s, then to ~0.5s. 
The `pp_potential` goal went from ~1.4s to ~0.5s for a typical request, and from ~1.7s to ~0.46s in the worst case.

- **Scoring** uses numpy arrays, and values that only depend on the beatmap or the mods (content similarity, classifier score, mod preference) are calculated once per distinct value, not once per variant.
- **Candidates** come from `beatmap_variants` held as numpy columns (`core_modules/variant_table.py`), and the filters are numpy masks instead of SQL. 
  The table is built once when the server starts (~12s, ~0.55GB of memory), from the in-memory database; the recommender never writes to `beatmap_variants`. 
  Building it frees ~0.5GB of temporary Python objects, which glibc would otherwise keep for the life of the process, so `load_variant_table()` hands it back with `malloc_trim`. 
  `tests/test_variant_ranking.py` checks the masks return the same rows, in the same order and with the same Python types, as the SQL they replaced.
- **Results are only turned into dicts when they're read.** `rank_variants` returns a `VariantRows`, which holds the ranked row numbers and score arrays, and builds dicts for the slice being read. 
  The result cache stores it as-is, so a page of 1,000 rows takes ~2ms to build, and a cached worst-case result takes ~0.12GB instead of ~6GB of 3 million dicts.
- **Static data is read once, at startup.** The NM candidate pool for content similarity comes from the variant table instead of a ~151k-row SQLite query per request (`get_maps`), 
  and the variant table also holds every beatmap's NM1 to NM5 probabilities (~6MB), so the classifier score is one array calculation instead of ~70 SQL queries and a Python loop per beatmap. 
  `tests/test_content_similarity.py` checks `get_maps` against the SQL it replaced.
- **`pp_potential` is computed for all variants at once** (`calculate_pp_potentials`) instead of in a per-variant loop (~10µs each). 
  To give bit-identical results it reproduces two details of the old Python arithmetic: `sum()` over floats uses compensated (Neumaier) summation since Python 3.12, and Python's `x ** 2` calls C `pow()` while numpy's multiplies, which can differ in the last bit.
- **Sorting** sorts on `final_score` alone and only re-sorts the rows that tie on it by the other keys, instead of a full `np.lexsort` pass per key. 
  `tests/test_variant_ranking.py` checks it against `np.lexsort` with many ties, NaNs and signed zeros.
- **Content similarity** takes the square root of each candidate's smallest squared distance, instead of one square root per seed × candidate pair (the same result, since the square root preserves order).

The output is identical to the original code (checked with `snapshot_recommender.py`, including smaller `neighbors_k` values, and the `pp_potential` goal).

### Python version

The backend runs on Python 3.15 with the JIT on (`PYTHON_JIT=1`), installed with uv in the Dockerfile, since the official `python:3.15-slim` image doesn't include the JIT. 
Measured in Docker with the backend's Dockerfile, changing only how Python is installed (Python 3.13.16 and 3.15.0, numpy 2.5.4 in all of them). 
*Official* is the `python:3.x-slim` image; *uv* is python-build-standalone installed with uv, the only one of these with the 3.15 JIT compiled in. 
Request times are the mean of 3 worst-case runs or 5 typical runs, with the production site running on the same PC, so differences of ~5% are noise. 
These were measured before the *cached data* round above, so the request times are higher than the current ones:

| | 3.13 official | 3.13 uv | 3.15 official | 3.15 uv | 3.15 uv, JIT on |
|---|---|---|---|---|---|
| Worst case, each result freed | 3.07s | 3.11s | 3.09s | 2.93s | 2.97s |
| Worst case, earlier results kept alive (as the result cache does) | 3.12s | 2.91s | 3.10s | 2.99s | 3.21s |
| Typical request (default settings) | 1.35s | 1.27s | 1.34s | 1.29s | 1.26s |
| Building the variant table at startup | 13.0s | 13.0s | 13.0s | 13.4s | 11.3s |

- **The Python version and the JIT don't change request times** anymore: the remaining work is numpy, which runs the same compiled code under every interpreter. 
  Garbage collection takes ~0.1s per worst-case request on every version.
- **The JIT only helps the startup table build** (~13% faster), the one remaining Python-heavy loop, and only once per restart. 
  It isn't available in the official image either: `python:3.15-slim` is built without `--enable-experimental-jit`, so `PYTHON_JIT=1` does nothing there.
- **Earlier, 3.15 was slower.** Before the variant table, every request created millions of Python objects and every cached result kept them alive. 
  3.15's garbage collector took longer the more objects were alive (worst case 23s on 3.13 vs 26s, 31s, then 34s on 3.15 as results piled up), and uv's Clang builds were ~10% faster than the official images. 
  Neither difference shows up now that results are numpy arrays.
- Other compilers (Numba, Cython, PyPy) or rewriting parts in another language wouldn't help much either, for the same reason as the JIT.

### Memory allocator (`MALLOC_ARENA_MAX=1`)

The server runs each request in an `asyncio.to_thread` worker thread, while the benchmark scripts run on the main thread, and that difference made production ~2-3x slower than the benchmarks. 
glibc gives worker threads their own malloc arenas, which hand the recommender's large numpy temporaries (e.g. the 64MB seed × candidate distance batches) back to the OS after each use, so every request page-faults that memory in again. 
The Dockerfile sets `MALLOC_ARENA_MAX=1`, so every thread uses the main arena. Measured in the backend container, through `asyncio.to_thread` like the server:

| | Default | `MALLOC_ARENA_MAX=1` |
|---|---|---|
| Content similarity | 1.4-2.1s | 0.23s |
| Typical request | ~1.17s | ~0.48s |
| Worst case | ~2.5s | ~1.33s |

`MALLOC_ARENA_MAX=2` only helps some requests. With one arena, threads share malloc's lock, which doesn't matter here: requests are limited by `RECOMMENDATION_CONCURRENCY` and spend their time in numpy, not in malloc. 
On the host (outside Docker) the same slowdown is smaller (~0.5s instead of ~0.22s for content similarity), so measure in the container when timing the server.
