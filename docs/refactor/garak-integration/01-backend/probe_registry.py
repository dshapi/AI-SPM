"""
platform_shared/simulation/probe_registry.py
────────────────────────────────────────────
Deterministic probe identity: (input string) → (canonical probe, category, phase).

Why this exists
───────────────
Before the refactor, three different modules (garak-runner, API-side garak
client, and the frontend) each maintained their own substring-based category
table.  They disagreed on edge cases — producing 'Unknown' probe labels and
inconsistent groupings across tabs.  This module is the single source of
truth; both backends import it and the frontend renders exactly what the
backend sends.

Contract
────────
``resolve(raw: str) -> ProbeIdentity`` is total — it always returns a result.
When the raw probe string does not match any alias, it still returns a
ProbeIdentity with:

    probe    = "unknown"
    category = "Unknown"
    phase    = OTHER
    known    = False
    raw      = <the original string>

The caller is expected to emit a ``simulation.warning`` with code
``"unknown_probe"`` and preserve ``raw`` in ``Attempt.meta.garak_probe_class``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from .attempts import AttemptPhase


# ── Canonical registry ───────────────────────────────────────────────────────
#
# Key       — user/UI-visible probe id (kept short, kebab/snake).  MUST be
#             unique across the whole table.
# garak_cls — dotted garak probe class path (e.g. "dan.Dan_11_0") or "" for
#             synthetic inline probes implemented in garak-runner.
# category  — human-readable category rendered in every tab.
# phase     — kill-chain phase used by the Timeline tab for grouping.

@dataclass(frozen=True, slots=True)
class _RegistryRow:
    probe:     str
    garak_cls: str
    category:  str
    phase:     AttemptPhase


@dataclass(frozen=True, slots=True)
class ProbeIdentity:
    probe:    str
    category: str
    phase:    AttemptPhase
    known:    bool
    raw:      str


_REGISTRY: Final[tuple[_RegistryRow, ...]] = (
    _RegistryRow("promptinject", "dan.Dan_11_0",          "Prompt Injection",        AttemptPhase.EXPLOIT),
    _RegistryRow("dataexfil",    "",                       "Data Exfiltration",       AttemptPhase.EXFILTRATION),
    _RegistryRow("tooluse",      "malwaregen.TopLevel",    "Tool Abuse",              AttemptPhase.EXECUTION),
    _RegistryRow("encoding",     "encoding.InjectBase64",  "Encoding Bypass",         AttemptPhase.EVASION),
    _RegistryRow("multiturn",    "grandma.Win10",          "Multi-turn Manipulation", AttemptPhase.RECON),
    _RegistryRow("jailbreak",    "dan.Dan_11_0",           "Jailbreak",               AttemptPhase.EXPLOIT),
    _RegistryRow("xss",          "xss.MarkdownImageExfil", "XSS",                     AttemptPhase.EVASION),
    _RegistryRow("malwaregen",   "malwaregen.TopLevel",    "Malware Generation",      AttemptPhase.EXECUTION),
    _RegistryRow("package_hall", "packagehallucination.Python", "Package Hallucination", AttemptPhase.RECON),
)


# ── Index for fast lookup (probe id, garak class, lowercase alias) ──────────

_BY_PROBE:    Final[dict[str, _RegistryRow]] = {r.probe:            r for r in _REGISTRY}
_BY_GARAK:    Final[dict[str, _RegistryRow]] = {r.garak_cls.lower(): r for r in _REGISTRY if r.garak_cls}
_BY_LOWER:    Final[dict[str, _RegistryRow]] = {r.probe.lower():    r for r in _REGISTRY}


def resolve(raw: str | None) -> ProbeIdentity:
    """Resolve any probe-identifying string to a canonical ProbeIdentity.

    Accepts (in order of precedence):
      1. Canonical probe id          (e.g. "promptinject")
      2. Garak dotted class path      (e.g. "dan.Dan_11_0")
      3. Probe id substring match    (e.g. "tooluse_v2" → "tooluse")

    Returns ProbeIdentity with known=False for completely unmapped input.
    """
    key = (raw or "").strip()
    if not key:
        return ProbeIdentity("unknown", "Unknown", AttemptPhase.OTHER, False, raw or "")

    # Exact probe-id hit
    hit = _BY_PROBE.get(key) or _BY_LOWER.get(key.lower())
    if hit:
        return ProbeIdentity(hit.probe, hit.category, hit.phase, True, raw or "")

    # Garak class path (case-insensitive; tolerates trailing classifier names)
    lower = key.lower()
    g_hit = _BY_GARAK.get(lower)
    if g_hit is None:
        # Also try first dotted segment — e.g. "dan.Dan_11_0" → "dan.*"
        head = lower.split(".", 1)[0]
        g_hit = next((r for r in _REGISTRY if r.garak_cls.lower().startswith(head + ".")), None)
    if g_hit:
        return ProbeIdentity(g_hit.probe, g_hit.category, g_hit.phase, True, raw or "")

    # Weak substring fallback (kept last so it never shadows exact hits).
    for row in _REGISTRY:
        if row.probe in lower:
            return ProbeIdentity(row.probe, row.category, row.phase, True, raw or "")

    return ProbeIdentity("unknown", "Unknown", AttemptPhase.OTHER, False, raw or "")


def canonical_probes() -> list[str]:
    """Stable ordered list of known probe ids — used by UI dropdowns/picker."""
    return [r.probe for r in _REGISTRY]


def known_categories() -> list[str]:
    """Sorted unique list of canonical categories (for Coverage tab rows)."""
    return sorted({r.category for r in _REGISTRY})
