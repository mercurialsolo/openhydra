"""Tests for Workspace."""

from __future__ import annotations

from pathlib import Path

import pytest

from openhydra.events import EventBus
from openhydra.workflow.workspace import Workspace


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    return Workspace("wf-001", tmp_path, EventBus())


def test_creates_directory(workspace: Workspace) -> None:
    assert workspace.path.exists()
    assert workspace.path.is_dir()


def test_register_artifact_with_content(workspace: Workspace) -> None:
    file_hash = workspace.register_artifact("output.txt", b"hello world")
    assert file_hash is not None
    assert (workspace.path / "output.txt").read_bytes() == b"hello world"


def test_register_artifact_from_disk(workspace: Workspace) -> None:
    (workspace.path / "existing.txt").write_text("existing file")
    file_hash = workspace.register_artifact("existing.txt")
    assert file_hash is not None


def test_register_artifact_not_found(workspace: Workspace) -> None:
    with pytest.raises(FileNotFoundError):
        workspace.register_artifact("nonexistent.txt")


def test_register_nested_path(workspace: Workspace) -> None:
    workspace.register_artifact("subdir/deep/file.py", b"code")
    assert (workspace.path / "subdir" / "deep" / "file.py").exists()


def test_list_artifacts(workspace: Workspace) -> None:
    workspace.register_artifact("a.txt", b"aaa")
    workspace.register_artifact("b.txt", b"bbb")
    artifacts = workspace.list_artifacts()
    assert "a.txt" in artifacts
    assert "b.txt" in artifacts


def test_same_content_same_hash(workspace: Workspace) -> None:
    h1 = workspace.register_artifact("f1.txt", b"same content")
    h2 = workspace.register_artifact("f2.txt", b"same content")
    assert h1 == h2


def test_different_content_different_hash(workspace: Workspace) -> None:
    h1 = workspace.register_artifact("f1.txt", b"content a")
    h2 = workspace.register_artifact("f2.txt", b"content b")
    assert h1 != h2
