# Demo runbook: 4 Happy Cases with `ORCH_LLM=on`

> **Lịch sử (2026-09-30), trên kho giả.** Các case dưới đây dùng căn `A12-08` của kho giả SQLite. Từ 2026-10-01,
> `make up` chạy trên **kho thật** (PostgreSQL, `SNAP-20260630-01`), nơi không có căn `A12-08`; câu hỏi thử trên kho thật
> nằm trong README gốc ("Câu hỏi thử trên kho thật"). Kho giả chỉ còn chạy bằng `make mock-up` (cổng 8001, planner
> deterministic, không LLM), nên các lệnh `make up`/cổng 8000 bên dưới không còn tái hiện đúng các case này.

### Start live demo
```bash
make up
```
Sau đó mở **http://localhost:8000**, chọn User **Alice**, click agent **orchestrator** và dán prompt.

- Giao diện và API chạy chung một cổng 8000.
- Lệnh trên tự build image, seed dữ liệu vào volume riêng `vdagent_var`, đợi container `healthy`, rồi in trạng thái (không in key).

Kiểm chứng ngày 2026-09-30 trên branch `agent_a/debug`:
- Cả 4 HC chạy live với Orchestrator LLM planner (OpenAI `gpt-4o-mini`).
- Plan do LLM tạo đều được code chấp nhận; không có lần từ chối hay chạy lại nào.
- Nguồn chuẩn: [AGENTS.md](../../../AGENTS.md) §19–§21.
- Bằng chứng: [demo_live_evidence/](demo_live_evidence/).

---

## 1. Trước khi chạy: env

Một file `.env` ở thư mục gốc (`cp .env.example .env`):

| Biến | Bắt buộc | Ghi chú |
|---|---|---|
| `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `LLM_MODEL` | có | Planner, đã kiểm chứng với `gpt-4o-mini`; Orchestrator, Data, Report không load nếu thiếu |
| `GEMINI_API_KEY` | không | Insight dùng Gemini trước nếu có; không có thì dùng OpenAI `gpt-6-luna` |

Những biến sau **không đặt trong `.env`**. Service `backend` trong `docker-compose.yml` tự đặt:
- `ORCH_LLM=on`
- `ORCH_SNAPSHOT_ID=SNAP-2026-09-28`
- `ORCH_SEMANTIC_VERSION=sc-1`
- `ORCH_DAG_TIMEOUT_S=300`

```bash
bash docker/check-env.sh   # chỉ in tên biến thiếu, không in giá trị; make up cũng chạy bước này
```

## 2. Các lệnh live (đều là target thật trong `Makefile`)

| Việc | Lệnh |
|---|---|
| Start (build, seed, đợi healthy, in trạng thái) | `make up` |
| Xem log | `make logs` |
| Chỉ xem bằng chứng LLM | `docker compose -f docker-compose.yml logs backend \| grep -E "llm plan\|INSIGHT_LLM_CALLED"` |
| Dừng (giữ dữ liệu) | `make down` |
| Xoá sạch (container và volume `vdagent_var`) | `make down && docker volume rm vdagent_var` |

`make up` kết thúc bằng (đã kiểm chứng 2026-10-01):
```
agents loaded: chart compare data insight orchestrator report
VDaAgent is up: http://localhost:8000  (UI and API)
```
Log khởi động (`make logs`) có dòng `orchestrator: LLM planner on (model gpt-4o-mini), snapshot SNAP-2026-09-28, semantic sc-1`.

> **Vì sao trước đây gặp `SNAPSHOT_REQUIRED`:**
> - `docker compose -f docker-compose.yml -f docker/compose.demo-live.yml up -d` không có `--profile offline` và không ghi tên service. Compose vì vậy khởi động service mặc định `backend`: stack dev, cổng 8000, không có biến `ORCH_*`, container `team_6_cai-backend-1`.
> - Override khi đó chỉ sửa `backend-offline`, nên không được áp dụng.
> - Đã sửa (2026-10-01): service mặc định `backend` giờ chính là stack live (`ORCH_LLM=on` + pin snapshot/semantic), khởi động bằng `make up` trên cổng 8000; profile `live` và cổng 8022 đã bỏ.

---

## 3. Bốn Happy Case (tất cả chạy với LLM ON)

Luồng chung:
1. **LLM** đọc câu hỏi và trả về JSON: `intent` và các bước (agent, operation, depends_on).
2. **Code** kiểm tra: schema chặt, catalog, dependency và cycle, luật vai trò, các bước bắt buộc, mã căn phải có trong câu hỏi.
3. Code tự gắn spec cùng pin snapshot/semantic.
4. **DAG executor** chạy plan.

Plan sai bị từ chối và không agent nào được gọi (`Không hoàn thành: LLM_PLAN_…`).

Canonical facts dùng chung:
- `SNAP-2026-09-28` / `sc-1`.
- DOM **138** so với trung vị **61** ngày.
- Đơn giá net **72.500.000** so với **64.500.000** VND/m², chênh **12,40%**.
- **5 căn tương đồng**: A12-11, A10-02, A14-03, B09-05, B11-07.
- **B-11** hiển thị.
- `discount_pct` và `inquiry_leads_30d` được báo là **không có dữ liệu**, không phải 0.

Kết quả live đã kiểm chứng:

| HC | Plan do LLM tạo | Waves | Task | Thời gian | Kết quả |
|---|---|---|---|---|---|
| HC1 | B1 data · B2 insight[B1] | `[[B1],[B2]]` | `t_e63bab30046c` | planner 2,3 s, tổng 6,6 s | 3 invocation completed |
| HC2 | B1 data · B2 compare[B1] | `[[B1],[B2]]` | `t_4a34aa062d3c` | planner 1,9 s, tổng 9,6 s | 3 invocation completed |
| HC3 | B1 data · B2 insight[B1] · B3 compare[B1] · B4 chart[B2,B3] | `[[B1],[B2,B3],[B4]]` | `t_455796e1e19d` | planner 3,0 s, tổng 18,7 s | 5 invocation, **5 biểu đồ**, B2/B3 bắt đầu cùng lúc |
| HC4 | B1 data · B2 insight[B1] · B3 compare[B1] · B4 chart[B2,B3] · B5 report[B2,B3,B4] | `[[B1],[B2,B3],[B4],[B5]]` | `t_2fa1d728cded` | planner 3,1 s, tổng 24,8 s | 6 invocation; trình duyệt 5/5 SVG, 0 console; lineage 7/7 |

Thời gian chủ yếu nằm ở hai lần gọi LLM (planner và Insight). Các bước deterministic chỉ mất dưới 1 s.

### HC-1: Explain / Root cause

**Tôi nói gì**
```
Vì sao căn A12-08 bán chậm?
```

- **Hệ thống chạy gì:** LLM lập plan `B1 data.fetch_units → B2 insight.explain_unit`. Insight diễn đạt bằng LLM.
- **Agent dự kiến:** orchestrator, data, insight. Waves: `[[B1],[B2]]`.

**Tôi cần nhìn gì**
1. Dòng đầu: `Phân tích căn A12-08 @ SNAP-2026-09-28 / sc-1`.
2. `OVERPRICED_VS_PEER: Căn A12-08 đã tồn 138 ngày; yếu tố có khả năng liên quan là giá cao hơn nhóm tương đồng … +12,4%` kèm `[art_…]`.
3. Bảng chỉ có B1, B2, "hoàn tất". Tab **Task**: orchestrator → data → insight.
4. `Hạn chế`: `METRIC_UNAVAILABLE:discount_pct`, `WINDOW_INCOMPLETE:inquiry_leads_30d:3`.

**Tôi cần nói gì (~25 s)**
> "Tôi hỏi bằng câu tự nhiên. AI của Orchestrator hiểu đây là câu hỏi 'vì sao' cho một căn cụ thể, nên lập kế hoạch 2 bước: lấy dữ liệu rồi giải thích. Kế hoạch được code kiểm tra trước khi chạy. Kết quả: căn này đã tồn 138 ngày, và yếu tố **có khả năng liên quan** là giá cao hơn nhóm tương đồng 12,4%. Số nào cũng có mã nguồn đi kèm; dữ liệu thiếu thì được ghi là thiếu, không bịa."

**PASS khi**
- [ ] B1 và B2 "hoàn tất"; có 138 ngày và +12,4% kèm `[art_…]`.
- [ ] Câu chữ mang tính liên quan, không khẳng định nhân quả.
- [ ] Log có `llm plan accepted` với `"wants": ["explain"]`.

**Nếu lỗi thì kiểm tra gì**
```bash
make up                                      # in lại 6 agent đã load
docker compose -f docker-compose.yml logs backend | grep -E "llm plan (accepted|rejected)" | tail -3
curl -s -H 'X-User-Id: u_000000000001' http://localhost:8000/api/tasks | head -c 500
```

### HC-2: Compare

**Tôi nói gì**
```
So sánh căn A12-08 với các căn tương đồng và chỉ ra những khác biệt đáng chú ý.
```

- **Hệ thống chạy gì:** LLM lập plan `B1 data.fetch_units → B2 compare.compare_to_peers`. Compare là deterministic.
- **Agent dự kiến:** orchestrator, data, compare. Waves: `[[B1],[B2]]`.

**Tôi cần nhìn gì**
1. `net_asking_price_per_m2: 72.500.000 VND/m² so với trung vị 64.500.000 … (chênh 12,40%)`.
2. `dom: 138 ngày so với trung vị 61 ngày … (chênh 126,23%)`.
3. `Nhóm tương đồng … 5 căn (A12-11, A10-02, A14-03, B09-05, B11-07). Tập 7 căn golden chưa có luật được duyệt (B-11).`
4. `Hạn chế`: `BLOCKED:B-2_min_peer_count`.

**Tôi cần nói gì (~25 s)**
> "Giờ tôi yêu cầu so sánh. AI chọn đúng agent Compare. Compare lấy 5 căn cùng loại, cùng đợt mở bán và cùng nhóm tầng làm nhóm tương đồng. A12-08 đắt hơn trung vị 12,4% mỗi mét vuông và tồn 138 ngày so với 61. Hệ thống tự ghi rõ một giới hạn: bộ 7 căn chuẩn của nghiệp vụ chưa có luật chọn được duyệt (B-11), nên hiện đang dùng 5 căn."

**PASS khi**
- [ ] Đúng 5 peers và dòng B-11 hiển thị.
- [ ] Các giá trị 72.500.000 / 64.500.000 / 12,40% / 138 / 61 đều đúng; không có PRJ-Y hay D12-09.

**Nếu lỗi thì kiểm tra gì**
```bash
docker compose -f docker-compose.yml logs backend | grep -E "llm plan|ERROR" | tail -5
curl -s -H 'X-User-Id: u_000000000001' http://localhost:8000/api/agents/orchestrator/messages | tail -c 1500
```

### HC-3: Visualization

**Tôi nói gì**
```
Phân tích căn A12-08 và cho tôi các biểu đồ quan trọng.
```

- **Hệ thống chạy gì:** LLM lập plan `B1 data → B2 insight ∥ B3 compare → B4 chart`, tạo **5 chart_spec**: 2 cột so với peer, 1 scatter, 2 KPI.
- **Agent dự kiến:** orchestrator, data, insight, compare, chart. Waves: `[[B1],[B2,B3],[B4]]`.
- **Đã sửa:** lần trước LLM bỏ Compare nên chỉ có 2 KPI. Giờ planner áp dụng cùng một luật cho cả chế độ deterministic lẫn LLM (`planner.normalize_wants`): *yêu cầu biểu đồ hoặc báo cáo mà không nói rõ cần phân tích gì thì phải có **cả** Insight và Compare*, vì Chart vẽ KPI từ Insight và biểu đồ so với peer từ Compare. Prompt nêu luật này, và code **từ chối** plan thiếu (`LLM_PLAN_MISSING_STEP`). Luật này áp theo ngữ nghĩa, không hardcode câu cụ thể. Nếu câu hỏi nói rõ chỉ một phân tích (vd "so sánh … và vẽ biểu đồ"), plan một nhánh vẫn hợp lệ.

**Lưu ý về UI:**
- Chat chỉ liệt kê id biểu đồ `art_…`, và các id này không click được, vì UI chỉ tạo link cho `ds_/ch_/rp_`.
- Biểu đồ **chỉ render khi được nhúng trong báo cáo**, nên phần 5/5 biểu đồ trên trình duyệt được trình diễn ở HC4.
- Ở HC3, chứng minh "biểu đồ lấy số thật" bằng API:
```bash
curl -s -H 'X-User-Id: u_000000000001' http://localhost:8000/api/chart-specs/<art_id>/1 | python3 -m json.tool | grep -E '"\$schema"|"type"|"value_exact"|"source_ref"' | head -12
```
Kết quả mong đợi:
- `vega-lite/v6.json`;
- mark hợp lệ (`bar`, `point` hoặc `text`);
- `value_exact` là `"138"`, `"61"`, `"72500000"`… đi kèm `source_ref` dạng `art_…@1#/…`.

**Tôi cần nhìn gì**
1. Dòng `Biểu đồ:` có **5** id; B4 `chart.draw_chart` "hoàn tất".
2. Tab **Task**: insight và compare chạy song song trước chart.
3. JSON chart_spec: Vega-Lite v6, có `bindings` và `source_ref`.

**Tôi cần nói gì (~25 s)**
> "Tôi xin các biểu đồ quan trọng. AI hiểu rằng muốn có biểu đồ so sánh thì phải chạy cả phân tích lẫn so sánh trước, nên lập kế hoạch 4 bước, trong đó hai phân tích chạy song song. Agent Chart không tự tính số: mỗi điểm trên biểu đồ gắn với đúng ô dữ liệu gốc qua `source_ref`. Lát nữa các biểu đồ này sẽ hiện trực tiếp trong báo cáo."

**PASS khi**
- [ ] Waves là `[[B1],[B2,B3],[B4]]`; có 5 id biểu đồ.
- [ ] chart_spec là Vega-Lite v6 và có `source_ref`; giá trị khớp HC2.

**Nếu lỗi thì kiểm tra gì**
```bash
docker compose -f docker-compose.yml logs backend | grep -E "llm plan (accepted|rejected)" | tail -2   # rejected → code của lỗi + reply LLM
docker compose -f docker-compose.yml logs backend | grep -iE "INVALID_VEGA_LITE|chart" | tail -5
```
Nếu plan bị từ chối với `LLM_PLAN_MISSING_STEP`, đó là hành vi an toàn: gửi lại prompt, hoặc dùng bản dự phòng (§5).

### HC-4: Full end-to-end report (case chính)

**Tôi nói gì**
```
Vì sao căn A12-08 bán chậm? So sánh với các căn tương đồng, vẽ biểu đồ và xuất báo cáo.
```

- **Hệ thống chạy gì:** User → **Orchestrator LLM planner** → plan có cấu trúc → code kiểm tra → DAG: `B1 data → B2 insight ∥ B3 compare → B4 chart → B5 report`.
- **Agent dự kiến:** cả 6. Waves: `[[B1],[B2,B3],[B4],[B5]]`.

**Tôi cần nhìn gì**
1. Bảng có B1…B5 đều "hoàn tất", và dòng `Báo cáo đã lưu: art_…`.
2. Tab **Task**: 6 invocation; insight và compare bắt đầu cùng lúc.
3. Tab **Artifacts** → REPORTS → **"Báo cáo căn A12-08 @ SNAP-2026-09-28"**. Báo cáo có 6 section:
   1. Bối cảnh
   2. Tóm tắt điều hành
   3. Chỉ số chính
   4. Phân tích & Insight
   5. Bằng chứng & Trực quan hóa
   6. Hạn chế & Chất lượng dữ liệu
4. **5 biểu đồ render**. Số liệu có trích dẫn `[S1]`, `[S2]`…; không có chuỗi `{{chart_spec:…}}`.
5. Terminal: `docker compose -f docker-compose.yml logs backend | grep "llm plan accepted" | tail -1` in ra plan do LLM tạo (`model`, `latency_ms`, `llm_plan`).

**Tôi cần nói gì (~30 s)**
> "Đây là câu hỏi đầy đủ. AI của Orchestrator hiểu 4 yêu cầu (giải thích, so sánh, biểu đồ, báo cáo) và lập kế hoạch 5 bước. Code kiểm tra kế hoạch đó, nên AI không thể gọi bừa agent hay tự chọn dữ liệu. Insight và Compare chạy song song, Chart vẽ từ kết quả của cả hai, Report gom tất cả thành báo cáo 6 phần. Mọi con số đều có trích dẫn về dữ liệu gốc và giống hệt bản chạy không dùng AI: AI chỉ lập kế hoạch và diễn đạt, không đổi số."

**PASS khi**
- [ ] 6 agent "hoàn tất"; waves là `[[B1],[B2,B3],[B4],[B5]]`.
- [ ] Các giá trị SNAP-2026-09-28 / sc-1 / 138 vs 61 / 72.500.000 vs 64.500.000 / 12,40% / 5 peers / B-11 đều đúng.
- [ ] Báo cáo đủ 6 section, 5/5 biểu đồ render, không có token thô, không có PRJ-Y hay D12-09.
- [ ] `discount_pct` và `inquiry_leads_30d` nằm trong phần hạn chế, không phải 0.

**Nếu lỗi thì kiểm tra gì**
```bash
docker compose -f docker-compose.yml logs backend | grep -E "llm plan (accepted|rejected)" | tail -1
curl -s -H 'X-User-Id: u_000000000001' http://localhost:8000/api/reports
curl -s -H 'X-User-Id: u_000000000001' http://localhost:8000/api/tasks | head -c 400
```

---

## 4. Checklist 5 phút trước demo

```bash
make up                                        # healthy + "agents loaded: chart compare data insight orchestrator report"
make logs | grep "LLM planner on"              # ORCH_LLM=on, snapshot SNAP-2026-09-28, semantic sc-1
```
- [ ] Muốn danh sách Tasks trống: `make down && docker volume rm vdagent_var && make up`.
- [ ] Mở `http://localhost:8000` bằng cửa sổ ẩn danh (tránh bundle JS cũ), thấy 6 agent, User = Alice.
- [ ] Chạy thử HC1 một lần. Log phải có `llm plan accepted`.
- [ ] Mạng ra ngoài tới `api.openai.com` hoạt động (LLM là phụ thuộc runtime).
- [ ] (Tuỳ chọn, ~2 phút) Baseline offline: `WS7_BROWSER_PYTHON=<python có playwright> acceptance/ws7/run.sh`, phải in `WS7 acceptance: PASS`. Lệnh này dùng cổng 8021 riêng.

## 5. Dự phòng: offline, deterministic (chỉ khi live gặp sự cố)

Chỉ dùng cho **fallback, regression, hoặc demo khẩn cấp** (khi mất mạng hoặc LLM lỗi). Cùng plan và cùng số liệu, nhưng plan do code lập, không có LLM.
```bash
make mock-up                                # http://localhost:8001 (ORCH_LLM=off, không cần key)
curl -s -H 'X-User-Id: u_000000000001' http://localhost:8001/api/agents
make mock-down                                  # rồi docker volume rm vdagent_offline_var nếu muốn xoá dữ liệu
```

## 6. Timeline demo 5 phút

| Thời gian | Case | Câu chuyện |
|---|---|---|
| 0:00–1:00 | HC1 | **Câu hỏi → Bằng chứng**: AI lập plan 2 bước; 138 ngày; liên quan giá +12,4% |
| 1:00–2:00 | HC2 | **So sánh**: AI chọn Compare; 5 căn tương đồng; trung vị 61 ngày và 64,5 triệu/m²; nói rõ B-11 |
| 2:00–3:00 | HC3 | **Trực quan hoá**: AI tự thêm Compare vì cần biểu đồ so sánh; 5 biểu đồ; `source_ref` |
| 3:00–5:00 | HC4 | **Báo cáo đầy đủ**: xem plan 5 bước trong log → 6 agent → mở báo cáo, lướt 6 section, 5 biểu đồ, trích dẫn |

## 7. Troubleshooting

| Triệu chứng | Nguyên nhân / xử lý |
|---|---|
| `SNAPSHOT_REQUIRED — no snapshot configured` | Container đang chạy được tạo từ cấu hình cũ. Chạy `make up` để tạo lại. |
| `port is already allocated` (8000) | Cổng đang bận. Đặt `VDAGENT_PORT=8010` trong `.env` rồi `make up`, hoặc tìm stack cũ bằng `docker ps --format '{{.Names}} {{.Ports}}'`. |
| `Không hoàn thành: LLM_PLAN_*` | Plan của LLM bị code từ chối (an toàn, không agent nào chạy). Xem `make logs \| grep "llm plan rejected"` để biết mã lỗi và câu trả lời của LLM. Gửi lại, hoặc dùng §5. |
| `Không hoàn thành: LLM_PLAN_UNAVAILABLE` | LLM timeout hoặc mất mạng. Kiểm tra mạng và key; nếu cần thì dùng §5. |
| Plugin failed khi start | `make logs \| grep failed`. Thường do thiếu biến bắt buộc trong `.env` gốc. |
| UI không có Tasks sau khi gửi | Chưa chọn User. Chọn Alice. |
| Biểu đồ không hiện trong báo cáo | `make logs \| grep INVALID_VEGA_LITE`; mở console của trình duyệt. |

## 8. Những điều KHÔNG được nói

- **Không** nói bộ 7 peer golden đã được giải quyết. Compare dùng **5 peers**; **B-11 BLOCKED**.
- **Không** nói hệ thống production-ready. **F-05** (xác thực) BLOCKED; header `X-User-Id` chỉ dành cho demo.
- **Không** nói cả 6 agent đều gọi LLM. Chỉ **Orchestrator** (lập plan) và **Insight** (diễn đạt) gọi LLM. Data, Compare, Chart và Report là deterministic.
- **Không** nói Gemini đã được kiểm chứng: Insight chạy trên OpenAI.
- **Không** nói Report LangGraph/Jev live đã được kiểm chứng. Báo cáo là bản deterministic, có kiểm tra bằng chứng.
- **Không** biến tương quan thành nhân quả. Hãy nói "yếu tố **có khả năng liên quan**".
- **Không** nói thiếu dữ liệu nghĩa là bằng 0 (`discount_pct`, `inquiry_leads_30d`).
- Các blocker còn mở: B-2, D2b, B-3, B-12. Mode live chỉ được kiểm chứng với đúng 4 prompt trên; cách hỏi khác là **NOT VERIFIED**, và LLM có thể lập plan khác (plan sai sẽ bị từ chối, không chạy sai).

## 9. Cleanup

```bash
make down                                   # dừng, giữ dữ liệu
make down && docker volume rm vdagent_var   # xoá container và volume vdagent_var
make mock-down && docker volume rm vdagent_offline_var   # nếu đã dùng kho giả
```
Các lệnh này chỉ đụng tới stack `backend` / `backend-offline` của project này.
