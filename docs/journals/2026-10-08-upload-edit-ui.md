# Upload/edit: đúng ảnh, đúng request, không chỉ đúng giao diện

**Date**: 2026-10-08 13:28
**Severity**: High
**Component**: Frontend upload/edit, Auto sizing, request pipeline
**Status**: Ongoing

## What Happened

Theo `docs/architecture.md` và requirements #11, phiên này thống nhất `FileDropzone` cho ảnh/key JSON; sửa ảnh đầu vào edit bị ẩn bởi nhãn advanced. Ảnh hiện dưới prompt, không phụ thuộc nút mở nâng cao. Review độc lập phát hiện race khi chuyển request, kể cả Reuse cùng model.

## The Brutal Truth

Ẩn đầu vào edit là lỗi thiết kế UI, không phải người dùng thiếu kiên nhẫn. Khó chịu hơn: giao diện đã đổi nhưng callback cũ vẫn có thể gắn ảnh hoặc submit request khác. Nhìn đúng không có nghĩa là chạy đúng; không thể đóng phiên chỉ bằng cảm giác yên tâm.

## Technical Details

- `frontend/src/ui/FileDropzone.tsx`: paste chỉ trong uploader được focus; kiểm MIME/đuôi file, dung lượng, số lượng. JSON không preview nội dung key, không nhận paste ảnh.
- `ReferenceUpload.tsx`: staging/preview trước consent; reset consent khi đổi tập ảnh. Multipart giữ file gốc, không crop/re-encode hay đụng watermark; ảnh chờ chưa là nguồn Auto.
- `imageSizing.ts`: lấy dimensions ảnh committed đầu tiên. Ratio dùng `abs(log(candidate/source))`, chọn khớp hoặc gần nhất và cảnh báo. WxH tuân `sizeRule`, ưu tiên ratio rồi diện tích mặc định. Thiếu dimensions phải chọn thủ công, không gửi sentinel Auto.
- Params cụ thể đi xuyên resolve/estimate/raw/submit. `requestVersion` phân biệt request cùng model; upload kiểm live context. Raw dùng signature freshness; confirmation cũ mất hiệu lực khi nội dung request đổi.

## What We Tried

Chọn uploader chung thay vì hai luồng xử lý file riêng; giữ consent riêng cho ảnh. Chọn input edit luôn hiện thay vì buộc mở advanced. Debug tối ưu tìm WxH bằng nearest-height/bounds thay cho quét mọi cặp, giữ thứ tự ưu tiên. Siết validation dimensions, allowed/force và giới hạn `sizeRule`; không hardcode model hoặc fallback âm thầm.

## Root Cause Analysis

Lọc advanced đã đánh đồng đầu vào bắt buộc với tùy chọn. Kiểm model/mode không đủ nhận diện request; cùng model vẫn có thể là lần Reuse mới. Callback bất đồng bộ và snapshot debounce cần kiểm độ mới ngay trước tác động.

## Lessons Learned

Review phải kiểm lifecycle, không chỉ layout. Metadata ảnh chỉ có giá trị khi thuộc context hiện hành; tối ưu search không được đổi constraint hoặc tiebreak.

## Next Steps

Main ghi kết quả verification cuối vào `docs/progress.md` trước bàn giao; tester/reviewer kiểm regression request-switch, freshness và WxH. Journal không xác nhận gate cuối. Không chạy API trả phí hay browser test; browser bị chặn bởi `approval-service 404`. Giới hạn adapter/model live không đổi; kiểm live cần phiên riêng được phép.
