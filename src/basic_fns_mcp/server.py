from __future__ import annotations

import fnmatch
import os
import re
import shutil
import subprocess
import uuid
from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import Field

from .config import ServerConfig, get_config
from .safety import DEFAULT_SKIP_DIRS, resolve, truncate


mcp = FastMCP(
    "basic-fns-mcp",
    instructions=(
        "All filesystem paths are relative to the server root. "
        "Use read/edit/write for file changes; ls/find/grep for discovery. "
        "edit requires an old_string that uniquely identifies the target "
        "unless replace_all is true."
    ),
)

_RG_AVAILABLE = shutil.which("rg") is not None


def _relp(target: Path, cfg: ServerConfig) -> str:
    """Return a POSIX-style path string relative to the server root."""
    return target.relative_to(cfg.root).as_posix()


def _result(text: str, cfg: ServerConfig | None = None) -> str:
    """Apply the configured output-character cap to tool output."""
    if cfg is None:
        cfg = get_config()
    return truncate(text, cfg.max_output_chars)


def _human_size(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024.0:
            return f"{size:.1f}{unit}"
        size /= 1024.0
    return f"{size:.1f}TB"


def _fmt_time(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def _as_text(value: str | bytes | None) -> str:
    """Coerce subprocess output to text (it can still be bytes on timeout)."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _cap_lines(lines: list[str], max_results: int, cap_message: str) -> str:
    out = "\n".join(lines[:max_results])
    if len(lines) > max_results:
        out += f"\n... [{len(lines) - max_results} {cap_message}]"
    return out


def read(
    path: Annotated[str, Field(description="File path relative to the server root")],
    offset: Annotated[int, Field(description="0-indexed starting line number")] = 0,
    limit: Annotated[int, Field(description="Maximum number of lines to return")] = 2000,
) -> str:
    """Read a text file and return its contents with cat-style line numbers."""
    cfg = get_config()
    target = resolve(path, cfg)

    if not target.is_file():
        raise ToolError(f"Not a file: {path!r}")

    size = target.stat().st_size
    if size > cfg.max_read_bytes:
        raise ToolError(
            f"File {path!r} is {size} bytes, exceeding the {cfg.max_read_bytes} byte limit."
        )

    # First chunk is checked for binary content.
    with open(target, "rb") as fh:
        if b"\x00" in fh.read(8192):
            raise ToolError("binary file")

    with open(target, "r", encoding="utf-8", errors="replace") as fh:
        lines = fh.read().splitlines()

    if offset < 0:
        offset = 0
    if limit < 0:
        limit = 0

    selected = lines[offset : offset + limit]
    last_lineno = offset + len(selected)
    width = max(1, len(str(last_lineno)))

    numbered = "\n".join(
        f"{(offset + i + 1):>{width}}\t{line}" for i, line in enumerate(selected)
    )
    return _result(numbered, cfg)


def write(
    path: Annotated[str, Field(description="File path relative to the server root")],
    content: Annotated[str, Field(description="Text content to write")],
) -> str:
    """Create or overwrite a file atomically (temp file + os.replace)."""
    cfg = get_config()
    target = resolve(path, cfg)

    if target.is_dir():
        raise ToolError(f"Cannot write to a directory: {path!r}")

    existed = target.exists()
    target.parent.mkdir(parents=True, exist_ok=True)

    tmp = target.parent / f".{target.name}.{uuid.uuid4().hex}.tmp"
    try:
        # newline="" writes content byte-for-byte, without translating "\n".
        with open(tmp, "w", encoding="utf-8", newline="") as fh:
            fh.write(content)
        os.replace(tmp, target)
    except Exception as exc:  # pragma: no cover - defensive
        if tmp.exists():
            tmp.unlink()
        raise ToolError(f"Failed to write {path!r}: {exc}") from exc

    rel = _relp(target, cfg)
    action = "replaced" if existed else "created"
    byte_count = len(content.encode("utf-8"))
    return _result(f"{rel}: {action}, {byte_count} bytes", cfg)


def edit(
    path: Annotated[str, Field(description="File path relative to the server root")],
    old_string: Annotated[str, Field(description="Text to replace")],
    new_string: Annotated[str, Field(description="Replacement text")],
    replace_all: Annotated[bool, Field(description="Replace every occurrence")] = False,
) -> str:
    """Replace *old_string* with *new_string* in a text file."""
    cfg = get_config()

    if old_string == new_string:
        raise ToolError("old_string and new_string are identical; no change requested.")

    target = resolve(path, cfg)
    if not target.is_file():
        raise ToolError(f"Not a file: {path!r}")

    # newline="" keeps CRLF (and lone CR) endings intact through the round trip.
    try:
        with open(target, "r", encoding="utf-8", newline="") as fh:
            original = fh.read()
    except UnicodeDecodeError as exc:
        raise ToolError(f"Cannot edit {path!r}: not valid UTF-8 text ({exc}).") from exc

    count = original.count(old_string)

    if count == 0:
        raise ToolError(f"old_string not found in {path!r}")
    if count > 1 and not replace_all:
        raise ToolError(
            f"Found {count} occurrences of old_string in {path!r}; "
            "add more surrounding context or set replace_all=True."
        )

    if replace_all:
        result = original.replace(old_string, new_string)
    else:
        idx = original.find(old_string)
        result = original[:idx] + new_string + original[idx + len(old_string) :]

    with open(target, "w", encoding="utf-8", newline="") as fh:
        fh.write(result)

    def snippet(text: str, center: int, width: int = 160) -> str:
        start = max(0, center - width // 2)
        end = min(len(text), center + width // 2)
        return text[start:end]

    idx_orig = original.find(old_string) + len(old_string) // 2
    idx_res = result.find(new_string, idx_orig - len(new_string)) + len(new_string) // 2
    before = snippet(original, idx_orig)
    after = snippet(result, idx_res)

    rel = _relp(target, cfg)
    summary = (
        f"Replaced {count} occurrence(s) in {rel}\n"
        f"--- before ---\n{before}\n"
        f"--- after ---\n{after}"
    )
    return _result(summary, cfg)


def bash(
    command: Annotated[str, Field(description="Shell command to run")],
    timeout: Annotated[int | None, Field(description="Timeout override in seconds")] = None,
    cwd: Annotated[str | None, Field(description="Working directory relative to server root")] = None,
) -> str:
    """Execute a shell command and return exit code, stdout, and stderr."""
    cfg = get_config()
    workdir = resolve(cwd, cfg) if cwd else cfg.root
    if timeout is None:
        timeout = cfg.bash_timeout

    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=str(workdir),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        stdout = proc.stdout
        stderr = proc.stderr
        exit_code = proc.returncode
    except subprocess.TimeoutExpired as exc:
        # On timeout the partial output may still be bytes despite text=True.
        stdout = _as_text(exc.stdout)
        stderr = _as_text(exc.stderr)
        return _result(
            f"Command timed out after {timeout} seconds.\n"
            f"stdout:\n{truncate(stdout, cfg.max_output_chars)}\n"
            f"stderr:\n{truncate(stderr, cfg.max_output_chars)}",
            cfg,
        )

    stdout_block = truncate(stdout, cfg.max_output_chars) if stdout else ""
    stderr_block = truncate(stderr, cfg.max_output_chars) if stderr else ""

    parts = [f"exit code: {exit_code}"]
    if stdout_block:
        parts.append(f"stdout:\n{stdout_block}")
    if stderr_block:
        parts.append(f"stderr:\n{stderr_block}")
    return _result("\n".join(parts), cfg)


def _grep_rg(
    cfg: ServerConfig,
    start: Path,
    pattern: str,
    glob: str | None,
    case_insensitive: bool,
    max_results: int,
) -> str:
    # --no-ignore keeps rg from consulting .gitignore/.ignore, so results match
    # the pure-Python fallback instead of varying with the host's VCS state.
    cmd = ["rg", "--no-heading", "--line-number", "--no-ignore"]
    for skip in DEFAULT_SKIP_DIRS:
        cmd.extend(["-g", f"!{skip}/**"])
    if case_insensitive:
        cmd.append("-i")
    if glob:
        cmd.extend(["-g", glob])
    # "--" stops a pattern that begins with "-" from being read as a flag.
    cmd.extend(["--", pattern])
    cmd.append(_relp(start, cfg) if start != cfg.root else ".")

    proc = subprocess.run(
        cmd,
        cwd=str(cfg.root),
        capture_output=True,
        text=True,
        timeout=cfg.bash_timeout or 120,
    )
    lines = [line[2:] if line.startswith("./") else line for line in proc.stdout.splitlines()]
    return _cap_lines(lines, max_results, "additional matches hidden")


def _grep_python(
    cfg: ServerConfig,
    start: Path,
    pattern: str,
    glob: str | None,
    case_insensitive: bool,
    max_results: int,
) -> str:
    flags = re.IGNORECASE if case_insensitive else 0
    try:
        rx = re.compile(pattern, flags)
    except re.error as exc:
        raise ToolError(f"Invalid regex pattern: {exc}") from exc

    matches: list[str] = []
    for dirpath, dirnames, filenames in os.walk(start):
        dirnames[:] = [d for d in dirnames if d not in DEFAULT_SKIP_DIRS]

        for filename in filenames:
            if glob and not fnmatch.fnmatch(filename, glob):
                continue
            filepath = Path(dirpath, filename)

            # Skip binary files.
            try:
                with open(filepath, "rb") as fh:
                    sample = fh.read(1024)
                if b"\x00" in sample:
                    continue
            except OSError:
                continue

            try:
                with open(filepath, "r", encoding="utf-8", errors="replace") as fh:
                    for lineno, line in enumerate(fh, start=1):
                        if rx.search(line):
                            rel = _relp(filepath, cfg)
                            matches.append(f"{rel}:{lineno}:{line.rstrip(chr(10))}")
            except OSError:
                pass

    return _cap_lines(matches, max_results, "additional matches hidden")


def grep(
    pattern: Annotated[str, Field(description="Regular expression pattern")],
    path: Annotated[str, Field(description="Directory under the server root to search")] = ".",
    glob: Annotated[str | None, Field(description="Glob filter, e.g. '*.py'")] = None,
    case_insensitive: Annotated[bool, Field(description="Case-insensitive search")] = False,
    max_results: Annotated[int, Field(description="Maximum results to return")] = 200,
) -> str:
    """Search file contents by regex."""
    cfg = get_config()
    start = resolve(path, cfg)
    if not start.is_dir():
        raise ToolError(f"Not a directory: {path!r}")

    if _RG_AVAILABLE:
        text = _grep_rg(cfg, start, pattern, glob, case_insensitive, max_results)
    else:
        text = _grep_python(cfg, start, pattern, glob, case_insensitive, max_results)
    return _result(text, cfg)


def find(
    pattern: Annotated[str, Field(description="Glob-style name pattern")] = "*",
    path: Annotated[str, Field(description="Directory under the server root")] = ".",
    type: Annotated[str | None, Field(description="Filter by 'file' or 'dir'")] = None,
    max_results: Annotated[int, Field(description="Maximum entries to return")] = 200,
) -> str:
    """Find files or directories by glob-style name match."""
    cfg = get_config()
    start = resolve(path, cfg)
    if not start.is_dir():
        raise ToolError(f"Not a directory: {path!r}")
    if type not in (None, "file", "dir"):
        raise ToolError(f"Invalid type filter: {type!r} (use 'file', 'dir', or omit)")

    results: list[str] = []
    # os.walk with in-place pruning avoids descending into skipped trees at all,
    # rather than walking them and discarding the results afterwards.
    for dirpath, dirnames, filenames in os.walk(start):
        dirnames[:] = sorted(d for d in dirnames if d not in DEFAULT_SKIP_DIRS)

        candidates: list[tuple[str, bool]] = []
        if type != "file":
            candidates.extend((d, True) for d in dirnames)
        if type != "dir":
            candidates.extend((f, False) for f in sorted(filenames))

        for name, is_dir in candidates:
            if not fnmatch.fnmatch(name, pattern):
                continue
            rel = _relp(Path(dirpath, name), cfg)
            results.append(f"{rel}/" if is_dir else rel)

    results.sort()
    return _result(_cap_lines(results, max_results, "additional entries hidden"), cfg)


def ls(
    path: Annotated[str, Field(description="Directory to list")] = ".",
    all: Annotated[bool, Field(description="Include hidden entries")] = False,
) -> str:
    """List the contents of a directory."""
    cfg = get_config()
    target = resolve(path, cfg)
    if not target.is_dir():
        raise ToolError(f"Not a directory: {path!r}")

    entries = [e for e in target.iterdir() if all or not e.name.startswith(".")]

    dirs = sorted([e for e in entries if e.is_dir()], key=lambda p: p.name)
    files = sorted([e for e in entries if not e.is_dir()], key=lambda p: p.name)

    lines: list[str] = []
    for entry in dirs:
        lines.append(f"{entry.name}/")
    for entry in files:
        st = entry.stat()
        lines.append(f"{entry.name} {_human_size(st.st_size)} {_fmt_time(st.st_mtime)}")

    return _result("\n".join(lines) if lines else "(empty directory)", cfg)


def register_tools(cfg: ServerConfig | None = None) -> None:
    """Register tools on the FastMCP instance respecting the active config.

    Idempotent: safe to call again after the configuration changes, which is what
    ``__main__`` does once it has parsed the CLI flags.
    """
    if cfg is None:
        cfg = get_config()

    enabled: list = [read, grep, find, ls]
    if not cfg.read_only:
        enabled.extend([write, edit])
    if cfg.allow_bash:
        enabled.append(bash)

    read_only_tools = {"read", "grep", "find", "ls"}

    # Clear every tool first so re-registration is silent and disabled tools go away.
    for name in ("read", "grep", "find", "ls", "write", "edit", "bash"):
        try:
            mcp.local_provider.remove_tool(name)
        except Exception:
            pass  # Not registered yet — nothing to remove.

    for fn in enabled:
        hint = (
            {"readOnlyHint": True}
            if fn.__name__ in read_only_tools
            else {"destructiveHint": True}
        )
        mcp.tool(fn, annotations=hint)


# Register against the default config at import time so the module can be served
# directly (e.g. `fastmcp run src/basic_fns_mcp/server.py`). __main__ re-runs this
# after applying CLI flags.
register_tools()
