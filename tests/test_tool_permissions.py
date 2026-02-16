"""Tests for deny-by-default tool permissions across catalog, executor, and providers."""

from __future__ import annotations

import sys
import types
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from openhydra.agents.base import SessionResult, ToolDefinition
from openhydra.agents.registry import AgentRegistry
from openhydra.roles.catalog import RoleCatalog, RoleDefinition
from openhydra.roles.executor import RoleExecutor
from openhydra.skills.registry import SkillRegistry
from openhydra.tools.executor import ToolExecutor
from openhydra.tools.filesystem import FilesystemToolRouter

# ---------------------------------------------------------------------------
# Catalog: allowed_tools semantics
# ---------------------------------------------------------------------------


def test_role_definition_default_allowed_tools_is_none():
    """Default allowed_tools is None (unrestricted)."""
    role = RoleDefinition(id="test", name="Test")
    assert role.allowed_tools is None


def test_catalog_absent_allowed_tools_is_none(tmp_path):
    """When allowed_tools key is absent in YAML, it becomes None."""
    yaml_content = "roles:\n  norole:\n    name: No Role\n    description: Test\n"
    p = tmp_path / "roles.yaml"
    p.write_text(yaml_content)

    catalog = RoleCatalog()
    catalog.load(p)
    role = catalog.get("norole")
    assert role.allowed_tools is None


def test_catalog_empty_allowed_tools_is_empty_list(tmp_path):
    """When allowed_tools key is present but empty, it becomes []."""
    yaml_content = (
        "roles:\n  norole:\n    name: No Role\n"
        "    description: Test\n    allowed_tools: []\n"
    )
    p = tmp_path / "roles.yaml"
    p.write_text(yaml_content)

    catalog = RoleCatalog()
    catalog.load(p)
    role = catalog.get("norole")
    assert role.allowed_tools == []


def test_catalog_explicit_allowed_tools(tmp_path):
    """When allowed_tools has items, they are preserved."""
    yaml_content = (
        "roles:\n  norole:\n    name: No Role\n    description: Test\n"
        "    allowed_tools:\n      - Read\n      - Bash\n"
    )
    p = tmp_path / "roles.yaml"
    p.write_text(yaml_content)

    catalog = RoleCatalog()
    catalog.load(p)
    role = catalog.get("norole")
    assert role.allowed_tools == ["Read", "Bash"]


# ---------------------------------------------------------------------------
# RoleExecutor._prepare_tools
# ---------------------------------------------------------------------------


@pytest.fixture
def tool_executor(tmp_path):
    """ToolExecutor with filesystem tools."""
    executor = ToolExecutor()
    router = FilesystemToolRouter(cwd=tmp_path)
    executor.set_filesystem_router(router)
    return executor


@pytest.fixture
def mock_provider():
    provider = AsyncMock()
    provider.name = "anthropic-api"
    provider.run_session = AsyncMock(return_value=SessionResult(
        output={"text": "done"},
        raw_text="done",
    ))
    return provider


@pytest.fixture
def agents(mock_provider):
    registry = AgentRegistry()
    registry.register(mock_provider, default=True)
    return registry


def test_prepare_tools_none_returns_none(tool_executor):
    """allowed_tools=None → returns None (unrestricted)."""
    role = RoleDefinition(id="t", name="T", allowed_tools=None)
    executor = RoleExecutor(
        roles=RoleCatalog(), agents=AgentRegistry(),
        skills=SkillRegistry(), tool_executor=tool_executor,
    )
    result = executor._prepare_tools(role)
    assert result is None


def test_prepare_tools_empty_returns_empty(tool_executor):
    """allowed_tools=[] → returns [] (deny all)."""
    role = RoleDefinition(id="t", name="T", allowed_tools=[])
    executor = RoleExecutor(
        roles=RoleCatalog(), agents=AgentRegistry(),
        skills=SkillRegistry(), tool_executor=tool_executor,
    )
    result = executor._prepare_tools(role)
    assert result == []


def test_prepare_tools_specific_filters(tool_executor):
    """allowed_tools=['Read', 'Bash'] → returns only matching tools."""
    role = RoleDefinition(id="t", name="T", allowed_tools=["Read", "Bash"])
    executor = RoleExecutor(
        roles=RoleCatalog(), agents=AgentRegistry(),
        skills=SkillRegistry(), tool_executor=tool_executor,
    )
    result = executor._prepare_tools(role)
    names = {t.name for t in result}
    assert names == {"Read", "Bash"}


async def test_executor_passes_empty_tools_to_provider(tool_executor, mock_provider, agents):
    """When allowed_tools=[], provider receives [] (not None)."""
    catalog = RoleCatalog()
    yaml = "roles:\n  locked:\n    name: Locked\n    description: No tools\n    allowed_tools: []\n"
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml)
        f.flush()
        catalog.load(Path(f.name))

    executor = RoleExecutor(
        roles=catalog, agents=agents,
        skills=SkillRegistry(), tool_executor=tool_executor,
    )
    await executor.execute("locked", "do nothing")

    call_kwargs = mock_provider.run_session.call_args[1]
    assert call_kwargs["tools"] == []


async def test_executor_passes_none_tools_for_unrestricted(tool_executor, mock_provider, agents):
    """When allowed_tools=None, provider receives None (unrestricted)."""
    catalog = RoleCatalog()
    yaml = "roles:\n  free:\n    name: Free\n    description: All tools\n"
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml)
        f.flush()
        catalog.load(Path(f.name))

    executor = RoleExecutor(
        roles=catalog, agents=agents,
        skills=SkillRegistry(), tool_executor=tool_executor,
    )
    await executor.execute("free", "do anything")

    call_kwargs = mock_provider.run_session.call_args[1]
    assert call_kwargs["tools"] is None


# ---------------------------------------------------------------------------
# Claude SDK: --allowedTools flag
# ---------------------------------------------------------------------------


async def test_claude_sdk_empty_tools_sends_empty_flag():
    """Claude SDK sends --allowedTools '' when tools is []."""
    from openhydra.agents.providers.claude_sdk import ClaudeSdkProvider

    provider = ClaudeSdkProvider()
    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(return_value=(b'{"result": "ok"}', b""))
    mock_proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
        await provider.run_session(
            instructions="Test", system_prompt="System", tools=[],
        )

    cmd = mock_exec.call_args[0]
    assert "--allowedTools" in cmd
    idx = cmd.index("--allowedTools")
    assert cmd[idx + 1] == ""


async def test_claude_sdk_none_tools_no_flag():
    """Claude SDK does NOT send --allowedTools when tools is None."""
    from openhydra.agents.providers.claude_sdk import ClaudeSdkProvider

    provider = ClaudeSdkProvider()
    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(return_value=(b'{"result": "ok"}', b""))
    mock_proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
        await provider.run_session(
            instructions="Test", system_prompt="System", tools=None,
        )

    cmd = mock_exec.call_args[0]
    assert "--allowedTools" not in cmd


# ---------------------------------------------------------------------------
# Agent SDK: allowed_tools
# ---------------------------------------------------------------------------


@dataclass
class _TextBlock:
    text: str
    type: str = "text"


@dataclass
class _ResultMessage:
    result: str = ""
    is_error: bool = False
    total_cost_usd: float = 0.0
    usage: dict | None = None
    type: str = "result"


@dataclass
class _ClaudeAgentOptions:
    system_prompt: str = ""
    model: str = ""
    max_turns: int = 30
    permission_mode: str = "bypassPermissions"
    allowed_tools: list[str] | None = None
    mcp_servers: dict | None = None
    cwd: str | None = None


@dataclass
class _AssistantMessage:
    content: list = field(default_factory=list)
    type: str = "assistant"


_mock_msgs: list = []


async def _mock_query(prompt, options=None):
    for msg in _mock_msgs:
        yield msg


@pytest.fixture
def _agent_sdk_module():
    """Install mock SDK."""
    mod = types.ModuleType("claude_agent_sdk")
    mod.TextBlock = _TextBlock
    mod.AssistantMessage = _AssistantMessage
    mod.ResultMessage = _ResultMessage
    mod.ClaudeAgentOptions = _ClaudeAgentOptions
    mod.query = _mock_query
    sys.modules["claude_agent_sdk"] = mod
    yield mod
    sys.modules.pop("claude_agent_sdk", None)


async def test_agent_sdk_empty_tools_sets_empty_list(_agent_sdk_module):
    """Agent SDK sets allowed_tools=[] when tools is []."""
    global _mock_msgs
    _mock_msgs = [_ResultMessage(result="ok")]

    captured = []
    orig = _agent_sdk_module.query

    async def _capture(prompt, options=None):
        captured.append(options)
        async for msg in orig(prompt, options):
            yield msg

    _agent_sdk_module.query = _capture

    from openhydra.agents.providers.agent_sdk import AgentSdkProvider
    p = AgentSdkProvider()
    await p.run_session(instructions="test", system_prompt="s", tools=[])

    assert len(captured) == 1
    assert captured[0].allowed_tools == []


async def test_agent_sdk_none_tools_no_restriction(_agent_sdk_module):
    """Agent SDK does not set allowed_tools when tools is None."""
    global _mock_msgs
    _mock_msgs = [_ResultMessage(result="ok")]

    captured = []
    orig = _agent_sdk_module.query

    async def _capture(prompt, options=None):
        captured.append(options)
        async for msg in orig(prompt, options):
            yield msg

    _agent_sdk_module.query = _capture

    from openhydra.agents.providers.agent_sdk import AgentSdkProvider
    p = AgentSdkProvider()
    await p.run_session(instructions="test", system_prompt="s", tools=None)

    assert len(captured) == 1
    assert captured[0].allowed_tools is None


# ---------------------------------------------------------------------------
# Anthropic API: tool call validation
# ---------------------------------------------------------------------------


async def test_anthropic_api_rejects_disallowed_tool():
    """Anthropic API rejects tool calls not in the allowed set."""
    from openhydra.agents.providers.anthropic_api import AnthropicApiProvider

    @dataclass
    class _Usage:
        input_tokens: int = 10
        output_tokens: int = 5

    @dataclass
    class _ToolUseBlock:
        type: str = "tool_use"
        id: str = "t1"
        name: str = "Bash"
        input: dict = field(default_factory=dict)

    @dataclass
    class _TextBlock:
        type: str = "text"
        text: str = "ok"

    @dataclass
    class _Response:
        content: list = field(default_factory=list)
        usage: _Usage = field(default_factory=_Usage)

    client = AsyncMock()
    # First call returns tool use for "Bash", second call returns text
    tool_resp = _Response(content=[_ToolUseBlock()])
    final_resp = _Response(content=[_TextBlock(text="Done")])
    client.messages.create = AsyncMock(side_effect=[tool_resp, final_resp])

    executor = AsyncMock(return_value="file content")

    with patch("openhydra.agents.providers.anthropic_api.anthropic") as mock_mod:
        mock_mod.AsyncAnthropic.return_value = client
        provider = AnthropicApiProvider(api_key="test", tool_executor=executor)

    # Only allow "Read", not "Bash"
    tools = [ToolDefinition(name="Read", description="Read files")]
    await provider.run_session(
        instructions="test", system_prompt="s", tools=tools,
    )

    # Executor should NOT have been called (Bash is not allowed)
    executor.assert_not_called()


# ---------------------------------------------------------------------------
# Codex CLI: warning log
# ---------------------------------------------------------------------------


async def test_codex_cli_warns_about_tool_restrictions():
    """Codex CLI logs warning when tool restrictions are provided."""
    from openhydra.agents.providers.codex_cli import CodexCliProvider

    provider = CodexCliProvider()
    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(return_value=(b'{"text": "ok"}', b""))
    mock_proc.returncode = 0

    tools = [ToolDefinition(name="Read", description="Read")]

    with (
        patch("asyncio.create_subprocess_exec", return_value=mock_proc),
        patch("openhydra.agents.providers.codex_cli.logger") as mock_logger,
    ):
        await provider.run_session(
            instructions="test", system_prompt="s", tools=tools,
        )

    mock_logger.warning.assert_called_once()
    assert "does not support tool restrictions" in mock_logger.warning.call_args[0][0]
