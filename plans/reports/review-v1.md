# Independent review v1 (read-only; backend ran only in demo mode on /tmp data dirs)

Status: DONE_WITH_CONCERNS. Tags: CONFIRMED = proved by code and/or reproduced against the demo backend; PLAUSIBLE = follows from code, not reproduced.

## Findings (ranked)

### 1. HIGH, CONFIRMED. No Host/Origin check + unvalidated `location` => DNS-rebinding can exfiltrate the Vertex access token or redirect all prompts/images to an attacker project
- `backend/app/main.py:49-92` has no TrustedHost/Origin check and no auth outside LAN mode. Repro: `curl -H 'Host: evil.example' :8012/api/providers` returns 200.
- `PUT /api/providers/vertex` (`api/providers.py:33-75`) accepts any string as `location`/`projectId`/`gcsBucket`. `vertex_common.host()` (`:46`) builds `https://{location}-aiplatform.googleapis.com`. Repro: location=`evil.example/x?` was stored and gives `https://evil.example/x?-aiplatform.googleapis.com/v1/projects/...`. `VertexClient.request` (`:107-110`) then sends `Authorization: Bearer <real access token>` to that host. Same in `vertex_veo._base`, `vertex_image._url`, `vertex_text.py:39`.
- Scenario: user has the app on 127.0.0.1:8000 and visits a hostile page. After rebinding, the page is same-origin, so it PUTs only `{"projectId":"p","location":"evil.example/x?"}`; the existing key is kept (`providers.py:69`). The next Veo job leaks a 1 h cloud-platform token. Alternatively it PUTs the attacker's own SA key and every later prompt and reference image lands in the attacker's GCP project.
- Even without rebinding, `POST /api/uploads` (multipart) and body-less POSTs (`/jobs/{id}/retry`, `/batches/{id}/cancel`, `/providers/vertex/test`) are cross-site "simple" requests (no CORS preflight). `PUT /api/settings` also works without a Content-Type header (`request.json()` ignores it), so settings (e.g. `confirmThresholdUsd`) can be rewritten once same-origin via rebinding.
- Also: the `serviceAccountPath` branch (`providers.py:61-66`) is a file-existence/JSON-shape oracle for arbitrary local paths (valid JSON that is not an SA key gives a different message than an unreadable file).
- Fix: Host allow-list (localhost/127.0.0.1/[::1] + the LAN host in LAN mode), reject cross-origin `Origin`, regex-validate location (`^[a-z0-9-]+$|global`) / projectId / bucket, require `Content-Type: application/json` on mutations. Remember the Vite proxy uses `changeOrigin:false` (Host stays localhost:5173), so the allow-list must cover dev.

### 2. HIGH, CONFIRMED. Any `/api/resolve` error crashes the whole UI (white screen)
- Backend returns `errors:[{key,reason}]` (`core/constraints.py:23,34`; reproduced: `{"errors":[{"key":"seed","reason":"must be within [0.0, 2147483647.0]"}]}`). Frontend types it as `string[]` (`api/types.ts:169`) and merges objects into the string list (`api/hooks.ts:58`: `errors.includes(e)` is always false for an object, then `errors.push(e)`). `GenerateFooter.tsx:31-33` renders `<li key={e}>{e}</li>`, so React throws "Objects are not valid as a React child". There is no ErrorBoundary.
- Scenario: type seed 99999999999 (or any value the local engine also rejects). The local engine adds a string, the server adds an object, the app unmounts. Unsent prompt and sweep state is lost, and results are lost on reload (they live only in the zustand store). The same applies to any server-only error (unknown param after Reuse, block rule).
- Fix: map server errors to `reason` strings (and dedupe by key); add an ErrorBoundary.

### 3. HIGH, CONFIRMED (cost). Poll/transport error after a successful Veo submit => full resubmit => double billing
- `core/jobs.py:228-239`: `submit()` then a `poll()` loop inside `_attempt`. Any exception from `poll()` (one transient `httpx.TransportError` -> kind `network`, a 5xx -> `network`, `timeout`) propagates to `_run` (`:195-217`), which retries the whole attempt, i.e. a NEW `predictLongRunning` (paid) while the first operation is still running. The same happens for the 900 s poll timeout (`:237`) and for a `network` error on `submit` whose response was lost.
- Cost: quota retries are free (429 means not accepted), network/timeout retries are not. Estimates and the confirm gate do not account for this.
- Fix: retry `poll` itself on transient errors (bounded) keeping the operation handle; only resubmit when `submit` never returned a handle; restrict resubmission to `quota` unless the error provably occurred before the request was sent.

### 4. MEDIUM, CONFIRMED. Unknown price => estimate $0 => confirm gate bypassed (invariant 6)
- `core/cost.py:48-50` returns `0,0` plus a warning when no row has a price; `api/planning.py:49` computes `confirmRequired = est["maxUsd"] > threshold` => false. Repro: `gemini-3.1-flash-lite-image` (manifest `table: []`, prices.json `unknown:true`), 24 variants => `{"minUsd":0,"maxUsd":0,"confirmRequired":false}`. Veo/Omni with a param combination not covered by the table behave the same.
- Fix: treat unknown as "needs confirmation" (`confirmRequired=true` when any job price is unknown), or block with an explicit ack.

### 5. MEDIUM, CONFIRMED. Veo native group (variantCount>1): UI shows only the first output, and "Tải" marks all as downloaded
- `frontend/src/grid/ResultCell.tsx:36,56-58` renders `job.assets[0]` only; `CompareModal.tsx:18` likewise. A Veo job with `variantCount:3` returns 3 assets (reproduced: 1 job, 3 assets), so 2 paid videos are reachable only through ZIP.
- `ResultCell.tsx:101` downloads one asset but `markDownloaded(job.assets.map(...))` marks all, so the `beforeunload` guard and the "download all unsaved" button stop protecting the other variants.
- Related, backend: `vertex_veo.parse_operation` (`:36-50`) ignores `raiMediaFilteredCount` when at least one video came back, and `jobs.py:244-250` never compares `len(files)` with `variant_count`. Group of 4 with 2 filtered => `succeeded` with 2 assets and no note, cost estimate still for 4.

### 6. MEDIUM, PLAUSIBLE. Gemini "thought images" collected as outputs
- `adapters/vertex_image.py:44-48` takes every `inlineData` part, only skipping `thought` for TEXT parts. With `thinking_level` set, Gemini image models can interleave thought (draft) images flagged `thought:true` (the research report notes "thought images not billed"). The job would get extra assets and the UI shows `assets[0]`, possibly a draft.
- Fix: skip parts with `part.get("thought")` for blobs too.

### 7. MEDIUM, CONFIRMED. `blocked` misclassification via substring regex
- `adapters/vertex_common.py:19-21` + `:63-64`: any 400/INVALID_ARGUMENT message matching `RAI|SAFETY|policy|violat|filtered...` (re.I, no word boundaries) becomes `blocked`. Verified: "Invalid constraint on resolution" matches (`constRAInt`); "training", "Australia", "afraid" also. Effect: a parameter bug is presented as a content block, and the user is told to change the prompt. It is also the wrong bucket for a payload error caused by the unverified [?] fields (see 12).
- Fix: word-boundary matching, restrict to known finishReason/blockReason fields, or only treat as blocked when the response carries explicit RAI fields.

### 8. MEDIUM, CONFIRMED. Memory: large video bytes are held in RAM several times, inputs retained forever (requirement: stream to disk)
- Veo/Omni inline base64: `r.json()` (whole body) -> `base64.b64decode` (`vertex_veo.py:41`, `vertex_omni.py:45`) -> `OutputRef.data` -> `write_outputs`. GCS path: `download_gcs` returns `r.content` (`vertex_veo.py:105-109`, non-streaming httpx). `Storage.register_file` re-reads the whole file for sha256 (`core/storage.py:44-52`). All of this runs on the event loop thread, so a 200-500 MB response blocks SSE/keepalives.
- `jobs.py:167-175` `_load_inputs` stores the raw bytes in `job.inputs` and never clears it after the attempt; `retry_job` deep-copies it (`:98`). 24 jobs x 14 references x 20 MB can reach several GB. `storage._assets`, `jobs`, `batches` are never evicted (acceptable locally, but the bytes are not).
- Fix: `client.stream()` to a file in `run_dir`, hash incrementally in a thread, clear `job.inputs` after submit, run decode/hash via `asyncio.to_thread`.

### 9. MEDIUM, CONFIRMED. Access token in URLs leaks into logs; docs open in LAN mode
- `frontend/src/api/client.ts:76` `assetUrl()` appends `?token=...` to every `<img>/<video>/<a download>`. uvicorn's access log prints the full request line. Reproduced: `INFO: 127.0.0.1 - "GET /api/providers?token=tok123 HTTP/1.1" 200`. Anyone with log access in LAN mode gets a reusable token. (The provider key is not affected.)
- `/docs`, `/openapi.json`, `/redoc` and `/` are unprotected in LAN mode (middleware only guards `/api/*`), so unauthenticated LAN hosts can read the full API surface. Minor: the websocket branch of the middleware would raise KeyError on `scope["method"]` (unused).
- Fix: short-lived signed asset URLs or a cookie set once; disable docs in LAN mode; `--no-access-log` or a log filter that strips `token=`.

### 10. MEDIUM, CONFIRMED (code). Preset/prompt library can wipe the file; LAN mode breaks saving
- `presets/PresetsMenu.tsx:13,23` and `prompts/PromptLibrary.tsx:13,21`: `data = []` is the default while loading or on error (401, network). "Lưu" then PUTs `[...[], new]` to `PUT /api/presets` which REPLACES the whole file. Two tabs have the same lost-update. The per-item upsert/delete endpoints exist but are unused.
- `crypto.randomUUID()` (`PresetsMenu.tsx:25`, `PromptLibrary.tsx:21`) is undefined outside a secure context: with `--lan` over `http://192.168.x.x` the click handler throws, so saving silently does nothing in the advertised LAN mode.
- Fix: use `PUT /api/{kind}/{id}` and `DELETE`; generate ids server-side (backend already does).

### 11. LOW-MEDIUM, CONFIRMED. Axis on `prompt` ignored; raw-request redaction mangles prompts; duplicates from no-op axes
- `core/expand.py:62-75`: `sweep.axes=[{param:"prompt",...}]` passes the `m.param()` check, but `job.prompt` and `eff["prompt"]` use the loop variable, so all jobs carry the base prompt (reproduced: axis {prompt:A}/{prompt:B} both produce text "orig") while the cells are labeled as differing. Real-money duplicates.
- Axis over a param that does not apply in the mode (silently dropped by `resolve` step 2) or that a force rule collapses (resolution 1080p + duration 4/6 => both forced to 8) yields N identical paid jobs; the estimate counts them all.
- `adapters/base.py:92` `redact_payload` replaces any string longer than 256 chars with no space in its first 64 chars by `<base64 N chars>`. Repro: a 300-char CJK prompt shows `<base64 300 chars>` in the "Request thô" tab (which is claimed to be the exact payload).

### 12. LOW-MEDIUM, PLAUSIBLE. Vertex payloads vs research (unverified claims stated as fact)
- `manifests/nano-banana-2.1.yaml:77-87` (and the other image manifests) send `generationConfig.thinkingConfig.thinkingLevel` with values minimal/low/medium/high. The research report 2a only says "Thinking Y (thinking_level, e.g. 'high')"; neither the path nor the enum is in the report and neither is marked [?] (unlike `seed`, `mime_type`). The Interactions snake_case form differs.
- `vertex_image.py:74` hard-codes `responseModalities:["IMAGE"]`; the report says image-only is requested via `response_format` (Interactions), and says nothing about classic generateContent accepting IMAGE-only for every model. Not marked [?] anywhere.
- Veo manifests always send `generateAudio`, `personGeneration` and `resolution` defaults (manifest defaults, `core/constraints.py:98`). `generateAudio` is flagged [?] ("secondary source"). If wrong, EVERY Veo job fails with INVALID_ARGUMENT (and, because of finding 7, may be labeled blocked). Consider sending optional [?] fields only when the user sets them.
- Omni: report 2.1 mentions both `response_format` and `generation_config.video_config`; adapter uses `response_format.duration/aspect_ratio/resolution`. Adapter docstring and manifest correctly say [?]; endpoint `/v1beta1/.../interactions` also [?]. Fine as long as the live smoke test happens before the data is trusted.
- `status: ga` + `lastVerified: 2026-10-07` on all image manifests although nothing was called live (header comment says so; the UI badge will not).
- `parse_operation` maps op error codes only for {8,3,7,16,4}; everything else (13 INTERNAL, 14 UNAVAILABLE, 9) falls to `network`, which is resubmitted (see 3).

### 13. LOW, CONFIRMED/PLAUSIBLE. Hygiene and resource gaps
- Absolute server paths leak in API and SSE: `Asset.path` is serialized in job `assets[]` and the upload response (reproduced: `/tmp/aigen-review-tmp/run-.../x.mp4`). Not a key, but the spec says paths of keys only; still unnecessary exposure. Exclude `path` from the public model.
- Upload limit is checked after the whole multipart body is spooled to disk (`api/assets.py:52`; no Content-Length precheck, no body cap): a multi-GB upload fills tmp before the 400. PLAUSIBLE.
- `expand.py:47` materializes `itertools.product` of all axis values before the cap check at `:49` (2 axes x 1500 values = 2.25M tuples, took 0.12 s; 100k x 100k would exhaust memory). Compute the product size first.
- Startup never sweeps stale `tmp/run-*` from a crashed/killed process (`core/storage.py:26-30`; cleanup only in the lifespan shutdown); SIGKILL leaves videos in tmp. `context.reset_adapters()` and shutdown never `aclose()` the cached `httpx.AsyncClient`s (`jobs.py:177-180`).
- Slow SSE consumer is dropped silently (`core/events.py:44-45`) but its generator keeps sending keepalives, so the client thinks it is connected; the frontend only recovers because of the 5 s poll while jobs run. Also `GET /api/batches/{id}` and `/api/jobs/{id}` are sync handlers (threadpool) that call `_refresh`, mutating state concurrently with the event loop (low risk).
- `retry_job` (`jobs.py:94-114`) bypasses the batch cap and the cost/confirm gate; retrying each of 24 failed Veo jobs, or a `canceled` job whose remote op may still be billing, spends money with no estimate. No cancel of the remote Veo operation (documented best-effort).
- `ConstraintEngine` backend vs frontend: a `block` rule that matches an intermediate state is kept in `blocked` even if a later force rule changes the state (`constraints.py:140-142`, sticky), while the frontend evaluates blocks after the fixpoint (`constraints.ts:112-115`). Also a list-valued `then` is an "allowed set" in the frontend (`constraints.ts:100-107`) but is assigned as a list value in the backend (`constraints.py:143-149`). No current manifest triggers either (no block rules, no list `then`); latent divergence.

### 14. LOW, CONFIRMED. Spec drift not recorded
- `pollIntervalSeconds` is documented as a setting (architecture.md "Endpoint thêm / đổi") and stored, but never read: adapters hard-code 15 s / 10 s / 0 (`vertex_veo.py:54`, `vertex_omni.py:54`). `jobTimeoutSeconds` is read (`jobs.py:229`, default 900) but absent from `DEFAULT_SETTINGS`, the docs, and `PUT /api/settings` (rejects unknown keys), so it cannot be changed.
- `PUT /api/settings` accepts any positive number (e.g. `maxJobsPerBatch: 1e12`, `maxAttempts: 2.5`, `confirmThresholdUsd: 100000`); only `> 0` is validated, so the guardrail values are trivially weakened.
- `GET /api/health` and the docs endpoints are open in LAN mode; health is documented, docs are not.
- Invariant 11 ("every param sent exists in the manifest") is not literally true for adapter-added fields (`sampleCount`, `storageUri`, `responseModalities`, `background`, `response_format.type`, `task`, `delivery`, `gcs_uri`); reasonable, but unrecorded.

## Things checked and found fine
- Path traversal: `/api/assets/{id}` and `/api/zip` resolve ids only through the in-memory `_assets` dict (uuid hex file names); ZIP `arcname=p.name`. No user-controlled path reaches the filesystem; presets/prompts/settings/providers writes use fixed file names in the data dir (atomic mkstemp + os.replace, 0600 on providers.json).
- Provider key never returned: `mask_providers` emits only configured/hasKey/keySource/projectId/location/gcsBucket; `RequestValidationError` handler drops `input`; adapter error messages use `type(e).__name__` for auth failures; ZIP sidecar uses a job dump that excludes `assets` and `inputs` (`exclude=True`). `.gitignore` covers providers.json and its tmp files; `ensure_providers_perms` re-chmods on every read.
- Upload: magic-byte sniffing (no trust in client mime), 20 MB cap on the buffered read, consent flow defaults to "has person"; output mime from provider is only used as a dict key for the extension.
- Token middleware: `//api/x` -> 404, `/api/../api/x` -> 401, constant-time compare, health only exempt; no routes outside `/api` except static + docs.
- State machine: terminal states final (`_set` guard), retry creates a new job id (reproduced), `blocked` never auto-retried (reproduced: attempts=1), quota retry then success (reproduced: attempts=2), cancel cancels the task and releases the semaphore through the context manager, a canceled-before-start task is harmless.
- Limiter: no deadlock/leak path found (semaphore released on cancel/exception; rpm lock only guards arithmetic). Note: the rpm sleep happens while holding a concurrency slot (reduces throughput, not a bug). Limiter is per model id, not per provider as the risk table says (quota is per project); not recorded.
- jobCount vs requestCount: reproduced `variants=6` on Veo => jobCount 6, requestCount 2, cost 2.4 = 6 x 4 s x $0.10; batch cap counts outputs, not requests (matches spec).
- Constraint engine terminates (MAX_ITER, oscillation reported as error); manifest cross-validation is solid; `lastVerified`/sunset/stale warnings present.
- SSE replay buffer bounded (deque 200, queue 1000); finite snapshot for non-SSE clients avoids hangs; shutdown wakes generators.
- Frontend: no `dangerouslySetInnerHTML`/`innerHTML`; prompts, errors, filenames rendered through React text nodes (no XSS found); `initToken` strips `?token=` from the address bar; `saveBlob` revokes the object URL; Settings clears the pasted JSON after sending; `upsertJob` ignores stale non-terminal events for terminal jobs; the fresh estimate before every generate is correct; `useLiveSync` cleans up its interval and listener.
- Adapter URL building for Veo `fetchPredictOperation`/`predictLongRunning`, `sampleCount` 1-4 native grouping and per-second pricing math match research-video-params.md 2.1/3/4; image `imageConfig.aspectRatio/imageSize` and model ids match research-image-params.md 2a; Omni price table matches the token math in the report.

## Method
Read all of backend/app, manifests, data, Makefile, .gitignore, frontend/src; ran the backend in demo mode (ports 8012/8013, /tmp data and tmp dirs, since deleted) to reproduce: Host header acceptance, no-Content-Type body acceptance, `?token=` in access log, unvalidated `location`, Veo grouping (1 job/3 assets), unknown-price estimate, axis-on-prompt, CJK redaction, resolve error shape, retry/blocked/quota flows. The repo's data/ and any real providers.json were not touched. No tests were run and no file other than this report was written.
