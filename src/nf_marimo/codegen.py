"""Groovy/Nextflow code generation shared by per-cell test runs and pipeline export."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Any

from .model import Channel, Param, Pipeline, Process, Samplesheet

INDENT = "    "
SAVE_AS = "{ filename -> filename.equals('versions.yml') ? null : filename }"

# nf-core base.config-like label defaults for test runs, capped to the local machine
TEST_RESOURCES = """\
process {
    resourceLimits = [cpus: Runtime.runtime.availableProcessors(), memory: 16.GB]
    cpus = 1
    memory = 4.GB
    withLabel: 'process_single' {
        cpus = 1
    }
    withLabel: 'process_low' {
        cpus = 2
        memory = 8.GB
    }
    withLabel: 'process_medium' {
        cpus = 6
        memory = 16.GB
    }
    withLabel: 'process_high' {
        cpus = 12
        memory = 16.GB
    }
}"""


# --------------------------------------------------------------------------- literals


def groovy_string(s: str) -> str:
    """Single-quoted Groovy string literal."""
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"


def groovy_literal(v: Any) -> str:
    """Render a Python value as a Groovy literal."""
    if v is None:
        return "[]"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int | float):
        return repr(v)
    if isinstance(v, str):
        return groovy_string(v)
    if isinstance(v, Path):
        return f"file({groovy_string(str(v))}, checkIfExists: true)"
    if isinstance(v, list | tuple):
        return "[" + ", ".join(groovy_literal(x) for x in v) + "]"
    if isinstance(v, dict):
        if not v:
            return "[:]"
        return "[" + ", ".join(f"{k}: {groovy_literal(x)}" for k, x in v.items()) + "]"
    raise TypeError(f"cannot convert {type(v).__name__} to a Groovy literal: {v!r}")


def ext_value(s: str) -> str:
    """Value for ``ext.args``/``ext.prefix``: a closure when it interpolates (``${...}``)."""
    if "${" in s:
        return '{ "' + s.replace("\\", "\\\\").replace('"', '\\"') + '" }'
    return groovy_string(s)


# --------------------------------------------------------------------------- expressions


def samplesheet_var(s: Samplesheet, *, test: bool) -> str:
    """Workflow variable holding a samplesheet channel."""
    return f"ch_{s.name}" if test else "ch_samplesheet"


def param_expr(p: Param) -> str:
    """Expression for a param used as a process input."""
    if p.type in ("file", "directory"):
        return f"file(params.{p.name}, checkIfExists: true)"
    return f"params.{p.name}"


def channel_expr(ch: Channel, *, test: bool) -> str:
    """Expression for a channel (including operators)."""
    if ch.kind == "samplesheet":
        base = samplesheet_var(ch.ref, test=test)
    elif ch.kind == "output":
        proc, emit = ch.ref
        base = f"{proc.alias}.out.{emit}"
    elif ch.kind == "param":
        base = f"channel.value({param_expr(ch.ref)})"
    else:  # pragma: no cover
        raise ValueError(ch.kind)
    for op in ch.ops:
        args = [channel_expr(a, test=test) for a in op.args]
        rendered = op.template.format(*args) if args else op.template
        rendered = rendered.replace("\n", "\n" + INDENT)
        base = f"{base}\n{INDENT}.{rendered}"
    return base


def input_expr(value: Any, *, test: bool) -> str:
    """Expression for a process input value."""
    if isinstance(value, Channel):
        return channel_expr(value, test=test)
    if isinstance(value, Param):
        return param_expr(value)
    return groovy_literal(value)


def process_call(proc: Process, *, test: bool) -> str:
    """``ALIAS(input1, input2, ...)`` with inputs in positional order."""
    args = []
    for key in proc.spec.input_keys:
        if key not in proc.inputs:
            raise ValueError(f"{proc.alias}: input {key!r} is not connected")
        expr = input_expr(proc.inputs[key], test=test)
        args.append(INDENT + expr.replace("\n", "\n" + INDENT))
    return f"{proc.alias}(\n" + ",\n".join(args) + "\n)"


def include_lines(procs: Iterable[Process], module_path: Callable[[Process], str]) -> list[str]:
    """``include { NAME as ALIAS } from '<path>'`` lines."""
    lines = []
    for p in procs:
        name = p.process_name
        clause = name if p.alias == name else f"{name} as {p.alias}"
        lines.append(f"include {{ {clause} }} from {groovy_string(module_path(p))}")
    return lines


def ext_config(procs: Iterable[Process], *, publish_dirs: bool = False) -> str:
    """``process { withName: ... }`` config block for ``ext.*`` (and ``publishDir``)."""
    blocks = []
    for p in procs:
        settings = []
        if p.ext_args:
            settings.append(f"ext.args = {ext_value(p.ext_args)}")
        if p.ext_prefix:
            settings.append(f"ext.prefix = {ext_value(p.ext_prefix)}")
        if publish_dirs:
            if p.publish:
                settings.append(
                    "publishDir = [\n"
                    f'{INDENT}path: {{ "${{params.outdir}}/{p.alias.lower()}" }},\n'
                    f"{INDENT}mode: params.publish_dir_mode,\n"
                    f"{INDENT}saveAs: {SAVE_AS}\n"
                    "]"
                )
            else:
                settings.append("publishDir = [enabled: false]")
        if settings:
            body = "\n".join(INDENT + s.replace("\n", "\n" + INDENT) for s in settings)
            blocks.append(f"withName: '{p.alias}' {{\n{body}\n}}")
    if not blocks:
        return ""
    inner = "\n\n".join(INDENT + b.replace("\n", "\n" + INDENT) for b in blocks)
    return "process {\n" + inner + "\n}\n"


# --------------------------------------------------------------------------- test wrapper


def samplesheet_rows_literal(s: Samplesheet) -> list[str]:
    """Literal channel items (``[meta, values...]``) from the test samplesheet."""
    items = []
    for row in s.read_test_rows():
        meta = {key: row[col] for col, key in s.meta_columns.items()}
        values = []
        for col, typ in s.value_columns.items():
            v = row.get(col, "")
            if typ == "file":
                p = Path(v)
                if "://" not in v and not p.is_absolute():
                    v = str(s.pipeline.notebook_dir / p)
                values.append(f"file({groovy_string(v)}, checkIfExists: true)")
            else:
                values.append(groovy_string(v))
        items.append("[" + ", ".join([groovy_literal(meta), *values]) + "]")
    return items


def render_wrapper(pipeline: Pipeline, targets: Sequence[Channel]) -> tuple[str, str]:
    """Render a test-run wrapper ``(main.nf, nextflow.config)`` publishing ``targets``."""
    procs: dict[int, Process] = {}
    sheets: dict[str, Samplesheet] = {}
    params: dict[str, Param] = {}

    def scan(value: Any) -> None:
        if isinstance(value, Param):
            params[value.name] = value
        elif isinstance(value, Channel):
            if value.kind == "samplesheet":
                sheets[value.ref.name] = value.ref
            elif value.kind == "param":
                params[value.ref.name] = value.ref
            for op in value.ops:
                for a in op.args:
                    scan(a)
            for p in value.upstream_processes():
                if id(p) not in procs:
                    procs[id(p)] = p
                    for v in p.inputs.values():
                        scan(v)

    for t in targets:
        scan(t)
    ordered = sorted(procs.values(), key=lambda p: p.order)

    lines = include_lines(ordered, lambda p: str(p.module.main_nf.resolve()))
    lines += ["", "workflow {", f"{INDENT}main:"]
    for s in sheets.values():
        rows = samplesheet_rows_literal(s)
        body = (",\n" + INDENT * 2).join(rows)
        lines.append(
            f"{INDENT}{samplesheet_var(s, test=True)} = channel.of(\n{INDENT * 2}{body}\n{INDENT})"
        )
    for p in ordered:
        lines.append(INDENT + process_call(p, test=True).replace("\n", "\n" + INDENT))
    for i, t in enumerate(targets):
        expr = channel_expr(t, test=True).replace("\n", "\n" + INDENT)
        lines.append(f"{INDENT}ch_out_{i} = {expr}")
    lines.append("")
    lines.append(f"{INDENT}publish:")
    for i, _ in enumerate(targets):
        lines.append(f"{INDENT}out_{i} = ch_out_{i}")
    lines.append("}")
    lines.append("")
    lines.append("output {")
    for i, _ in enumerate(targets):
        lines += [
            f"{INDENT}out_{i} {{",
            f"{INDENT * 2}path 'out_{i}'",
            f"{INDENT * 2}mode 'symlink'",
            f"{INDENT * 2}index {{",
            f"{INDENT * 3}path 'out_{i}.json'",
            f"{INDENT * 2}}}",
            f"{INDENT}}}",
        ]
    lines.append("}")
    script = "\n".join(lines) + "\n"

    cfg = []
    for p in params.values():
        cfg.append(f"params.{p.name} = {groovy_literal(p.test_value)}")
    cfg.append(TEST_RESOURCES)
    if pipeline.profile == "docker":
        gpus = " --gpus all" if pipeline.gpu else ""
        cfg += ["docker.enabled = true", f"docker.runOptions = '-u $(id -u):$(id -g){gpus}'"]
    if pipeline.gpu:  # nf-core convention: GPU-capable processes carry the process_gpu label
        cfg.append("process {\n    withLabel: 'process_gpu' {\n        accelerator = 1\n    }\n}")
    elif pipeline.profile == "conda":
        cfg += ["conda.enabled = true"]
    cfg.append(ext_config(ordered))
    if pipeline.config:
        cfg.append(pipeline.config)
    config = "\n".join(c for c in cfg if c) + "\n"
    return script, config


def parse_index(path: Path) -> list[Any]:
    """Parse a workflow-output index JSON into Python values (paths become ``Path``)."""

    def conv(v: Any) -> Any:
        if isinstance(v, str) and Path(v).is_absolute() and Path(v).exists():
            return Path(v)
        if isinstance(v, list):
            return [conv(x) for x in v]
        if isinstance(v, dict):
            return {k: conv(x) for k, x in v.items()}
        return v

    return [conv(x) for x in json.loads(path.read_text(encoding="utf-8"))]
