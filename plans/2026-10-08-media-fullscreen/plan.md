# Viewer toàn màn hình và tiếp tục QA

Ngày: 2026-10-08. Trạng thái: hoàn tất code, automated QA và review; gate offline xanh sau cleanup được duyệt, browser smoke và áp dụng runtime còn chờ.

- [x] Khảo sát phiên trước, requirements, AssetView/lưới/so sánh; spec trước code.
- [x] Review kế hoạch: viewer dùng chung, portal tránh modal lồng nhau, focus trap, Esc chặn lan sang so sánh, cleanup chỉ fullscreen sở hữu.
- Quyết định sau review: nút ngoài mở viewer phủ viewport; nút trong viewer yêu cầu browser fullscreen khi DOM đã mount (không phụ thuộc activation qua effect). Browser thoát fullscreen đóng viewer. Late resolve chỉ thoát đúng element đã tháo; giữ nguyên fullscreen không thuộc viewer. Background inert, cleanup idempotent, restore focus khi opener còn kết nối.
- [x] Triển khai viewer tại AssetView + component viewer + CSS; không đổi config/API/dependency.
- [x] Tester độc lập kiểm từ requirements, typecheck/test/build; debugger tiếp tục backend QA offline có giới hạn.
- [x] Review code độc lập, bàn giao giới hạn browser/live/restart; docs-manager sync progress.
- [ ] Browser smoke thực tế: lưới đơn/nhóm/so sánh, native video controls/tab/fullscreen và viewport contain.
- [x] Backend full security gate: 561/561 pass sau khi người dùng duyệt xóa đúng 25 file fixture cũ gây lỗi; scanner/test không đổi.

## Bằng chứng
- Frontend 220/220 tests (30 fullscreen), typecheck và production build PASS; re-review không còn bug production được xác nhận bằng inspection. Harness không thay thế browser.
- Backend concurrency 40/40, unit 212/212, ruff PASS; chi tiết tại `plans/reports/vertex-concurrency-resumed-qa.md`.
- Review backend sau QA phát hiện output-worker cancellation/partial-file và poll vượt deadline; bổ sung spec trước khi sửa `base.py`/`jobs.py`; số liệu 539/1 thuộc bản trước hardening này.
- Bản hardening cuối gồm streaming Vertex/HTTP dùng shared output-thread drain: 21/21 test độc lập mới PASS, full backend 560 PASS/1 scanner FAIL, ruff PASS. Re-review không còn lỗi cụ thể trong phạm vi đã sửa; giữ nguyên retry policy và operation, không resubmit generation. Không coi full gate xanh hoặc live verified.
- Gate cuối sau cleanup được duyệt: scanner targeted 1/1 PASS; backend 561/561 PASS (72,89 giây); frontend 220/220 PASS; ruff, typecheck và build PASS. Bằng chứng mới tại `plans/reports/final-gate-after-fixture-cleanup.md` thay thế trạng thái scanner pending phía trên, không thay thế browser/live verification.
- Chỉ xóa đúng 25 file fixture marker-matching dưới `tmp/test-vertex-concurrency-final/run-fcfdb6e991e9/` theo phê duyệt; không xóa thư mục, symlink, output khác hay cấu hình thật. Không restart backend, reload tab kết quả, cancel job hoặc gọi API trả phí. Người dùng lưu output/chờ job xong trước khi restart Python.

Nghiệm thu: nút cho mỗi ảnh/video kể cả nhóm và so sánh; contain, video controls không autoplay; đóng/Esc/focus; fallback fullscreen an toàn; URL cookie nguyên bản; không tác động job/download/reuse. Không restart server hoặc gọi API trả phí.
