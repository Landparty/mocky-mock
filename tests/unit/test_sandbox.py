from pathlib import Path

from mockymock.runtime.sandbox import sandbox_dir


def test_sandbox_dir_defaults_to_system_temp():
    with sandbox_dir() as tmp:
        assert tmp.is_dir()
        assert tmp.name.startswith("mockymock-")
    assert not tmp.exists()


def test_sandbox_dir_under_given_root_creates_root_and_cleans_up(tmp_path: Path):
    root = tmp_path / "deep" / "work"  # does not exist yet
    with sandbox_dir(root=root) as tmp:
        assert tmp.parent == root
        assert tmp.is_dir()
    assert not tmp.exists()
    assert root.is_dir()  # root itself survives
