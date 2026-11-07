"""Exporter file rewriters, on minimal stand-ins for the nf-core template files."""

import json

import pytest

from nf_marimo.export import nfcore
from nf_marimo.export.collect import ExportError


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_check_exportable(pipeline, project):
    nfcore._check_exportable(pipeline)  # fixture pipeline is complete
    import nf_marimo as nfm

    bad = nfm.pipeline("bad", notebook_dir=project)
    with pytest.warns(UserWarning, match="not connected"):
        bad.process("local/count", inputs={"mode": "l"})
    with pytest.raises(ExportError, match="not connected"):
        nfcore._check_exportable(bad)


def test_write_workflow(pipeline, tmp_path):
    _write(
        tmp_path / "workflows" / "textflow.nf",
        "include { methodsDescriptionText } from '../x'\n\n"
        "workflow TEXTFLOW {\n    main:\n    def ch_versions = channel.empty()\n}\n",
    )
    nfcore.write_workflow(pipeline, tmp_path)
    text = (tmp_path / "workflows" / "textflow.nf").read_text(encoding="utf-8")
    assert "include { UPPER } from '../modules/local/upper/main'" in text
    assert "    UPPER(\n        ch_samplesheet" in text
    assert text.index("UPPER(") < text.index("COUNT(")


def test_write_samplesheet_channel(pipeline, tmp_path):
    path = tmp_path / "subworkflows" / "local" / "utils_nfcore_textflow_pipeline" / "main.nf"
    _write(
        path,
        "    channel\n"
        '        .fromList(samplesheetToList(input, "${projectDir}/assets/schema_input.json"))\n'
        "        .map { fastq stuff }\n"
        "        .set { ch_samplesheet }\n",
    )
    nfcore.write_samplesheet_channel(pipeline, tmp_path)
    text = path.read_text(encoding="utf-8")
    assert "fastq" not in text
    assert ".set { ch_samplesheet }" in text


def test_write_input_schema(pipeline, tmp_path):
    _write(tmp_path / "assets" / "schema_input.json", json.dumps({"items": {}}))
    nfcore.write_input_schema(pipeline, tmp_path)
    schema = json.loads((tmp_path / "assets" / "schema_input.json").read_text(encoding="utf-8"))
    assert schema["items"]["properties"]["sample"]["meta"] == ["id"]
    assert "format" not in schema["items"]["properties"]["text"]  # URIs are not file paths
    assert schema["items"]["required"] == ["sample", "text"]
    csv = (tmp_path / "assets" / "samplesheet.csv").read_text(encoding="utf-8")
    assert csv == "sample,text\ns1,https://example.org/s1.txt\n"


def test_write_params(pipeline, tmp_path):
    _write(tmp_path / "nextflow.config", "params {\n    input                      = null\n}\n")
    _write(
        tmp_path / "nextflow_schema.json",
        json.dumps({"$defs": {"input_output_options": {"properties": {"input": {}}}}, "allOf": []}),
    )
    nfcore.write_params(pipeline, tmp_path)
    assert "suffix = 'END'" in (tmp_path / "nextflow.config").read_text(encoding="utf-8")
    schema = json.loads((tmp_path / "nextflow_schema.json").read_text(encoding="utf-8"))
    suffix = schema["$defs"]["workflow_options"]["properties"]["suffix"]
    assert suffix == {"type": "string", "description": "Appended line", "default": "END"}
    assert {"$ref": "#/$defs/workflow_options"} in schema["allOf"]


def test_write_test_config(pipeline, tmp_path):
    _write(
        tmp_path / "conf" / "test.config",
        "params {\n    // TODO nf-core: give test data\n"
        "    input  = params.pipelines_testdata_base_path + 'x.csv'\n}\n",
    )
    nfcore.write_test_config(pipeline, tmp_path)
    text = (tmp_path / "conf" / "test.config").read_text(encoding="utf-8")
    assert 'input = "${projectDir}/assets/samplesheet_test.csv"' in text
    assert "TODO" not in text
    assert (tmp_path / "assets" / "samplesheet_test.csv").exists()


def test_write_modules_config(pipeline, tmp_path):
    _write(tmp_path / "conf" / "modules.config", "process {\n}\n")
    nfcore.write_modules_config(pipeline, tmp_path)
    text = (tmp_path / "conf" / "modules.config").read_text(encoding="utf-8")
    assert "withName: 'UPPER'" in text
    assert "ext.args = '--fast'" in text
    assert "${params.outdir}/count" in text
