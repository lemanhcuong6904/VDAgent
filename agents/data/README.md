# Data agent

Agent duy nhất được đọc kho dữ liệu bất động sản (DW). Nó chạy trong process của Backend (plugin `vdagent_data`), nhận việc từ
Orchestrator, lấy dữ liệu có kiểm chứng và ghi lại thành artifact (`dataset`, `metric`, `dq`). Sau khi lấy xong, người dùng có thể hỏi tiếp
về chính dữ liệu vừa lấy ngay trong khung chat của Data.

Tài liệu này hướng dẫn **dựng và chạy Data agent trên DW thật** (Postgres của team DATA). Muốn chạy nhanh trên kho giả (SQLite) thì xem
[Chạy nhanh trên kho giả](#chạy-nhanh-trên-kho-giả).

## Data agent làm gì

| Tin nhắn đến | Đi đâu | Kết quả |
|---|---|---|
| JSON contract Orchestrator ↔ Agent v1.0 (`DISPATCH`, `ANSWER`, `START`, `CANCEL`, `STATUS_QUERY`) | pipeline v1.0 (`wire.py` → `v1.py`) | tin `REPORT` (DONE, ERROR hoặc QUESTION) |
| JSON `StepSpec@1` (Orchestrator hiện đang gửi dạng này) | pipeline cũ (`steps.py`) | `AgentReport@1` |
| Câu tự do do **người dùng** gõ trực tiếp cho Data | chat giải thích (`chat/`), cần LLM | câu trả lời về gói dữ liệu mới nhất của người dùng |
| Câu tự do từ **agent khác** | vòng LLM cũ trên kho retail (chế độ debug của Orchestrator) | không thuộc luồng chính |

- **Pipeline** là tất định, không dùng LLM: khóa kỳ chốt (snapshot), nhận diện đối tượng, đọc DW trong phạm vi quyền của người dùng, kiểm tra chất lượng,
  ghi artifact. Phạm vi quyền luôn lấy từ Backend, không lấy từ tin nhắn.
- **Lời kể** (narration): Data kể từng bước làm bằng ngôn ngữ tự nhiên trong khung chat. Dùng LLM nếu có, không thì dùng câu khuôn.
- **Chat giải thích**: trả lời "vì sao lấy căn này", "giá trị nào còn thiếu", "nguồn ở đâu", "thuật ngữ này là gì". Chỉ mô tả dữ liệu, không kết luận nguyên nhân
  (việc của Insight và Compare). Mọi số và mã trong câu trả lời phải có trong dữ liệu đã lấy, nếu không câu trả lời bị từ chối.

## Chạy trên DW thật

Có 3 mảnh: **Postgres** (container Docker, chứa DW `gold` và lớp view `re`), **Backend** (uvicorn, chạy cả 6 agent và phục vụ giao diện web), **trình duyệt**.

Lệnh dưới chạy trong **Git Bash** (Windows) hoặc bash (macOS, Linux), đứng ở thư mục gốc repo. Làm tuần tự; mỗi bước có dòng **Kiểm tra**, chưa đúng thì dừng.

> Cách chính thức: dựng DW (bước 1–2), điền DSN vào `.env` ở thư mục gốc rồi `make up` (xem README gốc, "Quick Start");
> các bước 3–9 dưới đây chạy Backend trực tiếp trên máy thay vì Docker. `make backend` không đặt DSN và `make mock-up`
> luôn dùng kho giả.

### 0. Cần có

| Công cụ | Kiểm tra | Ghi chú |
|---|---|---|
| Docker | `docker ps` chạy được | Windows, macOS: bật Docker Desktop trước |
| `uv` | `uv --version` | Python 3.12 do `uv` tự quản lý |
| Node 20 trở lên (đã thử Node 22) | `node --version` | chỉ để build giao diện |
| Khóa LLM tương thích OpenAI, có tool calling | | cho chat và lời kể bằng LLM; không có thì xem bước 4 |

```bash
uv sync
```

### 1. Dựng Postgres và nạp DW (một lần)

Windows (Git Bash) cần thêm: `export MSYS_NO_PATHCONV=1` và dùng `$(pwd -W)` thay cho `$(pwd)` ở lệnh `docker run`.

```bash
docker run -d --name cdw-pg -e POSTGRES_PASSWORD=cdw -e POSTGRES_DB=cdw -p 127.0.0.1:5433:5432 -p 172.17.0.1:5433:5432 \
  -v "$(pwd)/warehouse/backup:/backup:ro" -v "$(pwd)/docker/warehouse:/views:ro" postgres:16
```

Đợi Postgres sẵn sàng (chạy lại đến khi thấy `accepting connections`, rồi đợi thêm vài giây cho lần khởi tạo xong):

```bash
docker exec cdw-pg pg_isready -U postgres -d cdw
docker exec cdw-pg pg_restore -U postgres -d cdw --no-owner /backup/cdw_gold_snapshot_20260630.dump
```

**Kiểm tra:** `docker exec cdw-pg psql -U postgres -d cdw -tAc "select count(*) from gold.dm_unit_friction_diagnostics"` in `5051`.

Container đã có từ trước (`docker ps -a --filter name=cdw-pg`) thì chỉ cần `docker start cdw-pg` và bỏ qua bước này và bước 2. Container này không có volume dữ liệu: `docker rm cdw-pg` là mất DW, phải nạp lại.
Cổng `127.0.0.1:5433` mở cho máy bạn, `172.17.0.1:5433` (cầu Docker, `ip -4 addr show docker0`) cho các container của
`make up`, không mở ra mạng ngoài; mật khẩu `cdw` của tài khoản admin chỉ dùng cục bộ.
Với `make up`, DSN trong `.env` gốc là `postgresql://vdagent_reader:<READER_PW>@host.docker.internal:5433/cdw`.

### 2. Tạo lớp view `re` và role chỉ đọc (một lần, chạy lại cũng an toàn)

Backend không đọc bảng `gold` trực tiếp. Nó đọc schema `re` (view có hình dạng chuẩn mà các agent hiểu) bằng role `vdagent_reader`, role này chỉ đọc `re`.
Tạo mật khẩu ngẫu nhiên và áp view bằng script của repo:

```bash
READER_PW="$(uv run python -c 'import secrets; print(secrets.token_hex(12))' | tr -d '\r\n')"
docker exec -e PGUSER=postgres -e PGDATABASE=cdw -e VDAGENT_READER_PASSWORD="$READER_PW" cdw-pg sh /views/apply-views.sh
```

**Kiểm tra:** in `apply-views: done (47713 units visible in schema re)`.

### 3. Lưu địa chỉ kết nối, ngoài repo

```bash
W="$HOME/vdagent-real"; mkdir -p "$W"
echo "postgresql://vdagent_reader:$READER_PW@127.0.0.1:5433/cdw" > "$W/dsn.txt"
```

Dùng `127.0.0.1`, **không dùng `localhost`**: trên Windows, `localhost` có thể phân giải sang IPv6 trong khi cổng chỉ mở ở `127.0.0.1`, và kết nối Postgres treo ngẫu nhiên.

File này chứa mật khẩu: **không commit, không dán vào chat**. Sang phiên terminal mới thì chỉ cần đặt lại `W="$HOME/vdagent-real"`, file vẫn còn.
Mất mật khẩu thì lặp lại bước 2 (đặt mật khẩu mới) rồi ghi lại file này.

### 4. Cấu hình agent Data

```bash
cp -n agents/data/.env.example agents/data/.env
```

Mở `agents/data/.env` (đã được gitignore) và điền:

```
OPENAI_API_KEY=<khóa của bạn>
OPENAI_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini
```

- Không cần đặt `DATA_DW_PROFILE`: nhãn dữ liệu suy ra từ kho mà Backend thật sự đọc (PostgreSQL → `SNAPSHOT_STATUS_ASSUMED`,
  SQLite → `SYNTHETIC_SOURCE`). Đặt sai thì bị bỏ qua và log ghi cảnh báo. Mỗi dataset ghi nguồn trong `snapshot.warehouse`.
- Không có khóa LLM: thêm `DATA_LLM=off`. Pipeline vẫn chạy, lời kể dùng câu khuôn, nhưng chat giải thích không dùng được.
- Các agent khác không cần `.env` khi chạy theo bước 7 (chúng được tắt LLM bằng biến môi trường).

### 5. Tạo cơ sở dữ liệu của Backend và người dùng thử

Backend dùng hai file SQLite riêng cho người dùng, phạm vi quyền và hội thoại. Tạo trong thư mục làm việc, không đụng `var/`:

```bash
export PYTHONUTF8=1 VDAGENT_SCOPE_PROFILE=real
uv run python data/seed_warehouse.py "$W/warehouse.db"
uv run python data/seed_users.py "$W/backend.db"
```

`VDAGENT_SCOPE_PROFILE=real` quyết định phạm vi: **Alice** (`u_000000000001`) thấy dự án 100 và 400, **Bob** (`u_000000000002`) thấy dự án 200.
Thiếu biến này phạm vi là bản demo (`PRJ-X`, `PRJ-Y`) và Alice không thấy căn nào của DW thật. Phạm vi chỉ được gán cho người dùng chưa có phạm vi:
nếu đã seed nhầm, xóa `"$W"/backend.db*` rồi làm lại.

**Kiểm tra:** in `scopes seeded for: u_000000000001, u_000000000002`.

### 6. Build giao diện (một lần, và khi `frontend/` đổi)

```bash
(cd frontend && npm ci && npm run build)
```

Backend phục vụ `frontend/dist` ở đường dẫn `/` (thư mục này không nằm trong git).

### 7. Chạy Backend

```bash
export PYTHONUTF8=1
export VDAGENT_BACKEND_DB="$W/backend.db" VDAGENT_WAREHOUSE_DB="$W/warehouse.db"
export VDAGENT_RE_WAREHOUSE_DB="$(cat "$W/dsn.txt")"
export ORCH_LLM=off ORCH_SNAPSHOT_ID=SNAP-20260630-01 ORCH_SEMANTIC_VERSION=3.1.0
export INSIGHT_LLM=off COMPARE_LLM=off REPORT_LLM=off
uv run uvicorn vdagent_backend.app:app --host 127.0.0.1 --port 8000
```

Đợi khoảng 15 giây. **Kết quả đúng:** log có 6 dòng `plugin vdagent_<tên> loaded` (orchestrator, data, compare, insight, report, chart) rồi `Uvicorn running on http://127.0.0.1:8000`.
Muốn chạy nền thay vì giữ cửa sổ: thêm `nohup ... > "$W/backend.log" 2>&1 &`. Đổi cổng thì phải đặt `VDAGENT_MCP_PUBLIC_URL=http://localhost:<cổng>/mcp` (mặc định trỏ cổng 8000).

| Biến | Vì sao |
|---|---|
| `VDAGENT_RE_WAREHOUSE_DB` | bắt đầu bằng `postgresql://` thì Backend đọc Postgres thật; để trống là kho giả |
| `ORCH_SNAPSHOT_ID`, `ORCH_SEMANTIC_VERSION` | Orchestrator bắt buộc ghim kỳ chốt; thiếu thì câu hỏi tự do bị từ chối `SNAPSHOT_REQUIRED`. Với DW thật là `SNAP-20260630-01` và `3.1.0` |
| `ORCH_LLM=off`, `INSIGHT_LLM=off`, `COMPARE_LLM=off`, `REPORT_LLM=off` | các agent này lập kế hoạch và viết bằng luật và mẫu, không cần khóa |
| không đặt `DATA_LLM` | để Data dùng LLM cho lời kể và chat |

**Kiểm tra:** `curl -s -H "X-User-Id: u_000000000001" http://127.0.0.1:8000/api/agents` in danh sách 6 agent.

### 8. Thử bằng giao diện

Mở http://127.0.0.1:8000.
1. Chọn người dùng **Alice**.
2. Bấm **orchestrator**, gửi: `Vì sao căn OCP-U00005 bán chậm? So sánh với các căn tương đồng và vẽ biểu đồ.` Chạy Data, rồi Insight và Compare, rồi Chart.
   Trạng thái `partial` là bình thường (xem [Giới hạn đã biết](#giới-hạn-đã-biết)).
3. Bấm **data**: thấy lời kể từng bước của Data. Ô nhập có gợi ý hỏi tiếp. Hỏi thử:
   - `Vì sao bạn lấy căn này, và vì sao gói có nhiều căn như vậy?`
   - `Căn này đã tồn bao lâu, giá bao nhiêu, và giá trị nào còn thiếu?`
   - `Nguồn dữ liệu là bảng nào, kỳ chốt nào?`
4. Muốn thử trực tiếp contract v1.0: dán một khối JSON trong [`DEMO_V1.md`](DEMO_V1.md) vào khung chat của Data (mã căn thật dạng `OCP-U…`, `SMC-U…`, `VGP-U…`, `MAS-U…`).

Khi chat bị từ chối ("Mình chưa thể trả lời câu này một cách chắc chắn…"), log của Backend có dòng `data chat: answer rejected, no source for [...]` nêu giá trị nào không có nguồn.

### 9. Tắt và bật lại

| Việc | Lệnh |
|---|---|
| Tắt Backend | `Ctrl+C` ở terminal đang chạy |
| Tắt Postgres | `docker stop cdw-pg` (dữ liệu vẫn còn) |
| Bật lại | `docker start cdw-pg`, rồi chạy lại bước 7 (nhớ `W="$HOME/vdagent-real"`) |
| Làm lại sạch phía app, giữ DW | xóa `"$W"/backend.db*`, chạy lại bước 5 và 7 |

## Chạy nhanh trên kho giả

Không cần Docker. Kho giả là SQLite sinh sẵn (căn `A12-08`, dự án `PRJ-X`).

```bash
uv sync
for a in orchestrator data compare insight report chart; do cp -n agents/$a/.env.example agents/$a/.env; done   # điền khóa LLM trong từng file
export PYTHONUTF8=1
uv run python data/seed_warehouse.py var/warehouse.db
uv run python data/seed_users.py var/backend.db
uv run python data/seed_re_warehouse.py var/re_warehouse.db
uv run uvicorn vdagent_backend.app:app --host 127.0.0.1 --port 8000     # http://127.0.0.1:8000
```

Ba lệnh seed và lệnh cuối chính là `make reset-db` và `make backend` (máy không có `make`, như Windows, thì dùng lệnh trên).
Backend mặc định đọc `var/backend.db`, `var/warehouse.db`, `var/re_warehouse.db` nên không cần đặt biến môi trường.
Nhãn "dữ liệu mô phỏng" tự bật vì Backend đọc SQLite. Biến môi trường đầy đủ của Backend: `backend/.env.example`.
Mã căn của kho giả: `A12-08` (thuộc `PRJ-X`, Alice thấy được).

## Cấu hình của Data (`agents/data/.env`)

Plugin tự đọc file này lúc Backend khởi động; giá trị trong file thắng biến môi trường của Backend. Thiếu biến bắt buộc thì plugin không nạp được
(log `plugin vdagent_data failed: …`) và Backend vẫn chạy nhưng thiếu agent này.

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `LLM_MODEL` | | bắt buộc nếu không đặt `DATA_LLM=off`; endpoint tương thích OpenAI có tool calling |
| `LLM_TIMEOUT_S` | 120 | giới hạn mỗi lần gọi LLM |
| `DATA_LLM` | bật | `off`: không dùng LLM (không cần 3 biến trên, không có chat, lời kể bằng câu khuôn) |
| `DATA_NARRATE` | `on` | `off`: Data chỉ trả một bước kết quả, không kể từng bước |
| `DATA_NARRATE_LLM` | `on` | `off`: lời kể chỉ dùng câu khuôn (LLM chỉ thấy tên bảng, số dòng, mã, không thấy giá trị dòng) |
| `DATA_DW_PROFILE` | không đặt | chỉ là kỳ vọng; nhãn luôn theo kho Backend trả về (`snapshot.warehouse`), lệch thì log cảnh báo |

## Kiểm thử

```bash
uv run pytest agents/data                                      # không cần Docker, chạy trên kho giả
```

Các test trên DW thật tự bỏ qua nếu thiếu `VDAGENT_TEST_PG_DSN`. Để chạy chúng, sau bước 1 và 2:

```bash
export VDAGENT_TEST_PG_DSN="$(cat "$HOME/vdagent-real/dsn.txt")"
uv run pytest agents/data/vdagent_data/tests/test_real_dw.py agents/data/vdagent_data/tests/test_trace_real_dw.py backend/tests/warehouse/test_re_pg.py
```

Test của các agent khác (chart, compare, insight, orchestrator, report) đang import fixture và helper từ `vdagent_data.tests` và `vdagent_data.steps`;
khi đổi tên hoặc chuyển các file này phải giữ đường import cũ.

## Bản đồ code (`vdagent_data/`)

| File | Việc |
|---|---|
| `agent.py`, `__init__.py`, `settings.py` | plugin và định tuyến tin nhắn; vòng LLM cũ cho kho retail |
| `wire.py`, `contract_v1.py` | cửa contract v1.0: mô hình tin, `Door`, mã lỗi, cảnh báo, `data_confidence` |
| `v1.py`, `vocab.py`, `resolve.py` | 4 operation (`fetch_units`, `aggregate_metrics`, `fetch_peer_candidates`, `fetch_unit_context`), từ vựng, nhận diện đối tượng |
| `steps.py` | pipeline cũ `StepSpec@1`, snapshot, cảm biến chất lượng; `v1.py` dùng chung phần lõi |
| `trace.py`, `narrate.py` | sự kiện theo giai đoạn và lời kể |
| `chat/` | chat giải thích: `packages.py` (nạp gói), `tools.py` (8 tool chỉ đọc), `glossary.py`, `loop.py` (vòng LLM có kiểm chứng số) |
| `prompts/` | `chat.md`, `narrator.md` (đang dùng); `system.md`, `compact.md` (vòng LLM cũ) |

## Giới hạn đã biết

- `discount_pct` thật là 0.00 trong DW nhưng Data khai là thiếu: lớp view `re` che cột này, cần owner Backend thêm cột vào `docker/warehouse/canonical_views.sql`.
  Tương tự `is_overdue_flag`, `asking_price_per_m2`, `subsidy_duration_mo`. Vì vậy các lần chạy thường kết thúc `partial`.
- `dw_peer_n` không có trong DW thật nên luôn khai thiếu.
- Kho thật không có cột trạng thái duyệt snapshot; lớp view ghi `APPROVED`, nên kết quả luôn kèm `SNAPSHOT_STATUS_ASSUMED` cho đến khi team DATA xác nhận.
- Gói do Orchestrator yêu cầu chứa căn được hỏi cùng các căn ứng viên cùng loại căn (vài trăm căn).
- Chat chỉ đọc gói mới nhất của người dùng, chưa tự lấy dữ liệu mới.
- Mất `cdw-pg` là mất DW trong Docker; nạp lại từ `warehouse/backup` theo bước 1.

## Gặp lỗi

| Triệu chứng | Nguyên nhân và cách sửa |
|---|---|
| `docker: error during connect` | Docker chưa chạy; mở Docker Desktop |
| `port is already allocated` ở bước 1 | cổng 5433 đang bị dùng; `docker ps -a`, nếu có `cdw-pg` cũ thì `docker start cdw-pg` |
| `apply-views: schema gold is missing` | chưa nạp dump (bước 1) |
| Log `plugin vdagent_data failed` | thiếu `agents/data/.env` hoặc thiếu khóa; điền bước 4 hoặc đặt `DATA_LLM=off` |
| Câu hỏi tự do báo `SNAPSHOT_REQUIRED` | thiếu `ORCH_SNAPSHOT_ID` hoặc `ORCH_SEMANTIC_VERSION` (bước 7) |
| Data báo `OUT_OF_SCOPE` cho mọi căn | seed thiếu `VDAGENT_SCOPE_PROFILE=real` (bước 5), hoặc đang chọn nhầm người dùng |
| Số liệu giống kho giả (căn `A12-08`, dự án `PRJ-X`) | Backend đang đọc kho giả: kiểm `VDAGENT_RE_WAREHOUSE_DB` bắt đầu bằng `postgresql://` và đã `export` trước khi chạy uvicorn |
| Data trả `DQ_BLOCKING` | không có kỳ chốt hợp lệ; kiểm lại bước 2 |
| Backend hoặc test treo khi đọc DW thật | DSN dùng `localhost`; đổi thành `127.0.0.1` (bước 3) |
| Chat luôn từ chối trả lời | xem dòng `data chat: answer rejected` trong log; kiểm LLM có gọi được (khóa, `LLM_MODEL`) |
| Giao diện trắng hoặc 404 ở `/` | chưa build giao diện (bước 6) |
| Lỗi mật khẩu `vdagent_reader` | lặp lại bước 2 với mật khẩu mới rồi ghi lại bước 3 |
| Lỗi mã hóa khi chạy test trên Windows | `export PYTHONUTF8=1` |
