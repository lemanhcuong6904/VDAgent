# Template mở rộng frontend: agent, API và dữ liệu

Dùng tài liệu này cho **mỗi lần thay đổi agent, REST/SSE, dữ liệu hoặc artifact**. Mục tiêu là
giữ giao diện ổn định khi nguồn dữ liệu mở rộng: UI chỉ phụ thuộc vào contract công khai,
không phụ thuộc prompt, logic nội bộ của agent hay cấu trúc database. Nếu một contract
đang dùng phải đổi theo cách không tương thích, cần version/adapter và giai đoạn chuyển tiếp;
không thể bảo đảm frontend không bị ảnh hưởng bằng CSS hay kiểm tra kiểu TypeScript đơn thuần.

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
6. **Tách dữ liệu khỏi giao diện.** Agent/backend quyết định nội dung và trạng thái; frontend
   nhận DTO đã định nghĩa, định dạng để hiển thị, không tính lại kết quả phân tích từ raw data
   hoặc dựa vào câu chữ do agent sinh ra để suy luận trạng thái.
7. **Theme là contract giao diện riêng.** Màu cam-vàng, typography, spacing và bố cục nằm ở
   `frontend/src/styles.css`. Thay đổi agent/API/data không được tự ý đổi token màu hoặc
   các lớp layout chung; chỉ sửa giao diện khi có yêu cầu sản phẩm cụ thể.

## Ranh giới thay đổi

| Nguồn thay đổi | Frontend cần làm | Theme/bố cục |
| --- | --- | --- |
| Thêm agent dùng contract chat hiện có | Xác nhận agent xuất hiện từ `GET /api/agents`; kiểm tra tên dài và màu fallback. | Giữ nguyên. |
| Agent đổi prompt, mô hình, công cụ hoặc câu trả lời trong cùng contract | Không sửa UI; kiểm tra nội dung dài, Markdown và trạng thái rỗng. | Giữ nguyên. |
| Thêm field/endpoint/event có sử dụng ở UI | Cập nhật DTO → client/hook hoặc reducer → component ở đúng chỗ. | Tái sử dụng token và component hiện có. |
| Dữ liệu đổi giá trị nhưng giữ schema/ngữ nghĩa | Không sửa frontend; UI hiển thị giá trị backend trả. | Giữ nguyên. |
| Schema, ID, status hoặc artifact thay đổi không tương thích | Backend version hoặc giữ contract cũ; frontend thêm adapter và renderer sau khi có contract mới. | Giữ nguyên trừ khi yêu cầu hiển thị mới cần bố cục mới. |

Quy trình: mô tả contract và khả năng tương thích trước, xác định màn hình nào dùng dữ liệu,
rồi chỉ cập nhật lớp tương ứng. Nếu thay đổi ở agent/backend không làm đổi contract đang dùng,
ghi rõ “không cần sửa frontend” trong phiếu thay đổi.

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

- Không cập nhật số lượng hoặc danh sách agent bằng tay khi backend thêm agent mới.
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

## Thay đổi dữ liệu và artifact

Xem `frontend/src/api/types.ts` là hình dạng dữ liệu UI đang tiêu thụ. Dữ liệu nguồn hoặc
artifact có thể thay đổi độc lập nếu REST/SSE vẫn trả đúng DTO và giữ nguyên ý nghĩa field.

| Trường hợp | Cách xử lý |
| --- | --- |
| Thêm field chưa hiển thị | Backend giữ response cũ hợp lệ; không cần sửa component. |
| Thêm field sẽ hiển thị | Khai báo optional/default theo giai đoạn chuyển tiếp, định dạng ở component hoặc utility chung, có fallback cho `null`/thiếu field. |
| Đổi đơn vị, thời gian, precision hoặc ngữ nghĩa | Công bố contract mới hoặc metadata rõ ràng; không để frontend tự đoán đơn vị từ tên cột hay nội dung chat. |
| Thêm loại artifact/schema version | Bổ sung API/DTO/query key và renderer tương ứng; giữ cách đọc bản cũ hoặc hiển thị trạng thái “chưa hỗ trợ”. |
| Thay đổi ID/link artifact | Kiểm tra `frontend/src/ui/artifacts.ts` và `MessageItem.tsx`: parser hiện nhận link `ds_`, `ch_`, `rp_`; không suy ra loại artifact mới từ chuỗi tự do. |

Các viewer hiện ở `frontend/src/components/inspector/` (dataset, chart, report và chart spec
được nhúng trong report). Renderer mới phải xử lý loading, error, empty, `null`, dữ liệu dài,
bảng rộng và version không hỗ trợ. Dùng giá trị/nguồn tham chiếu backend trả; không thay
`null` bằng 0 hoặc tự tạo kết quả phân tích để “lấp chỗ trống”.

Nếu dữ liệu chỉ đổi bên trong database hoặc artifact store nhưng API vẫn giữ DTO, frontend
không cần chỉnh. Nếu đổi contract, cập nhật backend và frontend theo cùng một phiên bản hoặc
duy trì hai shape trong giai đoạn chuyển tiếp; không xóa field cũ ngay khi UI cũ còn dùng.

## Giữ theme và bố cục ổn định

- Theme cam-vàng hiện được đặt bằng token `:root` ở cuối `frontend/src/styles.css`:
  `--bg`, `--panel`, `--text`, `--muted`, `--border`, `--accent`, `--accent-soft`.
  Component mới dùng token và các pattern đang có; không thêm màu inline hoặc palette riêng
  theo tên agent hay loại dữ liệu.
- Giữ các vùng layout chung `.app`, `.sidebar`, `.chat-scroll`, `.composer`, `.inspector`
  khi chỉ đổi logic dữ liệu. CSS mới nên đặt trong selector của component mới để không thay
  diện mạo toàn workspace. Màu trạng thái (thành công/lỗi/đang chạy) phải giữ ý nghĩa riêng.
- Nội dung backend có độ dài không đoán trước. Cho text xuống dòng hoặc cắt có chủ ý; bảng
  và biểu đồ có vùng cuộn/co giãn, không làm thanh bên hay composer bị đẩy ra khỏi viewport.
- Kiểm tra các breakpoint sẵn có (1120px, 760px, 440px), trạng thái ẩn/hiện inspector,
  focus bằng bàn phím, độ tương phản và `prefers-reduced-motion` nếu thêm chuyển động.
- Chỉ thay token hoặc bố cục chung khi yêu cầu trực tiếp là đổi thiết kế. Khi đó ghi riêng
  phạm vi ảnh hưởng và xem lại các màn hình agent, chat, Conversations và inspector.

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

### Khi đổi dữ liệu/artifact

- [ ] Giá trị mới vẫn giữ schema, đơn vị, ID, status và ngữ nghĩa đã công bố; nếu không, có version/adapter.
- [ ] Field optional/`null`, artifact chưa hỗ trợ, dữ liệu dài và bảng rộng có cách hiển thị rõ.
- [ ] Không suy luận kết quả, trạng thái hoặc loại artifact từ câu chữ tùy biến của agent.

### Giữ giao diện

- [ ] Diff chỉ chạm tới DTO/client/hook/reducer/viewer cần thiết; token theme và layout chung chỉ đổi khi có yêu cầu thiết kế.
- [ ] Màu, spacing, focus, trạng thái và độ tương phản vẫn nhất quán ở 1440px, 768px, 390px.
- [ ] Chat, Conversations, composer và inspector không bị tràn hoặc đổi kích thước bất ngờ bởi dữ liệu mới.

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

## Dữ liệu/artifact
- Schema và version: `[cũ → mới hoặc không đổi]`
- ID, đơn vị, nullability, status, source refs: `[tác động]`
- Adapter/viewer cần cập nhật: `[file hoặc không cần]`
- Backward compatibility: `[backend cũ + frontend cũ hoạt động thế nào]`

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

## Tác động giao diện
- Theme token/layout chung: `[giữ nguyên hoặc lý do cần đổi]`
- Component mới/tái sử dụng: `[đường dẫn]`
- Nội dung dài, responsive, focus/contrast: `[cách kiểm tra]`

## Kiểm tra
- [ ] Test đỏ → xanh cho reducer/hook/mutation thay đổi hành vi.
- [ ] API/SSE contract test.
- [ ] 1440px, 768px, 390px.
- [ ] `npm test` và `npm run build`.
```
