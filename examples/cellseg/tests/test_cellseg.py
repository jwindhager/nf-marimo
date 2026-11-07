"""Tests of the cellseg example: module metadata, export, and end-to-end runs (integration)."""

import json
from pathlib import Path

import pytest
import yaml

import nf_marimo as nfm
from nf_marimo import notebook_file
from nf_marimo.export.collect import collect, find_nf_cells
from nf_marimo.meta import load_meta

EXAMPLE = Path(__file__).parents[1]
META_SCHEMA = Path(__file__).parents[3] / "tests" / "fixtures" / "meta-schema.json"

IDR_URL = "https://livingobjects.ebi.ac.uk/idr/zarr/v0.5/idr0033A/BR00109990_C2.zarr/0"
TEST_SAMPLES = [{"sample": "idr0033A_BR00109990_C2", "image": IDR_URL}]

MODEL_URL = "https://huggingface.co/mouseland/cellpose-sam/resolve/main/cpsam"


@pytest.mark.parametrize("module", ["cellpose_omezarr", "quantify_omezarr"])
def test_module_meta(module):
    import jsonschema

    path = EXAMPLE / "modules" / "local" / module / "meta.yml"
    jsonschema.validate(
        yaml.safe_load(path.read_text(encoding="utf-8")),
        json.loads(META_SCHEMA.read_text(encoding="utf-8")),
    )
    spec = load_meta(path)
    assert spec.input_keys[0] == "image"
    assert spec.input("image").elements[2].name == "image_url"


def test_collect_notebook():
    nb_path = EXAMPLE / "omezarr_cellseg.py"
    nf_cells = find_nf_cells(notebook_file.parse(nb_path))
    assert any("local/cellpose_omezarr" in c.code for c in nf_cells)
    col = collect(nb_path)
    assert col.pipeline.name == "cellseg"
    assert [p.alias for p in col.pipeline.processes] == ["CELLPOSE_OMEZARR", "QUANTIFY_OMEZARR"]
    executed = "\n".join(c.code for c in col.executed)
    assert "scanpy" not in executed
    assert "viewer(" not in executed


# --------------------------------------------------------------------------- integration


@pytest.fixture(scope="module")
def pipeline():
    pipeline = nfm.pipeline("cellseg", notebook_dir=EXAMPLE)
    samples = pipeline.samplesheet(
        "input", columns={"sample": "meta.id", "image": "uri"}, test=TEST_SAMPLES
    )
    seg = pipeline.process(
        "local/cellpose_omezarr",
        inputs={
            "image": samples.op(nfm.ops.stage_or_url()),
            "channels": pipeline.param("seg_channels", "Nuclei,Actin/Golgi/Membrane"),
            "model": pipeline.param("cellpose_model", MODEL_URL, type="file"),
        },
        ext_args="--level 2",
    )
    pipeline.process(
        "local/quantify_omezarr",
        inputs={"image": seg.out.zarr.op(nfm.ops.stage_or_url()), "label_name": "cellpose"},
        ext_args="--level 2",
    )
    return pipeline


def _read(path):
    """(image node, {label name: label node}) via ome-zarr-py."""
    from ome_zarr.io import parse_url
    from ome_zarr.reader import Label, Reader

    nodes = list(Reader(parse_url(str(path)))())
    labels = {n.metadata["name"]: n for n in nodes if any(isinstance(s, Label) for s in n.specs)}
    return nodes[0], labels


@pytest.mark.integration
def test_segmentation_writes_ngff_v05_with_labels(pipeline):
    from ome_zarr.io import parse_url

    seg = pipeline.processes[0]
    [(meta, zarr_path)] = seg.out.zarr.values()
    assert meta == {"id": "idr0033A_BR00109990_C2"}
    assert parse_url(str(zarr_path)).version == "0.5"
    image, labels = _read(zarr_path)
    assert list(labels) == ["cellpose"]
    assert image.metadata["channel_names"][0] == "Nuclei"  # omero metadata carried over
    label = labels["cellpose"]
    # one label level per image level, with matching y/x shapes and transformations
    assert [d.shape[1:] for d in label.data] == [d.shape[1:] for d in image.data]
    assert (
        label.metadata["coordinateTransformations"] == image.metadata["coordinateTransformations"]
    )


@pytest.mark.integration
def test_quantification_csv(pipeline):
    import csv

    import numpy as np

    seg, quant = pipeline.processes
    [(_, csv_path)] = quant.out.csv.values()
    with csv_path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    intensity = {f"intensity_{stat}-Nuclei" for stat in ("min", "max", "mean", "median")}
    assert {"label", "centroid-0", "area", *intensity} <= set(rows[0])
    [(_, zarr_path)] = seg.out.zarr.values()
    _, labels = _read(zarr_path)
    level2 = np.asarray(labels["cellpose"].data[2])  # quantified at --level 2
    assert len(rows) == len(np.unique(level2[level2 > 0]))


@pytest.mark.integration
def test_second_run_is_cached(pipeline):
    logs: list[str] = []
    pipeline.processes[1].run(on_log=logs.append)
    assert any("cached results" in line for line in logs)
