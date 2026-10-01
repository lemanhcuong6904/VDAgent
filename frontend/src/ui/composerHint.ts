const GENERIC = "(Enter to send, Shift+Enter for a new line)";

/** The Data chat answers questions about the package Data has just fetched; its prompt says so. */
const DATA_HINT =
  "Hỏi thêm về dữ liệu vừa lấy, ví dụ: “Vì sao lấy căn này?”, “Giá trị nào còn thiếu?”  (Enter để gửi, Shift+Enter xuống dòng)";

export function composerPlaceholder(agent: string): string {
  return agent === "data" ? DATA_HINT : `Message ${agent}…  ${GENERIC}`;
}
