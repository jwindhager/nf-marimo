"""Reusable Groovy channel-operator snippets.

Operators are only ever expressed in Groovy: every materialization of a channel goes through
Nextflow, so the same snippet is used by per-cell test runs and by the exported pipeline.
"""

from __future__ import annotations

# A URI with a scheme other than file:// is treated as remote (read in-process by the tool);
# everything else is staged as a local path.
_REMOTE_RE = r"/^(?!file:)[A-Za-z][A-Za-z0-9+.\-]*:\/\/.+/"


def stage_or_url() -> str:
    """Split ``[meta, data]`` into ``[meta, data_path_or_[], data_url_or_'']``.

    Use this to feed modules following the remote-or-local idiom
    ``tuple val(meta), path(data, stageAs: 'input/*'), val(data_url)``: local data (strings
    without a URI scheme, or ``Path`` objects emitted by upstream processes) is staged as
    files; remote URIs (``https://``, ``s3://``, ``gs://``, ...) are passed through as values.
    Works for any kind of file or directory; no file endings are inspected.
    """
    return (
        "map { meta, data ->\n"
        "    data instanceof Path\n"
        "        ? [meta, data, '']\n"
        f"        : (data.toString() ==~ {_REMOTE_RE}\n"
        "            ? [meta, [], data.toString()]\n"
        "            : [meta, file(data.toString(), checkIfExists: true), ''])\n"
        "}"
    )
