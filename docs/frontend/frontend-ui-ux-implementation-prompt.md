# Prompt triển khai giao diện VDAgent

Hãy **triển khai code**, không dừng ở việc lập kế hoạch, theo [docs/frontend-ui-ux-plan.md](./frontend-ui-ux-plan.md). Đọc `AGENTS.md`, plan, frontend hiện tại và API/SSE contract trước khi sửa. Tự thực hiện đến khi các hạng mục trong plan hoàn tất hoặc nêu rõ phần bị chặn bởi dữ liệu/API thực tế. Không dùng subagent.

## Mục tiêu và phạm vi

- Cải thiện workspace thành giao diện **sáng, bắt mắt vừa đủ và dễ đọc trong phiên phân tích dài**. Tham khảo bố cục và tương tác của [fe-agenttest](https://github.com/mhiu05/fe-agenttest); dùng [Impeccable](https://github.com/pbakaus/impeccable) làm tiêu chí về thứ bậc thông tin, typography, khoảng trắng, màu sắc, responsive và polish. Tham khảo ý tưởng, không sao chép mock logic hoặc palette tối/vàng của Impeccable.
- Giữ **Vite + React 18** và đúng năm agent hiện tại: `orchestrator`, `data`, `compare`, `insight`, `report`. Agent list lấy từ `/api/agents`; không tạo “chart agent”. Chart là artifact trong inspector.
- Giữ `UserPicker` demo. Chưa làm login/register, session gate, project selector, retry/approve hay tính năng không có backend contract. Không thêm trạng thái tiến trình, số liệu, lịch sử hoặc nút thao tác giả. Giữ REST, React Query, SSE, phân trang chat, task tree và luồng mở dataset/chart/report đang hoạt động.
- Tập trung trong `frontend/`; chỉ chạm backend nếu thật sự cần để sửa một hợp đồng đã có, và giải thích rõ lý do. Không đổi nhánh, không commit/push, không sửa hoặc ghi đè thay đổi không liên quan; `frontend/package-lock.json` có thể đã có thay đổi của người khác, hãy kiểm tra diff trước khi quyết định chạm vào nó.

## Cách làm bắt buộc

1. Kiểm tra `git status` và diff liên quan. Đọc `frontend/src/App.tsx`, `styles.css`, `components/*`, `api/*`, `events/*` để lập ánh xạ UI → dữ liệu thật. Xác định desktop/tablet/mobile và các trạng thái empty/loading/running/error/result.
2. Phác thảo nhanh 2–3 hướng cho **cùng một màn hình** gồm sidebar, chat, bảng và inspector; chọn một hướng sáng dễ đọc. Ghi ngắn gọn lý do chọn và token dự kiến (màu, chữ, khoảng cách). Không trì hoãn việc code để xin xác nhận cho quyết định thiết kế thông thường.
3. Làm **TDD theo từng lát chức năng**: viết test hành vi có ý nghĩa trước, chạy để thấy lỗi, triển khai tối thiểu cho test qua rồi chỉnh gọn. Ưu tiên test chọn agent/task, busy/queue, mở đóng sidebar/inspector, tab artifact, gửi tin và lỗi, SSE update. Với thay đổi CSS thuần, dùng kiểm tra trực quan thay cho snapshot test chỉ phản chiếu markup.
4. Triển khai từ design tokens và shell, sau đó sidebar/topbar, chat/composer, task timeline/inspector, artifact views và responsive. Giữ mọi thao tác hiện có hoạt động; nút chỉ xuất hiện khi có hành động thật. Trên màn hình nhỏ, sidebar và inspector phải mở/đóng được, focus hợp lý và composer không bị che.
5. Đánh giá chất lượng bằng vòng `critique → audit → polish`: xem ảnh chụp ở khoảng 1440px, 768px và 390px; chỉnh hierarchy, spacing, overflow, màu và trạng thái tương tác. Nội dung chính khoảng 15–16px, metadata dễ đọc, font hỗ trợ tiếng Việt. Kiểm tra tương phản chữ thường ≥ 4.5:1, chữ lớn ≥ 3:1, zoom 200%, bàn phím, nhãn truy cập và `prefers-reduced-motion`. Không truyền đạt trạng thái chỉ bằng màu.
6. Chạy `cd frontend && npm test` và `npm run build`; smoke test với backend thật nếu môi trường cho phép: chọn user demo, gửi tin, xem trạng thái agent/task, SSE reconnect, mở dataset/chart/report và đổi agent/task. Nếu backend không chạy được, dùng fixture ở tầng test để kiểm tra contract và ghi rõ giới hạn xác minh; không đưa fixture thành dữ liệu sản phẩm.

## Tiêu chí hoàn thành

Giao diện cho năm agent dễ quét và dễ đọc ở desktop lẫn mobile; dữ liệu và trạng thái đến từ backend thật; chat, task, cancel, artifact và chọn user demo không bị thoái lui; các kiểm thử/build qua hoặc có lỗi môi trường được mô tả chính xác. Khi xong, tóm tắt file đã đổi, quyết định thiết kế, kết quả kiểm thử/kiểm tra trực quan và giới hạn còn lại. **Không tự commit hoặc push.**
