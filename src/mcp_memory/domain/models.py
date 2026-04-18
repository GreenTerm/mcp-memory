from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

try:
    from enum import StrEnum
except ImportError:
    class StrEnum(str, Enum):
        """Python 3.10 compatibility fallback for StrEnum."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class HypothesisStatus(StrEnum):
    NEW = "new"
    PROBABLE = "probable"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class ActorType(StrEnum):
    USER = "user"
    AGENT = "agent"
    SYSTEM = "system"


@dataclass(slots=True)
class ObservedFact:
    fact: str
    source_origin: str = "manual"


@dataclass(slots=True)
class HypothesisItem:
    statement: str
    status: HypothesisStatus = HypothesisStatus.NEW
    confidence: float | None = None
    source_origin: str = "manual"


@dataclass(slots=True)
class EvidenceRef:
    evidence_id: str
    label: str


@dataclass(slots=True)
class StructureMember:
    name: str
    offset: str
    data_type: str
    size: int | None = None
    comment: str = ""


@dataclass(slots=True)
class StructureWrite:
    project_id: str
    binary_id: str
    structure_id: str
    raw_name: str
    current_name: str
    summary: str
    fields: list[StructureMember] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    observed_facts: list[ObservedFact] = field(default_factory=list)
    hypotheses: list[HypothesisItem] = field(default_factory=list)
    evidence_refs: list[EvidenceRef] = field(default_factory=list)
    source_origin: str = "manual"
    created_by: str = "system"
    updated_by: str = "system"


@dataclass(slots=True)
class StructureRecord(StructureWrite):
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)


@dataclass(slots=True)
class GlobalHypothesisWrite:
    project_id: str
    hypothesis_id: str
    title: str
    statement: str
    status: HypothesisStatus = HypothesisStatus.NEW
    confidence: float | None = None
    binary_id: str | None = None
    tags: list[str] = field(default_factory=list)
    observed_facts: list[ObservedFact] = field(default_factory=list)
    evidence_refs: list[EvidenceRef] = field(default_factory=list)
    source_origin: str = "manual"
    created_by: str = "system"
    updated_by: str = "system"


@dataclass(slots=True)
class GlobalHypothesisRecord(GlobalHypothesisWrite):
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)


@dataclass(slots=True)
class EvidenceWrite:
    project_id: str
    evidence_id: str
    entity_type: str
    entity_id: str
    evidence_type: str
    description: str
    address_start: str | None = None
    address_end: str | None = None
    xref: str | None = None
    block_ref: str | None = None
    excerpt: str | None = None
    attachment_path: str | None = None
    media_type: str | None = None
    size_bytes: int | None = None
    source_origin: str = "manual"
    created_by: str = "system"


@dataclass(slots=True)
class EvidenceRecord(EvidenceWrite):
    attachment_id: str | None = None
    created_at: str = field(default_factory=utc_now)


@dataclass(slots=True)
class FunctionWrite:
    project_id: str
    binary_id: str
    function_id: str
    address: str
    raw_name: str
    current_name: str
    summary: str
    behavior_description: str
    important_variables: list[str] = field(default_factory=list)
    used_apis: list[str] = field(default_factory=list)
    strings: list[str] = field(default_factory=list)
    constants: list[str] = field(default_factory=list)
    confidence: float | None = None
    tags: list[str] = field(default_factory=list)
    observed_facts: list[ObservedFact] = field(default_factory=list)
    hypotheses: list[HypothesisItem] = field(default_factory=list)
    evidence_refs: list[EvidenceRef] = field(default_factory=list)
    source_origin: str = "manual"
    created_by: str = "system"
    updated_by: str = "system"
    allow_conflict: bool = False


@dataclass(slots=True)
class FunctionRecord(FunctionWrite):
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
