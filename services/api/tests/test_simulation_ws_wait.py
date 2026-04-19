import os
import pytest


def test_ws_wait_default_is_10s():
    """Default WS wait timeout is 10s when env var not set."""
    os.environ.pop("WS_WAIT_TIMEOUT_S", None)
    # Re-import to pick up env var state
    import importlib
    import services.api.routes.simulation as sim_mod
    importlib.reload(sim_mod)
    assert sim_mod._WS_WAIT_TIMEOUT_S == 10.0


def test_ws_wait_uses_env_var_timeout(monkeypatch):
    """WS_WAIT_TIMEOUT_S env var controls the timeout."""
    monkeypatch.setenv("WS_WAIT_TIMEOUT_S", "5.0")
    import importlib
    import services.api.routes.simulation as sim_mod
    importlib.reload(sim_mod)
    assert sim_mod._WS_WAIT_TIMEOUT_S == 5.0
