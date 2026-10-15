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


# --- dangerous mode -------------------------------------------------------
# The point of these: confinement is off, but relative paths must still anchor
# to root so ordinary in-root usage is byte-identical to the safe mode.


def test_dangerous_allows_parent_escape(dangerous_cfg, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside")
    secret = outside / "secret.txt"
    secret.write_text("secret")
    assert resolve(str(secret), dangerous_cfg) == secret.resolve()


def test_dangerous_allows_absolute_outside(dangerous_cfg):
    assert resolve("/etc/passwd", dangerous_cfg) == Path("/etc/passwd")


def test_dangerous_allows_symlink_outside_root(dangerous_cfg, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside")
    secret = outside / "secret.txt"
    secret.write_text("secret")
    link = dangerous_cfg.root / "outside_link"
    link.symlink_to(secret)
    assert resolve("outside_link", dangerous_cfg) == secret.resolve()


def test_dangerous_still_anchors_relative_paths_to_root(dangerous_cfg):
    assert resolve("a/b/c.txt", dangerous_cfg) == dangerous_cfg.root / "a" / "b" / "c.txt"


def test_dangerous_defaults_off():
    from basic_fns_mcp.config import ServerConfig

    assert ServerConfig(root=Path.cwd()).dangerous is False
