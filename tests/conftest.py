from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures() -> Path:
    return FIXTURES


@pytest.fixture
def project() -> Path:
    """Fixture project: a notebook with local modules ``upper`` and ``count``."""
    return FIXTURES / "project"


@pytest.fixture
def pipeline(project):
    """Fixture pipeline: samplesheet -> UPPER -> COUNT (not run: outside a notebook)."""
    import nf_marimo as nfm

    pipeline = nfm.pipeline("textflow", notebook_dir=project)
    samples = pipeline.samplesheet(
        "input",
        columns={"sample": "meta.id", "text": "uri"},
        test=[{"sample": "s1", "text": "https://example.org/s1.txt"}],
    )
    suffix = pipeline.param("suffix", "END", description="Appended line")
    upper = pipeline.process(
        "local/upper",
        inputs={"text": samples.op(nfm.ops.stage_or_url()), "suffix": suffix},
        ext_args="--fast",
    )
    pipeline.process(
        "local/count",
        inputs={"text": upper.out.txt.op(nfm.ops.stage_or_url()), "mode": "l"},
        ext_prefix="${meta.id}_counts",
    )
    return pipeline
