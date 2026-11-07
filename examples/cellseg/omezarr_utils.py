"""OME-Zarr (v0.5) helpers for the cellseg notebook: image viewer and channel table.

OME-Zarr is read with ome-zarr-py; images are shown with the BioNGFF vizarr viewer
(``vizarr_widget.js``), including their label images. Dependencies come with the ``cellseg``
pixi feature (see the repository's ``pyproject.toml``).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import anywidget
import traitlets
from ome_zarr.io import parse_url
from ome_zarr.reader import Label, Multiscales, Node, Reader

OME_ZARR_VERSION = "0.5"


# --------------------------------------------------------------------------- reading


def _is(node: Node, spec: type) -> bool:
    return any(isinstance(s, spec) for s in node.specs)


@dataclass
class OMEZarrImage:
    """An OME-Zarr image as read by ome-zarr-py: image node + label nodes by name."""

    uri: str  # resolved image location (bioformats2raw roots resolve to ``.../0``)
    image: Node
    labels: dict[str, Node]

    @property
    def axes(self) -> list[str]:
        """Axis names, e.g. ``["c", "y", "x"]``."""
        return [a["name"] for a in self.image.metadata["axes"]]

    def extent(self) -> list[float]:
        """Physical bounding box ``[xmin, ymin, xmax, ymax]`` of the full-resolution level."""
        iy, ix = self.axes.index("y"), self.axes.index("x")
        shape = self.image.data[0].shape
        scale, trans = [1.0, 1.0], [0.0, 0.0]
        for t in self.image.metadata["coordinateTransformations"][0]:
            if t["type"] == "scale":
                scale = [t["scale"][iy], t["scale"][ix]]
            elif t["type"] == "translation":
                trans = [t["translation"][iy], t["translation"][ix]]
        return [
            trans[1],
            trans[0],
            trans[1] + shape[ix] * scale[1],
            trans[0] + shape[iy] * scale[0],
        ]


def read_image(source: str | Path) -> OMEZarrImage:
    """Read an OME-Zarr v0.5 image (local path or remote URI) with ome-zarr-py."""
    uri = str(source).rstrip("/")
    for candidate in (uri, uri + "/0"):
        loc = parse_url(candidate)
        if loc is None:
            continue
        nodes = list(Reader(loc)())
        images = [n for n in nodes if _is(n, Multiscales) and not _is(n, Label)]
        if images:
            if loc.version != OME_ZARR_VERSION:
                raise ValueError(
                    f"only OME-Zarr v{OME_ZARR_VERSION} is supported, got {loc.version}"
                )
            labels = {n.metadata["name"]: n for n in nodes if _is(n, Label)}
            return OMEZarrImage(candidate, images[0], labels)
    raise ValueError(f"{source} contains no OME-Zarr v{OME_ZARR_VERSION} multiscale image")


def channel_table(source: str | Path) -> Any:
    """Table of channels, pyramid levels and label images of an OME-Zarr image."""
    import marimo as mo

    img = read_image(source)
    meta = img.image.metadata
    levels = [
        {"level": i, "shape": " x ".join(map(str, d.shape)), "dtype": str(d.dtype)}
        for i, d in enumerate(img.image.data)
    ]
    channels = [
        {"index": i, "label": name, "visible": visible}
        for i, (name, visible) in enumerate(
            zip(meta.get("channel_names") or [], meta.get("visible") or [], strict=False)
        )
    ]
    return mo.vstack(
        [
            mo.md(
                f"**axes** `{', '.join(img.axes)}` · **NGFF** {OME_ZARR_VERSION} · "
                f"**labels** {', '.join(img.labels) or '—'}"
            ),
            mo.hstack(
                [mo.ui.table(channels, selection=None), mo.ui.table(levels, selection=None)],
                widths="equal",
            ),
        ]
    )


# --------------------------------------------------------------------------- viewing


class _CORSHandler(SimpleHTTPRequestHandler):
    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()

    def log_message(self, *args: Any) -> None:  # quiet
        pass


_SERVERS: dict[Path, str] = {}


def serve(directory: str | Path) -> str:
    """Serve ``directory`` read-only over HTTP on localhost (CORS enabled); return its URL.

    The viewer loads local OME-Zarr images (and their labels) through this, like remote ones.
    """
    directory = Path(directory).resolve()
    if directory not in _SERVERS:
        handler = partial(_CORSHandler, directory=str(directory))
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        _SERVERS[directory] = f"http://127.0.0.1:{server.server_address[1]}"
    return _SERVERS[directory]


class Viewer(anywidget.AnyWidget):
    """anywidget around the BioNGFF vizarr viewer (https://github.com/BioNGFF/vizarr)."""

    _esm = Path(__file__).with_name("vizarr_widget.js")
    sources = traitlets.List(traitlets.Unicode()).tag(sync=True)
    extent = traitlets.List(traitlets.Float()).tag(sync=True)  # fit view: [x0, y0, x1, y1]
    height = traitlets.Unicode("500px").tag(sync=True)


def viewer(source: str | Path, *, height: str = "500px") -> Any:
    """Interactive multiscale viewer for a local or remote OME-Zarr v0.5 image.

    Remote images are streamed by the browser directly; local images are served over
    localhost. Label images under ``labels/`` are listed in the viewer and can be toggled.
    """
    import marimo as mo

    img = read_image(source)
    url = img.uri
    if "://" not in url or url.startswith("file://"):
        path = Path(url.removeprefix("file://"))
        url = f"{serve(path.parent)}/{path.name}"
    return mo.ui.anywidget(Viewer(sources=[url], extent=img.extent(), height=height))
