# Re-review backend Vertex concurrency

Ngày: 2026-10-08. Phạm vi giới hạn: hai bản sửa output worker cancellation và poll deadline trong `backend/app/adapters/base.py`, `backend/app/core/jobs.py`, cùng nhánh streaming Vertex liên quan. Đối chiếu spec architecture, plan và báo cáo QA; không mở rộng frontend hoặc audit security.

## Kết luận re-review mới nhất — sau sửa streaming

- **Không còn lỗi production được xác nhận trong phạm vi hai finding đã sửa.** Finding 1 được đóng ở mức code review có kiểm tra offline giới hạn; finding 2 vẫn giữ kết luận đã sửa. Không phải xác nhận full regression hoặc backend live.
- `run_output_thread` dùng chung cho inline bytes/base64 và chunk write trong Vertex/HTTP. Streaming chờ drain trước khi đóng file, unlink và trả cancellation; Vertex có nhánh cleanup BaseException. Helper generic giữ nguyên cơ chế shield/drain, không đổi retry hoặc submit policy.
- Kiểm tra offline mới trên code hiện tại: Vertex và HTTP streaming, mỗi nhánh worker thành công/thất bại, ba lần cancel khi write bị giữ bằng event. Cả bốn tổ hợp đều giữ coroutine/file cho đến khi worker xong, rồi cleanup và bảo toàn cancellation. Inline bytes/base64 cũng pass cả bốn tổ hợp tương ứng.
- Recheck deadline: không gọi lại sau capped backoff hết deadline; done muộn khi poll nuốt cancellation vẫn bị từ chối. Không xác nhận defect resubmit/double-bill trong thay đổi này.
- Reproduction dùng fake transport/file và patch disk operations, không network hoặc ghi output thật; tất cả worker được giải phóng và drain trong giới hạn giây. Không chạy suite dài. Các test độc lập streaming đang được bổ sung theo bàn giao, chưa coi là PASS.
- QA cũ vẫn là 539 PASS, 1 security-scanner fixture FAIL. **Security/full-backend gate chưa xanh.** Không restart hoặc cleanup backend thật; chỉ cập nhật báo cáo.

## Kết luận vòng trước — đã được thay thế bởi re-review mới nhất

- **Còn một lỗi High, finding cancellation chưa đóng hoàn toàn.** `backend/app/adapters/vertex_common.py:324` vẫn gọi `await asyncio.to_thread(f.write, chunk)` không shield/drain. Output URI qua `base.py:116` gọi fetch trực tiếp, không qua `_write_thread`; Veo GCS dùng nhánh này. Khi cancel giữa write, coroutine đóng file và `_write_all` unlink file hiện tại trước khi worker kết thúc. Runner có thể thả lease/slot và shutdown đi tiếp trong khi write còn chạy. Đây là thiếu sót còn lại của finding 1, không phải finding mới ngoài phạm vi.
- Bằng chứng offline có giới hạn: fake HTTP stream và file/event worker, không network hoặc disk output; sau cancel ghi nhận coroutine đã kết thúc, file đã đóng/unlink nhưng worker chưa xong. Worker được giải phóng và chờ kết thúc trong reproduction.
- Khuyến nghị: drain từng worker ghi streaming, chịu repeated cancellation, trước khi đóng file/unlink/trả cancellation. Bổ sung test độc lập cho output URI/GCS, không chỉ inline bytes/base64; xác nhận lease/slot còn giữ đến khi worker xong.
- **Finding 2 không còn lỗi xác nhận được trong phạm vi kiểm tra.** Kiểm tra code pre/post call, `wait_for` theo remaining-time và sleep capped. Reproduction deadline 5 ms/backoff 20 ms: chỉ một call, kết thúc timeout; poll nuốt cancellation rồi trả done muộn vẫn bị từ chối. Không resubmit generation.
- Inline worker đã shield/drain qua repeated cancellation: ba lần cancel vẫn chờ worker, chỉ unlink sau khi worker kết thúc. Reproduction lỗi partial output xác nhận xóa cả file hiện tại và file trước đó. Không coi bằng chứng này là đã kiểm mọi nhánh streaming.
- Finding 3 là **naming ambiguity**, không phải regression: giữ chính sách invariant 14 `max(2, maxAttempts)` additional retries theo spec đã làm rõ.

## Giới hạn và gate

- Không sửa implementation/test/spec/plan/progress, không đọc providers.json hoặc secret, không gọi API trả phí, không restart/cancel job thật/cleanup runtime. Chỉ thêm báo cáo này theo ủy quyền.
- Không chạy suite dài. QA trước patch: 539 PASS, 1 security-scanner fixture FAIL; 40 concurrency tests PASS. Test độc lập cho patch còn chờ. **Không tuyên bố security/full-backend gate xanh**, không suy diễn số QA cũ là kết quả sau patch.
- Không có Git metadata để chứng minh diff/revision hoặc backend live đã nạp patch.
