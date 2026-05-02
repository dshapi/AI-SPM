"""
policies/rego_seed.py
─────────────────────
Reads the canonical OPA Rego policies (the same set OPA itself loads from
the ``opa-policies`` ConfigMap) and renders them into PolicyORM-shaped
dicts the seed function can ingest.

This is Phase 1 of the policies-page migration: read-only display of real
policies in the UI.  Phase 2 wires editing — and at that point we'll either
mount the ConfigMap into agent-orchestrator at runtime (so edits flow back
through `kubectl patch configmap`) or proxy through OPA's policy API.  For
now this seed runs once on startup and the rows are immutable from the
UI's perspective.

How it works
────────────
* The agent-orchestrator Dockerfile copies ``deploy/helm/aispm/files/
  policies/*.rego`` into ``/app/_rego_seed/`` at build time.
* On startup, ``policies/seed.py`` calls ``load_real_policies()`` which
  walks that directory and produces one dict per .rego file.
* Each dict matches the shape the existing ``create_policy_raw`` function
  expects, so we don't touch the schema or store layer.

Field derivation
────────────────
* ``policy_id``    — the .rego filename without the ``.rego`` suffix and
                     ``-v1`` appended ("jailbreak_policy" → "jailbreak_policy-v1").
* ``name``         — title-cased filename ("jailbreak_policy" → "Jailbreak Policy").
* ``description``  — extracted from the leading comment block of the
                     .rego file (everything between the file header and the
                     first non-comment line).  If no description is found,
                     a generic one based on the policy type is used.
* ``type``         — inferred from the filename keywords (e.g. files
                     containing "jailbreak" → "prompt-safety", "tool" →
                     "tool-access").  See ``_TYPE_BY_KEYWORD``.
* ``mode``         — ``"Enforce"`` for everything except ``recon_guard``
                     (kept on Monitor since it's noisy).
* ``status``       — always ``"Active"`` since these are the policies OPA
                     is currently loading.
* ``logic_code``   — the literal .rego file content.
* ``logic_language`` — always ``"rego"``.
* Stats / agents / tools / dataSources / impact — left at empty defaults.
  Real telemetry fills these in once the runtime starts attributing
  blocks to named policies (the work we did earlier today on
  ``policy_name`` end-to-end).

Errors are non-fatal — a malformed .rego file logs a warning and skips,
the seed continues with the rest.  This keeps a single bad policy from
preventing the whole library from loading.
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Optional

log = logging.getLogger("policies.rego_seed")

# ── Paths ────────────────────────────────────────────────────────────────────
# Default location bundled by the agent-orchestrator Dockerfile.  Tests can
# override via the REGO_SEED_DIR env var.
_DEFAULT_REGO_DIR = Path(__file__).resolve().parent.parent / "_rego_seed"


# ── Filename → policy-type inference ─────────────────────────────────────────
# Order matters: first match wins.  "tool_injection_guard" must hit
# "tool_injection" before "tool" so it lands in "prompt-safety" not
# "tool-access".

_TYPE_BY_KEYWORD: list[tuple[str, str]] = [
    ("jailbreak",         "prompt-safety"),
    ("prompt",            "prompt-safety"),
    ("tool_injection",    "prompt-safety"),
    ("recon",             "prompt-safety"),
    ("output_schema",     "output-validation"),
    ("output",            "output-validation"),
    ("pii",               "privacy-redaction"),
    ("memory",            "data-access"),
    ("tool",              "tool-access"),
    ("agent",             "agent-policy"),
    ("model",             "model-policy"),
]


def _infer_type(stem: str) -> str:
    """Return the human-friendly policy type for a .rego filename stem."""
    s = stem.lower()
    for keyword, ptype in _TYPE_BY_KEYWORD:
        if keyword in s:
            return ptype
    return "policy"


# ── Filename → display name ──────────────────────────────────────────────────
# "jailbreak_policy" → "Jailbreak Policy"
# "tool_injection_guard" → "Tool Injection Guard"

def _display_name(stem: str) -> str:
    return " ".join(word.capitalize() for word in stem.split("_"))


# ── .rego header → description ───────────────────────────────────────────────
# Pulls the leading comment block (before ``package``) and strips the ``#``
# prefix from each line.  Lines beginning with a section divider (──────)
# are discarded so the description reads cleanly.

_DIVIDER_RE = re.compile(r"^─+|^=+|^-{3,}|^={3,}")

def _extract_description(rego_text: str, fallback: str) -> str:
    lines: list[str] = []
    for raw in rego_text.splitlines():
        s = raw.strip()
        if s.startswith("package"):
            break
        if not s.startswith("#"):
            continue
        body = s.lstrip("#").strip()
        if not body or _DIVIDER_RE.match(body):
            continue
        lines.append(body)
    desc = " ".join(lines).strip()
    if not desc:
        return fallback
    # Keep descriptions readable — cap at ~280 chars so the UI tile doesn't
    # overflow.  This length matches the existing mock-policy descriptions.
    if len(desc) > 280:
        desc = desc[:277].rstrip() + "…"
    return desc


# ── Mode policy ──────────────────────────────────────────────────────────────
# Default to Enforce for every .rego file in deploy/helm/aispm/files/
# policies/ — they're all policies OPA is actively evaluating, so the
# Policies-page mode should mirror runtime reality. Includes recon_guard
# (capability-enumeration probes have no legitimate end-user rationale on
# a production chat surface, so the false-positive risk is minimal once
# operators have reviewed the pattern list once).
#
# If a specific policy ever needs to ship as Monitor by default (e.g.
# because it's experimental and high-FPR), add a stem-substring branch
# here. Today none do.

def _default_mode(stem: str) -> str:
    return "Enforce"


# ── Public entry point ───────────────────────────────────────────────────────

def load_real_policies(rego_dir: Optional[Path] = None) -> list[dict]:
    """Walk *rego_dir* and return one PolicyORM-shaped dict per .rego file.

    Returns ``[]`` if the directory doesn't exist (tests / local dev where
    the Dockerfile bundling step didn't run) — caller can fall back to
    mock data in that case.
    """
    if rego_dir is None:
        env_override = os.environ.get("REGO_SEED_DIR")
        rego_dir = Path(env_override) if env_override else _DEFAULT_REGO_DIR

    if not rego_dir.exists():
        log.info("rego_seed: directory %s not found — skipping real-policy seed", rego_dir)
        return []

    rego_files = sorted(rego_dir.glob("*.rego"))
    if not rego_files:
        log.info("rego_seed: directory %s has no .rego files", rego_dir)
        return []

    seeds: list[dict] = []
    for f in rego_files:
        try:
            text = f.read_text(encoding="utf-8")
        except Exception as exc:
            log.warning("rego_seed: failed to read %s — %s", f, exc)
            continue

        stem = f.stem  # e.g. "jailbreak_policy"
        ptype = _infer_type(stem)
        seeds.append({
            "id":             f"{stem}-v1",
            "name":           _display_name(stem),
            "version":        "v1",
            "type":           ptype,
            "mode":           _default_mode(stem),
            "status":         "Active",
            "scope":          "All Production Agents",
            "owner":          "security-ops",
            "createdBy":      "system-seed",
            "created":        "Apr 2026",
            "updated":        "—",
            "updatedFull":    "",
            "description":    _extract_description(
                text,
                fallback=f"OPA-enforced {ptype} policy ({stem}.rego). "
                         f"Loaded from the chart's opa-policies ConfigMap and "
                         f"evaluated on every relevant request.",
            ),
            "affectedAssets": 0,
            "relatedAlerts":  0,
            "linkedSimulations": 0,
            "agents":         [],
            "tools":          [],
            "dataSources":    [],
            "environments":   ["Production"],
            "exceptions":     [],
            "impact":         {"blocked": 0, "flagged": 0, "unchanged": 0, "total": 0},
            "history":        [
                {"version": "v1", "by": "system-seed", "when": "—",
                 "change": f"Imported from chart ConfigMap (deploy/helm/aispm/files/policies/{f.name})."},
            ],
            "logic_code":     text,
            "logic_language": "rego",
        })

    log.info("rego_seed: prepared %d real policies from %s", len(seeds), rego_dir)
    return seeds
