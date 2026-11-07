import re

import pytest

import nf_marimo as nfm
from nf_marimo.codegen import ext_value, groovy_literal, render_wrapper
from nf_marimo.snippet import process_cell

TEXT_URL = "https://example.org/s1.txt"
TEST_SAMPLES = [{"sample": "s1", "text": TEXT_URL}]
COLUMNS = {"sample": "meta.id", "text": "uri"}


def test_literals():
    assert groovy_literal(None) == "[]"
    assert groovy_literal({"id": "a", "n": 1, "ok": True}) == "[id: 'a', n: 1, ok: true]"
    assert groovy_literal(["it's"]) == "['it\\'s']"
    assert ext_value("--x 1") == "'--x 1'"
    assert ext_value("${meta.id}_x") == '{ "${meta.id}_x" }'


def test_wrapper_includes_upstream(pipeline):
    count = pipeline.processes[1]
    script, config = render_wrapper(pipeline, [count.out.tsv])
    assert "include { UPPER }" in script
    assert "include { COUNT }" in script
    assert script.index("UPPER(") < script.index("COUNT(")
    assert "ch_input = channel.of(" in script
    assert f"[[id: 's1'], '{TEXT_URL}']" in script
    assert re.search(r"UPPER\.out\.txt\n\s+\.map \{ meta, data ->", script)
    assert "index {\n            path 'out_0.json'" in script
    assert "params.suffix = 'END'" in config
    assert "withName: 'UPPER'" in config
    assert "ext.args = '--fast'" in config
    assert 'ext.prefix = { "${meta.id}_counts" }' in config


def test_wrapper_only_upstream(pipeline):
    upper = pipeline.processes[0]
    script, _ = render_wrapper(pipeline, [upper.out.txt])
    assert "COUNT" not in script


@pytest.mark.parametrize("gpu", [True, False])
def test_wrapper_gpu(project, gpu):
    pipeline = nfm.pipeline("textflow", notebook_dir=project, gpu=gpu)
    samples = pipeline.samplesheet("input", columns=COLUMNS, test=TEST_SAMPLES)
    upper = pipeline.process(
        "local/upper", inputs={"text": samples.op(nfm.ops.stage_or_url()), "suffix": "x"}
    )
    _, config = render_wrapper(pipeline, [upper.out.txt])
    assert ("--gpus all" in config) is gpu
    assert ("withLabel: 'process_gpu'" in config) is gpu


def test_missing_input_warns(project):
    pipeline = nfm.pipeline("x", notebook_dir=project)
    with pytest.warns(UserWarning, match="not connected"):
        p = pipeline.process("local/count", inputs={"mode": "l"})
    assert p.problems == ["input 'text' is not connected"]


def test_unknown_input_raises(project):
    pipeline = nfm.pipeline("x", notebook_dir=project)
    with pytest.raises(KeyError, match="unknown input"):
        pipeline.process("local/count", inputs={"reads": None})


def test_process_cell_snippet(pipeline):
    spec = pipeline.processes[0].spec
    code = process_cell("local/upper", spec)
    compile(code, "<snippet>", "exec")
    assert "upper = pipeline.process(" in code
    assert "'text': None,  # TODO [meta:map, text:file, text_url:string]" in code
    assert "# outputs: upper.out.txt" in code


def test_samplesheet_test_rows(project, tmp_path):
    pipeline = nfm.pipeline("x", notebook_dir=project)
    ch = pipeline.samplesheet("input", columns=COLUMNS, test=TEST_SAMPLES)
    assert ch.ref.read_test_rows() == TEST_SAMPLES
    csv = tmp_path / "s.csv"
    csv.write_text("sample,text\na,/data/a.txt\n", encoding="utf-8")
    file_sheet = nfm.pipeline("z", notebook_dir=tmp_path).samplesheet(
        "input", columns=COLUMNS, test="s.csv"
    )
    assert file_sheet.ref.read_test_rows() == [{"sample": "a", "text": "/data/a.txt"}]
    bad = nfm.pipeline("w", notebook_dir=project).samplesheet(
        "input", columns=COLUMNS, test=[{"sample": "a"}]
    )
    with pytest.raises(ValueError, match="lack column"):
        bad.ref.read_test_rows()


def test_samplesheet_test_dataframe(project):
    pd = pytest.importorskip("pandas")
    sheet = nfm.pipeline("y", notebook_dir=project).samplesheet(
        "input", columns=COLUMNS, test=pd.DataFrame(TEST_SAMPLES)
    )
    assert sheet.ref.read_test_rows() == TEST_SAMPLES


def test_process_not_run_outside_notebook(pipeline):
    assert all(p.results is None for p in pipeline.processes)


@pytest.mark.parametrize(("env", "expected"), [("0", False), ("1", True)])
def test_gpu_env_override(project, monkeypatch, env, expected):
    monkeypatch.setenv("NFM_GPU", env)
    assert nfm.pipeline("x", notebook_dir=project).gpu is expected
