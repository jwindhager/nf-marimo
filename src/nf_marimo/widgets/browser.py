"""Module browser widget: search nf-core and local modules, copy a ready-made process cell."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import anywidget
import traitlets

from .. import catalog
from ..model import _notebook_dir
from ..snippet import process_cell


class BrowserWidget(anywidget.AnyWidget):
    """Search modules and preview/copy the generated process-cell code."""

    _esm = Path(__file__).with_name("browser.js")
    _css = Path(__file__).with_name("process.css")

    query = traitlets.Unicode("").tag(sync=True)
    results = traitlets.List().tag(sync=True)
    selected = traitlets.Unicode("").tag(sync=True)
    snippet = traitlets.Unicode("").tag(sync=True)
    error = traitlets.Unicode("").tag(sync=True)

    def __init__(self, query: str = "", notebook_dir: Path | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._notebook_dir = notebook_dir or _notebook_dir()
        self.observe(self._search, names="query")
        self.observe(self._select, names="selected")
        self.query = query
        if not query:
            self._search({"new": ""})

    def _search(self, change: dict[str, Any]) -> None:
        try:
            hits = catalog.search(change["new"], notebook_dir=self._notebook_dir, limit=30)
            self.results = [
                {"id": h.id, "description": h.description, "keywords": list(h.keywords)}
                for h in hits
            ]
            self.error = ""
        except Exception as e:
            self.error = str(e)

    def _select(self, change: dict[str, Any]) -> None:
        module_id = change["new"]
        if not module_id:
            self.snippet = ""
            return
        try:
            source, _, name = module_id.partition("/")
            sha = catalog.latest_sha(name) if source == "nf-core" else None
            ref = catalog.resolve(module_id, self._notebook_dir, sha)
            self.snippet = process_cell(module_id, ref.spec, sha=sha)
            self.error = ""
        except Exception as e:
            self.error = str(e)


def browser(query: str = "", notebook_dir: str | Path | None = None) -> Any:
    """Return the module browser as a marimo UI element."""
    import marimo as mo

    return mo.ui.anywidget(BrowserWidget(query, Path(notebook_dir) if notebook_dir else None))
