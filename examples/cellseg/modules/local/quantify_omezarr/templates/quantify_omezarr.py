#!/usr/bin/env python3
"""Quantify single-cell features from an OME-Zarr v0.5 image and one of its label images.

Writes the output of scikit-image's ``regionprops_table`` as a CSV table (one row per label,
pixel units of the quantified pyramid level); per-channel intensity columns are named after
the OMERO channel labels, e.g. ``intensity_mean-Nuclei``. OME-Zarr is read with ome-zarr-py.

Nextflow template: values in dollar-brace placeholders are filled in by Nextflow.
"""

import argparse
import csv
import shlex

import numpy as np
from ome_zarr.io import parse_url
from ome_zarr.reader import Label, Multiscales, Reader
from skimage.measure import regionprops_table

IMAGE = "${image_uri}"
LABEL_NAME = "${label_name}"
PREFIX = "${prefix}"
ARGS = "${args}"
PROCESS = "${task.process}"

OME_ZARR_VERSION = "0.5"


def intensity_median(regionmask, intensity_image):
    """Per-channel median intensity of a region (not built into regionprops)."""
    return np.median(intensity_image[regionmask], axis=0)


# regionprops_table properties ("intensity_median" is implemented by the function above)
PROPERTIES = [
    "label",
    "centroid",
    "area",
    "eccentricity",
    "solidity",
    "extent",
    "orientation",
    "major_axis_length",
    "minor_axis_length",
    "intensity_min",
    "intensity_max",
    "intensity_mean",
    "intensity_median",
]


def parse_args(argv):
    p = argparse.ArgumentParser(prog="quantify_omezarr")
    p.add_argument("--level", type=int, default=0, help="pyramid level to quantify")
    return p.parse_args(argv)


def read_image(uri):
    """Return (image node, {label name: label node}) of an OME-Zarr v0.5 image.

    ``uri`` is a local path or remote URI; a bioformats2raw root resolves to its image ``0``.
    """
    for candidate in (uri, uri.rstrip("/") + "/0"):
        loc = parse_url(candidate)
        if loc is None:
            continue
        nodes = list(Reader(loc)())
        images = [
            n
            for n in nodes
            if any(isinstance(s, Multiscales) for s in n.specs)
            and not any(isinstance(s, Label) for s in n.specs)
        ]
        if images:
            if loc.version != OME_ZARR_VERSION:
                raise ValueError(f"only OME-Zarr v{OME_ZARR_VERSION} is supported, got {loc.version}")
            labels = {
                n.metadata["name"]: n
                for n in nodes
                if any(isinstance(s, Label) for s in n.specs)
            }
            return images[0], labels
    raise ValueError(f"{uri} contains no OME-Zarr multiscale image")


def level(node, index):
    """Return (array, axis names) of pyramid level ``index`` of ``node``."""
    return node.data[index], [a["name"] for a in node.metadata["axes"]]


def to_cyx(arr, axes):
    """Read an array as (C, Y, X), dropping singleton non-spatial axes."""
    data = np.asarray(arr)
    keep = [a for a in axes if a in ("c", "y", "x")]
    for i, ax in reversed(list(enumerate(axes))):
        if ax not in keep:
            if data.shape[i] != 1:
                raise ValueError(f"only 2D images are supported; axis {ax!r} has size > 1")
            data = data.take(0, axis=i)
    if "c" not in keep:
        return data[None]
    return np.moveaxis(data, keep.index("c"), 0)


def main():
    opts = parse_args(shlex.split(ARGS))
    image_node, label_nodes = read_image(IMAGE)
    if LABEL_NAME not in label_nodes:
        raise ValueError(f"label image {LABEL_NAME!r} not found; available: {list(label_nodes)}")

    image = to_cyx(*level(image_node, opts.level))  # (C, Y, X)
    labels = to_cyx(*level(label_nodes[LABEL_NAME], opts.level))[0].astype(np.int64)  # (Y, X)
    if labels.shape != image.shape[1:]:
        raise ValueError(f"label shape {labels.shape} != image shape {image.shape[1:]}")
    channels = list(image_node.metadata.get("channel_names") or []) or [
        str(i) for i in range(image.shape[0])
    ]

    table = regionprops_table(
        labels,
        intensity_image=np.moveaxis(image, 0, -1),
        properties=PROPERTIES,
        extra_properties=[intensity_median],
    )
    # name per-channel columns after the channels: intensity_mean-0 -> intensity_mean-Nuclei
    renamed = {
        f"{prop}-{i}": f"{prop}-{name}"
        for prop in PROPERTIES
        if prop.startswith("intensity_")
        for i, name in enumerate(channels)
    }
    header = [renamed.get(column, column) for column in table]
    with open(f"{PREFIX}.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(zip(*table.values(), strict=True))
    print(f"wrote {PREFIX}.csv: {len(table['label'])} objects x {len(header)} columns")
    write_versions()


def write_versions():
    """Write versions.yml (emitted on the 'versions' topic)."""
    import importlib.metadata as md

    with open("versions.yml", "w") as f:
        f.write(f'"{PROCESS}":' + chr(10))
        for tool, dist in [
            ("scikit-image", "scikit-image"),
            ("ome-zarr", "ome-zarr"),
        ]:
            f.write(f"    {tool}: {md.version(dist)}" + chr(10))


if __name__ == "__main__":
    main()
