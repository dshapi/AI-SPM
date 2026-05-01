"""
platform_shared/redis.py
────────────────────────
Single source of truth for building Redis clients across all AISPM
services. Handles two deployment modes from the same code:

1. Sentinel-aware (HA prod / dev-multinode): queries Redis Sentinel for
   the current master each connection. Survives master failover
   transparently — application code sees no error during a standby
   promotion.

2. Direct (single-broker / legacy): straight TCP to REDIS_HOST:REDIS_PORT.
   Same connection shape we had before this helper existed.

Mode is decided by env: if REDIS_SENTINEL_HOSTS is set we use Sentinel,
otherwise we use direct. Per-call ``decode_responses`` matches the prior
behavior where some callers (e.g. threat-hunting-agent) want bytes.

Replaces the copy-pasted ``_get_redis()`` functions that used to live in
every service. To migrate a service: import ``get_redis_client`` and
have its local ``_get_redis()`` (kept for backward compat / lazy init)
return the result.

Env vars consumed:
  REDIS_SENTINEL_HOSTS   "host1:26379,host2:26379,host3:26379"
                         comma-separated list of Sentinel endpoints.
                         When set, Sentinel mode is enabled.
  REDIS_SENTINEL_MASTER  Master name registered with Sentinel.
                         Default "mymaster" (Bitnami chart default).
  REDIS_HOST             Direct mode host. Default "redis-master".
  REDIS_PORT             Direct mode port. Default 6379.
  REDIS_PASSWORD         Auth password. Used in both modes if set.
  REDIS_SOCKET_TIMEOUT_S Per-call socket timeout in seconds. Default 5.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import redis
from redis.sentinel import Sentinel

log = logging.getLogger(__name__)

_DEFAULT_SENTINEL_PORT = 26379
_DEFAULT_MASTER_NAME   = "mymaster"
_DEFAULT_DIRECT_HOST   = "redis-master"
_DEFAULT_DIRECT_PORT   = 6379


def _parse_sentinel_hosts(raw: str) -> list[tuple[str, int]]:
    """Parse REDIS_SENTINEL_HOSTS env var into list of (host, port).

    Tolerates trailing commas, whitespace, and entries without an
    explicit port (defaults to 26379). Returns empty list when input
    is empty / invalid — caller treats that as "fall back to direct".
    """
    out: list[tuple[str, int]] = []
    for item in (raw or "").split(","):
        item = item.strip()
        if not item:
            continue
        if ":" in item:
            host, port_str = item.rsplit(":", 1)
            try:
                port = int(port_str)
            except ValueError:
                port = _DEFAULT_SENTINEL_PORT
        else:
            host, port = item, _DEFAULT_SENTINEL_PORT
        out.append((host, port))
    return out


def get_redis_client(
    *,
    decode_responses: bool = True,
    socket_timeout: Optional[float] = None,
) -> redis.Redis:
    """Return a Redis client appropriate for the current deployment.

    The client surface (``set``, ``get``, ``incr``, ``zadd``, etc.) is
    identical in both modes — callers do not need to know whether
    Sentinel is in use. Sentinel master discovery happens lazily inside
    the client; the first command after construction triggers a
    GET-MASTER-ADDR-BY-NAME query.

    Parameters
    ----------
    decode_responses
        Pass-through to redis-py. True for text-mode (most callers).
        False for byte-mode (threat-hunting-agent reads pickle blobs).
    socket_timeout
        Per-command timeout. Defaults to env REDIS_SOCKET_TIMEOUT_S
        or 5s. Sentinel queries use 2s independently (kept tighter so
        a slow sentinel doesn't add unbounded latency to every call).
    """
    if socket_timeout is None:
        socket_timeout = float(os.environ.get("REDIS_SOCKET_TIMEOUT_S", "5"))

    password = os.environ.get("REDIS_PASSWORD", "") or None
    sentinel_hosts = _parse_sentinel_hosts(os.environ.get("REDIS_SENTINEL_HOSTS", ""))

    if sentinel_hosts:
        master_name = os.environ.get("REDIS_SENTINEL_MASTER", _DEFAULT_MASTER_NAME)
        sentinel = Sentinel(
            sentinel_hosts,
            socket_timeout=2.0,
            password=password,
        )
        log.debug(
            "Redis client: sentinel mode (hosts=%d, master=%s)",
            len(sentinel_hosts), master_name,
        )
        return sentinel.master_for(
            master_name,
            socket_timeout=socket_timeout,
            decode_responses=decode_responses,
            password=password,
        )

    # Direct mode — single-node dev or any cluster without Sentinel exported.
    host = os.environ.get("REDIS_HOST", _DEFAULT_DIRECT_HOST)
    port = int(os.environ.get("REDIS_PORT", str(_DEFAULT_DIRECT_PORT)))
    log.debug("Redis client: direct mode (%s:%d)", host, port)
    return redis.Redis(
        host=host,
        port=port,
        password=password,
        decode_responses=decode_responses,
        socket_timeout=socket_timeout,
    )
