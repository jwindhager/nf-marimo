"""Run generated wrapper workflows with Nextflow (per-cell test mode)."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import threading
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from .codegen import parse_index, render_wrapper
from .model import Channel, ExportModeError, Pipeline, export_mode

_LOCKS: dict[Path, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


class NextflowError(RuntimeError):
    """A Nextflow run failed."""

    def __init__(self, message: str, log: str) -> None:
        super().__init__(message)
        self.log = log


def nextflow_bin() -> str:
    """Path to the ``nextflow`` executable (``$NFM_NEXTFLOW`` or on ``PATH``)."""
    exe = os.environ.get("NFM_NEXTFLOW") or shutil.which("nextflow")
    if not exe:
        hint = "run nf-marimo inside WSL2" if os.name == "nt" else "install it (`pixi install`)"
        raise FileNotFoundError(f"nextflow not found; {hint} (Nextflow requires a Unix shell)")
    return exe


def _lock(path: Path) -> threading.Lock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(path.resolve(), threading.Lock())


def _module_digest(pipeline: Pipeline, targets: Sequence[Channel]) -> str:
    h = hashlib.sha256()
    procs = {id(p): p for t in targets for p in t.upstream_processes()}
    for p in sorted(procs.values(), key=lambda p: p.order):
        for f in sorted(p.module.directory.rglob("*")):
            if f.is_file() and "tests" not in f.parts:
                h.update(str(f.relative_to(p.module.directory)).encode())
                h.update(f.read_bytes())
    return h.hexdigest()


def _session_id(state: Path) -> str | None:
    f = state / "session"
    return f.read_text(encoding="utf-8").strip() if f.exists() else None


def _record_session(state: Path) -> None:
    history = state / ".nextflow" / "history"
    if _session_id(state) or not history.exists():
        return
    last = [line for line in history.read_text(encoding="utf-8").splitlines() if line.strip()][-1]
    # columns: timestamp, duration, run name, status, revision, session id, command
    session = last.split("\t")[5].strip()
    (state / "session").write_text(session + "\n", encoding="utf-8")


def _emit(on_log: Callable[[str], None] | None, line: str) -> None:
    if on_log is not None:
        on_log(line)


def run_channels(
    pipeline: Pipeline,
    targets: Sequence[Channel],
    on_log: Callable[[str], None] | None = None,
    force: bool = False,
) -> list[list[Any]]:
    """Materialize ``targets`` by running a wrapper workflow; return one value list per target.

    Results are cached: if the wrapper script, config and involved module files are unchanged
    and a previous run's outputs still exist, Nextflow is not invoked at all. Otherwise the run
    resumes the notebook's persistent Nextflow session, so upstream tasks come from the cache.
    """
    if export_mode():
        raise ExportModeError("Nextflow runs are disabled while exporting")
    script, config = render_wrapper(pipeline, targets)
    digest = hashlib.sha256(
        (script + config + _module_digest(pipeline, targets)).encode()
    ).hexdigest()[:16]
    state = pipeline.work_dir
    run_dir = state / "runs" / digest
    out_dir = run_dir / "out"
    indexes = [out_dir / f"out_{i}.json" for i in range(len(targets))]

    with _lock(state):
        if not force and all(i.exists() for i in indexes):
            try:
                results = [parse_index(i) for i in indexes]
                _emit(on_log, f"[nf-marimo] cached results from {run_dir}")
                return results
            except Exception:
                pass

        run_dir.mkdir(parents=True, exist_ok=True)
        (state / ".gitignore").write_text("*\n", encoding="utf-8")
        (run_dir / "main.nf").write_text(script, encoding="utf-8")
        (run_dir / "nextflow.config").write_text(config, encoding="utf-8")
        cmd = [
            nextflow_bin(),
            "-log",
            str(run_dir / ".nextflow.log"),
            "run",
            str(run_dir / "main.nf"),
            "-c",
            str(run_dir / "nextflow.config"),
            "-work-dir",
            str(state / "work"),
            "-output-dir",
            str(out_dir),
            "-ansi-log",
            "false",
        ]
        session = _session_id(state)
        if session:
            cmd += ["-resume", session]
        _emit(on_log, "$ " + " ".join(cmd))
        proc = subprocess.Popen(
            cmd,
            cwd=state,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env={**os.environ, "NXF_ANSI_LOG": "false"},
        )
        log: list[str] = []
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip("\n")
            log.append(line)
            _emit(on_log, line)
        code = proc.wait()
        _record_session(state)
        if code != 0:
            tail = "\n".join(log[-60:])
            raise NextflowError(f"Nextflow failed with exit code {code}\n{tail}", "\n".join(log))
        return [parse_index(i) if i.exists() else [] for i in indexes]
