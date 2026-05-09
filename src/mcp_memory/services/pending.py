from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any

from mcp_memory.domain.models import utc_now
from mcp_memory.logging_utils import get_logger, log_event
from mcp_memory.storage import Database

from .evidence import EvidenceService
from .functions import FunctionService
from .hypotheses import GlobalHypothesisService
from .relations import RelationService, RelationWrite
from .structures import StructureService


@dataclass(slots=True)
class PendingChangeRecord:
    pending_change_id: str
    project_id: str
    entity_type: str
    entity_id: str
    operation: str
    payload: dict[str, Any]
    status: str
    created_at: str
    created_by: str


class PendingChangeValidationError(ValueError):
    """Raised when a pending change request is invalid."""


class PendingChangeService:
    def __init__(self, database: Database) -> None:
        self._database = database
        self._logger = get_logger("services")

    def create_pending_change(
        self,
        project_id: str,
        entity_type: str,
        entity_id: str,
        operation: str,
        payload: dict[str, Any],
        created_by: str,
    ) -> PendingChangeRecord:
        self._validate_text("project_id", project_id)
        self._validate_text("entity_type", entity_type)
        self._validate_text("entity_id", entity_id)
        self._validate_text("operation", operation)
        self._validate_text("created_by", created_by)

        record = PendingChangeRecord(
            pending_change_id=str(uuid.uuid4()),
            project_id=project_id,
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
        self._append_audit(record, "create_pending", created_by, "manual")
        connection.commit()
        log_event(
            self._logger,
            logging.INFO,
            "pending_created",
            project_id=record.project_id,
            pending_change_id=record.pending_change_id,
            entity_type=record.entity_type,
            entity_id=record.entity_id,
            operation=record.operation,
        )
        return record

    def list_pending_changes(self, project_id: str, status: str | None = "pending") -> list[PendingChangeRecord]:
        params: list[str] = [project_id]
        sql = """
            SELECT *
            FROM pending_changes
            WHERE project_id = ?
        """
        if status is not None:
            params.append(status)
            sql += " AND status = ?"
        sql += " ORDER BY created_at"
        rows = self._database.connection.execute(sql, params).fetchall()
        return [self._row_to_record(row) for row in rows]

    def get_pending_change(self, project_id: str, pending_change_id: str) -> PendingChangeRecord | None:
        row = self._database.connection.execute(
            """
            SELECT *
            FROM pending_changes
            WHERE project_id = ? AND pending_change_id = ?
            """,
            (project_id, pending_change_id),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    def confirm_change(
        self,
        project_id: str,
        pending_change_id: str,
        confirmed_by: str = "system",
        actor_type: str = "system",
    ) -> dict[str, Any]:
        record = self.get_pending_change(project_id, pending_change_id)
        if record is None:
            raise PendingChangeValidationError("pending change not found")
        if record.status != "pending":
            raise PendingChangeValidationError("pending change is not in pending status")

        applied = self._apply_operation(record, actor_type)
        connection = self._database.transaction()
        connection.execute(
            """
            UPDATE pending_changes
            SET status = 'confirmed'
            WHERE project_id = ? AND pending_change_id = ?
            """,
            (project_id, pending_change_id),
        )
        self._append_audit(record, "confirm_pending", confirmed_by, "manual")
        connection.commit()
        log_event(
            self._logger,
            logging.INFO,
            "pending_confirmed",
            project_id=project_id,
            pending_change_id=pending_change_id,
            operation=record.operation,
            actor_type=actor_type,
        )
        return {
            "pending_change": self.get_pending_change(project_id, pending_change_id),
            "applied": applied,
        }

    def reject_change(self, project_id: str, pending_change_id: str, rejected_by: str = "system") -> PendingChangeRecord:
        record = self.get_pending_change(project_id, pending_change_id)
        if record is None:
            raise PendingChangeValidationError("pending change not found")
        if record.status != "pending":
            raise PendingChangeValidationError("pending change is not in pending status")
        connection = self._database.transaction()
        connection.execute(
            """
            UPDATE pending_changes
            SET status = 'rejected'
            WHERE project_id = ? AND pending_change_id = ?
            """,
            (project_id, pending_change_id),
        )
        self._append_audit(record, "reject_pending", rejected_by, "manual")
        connection.commit()
        updated = self.get_pending_change(project_id, pending_change_id)
        if updated is None:
            raise PendingChangeValidationError("pending change not found after reject")
        log_event(
            self._logger,
            logging.WARNING,
            "pending_rejected",
            project_id=project_id,
            pending_change_id=pending_change_id,
            operation=record.operation,
        )
        return updated

    def _apply_operation(self, record: PendingChangeRecord, actor_type: str) -> Any:
        from mcp_memory.services.legacy_payloads import (
            evidence_write_from_payload,
            function_write_from_payload,
            global_hypothesis_write_from_payload,
            structure_write_from_payload,
        )

        if record.operation == "upsert_function":
            return FunctionService(self._database).upsert_function(
                function_write_from_payload(record.project_id, record.payload),
                actor_type=actor_type,
            )
        if record.operation == "upsert_structure":
            return StructureService(self._database).upsert_structure(
                structure_write_from_payload(record.project_id, record.payload),
                actor_type=actor_type,
            )
        if record.operation == "upsert_global_hypothesis":
            return GlobalHypothesisService(self._database).upsert_hypothesis(
                global_hypothesis_write_from_payload(record.project_id, record.payload),
                actor_type=actor_type,
            )
        if record.operation == "create_evidence":
            return EvidenceService(self._database).create_evidence(
                evidence_write_from_payload(record.project_id, record.payload),
                actor_type=actor_type,
            )
        if record.operation == "create_relation":
            return RelationService(self._database).create_relation(
                RelationWrite(
                    project_id=record.project_id,
                    from_entity_type=str(record.payload["from_entity_type"]),
                    from_entity_id=str(record.payload["from_entity_id"]),
                    to_entity_type=str(record.payload["to_entity_type"]),
                    to_entity_id=str(record.payload["to_entity_id"]),
                    relation_type=str(record.payload["relation_type"]),
                    created_by=str(record.payload.get("created_by", "pending-confirm")),
                ),
                actor_type=actor_type,
            )
        raise PendingChangeValidationError(f"unsupported pending operation: {record.operation}")

    def _append_audit(self, record: PendingChangeRecord, action: str, actor_id: str, source_origin: str) -> None:
        self._database.connection.execute(
            """
            INSERT INTO audit_log (
              audit_id, project_id, entity_type, entity_id, action, actor_type, actor_id, source_origin,
              request_id, summary, created_at
            ) VALUES (?, ?, 'pending_change', ?, ?, 'system', ?, ?, NULL, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                record.project_id,
                record.pending_change_id,
                action,
                actor_id,
                source_origin,
                f"{record.operation} -> {record.entity_type}:{record.entity_id}",
                utc_now(),
            ),
        )

    def _row_to_record(self, row: dict[str, object]) -> PendingChangeRecord:
        return PendingChangeRecord(
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

    def _validate_text(self, field_name: str, value: str) -> None:
        if not str(value).strip():
            raise PendingChangeValidationError(f"{field_name} must not be empty")
