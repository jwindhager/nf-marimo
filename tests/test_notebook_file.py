import shutil

from nf_marimo import notebook_file


def test_parse(fixtures):
    nb = notebook_file.parse(fixtures / "notebook.py")
    kinds = [c.kind for c in nb.cells]
    assert kinds == ["setup", "cell", "cell", "cell", "function", "cell"]
    setup, imports, config, use, util, md = nb.cells
    assert setup.defs == {"os"}
    assert imports.defs == {"mo", "nfm"}
    assert config.refs == {"nfm"}
    assert config.defs == {"pipeline", "x"}
    # defs not returned by marimo (helper, y) are still found; _private names are not
    assert use.defs == {"helper", "y"}
    assert util.defs == {"util"}
    assert md.refs == {"mo", "y"}
    assert [p.index for p in nb.parents(use)] == [config.index]


def test_ancestors_and_topological(fixtures):
    nb = notebook_file.parse(fixtures / "notebook.py")
    md = nb.cells[-1]
    anc = nb.ancestors([md])
    assert [c.index for c in anc] == [1, 2, 3, 5]
    order = nb.topological()
    assert order[0].kind == "setup"
    assert order.index(nb.cells[2]) < order.index(nb.cells[3])


def test_insert_cell(fixtures, tmp_path):
    path = tmp_path / "nb.py"
    shutil.copy(fixtures / "notebook.py", path)
    cell = notebook_file.insert_cell(path, "z = pipeline\nzz = x + 1")
    nb = notebook_file.parse(path)
    assert cell.refs == {"pipeline", "x"}
    assert cell.defs == {"z", "zz"}
    assert nb.cells[-1].code.startswith("z = pipeline")
    assert path.read_text(encoding="utf-8").rstrip().endswith("app.run()")
    # insert after a named cell
    notebook_file.insert_cell(path, "q = 1", after=1)
    nb = notebook_file.parse(path)
    assert nb.cells[2].defs == {"q"}
