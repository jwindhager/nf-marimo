import pytest

from nf_marimo import catalog


def test_local_module(project):
    ref = catalog.resolve("local/upper", project)
    assert ref.id == "local/upper"
    assert ref.process_name == "UPPER"
    assert ref.spec.input_keys == ["text", "suffix"]


def test_unknown_modules(project):
    with pytest.raises(FileNotFoundError):
        catalog.resolve("local/missing", project)
    with pytest.raises(ValueError, match="unknown module source"):
        catalog.resolve("other/x", project)


def test_search_local(project):
    hits = catalog.search("count", notebook_dir=project, sources=("local",))
    assert [h.id for h in hits] == ["local/count"]
    assert len(catalog.search("", notebook_dir=project, sources=("local",))) == 2


def test_cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("NFM_CACHE_DIR", str(tmp_path / "cache"))
    assert catalog.cache_dir() == tmp_path / "cache"
    assert catalog.cache_dir().is_dir()
