# compare agent

Trả lời câu hỏi *"So với các căn thật sự tương đồng, căn này chênh bao nhiêu và đứng thứ mấy?"* —
nhóm căn tương đồng, so trực diện hai đối tượng, so theo nhóm (tầng, hướng, view, phân khu), xếp hạng.
Compare nói **khác bao nhiêu**; Insight nói **vì sao**. Spec đầy đủ: *Compare Agent — Spec v5.3*
(Drive của team Agent B).

## Cách agent làm việc

| Bước | Ai làm | File |
|---|---|---|
| Hiểu câu hỏi → kế hoạch so sánh (`ComparisonPlan`) | Mô hình `gpt-6-luna` (dự phòng `gpt-4o-mini`); code kiểm kế hoạch, **mã căn phải có trong câu hỏi** | `planner.py`, `prompts/plan.md` |
| Không có / lỗi mô hình, hoặc kế hoạch sai | Bộ phân tích câu theo quy tắc (tiếng Việt có / không dấu) | `vh_chat.parse_request` |
| Mọi con số: mốc chuẩn, chênh, hạng, đáng chú ý, mức đủ dữ liệu | Engine tất định (`Decimal`, ROUND_HALF_UP) | `vh_service.py`, `vh_peers.py`, `vh_math.py`, `vh_sufficiency.py` |
| Câu trả lời | Mô hình viết 2–4 câu; code kiểm **mọi số phải có trong kết quả**, cấm từ nhân quả / khuyến nghị, sai thì viết lại 1 lần rồi dùng câu mẫu. Bảng số luôn do engine in | `phrasing.py`, `prompts/phrase.md`, `vh_chat.render` |

MCP tools granted by `mcp_tools` in `backend/config.yaml`: `query_datasets`, `describe_dataset`, `get_dataset_rows`, `artifact_put` / `artifact_get` / `artifact_list` (writes
`peer_definition`, `comparison`), `get_user_context`;
plus `send_to_agent` to reach the other agents.

Mỗi lượt ghi một bước công cụ `run_comparison` (tham số = yêu cầu đã chuẩn hóa, kết quả = trạng thái,
mức đủ dữ liệu, `artifact_id`, `content_hash`) để truy vết. Tin nhắn là JSON (từ agent khác) thì
bỏ qua mô hình, chạy thẳng engine.

**3 mức đủ dữ liệu** (spec §2.4, cùng bậc với Insight): **Đầy đủ** ≥ 10 căn tương đồng, đủ dữ liệu ·
**Hạn chế** 5–9 căn / đã mở tầng liền kề / thiếu dữ liệu một phần → câu trả lời mở đầu bằng giới hạn ·
**Không đủ** < 5 căn → không đưa số, gợi ý cách hỏi khác (`suggestedNextSteps`).

**Nhóm tương đồng do Data chọn** (spec v5.3 §1.5): yêu cầu có `peerSet` (gói `fetch_peer_candidates`:
`unit_key`, `match_tier` strict/expanded/excluded) thì Compare dùng nguyên, chỉ kiểm bất biến; không có
thì engine tự lọc theo luật peer của team (chế độ dùng cho golden và demo).

## Dữ liệu

- Căn mẫu **A12-08** (hero case) đi kèm plugin: `vdagent_compare/fixtures/hero_a12_08.json`.
- Đường production (`StepSpec@1` `compare_to_peers`) chỉ đọc artifact của Data Agent (kho AWS), không cần gói nào.
- Gói CSV VHOP (3.000 căn, chỉ cho đường hỏi tự do cũ) **thuộc team DATA, không commit ở đây**. Compare tìm lần lượt:
  `VDAGENT_VHOP_DATA_DIR` → `warehouse/vhop` → `var/vhop` → `data/vhop`. Lấy bản đã phát hành trên
  nhánh `DATA` (commit `adf2d05`) vào `var/vhop` (đã gitignore):

  ```
  git archive adf2d05 warehouse/vhop | tar -x -C var --strip-components=1
  ```

## Chạy

Cấu hình trong `agents/compare/.env` (gitignored, chép từ `.env.example`). **Mọi biến đều tùy chọn**:
không có `OPENAI_API_KEY` plugin vẫn nạp và trả lời bằng quy tắc + câu mẫu.

| Biến | Mặc định | |
|---|---|---|
| `OPENAI_API_KEY` | — | Có thì dùng mô hình |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | Endpoint tương thích OpenAI |
| `LLM_MODEL` / `LLM_FALLBACK_MODEL` | `gpt-6-luna` / `gpt-4o-mini` | Thử lần lượt |
| `LLM_TIMEOUT_S` | `20` | Mỗi lần gọi; cả lượt giữ trong 25 giây |
| `COMPARE_LLM` | `on` | `off` = không gọi mô hình dù có key |

**Terminal** (không cần UI):

```
uv run python -m vdagent_compare.demo --question "Tại sao A12-08 bán chậm?"
uv run python -m vdagent_compare.demo --chat            # hỏi liên tục, nhớ câu trước
uv run python -m vdagent_compare.demo --question "..." --json   # artifact gốc
```

**Backend + UI:** `make backend` (plugin `vdagent_compare` đã có trong `backend/config.yaml`), chọn
agent `compare`.

Câu hỏi mẫu: *Tại sao A12-08 bán chậm?* · *So sánh A12-08 với A12-11* · *So sánh A12-08 với căn tương
đồng cùng phân khu* · *So sánh căn SAPPHIRE1-13.001 với các căn tương đồng* · *Xếp hạng DOM của
SAPPHIRE1-13.001* · *So sánh DOM 2PN theo tầng trong PRJ-VHOP*.

## Test

```
uv run pytest agents/compare
```

Test cần gói CSV được đánh dấu `needs_pack` và tự bỏ qua khi máy chưa có gói. Test agent dùng mô hình
giả (`FakeLLM`), không gọi mạng. Đối chiếu 26 golden case (kho spec của Compare Owner):
`COMPARE_DEMO_DIR=agents/compare uv run python <kho-spec>/_tools/test/golden/golden_vs_python.py` → 42/42.
