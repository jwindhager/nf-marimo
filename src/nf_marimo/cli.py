"""``nfm`` command line interface."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Annotated

import typer

from . import catalog, notebook_file
from .snippet import process_cell

app = typer.Typer(help="nf-marimo: build nf-core pipelines using marimo.", no_args_is_help=True)


@app.command()
def search(
    query: Annotated[str, typer.Argument(help="search terms (name, keywords, description)")] = "",
    notebook_dir: Annotated[Path, typer.Option(help="directory with modules/local")] = Path(),
    limit: int = 30,
) -> None:
    """Search nf-core and local modules."""
    for e in catalog.search(query, notebook_dir=notebook_dir, limit=limit):
        typer.echo(f"{e.id:40s} {e.description[:80]}")


@app.command()
def add(
    module: Annotated[str, typer.Argument(help="e.g. nf-core/cellpose or local/my_module")],
    notebook: Annotated[Path, typer.Argument(help="marimo notebook to add the cell to")],
    after: Annotated[str | None, typer.Option(help="insert after the cell with this name")] = None,
    variable: Annotated[str | None, typer.Option(help="Python variable of the process")] = None,
    pipeline_var: Annotated[str, typer.Option(help="variable holding the pipeline")] = "pipeline",
) -> None:
    """Insert a pre-filled process cell for MODULE into NOTEBOOK."""
    source, _, name = module.partition("/")
    sha = catalog.latest_sha(name) if source == "nf-core" else None
    ref = catalog.resolve(module, notebook.resolve().parent, sha)
    code = process_cell(module, ref.spec, sha=sha, variable=variable, pipeline_var=pipeline_var)
    cell = notebook_file.insert_cell(notebook, code, after=after)
    typer.echo(f"added {module} at {notebook}:{cell.lineno}")


@app.command()
def export(
    notebook: Annotated[Path, typer.Argument(help="marimo notebook")],
    outdir: Annotated[Path, typer.Option("--outdir", "-o", help="pipeline output directory")],
    force: Annotated[bool, typer.Option(help="overwrite OUTDIR")] = False,
    lint: Annotated[bool, typer.Option(help="run nf-core pipelines lint")] = False,
    test: Annotated[bool, typer.Option(help="run the pipeline with -profile test")] = False,
    profile: Annotated[str, typer.Option(help="profile for --test")] = "docker",
) -> None:
    """Convert NOTEBOOK into an nf-core pipeline (non-Nextflow cells are ignored)."""
    from .export import ExportError
    from .export import export as do_export

    try:
        out = do_export(notebook, outdir, force=force, lint=lint, test=test, profile=profile)
    except ExportError as e:
        typer.secho(str(e), fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from e
    typer.secho(f"exported pipeline to {out}", fg=typer.colors.GREEN)
    typer.echo(f"run it with: nextflow run {out} -profile test,{profile} --outdir results")


@app.command()
def doctor() -> None:
    """Check that the external tools are available."""
    ok = True
    for tool, args in [
        ("nextflow", ["-version"]),
        ("java", ["-version"]),
        ("nf-core", ["--version"]),
        ("nf-test", ["version"]),
        ("docker", ["info", "--format", "{{.ServerVersion}}"]),
    ]:
        exe = shutil.which(tool)
        if exe is None:
            typer.secho(f"✗ {tool}: not found", fg=typer.colors.RED)
            ok = False
            continue
        proc = subprocess.run([exe, *args], capture_output=True, text=True, check=False)
        out = (proc.stdout + proc.stderr).strip().splitlines()
        info = next((line.strip() for line in out if any(c.isdigit() for c in line)), "")
        color = typer.colors.GREEN if proc.returncode == 0 else typer.colors.RED
        ok &= proc.returncode == 0
        typer.secho(f"{'✓' if proc.returncode == 0 else '✗'} {tool}: {info}", fg=color)
    try:
        catalog.search("", sources=("nf-core",), limit=1)
        typer.secho("✓ nf-core module index reachable", fg=typer.colors.GREEN)
    except Exception as e:
        typer.secho(f"✗ nf-core module index: {e}", fg=typer.colors.RED)
        ok = False
    raise typer.Exit(0 if ok else 1)


if __name__ == "__main__":
    app()
