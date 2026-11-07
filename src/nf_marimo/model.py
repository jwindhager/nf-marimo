"""Symbolic workflow model: pipelines, params, samplesheets, processes and channels.

Building these objects never runs anything. Channels are materialized lazily via
:meth:`Channel.values` (or a process widget's *Run* button), which runs Nextflow on a generated
wrapper workflow containing the target and everything upstream of it.
"""

from __future__ import annotations

import csv
import io
import os
import shutil
import threading
import warnings
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import httpx

from . import catalog
from .meta import ModuleSpec

ParamType = Literal["string", "integer", "number", "boolean", "file", "directory"]
ColumnType = Literal["string", "uri", "file"]


class ExportModeError(RuntimeError):
    """Raised when trying to run Nextflow while a notebook is being exported."""


# Export state is thread-local so that exporting from inside a running notebook kernel
# (export widget) does not affect other cells.
_EXPORT = threading.local()


def export_mode() -> bool:
    """Whether the notebook is currently being executed by ``nfm export`` (in this thread)."""
    return bool(getattr(_EXPORT, "active", False)) or os.environ.get("NFM_MODE") == "export"


@contextmanager
def exporting(notebook_dir: Path) -> Iterator[None]:
    """Mark the current thread as exporting the notebook in ``notebook_dir``."""
    prev = (getattr(_EXPORT, "active", False), getattr(_EXPORT, "notebook_dir", None))
    _EXPORT.active, _EXPORT.notebook_dir = True, notebook_dir
    try:
        yield
    finally:
        _EXPORT.active, _EXPORT.notebook_dir = prev


def _in_notebook() -> bool:
    try:
        import marimo as mo

        return bool(mo.running_in_notebook())
    except Exception:
        return False


def _notebook_dir() -> Path:
    local = getattr(_EXPORT, "notebook_dir", None)
    if local is not None:
        return Path(local)
    env = os.environ.get("NFM_NOTEBOOK_DIR")
    if env:
        return Path(env)
    try:
        import marimo as mo

        d = mo.notebook_dir()
        if d is not None:
            return Path(d)
    except Exception:
        pass
    return Path.cwd()


# --------------------------------------------------------------------------- channels


@dataclass(frozen=True)
class Op:
    """A Groovy operator applied to a channel, e.g. ``map { ... }`` or ``join({0})``.

    ``{0}``, ``{1}``, ... in ``template`` are replaced by the expressions of ``args``.
    """

    template: str
    args: tuple[Channel, ...] = ()


@dataclass(frozen=True, eq=False)
class Channel:
    """A symbolic Nextflow channel expression."""

    pipeline: Pipeline
    kind: Literal["samplesheet", "output", "param"]
    ref: Any  # Samplesheet | tuple[Process, str] | Param
    ops: tuple[Op, ...] = ()

    # -- operators ------------------------------------------------------------------------
    def op(self, groovy: str, *args: Channel) -> Channel:
        """Apply a raw Groovy operator (without leading dot), e.g. ``"map { m, f -> f }"``."""
        return Channel(self.pipeline, self.kind, self.ref, (*self.ops, Op(groovy, args)))

    def map(self, closure: str) -> Channel:
        """``.map { ... }`` with a Groovy closure body (braces optional)."""
        body = closure.strip()
        return self.op(f"map {body}" if body.startswith("{") else f"map {{ {body} }}")

    def collect(self) -> Channel:
        """``.collect()``."""
        return self.op("collect()")

    def first(self) -> Channel:
        """``.first()``."""
        return self.op("first()")

    def mix(self, *others: Channel) -> Channel:
        """``.mix(a, b, ...)``."""
        placeholders = ", ".join(f"{{{i}}}" for i in range(len(others)))
        return self.op(f"mix({placeholders})", *others)

    def join(self, other: Channel, by: int = 0) -> Channel:
        """``.join(other, by: n)``."""
        return self.op(f"join({{0}}, by: {by})", other)

    # -- graph ----------------------------------------------------------------------------
    def upstream_processes(self) -> list[Process]:
        """Return the processes this channel (transitively) depends on, in creation order."""
        seen: dict[int, Process] = {}

        def visit_channel(ch: Channel) -> None:
            if ch.kind == "output":
                visit_process(ch.ref[0])
            for op in ch.ops:
                for a in op.args:
                    visit_channel(a)

        def visit_process(p: Process) -> None:
            if id(p) in seen:
                return
            seen[id(p)] = p
            for v in p.inputs.values():
                if isinstance(v, Channel):
                    visit_channel(v)

        visit_channel(self)
        return sorted(seen.values(), key=lambda p: p.order)

    # -- materialization ------------------------------------------------------------------
    def values(self) -> list[Any]:
        """Run Nextflow (cached) and return the channel's items as Python values."""
        from .runner import run_channels

        if self.kind == "output" and not self.ops:
            proc, emit = self.ref
            if proc.results is not None and emit in proc.results:
                return proc.results[emit]
        return run_channels(self.pipeline, [self])[0]

    def __repr__(self) -> str:
        from .codegen import channel_expr

        return f"<Channel {channel_expr(self, test=True)}>"


# --------------------------------------------------------------------------- params & inputs


@dataclass(eq=False)
class Param:
    """A pipeline parameter (``params.<name>``)."""

    pipeline: Pipeline
    name: str
    default: Any = None
    type: ParamType = "string"
    description: str = ""
    test: Any = None

    @property
    def test_value(self) -> Any:
        """Value used in per-cell test runs and ``conf/test.config``."""
        return self.default if self.test is None else self.test

    @property
    def channel(self) -> Channel:
        """The parameter as a (value) channel expression."""
        return Channel(self.pipeline, "param", self)


class _ParamNamespace:
    def __init__(self, pipeline: Pipeline) -> None:
        self._pipeline = pipeline

    def __getattr__(self, name: str) -> Param:
        try:
            return self._pipeline._params[name]
        except KeyError:
            raise AttributeError(
                f"no param {name!r}; declare it with pipeline.param(...)"
            ) from None

    def __iter__(self) -> Iterator[Param]:
        return iter(self._pipeline._params.values())


@dataclass(eq=False)
class Samplesheet:
    """A samplesheet parameter (CSV), read with nf-schema in the exported pipeline.

    ``columns`` maps CSV column names to their role: ``"meta.<key>"`` (stored in the meta map),
    ``"string"``, ``"uri"`` (string, local path or remote URI) or ``"file"`` (staged path).
    The resulting channel emits ``[meta, <non-meta columns in order>...]``.

    ``test`` holds the example data used for test runs (and the exported ``-profile test``):
    rows defined in the notebook (list of dicts or a pandas DataFrame), or a CSV path/URL.
    """

    pipeline: Pipeline
    name: str
    columns: dict[str, str]
    test: TestData
    description: str = ""

    @property
    def test_is_file(self) -> bool:
        """Whether the test data is a CSV path/URL (rather than rows in the notebook)."""
        return isinstance(self.test, str | Path)

    @property
    def meta_columns(self) -> dict[str, str]:
        """CSV column -> meta key."""
        return {c: t.split(".", 1)[1] for c, t in self.columns.items() if t.startswith("meta.")}

    @property
    def value_columns(self) -> dict[str, str]:
        """CSV column -> type, for non-meta columns."""
        return {c: t for c, t in self.columns.items() if not t.startswith("meta.")}

    def read_test_rows(self) -> list[dict[str, str]]:
        """Return the test rows (from the notebook, or a CSV path relative to it, or a URL)."""
        test: Any = self.test
        if not self.test_is_file:
            records: list[dict[str, Any]] = (
                test.to_dict("records") if hasattr(test, "to_dict") else list(test)
            )
            rows = [{str(k): "" if v is None else str(v) for k, v in r.items()} for r in records]
            missing = {c for r in rows for c in self.columns if c not in r}
            if missing:
                raise ValueError(f"test samples lack column(s) {sorted(missing)}")
            return rows
        src = str(self.test)
        if "://" in src and not src.startswith("file://"):
            text = httpx.get(src, timeout=60, follow_redirects=True).text
        else:
            p = Path(src.removeprefix("file://"))
            text = (p if p.is_absolute() else self.pipeline.notebook_dir / p).read_text(
                encoding="utf-8"
            )
        return list(csv.DictReader(io.StringIO(text)))

    @property
    def channel(self) -> Channel:
        """The samplesheet channel."""
        return Channel(self.pipeline, "samplesheet", self)


# --------------------------------------------------------------------------- processes

TestData = str | Path | list[dict[str, Any]] | Any  # Any: pandas.DataFrame
InputValue = Channel | Param | str | int | float | bool | list | dict | Path | None


class _Outputs:
    def __init__(self, process: Process) -> None:
        self._process = process

    def __getattr__(self, emit: str) -> Channel:
        spec = self._process.spec
        if emit not in [o.emit for o in spec.outputs]:
            raise AttributeError(
                f"{self._process.alias} has no output {emit!r}; outputs: {spec.output_emits}"
            )
        return Channel(self._process.pipeline, "output", (self._process, emit))

    def __dir__(self) -> list[str]:
        return self._process.spec.output_emits

    def __iter__(self) -> Iterator[Channel]:
        return (getattr(self, e) for e in self._process.spec.output_emits)


@dataclass(eq=False)
class Process:
    """A Nextflow process (module invocation) in the workflow."""

    pipeline: Pipeline
    module: catalog.ModuleRef
    inputs: dict[str, InputValue]
    ext_args: str | None = None
    ext_prefix: str | None = None
    name: str | None = None
    publish: bool = True
    order: int = 0
    problems: list[str] = field(default_factory=list)
    results: dict[str, list[Any]] | None = None
    _widget: Any = None

    def __post_init__(self) -> None:
        spec = self.spec
        unknown = set(self.inputs) - set(spec.input_keys)
        if unknown:
            raise KeyError(
                f"{self.module.id}: unknown input(s) {sorted(unknown)}; inputs: {spec.input_keys}"
            )
        for key in spec.input_keys:
            if key not in self.inputs:
                self.problems.append(f"input {key!r} is not connected")
        for p in self.problems:
            warnings.warn(f"{self.alias}: {p}", stacklevel=3)

    @property
    def spec(self) -> ModuleSpec:
        """Module metadata."""
        return self.module.spec

    @property
    def process_name(self) -> str:
        """Process name as defined in the module."""
        return self.module.process_name

    @property
    def alias(self) -> str:
        """Unique process name in the workflow (``include { X as alias }``)."""
        return (self.name or self.process_name).upper()

    @property
    def out(self) -> _Outputs:
        """Output channels, e.g. ``proc.out.<emit>``."""
        return _Outputs(self)

    def upstream(self) -> list[Process]:
        """Return this process and everything upstream of it."""
        procs: dict[int, Process] = {id(self): self}
        for v in self.inputs.values():
            if isinstance(v, Channel):
                for p in v.upstream_processes():
                    procs[id(p)] = p
        return sorted(procs.values(), key=lambda p: p.order)

    def run(self, on_log: Callable[[str], None] | None = None) -> dict[str, list[Any]]:
        """Run this process (and its upstream) in test mode; return values per output."""
        from .runner import run_channels

        outs = list(self.out)
        results = run_channels(self.pipeline, outs, on_log=on_log)
        self.results = {e: r for e, r in zip(self.spec.output_emits, results, strict=True)}
        if self._widget is not None:
            self._widget.refresh()
        return self.results

    def run_in_cell(self) -> None:
        """Run with a live progress indicator in the current marimo cell."""
        import marimo as mo

        with mo.status.spinner(title=f"Running {self.alias} …", remove_on_exit=True) as sp:

            def on_log(line: str) -> None:
                if line.startswith(("[", "$", "ERROR")):
                    sp.update(subtitle=line[:160])

            self.run(on_log=on_log)

    @property
    def widget(self) -> Any:
        """The interactive process widget (an anywidget)."""
        if self._widget is None:
            from .widgets.process import ProcessWidget

            self._widget = ProcessWidget(self)
        return self._widget

    def _display_(self) -> Any:
        import marimo as mo

        return mo.ui.anywidget(self.widget)

    def __repr__(self) -> str:
        return f"<Process {self.alias} ({self.module.id})>"


# --------------------------------------------------------------------------- pipeline


class Pipeline:
    """Registry of a notebook's workflow: params, samplesheets and processes."""

    def __init__(
        self,
        name: str,
        *,
        description: str = "",
        author: str = "",
        org: str = "nf-marimo",
        version: str = "0.1.0dev",
        profile: Literal["docker", "conda", "none"] = "docker",
        gpu: bool | Literal["auto"] = "auto",
        notebook_dir: str | Path | None = None,
        config: str = "",
    ) -> None:
        if not name.isidentifier() or not name.islower():
            raise ValueError("pipeline name must be a lowercase identifier, e.g. 'mypipeline'")
        self.name = name
        self.description = description or f"{name} pipeline (generated with nf-marimo)"
        self.author = author
        self.org = org
        self.version = version
        self.profile = profile
        # test runs only: request GPUs for `process_gpu` processes
        # (auto: $NFM_GPU if set to 0/1, else whether an NVIDIA driver is present)
        if gpu == "auto":
            env = os.environ.get("NFM_GPU")
            gpu = env == "1" if env in ("0", "1") else shutil.which("nvidia-smi") is not None
        self.gpu = gpu
        self.notebook_dir = Path(notebook_dir) if notebook_dir else _notebook_dir()
        self.config = config
        self._params: dict[str, Param] = {}
        self.samplesheets: dict[str, Samplesheet] = {}
        self.processes: list[Process] = []
        self.params = _ParamNamespace(self)

    @property
    def work_dir(self) -> Path:
        """Per-notebook state directory (``.nfm``)."""
        return self.notebook_dir / ".nfm"

    def param(
        self,
        name: str,
        default: Any = None,
        *,
        type: ParamType | None = None,
        description: str = "",
        test: Any = None,
    ) -> Param:
        """Declare a pipeline parameter."""
        if type is None:
            type = (
                "boolean"
                if isinstance(default, bool)
                else "integer"
                if isinstance(default, int)
                else "number"
                if isinstance(default, float)
                else "string"
            )
        p = Param(self, name, default, type, description, test)
        self._params[name] = p
        return p

    def samplesheet(
        self,
        name: str = "input",
        *,
        columns: dict[str, str],
        test: TestData,
        description: str = "Path to comma-separated file containing information about the samples",
    ) -> Channel:
        """Declare a samplesheet parameter and return its channel."""
        if name in self.samplesheets:
            raise ValueError(f"samplesheet {name!r} already declared")
        if not any(t == "meta.id" for t in columns.values()):
            raise ValueError("one samplesheet column must map to 'meta.id'")
        s = Samplesheet(self, name, columns, test, description)
        self.samplesheets[name] = s
        return s.channel

    def process(
        self,
        module: str,
        inputs: dict[str, InputValue] | None = None,
        *,
        sha: str | None = None,
        ext_args: str | None = None,
        ext_prefix: str | None = None,
        name: str | None = None,
        publish: bool = True,
        run: bool | Literal["auto"] = "auto",
    ) -> Process:
        """Add a module invocation (``nf-core/<name>`` or ``local/<name>``) to the workflow.

        With ``run="auto"`` the process is test-run (on the samplesheet's test data, cached)
        when its notebook cell runs: running the cell runs the workflow step. It is not run
        outside a marimo notebook, during export, or while inputs are unconnected.
        """
        ref = catalog.resolve(module, self.notebook_dir, sha)
        proc = Process(
            self,
            ref,
            dict(inputs or {}),
            ext_args=ext_args,
            ext_prefix=ext_prefix,
            name=name,
            publish=publish,
            order=len(self.processes),
        )
        # notebook cells may re-run: replace an existing process with the same alias
        self.processes = [p for p in self.processes if p.alias != proc.alias]
        proc.order = max((p.order for p in self.processes), default=-1) + 1
        self.processes.append(proc)
        if run == "auto":
            run = _in_notebook() and not export_mode() and not proc.problems
        if run:
            proc.run_in_cell() if _in_notebook() else proc.run()
        return proc

    def __repr__(self) -> str:
        return f"<Pipeline {self.name}: {len(self.processes)} process(es)>"


def pipeline(name: str, **kwargs: Any) -> Pipeline:
    """Create the notebook's :class:`Pipeline` (one per notebook)."""
    return Pipeline(name, **kwargs)
