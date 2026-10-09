# AI Gen Studio

Tool web chạy local để gen ảnh/video qua Vertex AI (Nano Banana, Gemini Omni 1.1 Flash, Veo 3.1) với bảng điều khiển theo model, biến thể N/danh sách prompt/quét tham số và ước giá trước khi chạy. Nguồn sự thật: `docs/architecture.md` (ý định gốc: `docs/requirements.md`).

## Chạy nhanh (không cần key)
```bash
cd backend && uv sync          # lần đầu (Python 3.12 được ghim, uv tự tải)
AIGEN_DEMO=1 make dev          # từ thư mục gốc; backend ở http://127.0.0.1:8000 (+ frontend dev nếu có frontend/package.json)
```
Chế độ demo (`AIGEN_DEMO=1`) dùng DemoAdapter: ảnh PNG và MP4 thật nhưng giả lập, không gọi mạng. Từ khoá trong prompt: `[blocked]` → job `blocked`; `[quota]` → quota ở lần đầu rồi thành công (thử retry); `[fail]` → `invalid`. `AIGEN_DEMO_DELAY_MS` chỉnh độ trễ (mặc định 300).

Chạy thật: bỏ `AIGEN_DEMO`, nhập service account qua `PUT /api/providers/vertex` (hoặc form Settings). **Adapter Vertex chưa từng được thử với API thật.**

LAN: `cd backend && uv run python -m app --lan` (bind 0.0.0.0, in token ngẫu nhiên ra console; gửi `Authorization: Bearer <token>` hoặc `?token=`).

## Xem ảnh/video toàn màn hình
- Bấm nút **⛶** ở góc trên phải của từng ảnh/video trong lưới hoặc màn so sánh để mở trình xem phủ màn hình; ảnh/video giữ nguyên tỷ lệ, không crop hay re-encode.
- Trong trình xem, bấm **Toàn màn hình trình duyệt** nếu muốn ẩn giao diện trình duyệt. Nếu API không được hỗ trợ hoặc bị từ chối, vẫn xem lớn trong trang.
- Video có controls, không tự phát. Bấm **Đóng** hoặc **Esc** để thoát; không tạo job mới hay đánh dấu đã tải.
- Automated tests/typecheck/build đã pass; native fullscreen, keyboard controls video và bố cục thực tế vẫn cần browser smoke.

## Chỉnh sửa ảnh và tải file
- Chọn mode **Chỉnh sửa ảnh** (`edit`): khối **Ảnh gốc để chỉnh sửa** hiện ngay dưới prompt, không cần mở tham số nâng cao.
- Bấm chọn file, kéo thả vào vùng tải ảnh, hoặc đưa focus vào nút chọn file trong vùng đó rồi nhấn **Ctrl/Cmd+V** để dán ảnh. Dán ảnh không được bắt trên toàn trang. Mỗi ảnh tối đa 20 MB; số ảnh tối đa phụ thuộc model.
- Ảnh vừa chọn chỉ ở trạng thái chờ, có preview để kiểm tra/gỡ. Xác nhận checkbox quyền sử dụng rồi bấm tải lên; chưa xác nhận thì ảnh không được gửi. Thay tập file chờ phải xác nhận lại. Nếu ảnh có người, bật lựa chọn tương ứng để xem cảnh báo.
- Với model edit hỗ trợ tỷ lệ hoặc kích thước, **Auto** mặc định lấy kích thước của ảnh **đã tải lên thành công đầu tiên**, không lấy ảnh đang chờ xác nhận. Thay/gỡ ảnh đầu tiên sẽ cập nhật nguồn. Ví dụ, ảnh 1600 × 900 dùng 16:9 nếu model cho phép; nếu không có tỷ lệ khớp, Auto chọn tỷ lệ hợp lệ gần nhất và hiện cảnh báo. Model dùng kích thước `WxH` nhận kích thước hợp lệ theo luật của model.
- Nếu chưa có ảnh hoặc trình duyệt không đọc được kích thước (có thể gặp với HEIC/HEIF), Auto chặn Generate: chọn tỷ lệ/kích thước **thủ công** để tiếp tục. Uploader không crop hay re-encode ảnh; preview không thay đổi byte file gốc.
- Trong Settings → Vertex, mục **Nhập file JSON** dùng cùng uploader để chọn/kéo thả một file service account JSON tối đa 1 MB, nhưng **không nhận paste ảnh**. File được parse và kiểm tra trước khi lưu; vùng tải file không preview nội dung key. Không đưa key vào prompt/ảnh đầu vào hoặc chia sẻ key trong ảnh chụp/log. Mục **Dán JSON** riêng dành cho văn bản JSON, không phải dán ảnh.

### Kiểm tra thủ công tiếp theo
Mở `http://localhost:5173` khi frontend dev đang chạy, ưu tiên chế độ demo không gọi API trả phí:
- Chọn model edit cho phép 16:9, tải ảnh 1600 × 900 và xác nhận quyền: Auto phải hiện 16:9, uploader không crop ảnh gốc. Thử ảnh dọc và thay/gỡ ảnh đầu tiên để kiểm tra nguồn Auto; tỷ lệ không được model hỗ trợ phải có cảnh báo gần đúng.
- Thử chọn file, drag/drop và paste khi focus uploader; trước consent không được gửi ảnh. Kiểm tra lại consent khi thay file, gỡ preview và chọn thủ công với HEIC không đọc được kích thước.
- Thử chọn/kéo thả JSON service account hợp lệ và file không hợp lệ; uploader JSON không nhận paste ảnh và không hiện nội dung key. Không dùng/chia sẻ key thật trong ảnh chụp hoặc log kiểm thử.

**Giới hạn xác minh (2026-10-08):** theo QA độc lập, 190 test frontend pass, typecheck/build pass; đây không thay thế browser smoke. Browser smoke chưa chạy vì approval service trả 404. Phiên này không gọi API live/trả phí; tỷ lệ ảnh đầu ra của adapter/model thật chưa được xác minh bằng live generation.

## Chạy nhiều job/batch đồng thời
- Các job Vertex trong cùng phiên cấu hình provider dùng chung client/token/HTTP pool. Token còn hợp lệ được dùng lại; khi cần cấp token, các caller cùng chờ **một refresh chung (single-flight)**. Hủy một caller không hủy refresh của caller khác.
- App giới hạn đồng thời xuyên mọi batch ở cả **provider và model**: trần provider bằng `maxConcurrent` lớn nhất trong các manifest của provider; vẫn giữ giới hạn riêng của model, `concurrencyGroup` và `rpm`. Đây là **policy phía app dẫn xuất từ manifest**, không phải quota Google/provider đã xác minh và không làm tăng quota tài khoản.
- Job chưa lấy đủ slot vẫn `queued`, chưa đọc bytes ảnh đầu vào. Đổi cấu hình chỉ vô hiệu client của provider đó; job đang dùng client cũ giữ client đến khi hoàn tất/cleanup, job mới dùng cấu hình mới.
- Token transport có timeout hữu hạn. Lỗi transport khi cấp token được phân loại `network` trước khi gửi generation và chỉ retry với budget/backoff hữu hạn hiện có; lỗi auth vĩnh viễn hoặc `blocked` không tự retry. Không gửi lại generation đã được provider chấp nhận hoặc khi không chứng minh được request chưa gửi, tránh tính phí hai lần.
- Thông báo token transport chỉ dùng loại lỗi/lý do đã lọc; không đưa key, access token hay nội dung credential xuống trình duyệt hoặc vào log. Không chia sẻ credential/log chứa secret để chẩn đoán.

**Bằng chứng chẩn đoán offline (2026-10-08):** trước sửa, 8 caller đồng thời gây 8 refresh; sau sửa, 32 caller dùng chung 1 refresh. Đây là bằng chứng cho cơ chế đồng thời, **không chứng minh mọi `TransportError` live đều do race refresh**. Gate cuối: backend 561/561 tests, frontend 220/220 tests, ruff/typecheck/build PASS; re-review không còn lỗi được xác nhận trong phạm vi đã sửa. Chi tiết tại `plans/reports/final-gate-after-fixture-cleanup.md`. Không coi gate offline là xác minh API live hoặc backend đang chạy đã nạp bản sửa.

### Bàn giao và áp dụng backend mới
**Backend phải được khởi động lại để dùng mã Python đã sửa.** Trước đó, người dùng cần tải xuống các output chưa lưu và để job đang chạy hoàn tất. **Không tự restart backend, cancel job đang active hoặc cleanup kết quả để áp dụng bản sửa.** Chỉ khởi động lại khi người dùng đã sẵn sàng; output nằm trong `tmp/` có thể bị dọn khi tắt app. Không gửi lại job đã được provider nhận chỉ để thử bản sửa.

## Lệnh
| Lệnh | Việc |
|---|---|
| `make dev` | backend (uvicorn :8000) + frontend dev nếu có |
| `make test` | unit test backend (+ frontend nếu có) |
| `make verify` | bộ test độc lập `backend/tests/verify` (không gọi API trả phí nếu không có `LIVE=1`) |
| `make lint` | `ruff check` (+ lint frontend nếu có) |

## Cấu trúc
`backend/app` (api, core, adapters) · `manifests/*.yaml` (model, tham số, luật, bảng giá) · `data/` (`prices.json`, `settings.json`, `presets.json`, `prompts.json`; `providers.json` tự tạo, quyền 600, KHÔNG commit) · `tmp/` (output, dọn khi tắt app) · `frontend/` · `docs/`, `plans/`.

Biến môi trường: `AIGEN_DATA_DIR`, `AIGEN_TMP_DIR`, `AIGEN_MANIFESTS_DIR`, `AIGEN_DEMO`, `AIGEN_DEMO_DELAY_MS`, `AIGEN_LAN`, `AIGEN_TOKEN`, `AIGEN_RETRY_BASE_S`.

Thêm/sửa model = sửa file trong `manifests/` (kèm `lastVerified`); giá ở `pricing.table` của manifest, ghi đè được bằng `data/prices.json`.
