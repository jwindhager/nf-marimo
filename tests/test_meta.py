import json

import jsonschema
import pytest
import yaml

from nf_marimo.meta import load_meta


def test_nf_core_cellpose(fixtures):
    spec = load_meta(fixtures / "nf-core-cellpose.meta.yml")
    assert spec.name == "cellpose"
    assert spec.input_keys == ["image", "model"]
    image = spec.input("image")
    assert image.is_tuple
    assert image.has_meta
    assert spec.output_emits == ["mask", "flows", "cells"]
    assert spec.documentation
    assert "cellpose" in spec.documentation


@pytest.mark.parametrize("module", ["upper", "count"])
def test_local_modules(project, fixtures, module):
    path = project / "modules" / "local" / module / "meta.yml"
    schema = json.loads((fixtures / "meta-schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(yaml.safe_load(path.read_text(encoding="utf-8")), schema)
    spec = load_meta(path)
    assert spec.input_keys[0] == "text"
    assert spec.input("text").elements[2].name == "text_url"


def test_unknown_input(fixtures):
    spec = load_meta(fixtures / "nf-core-cellpose.meta.yml")
    with pytest.raises(KeyError, match="no input 'reads'"):
        spec.input("reads")
