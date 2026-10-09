# Architecture / Spec (nguồn sự thật)

## Deployment server B (2026-10-09)
- Chạy một replica FastAPI sau Traefik HTTPS trên server B; build frontend vào image bằng lockfile. `gen-ai.nexpo.vn` phục vụ frontend và proxy API cùng origin; `api-genai.nexpo.vn` phục vụ backend qua cùng container, không thêm CORS hoặc gửi provider key xuống browser.
- Bắt buộc LAN access token ngẫu nhiên, chỉ lưu ở file runtime ngoài Git; không dùng demo trên production. Không đưa `data/providers.json`, key local hoặc output vào image/repo; cấu hình provider mới qua UI sau deployment.
- Khi token được cấp qua `AIGEN_TOKEN`, startup chỉ thông báo đã cấu hình, không in token vào container log. Chế độ LAN local tự sinh token vẫn hiển thị một lần để người dùng kết nối.
- Data và output lưu bằng Docker volume độc lập; không thêm DB. Chỉ gắn network Traefik hiện hữu, không publish port backend ra host; không thay cấu hình các ứng dụng khác. Healthcheck không gọi API generation.
- Giữ lịch sử repository `tsxcorp/gen-ai`; deploy snapshot code đã kiểm tra, không force-push. Domain có DNS A về server B; TLS dùng resolver hiện hữu `letsencrypt`.

## Hardening sau review tiếp tục (2026-10-08)
- Hủy trong lúc ghi output bằng worker thread phải shield/drain worker trước khi trả cancellation và thả lease/slot. Xóa cả file hiện tại chưa register và file đã ghi khi thất bại; không re-encode bytes.
- Luật drain áp dụng cả ghi chunk streaming Vertex và HTTP dùng chung OpenAI/BytePlus: không đóng file hoặc trả lease khi worker ghi chunk còn chạy.
- Deadline poll bao gồm call và backoff/interval: không bắt đầu poll sau deadline, call in-flight có remaining-time timeout, không chấp nhận done quá deadline. Timeout vẫn giữ operation id và không submit lại.
- Giữ policy invariant 14 hiện tại: post-submit tối đa `max(2, maxAttempts)` lần retry ngoài lần gọi đầu (không phải tổng calls); không đổi cấu hình/retry policy trong vòng này. Review nêu ambiguity tên setting nhưng không tự đổi semantics đã spec hóa.

## Xem media toàn màn hình (2026-10-08)
- Mỗi asset ảnh/video trong lưới và so sánh có nút xem toàn màn hình riêng, không cản controls video hay chọn/tải kết quả.
- Mở viewer phủ viewport, giữ nguyên tỷ lệ bằng contain, video có controls và không autoplay. Có nút đóng, Esc, quản lý focus và trả focus về nút mở.
- Yêu cầu browser fullscreen từ thao tác người dùng; nếu API không hỗ trợ/bị từ chối, viewer vẫn xem lớn trong viewport và báo trạng thái. Đóng chỉ thoát fullscreen do viewer sở hữu.
- Dùng nguyên URL asset xác thực cookie, không key/query token, không re-encode, không gọi generation API hay thay trạng thái downloaded.

Dẫn xuất từ `docs/requirements.md` (ký hiệu `R-D#` = quyết định, `R-US#` = user story, `R-Never` = guardrail). Muốn đổi hành vi: sửa file này trước, rồi mới sửa code.

## Upload và Auto tỷ lệ edit (2026-10-08)
- `ui/FileDropzone` dùng chung cho ảnh và key JSON; nhận accept, giới hạn dung lượng/số file, trạng thái disabled/busy và callback. Drag/drop, chọn file bằng bàn phím; paste ảnh chỉ trong vùng focus của uploader ảnh. Không đọc clipboard toàn cục, không preview nội dung key.
- `ReferenceUpload` giữ ảnh chờ ở client, preview qua object URL và revoke khi thay/gỡ/unmount. Chỉ gửi multipart sau consent; giữ cảnh báo ảnh có người. Giới hạn 20 MB/file và maxItems từ manifest; mỗi ảnh gửi độc lập, giữ ảnh đã thành công nếu ảnh tiếp theo lỗi; không nhân đôi khi bấm liên tiếp. Không chuyển đổi file ảnh.
- Panel tách image/imageList ra thành khối ảnh đầu vào ngay sau prompt, không phụ thuộc level advanced hoặc accordion đóng. Trường unsupported hoặc không thuộc mode vẫn ẩn.
- Auto là lựa chọn UI riêng (không thêm vào params hay manifest provider), mặc định khi vào edit. Kích thước đọc bằng decoder ảnh của trình duyệt; ảnh đầu tiên trong slot ảnh làm nguồn, kể cả ảnh được Reuse. Metadata width/height/name chỉ ở client, request vẫn gửi asset id.
- Với trường ratio có values trong manifest: chọn giá trị có sai lệch `abs(log(candidate/source))` nhỏ nhất, khớp thì giữ đúng tỷ lệ; trường size WxH dùng sizeRule để chọn kích thước hợp lệ gần tỷ lệ gốc và diện tích mặc định. Hiển thị nguồn, kích thước và cảnh báo xấp xỉ. Không gửi Auto/adaptive thay cho tỷ lệ suy ra, không fallback âm thầm khi thiếu/không đọc được ảnh.
- Dùng cùng params cụ thể cho resolve, estimate, raw payload và submit. Khi Auto không suy ra được thì chặn Generate; manual vẫn hoạt động; preset/reuse lưu params cụ thể và giữ manual để không thay đổi request đã lưu. Ratio/size sweep xung đột với Auto phải báo rõ và chặn thay vì âm thầm bỏ qua.
- Không đổi API/config file, không gọi API trả phí trong kiểm thử. Giữ bảo mật key, consent, giới hạn upload và luật tính giá hiện tại.
- Auto chỉ áp dụng model ảnh có mode edit và trường ratio hoặc sizeRule phù hợp. Nguồn là ảnh đã upload thành công đầu tiên theo thứ tự slot/list; ảnh đang chờ consent không tham gia. Ratio lấy từ values đang allowed; tiebreak giữ thứ tự manifest. Với WxH, duyệt kích thước bội multipleOf trong mọi bound sizeRule; ưu tiên sai lệch log-ratio nhỏ nhất rồi sai lệch log-diện tích mặc định, cuối cùng thứ tự width/height tăng dần. Không có ứng viên hợp lệ thì chặn Auto. Luật force luôn có ưu tiên và phải hiển thị giải thích.
- Consent reset khi đổi tập file chờ. Upload thành công được gắn theo thứ tự, lỗi giữa chừng giữ kết quả đã gắn và chỉ retry phần chưa thành công. Hủy/unmount/chuyển model/slot không được gắn kết quả muộn. JSON chỉ đi endpoint cấu hình, không đi asset upload, không hiện nội dung key hoặc lưu vào browser persistence/log.
- Đổi ảnh/Auto/params/sweep vô hiệu confirmation cũ; Generate và phím tắt phải dùng cùng gate. Metadata dimensions tải muộn phải kiểm id/model còn hiện hành trước khi cập nhật. UI có focus bàn phím, mục tiêu bấm uploader/mode ≥44px, responsive và reduced-motion.

## System boundaries
### Concurrency và token Vertex (2026-10-08)
- Chẩn đoán offline: client hiện tại không single-flight refresh; 8 caller đồng thời với credential hết hạn tạo 8 refresh. Đây là lỗi đồng thời xác nhận được; chưa có log gốc để khẳng định mọi TransportError của user đều do race này.
- `VertexClient.token()` cache token hợp lệ, chia sẻ một asyncio task refresh cho toàn bộ waiter bằng shield; không tạo một worker thread cho từng waiter. Token exchange dùng requests Session dùng lại, timeout hữu hạn (không vượt HTTP timeout của client, tối đa 30s). Hủy một waiter không hủy task chung; close chờ task và đóng cả session đồng bộ/HTTP pool, không tạo client mới sau close.
- Google TransportError và RefreshError retryable trong token acquisition được map network với before_send=true vì request Vertex hiện tại chưa được gửi. Nếu đã có operation trước đó thì chỉ retry poll/download, không submit lại. Permanent RefreshError/config failure vẫn auth. Reason an toàn: timeout, TLS, proxy, DNS hoặc connection; không echo chuỗi exception gốc/key/token/URL chứa secret. Dùng budget/backoff submit hiện có, không thêm retry lồng vô hạn.
- AppContext giữ client dùng chung theo provider/config generation cho các adapter job. PUT/DELETE invalidate đúng provider, không đổi providers.json/schema. JobManager lease client theo identity suốt submit/poll/download; client retired chỉ đóng sau lease cuối, deduplicate close, track cleanup tasks để shutdown chờ đủ.
- Limiter giữ model/concurrencyGroup/rpm hiện có và thêm trần provider lấy max(maxConcurrent) từ manifest provider. Acquire model/group trước rồi provider; chỉ đọc inputs sau cả hai slot. Concurrency xuyên mọi batch, không hardcode quota/model/provider trong code; không tăng quota Google.
- Runner dọn completed asyncio task khi job kết thúc, nhưng giữ Job/Batch/result theo UX hiện có. Cancel/retry/blocked/cost gates giữ nguyên, không gửi lại operation đã được chấp nhận.
- Lease phải được đăng ký cùng lookup adapter trước await đầu tiên; remote cancel có lease riêng và task được track. Endpoint test/enhance vẫn dùng client standalone và tự close, không mượn pool job. Shutdown chặn job/lease mới, cancel/gather runner và remote cancel, rồi drain refresh/cleanup trước close identity một lần. Cap provider áp dụng xuyên cả client generation cũ/mới; đây là policy app bảo thủ, không phải quota Google đã kiểm live.

```
Browser (React) ──HTTP/SSE──► FastAPI (127.0.0.1)
                               ├─ manifests/*.yaml   (model + tham số + luật + giá)
                               ├─ data/*.json        (providers, presets, prompts, prices)
                               ├─ tmp/               (asset đang giữ, dọn khi tắt app)
                               └─ Adapters ──► Vertex AI (Gemini image, Omni, Veo, Gemini text)
```
Trong hệ thống: UI, API, job runner, adapters, ước giá, lưu file cấu hình. Ngoài hệ thống: Vertex AI/GCP (xác thực bằng service account), GCS bucket (tùy chọn, xem Open). Không có DB, không có đăng nhập user (R-D1, R-D2).

## Cấu trúc thư mục
```
backend/app/
  main.py                 # FastAPI app, bind 127.0.0.1, token middleware khi --lan
  api/                    # routers: manifests, estimate, batches, jobs, assets, enhance,
                          #          presets, prompts, providers, uploads, events(SSE)
  core/
    manifest.py           # load + validate manifest (Pydantic)
    constraints.py        # áp dụng luật when/then → params hiệu lực, lỗi
    expand.py             # N / prompt list / sweep → danh sách JobSpec
    cost.py               # ước giá (khoảng) từ manifest.pricing + prices.json
    jobs.py               # Batch, Job, state machine, runner asyncio
    limiter.py            # semaphore + rate limit theo provider/model
    storage.py            # tmp/, dọn dẹp, sha256, zip
    config_files.py       # đọc/ghi data/*.json (atomic, chmod 600 cho providers)
  adapters/
    base.py               # interface ProviderAdapter
    vertex_image.py       # Gemini Nano Banana
    vertex_omni.py        # Gemini Omni 1.1 Flash
    vertex_veo.py         # Veo 3.1 / Fast / Lite
    vertex_text.py        # Prompt enhancer (Gemini text)
manifests/                # nano-banana-2.1.yaml, veo-3.1.yaml, omni-1.1-flash.yaml, ...
data/                     # providers.json (600), presets.json, prompts.json, prices.json
frontend/src/             # panel/ (ParamPanel, RawRequestTab), grid/, queue/, compare/,
                          # presets/, prompts/, settings/, store/
tests/                    # unit (backend), contract, property, live (LIVE=1)
```

## Core entities
- **ModelManifest**: `id, provider, kind(image|video), status(ga|preview|deprecated), sunsetDate, lastVerified, modes[], params[], constraints[], pricing, limits`.
- **Param**: `key, label, type(enum|int|float|bool|text|ratio|image|imageList), values/range, default, group, level(basic|advanced), appliesToModes[], providerPath, supported(bool)`.
- **Constraint**: `when{param:values}`, `then{param:value} | block`, `reason`. Hai loại: *force* (khóa giá trị), *forbid* (chặn tổ hợp).
- **GenerationRequest**: `modelId, mode, params{}, prompt, assets{slot→assetId}`.
- **Sweep spec**: `variants N, prompts[], axes[{param, values}] (≤2), seedMode(random|fixed|none)`.
- **Batch**: `id, createdAt, jobs[], estimate{minUsd,maxUsd}, confirmed(bool)`.
- **Job**: `id, batchId, modelId, requestedParams, effectiveParams, status, error{kind,message}, assets[], costEstimateUsd[min,max], attempts`.
- **Asset**: `id, path(tmp/...), mime, sha256, sizeBytes, kind(upload|output)`, kèm sidecar tham số khi xuất ZIP.
- **Preset / PromptTemplate / PriceEntry**: bản ghi trong file JSON, `PriceEntry.lastVerified`.

## Contracts (API)
Tất cả lỗi: `{error:{kind, message, details?}}`; `kind ∈ quota|blocked|invalid|network|timeout|auth|not_found|confirm_required`. HTTP: invalid 400, auth 401, not_found 404, confirm_required 409, quota 429, blocked 422, network 502, timeout 504. Lỗi validate body của FastAPI cũng trả `invalid` 400 (không echo giá trị đầu vào).

| Endpoint | In → Out | Lỗi chính |
|---|---|---|
| `GET /api/manifests` | → danh sách tóm tắt (id, kind, status, sunsetDate, lastVerified) | – |
| `GET /api/manifests/{id}` | → manifest đầy đủ (params, constraints, pricing) | not_found |
| `POST /api/resolve` | `{modelId, mode, params}` → `{effectiveParams, locked[{key,reason}], errors[]}` | invalid |
| `POST /api/estimate` | `{request, sweep}` → `{jobCount, minUsd, maxUsd, perJob[], warnings[]}` | invalid |
| `POST /api/batches` | `{request, sweep, confirmOverThreshold}` → `{batchId, jobs[], estimate, confirmed}` | invalid (vượt trần batch), `confirm_required` (409, `details{minUsd,maxUsd,thresholdUsd}`) nếu `estimate.maxUsd` > ngưỡng mà chưa confirm |
| `GET /api/batches/{id}` | → batch + job + trạng thái | not_found |
| `POST /api/batches/{id}/cancel` | → ok (job chưa gửi: canceled; đã gửi: best-effort) | – |
| `POST /api/jobs/{id}/retry` | → job mới | invalid (job `blocked` hoặc `invalid` không retry tự động; retry tay vẫn cho) |
| `GET /api/events` (SSE) | stream `job.updated`, `batch.updated` | – |
| `POST /api/uploads` | multipart + `{hasPerson:bool, consent:bool}` → Asset | invalid (có người mà thiếu consent) |
| `GET /api/assets/{id}` | → bytes (range) | not_found |
| `POST /api/zip` | `{assetIds[]}` → zip stream: file gốc + `<id>.json` tham số | not_found |
| `POST /api/enhance` | `{modelId, prompt}` → `{suggestion}` (không ghi đè) | quota, blocked |
| `GET/PUT /api/presets`, `/api/prompts` | CRUD, ghi `data/*.json` | invalid |
| `GET /api/providers` | → cấu hình **đã che** (`hasKey:true`, không trả nội dung) | – |
| `PUT /api/providers/vertex` | `{serviceAccountPath|json, projectId, location, gcsBucket?}` | invalid |
| `POST /api/providers/vertex/test` | → ok / auth error | auth |

## Adapter interface
```python
class ProviderAdapter(Protocol):
    def build_payload(self, job: JobSpec) -> dict          # dịch effectiveParams → payload thật (cũng dùng cho tab "Request thô")
    async def submit(self, job) -> SubmitHandle            # lỗi chuẩn hóa về 5 loại
    async def poll(self, handle) -> PollResult             # running | done(outputs) | failed(error)
    async def download(self, outputs, dest: Path) -> list[Asset]
```
`build_payload` là hàm thuần để contract test và để tab request thô khớp 100% payload gửi đi (DoD).

## Key flows
1. **Dựng panel**: UI chọn model → `GET manifest` → render field theo `level/group` → mỗi lần đổi tham số gọi `POST /api/resolve` (hoặc áp luật cục bộ) để khóa/ẩn field kèm `reason`.
2. **Gen batch**: UI → `POST /api/estimate` → hiện "N job · $min–$max" → nếu > ngưỡng, chờ xác nhận → `POST /api/batches` → `expand` thành JobSpec → xếp hàng → limiter theo model → adapter `submit` → `poll` có jitter → `download` về `tmp/` → `succeeded` → SSE → lưới.
3. **Veo native count**: nếu mọi job chỉ khác `seed`/biến thể ngẫu nhiên và model có `maxVariantsNative>1`, gộp thành request `sampleCount=k` (tối đa 4); lỗi/ chặn áp dụng cả nhóm; giá tính theo k video.
4. **Lỗi**: `quota(429)` → retry backoff + jitter tới `maxAttempts`; `blocked` → trạng thái `blocked`, không retry; `invalid` → fail ngay; `network/timeout` → retry giới hạn.
5. **Reuse/Vary**: UI lấy `requestedParams` của job nạp vào panel (không gọi API).
6. **Ảnh sang video**: UI chuyển Asset sang panel video, set `mode=i2v` (first) hoặc `first_last`, slot `first_frame`/`last_frame`.
7. **Tải/ZIP**: gom assetIds → stream zip (file gốc nguyên bytes + JSON tham số).
8. **Tắt app**: dọn `tmp/`. Trình duyệt dùng `beforeunload` cảnh báo khi còn kết quả chưa tải hoặc job đang chạy.

## Invariants
1. Key không bao giờ ra khỏi backend: không có trong response, log, hay ZIP (R-Never).
2. Mọi payload gửi provider được validate theo manifest + constraints ở backend; client không đáng tin.
3. `effectiveParams` ≠ `requestedParams` nếu có luật *force*; cả hai được lưu trong Job và sidecar.
4. Một Job chỉ ở 1 trạng thái trong `queued → running → succeeded|failed|blocked|canceled`; chuyển trạng thái đơn điệu (không quay lại `running` sau `succeeded`), `retry` tạo Job mới.
5. `blocked` và `invalid` không bao giờ được tự động retry.
6. Số job trong batch ≤ `maxJobsPerBatch` (24, cấu hình được); giá ước `max` > `confirmThresholdUsd` (5, cấu hình được) thì cần xác nhận rõ.
7. Số job đồng thời tới 1 model ≤ `limits.maxConcurrent`.
8. File output không bị re-encode; metadata chỉ nằm ở sidecar JSON.
9. Manifest quá hạn `lastVerified` > 30 ngày hoặc `status=deprecated` luôn hiện cảnh báo trong UI.
10. `data/providers.json` có quyền `0600` và nằm trong `.gitignore`; nếu quyền lỏng hơn thì backend từ chối khởi động hoặc tự sửa, ghi cảnh báo.
11. Mỗi giá trị `Param` gửi đi tồn tại trong manifest của model đó; field `supported:false` không bao giờ vào payload.

## Truy vết yêu cầu → thành phần
| Yêu cầu | Thành phần |
|---|---|
| R-US1 panel theo model | `manifest.py`, `constraints.py`, `/api/resolve`, `frontend/panel` |
| R-US2/3 biến thể, sweep | `expand.py`, `jobs.py`, Veo native count (flow 3) |
| R-US4 ước giá | `cost.py`, `prices.json`, `/api/estimate` |
| R-US5 runner/retry/cancel | `jobs.py`, `limiter.py`, adapters |
| R-US6 lưới/so sánh/ZIP | `storage.py`, `/api/zip`, `frontend/grid,compare` |
| R-US7/8 reuse, ảnh→video | `frontend/store`, panel video slots |
| R-US9 preset/prompt | `config_files.py`, `/api/presets,prompts` |
| R-US10 enhancer | `vertex_text.py`, `/api/enhance` |
| R-US11 an toàn | `/api/uploads` consent, chuẩn hóa `blocked` ở adapters |
| R-US12 key/token | `providers` router, `main.py` token middleware |
| Rủi ro reload | `beforeunload`, SSE, cảnh báo UI |

## Mở / chưa quyết (đồng bộ với requirements Open)
- Omni trên Vertex bắt buộc `gcs_uri`? → quyết định `gcsBucket` có bắt buộc trong `providers.json` không; adapter hỗ trợ cả inline và GCS.
- Có gom được variants Veo native hay luôn tách job: giữ native vì đã [V] có `sampleCount`, kiểm bằng test live.
- Mô hình phụ thuộc chéo `mode ↔ params` (vd `lastFrame` cần `image`): biểu diễn bằng `appliesToModes` + constraint `forbid`.

## Cập nhật sau P1 backend (2026-10-07) — chốt các chỗ hợp đồng còn mơ hồ
Code là bản triển khai đầu tiên; các điểm dưới đây là **quyết định chốt trong lúc cài**, đã phản ánh vào code.

**Hình dạng request**
- `request = {modelId, mode?, prompt?, params{}, assets{slot→assetId|[assetId]}}`. `prompt` là param `prompt` (type text) của mọi manifest: gửi ở top-level `prompt` hoặc `params.prompt` đều được (cái nào có thì dùng, `params.prompt` luôn được điền lại cho từng job nên `requestedParams.prompt` có mặt).
- Slot ảnh (`first_frame`, `last_frame`, `reference_images`) đặt trong `assets` **hoặc** trong `params` bằng assetId; `effectiveParams`/`requestedParams` giữ assetId để Reuse nạp lại slot. Slot bắt buộc theo `mode` (`required:true` + `appliesToModes`) được kiểm khi estimate/batches, và cả ở `/api/resolve` khi đã có ít nhất một slot.
- `sweep = {variants|n (mặc định 1), prompts[], axes, seedMode(random|fixed|none, mặc định none), seed?}`; `axes` là `[{param, values}]` hoặc map `{param: values}`; tối đa 2 trục. Tổng job = `prompts × trục1 × trục2 × variants` ≤ `maxJobsPerBatch`.
- Param không hỗ trợ ở một model thì **không có trong manifest** (Omni không có `negative_prompt`/`seed`; Flash-Lite không có `thinking_level`/`google_search`). Gửi key lạ → `errors[]` (resolve) hoặc `invalid` (estimate/batches). Param không áp dụng cho `mode` hiện tại bị bỏ im lặng.

**Ước giá**
- Bảng giá nằm ở `manifest.pricing.table[{when,usd}]` (+ `unit: per_image|per_second`). `data/prices.json` (`entries[<modelId>]`) giữ `lastVerified`, `source`, `variance{min,max}`, `unknown` và **có thể ghi đè** `table`. Thiếu `data/prices.json` trong thư mục dữ liệu → đọc bản seed của repo (chỉ đọc, không ghi).
- Khoảng giá: param không nằm trong `effectiveParams` thì mọi dòng khớp đều tính (min..max); `variance` nhân thêm biên. Giá chưa biết → $0 kèm cảnh báo. `lastVerified` > `staleDays` (30) → cảnh báo "stale". Manifest quá hạn / deprecated / sắp sunset (≤60 ngày) / preview → `warnings[]`.
- `POST /api/estimate` → `{jobCount, outputCount, requestCount, minUsd, maxUsd, perJob[], warnings[], thresholdUsd, confirmRequired, maxJobsPerBatch}`. `jobCount` = số output yêu cầu (cái mà trần batch đếm); `requestCount` = số request tới provider sau gộp native (= số Job trong batch). Với Veo `variants=3` giống nhau: `jobCount 3`, `requestCount 1` (1 Job có `variantCount:3`, `assets[]` 3 phần tử, lỗi áp dụng cả nhóm).

**Endpoint thêm / đổi**
- `GET /api/jobs/{id}`; `GET /api/health` (không cần token); `GET/PUT /api/settings` (`confirmThresholdUsd`, `maxJobsPerBatch`, `staleDays`, `maxAttempts`, `retryBaseSeconds`, `retryMaxSeconds`, `pollIntervalSeconds`, `enhancerModel`).
- `POST /api/payload` `{request, sweep?}` → `{payloads:[{jobId, variantCount, axis, payload}]}`: đúng kết quả `build_payload` cho từng job (base64 ảnh nhúng bị thay bằng `<base64 N chars>`) — nguồn cho tab "Request thô". Chưa có luồng "sửa tay rồi gửi" (xem Known gaps).
- `GET/PUT /api/presets|prompts`: file và response có dạng `{"items":[...]}`; PUT nhận `{items}` hoặc mảng trần (thay toàn bộ). Thêm `PUT /api/{presets|prompts}/{id}` (upsert) và `DELETE`.
- `GET /api/providers` → `{vertex:{configured, hasKey, keySource: json|path|null, projectId, location, gcsBucket}}` — không trả đường dẫn key, email hay nội dung.
- `POST /api/uploads`: nếu thiếu cờ `hasPerson` thì coi như **có người** (cần `consent=true`); upload chỉ nhận png/jpeg/webp/heic/heif (kiểm magic bytes), ≤ 20 MB.
- `GET /api/events`: client gửi `Accept: text/event-stream` (EventSource) → stream sống, có `id:` và replay theo `Last-Event-ID` (buffer 200 sự kiện), keepalive 15 s. Client không gửi header đó → trả **snapshot hữu hạn** các sự kiện gần nhất rồi đóng (để HTTP client thường và TestClient không treo).
- `Job` có thêm `model` (alias của `modelId`), `variantCount`, `axis`, `note`, `bestEffortCancel`, `assetsIn`, `locked`.

**Adapter**
- `build_payload(job)` thuần: ảnh đầu vào lấy từ `job.inputs` (runner nạp bytes từ storage trước khi gọi). `download(outputs, dest)` trả `Downloaded{path,mime}` (ghi thẳng vào `tmp/run-*/`), runner mới đăng ký Asset — adapter không phụ thuộc storage.
- Tham số map sang payload bằng `Param.providerPath` (dotted) + `providerFormat` (vd `"{}s"`); riêng `prompt`, ảnh, `google_search`, `safety_threshold` do adapter xử lý.
- Omni: tham số `model_variant` (providerPath `model`) chọn `gemini-omni-1.1-flash-preview` hoặc `gemini-omni-flash-preview`; luật `when model_variant=gemini-omni-flash-preview then resolution=720p`. (Requirements nói "bản -preview chỉ 720p" mà không phân biệt hai id — xem Open.)

**Chạy / cấu hình**: `AIGEN_DATA_DIR`, `AIGEN_TMP_DIR`, `AIGEN_MANIFESTS_DIR`, `AIGEN_DEMO`, `AIGEN_DEMO_DELAY_MS`, `AIGEN_LAN`, `AIGEN_TOKEN` (cố định token thay vì ngẫu nhiên), `AIGEN_RETRY_BASE_S` (demo mặc định 0.3 s). `python -m app --lan` bind 0.0.0.0 + token. Token nhận qua `Authorization: Bearer`, `X-Access-Token` hoặc `?token=`; chỉ `/api/*` (trừ `/api/health`) bị chặn. Output nằm ở `tmp/run-<id>/`, cả thư mục bị xoá khi tắt app. `providers.json` quyền lỏng hơn 0600 → tự sửa + cảnh báo log.

**Open mới**: (1) "Omni -preview chỉ 720p": áp cho `gemini-omni-flash-preview` (theo báo cáo nghiên cứu) hay cho mọi id Vertex `-preview`? Hiện làm theo cách thứ nhất. (2) Giới hạn reference theo vai (object/character) chưa enforce, chỉ `maxItems` tổng.

## Invariants bổ sung sau review độc lập (2026-10-07) — nguồn: plans/reports/review-v1.md
12. **Host/Origin**: backend từ chối request có `Host` không thuộc allowlist (`127.0.0.1`, `localhost`, `[::1]`, + host đã cấu hình khi `--lan`) và request ghi (POST/PUT/DELETE) có `Origin` khác origin của app; bắt buộc `Content-Type: application/json` cho PUT/POST JSON (chống cross-site "simple request"). `/docs`, `/openapi.json`, `/redoc` cũng chịu token ở chế độ LAN.
13. **Vertex `location`** chỉ nhận `global` hoặc khớp `^[a-z]+-[a-z0-9]+[0-9]$`; `projectId` khớp `^[a-z][a-z0-9-]{4,28}[a-z0-9]$`; `gcsBucket` khớp quy tắc tên bucket. Host đích luôn phải kết thúc bằng `googleapis.com`; Bearer token không bao giờ gửi tới host khác.
14. **Không submit lại sau khi submit đã thành công**: lỗi `network`/`timeout` trong `poll`/`download` chỉ retry **poll/download** trên cùng operation, không gọi lại `submit`. Retry `submit` chỉ khi chưa nhận được handle và lỗi là `quota` hoặc lỗi kết nối trước khi gửi xong. Timeout poll → job `failed(timeout)` kèm operation id, không tự submit lại.
15. **Giá không xác định** (price unknown) không được làm `confirmRequired=false`: khi bất kỳ job nào có giá `unknown`, estimate trả `unknownPrice=true` và batch cần xác nhận.
16. **Nhóm Veo native**: số asset trả về < `variantCount` phải ghi `warnings` (vd `raiMediaFilteredCount`) trên job; UI hiển thị toàn bộ asset của job, tải/ZIP đánh dấu "đã tải" theo từng asset.
17. **Phân loại `blocked`** dùng mã lỗi/field có cấu trúc của provider (RAI filtered count, finishReason, code), không dò chuỗi con tự do; lỗi không nhận dạng được là `invalid` hoặc `network`, không phải `blocked`.
18. **Gemini thought images** không bao giờ được thu làm output.
19. **Bộ nhớ**: video không giữ nguyên trong RAM; stream tải xuống đĩa, sha256 tính khi ghi; tác vụ nặng chạy ngoài event loop.
20. **Token** không đi trong URL tài nguyên: asset được phục vụ qua cookie `HttpOnly; SameSite=Strict` do `/api/session` đặt sau khi xác thực bằng header; không log query string.
21. **Settings** `PUT /api/settings` có giới hạn cứng (`maxJobsPerBatch` ≤ 64, `confirmThresholdUsd` ≥ 0, các khóa lạ bị từ chối) và chỉ chấp nhận khóa đã tài liệu hóa, gồm `jobTimeoutSeconds`, `pollIntervalSeconds` (phải thực sự được dùng).
22. **Sweep**: trục trên `prompt` hợp lệ và áp vào từng job; trục không áp dụng cho mode hiện tại hoặc bị luật *force* gộp thành giá trị trùng bị loại/cảnh báo trước khi tính job; kiểm batch cap **trước** khi nhân `product`.
23. `Asset.path` (đường dẫn tuyệt đối) không xuất hiện trong API/SSE; `retry_job` áp lại batch cap và cổng xác nhận chi phí.
24. **Frontend**: `errors` từ `/api/resolve` là `{key, reason}[]`; có ErrorBoundary ở gốc; preset/prompt dùng endpoint upsert theo item và không PUT khi dữ liệu chưa tải xong; không dùng `crypto.randomUUID` nếu thiếu (fallback).

## Cập nhật sau sửa backend theo review (2026-10-07) — cách cài invariants 12-23
Ghi lại các quyết định cài đặt (không đổi ý nghĩa invariant; chỗ lệch nhẹ được đánh dấu **lệch**).
- **Guard (invariant 12, 20)**: một ASGI middleware `GuardMiddleware` (`app/main.py`) chạy theo thứ tự Host → Origin → Content-Type → trần upload → token. Allowlist Host: `127.0.0.1`, `localhost`, `::1` (+ `AIGEN_ALLOWED_HOSTS`, phẩy phân tách); ở `--lan` thêm mọi IP literal (không thể bị DNS-rebind) và hostname máy. **Lệch**: host `testserver` (mặc định của Starlette TestClient) chỉ được chấp nhận khi `AIGEN_DEMO=1`. Origin của POST/PUT/PATCH/DELETE phải là host thuộc allowlist (**mọi port**, vì Vite dev chạy cổng khác); `Origin: null` và `Sec-Fetch-Site: cross-site` bị từ chối (403, kind `forbidden`). Request có body phải `application/json` (415), riêng `/api/uploads` phải `multipart/form-data`; POST không body (retry/cancel/test/session) không cần Content-Type.
- **Token (invariant 20)**: chỉ nhận qua `Authorization: Bearer` hoặc `X-Access-Token`. **Lệch**: `?token=` **bị bỏ hẳn** (trước đây nhận để tương thích; không thể bảo đảm không lọt vào log proxy). `POST /api/session` (xác thực bằng header ở LAN; local không cần) đặt cookie `aigen_session` (`HttpOnly; SameSite=Strict; Path=/`, giá trị = HMAC dẫn xuất từ token, không phải token). Cookie chỉ được chấp nhận cho `GET|HEAD` `/api/assets/*`, `/api/events`, `/docs`, `/openapi.json`, `/redoc`; không dùng được cho API khác hay cho ghi. Log truy cập uvicorn bị lọc bỏ query string.
- **Vertex (invariant 13)**: `validate_vertex_fields` (PUT providers, và khi đọc `providers.json` sửa tay), `host()` kiểm location, `assert_google_url` chặn gửi Bearer tới host không phải `https://*.googleapis.com`; `follow_redirects=False`; `gcsUri` trả về được kiểm tên bucket. `location` có mặt trong body mà rỗng/sai → 400 (chỉ khi vắng mới mặc định `us-central1`). Mọi lỗi `serviceAccountPath` dùng một thông báo (không còn oracle).
- **Submit/poll (invariant 14)**: `AdapterError.before_send` đánh dấu lỗi chắc chắn xảy ra trước khi request gửi đi (`ConnectError`/`ConnectTimeout`/`PoolTimeout`). `submit` chỉ lặp khi chưa có handle và (`quota` hoặc `network` có `before_send`). Sau khi có handle: `poll`/`download` lặp có giới hạn (`max(2, maxAttempts)`) cho `network|timeout|quota` trên cùng operation; mọi lỗi sau submit (kể cả operation `failed` do quota) là kết thúc job, **không bao giờ submit lại**; timeout poll → `failed(timeout)` với operation id trong `error.message` và `Job.operationId`. Người dùng retry tay nếu muốn trả tiền lần nữa. Mã lỗi operation không nhận dạng được → `invalid` (không còn `network`).
- **Giá (invariant 15)**: `estimate.unknownPrice` + `perJob[].unknownPrice`; `confirmRequired = unknownPrice || maxUsd > threshold`; `POST /api/batches` trả 409 `confirm_required` (`details.unknownPrice`).
- **Nhóm Veo (invariant 16)**: `PollResult.warnings` (từ `raiMediaFilteredCount/Reasons`); runner thêm "received X of Y requested outputs"; lưu ở `Job.warnings` và sidecar ZIP.
- **blocked (invariant 17)**: chỉ khi trường có cấu trúc khớp enum chính xác (`error.details[].reason`, `promptFeedback.blockReason`, `finishReason`, `raiMediaFilteredCount`, `error.code/reason/status` của Omni) thuộc `BLOCK_REASONS`; văn bản tự do không bao giờ quyết định.
- **Bộ nhớ (invariant 19)**: `write_outputs` (async, `adapters/base.py`) ghi từng output ra đĩa ngoài event loop, sha256 tính khi ghi (`Downloaded.sha256/size_bytes`); base64 > 256 KB được giải mã từng khối thẳng ra file; GCS tải bằng `client.stream` (`VertexClient.stream_to_file`); JSON > 1 MB parse trong thread; `job.inputs` được giải phóng ngay sau `submit`; upload ghi từng khối + trần 20 MB kiểm ngay khi stream (middleware cắt body > 21 MB với 413).
- **Settings (invariant 21)**: `SETTING_LIMITS` ở `core/config_files.py`: `maxJobsPerBatch` int 1–64, `confirmThresholdUsd` 0–1e6, `maxAttempts` int 1–10, `pollIntervalSeconds` ≥ 0.05, `jobTimeoutSeconds` ≥ 1, v.v.; khóa lạ, bool, NaN/inf, số lẻ cho khóa int → 400; file `settings.json` sửa tay bị kẹp về giới hạn cứng và khóa lạ bị bỏ. Thêm `jobTimeoutSeconds` (mặc định 900) vào `DEFAULT_SETTINGS`. `pollIntervalSeconds` (mặc định 10) được runner dùng cho adapter Veo/Omni (`poll_interval_s=None`); **lệch**: Veo trước đây poll 15 s cứng, nay theo setting.
- **Sweep (invariant 22)**: trục `prompt` áp vào từng job (không được kết hợp với `sweep.prompts`); trục không áp dụng cho mode → bỏ kèm cảnh báo; giá trị trục trùng bị loại; combo cho effective params trùng (do luật *force* hoặc trục vô hiệu) bị bỏ kèm cảnh báo; trần job kiểm bằng `math.prod` **trước** `itertools.product` (trên số trục đã loại trùng, trước khi gộp theo luật force). Cảnh báo đi vào `estimate.warnings`. `redact_payload` chỉ che chuỗi toàn ký tự base64.
- **retry/Asset (invariant 23)**: `Asset.path` `exclude=True`. `POST /api/jobs/{id}/retry` nhận body tùy chọn `{confirmOverThreshold}`; áp lại cổng chi phí (giá ước của job > ngưỡng hoặc giá không xác định → 409). Trần batch cho retry: tổng output của batch **sau khi thay** job cũ (job đã bị retry thay, `Job.retryOf`, không tính) không được vượt `maxJobsPerBatch`; retry job trong batch đầy được, làm batch phình thì 400. Dọn tmp: thư mục chạy là `tmp/run-<pid>-<id>`; khi khởi động xoá mọi `run-*` mà pid không còn sống (hoặc tên không có pid). Tắt app / đổi provider đóng `httpx.AsyncClient` của adapter.
- **Constraint engine**: luật `block` chỉ đánh giá một lần trên trạng thái sau fixpoint; `then` dạng list là tập cho phép (giá trị ngoài tập → phần tử đầu; 1 phần tử = ép), khớp `frontend/constraints.ts`.
- **Manifest (review #12)**: thêm `verified` (mặc định true; hiện **false** ở cả 8 manifest) và `verifiedLive` (mặc định false). `lastVerified` nghĩa là ngày đối chiếu tài liệu, không phải gọi API thật. `manifest_warnings` luôn cảnh báo "payload chưa xác nhận bằng gọi API thật" khi `!verified || !verifiedLive`. Trường payload chưa kiểm được đánh `[?]` trong code (`responseModalities`, `thinkingConfig`) và manifest.
- **Job** thêm `warnings[]`, `operationId`, `retryOf`; manifest summary thêm `verified`, `verifiedLive`; `ApiError` kind mới `forbidden` (403).

## Cập nhật: đa provider (2026-10-07) — nguồn: requirements "Cập nhật phạm vi D6b"
- **Provider registry**: `vertex`, `openai`, `byteplus`. Mỗi provider có adapter(s), schema cấu hình riêng, trạng thái `configured`.
- **API (mở rộng, giữ tương thích)**:
  - `GET /api/providers` → `{ vertex:{configured,hasKey,authMethod:"service_account"|"adc"|null,projectId,location,gcsBucket}, openai:{configured,hasKey,organization,project}, byteplus:{configured,hasKey,region} }` (không bao giờ trả key).
  - `PUT /api/providers/{id}`: vertex `{authMethod, projectId, location, gcsBucket?, serviceAccountPath|json}` (authMethod=adc thì không cần key); openai `{apiKey, organization?, project?}`; byteplus `{apiKey, region?}`. Bỏ trống key khi đã có key = giữ nguyên.
  - `POST /api/providers/{id}/test` → `{ok, message}` (demo: ok). `DELETE /api/providers/{id}` xóa cấu hình.
  - `GET /api/manifests` mỗi mục thêm `provider` và `configured`. Demo mode: tất cả `configured:true`.
  - Batch/estimate-confirm cho model của provider chưa cấu hình → 400 kind `not_configured` (không submit). `/api/estimate` vẫn hoạt động.
- **Adapters mới**: `openai_image` (generations + edits với ảnh tham chiếu; response base64; lỗi `moderation_blocked` → `blocked`, 429 → `quota`); `byteplus_seedance` (`POST /contents/generations/tasks`, `GET .../{id}`; role first_frame/last_frame; `generate_audio`, `watermark`, `resolution`, `ratio`, `duration`, `return_last_frame`; hủy chỉ khi `queued`; tải video về ngay vì URL sống 24 giờ).
- **Invariants** áp dụng cho cả 3 provider: 1 (key không ra ngoài), 2, 5, 12–24. Bổ sung: 25. Mỗi provider có `limits.maxConcurrent` riêng (Seedance mặc định 3, OpenAI 5, Vertex 4) và cấu hình auth riêng; 26. xóa/đổi provider không ảnh hưởng key của provider khác; 27. manifest chưa gọi live có `verifiedLive:false` và UI hiện cảnh báo.
- **Frontend**: Settings có tab/khối riêng mỗi provider (badge configured, form riêng, Test riêng, Xóa); Studio sidebar gom theo provider, model chưa cấu hình mờ + liên kết "Cài đặt"; chip lọc theo provider; ô kết quả hiển thị provider+model.

## Cập nhật sau cài đặt đa provider backend (2026-10-07) — quyết định cài đặt, chỗ lệch ghi **lệch**
- **Registry**: `app/providers.py` (id, schema PUT, validate, mask, `is_configured`), `adapters/factory.make_client(provider, providers)` chỉ đọc entry của provider đó; PUT/DELETE chỉ ghi lại đúng 1 entry (invariant 26). `providers.json`: `vertex{authMethod,projectId,location,gcsBucket,serviceAccountJson|Path}`, `openai{apiKey,organization,project}`, `byteplus{apiKey,region}`; file Vertex cũ không có `authMethod` = `service_account`.
- **PUT**: `apiKey` rỗng/vắng khi đã có key = giữ nguyên; trường tùy chọn (`organization`, `project`, `region`) vắng = giữ, `null`/`""` = xóa; `region` mặc định `ap-southeast`, khớp `^[a-z]+(-[a-z0-9]+)*$` (≤32). `apiKey` 8–512 ký tự ASCII in được, không khoảng trắng (chống header injection); `organization`/`project` khớp `^[A-Za-z0-9_.:-]{1,128}$`. Lỗi validate không bao giờ echo giá trị. Chuyển Vertex sang `adc` thì **xóa** key đã lưu (không để bí mật thừa trên đĩa); `adc` + `json/serviceAccountPath` → 400. ADC dùng `google.auth.default`, gửi thêm header `x-goog-user-project` = `projectId` [?].
- **`GET /api/providers`** thêm `authMethod` (null khi chưa lưu) cho vertex; vẫn giữ `keySource`. Demo **không** ép `configured:true` ở endpoint này (chỉ ở `/api/manifests`).
- **`POST /api/providers/{id}/test`** → `{ok, message}`; demo `{ok:true, demo:true}`; chưa cấu hình → 400 `not_configured` (**lệch** nhẹ: trước đây vertex trả `auth`). OpenAI test = `GET /v1/models`; BytePlus = `GET /contents/generations/tasks?page_size=1` (đều miễn phí) [?]. `DELETE` idempotent, trả view đã che của provider đó. Id lạ → 404.
- **`not_configured`**: kind mới, HTTP 400. `POST /api/batches` và retry kiểm trước khi plan; `/api/estimate`, `/api/payload` vẫn chạy. Runner: provider bị xóa giữa chừng → job `failed(not_configured)`.
- **Manifest**: `GET /api/manifests[/{id}]` có `configured`; `Job.provider` (mới) để lưới hiển thị provider. `Limits.concurrencyGroup` (mới): các model cùng nhóm dùng **một** semaphore (Seedance 3 job đồng thời cho cả 4 model; OpenAI 5). `Param.suggestions` + `Param.sizeRule{allow,multipleOf,maxEdge,maxRatio,minPixels,maxPixels}` (mới) cho `size` của gpt-image (kiểu `text`, frontend cũ vẫn hiển thị được).
- **OpenAI**: `size` `auto` hoặc `WxH` bội của 16, cạnh dài ≤3840, tỉ lệ ≤3:1, 655,360–8,294,400 px (theo báo cáo [V]); mặc định `quality=medium`, `size=1024x1024` (không dùng `auto` mặc định vì giá không đoán được). `output_compression` chỉ gửi khi jpeg/webp; `background=transparent` ép `output_format` ∈ {png,webp}. Edit = multipart `image[]` tới `/v1/images/edits` [?]; chưa có mask. `n` = `variantCount` (maxVariantsNative=1 nên luôn 1). Lỗi `moderation_blocked`/`content_policy_violation` (trường `error.code`) → `blocked`; 429 → `quota`; 401/403 → `auth`.
- **Seedance**: 3 mode `t2v|i2v|first_last` (slot `first_frame`/`last_frame` như Veo), luật `mode∈{i2v,first_last} → ratio=adaptive` cho cả 4 model; `resolution`: 2.5 {480p,720p,1080p}, 2.0 {+4k}, Fast/Mini {480p,720p}; không có `seed`/`negative_prompt` trong manifest. **Lệch**: không có `return_last_frame` và không có `duration=-1` (auto) vì ước giá cần số giây; `duration` 4–30 (2.5) / 4–15 (2.0*). Video tải bằng `GET` có chữ ký, **không** gửi key; host tải phải là `https://*.bytepluses.com` (không IP, không userinfo) [?: nếu URL thật nằm ở miền khác sẽ bị từ chối]. `cancel(handle)`: runner gọi best-effort khi hủy job đang chạy; adapter chỉ `DELETE` khi task còn `queued`. Mã lỗi `*SensitiveContentDetected` (trường `error.code`) → `blocked`, `QuotaExceeded|RateLimitExceeded|…` → `quota`, mã lạ → `invalid` (không bao giờ transient).
- **Giá**: Seedance `per_second` (xấp xỉ token-giá theo bảng báo cáo §4, variance 1.0–1.15); gpt-image `per_image` xấp xỉ từ bảng gpt-image-2 1024² nhân theo diện tích (sunburst, variance 0.8–1.5); `flare` và `quality∈{xhigh,max,auto}` / size ngoài bảng → `unknownPrice` (cần xác nhận).
- **Phụ thuộc**: thêm `requests` vào `pyproject.toml`; thiếu nó thì `google.auth.transport.requests` ném ImportError nên mọi auth Vertex thật sẽ hỏng (lỗi có từ P1, chưa lộ vì chưa gọi live).
