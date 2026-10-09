# Uploader dùng chung và edit ratio theo ảnh gốc

Trạng thái: hoàn tất implementation, kiểm thử tự động và review; browser smoke bị chặn. Ngày: 2026-10-08.

## Phạm vi đã được duyệt
- React/TypeScript strict, FastAPI giữ nguyên API/config. Không thêm dependency/provider, không gọi API trả phí.
- Uploader dùng chung ảnh/key JSON; kéo thả, paste ảnh theo focus, preview/gỡ/validation, consent bắt buộc trước upload.
- Edit hiện ảnh ngay dưới prompt. Auto theo ảnh tham chiếu đầu tiên, exact/nearest với thông báo; size WxH theo sizeRule. Không re-encode/crop.
- Icon SVG cho option và nhóm điều khiển, polish tối vừa phải, bàn phím/focus và responsive.

## Checklist
- [x] Khảo sát UI, manifest, upload API và luồng request.
- [x] Cập nhật requirements/spec trước code.
- [x] Review độc lập kế hoạch/thiết kế (ui-ux-designer); bổ sung lifecycle, constraint, deterministic sizing và confirmation freshness.
- [x] Uploader chung và tích hợp ReferenceUpload/VertexForm.
- [x] Auto ratio/size dùng nhất quán ở resolve/estimate/payload/submit; edit image visibility.
- [x] Icon, option controls và polish UI (code/kiểm thử tự động; chưa xác minh thị giác trong browser).
- [x] Test độc lập từ requirements, typecheck/build: automated verified; browser blocked (approval service 404), không ghi nhận browser pass.
- [x] Review độc lập và sửa lỗi trong phạm vi.
- [x] Cập nhật docs/progress.md, bàn giao và giới hạn chưa xác minh.

## Touchpoints
`frontend/src/ui`, `panel`, `settings/VertexForm`, `lib/imageSizing`, `api/hooks`, `store/studio`, `styles.css`, test frontend. Không sửa backend hoặc config schema.

## Bằng chứng cuối và giới hạn (2026-10-08)
- Theo bằng chứng main cung cấp: tester độc lập chạy `npm test` — 190 pass / 0 fail / 0 skip trong 10 file (765 ms); `npm run typecheck` PASS; `npm run build` PASS, 124 modules (5,78 s), không warning. Worker kiểm tra độc lập cùng 190 tests/typecheck/build PASS.
- Reviewer re-review: cả 3 stale contexts CLOSED, không còn bug cụ thể được xác nhận. Phạm vi là code/test với event harness nông, không phải browser. Các sửa context gồm Reuse cùng model/remount theo requestVersion, mounted/live-state trước submit sau estimate, raw payload/draft signatures và guard context/capacity khi upload.
- Debugger: probes gốc pass; chooser tối ưu khớp exhaustive trên 500 trường hợp bounded, không còn issue được xác nhận. Nearest-height scan giữ ưu tiên ratio → area; đã xử lý WxH allowed/bounds/hiệu năng và phục hồi dimensions không hợp lệ.
- Không thêm dependency; không đổi config/API schema/backend. README và progress đã sync; journal do journal-writer độc lập sở hữu.
- Browser smoke không khả dụng do approval service 404; không có xác minh browser/API live, không gọi API trả phí. Tỷ lệ ảnh đầu ra của adapter/model thật chưa được kiểm bằng live generation. Repo không có `.git`, không commit.

## Tiếp theo — browser smoke thủ công (chưa thực hiện)
- Mở `http://localhost:5173` khi frontend dev chạy, dùng demo: ảnh 1600 × 900 → Auto 16:9 nếu model cho phép; xác nhận uploader không crop ảnh gốc. Thử ảnh dọc, tỷ lệ gần đúng và thay/gỡ ảnh đầu tiên.
- Thử chọn/drag/paste theo focus, consent trước upload và reset khi thay file, HEIC không đọc được kích thước → manual.
- Kiểm tra JSON hợp lệ/không hợp lệ, không paste ảnh/preview key; không đưa secret vào ảnh chụp/log.

## Tiêu chí nghiệm thu
- Chọn/kéo thả/paste ảnh đều đi qua validation và consent; preview không làm đổi byte ảnh.
- Chế độ edit không giấu input dưới advanced; file JSON vẫn parse/validate và không hiện secret.
- 1600×900 → 16:9 nếu model hỗ trợ; ratio lạ có cảnh báo, thiếu dimensions thì không submit Auto. Ảnh đầu tiên thay/gỡ cập nhật tỷ lệ.
- Payload không chứa sentinel Auto; manual, model switch, preset/reuse, sweep và video không bị phá vỡ.
- Test hiện có và test độc lập mới pass; không phát sinh type/build error.
