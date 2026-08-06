from __future__ import annotations

from pathlib import Path

from fastmcp.exceptions import ToolError

from .config import ServerConfig


# Directories ignored by the recursive search/listing tools.
DEFAULT_SKIP_DIRS = frozenset(
    {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}
)


def resolve(path: str, cfg: ServerConfig) -> Path:
    """Resolve *path* to an absolute Path that must be inside the server root.

    Symlinks are followed by ``Path.resolve()``.  If the resolved path is not
    ``root`` or a descendant of ``root``, ``ToolError`` is raised.
    """
    expanded = Path(path).expanduser()
    raw = cfg.root / expanded if not expanded.is_absolute() else expanded
    resolved = raw.resolve()
    root = cfg.root.resolve()

    if not resolved.is_relative_to(root):
        raise ToolError(
            f"Path {path!r} resolves outside the server root ({root})."
        )
    return resolved


def truncate(text: str, limit: int) -> str:
    """Return *text* truncated to *limit* characters with an omission note."""
    if limit <= 0:
        return text
    if len(text) <= limit:
        return text
    kept = text[:limit]
    omitted = len(text) - limit
    return f"{kept}\n... [truncated, {omitted} chars omitted]"
