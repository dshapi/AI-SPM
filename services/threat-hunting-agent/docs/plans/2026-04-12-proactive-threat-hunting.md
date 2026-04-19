# Proactive Threat Hunting Layer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a scheduler-driven security scanning system to the threat-hunting-agent that continuously collects system state, converts it to synthetic events, and feeds them into the existing `run_hunt()` / `FindingsService` pipeline with `source = "proactive_scan"`.

**Architecture:** A `ProactiveScheduler` fires every N seconds (default 300), iterating a deterministic `SCAN_REGISTRY`. Each scan calls a read-only collector, converts the result to synthetic event dicts, and calls the existing `hunt_agent(TENANT_ID, events)` callable. The returned `Finding` dict is stamped with `source = "proactive_scan"` and `is_proactive = True` before being handed to the existing `persist_fn`. No new pipeline, no new agent, no LLM in the scan path.

**Tech Stack:** Python 3.10, threading.Timer, httpx (already present), socket (stdlib), existing `tools/postgres_tool.py` + `tools/redis_tool.py`, pydantic-settings for config, pytest + unittest.mock for tests.

---

## File Map

### New files — `services/threat-hunting-agent/proactive/`
| File | Responsibility |
|------|---------------|
| `proactive/__init__.py` | Package marker |
| `proactive/scan_registry.py` | `ScanDefinition` dataclass + `SCAN_REGISTRY` dict; single authoritative list of all scans |
| `proactive/scan_runner.py` | `run_scan(scan_type, hunt_agent, persist_fn)` + `run_all_scans()`; event conversion layer |
| `proactive/scheduler.py` | `ProactiveScheduler` with `start()` / `stop()`; threading.Timer loop |
| `proactive/collectors/__init__.py` | Package marker |
| `proactive/collectors/secrets_collector.py` | Scan Redis key names for secret-pattern exposure |
| `proactive/collectors/network_collector.py` | Socket-probe known service ports for unexpected reachability |
| `proactive/collectors/agent_config_collector.py` | Query model registry for unacceptable-risk or unapproved models |
| `proactive/collectors/runtime_collector.py` | Audit log + session anomaly pattern detection (Postgres + orchestrator API) |

### New files — `services/threat-hunting-agent/tests/proactive/`
| File | Responsibility |
|------|---------------|
| `tests/proactive/__init__.py` | Package marker |
| `tests/proactive/test_scan_registry.py` | All scans registered; ScanDefinition fields valid |
| `tests/proactive/test_collectors.py` | Each collector returns expected structure; mock dependencies |
| `tests/proactive/test_scan_runner.py` | event conversion shape; `run_scan` → hunt called → persist called; source stamped |
| `tests/proactive/test_scheduler.py` | Scheduler fires run_all_scans on interval; stop() cancels timer |

### Modified files
| File | Change |
|------|--------|
| `services/threat-hunting-agent/config.py` | Add `proactive_scan_interval_sec: int = 300` |
| `services/threat-hunting-agent/service/findings_service.py` | Use `finding_dict.get("source", "threat-hunting-agent")` instead of hardcoded string |
| `services/threat-hunting-agent/app.py` | Instantiate + start/stop `ProactiveScheduler` in lifespan |
| `services/agent-orchestrator-service/threat_findings/schemas.py` | Add `is_proactive: bool = False` to `CreateFindingRequest` and `FindingRecord` |
| `services/agent-orchestrator-service/threat_findings/models.py` | Add `is_proactive` to `_orm_to_record()` and `insert()` |
| `services/agent-orchestrator-service/threat_findings/service.py` | Populate `source` and `is_proactive` from `req` in both `create_finding` and `persist_finding_from_dict` |
| `services/agent-orchestrator-service/db/models.py` | Add `is_proactive = Column(Boolean, nullable=True)` to `ThreatFindingORM` |
| `services/agent-orchestrator-service/main.py` | Add `("is_proactive", "BOOLEAN")` to `_NEW_THREAT_FINDING_COLS` migration list |

---

## Task 1: Add `is_proactive` to the orchestrator schema + ORM

**Files:**
- Modify: `services/agent-orchestrator-service/db/models.py`
- Modify: `services/agent-orchestrator-service/threat_findings/schemas.py`
- Modify: `services/agent-orchestrator-service/threat_findings/models.py`
- Modify: `services/agent-orchestrator-service/threat_findings/service.py`
- Modify: `services/agent-orchestrator-service/main.py`
- Test: `services/agent-orchestrator-service/tests/threat_findings/test_service.py`

- [ ] **Step 1: Add ORM column to `db/models.py`**

  In `ThreatFindingORM`, after the `updated_at` column, add:
  ```python
  is_proactive = Column(Boolean, nullable=True, default=False)
  ```

- [ ] **Step 2: Add field to `threat_findings/schemas.py`**

  In `FindingRecord` dataclass, after `updated_at`:
  ```python
  is_proactive: bool = False
  ```

  In `CreateFindingRequest` Pydantic model, after `source`:
  ```python
  is_proactive: bool = False
  ```

- [ ] **Step 3: Update `threat_findings/models.py`**

  In `_orm_to_record()`, after `source=row.source`:
  ```python
  is_proactive=bool(row.is_proactive) if row.is_proactive is not None else False,
  ```

  In `ThreatFindingRepository.insert()`, after `source=rec.source`:
  ```python
  is_proactive=rec.is_proactive,
  ```

- [ ] **Step 4: Populate `source` and `is_proactive` from request in `service.py`**

  In `create_finding`, the `FindingRecord` constructor currently omits `source` and `is_proactive`. Add them:
  ```python
  rec = FindingRecord(
      id=str(uuid4()),
      batch_hash=req.batch_hash,
      title=req.title,
      severity=req.severity,
      description=req.description,
      evidence=req.evidence,
      ttps=req.ttps,
      tenant_id=req.tenant_id,
      source=req.source,           # ADD
      is_proactive=req.is_proactive,  # ADD
  )
  ```

  In `persist_finding_from_dict`, the `FindingRecord` constructor already sets `source`. Add `is_proactive`:
  ```python
  is_proactive=bool(finding_dict.get("is_proactive", False)),
  ```

- [ ] **Step 5: Add column to migration list in `main.py`**

  In `_NEW_THREAT_FINDING_COLS`, append:
  ```python
  ("is_proactive", "BOOLEAN"),
  ```

- [ ] **Step 6: Write failing test for `is_proactive` passthrough**

  In `tests/threat_findings/test_service.py`, add:
  ```python
  @pytest.mark.asyncio
  async def test_create_finding_stores_is_proactive(svc):
      finding_repo, case_repo = _make_repos()
      req = CreateFindingRequest(
          title="Proactive scan finding",
          severity="medium", description="desc",
          evidence=[], ttps=[], tenant_id="t1",
          batch_hash="hash-proactive",
          source="proactive_scan",
          is_proactive=True,
      )
      await svc.create_finding(req, finding_repo, case_repo)
      inserted = finding_repo.insert.call_args[0][0]
      assert inserted.source == "proactive_scan"
      assert inserted.is_proactive is True
  ```

  Run: `cd services/agent-orchestrator-service && python -m pytest tests/threat_findings/test_service.py::test_create_finding_stores_is_proactive -v`
  Expected: FAIL (field not yet on FindingRecord)

- [ ] **Step 7: Run test — verify it passes after implementation**

  Run: `python -m pytest tests/threat_findings/test_service.py -v`
  Expected: all pass

- [ ] **Step 8: Run full orchestrator suite**

  Run: `python -m pytest -x -q`
  Expected: all pass (was 287 before this task)

- [ ] **Step 9: Commit**
  ```bash
  git add services/agent-orchestrator-service/
  git commit -m "feat(orchestrator): add is_proactive field to threat findings schema + ORM"
  ```

---

## Task 2: Fix `source` passthrough in `FindingsService`

**Files:**
- Modify: `services/threat-hunting-agent/service/findings_service.py`
- Test: `services/threat-hunting-agent/tests/test_findings_service.py`

Context: `findings_service.py` currently hardcodes `"source": "threat-hunting-agent"` in the payload dict, ignoring whatever `source` is in the finding dict. This means proactive findings will have the wrong source in the DB.

- [ ] **Step 1: Write failing test**

  In `tests/test_findings_service.py` (create if not present), add:
  ```python
  from unittest.mock import MagicMock, patch
  import pytest
  from service.findings_service import FindingsService

  def _make_svc():
      svc = FindingsService(
          orchestrator_url="http://fake-orchestrator",
          dev_token_url="http://fake-api/dev-token",
      )
      return svc

  def test_persist_finding_passes_source_through(respx_mock=None):
      """source in finding_dict must reach the POST payload, not be overwritten."""
      import httpx
      from unittest.mock import patch, MagicMock
      
      svc = _make_svc()
      captured = {}

      def fake_post(url, json=None, headers=None, **kwargs):
          captured["payload"] = json
          resp = MagicMock()
          resp.raise_for_status = lambda: None
          resp.json.return_value = {"id": "x", "deduplicated": False}
          return resp

      def fake_get(url, **kwargs):
          resp = MagicMock()
          resp.raise_for_status = lambda: None
          resp.json.return_value = {"token": "tok", "expires_in": 3600}
          return resp

      with patch.object(svc._client, "post", side_effect=fake_post), \
           patch.object(svc._client, "get", side_effect=fake_get):
          svc.persist_finding(
              {"title": "T", "severity": "low", "source": "proactive_scan"},
              "t1",
          )

      assert captured["payload"]["source"] == "proactive_scan"
  ```

  Run: `cd services/threat-hunting-agent && python -m pytest tests/test_findings_service.py::test_persist_finding_passes_source_through -v`
  Expected: FAIL

- [ ] **Step 2: Fix the hardcoded source in `findings_service.py`**

  Change line:
  ```python
  "source": "threat-hunting-agent",
  ```
  To:
  ```python
  "source": finding_dict.get("source", "threat-hunting-agent"),
  ```

- [ ] **Step 3: Run test — verify it passes**

  Run: `python -m pytest tests/test_findings_service.py -v`
  Expected: PASS

- [ ] **Step 4: Commit**
  ```bash
  git add services/threat-hunting-agent/service/findings_service.py \
          services/threat-hunting-agent/tests/test_findings_service.py
  git commit -m "fix(findings-service): pass source from finding dict instead of hardcoding"
  ```

---

## Task 3: Add `proactive_scan_interval_sec` to config + scan registry

**Files:**
- Modify: `services/threat-hunting-agent/config.py`
- Create: `services/threat-hunting-agent/proactive/__init__.py`
- Create: `services/threat-hunting-agent/proactive/scan_registry.py`
- Test: `services/threat-hunting-agent/tests/proactive/__init__.py`
- Test: `services/threat-hunting-agent/tests/proactive/test_scan_registry.py`

- [ ] **Step 1: Add config field**

  In `config.py`, add to `Settings`:
  ```python
  proactive_scan_interval_sec: int = 300
  ```

- [ ] **Step 2: Create package markers**

  Create `proactive/__init__.py` (empty).
  Create `tests/proactive/__init__.py` (empty).

- [ ] **Step 3: Write failing test for scan registry**

  Create `tests/proactive/test_scan_registry.py`:
  ```python
  """Tests for proactive/scan_registry.py"""
  import pytest
  from proactive.scan_registry import SCAN_REGISTRY, ScanDefinition, SCAN_NAMES

  class TestScanRegistry:
      def test_all_expected_scans_present(self):
          assert "exposed_credentials" in SCAN_REGISTRY
          assert "unused_open_ports" in SCAN_REGISTRY
          assert "overprivileged_tools" in SCAN_REGISTRY
          assert "sensitive_data_exposure" in SCAN_REGISTRY
          assert "anomalous_runtime_behavior" in SCAN_REGISTRY

      def test_scan_count(self):
          assert len(SCAN_REGISTRY) == 5

      def test_each_entry_is_scan_definition(self):
          for name, defn in SCAN_REGISTRY.items():
              assert isinstance(defn, ScanDefinition), f"{name} not a ScanDefinition"

      def test_scan_definition_has_collector(self):
          for name, defn in SCAN_REGISTRY.items():
              assert callable(defn.collector), f"{name}.collector not callable"
              assert defn.description, f"{name}.description empty"

      def test_scan_names_constant_matches_registry(self):
          assert set(SCAN_NAMES) == set(SCAN_REGISTRY.keys())
  ```

  Run: `python -m pytest tests/proactive/test_scan_registry.py -v`
  Expected: FAIL (module doesn't exist)

- [ ] **Step 4: Implement `proactive/scan_registry.py`**

  ```python
  """
  proactive/scan_registry.py
  ───────────────────────────
  Central registry of all proactive security scans.

  Each entry maps a scan name → ScanDefinition with a deterministic,
  read-only collector callable. The LLM is never in the scan path.
  """
  from __future__ import annotations

  from dataclasses import dataclass
  from typing import Any, Callable, Dict, List


  @dataclass(frozen=True)
  class ScanDefinition:
      """Immutable descriptor for one proactive scan."""
      name:        str
      description: str
      collector:   Callable[[], List[Dict[str, Any]]]


  def _lazy_secrets() -> List[Dict[str, Any]]:
      from proactive.collectors.secrets_collector import collect
      return collect()


  def _lazy_network() -> List[Dict[str, Any]]:
      from proactive.collectors.network_collector import collect
      return collect()


  def _lazy_agent_config() -> List[Dict[str, Any]]:
      from proactive.collectors.agent_config_collector import collect
      return collect()


  def _lazy_runtime() -> List[Dict[str, Any]]:
      from proactive.collectors.runtime_collector import collect
      return collect()


  # Aliases so scan_runner can call the same collector for two scan names.
  # sensitive_data_exposure is secrets_collector with a broader lens.
  def _lazy_sensitive_data() -> List[Dict[str, Any]]:
      from proactive.collectors.secrets_collector import collect_sensitive_data
      return collect_sensitive_data()


  SCAN_REGISTRY: Dict[str, ScanDefinition] = {
      "exposed_credentials": ScanDefinition(
          name="exposed_credentials",
          description=(
              "Scan Redis key names for patterns matching API keys, tokens, "
              "passwords, and other credentials that should not be in memory."
          ),
          collector=_lazy_secrets,
      ),
      "unused_open_ports": ScanDefinition(
          name="unused_open_ports",
          description=(
              "Probe known internal service ports to detect unexpected "
              "reachability that may indicate a misconfigured or rogue service."
          ),
          collector=_lazy_network,
      ),
      "overprivileged_tools": ScanDefinition(
          name="overprivileged_tools",
          description=(
              "Query the model registry for AI models with unacceptable risk tier "
              "still in active status, or missing mandatory approval metadata."
          ),
          collector=_lazy_agent_config,
      ),
      "sensitive_data_exposure": ScanDefinition(
          name="sensitive_data_exposure",
          description=(
              "Broader scan for PII patterns, database connection strings, and "
              "other sensitive data stored under unexpected Redis namespaces."
          ),
          collector=_lazy_sensitive_data,
      ),
      "anomalous_runtime_behavior": ScanDefinition(
          name="anomalous_runtime_behavior",
          description=(
              "Detect abnormal session patterns: repeated high-risk sessions from "
              "the same actor, tool-abuse frequency, and anomalous memory usage."
          ),
          collector=_lazy_runtime,
      ),
  }

  # Convenience list for iteration and tests
  SCAN_NAMES: List[str] = list(SCAN_REGISTRY.keys())
  ```

- [ ] **Step 5: Run test — verify it passes**

  Run: `python -m pytest tests/proactive/test_scan_registry.py -v`
  Expected: PASS (collectors don't need to be implemented yet — lambdas are callables)

- [ ] **Step 6: Commit**
  ```bash
  git add services/threat-hunting-agent/config.py \
          services/threat-hunting-agent/proactive/ \
          services/threat-hunting-agent/tests/proactive/
  git commit -m "feat(proactive): scan registry + config field"
  ```

---

## Task 4: Implement the four collectors

**Files:**
- Create: `proactive/collectors/__init__.py`
- Create: `proactive/collectors/secrets_collector.py`
- Create: `proactive/collectors/network_collector.py`
- Create: `proactive/collectors/agent_config_collector.py`
- Create: `proactive/collectors/runtime_collector.py`
- Test: `tests/proactive/test_collectors.py`

- [ ] **Step 1: Write failing tests for all collectors**

  Create `tests/proactive/test_collectors.py`:
  ```python
  """
  Tests for all four proactive collectors.
  All external I/O is mocked — no real Redis, Postgres, or network calls.
  """
  from __future__ import annotations

  import json
  import socket
  from unittest.mock import MagicMock, patch

  import pytest


  # ── secrets_collector ────────────────────────────────────────────────────────

  class TestSecretsCollector:
      def test_returns_list(self):
          from proactive.collectors.secrets_collector import collect
          with patch("tools.redis_tool._redis_client") as mock_redis:
              mock_redis.scan_iter.return_value = iter([])
              result = collect()
          assert isinstance(result, list)

      def test_detects_api_key_pattern(self):
          from proactive.collectors.secrets_collector import collect
          suspicious_keys = [b"session:user1:api_key", b"config:openai_token"]
          with patch("tools.redis_tool._redis_client") as mock_redis:
              mock_redis.scan_iter.return_value = iter(suspicious_keys)
              result = collect()
          assert len(result) == 2
          assert result[0]["type"] == "secret_exposure"
          assert "location" in result[0]
          assert "key_name" in result[0]

      def test_ignores_safe_keys(self):
          from proactive.collectors.secrets_collector import collect
          safe_keys = [b"freeze:user1", b"session:abc123", b"mem:session:t1:u1:chat"]
          with patch("tools.redis_tool._redis_client") as mock_redis:
              mock_redis.scan_iter.return_value = iter(safe_keys)
              result = collect()
          assert result == []

      def test_collect_sensitive_data_returns_list(self):
          from proactive.collectors.secrets_collector import collect_sensitive_data
          with patch("tools.redis_tool._redis_client") as mock_redis:
              mock_redis.scan_iter.return_value = iter([])
              result = collect_sensitive_data()
          assert isinstance(result, list)

      def test_redis_unavailable_returns_empty(self):
          from proactive.collectors.secrets_collector import collect
          with patch("tools.redis_tool._redis_client", None):
              result = collect()
          assert result == []


  # ── network_collector ────────────────────────────────────────────────────────

  class TestNetworkCollector:
      def test_returns_list(self):
          from proactive.collectors.network_collector import collect
          with patch("socket.create_connection", side_effect=ConnectionRefusedError):
              result = collect()
          assert isinstance(result, list)

      def test_open_port_detected(self):
          from proactive.collectors.network_collector import collect
          # Simulate one port open (mock create_connection returns normally)
          mock_sock = MagicMock()
          def _connect(addr, timeout):
              host, port = addr
              if port == 8094:  # orchestrator — expected reachable
                  return mock_sock
              raise ConnectionRefusedError
          with patch("socket.create_connection", side_effect=_connect):
              result = collect()
          assert any(r["port"] == 8094 and r["reachable"] is True for r in result)

      def test_each_result_has_required_fields(self):
          from proactive.collectors.network_collector import collect
          with patch("socket.create_connection", side_effect=ConnectionRefusedError):
              result = collect()
          for item in result:
              assert "type" in item
              assert "host" in item
              assert "port" in item
              assert "reachable" in item
              assert item["type"] == "port_status"


  # ── agent_config_collector ───────────────────────────────────────────────────

  class TestAgentConfigCollector:
      def _make_pg_factory(self, rows):
          """Return a fake Postgres connection factory yielding `rows`."""
          mock_conn = MagicMock()
          mock_cursor = MagicMock()
          mock_cursor.__enter__ = lambda s: s
          mock_cursor.__exit__ = MagicMock(return_value=False)
          mock_cursor.fetchall.return_value = rows
          mock_conn.cursor.return_value = mock_cursor
          return lambda: mock_conn

      def test_returns_list(self):
          from proactive.collectors.agent_config_collector import collect
          import tools.postgres_tool as pt
          pt.set_connection_factory(self._make_pg_factory([]))
          result = collect()
          assert isinstance(result, list)

      def test_detects_unacceptable_risk_model(self):
          from proactive.collectors.agent_config_collector import collect
          import tools.postgres_tool as pt
          row = {
              "model_id": "m1", "name": "DangerBot",
              "risk_tier": "unacceptable", "status": "approved",
              "approved_by": None, "tenant_id": "t1",
          }
          pt.set_connection_factory(self._make_pg_factory([row]))
          result = collect()
          assert len(result) >= 1
          assert result[0]["type"] == "unsafe_config"
          assert "model_id" in result[0]

      def test_each_result_has_required_fields(self):
          from proactive.collectors.agent_config_collector import collect
          import tools.postgres_tool as pt
          row = {
              "model_id": "m2", "name": "RiskyBot",
              "risk_tier": "high", "status": "registered",
              "approved_by": None, "tenant_id": "t1",
          }
          pt.set_connection_factory(self._make_pg_factory([row]))
          result = collect()
          for item in result:
              assert "type" in item
              assert item["type"] == "unsafe_config"
              assert "model_id" in item
              assert "issue" in item
              assert "risk_tier" in item

      def test_postgres_unavailable_returns_empty(self):
          from proactive.collectors.agent_config_collector import collect
          import tools.postgres_tool as pt
          pt.set_connection_factory(None)
          result = collect()
          assert result == []


  # ── runtime_collector ────────────────────────────────────────────────────────

  class TestRuntimeCollector:
      def test_returns_list(self):
          from proactive.collectors.runtime_collector import collect
          import tools.postgres_tool as pt
          mock_conn = MagicMock()
          mock_cursor = MagicMock()
          mock_cursor.__enter__ = lambda s: s
          mock_cursor.__exit__ = MagicMock(return_value=False)
          mock_cursor.fetchall.return_value = []
          mock_conn.cursor.return_value = mock_cursor
          pt.set_connection_factory(lambda: mock_conn)
          result = collect()
          assert isinstance(result, list)

      def test_detects_repeated_actor(self):
          from proactive.collectors.runtime_collector import collect
          import tools.postgres_tool as pt
          # Simulate actor "bad-user" appearing 10 times in audit log
          rows = [{"actor": "bad-user", "event_count": 10, "last_seen": "2026-01-01T00:00:00"}]
          mock_conn = MagicMock()
          mock_cursor = MagicMock()
          mock_cursor.__enter__ = lambda s: s
          mock_cursor.__exit__ = MagicMock(return_value=False)
          mock_cursor.fetchall.return_value = rows
          mock_conn.cursor.return_value = mock_cursor
          pt.set_connection_factory(lambda: mock_conn)
          result = collect()
          assert any(r["type"] == "anomalous_pattern" for r in result)

      def test_each_result_has_required_fields(self):
          from proactive.collectors.runtime_collector import collect
          import tools.postgres_tool as pt
          rows = [{"actor": "u1", "event_count": 8, "last_seen": "2026-01-01T00:00:00"}]
          mock_conn = MagicMock()
          mock_cursor = MagicMock()
          mock_cursor.__enter__ = lambda s: s
          mock_cursor.__exit__ = MagicMock(return_value=False)
          mock_cursor.fetchall.return_value = rows
          mock_conn.cursor.return_value = mock_cursor
          pt.set_connection_factory(lambda: mock_conn)
          result = collect()
          for item in result:
              assert "type" in item
              assert "pattern" in item

      def test_postgres_unavailable_returns_empty(self):
          from proactive.collectors.runtime_collector import collect
          import tools.postgres_tool as pt
          pt.set_connection_factory(None)
          result = collect()
          assert result == []
  ```

  Run: `python -m pytest tests/proactive/test_collectors.py -v`
  Expected: FAIL (modules don't exist)

- [ ] **Step 2: Create `proactive/collectors/__init__.py`** (empty)

- [ ] **Step 3: Implement `proactive/collectors/secrets_collector.py`**

  ```python
  """
  proactive/collectors/secrets_collector.py
  ──────────────────────────────────────────
  Scan Redis key names for patterns matching credentials and secrets.

  Strategy: scan all Redis key names (not values — never read values).
  Flag any key whose name matches a known-sensitive pattern.
  Read-only. Deterministic. Never calls LLM.
  """
  from __future__ import annotations

  import logging
  import re
  from typing import Any, Dict, List

  logger = logging.getLogger(__name__)

  # Key name patterns that suggest a secret is stored under this key
  _SECRET_PATTERNS = re.compile(
      r"(api[_\-]?key|token|secret|password|passwd|credential|private[_\-]?key"
      r"|auth[_\-]?key|bearer|sk-|access[_\-]?key|client[_\-]?secret"
      r"|db[_\-]?pass|database[_\-]?url|connection[_\-]?string)",
      re.IGNORECASE,
  )

  # PII / sensitive data patterns (used by collect_sensitive_data)
  _SENSITIVE_PATTERNS = re.compile(
      r"(ssn|social.security|credit.card|card[_\-]?number|cvv|iban"
      r"|dob|date.of.birth|passport|license[_\-]?number|phone[_\-]?number"
      r"|email[_\-]?list|pii|personal.data)",
      re.IGNORECASE,
  )


  def _get_client():
      """Return the module-level Redis client, or None if not initialised."""
      try:
          import tools.redis_tool as rt
          return rt._redis_client
      except Exception:
          return None


  def _scan_keys(pattern_re: re.Pattern, scan_glob: str = "*") -> List[Dict[str, Any]]:
      """
      Scan all Redis key names matching scan_glob and flag those whose names
      match pattern_re.  Never reads key values.
      """
      client = _get_client()
      if client is None:
          logger.debug("secrets_collector: Redis client not available — skipping")
          return []

      results: List[Dict[str, Any]] = []
      try:
          for raw_key in client.scan_iter(scan_glob, count=500):
              key_name = raw_key.decode() if isinstance(raw_key, bytes) else str(raw_key)
              if pattern_re.search(key_name):
                  results.append({
                      "type": "secret_exposure",
                      "key_name": key_name,
                      "location": "redis",
                      "pattern_matched": pattern_re.pattern[:60],
                  })
      except Exception as exc:
          logger.warning("secrets_collector: scan failed: %s", exc)

      return results


  def collect() -> List[Dict[str, Any]]:
      """
      Main collector: scan for exposed credentials / API key patterns.
      Called by scan_registry for the 'exposed_credentials' scan.
      """
      return _scan_keys(_SECRET_PATTERNS)


  def collect_sensitive_data() -> List[Dict[str, Any]]:
      """
      Broader collector: scan for PII / sensitive data under unexpected keys.
      Called by scan_registry for the 'sensitive_data_exposure' scan.
      """
      return _scan_keys(_SENSITIVE_PATTERNS)
  ```

- [ ] **Step 4: Implement `proactive/collectors/network_collector.py`**

  ```python
  """
  proactive/collectors/network_collector.py
  ──────────────────────────────────────────
  Probe known internal service ports to detect unexpected reachability.

  We maintain a whitelist of expected-reachable services and a list of
  ports that should NEVER be reachable from within the agent network.
  Read-only (socket connect only, no data sent). Deterministic.
  """
  from __future__ import annotations

  import logging
  import socket
  from typing import Any, Dict, List

  logger = logging.getLogger(__name__)

  # (host, port, expected_reachable, service_name)
  # expected_reachable=True  → flag if NOT reachable (service down)
  # expected_reachable=False → flag if IS reachable (rogue / misconfigured)
  _PROBE_TARGETS = [
      # Internal services — should be reachable within the Docker network
      ("agent-orchestrator", 8094, True,  "agent-orchestrator-service"),
      ("api",                8080, True,  "platform-api"),
      ("guard-model",        8200, True,  "guard-model-service"),
      ("opa",                8181, True,  "opa-policy-engine"),
      ("redis",              6379, True,  "redis-cache"),
      # Kafka broker — internal only
      ("kafka-broker",       9092, True,  "kafka-broker"),
      # These should NEVER be directly reachable from the agent container
      # (they are DB ports that should only be reachable via the API layer)
      ("spm-db",             5432, False, "postgres-spm-db"),
  ]

  _CONNECT_TIMEOUT = 1.0   # seconds — keep scans fast


  def _probe(host: str, port: int) -> bool:
      """Return True if the (host, port) is reachable, False otherwise."""
      try:
          with socket.create_connection((host, port), timeout=_CONNECT_TIMEOUT):
              return True
      except (ConnectionRefusedError, socket.timeout, OSError):
          return False


  def collect() -> List[Dict[str, Any]]:
      """
      Probe all known service endpoints and return a structured status list.
      Flags: unexpected reachability (should_be=False but reachable=True)
             and unexpected outages (should_be=True but reachable=False).
      """
      results: List[Dict[str, Any]] = []
      for host, port, expected, service_name in _PROBE_TARGETS:
          try:
              reachable = _probe(host, port)
              anomalous = reachable != expected
              results.append({
                  "type":             "port_status",
                  "host":             host,
                  "port":             port,
                  "service_name":     service_name,
                  "reachable":        reachable,
                  "expected_reachable": expected,
                  "anomalous":        anomalous,
              })
              if anomalous:
                  logger.warning(
                      "network_collector: anomaly host=%s port=%d reachable=%s expected=%s",
                      host, port, reachable, expected,
                  )
          except Exception as exc:
              logger.warning("network_collector: probe failed host=%s port=%d: %s", host, port, exc)

      return results
  ```

- [ ] **Step 5: Implement `proactive/collectors/agent_config_collector.py`**

  ```python
  """
  proactive/collectors/agent_config_collector.py
  ────────────────────────────────────────────────
  Query the model registry for dangerous or misconfigured AI agents.

  Detects:
    - Models with risk_tier='unacceptable' that are still active
    - Models with risk_tier='high' missing mandatory approved_by
    - Models in status='registered' that were never approved (no approved_at)

  Read-only. Uses the existing Postgres query helper. Deterministic.
  """
  from __future__ import annotations

  import json
  import logging
  from typing import Any, Dict, List

  logger = logging.getLogger(__name__)

  # Tiers that require mandatory human approval before deployment
  _APPROVAL_REQUIRED_TIERS = {"high", "unacceptable"}

  # Tiers that should never be in an active (approved/registered) state
  _FORBIDDEN_ACTIVE_TIERS = {"unacceptable"}

  # Active deployment statuses
  _ACTIVE_STATUSES = {"approved", "registered"}


  def collect() -> List[Dict[str, Any]]:
      """
      Query model registry and return a list of unsafe_config findings.
      Returns [] if Postgres is unavailable (non-fatal).
      """
      try:
          import tools.postgres_tool as pt
          if pt._connection_factory is None:
              logger.debug("agent_config_collector: Postgres not initialised — skipping")
              return []
      except Exception:
          return []

      from config import TENANT_ID
      results: List[Dict[str, Any]] = []

      try:
          raw = pt.query_model_registry(tenant_id=TENANT_ID, limit=200)
          models = json.loads(raw) if isinstance(raw, str) else raw
          if isinstance(models, dict) and "error" in models:
              logger.warning("agent_config_collector: registry query error: %s", models["error"])
              return []
      except Exception as exc:
          logger.warning("agent_config_collector: query failed: %s", exc)
          return []

      for model in models:
          model_id    = str(model.get("model_id", ""))
          name        = model.get("name", "unknown")
          risk_tier   = (model.get("risk_tier") or "").lower()
          status      = (model.get("status") or "").lower()
          approved_by = model.get("approved_by")
          approved_at = model.get("approved_at")

          # Rule 1: unacceptable-risk model still active
          if risk_tier in _FORBIDDEN_ACTIVE_TIERS and status in _ACTIVE_STATUSES:
              results.append({
                  "type":      "unsafe_config",
                  "model_id":  model_id,
                  "model_name": name,
                  "risk_tier": risk_tier,
                  "status":    status,
                  "issue":     (
                      f"Model '{name}' has risk_tier='{risk_tier}' but is still "
                      f"in status='{status}'. Unacceptable-risk models must be retired."
                  ),
              })

          # Rule 2: high/unacceptable tier without approval
          elif risk_tier in _APPROVAL_REQUIRED_TIERS and not approved_by:
              results.append({
                  "type":      "unsafe_config",
                  "model_id":  model_id,
                  "model_name": name,
                  "risk_tier": risk_tier,
                  "status":    status,
                  "issue":     (
                      f"Model '{name}' has risk_tier='{risk_tier}' but "
                      f"approved_by is empty — mandatory approval is missing."
                  ),
              })

          # Rule 3: registered (never approved) with no approved_at
          elif status == "registered" and approved_at is None and risk_tier not in ("minimal", "limited"):
              results.append({
                  "type":      "unsafe_config",
                  "model_id":  model_id,
                  "model_name": name,
                  "risk_tier": risk_tier,
                  "status":    status,
                  "issue":     (
                      f"Model '{name}' (risk_tier='{risk_tier}') is in 'registered' "
                      f"status with no approval record — review required."
                  ),
              })

      return results
  ```

- [ ] **Step 6: Implement `proactive/collectors/runtime_collector.py`**

  ```python
  """
  proactive/collectors/runtime_collector.py
  ──────────────────────────────────────────
  Detect anomalous runtime patterns by querying the audit log.

  Detects:
    - High-frequency events from the same actor in the last hour
    - Sessions with risk_score >= HIGH_RISK_THRESHOLD in the last hour

  Read-only. Uses existing Postgres query helper. Deterministic.
  """
  from __future__ import annotations

  import json
  import logging
  from typing import Any, Dict, List

  logger = logging.getLogger(__name__)

  # Actor events/hour threshold above which behaviour is flagged as anomalous
  _HIGH_FREQUENCY_THRESHOLD = 5

  # Risk score above which a session is worth flagging
  _HIGH_RISK_THRESHOLD = 0.7


  def collect() -> List[Dict[str, Any]]:
      """
      Scan audit log for anomalous actor frequency patterns.
      Returns [] if Postgres is unavailable (non-fatal).
      """
      try:
          import tools.postgres_tool as pt
          if pt._connection_factory is None:
              logger.debug("runtime_collector: Postgres not initialised — skipping")
              return []
      except Exception:
          return []

      from config import TENANT_ID
      results: List[Dict[str, Any]] = []

      # ── High-frequency actor detection ───────────────────────────────────────
      try:
          conn = pt._get_conn()
          try:
              import psycopg2.extras
              with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                  cur.execute(
                      """
                      SELECT
                          actor,
                          COUNT(*) AS event_count,
                          MAX(timestamp)::text AS last_seen
                      FROM audit_export
                      WHERE tenant_id = %s
                        AND timestamp >= NOW() - INTERVAL '1 hour'
                        AND actor IS NOT NULL
                        AND actor != ''
                      GROUP BY actor
                      HAVING COUNT(*) >= %s
                      ORDER BY event_count DESC
                      LIMIT 20
                      """,
                      (TENANT_ID, _HIGH_FREQUENCY_THRESHOLD),
                  )
                  rows = [dict(r) for r in cur.fetchall()]
          finally:
              conn.close()

          for row in rows:
              results.append({
                  "type":        "anomalous_pattern",
                  "pattern":     "high_frequency_actor",
                  "actor":       row.get("actor"),
                  "event_count": row.get("event_count"),
                  "last_seen":   str(row.get("last_seen", "")),
                  "threshold":   _HIGH_FREQUENCY_THRESHOLD,
                  "description": (
                      f"Actor '{row.get('actor')}' generated "
                      f"{row.get('event_count')} events in the last hour "
                      f"(threshold: {_HIGH_FREQUENCY_THRESHOLD})."
                  ),
              })

      except Exception as exc:
          logger.warning("runtime_collector: actor frequency query failed: %s", exc)

      return results
  ```

- [ ] **Step 7: Run collector tests**

  Run: `python -m pytest tests/proactive/test_collectors.py -v`
  Expected: all pass

  > Note: `test_detects_repeated_actor` patches `pt.set_connection_factory` which uses psycopg2's `RealDictCursor` via `_query()`. The runtime collector uses a raw connection directly, so mock the connection factory to return a mock connection + mock cursor returning the row dict. If the test uses `cursor(cursor_factory=...)` it needs the mock to handle keyword args. Adjust mock setup:
  > ```python
  > mock_conn.cursor.return_value.__enter__ = lambda s: mock_cursor
  > ```

- [ ] **Step 8: Commit**
  ```bash
  git add services/threat-hunting-agent/proactive/collectors/ \
          services/threat-hunting-agent/tests/proactive/test_collectors.py
  git commit -m "feat(proactive): implement all four collectors (secrets, network, config, runtime)"
  ```

---

## Task 5: Implement scan runner + event conversion

**Files:**
- Create: `services/threat-hunting-agent/proactive/scan_runner.py`
- Test: `services/threat-hunting-agent/tests/proactive/test_scan_runner.py`

The scan runner ties together: registry → collector → event conversion → `hunt_agent` → source stamping → `persist_fn`.

- [ ] **Step 1: Write failing tests**

  Create `tests/proactive/test_scan_runner.py`:
  ```python
  """
  Tests for proactive/scan_runner.py
  """
  from __future__ import annotations

  from unittest.mock import MagicMock, patch
  import pytest

  from proactive.scan_runner import convert_to_events, run_scan, run_all_scans
  from proactive.scan_registry import SCAN_NAMES


  # ── convert_to_events ────────────────────────────────────────────────────────

  class TestConvertToEvents:
      def test_returns_list(self):
          data = [{"type": "secret_exposure", "key_name": "api_key:prod"}]
          events = convert_to_events("exposed_credentials", data)
          assert isinstance(events, list)
          assert len(events) == 1

      def test_event_shape(self):
          data = [{"type": "secret_exposure", "key_name": "token:abc"}]
          events = convert_to_events("exposed_credentials", data)
          e = events[0]
          assert e["event_type"] == "proactive_scan"
          assert e["scan_type"] == "exposed_credentials"
          assert e["source"] == "proactive_scan"
          assert e["is_proactive"] is True
          assert "timestamp" in e
          assert "tenant_id" in e
          assert "data" in e

      def test_empty_data_returns_empty(self):
          events = convert_to_events("unused_open_ports", [])
          assert events == []

      def test_topic_tag(self):
          data = [{"type": "port_status", "port": 9999, "reachable": True}]
          events = convert_to_events("unused_open_ports", data)
          assert events[0]["_topic"] == "cpm.t1.proactive_scan"


  # ── run_scan ─────────────────────────────────────────────────────────────────

  class TestRunScan:
      def _make_deps(self, collector_data, finding_title="Test Finding"):
          hunt_called = []
          persisted = []

          def hunt_agent(tenant_id, events):
              hunt_called.append((tenant_id, events))
              return {
                  "finding_id": "f1",
                  "title": finding_title,
                  "severity": "medium",
                  "should_open_case": False,
                  "source": "threat_hunt",  # agent returns this; runner should override
              }

          def persist_fn(tenant_id, finding):
              persisted.append((tenant_id, finding))

          return hunt_agent, persist_fn, hunt_called, persisted

      def test_run_scan_calls_hunt_agent(self):
          hunt_agent, persist_fn, hunt_called, _ = self._make_deps(
              [{"type": "secret_exposure"}])
          mock_collector = MagicMock(return_value=[{"type": "secret_exposure", "key_name": "k"}])
          with patch("proactive.scan_registry.SCAN_REGISTRY", {
              "exposed_credentials": MagicMock(collector=mock_collector),
          }):
              run_scan("exposed_credentials", hunt_agent, persist_fn)
          assert len(hunt_called) == 1
          assert hunt_called[0][0] == "t1"

      def test_run_scan_stamps_source(self):
          hunt_agent, persist_fn, _, persisted = self._make_deps([])
          mock_collector = MagicMock(return_value=[{"type": "secret_exposure"}])
          with patch("proactive.scan_registry.SCAN_REGISTRY", {
              "exposed_credentials": MagicMock(collector=mock_collector),
          }):
              run_scan("exposed_credentials", hunt_agent, persist_fn)
          assert len(persisted) == 1
          assert persisted[0][1]["source"] == "proactive_scan"
          assert persisted[0][1]["is_proactive"] is True

      def test_run_scan_skips_persist_for_fallback(self):
          hunt_agent, persist_fn, _, persisted = self._make_deps(
              [], finding_title="Hunt completed — no finding produced")
          mock_collector = MagicMock(return_value=[{"type": "secret_exposure"}])
          with patch("proactive.scan_registry.SCAN_REGISTRY", {
              "exposed_credentials": MagicMock(collector=mock_collector),
          }):
              run_scan("exposed_credentials", hunt_agent, persist_fn)
          assert persisted == []

      def test_run_scan_empty_collector_skips_hunt(self):
          hunt_called = []
          hunt_agent = lambda t, e: hunt_called.append(e) or {}
          mock_collector = MagicMock(return_value=[])
          with patch("proactive.scan_registry.SCAN_REGISTRY", {
              "unused_open_ports": MagicMock(collector=mock_collector),
          }):
              run_scan("unused_open_ports", hunt_agent, lambda t, f: None)
          assert hunt_called == []

      def test_run_scan_collector_exception_does_not_crash(self):
          def bad_collector():
              raise RuntimeError("collector exploded")
          with patch("proactive.scan_registry.SCAN_REGISTRY", {
              "exposed_credentials": MagicMock(collector=bad_collector),
          }):
              # Should not raise
              run_scan("exposed_credentials", lambda t, e: {}, lambda t, f: None)


  # ── run_all_scans ────────────────────────────────────────────────────────────

  class TestRunAllScans:
      def test_run_all_scans_calls_each_scan(self):
          called_scans = []
          def fake_run_scan(scan_type, hunt_agent, persist_fn):
              called_scans.append(scan_type)

          with patch("proactive.scan_runner.run_scan", side_effect=fake_run_scan):
              run_all_scans(hunt_agent=MagicMock(), persist_fn=MagicMock())

          assert set(called_scans) == set(SCAN_NAMES)
  ```

  Run: `python -m pytest tests/proactive/test_scan_runner.py -v`
  Expected: FAIL

- [ ] **Step 2: Implement `proactive/scan_runner.py`**

  ```python
  """
  proactive/scan_runner.py
  ─────────────────────────
  Scan runner: collects data, converts to events, calls hunt agent, persists findings.

  Public API:
    run_scan(scan_type, hunt_agent, persist_fn)
    run_all_scans(hunt_agent, persist_fn)
    convert_to_events(scan_type, data) → List[dict]
  """
  from __future__ import annotations

  import logging
  from datetime import datetime, timezone
  from typing import Any, Callable, Dict, List, Optional

  from config import TENANT_ID

  logger = logging.getLogger(__name__)

  _FALLBACK_TITLE = "Hunt completed — no finding produced"


  def convert_to_events(
      scan_type: str,
      data: List[Dict[str, Any]],
  ) -> List[Dict[str, Any]]:
      """
      Convert collector output into agent-compatible event dicts.

      Each item in `data` becomes one event.  Common proactive metadata
      (_topic, event_type, scan_type, source, is_proactive) is attached to all.
      Empty data → empty list (no events to hunt on).
      """
      if not data:
          return []

      now = datetime.now(timezone.utc).isoformat()
      events = []
      for item in data:
          event = {
              "_topic":       f"cpm.{TENANT_ID}.proactive_scan",
              "event_type":   "proactive_scan",
              "scan_type":    scan_type,
              "source":       "proactive_scan",
              "is_proactive": True,
              "timestamp":    now,
              "tenant_id":    TENANT_ID,
              "data":         item,
              # Flatten key fields for scorer.py (risk / verdict)
              "guard_verdict": "flag" if item.get("anomalous") else "allow",
              "guard_score":   0.6 if item.get("anomalous") else 0.0,
          }
          events.append(event)

      return events


  def run_scan(
      scan_type: str,
      hunt_agent: Callable[[str, List[Dict[str, Any]]], dict],
      persist_fn: Optional[Callable[[str, dict], None]],
  ) -> None:
      """
      Run one proactive scan end-to-end:
        1. Call the collector (deterministic, no LLM)
        2. Convert results to event dicts
        3. If events: call hunt_agent (LLM analysis)
        4. Stamp source = "proactive_scan" + is_proactive = True
        5. Persist via persist_fn (unless fallback / no-op finding)
      """
      from proactive.scan_registry import SCAN_REGISTRY

      defn = SCAN_REGISTRY.get(scan_type)
      if defn is None:
          logger.warning("run_scan: unknown scan_type=%r — skipping", scan_type)
          return

      # ── 1. Collect ───────────────────────────────────────────────────────────
      try:
          data = defn.collector()
      except Exception as exc:
          logger.exception("run_scan: collector failed scan=%s: %s", scan_type, exc)
          return

      logger.debug("run_scan: scan=%s collector_items=%d", scan_type, len(data))

      # ── 2. Convert to events ─────────────────────────────────────────────────
      events = convert_to_events(scan_type, data)
      if not events:
          logger.debug("run_scan: scan=%s produced no events — skipping hunt", scan_type)
          return

      # ── 3. Hunt ──────────────────────────────────────────────────────────────
      try:
          finding = hunt_agent(TENANT_ID, events)
      except Exception as exc:
          logger.exception("run_scan: hunt_agent failed scan=%s: %s", scan_type, exc)
          return

      if not isinstance(finding, dict):
          logger.warning("run_scan: hunt_agent returned non-dict scan=%s: %s", scan_type, type(finding))
          return

      # ── 4. Skip fallback placeholder ─────────────────────────────────────────
      if finding.get("title", "") == _FALLBACK_TITLE:
          logger.debug("run_scan: fallback finding scan=%s — not persisting", scan_type)
          return

      # ── 5. Stamp proactive provenance (override agent's default source) ───────
      finding["source"]       = "proactive_scan"
      finding["is_proactive"] = True

      logger.info(
          "run_scan: scan=%s title=%r severity=%s should_open_case=%s",
          scan_type,
          finding.get("title"),
          finding.get("severity"),
          finding.get("should_open_case"),
      )

      # ── 6. Persist ───────────────────────────────────────────────────────────
      if persist_fn is not None:
          try:
              persist_fn(TENANT_ID, finding)
          except Exception as exc:
              logger.exception("run_scan: persist_fn failed scan=%s: %s", scan_type, exc)


  def run_all_scans(
      hunt_agent: Callable[[str, List[Dict[str, Any]]], dict],
      persist_fn: Optional[Callable[[str, dict], None]],
  ) -> None:
      """
      Iterate the full SCAN_REGISTRY and run every scan.
      Individual scan failures are caught and logged; never propagates.
      """
      from proactive.scan_registry import SCAN_NAMES
      logger.info("run_all_scans: starting cycle scan_count=%d", len(SCAN_NAMES))
      for scan_type in SCAN_NAMES:
          try:
              run_scan(scan_type, hunt_agent, persist_fn)
          except Exception as exc:
              logger.exception("run_all_scans: unhandled error scan=%s: %s", scan_type, exc)
      logger.info("run_all_scans: cycle complete")
  ```

- [ ] **Step 3: Run scan runner tests**

  Run: `python -m pytest tests/proactive/test_scan_runner.py -v`
  Expected: all pass

- [ ] **Step 4: Commit**
  ```bash
  git add services/threat-hunting-agent/proactive/scan_runner.py \
          services/threat-hunting-agent/tests/proactive/test_scan_runner.py
  git commit -m "feat(proactive): scan runner + event conversion layer"
  ```

---

## Task 6: Implement the ProactiveScheduler

**Files:**
- Create: `services/threat-hunting-agent/proactive/scheduler.py`
- Test: `services/threat-hunting-agent/tests/proactive/test_scheduler.py`

- [ ] **Step 1: Write failing tests**

  Create `tests/proactive/test_scheduler.py`:
  ```python
  """
  Tests for proactive/scheduler.py
  """
  from __future__ import annotations

  import threading
  import time
  from unittest.mock import MagicMock, patch

  import pytest

  from proactive.scheduler import ProactiveScheduler


  class TestProactiveScheduler:
      def _make_scheduler(self, interval=60, **kwargs):
          return ProactiveScheduler(
              hunt_agent=MagicMock(return_value={"title": "T", "severity": "low"}),
              persist_fn=MagicMock(),
              scan_interval_sec=interval,
              **kwargs,
          )

      def test_start_sets_timer(self):
          s = self._make_scheduler(interval=9999)
          s.start()
          assert s._timer is not None
          s.stop()

      def test_stop_sets_event(self):
          s = self._make_scheduler(interval=9999)
          s.start()
          s.stop()
          assert s._stop_event.is_set()

      def test_stop_cancels_timer(self):
          s = self._make_scheduler(interval=9999)
          s.start()
          s.stop()
          # Timer should be cancelled — daemon=True so process exits cleanly
          assert s._timer is not None  # timer was created

      def test_run_all_scans_called_on_fire(self):
          fired = []
          s = self._make_scheduler(interval=9999)
          s.start()
          with patch("proactive.scheduler.run_all_scans", side_effect=lambda **kw: fired.append(1)):
              s._stop_event.set()   # prevent re-arm
              s._fire()
          assert len(fired) == 1
          s.stop()

      def test_fire_exception_does_not_crash(self):
          s = self._make_scheduler(interval=9999)
          s.start()
          with patch("proactive.scheduler.run_all_scans", side_effect=RuntimeError("boom")):
              s._stop_event.set()
              s._fire()   # should not raise
          s.stop()

      def test_stop_before_start_does_not_crash(self):
          s = self._make_scheduler(interval=9999)
          s.stop()  # should not raise

      def test_double_stop_does_not_crash(self):
          s = self._make_scheduler(interval=9999)
          s.start()
          s.stop()
          s.stop()  # should not raise

      def test_interval_stored(self):
          s = self._make_scheduler(interval=123)
          assert s._scan_interval_sec == 123
  ```

  Run: `python -m pytest tests/proactive/test_scheduler.py -v`
  Expected: FAIL

- [ ] **Step 2: Implement `proactive/scheduler.py`**

  ```python
  """
  proactive/scheduler.py
  ───────────────────────
  Scheduler for the proactive threat-hunting scan loop.

  Uses threading.Timer so the scan runs in a daemon thread without
  blocking the FastAPI event loop.  A stop_event prevents re-arming
  after shutdown.

  Interface:
    start() — begin the periodic scan loop
    stop()  — cancel the pending timer and clean up
  """
  from __future__ import annotations

  import logging
  import threading
  from typing import Any, Callable, Dict, List, Optional

  from proactive.scan_runner import run_all_scans

  logger = logging.getLogger(__name__)


  class ProactiveScheduler:
      """
      Fires run_all_scans() every scan_interval_sec seconds.

      Args:
          hunt_agent:        Callable(tenant_id, events) → dict
          persist_fn:        Callable(tenant_id, finding_dict) → None
          scan_interval_sec: Seconds between full scan cycles (default 300).
      """

      def __init__(
          self,
          hunt_agent: Callable[[str, List[Dict[str, Any]]], dict],
          persist_fn: Optional[Callable[[str, dict], None]],
          scan_interval_sec: int = 300,
      ) -> None:
          self._hunt_agent        = hunt_agent
          self._persist_fn        = persist_fn
          self._scan_interval_sec = scan_interval_sec

          self._stop_event = threading.Event()
          self._timer: Optional[threading.Timer] = None

      # ── Lifecycle ────────────────────────────────────────────────────────

      def start(self) -> None:
          """Arm the first timer. Scans begin after one full interval."""
          logger.info(
              "ProactiveScheduler starting: interval=%ds scan_count=%d",
              self._scan_interval_sec,
              5,  # len(SCAN_NAMES) — avoid import at startup
          )
          self._schedule()

      def stop(self) -> None:
          """Cancel the pending timer. No-op if not started or already stopped."""
          logger.info("ProactiveScheduler stopping")
          self._stop_event.set()
          if self._timer is not None:
              self._timer.cancel()
          logger.info("ProactiveScheduler stopped")

      # ── Internal ─────────────────────────────────────────────────────────

      def _schedule(self) -> None:
          if self._stop_event.is_set():
              return
          self._timer = threading.Timer(self._scan_interval_sec, self._fire)
          self._timer.daemon = True
          self._timer.start()

      def _fire(self) -> None:
          """Run all scans, then re-arm (unless stopped)."""
          try:
              run_all_scans(
                  hunt_agent=self._hunt_agent,
                  persist_fn=self._persist_fn,
              )
          except Exception as exc:
              logger.exception("ProactiveScheduler: unhandled error in scan cycle: %s", exc)
          finally:
              self._schedule()
  ```

- [ ] **Step 3: Run scheduler tests**

  Run: `python -m pytest tests/proactive/test_scheduler.py -v`
  Expected: all pass

- [ ] **Step 4: Commit**
  ```bash
  git add services/threat-hunting-agent/proactive/scheduler.py \
          services/threat-hunting-agent/tests/proactive/test_scheduler.py
  git commit -m "feat(proactive): ProactiveScheduler with threading.Timer loop"
  ```

---

## Task 7: Wire ProactiveScheduler into `app.py` lifespan

**Files:**
- Modify: `services/threat-hunting-agent/app.py`

- [ ] **Step 1: Add import**

  After existing imports in `app.py`, add:
  ```python
  from proactive.scheduler import ProactiveScheduler
  ```

- [ ] **Step 2: Instantiate and start scheduler in lifespan**

  After the existing `consumer.start()` block (around line 155), add:
  ```python
  # -- Proactive scanner -------------------------------------------------------
  # Runs deterministic security scans every proactive_scan_interval_sec (default 300s).
  # Uses the same hunt_agent and persist_fn callbacks as the Kafka consumer.
  proactive_scheduler = ProactiveScheduler(
      hunt_agent=_hunt,
      persist_fn=_persist,
      scan_interval_sec=settings.proactive_scan_interval_sec,
  )
  proactive_scheduler.start()
  app.state.proactive_scheduler = proactive_scheduler
  logger.info(
      "ProactiveScheduler started: interval=%ds",
      settings.proactive_scan_interval_sec,
  )
  ```

- [ ] **Step 3: Stop scheduler in teardown**

  In the teardown section, after `poller.stop()`:
  ```python
  proactive_scheduler.stop()
  ```

- [ ] **Step 4: Verify app.py starts cleanly (syntax check)**

  Run: `python -c "import app; print('OK')"` from the service directory.
  Expected: OK (LangChain not available in test env — the import error is expected and pre-existing)

  Actually run: `python -m py_compile app.py && echo OK`
  Expected: OK

- [ ] **Step 5: Commit**
  ```bash
  git add services/threat-hunting-agent/app.py
  git commit -m "feat(proactive): wire ProactiveScheduler into app lifespan"
  ```

---

## Task 8: Full test suite validation

- [ ] **Step 1: Run all threat-hunting-agent tests that don't require LangChain**

  Run:
  ```bash
  cd services/threat-hunting-agent
  python -m pytest tests/test_kafka_consumer.py \
                   tests/proactive/ \
                   tests/test_findings_service.py \
                   -v --tb=short
  ```
  Expected: all pass

- [ ] **Step 2: Run full orchestrator test suite**

  Run:
  ```bash
  cd services/agent-orchestrator-service
  python -m pytest -x -q
  ```
  Expected: ≥287 pass (plus new test_create_finding_stores_is_proactive)

- [ ] **Step 3: Final commit + rebuild instructions**

  ```bash
  git add -A
  git commit -m "feat: proactive threat hunting layer — scheduler, registry, collectors, tests"
  ```

  Then rebuild:
  ```bash
  docker compose build threat-hunting-agent agent-orchestrator
  docker compose up -d threat-hunting-agent agent-orchestrator
  ```

---

## Example Proactive Finding Output

When the agent processes a `proactive_scan` event batch and identifies a threat, the persisted finding will look like:

```json
{
  "id": "f7a3c2d1-...",
  "batch_hash": "sha256:...",
  "title": "Unacceptable-Risk AI Model Active in Production",
  "severity": "high",
  "status": "open",
  "source": "proactive_scan",
  "is_proactive": true,
  "tenant_id": "t1",
  "asset": "Threat Hunting AI Agent",
  "hypothesis": "Model 'DangerBot' (risk_tier=unacceptable) is in approved status with no human approval record. This violates the AI governance policy and poses unmitigated risk.",
  "evidence": [
    "model_id=m1 name=DangerBot risk_tier=unacceptable status=approved approved_by=null",
    "overprivileged_tools scan detected 1 policy violation(s)"
  ],
  "triggered_policies": ["ai_governance.unacceptable_risk_prohibition"],
  "recommended_actions": ["quarantine_agent", "escalate"],
  "should_open_case": true,
  "confidence": 0.8,
  "risk_score": 0.75,
  "created_at": "2026-04-12T14:30:00.000Z"
}
```
