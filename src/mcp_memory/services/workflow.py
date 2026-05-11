from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any

from mcp_memory.config import ProjectConfig
from mcp_memory.domain.models import utc_now
from mcp_memory.logging_utils import get_logger, log_event
from mcp_memory.storage import Database


class GenericPendingValidationError(ValueError):
    """Raised when a generic pending change is invalid."""


@dataclass(slots=True)
class GenericPendingChangeRecord:
    pending_change_id: str
    project_id: str
    entity_type: str
    entity_id: str
    operation: str
    payload: dict[str, Any]
    status: str
    created_at: str
    created_by: str


class GenericWorkflowService:
    def __init__(self, database: Database, project: ProjectConfig) -> None:
        self._database = database
        self._project = project
        self._logger = get_logger("services")

    def apply_or_queue(self, operation: str, payload: dict[str, Any], created_by: str = "system") -> Any:
        if self._project.write_mode == "confirm":
            return self.create_pending_change(operation, payload, created_by=created_by)
        return self._apply_operation(operation, payload, actor_type="system")

    def create_pending_change(self, operation: str, payload: dict[str, Any], created_by: str = "system") -> GenericPendingChangeRecord:
        if operation not in {"upsert_record", "archive_record", "create_relation", "add_evidence"}:
            raise GenericPendingValidationError(f"unsupported pending operation: {operation}")
        entity_type, entity_id = self._pending_subject(operation, payload)
        if not str(created_by).strip():
            raise GenericPendingValidationError("created_by must not be empty")
        record = GenericPendingChangeRecord(
            pending_change_id=str(uuid.uuid4()),
            project_id=self._project.project_id,
            entity_type=entity_type,
            entity_id=entity_id,
            operation=operation,
            payload=payload,
            status="pending",
            created_at=utc_now(),
            created_by=created_by,
        )
        connection = self._database.transaction()
        connection.execute(
            """
            INSERT INTO pending_changes (
              pending_change_id, project_id, entity_type, entity_id, operation, payload_json,
              status, created_at, created_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.pending_change_id,
                record.project_id,
                record.entity_type,
                record.entity_id,
                record.operation,
                json.dumps(record.payload, ensure_ascii=False),
                record.status,
                record.created_at,
                record.created_by,
            ),
        )
        self._append_audit(record, "create_pending", created_by)
        connection.commit()
        log_event(
            self._logger,
            logging.INFO,
            "generic_pending_created",
            project_id=record.project_id,
            pending_change_id=record.pending_change_id,
            operation=record.operation,
        )
        return record

    def list_pending_changes(self, status: str | None = "pending") -> list[GenericPendingChangeRecord]:
        params: list[Any] = [self._project.project_id]
        sql = "SELECT * FROM pending_changes WHERE project_id = ?"
        if status is not None:
            params.append(status)
            sql += " AND status = ?"
        sql += " ORDER BY created_at"
        rows = self._database.connection.execute(sql, params).fetchall()
        return [self._row_to_record(row) for row in rows]

    def confirm_change(self, pending_change_id: str, confirmed_by: str = "system", actor_type: str = "system") -> dict[str, Any]:
        record = self.get_pending_change(pending_change_id)
        if record is None:
            raise GenericPendingValidationError("pending change not found")
        if record.status != "pending":
            raise GenericPendingValidationError("pending change is not in pending status")
        connection = self._database.transaction()
        try:
            applied = self._apply_operation(record.operation, record.payload, actor_type=actor_type, commit=False)
            connection.execute(
                "UPDATE pending_changes SET status = 'confirmed' WHERE project_id = ? AND pending_change_id = ?",
                (self._project.project_id, pending_change_id),
            )
            self._append_audit(record, "confirm_pending", confirmed_by)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        return {"pending_change": self.get_pending_change(pending_change_id), "applied": applied.data}

    def reject_change(self, pending_change_id: str, rejected_by: str = "system") -> GenericPendingChangeRecord:
        record = self.get_pending_change(pending_change_id)
        if record is None:
            raise GenericPendingValidationError("pending change not found")
        if record.status != "pending":
            raise GenericPendingValidationError("pending change is not in pending status")
        connection = self._database.transaction()
        connection.execute(
            "UPDATE pending_changes SET status = 'rejected' WHERE project_id = ? AND pending_change_id = ?",
            (self._project.project_id, pending_change_id),
        )
        self._append_audit(record, "reject_pending", rejected_by)
        connection.commit()
        updated = self.get_pending_change(pending_change_id)
        if updated is None:
            raise GenericPendingValidationError("pending change not found after reject")
        return updated

    def get_pending_change(self, pending_change_id: str) -> GenericPendingChangeRecord | None:
        row = self._database.connection.execute(
            "SELECT * FROM pending_changes WHERE project_id = ? AND pending_change_id = ?",
            (self._project.project_id, pending_change_id),
        ).fetchone()
        return None if row is None else self._row_to_record(row)

    def _apply_operation(self, operation: str, payload: dict[str, Any], actor_type: str, commit: bool = True) -> Any:
        from mcp_memory.protocol import (
            AddEvidenceCommand,
            ArchiveRecordCommand,
            CreateRelationCommand,
            ProjectDispatcher,
            UpsertRecordCommand,
        )

        dispatcher = ProjectDispatcher(self._database, self._project)
        if operation == "upsert_record":
            return dispatcher.dispatch(
                UpsertRecordCommand(
                    entity_type=str(payload["entity_type"]),
                    record_id=None if payload.get("record_id") is None else str(payload["record_id"]),
                    payload=dict(payload["payload"]),
                    source_origin=str(payload.get("source_origin", "pending")),
                    created_by=str(payload.get("created_by", "pending")),
                    updated_by=str(payload.get("updated_by", payload.get("created_by", "pending"))),
                    actor_type=actor_type,
                    commit=commit,
                )
            )
        if operation == "archive_record":
            return dispatcher.dispatch(
                ArchiveRecordCommand(
                    entity_type=str(payload["entity_type"]),
                    record_id_or_slug=str(payload["record_id_or_slug"]),
                    archived_by=str(payload.get("archived_by", "pending")),
                    actor_type=actor_type,
                    commit=commit,
                )
            )
        if operation == "create_relation":
            return dispatcher.dispatch(
                CreateRelationCommand(
                    from_entity_type=str(payload["from_entity_type"]),
                    from_record_id=str(payload["from_record_id"]),
                    to_entity_type=str(payload["to_entity_type"]),
                    to_record_id=str(payload["to_record_id"]),
                    relation_type=str(payload["relation_type"]),
                    created_by=str(payload.get("created_by", "pending")),
                    actor_type=actor_type,
                    commit=commit,
                )
            )
        if operation == "add_evidence":
            return dispatcher.dispatch(
                AddEvidenceCommand(
                    entity_type=str(payload["entity_type"]),
                    record_id=str(payload["record_id"]),
                    evidence_type=str(payload["evidence_type"]),
                    description=str(payload["description"]),
                    evidence_id=None if payload.get("evidence_id") is None else str(payload["evidence_id"]),
                    excerpt=None if payload.get("excerpt") is None else str(payload["excerpt"]),
                    attachment_path=None if payload.get("attachment_path") is None else str(payload["attachment_path"]),
                    media_type=None if payload.get("media_type") is None else str(payload["media_type"]),
                    size_bytes=None if payload.get("size_bytes") is None else int(payload["size_bytes"]),
                    created_by=str(payload.get("created_by", "pending")),
                    source_origin=str(payload.get("source_origin", "pending")),
                    actor_type=actor_type,
                    commit=commit,
                )
            )
        raise GenericPendingValidationError(f"unsupported pending operation: {operation}")

    def _pending_subject(self, operation: str, payload: dict[str, Any]) -> tuple[str, str]:
        if operation == "upsert_record":
            return str(payload["entity_type"]), str(payload.get("record_id") or payload.get("payload", {}).get("slug") or "<new>")
        if operation == "archive_record":
            return str(payload["entity_type"]), str(payload["record_id_or_slug"])
        if operation == "create_relation":
            return "relation", f"{payload['from_entity_type']}:{payload['from_record_id']}->{payload['to_entity_type']}:{payload['to_record_id']}"
        if operation == "add_evidence":
            return str(payload["entity_type"]), str(payload["record_id"])
        raise GenericPendingValidationError(f"unsupported pending operation: {operation}")

    def _append_audit(self, record: GenericPendingChangeRecord, action: str, actor_id: str) -> None:
        self._database.connection.execute(
            """
            INSERT INTO audit_log (
              audit_id, project_id, entity_type, entity_id, action, actor_type, actor_id,
              source_origin, request_id, summary, created_at
            ) VALUES (?, ?, 'pending_change', ?, ?, 'system', ?, 'manual', NULL, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                record.project_id,
                record.pending_change_id,
                action,
                actor_id,
                f"{record.operation} -> {record.entity_type}:{record.entity_id}",
                utc_now(),
            ),
        )

    def _row_to_record(self, row: dict[str, Any]) -> GenericPendingChangeRecord:
        return GenericPendingChangeRecord(
            pending_change_id=str(row["pending_change_id"]),
            project_id=str(row["project_id"]),
            entity_type=str(row["entity_type"]),
            entity_id=str(row["entity_id"]),
            operation=str(row["operation"]),
            payload=json.loads(str(row["payload_json"])),
            status=str(row["status"]),
            created_at=str(row["created_at"]),
            created_by=str(row["created_by"]),
        )
