from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from mcp_memory.config import ProjectConfig
from mcp_memory.schema import load_project_schema
from mcp_memory.services import (
    GenericEvidenceService,
    GenericEvidenceWrite,
    GenericRelationService,
    GenericRelationWrite,
    RecordService,
    RecordWrite,
    SearchQuery,
    SearchService,
)
from mcp_memory.storage import Database


@dataclass(slots=True)
class ProtocolResult:
    status: str
    data: Any


@dataclass(slots=True)
class GetSchemaQuery:
    pass


@dataclass(slots=True)
class ListEntityTypesQuery:
    pass


@dataclass(slots=True)
class SearchRecordsQuery:
    q: str = ""
    entity_types: list[str] | None = None
    tag: str | None = None
    limit: int = 10


@dataclass(slots=True)
class GetRecordQuery:
    entity_type: str
    record_id_or_slug: str
    include_archived: bool = False


@dataclass(slots=True)
class ListRecordsQuery:
    entity_type: str | None = None
    include_archived: bool = False
    limit: int = 100


@dataclass(slots=True)
class UpsertRecordCommand:
    entity_type: str
    payload: dict[str, Any]
    record_id: str | None = None
    source_origin: str = "manual"
    created_by: str = "system"
    updated_by: str = "system"
    actor_type: str = "system"


@dataclass(slots=True)
class ArchiveRecordCommand:
    entity_type: str
    record_id_or_slug: str
    archived_by: str = "system"
    actor_type: str = "system"


@dataclass(slots=True)
class CreateRelationCommand:
    from_entity_type: str
    from_record_id: str
    to_entity_type: str
    to_record_id: str
    relation_type: str
    created_by: str = "system"
    actor_type: str = "system"


@dataclass(slots=True)
class GetRelatedQuery:
    entity_type: str
    record_id_or_slug: str
    hops: int = 1


@dataclass(slots=True)
class AddEvidenceCommand:
    entity_type: str
    record_id: str
    evidence_type: str
    description: str
    evidence_id: str | None = None
    excerpt: str | None = None
    attachment_path: str | None = None
    media_type: str | None = None
    size_bytes: int | None = None
    created_by: str = "system"
    source_origin: str = "manual"
    actor_type: str = "system"


ProtocolMessage = (
    GetSchemaQuery
    | ListEntityTypesQuery
    | SearchRecordsQuery
    | GetRecordQuery
    | ListRecordsQuery
    | UpsertRecordCommand
    | ArchiveRecordCommand
    | CreateRelationCommand
    | GetRelatedQuery
    | AddEvidenceCommand
)


class ProjectDispatcher:
    def __init__(self, database: Database, project: ProjectConfig) -> None:
        self._database = database
        self._project = project

    def dispatch(self, message: ProtocolMessage) -> ProtocolResult:
        if isinstance(message, GetSchemaQuery):
            return ProtocolResult("ok", load_project_schema(self._project.schema_path).to_dict())
        if isinstance(message, ListEntityTypesQuery):
            return ProtocolResult("ok", RecordService(self._database, self._project).list_entity_types())
        if isinstance(message, SearchRecordsQuery):
            data = SearchService(self._database).search(
                SearchQuery(
                    project_id=self._project.project_id,
                    query_text=message.q,
                    entity_types=message.entity_types,
                    tag=message.tag,
                    limit=message.limit,
                )
            )
            return ProtocolResult("ok", {"items": data})
        if isinstance(message, GetRecordQuery):
            record = RecordService(self._database, self._project).get_record(
                message.entity_type,
                message.record_id_or_slug,
                include_archived=message.include_archived,
            )
            return ProtocolResult("ok", record)
        if isinstance(message, ListRecordsQuery):
            records = RecordService(self._database, self._project).list_records(
                entity_type=message.entity_type,
                include_archived=message.include_archived,
                limit=message.limit,
            )
            return ProtocolResult("ok", {"items": records})
        if isinstance(message, UpsertRecordCommand):
            record = RecordService(self._database, self._project).upsert_record(
                RecordWrite(
                    entity_type=message.entity_type,
                    record_id=message.record_id,
                    payload=message.payload,
                    source_origin=message.source_origin,
                    created_by=message.created_by,
                    updated_by=message.updated_by,
                ),
                actor_type=message.actor_type,
            )
            return ProtocolResult("created", record)
        if isinstance(message, ArchiveRecordCommand):
            record = RecordService(self._database, self._project).archive_record(
                message.entity_type,
                message.record_id_or_slug,
                archived_by=message.archived_by,
                actor_type=message.actor_type,
            )
            return ProtocolResult("ok", record)
        if isinstance(message, CreateRelationCommand):
            relation = GenericRelationService(self._database, self._project).create_relation(
                GenericRelationWrite(
                    from_entity_type=message.from_entity_type,
                    from_record_id=message.from_record_id,
                    to_entity_type=message.to_entity_type,
                    to_record_id=message.to_record_id,
                    relation_type=message.relation_type,
                    created_by=message.created_by,
                ),
                actor_type=message.actor_type,
            )
            return ProtocolResult("created", relation)
        if isinstance(message, GetRelatedQuery):
            data = GenericRelationService(self._database, self._project).traverse_related(
                message.entity_type,
                message.record_id_or_slug,
                hops=message.hops,
            )
            return ProtocolResult("ok", {"items": data})
        if isinstance(message, AddEvidenceCommand):
            evidence = GenericEvidenceService(self._database, self._project).create_evidence(
                GenericEvidenceWrite(
                    entity_type=message.entity_type,
                    record_id=message.record_id,
                    evidence_id=message.evidence_id,
                    evidence_type=message.evidence_type,
                    description=message.description,
                    excerpt=message.excerpt,
                    attachment_path=message.attachment_path,
                    media_type=message.media_type,
                    size_bytes=message.size_bytes,
                    created_by=message.created_by,
                    source_origin=message.source_origin,
                ),
                actor_type=message.actor_type,
            )
            return ProtocolResult("created", evidence)
        raise TypeError(f"Unsupported protocol message: {type(message).__name__}")
