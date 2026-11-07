from nf_marimo import ops
from nf_marimo.snippet import default_variable


def test_stage_or_url():
    groovy = ops.stage_or_url()
    assert groovy.startswith("map { meta, data ->")
    assert "data instanceof Path" in groovy  # upstream outputs are staged
    assert "[meta, [], data.toString()]" in groovy  # remote URIs are passed as values
    assert "file(data.toString(), checkIfExists: true)" in groovy  # local paths are staged
    assert "(?!file:)" in groovy  # file:// URIs count as local


def test_default_variable():
    assert default_variable("fastqc") == "fastqc"
    assert default_variable("bwa/mem") == "bwa_mem"
    assert default_variable("import") == "import_"
