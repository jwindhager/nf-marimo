# Local fallback image for the OME-Zarr modules.
# Preferred (nf-core convention): a pinned Seqera Containers image built from environment.yml
# at https://seqera.io/containers - replace the `container` directive in the modules then.
#
#   docker build -t nf-marimo/omezarr-tools:0.2.0 .
#   docker build -t nf-marimo/omezarr-tools:0.2.0-gpu \
#     --build-arg ENV_FILE=environment-gpu.yml --build-arg CUDA=13.0 .
FROM mambaorg/micromamba:2.10.0
ARG ENV_FILE=environment.yml
# CUDA version to solve GPU packages for (no GPU is present at build time); empty: CPU-only
ARG CUDA=""
COPY --chown=$MAMBA_USER:$MAMBA_USER ${ENV_FILE} /tmp/environment.yml
RUN CONDA_OVERRIDE_CUDA="${CUDA}" micromamba install -y -n base -f /tmp/environment.yml \
    && micromamba clean --all --yes
# procps provides `ps`, needed by Nextflow for task metrics
USER root
RUN apt-get update && apt-get install -y --no-install-recommends procps \
    && rm -rf /var/lib/apt/lists/*
USER $MAMBA_USER
ENV PATH=/opt/conda/bin:$PATH
