"""Tests for the kiro-cli + codex enhanced-backend providers (no subprocess)."""


def test_all_three_backends_registered():
    import agenticops.acp  # triggers registration at import
    from agenticops.acp.registry import available_backends
    assert available_backends() == ["claude-code", "codex", "kiro-cli"]


def test_get_kiro_backend():
    import agenticops.acp
    from agenticops.acp.registry import get_backend
    be = get_backend("kiro-cli")
    assert be.name == "kiro-cli"
    caps = be.capabilities()
    assert caps.streaming and caps.permissions and not caps.tools


def test_get_codex_backend():
    import agenticops.acp
    from agenticops.acp.registry import get_backend
    be = get_backend("codex")
    assert be.name == "codex"
    caps = be.capabilities()
    assert caps.streaming and not caps.tools


def test_kiro_uses_configured_command(monkeypatch):
    monkeypatch.setattr("agenticops.config.settings.acp_kiro_command", "kiro-cli", raising=False)
    monkeypatch.setattr("agenticops.config.settings.acp_kiro_args", ["acp", "--trust-all-tools"], raising=False)
    import agenticops.acp
    from agenticops.acp.registry import get_backend
    be = get_backend("kiro-cli")
    # the backend wraps an AcpClient with the configured launch command
    assert be._client._command == "kiro-cli"
    assert "acp" in be._client._args


def test_codex_passes_openai_key_when_present(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-xxx")
    import agenticops.acp
    from agenticops.acp.registry import get_backend
    be = get_backend("codex")
    assert be._client._env.get("OPENAI_API_KEY") == "sk-test-xxx"


def test_acp_client_protocol_version_default_is_1():
    from agenticops.acp.client import AcpClient
    c = AcpClient(command="x", args=[])
    assert c._protocol_version == 1
    c2 = AcpClient(command="x", args=[], protocol_version=2)
    assert c2._protocol_version == 2
