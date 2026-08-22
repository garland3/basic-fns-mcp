# basic-fns-mcp

A **streamable-HTTP/stdio MCP server** exposing the core filesystem, shell, search, and listing tools that mirror the default agent toolset.

## Tools

| Tool | Hint | Purpose |
|------|------|---------|
| `read` | readOnly | Read a text file with cat-style line numbers |
| `write` | destructive | Create or overwrite a file atomically |
| `mkdir` | destructive | Create a directory and any missing parents |
| `edit` | destructive | Targeted string replacement in a text file |
| `bash` | destructive | Execute a shell command and capture output/exit code |
| `grep` | readOnly | Search file contents by regex (uses `rg --no-ignore` if available, with a Python fallback) |
| `find` | readOnly | Find files/directories by glob-style name match |
| `ls` | readOnly | List directory contents |

All filesystem paths are resolved relative to the configured **server root**. The server refuses any path that resolves outside that root, including symlinks that escape it — unless [`--dangerous`](#--dangerous) is set, which drops that check.

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
| `--read-only` | `BASIC_FNS_READ_ONLY` | `false` | Disable `write`, `mkdir`, and `edit` |
| `--no-bash` | `BASIC_FNS_ALLOW_BASH` | `true` | Do not register the `bash` tool |
| `--dangerous` | `BASIC_FNS_DANGEROUS` | `false` | **Drop root confinement entirely** — see below |
| `--transport` / `--stdio` | `BASIC_FNS_TRANSPORT` | `http` | `http` or `stdio` |

Command-line arguments win over environment variables.

## Security

* **Path sandbox**: `read`, `write`, `mkdir`, `edit`, `grep`, `find`, and `ls` resolve every path inside `--root`. Symlinks are followed and checked; any path that resolves outside the root is rejected. Disabled by `--dangerous`.
* **`bash` is not sandboxed**: `bash` runs with the full privileges of the server process. A shell command can `cd` anywhere, read any file the server user can read, and execute arbitrary code. Only bind to loopback (`127.0.0.1`) and expose this server to trusted clients.
* **No command blocklist**: Blocklists are easily bypassed and create a false sense of security, so none is implemented.
* **Read-only mode**: Use `--read-only` to prevent file modification via this server.

### `--dangerous`

`--dangerous` (alias `--dangerously-allow-full-access`, env `BASIC_FNS_DANGEROUS=1`)
removes the root check from the path tools. They can then read, write, and edit
anything the user running the server can — exactly the reach `bash` always had.
`--root` keeps working as the base for relative paths, so in-root usage is
unchanged.

The flag exists because the sandbox was never a real boundary while `bash` was
registered: a model that wanted a file outside the root could always shell out
for it. On a single-user trusted machine, enforcing the check on six tools and
not the seventh buys nothing but friction. Turning it on makes the reach honest
and consistent instead of pretending to a containment the server cannot provide.

Turning it off does not create a sandbox either. If you need a real boundary,
run the server as a separate unprivileged user or in a container — those are
enforced by the OS rather than by this process checking its own arguments.

Use it only where every client is trusted. It is **off by default**, must be
requested explicitly, and logs a warning to stderr at startup naming the user
whose privileges are in play:

```
WARNING: basic-fns-mcp running with --dangerous. Root confinement is OFF;
file tools can reach anything user 'you' can read or write.
```

Pair it with `--no-bash` and you get the inverse trade: full filesystem reach,
no arbitrary command execution.

## Development

Run the test suite:

```bash
uv run pytest -q
```

## License

MIT
