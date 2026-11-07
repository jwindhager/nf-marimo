process COUNT {
    tag "${meta.id}"
    label 'process_single'

    input:
    tuple val(meta), path(text, stageAs: 'input/*'), val(text_url)
    val mode

    output:
    tuple val(meta), path("${prefix}.tsv"), emit: tsv
    path "versions.yml", topic: versions, emit: versions

    script:
    prefix = task.ext.prefix ?: "${meta.id}"
    def source = text ? "cat ${text}" : "curl -sfL ${text_url}"
    """
    printf "${mode}\\t%s\\n" \$(${source} | wc -${mode}) > ${prefix}.tsv

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        coreutils: \$(wc --version | head -n1 | sed 's/.* //')
    END_VERSIONS
    """
}
