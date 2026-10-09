# QA backend Vertex concurrency — tiếp tục phiên còn dang dở

Ngày: 2026-10-08, múi giờ Asia/Ho_Chi_Minh. Phạm vi: validation backend offline và báo cáo; không sửa implementation/test/spec/plan/progress của người khác.

## Kết luận

- **Concurrency: 40/40 PASS. Backend unit: 212/212 PASS. Verify: 327 PASS, 1 FAIL. Tổng: 539 PASS, 1 FAIL, 0 SKIP, 1 warning.** Full backend gate **chưa xanh**.
- **Ruff PASS**, exit 0, `All checks passed!`.
- Không có test timeout hoặc hang trong lần chạy này. Pytest hoàn tất trong 72,35 giây; supervisor đo 74,36 giây gồm overhead tooling. Ruff 0,13 giây.
- Failure duy nhất là `test_no_key_material_committed`: scanner toàn cây thư mục gặp 25 đường dẫn fixture `providers.json` có marker private-key dưới `tmp/test-vertex-concurrency-final/run-fcfdb6e991e9/`. Đây không phải failure assertion concurrency. Không xác nhận nội dung fixture là key thật hay giả, không mở lại các file đó.
- Không restart server thật, không cancel job thật, không dừng tiến trình cũ, không gọi API trả phí. Không đọc cấu hình thật `data/providers.json`; audit hook chặn mở đúng đường dẫn này. Tests tự tạo/đọc cấu hình synthetic trong thư mục tạm; scanner hiện hữu cũng đọc fixture cũ như failure trên. Giới hạn này cần được hiểu rõ: lần chạy không chặn mọi file trùng basename `providers.json`, chỉ chặn cấu hình thật của project.

## Nguồn và môi trường

- Đã đọc `CLAUDE.md`, `docs/requirements.md`, plan Vertex concurrency, progress liên quan; đối chiếu architecture mục concurrency/token và fixture/test liên quan trực tiếp. Skills sử dụng: debug, problem-solving, test; project-organization để đặt báo cáo đúng đường dẫn được giao.
- Không có `.git`: `git status --short` trả `fatal: not a git repository`. Không chứng minh được commit/deployment revision, không thao tác Git.
- Tooling hiện hữu: Python 3.12.13, pytest 9.1.1, hypothesis 6.168.5, pytest-asyncio 1.4.0, anyio 4.15.1; không cài/cập nhật dependency.
- Mtime ghi nhận: `vertex_common.py` 14:18:11; `context.py` 14:03:21; `jobs.py` 14:26:35; test concurrency 14:19:44 ngày 2026-10-08; `uv.lock` 17:52:02 ngày 2026-10-07 (+0700). Mtime không phải bằng chứng bản đang chạy trong server thật.
- Không tạo codebase summary vì không cần khảo sát toàn bộ cấu trúc; chỉ đọc đường dẫn đã xác định bởi plan/fixture/log failure. Không dùng repomix để tránh đóng gói credential/dữ liệu ngoài phạm vi.

## Lệnh và hàng rào an toàn

Chạy trong `backend/`, bằng supervisor Python và tooling existing:

```text
LIVE=0 UV_OFFLINE=1 UV_CACHE_DIR=/private/tmp/uv-vertex-qa-cache
AIGEN_DEMO=1 AIGEN_DATA_DIR=<run>/data AIGEN_TMP_DIR=<run>/assets
PYTHONDONTWRITEBYTECODE=1

uv run --offline --no-sync python -c <audit hook + pytest.main>
pytest.main(['tests/unit', 'tests/verify', '-vv', '--tb=short',
             '-o', 'faulthandler_timeout=30', '-p', 'no:cacheprovider'])
uv run --offline --no-sync ruff check --no-cache
```

- Audit hook từ chối `socket.connect` cho AF_INET/AF_INET6, không chỉ dựa vào `LIVE=0`. MockTransport/TestClient chạy in-process; không gọi server đang chạy. Unit fixture copy seed data với ignore `providers.json`; verify fixture dùng thư mục tạm.
- Mỗi subprocess có process group mới; deadline pytest 180 giây, ruff 60 giây. Nếu quá hạn: chỉ SIGTERM group vừa tạo, đợi 5 giây rồi SIGKILL group đó nếu cần. Không timeout thực tế, không phát signal.
- Lần khởi động đầu gặp lỗi sandbox cache `/Users/pix/.cache/uv`; đổi cache tooling sang `/private/tmp`, không cần nâng quyền hoặc mạng. Không thay dependency hay test để vượt gate.
- Log cục bộ: `/private/tmp/vertex-resumed-qa-l1gcwkuu/unit-verify.log` và `/private/tmp/vertex-resumed-qa-l1gcwkuu/ruff.log`. Log failure chỉ liệt kê đường dẫn và regex, không in giá trị key.

## Timeline có bằng chứng

| Thời điểm (+0700, 2026-10-08) | Sự kiện |
|---|---|
| Trước 15:27:01 | Đọc plan/progress/fixture; lỗi cache tooling được giải quyết bằng cache tạm |
| 15:27:01 | Bắt đầu backend unit+verify; collect 540 items |
| Trong lần chạy | Toàn bộ 40 cases concurrency PASS; security scanner ghi một FAIL |
| 15:28:16 | Backend hoàn tất exit 1: 539 passed, 1 failed, 1 warning |
| 15:28:16 | Ruff bắt đầu và hoàn tất exit 0 |

Progress cũ ghi hai regression input-loader/shutdown đã sửa và nhóm input/cancel 4 pass nhưng gate cuối còn chờ. Lần này 4 tổ hợp input-thread cancellation cùng shutdown/remote-cancel tests đều PASS; không suy diễn rằng tiến trình backend thật đã nạp bản sửa.

## Nghiệm thu concurrency đã kiểm

Từ log `tests/unit/test_vertex_concurrency.py`, 40 cases PASS, gồm parametrization:

- 32 waiter chỉ một refresh; token valid không schedule worker; cancel waiter không duplicate refresh; refresh fail có thể phục hồi; client đã close không restart refresh.
- Token session dùng lại, timeout hữu hạn; lỗi refresh/transport được sanitize và phân loại; không gửi generation nếu token acquisition fail.
- Retry budget theo network/auth/post-send, không double-billing; lỗi token khi poll không submit lại generation đã được nhận.
- Cross-batch/model/provider caps, cả concurrencyGroup; rpm spacing; cap chung xuyên client generation cũ/mới; completed task cleanup.
- Reset provider giữ client retired đến lease cuối trong submit/poll/download; pool isolation và targeted reset.
- Close chờ refresh/pools; canceled close waiter không phá cleanup; shutdown chờ cleanup; remote cancel giữ lease kể cả lỗi; input-thread cancellation không hồi sinh bytes cho bốn tổ hợp batch/shutdown.

Đây là bằng chứng offline của cơ chế, không phải xác nhận quota Google, Vertex live, hoặc nguyên nhân mọi TransportError của người dùng.

## Failure: giả thuyết và loại trừ

1. **Regression concurrency/runner gây gate đỏ:** loại trừ đối với failure quan sát được. 212 unit PASS, bao gồm 40 concurrency cases; trace duy nhất trỏ đến scanner `tests/verify/test_s11_s12_safety_keys_access.py:194`, `assert not hits`.
2. **Scanner nhận dữ liệu fixture cũ trong project tmp:** xác nhận chuỗi nguyên nhân trực tiếp. `repo_files()` dùng `os.walk(REPO)`; `SKIP_DIRS` loại tests/cache/venv/dist nhưng không loại `tmp`; log failure chứa 25 đường dẫn cùng root `tmp/test-vertex-concurrency-final/run-fcfdb6e991e9`, không phải thư mục tạm do phiên này tạo. Scanner nhận marker private-key ở những file này rồi làm assertion fail. Không cần mở nội dung credential để chứng minh cơ chế scanner.
3. **Key thật bị commit hoặc lộ qua response:** chưa có bằng chứng kết luận từ failure này. Không có Git metadata để chứng minh commit; marker regex không chứng minh tính thật của credential. Các test bảo mật response/log/zip/config isolation khác PASS, nhưng không thay thế audit key thật. Không bỏ test, không xóa fixture của người khác, không tuyên bố security gate PASS.

Warning duy nhất: StarletteDeprecationWarning từ `fastapi/testclient.py` về dùng httpx với Starlette TestClient. Không phải nguyên nhân exit 1; không đổi dependency ngoài phạm vi.

## Blocker và phòng ngừa

- **P1 — Owner QA/security xử lý phạm vi scanner hoặc artifact hygiene:** xác định quyền sở hữu run cũ trước mọi cleanup; ưu tiên đặt pytest basetemp ngoài project cho các phiên sau. Giữ yêu cầu phát hiện secret ở source, không làm yếu test cho pass. Chạy lại full gate sau xử lý có chủ đích; hiện chưa được phép đóng checklist backend full regression.
- **P1 — Review độc lập cuối còn chờ:** báo cáo này là validation, không thay thế code review; không xác nhận frontend regression trong phiên backend-only.
- **P1 — Vận hành còn chờ người dùng:** tải output chưa lưu, chờ job thật kết thúc rồi chủ động restart để nạp Python mới. Không thực hiện thao tác này trong QA.
- **P2 — Timeout/hygiene:** giữ supervisor deadline và log verbose/faulthandler cho QA; lưu artifact ngoài project, guard credential thật và IP network khi chạy offline. Tiến trình QA cũ được progress nhắc tới chưa được xác định hoặc cleanup, không coi phiên mới hết hang là bằng chứng chúng đã hết.
- **P2 — Theo dõi vận hành sau bàn giao:** đo refresh count/waiters, client-generation lease/close, provider active/queued, before-send retry so với post-send failure; không log token/key/raw exception. Đây là đề xuất, chưa triển khai hoặc kiểm live.

## Câu hỏi còn mở

- Owner có cho phép xử lý thư mục fixture cũ và chạy lại full security/backend gate không?
- Review độc lập cuối và frontend regression của Vertex concurrency đã có bằng chứng cuối chưa?
- Backend thật đang nạp revision nào, job/output nào cần bảo toàn trước restart? Chưa kiểm tra server hoặc job thật.
- TransportError live cụ thể có cùng nguyên nhân với race refresh offline không? Không có log live/trace và không gọi API trả phí để xác nhận.
