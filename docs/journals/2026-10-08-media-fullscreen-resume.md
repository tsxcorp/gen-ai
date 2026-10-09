# Viewer toàn màn hình: code xanh, nghiệm thu chưa xong

## Cập nhật sau phê duyệt cleanup — 2026-10-08
- Người dùng duyệt cleanup riêng fixture cũ gây scanner FAIL. Xóa đúng 25 file marker-matching dưới run test cũ; giữ nguyên thư mục/symlink/output khác và cấu hình thật, không thay scanner/test.
- Gate offline mới: scanner 1/1 PASS; backend 561/561 PASS; frontend 220/220 PASS; ruff/typecheck/build PASS. Báo cáo `plans/reports/final-gate-after-fixture-cleanup.md` thay thế blocker scanner trong các đoạn lịch sử dưới đây.
- Không restart/cancel job/gọi API trả phí. Browser native smoke, provider live và áp dụng runtime vẫn chưa thực hiện; giữ Ongoing cho phần nghiệm thu/vận hành còn mở.

**Date**: 2026-10-08 16:31
**Severity**: Medium
**Component**: Media viewer / QA backend Vertex concurrency
**Status**: Ongoing

## What Happened

Đã đọc plan fullscreen, thay đổi spec trong `docs/architecture.md`, `AssetView.tsx`, `MediaViewer.tsx` và báo cáo `plans/reports/vertex-concurrency-resumed-qa.md`. Viewer dùng chung cho ảnh/video ở lưới, nhóm và so sánh; automated QA đạt, nhưng browser smoke và backend full gate chưa hoàn tất.

## The Brutal Truth

Khó chịu nhất là test xanh vẫn chưa chứng minh được controls video và fullscreen native hoạt động đúng trên trình duyệt thật. Gọi đây là “xong” sẽ chuyển rủi ro cho người dùng. Backend cũng không được gọi là xanh khi scanner còn đỏ.

## Technical Details

- Frontend: **220/220 tests PASS**, gồm **30 fullscreen**; typecheck và production build PASS, theo plan.
- Backend: concurrency **40/40** nằm trong unit **212/212**; unit + verify tổng **539 PASS, 1 FAIL**; ruff PASS. Không cộng concurrency lần nữa.
- Failure: `test_no_key_material_committed` gặp 25 đường dẫn fixture `providers.json` chứa marker private-key trong thư mục tmp cũ. Báo cáo không xác nhận đó là key thật hay giả.
- `createPortal(..., document.body)` phủ viewport; media dùng `assetUrl(asset.id)` xác thực cookie, nguyên asset, không re-encode hay gỡ watermark.

## What We Tried

Chọn nút ngoài mở viewer, nút bên trong yêu cầu browser fullscreen sau khi DOM mount. Không dựa vào effect để giữ user activation. API thiếu hoặc từ chối vẫn giữ viewer viewport với thông báo.

Review đã siết background `inert`, focus trap/restore, Esc capture không lan sang so sánh; cleanup và late resolve chỉ thoát fullscreen thuộc viewer, không đụng fullscreen khác. Không xóa fixture hoặc làm yếu scanner để lấy màu xanh.

## Root Cause Analysis

Backend full gate thất bại vì scanner quét cả fixture tmp tồn dư trong project, không phải assertion concurrency. Khoảng trống frontend là chưa kiểm browser thật; harness không chứng minh hành vi native.

## Lessons Learned

Tách viewport viewer khỏi browser fullscreen; quản lý ownership và focus như tài nguyên phải cleanup. Đặt artifact QA ngoài project, giữ nguyên yêu cầu phát hiện secret. Phân biệt automated PASS với nghiệm thu vận hành.

## Next Steps

- QA frontend: trước nghiệm thu, smoke lưới/nhóm/so sánh, contain, Tab/Esc và native video controls/fullscreen.
- Owner + QA backend: xin phép xử lý fixture cũ rồi chạy lại full security gate; không tự xóa.
- Người dùng: lưu output, chờ job kết thúc trước restart backend; restart và kiểm live **chưa làm**. Không đọc secrets hoặc gọi API trả phí trong phiên này.

## Bổ sung hardening backend — 2026-10-08

Re-review xác nhận thêm hai bug; worker đã sửa sau khi cập nhật spec. Đây là lỗi lifecycle và deadline thật, không phải nhiễu scanner:

- `base.py`: cancellation khi ghi output chưa drain worker thread và cleanup đầy đủ file dở dang. Bản sửa shield/drain trước khi trả cancellation, thả lease/slot; lỗi phải xóa cả file chưa register và file đã ghi, giữ nguyên bytes.
- `jobs.py`: deadline poll chưa bao trùm call in-flight và backoff/interval. Bản sửa không bắt đầu poll sau deadline, giới hạn call bằng thời gian còn lại và không nhận done quá hạn; timeout giữ operation id, không submit lại.

Đau ở chỗ số test PASS trước đó không bắt được hai khe hở này. Hủy coroutine không đồng nghĩa thread ngừng ghi; kiểm deadline ngoài call không giới hạn được thời gian call. Bài học: kiểm độc lập cả cleanup sau hủy và budget xuyên suốt call/sleep, không chỉ happy path.

Quyết định giữ nguyên policy `max(2, maxAttempts)`: số lần retry post-submit ngoài lần gọi đầu, không phải tổng calls. Chỉ làm rõ semantics đã có; không đổi cấu hình hay retry policy để xử lý ambiguity tên setting.

**Validation còn chờ**: tester độc lập phải kiểm hai bản sửa, reviewer phải re-review trước khi đóng hardening. Các số liệu QA phía trên thuộc lượt trước, không chứng minh bản sửa mới PASS. Chờ người điều phối cung cấp metrics cuối rồi cập nhật journal; chưa tuyên bố resolved, restart hoặc live validation.

## Bằng chứng cuối — 2026-10-08

Cập nhật từ người điều phối, thay thế trạng thái chờ validation của hai bản sửa phía trên:

- Hardening output bao phủ cả inline và stream qua helper dùng chung trong `base.py`, cho Vertex và HTTP: drain worker khi cancellation lặp lại, cleanup file dở dang trước khi thả tài nguyên. Poll trong `jobs.py` bị chặn bởi deadline xuyên call và backoff.
- **21 tests targeted độc lập PASS**. Backend full: **560 PASS, 1 FAIL**; **ruff PASS**. Failure scanner fixture tmp cũ vẫn nguyên, full gate chưa xanh; không sửa fixture hoặc làm yếu test.
- Review mới nhất thay thế kết luận review trước: **không còn bug được xác nhận trong phạm vi hẹp đã review**. Đây không phải bảo đảm toàn backend hết lỗi.
- Frontend: **220 tests PASS**, typecheck và production build **PASS**. Không cộng 21 targeted vào full-suite để tạo tổng mới.

Nhẹ người vì hai lỗi lifecycle/deadline đã có kiểm thử độc lập và re-review, nhưng không được biến cảm giác đó thành tuyên bố nghiệm thu. Policy retry `max(2, maxAttempts)` vẫn giữ nguyên. Browser native smoke, kiểm live và restart backend **chưa thực hiện**. QA tiếp tục smoke trước nghiệm thu; owner xử lý scanner fixture theo phê duyệt rồi chạy lại full gate; người dùng lưu output và chờ job kết thúc trước restart. Journal giữ **Ongoing** cho các phần còn mở.
