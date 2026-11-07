import threading

import pytest

import nf_marimo as nfm
from nf_marimo.codegen import channel_expr
from nf_marimo.model import ExportModeError, export_mode, exporting

COLUMNS = {"sample": "meta.id", "text": "uri"}


def test_pipeline_name_must_be_lowercase_identifier(project):
    with pytest.raises(ValueError, match="lowercase identifier"):
        nfm.pipeline("My-Pipeline", notebook_dir=project)


def test_samplesheet_validation(project):
    pipeline = nfm.pipeline("x", notebook_dir=project)
    with pytest.raises(ValueError, match=r"meta\.id"):
        pipeline.samplesheet("input", columns={"text": "uri"}, test=[])
    pipeline.samplesheet("input", columns=COLUMNS, test=[])
    with pytest.raises(ValueError, match="already declared"):
        pipeline.samplesheet("input", columns=COLUMNS, test=[])


def test_samplesheet_columns(project):
    pipeline = nfm.pipeline("x", notebook_dir=project)
    sheet = pipeline.samplesheet(
        "input", columns={"sample": "meta.id", "group": "meta.group", "text": "uri"}, test=[]
    ).ref
    assert sheet.meta_columns == {"sample": "id", "group": "group"}
    assert sheet.value_columns == {"text": "uri"}


def test_param_type_inference(project):
    pipeline = nfm.pipeline("x", notebook_dir=project)
    assert pipeline.param("a", True).type == "boolean"
    assert pipeline.param("b", 1).type == "integer"
    assert pipeline.param("c", 1.5).type == "number"
    assert pipeline.param("d", "s").type == "string"
    assert pipeline.param("e", "f.txt", type="file").type == "file"
    assert pipeline.param("t", 1, test=2).test_value == 2
    assert pipeline.params.a.default is True
    assert {p.name for p in pipeline.params} == {"a", "b", "c", "d", "e", "t"}
    with pytest.raises(AttributeError, match="declare it"):
        _ = pipeline.params.missing


def test_process_alias_and_outputs(pipeline):
    upper, count = pipeline.processes
    assert upper.alias == "UPPER"
    assert upper.spec.output_emits == ["txt"]
    assert dir(upper.out) == ["txt"]
    with pytest.raises(AttributeError, match="has no output"):
        _ = upper.out.missing
    assert [p.alias for p in count.upstream()] == ["UPPER", "COUNT"]


def test_process_name_and_rerun_replaces(project):
    pipeline = nfm.pipeline("x", notebook_dir=project)
    a = pipeline.process("local/upper", inputs={"text": None, "suffix": "x"}, name="upper_a")
    assert a.alias == "UPPER_A"
    pipeline.process("local/upper", inputs={"text": None, "suffix": "y"}, name="upper_a")
    assert (
        len(pipeline.processes) == 1
    )  # re-running a cell replaces the process with the same alias


def test_channel_operators(pipeline):
    upper = pipeline.processes[0]
    ch = upper.out.txt
    assert channel_expr(ch.collect(), test=True).endswith(".collect()")
    assert channel_expr(ch.first(), test=True).endswith(".first()")
    assert channel_expr(ch.map("meta, f -> f"), test=True).endswith(".map { meta, f -> f }")
    assert "join(UPPER.out.txt, by: 0)" in channel_expr(ch.join(ch), test=True)
    assert "mix(UPPER.out.txt)" in channel_expr(ch.mix(ch), test=True)
    assert channel_expr(pipeline.params.suffix.channel, test=True) == "channel.value(params.suffix)"
    assert ch.upstream_processes() == [upper]


def test_export_mode_is_thread_local(project, tmp_path):
    seen = []
    with exporting(tmp_path):
        assert export_mode()
        thread = threading.Thread(target=lambda: seen.append(export_mode()))
        thread.start()
        thread.join()
    assert seen == [False]
    assert not export_mode()


def test_values_raise_in_export_mode(pipeline, tmp_path):
    with exporting(tmp_path), pytest.raises(ExportModeError):
        pipeline.processes[0].out.txt.values()
