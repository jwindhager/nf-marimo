"""Validate module meta.yml files against the nf-core modules meta schema."""

import json
import sys
from pathlib import Path

import jsonschema
import yaml

SCHEMA = Path(__file__).parents[1] / "tests" / "fixtures" / "meta-schema.json"


def main(paths: list[str]) -> int:
    """Validate ``paths``; return a non-zero exit code on errors."""
    validator = jsonschema.Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8")))
    failed = 0
    for p in paths:
        for err in validator.iter_errors(yaml.safe_load(Path(p).read_text(encoding="utf-8"))):
            print(f"{p}: {'/'.join(map(str, err.path))}: {err.message}")
            failed = 1
    return failed


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
