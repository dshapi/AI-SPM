# Live Credential Lookup — kill the env-restart cycle

**Status**: ready to review on `feature/live-credential-lookup`
**Date**: 2026-04-25 (built overnight while you slept)
**Author**: cowork
**Trigger**: "i dont like the fact that i meed to restart a srervice after config change"

## The problem

Today, every consuming service (`api`, `guard_model`, `agent-orchestrator`,
`garak`) calls `hydrate_env_from_db()` once at startup. The hydrator pulls
managed credentials out of `spm-db` into `os.environ`, then the service
reads them with `os.getenv("ANTHROPIC_API_KEY")`.

That works for the first boot. It breaks the moment an admin rotates a
credential through the UI — the new value lands in `integration_credentials`,
but every running container still has the old value frozen in its process
environment. The fix is to bounce the container, which is exactly the
operational footgun this branch removes.

## The fix

Replace process-environment reads with a **live lookup** that consults
Redis first (TTL ~30s) and falls back to a direct `spm-db` query on miss.
Successful DB reads populate the cache. Writes through
`POST /integrations/{id}/configure` invalidate the vendor's cache entries
on commit, so the next consumer read sees the new value within
milliseconds — no restart.

```
Before:                          After:
  startup → hydrate env            request → get_credential(vendor)
  request → os.getenv(NAME)                   ↓
                                            Redis cache (TTL=30s)
  rotation → os.getenv stale                  ↓ miss
  ⇒ docker restart needed                   spm-db direct query
                                              ↓
                                            cache + return

  rotation: configure POST → DB commit → invalidate_credential_cache(vendor)
            → next read pulls fresh value, no restart
```

## What changed

### New module: `platform_shared/credentials.py`

```python
get_credential(vendor, field='api_key', kind='credential', ttl=30, default=None)
get_credential_by_env(env_name, ttl=30, default=None)        # ENV_EXPORT_MAP shim
invalidate_credential_cache(vendor) -> int                    # SCAN-based wipe
reset_redis_client()                                          # tests/operators
```

Design choices worth knowing:

- **Fail-soft everywhere.** Redis down → fall through to DB. DB down →
  return `default` (which the caller wires to the env-var, preserving
  the old hydrator's behavior). A chat request never 500s because the
  cache blinked.
- **Direct psycopg2, no SQLAlchemy.** Same constraint as
  `integration_config.py` — this module has to import cleanly inside
  containers that don't ship `spm.db`.
- **Negative caching deliberately omitted.** If a credential is genuinely
  unconfigured, the caller has bigger problems than 1 extra DB query.

### Write-through invalidation: `services/spm_api/integrations_routes.py`

After `db.commit()` in `POST /integrations/{id}/configure`, the endpoint
calls `invalidate_credential_cache(row.external_id)`. Wrapped in
try/except — the worst case if invalidation fails is one TTL window
(~30s) of stale reads, not a 500.

### Consumer migrations

| Service | What now reads live |
|---|---|
| `services/api/app.py` | `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`, `TAVILY_API_KEY`, `GARAK_INTERNAL_SECRET`. Per-key SDK client cache (`_anthropic_clients` dict) so a rotated key spawns a fresh `anthropic.Anthropic` instead of reusing a client with stale auth headers. |
| `services/guard_model/app.py` | `GUARD_PROMPT_MODE`, `LLM_MODEL` (via `_live_prompt_mode()` / `_live_groq_model()`). Used in the LLM call path and `/health` payload. |
| `services/agent-orchestrator-service/main.py` | `LLM_MODEL` in both docker and anthropic provider branches. `LLM_API_KEY` left alone — it's operator-set, not in `ENV_EXPORT_MAP`. |
| `services/garak/main.py` | `GARAK_INTERNAL_SECRET` in `_make_generator()`. |

The boot-time `hydrate_env_from_db()` call is **kept** in every service —
it's now the fallback layer that `get_credential_by_env` returns when
both Redis and the DB miss, which preserves operator overrides and the
local-dev `.env` workflow.

### Tests: `tests/test_credentials_live.py`

11 tests covering cache HIT, MISS, rotation roundtrip, Redis-down,
DB-down, blank-not-cached, env precedence (DB beats env when present, env
wins on DB miss), unmanaged-var passthrough, multi-field invalidation,
and invalidation safety when Redis is down.

```
$ pytest tests/test_credentials_live.py -v
============================== 11 passed in 0.02s ==============================
```

Full repo suite still green: **357 passed** (the only red is
`test_alembic_migrations.py` which is missing the `alembic` CLI in this
sandbox — an environmental issue unrelated to this branch).

## Branch contents

```
$ git log --oneline main..feature/live-credential-lookup
ea14aea test(credentials): unit suite for live lookup, cache, and rotation
67cdd1b feat(services): migrate managed-credential reads to live get_credential_by_env
ee45335 feat(integrations): write-through cache invalidation on configure
392756c feat(credentials): add live get_credential() helper with Redis caching
```

```
$ git diff --stat main..feature/live-credential-lookup
 docs/plans/2026-04-25-live-credential-lookup.md       | <this file>
 platform_shared/credentials.py                        | 378 ++++++
 services/agent-orchestrator-service/main.py           |  10 +-
 services/api/app.py                                   |  64 +-
 services/garak/main.py                                |   7 +-
 services/guard_model/app.py                           |  44 +-
 services/spm_api/integrations_routes.py               |  22 +
 tests/test_credentials_live.py                        | 231 ++++
```

## How to verify it works

This is the smoke I'd run before merging. None of it requires rebuilding
images — every change is pure Python and the consuming services already
import `platform_shared.*` at runtime.

1. Bring up the stack on the branch:
   ```
   git worktree prune  # clean up the sandbox worktree from overnight
   git checkout feature/live-credential-lookup
   docker compose restart api guard-model agent-orchestrator garak spm-api
   ```
2. Confirm chat works with the current Anthropic key (baseline).
3. Through the Integrations page, rotate the Anthropic API key to a
   value you know is wrong (e.g. `sk-ant-WRONG`). Click Save.
4. Send a chat message **without restarting any container**. Expect a
   401 from Anthropic in the logs — proves the new key was picked up
   live.
5. Rotate back to the real key. Send another chat message. Expect
   success, again with no restart.

If step 4 doesn't show the wrong key being used, check
`docker compose logs spm-api | grep "credentials: invalidated"` — you
should see `cache entries for vendor=int-003` after the configure POST.

## Trade-offs and known gaps

- **30s worst-case TTL window** — if Redis is up but invalidation
  somehow fails (network blip mid-DEL), consumers serve the old value
  for up to 30s. We log a warning when this happens. If you want
  zero-window guarantees, drop TTL to 0 and treat Redis purely as a
  rotation pub/sub channel — straightforward future work.
- **Per-key SDK client leak in `services/api/app.py`** — the
  `_anthropic_clients` dict never evicts stale entries. This is
  intentional: each key creates one ~kB client that lives until the
  process ends. Solving it cleanly requires coordinating eviction
  across in-flight requests, which isn't worth the complexity.
- **Operator-set vars unchanged.** `LLM_API_KEY` (orchestrator),
  `GROQ_API_KEY` (guard), `LOG_LEVEL`, `ORCHESTRATOR_URL`, etc. are
  not in `ENV_EXPORT_MAP` so they continue to be plain `os.getenv`.
  That matches existing semantics — these are deployment-time concerns,
  not UI-rotated credentials.
- **Hydrator still runs at boot.** It's now the fallback layer for
  `get_credential_by_env`. We could eventually delete it, but doing so
  would break any caller that does a bare `os.getenv("ANTHROPIC_API_KEY")`
  in code we missed. Easier to leave it as defence in depth.

## What's NOT in this branch

- No container restart performed during this work — your live stack is
  untouched.
- No merge to `main`. Branch is `feature/live-credential-lookup`,
  ready for you to review.
- No changes to the UI — rotation works through the existing
  `POST /integrations/{id}/configure` endpoint.
- No new dependencies. `redis` and `psycopg2` are already in every
  consuming service's requirements.


---

## Amendment — fail-closed cache (post-incident)

### What prompted this

Real-world test on `feature/live-credential-lookup` ran into two
coupled failures on the same request:

1. Redis's `/data` bind-mount went stale on the host → BGSAVE
   repeatedly failed → Redis flipped into
   `stop-writes-on-bgsave-error`, so every rate-limit ZADD started
   raising MISCONF → 500 on `/chat` and `/chat/stream`.
2. While Redis was rejecting writes, the configure endpoint's
   `invalidate_credential_cache(vendor)` `DEL` silently failed
   (correctly — a cache blip shouldn't undo a committed save). When
   Redis came back, it served the *old* cached credential to
   services/api, which 401'd against Anthropic.

The spm-api Test button read the DB directly via SQLAlchemy and
worked, which is how we narrowed this down: the cache was lying to one
consumer while the DB held the truth.

### The fix

Move the cache from "trust until explicitly invalidated" to
"trust briefly, then re-verify cheaply." See `platform_shared/credentials.py`
for the implementation; the two-window model is:

  * **`FRESHNESS_S`** (default 5s) — trust the cache unconditionally.
    Hot path: one Redis GET, no DB hit.
  * **`FRESHNESS_S < age < TTL_S`** — run a cheap
    `SELECT updated_at` on the credential row (indexed PK lookup, no
    value transfer, no decryption). Match → extend both windows.
    Mismatch → refetch the full value. DB error → serve cached but
    DO NOT extend TTL, so a prolonged outage can't pin a stale
    credential forever.
  * **Past `TTL_S`** — Redis has expired the key; do a full lookup.

The writer's `invalidate_credential_cache` stays in place but is now
purely an optimisation. Correctness no longer depends on it ever
succeeding, which is what the Redis-MISCONF incident surfaced.

### Cost

Worst case one cheap version-check per credential per `freshness_s`
per consumer. `SELECT updated_at` on an indexed (integration_id,
credential_type) row is <1ms — negligible next to an Anthropic API
call.

### Belt-and-braces on Redis persistence

Same worktree: baked `--save ""` and `--stop-writes-on-bgsave-error no`
into the redis service command (see `docker-compose.yml`). Our use of
Redis is purely ephemeral (rate-limit counters + 30s credential
cache); there is nothing worth persisting through a restart, so RDB
is off and AOF is belt-and-braces for in-flight burst loss. This
forecloses the whole class of "disk hiccup cascades into 500s" that
started this.

### Tests

`tests/test_credentials_live.py` now exercises 16 cases. Net-new over
the baseline 11:

  - Fresh window served without any DB hit
  - Stale window, version match → cheap check only, TTL extended
  - Stale window, version drift → full refetch, recache
  - Stale window, DB down → serve cached, TTL NOT extended
  - `freshness_s=0` forces revalidation on every read
  - Legacy raw-string cache entries are dropped and migrated to JSON

Full suite: 362 passed (+5 from the 357 baseline).
