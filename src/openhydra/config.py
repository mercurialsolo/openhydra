"""Configuration loading from YAML files and environment variables."""

from __future__ import annotations

import logging
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


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
    default_provider: str = "claude-sdk"
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
    api_key: str = ""


@dataclass
class SlackConfig:
    enabled: bool = False
    bot_token: str = ""   # xoxb-...  (env: OPENHYDRA_SLACK_BOT_TOKEN)
    app_token: str = ""   # xapp-...  (env: OPENHYDRA_SLACK_APP_TOKEN)
    allowed_users: list[str] = field(default_factory=list)  # empty = allow all


@dataclass
class DiscordConfig:
    enabled: bool = False
    bot_token: str = ""   # env: OPENHYDRA_DISCORD_BOT_TOKEN
    allowed_users: list[str] = field(default_factory=list)  # empty = allow all


@dataclass
class WhatsAppConfig:
    enabled: bool = False
    backend: str = "baileys"         # "baileys" | "cloud-api"
    node_path: str = "node"
    auth_dir: str = ""               # default: state_dir/whatsapp_auth
    # Legacy cloud API fields (kept for backward compat)
    access_token: str = ""           # env: OPENHYDRA_WHATSAPP_ACCESS_TOKEN
    phone_number_id: str = ""
    verify_token: str = ""           # webhook verification
    allowed_phones: list[str] = field(default_factory=list)  # empty = allow all


@dataclass
class HeartbeatConfig:
    enabled: bool = False
    interval_seconds: float = 300.0     # 5 min default
    quiet_hours_start: int | None = None  # 0-23
    quiet_hours_end: int | None = None


@dataclass
class ChannelsConfig:
    slack: SlackConfig = field(default_factory=SlackConfig)
    discord: DiscordConfig = field(default_factory=DiscordConfig)
    whatsapp: WhatsAppConfig = field(default_factory=WhatsAppConfig)
    debounce_delay_ms: int = 1500
    debounce_max_wait_ms: int = 5000
    approval_timeout_seconds: float = 120.0
    approval_timeout_action: str = "reject"  # reject | approve | ignore


@dataclass
class McpServerConfig:
    name: str = ""
    transport: str = "stdio"  # "stdio" | "sse"
    command: str | None = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    url: str | None = None


@dataclass
class McpTemplatesConfig:
    browser: str = "claude-in-chrome"  # "claude-in-chrome" | "playwright" | "none"
    search: str = "tavily"  # "tavily" | "duckduckgo" | "perplexity" | "none"


@dataclass
class ToolsConfig:
    mcp_servers: list[McpServerConfig] = field(default_factory=list)
    templates: McpTemplatesConfig = field(default_factory=McpTemplatesConfig)


@dataclass
class OpenHydraConfig:
    engine: EngineConfig = field(default_factory=EngineConfig)
    agents: AgentsConfig = field(default_factory=AgentsConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    skills: SkillsConfig = field(default_factory=SkillsConfig)
    tools: ToolsConfig = field(default_factory=ToolsConfig)
    web: WebConfig = field(default_factory=WebConfig)
    channels: ChannelsConfig = field(default_factory=ChannelsConfig)
    heartbeat: HeartbeatConfig = field(default_factory=HeartbeatConfig)


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

    # Parse MCP server configs
    if "tools" in raw and "mcp_servers" in raw["tools"]:
        for srv_raw in raw["tools"]["mcp_servers"]:
            config.tools.mcp_servers.append(McpServerConfig(
                name=srv_raw.get("name", ""),
                transport=srv_raw.get("transport", "stdio"),
                command=srv_raw.get("command"),
                args=srv_raw.get("args", []),
                env=srv_raw.get("env", {}),
                url=srv_raw.get("url"),
            ))

    # Parse MCP templates config
    if "tools" in raw and "templates" in raw["tools"]:
        tpl = raw["tools"]["templates"]
        config.tools.templates = McpTemplatesConfig(
            browser=tpl.get("browser", "claude-in-chrome"),
            search=tpl.get("search", "tavily"),
        )

    # Parse web config
    if "web" in raw:
        web_raw = raw["web"]
        if "enabled" in web_raw:
            config.web.enabled = web_raw["enabled"]
        if "host" in web_raw:
            config.web.host = web_raw["host"]
        if "api_key" in web_raw:
            config.web.api_key = _resolve_env_vars(web_raw["api_key"])

    if api_key := os.environ.get("OPENHYDRA_WEB_API_KEY"):
        config.web.api_key = api_key

    # Parse channels config
    if "channels" in raw:
        ch_raw = raw["channels"]

        if "slack" in ch_raw:
            s = ch_raw["slack"]
            config.channels.slack = SlackConfig(
                enabled=s.get("enabled", False),
                bot_token=_resolve_env_vars(s.get("bot_token", "")),
                app_token=_resolve_env_vars(s.get("app_token", "")),
                allowed_users=s.get("allowed_users", []),
            )

        if "discord" in ch_raw:
            d = ch_raw["discord"]
            config.channels.discord = DiscordConfig(
                enabled=d.get("enabled", False),
                bot_token=_resolve_env_vars(d.get("bot_token", "")),
                allowed_users=d.get("allowed_users", []),
            )

        if "whatsapp" in ch_raw:
            w = ch_raw["whatsapp"]
            config.channels.whatsapp = WhatsAppConfig(
                enabled=w.get("enabled", False),
                backend=w.get("backend", "baileys"),
                node_path=w.get("node_path", "node"),
                auth_dir=w.get("auth_dir", ""),
                access_token=_resolve_env_vars(w.get("access_token", "")),
                phone_number_id=w.get("phone_number_id", ""),
                verify_token=_resolve_env_vars(w.get("verify_token", "")),
                allowed_phones=w.get("allowed_phones", []),
            )

        if "debounce_delay_ms" in ch_raw:
            config.channels.debounce_delay_ms = ch_raw["debounce_delay_ms"]
        if "debounce_max_wait_ms" in ch_raw:
            config.channels.debounce_max_wait_ms = ch_raw["debounce_max_wait_ms"]
        if "approval_timeout_seconds" in ch_raw:
            config.channels.approval_timeout_seconds = ch_raw["approval_timeout_seconds"]
        if "approval_timeout_action" in ch_raw:
            config.channels.approval_timeout_action = ch_raw["approval_timeout_action"]

    # Parse heartbeat config
    if "heartbeat" in raw:
        hb = raw["heartbeat"]
        config.heartbeat = HeartbeatConfig(
            enabled=hb.get("enabled", False),
            interval_seconds=hb.get("interval_seconds", 300.0),
            quiet_hours_start=hb.get("quiet_hours_start"),
            quiet_hours_end=hb.get("quiet_hours_end"),
        )

    # Environment variable overrides for channel tokens
    if slack_bot := os.environ.get("OPENHYDRA_SLACK_BOT_TOKEN"):
        config.channels.slack.bot_token = slack_bot
    if slack_app := os.environ.get("OPENHYDRA_SLACK_APP_TOKEN"):
        config.channels.slack.app_token = slack_app
    if discord_token := os.environ.get("OPENHYDRA_DISCORD_BOT_TOKEN"):
        config.channels.discord.bot_token = discord_token
    if wa_token := os.environ.get("OPENHYDRA_WHATSAPP_ACCESS_TOKEN"):
        config.channels.whatsapp.access_token = wa_token

    # Default skill source: ./skills if no sources configured
    if not config.skills.sources:
        config.skills.sources.append(SkillSourceConfig(type="filesystem", path="./skills"))

    # Default memory path
    if config.memory.sqlite_path is None:
        config.memory.sqlite_path = config.engine.state_dir / "memory.db"

    return config


def ensure_api_key(config: OpenHydraConfig) -> None:
    """Generate and persist an API key if none is configured.

    Only triggers when ``web.api_key`` is empty and the
    ``OPENHYDRA_WEB_API_KEY`` env var is not set.  The generated key
    is written back to ``~/.openhydra/openhydra.yaml`` so it survives
    restarts.
    """
    if config.web.api_key:
        return  # already set via env or config file

    key = secrets.token_hex(16)
    config.web.api_key = key

    # Persist to user config
    user_config_path = Path.home() / ".openhydra" / "openhydra.yaml"
    existing: dict = {}
    if user_config_path.exists():
        with open(user_config_path) as f:
            existing = yaml.safe_load(f) or {}

    existing.setdefault("web", {})["api_key"] = key
    user_config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(user_config_path, "w") as f:
        yaml.safe_dump(existing, f, default_flow_style=False)

    logger.info("Generated API key: %s", key)
