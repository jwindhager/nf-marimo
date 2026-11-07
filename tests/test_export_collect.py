from nf_marimo import notebook_file
from nf_marimo.export.collect import collect, find_nf_cells


def test_collect_fixture_project(project):
    nb_path = project / "workflow.py"
    nb = notebook_file.parse(nb_path)
    nf_cells = find_nf_cells(nb)
    codes = "\n".join(c.code for c in nf_cells)
    assert "nfm.pipeline(" in codes
    assert "local/upper" in codes
    # analysis cells consuming outputs are not nf cells
    assert all(".values()" not in c.code for c in nf_cells)

    col = collect(nb_path)
    pipeline = col.pipeline
    assert pipeline.name == "textflow"
    assert [p.alias for p in pipeline.processes] == ["UPPER", "COUNT"]
    # notebook-local modules (helpers.py) are importable during export
    executed = "\n".join(c.code for c in col.executed)
    assert "import helpers" in executed
    assert "summarize" not in executed
    assert pipeline.samplesheets["input"].read_test_rows()[1] == {
        "sample": "s2",
        "text": "data/s2.txt",
    }


def test_impure_workflow_cells(project):
    from nf_marimo.export.collect import impure_statements

    nb = notebook_file.parse_source(
        "import marimo\napp = marimo.App()\n\n\n@app.cell\ndef _(pipeline):\n"
        "    upper = pipeline.process('local/upper')\n    upper\n    print('side effect')\n"
        "    return (upper,)\n"
    )
    assert impure_statements(nb.cells[0]) == [3]
    # the fixture notebook's workflow cells are pure
    col = collect(project / "workflow.py")
    assert col.warnings == []
