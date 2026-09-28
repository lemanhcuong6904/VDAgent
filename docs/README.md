# Tài liệu VDaAgent / Team 6 cAi

README ở thư mục gốc giúp chạy thử nhanh. Trang này giải thích hệ thống bằng lời đơn giản và chỉ
tới tài liệu chi tiết.

## Hệ thống hoạt động thế nào (đọc trước)

1. Người dùng gửi câu hỏi qua web UI hoặc API (`src/server.ts`).
2. API ghi một "run" vào PostgreSQL rồi trả về ngay. Worker (`src/worker.ts`) nhận run đó và chạy.
3. Worker chọn agent. Agent là một khối code có manifest: tên, input/output, và danh sách quyền.
4. Agent không tự kết nối database hay model. Nó chỉ gọi các "port" do host cấp
   (`src/ports/host-factory.ts`): `model`, `tools`, `warehouse`, `artifacts`, `memory`, `collaboration`.
5. Mỗi port lại gọi tool trong tool pool. Tool chỉ chạy nếu manifest của agent có quyền (`toolGrants`)
   và pool cũng cho phép agent đó. Thiếu một trong hai là bị từ chối.
6. Mọi kết quả port có một `status`: `ok`, `denied`, `failed`, `unknown`... `unknown` nghĩa là việc có thể
   đã xảy ra (ví dụ đã ghi DB nhưng mất kết nối), nên không được tự động thử lại.
7. Kết quả, token và chi phí được ghi lại; event gửi ra ngoài qua outbox.

Ví dụ: câu "vùng nào bán nhiều nhất?" → agent analytics lập kế hoạch → gọi `warehouse` đọc bảng sales →
gọi `model` tóm tắt → trả "North".

## Chọn tài liệu theo việc cần làm

| Tôi muốn... | Đọc |
| --- | --- |
| Chạy thử, cấu hình `.env`, lệnh kiểm tra | [README](../README.md) |
| Viết agent mới (có template và test sẵn) | [Agent authoring](agent-authoring.md) |
| Hiểu agent plugin cũ, prompt, guardrail | [Agents](agents.md) |
| Viết tool và cấp quyền cho agent | [Tools](tools.md) |
| Viết agent bằng Python | [AgentRunner protocol](agent-runner.md) |
| Gọi HTTP/MCP API | [API reference](api.md) |
| Hiểu contract `agent.v1`, ports, schemas | [Public contracts](public-contracts.md) |
| Xem luồng dữ liệu, memory, scale, deploy | [Kiến trúc](architecture.md) |
| Vận hành, backup, worker/outbox | [Operations](operations.md) |
| Auth, rate limit, sandbox, delegation | [Security](security.md) |
| Xử lý sự cố | [Runbooks](runbooks/README.md) |
| Biết ai sở hữu thư mục nào | [Folder ownership](folder-ownership.md) |
| Xem tiến độ và việc còn mở | [PROGRESS](../PROGRESS.md) |
| Xem bằng chứng, receipts | [Execution evidence](execution/README.md) |
| Contract từng subsystem | `docs/contracts/` |

## Chạy local

1. Cài Node.js 22+, Corepack, Docker và Docker Compose.
2. `corepack pnpm install --frozen-lockfile` và `npm --prefix frontend ci`.
3. Chép `.env.example` thành `.env`; điền token local, mật khẩu PostgreSQL và `MODEL_API_KEY`.
   `DATABASE_URL` phải dùng cùng user/password với PostgreSQL trong Compose.
4. `docker compose up --build -d`; mở `http://localhost:3000`.
5. Kiểm tra: `curl -fsS http://localhost:3000/live` trả `{"status":"ok"}`, `/ready` trả 200.

Không commit `.env`. `docker compose down` giữ dữ liệu; `docker compose down -v` xóa dữ liệu local.

## Kiểm thử

| Lệnh | Kiểm gì | Tốn tiền? |
| --- | --- | --- |
| `corepack pnpm check` | TypeScript | Không |
| `corepack pnpm lint` | Biome | Không |
| `corepack pnpm test` | Backend tests (model giả) | Không |
| `corepack pnpm frontend:build`, `npm --prefix frontend test` | Frontend | Không |
| `corepack pnpm baseline:postgres` | Toàn bộ gate trên PostgreSQL dùng một lần, ghi receipt | Không |
| `corepack pnpm bench:e2e` | API + worker + model thật từ `.env`, đo thời gian | Có (dừng khi chạm `--budget`, mặc định $0.30) |

Khoảng 84 test cần PostgreSQL. Chúng chỉ chạy khi có `TEST_DATABASE_URL` trỏ tới database test riêng;
thiếu biến này thì test bị skip và receipt không được PASS. Không trỏ biến này tới production.

Quyền push/PR theo nhánh: [`GIT_RULE.md`](../GIT_RULE.md).
