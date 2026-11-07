"""nf-marimo: build nf-core pipelines using marimo.

Typical usage in a notebook::

    import nf_marimo as nfm

    pipeline = nfm.pipeline("mypipeline")
    samples = pipeline.samplesheet(
        "input",
        columns={"sample": "meta.id", "fastq": "file"},
        test=[{"sample": "s1", "fastq": "data/s1.fastq.gz"}],
    )
    fastqc = pipeline.process("nf-core/fastqc", inputs={"reads": samples})
    fastqc         # running this cell test-runs the step; shows wiring and results
"""

from . import ops
from .catalog import search
from .model import Channel, ExportModeError, Param, Pipeline, Process, pipeline
from .runner import NextflowError

__version__ = "0.1.0.dev0"

__all__ = [
    "Channel",
    "ExportModeError",
    "NextflowError",
    "Param",
    "Pipeline",
    "Process",
    "browse",
    "ops",
    "pipeline",
    "search",
]


def browse(query: str = "", notebook_dir: str | None = None):
    """Interactive module browser (marimo UI element)."""
    from .widgets.browser import browser

    return browser(query, notebook_dir)
