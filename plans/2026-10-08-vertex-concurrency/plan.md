# Ổn định nhiều job Vertex chạy đồng thời

Ngày: 2026-10-08. Trạng thái: implementation/re-review và gate offline hoàn tất; browser, live verification và restart runtime còn chờ.

## Bằng chứng và phạm vi
- Tái hiện offline 8 token callers → 8 refresh trước sửa; không đọc key, không gọi API thật.
- Chia sẻ client theo provider, single-flight token, phân loại lỗi transport an toàn và retry before_send theo budget cũ.
- Giữ giới hạn model/group/rpm, thêm cap provider dẫn xuất từ manifest; dọn task và close client an toàn khi reconfigure/shutdown.
- Không sửa provider/config format/DB/giá/model list; không tự retry blocked hoặc job đã submit.

## Checklist
- [x] Khảo sát token, factory/context, runner và limiter; tái hiện offline.
- [x] Cập nhật requirements/spec trước code.
- [x] Review độc lập kế hoạch/thiết kế (debugger); bổ sung lease atomic, remote cancel, ownership và generation-independent cap.
- [x] Single-flight/cached token/transport/session lifecycle.
- [x] Client pooling/provider concurrency/task cleanup/retirement lease.
- [x] Test độc lập concurrency/cancellation/retry/không double-bill; backend unit+verify, ruff, frontend regression.
- [x] Hardening inline/stream output cancellation và poll deadline theo spec cập nhật trước code.
- [x] Review độc lập và cập nhật docs/progress (re-review backend giới hạn inline/stream drain và poll deadline).

## Nghiệm thu
- 32 waiter chung một credential refresh đúng một lần; token còn valid không refresh; waiter bị cancel không phá job khác.
- Token transport fail trước generation có network/before_send và reason không secret; auth permanent không retry; generation timeout sau send không resubmit.
- Nhiều batch/model không vượt cap provider hoặc model riêng; queued không giữ bytes input. Cấu hình provider khác không đóng client Vertex đang dùng.
- Retired shared client không đóng khi job còn active; close một lần sau lease cuối; shutdown chờ refresh/cleanup; completed tasks được dọn.
- Không gọi API trả phí, test mô phỏng transport để kiểm cơ chế chứ không giả implementation.

## Trạng thái QA và bàn giao còn chờ (2026-10-08)
- **Bằng chứng mới nhất sau cleanup được duyệt:** `../reports/final-gate-after-fixture-cleanup.md`: scanner 1/1 PASS; full backend 561/561 PASS trong 72,89 giây; frontend 220/220 PASS, ruff/typecheck/build PASS. Không fail/skip/timeout, còn warning deprecation Starlette/httpx. Người dùng duyệt xóa đúng 25 file fixture gây lỗi dưới run cũ; không xóa thư mục/symlink/output khác/config thật, không sửa scanner/test. Đóng gate offline; các số liệu 539/1 và 560/1 phía dưới là lịch sử trước cleanup, không còn là blocker hiện tại. Browser/live/restart vẫn pending.
- QA nền tại `../reports/vertex-concurrency-resumed-qa.md`: concurrency 40/40 PASS (nằm trong unit 212/212 PASS), tổng unit+verify 539 PASS, 1 FAIL. Bằng chứng cuối sau hardening do main cung cấp: test độc lập `backend/tests/unit/test_output_poll_hardening.py` 21/21 PASS trong 0,82 giây; full backend 560 PASS, 1 FAIL trong 72,35 giây; ruff PASS, warning hiện hữu còn nguyên. Gate kết hợp vẫn pending vì scanner chưa xanh.
- Failure duy nhất: `test_no_key_material_committed` gặp 25 đường dẫn fixture cũ có marker private-key dưới `tmp/test-vertex-concurrency-final/run-fcfdb6e991e9/`. Không kết luận marker là key thật hay giả; không làm yếu scanner hoặc xóa fixture để đổi gate thành xanh. Hai regression input-loader/shutdown đã được kiểm lại, gồm bốn tổ hợp input-thread cancellation PASS.
- Spec architecture cập nhật trước hardening: `run_output_thread` trong `base.py` dùng chung cho inline bytes/base64 và chunk streaming trong `vertex_common.py`/`http_common.py`, drain trước close/unlink/thả lease; dọn partial output hiện tại khi thất bại. Poll không bắt đầu hoặc chấp nhận done quá deadline, backoff/call giới hạn theo thời gian còn lại. Invariant 14 giữ `max(2, maxAttempts)` retries bổ sung ngoài lần gọi đầu; chỉ làm rõ ambiguity, không đổi hành vi.
- Re-review mới nhất tại `../reports/vertex-concurrency-resumed-review.md` thay thế findings cũ: không còn lỗi production được xác nhận trong phạm vi inline/stream drain và poll deadlines; không phải audit security toàn hệ thống hoặc xác nhận backend live. Báo cáo còn ghi QA trước patch; số liệu cuối 560 PASS / 1 FAIL ở trên do main cung cấp sau đó. Failure scanner fixture cũ tại verify line 194 không đổi.
- Bằng chứng frontend cuối do main cung cấp, không đổi: 220/220 tests PASS trong 11 file, gồm 30 fullscreen tests; typecheck/build PASS (Vite 5,91 giây, không warning). Reviewer re-review không còn bug production được xác nhận; các issue TS, tab video, descendant fullscreen và opener trước đó đã sửa. Frontend automated regression/re-review hoàn tất; không suy diễn thành browser PASS.
- Browser native fullscreen, tab qua video controls và bố cục trực quan chưa được xác minh: UI observation rất chậm, chưa thực hiện smoke thật. Không đánh dấu browser hoàn tất hoặc suy diễn automated tests thành browser PASS.
- Một số tiến trình pytest/review/QA cũ còn treo với code cũ. Approval cho kiểm tra `ps` lỗi 404; cleanup còn chờ metadata session đã biết hoặc bàn giao người dùng, không xác định/dừng tiến trình theo suy đoán.
- Backend thật (87341 theo main) chưa restart, không can thiệp job/ảnh hiện có. Bản sửa Python cần restart để áp dụng, nhưng chỉ sau khi người dùng tải output chưa lưu và job active hoàn tất; không tự restart/cancel/cleanup kết quả. Chưa xác minh live Vertex; không coi hoàn tất code/test là đã hoàn toàn vận hành bản sửa.
