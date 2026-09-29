"""Vietnamese wording for Sales Ops (build spec 01 §10.5): code templates, no LLM. OPEN(Q-19): PO approval of the text.
Error codes and step ids appear only under "Chi tiết kỹ thuật"."""

from __future__ import annotations

PART_NAMES = {"data": "Số liệu", "compare": "So sánh với nhóm tương đồng", "insight": "Giải thích nguyên nhân",
              "chart": "Biểu đồ", "report": "Báo cáo nháp"}


def part(agent: str) -> str:
    return PART_NAMES.get(agent, agent)


def part_lower(agent: str) -> str:
    name = part(agent)
    return name[:1].lower() + name[1:]


def card_title(agent: str, mention: str) -> str:
    return f'Phần "{part(agent)}" của {mention} chưa dùng được'


def retry_label(agent: str) -> str:
    return f"Thử lại phần {part_lower(agent)}"


def no_data_sentence(need: str, mention: str) -> str:
    return f"Chưa có dữ liệu {need} cho {mention} ở kỳ dữ liệu hiện tại. Các phần khác vẫn hiển thị."


def timeout_sentence(agent: str) -> str:
    return (f"Phần {part_lower(agent)} chưa xong vì xử lý quá thời gian cho phép; đội vận hành đã được báo."
            " Bạn có thể thử lại sau.")


__all__ = ["PART_NAMES", "card_title", "no_data_sentence", "part", "part_lower", "retry_label", "timeout_sentence"]
