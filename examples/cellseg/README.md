# Example: OME-Zarr cell segmentation & quantification

[`omezarr_cellseg.py`](omezarr_cellseg.py) is an nf-marimo notebook that:

1. explores a Cell Painting image (U2OS cells, [IDR idr0033A](https://idr.openmicroscopy.org/webclient/?show=screen-1751),
   OME-Zarr v0.5) streamed from the cloud,
2. segments cells with Cellpose (`CELLPOSE_OMEZARR`), writing a new OME-Zarr with the image and
   `labels/cellpose`,
3. shows the segmentation as a label layer on the image,
4. quantifies single cells into a CSV table (`QUANTIFY_OMEZARR`; scikit-image `regionprops`),
5. explores the cells with scanpy/squidpy (phenotypes, spatial neighbourhoods),

and exports to an nf-core pipeline (`cellseg`). The example data (test samplesheet) is defined
in the notebook's first cell.

## Contents

| Path                        | What                                                                                  |
| --------------------------- | ------------------------------------------------------------------------------------- |
| `omezarr_cellseg.py`        | the notebook                                                                          |
| `omezarr_utils.py`          | notebook helpers: OME-Zarr reading (ome-zarr-py), viewer, channel table               |
| `vizarr_widget.js`          | anywidget front end of the [BioNGFF vizarr](https://github.com/BioNGFF/vizarr) viewer |
| `modules/local/`            | `cellpose_omezarr`, `quantify_omezarr` (nf-core module layout, nf-test)               |
| `containers/omezarr-tools/` | Dockerfile + conda environments (CPU, GPU) of the modules                             |
| `tests/`                    | pytest (module metadata, export, end-to-end) and nf-test config                       |

## Conventions

- **OME-Zarr v0.5 only** (zarr v3). Inputs are recognised by URI scheme and NGFF metadata, never
  by file endings.
- **OME-Zarr I/O goes through [ome-zarr-py](https://github.com/ome/ome-zarr-py)** (reader and
  writers) rather than plain zarr.
- **Remote or local input**: both modules take `tuple val(meta), path(image), val(image_url)`;
  exactly one of the two is set (`nfm.ops.stage_or_url()` splits a samplesheet column
  accordingly). Remote images are read in place, local ones are staged.
- **Outputs**: a self-contained OME-Zarr (image + `labels/<name>`) and a CSV table with the
  `regionprops` columns (pixel units of the quantified level; per-channel intensity columns
  named after the channels, e.g. `intensity_mean-Nuclei`).
- **Viewer**: the BioNGFF vizarr viewer (`@biongff/vizarr`, pinned) shows images and their
  label images; local OME-Zarr is served to it over localhost.
- **GPU**: `CELLPOSE_OMEZARR` carries the nf-core `process_gpu` label and switches to the GPU
  image when `task.accelerator` is set (`-profile docker,gpu` in the exported pipeline).

## Usage

```bash
pixi run cellseg-build-containers   # nf-marimo/omezarr-tools:0.2.0 (+ -gpu)
pixi run cellseg-edit               # open the notebook (marimo, lazy mode)
pixi run cellseg-export             # -> build/nf-cellseg (nf-core pipeline, linted)
nextflow run build/nf-cellseg -profile test,docker[,gpu] --outdir results

pixi run cellseg-test               # pytest (incl. end-to-end runs with nextflow + docker)
pixi run cellseg-nf-test            # nf-test of the local modules
```

The containers are built locally for now; the nf-core convention is a pinned
[Seqera Containers](https://seqera.io/containers) image built from the modules'
`environment.yml`.

### Running with or without a GPU

Only `CELLPOSE_OMEZARR` uses a GPU (via the nf-core `process_gpu` label); everything else
runs on the CPU. GPU runs need an NVIDIA driver supporting CUDA 13.0 and the
[NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/),
so that `docker run --gpus all ...` works.

1. **Build the container(s)** (`pixi run cellseg-build-containers` builds both):

   ```bash
   cd examples/cellseg/containers/omezarr-tools
   docker build -t nf-marimo/omezarr-tools:0.2.0 .            # CPU (always needed)
   docker build -t nf-marimo/omezarr-tools:0.2.0-gpu \
     --build-arg ENV_FILE=environment-gpu.yml --build-arg CUDA=13.0 .   # GPU (optional)
   ```

2. **Notebook and tests**: the GPU is used automatically if an NVIDIA driver is detected
   (`nvidia-smi`). Override this with the `NFM_GPU` environment variable, or per notebook
   with `nfm.pipeline(..., gpu=False)` / `gpu=True`:

   ```bash
   NFM_GPU=0 pixi run cellseg-edit   # CPU only, even on a GPU machine
   NFM_GPU=1 pixi run cellseg-edit   # GPU
   NFM_GPU=0 pixi run cellseg-test
   ```

3. **Exported pipeline**: CPU by default; add the `gpu` profile to use the GPU:

   ```bash
   nextflow run build/nf-cellseg -profile test,docker --outdir results       # CPU
   nextflow run build/nf-cellseg -profile test,docker,gpu --outdir results   # GPU
   ```

4. **Module tests (nf-test)**: likewise, with or without the `gpu` profile:

   ```bash
   cd examples/cellseg
   nf-test test modules/local --profile docker       # CPU
   nf-test test modules/local --profile docker,gpu   # GPU
   ```

## Known limitations

- Cellpose runs on the full-resolution level by default; pass `ext_args="--level 1"` for a
  faster, coarser test run.
