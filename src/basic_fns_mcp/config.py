from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ServerConfig:
    """Runtime configuration for the basic-fns-mcp server."""

    root: Path
    host: str = "127.0.0.1"
    port: int = 8080
    max_read_bytes: int = 2_000_000
    max_output_chars: int = 100_000
    bash_timeout: int = 120
    allow_bash: bool = True
    read_only: bool = False

    def __post_init__(self):
        # Ensure the root is fully resolved the first time the object is built.
        object.__setattr__(self, "root", self.root.resolve())


_current_config: ServerConfig | None = None


def get_config() -> ServerConfig:
    """Return the current server configuration, building a default one if needed."""
    global _current_config
    if _current_config is None:
        _current_config = ServerConfig(root=Path.cwd().resolve())
    return _current_config


def set_config(cfg: ServerConfig | None) -> None:
    """Set (or clear) the active server configuration."""
    global _current_config
    _current_config = cfg
