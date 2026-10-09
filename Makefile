# AI Gen Studio. Backend: uv + FastAPI. Frontend (when present): pnpm + Vite.
.PHONY: dev backend frontend test verify lint

PORT ?= 8000
HAS_FRONTEND := $(wildcard frontend/package.json)

# Backend on 127.0.0.1:$(PORT); frontend dev server too if frontend/package.json exists.
# Backend alone in demo mode: AIGEN_DEMO=1 make dev
dev:
	@$(MAKE) --no-print-directory -j2 backend $(if $(HAS_FRONTEND),frontend,)

backend:
	cd backend && uv run uvicorn app.main:app --host 127.0.0.1 --port $(PORT) --timeout-graceful-shutdown 2

frontend:
	cd frontend && pnpm install --silent && pnpm dev

test:
	cd backend && uv run pytest tests/unit
	@if [ -f frontend/package.json ]; then cd frontend && pnpm test --run; fi

# Independent verification suite (owned by the tester role). Never calls paid APIs without LIVE=1.
verify:
	cd backend && uv run pytest tests/verify

lint:
	cd backend && uv run ruff check
	@if [ -f frontend/package.json ]; then cd frontend && pnpm lint; fi
