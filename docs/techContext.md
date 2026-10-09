# Tech Context

## Stack
- Backend: Python 3.12, FastAPI + uvicorn, Pydantic v2, httpx (async), `google-auth` (service account), `google-genai` SDK nếu hỗ trợ đủ Omni/Veo trên Vertex (xem Open #1), PyYAML (manifest), pytest + hypothesis, ruff.
- Frontend: Vite + React 18 + TypeScript, TanStack Query, Zustand (state phiên), form tự dựng từ manifest (không dùng thư viện form schema ngoài), vitest + Testing Library.
- Quản lý gói: `uv` (backend), `pnpm` (frontend). Một `Makefile`: `make dev`, `make test`, `make verify`, `make lint`.
- Realtime: SSE (`/api/events`) cho tiến độ job. Không WebSocket (YAGNI).
- Không database, không Redis, không Docker bắt buộc. Job runner = asyncio trong process.
- Kiểu dữ liệu chung: backend phát OpenAPI; frontend sinh type bằng `openapi-typescript`. Manifest là nguồn duy nhất cho form (backend phục vụ `/api/manifests`).

## Constraints
- Local-first, 1 người dùng, bind `127.0.0.1` mặc định; `--lan` bắt buộc token ngẫu nhiên (requirements D1).
- Key provider chỉ ở backend (`data/providers.json`, quyền 600, trong `.gitignore`), không xuất hiện trong API response/log (D3, guardrail).
- Không DB; file bền duy nhất: `data/providers.json`, `presets.json`, `prompts.json`, `prices.json`. Output gen ở `tmp/` và bị dọn khi tắt app (D2).
- Provider V1 chỉ Vertex AI qua service account JSON (D6). OpenAI, Seedance là V1.5 qua cùng interface adapter.
- Tính tiền thật: test tự động không được gọi API trả phí trừ khi `LIVE=1`.
- Thông số model là dữ liệu (manifest), không hardcode trong code (requirements Norms).

## Decisions (kèm lý do)
- **Manifest YAML + backend phục vụ, frontend render** — vì form phải khớp validate backend; tránh duy trì schema ở 2 ngôn ngữ (Python và TS).
- **Constraint là luật khai báo (`when/then/reason`)**, backend là bên quyết định cuối, frontend chỉ phản chiếu để ẩn/khóa field — vì "ép duration=8 khi 1080p" phải đúng ở cả 2 nơi và test được độc lập.
- **N biến thể = N job độc lập**, trừ khi model có số lượng native (Veo `sampleCount`) và mọi tham số khác giống nhau — vì phần lớn model không có `n` và seed không tái lập.
- **SSE thay vì polling từ trình duyệt** — job dài vài phút, một kết nối đơn giản hơn.
- **Tải file về `tmp/` ngay khi job xong** — URL provider hết hạn (Seedance 24h, Gemini 2 ngày) và Vertex có thể trả bytes.
- **Giữ nguyên file gốc, metadata đi kèm bằng JSON sidecar** — re-encode có thể phá SynthID/C2PA.
- **Ưu tiên REST qua httpx + google-auth nếu SDK chưa phủ Omni (Interactions API)** — quyết định ở plan sau khi kiểm SDK.

## Open (cần kiểm ở plan/kickoff)
1. SDK `google-genai` có hỗ trợ Omni Interactions và Veo `predictLongRunning` trên Vertex chưa; nếu không dùng REST thuần.
2. Omni trên Vertex có bắt buộc GCS bucket không (requirements Open #1) → quyết định `storage` option trong `providers.json`.
3. Quota Vertex thực tế của project user để đặt `limits.maxConcurrent` mặc định.
