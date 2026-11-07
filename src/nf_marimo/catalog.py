"""Module catalog with pluggable sources (nf-core, local)."""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import httpx

from .meta import ModuleSpec, load_meta

NF_CORE_INDEX_URL = "https://nf-co.re/components.json"
NF_CORE_RAW_URL = "https://raw.githubusercontent.com/nf-core/modules/{sha}/{path}"
INDEX_TTL_SECONDS = 24 * 3600

Source = Literal["nf-core", "local"]


def cache_dir() -> Path:
    """Return the nf-marimo cache directory (``$NFM_CACHE_DIR`` or ``~/.cache/nf-marimo``)."""
    d = Path(os.environ.get("NFM_CACHE_DIR", Path.home() / ".cache" / "nf-marimo"))
    d.mkdir(parents=True, exist_ok=True)
    return d


@dataclass(frozen=True)
class ModuleRef:
    """A resolved reference to a module that can be included in a workflow."""

    source: Source
    name: str  # e.g. "fastqc", "bwa/mem", "my_module"
    directory: Path  # local directory containing main.nf + meta.yml
    sha: str | None = None  # git sha (nf-core only)

    @property
    def id(self) -> str:
        """Identifier as used in notebooks, e.g. ``nf-core/cellpose``."""
        return f"{self.source}/{self.name}"

    @property
    def main_nf(self) -> Path:
        """Path to the module's ``main.nf``."""
        return self.directory / "main.nf"

    @property
    def spec(self) -> ModuleSpec:
        """Parsed module metadata."""
        return load_meta(self.directory / "meta.yml")

    @property
    def process_name(self) -> str:
        """Name of the Nextflow process defined in ``main.nf``."""
        m = re.search(
            r"^\s*process\s+([A-Za-z0-9_]+)\s*\{", self.main_nf.read_text(encoding="utf-8"), re.M
        )
        if not m:
            raise ValueError(f"no process definition found in {self.main_nf}")
        return m.group(1)


@dataclass(frozen=True)
class CatalogEntry:
    """Search result."""

    source: Source
    name: str
    description: str
    keywords: tuple[str, ...]
    sha: str | None = None

    @property
    def id(self) -> str:
        """Identifier as used in notebooks, e.g. ``nf-core/cellpose``."""
        return f"{self.source}/{self.name}"


# --------------------------------------------------------------------------- nf-core


def _nf_core_index(refresh: bool = False) -> dict:
    path = cache_dir() / "components.json"
    fresh = path.exists() and time.time() - path.stat().st_mtime < INDEX_TTL_SECONDS
    if refresh or not fresh:
        try:
            r = httpx.get(NF_CORE_INDEX_URL, timeout=120, follow_redirects=True)
            r.raise_for_status()
            path.write_bytes(r.content)
        except httpx.HTTPError:
            if not path.exists():
                raise
    return json.loads(path.read_text(encoding="utf-8"))


def _module_name(entry: dict) -> str:
    """Install name, e.g. ``bwa/mem`` (index names flatten it to ``bwa_mem``)."""
    path = str(entry.get("path", ""))
    if path.startswith("modules/nf-core/") and path.endswith("/meta.yml"):
        return path.removeprefix("modules/nf-core/").removesuffix("/meta.yml")
    return str(entry["name"])


def _nf_core_entry(name: str) -> dict:
    for m in _nf_core_index()["modules"]:
        if _module_name(m) == name:
            return m
    raise KeyError(f"nf-core module {name!r} not found in {NF_CORE_INDEX_URL}")


def latest_sha(name: str) -> str:
    """Git sha of the latest commit touching nf-core module ``name``."""
    return str(_nf_core_entry(name)["git_sha"])


def fetch_nf_core_module(name: str, sha: str | None = None) -> ModuleRef:
    """Download nf-core module ``name`` at ``sha`` (default: latest) into the cache."""
    entry = _nf_core_entry(name)
    sha = sha or str(entry["git_sha"])
    target = cache_dir() / "modules" / "nf-core" / sha / name
    if not (target / "main.nf").exists():
        prefix = f"modules/nf-core/{name}/"
        with httpx.Client(timeout=60, follow_redirects=True) as client:
            for f in entry["files"]:
                if "/tests/" in f or not f.startswith(prefix):
                    continue
                r = client.get(NF_CORE_RAW_URL.format(sha=sha, path=f))
                r.raise_for_status()
                out = target / f.removeprefix(prefix)
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(r.content)
    return ModuleRef("nf-core", name, target, sha)


# --------------------------------------------------------------------------- local


def local_modules_dir(notebook_dir: Path) -> Path:
    """Directory holding local modules for a notebook."""
    return notebook_dir / "modules" / "local"


def local_module(name: str, notebook_dir: Path) -> ModuleRef:
    """Resolve local module ``name`` relative to ``notebook_dir``."""
    d = local_modules_dir(notebook_dir) / name
    if not (d / "main.nf").exists():
        raise FileNotFoundError(f"local module {name!r} not found at {d}")
    return ModuleRef("local", name, d)


# --------------------------------------------------------------------------- API


def resolve(module: str, notebook_dir: Path, sha: str | None = None) -> ModuleRef:
    """Resolve a module identifier such as ``nf-core/cellpose`` or ``local/foo``."""
    source, _, name = module.partition("/")
    if source == "nf-core":
        return fetch_nf_core_module(name, sha)
    if source == "local":
        return local_module(name, notebook_dir)
    raise ValueError(f"unknown module source {source!r} in {module!r} (use 'nf-core/' or 'local/')")


def search(
    query: str = "",
    notebook_dir: Path | None = None,
    sources: tuple[Source, ...] = ("local", "nf-core"),
    limit: int = 50,
) -> list[CatalogEntry]:
    """Search modules by name, keywords and description (all terms must match)."""
    terms = query.lower().split()
    results: list[CatalogEntry] = []

    def matches(*fields: str) -> bool:
        text = " ".join(fields).lower()
        return all(t in text for t in terms)

    if "local" in sources and notebook_dir is not None:
        root = local_modules_dir(notebook_dir)
        for meta in sorted(root.glob("*/meta.yml")) if root.exists() else []:
            spec = load_meta(meta)
            name = meta.parent.name
            if matches(name, spec.description, *spec.keywords):
                results.append(CatalogEntry("local", name, spec.description, spec.keywords))
    if "nf-core" in sources:
        for m in _nf_core_index()["modules"]:
            meta = m.get("meta") or {}
            desc = str(meta.get("description", "")).strip()
            kws = tuple(str(k) for k in meta.get("keywords") or ())
            name = _module_name(m)
            if matches(name, desc, *kws):
                results.append(CatalogEntry("nf-core", name, desc, kws, m.get("git_sha")))
    return results[:limit]
