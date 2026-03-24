# ── Stage 1: Build ──
FROM ghcr.io/astral-sh/uv:0.6-python3.12-bookworm-slim AS builder

WORKDIR /app

COPY pyproject.toml uv.lock .python-version ./

RUN uv sync --frozen --no-dev --no-install-project

COPY . .

# ── Stage 2: Runtime ──
FROM python:3.12-slim-bookworm

RUN groupadd --gid 1000 prime8 && \
    useradd --uid 1000 --gid prime8 --create-home prime8

WORKDIR /app

COPY --from=builder --chown=prime8:prime8 /app/.venv /app/.venv
COPY --from=builder --chown=prime8:prime8 /app/bot.py /app/config.py /app/
COPY --from=builder --chown=prime8:prime8 /app/cogs /app/cogs
COPY --from=builder --chown=prime8:prime8 /app/services /app/services
COPY --from=builder --chown=prime8:prime8 /app/utils /app/utils

RUN mkdir -p /app/data/state && chown prime8:prime8 /app/data/state

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

USER prime8

EXPOSE 9091

STOPSIGNAL SIGTERM

CMD ["python", "bot.py"]
