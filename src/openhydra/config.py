"""Configuration loading from YAML files and environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class EngineConfig:
    max_concurrent_sessions: int = 2
    max_retries_per_step: int = 3
    state_dir: Path = field(default_factory=lambda: Path.home() / ".openhydra")


@dataclass
class ProviderConfig:
    model: str | None = None
    api_key: str | None = None
    base_url: str | None = None


@dataclass
class AgentsConfig:
    default_provider: str = "anthropic-api"
    providers: dict[str, ProviderConfig] = field(default_factory=dict)


@dataclass
class MemoryConfig:
    backend: str = "sqlite"  # sqlite | qdrant | chroma | in-memory
    embedding_provider: str = "tfidf"  # anthropic | openai | sentence-transformers | tfidf
    sqlite_path: Path | None = None
    qdrant_url: str = "http://localhost:6333"


@dataclass
class SkillSourceConfig:
    type: str = "filesystem"  # filesystem | git | http
    path: str | None = None
    url: str | None = None
    branch: str = "main"


@dataclass
class SkillsConfig:
    sources: list[SkillSourceConfig] = field(default_factory=list)


@dataclass
class WebConfig:
    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = 7070


@dataclass
class OpenHydraConfig:
    engine: EngineConfig = field(default_factory=EngineConfig)
    agents: AgentsConfig = field(default_factory=AgentsConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    skills: SkillsConfig = field(default_factory=SkillsConfig)
    web: WebConfig = field(default_factory=WebConfig)


def _resolve_env_vars(value: str) -> str:
    """Resolve ${ENV_VAR} references in config values."""
    if isinstance(value, str) and "${" in value:
        import re

        def replacer(match: re.Match) -> str:
            var_name = match.group(1)
            return os.environ.get(var_name, match.group(0))

        return re.sub(r"\$\{(\w+)\}", replacer, value)
    return value


def load_config(config_path: Path | None = None) -> OpenHydraConfig:
    """Load configuration from YAML file and environment variables.

    Search order:
    1. Explicit path (if provided)
    2. .openhydra/openhydra.yaml (project-local)
    3. ~/.openhydra/openhydra.yaml (user-global)
    4. Defaults
    """
    search_paths = []
    if config_path:
        search_paths.append(config_path)
    search_paths.extend([
        Path.cwd() / ".openhydra" / "openhydra.yaml",
        Path.home() / ".openhydra" / "openhydra.yaml",
    ])

    raw: dict = {}
    for path in search_paths:
        if path.exists():
            with open(path) as f:
                raw = yaml.safe_load(f) or {}
            break

    # Apply environment variable overrides
    config = OpenHydraConfig()

    if state_dir := os.environ.get("OPENHYDRA_STATE_DIR"):
        config.engine.state_dir = Path(state_dir)
    elif "engine" in raw and "state_dir" in raw["engine"]:
        config.engine.state_dir = Path(os.path.expanduser(raw["engine"]["state_dir"]))

    if max_concurrent := os.environ.get("OPENHYDRA_MAX_CONCURRENT_SESSIONS"):
        config.engine.max_concurrent_sessions = int(max_concurrent)
    elif "engine" in raw and "max_concurrent_sessions" in raw["engine"]:
        config.engine.max_concurrent_sessions = raw["engine"]["max_concurrent_sessions"]

    if provider := os.environ.get("OPENHYDRA_DEFAULT_PROVIDER"):
        config.agents.default_provider = provider
    elif "agents" in raw and "default_provider" in raw["agents"]:
        config.agents.default_provider = raw["agents"]["default_provider"]

    if backend := os.environ.get("OPENHYDRA_MEMORY_BACKEND"):
        config.memory.backend = backend
    elif "memory" in raw and "backend" in raw["memory"]:
        config.memory.backend = raw["memory"]["backend"]

    if embedding := os.environ.get("OPENHYDRA_EMBEDDING_PROVIDER"):
        config.memory.embedding_provider = embedding
    elif "memory" in raw and "embedding_provider" in raw["memory"]:
        config.memory.embedding_provider = raw["memory"]["embedding_provider"]

    if port := os.environ.get("OPENHYDRA_WEB_PORT"):
        config.web.port = int(port)
    elif "web" in raw and "port" in raw["web"]:
        config.web.port = raw["web"]["port"]

    # Parse provider configs
    if "agents" in raw and "providers" in raw["agents"]:
        for name, prov_raw in raw["agents"]["providers"].items():
            config.agents.providers[name] = ProviderConfig(
                model=prov_raw.get("model"),
                api_key=_resolve_env_vars(prov_raw.get("api_key", "")),
                base_url=prov_raw.get("base_url"),
            )

    # Parse skill sources
    if "skills" in raw and "sources" in raw["skills"]:
        for src_raw in raw["skills"]["sources"]:
            config.skills.sources.append(SkillSourceConfig(
                type=src_raw.get("type", "filesystem"),
                path=src_raw.get("path"),
                url=src_raw.get("url"),
                branch=src_raw.get("branch", "main"),
            ))

    # Default skill source: ./skills if no sources configured
    if not config.skills.sources:
        config.skills.sources.append(SkillSourceConfig(type="filesystem", path="./skills"))

    # Default memory path
    if config.memory.sqlite_path is None:
        config.memory.sqlite_path = config.engine.state_dir / "memory.db"

    return config
