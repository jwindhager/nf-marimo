"""Parse nf-core module ``meta.yml`` files (nested input/output format)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_META_RE = re.compile(r"^meta\d*$")


@dataclass(frozen=True)
class Element:
    """A single element of an input/output channel (e.g. ``meta`` or ``reads``)."""

    name: str
    type: str = "string"
    description: str = ""
    pattern: str | None = None

    @property
    def is_meta(self) -> bool:
        """Whether this element is a Groovy meta map."""
        return self.type == "map" and _META_RE.match(self.name) is not None


@dataclass(frozen=True)
class InputChannelSpec:
    """One positional input channel of a module."""

    index: int
    elements: tuple[Element, ...]

    @property
    def is_tuple(self) -> bool:
        """Whether the channel carries a tuple."""
        return len(self.elements) > 1

    @property
    def has_meta(self) -> bool:
        """Whether the channel carries a meta map."""
        return any(e.is_meta for e in self.elements)

    @property
    def key(self) -> str:
        """Name used to address this channel (first non-meta element)."""
        for e in self.elements:
            if not e.is_meta:
                return e.name
        return self.elements[0].name

    @property
    def description(self) -> str:
        """Description of the keyed element."""
        for e in self.elements:
            if e.name == self.key:
                return e.description.strip()
        return ""


@dataclass(frozen=True)
class OutputSpec:
    """One named output (emit) of a module."""

    emit: str
    elements: tuple[Element, ...]

    @property
    def is_versions(self) -> bool:
        """Whether this is a versions output."""
        return self.emit == "versions" or self.emit.startswith("versions_")


@dataclass(frozen=True)
class ModuleSpec:
    """Parsed module metadata."""

    name: str
    description: str
    keywords: tuple[str, ...]
    inputs: tuple[InputChannelSpec, ...]
    outputs: tuple[OutputSpec, ...]
    tools: tuple[dict[str, Any], ...] = field(default=())

    def input(self, key: str) -> InputChannelSpec:
        """Return the input channel addressed by ``key``."""
        for ch in self.inputs:
            if ch.key == key:
                return ch
        raise KeyError(f"module {self.name!r} has no input {key!r}; inputs: {self.input_keys}")

    @property
    def input_keys(self) -> list[str]:
        """Names of all input channels, in positional order."""
        return [ch.key for ch in self.inputs]

    @property
    def output_emits(self) -> list[str]:
        """Names of all non-versions outputs."""
        return [o.emit for o in self.outputs if not o.is_versions]

    @property
    def documentation(self) -> str | None:
        """Documentation URL of the first tool, if any."""
        for tool in self.tools:
            for info in tool.values():
                if isinstance(info, dict) and info.get("documentation"):
                    return str(info["documentation"])
        return None


def _element(entry: Any) -> Element:
    if not isinstance(entry, dict) or not entry:
        return Element(name=str(entry))
    (name, info), *_ = entry.items()
    if not isinstance(info, dict):
        info = {}
    return Element(
        name=str(name),
        type=str(info.get("type", "string")),
        description=str(info.get("description", "")),
        pattern=info.get("pattern"),
    )


def _elements(item: Any) -> tuple[Element, ...]:
    if isinstance(item, list):
        return tuple(_element(e) for e in item)
    return (_element(item),)


def parse_meta(data: dict[str, Any]) -> ModuleSpec:
    """Parse the content of a ``meta.yml`` (as loaded YAML) into a :class:`ModuleSpec`."""
    inputs = tuple(
        InputChannelSpec(index=i, elements=_elements(item))
        for i, item in enumerate(data.get("input") or [])
    )
    outputs_raw = data.get("output") or {}
    if isinstance(outputs_raw, list):  # legacy flat format: list of single-key dicts
        outputs_raw = {next(iter(o)): [o] for o in outputs_raw}
    outputs = []
    for emit, items in outputs_raw.items():
        # each emit is a list with exactly one channel (tuple or single element)
        item = items[0] if isinstance(items, list) and len(items) == 1 else items
        outputs.append(OutputSpec(emit=str(emit), elements=_elements(item)))
    return ModuleSpec(
        name=str(data.get("name", "")),
        description=str(data.get("description", "")).strip(),
        keywords=tuple(data.get("keywords") or ()),
        inputs=inputs,
        outputs=tuple(outputs),
        tools=tuple(data.get("tools") or ()),
    )


def load_meta(path: str | Path) -> ModuleSpec:
    """Load and parse a ``meta.yml`` file."""
    return parse_meta(yaml.safe_load(Path(path).read_text(encoding="utf-8")))
