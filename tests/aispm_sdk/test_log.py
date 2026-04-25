"""aispm.log — JSON line emission + secret redaction."""
from __future__ import annotations

import json

from aispm import _log_module as log_mod
from aispm.log import log


def test_log_emits_one_json_line(capsys, monkeypatch):
    monkeypatch.setattr(log_mod, "_AGENT_ID",  "ag-001")
    monkeypatch.setattr(log_mod, "_TENANT_ID", "t1")

    log("starting reasoning step")
    out = capsys.readouterr().out.strip()
    assert out, "log should emit on stdout"
    rec = json.loads(out)
    assert rec["msg"]       == "starting reasoning step"
    assert rec["agent_id"]  == "ag-001"
    assert rec["tenant_id"] == "t1"
    assert "ts" in rec


def test_log_carries_extra_fields_and_trace(capsys):
    log("step", trace="trc-1", step_idx=3, tool="web_fetch")
    rec = json.loads(capsys.readouterr().out.strip())
    assert rec["trace"]    == "trc-1"
    assert rec["step_idx"] == 3
    assert rec["tool"]     == "web_fetch"


def test_log_redacts_secret_like_fields(capsys):
    log("connecting",
         api_key="sk-leaked", auth_token="bearer-leaked",
         user_password="pwd-leaked", db_secret="s-leaked",
         user="dany")
    rec = json.loads(capsys.readouterr().out.strip())
    # Sensitive fields are scrubbed but their presence is recorded.
    assert rec["api_key"]       == "<redacted>"
    assert rec["auth_token"]    == "<redacted>"
    assert rec["user_password"] == "<redacted>"
    assert rec["db_secret"]     == "<redacted>"
    # Non-sensitive fields pass through.
    assert rec["user"] == "dany"


def test_log_handles_unset_constants(capsys, monkeypatch):
    monkeypatch.setattr(log_mod, "_AGENT_ID",  "")
    monkeypatch.setattr(log_mod, "_TENANT_ID", "")
    log("hello")
    rec = json.loads(capsys.readouterr().out.strip())
    assert rec["agent_id"]  == ""
    assert rec["tenant_id"] == ""
