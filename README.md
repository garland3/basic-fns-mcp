# basic-fns-mcp

A **streamable-HTTP/stdio MCP server** exposing the core filesystem, shell, search, and listing tools that mirror the default agent toolset.

## Tools

| Tool | Hint | Purpose |
|------|------|---------|
| `read` | readOnly | Read a text file with cat-style line numbers |
| `write` | destructive | Create or overwrite a file atomically |
| `edit` | destructive | Targeted string replacement in a text file |
| `bash` | destructive | Execute a shell command and capture output/exit code |
| `grep` | readOnly | Search file contents by regex (uses `rg --no-ignore` if available, with a Python fallback) |
| `find` | readOnly | Find files/directories by glob-style name match |
| `ls` | readOnly | List directory contents |

All filesystem paths are resolved relative to the configured **server root**. The server refuses any path that resolves outside that root, including symlinks that escape it.

## Quick start

Install and run over HTTP:

```bash
uv sync
uv run basic-fns-mcp --root . --port 8080
```

Add it to Claude Code:

```bash
claude mcp add --transport http basic-fns http://127.0.0.1:8080/mcp
```

### stdio

The same server runs over stdio, where the client spawns it as a subprocess:

```bash
uv run basic-fns-mcp --stdio            # or: --transport stdio
```

Add it to Claude Code:

```bash
claude mcp add basic-fns -- uv run --directory /path/to/basic-fns-mcp basic-fns-mcp --stdio
```

Or in an MCP client config file:

```json
{
  "mcpServers": {
    "basic-fns": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/basic-fns-mcp", "basic-fns-mcp", "--stdio"],
      "env": { "BASIC_FNS_ROOT": "/path/to/your/project" }
    }
  }
}
```

On stdio, stdout is the protocol channel — the startup banner is suppressed and all
logging goes to stderr. The `--host`/`--port` flags are ignored.

The module can also be served directly, since tools are registered at import time:

```bash
uv run fastmcp run src/basic_fns_mcp/server.py
```

## CLI flags / environment variables

| Flag | Environment variable | Default | Meaning |
|------|---------------------|---------|---------|
| `--root` | `BASIC_FNS_ROOT` | current working directory | Sandbox root; all paths resolve under it |
| `--host` | `BASIC_FNS_HOST` | `127.0.0.1` | HTTP bind address |
| `--port` | `BASIC_FNS_PORT` | `8080` | HTTP bind port |
| `--max-read-bytes` | `BASIC_FNS_MAX_READ_BYTES` | `2_000_000` | Refuse `read` for files larger than this |
| `--max-output-chars` | `BASIC_FNS_MAX_OUTPUT` | `100_000` | Cap any tool result to this length |
| `--bash-timeout` | `BASIC_FNS_BASH_TIMEOUT` | `120` | Default shell timeout in seconds |
| `--read-only` | `BASIC_FNS_READ_ONLY` | `false` | Disable `write` and `edit` |
| `--no-bash` | `BASIC_FNS_ALLOW_BASH` | `true` | Do not register the `bash` tool |
| `--transport` / `--stdio` | `BASIC_FNS_TRANSPORT` | `http` | `http` or `stdio` |

Command-line arguments win over environment variables.

## Security

* **Path sandbox**: `read`, `write`, `edit`, `grep`, `find`, and `ls` resolve every path inside `--root`. Symlinks are followed and checked; any path that resolves outside the root is rejected.
* **`bash` is not sandboxed**: `bash` runs with the full privileges of the server process. A shell command can `cd` anywhere, read any file the server user can read, and execute arbitrary code. Only bind to loopback (`127.0.0.1`) and expose this server to trusted clients.
* **No command blocklist**: Blocklists are easily bypassed and create a false sense of security, so none is implemented.
* **Read-only mode**: Use `--read-only` to prevent file modification via this server.

## Development

Run the test suite:

```bash
uv run pytest -q
```

## License

MIT
