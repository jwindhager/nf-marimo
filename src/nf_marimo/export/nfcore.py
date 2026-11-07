"""Generate an nf-core pipeline from a collected notebook workflow."""

from __future__ import annotations

import csv
import json
import re
import shutil
import subprocess
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml

from ..codegen import INDENT, ext_config, groovy_literal, groovy_string, include_lines, process_call
from ..model import Param, Pipeline, Process
from .collect import ExportError

SKIP_FEATURES = [
    "github",
    "github_badges",
    "ci",
    "igenomes",
    "multiqc",
    "fastqc",
    "codespaces",
    "vscode",
    "seqera_platform",
    "email",
    "rocrate",
]

GITATTRIBUTES = """*.config linguist-language=nextflow
*.nf.test linguist-language=nextflow
modules/nf-core/** linguist-generated
subworkflows/nf-core/** linguist-generated
"""

_SCHEMA_TYPES = {"string": "string", "integer": "integer", "number": "number", "boolean": "boolean"}


def _run(cmd: list[str], cwd: Path | None = None) -> str:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise ExportError(f"command failed: {' '.join(cmd)}\n{proc.stdout}\n{proc.stderr}")
    return proc.stdout


def _replace_once(text: str, pattern: str, repl: str, what: str, flags: int = 0) -> str:
    new, n = re.subn(pattern, lambda _m: repl, text, count=1, flags=flags)
    if n != 1:
        raise ExportError(f"nf-core template changed: could not find {what}")
    return new


def _check_exportable(pipeline: Pipeline) -> None:
    errors = []
    for p in pipeline.processes:
        errors += [f"{p.alias}: {msg}" for msg in p.problems]
    if not pipeline.processes:
        errors.append("the workflow has no processes")
    if set(pipeline.samplesheets) - {"input"}:
        errors.append("only one samplesheet named 'input' is supported for export")
    aliases = [p.alias for p in pipeline.processes]
    dupes = {a for a in aliases if aliases.count(a) > 1}
    if dupes:
        errors.append(f"duplicate process names {sorted(dupes)}; pass name=... to pipeline.process")
    for p in pipeline.processes:
        if p.module.source == "nf-core" and not p.module.sha:
            errors.append(f"{p.alias}: nf-core module is not pinned (pass sha=...)")
    if errors:
        raise ExportError("cannot export:\n  - " + "\n  - ".join(errors))


# --------------------------------------------------------------------------- scaffold


def scaffold(pipeline: Pipeline, outdir: Path) -> None:
    """Create the pipeline skeleton with ``nf-core pipelines create``."""
    outdir.parent.mkdir(parents=True, exist_ok=True)
    template = outdir.parent / f".{outdir.name}.nfm-template.yml"
    template.write_text(
        yaml.safe_dump(
            {
                "name": pipeline.name,
                "description": pipeline.description,
                "author": pipeline.author or "nf-marimo",
                "org": pipeline.org,
                "version": pipeline.version,
                "is_nfcore": False,
                "skip_features": SKIP_FEATURES,
            }
        ),
        encoding="utf-8",
    )
    try:
        _run(
            ["nf-core", "pipelines", "create", "--template-yaml", str(template), "-o", str(outdir)]
        )
    finally:
        template.unlink(missing_ok=True)


def install_modules(pipeline: Pipeline, outdir: Path) -> None:
    """Install nf-core modules (pinned) and copy local modules."""
    done: set[str] = set()
    for p in pipeline.processes:
        m = p.module
        if m.id in done:
            continue
        done.add(m.id)
        if m.source == "nf-core":
            _run(
                ["nf-core", "modules", "install", "--dir", str(outdir), "--sha", str(m.sha), m.name]
            )
        else:
            dst = outdir / "modules" / "local" / m.name
            shutil.copytree(m.directory, dst, dirs_exist_ok=True)


# --------------------------------------------------------------------------- generated files


def _module_include_path(p: Process) -> str:
    return f"../modules/{p.module.source}/{p.module.name}/main"


def write_workflow(pipeline: Pipeline, outdir: Path) -> None:
    """Inject includes and process calls into ``workflows/<name>.nf``."""
    path = outdir / "workflows" / f"{pipeline.name}.nf"
    text = path.read_text(encoding="utf-8")
    includes = "\n".join(include_lines(pipeline.processes, _module_include_path))
    m = re.search(r"include \{ methodsDescriptionText \}[^\n]*\n", text)
    if not m:
        raise ExportError("nf-core template changed: could not find include block")
    text = text[: m.end()] + includes + "\n" + text[m.end() :]

    calls = []
    for p in pipeline.processes:
        calls.append(f"{INDENT}//\n{INDENT}// MODULE: {p.module.id}\n{INDENT}//")
        calls.append(INDENT + process_call(p, test=False).replace("\n", "\n" + INDENT))
        calls.append("")
    anchor = re.search(r"\n(\s*)def ch_versions = channel\.empty\(\)\n", text)
    if not anchor:
        raise ExportError("nf-core template changed: could not find ch_versions")
    text = text[: anchor.end()] + "\n" + "\n".join(calls) + text[anchor.end() :]
    path.write_text(text, encoding="utf-8")


def write_samplesheet_channel(pipeline: Pipeline, outdir: Path) -> None:
    """Replace the template's FASTQ-specific samplesheet handling."""
    path = outdir / "subworkflows" / "local" / f"utils_nfcore_{pipeline.name}_pipeline" / "main.nf"
    text = path.read_text(encoding="utf-8")
    text = _replace_once(
        text,
        r"channel\s*\n\s*\.fromList\(samplesheetToList\(input, [^\n]*\)\)\n"
        r".*?\.set \{ ch_samplesheet \}",
        "channel\n"
        '        .fromList(samplesheetToList(input, "${projectDir}/assets/schema_input.json"))\n'
        "        .set { ch_samplesheet }",
        "samplesheet channel creation",
        flags=re.S,
    )
    path.write_text(text, encoding="utf-8")


def write_input_schema(pipeline: Pipeline, outdir: Path) -> None:
    """Write ``assets/schema_input.json`` (nf-schema) for the samplesheet."""
    sheet = pipeline.samplesheets.get("input")
    if sheet is None:
        return
    path = outdir / "assets" / "schema_input.json"
    schema = json.loads(path.read_text(encoding="utf-8"))
    props: dict[str, Any] = {}
    for col, typ in sheet.columns.items():
        if typ.startswith("meta."):
            props[col] = {
                "type": "string",
                "pattern": "^\\S+$",
                "errorMessage": f"'{col}' must be provided and cannot contain spaces",
                "meta": [typ.split(".", 1)[1]],
            }
        elif typ == "file":
            props[col] = {
                "type": "string",
                "format": "file-path",
                "exists": True,
                "errorMessage": f"'{col}' must be an existing file",
            }
        else:  # string / uri: local path or remote URI, no file-ending checks
            props[col] = {
                "type": "string",
                "pattern": "^\\S+$",
                "errorMessage": f"'{col}' must be provided and cannot contain spaces",
            }
    schema["items"]["properties"] = props
    schema["items"]["required"] = list(sheet.columns)
    path.write_text(json.dumps(schema, indent=4) + "\n", encoding="utf-8")
    _write_csv(outdir / "assets" / "samplesheet.csv", sheet.columns, sheet.read_test_rows())


def _write_csv(path: Path, columns: Iterable[str], rows: list[dict[str, str]]) -> None:
    cols = list(columns)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def _param_default(p: Param) -> str:
    return "null" if p.default is None else groovy_literal(p.default)


def write_params(pipeline: Pipeline, outdir: Path) -> None:
    """Add workflow params to ``nextflow.config`` and ``nextflow_schema.json``."""
    params = list(pipeline.params)
    cfg = outdir / "nextflow.config"
    text = cfg.read_text(encoding="utf-8")
    if params:
        width = max(len(p.name) for p in params)
        block = "\n    // Workflow options (nf-marimo)\n" + "".join(
            f"    {p.name.ljust(width)} = {_param_default(p)}\n" for p in params
        )
        m = re.search(r"\n    input\s+= null\n", text)
        if not m:
            raise ExportError("nf-core template changed: could not find params.input")
        text = text[: m.end()] + block + text[m.end() :]
    cfg.write_text(text, encoding="utf-8")

    schema_path = outdir / "nextflow_schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    defs = schema.setdefault("$defs", {})
    if params:
        props: dict[str, Any] = {}
        for p in params:
            prop: dict[str, Any] = {"type": _SCHEMA_TYPES.get(p.type, "string")}
            if p.type == "file":
                prop["format"] = "file-path"
                prop["exists"] = True
            elif p.type == "directory":
                prop["format"] = "directory-path"
                prop["exists"] = True
            if p.description:
                prop["description"] = p.description
            if p.default is not None:
                prop["default"] = p.default
            props[p.name] = prop
        defs["workflow_options"] = {
            "title": "Workflow options",
            "type": "object",
            "fa_icon": "fas fa-cogs",
            "description": "Options of the workflow steps.",
            "properties": props,
        }
        refs = schema.setdefault("allOf", [])
        ref = {"$ref": "#/$defs/workflow_options"}
        if ref not in refs:
            refs.insert(1, ref)
    sheet = pipeline.samplesheets.get("input")
    if sheet is not None:
        io_props = defs.get("input_output_options", {}).get("properties", {})
        if "input" in io_props:
            io_props["input"]["description"] = sheet.description
    schema_path.write_text(json.dumps(schema, indent=4) + "\n", encoding="utf-8")


def write_test_config(pipeline: Pipeline, outdir: Path) -> None:
    """Point ``conf/test.config`` at the notebook's test inputs."""
    path = outdir / "conf" / "test.config"
    text = path.read_text(encoding="utf-8")
    lines = []
    sheet = pipeline.samplesheets.get("input")
    if sheet is not None:
        src = str(sheet.test) if sheet.test_is_file else ""
        if "://" in src and not src.startswith("file://"):
            lines.append(f"    input = {groovy_string(src)}")
        else:  # rows defined in the notebook (or a local CSV) -> assets/samplesheet_test.csv
            _write_csv(
                outdir / "assets" / "samplesheet_test.csv", sheet.columns, sheet.read_test_rows()
            )
            lines.append('    input = "${projectDir}/assets/samplesheet_test.csv"')
    for p in pipeline.params:
        if p.test is not None:
            lines.append(f"    {p.name} = {groovy_literal(p.test)}")
    text = re.sub(r"\n\s*// TODO nf-core:[^\n]*", "", text)
    text = _replace_once(
        text,
        r"\n    input\s*= params\.pipelines_testdata_base_path[^\n]*",
        "\n" + "\n".join(lines),
        "test input",
    )
    path.write_text(text, encoding="utf-8")


def write_modules_config(pipeline: Pipeline, outdir: Path) -> None:
    """Append ``ext.*``/``publishDir`` settings to ``conf/modules.config``."""
    path = outdir / "conf" / "modules.config"
    path.write_text(
        path.read_text(encoding="utf-8").rstrip("\n")
        + "\n\n"
        + ext_config(pipeline.processes, publish_dirs=True)
    )


# --------------------------------------------------------------------------- entry point


def generate(pipeline: Pipeline, outdir: Path, *, force: bool = False) -> Path:
    """Generate the nf-core pipeline for ``pipeline`` into ``outdir``."""
    _check_exportable(pipeline)
    if outdir.exists() and any(outdir.iterdir()):
        if not force:
            raise ExportError(f"{outdir} is not empty (use --force to overwrite)")
        shutil.rmtree(outdir)
    scaffold(pipeline, outdir)
    install_modules(pipeline, outdir)
    write_workflow(pipeline, outdir)
    write_samplesheet_channel(pipeline, outdir)
    write_input_schema(pipeline, outdir)
    write_params(pipeline, outdir)
    write_test_config(pipeline, outdir)
    write_modules_config(pipeline, outdir)
    gitattributes = outdir / ".gitattributes"
    if not gitattributes.exists():
        gitattributes.write_text(GITATTRIBUTES, encoding="utf-8")
    return outdir
