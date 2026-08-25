import os
import time

import pytest

from basic_fns_mcp.config import ServerConfig, set_config
from basic_fns_mcp.safety import truncate
from basic_fns_mcp.server import (
    bash,
    edit,
    find,
    grep,
    ls,
    mcp,
    mkdir,
    read,
    register_tools,
    write,
)
from fastmcp.exceptions import ToolError


# ---------------------------------------------------------------------------
# read

def test_read_line_numbering_and_offset_limit(cfg):
    f = cfg.root / "numbers.txt"
    f.write_text("alpha\nbeta\ngamma\ndelta\n", encoding="utf-8")

    out = read("numbers.txt", offset=0, limit=2)
    assert "1\talpha" in out
    assert "2\tbeta" in out
    assert "gamma" not in out

    out = read("numbers.txt", offset=2, limit=2)
    assert "3\tgamma" in out
    assert "4\tdelta" in out


def test_read_rejects_binary(cfg):
    f = cfg.root / "binary.bin"
    f.write_bytes(b"\x00\x01\x02")
    with pytest.raises(ToolError, match="binary file"):
        read("binary.bin")


def test_read_rejects_oversize_file(cfg):
    tiny = ServerConfig(
        root=cfg.root,
        max_read_bytes=5,
        read_only=True,
    )
    set_config(tiny)
    f = cfg.root / "big.txt"
    f.write_text("much too large")
    with pytest.raises(ToolError, match="exceeding"):
        read("big.txt")


# ---------------------------------------------------------------------------
# write

def test_write_creates_parents_and_overwrites_atomically(cfg):
    result = write("new file", "hello")
    assert "created" in result
    assert "5 bytes" in result
    assert (cfg.root / "new file").read_text() == "hello"

    result = write("new file", "world")
    assert "replaced" in result

    # Atomic temp leftovers should be gone.
    leftovers = [p for p in cfg.root.rglob("*.tmp")]
    assert not leftovers


# ---------------------------------------------------------------------------
# mkdir

def test_mkdir_creates_directory_and_parents(cfg):
    result = mkdir("parent/child")
    assert result == "parent/child/: created"
    assert (cfg.root / "parent" / "child").is_dir()


def test_mkdir_rejects_existing_path(cfg):
    (cfg.root / "existing").mkdir()
    with pytest.raises(ToolError, match="Directory already exists"):
        mkdir("existing")

    (cfg.root / "file").write_text("content")
    with pytest.raises(ToolError, match="not a directory"):
        mkdir("file")


def test_mkdir_rejects_path_outside_root(cfg):
    with pytest.raises(ToolError, match="outside the server root"):
        mkdir("../outside")


def test_mkdir_registration_respects_read_only(cfg, monkeypatch):
    registered = []
    monkeypatch.setattr(
        mcp,
        "tool",
        lambda fn, annotations: registered.append((fn.__name__, annotations)),
    )
    monkeypatch.setattr(mcp.local_provider, "remove_tool", lambda name: None)

    register_tools(cfg)
    assert ("mkdir", {"destructiveHint": True}) in registered

    registered.clear()
    register_tools(ServerConfig(root=cfg.root, read_only=True, allow_bash=False))
    assert all(name != "mkdir" for name, _ in registered)


# ---------------------------------------------------------------------------
# edit

def test_edit_errors_when_old_not_found(cfg):
    (cfg.root / "edit_me.txt").write_text("hello world")
    with pytest.raises(ToolError, match="not found"):
        edit("edit_me.txt", old_string="missing", new_string="replacement")


def test_edit_errors_with_multiple_matches_without_replace_all(cfg):
    (cfg.root / "edit_me.txt").write_text("foo foo foo")
    with pytest.raises(ToolError, match="3 occurrences"):
        edit("edit_me.txt", old_string="foo", new_string="bar")


def test_edit_succeeds_with_replace_all(cfg):
    (cfg.root / "edit_me.txt").write_text("foo foo foo")
    out = edit("edit_me.txt", old_string="foo", new_string="bar", replace_all=True)
    assert "3 occurrence(s)" in out
    assert (cfg.root / "edit_me.txt").read_text() == "bar bar bar"


def test_edit_preserves_crlf_line_endings(cfg):
    f = cfg.root / "crlf.txt"
    f.write_bytes(b"one\r\ntwo\r\nthree\r\n")
    edit("crlf.txt", old_string="two", new_string="TWO")
    assert f.read_bytes() == b"one\r\nTWO\r\nthree\r\n"


def test_edit_rejects_non_utf8_file(cfg):
    f = cfg.root / "latin.txt"
    f.write_bytes(b"caf\xe9 and more")
    with pytest.raises(ToolError, match="not valid UTF-8"):
        edit("latin.txt", old_string="and", new_string="AND")


def test_write_does_not_translate_newlines(cfg):
    write("crlf_out.txt", "a\r\nb\r\n")
    assert (cfg.root / "crlf_out.txt").read_bytes() == b"a\r\nb\r\n"


def test_edit_errors_when_no_change_requested(cfg):
    with pytest.raises(ToolError, match="identical"):
        edit("edit_me.txt", old_string="x", new_string="x")


# ---------------------------------------------------------------------------
# bash

def test_bash_returns_nonzero_exit_code(cfg):
    out = bash("echo stdout_text; echo stderr_text >&2; exit 7")
    assert "exit code: 7" in out
    assert "stdout_text" in out
    assert "stderr_text" in out


def test_bash_timeout_path(cfg):
    short = ServerConfig(root=cfg.root, bash_timeout=1)
    set_config(short)
    start = time.monotonic()
    out = bash("sleep 10")
    elapsed = time.monotonic() - start
    assert elapsed < 5
    assert "timed out after 1 seconds" in out


# ---------------------------------------------------------------------------
# grep / find / ls

def _make_search_tree(cfg):
    # Should be skipped.
    (cfg.root / ".git").mkdir()
    (cfg.root / ".git" / "skip.txt").write_text("match in git")
    (cfg.root / "node_modules" / "pkg").mkdir(parents=True)
    (cfg.root / "node_modules" / "pkg" / "skip.txt").write_text("match in node_modules")

    # Should be found.
    (cfg.root / "src").mkdir()
    (cfg.root / "src" / "found.py").write_text("def alpha():\n    pass\n")
    (cfg.root / "src" / "beta.txt").write_text("beta value\n")


def test_grep_honors_skip_list(cfg):
    _make_search_tree(cfg)
    out = grep("match")
    assert "skip.txt" not in out
    assert "found.py" not in out
    out = grep("alpha")
    assert "src/found.py" in out


def test_grep_caps_results(cfg):
    _make_search_tree(cfg)
    out = grep("alpha|beta", max_results=1)
    result_lines = [ln for ln in out.splitlines() if not ln.startswith("... [")]
    assert len(result_lines) == 1
    assert "additional matches hidden" in out


def test_grep_ignores_gitignore(cfg):
    """Results must not depend on whether ripgrep is installed."""
    (cfg.root / ".gitignore").write_text("secret.txt\n")
    (cfg.root / "secret.txt").write_text("needle here\n")
    (cfg.root / "plain.txt").write_text("needle here\n")

    out = grep("needle")
    assert "secret.txt" in out
    assert "plain.txt" in out


def test_grep_pattern_starting_with_dash(cfg):
    (cfg.root / "dash.txt").write_text("value --flagged here\n")
    out = grep("--flagged")
    assert "dash.txt" in out


def test_find_matches_file_named_like_a_skip_dir(cfg):
    (cfg.root / "build").write_text("this is a file, not a directory")
    out = find("build")
    assert "build" in out


def test_find_honors_skip_list(cfg):
    _make_search_tree(cfg)
    out = find("*.txt")
    assert "skip.txt" not in out
    assert "beta.txt" in out


def test_find_type_filter(cfg):
    _make_search_tree(cfg)
    out = find(pattern="*", path=".", type="dir")
    assert "src/" in out
    assert "beta.txt" not in out

    out = find(pattern="*", path=".", type="file")
    assert "beta.txt" in out
    assert "\nsrc/\n" not in out  # no directory entries in file-only output


def test_find_caps_results(cfg):
    for i in range(5):
        (cfg.root / f"file{i}.txt").write_text(str(i))
    out = find("*.txt", max_results=3)
    assert "additional entries hidden" in out
    assert out.count("\n") == 3  # 3 result lines + cap line


def test_ls_lists_and_respects_hidden_flag(cfg):
    (cfg.root / "visible.txt").write_text("x")
    (cfg.root / ".hidden").write_text("y")
    (cfg.root / "adir").mkdir()

    out = ls(".", all=False)
    assert "visible.txt" in out
    assert ".hidden" not in out
    assert "adir/" in out
    # Directories should appear before files in the output.
    assert out.index("adir/") < out.index("visible.txt")

    out_all = ls(".", all=True)
    assert ".hidden" in out_all


def test_ls_errors_for_file_path(cfg):
    (cfg.root / "not_a_dir.txt").write_text("x")
    with pytest.raises(ToolError, match="Not a directory"):
        ls("not_a_dir.txt")
