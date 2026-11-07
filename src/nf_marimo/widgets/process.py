"""Interactive widget for a process cell: wiring status, *Run* button, log and results."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import anywidget
import traitlets

if TYPE_CHECKING:
    from ..model import Process

_ESM = Path(__file__).with_name("process.js")
_CSS = Path(__file__).with_name("process.css")


def _describe(value: Any) -> str:
    from ..codegen import input_expr
    from ..model import Channel, Param

    if isinstance(value, Channel | Param):
        return input_expr(value, test=True)
    return repr(value)


def _render_value(v: Any) -> str:
    if isinstance(v, list):
        return "[" + ", ".join(_render_value(x) for x in v) + "]"
    if isinstance(v, dict):
        return "[" + ", ".join(f"{k}:{x}" for k, x in v.items()) + "]"
    return str(v)


class ProcessWidget(anywidget.AnyWidget):
    """Widget showing a process' wiring and, once its cell has run, its results."""

    _esm = _ESM
    _css = _CSS

    title = traitlets.Unicode("").tag(sync=True)
    module = traitlets.Unicode("").tag(sync=True)
    description = traitlets.Unicode("").tag(sync=True)
    inputs = traitlets.List().tag(sync=True)
    outputs = traitlets.List().tag(sync=True)
    problems = traitlets.List().tag(sync=True)
    status = traitlets.Unicode("not run").tag(sync=True)  # not run | done
    results = traitlets.Dict().tag(sync=True)

    def __init__(self, process: Process, **kwargs: Any) -> None:
        spec = process.spec
        super().__init__(
            title=process.alias,
            module=process.module.id + (f"@{process.module.sha[:7]}" if process.module.sha else ""),
            description=spec.description,
            inputs=[
                {
                    "key": ch.key,
                    "elements": [f"{e.name}:{e.type}" for e in ch.elements],
                    "description": ch.description,
                    "connected": ch.key in process.inputs,
                    "source": _describe(process.inputs[ch.key]) if ch.key in process.inputs else "",
                }
                for ch in spec.inputs
            ],
            outputs=[
                {"emit": o.emit, "elements": [e.name for e in o.elements]}
                for o in spec.outputs
                if not o.is_versions
            ],
            problems=list(process.problems),
            **kwargs,
        )
        self._process = process
        self.refresh()

    def refresh(self) -> None:
        """Update the displayed results from the process."""
        res = self._process.results
        if res is None:
            self.status = "not run"
            self.results = {}
        else:
            self.status = "done"
            self.results = {
                emit: [_render_value(item) for item in items] for emit, items in res.items()
            }
