# Research: IMAGE generation parameters per provider/model (as of 2026-10-07)

Method: official docs fetched/parsed directly where possible (Gemini API docs, Vertex docs, OpenAI guide + model pages, BFL openapi.json, Ideogram v2 docs, Recraft docs). Seedream and Stability official pages are JS-rendered and could NOT be parsed; those rows rely on search snippets/third parties and are flagged. Confidence tags: [V]=verified in official source this session, [P]=partial/third-party, [?]=unverified.

## 0. Headline findings (change the product plan)

1. **Imagen is dead.** Gemini API: Imagen shut down (docs: "Imagen models are shut down"; reported shutdown 2026-08-17 [P]). Vertex release notes: all imagen-3.0/4.0 GA endpoints "deprecated", update before 2026-06-30 [V]; none appear in Vertex model-versions table. Do NOT build an Imagen adapter. Google's image lineage is now Gemini "Nano Banana" via generateContent/Interactions. Imagen-only knobs (sampleCount up to 4, negativePrompt, seed+addWatermark=false, personGeneration, safetyFilterLevel, enhancePrompt, outputOptions compression) have no direct Gemini equivalent.
2. **Vertex AI is now branded "Gemini Enterprise Agent Platform"** (docs). Gemini image models are available there too (global location, GOOGLE_GENAI_USE_ENTERPRISE=True) [V].
3. **OpenAI latest = `gpt-image-2.5-sunburst` (precision/edit) and `gpt-image-2.5-flare` (fast)**, launched 2026-09-08 [V/P]. gpt-image-2 (Apr-Jun 2026), 1.5, 1, 1-mini are older. dall-e-2/3 legacy.
4. **BFL: FLUX.3 image (`/v1/flux-3-image`) exists** alongside FLUX.2 [pro|max|flex|klein 4B/9B] [V from openapi.json]. FLUX.3 dropped width/height/seed in favour of `aspect_ratio`+`resolution` (no `seed` field in schema).
5. **Ideogram API v2 is also an aggregator**: hosts Ideogram 4.0 / 4.5 and proxies GPT Image 2/2.5, Nano Banana 2/Pro, Z-Image, P-Image, Topaz upscalers, Kling/MiniMax/Seedance 2.0/2.5 video [V]. Relevant for "other hosts" strategy.
6. **Seedream latest = 5.0 family (Pro / Flash / Lite)**; Pro launched 2026-07-08 [P]. Different model IDs on BytePlus (international, `dola-…` prefix reported) vs Volcengine (China, `doubao-…`) [P].
7. **Stability: no new image model found in 2026**; flagship still SD 3.5 Large / Stable Image Ultra [P].
8. **Parameter surfaces diverge wildly** (e.g. 'n' max: OpenAI 10, Ideogram 8, Recraft 6, BFL 1, Gemini ~1 "won't always follow" count). A generic "N variants" feature must be implemented as **client-side fan-out** (N parallel requests) with native batching only as an optimisation. Seed determinism is absent/weak on Gemini and OpenAI.

## 1. Model catalogue (current)

| Provider | Latest model IDs | Notes |
|---|---|---|
| Google (Gemini API & Vertex) | `gemini-nano-banana-2.1` (new workhorse), `gemini-3.1-flash-image` (NB2), `gemini-3.1-flash-lite-image` (NB2 Lite, cheapest), `gemini-3-pro-image` (NB Pro; often seen as `-preview`), `gemini-2.5-flash-image` (legacy, shutdown 2026-10-02 reported [P]) | [V] docs list. Vertex retirement: 3.1-flash-lite-image 2027-06-28+, 3-pro-image / 3.1-flash-image 2027-05-28+. Vertex list also includes `gemini-nano-banana-2.1`. |
| OpenAI | `gpt-image-2.5-sunburst`, `gpt-image-2.5-flare` (snapshots `...-2026-09-08`); `gpt-image-2`, `gpt-image-1.5`, `gpt-image-1`, `gpt-image-1-mini` | [V] Image API only (`/v1/images/generations`, `/edits`; Batch ok). Org Verification may be required. |
| ByteDance Seedream | Seedream 5.0 Pro (`...seedream-5-0-pro-260628`), 5.0 Flash, 5.0 Lite (`seedream-5-0-260128`), 4.5, 4.0 | [P] IDs from third parties; confirm in ModelArk console. |
| BFL | FLUX.3 image; FLUX.2 pro / max / flex / klein-4b / klein-9b (dev = open weights only); FLUX.1 Kontext pro/max, 1.1 pro/Ultra, Fill, Expand | [V] openapi.json. Tools: outpainting, erase, deblur, vto. |
| Ideogram | Ideogram 4.5 (edit-centric, new), 4.0, 3.0 (+character, custom model), 2a/2 | [V] |
| Recraft | `recraftv4_1` (default), `_pro` (2K), `_flash`, `_utility`, `recraftv4`, `recraftv4_styles`, + `_vector` variants; V3/V2 legacy | [V] |
| Stability | Stable Image Ultra (SD3.5 Large), Core, SD 3.5 Large/Medium/Turbo; edit tools | [P] |

## 2. Parameter matrix (generation)

Legend: Y=supported, -=not supported, ?=unverified. "n" = images per request.

### 2a. Google Gemini image (Gemini API `generateContent`/Interactions; Vertex generateContent)

| Param | NB2.1 `gemini-nano-banana-2.1` | NB2 `gemini-3.1-flash-image` | NB2 Lite `…flash-lite-image` | NB Pro `gemini-3-pro-image` | `gemini-2.5-flash-image` |
|---|---|---|---|---|---|
| Aspect ratio | 1:1,2:3,3:2,3:4,4:3,4:5,5:4,9:16,16:9,21:9 **+ 1:4,4:1,1:8,8:1** [V table] | 10 std ratios (+extreme ones? [?]) | 10 std ratios | 10 std ratios | 10 std ratios |
| Size tier (`image_size`, UPPERCASE K or rejected) | 1K,2K,4K (no 0.5K) | 512px(0.5K),1K,2K,4K | **1K only** | 1K,2K,4K | fixed ~1K |
| Output px (1:1) | 1024/2048/4096 | + 512 | 1024 | 1024/2048/4096 | 1024 |
| n per request | not controllable; "won't always follow exact number" | same | same | same | same (candidateCount appears in samples, unreliable [?]) |
| Reference images | 14 total: ≤10 objects + ≤4 characters (+ style refs?) [V] | same as 2.1 | up to 14 objects; characters N/A (per table) | 14 total: ≤6 objects, ≤5 characters | best ≤3 |
| Edit / multi-turn | Y (conversational) | Y | not optimised for multi-turn | Y | Y |
| Negative prompt | - (use "semantic negatives") | - | - | - | - |
| Seed | ? (generationConfig.seed exists on API but determinism not documented for images) | ? | ? | ? | ? |
| Guidance/steps | - | - | - | - | - |
| Thinking | Y (thinking_level, e.g. "high"; thought images not billed) | Y | ? | Y | - |
| Google Search grounding | Y (web + image search) | Y (web+image) | **-** | Y | - |
| Output mime | jpeg/png via `response_format.mime_type` (Interactions) [P] | same | same | same | same |
| Safety | `safetySettings` (category/threshold/method) on Vertex+API [V sample]; no Imagen-style personGeneration | same | same | same | same |
| Watermark | SynthID always on, not removable [V] | same | same | same | same |
| Text rendering | strong (best langs listed: EN, ar-EG, de, es-MX, fr, hi, id, it, ja, ko, pt-BR, ru, uk, vi, zh) | | | | |
| Video input as context | Y | Y | Y | - | - |
| Prompt rewriting | implicit via thinking; no flag | | | | |
| Per-image price (std) | $0.034 (1K) / $0.050 (2K) / $0.076 (4K) [V via search of Google page] | ~$0.067/0.101/0.151, 0.5K $0.045 [P] | cheapest (price ? ) | $0.134 (1K/2K) / $0.24 (4K) [V] | legacy |
| Batch price | 50% (NB2.1 $15/M tokens) | 50% | | 50% | |

Quirks: Two API shapes coexist: classic `generationConfig.imageConfig{aspectRatio,imageSize}` (camelCase; still in Vertex samples) vs new Interactions API `response_format{type:"image",aspect_ratio,image_size,mime_type}` (snake_case; docs default to it for NB2.1). Adapter must pick one per host. Default output matches input image size, else 1:1. 4:5/5:4 and extreme ratios have lower token counts. Response may contain interleaved text; request image-only via response_format.

### 2b. OpenAI

| Param | gpt-image-2.5 sunburst/flare | gpt-image-2 | gpt-image-1.x |
|---|---|---|---|
| prompt max | 32k chars [P, from older spec] | same | 32k |
| size | `auto` or any `WxH`: edges multiple of 16, max edge 3840, ratio ≤3:1, 655,360–8,294,400 px; >2560x1440 "experimental" [V] | same constraints [V] | 1024x1024, 1536x1024, 1024x1536, auto |
| quality | low, medium, high, **xhigh, max**, auto(default) [V] | low/medium/high/auto | low/medium/high/auto |
| n | 1–10 (older spec; recheck) [P] | 1–10 | 1–10 |
| output_format | png(default)/jpeg/webp [V] | same | same |
| output_compression | 0–100 for jpeg/webp [V] | | |
| background | transparent/opaque/auto; transparent needs png/webp [V] | | (gpt-image-2 transparent support: ? treat 2.5 as Y) |
| moderation | `auto`(default) / `low` [V] | | |
| input_fidelity | n/a for 2/2.5 (always high; param disallowed on gpt-image-2; assume same on 2.5 [?]) | omit | low/high |
| partial_images (streaming) | 0–3, +100 output tokens each [V] | | |
| Edit: images | up to 16 PNG/WEBP/JPG <25MB each [P older spec; recheck for 2.5] | | 16 |
| Mask | PNG with alpha, <4MB, same dims, applied to **first** image; prompt-guided, not pixel-exact [V] | | |
| seed / negative / guidance / steps / style | - (none) | - | - (dall-e-3 `style` vivid/natural legacy only) |
| Watermark | C2PA metadata (not verified this session [?]) | | |
| Response | base64 only (no URL) | | |
| Price | tokens: $5/M text in, $8/M image in, $30/M image out; batch -50% image out. Per-image: gpt-image-2 1024² low $0.006 / med $0.053 / high $0.211 [V]; 2.5 table not rendered, token counts differ by model/quality (low 1024²≈196 tokens ≈ $0.006 shown) [P] | | 1.5/1 legacy flat tables |
| Rate limits | IPM: Build 20, Launch 150, Grow 250 (official model page); third-party shows Tier1 5 IPM → Tier5 250 [conflict, tier naming changed] | | |

Quirks: Latency up to 2 min; Responses API route adds mainline-model token cost and multi-turn editing; cached image input pricing only in Responses tool path. Errors: `image_generation_user_error` / `moderation_blocked` with `moderation_details{stage,categories}` - do not auto-retry. `auto` for size/quality/background makes cost unpredictable: estimator must show "unknown".

### 2c. ByteDance Seedream (ModelArk `POST /api/v3/images/generations`, ark.ap-southeast.bytepluses.com) [P: official page not parseable]

| Param | Notes |
|---|---|
| model | per-region IDs (see §1) |
| prompt | rec. ≤300 CJK chars / 600 English words |
| size | `1K`/`1.5K`/`2K` (5.0, 1.5K priced as 1K) or `WxH`; 3K/4K tiers for Lite/4.5/4.0 disputed; 5.0 Pro max 2K [P conflict] |
| aspect ratios | ~17 incl. 1:1,2:3,3:2,3:4,4:3,9:16,16:9,21:9; ratio range 1:16–16:1 on Pro [P conflict] |
| image (refs) | Pro: 10 (most sources; OpenRouter says 14); Lite/4.5/4.0: up to 14; input+output ≤15 |
| sequential_image_generation | `auto`/`disabled` (default disabled); `…_options.max_images`; NOT on Pro/Flash; billed per output image |
| response_format | `url` (default, ~24h expiry [?]) / `b64_json` |
| output_format | png/jpeg on 5.0; jpeg only on 4.x [P] |
| watermark | boolean; default differs by version (true on 3.0 doc) -> always send explicitly |
| optimize_prompt_options | mode `standard` (4.0 also `fast`) [P] |
| tools | web_search on Lite (not Pro/Flash) [P] |
| stream | Lite yes; Pro no [P] |
| seed, guidance_scale | seed: ? (3.0 had seed + guidance_scale; Pro: guidance_scale not supported [P]); negative prompt: - [?] |
| Price | Pro $0.045 (1K) / $0.09 (2K) + $0.003/extra ref; Lite $0.035; Flash from ~$0.018 [P] |

### 2d. Black Forest Labs (api.bfl.ai, async: submit → poll `get_result` / webhook; auth `x-key`) [V openapi.json]

| Param | FLUX.3 image | FLUX.2 pro/max | FLUX.2 flex | FLUX.2 klein 4B/9B | FLUX.1 Kontext pro/max | FLUX1.1 Ultra |
|---|---|---|---|---|---|---|
| width/height | - | int ≥64 (mult. of 16; ≤~4MP), 0=auto | same | same | - (aspect_ratio) | - |
| aspect_ratio | auto + 15: 21:9,2:1,16:9,3:2,7:5,4:3,5:4,1:1,4:5,3:4,5:7,2:3,9:16,1:2,9:21 | - | - | - | string (limits ?) | string, default 16:9 |
| resolution tier | 768sq,1k,1.5k,2k,4k (default 1k) | - | - | - | - | - |
| seed | **not in schema** | Y | Y | Y | Y | Y |
| guidance / steps | - | - | guidance (default 5), steps (default 50) | - | - | - |
| prompt_upsampling | (grounding bool, default true: web+image search) | `disable_pup` (default false) | prompt_upsampling (default true) | - | prompt_upsampling (false) | false |
| safety_tolerance | int 0–4 (default 2) | 0–5 (2) | 0–5 | 0–5 | 0–6 | 0–6 |
| output_format | not listed | jpeg(default)/png/webp | same | same | png default | jpeg |
| reference images | `images` 1–10 (URL/base64) | input_image..input_image_8 (8) | 8 (+blob path) | 4 | 4 (input_image..4) | `image_prompt`+strength 0–1 (0.1) |
| n | 1 (client fan-out) | 1 | 1 | 1 | 1 | 1 |
| negative prompt | - | - | - | - | - | - |
| Inpaint/outpaint/erase/upscale | Tools: Fill (guidance 60, steps 50), Expand (top/bottom/left/right), outpainting-v1, erase-v1 (mask, dilate_pixels 0–25), deblur, vto | | | | | raw: bool |
| Webhook | webhook_url/secret | Y | Y | Y | Y | Y |
| Price | $0.041 (768sq) / $0.048 (1k) / $0.10 (2k) / $0.607 (4k) [V] | pro from $0.03 (edit $0.045), max from $0.07 | from $0.05 | 4B from $0.014, 9B from $0.015 | $0.04 / $0.08 | $0.06 |

Quirks: pricing is megapixel-based on FLUX.2 (cost depends on width×height, incl. input images for editing); credits 1=$0.01; submission response returns cost. Results URLs are short-lived (download promptly) [?]. Third-party hosts (fal, Azure Foundry, AIML) rename params (`image_size` presets, `image_urls`).

### 2e. Ideogram (api.ideogram.ai; `Api-Key` header) [V]

| Param | 4.5 `/v2/image/generate/ideogram-4-5` | 4.0 `/v2/image/generate/ideogram-4` | 3.0 `/v1/ideogram-v3/generate` |
|---|---|---|---|
| prompt | NL or structured JSON prompt | same | text |
| num_images | Y (max not stated; 3.0 = 1–8) | Y | 1–8 |
| size/resolution | `size`: auto/source/exact WxH from 1K/2K presets | `resolution` enum, 38 values 512x1536 … 2880x1440, 2048x2048 | `resolution` (69 values) XOR `aspect_ratio` (15, e.g. 1x1,16x9) |
| quality | `quality` (very_low…high; very_low only with source images; default high w/o images, medium with) | - (uses `rendering_speed` turbo/default/quality) | `rendering_speed` FLASH/TURBO/DEFAULT/QUALITY |
| magic_prompt | auto/on/off | auto/on/off | AUTO/ON/OFF |
| seed | Y | Y | 0–2147483647 |
| negative_prompt | ? | **no** | Y |
| style | - | - | style_type AUTO/GENERAL/REALISTIC/DESIGN/FICTION; style_preset (62), style_codes, color_palette (preset or hex+weights), custom_model_uri |
| edit | `images` ≤5 (≤25MB), `mask` (black=edit) | - (Remix/transparent endpoints) | Remix, Inpaint, Reframe, Replace BG, Upscale, Describe, Layerize |
| transparent | n/a | separate endpoint `ideogram-4-transparent` (PNG alpha) | separate transparent endpoint (FLASH unsupported) |
| extras | `enable_copyright_detection`, `dry_run=true` (price quote, no billing), `async`/`webhook_url`/poll `GET /v2/generations/{id}` | same | sync |
| Price | ? (not verified) | Turbo $0.03 / Default $0.06 / Quality $0.10 [P] | $0.03 / $0.06 / $0.09 (char ref $0.10–0.20) [P] |

Quirks: images `is_image_safe=false` → empty URL (billed? unknown). URLs ephemeral. `dry_run` price quote = ideal for the cost estimator.

### 2f. Recraft (external.api.recraft.ai/v1, OpenAI-SDK compatible) [V]

| Param | Details |
|---|---|
| model | recraftv4_1 (default), recraftv4_1_pro, _flash, _utility(+_pro), recraftv4, recraftv4_pro, recraftv4_styles(+_pro), V3/V2 (+_vector). Default becomes recraftv4_styles when style refs attached |
| n | 1–6 |
| size | `w:h` ratio (preferred, 14 ratios incl. 2:1,3:2,4:3,5:4,6:10,14:10,16:9 + inverses) or exact WxH from per-model table: 1K models 1024², 1536x768, … ; Pro 2K models 2048² etc.; vector = ratio only |
| style / style_id / style_match | style enum (raster+vector; not on V4.1 Flash); style_id (custom, mutually exclusive with style_references); style_match `regular` (V2/V3) / `flexible`,`precise` (V4+) |
| style_references | 1–10 images, ≤64MB total (creates private style, +$0.005) |
| negative_prompt | **V2/V3 only** |
| random_seed | Y |
| response_format | url (default, ~24h) / b64_json / multipart (lowest latency) |
| image_format | webp (default, lossless) / png (raster) ; vector → SVG |
| text_layout | V3 only (bounding boxes) |
| controls | artistic_level 0–5 (V3), background_color, colors, no_text; partial on V4 |
| prompt max | 10,000 chars (V4+), 1,000 (V2/V3) |
| Endpoints | image-to-image, inpaint, outpaint, replace/generate background, vectorize ($0.01), remove background ($0.01), erase region, crisp upscale ($0.004), creative upscale ($0.25), refine details ($0.21), remix, enhance prompt ($0.01) |
| Price/img | V4.1 Flash $0.007; V4.1 $0.035 (cols for other variants: $0.08/$0.21/$0.30 - column headers not parsed, likely vector / Pro 2K / Pro vector [?]); V4 Styles $0.035; V4 $0.04; V3 $0.04/$0.08; V2 $0.022 |
| Rate limits | 100 images/min and 5 req/s per user [V] |
| Input images | PNG/JPG/WEBP <20MB, ≤16MP, ≤4096 px, ≥256 px; masks grayscale pure 0/255 |

### 2g. Stability AI (api.stability.ai/v2beta/stable-image/generate/{ultra|core|sd3}) [P]

prompt (≤10,000), negative_prompt (≤10,000), aspect_ratio (21:9,16:9,3:2,5:4,1:1,4:5,2:3,9:16,9:21; default 1:1; dropped in img2img), seed 0–4,294,967,294 (0=random), style_preset (17: 3d-model, analog-film, anime, cinematic, comic-book, digital-art, enhance, fantasy-art, isometric, line-art, low-poly, modeling-compound, neon-punk, origami, photographic, pixel-art, tile-texture; Core, SD3 [?]), output_format png(default)/jpeg/webp, strength 0–1 (img2img, default 0.7), SD3.5: `model`, `cfg_scale`. n=1. Prices: Ultra 8 credits ($0.08), SD3.5 Medium 3.5 ($0.035), Core 3 ($0.03); 1 credit=$0.01. Edit tools (inpaint, erase, outpaint, search-and-replace/recolor, remove BG, upscale conservative/creative/fast, control sketch/structure/style) exist [?: not re-verified]. Unverified: rate limit (historically 150 req/10s).

## 3. Cross-provider capability matrix (summary)

| Capability | Gemini NB* | OpenAI 2.5 | Seedream 5 | FLUX.2/3 | Ideogram 4/4.5 | Recraft V4 | Stability |
|---|---|---|---|---|---|---|---|
| n per request | ~1 (unreliable) | 1–10 | 1 (Pro) / up to 15 seq (Lite) | 1 | 8 (3.0) | 6 | 1 |
| Seed | ? | - | ? | Y (not FLUX.3) | Y | Y | Y |
| Negative prompt | - | - | - | - | 3.0 only | V2/V3 only | Y |
| Guidance/CFG | - | - | ? | flex only | - | - | SD3.5 cfg_scale |
| Steps | - | - | - | flex only | - | - | - |
| Quality knob | size tier+thinking | low…max | size tier | resolution/MP | speed or quality enum | model tier | model |
| Style presets | - (prompt) | - | - | - | 3.0 style_type/preset/codes | styles+substyles, style refs | style_preset |
| Size model | ratio enum + 1K/2K/4K | free WxH within rules | tier or WxH | WxH or ratio+tier | enum list | ratio / enum WxH | ratio enum |
| Output format | png/jpeg | png/jpeg/webp+compression | png/jpeg | jpeg/png/webp | server-chosen (PNG for transparent) | webp/png/svg | png/jpeg/webp |
| Transparent bg | - | Y (png/webp) | - | - | separate endpoint | remove-bg endpoint / vector | remove-bg tool |
| Safety control | safetySettings | moderation auto/low | ? | safety_tolerance | server (is_image_safe) | - | server |
| Watermark | SynthID (forced) | metadata | `watermark` bool | - | - | - | - |
| Prompt rewrite | thinking (implicit) | implicit | optimize_prompt_options | upsampling/pup/grounding | magic_prompt | enhance endpoint ($0.01) | - |
| Ref images | 14 | 16 | 10–14 | 8 (F2) / 10 (F3) | 5 (4.5) | style refs 10 | img2img / control |
| Inpaint mask | prompt-based edit (no mask param) | mask (first image) | ? | Fill/Expand/Erase tools | mask (4.5, 3.0 inpaint) | inpaint (mask) | inpaint |
| Outpaint | prompt | prompt/size | ? | Expand/outpainting | Reframe | outpaint | outpaint |
| Upscale | - | - | - | (video upscaler only) | Topaz via hub | crisp/creative | Y |
| Text rendering | strong | strong | strong (Pro) | flex typography | very strong | V3 text_layout | fair |
| Async pattern | sync | sync (stream) | sync | async poll/webhook | sync or async | sync | sync |
| Return | base64 inline | base64 only | url/b64 | URL (short-lived) | URL (ephemeral) | URL ~24h / b64 | binary/b64 |

## 4. Rate limits / quotas (best known)
- OpenAI gpt-image-2.5: IPM Build 20 / Launch 150 / Grow 250; TPM 250k–8M [V official model page]. Older tier naming (Tier1 5 IPM) appears in third parties.
- Gemini: per-project RPM/TPM/RPD + IPM for image models; NB2/Pro not on free tier; Batch API 50% cheaper, ≤24h; exact numbers only in AI Studio/console [V framework, ? numbers].
- Recraft: 100 images/min, 5 req/s per user [V].
- BFL: documented concurrency limits not verified [?].
- Ideogram: 402/429 with `inflight_limit` (`max_inflight_requests`, queue fast/slow), `daily_limit` [V]; numbers not given.
- Seedream, Stability: not verified.

## 5. Notable design implications
1. Define a **canonical request schema** + per-model **capability manifest** (JSON schema per model with enums/ranges/defaults/"depends on"), generated UI from it. Constraints exist (e.g. quality `very_low` only with source images; OpenAI size rules; Gemini uppercase K; FLUX.3 no width/height) → manifest needs cross-field validation rules, not just enums.
2. Variants: implement fan-out with per-provider concurrency caps (OpenAI IPM, Recraft 5 rps, Ideogram inflight). Use native `n` where it exists (OpenAI ≤10, Ideogram, Recraft ≤6, Seedream sequential) – note cost semantics differ (sequential billed per image).
3. Seed-variants: only some models honour seeds; "N variants" via seeds is not portable.
4. Cost estimator needs per-model pricing functions (tokens for OpenAI/Gemini, MP for FLUX.2, tier for others); Ideogram `dry_run` and BFL response `cost` give authoritative quotes.
5. Results storage: most hosts return expiring URLs (Recraft ~24h, Ideogram ephemeral, BFL short) → download and persist immediately.
6. BYO-keys on a web UI: browser-direct calls hit CORS on most of these APIs; needs local backend/proxy (decision for architecture).
7. Aggregator hosts (fal.ai, Replicate, Ideogram hub, OpenRouter, Azure Foundry) rename/limit parameters; treat as separate "route" per model.

## 6. Not verified (explicit)
- Seedream: official BytePlus parameter tables (size tiers, ref count Pro=10 vs 14, seed, output_format, rate limits, exact intl model IDs).
- Stability: official OpenAPI/current endpoints, rate limits, edit tools list.
- OpenAI 2.5: per-image price table by size/quality, `n` max, edit image count (16) and `input_fidelity`/transparent support on 2.5 (extrapolated from gpt-image-2 and older spec).
- Gemini: `seed`/`candidateCount` behaviour for image models; exact ratios for NB2/NB2-Lite/Pro extreme-ratio support; NB2 Lite price; Vertex-specific price/quota; whether classic generateContent still supports every NB2.1 option; exact Imagen shutdown date on Vertex (sources: 2026-06-30 / 2026-08-17 / 2027-03-15 conflict).
- Ideogram 4.5 pricing and `n` max, negative_prompt on 4.5.
- Recraft price column headers; BFL rate limits; fal.ai / Replicate schemas (per-model, change often).
- Third-party blog numbers marked [P] could be stale.

## 7. QUESTIONS for the product owner

| # | Question | Why it matters | Options |
|---|---|---|---|
| 1 | Imagen is retired; Google image = Gemini "Nano Banana" only. Confirm we skip Imagen entirely, and is Vertex needed at all vs. Gemini API key? | Vertex needs GCP project/ADC/service-account auth vs a simple API key; same models both places. | (a) Gemini API key only; (b) Gemini API + Vertex as second route; (c) Vertex only (enterprise users) |
| 2 | Which providers/models are in v1 scope? | Each adds an adapter + manifest; ~10 families exist. | (a) Gemini + OpenAI + Seedream (+ video parity); (b) + FLUX + Ideogram + Recraft; (c) + generic fal/Replicate adapter |
| 3 | Direct provider APIs, aggregators (fal/Replicate/OpenRouter), or both? | Aggregators rename/limit params, differ in price; direct gives full control but 8 integrations. | (a) Direct only; (b) Direct for majors + fal for long tail; (c) Aggregator-first |
| 4 | How "ALL real parameters" is defined: only documented stable params, or also experimental/preview (OpenAI >2560x1440, Gemini thinking_level)? | Drives manifest maintenance cost and breakage as models change monthly. | (a) Stable only; (b) Stable + flagged "experimental"; (c) Free-form JSON override per model (escape hatch) |
| 5 | What does "N variants in one go" mean: same prompt N times, prompt/param sweeps (grid over seed/quality/model), or cross-model comparison? | Seeds are unsupported on OpenAI/Gemini; native n differs 1–10; cost multiplies. | (a) Same prompt xN; (b) Parameter grid/matrix; (c) Same prompt across multiple models (compare view) |
| 6 | Max N and spend guardrails? Show pre-run cost estimate and require confirmation above a threshold? | 4K FLUX.3 is $0.61/img, gpt-image high ≈$0.21; N=16 can cost several dollars per click. | (a) Hard cap N + budget per batch; (b) Estimate + confirm; (c) No limits (user's keys) |
| 7 | Reproducibility: store full request JSON + provider response + seed per image? Must "re-run with same params" work? | Seeds are partial; models update silently (snapshots only on OpenAI). | (a) Log params only; (b) Params + pinned model snapshot; (c) Full artifacts + re-run button |
| 8 | Where do keys live and where do calls run: browser-only, local backend, or hosted? | CORS blocks most providers from the browser; hosted storing keys is a security/trust issue. | (a) Local app (Node/Python) keys in OS keychain/.env; (b) Web UI + local proxy; (c) Hosted with encrypted keys |
| 9 | Editing scope: only text-to-image, or also edit/inpaint/outpaint/upscale/background removal/reference-image workflows? | Roughly doubles the matrix; masks differ (alpha vs black/white vs prompt-only; first image only). | (a) Text-to-image + reference images; (b) + mask edit; (c) Full toolbox (upscale, BG removal, vectorize) |
| 10 | Safety/moderation: expose provider knobs (OpenAI `low`, BFL tolerance 0–5, Gemini safetySettings) with warnings, or lock defaults? Any user age/content policy? | Some settings relax filtering; provider ToS apply to the key owner; OpenAI may need Org Verification. | (a) Expose all with warning; (b) Defaults only; (c) Expose but gated behind an "advanced" toggle |
| 11 | Watermark/provenance: SynthID is forced on Gemini; Seedream has a visible watermark flag. Do users need clean output or provenance preserved? | Affects defaults and legal claims. | (a) Surface provider default, never strip; (b) Offer watermark toggle where API allows; (c) Embed our own metadata |
| 12 | Output handling: formats, storage, gallery, naming, metadata embedding, retention? Many URLs expire in ~24h. | Must persist immediately; PNG/WebP/JPEG differences; transparent PNG. | (a) Local disk + sqlite index; (b) Cloud storage; (c) Both |
| 13 | Prompt tooling: expose provider prompt-rewriters (OpenAI none, Ideogram magic_prompt, Recraft enhance, FLUX upsampling, Seedream optimize) or add our own LLM prompt-enhancer, and show the rewritten prompt? | Rewriting changes results and cost; some providers return the final prompt (Ideogram), others hide it. | (a) Pass-through toggles only; (b) Own enhancer (BYO LLM key); (c) Both |
| 14 | Update strategy: models change monthly. Remote-updatable manifest/registry, or release-bound? Auto-discover models via list-models APIs? | Directly determines how "latest models" requirement survives. | (a) Manifest in repo, manual updates; (b) Remote JSON registry; (c) Auto-discovery + user-defined custom models |
| 15 | Presets & UX for ~15–30 params per model: progressive disclosure, saved presets, cross-model "universal" controls (aspect, count) mapped to native ones? | Universal-to-native mapping is lossy (ratio vs WxH vs tier). | (a) Native controls only per model; (b) Universal basics + per-model advanced panel; (c) Presets/templates shared across models |
| 16 | Concurrency/rate-limit behaviour: auto-queue and retry with backoff, or fail fast? | IPM/rps limits (OpenAI 20–250 IPM, Recraft 5 rps) make big batches 429 quickly. | (a) Per-provider throttled queue; (b) User-set concurrency; (c) Use Batch APIs (50% cheaper, async up to 24h) as an option |

## 8. SOURCES
- Gemini API image generation (Nano Banana): https://ai.google.dev/gemini-api/docs/image-generation
- Gemini API pricing: https://ai.google.dev/gemini-api/docs/pricing ; rate limits: https://ai.google.dev/gemini-api/docs/rate-limits
- Vertex "Generate images with Gemini": https://docs.cloud.google.com/vertex-ai/generative-ai/docs/multimodal/image-generation
- Vertex model versions/retirement: https://docs.cloud.google.com/vertex-ai/generative-ai/docs/learn/model-versions
- Vertex release notes (Imagen deprecation): https://docs.cloud.google.com/vertex-ai/generative-ai/docs/release-notes
- Firebase Gemini image / Imagen migration: https://firebase.google.com/docs/ai-logic/generate-images-gemini
- Imagen shutdown summaries (third-party): https://dev.to/akaranjkar08/imagen-3-4-shut-down-june-24-migrate-to-gemini-image-2026-1h87 , https://byteiota.com/imagen-4-shutdown-august-17-migrate-to-gemini-image-api-now/
- OpenAI image guide: https://developers.openai.com/api/docs/guides/image-generation
- OpenAI model pages: https://developers.openai.com/api/docs/models/gpt-image-2.5-sunburst.md , https://developers.openai.com/api/docs/models/gpt-image-2.5-flare.md
- OpenAI OpenAPI (older, stale for 2.x): https://github.com/openai/openai-openapi
- GPT Image 2.5 coverage: https://datanorth.ai/news/openai-launches-chatgpt-images-2-5 , https://www.atlascloud.ai/blog/tips/gpt-image-2.5-rate-limits , https://en.wikipedia.org/wiki/GPT_Image
- BFL OpenAPI: https://api.bfl.ai/openapi.json ; pricing: https://docs.bfl.ai/quick_start/pricing ; FLUX.2 pro ref: https://docs.bfl.ai/api-reference/models/generate-or-edit-an-image-with-flux2-%5Bpro%5D
- Ideogram docs index: https://developer.ideogram.ai/v2/llms.txt ; 4.5: https://developer.ideogram.ai/api-reference/images/generate/ideogram-4-5.md ; 4.0: https://developer.ideogram.ai/api-reference/images/generate/ideogram-4.md ; 3.0: https://developer.ideogram.ai/api-reference/api-reference/generate-v3
- Ideogram pricing (third-party): https://developer.puter.com/tutorials/ideogram-api-pricing/ , https://kie.ai/blog/ideogram-v4-pricing
- Recraft endpoints: https://www.recraft.ai/docs/api-reference/endpoints ; limits/sizes: https://www.recraft.ai/docs/api-reference/appendix ; pricing: https://www.recraft.ai/docs/api-reference/pricing
- BytePlus ModelArk image API (not parsed): https://docs.byteplus.com/en/docs/ModelArk/1541523 ; Seedream 5.0 Pro tutorial: https://docs.byteplus.com/en/docs/ModelArk/2582774
- Seedream third-party: https://openrouter.ai/bytedance-seed/seedream-5-0-pro , https://docs.apiyi.com/en/api-capabilities/seedream-image/overview , https://evolink.ai/seedream-5-0-pro , https://www.heyuan110.com/posts/ai/2026-07-09-seedream-5-pro/
- Stability (third-party/secondary): https://platform.stability.ai/docs/getting-started/stable-image , https://fast.io/resources/stability-ai-review-2026/ , https://docs.litellm.ai/docs/providers/stability

Status: DONE_WITH_CONCERNS
