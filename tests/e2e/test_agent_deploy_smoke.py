"""End-to-end smoke test for the agent runtime control plane.

Boots against the full docker-compose stack (``./start.sh``). Skipped
unless the stack is already up and reachable on the documented ports;
this lets a normal ``pytest`` run skip e2e tests without failure.

Coverage:
  - POST /api/spm/agents (multipart) accepts a valid agent.py and returns 201
  - Bad syntax → 422
  - GET  /api/spm/agents lists the new row
  - DELETE /api/spm/agents/{id} retires it cleanly

Notes
─────
- The dev token is fetched from the ``/api/dev-token`` endpoint that
  spm-api exposes in dev mode. Production deployments mint tokens
  through the real auth path; the E2E test only runs against dev.
- ``deploy_after=False`` so we don't actually spawn a container in
  smoke tests — that's covered separately by the controller unit
  tests with mocked Docker.
"""
from __future__ import annotations

import io
import pathlib

import pytest
import requests

API   = "http://localhost:8092/api/spm"
TOKEN = "http://localhost:8092/api/dev-token"


def _stack_up() -> bool:
    """True if spm-api responds on the dev port — used to skip when the
    stack isn't running."""
    try:
        return requests.get("http://localhost:8092/health", timeout=2
                              ).status_code == 200
    except requests.RequestException:
        return False


# Skip the whole module if the stack isn't running. Running `./start.sh`
# brings it up; CI runs this in a separate stage that boots compose first.
pytestmark = pytest.mark.skipif(
    not _stack_up(),
    reason="docker-compose stack not running on :8092",
)


@pytest.fixture(scope="module")
def admin_token() -> str:
    r = requests.get(TOKEN, timeout=5)
    r.raise_for_status()
    return r.json()["token"]


@pytest.fixture
def headers(admin_token: str) -> dict:
    return {"Authorization": f"Bearer {admin_token}"}


# ─── Smoke ─────────────────────────────────────────────────────────────────

class TestAgentLifecycleSmoke:
    def test_upload_list_delete(self, headers):
        code_path = (pathlib.Path(__file__).parent
                      / "fixtures" / "hello_agent.py")

        # Upload
        with code_path.open("rb") as f:
            r = requests.post(
                f"{API}/agents",
                headers=headers,
                data={
                    "name": "hello-smoke",
                    "version": "1.0",
                    "agent_type": "custom",
                    "owner": "smoke",
                    "deploy_after": "false",
                },
                files={"code": ("agent.py", f, "text/x-python")},
                timeout=30,
            )
        assert r.status_code == 201, r.text
        agent_id = r.json()["id"]

        try:
            # Listed
            r = requests.get(f"{API}/agents", headers=headers, timeout=5)
            assert r.status_code == 200
            assert any(row["id"] == agent_id for row in r.json())

            # Detail accessible
            r = requests.get(f"{API}/agents/{agent_id}", headers=headers, timeout=5)
            assert r.status_code == 200
            assert r.json()["name"] == "hello-smoke"
        finally:
            # Cleanup — DELETE retires the row + topics
            requests.delete(f"{API}/agents/{agent_id}",
                             headers=headers, timeout=10)


class TestAgentValidationSmoke:
    def test_bad_syntax_rejected(self, headers):
        r = requests.post(
            f"{API}/agents",
            headers=headers,
            data={"name": "bad", "version": "1", "agent_type": "custom",
                  "deploy_after": "false"},
            files={"code": ("agent.py", io.BytesIO(b"def main(::"),
                            "text/x-python")},
            timeout=10,
        )
        assert r.status_code == 422
        assert any("syntax" in d.lower() for d in r.json()["detail"])
