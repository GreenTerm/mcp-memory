from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from mcp_memory.config import ProjectConfig
from mcp_memory.domain.models import utc_now
from mcp_memory.logging_utils import get_logger, log_event
from mcp_memory.schema import SchemaValidationError, load_project_schema
from mcp_memory.storage import Database

from .records import RecordService


class GenericEvidenceValidationError(ValueError):
    """Raised when generic evidence is invalid."""


@dataclass(slots=True)
class GenericEvidenceWrite:
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


@dataclass(slots=True)
class GenericEvidenceRecord:
    evidence_id: str
    project_id: str
    entity_type: str
    record_id: str
    evidence_type: str
    description: str
    excerpt: str | None
    attachment_id: str | None
    attachment_path: str | None
    media_type: str | None
    size_bytes: int | None
    source_origin: str
    created_at: str
    created_by: str


class GenericEvidenceService:
    def __init__(self, database: Database, project: ProjectConfig) -> None:
        self._database = database
        self._project = project
        self._schema = load_project_schema(project.schema_path)
        self._records = RecordService(database, project)
        self._logger = get_logger("services")

    def create_evidence(self, write: GenericEvidenceWrite, actor_type: str = "system") -> GenericEvidenceRecord:
        self._validate_schema_entity(write.entity_type)
        record = self._records.get_record(write.entity_type, write.record_id)
        if record is None:
            raise GenericEvidenceValidationError("record not found")
        self._validate_text("evidence_type", write.evidence_type)
        self._validate_text("description", write.description)
        if write.size_bytes is not None and write.size_bytes < 0:
            raise GenericEvidenceValidationError("size_bytes must not be negative")

        evidence_id = write.evidence_id or str(uuid.uuid4())
        attachment_id = None
        if write.attachment_path:
            attachment_id = str(uuid.uuid4())
        evidence = GenericEvidenceRecord(
            evidence_id=evidence_id,
            project_id=self._project.project_id,
            entity_type=write.entity_type,
            record_id=record.record_id,
            evidence_type=write.evidence_type,
            description=write.description,
            excerpt=write.excerpt,
            attachment_id=attachment_id,
            attachment_path=write.attachment_path,
            media_type=write.media_type,
            size_bytes=write.size_bytes,
            source_origin=write.source_origin,
            created_at=utc_now(),
            created_by=write.created_by,
        )
        connection = self._database.transaction()
        if attachment_id is not None:
            connection.execute(
                """
                INSERT INTO attachments(attachment_id, project_id, relative_path, media_type, size_bytes, created_at, created_by)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    attachment_id,
                    evidence.project_id,
                    write.attachment_path,
                    write.media_type,
                    write.size_bytes,
                    evidence.created_at,
                    write.created_by,
                ),
            )
        connection.execute(
            """
            INSERT INTO evidence (
              evidence_id, project_id, entity_type, entity_id, evidence_type, address_start,
              address_end, xref, block_ref, description, excerpt, attachment_id, source_origin,
              created_at, created_by
            ) VALUES (?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, ?, ?, ?, ?, ?, ?)
            """,
            (
                evidence.evidence_id,
                evidence.project_id,
                evidence.entity_type,
                evidence.record_id,
                evidence.evidence_type,
                evidence.description,
                evidence.excerpt,
                evidence.attachment_id,
                evidence.source_origin,
                evidence.created_at,
                evidence.created_by,
            ),
        )
        self._append_audit(evidence, actor_type)
        connection.commit()
        log_event(
            self._logger,
            logging.INFO,
            "generic_evidence_created",
            project_id=evidence.project_id,
            entity_type=evidence.entity_type,
            record_id=evidence.record_id,
            evidence_id=evidence.evidence_id,
        )
        return evidence

    def list_evidence(self, entity_type: str, record_id_or_slug: str) -> list[GenericEvidenceRecord]:
        self._validate_schema_entity(entity_type)
        record = self._records.get_record(entity_type, record_id_or_slug, include_archived=True)
        if record is None:
            raise GenericEvidenceValidationError("record not found")
        rows = self._database.connection.execute(
            """
            SELECT e.*, a.relative_path, a.media_type, a.size_bytes
            FROM evidence e
            LEFT JOIN attachments a ON a.attachment_id = e.attachment_id
            WHERE e.project_id = ? AND e.entity_type = ? AND e.entity_id = ?
            ORDER BY e.created_at DESC
            """,
            (self._project.project_id, entity_type, record.record_id),
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def _validate_schema_entity(self, entity_type: str) -> None:
        try:
            self._schema.entity(entity_type)
        except SchemaValidationError as exc:
            raise GenericEvidenceValidationError(str(exc)) from exc

    def _row_to_record(self, row: dict[str, Any]) -> GenericEvidenceRecord:
        return GenericEvidenceRecord(
            evidence_id=str(row["evidence_id"]),
            project_id=str(row["project_id"]),
            entity_type=str(row["entity_type"]),
            record_id=str(row["entity_id"]),
            evidence_type=str(row["evidence_type"]),
            description=str(row["description"]),
            excerpt=None if row["excerpt"] is None else str(row["excerpt"]),
            attachment_id=None if row["attachment_id"] is None else str(row["attachment_id"]),
            attachment_path=None if row.get("relative_path") is None else str(row["relative_path"]),
            media_type=None if row.get("media_type") is None else str(row["media_type"]),
            size_bytes=None if row.get("size_bytes") is None else int(row["size_bytes"]),
            source_origin=str(row["source_origin"]),
            created_at=str(row["created_at"]),
            created_by=str(row["created_by"]),
        )

    def _append_audit(self, evidence: GenericEvidenceRecord, actor_type: str) -> None:
        self._database.connection.execute(
            """
            INSERT INTO audit_log (
              audit_id, project_id, entity_type, entity_id, action, actor_type, actor_id,
              source_origin, request_id, summary, created_at
            ) VALUES (?, ?, ?, ?, 'add_evidence', ?, ?, ?, NULL, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                evidence.project_id,
                evidence.entity_type,
                evidence.record_id,
                actor_type,
                evidence.created_by,
                evidence.source_origin,
                evidence.description,
                utc_now(),
            ),
        )

    def _validate_text(self, field_name: str, value: str) -> None:
        if not str(value).strip():
            raise GenericEvidenceValidationError(f"{field_name} must not be empty")
