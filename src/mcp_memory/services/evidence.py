from __future__ import annotations

import uuid
import logging
from dataclasses import fields

from mcp_memory.domain import EvidenceRecord, EvidenceWrite
from mcp_memory.domain.models import utc_now
from mcp_memory.logging_utils import get_logger, log_event
from mcp_memory.storage import Database


class EvidenceValidationError(ValueError):
    """Raised when an evidence payload breaks local storage rules."""


class EvidenceService:
    def __init__(self, database: Database) -> None:
        self._database = database
        self._logger = get_logger("services")

    def create_evidence(self, payload: EvidenceWrite, actor_type: str = "system", commit: bool = True) -> EvidenceRecord:
        self._validate(payload)
        now = utc_now()
        attachment_id = None
        connection = self._database.transaction()
        if payload.attachment_path:
            attachment_id = str(uuid.uuid4())
            connection.execute(
                """
                INSERT INTO attachments (
                  attachment_id, project_id, relative_path, media_type, size_bytes, created_at, created_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    attachment_id,
                    payload.project_id,
                    payload.attachment_path,
                    payload.media_type,
                    payload.size_bytes,
                    now,
                    payload.created_by,
                ),
            )

        record_payload = {
            field.name: getattr(payload, field.name)
            for field in fields(EvidenceWrite)
        }
        record = EvidenceRecord(
            **record_payload,
            attachment_id=attachment_id,
            created_at=now,
        )
        connection.execute(
            """
            INSERT INTO evidence (
              evidence_id, project_id, entity_type, entity_id, evidence_type, address_start, address_end,
              xref, block_ref, description, excerpt, attachment_id, source_origin, created_at, created_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.evidence_id,
                record.project_id,
                record.entity_type,
                record.entity_id,
                record.evidence_type,
                record.address_start,
                record.address_end,
                record.xref,
                record.block_ref,
                record.description,
                record.excerpt,
                record.attachment_id,
                record.source_origin,
                record.created_at,
                record.created_by,
            ),
        )
        self._append_audit(record, actor_type)
        if commit:
            connection.commit()
        log_event(
            self._logger,
            logging.INFO,
            "evidence_created",
            project_id=record.project_id,
            evidence_id=record.evidence_id,
            entity_type=record.entity_type,
            entity_id=record.entity_id,
            attachment=bool(record.attachment_id),
            actor_type=actor_type,
        )
        return record

    def list_evidence(self, project_id: str, entity_type: str, entity_id: str) -> list[EvidenceRecord]:
        rows = self._database.connection.execute(
            """
            SELECT e.*, a.relative_path, a.media_type, a.size_bytes
            FROM evidence e
            LEFT JOIN attachments a ON a.attachment_id = e.attachment_id
            WHERE e.project_id = ? AND e.entity_type = ? AND e.entity_id = ?
            ORDER BY e.created_at
            """,
            (project_id, entity_type, entity_id),
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def list_project_evidence(self, project_id: str) -> list[EvidenceRecord]:
        rows = self._database.connection.execute(
            """
            SELECT e.*, a.relative_path, a.media_type, a.size_bytes
            FROM evidence e
            LEFT JOIN attachments a ON a.attachment_id = e.attachment_id
            WHERE e.project_id = ?
            ORDER BY e.created_at
            """,
            (project_id,),
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def _append_audit(self, record: EvidenceRecord, actor_type: str) -> None:
        self._database.connection.execute(
            """
            INSERT INTO audit_log (
              audit_id, project_id, entity_type, entity_id, action, actor_type, actor_id, source_origin,
              request_id, summary, created_at
            ) VALUES (?, ?, ?, ?, 'create_evidence', ?, ?, ?, NULL, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                record.project_id,
                record.entity_type,
                record.entity_id,
                actor_type,
                record.created_by,
                record.source_origin,
                record.description[:120],
                record.created_at,
            ),
        )

    def _row_to_record(self, row: dict[str, object]) -> EvidenceRecord:
        return EvidenceRecord(
            project_id=str(row["project_id"]),
            evidence_id=str(row["evidence_id"]),
            entity_type=str(row["entity_type"]),
            entity_id=str(row["entity_id"]),
            evidence_type=str(row["evidence_type"]),
            description=str(row["description"]),
            address_start=None if row["address_start"] is None else str(row["address_start"]),
            address_end=None if row["address_end"] is None else str(row["address_end"]),
            xref=None if row["xref"] is None else str(row["xref"]),
            block_ref=None if row["block_ref"] is None else str(row["block_ref"]),
            excerpt=None if row["excerpt"] is None else str(row["excerpt"]),
            attachment_path=None if row["relative_path"] is None else str(row["relative_path"]),
            media_type=None if row["media_type"] is None else str(row["media_type"]),
            size_bytes=None if row["size_bytes"] is None else int(row["size_bytes"]),
            source_origin=str(row["source_origin"]),
            created_by=str(row["created_by"]),
            attachment_id=None if row["attachment_id"] is None else str(row["attachment_id"]),
            created_at=str(row["created_at"]),
        )

    def _validate(self, payload: EvidenceWrite) -> None:
        required_fields = {
            "project_id": payload.project_id,
            "evidence_id": payload.evidence_id,
            "entity_type": payload.entity_type,
            "entity_id": payload.entity_id,
            "evidence_type": payload.evidence_type,
            "description": payload.description,
            "created_by": payload.created_by,
            "source_origin": payload.source_origin,
        }
        for field_name, value in required_fields.items():
            if not str(value).strip():
                raise EvidenceValidationError(f"{field_name} must not be empty")
        self._bounded_text("description", payload.description, 2048)
        if payload.excerpt:
            self._bounded_text("excerpt", payload.excerpt, 4096)
        if payload.attachment_path:
            self._bounded_text("attachment_path", payload.attachment_path, 1024)
        if payload.size_bytes is not None and payload.size_bytes < 0:
            raise EvidenceValidationError("size_bytes must not be negative")

    def _bounded_text(self, field_name: str, value: str, max_length: int) -> None:
        text = str(value).strip()
        if not text:
            raise EvidenceValidationError(f"{field_name} must not be empty")
        if len(text) > max_length:
            raise EvidenceValidationError(f"{field_name} exceeds max length {max_length}")
