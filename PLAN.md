# PLAN.md — `basic-fns-mcp`

Build a **streamable-HTTP MCP server** exposing the core filesystem/shell tools that mirror
the Pi agent's default toolset, plus search/listing helpers.

Target tools (7):

| Tool    | Purpose |
|---------|---------|
| `read`  | Read file contents from the working directory |
| `write` | Create (or overwrite) files |
| `edit`  | Targeted string-replacement edits — never full rewrites |
| `bash`  | Execute shell commands |
| `grep`  | Search file *contents* by regex |
| `find`  | Find *files* by glob/name pattern |
| `ls`    | List directory contents |

---

## 0. Environment (already verified — do not re-check)

- Working dir: `/home/garlan/ATLAS-GROUP/basic-fns-mcp` (currently empty).
- Not a git repo. Run `git init` before the first commit.
- `fastmcp` **3.1.0** is importable with the system `python3`.
- `uv` is installed at `/home/garlan/.local/bin/uv`.

FastMCP 3.x API facts confirmed by introspection:

```python
FastMCP.run(self, transport=None, show_banner=None, **transport_kwargs) -> None
# @mcp.tool works both bare and with kwargs (name=, description=, annotations=, tags=, ...)
```

So HTTP serving is `mcp.run(transport="http", host=..., port=...)`.

---

## 1. Layout

```
basic-fns-mcp/
├── pyproject.toml
├── README.md
├── PLAN.md                # this file
├── .gitignore
├── src/basic_fns_mcp/
│   ├── __init__.py
│   ├── __main__.py        # `python -m basic_fns_mcp`
│   ├── server.py          # FastMCP instance + tool registrations
│   ├── config.py          # ServerConfig: root dir, limits, allow-write, bash toggle
│   └── safety.py          # path resolution / sandbox enforcement
└── tests/
    ├── conftest.py
    ├── test_safety.py
    └── test_tools.py
```

`pyproject.toml`: name `basic-fns-mcp`, requires-python `>=3.10`, deps `fastmcp>=3.1,<4`.
Console script `basic-fns-mcp = "basic_fns_mcp.__main__:main"`.
Dev extra: `pytest`, `pytest-asyncio`.

---

## 2. `config.py`

A frozen dataclass built once at startup from CLI flags + env vars (CLI wins):

| Field | Env | Default | Meaning |
|---|---|---|---|
| `root` | `BASIC_FNS_ROOT` | `os.getcwd()` | Sandbox root; all paths resolve under it |
| `host` | `BASIC_FNS_HOST` | `127.0.0.1` | Bind address |
| `port` | `BASIC_FNS_PORT` | `8080` | Bind port |
| `max_read_bytes` | `BASIC_FNS_MAX_READ_BYTES` | `2_000_000` | Refuse larger reads |
| `max_output_chars` | `BASIC_FNS_MAX_OUTPUT` | `100_000` | Truncate any tool result beyond this |
| `bash_timeout` | `BASIC_FNS_BASH_TIMEOUT` | `120` | Seconds |
| `allow_bash` | `BASIC_FNS_ALLOW_BASH` | `true` | If false, `bash` is not registered |
| `read_only` | `BASIC_FNS_READ_ONLY` | `false` | If true, `write`/`edit` are not registered |

Store the resolved config in a module-level singleton the tools read at call time.

---

## 3. `safety.py` — the part that matters most

```python
def resolve(path: str, cfg: ServerConfig) -> Path
```

Rules:
1. Expand `~`, then resolve relative paths against `cfg.root`.
2. `Path.resolve()` the result (**resolves symlinks**) and the root.
3. Reject unless the resolved path is `root` or has `root` among its `.parents`.
   Use `Path.is_relative_to` — never string `startswith` (`/srv/app-evil` would
   pass a `startswith("/srv/app")` check).
4. Raise `ToolError` (from `fastmcp.exceptions`) with a clear message on rejection —
   `ToolError` text is surfaced to the client; other exceptions get masked.

Also provide `truncate(text, limit) -> str` appending
`\n... [truncated, N chars omitted]`.

**`bash` sandboxing:** run with `cwd=cfg.root`, but do NOT pretend the sandbox holds —
a shell command can `cd` anywhere. Document this honestly in the README: `bash` grants
full user-level shell access and the server should only be bound to loopback and
exposed to trusted clients. Do not build a command blocklist; they are trivially
bypassed and give false confidence.

---

## 4. Tool specs

Each tool: typed params, `Annotated[..., Field(description=...)]` for arg docs, a
docstring the model actually reads, and `annotations={"readOnlyHint": True}` on
`read`/`grep`/`find`/`ls` and `{"destructiveHint": True}` on `write`/`edit`/`bash`.

All paths returned to the caller should be **relative to `cfg.root`** for compactness.

### `read(path, offset=0, limit=2000)`
- Reject if not a file, or size > `max_read_bytes`.
- Read text as UTF-8 with `errors="replace"`.
- `offset` is a 0-indexed line number; `limit` is a line count.
- Return lines prefixed `cat -n` style: right-aligned line number, tab, content
  (matches what coding agents expect and makes `edit` targeting easier).
- Detect binary (NUL byte in first 8 KiB) → `ToolError("binary file")`.

### `write(path, content)`
- Create parent dirs (`mkdir(parents=True, exist_ok=True)`).
- Overwrite allowed; report whether it created or replaced, and the byte count.
- Write atomically: temp file in the same dir + `os.replace`.

### `edit(path, old_string, new_string, replace_all=False)`
- Error if `old_string == new_string`.
- Count occurrences. If 0 → error "not found". If >1 and not `replace_all` →
  error naming the count and telling the caller to add more surrounding context or
  pass `replace_all=True`.
- Preserve original line endings and trailing-newline presence.
- Return the number of replacements plus a small before/after context snippet.

### `bash(command, timeout=None, cwd=None)`
- `subprocess.run(command, shell=True, cwd=..., capture_output=True, text=True, timeout=...)`.
- `cwd` defaults to `cfg.root`, resolved through `safety.resolve` if given.
- On `TimeoutExpired`, return a clear timeout message including partial output if available.
- Return a combined block: exit code, then `stdout`, then `stderr` (only include
  sections that are non-empty). Truncate each to `max_output_chars`.
- Never raise on non-zero exit — a failed command is a *result*, not a tool error.

### `grep(pattern, path=".", glob=None, case_insensitive=False, max_results=200)`
- Prefer shelling out to `rg --no-heading --line-number` when `rg` is on PATH
  (check once with `shutil.which`); fall back to a pure-Python walk using `re`.
- The Python fallback must skip binary files and honor `glob` via `fnmatch`.
- Always skip: `.git`, `node_modules`, `__pycache__`, `.venv`, `venv`, `dist`, `build`.
- Return `relpath:lineno:line`, capped at `max_results`, and state when capped.

### `find(pattern="*", path=".", type=None, max_results=200)`
- Glob-style name match via `Path.rglob` + `fnmatch`.
- `type` accepts `"file"` / `"dir"` / `None`.
- Same skip-list and cap behavior as `grep`. Sort results for determinism.

### `ls(path=".", all=False)`
- Directories first, then files, each alphabetical.
- One entry per line: name (with trailing `/` for dirs), size for files, mtime.
- Hidden entries only when `all=True`.
- Error if `path` is not a directory.

---

## 5. `server.py` wiring

```python
mcp = FastMCP("basic-fns-mcp", instructions="...")
```

Register the read-only tools unconditionally; gate `write`/`edit` on
`not cfg.read_only` and `bash` on `cfg.allow_bash`. `instructions` should tell the
client that all paths are relative to the server root and that `edit` requires
unique `old_string` context.

`__main__.py` — `argparse` with `--root --host --port --read-only --no-bash
--bash-timeout --transport {http,stdio}`; build the config, then
`mcp.run(transport=args.transport, host=..., port=...)` (pass host/port only for
`http`). Default transport is `http`; keep `stdio` available since it makes local
testing and Claude Code registration trivial.

---

## 6. Tests

`pytest` + `tmp_path` fixture that points `cfg.root` at a scratch tree.
Call the underlying functions directly (import the plain functions, not the
`FunctionTool` wrappers — keep each tool body in a module-level function so it is
importable and testable).

Must cover:
- `resolve` rejects `../` escape, absolute outside path, and a symlink pointing outside root.
- `resolve` accepts a nested relative path and a path equal to root.
- `read` line numbering, `offset`/`limit`, binary rejection, oversize rejection.
- `write` creates parents, overwrites, is atomic (no leftover temp files in the dir).
- `edit` — 0 matches errors, 2 matches errors without `replace_all`, succeeds with it,
  no-op when old == new errors.
- `bash` — non-zero exit returns output rather than raising; timeout path.
- `grep`/`find`/`ls` — skip-list honored, cap honored and announced.

Target: all tests pass with `uv run pytest`.

---

## 7. Verification before reporting done

1. `uv sync` (or `uv venv && uv pip install -e ".[dev]"`).
2. `uv run pytest -q` — all green.
3. Start it: `uv run basic-fns-mcp --port 8080` and confirm it binds.
4. Smoke-test the HTTP endpoint with a FastMCP client in a scratch script:
   ```python
   from fastmcp import Client
   async with Client("http://127.0.0.1:8080/mcp") as c:
       print([t.name for t in await c.list_tools()])
       print(await c.call_tool("ls", {"path": "."}))
   ```
   Confirm all 7 tool names appear and `ls`/`read`/`bash` return sane results.
   Put scratch scripts in the scratchpad dir, not the repo.
5. Write `README.md`: what each tool does, every flag/env var, the
   `claude mcp add --transport http basic-fns http://127.0.0.1:8080/mcp`
   registration line, and an explicit **security** section covering the sandbox's
   real boundary and `bash`'s lack of one.

Report honestly: if a test fails or a step is skipped, say so with the output.
