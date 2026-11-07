process QUANTIFY_OMEZARR {
    tag "${meta.id}"
    label 'process_single'

    conda "${moduleDir}/environment.yml"
    // TODO: replace with a pinned Seqera Containers image built from environment.yml
    container "nf-marimo/omezarr-tools:0.2.0"

    input:
    tuple val(meta), path(image, stageAs: 'input/*'), val(image_url)
    val label_name

    output:
    tuple val(meta), path("${prefix}.csv"), emit: csv
    path "versions.yml", topic: versions, emit: versions

    when:
    task.ext.when == null || task.ext.when

    script:
    args = task.ext.args ?: ''
    prefix = task.ext.prefix ?: "${meta.id}"
    image_uri = image ? image.toString() : image_url
    template 'quantify_omezarr.py'

    stub:
    prefix = task.ext.prefix ?: "${meta.id}"
    """
    touch ${prefix}.csv

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        ome-zarr: stub
        scikit-image: stub
    END_VERSIONS
    """
}
