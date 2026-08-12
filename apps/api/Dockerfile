# --- builder ---
FROM python:3.12-slim AS builder

WORKDIR /build

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY app ./app

# docker-compose.yml's api/worker services are dev-mode (--reload, bind
# mounts) and CLAUDE.md documents `docker compose exec api pytest` /
# `ruff` / `mypy` as the standard workflow against this exact image, so
# the dev extras belong in the image this Dockerfile builds. Gate C's
# docker-compose.prod.yml is expected to build a leaner variant.
RUN pip install --no-cache-dir --prefix=/install .[dev]

# --- runtime ---
FROM python:3.12-slim AS runtime

RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 1000 scanner \
    && useradd --uid 1000 --gid scanner --shell /bin/bash --create-home scanner

COPY --from=builder /install /usr/local

WORKDIR /app
COPY --chown=scanner:scanner . .

USER scanner

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
