import shutil

from typer.testing import CliRunner

from nf_marimo import notebook_file
from nf_marimo.cli import app

runner = CliRunner()


def test_add_local_module(project, tmp_path):
    shutil.copytree(project, tmp_path / "project")
    nb = tmp_path / "project" / "workflow.py"
    result = runner.invoke(app, ["add", "local/count", str(nb), "--variable", "count2"])
    assert result.exit_code == 0, result.output
    cells = notebook_file.parse(nb).cells
    assert "count2 = pipeline.process(" in cells[-1].code
    assert "count2" in cells[-1].defs


def test_export_without_workflow_fails(fixtures, tmp_path):
    result = runner.invoke(app, ["export", str(fixtures / "notebook.py"), "-o", str(tmp_path)])
    assert result.exit_code == 1
