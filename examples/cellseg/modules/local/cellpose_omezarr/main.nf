process CELLPOSE_OMEZARR {
    tag "${meta.id}"
    label 'process_medium'
    label 'process_gpu'

    conda "${moduleDir}/environment.yml"
    // TODO: replace with pinned Seqera Containers images built from environment(-gpu).yml
    container "${ task.accelerator ? 'nf-marimo/omezarr-tools:0.2.0-gpu' : 'nf-marimo/omezarr-tools:0.2.0' }"

    input:
    tuple val(meta), path(image, stageAs: 'input/*'), val(image_url)
    val channels
    path model

    output:
    tuple val(meta), path("${prefix}.ome.zarr"), emit: zarr
    path "versions.yml", topic: versions, emit: versions

    when:
    task.ext.when == null || task.ext.when

    script:
    args = task.ext.args ?: ''
    prefix = task.ext.prefix ?: "${meta.id}"
    image_uri = image ? image.toString() : image_url
    model_path = model ? model.toString() : ''
    use_gpu = task.accelerator ? 'true' : ''
    template 'cellpose_omezarr.py'

    stub:
    prefix = task.ext.prefix ?: "${meta.id}"
    """
    mkdir -p ${prefix}.ome.zarr/labels/cellpose
    echo '{"zarr_format": 3, "node_type": "group", "attributes": {"ome": {"version": "0.5"}}}' > ${prefix}.ome.zarr/zarr.json

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        cellpose: stub
        ome-zarr: stub
    END_VERSIONS
    """
}
