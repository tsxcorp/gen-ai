# Gate cuối sau cleanup fixture

Ngày: 2026-10-08, múi giờ Asia/Ho_Chi_Minh. Phạm vi: QA offline và báo cáo; không sửa implementation, test, cấu hình hay dependency.

## Kết luận

**Gate offline PASS.** Scanner regression pass; full backend unit + verify **561/561 pass**; frontend **220/220 pass**; Ruff, typecheck và production build đều exit 0. Không test thất bại, bỏ qua hoặc quá deadline trong lần gate cuối.

Theo thông báo điều phối, main đã xóa đúng 25 file fixture marker-matching trong `tmp/test-vertex-concurrency-final/run-fcfdb6e991e9/` theo phê duyệt người dùng. QA không thực hiện cleanup bổ sung, không xóa thư mục/symlink/output/config và không sửa hoặc làm yếu scanner. Failure scanner ở lần QA trước không còn tái hiện trong lần chạy cuối dưới audit hiện hữu.

## Kết quả chính xác

| Gate | Kết quả | Thời gian runner | Thời gian supervisor | Exit |
|---|---|---:|---:|---:|
| Scanner `test_no_key_material_committed` | 1 pass, 0 fail, 0 skip | 1,35 s | 2,251 s | 0 |
| Backend `tests/unit` + `tests/verify` | 561 pass, 0 fail, 0 skip | 72,89 s | 75,087 s | 0 |
| Backend Ruff toàn cây `.` | All checks passed | — | 0,130 s | 0 |
| Frontend Vitest | 220 pass, 11/11 files pass, 0 fail, 0 skip | 822 ms | 1,095 s | 0 |
| Frontend TypeScript `tsc --noEmit` | PASS | — | 1,703 s | 0 |
| Frontend `npm run build` | TypeScript + Vite PASS | Vite 5,67 s | 7,906 s | 0 |

Hai full suite có tổng **781 test pass**. Scanner targeted là một lần chạy lại test đã nằm trong backend suite, không phải test độc lập thứ 782. Backend bao gồm 21 case output/poll hardening; frontend bao gồm 30 case media fullscreen.

### Warning và hiệu năng

- Pytest scanner và backend đều báo 1 `StarletteDeprecationWarning`: việc dùng httpx với Starlette TestClient bị deprecated. Đây là cùng một loại warning ở hai lần chạy; không đổi dependency để xử lý trong phạm vi gate này.
- Ruff, frontend tests, typecheck và build không báo warning.
- Backend test chậm nhất: `test_us15_no_provider_key_in_responses_sse_zip_logs_or_files`, 8,64 s. Không timeout/hang.
- Frontend file chậm nhất: `src/ui/uploaderEvents.test.tsx`, 355 ms; fullscreen file 94 ms.
- Build transform 125 modules. JS 274,56 kB, gzip 88,55 kB; CSS 19,77 kB, gzip 4,69 kB; HTML 0,40 kB, gzip 0,27 kB.

## Lệnh và hàng rào an toàn

Dùng tooling đã cài: `backend/.venv/bin/python`, `backend/.venv/bin/ruff`, Node/Vitest/TypeScript/Vite hiện hữu. Không dùng uv hoặc tải dependency.

```text
LIVE=0 AIGEN_DEMO=1 PYTHONDONTWRITEBYTECODE=1
pytest.main([<target>, '-q', '--tb=short', '--durations=5',
             '-o', 'faulthandler_timeout=30', '-p', 'no:cacheprovider',
             '--basetemp', <project-local path>])
backend/.venv/bin/ruff check . --no-cache
node node_modules/vitest/vitest.mjs run
node node_modules/typescript/bin/tsc --noEmit
npm run build
```

- Reuse cấu trúc supervisor/audit offline: mỗi subprocess có process group riêng, stdout/stderr vào log trong project. Deadline scanner 45 s; backend 120 s; Ruff 30 s; frontend tests/typecheck 45 s mỗi lệnh; build 60 s. Không deadline nào bị vượt; không phát signal dừng tiến trình.
- Audit Python từ chối socket connect/sendto AF_INET/AF_INET6 và mở cấu hình thật `data/providers.json`. MockTransport/TestClient in-process vẫn được dùng. Dữ liệu/cấu hình synthetic của tests nằm dưới basetemp.
- Node preload artifact chặn TCP/TLS/UDP qua API Node chuẩn và mở/read cấu hình provider thật qua fs; được truyền tới frontend subprocess/worker bằng `NODE_OPTIONS`. Không thay source frontend hoặc dependency.
- `TMPDIR`, `TEMP`, `TMP`, `AIGEN_DATA_DIR`, `AIGEN_TMP_DIR` và Hypothesis storage đều trỏ vào vùng QA trong project. Không tạo output mới ngoài project trong lần gate này.
- Không gọi API trả phí, không đọc key thật, không restart server hoặc cancel job thật. Không có cleanup ngoài 25 fixture do main đã thực hiện.

## Bằng chứng lưu trong project

Root: `backend/tests/.qa-tmp-gate-20261008-final/`.

- `scanner.log`, `backend.log`, `ruff.log`.
- `frontend-tests.log`, `frontend-typecheck.log`, `frontend-build.log`.
- `results.json`: exit code, thời gian supervisor, trạng thái timeout của cả sáu gate.
- `scanner-temp/`, `backend-temp/`, `system-tmp/`, dữ liệu synthetic và artifact `offline-node.cjs`.
- `frontend/dist/`: output production build được tạo lại bởi lệnh build chuẩn.

QA của lần này chỉ tạo báo cáo và artifact validation; **không tạo/sửa test hoặc implementation**. Artifact cũ được giữ nguyên.

## Giới hạn và đề xuất

- Không xác nhận browser thật, native fullscreen/focus/video controls, visual layout, provider live hoặc server đang chạy. Test harness và offline fakes không thay thế các kiểm tra đó.
- Scanner pass dưới audit chặn đọc cấu hình thật; không suy ra `data/providers.json` vắng mặt hay an toàn từ kết quả này. Không mở file thật để xác minh.
- Không đo line/branch/function coverage, benchmark tải hoặc memory leak trong gate này; không có claim coverage hay performance production.
- Đề xuất riêng sau gate: xử lý deprecation TestClient khi được giao; browser/live QA cần phạm vi và phê duyệt riêng. Không thực hiện thêm trong phiên này.

## Câu hỏi chưa giải quyết

Không có câu hỏi chặn gate offline. Browser/live và coverage vẫn chưa được kiểm chứng, ngoài phạm vi được giao.
