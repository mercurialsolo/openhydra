"""Shared test fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from openhydra.config import EngineConfig, MemoryConfig, OpenHydraConfig
from openhydra.db import Database


@pytest.fixture
def tmp_dir(tmp_path: Path) -> Path:
    """Temporary directory for test state."""
    return tmp_path


@pytest.fixture
def config(tmp_dir: Path) -> OpenHydraConfig:
    """Test configuration with temporary state directory."""
    return OpenHydraConfig(
        engine=EngineConfig(state_dir=tmp_dir),
        memory=MemoryConfig(sqlite_path=tmp_dir / "memory.db"),
    )


@pytest.fixture
async def db(tmp_dir: Path) -> Database:
    """Connected test database."""
    database = Database(tmp_dir / "test.db")
    await database.connect()
    yield database
    await database.close()
