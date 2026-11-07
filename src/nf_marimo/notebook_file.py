"""Read and edit marimo notebook files using only the stdlib :mod:`ast`.

marimo notebooks are documented plain-Python files::

    app = marimo.App()

    with app.setup:            # optional
        import marimo as mo

    @app.cell
    def _(dep_a, dep_b):       # parameters = references to other cells
        x = dep_a + dep_b
        return (x,)            # (subset of) definitions

    @app.function              # optional top-level functions / classes
    def helper(): ...

We intentionally do not use marimo's private parser (``marimo._ast``).
"""

from __future__ import annotations

import ast
import builtins
import textwrap
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

CellKind = Literal["cell", "setup", "function", "class"]

_BUILTINS = frozenset(dir(builtins))


@dataclass
class CellInfo:
    """A single notebook cell."""

    index: int
    name: str
    kind: CellKind
    code: str
    refs: frozenset[str]
    defs: frozenset[str]
    lineno: int
    end_lineno: int


@dataclass
class Notebook:
    """A parsed notebook."""

    path: Path | None
    source: str
    cells: list[CellInfo] = field(default_factory=list)

    @property
    def setup(self) -> CellInfo | None:
        """The setup cell, if present."""
        return next((c for c in self.cells if c.kind == "setup"), None)

    def definers(self) -> dict[str, CellInfo]:
        """Map every defined name to the cell defining it."""
        return {name: c for c in self.cells for name in c.defs}

    def parents(self, cell: CellInfo) -> list[CellInfo]:
        """Cells whose definitions ``cell`` references."""
        definers = self.definers()
        out = {definers[r].index: definers[r] for r in cell.refs if r in definers}
        out.pop(cell.index, None)
        return [out[i] for i in sorted(out)]

    def ancestors(self, cells: Iterable[CellInfo]) -> list[CellInfo]:
        """Transitive closure of ``cells`` and their parents (sorted by position)."""
        seen: dict[int, CellInfo] = {}
        stack = list(cells)
        while stack:
            c = stack.pop()
            if c.index in seen:
                continue
            seen[c.index] = c
            stack.extend(self.parents(c))
        return [seen[i] for i in sorted(seen)]

    def topological(self, cells: Iterable[CellInfo] | None = None) -> list[CellInfo]:
        """Topologically sort ``cells`` (default: all), setup first, ties by position."""
        subset = {c.index: c for c in (self.cells if cells is None else cells)}
        order: list[CellInfo] = []
        state: dict[int, int] = {}

        def visit(c: CellInfo) -> None:
            if state.get(c.index) == 2:
                return
            if state.get(c.index) == 1:
                raise ValueError(f"cycle detected involving cell {c.name!r} (line {c.lineno})")
            state[c.index] = 1
            for p in self.parents(c):
                if p.index in subset:
                    visit(p)
            state[c.index] = 2
            order.append(c)

        roots = sorted(subset.values(), key=lambda c: (c.kind != "setup", c.index))
        for c in roots:
            visit(c)
        return order


# --------------------------------------------------------------------------- analysis


def _target_names(node: ast.AST) -> set[str]:
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def _bound_names(stmts: Iterable[ast.stmt]) -> set[str]:
    """Names bound at the top level of a block (not inside nested functions/classes)."""
    out: set[str] = set()
    for s in stmts:
        if isinstance(s, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            out.add(s.name)
        elif isinstance(s, ast.Import | ast.ImportFrom):
            for a in s.names:
                out.add((a.asname or a.name).split(".")[0])
        elif isinstance(s, ast.Assign):
            for t in s.targets:
                out |= _target_names(t)
        elif isinstance(s, ast.AugAssign | ast.AnnAssign):
            out |= _target_names(s.target)
        elif isinstance(s, ast.For | ast.AsyncFor):
            out |= _target_names(s.target)
            out |= _bound_names(s.body) | _bound_names(s.orelse)
        elif isinstance(s, ast.While | ast.If):
            out |= _bound_names(s.body) | _bound_names(s.orelse)
        elif isinstance(s, ast.With | ast.AsyncWith):
            for item in s.items:
                if item.optional_vars is not None:
                    out |= _target_names(item.optional_vars)
            out |= _bound_names(s.body)
        elif isinstance(s, ast.Try):
            out |= _bound_names(s.body) | _bound_names(s.orelse) | _bound_names(s.finalbody)
            for h in s.handlers:
                if h.name:
                    out.add(h.name)
                out |= _bound_names(h.body)
        # walrus assignments anywhere at top level
        for n in ast.walk(s):
            if isinstance(n, ast.NamedExpr):
                out.add(n.target.id)
    return out


def _public(names: Iterable[str]) -> frozenset[str]:
    return frozenset(n for n in names if not n.startswith("_"))


def loaded_names(code: str) -> set[str]:
    """All names loaded anywhere in ``code`` (over-approximation of free variables)."""
    tree = ast.parse(code)
    return {n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}


def defined_names(code: str) -> frozenset[str]:
    """Public names defined at the top level of ``code``."""
    return _public(_bound_names(ast.parse(code).body))


def _decorator_kind(fn: ast.FunctionDef | ast.ClassDef) -> CellKind | None:
    for d in fn.decorator_list:
        target = d.func if isinstance(d, ast.Call) else d
        if (
            isinstance(target, ast.Attribute)
            and isinstance(target.value, ast.Name)
            and target.value.id == "app"
        ):
            if target.attr == "cell":
                return "cell"
            if target.attr == "function":
                return "function"
            if target.attr == "class_definition":
                return "class"
    return None


def _segment(lines: list[str], start: int, end: int) -> str:
    return textwrap.dedent("\n".join(lines[start - 1 : end]))


def parse_source(source: str, path: Path | None = None) -> Notebook:
    """Parse notebook ``source`` into a :class:`Notebook`."""
    tree = ast.parse(source)
    lines = source.splitlines()
    nb = Notebook(path=path, source=source)
    for node in tree.body:
        if (
            isinstance(node, ast.With)
            and len(node.items) == 1
            and isinstance(node.items[0].context_expr, ast.Attribute)
            and node.items[0].context_expr.attr == "setup"
        ):
            body = node.body
            code = _segment(lines, body[0].lineno, body[-1].end_lineno or body[-1].lineno)
            if code.strip() == "pass":
                code = ""
            nb.cells.append(
                CellInfo(
                    index=len(nb.cells),
                    name="setup",
                    kind="setup",
                    code=code,
                    refs=frozenset(),
                    defs=_public(_bound_names(body)),
                    lineno=node.lineno,
                    end_lineno=node.end_lineno or node.lineno,
                )
            )
            continue
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            continue
        kind = _decorator_kind(node)  # type: ignore[arg-type]
        if kind is None:
            continue
        start = min([d.lineno for d in node.decorator_list] + [node.lineno])
        end = node.end_lineno or node.lineno
        if kind in ("function", "class"):
            code = _segment(lines, node.lineno, end)
            refs = frozenset(loaded_names(code) - _BUILTINS - {node.name})
            nb.cells.append(
                CellInfo(
                    len(nb.cells), node.name, kind, code, refs, frozenset({node.name}), start, end
                )
            )
            continue
        assert isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        body = list(node.body)
        returned: set[str] = set()
        if body and isinstance(body[-1], ast.Return):
            ret = body.pop()
            assert isinstance(ret, ast.Return)
            if ret.value is not None:
                returned = _target_names(ret.value)
        code = (
            _segment(lines, body[0].lineno, body[-1].end_lineno or body[-1].lineno) if body else ""
        )
        if code.strip() == "pass":
            code = ""
        refs = frozenset(a.arg for a in node.args.args)
        defs = _public(_bound_names(body) | returned)
        nb.cells.append(CellInfo(len(nb.cells), node.name, "cell", code, refs, defs, start, end))
    return nb


def parse(path: str | Path) -> Notebook:
    """Parse the marimo notebook at ``path``."""
    p = Path(path)
    return parse_source(p.read_text(encoding="utf-8"), p)


# --------------------------------------------------------------------------- editing


def render_cell(code: str, refs: Iterable[str], defs: Iterable[str], name: str = "_") -> str:
    """Render ``code`` as an ``@app.cell`` function in marimo's file format."""
    params = ", ".join(sorted(set(refs)))
    body = textwrap.indent(textwrap.dedent(code).strip("\n"), "    ") or "    pass"
    d = sorted(set(defs))
    ret = "    return\n" if not d else f"    return ({', '.join(d)},)\n"
    return f"@app.cell\ndef {name}({params}):\n{body}\n{ret}"


def insert_cell(path: str | Path, code: str, after: str | int | None = None) -> CellInfo:
    """Insert ``code`` as a new cell into the notebook at ``path``.

    Parameters
    ----------
    path
        Notebook file.
    code
        Cell body.
    after
        Name or index of the cell after which to insert; default: append as last cell.

    Returns
    -------
    CellInfo
        The inserted cell (as re-parsed from the updated file).

    """
    p = Path(path)
    nb = parse(p)
    definers = nb.definers()
    new_defs = defined_names(code)
    refs = {n for n in loaded_names(code) if n in definers and n not in new_defs}
    text = render_cell(code, refs, new_defs)

    lines = nb.source.splitlines(keepends=True)
    if after is None:
        # before the ``if __name__ == "__main__":`` guard (or at the end)
        insert_at = len(lines)
        for i, line in enumerate(lines):
            if line.startswith("if __name__"):
                insert_at = i
                break
    else:
        target = (
            nb.cells[after]
            if isinstance(after, int)
            else next((c for c in nb.cells if c.name == after), None)
        )
        if target is None:
            raise KeyError(f"no cell named {after!r}")
        insert_at = target.end_lineno
    chunk = ("\n\n" if insert_at and lines[insert_at - 1].strip() else "") + text + "\n\n"
    new_source = "".join(lines[:insert_at]) + chunk + "".join(lines[insert_at:]).lstrip("\n")
    p.write_text(new_source, encoding="utf-8")
    new_nb = parse(p)
    return next(c for c in new_nb.cells if c.lineno > insert_at)
