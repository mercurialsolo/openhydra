"""Tests for filesystem built-in tools."""

from __future__ import annotations

import pytest

from openhydra.tools.filesystem import FilesystemToolRouter, get_filesystem_tool_definitions


@pytest.fixture
def tmp_workspace(tmp_path):
    """Create a temp workspace directory."""
    return tmp_path


@pytest.fixture
def router(tmp_workspace):
    """Create a FilesystemToolRouter with temp workspace."""
    return FilesystemToolRouter(cwd=tmp_workspace)


def test_tool_definitions_complete():
    """All 6 filesystem tools are defined."""
    defs = get_filesystem_tool_definitions()
    names = {d.name for d in defs}
    assert names == {"Read", "Write", "Edit", "Bash", "Glob", "Grep"}
    for d in defs:
        assert d.source == "builtin"
        assert d.input_schema is not None


def test_has_tool(router):
    """Router recognizes its tool names."""
    assert router.has_tool("Read")
    assert router.has_tool("Write")
    assert router.has_tool("Edit")
    assert router.has_tool("Bash")
    assert router.has_tool("Glob")
    assert router.has_tool("Grep")
    assert not router.has_tool("Unknown")


async def test_write_and_read(router, tmp_workspace):
    """Write a file then read it back."""
    file_path = str(tmp_workspace / "hello.txt")
    result = await router.execute("Write", {"file_path": file_path, "content": "hello world\n"})
    assert "Successfully wrote" in result

    result = await router.execute("Read", {"file_path": file_path})
    assert "hello world" in result
    assert "1\t" in result  # line number


async def test_read_nonexistent(router):
    """Reading a nonexistent file returns error."""
    result = await router.execute("Read", {"file_path": "/nonexistent/file.txt"})
    assert "Error" in result or "not found" in result


async def test_edit(router, tmp_workspace):
    """Edit replaces text in file."""
    file_path = str(tmp_workspace / "edit_me.txt")
    await router.execute("Write", {"file_path": file_path, "content": "foo bar baz"})

    result = await router.execute("Edit", {
        "file_path": file_path,
        "old_string": "bar",
        "new_string": "qux",
    })
    assert "Successfully edited" in result

    content = (tmp_workspace / "edit_me.txt").read_text()
    assert content == "foo qux baz"


async def test_edit_not_found(router, tmp_workspace):
    """Edit fails when old_string not found."""
    file_path = str(tmp_workspace / "edit_nf.txt")
    await router.execute("Write", {"file_path": file_path, "content": "abc"})

    result = await router.execute("Edit", {
        "file_path": file_path,
        "old_string": "xyz",
        "new_string": "new",
    })
    assert "not found" in result


async def test_edit_ambiguous(router, tmp_workspace):
    """Edit fails when old_string matches multiple times."""
    file_path = str(tmp_workspace / "edit_dup.txt")
    await router.execute("Write", {"file_path": file_path, "content": "aaa bbb aaa"})

    result = await router.execute("Edit", {
        "file_path": file_path,
        "old_string": "aaa",
        "new_string": "ccc",
    })
    assert "2 times" in result


async def test_bash(router):
    """Bash executes a command and returns output."""
    result = await router.execute("Bash", {"command": "echo hello"})
    assert "hello" in result


async def test_bash_failure(router):
    """Bash reports non-zero exit code."""
    result = await router.execute("Bash", {"command": "exit 42"})
    assert "Exit code: 42" in result


async def test_glob(router, tmp_workspace):
    """Glob finds matching files."""
    (tmp_workspace / "a.py").write_text("pass")
    (tmp_workspace / "b.py").write_text("pass")
    (tmp_workspace / "c.txt").write_text("text")

    result = await router.execute("Glob", {"pattern": "*.py"})
    assert "a.py" in result
    assert "b.py" in result
    assert "c.txt" not in result


async def test_glob_no_matches(router, tmp_workspace):
    """Glob returns message when no matches."""
    result = await router.execute("Glob", {"pattern": "*.nonexistent"})
    assert "No files found" in result


async def test_grep(router, tmp_workspace):
    """Grep finds pattern in files."""
    (tmp_workspace / "search.py").write_text("def hello():\n    return 42\n")

    result = await router.execute("Grep", {"pattern": "def hello"})
    assert "search.py" in result
    assert "def hello" in result


async def test_grep_no_matches(router, tmp_workspace):
    """Grep returns message when no matches."""
    (tmp_workspace / "empty_search.py").write_text("nothing here\n")

    result = await router.execute("Grep", {"pattern": "xyz123"})
    assert "No matches" in result


async def test_unknown_tool(router):
    """Router raises KeyError for unknown tools."""
    with pytest.raises(KeyError, match="Unknown filesystem tool"):
        await router.execute("NotATool", {})


async def test_filesystem_tools_in_tool_executor(tmp_workspace):
    """Filesystem tools are listed and executable through ToolExecutor."""
    from openhydra.tools.executor import ToolExecutor

    executor = ToolExecutor()
    router = FilesystemToolRouter(cwd=tmp_workspace)
    executor.set_filesystem_router(router)

    tools = executor.list_all_tools()
    names = [t.name for t in tools]
    assert "Read" in names
    assert "Write" in names
    assert "Bash" in names

    # Execute through ToolExecutor
    file_path = str(tmp_workspace / "via_executor.txt")
    result = await executor.execute("Write", {"file_path": file_path, "content": "test"})
    assert "Successfully wrote" in result

    result = await executor.execute("Read", {"file_path": file_path})
    assert "test" in result
