FROM node:20-bookworm-slim AS frontend
WORKDIR /build/frontend
RUN corepack enable
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN corepack prepare pnpm@9.15.9 --activate && pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm build

FROM ghcr.io/astral-sh/uv:0.8.22 AS uv
FROM python:3.12-slim-bookworm
COPY --from=uv /uv /uvx /usr/local/bin/
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev
COPY backend/app ./app
COPY manifests /app/manifests
COPY data/presets.json data/prices.json data/prompts.json data/settings.json /app/data/
COPY --from=frontend /build/frontend/dist /app/frontend/dist
RUN useradd --uid 10001 --create-home app && mkdir -p /var/lib/aigen/data /var/lib/aigen/tmp && chown -R app:app /var/lib/aigen
USER app
ENV PATH="/app/backend/.venv/bin:$PATH" AIGEN_DATA_DIR=/var/lib/aigen/data AIGEN_TMP_DIR=/var/lib/aigen/tmp
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--timeout-graceful-shutdown", "30"]
