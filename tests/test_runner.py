import json

import pytest

from nf_marimo import runner
from nf_marimo.codegen import parse_index


def test_parse_index(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("x", encoding="utf-8")
    index = tmp_path / "out_0.json"
    index.write_text(json.dumps([[{"id": "s1"}, str(f)], "value"]), encoding="utf-8")
    assert parse_index(index) == [[{"id": "s1"}, f], "value"]


def test_record_session(tmp_path):
    (tmp_path / ".nextflow").mkdir()
    history = "2026-01-01\t1s\tfunny_name\tOK\tabc\t1234-5678\tnextflow run main.nf\n"
    (tmp_path / ".nextflow" / "history").write_text(history, encoding="utf-8")
    runner._record_session(tmp_path)
    assert runner._session_id(tmp_path) == "1234-5678"


def test_nextflow_missing(monkeypatch):
    monkeypatch.delenv("NFM_NEXTFLOW", raising=False)
    monkeypatch.setattr(runner.shutil, "which", lambda _: None)
    with pytest.raises(FileNotFoundError, match="nextflow not found"):
        runner.nextflow_bin()
