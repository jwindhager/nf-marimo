"""Collect a notebook's workflow by executing only its Nextflow-relevant cells."""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .. import notebook_file
from ..model import ExportModeError, Pipeline, exporting

PIPELINE_METHODS = {"process", "param", "samplesheet"}


class ExportError(RuntimeError):
    """The notebook cannot be exported."""


@dataclass
class Collected:
    """Result of :func:`collect`."""

    pipeline: Pipeline
    notebook: notebook_file.Notebook
    nf_cells: list[notebook_file.CellInfo]
    executed: list[notebook_file.CellInfo]
    warnings: list[str]


def _nfm_aliases(nb: notebook_file.Notebook) -> tuple[set[str], set[str]]:
    """Names bound to the ``nf_marimo`` module and to its ``pipeline`` function."""
    modules, funcs = set(), set()
    for c in nb.cells:
        for node in ast.walk(ast.parse(c.code or "pass")):
            if isinstance(node, ast.Import):
                for a in node.names:
                    if a.name == "nf_marimo":
                        modules.add(a.asname or a.name)
            elif isinstance(node, ast.ImportFrom) and node.module == "nf_marimo":
                for a in node.names:
                    if a.name == "pipeline":
                        funcs.add(a.asname or a.name)
    return modules, funcs


def impure_statements(cell: notebook_file.CellInfo) -> list[int]:
    """Line numbers (within the cell) of statements that are not part of the workflow.

    Workflow cells should only contain assignments (``x = pipeline.process(...)``, channel
    operators, ...) and bare names (to display a process). Anything else runs on export but
    does not become part of the pipeline.
    """
    lines = []
    for stmt in ast.parse(cell.code or "pass").body:
        if isinstance(stmt, ast.Assign | ast.AnnAssign | ast.Pass):
            continue
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Name | ast.Constant):
            continue
        lines.append(stmt.lineno)
    return lines


def find_nf_cells(nb: notebook_file.Notebook) -> list[notebook_file.CellInfo]:
    """Cells that create the pipeline or call ``<pipeline>.process/param/samplesheet``."""
    modules, funcs = _nfm_aliases(nb)
    pipeline_vars: set[str] = set()
    for c in nb.cells:  # names assigned from nfm.pipeline(...)
        for node in ast.walk(ast.parse(c.code or "pass")):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                f = node.value.func
                is_pipeline = (isinstance(f, ast.Name) and f.id in funcs) or (
                    isinstance(f, ast.Attribute)
                    and f.attr == "pipeline"
                    and isinstance(f.value, ast.Name)
                    and f.value.id in modules
                )
                if is_pipeline:
                    pipeline_vars |= {t.id for t in node.targets if isinstance(t, ast.Name)}
    out = []
    for c in nb.cells:
        for node in ast.walk(ast.parse(c.code or "pass")):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            if isinstance(f, ast.Name) and f.id in funcs:
                out.append(c)
                break
            if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
                if f.value.id in modules and f.attr == "pipeline":
                    out.append(c)
                    break
                if f.value.id in pipeline_vars and f.attr in PIPELINE_METHODS:
                    out.append(c)
                    break
    return out


def collect(path: str | Path) -> Collected:
    """Execute the notebook's Nextflow cells (and their ancestors) and return the pipeline.

    Ordinary analysis cells consuming workflow outputs are descendants of the Nextflow cells
    and are neither executed nor exported.
    """
    path = Path(path).resolve()
    nb = notebook_file.parse(path)
    nf_cells = find_nf_cells(nb)
    if not nf_cells:
        raise ExportError(f"{path}: no nf-marimo cells found (expected nfm.pipeline(...))")
    selected = nb.ancestors(nf_cells)
    if nb.setup is not None and nb.setup not in selected:
        selected.append(nb.setup)
    order = nb.topological(selected)

    ns: dict[str, Any] = {"__file__": str(path), "__name__": "__nfm_export__"}
    # like marimo (and `python notebook.py`), resolve imports relative to the notebook
    sys.path.insert(0, str(path.parent))
    try:
        _exec_cells(order, ns, path)
    finally:
        sys.path.remove(str(path.parent))

    pipelines = {id(v): v for v in ns.values() if isinstance(v, Pipeline)}
    if len(pipelines) != 1:
        raise ExportError(f"expected exactly one nfm.pipeline(...), found {len(pipelines)}")
    warnings = [
        f"{path}: cell at line {cell.lineno}, statement {line}: not part of the pipeline "
        "(keep workflow cells pure: move other code into a separate cell)"
        for cell in nf_cells
        for line in impure_statements(cell)
    ]
    return Collected(next(iter(pipelines.values())), nb, nf_cells, order, warnings)


def _exec_cells(order: list[notebook_file.CellInfo], ns: dict[str, Any], path: Path) -> None:
    with exporting(path.parent):
        for cell in order:
            try:
                exec(compile(cell.code, f"{path}:{cell.lineno}", "exec"), ns)
            except ExportModeError as e:
                raise ExportError(
                    f"cell at line {cell.lineno} is needed by the workflow but runs Nextflow "
                    f"(e.g. calls .values()): {e}"
                ) from e
            except Exception as e:
                raise ExportError(f"cell at line {cell.lineno} failed: {e!r}") from e
