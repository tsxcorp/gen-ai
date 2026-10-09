# Requirements — AI Gen Studio (V1: Vertex-first)

## Bổ sung yêu cầu người dùng (2026-10-08): xem toàn màn hình
- Xem riêng từng ảnh/video kết quả trong lưới hoặc so sánh bằng nút toàn màn hình; giữ tỷ lệ và nguyên bytes, video có điều khiển phát, đóng bằng nút hoặc Esc, trả focus về nút mở. Trình duyệt không hỗ trợ fullscreen vẫn có viewer phủ viewport. Không ảnh hưởng chọn/tải/reuse/job.

> Trạng thái: DRAFT chờ user duyệt. Nguồn: phỏng vấn BA 5 vòng + 4 báo cáo nghiên cứu trong `plans/reports/` (tra 2026-10-07).
> Quy ước độ tin: **[V]** đã đọc tài liệu chính thức · **[P]** nguồn phụ/search · **[?]** chưa xác minh. Mọi thông số model phải được xác minh lại bằng 1 lần gọi API thật ở bước kickoff (chưa ai gọi API thật).

## Objective
Một tool web chạy local (FastAPI + React) để gen ảnh và video qua Vertex AI (Google) bằng service account của user, với **bảng điều khiển đầy đủ thông số theo từng model** và **gen nhiều biến thể** (N bản, danh sách prompt, quét 1–2 tham số), ước tính chi phí trước khi chạy. Kết quả gen nằm tạm, tải xuống rồi bỏ; cấu hình (key, preset, prompt library) thì bền.

## Problem
Mỗi model có hàng chục tham số, tên và đơn vị khác nhau, nhiều ràng buộc chéo (ví dụ Veo ép duration=8s khi chọn 1080p). Playground chính chủ mỗi nơi một kiểu, không sweep được, không biết tốn bao nhiêu tiền trước khi bấm. Gen N biến thể = N job trả tiền riêng nên lỡ tay là mất tiền thật. Muốn một chỗ điều khiển hết, thử nhiều biến thể có kiểm soát, và mở rộng sang provider khác sau mà không viết lại.

## Quyết định đã chốt (phỏng vấn)
| # | Quyết định | Lý do |
|---|---|---|
| D1 | Local-first, 1 người, nội bộ. Bind `127.0.0.1`; mở LAN thì bắt buộc token truy cập sinh ngẫu nhiên mỗi lần chạy | Đơn giản, key không rời máy |
| D2 | Không DB. Kết quả gen: file ở thư mục temp của backend, state ở trình duyệt, reload trang mất lưới kết quả; job đang chạy vẫn xong ở backend | User muốn "tải xuống, không tải thì mất" |
| D3 | Cấu hình bền bằng file local (không DB): `providers.json` (key/setting, quyền 600, ngoài git), `presets.json`, `prompts.json`, `prices.json` | Preset/prompt library vô dụng nếu mất mỗi lần reload |
| D4 | UI = form + lưới kết quả. Canvas node (Magnific/Freepik Spaces) để V2 | Giao nhanh, tái dùng được nền job/manifest |
| D5 | Stack: Python FastAPI + React (Vite, TypeScript) | User chọn |
| D6 | V1 chỉ Vertex: ảnh Nano Banana; video Gemini Omni 1.1 Flash + Veo 3.1. Auth = service account JSON. OpenAI gpt-image-2.5 và Seedance 2.5 ở V1.5 sau interface chung | "Ưu tiên Vertex trước"; Seedance không chạy trên Vertex [P], cần key BytePlus riêng chưa có |
| D7 | Panel: nhóm gập + Advanced + tab xem/sửa request thô (JSON) | Đầy đủ mà vẫn dễ dùng |
| D8 | Biến thể: N bản + danh sách prompt + quét 1–2 tham số, hiển thị tổng job và giá dự kiến trước khi chạy | Yêu cầu cốt lõi của user |
| D9 | Chi phí: ước tính trước + hỏi xác nhận khi vượt ngưỡng (mặc định 5 USD, chỉnh được). `prices.json` có `lastVerified` | Tránh nhân tiền ngoài ý muốn |
| D10 | Video V1: text-to-video, image-to-video (frame đầu), frame đầu + cuối. Chưa có multi-reference, extend, video-edit | User chọn |
| D11 | Hậu xử lý V1: "Làm lại + chỉnh 1 field" (Reuse/Vary), "Ảnh sang video" (đưa ảnh vào first/last frame). Upscale kiểu Magnific để V2 | User chọn |
| D12 | Tính năng UX V1: preset tham số, prompt enhancer (Gemini trên Vertex, cùng service account), so sánh cạnh nhau + chọn nhiều + tải ZIP, thư viện prompt | User chọn |
| D13 | An toàn: cảnh báo + checkbox xác nhận khi upload ảnh có người; lỗi bị chặn chuẩn hóa thành trạng thái `blocked`, không tự retry | User chọn |
| D14 | Sora bị loại (OpenAI tắt 2026-09-24 [V]); Imagen bị loại (đã retire [V]) | Báo cáo nghiên cứu |

## Definition of Done (V1)
- [ ] Chạy `make dev` (hoặc lệnh tương đương) lên app ở localhost; UI nhập được `providers.json` qua form, key không bao giờ xuất hiện trong response API hay log.
- [ ] Chọn model → panel chỉ hiện field model đó hỗ trợ, ẩn/khóa field không hợp lệ theo luật ràng buộc, chuyển model giữ lại prompt.
- [ ] Gen 1 ảnh Nano Banana và 1 video (Omni và Veo 3.1) thật bằng service account của user, tải được file về.
- [ ] N bản, danh sách prompt, quét 1–2 trục tham số chạy được; cancel batch; retry chỉ job lỗi.
- [ ] Trước khi chạy hiện số job + khoảng giá; vượt ngưỡng thì chặn đến khi user xác nhận.
- [ ] Preset và prompt library lưu/nạp qua file JSON, còn nguyên sau khi restart app.
- [ ] Tab request thô khớp 100% payload thật gửi lên Vertex (contract test).
- [ ] Mọi output trong phiên có JSON tham số đi kèm khi tải ZIP; không output nào mất trước khi user reload hoặc tắt app.

## REASONS Canvas
- **Requirements**: panel tham số theo model, biến thể có kiểm soát, ước giá, tải xuống.
- **Entities**: Provider, ModelManifest, Param, Constraint, GenerationRequest, Batch, Job, Asset, Preset, PromptTemplate, PriceEntry.
- **Approach**: manifest dữ liệu (JSON/YAML) mô tả mọi model; backend validate theo manifest và dịch sang payload provider; frontend dựng form từ manifest do backend phục vụ (không nhân đôi schema ở 2 ngôn ngữ).
- **Structure**: `backend/` (FastAPI, adapters, job runner, cost), `frontend/` (React), `manifests/`, `data/` (file cấu hình), `docs/`.
- **Operations**: job runner trong process (asyncio), limiter theo provider, poll có jitter, tải file về temp ngay, dọn temp khi tắt app.
- **Norms**: không hardcode danh sách model/giá trong code; mọi thay đổi model là sửa manifest.
- **Safeguards**: key chỉ ở backend; ước giá + xác nhận; blocked không retry; không gỡ watermark SynthID.

## Bảng điều khiển V1 (đặc tả tham số)
Thông số lấy từ báo cáo nghiên cứu, mỗi manifest ghi `lastVerified`. Mọi chỗ **[?]** phải test thật ở kickoff trước khi viết constraint cứng.

### Nhóm panel dùng chung
Basic luôn hiện: Prompt, Aspect ratio, Độ phân giải/size, Số bản (N), Model. Nhóm gập: Kích thước, Tham chiếu (ảnh), Âm thanh (video), An toàn, Xuất file, Chi phí. Advanced: các field còn lại. Footer cố định: tổng job, khoảng giá, nút Generate. Tab "Request thô": JSON thật, sửa tay được, có validate.

### Ảnh — Gemini Nano Banana (Vertex, qua generateContent) 
| Param | Giá trị / ràng buộc | Tin cậy |
|---|---|---|
| model | `gemini-nano-banana-2.1` (mặc định), `gemini-3.1-flash-image`, `gemini-3.1-flash-lite-image`, `gemini-3-pro-image` | [V] |
| aspect_ratio | 1:1, 2:3, 3:2, 3:4, 4:3, 4:5, 5:4, 9:16, 16:9, 21:9; riêng NB 2.1 thêm 1:4, 4:1, 1:8, 8:1 | [V] |
| image_size | 512 (chỉ 3.1-flash), 1K, 2K, 4K; Lite chỉ 1K. Phải viết hoa chữ K, thường là bị từ chối | [V] |
| reference images | tối đa 14 (NB2.1: ≤10 object + ≤4 character; Pro: ≤6 object + ≤5 character; Lite: ≤14 object) | [V] |
| thinking_level | có ở NB2.1 / 3.1 / Pro | [V] |
| google search grounding | có (không có ở Lite) | [V] |
| mime_type | jpeg / png | [P] |
| safetySettings | category × threshold | [V] |
| seed | API có field nhưng không rõ có tái lập được ảnh | [?] |
| N per request | **Không điều khiển được** → N bản = N request | [V] |
| không có | negative prompt, CFG, steps. SynthID luôn bật | [V] |
Hai kiểu API cùng tồn tại (`generationConfig.imageConfig` camelCase và Interactions `response_format` snake_case); adapter chọn kiểu theo host Vertex.

### Video — Gemini Omni 1.1 Flash (Vertex Preview: `gemini-omni-1.1-flash-preview`)
| Param | Giá trị / ràng buộc | Tin cậy |
|---|---|---|
| mode (`task`) | text_to_video, image_to_video, first+last frame. (reference/edit/extend ngoài V1) | [V] |
| resolution | `gemini-omni-1.1-flash(-preview)`: 360p, 720p (mặc định), 1080p, 4k (upscaled). Model **khác** `gemini-omni-flash-preview` (không có "1.1") chỉ hỗ trợ 720p. | [V] |
| aspect_ratio | 16:9 (mặc định), 9:16 | [V] |
| duration | "3s"–"10s" theo Vertex; docs Gemini API không nêu | [?] |
| audio | luôn bật, điều khiển bằng prompt | [V] |
| không có | seed, negative prompt, camera control (chỉ bằng prompt). Mặc định có thể cắt nhiều cảnh nếu không ghi "single continuous shot" | [V] |
| delivery | inline base64 (≈4 MB trần) hoặc URI/GCS; Vertex dùng `delivery:"uri"` + `gcs_uri` | [?] có cần bucket |
| sync/async | `background:false` là sync; `background:true` là async | [V] |
| giá | token: ≈$0.034/s (360p), 0.10 (720p), 0.152 (1080p), 0.304 (4K) | [V] |

### Video — Veo 3.1 / 3.1 Fast / 3.1 Lite (Vertex, `predictLongRunning`)
| Param | Giá trị / ràng buộc | Tin cậy |
|---|---|---|
| model | Veo 3.1, 3.1 Fast (GA); 3.1 Lite (Preview). **Veo 3.1 GA dự kiến retire từ 2026-11-17** | [V] |
| mode | T2V, I2V (`image`), first+last (`lastFrame`, bắt buộc có `image`) | [V] |
| durationSeconds | 4, 6, 8 (mặc định 8). **Bắt buộc 8** khi 1080p, 4K | [V] |
| resolution | 720p (mặc định), 1080p, 4k; Lite không có 4K | [V] |
| aspectRatio | 16:9, 9:16 | [V] |
| sampleCount | 1–4 trên Vertex (số lượng native, tính tiền từng video) | [V] |
| seed | uint32, không đảm bảo tái lập | [V] |
| negativePrompt | có | [V] |
| generateAudio | bool trên Vertex | [?] |
| personGeneration | `allow_adult` (mặc định) / `disallow`; vùng EU/UK/CH/MENA chỉ `allow_adult` | [V] |
| storageUri | gs:// tùy chọn; bỏ qua thì trả bytes | [V] |
| resizeMode / compressionQuality | crop/pad cho I2V; optimized/lossless | [P] |
| quota | ≈50 request/phút/model (đơn vị ghi sai trong docs) | [?] |
| giá | 3.1: $0.40/s có audio, $0.20/s không; Fast: $0.10–0.12/s (720p/1080p) có audio; Lite: $0.05–0.08/s | [V] |

### Ràng buộc chéo (dạng luật trong manifest, không hardcode trong UI)
- Veo: `1080p|4k ⇒ duration=8`; `lastFrame ⇒ image`; Lite ⇒ không 4K.
- Nano Banana: `image_size` hợp lệ theo model; số reference theo model và vai (object/character).
- Omni: model `gemini-omni-flash-preview` (không phải 1.1) ⇒ chỉ 720p; `gemini-omni-1.1-flash` hỗ trợ 360p–4K.
- Quy tắc: field không hỗ trợ **ẩn**, field bị ép **khóa kèm lý do**, tổ hợp sai **chặn trước khi gửi**.

### V1.5 (chưa build, manifest sẵn sau interface chung) — chi tiết ở báo cáo
- **gpt-image-2.5** (`sunburst` chính xác / `flare` nhanh): quality low→max, size WxH tuỳ ý (mỗi cạnh là bội số 16, cạnh dài ≤3840, tỉ lệ ≤3:1, **tổng pixel trong 655.360–8.294.400** [V]; ví dụ 3840x3840 và 16x16 là KHÔNG hợp lệ), n tới 10 [P], png/jpeg/webp + compression, background transparent, moderation auto/low. Không có seed/negative/CFG. Cần Org Verification [?].
- **Seedance 2.5** (`dreamina-seedance-2-5-260628`, BytePlus ModelArk): T2V, first, first+last, omni-reference; 480/720/1080p, ratio 16:9…21:9/adaptive, duration 4–30 hoặc -1, `generate_audio`, `watermark`, `output_format` mp4/mov, `return_last_frame`, `draft` 480p. **Không có seed, camera_fixed, negative.** Tài khoản cần kích hoạt (số dư >30 USD hoặc gói), cá nhân 3 job đồng thời. URL 24 giờ.

## User stories và Acceptance
1. **Chọn model, panel tự đổi.** As a user, I want panel chỉ hiện tham số model hỗ trợ, so that không gửi tham số bị bỏ qua.
   - Given Veo 3.1 đang chọn, When đặt resolution=1080p, Then duration khóa ở 8 kèm tooltip lý do.
   - Given Nano Banana 3.1-flash-lite, When mở size, Then chỉ có 1K.
   - Given Omni, Then không có ô negative prompt và seed.
2. **Gen N biến thể.** As a user, I want gen N bản một lần, so that chọn bản đẹp nhất.
   - Given Nano Banana N=6, When bấm Generate, Then có 6 job độc lập, hiện đúng 6 ô trong lưới, ô lỗi có nút retry riêng.
   - Given Veo `sampleCount` hỗ trợ native, Then dùng native khi tham số còn lại giống nhau; lỗi gộp vào 1 job.
   - Given N vượt trần batch (mặc định 24), Then chặn và báo lý do.
3. **Quét tham số và danh sách prompt.** 
   - Given 3 prompt × quality/aspect quét 2 trục (3×2), When xem preview, Then hiện "18 job · ~$X–$Y" trước khi chạy.
   - Given tổng giá > ngưỡng, Then nút chạy yêu cầu xác nhận lần 2.
4. **Ước tính chi phí.** Given model có giá token (Omni, Veo theo giây), When đổi duration/resolution/audio, Then khoảng giá cập nhật tức thì; Given `prices.json` quá 30 ngày `lastVerified`, Then hiện cảnh báo "giá có thể cũ".
5. **Job runner.** 
   - Given 429/quota, Then retry có backoff và jitter, tối đa K lần; Given `blocked` hoặc invalid params, Then không retry, hiện nguyên nhân.
   - Given user bấm Cancel batch, Then job chưa gửi bị hủy, job đã gửi đánh dấu "best-effort" (Veo/Omni có thể không hủy được [?]).
   - Given job thành công, Then file được tải về temp ngay (không giữ URL provider).
6. **Kết quả và tải.** Given lưới kết quả, When chọn nhiều và bấm Tải ZIP, Then ZIP gồm file gốc nguyên vẹn + 1 JSON tham số/job (không re-encode, không gỡ SynthID). So sánh cạnh nhau 2–4 ô, có tham số bên dưới.
7. **Reuse/Vary.** Given 1 kết quả, When bấm Reuse, Then toàn bộ tham số nạp lại vào panel; sửa 1 field rồi Generate là job mới.
8. **Ảnh sang video.** Given 1 ảnh trong lưới, When bấm "Làm video", Then chuyển sang panel video với ảnh ở slot first_frame (hoặc last_frame), mode tự đặt đúng.
9. **Preset và prompt library.** Given tôi lưu preset "Reel 9:16 720p", When restart app, Then preset còn và nạp lại đúng tham số. Prompt library chèn được vào ô prompt.
10. **Prompt enhancer.** Given prompt thô, When bấm Enhance, Then Gemini (Vertex) trả prompt viết lại hiện ở ô xem trước để chấp nhận/sửa/bỏ; không tự ghi đè. System prompt khác nhau cho ảnh, Veo, Omni.
11. **An toàn.** Given upload ảnh tham chiếu, Then hiện cảnh báo + checkbox "tôi có quyền dùng ảnh này", không tick thì không dùng được ảnh đó; Given provider chặn, Then job = `blocked` + lý do chuẩn hóa, không retry.
    - Uploader dùng chung cho ảnh và file key JSON: chọn file hoặc kéo thả; vùng ảnh nhận Ctrl/Cmd+V khi focus, không bắt clipboard toàn trang. Có preview, tên/dung lượng, trạng thái tải/lỗi và gỡ ảnh; không upload ảnh trước khi xác nhận quyền. Không chấp nhận quá số ảnh hoặc quá giới hạn 20 MB mỗi ảnh.
    - Mode edit luôn hiện ảnh đầu vào ngay dưới prompt, kể cả trường được đánh dấu advanced trong manifest. Không cần mở tham số nâng cao để chọn ảnh.
    - Auto ratio trong edit lấy kích thước hiển thị của ảnh tham chiếu đầu tiên. Với model có danh sách ratio, dùng ratio khớp hoặc gần nhất theo sai lệch tỷ lệ tương đối và cảnh báo nếu không khớp. Với model dùng size WxH, suy ra kích thước hợp lệ gần tỷ lệ gốc theo sizeRule trong manifest. Chỉ gửi giá trị cụ thể đã được validate; không gửi sentinel Auto. Nếu chưa có ảnh/không đọc được kích thước, yêu cầu chọn ratio/size thủ công thay vì âm thầm dùng mặc định. Không crop, re-encode hoặc làm mất watermark.
    - Nhiều job/batch dùng chung provider không được tạo bão refresh token: một refresh đang chạy được chia sẻ cho các waiter, token hợp lệ dùng lại; hủy một waiter không hủy refresh của waiter khác. Các adapter Vertex trong cùng phiên cấu hình dùng chung client/token/HTTP pool.
    - Giới hạn đồng thời áp dụng cả provider và model qua mọi batch. Trần provider lấy từ maxConcurrent lớn nhất của manifest provider; model giữ trần riêng thấp hơn và rpm/concurrencyGroup hiện có. Job chưa có slot giữ queued, chưa đọc bytes ảnh tham chiếu. Task đã kết thúc phải được dọn khỏi bộ nhớ runner.
    - Lỗi kết nối khi cấp token là network trước khi gửi generation, không giả thành sai key; retry hữu hạn theo luật before_send hiện có. Không tự retry auth/key bị từ chối, blocked hoặc submit sau khi provider đã nhận. Thông báo chỉ gồm loại lỗi/lý do đã lọc, không key/token/nội dung credential.
    - Đổi cấu hình provider chỉ vô hiệu client/adapter của provider đó; job đang dùng client cũ được hoàn tất/cleanup trước khi đóng, job mới dùng cấu hình mới. Shutdown phải đóng client/token transport đúng một lần, chờ refresh đang chạy, không rò session.
12. **Key và truy cập.** Given nhập service account, project ID, location, Then lưu vào `providers.json` quyền 600; GET API không trả key. Given chạy với `--lan`, When thiếu token, Then 401.

## Data contracts (bản phác, sẽ chốt ở spec)
```jsonc
// ModelManifest (YAML/JSON trong manifests/)
{
  "id": "veo-3.1", "provider": "vertex", "kind": "video", "status": "ga|preview|deprecated",
  "sunsetDate": "2026-11-17", "lastVerified": "2026-10-07",
  "modes": ["t2v","i2v","first_last"],
  "params": [{ "key":"duration", "type":"enum", "values":[4,6,8], "default":8,
               "group":"size", "level":"basic|advanced", "providerPath":"parameters.durationSeconds" }],
  "constraints": [{ "when":{"resolution":["1080p","4k"]}, "then":{"duration":8}, "reason":"Veo ép 8s" }],
  "pricing": { "unit":"per_second", "table":[ {"when":{"audio":true},"usd":0.40} ] },
  "limits": { "maxConcurrent": 4, "maxVariantsNative": 4 }
}
// Job
{ "id":"uuid","batchId":"uuid","model":"veo-3.1","requestedParams":{}, "effectiveParams":{},
  "status":"queued|running|succeeded|failed|blocked|canceled",
  "error":{"kind":"quota|blocked|invalid|network|timeout","message":""},
  "assets":[{"path":"temp/...","mime":"video/mp4","sha256":""}], "costEstimateUsd":[0,0] }
```
Provider adapter interface: `validate(params) → submit(job) → poll(job) → download(job)`; lỗi chuẩn hóa về 5 loại ở trên.

## Guardrails
- **Always**: validate tham số theo manifest ở backend (không tin client); ghi `requestedParams` và `effectiveParams`; tải file về ngay khi job xong; che key trong log; ước giá trước mỗi batch.
- **Ask first**: thêm provider mới ngoài danh sách; đổi định dạng file cấu hình (`providers.json`…); bất kỳ thứ gì ghi ra ngoài thư mục project; thêm DB.
- **Never**: commit key hay `providers.json`; gửi key xuống trình duyệt; tự retry job `blocked`; gỡ/che watermark SynthID hay re-encode file gốc; hardcode giá/danh sách model trong code; weaken test cho pass; gọi API tốn tiền trong test tự động mà không có cờ `LIVE=1`.
- Authority khi xung đột: guardrail này > spec > yêu cầu tính năng.

## Non-goals (V1)
DB, đăng nhập/nhiều user, SaaS; canvas node/flow (V2); upscale/relight kiểu Magnific (V2); OpenAI và Seedance (V1.5); Sora (đã chết), Imagen (đã retire); multi-reference video, extend, video-edit, lip-sync; inpaint/mask; gen lại seed để tái lập (không có model nào đảm bảo); lịch sử bền qua reload; quản lý ngân sách theo tháng.

## Rủi ro chính
| Rủi ro | Ảnh hưởng | Giảm thiểu |
|---|---|---|
| Model/giá đổi liên tục (Veo 3.1 GA retire ≥2026-11-17, Imagen retire, Sora tắt) | Manifest cũ gửi sai | Manifest dữ liệu có `status`/`sunsetDate`/`lastVerified`, smoke test live |
| Omni trên Vertex đang Preview, schema có thể đổi | Adapter gãy | Tách adapter, contract test, cờ `preview` |
| Biến thể không tái lập được (Omni/Nano Banana không seed) | Kỳ vọng sai | Ghi rõ trong UI "mỗi lần chạy là ngẫu nhiên", sweep tham số làm trục chính |
| Quota Vertex thấp (~50 req/phút Veo) | N lớn bị 429 | Limiter theo provider, hàng đợi, backoff |
| Chi phí nhân N | Mất tiền | Ước giá + ngưỡng xác nhận + trần batch |
| Reload mất kết quả | Mất tiền đã trả | Banner nhắc, nút tải ZIP nổi bật, cảnh báo khi đóng tab có job/kết quả chưa tải (`beforeunload`) |

## Open questions (chưa chốt, không được đoán)
1. **Omni trên Vertex có bắt buộc GCS bucket không?** Docs ghi `delivery:"uri"` + `gcs_uri`; inline base64 chỉ ≈4 MB. Ảnh hưởng: user có phải tạo bucket. → Test thật ở kickoff.
2. Seed của Gemini image có tái lập không? (docs không nói) → Test thật.
3. Reference images cho Nano Banana có vào V1 không? Tôi giả định **có** (slot ảnh tham chiếu trong panel), còn mask/inpaint thì không. User chưa xác nhận rõ.
4. Quota Vertex thực tế của project user (Veo, Omni, Gemini image) và region/location (Gemini image dùng `global`).
5. Giá Nano Banana 2.1 / Lite và Veo/Omni lấy từ tài liệu qua subagent, cần đối chiếu console billing; seed `prices.json` kèm `lastVerified`.
6. Prompt enhancer dùng model Gemini nào (rẻ nhất đủ dùng) và system prompt cho từng model.
7. Trần batch mặc định (đề xuất 24 job) và ngưỡng xác nhận (đề xuất 5 USD): user chốt con số.
8. Conflict nguồn về ngày Imagen tắt (2026-06-30 / 2026-08-17 / 2027-03-15); không ảnh hưởng V1 vì đã loại Imagen.
9. Veo 3.1 Lite: Vertex nói có extend, Gemini API nói không; ngoài V1 nên chưa cần.
10. V1.5: user có key Seedance (BytePlus kích hoạt) hay dùng host khác? Org Verification của OpenAI đã có chưa?

## Tham khảo
`plans/reports/research-image-params.md`, `research-video-params.md`, `research-prior-art-ux.md`, `research-ops-compliance.md`. Lưu ý: các báo cáo dựa chủ yếu vào WebSearch (WebFetch lỗi trong 2 subagent), nên mục [P]/[VERIFY] cần kiểm lại.

## Cập nhật phạm vi (2026-10-07, theo yêu cầu user): đa provider ngay trong V1
- **D6b** (thay D6): V1 gồm 3 provider, mỗi provider có cài đặt xác thực riêng và chọn provider = chọn model lúc gen.
  - **Vertex** (Google): auth = service account JSON (nhập file / đường dẫn / dán) **hoặc ADC** (`gcloud auth application-default login`, kể cả dùng `--client-id-file`). Models: Nano Banana (4), Gemini Omni 1.1 Flash, Veo 3.1 / Fast / Lite.
  - **OpenAI**: API key (+ `organization`/`project` tùy chọn). Models: `gpt-image-2.5-sunburst`, `gpt-image-2.5-flare` (ảnh; thông số ở báo cáo `research-image-params.md` §2b). Cần Org Verification [?].
  - **BytePlus (Seedance)**: API key + region (mặc định `ap-southeast`, host `ark.ap-southeast.bytepluses.com`). Models: Seedance 2.5 (`dreamina-seedance-2-5-260628`), 2.0, 2.0 Fast, 2.0 Mini (thông số ở `research-video-params.md` §2.2). Không có seed/negative; URL kết quả sống 24 giờ nên tải về ngay; tài khoản cá nhân 3 job đồng thời.
- **Stories bổ sung**
  - US13: Given chưa cấu hình OpenAI, When mở Studio, Then model OpenAI hiển thị mờ kèm nút "Cài đặt", và gửi batch cho nó trả lỗi `not_configured`.
  - US14: Given đã cấu hình cả 3 provider, When gen một ảnh Nano Banana rồi một ảnh gpt-image, Then cả hai kết quả nằm chung lưới, so sánh cạnh nhau được, mỗi ô ghi rõ provider và model.
  - US15: Given lưu key OpenAI, Then `GET /api/providers` chỉ trả `hasKey:true`, key không bao giờ xuất hiện ở response/log/ZIP/SSE (áp dụng mọi provider).
  - US16: Given Seedance chọn first+last frame hoặc 4K, Then luật ràng buộc theo manifest (ratio `adaptive` khi có frame, 4K chỉ ở 2.0, Fast/Mini không có 1080p/4K, không có seed/negative).
- Non-goals thu hẹp: vẫn không làm OAuth login flow trong app, Kling/Runway/FLUX/Ideogram, gateway fal/Replicate.
- **Rủi ro mới**: adapter OpenAI và BytePlus chưa gọi API thật (`verifiedLive:false`); BytePlus cần kích hoạt tài khoản (số dư >30 USD hoặc gói) [P]; OpenAI gpt-image cần Org Verification [?].
