"""
OPA client — evaluates Rego policies via HTTP with fail-closed semantics.
Includes a simple in-memory TTL cache to reduce OPA round-trips.
"""
from __future__ import annotations
import time
import logging
import threading
from typing import Any, Dict, Optional
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from platform_shared.config import get_settings

log = logging.getLogger(__name__)

_DENY_RESPONSE = {"decision": "block", "reason": "OPA unavailable — fail closed", "action": "deny_execution"}
_DENY_TOOL = {"decision": "block", "reason": "OPA unavailable — fail closed", "action": "deny_tool_execution"}
_DENY_MEMORY = {"decision": "block", "reason": "OPA unavailable — fail closed"}


class OPAClient:
    """
    Thin HTTP client for OPA policy evaluation.

    Features:
    - Connection pooling via requests.Session
    - Retry with exponential backoff (3 retries, statuses 500/502/503)
    - In-memory result cache with TTL (default 5s)
    - Fail-closed: any OPA error returns a deny response
    - Circuit breaker: after 5 consecutive failures, short-circuit for 30s
    """

    _CACHE_TTL = 5.0          # seconds to cache identical policy results
    _CIRCUIT_THRESHOLD = 5    # consecutive failures before opening circuit
    _CIRCUIT_RESET_SEC = 30   # seconds to wait before retrying after circuit opens

    def __init__(self) -> None:
        self._url = get_settings().opa_url
        self._timeout = get_settings().opa_timeout
        self._session = self._build_session()
        self._cache: Dict[str, tuple[float, dict]] = {}
        self._cache_lock = threading.Lock()
        self._failure_count = 0
        self._circuit_open_at: Optional[float] = None

    @staticmethod
    def _build_session() -> requests.Session:
        session = requests.Session()
        retry = Retry(
            total=3,
            backoff_factor=0.3,
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=["POST"],
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=16)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    def _is_circuit_open(self) -> bool:
        if self._circuit_open_at is None:
            return False
        if time.monotonic() - self._circuit_open_at > self._CIRCUIT_RESET_SEC:
            self._circuit_open_at = None
            self._failure_count = 0
            log.info("OPA circuit breaker reset")
            return False
        return True

    def _record_failure(self) -> None:
        self._failure_count += 1
        if self._failure_count >= self._CIRCUIT_THRESHOLD and self._circuit_open_at is None:
            self._circuit_open_at = time.monotonic()
            log.error("OPA circuit breaker OPENED after %d consecutive failures", self._failure_count)

    def _record_success(self) -> None:
        self._failure_count = 0
        self._circuit_open_at = None

    def _cache_key(self, path: str, input_data: dict) -> str:
        import hashlib, json
        payload = json.dumps({"path": path, "input": input_data}, sort_keys=True, default=str)
        return hashlib.md5(payload.encode()).hexdigest()

    def _get_cached(self, key: str) -> Optional[dict]:
        with self._cache_lock:
            entry = self._cache.get(key)
            if entry and time.monotonic() - entry[0] < self._CACHE_TTL:
                return entry[1]
        return None

    def _set_cached(self, key: str, result: dict) -> None:
        with self._cache_lock:
            self._cache[key] = (time.monotonic(), result)

    def eval(self, path: str, input_data: dict) -> dict:
        """
        Evaluate an OPA policy at the given path with the given input.
        Returns the policy result dict.
        Fails closed on any error.
        """
        if self._is_circuit_open():
            log.warning("OPA circuit open — returning deny for path=%s", path)
            return _DENY_RESPONSE

        cache_key = self._cache_key(path, input_data)
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        try:
            resp = self._session.post(
                f"{self._url}{path}",
                json={"input": input_data},
                timeout=self._timeout,
            )
            resp.raise_for_status()
            result = resp.json().get("result", {})
            if not isinstance(result, dict):
                result = {}
            self._record_success()
            self._set_cached(cache_key, result)
            return result
        except requests.exceptions.Timeout:
            log.error("OPA timeout path=%s", path)
            self._record_failure()
            return _DENY_RESPONSE
        except requests.exceptions.ConnectionError:
            log.error("OPA connection error path=%s", path)
            self._record_failure()
            return _DENY_RESPONSE
        except Exception as e:
            log.error("OPA eval error path=%s error=%s", path, e)
            self._record_failure()
            return _DENY_RESPONSE

    def health_check(self) -> bool:
        """Returns True if OPA is reachable."""
        try:
            resp = self._session.get(f"{self._url}/health", timeout=2.0)
            return resp.status_code == 200
        except Exception:
            return False


# Module-level singleton
_opa_client: Optional[OPAClient] = None


def get_opa_client() -> OPAClient:
    global _opa_client
    if _opa_client is None:
        _opa_client = OPAClient()
    return _opa_client
