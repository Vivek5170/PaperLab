"""Pre-flight entry-point tests: register once, abort duplicates, CLI behavior."""
from __future__ import annotations

import database
from preflight import main, preflight_register


def test_preflight_register_returns_paper_id(tmp_db, tmp_path):
    q = tmp_path / "q.pdf"
    s = tmp_path / "s.pdf"
    q.write_bytes(b"Q")
    s.write_bytes(b"S")
    pid = preflight_register(str(q), str(s))
    assert isinstance(pid, int) and pid > 0
    assert database.get_paper(pid)["archive"] == 0


def test_preflight_duplicate_cli_exits_2(tmp_db, tmp_path, capsys):
    q = tmp_path / "q.pdf"
    s = tmp_path / "s.pdf"
    q.write_bytes(b"Q")
    s.write_bytes(b"S")
    assert main([str(q), str(s)]) == 0
    capsys.readouterr()
    assert main([str(q), str(s)]) == 2  # duplicate pair aborts
    assert "Duplicate" in capsys.readouterr().err


def test_preflight_missing_file_cli_exits_1(tmp_db, tmp_path):
    assert main([str(tmp_path / "nope.pdf")]) == 1
