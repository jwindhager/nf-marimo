#!/usr/bin/env python3
"""Segment cells in an OME-Zarr v0.5 image with Cellpose.

Writes a self-contained OME-Zarr v0.5 containing the (copied) multiscale image and the
segmentation as a multiscale label image under ``labels/<label_name>``. All OME-Zarr I/O goes
through ome-zarr-py.

Nextflow template: values in dollar-brace placeholders are filled in by Nextflow.
"""

import argparse
import os
import shlex

import numpy as np
import zarr
from ome_zarr.format import FormatV05
from ome_zarr.io import parse_url
from ome_zarr.reader import Label, Multiscales, Reader
from ome_zarr.writer import write_multiscale, write_multiscale_labels

IMAGE = "${image_uri}"
CHANNELS = "${channels}"
MODEL = "${model_path}"
PREFIX = "${prefix}"
ARGS = "${args}"
THREADS = int("${task.cpus}")
PROCESS = "${task.process}"
USE_GPU = bool("${use_gpu}")  # set when task.accelerator is requested

OME_ZARR_VERSION = "0.5"


def parse_args(argv):
    p = argparse.ArgumentParser(prog="cellpose_omezarr")
    p.add_argument("--level", type=int, default=0, help="pyramid level to segment")
    p.add_argument("--label-name", default="cellpose", help="name of the label image")
    p.add_argument("--diameter", type=float, default=None, help="cell diameter (pixels)")
    p.add_argument("--flow-threshold", type=float, default=0.4)
    p.add_argument("--cellprob-threshold", type=float, default=0.0)
    p.add_argument("--min-size", type=int, default=15)
    return p.parse_args(argv)


def read_image(uri):
    """Return (location, image node) of an OME-Zarr v0.5 image (local path or remote URI).

    A bioformats2raw root (no multiscales of its own) resolves to its first image, ``0``.
    """
    for candidate in (uri, uri.rstrip("/") + "/0"):
        loc = parse_url(candidate)
        if loc is None:
            continue
        for node in Reader(loc)():
            specs = node.specs
            if any(isinstance(s, Multiscales) for s in specs) and not any(
                isinstance(s, Label) for s in specs
            ):
                if loc.version != OME_ZARR_VERSION:
                    raise ValueError(f"only OME-Zarr v{OME_ZARR_VERSION} is supported, got {loc.version}")
                return loc, node
    raise ValueError(f"{uri} contains no OME-Zarr multiscale image")


def main():
    os.environ.setdefault("OMP_NUM_THREADS", str(THREADS))
    # the container's home directory is not writable for the task user: keep caches local
    os.environ["HOME"] = os.getcwd()
    os.environ["MPLCONFIGDIR"] = os.path.join(os.getcwd(), ".matplotlib")
    opts = parse_args(shlex.split(ARGS))
    loc, image = read_image(IMAGE)
    meta = image.metadata
    axes = [a["name"] for a in meta["axes"]]
    if "y" not in axes or "x" not in axes:
        raise ValueError(f"image needs y and x axes, got {axes}")
    levels = image.data  # lazy (dask) arrays, one per pyramid level
    shape0 = levels[0].shape
    for ax in axes:
        if ax not in ("c", "y", "x") and shape0[axes.index(ax)] != 1:
            raise ValueError(f"only 2D images are supported; axis {ax!r} has size > 1")

    # -- select channels by name (omero labels) --------------------------------------------
    names = list(meta.get("channel_names") or [])
    wanted = [c.strip() for c in CHANNELS.split(",") if c.strip()]
    if "c" in axes:
        missing = [c for c in wanted if c not in names]
        if missing:
            raise ValueError(f"channels {missing} not found; available: {names}")
        idx = [names.index(c) for c in wanted] or [0]
    else:
        idx = [0]

    # -- read the level to segment as (Y, X, C) --------------------------------------------
    sel = tuple(idx if ax == "c" else (slice(None) if ax in ("y", "x") else 0) for ax in axes)
    data = np.asarray(levels[opts.level][sel])
    if "c" in axes:
        data = np.moveaxis(data, [a for a in axes if a in ("c", "y", "x")].index("c"), -1)
    else:
        data = data[..., None]
    print(f"segmenting level {opts.level}: shape={data.shape} channels={wanted or names[:1]}")

    # -- run Cellpose -----------------------------------------------------------------------
    from cellpose import models

    model = models.CellposeModel(gpu=USE_GPU, pretrained_model=MODEL or "cpsam")
    print(f"cellpose device: {model.device}")
    masks, _, _ = model.eval(
        data,
        channel_axis=-1,
        diameter=opts.diameter,
        flow_threshold=opts.flow_threshold,
        cellprob_threshold=opts.cellprob_threshold,
        min_size=opts.min_size,
    )
    masks = masks.astype(np.uint32)
    print(f"found {int(masks.max())} objects")

    # -- label pyramid matching the image's levels (nearest neighbour) --------------------
    def yx(shape):
        return shape[axes.index("y")], shape[axes.index("x")]

    def nearest(labels, shape):
        """Resample a 2D label image to ``shape`` (nearest neighbour; ids are preserved)."""
        rows = ((np.arange(shape[0]) + 0.5) * labels.shape[0] / shape[0]).astype(int)
        cols = ((np.arange(shape[1]) + 0.5) * labels.shape[1] / shape[1]).astype(int)
        return labels[np.ix_(rows, cols)]

    label_levels = []
    for level in levels:
        lv = masks if masks.shape == yx(level.shape) else nearest(masks, yx(level.shape))
        shape = tuple(level.shape[i] if ax in ("y", "x") else 1 for i, ax in enumerate(axes))
        label_levels.append(lv.astype(np.uint32).reshape(shape))

    # -- write output OME-Zarr (image copy + labels) with ome-zarr ------------------------
    transforms = meta["coordinateTransformations"]
    out = parse_url(f"{PREFIX}.ome.zarr", mode="w", fmt=FormatV05())
    root = zarr.open_group(out.store, mode="w")  # group handle for the ome-zarr writers
    omero = loc.root_attrs.get("omero")
    write_multiscale(
        levels,
        root,
        fmt=FormatV05(),
        axes=meta["axes"],
        coordinate_transformations=transforms,
        storage_options=[{"chunks": level.chunksize} for level in levels],
        name=meta.get("name"),
        **({"metadata": {"omero": omero}} if omero else {}),
    )
    write_multiscale_labels(
        label_levels,
        root,
        opts.label_name,
        fmt=FormatV05(),
        axes=meta["axes"],
        coordinate_transformations=transforms,
        storage_options=[
            {"chunks": tuple(min(1024, s) for s in level.shape)} for level in label_levels
        ],
    )
    print(f"wrote {PREFIX}.ome.zarr")
    write_versions()


def write_versions():
    """Write versions.yml (emitted on the 'versions' topic)."""
    import importlib.metadata as md

    with open("versions.yml", "w") as f:
        f.write(f'"{PROCESS}":' + chr(10))
        for tool, dist in [("cellpose", "cellpose"), ("ome-zarr", "ome-zarr")]:
            f.write(f"    {tool}: {md.version(dist)}" + chr(10))


if __name__ == "__main__":
    main()
