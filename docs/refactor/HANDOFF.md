# Handoff — phiên refactor 2026-09-29

Cập nhật cuối mỗi phiên làm việc trên kế hoạch này. Mục mới nhất ở trên cùng. Xem `PLAN.md` cho bối
cảnh đầy đủ, `TASKS.md` cho danh sách việc.

## Câu hỏi mở (cần hỏi chủ dự án trước khi code, chưa có câu trả lời)

- **[ĐANG CHỜ — QUAN TRỌNG, XEM MỤC "TẠM DỪNG" BÊN DƯỚI]** Xây đúng wire-protocol async
  (DISPATCH/COMMAND_ACK + REPORT độc lập/REWIRE/RELEASE/CANCEL/STATUS_QUERY) trong
  `vdagent_sdk`/`backend/vdagent_backend/engine/` cho 3 agent orchestrator/data/report theo
  `docs/agent-a/orchestrator/contract-v1.0.md`, HAY mô phỏng bằng lời gọi đồng bộ hiện có
  (`ctx.call_agent`)? Chủ dự án cần bàn lại với team AGENT_A trước khi chốt — xem tóm tắt đầy đủ
  trong nhật ký 2026-09-29 (phiên 2) bên dưới.

## Nhật ký

### 2026-09-29 (phiên 2) — Tạm dừng: quyết định transport async vs đồng bộ cho contract-v1.0.md

- Bối cảnh: chủ dự án yêu cầu build lại 3 agent (orchestrator, data, report) tham khảo code demo,
  theo đúng `docs/agent-a/orchestrator/contract-v1.0.md` (đảo ngược một phần quyết định "bỏ qua
  docs/agent-a" ở phiên 1 — chỉ áp dụng lại cho riêng phần nội dung contract của 3 agent này, còn
  quyết định coi phần kiến trúc TypeScript của docs/agent-a là lỗi thời thì vẫn giữ).
- Đã xong:
  - Đọc kỹ `contract-v1.0.md` (2988 dòng) bằng agent chuyên trách, tóm tắt đầy đủ 7 mục: envelope,
    9 loại message, trình tự thời gian thực tế 1 bước, vòng đời 1 run (ví dụ mẫu "Landmark bán
    chậm"), tab DATA, tab REPORT, phần Orchestrator nội bộ.
  - **Phát hiện quan trọng nhất:** contract này là giao thức **bất đồng bộ thật sự** — DISPATCH chỉ
    nhận COMMAND_ACK (xác nhận đã nhận việc, CHƯA chạy); kết quả thật đến sau qua **REPORT**, một
    message độc lập agent tự gửi bất cứ lúc nào trong cửa sổ `deadline_s + 15s`, hoặc bị
    STATUS_QUERY poll mỗi 2 giây nếu agent không tự đẩy. Có wave-dispatch (nhiều bước chạy song
    song thật), REWIRE/RELEASE/CANCEL/ANSWER tiêm vào giữa lúc bước đang "treo" chờ REPORT, và
    tolerate nhận trùng (retry theo outbox 2s/4s — at-least-once).
  - Điều này **khác về bản chất** với `ctx.call_agent` hiện tại (block tới khi callee trả lời xong
    hẳn) — không thể build đúng chỉ bằng cách viết 3 agent plugin, mà cần thêm API mới vào
    `vdagent_sdk` + sửa `backend/vdagent_backend/engine/engine.py` (hạ tầng dùng chung cho cả 5
    agent, kể cả insight/compare vốn được yêu cầu giữ nguyên).
  - Đã trình bày rõ 2 lựa chọn cho chủ dự án: (a) xây đúng async trong SDK/Backend — khối lượng lớn,
    rủi ro cao vì đụng hạ tầng chung; (b) mô phỏng ngữ nghĩa DISPATCH+REPORT bằng 1 lời gọi đồng bộ
    — rẻ hơn nhiều nhưng mất khả năng wave-song-song thật và can thiệp giữa chừng (REWIRE/RELEASE/
    QUESTION-treo) mà chính ví dụ mẫu trong contract lại dùng tới (4/6 bước trong ví dụ mẫu gặp lỗi
    hoặc hỏi lại giữa chừng).
- Đang dở: **chủ dự án chọn tạm dừng, sẽ bàn lại với team AGENT_A trước khi chốt hướng.** Chưa viết
  dòng code nào cho phần này (chỉ đọc + tóm tắt).
- Bước tiếp theo (khi có câu trả lời):
  1. Nếu chọn (a) async thật: cần thiết kế lại trước — ít nhất là: API mới nào thêm vào
     `vdagent_sdk` (ví dụ `ctx.dispatch_agent()` không-block + cách nhận REPORT như inbound message
     độc lập vào stack của Orchestrator), có cần bảng DB mới cho run/step/wait_list hay tái dùng
     `invocations`/`tasks` hiện có, và quan trọng nhất: xác nhận việc này **không phá vỡ** hành vi
     đồng bộ mà insight/compare/data(hiện tại)/orchestrator(hiện tại) đang dựa vào (5 review agent
     ở phiên 1 đã xác nhận engine hiện tại PASS tuyệt đối theo mô hình đồng bộ — đổi engine có nguy
     cơ phá vỡ toàn bộ, không chỉ 3 agent này).
  2. Nếu chọn (b) mô phỏng đồng bộ: có thể bắt đầu ngay bằng cách lấy cấu trúc dữu liệu StepSpec/
     DoneResult/error-code từ tab DATA và tab REPORT của contract-v1.0.md, viết package
     `vdagent_contracts` mới (hiện chưa tồn tại ở đâu cả — xem phiên 1), rồi build agent theo mẫu
     code demo nhưng gọi qua `ctx.call_agent` sẵn có, không đổi backend.
  3. Nếu chọn tạm hoãn: không làm gì thêm ở mục "3 agent" này, quay lại làm nốt `TASKS.md` (T0-T7,
     hardening nhỏ, không phụ thuộc quyết định này).
- Kiểm tra: không áp dụng (chưa sửa code).
- Contract giữa agent: không đổi (chưa code).
- Cần báo: **chủ dự án tự bàn với team AGENT_A** — không phải việc của phiên Claude Code này.
- Chú ý / quyết định quan trọng: xem mục "Phát hiện quan trọng nhất" ở trên — đây là lý do dừng.
- Chưa commit: `docs/refactor/HANDOFF.md` (mục này) vừa cập nhật, `PLAN.md`/`TASKS.md` của phiên 1
  chưa commit từ trước.

### 2026-09-29 (phiên 1) — Khởi tạo plan sau khi revert bản copy sai

- Task/issue: (chưa có issue GitHub — repo dùng docs/agent-a's issue-based workflow nhưng docs đó
  bị coi là lỗi thời, xem PLAN.md mục 0.2; nếu team muốn track qua GitHub issue thật, tạo issue
  riêng và dán link vào đây)
- Agent chạm: không agent nào — đây là giai đoạn khảo sát + revert + lập plan, chưa sửa code thật.
- Đã xong:
  - Copy `vde-agent-demo/agents` → `Team_6_cAi/agents` (theo yêu cầu gốc), xác nhận đủ file.
  - Phát hiện code copy vào không tương thích kiến trúc hiện tại (thiếu package `vdagent_contracts`,
    dùng StepSpec contract không có doc mô tả trong repo này).
  - Revert hoàn toàn: `git checkout -- agents/data agents/insight agents/orchestrator` +
    `git clean -fd` cho các thư mục đó + `agents/_shared`. `git status --porcelain -- agents` sạch.
  - Đối chiếu sâu 4 mảng code hiện tại (đã revert) với `docs/superpowers/specs/*.md` bằng 4 agent
    song song, mỗi agent trích dẫn file:line cho từng claim. Kết quả: PASS gần như tuyệt đối, chỉ
    có gap nhỏ (test thiếu, cosmetic) — liệt kê trong `TASKS.md`.
  - Viết `PLAN.md`, `TASKS.md`, `HANDOFF.md` (file này) để track phần hardening còn lại.
- Đang dở: chưa bắt đầu T0 (xác nhận `uv sync`/`uv run pytest` chạy sạch trên máy thật).
- Bước tiếp theo: chạy T0. Nếu pass, làm T1-T7 theo thứ tự trong `TASKS.md` (không bắt buộc theo
  đúng thứ tự số, có thể làm song song vì các task độc lập nhau — khác agent, khác file).
- Kiểm tra: chưa chạy test nào trong phiên này (chỉ đọc code, không sửa).
- Contract giữa agent: không đổi gì — toàn bộ phát hiện đều là hardening nội bộ từng agent, không
  đổi StepSpec/Envelope/API bên ngoài.
- Cần báo: không có việc ngoài phạm vi cần báo owner khác tại thời điểm này.
- Chú ý / quyết định quan trọng:
  - Quyết định "revert code copy, chỉ tham khảo demo" và "coi docs/agent-a là lỗi thời, bỏ qua khi
    lập plan" đã được chủ dự án xác nhận trực tiếp trong phiên 2026-09-29 (không phải suy đoán).
  - Một review ở vòng đầu (dùng docs/agent-a làm chuẩn, trước khi phát hiện docs/superpowers/specs)
    từng nghi ngờ hành vi "Jev lỗi/timeout = pass" của `report` là bug che giấu lỗi. Sau khi đối
    chiếu lại với spec thật, đây là hành vi **có chủ đích**, đã có test — không phải bug, không sửa.
    Ghi lại ở đây để phiên sau không lặp lại nhầm lẫn tương tự.
- Chưa commit: có — `docs/refactor/PLAN.md`, `docs/refactor/TASKS.md`,
  `docs/refactor/HANDOFF.md` (file này) là file mới, chưa add/commit.
