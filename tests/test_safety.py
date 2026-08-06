from pathlib import Path

import pytest

from basic_fns_mcp.safety import resolve, truncate
from fastmcp.exceptions import ToolError


def test_resolve_accepts_nested_relative(cfg):
    assert resolve("a/b/c.txt", cfg) == cfg.root / "a" / "b" / "c.txt"


def test_resolve_accepts_root(cfg):
    assert resolve(".", cfg) == cfg.root


def test_resolve_rejects_parent_escape(cfg):
    with pytest.raises(ToolError):
        resolve("../escape.txt", cfg)


def test_resolve_rejects_absolute_outside(cfg):
    with pytest.raises(ToolError):
        resolve("/etc/passwd", cfg)


def test_resolve_rejects_symlink_outside_root(cfg, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside")
    secret = outside / "secret.txt"
    secret.write_text("secret")
    link = cfg.root / "outside_link"
    link.symlink_to(secret)
    with pytest.raises(ToolError):
        resolve("outside_link", cfg)


def test_truncate_appends_omission_note():
    text = "1234567890"
    assert truncate(text, 5) == "12345\n... [truncated, 5 chars omitted]"


def test_truncate_keeps_short_text():
    text = "hello"
    assert truncate(text, 100) == "hello"
