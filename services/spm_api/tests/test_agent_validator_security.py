"""Tests that agent_validator rejects paths outside the allowlist."""
import os, pytest


def test_path_outside_allowlist_rejected(tmp_path, monkeypatch):
    """A path outside the allowlist dir must raise ValueError."""
    evil = tmp_path / "evil_agent.py"
    evil.write_text("import os; os.system('id')")
    monkeypatch.setenv("AGENT_ALLOWLIST_DIR", str(tmp_path / "agents"))  # different dir
    from services.spm_api import agent_validator
    import importlib; importlib.reload(agent_validator)
    with pytest.raises((ValueError, PermissionError)):
        agent_validator.validate_agent_module(str(evil))


def test_path_traversal_rejected(tmp_path, monkeypatch):
    """Path traversal attempts must be rejected."""
    monkeypatch.setenv("AGENT_ALLOWLIST_DIR", str(tmp_path / "agents"))
    from services.spm_api import agent_validator
    import importlib; importlib.reload(agent_validator)
    with pytest.raises((ValueError, PermissionError)):
        agent_validator.validate_agent_module("/etc/passwd")


def test_valid_agent_path_accepted(tmp_path, monkeypatch):
    """A .py file inside the allowlist dir must load without raising."""
    allowlist = tmp_path / "agents"
    allowlist.mkdir()
    agent = allowlist / "my_agent.py"
    agent.write_text("class Agent: pass\n")
    monkeypatch.setenv("AGENT_ALLOWLIST_DIR", str(allowlist))
    from services.spm_api import agent_validator
    import importlib; importlib.reload(agent_validator)
    mod = agent_validator.validate_agent_module(str(agent))
    assert hasattr(mod, "Agent")
