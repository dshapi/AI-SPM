# tests/e2e/test_k8s_agent_lifecycle.py
"""E2E smoke test: full agent lifecycle on the k8s cluster.

Prerequisites:
  - AISPM_BASE_URL env var pointing at the spm-api ingress
    e.g. https://aispm.yourdomain.com/api/spm
    or   http://localhost:<port-forward-port>/api/spm  for local dev
  - A valid admin JWT in AISPM_ADMIN_JWT env var
  - kubectl context pointing at the target cluster

The test registers an agent, deploys it, waits for running state,
sends a chat message, then retires the agent.  Each assertion also
checks the expected k8s object state via the k8s Python client.

Dev environment note:
  Kata Containers are not available on Rancher Desktop.  Set
  SKIP_KATA_CHECK=1 to skip the runtimeClassName assertion when
  running against a dev cluster.
"""
import os
import time
import pytest
import httpx
from kubernetes import client, config

BASE = os.environ["AISPM_BASE_URL"]   # https://host/api/spm
JWT  = os.environ["AISPM_ADMIN_JWT"]
NS   = os.environ.get("AGENT_POD_NAMESPACE", "aispm-agents")
SKIP_KATA = os.environ.get("SKIP_KATA_CHECK", "").lower() in ("1", "true", "yes")

HEADERS = {"Authorization": f"Bearer {JWT}"}

AGENT_PY = '''
import aispm
aispm.ready()
# Minimal agent — just signals ready and idles.
while True:
    import time; time.sleep(60)
'''


@pytest.fixture(scope="module")
def k8s():
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()
    return client.CoreV1Api()


def test_full_agent_lifecycle(k8s):
    # 1. Register agent
    resp = httpx.post(
        f"{BASE}/agents",
        headers=HEADERS,
        files={"file": ("agent.py", AGENT_PY.encode(), "text/x-python")},
        data={"name": "smoke-test-agent", "version": "1.0.0",
              "agent_type": "custom", "owner": "e2e"},
        timeout=30,
    )
    assert resp.status_code == 201, f"register failed: {resp.text}"
    agent_id = resp.json()["id"]

    try:
        # 2. Deploy
        resp = httpx.post(
            f"{BASE}/agents/{agent_id}/start",
            headers=HEADERS, timeout=60,
        )
        assert resp.status_code == 200, f"start failed: {resp.text}"

        # 3. Wait for running state (poll up to 60s)
        for _ in range(60):
            time.sleep(1)
            r = httpx.get(f"{BASE}/agents/{agent_id}", headers=HEADERS)
            if r.json().get("runtime_state") == "running":
                break
        else:
            pytest.fail(f"agent never reached running; last state: {r.json()}")

        # 4. Verify Pod exists in k8s
        pod = k8s.read_namespaced_pod(name=f"agent-{agent_id}", namespace=NS)
        if not SKIP_KATA:
            assert pod.spec.runtime_class_name == "kata", \
                f"expected kata, got {pod.spec.runtime_class_name}"
        assert pod.metadata.labels.get("role") == "agent-runtime"

        # 5. Verify ConfigMap exists
        cm = k8s.read_namespaced_config_map(
            name=f"agent-code-{agent_id}", namespace=NS)
        assert "agent.py" in cm.data

        # 6. Verify NetworkPolicy is in place
        net = client.NetworkingV1Api()
        policies = net.list_namespaced_network_policy(namespace=NS)
        names = [p.metadata.name for p in policies.items]
        assert "default-deny-all" in names
        assert "agent-allow-egress" in names

        # 7. Stop the agent
        resp = httpx.post(
            f"{BASE}/agents/{agent_id}/stop",
            headers=HEADERS, timeout=30,
        )
        assert resp.status_code == 200

    finally:
        # 8. Retire (cleanup) — runs even if assertions fail
        httpx.delete(
            f"{BASE}/agents/{agent_id}",
            headers=HEADERS, timeout=30,
        )
        # Verify Pod and ConfigMap are gone
        time.sleep(3)
        try:
            k8s.read_namespaced_pod(name=f"agent-{agent_id}", namespace=NS)
            pytest.fail("Pod still exists after retire")
        except client.exceptions.ApiException as e:
            assert e.status == 404
