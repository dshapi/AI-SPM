# ADR 0001 — Garak probe-attempt parallelism

| Field            | Value                                   |
|------------------|-----------------------------------------|
| Status           | Proposed                                |
| Date             | 2026-04-21                              |
| Deciders         | Dany (platform), TBD                    |
| Garak version    | 0.14.1 (`services/garak/requirements.txt`) |
| Scope            | UI-exposed probes only (5 classes)      |
| Related          | task #17 (per-attempt correlation_id), task #8 (hard timeout), task #13 fix D (canonical-aware dedup) |

## Context

A simple 5-probe Garak run in the Simulation Lab regularly takes ~60–82 seconds wall-clock. The encoding probe (`encoding.InjectBase64`) hits the 60-second per-probe timeout and returns a synthetic `simulation.probe_error` finding instead of real results. The user-visible consequence is a red "0 blocked / 1 probes" row on the Coverage tab with no Timeline / Explainability content.

Root cause is two-layered:

1. **Each Garak probe runs `max_attempts=10` serially.** `InjectBase64` generates a Cartesian product of templates × payloads × encoders; each prompt round-trips through the full CPM pipeline (`/internal/probe` → lexical → guard → OPA → LLM → output-scan), typically ~7s. Ten serial attempts = ~70s, past the 60s budget.
2. **The `CPMPipelineGenerator` declares itself non-parallel.** `services/garak/main.py:222` sets `parallel_attempts = 1, max_workers = 1` on the generator and the garak compat shim forces the same defaults on any probe missing those attributes.

Two other degrees of freedom exist (documented but not decided here):

- The per-probe timeout is 60s on both sides (sidecar `PROBE_TIMEOUT_S` and api `probe_timeout_s`); bumping them is a trivial env change but only reduces timeout frequency, not wall-clock.
- The `max_attempts` default (`GarakConfig.max_attempts = 10`) could be lowered; this reduces signal per probe and is orthogonal to the parallelism question.

This ADR is strictly about whether individual probe **attempts** (prompts within one probe) can safely execute concurrently.

## Decision

**Add opt-in, per-probe parallel-attempt support, gated behind `GARAK_PARALLEL_ATTEMPTS` (default 1 — current serial behavior).**

Implementation surface area:

1. Add a `PARALLEL_SAFE_PROBES: set[str]` allowlist in `services/garak/main.py`, initially containing:
   - `dan.Dan_11_0`
   - `encoding.InjectBase64`
   - `malwaregen.TopLevel`
   - `grandma.Win10`
   - `_DataExfilProbe` (custom in-repo probe)
2. In `_run_probe_sync`, after instantiating the probe, if the resolved probe name is in the allowlist AND `GARAK_PARALLEL_ATTEMPTS > 1`:
   - Set `probe.parallel_attempts = N`
   - Set `probe.parallelisable_attempts = True`
   - Set `generator.parallel_attempts = N`, `generator.max_workers = N`, `generator.parallel_capable = True`
3. Keep serial execution as the fallback for any probe not in the allowlist.
4. Document the parallelism model garak uses (multiprocessing pool) and the known caveat about `CPMPipelineGenerator._meta` (below).

## Classification

All four external probes pre-compute `self.prompts` in `__init__` from static templates / payload lists — no feedback loop, no state mutation across attempts, no detector ordering dependency. The in-repo `_DataExfilProbe` iterates a 5-element static list. Full findings from the garak 0.14.1 source (agent-assisted, see commit notes):

| Probe                        | Classification | Rationale |
|------------------------------|----------------|-----------|
| `dan.Dan_11_0`               | **safe**       | Prompts loaded from JSON at class-create time via `DANProbeMeta`. The metaclass-injected `probe()` only string-formats `{generator.name}` once before delegating to `Probe.probe()`. No attempt-to-attempt state. |
| `encoding.InjectBase64`      | **safe**       | `EncodingMixin.__init__` pre-generates the full `(templates × payloads × encoders)` Cartesian product into `self.prompts` + `self.triggers`. `_attempt_prestore_hook` reads by `seq` index — thread-safe. |
| `malwaregen.TopLevel`        | **safe**       | `__init__` builds `self.prompts` via language-substitution over `base_prompts` (8 languages × 2 templates = 16 prompts). No mutation, no feedback. |
| `grandma.Win10`              | **safe**       | `__init__` loads the payloads list once, builds `self.prompts` via Cartesian product of templates × product-names. Detectors run independently per attempt. |
| `_DataExfilProbe` (in-repo)  | **safe**       | Iterates a literal 5-item `_PROMPTS` tuple. `generator.generate()` is the only I/O. No shared state. |

**Confidence: high for all five.** None of these follow the adversarial-loop pattern (`atkgen`, `snowball`, `continuation.*`-style where prompt N+1 depends on the output of N). Garak classes that DO follow that pattern are not on the allowlist and will continue to run serially.

## Consequences

**Positive**

- With `GARAK_PARALLEL_ATTEMPTS=4`, `InjectBase64` drops from ~70s to ~18s at `max_attempts=10` — back inside the 60s budget and faster than the current 30s budget at 3 attempts.
- `dan.Dan_11_0` and `malwaregen.TopLevel` run ~4x faster.
- Users see the full attempt count in Timeline / Explainability (now that task #17 fixed per-attempt correlation_ids).

**Negative / risks**

- **Concurrent load on the CPM pipeline.** Each parallel attempt hits the full guard-model + LLM chain. With 4 concurrent requests per probe and 5 probes serial, peak pressure is 4× what it is today. Rate limits on the upstream LLM provider are the likely first failure mode. We should verify with a load test before enabling in prod.
- **`CPMPipelineGenerator._meta` is process-local.** Garak's base class uses `multiprocessing.Pool` with `imap_unordered` for parallelism, which forks SUBPROCESSES. `generator._meta` is populated in the child, but `_run_probe_sync` reads `_meta[str(hash(prompt_str))]` in the parent — the parent's dict would be empty and trace metadata (guard decision, reason, score) would silently fall back to defaults. **Before enabling any probe at N>1, we must switch the generator's execution model to threads** (subclass / patch to use `ThreadPoolExecutor` instead of `multiprocessing.Pool`), OR migrate `_meta` to an out-of-process store (Redis), OR return metadata inline via a different channel. Proposed short-term: thread-pool patch inside `services/garak/main.py`, scoped to allowlisted probes.
- **Per-attempt timeout still applies.** Parallelism reduces wall-clock, not per-request latency. A single slow LLM call can still blow the probe-level budget.
- **Allowlist is a maintenance burden.** When we pull in a new garak version or expose a new probe in the UI, we must revisit the classification. Mitigation: default-deny — any probe not in the allowlist runs serially.

**Neutral**

- `parallel_attempts=1` remains the default, so this change is a no-op until an operator sets the env var.
- Existing tests are untouched; the classification is additive.

## Rollout plan

1. **Land this ADR + code skeleton** (allowlist, env var, probe/generator attribute toggles). Default `GARAK_PARALLEL_ATTEMPTS=1` — zero behavioural change.
2. **Fix the `_meta` cross-process problem** (thread-pool patch). Add a unit test that runs `InjectBase64` with 4 parallel attempts through a stub generator and asserts `generator._meta` is populated correctly on the caller side.
3. **Enable in staging at N=4** for the five allowlisted probes. Watch: p99 latency to `/internal/probe`, LLM provider rate-limit counters, guard-model queue depth. Keep on for 48h before promoting.
4. **Promote to prod at N=4.** Tunable per environment via `.env`. Keep `GARAK_PROBE_TIMEOUT_S` at 180s so a single slow probe still doesn't block forever.
5. **Widen the allowlist** when a new probe is added to the UI: require a probe-specific test (parallel vs. serial outputs equivalent) before classification changes to `safe`.

## Alternatives considered

- **A. Bump `max_attempts` down to 3.** Fastest fix (one-line change in `GarakConfig`). Reduces signal per probe; an adversary who makes 10 tries has more chances than one who gets 3. Good as a hot-fix but not a long-term answer.
- **B. Bump `PROBE_TIMEOUT_S` to 180s on both sides.** Masks the symptom. Doesn't address the fundamental "10 × 7s attempts don't fit in 60s" math, just moves the cliff. Should be combined with this ADR, not replace it.
- **C. App-level parallelism in `services/api/garak_runner.py`** using `asyncio.gather` over the probes (not attempts). Useful and nearly orthogonal — parallelise probes AND attempts — but has the same concurrent-load concerns and hides the fact that the real bottleneck is within a probe, not across probes. Could come as ADR 0002 later.
- **D. Do nothing, just reduce `max_attempts`.** Viable as a hotfix, considered here as "A". Rejected as the long-term answer because it systematically under-tests the live system's defenses.

## Open questions

- Is our LLM provider's rate limit compatible with 4× peak concurrency? Needs to be answered before step 3.
- Should `PARALLEL_SAFE_PROBES` live in code or config? Code for now (review gate on PR); migrate to YAML if the set grows past 15–20 probes.
- Do we want per-probe N (e.g., N=8 for encoding, N=4 for dan) or one global N? Start with one global N; add per-probe tuning only if measurements warrant.
