"""
services/api/simulation/attempts.py
───────────────────────────────────
Canonical Attempt / ProbeRunResult / Summary / WebSocket-envelope models.

v2.1 — correctness audit
─────────────────────────
* ``sequence`` REMOVED from Attempt.  Sequence is an envelope concern, not
  an attempt concern.  The orchestrator assigns one monotonic sequence
  per emitted frame; duplicating the counter on the attempt caused gaps
  and misordering (orchestrator reseq vs runner sequence_base).
* Added ``model_invoked: bool`` — True when the model actually produced
  output.  Drives the Output tab.
* Added ``probe_raw: str`` — the exact probe string the caller sent
  (before registry normalisation).  Keeps the UI honest about what the
  operator requested vs what we actually ran.
* ``SimulationWarningData.detail`` is structured (dict) — no string
  warnings leak through.
* Added ``SimulationProbeCompletedEvent`` — fires when a probe finishes,
  carries ``probe_duration_ms`` + final per-probe stats.
* ``GuardDecision`` invariant unchanged: when present, ``policy_id`` and
  ``policy_name`` are mandatory and must not be invented.  See
  ``garak_adapter`` for the ``__unresolved__:<probe>`` convention used
  when the pipeline executes the guard but omits policy metadata.

Design invariants
─────────────────
1.  ``Attempt`` is the ONLY canonical unit of observation.
2.  No silent ``unknown_probe`` — the registry always resolves; unknown
    inputs produce a ``simulation.warning`` with code ``unknown_probe``.
3.  ``GuardDecision`` is always structured when a guard ran.  Missing
    policy metadata surfaces as ``__unresolved__:<probe>`` so the UI can
    render a distinct "Unresolved policy mapping" row — NEVER "Unknown".
4.  WebSocket envelope = ``type`` + ``session_id`` + ``sequence`` +
    ``timestamp`` + ``data``.  ``sequence`` is the orchestrator's single
    monotonic counter.  Fragment events removed.

Python: 3.11+.  Pydantic v2.
"""
from __future__ import annotations

import datetime as _dt
import uuid as _uuid
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ── Enums ────────────────────────────────────────────────────────────────────

class AttemptPhase(str, Enum):
    RECON        = "recon"
    EXPLOIT      = "exploit"
    EVASION      = "evasion"
    EXECUTION    = "execution"
    EXFILTRATION = "exfiltration"
    OTHER        = "other"


class AttemptResult(str, Enum):
    BLOCKED = "blocked"
    ALLOWED = "allowed"
    ERROR   = "error"


class AttemptStatus(str, Enum):
    RUNNING   = "running"
    COMPLETED = "completed"
    FAILED    = "failed"


class GuardAction(str, Enum):
    BLOCK  = "block"
    ALLOW  = "allow"
    REVIEW = "review"
    ERROR  = "error"


# ── Core data shapes ────────────────────────────────────────────────────────

UNRESOLVED_POLICY_PREFIX = "__unresolved__:"
UNRESOLVED_POLICY_NAME   = "Unresolved policy mapping"
UNRESOLVED_POLICY_REASON = "Guard executed but policy metadata missing"


class GuardDecision(BaseModel):
    """Structured output of a guard / policy evaluation.

    Invariant: when the guard ran, this object is present and all fields
    are populated.  Missing policy metadata is represented by
    ``policy_id="__unresolved__:<probe>"`` and
    ``policy_name="Unresolved policy mapping"`` — NEVER by inventing a
    ``{probe}_default_policy`` name.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    action:      GuardAction
    score:       float = Field(..., ge=0.0, le=1.0)
    threshold:   float = Field(..., ge=0.0, le=1.0)
    policy_id:   str   = Field(..., min_length=1)
    policy_name: str   = Field(..., min_length=1)
    reason:      str   = Field(default="")

    @property
    def unresolved(self) -> bool:
        return self.policy_id.startswith(UNRESOLVED_POLICY_PREFIX)


class AttemptMeta(BaseModel):
    model_config = ConfigDict(extra="allow")

    garak_probe_class: str = Field(default="")
    garak_profile:     str = Field(default="")
    detector:          str = Field(default="")


class Attempt(BaseModel):
    """One canonical probe attempt.

    Note: NO ``sequence`` field here.  Sequence is assigned by the
    orchestrator at envelope build time.  Keeping two counters in sync
    is the bug that caused the original gaps / duplicates — we only
    maintain one.
    """

    model_config = ConfigDict(extra="forbid")

    # ── Identity ────────────────────────────────────────────────────────────
    attempt_id:   _uuid.UUID         = Field(default_factory=_uuid.uuid4)
    session_id:   _uuid.UUID

    # ── Taxonomy ────────────────────────────────────────────────────────────
    probe:        str                = Field(..., min_length=1, description="Canonical probe id.")
    probe_raw:    str                = Field(..., description="Probe string as requested by the caller, pre-registry.")
    category:     str                = Field(..., min_length=1)
    phase:        AttemptPhase

    # ── Timing ──────────────────────────────────────────────────────────────
    started_at:   _dt.datetime       = Field(default_factory=lambda: _dt.datetime.now(_dt.timezone.utc))
    completed_at: _dt.datetime | None = None
    latency_ms:   int | None         = Field(default=None, ge=0)

    # ── Payload ─────────────────────────────────────────────────────────────
    prompt_raw:       str            = Field(..., description="Raw prompt as produced by the probe.")
    prompt_sanitized: str            = Field(default="")
    guard_input:      str            = Field(default="")
    model_response:   str | None     = Field(default=None)

    # ── Lifecycle / disposition ─────────────────────────────────────────────
    guard_decision:  GuardDecision | None = None
    result:          AttemptResult
    risk_score:      int             = Field(..., ge=0, le=100)
    status:          AttemptStatus   = AttemptStatus.COMPLETED
    error:           str | None      = None

    # ── NEW: model-invocation flag ──────────────────────────────────────────
    model_invoked:   bool            = Field(
        ..., description="True iff the downstream model was actually invoked "
                         "for this prompt.  Blocked-before-model attempts are False."
    )

    # ── Provenance ──────────────────────────────────────────────────────────
    meta:            AttemptMeta     = Field(default_factory=AttemptMeta)

    @field_validator("attempt_id")
    @classmethod
    def _nonempty_uuid(cls, v: _uuid.UUID) -> _uuid.UUID:
        if v.int == 0:
            raise ValueError("attempt_id must be a real (non-zero) UUID")
        return v


class ProbeRunStats(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    attempt_count: int = Field(..., ge=0)
    blocked_count: int = Field(..., ge=0)
    allowed_count: int = Field(..., ge=0)
    error_count:   int = Field(..., ge=0)


class StructuredWarning(BaseModel):
    """Warning carried inside ProbeRunResult and over the WS wire.

    Kept distinct from a plain string so every consumer sees the same
    shape.  ``detail`` is free-form dict; never use string templating.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    code:    str = Field(..., min_length=1)
    message: str = Field(..., min_length=1)
    detail:  dict[str, Any] = Field(default_factory=dict)


class ProbeRunResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: _uuid.UUID
    probe:      str
    probe_raw:  str
    category:   str
    phase:      AttemptPhase
    attempts:   list[Attempt]
    stats:      ProbeRunStats
    warnings:   list[StructuredWarning] = Field(default_factory=list)
    duration_ms: int = Field(..., ge=0, description="Wall-clock time spent inside _run_probe_sync.")


class SimulationSummary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    probe_count:       int
    attempt_count:     int
    blocked_count:     int
    allowed_count:     int
    error_count:       int
    in_progress_count: int
    peak_risk_score:   int
    elapsed_ms:        int
    triggered_policies: list[str] = Field(default_factory=list)


# ── WebSocket event envelope ─────────────────────────────────────────────────

_EventType = Literal[
    "simulation.started",
    "simulation.probe_started",
    "simulation.probe_completed",
    "simulation.attempt",
    "simulation.summary",
    "simulation.completed",
    "simulation.warning",
    "simulation.error",
]


class _BaseEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type:       _EventType
    session_id: _uuid.UUID
    sequence:   int = Field(..., ge=0, description="Monotonic, assigned by orchestrator on emit.")
    timestamp:  _dt.datetime = Field(default_factory=lambda: _dt.datetime.now(_dt.timezone.utc))


class SimulationStartedData(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    probes:         list[str]
    profile:        str
    execution_mode: str
    max_attempts:   int


class SimulationStartedEvent(_BaseEvent):
    type: Literal["simulation.started"] = "simulation.started"
    data: SimulationStartedData


class ProbeStartedData(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    probe:    str
    probe_raw: str
    category: str
    phase:    AttemptPhase
    index:    int
    total:    int


class SimulationProbeStartedEvent(_BaseEvent):
    type: Literal["simulation.probe_started"] = "simulation.probe_started"
    data: ProbeStartedData


class ProbeCompletedData(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    probe:              str
    probe_raw:          str
    category:           str
    phase:              AttemptPhase
    index:              int
    total:              int
    attempt_count:      int = Field(..., ge=0)
    blocked_count:      int = Field(..., ge=0)
    allowed_count:      int = Field(..., ge=0)
    error_count:        int = Field(..., ge=0)
    probe_duration_ms:  int = Field(..., ge=0)


class SimulationProbeCompletedEvent(_BaseEvent):
    type: Literal["simulation.probe_completed"] = "simulation.probe_completed"
    data: ProbeCompletedData


class SimulationAttemptEvent(_BaseEvent):
    type: Literal["simulation.attempt"] = "simulation.attempt"
    data: Attempt


class SimulationSummaryEvent(_BaseEvent):
    type: Literal["simulation.summary"] = "simulation.summary"
    data: SimulationSummary


class SimulationCompletedData(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    summary:  SimulationSummary
    total_ms: int


class SimulationCompletedEvent(_BaseEvent):
    type: Literal["simulation.completed"] = "simulation.completed"
    data: SimulationCompletedData


class SimulationWarningData(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    code:    str = Field(..., min_length=1)
    message: str = Field(..., min_length=1)
    detail:  dict[str, Any] = Field(default_factory=dict)


class SimulationWarningEvent(_BaseEvent):
    type: Literal["simulation.warning"] = "simulation.warning"
    data: SimulationWarningData


class SimulationErrorData(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    error_message: str = Field(..., min_length=1)
    fatal:         bool = True


class SimulationErrorEvent(_BaseEvent):
    type: Literal["simulation.error"] = "simulation.error"
    data: SimulationErrorData


SimulationEvent = (
    SimulationStartedEvent
    | SimulationProbeStartedEvent
    | SimulationProbeCompletedEvent
    | SimulationAttemptEvent
    | SimulationSummaryEvent
    | SimulationCompletedEvent
    | SimulationWarningEvent
    | SimulationErrorEvent
)


# ── Pure helpers ─────────────────────────────────────────────────────────────

def summarize(attempts: list[Attempt], *, elapsed_ms: int, probe_count: int) -> SimulationSummary:
    blocked = sum(1 for a in attempts if a.result is AttemptResult.BLOCKED)
    allowed = sum(1 for a in attempts if a.result is AttemptResult.ALLOWED)
    errored = sum(1 for a in attempts if a.result is AttemptResult.ERROR)
    in_prog = sum(1 for a in attempts if a.status is AttemptStatus.RUNNING)
    policies = sorted({
        a.guard_decision.policy_id
        for a in attempts
        if a.guard_decision is not None and a.guard_decision.policy_id
    })
    return SimulationSummary(
        probe_count       = probe_count,
        attempt_count     = len(attempts),
        blocked_count     = blocked,
        allowed_count     = allowed,
        error_count       = errored,
        in_progress_count = in_prog,
        peak_risk_score   = max((a.risk_score for a in attempts), default=0),
        elapsed_ms        = elapsed_ms,
        triggered_policies = policies,
    )


def make_unresolved_policy(probe: str, *, score: float, threshold: float,
                           action: GuardAction) -> GuardDecision:
    """Build a GuardDecision for the "guard ran, no policy metadata" case.

    Callers MUST use this factory — never invent a policy name/id.  The
    distinct ``__unresolved__:*`` id lets the UI render a warning row
    instead of a confident policy line.
    """
    return GuardDecision(
        action      = action,
        score       = max(0.0, min(1.0, score)),
        threshold   = max(0.0, min(1.0, threshold)),
        policy_id   = f"{UNRESOLVED_POLICY_PREFIX}{probe}",
        policy_name = UNRESOLVED_POLICY_NAME,
        reason      = UNRESOLVED_POLICY_REASON,
    )
