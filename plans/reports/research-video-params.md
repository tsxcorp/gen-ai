# Research: Video generation parameters, domain norms and entities

Date of research: 2026-10-07. Facet: "Domain norms & entities, VIDEO generation parameters" for a multi-provider AI generation studio (web UI, bring-your-own-keys).
Confidence legend: **[V]** verified in first-party docs fetched today; **[S]** from third-party/search snippet only; **[?]** could not verify.

---

## 0. Headline findings (things that change the product premise)

1. **OpenAI Sora is dead.** OpenAI notified on 2026-03-24 and removed the Videos API plus `sora-2`, `sora-2-pro` and the dated snapshots on **2026-09-24**. The deprecations page lists no replacement. [V: developers.openai.com/api/docs/deprecations] The "OpenAI Sora" provider in the brief should be dropped. An OpenAI key is still useful for images only.
2. **Seedance newest = Seedance 2.5** (`dreamina-seedance-2-5-260628` on BytePlus ModelArk). Launched 2026-07-31, "fully available" per the ModelArk API page. [V] Seedance 3.0 is NOT announced; the sites claiming it are unsourced. [S]
3. **Google's newest video model is no longer Veo.** It is **Gemini Omni Flash** (`gemini-omni-1.1-flash`, GA on the Gemini API; `gemini-omni-1.1-flash-preview` Preview on Vertex, released 2026-08-27). Google's own docs say "use Omni as your default model for video generation" and keep Veo 3.1 for scene extension, last-frame control and legacy pipelines. [V] Veo 4 does not exist officially. Veo 3.1 GA on Vertex has "Retirement date: November 17, 2026 or later" (about 6 weeks out). [V]
4. **Vertex AI is renamed "Gemini Enterprise Agent Platform"** (docs paths changed; API host `aiplatform.googleapis.com` unchanged). [V]
5. Other newest versions found [V unless noted]: **Kling 3.0 / 3.0 Omni / 3.0 Turbo** (Kling 4.0 announced 2026-09-28, closed beta, [S]); **Luma Ray 3.2** (June 2026, new "Luma Agents API"); **Runway Gen-4.5** (plus Seedance, Veo, Wan, Hailuo, Omni hosted on its API); **MiniMax H3 / H3 Max** (the "Hailuo 3" line; Hailuo 2.3 is now legacy); **Wan 3.0** (`wan3.0-video`, preview, 2026-08-24; Wan 2.7 is the previous line).
6. **Runway Dev API is itself a multi-model gateway** (Seedance 2.0/2.5, Veo 3.1, Gemini Omni, Wan 3.0, MiniMax H3, Grok Imagine Video 1.5, HappyHorse 1.0, Gen-4.5, Aleph 2.0, Act-Two) with one task API. Relevant to the "one key vs many keys" question.
7. **"N variants in one go" is mostly NOT native.** Only Vertex Veo has a native count (`sampleCount` 1-4). Everything else is 1 video per request, so N variants = N parallel jobs, bounded by per-provider concurrency (Section 4). Variants must be a client-side fan-out feature.
8. **Native audio is now the norm** (Veo, Omni, Seedance 1.5+, Kling 3, Wan 3, Hailuo H3, Grok). Audio changes price on several models. Two different shapes exist: boolean vs enum.

---

## 1. Model landscape (as of 2026-10-07)

| Provider | Current top model(s) (API id) | Status | Older still callable |
|---|---|---|---|
| Google (Gemini API) | `gemini-omni-1.1-flash` (GA, paid tier), `gemini-omni-flash-preview`; `veo-3.1-generate-preview`, `veo-3.1-fast-generate-preview`, `veo-3.1-lite-generate-preview` | Omni GA; Veo 3.1 Preview. Veo 3.1 **preview endpoints on Gemini API shut down 2026-10-22** [S, one source, verify] | Veo 3 / 3 Fast (Stable) |
| Google (Vertex / Agent Platform) | `gemini-omni-1.1-flash-preview` (Preview, `global`), `gemini-omni-flash-preview` (720p only); `veo-3.1-generate-001` (GA), `veo-3.1-fast-generate-001` (GA), `veo-3.1-lite-generate-001` (Preview, 2026-04-02) | Veo 3.1 GA retirement Nov 17, 2026 or later | veo-3.0-*, veo-2.0-generate-001 |
| ByteDance Seedance (BytePlus ModelArk intl) | `dreamina-seedance-2-5-260628`; `dreamina-seedance-2-0-260128`, `-2-0-fast-260128`, `-2-0-mini-260615`; `seedance-1-0-pro-250528`, `seedance-1-0-pro-fast-251015`; `seedance-1-5-pro-251215` is marked **Retired** (replacement 2.0 mini) | 2.5 GA | Volcengine (China) has separate IDs/console [S] |
| Kling (Kuaishou) | `kling-3.0`, `kling-3.0-omni`, `kling-3.0-turbo`; also O1, 2.6, 2.5 Turbo | 3.0 current; 4.0 announced [S] | |
| Runway | `gen4.5`, `gen4_turbo`, `aleph2` (edit), `act_two`, + hosted third-party models | current | |
| Luma | `ray-3.2` (Luma Agents API at `agents.lumalabs.ai`) | current; "rates subject to change ahead of GA" | Ray 3.14 (Jan 2026), Ray 2 on Bedrock |
| MiniMax | `MiniMax-H3`, `MiniMax-H3-Max` (V2 endpoint `/v2/video_generation`); legacy `MiniMax-Hailuo-2.3`, `-2.3-Fast`, `-02` (V1 endpoint) | H3 current | |
| Alibaba Wan | `wan3.0-video`, `wan3.0-video-prime` (preview); Wan 2.7 (`wan2.7-t2v-*`, `wan2.7-i2v-*`, `wan2.7-videoedit`) | Wan3 preview | Wan 2.2 open weights |
| OpenAI | none | Sora API removed 2026-09-24 | |
| Others seen | xAI Grok Imagine Video 1.5 (+Lite), HappyHorse 1.0 (via Runway) | not researched directly | |

Aggregators for Seedance (BYO-key alternatives): fal.ai `bytedance/seedance-2.5/...` (also a `/us/` hosted variant), Replicate `bytedance/seedance-2.5` and `-2.0`, OpenRouter, Runway Dev (`seedance2_5`), MuAPI, Evolink, WaveSpeed. Prices on fal are about 2x ModelArk (fal 720p about $0.47/s vs ModelArk $0.231/s) [S].

---

## 2. Parameter matrix

Notation: `-` = not supported / not applicable. "Native" = provider's own API. Where Runway Dev hosts a model, its schema differs from the native one; noted in 2.4.

### 2.1 Google: Gemini Omni Flash, Veo 3.1 family

Omni uses the **Interactions API** (`POST /v1beta/interactions`, model id in body, `response_format` object, `generation_config.video_config`), NOT `predictLongRunning`. Veo 3.1 on Gemini API now also goes through `generateContent` per the doc banner [V]; Vertex Veo still uses `predictLongRunning` + `fetchPredictOperation` [V].

| Parameter | Gemini Omni 1.1 Flash | Veo 3.1 / 3.1 Fast (Vertex GA) | Veo 3.1 Lite (Vertex Preview) |
|---|---|---|---|
| Modes: text-to-video | yes | yes | yes |
| image-to-video (first frame) | yes (image in `input`) | yes (`image`) | yes |
| first+last frame | yes (2 images) | yes (`lastFrame`, needs `image`) | yes |
| reference-to-video | yes (`task: reference_to_video`; Vertex: up to 10 images, 3 videos) | yes, `referenceImages` up to 3 `asset` OR 1 `style` (style: Preview models only per older page [S]); forces 8s | **no** |
| extend | yes (3-10s continuation; uploaded input <=10s; multi-turn via `previous_interaction_id`; Vertex: input 1-30s, total up to 40s) | yes (+7s, up to 20x, input 720p only, Veo-generated only on Gemini API; Vertex input 1-30s, up to 37s) | Vertex page says extend supported; Gemini API says no [conflict] |
| video-to-video edit | yes (`task: edit`, conversational, stateful) | - | - |
| lip-sync | - (audio references unsupported in current API) | - | - |
| `task` hint | `text_to_video, image_to_video, reference_to_video, edit, extend` (optional, "adds constraints") | - | - |
| Duration (s) | Vertex `duration` "3s".."10s" in `response_format`; Gemini API docs list none (Runway: 3-10 int or auto) | `durationSeconds` 4, 6, 8 (default 8); **must be 8** for reference images, 1080p, 4K, extension | 4, 6, 8; 8 for refs and 1080p |
| Resolution | `resolution`: 360p, 720p (default), 1080p (upscaled), 4k (upscaled). `gemini-omni-flash-preview` only 720p | `resolution` 720p (default), 1080p, 4k (1080p/4k only at 8s; extension 720p only) | 720p, 1080p (no 4K) |
| Aspect ratio | `aspect_ratio` 16:9 (default), 9:16 | `aspectRatio` 16:9 (default), 9:16 | same |
| FPS | not documented | 24 fixed | 24 |
| Seed | no (temperature/top_p etc. unsupported) | `seed` uint32 0-4294967295 (not deterministic) | same |
| Negative prompt | **no** (put negatives in prompt) | `negativePrompt` | `negativePrompt` |
| Audio | always on; steer via prompt; Vertex lists "Speech, music, SFX" | Vertex REST: `generateAudio` bool [S, old model-reference page]; Gemini API: always on | same |
| Prompt enhance | - | `enhancePrompt` Veo 2 only [S] | - |
| N outputs per request | 1 | **`sampleCount` 1-4** (Vertex), 1 on Gemini API | up to 4 (Vertex) |
| Person generation | safety filters, region rules (EEA/UK/CH: no uploaded-video edit/extend; no minors) | `personGeneration`: Vertex `allow_adult` (default) / `disallow`; Gemini API T2V `allow_all` only, I2V/refs `allow_adult` only; EU/UK/CH/MENA `allow_adult` only | same |
| Input image limits | Vertex: <=10 images, 20 MB inline / 30 MB GCS; png, jpeg, webp, heic, heif; Vertex video input <=3 videos (<=10s), mp4/mov/webm/etc. | 20 MB; 720p or 1080p inputs; `resizeMode` crop/pad (image-to-video, Veo 3 only) | 20 MB |
| Output format | mp4, base64 inline (>4MB: use `delivery:"uri"`); Vertex `gcs_uri` | mp4 (video/mp4); `compressionQuality` optimized/lossless [S] | mp4 |
| Output location | Gemini API: inline base64 or Files-API URI (poll until ACTIVE); Vertex: `delivery:"uri"` + `gcs_uri` | Vertex: `storageUri` (gs://) optional; if omitted, bytes in response. Gemini API: Google-hosted, 2 days | same |
| Watermark | SynthID always (invisible); C2PA on Vertex. No visible-watermark toggle | same | same |
| Camera control | prompt only | prompt only | prompt only |
| Sync/async | `background:false, store:false, stream:false` = synchronous unary (fastest); `background:true` for async. `store:false` makes video non-editable next turn | long-running op, poll | same |

### 2.2 ByteDance Seedance (BytePlus ModelArk) [V, from `docs.byteplus.com/en/docs/ModelArk/1520757`]

Endpoint `POST https://ark.ap-southeast.bytepluses.com/api/v3/contents/generations/tasks`. Auth: API key only. Params can go in body (strict validation, recommended) or appended to prompt as `--rs 720p --rt 16:9 --dur 5 --seed 11 --cf false --wm true` (legacy, weak validation).

| Parameter | Seedance 2.5 | 2.0 / 2.0 Fast / 2.0 Mini | 1.5 pro (Retired) | 1.0 pro / pro fast |
|---|---|---|---|---|
| Modes | T2V; first frame; first+last; **omni reference** (0-30 img, 0-10 video, 0-10 audio; audio-only OK) incl. edit + extend (forward or backward) | same but refs 0-9 img, 0-3 video, 0-3 audio; audio-only NOT ok (need >=1 image/video) | T2V, first, first+last | T2V, first (+last for pro; fast has no last) |
| `omni_reference_task_type` | `auto` (default) / `reference` / `edit` / `extend`. Edit: needs reference_video 4-30s, `ratio=adaptive`, `duration=-1`. Extend: `ratio=adaptive` | - | - | - |
| `content[].role` | `first_frame`, `last_frame`, `reference_image`, `reference_video`, `reference_audio`; also `draft_task` item | no draft | draft | - |
| Mutually exclusive | first-frame, first+last, omni-reference cannot be mixed | same | | |
| `resolution` | 480p, **720p default**, 1080p (10-bit, H.265) | 2.0: 480p, 720p, 1080p, **4k** (10-bit H.265). Fast/Mini: 480p, 720p only | 480p, 720p default, 1080p | 480p, 720p, **1080p default** |
| `ratio` | 16:9, 4:3, 1:1, 3:4, 9:16, 21:9, `adaptive` (default). Forced `adaptive` for I2V, edit, extend | same list, I2V may specify | same | no `adaptive` for T2V (default 16:9); I2V default adaptive |
| `duration` (s) | 4-30 or -1 (auto). Edit: -1 only (output approx. input length, can be fractional, about 0.4s shorter) | 4-15 or -1, default 5 | 4-12 or -1 | 2-12, default 5 |
| `frames` | - | - | - | 29-289 where frames = 25+4n (1.0 only; overrides `duration`) |
| FPS | 24 fixed | 24 | 24 | 24 |
| `seed` | **not supported** | **not supported** | -1..2147483647 | same |
| `camera_fixed` | not supported | not supported | yes (not with reference images) | yes |
| `generate_audio` | bool default true (mono output) | bool default true | yes | - (silent) |
| `watermark` | bool, default false ("AI Generated" bottom right) | same | same | same |
| `output_format` | `mp4` (default) / `mov` (H.264, YUV 4:4:4, PCM) | mp4 | mp4 | mp4 |
| `return_last_frame` | bool (jpeg, no watermark; for chaining clips) | yes | yes | yes |
| `draft` | bool, 480p only; then final via `draft_task.id` | - | yes | - |
| `service_tier` | `default` only (flex not supported) | `default` only | `default`, `flex` (50% price) | `default`, `flex` |
| `priority` | int 0-9 (FIFO otherwise; not with flex) | yes | - | - |
| `callback_url` | webhook: `queued/running/succeeded/failed/expired`; retries 3x if no ack in 5s | yes | yes | yes |
| `execution_expires_after` | 3600-259200 s, default 172800 (48h) | same | same | same |
| `safety_identifier` | string <=64 chars (hashed end-user id) | same | same | same |
| Prompt enhance | none exposed | none | none | none |
| Negative prompt | none (put in prompt) | none | none | none |
| Prompt language / length | EN + ES, ID, PT, JA, MS, TH, AR, VI, KO; <=500 CJK chars / 1000 EN words recommended | EN + ES, ID, PT, JA | EN | EN |
| N per request | 1 | 1 | 1 | 1 |
| Image input | jpeg/png/webp/bmp/tiff/gif (+heic/heif for 1.5+); aspect 0.4-2.5; 300-6000 px per side; <30 MB each; request body <64 MB; URL, base64 (`data:image/png;base64,...`) or `asset://` ID | same | same | no heic |
| Video input | mp4/mov, H.264/H.265, AAC/MP3; 480p-4K; 2-30s each (edit 4-30s), <=10 clips total <=30s; <=200 MB each; 24-60 fps; 0.4-2.5 aspect | 2-15s each, <=3 clips, total <=15s | - | - |
| Audio input | wav/mp3; 2-30s each, <=10 clips, total <=30s; <=15 MB each | 2-15s, <=3 clips, total <=15s | - | - |
| Real-person faces | uploads of images/videos with real faces **rejected**; workarounds: model's own face-containing outputs (30 days), preset digital characters (`asset://`), authorized real-person assets library | same | | |
| Output URL | `content.video_url`, valid **24 hours**; `last_frame_url` also 24h | same | same | same |

Pixel sizes per resolution x ratio differ slightly by model family (e.g. 480p 16:9 is 854x480 on 2.5, 864x496 on 2.0, 864x480 on 1.0). The UI must show "actual output size" per model rather than a single table.

### 2.3 Kling (Kuaishou) [V from `kling.ai/document-api/...md`; new nested schema]

Base host seen: `https://api-singapore.klingai.com`. Endpoint per model: `POST /text-to-video/kling-3.0`, `/image-to-video/kling-3.0`, `/omni-video/kling-3.0-omni`, `/text-to-video/kling-3.0-turbo`; poll `GET /tasks`. Status: `submitted, processing, succeeded, failed`. Older 2.6 and earlier use the legacy flat schema (`model_name`, `mode: std|pro`, `sound: on|off`, `cfg_scale`, `camera_control`) [S for legacy details].

| Parameter | Kling 3.0 (T2V / I2V) | Kling 3.0 Omni | Kling 3.0 Turbo |
|---|---|---|---|
| Modes | T2V; I2V with `contents[]` types `first_frame`, `last_frame`, `element` | `contents[]` types `prompt, first_frame, last_frame, refer_image, feature_video, base_video, element` (reference, edit via `base_video`) | T2V, I2V |
| Other endpoints | Motion Control 3.0, Element Management, Voice Management, Avatar, Lip Sync, multi-element editing | same | - |
| `settings.resolution` | 720p (default), 1080p, 4k | 720p, 1080p, 4k | 720p, 1080p (no 4K) |
| `settings.aspect_ratio` | 16:9 (default), 9:16, 1:1 (T2V only; I2V follows image) | same | same |
| `settings.duration` | int 3-15, default 5 | 3-15 | 3-15 |
| `settings.audio` | `native` / `off` (default off) | `native` / `original` (keep source audio) / `off` | not listed |
| `settings.multi_shot` | bool default true. Prompt syntax "shot n, m, words;" up to 6 shots, each >=1s, sum = total duration, each shot prompt <=512 chars (fal exposes this as `multi_prompt` + `shot_type: customize|intelligent`) | yes | - |
| `prompt` | <=3072 chars (recommend <=2500); positive and negative in same text | same | same |
| `negative_prompt`, `cfg_scale`, `seed`, `camera_control` | not in new nested schema [V absence]; fal wrapper still exposes `negative_prompt`, `cfg_scale` (0-1, default 0.5) [S] | - | - |
| `options.callback_url`, `options.external_task_id` (unique per account), `options.watermark_info.enabled` | yes; custom watermark unsupported | yes | yes |
| N per request | 1 | 1 | 1 |
| Output URL | hotlink-protected, cleared after **30 days** | | |
| Concurrency | per account x model version x resource pack; 1 slot per video task; error code 1303 `parallel task over resource pack limit`; no QPS limit; queries don't consume slots | | |

Not verified: Kling per-second price (sold as resource packs / units); exact camera_control in 3.0 (appears dropped from the new schema); lip-sync, avatar and motion-control parameter lists.

### 2.4 Runway Dev API [V from `docs.dev.runwayml.com/api.md`]

Requires header `X-Runway-Version`. `POST /v1/text_to_video | /v1/image_to_video | /v1/video_to_video` with discriminated union on `model`. Native Runway models:

| Param | `gen4.5` | `gen4_turbo` | `aleph2` |
|---|---|---|---|
| Modes | T2V, I2V (first frame) | I2V only | V2V edit (input <=30s) |
| `ratio` | `1280:720`, `720:1280` (T2V); I2V ratios differ per docs/third parties (six ratios incl. 1104:832, 960:960, 1584:672 [S]) | same six [S] | - |
| `duration` | int 2-10 | 5 or 10 [S] | - |
| `seed` | 0-4294967295 | yes | - |
| `promptText` | <=1000 chars | | |
| `contentModeration.publicFigureThreshold` | `auto`/`low` | | |
| `outputFormat` | mp4, prores, png_sequence, hdr10, hlg, sdr_rec709_10bit, hdr_pq_12bit_master, hdr_prores, hdr_png_sequence, hdr_exr_*; `proresProfile` 422/4444/... | | |
| Audio | none | none | |

Hosted third-party models use Runway-style fields (`promptText`, `ratio` as `W:H` pixels, `duration`, `audio`, `references[]`, `referenceVideos[]`, `referenceAudio[]`). Notable differences from native: Veo via Runway only takes ratios `1280:720, 720:1280, 1080:1920, 1920:1080`, durations 4/6/8, `negativePrompt`, `audio`; **no `resolution` field**, resolution is implied by ratio. Seedance via Runway has `seed` (native ModelArk 2.x does not) and `duration: "auto"`. `seedance2_5` draft: `draft:true` then `draftTaskId` (enhance within 7 days). `h3_max` has `promptExpansionMode`. `wan3` duration 2-30, `audio` bool.

Task API: `PENDING, THROTTLED, RUNNING, SUCCEEDED, FAILED, CANCELLED`; poll `GET /v1/tasks/{id}` (not faster than every 5s); `output` URLs expire in **24-48h**. `THROTTLED` = queued behind your concurrency limit (not an error). Tier-based concurrency "per model, per project"; no RPM limit but a daily generation cap.

### 2.5 Luma Ray 3.2 [V from `docs.agents.lumalabs.ai`]

`POST https://agents.lumalabs.ai/v1/generations` with `model: "ray-3.2"`, `type: "video" | "video_edit" | "video_reframe"`.

| Param | Values |
|---|---|
| `prompt` | 1-6000 chars (required) |
| `aspect_ratio` | 9:16, 3:4, 1:1, 4:3, 16:9, 21:9 (omitted = model chooses) |
| `video.resolution` | 360p (draft, SDR only), 540p (not with HDR), **720p default**, 1080p |
| `video.duration` | `5s` (default), `10s` (not with HDR, start/end frame, loop) |
| `video.start_frame`, `video.end_frame` | ImageRef: `url`, base64 `data`+`media_type`, `file_id`, or `generation_id`; <=50 MB, <=8000 px per side; mutually exclusive with `keyframes`; not with 10s |
| `video.keyframes` + `video.keyframe_indexes` | 1-64 images at arbitrary frame positions on the 24 fps grid (5s: 0-120, 10s: 0-240); allows 10s and HDR |
| `video.loop` | bool; not with 10s, HDR, end_frame, keyframes; forward-extend only when extending |
| `video.hdr` | bool; 720p/1080p, 5s only; costs more |
| `video.exr_export` | bool, requires hdr; EXR in ACES2065-1 |
| Extend | pass `generation_id` as `start_frame` (forward) or `end_frame` (backward), SDR only, billed as one 5s block |
| Audio, negative prompt, seed, N | none documented |
| Output | MP4 via presigned URL, **expires 1 hour** (re-GET to mint new URL); generation id does not expire |
| States | `queued`..`completed`/`failed`; typical 5s/720p "well under two minutes" |
| Limits | RPM + concurrent jobs per client, plan-dependent; 429 on exceed |

### 2.6 MiniMax H3 / H3 Max (V2 API) [V from `platform.minimax.io/docs`]

`POST https://api.minimax.io/v2/video_generation`; body: `model`, `content[]` (text required + `image_url`/`video_url`/`audio_url` with `role`), `resolution`, `duration` (both required), `ratio`, `extra`, `callback_url`.

| Param | MiniMax-H3 | MiniMax-H3-Max (fast) | Legacy Hailuo 2.3 (V1 `/v1/video_generation`) |
|---|---|---|---|
| Modes | T2V, first frame, last frame, first+last, reference-to-video (<=9 images, <=3 videos, <=3 audio). I2V and reference mutually exclusive | same | T2V, I2V (`first_frame_image` required for I2V and for -Fast), FL2V (`last_frame_image`, shown with Hailuo-02), subject reference |
| `resolution` | `768P`, `2K` | `480P`, `768P` (default), no 2K | `768P` (default) or `1080P` |
| `duration` | int 4-15 | int 5-15 | 6 (768P or 1080P) or 10 (768P only) |
| `ratio` | `adaptive` (default), 21:9, 16:9, 4:3, 1:1, 3:4, 9:16. T2V must be explicit; I2V forced adaptive | same | - |
| Prompt expansion | - | `extra.prompt_expansion_mode`: `disabled`, `balanced` (default), `quality` | `prompt_optimizer` bool (default true) [S] |
| Camera control | via prompt | via prompt | bracket commands in prompt, e.g. `[Pedestal up]`, `[Static shot]` |
| Audio | native; reference audio free | | - |
| Seed | not in V2 doc | not in V2 doc (Runway wrapper exposes `seed`) | - |
| Image input | JPG/JPEG/PNG/WEBP/HEIC/HEIF, <=30 MB, 256-5760 px, aspect 0.4-2.5; body <=64 MB | same | JPG/PNG, <=20 MB [S] |
| Video input | mp4/mov, <=50 MB, 2-15s each, total <=15s, 23.976-60 fps | | |
| Output | `content.url`; re-query for a new URL after expiry; tasks queryable **7 days** | | |
| Status | `queued, running, succeeded, failed, cancelled`; webhook with a **challenge handshake** (return `challenge` within 3s) | | |
| Extras | "H3-Context-IR" prompt-structuring task; video **regeneration** (768P output re-rendered to 2K) | | |

### 2.7 Alibaba Wan 3.0 [V from `alibabacloud.com/help/en/model-studio/wan3-video-generation-api-reference`]

`POST https://{WorkspaceId}.<region>.maas.aliyuncs.com/api/v1/services/aigc/video-generation/video-synthesis`, header `X-DashScope-Async: enable`. Regions: Singapore, Beijing, US-Virginia, Tokyo, Frankfurt, Hong Kong; **model, endpoint and key must be in the same region**. Doc marked "Currently in preview", last updated 2026-09-28.

| Param | Values |
|---|---|
| `model` | `wan3.0-video` (standard), `wan3.0-video-prime` (faster) |
| `input.prompt` | <=20,000 chars (EN/ZH); in reference mode, address media as "Image 1", "Video 1", "Audio 1" |
| `input.media[]` types | `first_frame`(1), `last_frame`(1), `reference_image`(<=10), `reference_video`(<=5, total <=15s), `reference_audio`(<=5, total <=15s), `file`(1; docx/pdf/pptx/etc., <=100MB, <=50 pages), `link`(1 web page) |
| `parameters.resolution` | `480P`, `720P`, **`1080P` default** |
| `parameters.ratio` | `adaptive` (default), 21:9, 16:9, 4:3, 1:1, 3:4, 9:16 |
| `parameters.duration` | int 2-30, default 5; -1 = smart; with video input, input + output <= 30s |
| `parameters.audio` | bool default true (no price effect) |
| `parameters.seed` | -1 or 0-2147483647 (not exactly reproducible) |
| `parameters.prompt_extend` | bool default true; **must be true** when file or link input is used |
| `parameters.watermark` | bool default false |
| FPS | 30 (stated in doc) |
| Image input | JPEG/PNG(no alpha)/BMP/WEBP, 240-8000 px, aspect <=8:1, <=20 MB |
| Video input | mp4/mov, 1-15s each, >=16 fps, 240-4096 px, <=100 MB |
| Audio input | wav/mp3, 1-15s, <=15 MB |
| Task | `task_id` valid **24 hours**; typical 1-5 minutes; result URL expiry not verified here [?] |
| Negative prompt, camera control | not in Wan3 doc; Wan 2.7 doc not re-read for `negative_prompt` [?] |

Wan 2.7 (older, still listed): `wan2.7-t2v-2026-06-12`, `wan2.7-i2v-2026-04-25` (first frame, first+last, continuation via `first_clip`, `driving_audio`), `wan2.7-videoedit` (mp4/mov, 2-10s). [S from search snippets]

### 2.8 OpenAI Sora (for the record) [V: removal; S: params]

Params were `prompt`, `model` (`sora-2`, `sora-2-pro`), `seconds` (4/8/12), `size` (720x1280, 1280x720, 1024x1792, 1792x1024), `input_reference`, `remix_video_id`. All removed 2026-09-24. Do not build an adapter.

### 2.9 Cross-provider capability grid (condensed)

| Capability | Omni | Veo 3.1 | Seedance 2.5 | Seedance 2.0 | Kling 3.0 | Runway gen4.5 | Luma ray-3.2 | MiniMax H3 | Wan 3.0 |
|---|---|---|---|---|---|---|---|---|---|
| T2V | y | y | y | y | y | y | y | y | y |
| I2V first frame | y | y | y | y | y | y | y | y | y |
| First+last | y | y | y | y | y | - | y (+16-64 keyframes) | y | y |
| Multi-reference images | y | y (<=3) | y (<=30) | y (<=9) | y (elements, <=4 total ref) | - | - (keyframes only) | y (<=9) | y (<=10) |
| Reference video | y (<=3x3s) | - | y (<=10) | y (<=3) | y (feature/base video) | - | - | y (<=3) | y (<=5) |
| Reference audio | - | - | y (<=10) | y (<=3) | element voice_id | - | - | y (<=3) | y (<=5) |
| Extend | y | y | y | y | - (not seen) | - | y | - | via video input |
| Video edit | y | - | y | y | y (Omni) | `aleph2` | `video_edit` | - (regeneration only) | Wan 2.7 `videoedit` |
| Native audio | y (always) | y (Vertex: toggle; Gemini API always) | y (toggle) | y (toggle) | y (toggle) | - | - | y | y (toggle) |
| Seed | - | y | - | - | - | y | - | - | y |
| Negative prompt | - (prompt only) | y | - | - | - (in prompt text) | - | - | - | - |
| Prompt rewrite toggle | - | - | - | - | - | - | - | y (Max: 3 modes) | y (`prompt_extend`) |
| Max duration (s) | 10 | 8 | 30 | 15 | 15 | 10 | 10 | 15 | 30 |
| Max resolution | 4K (upscaled) | 4K | 1080p | 4K | 4K | 720p-class | 1080p (HDR 1080p) | 2K | 1080p |
| Native N>1 | - | Vertex 1-4 | - | - | - | - | - | - | - |
| Webhook | - (poll / SSE) | - (poll) | y | y | y | - (poll) | - (poll) | y (challenge) | - (poll) |

---

## 3. Async job model per provider

| Provider | Submit | Status | Completion signal | Typical latency | Task/job TTL | Output URL expiry | Notes |
|---|---|---|---|---|---|---|---|
| Vertex Veo | `POST .../publishers/google/models/{id}:predictLongRunning` returns operation name | `POST ...:fetchPredictOperation {operationName}` (SDK: `operations.get`, doc samples poll every 15s) | `done: true` | Gemini API doc: min 11s, max 6 min at peak | not stated | with `storageUri`: lives in your bucket (no expiry). Without it: bytes in response. Gemini API (non-Vertex): **2 days** server-side; extension reference resets timer | **GCS bucket is optional** on Veo REST (`storageUri` "Optional"), but Omni on Vertex uses `delivery: "uri"` + `gcs_uri`. For a local tool, returning bytes is simpler but large responses are heavy |
| Gemini Omni | `POST /v1beta/interactions`; sync by default or `background:true` | `GET /v1beta/interactions/{id}` (note: GET returns inline base64 even if created with uri) | `status: completed` | not stated ("varies") | `store:true` keeps for multi-turn edit | `delivery:"uri"` gives Google-hosted file; poll Files API until `ACTIVE`; Gemini inline limit about 4 MB so use uri above 720p | Free tier none; paid only |
| Seedance (ModelArk) | `POST /contents/generations/tasks` | `GET /contents/generations/tasks/{id}`, list, cancel/delete (cancel only while `queued`) | `succeeded`; webhook available | minutes (not stated officially) | task id stored **7 days** | `video_url` **24 h** | `expired` after `execution_expires_after` (default 48h). Activation needs balance > USD 30 or a savings plan/resource pack |
| Kling | POST per-endpoint | `GET /tasks` (by `task_ids` / `external_task_ids`) or callback | `succeeded` | not stated | list window 30 days | **30 days** | Concurrency counted from `submitted` to end |
| Runway | `POST /v1/{text,image,video}_to_video` returns `id`, `estimatedCost` | `GET /v1/tasks/{id}` (<=1 poll/5s) | `SUCCEEDED` | example in docs: about 15s per gen4-class task | not stated | **24-48 h** | `THROTTLED` = held behind concurrency; refunds of unused credits for `duration:auto` |
| Luma | `POST /v1/generations` (201) | `GET /v1/generations/{id}` | `completed` | 5s/720p under about 2 min; 10s/1080p/HDR several times longer | generation id never expires | presigned URL **1 hour** (re-GET) | RPM + concurrent job caps, 429 |
| MiniMax | `POST /v2/video_generation` returns `task_id` | `GET` query (last 7 days), list, cancel/delete | `succeeded` / webhook | not stated | **7 days** | re-query for new URL after expiry (duration not stated) | webhook requires challenge handshake within 3s |
| Wan | `POST` with `X-DashScope-Async: enable` | query by `task_id` | success state | 1-5 min | `task_id` **24 h** | not verified | region-locked keys |

### Quotas and concurrency (what is verifiable)
- Seedance (ModelArk) [V]: 2.5 and 2.0 family default tier **enterprise 600 RPM / 10 concurrent; individual 180 RPM / 3 concurrent**; 2.0 **4K: 15 RPM / 1 concurrent**; flex unsupported. 1.0 pro: 600 RPM / 10 concurrent.
- Runway [V]: concurrency per usage tier, per model, per project; extras queue as `THROTTLED`; no RPM cap but a daily generation cap; tier upgrades are automatic on spend.
- Kling [V]: per-account concurrency by resource pack (highest active pack wins); 1303 on overflow; no QPS limit.
- Luma [V]: RPM + concurrent jobs, plan-dependent, in dashboard.
- Vertex Veo [V, with doubt]: model page shows "Regional online prediction requests per base model per minute: 50", with the unit mislabeled "tokens". Treat as about 50 req/min, verify in the Quotas console. Fixed quota only; **no pay-as-you-go listed on the model page, Provisioned Throughput supported** (the pricing page still lists per-second prices; reconcile in the console).
- Gemini Omni on Vertex: Standard PayGo (global), Preview.
- MiniMax: rate limits page exists, not read [?].

**Design consequence:** generating N variants = N jobs. A client-side scheduler needs a per-provider concurrency semaphore (Seedance 3 or 10, Kling pack-based, Runway tier-based, Veo sampleCount up to 4 per call), retry with backoff, and cancel only works for queued Seedance tasks.

---

## 4. Pricing (list prices; USD; verify before showing to users)

| Model | Price | Source quality |
|---|---|---|
| Veo 3.1 (Vertex and Gemini API) | with audio $0.40/s (720p, 1080p), $0.60/s 4K; no audio $0.20/s ($0.40 4K) | V (Vertex pricing page, Gemini pricing page) |
| Veo 3.1 Fast | with audio $0.10 (720p), $0.12 (1080p), $0.30 (4K); no audio $0.08 / $0.10 / $0.25 on Vertex | V |
| Veo 3.1 Lite | with audio $0.05 (720p), $0.08 (1080p); no audio $0.03 / $0.05; no 4K | V |
| Gemini Omni 1.1 Flash | token billing: $17.50 per 1M video output tokens; 5,792 tok/s at 720p (about $0.10/s), 1,931 at 360p (about $0.034/s), 8,688 at 1080p (about $0.152/s), 17,376 at 4K (about $0.304/s). Input $1.50 per 1M (image 1,120 tok, audio 32 tok/s, video 5,792 tok/s) | V (Vertex pricing page; Gemini page states about $0.10/s) |
| Seedance 2.5 (ModelArk) | $10.70 per 1M tokens (480p/720p, no video input), $6.40 with video input; 1080p $11.70 / $7.00. 5s 16:9 no-video-input: $0.514 (480p, $0.103/s), $1.156 (720p, $0.231/s), $2.843 (1080p, $0.569/s). With a video input: up to $2.15 / $4.84 / $11.91 for 5s output with 30s input. Min token floors with video input | V |
| Seedance 2.0 | $0.07/s (480p), $0.15/s (720p), $0.37/s (1080p), $0.78/s (4K) at 5s 16:9 | V |
| Seedance 2.0 Fast | list $0.06/s (480p), $0.12/s (720p); promo 25% off ended 2026-10-07 | V |
| Seedance 2.0 Mini | $0.04/s (480p), $0.08/s (720p); promo 60% off ended 2026-10-07 (about $0.03/s promo) | V |
| Seedance 1.5 pro (retired) | $0.12 per 5s 480p audio ... | V, retired |
| Seedance on fal | 2.5: about $0.22 / $0.47 / $1.16 per s (480/720/1080p); `/us/` variant dearer | S |
| Runway (credits at $0.01) | gen4.5 12 cr/s ($0.12/s); gen4_turbo 5 cr/s; aleph2 28 cr/s (56 min); act_two 5; veo3.1 40 cr/s audio, 20 no audio; veo3.1_fast 15/10; seedance2_5 20/30/68 cr/s (480/720/1080p) + 10/15/34 cr/s of input video, 80 cr minimum; seedance2 36 (480/720), 40 (1080p), 150 (4K); wan3 5/10/20; hailuo3 10 (768P) / 15 (2K); h3_max 5/8; omni 1.1: 3.4/10/15/30 (360/720/1080/4K) | V |
| Luma Ray 3.2 | 5s SDR: 360p $0.06, 540p $0.15, 720p $0.30, 1080p $1.20; 10s: $0.18, $0.45, $0.90, $3.60; HDR 5s: $0.60 (720p), $2.40 (1080p); HDR+EXR $0.90 / $3.60; edit 5s SDR 720p $1.08; "subject to change before GA" | V |
| MiniMax H3 | $0.08/s (768P), $0.13/s (2K); extra: first 5 reference images free then $0.04 each; reference video billed at the same per-second rates; audio ref free | V |
| MiniMax H3 Max | $0.05/s (480P), $0.08/s (768P); first 2 images free, then $0.074; reference video $0.0553/s (480P), $0.143/s (768P) | V |
| Wan 3.0 | $0.05 / $0.10 / $0.20 per output second (480p/720p/1080p) intl | S (search; not re-fetched from price page) |
| Kling 3.0 | not verified (resource-pack pricing; resellers vary) | ? |
| Sora 2 | n/a (removed) | V |

Pricing quirks the cost estimator must model: token-based billing (Seedance, Omni) where cost depends on width x height x seconds x 24 fps; input-video surcharges; minimum charges; audio on/off price delta (Veo, Seedance 1.5); aspect ratio affects token count; failed or blocked generations are not billed (Google says so explicitly, Seedance "only successful"); draft-then-final doubles cost but the draft is cheap (480p).

---

## 5. Quirks and traps (things a UI/engine must encode as constraints)

**Constraint-heavy parameters (UI needs dependent/disabled logic, not a flat form):**
- Veo: `durationSeconds` forced to 8 when resolution is 1080p/4k, when using reference images, or extension; extension forces 720p. `personGeneration` allowed values depend on mode (T2V `allow_all` only on Gemini API; I2V/refs `allow_adult` only). Lite has no reference images, no 4K.
- Seedance 2.5: `ratio` is forced to `adaptive` for first-frame, first+last, edit, extend; `duration` forced to `-1` for edit; I2V modes and omni-reference are mutually exclusive; `seed` and `camera_fixed` silently unsupported on 2.x (sending them via the legacy `--seed` suffix may be ignored, strict body mode errors); `service_tier=flex` not available for 2.x; draft only 480p; `omni_reference_task_type` is an early-validation hint, otherwise errors arrive asynchronously (`InvalidParameter.TaskTypeConstraint`, `...TaskTypeMismatch`).
- Seedance 4K and 1080p outputs are 10-bit H.265 (2.0 4K, 2.5 1080p); many players cannot play them. `mov` output uses YUV 4:4:4 + PCM and plays only in some players. Generated audio is mono.
- Luma: 10s excludes HDR, loop, start/end frames; HDR excludes 360p/540p; `keyframes` excludes start/end/loop; EXR needs HDR. 360p is a draft tier.
- Kling 3.0: 4K only on non-Turbo; multi-shot is controlled by prompt syntax whose shot durations must sum to `duration`; `audio` enum differs between endpoints (`original` only on Omni).
- MiniMax H3: T2V requires explicit ratio; I2V ratio ignored (forced adaptive); first/last frame and reference modes cannot be mixed; Max has no 2K and no 4s.
- Wan 3: `prompt_extend` must be true for file/link inputs; keys are region-bound; with video input, input + output seconds <= 30.
- Omni: `task` hint "adds constraints" and Google recommends prompting instead; uploaded-video edit/extend blocked in EEA/CH/UK; no system instructions, temperature, top_p, negative prompt; model produces multi-shot cuts by default unless prompted "single continuous shot".

**Naming/shape inconsistencies (adapter layer must normalize):**
- Aspect ratio: `aspectRatio` (Vertex) vs `aspect_ratio` (Gemini/Luma/Kling settings) vs `ratio` (Seedance/MiniMax/Wan) vs `W:H` pixel strings (Runway `1280:720`).
- Duration: integer (Seedance/Kling/MiniMax/Wan/Runway), string `"8"` (Veo REST), `"5s"` (Luma, Vertex Omni).
- Audio: `generate_audio` bool (Seedance), `generateAudio` bool (Vertex Veo), `audio` bool (Runway/Wan), `settings.audio` enum native/off/original (Kling), always-on (Omni, Gemini Veo).
- Image reference roles: `first_frame`/`last_frame`/`reference_image` (Seedance, MiniMax, Wan), `position: first|last` (Runway), `start_frame`/`end_frame`/`keyframes` (Luma), `image`/`lastFrame`/`referenceImages[].referenceType` (Veo).
- Seed ranges differ (Veo 0..2^32-1, Seedance 1.x -1..2^31-1, Wan -1/0..2^31-1, Runway 0..2^32-1).
- Resolution naming: `720p` vs `720P` vs `768P` vs `2K` vs `4k`. MiniMax uses 768P, not 720p.
- Output delivery: inline base64 (Omni, Vertex without storageUri), hosted URL with TTL (everything else), GCS (Vertex).

**Operational traps:**
- Output URLs expire fast (Luma 1h, Seedance 24h, Runway 24-48h, Gemini 2 days) vs Kling 30 days. A local tool must download immediately and store locally, otherwise the history gallery rots.
- Veo 3.1 GA retirement (Nov 17, 2026 or later) and Gemini API preview shutdown (Oct 22 per one source) imply the model catalog must be data-driven (config/registry), not hardcoded; Seedance 1.5 pro already retired, Sora already gone.
- Seedance requires account activation (balance > $30 or pack); an invalid-key vs not-activated error needs distinct messaging.
- Real-face images are rejected by Seedance 2.x; Omni and Veo also restrict people/minors by region. The UI must surface moderation failures clearly; Google does not charge for blocked generations.
- Seedance promo pricing ended today (2026-10-07 14:00 UTC+8): any hardcoded "discounted" prices are stale.
- Docs are frequently marked preview ("Wan3 preview", "Luma rates may change before GA", Vertex Omni Preview). Expect schema churn; pin versions and add a "last verified" stamp per model.
- Web-app note: browsers calling these APIs directly will hit CORS and expose keys; BYOK on a web UI almost certainly needs a thin backend/proxy (see Q1).

---

## 6. What I could not verify (honest gaps)

- Kling: per-second API price; camera_control and negative_prompt/seed status in the new 3.0 nested schema; lip-sync and Motion Control parameter lists; Kling 4.0 (single third-party claim, announced 2026-09-28).
- Runway: official gen4.5 I2V ratio list and gen4_turbo duration options (I got them from third parties; the fetched api.md only showed T2V details for gen4.5; the I2V section was only partially read).
- Wan 3.0: result video URL TTL, price page (price from search), concurrency/RPS, whether negative_prompt exists; Wan 2.7 field-level details.
- MiniMax: rate limits page, result URL TTL duration, seed on V2.
- Vertex Veo: exact current parameter table for `generateAudio`, `compressionQuality`, `enhancePrompt`, `resizeMode` (the official model-reference URL now redirects to a generic predict page; these came from a search summary, partially from the I2V page: `resizeMode` crop/pad confirmed). Vertex Veo true quota numbers. Whether Veo 3.1 Lite supports extension on Vertex (Vertex says yes, Gemini API says no).
- Gemini API: whether Omni accepts a `duration` field (Vertex docs say `duration` "3s"-"10s"; Gemini API docs fetched show none).
- Veo 3.1 preview shutdown date 2026-10-22 on Gemini API: single source.
- Latency numbers beyond Google ("11s to 6 min"), Luma ("under 2 min"), Runway example ("15s"), Wan ("1-5 min"); none are SLAs.
- No hands-on API calls were made (no keys). Everything is doc-derived.
- xAI Grok Imagine Video 1.5 and HappyHorse 1.0: seen only in Runway's catalog; not researched.

---

## 7. QUESTIONS for the product owner

1. **Q: Sora is gone. Do we drop the OpenAI video provider entirely, and what do we use the OpenAI key for (images only, or nothing)?**
   Why it matters: the stated provider list is invalid; scope and the "OpenAI key" onboarding step change.
   Options: (a) drop Sora, keep OpenAI key for image models only; (b) drop OpenAI entirely from v1; (c) keep a disabled "Sora (discontinued)" placeholder for the history of past outputs.

2. **Q: For Google, which backend and model tier is the target: Vertex (GCS, service account/ADC), Gemini API key, or both? And is Gemini Omni first-class or is Veo 3.1 the default?**
   Why it matters: Google says Omni is the default video model and Veo 3.1 on Vertex retires Nov 17, 2026 or later; auth, output handling (GCS vs inline vs 2-day hosted URL), quotas and the whole request shape (`predictLongRunning` vs Interactions API) differ.
   Options: (a) Gemini API key only (simplest BYOK, Omni GA + Veo preview); (b) Vertex only (enterprise, GCS, Omni still Preview); (c) both behind one "Google" adapter with a backend switch.

3. **Q: Which Seedance access path: BytePlus ModelArk direct, or via an aggregator (fal, Replicate, Runway Dev)? Is the user outside China?**
   Why it matters: ModelArk has the full parameter surface (draft, priority, task-type hint, mov, callbacks) and about half the price of fal, but requires activation with a balance above $30 and has no `seed` for 2.x; aggregators reduce signup friction but change parameters, prices and support a subset. Volcengine (China) uses different IDs.
   Options: (a) ModelArk direct only; (b) ModelArk plus fal/Replicate as fallback; (c) one gateway (Runway Dev or fal) for several models to cut the number of keys.

4. **Q: What does "ALL real parameters" mean in practice: schema-faithful per model (each model's native names/ranges, with constraint rules and disabled states) or a normalized common form with an "advanced raw JSON" escape hatch?**
   Why it matters: the parameter spaces are heavily conditional (duration forced to 8 for 1080p, ratio forced adaptive for edit, mutually exclusive modes). Faithful forms need a declarative per-model schema with dependency rules; normalized forms hide features.
   Options: (a) per-model declarative schema driving the form (recommended for the stated requirement), plus raw JSON editor; (b) common core fields plus per-model "advanced" accordion; (c) raw JSON only in v1.

5. **Q: What is the contract for "N variants in one go"?**
   Why it matters: only Vertex Veo has native `sampleCount` (1-4); everything else is N separate paid jobs, limited by per-account concurrency (Seedance individual tier: 3 concurrent; Kling pack-based; Runway tier-based). Also decides cost safety and UI.
   Options: (a) N identical requests with different seeds (only works where a seed exists; Omni, Seedance 2.x, Kling 3, Luma have none, so variance is random); (b) a parameter sweep (variants differ by prompt/duration/resolution/model, a matrix view); (c) both, with a hard cost cap and a pre-flight cost total shown before submit.

6. **Q: Is cross-model comparison ("same prompt to Veo, Omni, Seedance, Kling side by side") a core use case, or is each model used separately?**
   Why it matters: comparison requires a normalized request mapper and an unsupported-parameter policy (silently drop, warn, block); separate use only needs per-model forms.
   Options: (a) core: shared prompt/images/duration/ratio mapped to each model with a diff of what was dropped; (b) secondary: copy settings between models best-effort; (c) none in v1.

7. **Q: Where do generated files live, and for how long?**
   Why it matters: output URLs expire in 1h (Luma), 24h (Seedance, Wan task), 24-48h (Runway), 2 days (Gemini API), 30 days (Kling), while Vertex can write to the user's GCS. Determines storage, privacy, and whether history works after a week.
   Options: (a) auto-download everything to local disk/IndexedDB immediately, history is local-only; (b) store to user-provided cloud bucket (GCS/S3); (c) keep only provider URLs and warn on expiry (not recommended).

8. **Q: Is this local-only (runs on the user's machine, keys in a local config) or a hosted web app with user accounts?**
   Why it matters: BYOK from a browser exposes keys and hits CORS (most video APIs are not browser-callable); webhooks (Seedance, Kling, MiniMax) need a public URL, otherwise polling; Vertex needs ADC/service-account JSON that must not live in a browser. Key storage and long-running job survival (tab closed) differ.
   Options: (a) local app with a small local backend (keys in OS keychain or `.env`, polling, jobs survive tab close); (b) hosted multi-user with an encrypted key vault and a job queue; (c) pure browser SPA (limits: no Vertex, CORS, keys in localStorage).

9. **Q: Which input modes are must-have for v1: image-to-video, first+last frame, multi-reference, video extend, video edit, lip-sync/avatar, motion control?**
   Why it matters: each mode needs an asset upload pipeline with constraints (size, ratio, duration, formats); reference video/audio inputs need public URLs or base64 (64 MB body caps) and, for Seedance 2.x, real-face rejection. Lip-sync, avatar and motion control (Kling) are separate APIs from basic generation.
   Options: (a) T2V + I2V (first/last) + multi-reference images only; (b) add extend/edit; (c) full set including audio/video references and Kling-specific tools.

10. **Q: How should cost be controlled and shown?**
    Why it matters: costs swing 100x (Veo Lite $0.03/s to Seedance 2.0 4K $0.78/s, Luma 10s 1080p $3.60), pricing is token-based for Seedance/Omni, several models bill input video, draft modes exist, and promos expire (Seedance promo just ended). With N variants, a mistake multiplies.
    Options: (a) mandatory pre-flight estimate plus per-batch cap and confirmation; (b) soft estimate only, running spend ledger; (c) none (user's own keys). Also decide whether to ship a pricing table that is refreshed manually or fetched.

11. **Q: How strict should we be with unverified or unstable models (Wan 3 preview, Vertex Omni Preview, Luma Ray 3.2 rates before GA, Kling 4.0 coming this month)?**
    Why it matters: schemas will churn; Veo 3.1 GA retires in about 6 weeks, Seedance 1.5 pro already retired. A hardcoded catalog goes stale fast.
    Options: (a) data-driven model registry (JSON/YAML per model with params, constraints, prices, `lastVerified`, status) updatable without code releases; (b) ship a fixed v1 catalog (Omni, Veo 3.1, Seedance 2.5/2.0, Kling 3.0) and add later; (c) adapters via a gateway (Runway Dev / fal) to inherit their catalog churn.

12. **Q: Which providers are actually in the v1 "model list", given the brief says "possibly Kling, Runway, Luma, Hailuo, Wan"?**
    Why it matters: each provider is a separate adapter with its own auth, async protocol and error model; effort is roughly one adapter per provider. Hailuo is now MiniMax H3 (new V2 API), Wan is Wan 3.0 (region-bound keys, Alibaba Model Studio), Runway doubles as a gateway.
    Options: (a) Tier 1: Google (Omni+Veo), Seedance, Kling; Tier 2 later: Luma, MiniMax, Wan, Runway; (b) all eight in v1 (large); (c) Google + Seedance + one gateway (Runway Dev or fal) to cover the rest cheaply.

13. **Q: What is the policy for content/safety and moderation outcomes?**
    Why it matters: Seedance rejects real-face inputs and returns async errors; Veo/Omni block by region and for minors; Google does not charge for blocked outputs; Seedance exposes `safety_identifier`; Runway has `publicFigureThreshold`; watermark options vary (Kling/Seedance/Wan visible watermark toggles, Google SynthID mandatory).
    Options: (a) pass-through with clear error surfacing and a per-model "restrictions" note; (b) add a local pre-check (face/minor detection) before upload; (c) no handling beyond display of provider errors.

14. **Q: Do you want prompt tooling (prompt enhancement/rewrite, multi-shot builder, negative prompt handling) in the studio?**
    Why it matters: capability is uneven: negative_prompt exists only on Veo; Omni/Kling/Seedance take negatives inside the prompt; rewrite toggles exist on Wan (`prompt_extend`), MiniMax Max (3 modes), legacy Hailuo; Kling multi-shot needs the "shot n, m, words" syntax; Seedance and Wan support in-prompt references like [Image1]/"Image 1". A shared prompt layer could translate these.
    Options: (a) per-model controls only (expose exactly what the API has); (b) add a studio-side prompt helper (LLM rewrite, multi-shot builder) that outputs per-model prompt syntax; (c) defer.

15. **Q: Do multi-step workflows matter (draft then final, last-frame chaining for long videos, extend loops, edit-the-result)?**
    Why it matters: Seedance draft (480p, then enhance, `return_last_frame` for chaining), Veo extend (+7s up to 20x within the 2-day window), Omni stateful edit (`previous_interaction_id` requires `store:true`), Luma generation_id extend all rely on provider-side state that expires. Implementation is a graph of jobs rather than a single request.
    Options: (a) single-shot generations only in v1; (b) support "use as input / extend / edit this output" actions on a result card (needs provider IDs persisted); (c) full job-graph/timeline editor.

---

## 8. SOURCES

First-party (fetched):
- OpenAI deprecations (Sora/Videos API removal 2026-09-24): https://developers.openai.com/api/docs/deprecations
- Gemini API, Gemini Omni Flash: https://ai.google.dev/gemini-api/docs/omni (raw: https://ai.google.dev/gemini-api/docs/omni.md.txt)
- Gemini API, Veo 3.1: https://ai.google.dev/gemini-api/docs/veo (raw `.md.txt`), video overview https://ai.google.dev/gemini-api/docs/video
- Gemini API pricing: https://ai.google.dev/gemini-api/docs/pricing
- Vertex (Gemini Enterprise Agent Platform) video overview: https://docs.cloud.google.com/vertex-ai/generative-ai/docs/video/overview
- Vertex Veo 3.1 model page: https://docs.cloud.google.com/vertex-ai/generative-ai/docs/models/veo/3-1-generate
- Vertex Omni 1.1 Flash model page: https://docs.cloud.google.com/vertex-ai/generative-ai/docs/models/gemini/omni-1-1-flash
- Vertex text-to-video, image, first/last, references, extend, edit pages: https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/video/generate-videos-from-text (siblings: `generate-videos-from-an-image`, `generate-videos-from-first-and-last-frames`, `generate-videos-from-references`, `extend-videos`, `edit-videos`)
- Vertex generative AI pricing: https://cloud.google.com/vertex-ai/generative-ai/pricing
- BytePlus ModelArk, Create video generation task (Seedance 2.5/2.0/1.x parameters): https://docs.byteplus.com/en/docs/ModelArk/1520757
- ModelArk Retrieve task: https://docs.byteplus.com/en/docs/ModelArk/1521309
- ModelArk Seedance 2.5 tutorial: https://docs.byteplus.com/en/docs/ModelArk/2607688
- ModelArk model list and rate limits: https://docs.byteplus.com/en/docs/ModelArk/1330310
- ModelArk pricing: https://docs.byteplus.com/en/docs/ModelArk/1544106
- Kling API docs index (llms.txt): https://kling.ai/document-api/llms.txt ; text-to-video 3.0: https://kling.ai/document-api/api/video/3-0-omni/text-to-video.md ; image-to-video: https://kling.ai/document-api/api/video/3-0-omni/image-to-video.md ; omni: https://kling.ai/document-api/api/video/3-0-omni/video-omni.md ; turbo: https://kling.ai/document-api/api/video/3-0-turbo/text-to-video.md ; concurrency: https://kling.ai/document-api/api/get-started/concurrency-rules.md
- Runway Dev: https://docs.dev.runwayml.com/llms.txt , API reference https://docs.dev.runwayml.com/api.md , models https://docs.dev.runwayml.com/guides/models.md , pricing https://docs.dev.runwayml.com/guides/pricing.md , tiers https://docs.dev.runwayml.com/usage/tiers.md , context https://docs.dev.runwayml.com/ai-context.md
- Luma Agents API video generation: https://docs.agents.lumalabs.ai/guides/videos/generation ; pricing https://docs.agents.lumalabs.ai/guides/pricing ; rate limits https://docs.agents.lumalabs.ai/guides/rate-limits
- MiniMax V2 video create: https://platform.minimax.io/docs/api-reference/video-generation-v2-create.md ; query: https://platform.minimax.io/docs/api-reference/video-generation-v2-query.md ; pay-as-you-go pricing https://platform.minimax.io/docs/guides/pricing-paygo.md ; models https://platform.minimax.io/docs/guides/models-intro.md ; index https://platform.minimax.io/docs/llms.txt
- Alibaba Wan3.0 API reference: https://www.alibabacloud.com/help/en/model-studio/wan3-video-generation-api-reference ; guide https://www.alibabacloud.com/help/en/model-studio/wan3-video-generation-guide
- fal.ai Kling schemas (OpenAPI): https://fal.ai/api/openapi/queue/openapi.json?endpoint_id=fal-ai/kling-video/v3/pro/text-to-video

Third-party / search-derived (lower confidence):
- Veo 4 status and Veo 3.1 Lite: https://aireiter.com/blog/veo-4 , https://dev.to/tokenmixai/veo-4-release-date-70-odds-for-google-io-2026-veo-31-lite-live-500e
- Seedance 2.5 launch/pricing/aggregators: https://www.cometapi.com/seedance-2-5-api-pricing/ , https://fal.ai/models/bytedance/seedance-2.5/text-to-video , https://replicate.com/bytedance/seedance-2.5 , https://openrouter.ai/bytedance/seedance-2.5
- Seedance 3.0 not announced: https://mobilemall.co/blog/seedance-3-0-is-not-out-yet-what-the-2-5-update-already-gives-away-about-it/
- Seedance 2.5 third-party guide (marketing, some unverified claims e.g. 4K): https://github.com/Anil-matcha/awesome-seedance-2.5-api-prompts
- Sora shutdown coverage: https://higgsfield.ai/blog/sora-api-migration-guide , https://community.openai.com/t/is-the-sora2-api-still-working/1379946
- Kling 3.0 / 4.0 status: https://en.wikipedia.org/wiki/Kling_AI , https://pexo.ai/blog/what-is-kling-3-0-turbo-3190
- Wan 3.0 launch: https://winbuzzer.com/2026/08/25/alibaba-launches-wan3-0-for-30-second-ai-video-from-documents-xcxwbn/ ; Wan 2.7: https://www.alibabacloud.com/help/en/model-studio/text-to-video-api-reference
- Hailuo 2.3 legacy summary: https://www.pixazo.ai/models/hailuo , https://replicate.com/minimax/hailuo-2.3

Status: DONE_WITH_CONCERNS
