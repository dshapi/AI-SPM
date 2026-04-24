"""
platform_shared.integration_config — direct-DB config hydration.

The DB is the source of truth for managed configuration (Anthropic API
key, Tavily key, Ollama endpoint, Garak/bootstrap secrets, etc).  This
module is called at process startup by every consuming service to pull
those values out of spm-db and into `os.environ`, so the rest of the
service can keep using `os.getenv("ANTHROPIC_API_KEY")` exactly as
before without knowing or caring that the value came from Postgres.

Design decisions
────────────────
* Synchronous psycopg2 — runs once at boot, before any async event loop
  starts, so sync code is simplest and avoids pulling asyncpg into
  services that don't otherwise need it.
* Fails-soft — if the DB is unreachable or the row is missing, we
  log a warning and leave the env var alone.  This keeps local dev with
  a plain `.env` working, and lets a service whose hydration fails fall
  through to whatever value (if any) the operator already exported.
* Non-destructive by default — existing env vars are NOT overwritten
  unless `overwrite=True`.  This preserves operator overrides and, during
  the migration window, lets the transitional `.env` values win over the
  empty DB on the very first boot (before the bootstrap endpoint has
  been called).
* No SQLAlchemy, no ORM imports — this module has to be importable from
  every container, some of which do not ship the `spm.db` package.

Wire-up
───────
At the top of each consuming service's entry point:

    from platform_shared.integration_config import hydrate_env_from_db
    hydrate_env_from_db()      # before any os.getenv("ANTHROPIC_API_KEY") calls

The managed env-var set is the list returned by `managed_env_keys()`;
any key not in that list is left untouched.
"""
from __future__ import annotations

import base64
import logging
import os
from typing import Dict, List, Optional, Tuple

log = logging.getLogger("platform_shared.integration_config")


# ─────────────────────────────────────────────────────────────────────────────
# Canonical env-var → DB mapping.
#
# MUST stay in sync with services/spm_api/integrations_seed_data.py's
# ENV_EXPORT_MAP.  Duplicated here (rather than imported) because this
# module must be importable from containers that do not ship spm_api.
#
#   (external_id, kind, key_in_db, env_var_name)
#   kind ∈ {"config", "credential"}
# ─────────────────────────────────────────────────────────────────────────────
ENV_EXPORT_MAP: List[Tuple[str, str, str, str]] = [
    ("int-003", "credential", "api_key",                   "ANTHROPIC_API_KEY"),
    ("int-003", "config",     "model",                     "ANTHROPIC_MODEL"),
    ("int-016", "credential", "api_key",                   "TAVILY_API_KEY"),
    ("int-017", "config",     "base_url",                  "GROQ_BASE_URL"),
    ("int-017", "config",     "model",                     "LLM_MODEL"),
    ("int-017", "config",     "guard_prompt_mode",         "GUARD_PROMPT_MODE"),
    ("int-017", "config",     "keep_alive",                "OLLAMA_KEEP_ALIVE"),
    ("int-018", "credential", "shared_secret",             "GARAK_INTERNAL_SECRET"),
    ("int-018", "credential", "internal_bootstrap_secret", "SPM_INTERNAL_BOOTSTRAP_SECRET"),
]


def managed_env_keys() -> List[str]:
    """The env-var names this module will populate (dedup, stable order)."""
    seen, out = set(), []
    for _ext, _kind, _key, name in ENV_EXPORT_MAP:
        if name not in seen:
            seen.add(name)
            out.append(name)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# DB connection URL resolution.
#
# Containers typically set SPM_DB_URL to a SQLAlchemy-style URL.  psycopg2
# doesn't understand the `+asyncpg` / `+psycopg2` scheme suffix, so we
# strip it.  If SPM_DB_URL isn't set we fall back to the usual pieces.
# ─────────────────────────────────────────────────────────────────────────────
def _resolve_db_url() -> Optional[str]:
    raw = (os.getenv("SPM_DB_URL") or "").strip()
    if raw:
        # "postgresql+asyncpg://..."  → "postgresql://..."
        # "postgresql+psycopg2://..." → "postgresql://..."
        if raw.startswith("postgresql+"):
            _, _, rest = raw.partition("+")
            _, _, after_plus = rest.partition("://")
            return "postgresql://" + after_plus
        return raw

    host = os.getenv("SPM_DB_HOST") or "spm-db"
    port = os.getenv("SPM_DB_PORT") or "5432"
    user = os.getenv("SPM_DB_USER") or "spm_rw"
    pw   = os.getenv("SPM_DB_PASSWORD") or ""
    name = os.getenv("SPM_DB_NAME") or "spm"
    if not pw:
        return None
    return f"postgresql://{user}:{pw}@{host}:{port}/{name}"


def _decode_secret(enc: Optional[str]) -> str:
    """Inverse of services.spm_api.integrations_routes._encode_secret."""
    if not enc:
        return ""
    try:
        return base64.b64decode(enc.encode("ascii")).decode("utf-8")
    except Exception:
        log.warning("integration_config: failed to base64-decode credential; "
                    "treating as empty")
        return ""


# ─────────────────────────────────────────────────────────────────────────────
# Main entrypoint
# ─────────────────────────────────────────────────────────────────────────────
def hydrate_env_from_db(
    overwrite: bool = False,
    timeout_s: float = 3.0,
) -> int:
    """Pull managed config from spm-db into `os.environ`.

    Returns the number of env vars successfully populated.  Never raises
    — callers can treat a return value of 0 as 'fell through to existing
    env vars or bootstrap .env'.

    Parameters
    ----------
    overwrite:
        If False (default) an env var already set in the process
        environment is left alone.  If True, DB values win.
    timeout_s:
        psycopg2 connect_timeout (seconds).  Kept short so a stuck DB
        doesn't block container startup forever.
    """
    url = _resolve_db_url()
    if not url:
        log.warning(
            "integration_config: SPM_DB_URL / SPM_DB_PASSWORD not set — "
            "skipping DB hydration, relying on existing os.environ.",
        )
        return 0

    try:
        import psycopg2  # local import so services without the driver
        import psycopg2.extras  # don't fail at import time
    except Exception as exc:  # pragma: no cover — driver missing
        log.warning("integration_config: psycopg2 not installed (%s); "
                    "skipping DB hydration.", exc)
        return 0

    # ── Open a short-lived RO connection ──
    try:
        conn = psycopg2.connect(url, connect_timeout=int(max(1, timeout_s)))
    except Exception as exc:
        log.warning("integration_config: could not connect to spm-db (%s); "
                    "skipping hydration.", exc)
        return 0

    try:
        conn.set_session(readonly=True, autocommit=True)
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            # Pull every integration that the ENV_EXPORT_MAP cares about,
            # plus all its credential rows, in two cheap queries.
            wanted_ext_ids = tuple(sorted({ext for (ext, _, _, _) in ENV_EXPORT_MAP}))
            cur.execute(
                """
                SELECT id, external_id, COALESCE(config, '{}'::jsonb) AS config
                FROM   integrations
                WHERE  external_id = ANY(%s)
                """,
                ([*wanted_ext_ids],),
            )
            rows = cur.fetchall()
            if not rows:
                log.warning(
                    "integration_config: spm-db reachable but no integrations "
                    "rows match %s — has POST /integrations/bootstrap run yet?",
                    wanted_ext_ids,
                )
                return 0

            by_ext_id: Dict[str, Dict] = {r["external_id"]: dict(r) for r in rows}

            # NOTE: integration_credentials.integration_id is typed `uuid`;
            # psycopg2 serializes a Python list of UUID strings as text[] by
            # default, so without the ::uuid[] cast Postgres raises
            # "operator does not exist: uuid = text".  The cast lets
            # Postgres parse the string literals as uuids on the server side.
            cur.execute(
                """
                SELECT integration_id, credential_type,
                       value_enc, is_configured
                FROM   integration_credentials
                WHERE  integration_id = ANY(%s::uuid[])
                """,
                ([str(r["id"]) for r in rows],),
            )
            creds_by_int: Dict = {}
            for c in cur.fetchall():
                creds_by_int.setdefault(c["integration_id"], {})[
                    c["credential_type"]
                ] = c

    finally:
        try:
            conn.close()
        except Exception:
            pass

    # ── Materialise each (ext_id, kind, key) → env value ──
    populated = 0
    for ext_id, kind, key, env_name in ENV_EXPORT_MAP:
        if (not overwrite) and os.environ.get(env_name, "").strip():
            continue

        integ = by_ext_id.get(ext_id)
        if integ is None:
            continue

        value: Optional[str] = None
        if kind == "config":
            cfg = integ.get("config") or {}
            v = cfg.get(key) if isinstance(cfg, dict) else None
            if v not in (None, ""):
                value = str(v)
        elif kind == "credential":
            cred = (creds_by_int.get(integ["id"]) or {}).get(key)
            if cred and cred.get("is_configured") and cred.get("value_enc"):
                value = _decode_secret(cred["value_enc"])

        if value:
            os.environ[env_name] = value
            populated += 1

    if populated == 0:
        log.warning(
            "integration_config: connected to spm-db but populated 0 env "
            "vars — bootstrap may not have run, or credentials are unconfigured.",
        )
    else:
        log.info("integration_config: hydrated %d env var(s) from spm-db "
                 "(%s)", populated,
                 ", ".join(sorted(k for k in managed_env_keys()
                                  if os.environ.get(k))))
    return populated


# Re-export so scripts can do a one-liner check.
__all__ = ["hydrate_env_from_db", "managed_env_keys", "ENV_EXPORT_MAP"]
