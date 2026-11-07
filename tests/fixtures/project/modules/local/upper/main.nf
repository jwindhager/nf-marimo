process UPPER {
    tag "${meta.id}"
    label 'process_single'

    input:
    tuple val(meta), path(text, stageAs: 'input/*'), val(text_url)
    val suffix

    output:
    tuple val(meta), path("${prefix}.txt"), emit: txt
    path "versions.yml", topic: versions, emit: versions

    script:
    prefix = task.ext.prefix ?: "${meta.id}"
    def source = text ? "cat ${text}" : "curl -sfL ${text_url}"
    """
    ${source} | tr '[:lower:]' '[:upper:]' > ${prefix}.txt
    echo "${suffix}" >> ${prefix}.txt

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        coreutils: \$(tr --version | head -n1 | sed 's/.* //')
    END_VERSIONS
    """
}
