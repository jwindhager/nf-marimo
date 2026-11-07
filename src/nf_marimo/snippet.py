"""Generate process-cell code ("template to fill in") from module metadata."""

from __future__ import annotations

import keyword
import re
import textwrap

from .meta import ModuleSpec


def default_variable(module_name: str) -> str:
    """Python variable name for a module, e.g. ``bwa/mem`` -> ``bwa_mem``."""
    var = re.sub(r"\W", "_", module_name).lower()
    return var + "_" if keyword.iskeyword(var) else var


def process_cell(
    module_id: str,
    spec: ModuleSpec,
    *,
    sha: str | None = None,
    pipeline_var: str = "pipeline",
    variable: str | None = None,
) -> str:
    """Return the code of a process cell for ``module_id`` (``nf-core/x`` or ``local/x``)."""
    var = variable or default_variable(module_id.split("/", 1)[1])
    lines = [f"# {spec.description}" if spec.description else f"# {module_id}"]
    if spec.documentation:
        lines.append(f"# docs: {spec.documentation}")
    outs = ", ".join(f"{var}.out.{e}" for e in spec.output_emits)
    if outs:
        lines.append(f"# outputs: {outs}")
    lines.append(f"{var} = {pipeline_var}.process(")
    lines.append(f"    {module_id!r},")
    if sha:
        lines.append(f"    sha={sha!r},")
    lines.append("    inputs={")
    for ch in spec.inputs:
        shape = ", ".join(f"{e.name}:{e.type}" for e in ch.elements)
        hints = [f"[{shape}]" if ch.is_tuple else shape]
        patterns = [e.pattern for e in ch.elements if e.pattern and e.pattern != "*"]
        if patterns:
            hints.append("pattern " + ", ".join(patterns))
        desc = " ".join(ch.description.split())
        if desc:
            hints.append(textwrap.shorten(desc, 80, placeholder="…"))
        lines.append(f"        {ch.key!r}: None,  # TODO {' | '.join(hints)}")
    lines.append("    },")
    lines.append('    ext_args="",')
    lines.append(")")
    lines.append(var)
    return "\n".join(lines) + "\n"
