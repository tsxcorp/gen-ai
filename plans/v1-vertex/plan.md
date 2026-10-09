# Plan V1 — Vertex-first (dẫn xuất từ docs/architecture.md)

## Bố cục repo (chốt để các vai làm song song không đụng nhau)
```
backend/            pyproject.toml (uv, python>=3.11), app/ (package `app`), tests/unit (implementer), tests/verify (tester)
manifests/          *.yaml  (implementer backend)
data/               providers.json (gitignored), presets.json, prompts.json, prices.json
frontend/           Vite + React + TS (implementer frontend)
Makefile .gitignore README.md   (implementer backend)
```
- App factory: `app.main:create_app()`; chạy `uvicorn app.main:app` từ `backend/`.
- Env: `AIGEN_DATA_DIR`, `AIGEN_TMP_DIR`, `AIGEN_MANIFESTS_DIR` (mặc định `../data`, `../tmp`, `../manifests`), `AIGEN_DEMO=1` (mọi adapter → DemoAdapter giả lập; prompt chứa `[blocked]` → blocked, `[quota]` → quota lần đầu rồi ok, `[fail]` → invalid), `AIGEN_DEMO_DELAY_MS`.
- Frontend dev proxy `/api` → `127.0.0.1:8000`.

## Phases
| # | Việc | Chủ | Ghi chú |
|---|---|---|---|
| P1 | Backend lõi: manifest, constraints, expand, cost, jobs, limiter, storage, config_files, API, SSE, token middleware, DemoAdapter, 3 adapter Vertex (REST/httpx, chưa test live) + 5–7 manifest | backend-impl | Không viết tests/verify |
| P2 | Frontend: panel động từ manifest, tab request thô, lưới, queue, compare, presets, prompts, settings, enhance, beforeunload | frontend-impl | Chỉ biết hợp đồng API |
| P3 | Test độc lập từ requirements: acceptance, contract, property | tester | Không đọc code của backend; chỉ đọc requirements + bảng API |
| P4 | Gate: pytest verify, unit, tsc, build, smoke trên trình duyệt với demo | main | |
| P5 | Review độc lập (reviewer) → fix → retest | reviewer + impl | |

## Tiêu chí hoàn thành
Khớp `Definition of Done` trong `docs/requirements.md`, phần chứng minh được offline. Mục cần Vertex thật ghi rõ "chưa kiểm".
