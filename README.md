# nf-marimo

Build [nf-core](https://nf-co.re) pipelines using [marimo](https://marimo.io).

> [!WARNING]
> This is a vibe-coded prototype. Expect rough edges and breaking changes; use at your own
> risk.

A big thank you to [Phil Ewels](https://phil.ewels.co.uk/) for the idea behind nf-marimo! 🙏

- **Process cells**: a cell calling `pipeline.process("nf-core/<module>" | "local/<module>", ...)` is a
  workflow step. Its inputs/outputs come from the module's `meta.yml`; outputs (`proc.out.<emit>`)
  are wired into other process cells through ordinary marimo dataflow.
- **Test mode**: running a process cell (marimo's own run button) test-runs that step with
  Nextflow on the example data, which is defined in the notebook itself
  (`pipeline.samplesheet(..., test=[{...}, ...])`). Results are cached (`-resume` on a per-notebook
  session), and `channel.values()` returns them as Python objects (`[(meta, Path), ...]`) for
  interactive analysis in normal cells. The project enables marimo's _lazy_ mode, so edits mark
  dependent cells stale instead of re-running workflow steps automatically.
- **Export**: `nfm export` converts the notebook into an nf-core pipeline (official template,
  nf-schema samplesheet, `modules.config`, test profile). Non-Nextflow cells are ignored.

## Quickstart

Requires [pixi](https://pixi.sh) and Docker. pixi provides Python, Nextflow, Java and nf-test.
Supported platforms: Linux, macOS (Intel and Apple Silicon) and Windows. Nextflow needs a
Unix shell, so on Windows, editing notebooks, module search and export work natively, while
running workflow steps requires [WSL2](https://learn.microsoft.com/windows/wsl/).

```bash
pixi install
pixi run nfm doctor                       # check nextflow / java / docker / module index
pixi run marimo edit my_workflow.py       # start a notebook (see examples/ for a complete one)
```

A minimal notebook:

```python
import nf_marimo as nfm

# example data for test runs, defined in the notebook (exported as the test profile)
test_samples = [{"sample": "s1", "fastq": "data/s1.fastq.gz"}]

pipeline = nfm.pipeline("mypipeline")
samples = pipeline.samplesheet("input", columns={"sample": "meta.id", "fastq": "file"}, test=test_samples)
```

Local modules live next to the notebook in `modules/local/<name>/` (nf-core module layout) and
are referenced as `local/<name>`.

### marimo settings

Running a process cell runs Nextflow, so two marimo runtime settings are recommended (this
repository sets them in its `pyproject.toml`; they can also go into your marimo user config):

```toml
[tool.marimo.runtime]
on_cell_change = "lazy"   # mark dependent cells stale on edits instead of re-running them
auto_instantiate = false  # don't run the notebook when it is opened
```

### Adding process cells

```bash
pixi run nfm search fastqc                       # nf-core + local modules
pixi run nfm add nf-core/fastqc my_workflow.py   # inserts a pre-filled process cell
```

or use the browser widget in a notebook: `nfm.browse("fastqc")`.

A generated cell is a template to fill in (code is the single source of truth):

```python
# Run FastQC on sequenced reads
# docs: https://www.bioinformatics.babraham.ac.uk/projects/fastqc/Help/
# outputs: fastqc.out.html, fastqc.out.zip
fastqc = pipeline.process(
    'nf-core/fastqc',
    sha='7b3452a23773f687ededb4befd037920e5a51341',
    inputs={
        'reads': None,  # TODO [meta:map, reads:file] | List of input FastQ files …
    },
    ext_args="",
)
fastqc
```

Running such a cell test-runs the step (on GPU, too: processes with the nf-core `process_gpu`
label get the GPU when `nfm.pipeline(..., gpu=True)`, auto-detected by default).

### Exporting to nf-core

```bash
pixi run nfm export my_workflow.py --outdir build/mypipeline --lint
nextflow run build/mypipeline -profile test,docker --outdir results
```

`nfm export` parses the notebook file (plain Python, no marimo internals), executes only the
cells that define the workflow (`nfm.pipeline`, `pipeline.samplesheet/param/process`) and their
ancestors, validates the wiring, then runs `nf-core pipelines create`, installs nf-core modules
at their pinned sha, copies local modules and generates `workflows/<name>.nf`,
`conf/modules.config`, params/schema and `conf/test.config`.

## Examples

- [`examples/cellseg`](examples/cellseg/README.md): Cellpose segmentation and single-cell
  quantification of OME-Zarr images, with interactive viewers and scverse analysis in between.

## Development

```bash
pixi run lint            # pre-commit: ruff, pyrefly, prettier, nextflow lint, meta.yml schema
pixi run typecheck       # pyrefly
pixi run test            # unit tests (tests/)
```

## License

[MIT](LICENSE)
