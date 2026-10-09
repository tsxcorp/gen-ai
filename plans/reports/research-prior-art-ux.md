# Prior art & UX patterns: multi-provider image+video studio (2026-10)

Confidence: web-search summaries only; I did not hands-on test any product and WebFetch failed. Claims on Higgsfield, Weavy, Runway, Kling web, ImagineArt, LTX, Midjourney web UI are NOT verified. Treat them as unknown.

## 1. FINDINGS
- Freepik Spaces (launched 2025-11-04) is a node canvas: nodes = upload/text prompt/Image Generator/Video Generator/AI assistant/Image Upscaler (Magnific, Creative vs Precision modes)/Video Combiner. Wires carry data between nodes. Real-time multi-user. Saved flows are re-runnable with new inputs.
- Batch in Spaces is a "List" node: a list of N prompts fed to a generator gives N outputs in one run. Lists chain (images -> second List -> upscaler). The generator also has a "number of creations" count. Batch = fan-out over inputs, not a param grid.
- Magnific upscaler params are integer sliders -10..10: creativity, HDR, resemblance, fractality. Also scale 2/4/8/16x, "optimized for" presets, engine, prompt. Known failure: high creativity+HDR gives plastic skin. Relight and Style Transfer are separate tools (param details unverified). They look like image->image nodes with a reference input, so they fit a generic "post-process action" slot.
- Krea: same prompt across many video models for comparison, plus Krea Nodes (reusable workflows, App Builder). Krea positions itself as multi-model experimentation. Higgsfield: aggregator with cinematic camera presets (70+), character consistency, lip-sync. Image is secondary. Its unlimited/free generations are site-only, which signals that cost rules differ by surface.
- Google Flow (Whisk and ImageFX merged in Feb 2026): 1-4 variations per generation, an asset grid to review and pick, "Ingredients to Video" (up to 3 reference images), Scenebuilder timeline (clips up to 8s chained). Credits are shared across tools and 1 credit is spent per variation, so cost scales visibly with N.
- Leonardo: default 4 images per prompt, "Advanced settings" that vary by model (PhotoReal, negative prompt, tiling, fixed seed, init strength for img2img). This is the simple basic/advanced split most apps use.
- Schema-driven forms are the established pattern. fal: playground form auto-generated from the model's OpenAPI 3.0 schema (Pydantic Field metadata, field ordering, hidden fields, ui hints such as textarea). Replicate: Input schema from Cog (name/type/default/min/max/enum), validated server-side, plus a side-by-side Playground (Oct 2024). Typical mapping: enum->select, number+range->slider, array->tags/multi-input, T|null->optional, file->uploader.
- Sweeps: A1111 X/Y/Z plot (range syntax `20-60(+5)`, Z = multiple grids, fixed seed advised, cost explodes: 10x6=60). Invoke: dynamic prompts x iterations = batch, queue with per-batch cancel and front-of-queue, and it has complaints (cancelling resets scroll position). ComfyUI: no native sweep, batch image doesn't store its own seed so you can't regenerate one batch member; community uses "base seed -> list of N seeds" nodes. Lesson: store a per-output resolved seed and the full resolved param snapshot.
- Common failure modes: (a) showing params the model ignores/rejects; (b) batch outputs without reproducible per-item params; (c) no cost visibility before running a grid; (d) queue UI that jumps or can't cancel selectively; (e) history that is a flat feed with no project/folder or search; (f) relaxed/fast queue semantics hidden (Midjourney).

## 2. FEATURE IDEAS (value/effort)
MVP
1. Model registry with capability manifest (JSON Schema + UI hints + provider mapping) -> auto-generated param panel; unsupported params never rendered; conditional fields (e.g. image-ref only for i2v models).
2. Basic/Advanced split: prompt, aspect/duration, count visible; seed, steps/guidance, negative prompt, safety, etc. under Advanced. Persist last settings per model.
3. N variants per run (count) as a result grid; each tile stores seed + resolved params + provider request id.
4. Job queue with per-job status (queued/running/failed/done), cancel, retry, concurrency limit per provider, async polling for video.
5. Pre-run cost estimate (per model manifest: price formula) and running total; a hard confirm over a threshold.
6. History with persistent storage (all outputs + params), "reuse params" / "open in panel", favorite star, delete.
7. Reference-image slot(s) typed by role (first frame, style ref, subject), drag/drop from history.
v2
8. Sweep builder: seed sweep, prompt list (like Spaces List), prompt permutations `{a|b}`, one-axis param sweep; preview of total count + cost before run; result as grid with axis labels (A1111 X/Y style, 2 axes first).
9. Side-by-side compare (same prompt across N models, synced zoom/play for video), pick winner.
10. Result actions: upscale, vary (new seed / same params), remix (edit prompt prefilled), image->video (send to i2v with the frame), extract last frame -> continue.
11. Presets (named param sets per model) and prompt library with tags; prompt enhancer (LLM rewrite, show diff, opt-in).
12. Projects/folders, tags, search by prompt/model/param, bulk download/export with metadata sidecar JSON.
Later
13. Node canvas / saved reusable flows (Spaces/Krea Nodes style) with List nodes; run-flow-with-new-inputs. High effort; do after the actions in 10 are proven (a flow is a chain of those actions).
14. Magnific-like postprocess nodes (upscale w/ creativity/HDR/resemblance, relight, style transfer) as provider-specific tools if the provider exposes an API.
15. Timeline/storyboard (Flow Scenebuilder), video combiner, shared credit budget per project, team collaboration, LoRA/style training (out of scope probably).

## 3. QUESTIONS FOR PRODUCT OWNER
1. Q: Form-based studio or node canvas as the primary UI? Why: canvas multiplies scope (graph engine, execution, wiring UX). Options: (a) form+grid+actions only, canvas later; (b) form first, with a minimal "chain" pipeline (gen -> upscale -> video); (c) canvas from day 1.
2. Q: Single user local tool or multi-user/hosted? Why: drives auth, key storage, history DB, collaboration. Options: (a) local, single user; (b) self-hosted small team; (c) SaaS.
3. Q: How are provider API keys handled? Why: security and billing responsibility. Options: (a) user's own keys in local env/vault; (b) shared team keys with per-user quotas; (c) platform-resold credits.
4. Q: Source of truth for per-model params? Why: determines maintenance cost as models change monthly. Options: (a) hand-written manifest per model; (b) import from provider schemas (fal/Replicate-style OpenAPI) + manual overrides; (c) hybrid with a manifest linter/tests against the provider.
5. Q: How "detailed" is detailed? Why: every raw param vs curated. Options: (a) expose all provider params, grouped; (b) curated basic + "raw JSON override" escape hatch; (c) curated only.
6. Q: Max batch/variant size and sweep types needed (count, seed, prompt list, permutations, param grid)? Why: cost blow-up and queue/rate-limit design. Options: (a) count + seed only; (b) + prompt list/permutations; (c) full X/Y/Z grid with cost cap.
7. Q: Cost visibility: estimate only, or actual tracking and budgets? Why: pricing is per provider/model/duration/resolution, and some are token-based. Options: (a) estimate from manifest; (b) estimate + actual ledger from responses; (c) + per-project budget caps/hard stop.
8. Q: Is compare across models a core flow? Why: it requires normalising inputs (aspect, duration, refs) across providers. Options: (a) manual: run separately and compare in history; (b) "run on N models" multi-select with auto-mapped common params; (c) synced compare viewer too.
9. Q: Which post-actions are must-have (upscale, vary, remix, i2v, last-frame continue, relight/style transfer)? Why: determines which provider endpoints/integrations to build (Magnific API exists for upscaler). Options: (a) vary/remix/i2v only; (b) + upscale via Magnific/other; (c) + relight/style transfer.
10. Q: Storage and retention of outputs? Why: provider URLs expire; video is large. Options: (a) download all to local disk; (b) object storage (GCS/S3) with DB; (c) keep provider URLs, download on favorite.
11. Q: Organization model: flat history, projects/folders, tags, or boards? Why: affects DB schema from the start. Options: (a) flat + favorites + search; (b) projects + tags; (c) boards/canvases.
12. Q: Prompt tooling: enhancer, library, templates with variables? Why: enhancer needs an LLM provider and consent for rewriting. Options: (a) none in MVP; (b) library + presets; (c) library + LLM enhancer with diff view.
13. Q: Reference-image handling: how many, which roles, and where from (upload, history, URL)? Why: models differ (first/last frame, multi-ref, style ref). Options: (a) single image; (b) role-typed multi-slot driven by manifest; (c) + masks/inpaint editor.
14. Q: Async/failed job policy: auto-retry, partial refunds, what counts as cost on failures or safety blocks? Why: user trust. Options: (a) manual retry; (b) auto-retry transient only; (c) retries + per-job error taxonomy surfaced.
15. Q: Is Magnific parity (creativity/HDR/resemblance/fractality sliders) wanted, or just "upscale" as a button? Why: Magnific is its own provider/API and pricing. Options: (a) button with default; (b) expose sliders; (c) skip, use model-native upscalers.

## 4. SOURCES
- https://www.freepik.com/ai/docs/utility-nodes
- https://www.krea.ai/blog/freepik-spaces-vs-krea-nodes (fetch failed; used search snippet only)
- https://chasejarvis.com/blog/freepik-spaces/
- https://kingy.ai/news/freepik-spaces-freepik-lists-review-the-bulk-creative-production-tool-agencies-have-been-waiting-for/
- https://www.forbes.com/sites/ronschmelzer/2025/11/04/freepiks-spaces-makes-ai-a-team-sport-for-creators/
- https://docs.magnific.com/api-reference/image-upscaler-creative/post-image-upscaler
- https://docs.flora.ai/models/image-models/magnific-upscaler-and-enhancer
- https://www.magnific.com/blog/understanding-freepiks-upscaler-modes/
- https://imageat.com/compare/krea-vs-higgsfield ; https://magichour.ai/blog/higgsfield-alternatives
- https://blog.google/technology/ai/flow-video-tips/ ; https://www.solidaitech.com/2026/05/google-flow.html
- https://docs.fal.ai/reference/platform-apis/openapi-schema ; https://fal.ai/docs/documentation/model-apis/playground
- https://replicate.com/changelog ; https://replicate.com/docs/reference/http
- https://github.com/AUTOMATIC1111/stable-diffusion-webui/pull/7146
- https://support.invoke.ai/support/solutions/articles/151000158823-queue ; https://github.com/invoke-ai/InvokeAI/issues/6437
- https://github.com/Comfy-Org/ComfyUI/issues/8052
- https://aituts.com/midjourney-speed/ ; https://www.toolify.ai/ai-news/unlock-the-full-potential-advanced-settings-for-leonardo-ai-image-generation-72062
- https://martini.art/en/vs/openart ; https://openart.ai/blog/best-ai-generators/

## Gaps (not researched/verified)
Weavy, Runway, Kling web, ImagineArt, LTX Studio, Midjourney web editor UI, Relight/Style Transfer params, any cost-display UI specifics at competitors. Prompt-library/favorites UX at competitors only inferred.
