# Template mở rộng frontend: agent và backend API

Dùng tài liệu này cho **mỗi lần thêm agent, endpoint, field DTO hoặc SSE event**. Mục tiêu là
để backend có thể mở rộng mà không buộc UI phải hardcode tên agent, tạo trạng thái giả, hoặc làm
hỏng cache của user đang dùng.

> Sao chép phần “Phiếu thay đổi” ở cuối file vào PR/issue rồi điền đầy đủ trước khi code.

## Nguyên tắc không phá vỡ

1. **Danh sách agent là dữ liệu.** Sidebar, workspace và chat nhận agent từ `GET /api/agents`
   thông qua `useAgents()`. Không thêm agent mới vào mảng hằng, menu tĩnh, `switch` theo tên,
   hoặc fixture runtime ở frontend.
2. **Giữ contract cũ hợp lệ.** Field mới phải optional hoặc có giá trị mặc định ở backend. Không
   đổi nghĩa, kiểu dữ liệu, format ID hay trạng thái của field đã public khi chưa có migration.
3. **Một nguồn sự thật cho mỗi resource.** REST tải dữ liệu ban đầu/recovery; SSE cập nhật cache
   khi có thay đổi. Khi SSE không đến, UI vẫn phải có đường recovery bằng invalidation/refetch.
4. **Cache phải theo resource và user.** Dùng `queryKeys` trong `frontend/src/api/keys.ts`; không
   ghi trực tiếp vào key tự tạo. `App` tạo `QueryClient` mới khi đổi user, nên không thêm `userId`
   vào key nếu vẫn giữ kiến trúc này.
5. **Chỉ hiện thao tác backend thật hỗ trợ.** Nếu API chưa có retry, approve, cancel, export… thì
   không thêm nút hoặc progress giả. Hiển thị loading/error/empty từ query thật thay vì fixture.

## Thêm agent mới

### Contract backend tối thiểu

`GET /api/agents` phải trả agent mới theo shape hiện có:

```ts
interface AgentDTO {
  name: string;         // khóa ổn định, URL-safe; ví dụ "forecast"
  description: string;  // mô tả ngắn do backend sở hữu
  busy: boolean;
  queue_len: number;
}
```

Agent mới phải hỗ trợ cùng contract chat hiện tại:

- `GET /api/agents/{agent}/messages?before_seq=&limit=`
- `POST /api/agents/{agent}/messages` với `{ content }`
- event `message.appended`, `invocation.updated` và `agent.status` có `agent` đúng bằng `name`.

### Việc frontend phải làm

Thông thường **không cần đổi** `AgentList`, `ChatPane`, `TaskList` hay `Inspector`: chúng đã map
theo `AgentDTO.name`. Chỉ kiểm tra các điểm sau:

- `agentColor(name)` phải có màu fallback ổn định cho tên chưa biết; màu không được là cách duy
  nhất để nhận biết trạng thái.
- Không dùng icon, prompt mẫu, route hay điều kiện `agent === "…"` trừ khi feature đó thật sự là
  capability riêng được backend công bố.
- Nếu đổi hoặc bỏ `orchestrator`, xem fallback chọn agent tại `App.tsx`. Lựa chọn an toàn là agent
  UI đang chọn, rồi `orchestrator` nếu còn tồn tại, cuối cùng là agent đầu tiên backend trả về.
- Kiểm tra tên dài, description rỗng và agent busy/queue trên desktop lẫn mobile.

### Không làm

- Không sửa danh sách “năm agent” bằng tay khi backend thêm agent thứ sáu.
- Không copy response agent vào state local để hiển thị; React Query cache là nguồn dữ liệu.
- Không suy ra capability từ tên. Nếu cần hiển thị capability, thêm metadata có version vào API.

## Thêm hoặc thay đổi REST API

### Thứ tự thực hiện

1. Ghi request/response/error trong phiếu bên dưới và thêm test backend contract trước.
2. Thêm DTO vào `frontend/src/api/types.ts`. Field mới dùng `?:` khi backend cũ có thể chưa trả.
3. Thêm method thuần vào `frontend/src/api/client.ts`; method phải giữ `X-User-Id`, URL encode
   segment và xử lý error envelope qua `ApiClient.request`.
4. Thêm một `queryKeys` ổn định, sau đó một hook trong `frontend/src/api/queries.ts`.
5. Đặt loading, error, empty và content ở component dùng hook. Không dùng data của resource khác
   làm placeholder có vẻ như dữ liệu thật.
6. Chỉ invalidation chính xác resource bị thay đổi sau mutation. Nếu query active cần thấy kết quả
   ngay, gọi `invalidateQueries` với `queryKeys` tương ứng.

### Quy tắc tương thích

| Thay đổi | Cách an toàn |
| --- | --- |
| Thêm field response | Backend luôn trả default, hoặc frontend khai báo optional và có fallback rõ ràng. |
| Đổi tên/remove field | Giữ field cũ trong một release; frontend đọc cả hai qua adapter rồi xóa ở release kế tiếp. |
| Thêm status | UI có nhánh fallback “unknown/in progress”, không cast ép status chưa biết thành completed. |
| Thêm endpoint | Không thay endpoint cũ nếu cùng màn hình còn cần client cũ; giới thiệu endpoint mới và migrate dần. |
| Đổi pagination | Giữ `before_seq`/thứ tự hiện có hoặc version endpoint; không làm lẫn trang mới/cũ trong cache. |
| Thêm quyền hạn | Backend trả lỗi có code ổn định; frontend hiển thị error thật, không ẩn dữ liệu như empty state. |

## Thêm SSE event

SSE không thay REST. Event chỉ giảm độ trễ; reconnect hiện tại sẽ invalidate query để REST phục hồi
state bị bỏ lỡ.

1. Định nghĩa event discriminated union trong `api/types.ts` và thêm tên vào `SERVER_EVENT_NAMES`.
2. Thêm reducer immutable vào `events/applyEvent.ts`, dùng đúng `queryKeys` và không tạo cache cho
   resource chưa được fetch (`old ? update(old) : undefined`).
3. Event phải chứa ID/resource đủ để cập nhật đúng user, agent, task hoặc artifact; không yêu cầu
   frontend đoán từ text message.
4. Event trùng lặp và event đến sai thứ tự phải idempotent. Với messages, dedupe bằng `id` và sắp
   thứ tự bằng `seq` như reducer hiện có.
5. Nếu event chỉ báo “đã thay đổi” nhưng không có payload đầy đủ, invalidate key chính xác thay vì
   tự dựng DTO thiếu field.

## Checklist test và review

### Khi thêm agent

- [ ] API trả agent mới cùng agent cũ; UI hiển thị đúng số lượng backend trả.
- [ ] Chọn agent mới tải đúng `/messages`, gửi được message và chuyển agent không mất cache sai.
- [ ] `busy`, `queue_len`, pending và event `agent.status` cập nhật đúng.
- [ ] Agent tên dài/không có màu định nghĩa vẫn đọc được ở 1440px, 768px và 390px.

### Khi thêm API/SSE

- [ ] Test reducer trước khi sửa hành vi SSE/mutation; kiểm tra duplicate, thứ tự và cache chưa tải.
- [ ] Test REST success, empty, API error và recovery sau reconnect/refetch.
- [ ] Kiểm tra đổi user không thấy dữ liệu/cached message của user trước.
- [ ] Chạy `cd frontend && npm test` và `npm run build`.
- [ ] Không stage `package-lock.json` hoặc file không liên quan nếu thay đổi không cần dependency.

## Phiếu thay đổi (sao chép cho mỗi PR)

```md
# Frontend extension: [tên ngắn]

## Mục tiêu
- [Người dùng có thể làm gì?]
- [Resource/agent nào thay đổi?]

## Contract backend
- REST: `[METHOD] [path]`
- Request: `[body/query/header]`
- Response: `[DTO hoặc link OpenAPI]`
- Error codes: `[code → cách UI hiển thị]`
- Tương thích cũ: `[field/endpoint/status cũ được giữ thế nào]`

## Cache và realtime
- Query key/hook: `[queryKeys.… / use…]`
- Mutation invalidates: `[keys]`
- SSE event: `[event + payload]` hoặc `không cần`
- Recovery khi bỏ lỡ SSE: `[refetch/invalidate nào]`

## Hiển thị
- Loading: `[UI]`
- Empty: `[UI]`
- Error: `[UI]`
- Quyền/thao tác thật từ backend: `[UI]`
- Mobile/a11y: `[focus, overflow, label]`

## Kiểm tra
- [ ] Test đỏ → xanh cho reducer/hook/mutation thay đổi hành vi.
- [ ] API/SSE contract test.
- [ ] 1440px, 768px, 390px.
- [ ] `npm test` và `npm run build`.
```
