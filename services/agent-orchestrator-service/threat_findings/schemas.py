from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class FindingRecord:
    id:           str
    batch_hash:   str
    title:        str
    severity:     str
    description:  str
    evidence:     Dict[str, Any]
    ttps:         List[str]
    tenant_id:    str
    status:       str = "open"
    created_at:   str = field(default_factory=_utcnow)
    closed_at:    Optional[str] = None
    deduplicated: bool = False   # transient — not persisted


class CreateFindingRequest(BaseModel):
    title:       str            = Field(..., min_length=1)
    severity:    str            = Field(..., pattern="^(low|medium|high|critical)$")
    description: str            = Field(..., min_length=1)
    evidence:    Dict[str, Any] = Field(default_factory=dict)
    ttps:        List[str]      = Field(default_factory=list)
    tenant_id:   str            = Field(..., min_length=1)
    batch_hash:  str            = Field(..., min_length=1)


class FindingResponse(BaseModel):
    id:           str
    title:        str
    severity:     str
    status:       str
    created_at:   str
    deduplicated: bool = False

    @classmethod
    def from_record(cls, rec: FindingRecord) -> "FindingResponse":
        return cls(
            id=rec.id, title=rec.title, severity=rec.severity,
            status=rec.status, created_at=rec.created_at,
            deduplicated=rec.deduplicated,
        )
