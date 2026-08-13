FROM ghcr.io/astral-sh/uv:0.11.6 AS uv
FROM python:3.11.15-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/worker/.venv/bin:$PATH"

COPY --from=uv /uv /uvx /bin/

RUN groupadd --gid 10002 worker \
    && useradd --uid 10002 --gid worker --no-create-home --shell /usr/sbin/nologin worker \
    && install --directory --owner=10002 --group=10002 --mode=0750 /artifacts

WORKDIR /worker

COPY oasis_worker/pyproject.toml oasis_worker/uv.lock ./
RUN apt-get update \
    && apt-get install --yes --no-install-recommends gcc libc6-dev \
    && uv sync --frozen --no-dev --no-install-project \
    && apt-get purge --yes --auto-remove gcc libc6-dev \
    && rm -rf /var/lib/apt/lists/*

COPY oasis_worker/src ./src
RUN uv sync --frozen --no-dev

USER worker

VOLUME ["/artifacts"]

ENTRYPOINT ["python", "-m", "oasis_worker"]
