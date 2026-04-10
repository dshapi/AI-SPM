"""
promptguard.layers.base
───────────────────────
Base classes for all screening layers.

Every layer must:
- Accept a raw text string
- Return a LayerResult with blocked=True/False and an optional label
- Never raise; catch internal errors and return blocked=True (fail-closed)
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class LayerResult:
    """Result from a single screening layer."""
    blocked: bool
    label: Optional[str] = None          # short machine label, e.g. "base64_payload"
    reason: str = ""                     # human-readable reason (internal logging only)
    score: float = 0.0                   # 0.0–1.0 confidence; 1.0 = certain block
    metadata: dict = field(default_factory=dict)

    @classmethod
    def allow(cls) -> "LayerResult":
        return cls(blocked=False)

    @classmethod
    def block(cls, label: str, reason: str = "", score: float = 1.0,
              **meta) -> "LayerResult":
        return cls(blocked=True, label=label, reason=reason, score=score,
                   metadata=meta)


class BaseLayer:
    """
    Abstract base for all promptguard layers.

    Subclasses implement ``_screen(text: str) -> LayerResult``.
    The public ``screen()`` method wraps it with fail-closed error handling.
    """

    #: Short name used in logs and metrics
    name: str = "base"

    def screen(self, text: str) -> LayerResult:
        """
        Screen *text* and return a LayerResult.
        Always returns a result — never raises.
        """
        if not text or not text.strip():
            return LayerResult.allow()
        try:
            return self._screen(text)
        except Exception as exc:  # noqa: BLE001
            # Fail closed: any unexpected error → block with error label
            return LayerResult.block(
                label="layer_error",
                reason=f"{self.name} raised {type(exc).__name__}",
                score=0.5,
            )

    def _screen(self, text: str) -> LayerResult:
        raise NotImplementedError
