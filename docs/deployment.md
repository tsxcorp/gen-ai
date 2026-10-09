# Triển khai server B

## Kiến trúc
- Server B: Docker Compose project `genai` tại `/opt/gen-ai`, gắn network ngoài `dokploy-network`.
- Frontend: `https://gen-ai.nexpo.vn`; backend: `https://api-genai.nexpo.vn/api/health`.
- Frontend gọi `/api` cùng origin qua Traefik tới cùng backend để giữ cookie/SSE/asset hiện hữu; không cần CORS. Domain API riêng dùng cho tích hợp có header token, không thay API base URL của frontend.
- Một process/replica backend vì hàng đợi, session và event hub ở RAM. Không scale nhiều worker; restart làm mất trạng thái job trong RAM, cần để job đang chạy hoàn tất trước khi redeploy.
- DNS A của hai domain trỏ server B; TLS tự cấp bằng resolver Traefik `letsencrypt` hiện hữu. Compose chỉ thêm router/containers riêng, không chỉnh app khác.

## Secret và dữ liệu
- `.env.production` trên server: `AIGEN_TOKEN` ngẫu nhiên, quyền `600`; không đưa vào Git/image và không in token trong hướng dẫn. Người quản trị lấy token qua SSH và nhập vào form access token của frontend, không truyền qua URL.
- LAN mode bắt buộc, demo tắt. Health public; các API khác cần token/header hoặc cookie cho media/SSE theo spec.
- Không chuyển `data/providers.json` local lên server. Cấu hình provider qua UI bằng HTTPS; key chỉ lưu backend.
- Volume `genai_genai-data` chứa cấu hình runtime, `genai_genai-output` chứa output. Không chạy `down -v` hoặc prune volume; tải output cần lưu trước khi cleanup/redeploy.
- Dockerfile chạy user UID 10001; build context chỉ cho phép source, manifest và bốn JSON không-secret.

## Cập nhật
1. Chạy test offline với `LIVE=0`, kiểm secret và commit/push source.
2. Đưa snapshot source đã duyệt vào `/opt/gen-ai`, không copy key, cache, output hoặc `.git` vào build context.
   Khi tạo archive trên macOS dùng `COPYFILE_DISABLE=1 tar --no-mac-metadata`; `.dockerignore` cũng loại `._*` để manifest loader không đọc nhầm AppleDouble thành YAML.
3. Chạy `docker compose -p genai -f compose.production.yml build`; chỉ chuyển sang image mới khi test và review đạt.
4. Ghi nhận image ID cũ và tag giữ lại trước khi cập nhật, sau đó `docker compose -p genai -f compose.production.yml up -d`.
5. Kiểm tra health hai domain, HTTP redirect, TLS, API không-token trả 401, API có-token/session/media hoạt động. Không gọi generation trả phí khi smoke.

## Rollback và vận hành
- Tag image cũ thành `gen-ai:rollback-<release>` trước khi rebuild. Để rollback: `GENAI_RELEASE=rollback-<release> docker compose -p genai -f compose.production.yml up -d --no-build`. Không xóa volume.
- Kiểm tra trạng thái bằng `docker compose -p genai -f compose.production.yml ps`; healthcheck gọi localhost không tốn phí provider.
- Khi token được cấp qua `AIGEN_TOKEN`, backend không in token vào startup log. Không chia sẻ raw log/secret và chỉ truy cập log trong môi trường quản trị riêng.
- Backup data volume bảo mật riêng, giữ quyền truy cập hạn chế; không commit backup hoặc output.
- Theo dõi dung lượng output; Docker restart có thể tái sử dụng PID nên cleanup run cũ không bảo đảm xóa mọi output sau crash. Trước khi vận hành dài hạn cần policy retention/backup riêng; không tự xóa output người dùng để lấy chỗ trống.

## Bằng chứng QA 2026-10-09
- Test độc lập offline: backend unit 233 PASS, frontend 220 PASS; frontend TypeScript/build PASS.
- Compose validate không resolve runtime env: PASS. Không gọi API generation trả phí.
- Runtime/TLS: container `genai-app-1` healthy; hai domain HTTPS chứng chỉ hợp lệ, health `demo=false`, `lan=true`, `tokenRequired=true`, 14 model. HTTP redirect 308 về HTTPS đã kiểm từ server và máy local.
- API không-token trả 401; manifests/providers có token PASS; session có HttpOnly/SameSite=Strict PASS. Token không xuất hiện trong startup log. UID 10001 ghi được cả hai volume, không publish host port; giới hạn 2 GiB/2 CPU/256 PID được Docker enforce.
- Image release giữ lại: `gen-ai:release-20261009`, ID `sha256:22280265d75985d952e4206a7b36002afbd69ee034f752606a08733cf8171786`. Không chuyển provider credentials local; người quản trị cần cấu hình qua UI.
