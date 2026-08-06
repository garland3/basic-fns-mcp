import pytest

from basic_fns_mcp.config import ServerConfig, set_config


@pytest.fixture
def cfg(tmp_path):
    """Create a scratch-root config and install it as the active singleton."""
    c = ServerConfig(
        root=tmp_path.resolve(),
        allow_bash=True,
        read_only=False,
        bash_timeout=120,
        max_read_bytes=2_000_000,
        max_output_chars=100_000,
    )
    set_config(c)
    return c
