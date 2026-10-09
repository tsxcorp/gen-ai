# AI Gen Studio — Working Rules

- Spec là nguồn sự thật: `docs/architecture.md`. Sửa spec trước, code sau. Ý định gốc ở `docs/requirements.md`.
- Guardrails (từ `docs/requirements.md`):
  - Ask first: thêm provider ngoài danh sách; đổi định dạng file cấu hình; ghi ngoài thư mục project; thêm DB.
  - Never: commit key hoặc `data/providers.json`; gửi key xuống trình duyệt; tự retry job `blocked`; re-encode hay gỡ SynthID/watermark; hardcode giá hoặc danh sách model trong code; làm yếu test cho pass; gọi API trả phí trong test tự động khi không có `LIVE=1`.
- YAGNI, KISS, DRY. Implementation thật, không mock để cho pass.
- Tách vai: người viết code ≠ người viết test ≠ người review. Test độc lập dẫn xuất từ `requirements.md`, không từ code.
- Thông số model là dữ liệu trong `manifests/`, kèm `lastVerified`. Mục đánh dấu `[?]` trong requirements phải được kiểm bằng gọi API thật trước khi thành luật cứng.
- Cuối mỗi phiên: ghi `docs/progress.md` (done / next / decisions).
- Quy ước: Python theo `ruff`, TS strict; commit nhỏ, thông điệp mô tả "tại sao". Tiếng Việt cho tài liệu, tiếng Anh cho identifier.
