import marimo

__generated_with = "0.25.2"
app = marimo.App()


@app.cell
def _():
    test_samples = [
        {"sample": "s1", "text": "https://example.org/s1.txt"},
        {"sample": "s2", "text": "data/s2.txt"},
    ]
    return (test_samples,)


@app.cell
def _():
    import marimo as mo
    import nf_marimo as nfm
    import helpers

    return helpers, mo, nfm


@app.cell
def _(nfm, test_samples):
    pipeline = nfm.pipeline("textflow", description="Fixture workflow")
    samples = pipeline.samplesheet("input", columns={"sample": "meta.id", "text": "uri"}, test=test_samples)
    suffix = pipeline.param("suffix", "END", description="Appended line")
    return samples, suffix, pipeline


@app.cell
def _(nfm, samples, suffix, pipeline):
    upper = pipeline.process(
        "local/upper",
        inputs={"text": samples.op(nfm.ops.stage_or_url()), "suffix": suffix},
        ext_args="--fixture",
    )
    upper
    return (upper,)


@app.cell
def _(nfm, upper, pipeline):
    count = pipeline.process(
        "local/count",
        inputs={"text": upper.out.txt.op(nfm.ops.stage_or_url()), "mode": "l"},
        ext_prefix="${meta.id}_counts",
    )
    return (count,)


@app.cell
def _(count, helpers):
    # analysis cell: consumes workflow outputs, must not be exported
    table = helpers.summarize(count.out.tsv.values())
    return


if __name__ == "__main__":
    app.run()
