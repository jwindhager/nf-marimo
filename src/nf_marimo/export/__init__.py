"""Convert a marimo notebook into an nf-core pipeline."""

from __future__ import annotations

import subprocess
import warnings
from pathlib import Path

from .collect import Collected, ExportError, collect
from .nfcore import generate

__all__ = ["Collected", "ExportError", "collect", "export"]


def export(
    notebook: str | Path,
    outdir: str | Path,
    *,
    force: bool = False,
    lint: bool = False,
    test: bool = False,
    profile: str = "docker",
) -> Path:
    """Export ``notebook`` to an nf-core pipeline in ``outdir``.

    Parameters
    ----------
    notebook
        Path to the marimo notebook.
    outdir
        Output directory of the pipeline (must be empty unless ``force``).
    force
        Overwrite ``outdir``.
    lint
        Run ``nf-core pipelines lint`` afterwards.
    test
        Run the pipeline with ``-profile test,<profile>`` afterwards.
    profile
        Container/conda profile used for ``test``.

    Returns
    -------
    Path
        The pipeline directory.

    """
    collected = collect(notebook)
    for message in collected.warnings:
        warnings.warn(message, stacklevel=2)
    out = generate(collected.pipeline, Path(outdir).resolve(), force=force)
    if lint:
        subprocess.run(["nf-core", "pipelines", "lint", "--dir", str(out)], check=False)
    if test:
        subprocess.run(
            [
                "nextflow",
                "run",
                str(out),
                "-profile",
                f"test,{profile}",
                "--outdir",
                str(out.parent / f"{out.name}-test-results"),
            ],
            cwd=out.parent,
            check=True,
        )
    return out
