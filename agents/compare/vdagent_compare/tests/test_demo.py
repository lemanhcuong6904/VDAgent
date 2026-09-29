"""Terminal demo: the same agent as the Backend, readable without a markdown viewer."""
from __future__ import annotations

import json

from vdagent_compare import demo
from vdagent_compare.demo import to_terminal


def test_markdown_becomes_plain_aligned_text():
    text = "### Kết quả\n\nTrạng thái: **Hoàn tất**.\n\n| Chỉ số | Căn |\n| --- | --- |\n| DOM | 138 |\n| Giá ròng/m² | 72.500.000 |"
    out = to_terminal(text)
    assert "###" not in out and "**" not in out and "| --- |" not in out
    lines = out.splitlines()
    assert "KẾT QUẢ" in lines[0]
    header, rule, row1, row2 = [line for line in lines if "Chỉ số" in line or set(line.strip()) == {"-", " "}
                                or "DOM" in line or "Giá ròng" in line]
    assert header.index("Căn") == row1.index("138") == row2.index("72.500.000")


def test_single_question_prints_a_plain_answer(capsys):
    assert demo.main(["--question", "Tại sao A12-08 bán chậm?", "--no-llm"]) == 0
    out = capsys.readouterr().out
    assert "62.500.000" in out and "**" not in out and "###" not in out


def test_json_flag_prints_the_raw_artifacts(capsys):
    assert demo.main(["--question", "Tại sao A12-08 bán chậm?", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["peer_definition"]["peerCount"] == 5


def test_chat_mode_keeps_history_and_stops_on_exit(capsys, monkeypatch):
    answers = iter(["Tại sao A12-08 bán chậm?", "So sánh A12-08 với A12-11", "thoát"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    assert demo.main(["--chat", "--no-llm"]) == 0
    out = capsys.readouterr().out
    assert out.count("Compare >") == 2
    assert "so trực diện" in out.lower()
