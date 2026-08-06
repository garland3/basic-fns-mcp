from __future__ import annotations

import argparse
import os
from pathlib import Path

from .config import ServerConfig, set_config
from .server import mcp, register_tools


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_path(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    return Path(value).expanduser().resolve() if value else default


def main() -> None:
    defaults = {
        "root": _env_path("BASIC_FNS_ROOT", Path.cwd().resolve()),
        "host": os.environ.get("BASIC_FNS_HOST", "127.0.0.1"),
        "port": _env_int("BASIC_FNS_PORT", 8080),
        "max_read_bytes": _env_int("BASIC_FNS_MAX_READ_BYTES", 2_000_000),
        "max_output_chars": _env_int("BASIC_FNS_MAX_OUTPUT", 100_000),
        "bash_timeout": _env_int("BASIC_FNS_BASH_TIMEOUT", 120),
        "allow_bash": _env_bool("BASIC_FNS_ALLOW_BASH", True),
        "read_only": _env_bool("BASIC_FNS_READ_ONLY", False),
    }

    parser = argparse.ArgumentParser(
        prog="basic-fns-mcp",
        description="Streamable-HTTP (or stdio) MCP server for basic filesystem, shell, and search tools.",
    )
    parser.add_argument("--root", type=Path, default=defaults["root"], help="Server root directory")
    parser.add_argument("--host", type=str, default=defaults["host"], help="HTTP bind address")
    parser.add_argument("--port", type=int, default=defaults["port"], help="HTTP bind port")
    parser.add_argument(
        "--max-read-bytes", type=int, default=defaults["max_read_bytes"], help="Maximum file read size"
    )
    parser.add_argument(
        "--max-output-chars", type=int, default=defaults["max_output_chars"], help="Maximum tool output length"
    )
    parser.add_argument("--bash-timeout", type=int, default=defaults["bash_timeout"], help="Default shell timeout")
    parser.add_argument("--read-only", action="store_true", help="Disable write and edit tools")
    parser.add_argument("--no-bash", action="store_true", help="Disable the bash tool")
    parser.add_argument(
        "--transport",
        choices=("http", "stdio"),
        default=os.environ.get("BASIC_FNS_TRANSPORT", "http"),
        help="Transport to use: 'http' (default) or 'stdio' for a locally spawned server",
    )
    parser.add_argument(
        "--stdio",
        action="store_true",
        help="Shorthand for --transport stdio",
    )

    args = parser.parse_args()

    transport = "stdio" if args.stdio else args.transport
    if transport not in ("http", "stdio"):
        parser.error(f"invalid transport {transport!r} (expected 'http' or 'stdio')")

    cfg = ServerConfig(
        root=args.root,
        host=args.host,
        port=args.port,
        max_read_bytes=args.max_read_bytes,
        max_output_chars=args.max_output_chars,
        bash_timeout=args.bash_timeout,
        allow_bash=defaults["allow_bash"] and not args.no_bash,
        read_only=defaults["read_only"] or args.read_only,
    )

    set_config(cfg)
    register_tools(cfg)

    if transport == "http":
        mcp.run(transport="http", host=cfg.host, port=cfg.port)
    else:
        # stdout is the MCP channel on stdio; the banner would corrupt it.
        mcp.run(transport="stdio", show_banner=False)


if __name__ == "__main__":
    main()
