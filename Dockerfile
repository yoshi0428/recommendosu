# Python 3.15 is installed with uv (python-build-standalone builds) rather
# than using python:3.15-slim, because only these builds include the JIT.
# The JIT makes building the variant table at startup ~13% faster; requests
# take about the same time either way. See "Python version" in the README.
FROM debian:trixie-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHON_JIT=1

# One malloc arena for every thread. Requests run in asyncio.to_thread worker
# threads, and glibc's per-thread arenas hand the recommender's large numpy
# temporaries back to the OS after each use, so every request page-faults
# them in again: a typical request took ~1.2s in a worker thread vs ~0.5s on
# the main thread. See "Python version" in the README.
ENV MALLOC_ARENA_MAX=1

# DEBUG also logs the recommendation config and each request's top 10.
ENV LOG_LEVEL=INFO

ENV UV_PYTHON_INSTALL_DIR=/opt/python
ENV PATH=/opt/venv/bin:$PATH

# python:3.15-slim includes these; osu! API requests need the CA certificates.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/*

# uv is mounted only while these steps run, so it isn't kept in the image.
RUN --mount=from=ghcr.io/astral-sh/uv:0.13.1,source=/uv,target=/usr/local/bin/uv \
    uv python install 3.15 && uv venv --python 3.15 /opt/venv

WORKDIR /app

COPY requirements.txt .

RUN --mount=from=ghcr.io/astral-sh/uv:0.13.1,source=/uv,target=/usr/local/bin/uv \
    uv pip install --no-cache --python /opt/venv/bin/python -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
