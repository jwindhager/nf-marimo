"""Shared pytest configuration (generic tests and example tests)."""

import shutil

import pytest


def pytest_collection_modifyitems(config, items):
    """Skip integration tests when nextflow or docker are unavailable."""
    missing = [t for t in ("nextflow", "docker") if shutil.which(t) is None]
    if not missing:
        return
    skip = pytest.mark.skip(reason=f"requires {', '.join(missing)}")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)
