"""Filesystem built-in tools — Read, Write, Edit, Bash, Glob, Grep.

Used by the Anthropic API provider to execute tools locally when
Claude SDK / Codex CLI are not the active provider. These mirror
the tools available in Claude Code's built-in toolset.
"""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path
from typing import Any

from ..agents.base import ToolDefinition

# Maximum output size to prevent OOM on huge files/commands
MAX_OUTPUT_CHARS = 30_000

# Environment variables stripped from child processes to prevent secret leaks
_SENSITIVE_ENV_KEYS = {
    "CLAUDECODE",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "OPENHYDRA_WEB_API_KEY",
    "OPENHYDRA_SLACK_BOT_TOKEN",
    "OPENHYDRA_SLACK_APP_TOKEN",
    "OPENHYDRA_DISCORD_BOT_TOKEN",
    "OPENHYDRA_WHATSAPP_ACCESS_TOKEN",
    "TAVILY_API_KEY",
    "PERPLEXITY_API_KEY",
}

# Shell patterns that are destructive or dangerous
_DANGEROUS_PATTERNS = [
    re.compile(r"\brm\s+-rf\s+/"),
    re.compile(r"\bmkfs\b"),
    re.compile(r"\bdd\s+.*of=/dev/"),
    re.compile(r"\bcurl\b.*\|\s*sh\b"),
    re.compile(r"\bwget\b.*\|\s*sh\b"),
]


def get_filesystem_tool_definitions() -> list[ToolDefinition]:
    """Return ToolDefinition list for filesystem tools."""
    return [
        ToolDefinition(
            name="Read",
            description="Read a file from the filesystem.",
            input_schema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Absolute path to the file.",
                    },
                    "offset": {
                        "type": "integer",
                        "description": "Line number to start from.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Number of lines to read.",
                    },
                },
                "required": ["file_path"],
            },
            source="builtin",
        ),
        ToolDefinition(
            name="Write",
            description="Write content to a file (creates or overwrites).",
            input_schema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Absolute path to the file.",
                    },
                    "content": {
                        "type": "string",
                        "description": "Content to write.",
                    },
                },
                "required": ["file_path", "content"],
            },
            source="builtin",
        ),
        ToolDefinition(
            name="Edit",
            description=(
                "Edit a file by replacing old_string with new_string."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Absolute path to the file.",
                    },
                    "old_string": {
                        "type": "string",
                        "description": "Text to find and replace.",
                    },
                    "new_string": {
                        "type": "string",
                        "description": "Replacement text.",
                    },
                },
                "required": ["file_path", "old_string", "new_string"],
            },
            source="builtin",
        ),
        ToolDefinition(
            name="Bash",
            description="Run a shell command and return output.",
            input_schema={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The shell command to run.",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Timeout in seconds (default 120).",
                    },
                },
                "required": ["command"],
            },
            source="builtin",
        ),
        ToolDefinition(
            name="Glob",
            description="Find files matching a glob pattern.",
            input_schema={
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Glob pattern (e.g. '**/*.py').",
                    },
                    "path": {
                        "type": "string",
                        "description": "Directory to search in.",
                    },
                },
                "required": ["pattern"],
            },
            source="builtin",
        ),
        ToolDefinition(
            name="Grep",
            description="Search file contents with regex.",
            input_schema={
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Regex pattern to search for.",
                    },
                    "path": {
                        "type": "string",
                        "description": "File or directory to search.",
                    },
                    "glob": {
                        "type": "string",
                        "description": "Filter files by glob pattern.",
                    },
                },
                "required": ["pattern"],
            },
            source="builtin",
        ),
    ]


class FilesystemToolRouter:
    """Executes filesystem tools (Read, Write, Edit, Bash, Glob, Grep).

    Constructed with a working directory for safety.
    When ``restrict_to_cwd`` is True, all file operations are confined
    to the working directory tree (path traversal prevention).
    """

    def __init__(
        self,
        cwd: str | Path | None = None,
        restrict_to_cwd: bool = False,
    ) -> None:
        self._cwd = Path(cwd) if cwd else Path.cwd()
        self._restrict_to_cwd = restrict_to_cwd
        self._tool_names = {
            "Read", "Write", "Edit", "Bash", "Glob", "Grep",
        }

    def has_tool(self, name: str) -> bool:
        return name in self._tool_names

    def _validate_path(self, path: Path) -> str | None:
        """Return error string if path escapes cwd, else None."""
        if not self._restrict_to_cwd:
            return None
        try:
            resolved = path.resolve()
            cwd_resolved = self._cwd.resolve()
            if not (resolved == cwd_resolved
                    or str(resolved).startswith(str(cwd_resolved) + os.sep)):
                return (
                    f"Error: path '{path}' is outside the allowed "
                    f"directory '{cwd_resolved}'"
                )
        except (OSError, ValueError) as e:
            return f"Error: invalid path: {e}"
        return None

    @staticmethod
    def _safe_env() -> dict[str, str]:
        """Build child environment with sensitive keys stripped."""
        return {
            k: v for k, v in os.environ.items()
            if k not in _SENSITIVE_ENV_KEYS
        }

    def get_definitions(self) -> list[ToolDefinition]:
        return get_filesystem_tool_definitions()

    async def execute(self, name: str, args: dict[str, Any]) -> str:
        if name == "Read":
            return self._read(args)
        elif name == "Write":
            return self._write(args)
        elif name == "Edit":
            return self._edit(args)
        elif name == "Bash":
            return await self._bash(args)
        elif name == "Glob":
            return self._glob(args)
        elif name == "Grep":
            return await self._grep(args)
        raise KeyError(f"Unknown filesystem tool: {name}")

    def _read(self, args: dict[str, Any]) -> str:
        file_path = args.get("file_path", "")
        offset = args.get("offset", 0)
        limit = args.get("limit", 2000)

        path = Path(file_path)
        if not path.is_absolute():
            path = self._cwd / path

        if err := self._validate_path(path):
            return err

        if not path.exists():
            return f"Error: File not found: {path}"

        try:
            lines = path.read_text().splitlines()
            selected = lines[offset:offset + limit]
            numbered = []
            for i, line in enumerate(selected, start=offset + 1):
                numbered.append(f"{i:>6}\t{line}")
            result = "\n".join(numbered)
            if len(result) > MAX_OUTPUT_CHARS:
                result = result[:MAX_OUTPUT_CHARS] + "\n... (truncated)"
            return result
        except Exception as e:
            return f"Error reading file: {e}"

    def _write(self, args: dict[str, Any]) -> str:
        file_path = args.get("file_path", "")
        content = args.get("content", "")

        path = Path(file_path)
        if not path.is_absolute():
            path = self._cwd / path

        if err := self._validate_path(path):
            return err

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
            return f"Successfully wrote {len(content)} bytes to {path}"
        except Exception as e:
            return f"Error writing file: {e}"

    def _edit(self, args: dict[str, Any]) -> str:
        file_path = args.get("file_path", "")
        old_string = args.get("old_string", "")
        new_string = args.get("new_string", "")

        path = Path(file_path)
        if not path.is_absolute():
            path = self._cwd / path

        if err := self._validate_path(path):
            return err

        if not path.exists():
            return f"Error: File not found: {path}"

        try:
            content = path.read_text()
            count = content.count(old_string)
            if count == 0:
                return "Error: old_string not found in file"
            if count > 1:
                return (
                    f"Error: old_string found {count} times. "
                    "Provide more context to make it unique."
                )
            content = content.replace(old_string, new_string, 1)
            path.write_text(content)
            return f"Successfully edited {path}"
        except Exception as e:
            return f"Error editing file: {e}"

    async def _bash(self, args: dict[str, Any]) -> str:
        command = args.get("command", "")
        timeout = args.get("timeout", 120)

        # Block dangerous commands
        for pattern in _DANGEROUS_PATTERNS:
            if pattern.search(command):
                return f"Error: command blocked by safety filter: {command}"

        try:
            child_env = self._safe_env()
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self._cwd),
                env=child_env,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout,
            )
            output = stdout.decode()
            if stderr:
                output += "\n" + stderr.decode()
            if len(output) > MAX_OUTPUT_CHARS:
                output = output[:MAX_OUTPUT_CHARS] + "\n... (truncated)"
            if proc.returncode != 0:
                output = (
                    f"Exit code: {proc.returncode}\n{output}"
                )
            return output
        except asyncio.TimeoutError:
            return f"Error: Command timed out after {timeout}s"
        except Exception as e:
            return f"Error running command: {e}"

    def _glob(self, args: dict[str, Any]) -> str:
        pattern = args.get("pattern", "")
        path = args.get("path", str(self._cwd))

        search_dir = Path(path)
        if not search_dir.is_absolute():
            search_dir = self._cwd / search_dir

        if err := self._validate_path(search_dir):
            return err

        try:
            matches = sorted(
                search_dir.glob(pattern),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            if not matches:
                return "No files found matching pattern."
            result = "\n".join(str(m) for m in matches[:100])
            return result
        except Exception as e:
            return f"Error in glob: {e}"

    async def _grep(self, args: dict[str, Any]) -> str:
        pattern = args.get("pattern", "")
        path = args.get("path", str(self._cwd))
        file_glob = args.get("glob", "")

        search_path = Path(path)
        if not search_path.is_absolute():
            search_path = self._cwd / search_path

        if err := self._validate_path(search_path):
            return err

        try:
            regex = re.compile(pattern)
        except re.error as e:
            return f"Error: Invalid regex: {e}"

        matches: list[str] = []
        try:
            if search_path.is_file():
                files = [search_path]
            else:
                glob_pattern = file_glob or "**/*"
                files = [
                    f for f in search_path.glob(glob_pattern) if f.is_file()
                ]

            for file in files[:500]:  # cap file count
                try:
                    content = file.read_text(errors="replace")
                    for i, line in enumerate(content.splitlines(), 1):
                        if regex.search(line):
                            matches.append(f"{file}:{i}: {line}")
                            if len(matches) >= 200:
                                break
                except (PermissionError, IsADirectoryError):
                    continue
                if len(matches) >= 200:
                    break

            if not matches:
                return "No matches found."
            return "\n".join(matches)
        except Exception as e:
            return f"Error in grep: {e}"
