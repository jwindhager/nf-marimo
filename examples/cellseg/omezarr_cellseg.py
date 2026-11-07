import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell
def _():
    # Example data for test runs: edit freely (add rows, point to local OME-Zarr paths, ...).
    # Exported as the pipeline's `-profile test` samplesheet; real runs use `--input <csv>`.
    test_samples = [
        {
            "sample": "idr0033A_BR00109990_C2",
            "image": "https://livingobjects.ebi.ac.uk/idr/zarr/v0.5/idr0033A/BR00109990_C2.zarr/0",
        },
    ]
    return (test_samples,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # Cell segmentation & quantification on OME-Zarr

    This notebook is an **nf-core workflow**: cells calling `pipeline.process(...)` are
    workflow steps (Nextflow processes). **Running such a cell test-runs the step** on the
    example data (first cell) with Nextflow; results are cached, so re-running is instant.
    The notebook uses marimo's *lazy* mode: edits mark dependent cells as stale instead of
    re-running (and re-computing) them automatically. All other cells are ordinary marimo
    cells for interactive analysis and are ignored when converting the notebook into an
    nf-core pipeline:

    ```bash
    pixi run nfm export examples/cellseg/omezarr_cellseg.py --outdir build/nf-cellseg
    ```

    **Data:** Cell Painting image (U2OS cells) from
    [IDR idr0033A](https://idr.openmicroscopy.org/webclient/?show=screen-1751),
    published as OME-Zarr v0.5 — it is streamed from the cloud, never downloaded as a whole.
    """)
    return


@app.cell
def _():
    import marimo as mo
    import omezarr_utils as omezarr  # example helpers next to this notebook

    import nf_marimo as nfm

    return mo, nfm, omezarr


@app.cell
def _(nfm, test_samples):
    # ⚙ workflow configuration: pipeline, inputs (samplesheet) and parameters
    pipeline = nfm.pipeline(
        "cellseg",
        description="Cellpose segmentation and single-cell quantification of OME-Zarr images",
        author="Jonas Windhager",
        org="jwindhager",
    )
    samples = pipeline.samplesheet(
        "input",
        columns={"sample": "meta.id", "image": "uri"},
        test=test_samples,
    )
    cellpose_model = pipeline.param(
        "cellpose_model",
        "https://huggingface.co/mouseland/cellpose-sam/resolve/main/cpsam",
        type="file",
        description="Cellpose model weights (default: Cellpose-SAM)",
    )
    seg_channels = pipeline.param(
        "seg_channels",
        "Nuclei,Actin/Golgi/Membrane",
        description="Comma-separated channel names used for segmentation (nuclear first)",
    )
    return cellpose_model, pipeline, samples, seg_channels


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 1 · Explore the raw image

    The multiscale image is streamed chunk-wise from the IDR (only visible tiles are loaded).
    """)
    return


@app.cell
def _(test_samples):
    # the (first) test sample's image URI
    image_uri = test_samples[0]["image"]
    image_uri
    return (image_uri,)


@app.cell
def _(image_uri, omezarr):
    omezarr.channel_table(image_uri)
    return


@app.cell
def _(image_uri, omezarr):
    omezarr.viewer(image_uri)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 2 · Segment cells with Cellpose

    `CELLPOSE_OMEZARR` reads the image in place (local path *or* cloud URL) and writes a new
    OME-Zarr containing the image and the segmentation under `labels/cellpose`.
    Run the next cell to test this step.
    """)
    return


@app.cell
def _(cellpose_model, nfm, pipeline, samples, seg_channels):
    # ⚙ Segment cells in an OME-Zarr v0.5 image with Cellpose
    # outputs: seg.out.zarr
    seg = pipeline.process(
        "local/cellpose_omezarr",
        inputs={
            "image": samples.op(nfm.ops.stage_or_url()),  # [meta, path|[], url|'']
            "channels": seg_channels,
            "model": cellpose_model,
        },
        ext_args="",  # e.g. "--level 1" to segment a lower-resolution level
    )
    seg
    return (seg,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 3 · Inspect the segmentation

    Overlay of the Cellpose labels on the image (both read from the output OME-Zarr).
    """)
    return


@app.cell
def _(seg):
    _meta, seg_zarr = seg.out.zarr.values()[0]  # results of the process cell above
    seg_zarr
    return (seg_zarr,)


@app.cell
def _(omezarr, seg_zarr):
    omezarr.viewer(seg_zarr)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 4 · Quantify single cells

    `QUANTIFY_OMEZARR` measures per-cell intensities and morphology (scikit-image
    `regionprops`) into a CSV table.
    """)
    return


@app.cell
def _(nfm, pipeline, seg):
    # ⚙ Quantify single-cell intensities and morphology into a CSV table
    # outputs: quant.out.csv
    quant = pipeline.process(
        "local/quantify_omezarr",
        inputs={
            "image": seg.out.zarr.op(nfm.ops.stage_or_url()),
            "label_name": "cellpose",
        },
    )
    quant
    return (quant,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 5 · Explore the single-cell data (scverse)
    """)
    return


@app.cell
def _(quant):
    import pandas as pd

    _meta, _csv = quant.out.csv.values()[0]
    table = pd.read_csv(_csv)  # one row per cell (regionprops)
    table
    return (table,)


@app.cell
def _(mo):
    resolution = mo.ui.slider(0.1, 2.0, step=0.1, value=0.5, label="Leiden resolution")
    resolution
    return (resolution,)


@app.cell
def _(resolution, table):
    import matplotlib.pyplot as plt
    import scanpy as sc
    import squidpy as sq

    # cells x channels (mean intensities) for scanpy/squidpy
    _mean = [c for c in table.columns if c.startswith("intensity_mean-")]
    ad_ = sc.AnnData(
        X=table[_mean].to_numpy(dtype="float32"),
        obs=table[["label", "area", "eccentricity", "solidity"]].set_index(
            table["label"].astype(str)
        ),
    )
    ad_.var_names = [c.removeprefix("intensity_mean-") for c in _mean]
    ad_.obsm["spatial"] = table[["centroid-1", "centroid-0"]].to_numpy()  # (x, y) in pixels
    ad_.layers["raw"] = ad_.X.copy()
    sc.pp.log1p(ad_)
    sc.pp.scale(ad_)
    sc.pp.pca(ad_, n_comps=min(4, ad_.n_vars - 1))
    sc.pp.neighbors(ad_)
    sc.tl.umap(ad_)
    sc.tl.leiden(ad_, resolution=resolution.value, flavor="igraph", n_iterations=2)
    sq.gr.spatial_neighbors_delaunay(ad_)
    sq.gr.nhood_enrichment(ad_, cluster_key="leiden")
    return ad_, plt, sc, sq


@app.cell
def _(ad_, mo):
    mo.md(f"""
    **{ad_.n_obs} cells** · median area {ad_.obs["area"].median():.0f} px ·
    **{ad_.obs["leiden"].nunique()} phenotypes** (Leiden)
    """)
    return


@app.cell
def _(ad_, plt, sc):
    sc.pl.violin(
        ad_, ["area", "eccentricity", "solidity"], multi_panel=True, jitter=0.3, show=False
    )
    plt.gcf()
    return


@app.cell
def _(ad_, plt, sc):
    sc.pl.umap(ad_, color=["leiden", *ad_.var_names[:3]], ncols=2, show=False)
    plt.gcf()
    return


@app.cell
def _(ad_, plt, sc):
    sc.pl.matrixplot(
        ad_, ad_.var_names, groupby="leiden", layer="raw", standard_scale="var", show=False
    )
    plt.gcf()
    return


@app.cell
def _(ad_, plt, sq):
    sq.pl.spatial_scatter(ad_, color="leiden", shape=None, size=20, figsize=(8, 6))
    plt.gcf()
    return


@app.cell
def _(ad_, plt, sq):
    sq.pl.nhood_enrichment(ad_, cluster_key="leiden", figsize=(5, 5))
    plt.gcf()
    return


if __name__ == "__main__":
    app.run()
