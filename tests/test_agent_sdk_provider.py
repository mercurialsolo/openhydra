"""Tests for AgentSdkProvider — all tests mock the SDK (no real CLI calls)."""

from __future__ import annotations

import sys
import types
from dataclasses import dataclass, field

import pytest

# ---------------------------------------------------------------------------
# Mock SDK types — injected into sys.modules before provider import
# ---------------------------------------------------------------------------


@dataclass
class TextBlock:
    text: str
    type: str = "text"


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


@dataclass
class AssistantMessage:
    content: list = field(default_factory=list)
    type: str = "assistant"


@dataclass
class SystemMessage:
    content: str = ""
    type: str = "system"


@dataclass
class ResultMessage:
    result: str = ""
    is_error: bool = False
    total_cost_usd: float = 0.0
    usage: Usage | None = None
    type: str = "result"


@dataclass
class ClaudeAgentOptions:
    system_prompt: str = ""
    model: str = ""
    max_turns: int = 30
    permission_mode: str = "bypassPermissions"
    allowed_tools: list[str] | None = None
    mcp_servers: dict | None = None
    cwd: str | None = None


# Sentinel — will be replaced per-test
_mock_messages: list = []


async def _mock_query(prompt: str, options: ClaudeAgentOptions | None = None):
    """Async generator yielding pre-set mock messages."""
    for msg in _mock_messages:
        yield msg


def _install_mock_sdk():
    """Install a fake claude_agent_sdk module into sys.modules."""
    mod = types.ModuleType("claude_agent_sdk")
    mod.TextBlock = TextBlock
    mod.Usage = Usage
    mod.AssistantMessage = AssistantMessage
    mod.SystemMessage = SystemMessage
    mod.ResultMessage = ResultMessage
    mod.ClaudeAgentOptions = ClaudeAgentOptions
    mod.query = _mock_query
    sys.modules["claude_agent_sdk"] = mod
    return mod


def _uninstall_mock_sdk():
    sys.modules.pop("claude_agent_sdk", None)


@pytest.fixture(autouse=True)
def _sdk_module():
    """Install mock SDK before each test, remove after."""
    _install_mock_sdk()
    yield
    _uninstall_mock_sdk()


@pytest.fixture
def provider():
    from openhydra.agents.providers.agent_sdk import AgentSdkProvider
    return AgentSdkProvider()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_name(provider):
    assert provider.name == "agent-sdk"


async def test_successful_session(provider):
    global _mock_messages
    _mock_messages = [
        SystemMessage(content="System ready"),
        AssistantMessage(content=[TextBlock(text="Hello from agent")]),
        ResultMessage(
            result="final result",
            is_error=False,
            total_cost_usd=0.02,
            usage=Usage(input_tokens=100, output_tokens=200),
        ),
    ]

    result = await provider.run_session(
        instructions="Do something",
        system_prompt="You are helpful",
    )

    assert result.raw_text == "Hello from agent\nfinal result"
    assert result.cost_usd == 0.02
    assert result.input_tokens == 100
    assert result.output_tokens == 200
    assert result.tokens_used == 300
    assert result.model == "claude-sonnet-4-5-20250929"


async def test_successful_session_dict_usage(provider):
    """Test with dict usage (matches real SDK behavior)."""
    global _mock_messages
    _mock_messages = [
        AssistantMessage(content=[TextBlock(text="Hello")]),
        ResultMessage(
            result="done",
            is_error=False,
            total_cost_usd=0.05,
            usage={
                "input_tokens": 500,
                "output_tokens": 100,
                "cache_read_input_tokens": 1000,
                "cache_creation_input_tokens": 200,
            },
        ),
    ]

    result = await provider.run_session(
        instructions="Do something",
        system_prompt="You are helpful",
    )

    assert result.input_tokens == 500
    assert result.output_tokens == 100
    assert result.tokens_used == 1800  # 500 + 100 + 1000 + 200
    assert result.cost_usd == 0.05


async def test_error_result(provider):
    global _mock_messages
    _mock_messages = [
        ResultMessage(
            result="Permission denied",
            is_error=True,
            total_cost_usd=0.0,
        ),
    ]

    result = await provider.run_session(
        instructions="Fail",
        system_prompt="System",
    )

    assert "error" in result.output
    assert "Permission denied" in result.raw_text


async def test_sdk_exception_handling(provider):
    global _mock_messages

    async def _failing_query(prompt, options=None):
        raise RuntimeError("SDK crashed")
        yield  # noqa: F841 — makes this an async generator

    mock_mod = sys.modules["claude_agent_sdk"]
    mock_mod.query = _failing_query

    result = await provider.run_session(
        instructions="Crash",
        system_prompt="System",
    )

    assert "error" in result.output
    assert "SDK crashed" in result.raw_text


async def test_check_availability(provider):
    assert await provider.check_availability() is True


async def test_check_availability_missing(provider):
    import builtins

    from openhydra.agents.providers.agent_sdk import AgentSdkProvider

    real_import = builtins.__import__

    def _block_sdk(name, *args, **kwargs):
        if name == "claude_agent_sdk":
            raise ImportError("mocked missing")
        return real_import(name, *args, **kwargs)

    builtins.__import__ = _block_sdk
    try:
        p = AgentSdkProvider()
        assert await p.check_availability() is False
    finally:
        builtins.__import__ = real_import


async def test_mcp_config_unwrapped():
    from openhydra.agents.providers.agent_sdk import AgentSdkProvider

    mcp = {"mcpServers": {"chrome": {"command": "npx"}}}
    p = AgentSdkProvider(mcp_config=mcp)

    result = p._build_mcp_servers()
    assert result == {"chrome": {"command": "npx"}}


async def test_mcp_config_already_flat():
    from openhydra.agents.providers.agent_sdk import AgentSdkProvider

    mcp = {"chrome": {"command": "npx"}}
    p = AgentSdkProvider(mcp_config=mcp)

    result = p._build_mcp_servers()
    assert result == {"chrome": {"command": "npx"}}


async def test_allowed_tools_mapping():
    from openhydra.agents.base import ToolDefinition
    from openhydra.agents.providers.agent_sdk import AgentSdkProvider

    global _mock_messages
    captured_options = []

    original_query = sys.modules["claude_agent_sdk"].query

    async def _capture_query(prompt, options=None):
        captured_options.append(options)
        async for msg in original_query(prompt, options):
            yield msg

    sys.modules["claude_agent_sdk"].query = _capture_query

    _mock_messages = [
        ResultMessage(result="done", usage=Usage()),
    ]

    p = AgentSdkProvider()
    tools = [
        ToolDefinition(name="Read", description="Read files"),
        ToolDefinition(name="Bash", description="Run commands"),
    ]
    await p.run_session(
        instructions="test",
        system_prompt="system",
        tools=tools,
    )

    assert len(captured_options) == 1
    assert captured_options[0].allowed_tools == ["Read", "Bash"]


async def test_env_stripping():
    import os

    from openhydra.agents.providers.agent_sdk import _stripped_env

    # Test CLAUDECODE stripped inside context, restored after
    os.environ["CLAUDECODE"] = "true"
    with _stripped_env():
        assert "CLAUDECODE" not in os.environ
    assert os.environ.get("CLAUDECODE") == "true"

    # Test ANTHROPIC_API_KEY stripped when OAuth present
    os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = "token123"
    os.environ["ANTHROPIC_API_KEY"] = "sk-test"
    with _stripped_env():
        assert "ANTHROPIC_API_KEY" not in os.environ
        assert "CLAUDECODE" not in os.environ
    # Both restored after
    assert os.environ.get("ANTHROPIC_API_KEY") == "sk-test"
    assert os.environ.get("CLAUDECODE") == "true"

    # Clean up
    os.environ.pop("CLAUDE_CODE_OAUTH_TOKEN", None)
    os.environ.pop("ANTHROPIC_API_KEY", None)
    os.environ.pop("CLAUDECODE", None)


async def test_env_stripping_keeps_api_key_without_oauth():
    import os

    from openhydra.agents.providers.agent_sdk import _stripped_env

    os.environ.pop("CLAUDE_CODE_OAUTH_TOKEN", None)
    os.environ["ANTHROPIC_API_KEY"] = "sk-test"
    os.environ["CLAUDECODE"] = "true"
    with _stripped_env():
        # API key should remain when no OAuth token
        assert os.environ.get("ANTHROPIC_API_KEY") == "sk-test"
        # But CLAUDECODE should still be stripped
        assert "CLAUDECODE" not in os.environ
    # Both restored
    assert os.environ.get("ANTHROPIC_API_KEY") == "sk-test"
    assert os.environ.get("CLAUDECODE") == "true"

    # Clean up
    os.environ.pop("ANTHROPIC_API_KEY", None)
    os.environ.pop("CLAUDECODE", None)


async def test_no_result_message(provider):
    global _mock_messages
    _mock_messages = [
        AssistantMessage(content=[TextBlock(text="Only assistant text")]),
    ]

    result = await provider.run_session(
        instructions="test",
        system_prompt="system",
    )

    assert result.raw_text == "Only assistant text"
    assert result.output == {"text": "Only assistant text"}


async def test_json_output_parsing(provider):
    global _mock_messages

    # Fenced JSON
    _mock_messages = [
        AssistantMessage(content=[TextBlock(text='```json\n{"plan": "step1"}\n```')]),
        ResultMessage(result="", usage=Usage()),
    ]
    result = await provider.run_session(instructions="test", system_prompt="s")
    assert result.output == {"plan": "step1"}

    # Raw JSON
    _mock_messages = [
        AssistantMessage(content=[TextBlock(text='{"status": "ok"}')]),
        ResultMessage(result="", usage=Usage()),
    ]
    result = await provider.run_session(instructions="test", system_prompt="s")
    assert result.output == {"status": "ok"}

    # Plain text
    _mock_messages = [
        AssistantMessage(content=[TextBlock(text="just text")]),
        ResultMessage(result="", usage=Usage()),
    ]
    result = await provider.run_session(instructions="test", system_prompt="s")
    assert result.output == {"text": "just text"}
