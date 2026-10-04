# VDaAgent

Trợ lý phân tích gồm 6 agent, dành cho Sales Ops bất động sản. Bạn đặt câu hỏi bằng ngôn ngữ tự nhiên, ví dụ "Vì sao căn
MAS-U03832 bán chậm? So sánh với các căn tương đồng, vẽ biểu đồ và xuất báo cáo.". Hệ thống đọc **kho dữ liệu thật**
(PostgreSQL của team DATA) và trả về câu trả lời có trích dẫn, biểu đồ và báo cáo 6 phần.

- **Các agent:** Orchestrator, Data, Insight, Compare, Chart và Report. Chúng là plugin chạy trong cùng một tiến trình
  Backend, và chỉ giao tiếp qua engine của Backend cùng một artifact store dùng chung.
- **LLM ở chỗ cần ngôn ngữ, code ở chỗ cần con số.**
  - LLM của Orchestrator hiểu câu hỏi và đề xuất plan. Code kiểm tra plan rồi chạy nó dưới dạng DAG.
  - Insight dùng LLM để diễn đạt kết quả.
  - Data, Compare, Chart và Report chạy deterministic.
- **Truy vết được.**
  - Mọi artifact đều có version và content hash.
  - Mọi con số trong biểu đồ hay báo cáo đều có `source_ref` trỏ về đúng field của artifact.
  - Mỗi run pin một snapshot và một semantic version: production `SNAP-20260630-01` / `3.1.0`; kho giả
    `SNAP-2026-09-28` / `sc-1`.

## Kiến trúc tóm tắt

```text
UI / REST → Backend FastAPI (6 plugin cùng process) → Orchestrator: LLM đề xuất plan, code kiểm tra (catalog · deps · pin)
  → Data → [Insight ∥ Compare] → Chart → Report        (mọi artifact: có version, hash, nằm trong artifact store)
Kho: production AWS RDS cdw (view re → gold) · test/offline: SQLite chỉ khi chỉ định rõ (make mock-up)
```

Chi tiết: [docs/architecture/system.md](docs/architecture/system.md). Quy tắc và trạng thái kiểm chứng:
[AGENTS.md](AGENTS.md). Mục lục tài liệu: [docs/README.md](docs/README.md).

## Quick Start

**Cần có:** Docker với Compose v2, một API key tương thích OpenAI và **kho dữ liệu PostgreSQL** (xem bên dưới).
Không cần Python hay Node trên máy. Linux dùng GNU make; Windows dùng Docker Desktop và Windows PowerShell
(WSL2 không bắt buộc).

### 1. Clone

```bash
git clone git@github.com:HOANGQUANGMINH371195/Team_6_cAi.git
cd Team_6_cAi
```

### 2. Configure

```bash
cp .env.example .env
```

Điền vào `.env`:

| Biến | Bắt buộc? | Ghi chú |
|---|---|---|
| `OPENAI_API_KEY` | **bắt buộc** | key của endpoint tương thích OpenAI |
| `OPENAI_BASE_URL` | **bắt buộc** | đã điền sẵn `https://api.openai.com/v1` |
| `LLM_MODEL` | **bắt buộc** | đã điền sẵn `gpt-4o-mini` (đã kiểm chứng) |
| `VDAGENT_RE_WAREHOUSE_DB` | **bắt buộc** | DSN của kho thật: `postgresql://vdagent_reader:<mật khẩu>@<host>:<port>/<db>`, nhìn **từ trong Docker** |
| `ORCH_SNAPSHOT_ID` | **bắt buộc** | đã điền sẵn `SNAP-20260630-01`; phải là snapshot APPROVED trong kho |
| `ORCH_SEMANTIC_VERSION` | **bắt buộc** | đã điền sẵn `3.1.0`; phải khớp snapshot |
| `GEMINI_API_KEY` | tuỳ chọn | Insight dùng Gemini trước nếu có key này |
| `VDAGENT_PORT` | tuỳ chọn | cổng của UI và API, mặc định `8000` |

### Cách xác định `VDAGENT_RE_WAREHOUSE_DB`

DSN có dạng:

```text
postgresql://<user>:<password>@<host>:<port>/<database>
```

Với warehouse local được repo hướng dẫn dựng, DSN trong `.env` thường là:

```text
postgresql://vdagent_reader:<YOUR_PASSWORD>@host.docker.internal:5433/cdw
```

Không ghi password thật vào README, Git hoặc log.

**User và password.** Backend dùng role đọc riêng `vdagent_reader`, không dùng tài khoản admin `postgres`.
Role này được tạo/cập nhật bởi [`docker/warehouse/apply-views.sh`](docker/warehouse/apply-views.sh), với password truyền
qua biến `VDAGENT_READER_PASSWORD`. Khi dựng warehouse theo [hướng dẫn Data agent](agents/data/README.md), password là
giá trị `READER_PW` bạn tự tạo/cấp lúc chạy bước tạo role; nếu warehouse do team khác quản lý, lấy password của role
`vdagent_reader` từ người quản trị warehouse. Password không được lưu trong repo. Nếu quên password, đặt password mới
bằng script `apply-views.sh` rồi cập nhật `.env`.

**Database và port.** Container local mặc định là `cdw-pg`, database là `cdw`, PostgreSQL trong container lắng nghe
`5432`, còn host publish ra `5433`. Kiểm tra container và port mapping:

Linux:

```bash
docker ps
docker port cdw-pg
```

Windows PowerShell:

```powershell
docker ps
docker port cdw-pg
```

Nếu thấy:

```text
5432/tcp -> 127.0.0.1:5433
```

thì `host port = 5433`, `PostgreSQL container port = 5432`. Để xác nhận database name:

```bash
docker exec cdw-pg printenv POSTGRES_DB
```

Lệnh trên cũng chạy nguyên dạng trong Windows PowerShell. Với setup local hiện tại, kết quả là `cdw`. Nếu biến này
không có, xem danh sách database bằng:

```bash
docker exec -it cdw-pg psql -U postgres -l
```

`localhost` và `127.0.0.1` trong container là chính container backend, không phải máy host. Vì vậy PostgreSQL trên
host có địa chỉ `127.0.0.1:5433` phải được viết trong DSN của backend Docker là `host.docker.internal:5433`.
Không dùng `localhost:5433` trong `VDAGENT_RE_WAREHOUSE_DB`.

**Kiểm tra kết nối từ host.** Nếu máy host có `psql`, kiểm tra bằng loopback của host:

```bash
psql "postgresql://vdagent_reader:<PASSWORD>@127.0.0.1:5433/cdw"
```

Trên Windows PowerShell dùng cùng lệnh nếu `psql` đã có trong `PATH`. Đây chỉ là kiểm tra từ host; kiểm tra đúng
theo góc nhìn Docker bằng:

Linux:

```bash
make warehouse-check
```

Windows PowerShell:

```powershell
.\dev.ps1 warehouse-check
```

Raw Compose equivalent:

```powershell
docker compose -f docker-compose.yml run --rm warehouse-check
```

Kết quả thành công sẽ in warehouse backend/source, snapshot, semantic version và số units; số units có thể thay đổi
theo dataset. Ví dụ:

```text
Warehouse backend: PostgreSQL
Warehouse source: host.docker.internal:5433/cdw
Snapshot: SNAP-20260630-01 (APPROVED)
Semantic version: 3.1.0
Units visible in schema re: 47713
```

| Lỗi | Nguyên nhân thường gặp | Cách xử lý |
|---|---|---|
| `connection refused` | Sai host/port hoặc PostgreSQL chưa chạy | Chạy `docker ps`, `docker port cdw-pg`; kiểm tra port mapping |
| Dùng `localhost` trong Docker | Container đang tự gọi chính nó | Đổi host thành `host.docker.internal` |
| `password authentication failed` | Sai user/password | Kiểm tra credentials của role đọc `vdagent_reader` |
| `database does not exist` | Sai database name | Kiểm tra `POSTGRES_DB` hoặc `psql -l` |
| `warehouse-check` fail snapshot | Warehouse không đúng dataset/version | Kiểm tra `ORCH_SNAPSHOT_ID` và `ORCH_SEMANTIC_VERSION` |

**Host trong DSN:** PostgreSQL ở máy khác thì dùng tên/IP của máy đó. PostgreSQL trên chính máy bạn thì dùng
`host.docker.internal`, và cổng của nó phải mở cho Docker (vd `-p 172.17.0.1:5433:5432`); `127.0.0.1`/`localhost` bị
từ chối vì trong container đó là chính container.

**Chưa có endpoint kho thật?** Dựng bản snapshot `SNAP-20260630-01` mà team DATA giao trong `warehouse/backup/` theo
[agents/data/README.md](agents/data/README.md#1-dựng-postgres-và-nạp-dw-một-lần) bước 1–2, rồi dùng
`VDAGENT_RE_WAREHOUSE_DB=postgresql://vdagent_reader:<mật khẩu>@host.docker.internal:5433/cdw`.

### 3. Run

#### Linux

```bash
make up
```

Lần đầu mất vài phút để build image. `make up` dừng ngay với thông báo rõ ràng (không in giá trị bí mật) nếu `.env` thiếu
biến, nếu kho không kết nối được từ Docker, hoặc nếu snapshot không có/không APPROVED trong kho. **Không bao giờ chạy
trên kho giả.** Khi xong, lệnh in:

```
Warehouse backend: PostgreSQL
Warehouse source: host.docker.internal:5433/cdw
Snapshot: SNAP-20260630-01 (APPROVED)
Semantic version: 3.1.0
agents loaded: chart compare data insight orchestrator report
VDaAgent is up: http://localhost:8000  (UI and API)
```

### 4. Open

UI: http://localhost:8000
API: http://localhost:8000/api (header `X-User-Id: u_000000000001`)

Thử: chọn user **Alice** (thấy dự án 100 và 400), click agent **orchestrator**, gửi
`Vì sao căn MAS-U03832 bán chậm? So sánh với các căn tương đồng, vẽ biểu đồ và xuất báo cáo.`
Sau khoảng 1 phút: bảng B1…B5 "hoàn tất"; báo cáo nằm ở **Artifacts → Reports**.

#### Windows PowerShell

PowerShell chạy cùng Compose file và cùng các bước kiểm tra `.env`, warehouse, seed và health như Linux; không cần
GNU make hoặc WSL2. Windows cần Docker Desktop với Docker Compose v2 và Windows PowerShell (kể cả PowerShell 5.1):

```powershell
Copy-Item .env.example .env
.\dev.ps1 up
```

Mở `http://localhost:8000`. Nếu đặt `VDAGENT_PORT` trong `.env`, dùng cổng đó.

Raw Docker equivalent (orchestration only):

```powershell
docker compose -f docker-compose.yml up -d --build --wait backend
```

Lệnh raw này tự chạy `seed` và `warehouse-check` nhờ `depends_on`, rồi chờ backend healthy. Nó **không** chạy
`docker/check-env.sh` và không kiểm tra format DSN/giá trị rỗng; dùng `.\dev.ps1 up` làm quick start được khuyến nghị
để giữ preflight đó.

### Stop

```bash
make down
```

Windows PowerShell:

```powershell
.\dev.ps1 down
```

Raw equivalent:

```powershell
docker compose -f docker-compose.yml down
```

Dữ liệu ứng dụng (người dùng, hội thoại, artifact) giữ trong Docker volume có tên cố định `vdagent_real_var`.

### Logs

```bash
make logs
```

Trạng thái, restart và build nhanh:

```bash
make status
make restart
make build
```

Windows PowerShell tương đương:

```powershell
.\dev.ps1 status
.\dev.ps1 restart
.\dev.ps1 build
.\dev.ps1 logs
```

Raw commands:

```powershell
docker compose -f docker-compose.yml logs -f backend
docker compose -f docker-compose.yml ps
```

Reset toàn bộ dữ liệu trên Windows PowerShell 5.1 (chạy từng lệnh; không dùng `&&`):

```powershell
.\dev.ps1 down
docker volume rm vdagent_real_var
```

Linux reset:

```bash
make down
docker volume rm vdagent_real_var
```

`make status` / `.\dev.ps1 status` hiển thị health của backend. Healthcheck thật là `GET /api/users` (không có
route `/health`).

## Câu hỏi thử trên kho thật

Đã kiểm chứng 2026-10-01 trên `SNAP-20260630-01` / `3.1.0` (user **Alice**):

| Prompt | Plan | Kết quả |
|---|---|---|
| `Vì sao căn MAS-U03832 bán chậm? So sánh với các căn tương đồng, vẽ biểu đồ và xuất báo cáo.` | Data → [Insight ∥ Compare] → Chart → Report | 13 căn tương đồng; 53.449.321 so với 52.577.623 VND/m² (+1,66%); `SEVERE_PHYSICAL_DEFECT`, `LOW_SALES_INCENTIVE`; biểu đồ; báo cáo 6 phần |
| `Vì sao căn OCP-U00005 bán chậm? So sánh với các căn tương đồng, vẽ biểu đồ và xuất báo cáo.` | như trên | Insight `DEEP_FUNNEL_DROP_OFF`; Compare chỉ còn 1 căn cùng đợt mở bán nên báo **không đủ dữ liệu so sánh** (đúng luật, không bịa nhóm) |

Plan do LLM lập nằm trong log: `make logs | grep "llm plan accepted"`.

## Các mode khác

| Mode | Lệnh | URL | Dùng khi |
|---|---|---|---|
| **Kho giả** (dữ liệu tổng hợp, căn `A12-08`; không cần key, planner deterministic) | `make mock-up` / `make mock-down` | http://localhost:8001 | test, phát triển offline; **không** phải sản phẩm |
| Bộ acceptance trên kho giả (stack mới, tách biệt) | `acceptance/ws7/run.sh` (đặt `WS7_BROWSER_PYTHON` là Python có Playwright) | cổng 8021 | regression |
| Bộ test trong Docker | `make docker-test` | — | không cần mạng, không cần key |
| Chạy local không dùng Docker | `uv sync`, `make reset-db`, `make backend`, rồi `cd frontend && npm install && npm run dev` | :8000 / :5173 | phát triển; bắt buộc đặt `VDAGENT_RE_WAREHOUSE_DB` (DSN kho thật trong `.env`, hoặc `./var/re_warehouse.db` cho kho giả), thiếu thì Backend không khởi động; xem [agents/data/README.md](agents/data/README.md) |

Golden case trên kho giả (căn `A12-08`) và trên kho thật: [docs/testing/e2e-golden.md](docs/testing/e2e-golden.md).

Test trên máy: `uv sync && uv run pytest -q -p no:cacheprovider`. Test frontend: `cd frontend && npm test`.

## Xử lý sự cố

| Triệu chứng | Cách xử lý |
|---|---|
| `MISSING .env` / `EMPTY .env: <KEY>` | `cp .env.example .env`, điền đúng biến được nêu, rồi `make up` lại. |
| `ERROR: Real warehouse is required. Set VDAGENT_RE_WAREHOUSE_DB in .env.` | Điền DSN PostgreSQL của kho thật. Kho giả chỉ chạy bằng `make mock-up`. |
| `points at 127.0.0.1/localhost` | Trong Docker đó là chính container. Dùng `host.docker.internal` (PostgreSQL trên máy bạn) hoặc host thật. |
| `ERROR: cannot reach the warehouse at …` | Sai host/cổng/mật khẩu, hoặc PostgreSQL chưa mở cổng cho Docker (vd thêm `-p 172.17.0.1:5433:5432`). |
| `ERROR: snapshot … is not in the warehouse` / `not APPROVED` / `semantic version` | Sửa `ORCH_SNAPSHOT_ID` / `ORCH_SEMANTIC_VERSION` trong `.env` theo danh sách thông báo in ra. |
| `MISSING agents: …` | Một plugin không load. Xem `make logs \| grep failed`. |
| `port is already allocated` | Cổng 8000 đang bận. Đặt `VDAGENT_PORT=8010` trong `.env`, rồi `make up`. |
| `Không hoàn thành: LLM_PLAN_…` | Plan của LLM bị bước kiểm tra từ chối, nên chưa có gì chạy. Xem `make logs \| grep "llm plan rejected"`. Gửi lại. |
| `UNIT_NOT_FOUND` | Mã căn không thuộc phạm vi của user (Alice: dự án 100, 400; Bob: 200). |
| Gửi xong không thấy task nào | Chưa chọn user. Chọn Alice. |

## Cần biết trước khi demo

- Mỗi dataset ghi rõ nguồn trong `snapshot.warehouse` (`backend: postgresql`, host, database), và nhãn dữ liệu
  (`SNAPSHOT_STATUS_ASSUMED` cho kho thật, `SYNTHETIC_SOURCE` cho kho giả) suy ra từ nguồn thật, không từ cấu hình.
- Kho thật không có cột trạng thái duyệt snapshot: lớp view `re` ghi `APPROVED`, nên kết quả luôn kèm
  `SNAPSHOT_STATUS_ASSUMED`. Một số cột (`discount_pct`, `asking_price_per_m2`, …) bị lớp view che nên báo thiếu
  (xem [agents/data/README.md](agents/data/README.md#giới-hạn-đã-biết)).
- Luật chọn căn tương đồng của Compare (cùng loại căn, cùng đợt mở bán, diện tích ±10%, cùng nhóm hướng) chưa được
  nghiệp vụ duyệt (**B-11**); nhóm nhỏ hơn mức tối thiểu thì Compare báo không đủ dữ liệu.
- Metric thiếu được báo là không có dữ liệu, không bao giờ là 0. Các phát hiện là tương quan, không phải nguyên nhân.
- **Chưa sẵn sàng production.** Danh tính người dùng chỉ là header demo `X-User-Id` (F-05, BLOCKED); xem
  [docs/security/auth-design.md](docs/security/auth-design.md).

## Tham chiếu cho developer

- Tài liệu SDK và MCP tool cho người viết agent: `make sdk-docs` (build vào `docs/sdk/`, đã gitignore) hoặc
  `make sdk-docs-serve` rồi mở http://127.0.0.1:8080.
- Plugin nằm trong `backend/config.yaml` (trong Docker là `backend/config.compose.yaml`); mỗi plugin export
  `setup(api, opts)` và chỉ phụ thuộc `vdagent_sdk` (`sdk/`). Plugin load lỗi được log `plugin <module> failed: …` và bị
  bỏ qua.
- **Quyền MCP tool** cấp theo từng plugin bằng `mcp_tools: [...]` trong config; plugin không có `mcp_tools` không thấy
  tool nào. Quyền ghi artifact theo loại vẫn do Backend kiểm (mỗi agent chỉ ghi loại của mình).
- Một lượt chạy báo từng bước qua `ctx`: `emit_assistant`, rồi đúng một kết quả cho mỗi tool call
  (`emit_tool_result`; với `send_to_agent` thì `call_agent` trước), và kết thúc bằng một bước không có tool call (câu
  trả lời). Sai thứ tự → Backend đánh lượt đó `contract violation: …`.
- Plugin dùng chung tiến trình và event loop: không được block loop, không ghi `os.environ`, và giữ trạng thái theo user
  trong `ctx.memory` (FTS5 + sqlite-vec trong `backend.db`), không lưu trên object của agent.
- Thêm agent: copy `agents/_template` thành `agents/<name>` (đổi `agent_template/` thành `vdagent_<name>/`); thêm vào
  `[tool.uv.workspace].members`, `[tool.basedpyright].extraPaths`, `dependencies` và `[tool.uv.sources]` của
  `pyproject.toml` gốc rồi `uv sync`; liệt kê `- module: vdagent_<name>` kèm `mcp_tools` trong cả hai file config; với
  Docker thì copy `pyproject.toml` của nó trong `Dockerfile.python`; biến môi trường của nó đặt trong `.env` gốc.
- Backend (kiến trúc mới từ `main`): `runtime/` (engine), `http/` (REST + SSE), `mcp/` (`catalog.py` + `handlers.py`),
  `persistence/` (SQLAlchemy Core + Alembic), `artifacts/`, `conversations/`. Contract (`StepSpec@1`, `AgentReport@1`,
  envelope, catalog) nằm trong `contracts/vdagent_contracts/`.
- Override của Backend (`backend/.env`, tuỳ chọn): `VDAGENT_<KEY>` cho mọi khoá vô hướng của config, vd
  `VDAGENT_BACKEND_DB`, `VDAGENT_RE_WAREHOUSE_DB`, `VDAGENT_MCP_PUBLIC_URL`, `VDAGENT_MAX_STEPS`, và `VDAGENT_CONFIG`.
- Hợp đồng plugin/SDK: docstring của `sdk/vdagent_sdk` (`make sdk-docs`). Đặc tả thiết kế có ngày, kế hoạch tích hợp
  2026-09-30 và bằng chứng (lịch sử): [docs/archive/](docs/archive/README.md).
