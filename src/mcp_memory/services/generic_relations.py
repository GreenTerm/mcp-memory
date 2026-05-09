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


class GenericRelationValidationError(ValueError):
    """Raised when a generic relation request is invalid."""


@dataclass(slots=True)
class GenericRelationWrite:
    from_entity_type: str
    from_record_id: str
    to_entity_type: str
    to_record_id: str
    relation_type: str
    created_by: str = "system"


@dataclass(slots=True)
class GenericRelationRecord:
    relation_id: str
    project_id: str
    from_entity_type: str
    from_record_id: str
    to_entity_type: str
    to_record_id: str
    relation_type: str
    created_at: str
    created_by: str


class GenericRelationService:
    def __init__(self, database: Database, project: ProjectConfig) -> None:
        self._database = database
        self._project = project
        self._schema = load_project_schema(project.schema_path)
        self._records = RecordService(database, project)
        self._logger = get_logger("services")

    def create_relation(self, write: GenericRelationWrite, actor_type: str = "system") -> GenericRelationRecord:
        relation_type = self._relation_type(write.relation_type)
        if not relation_type.allows(write.from_entity_type, write.to_entity_type):
            raise GenericRelationValidationError(
                f"{write.relation_type} does not allow {write.from_entity_type} -> {write.to_entity_type}"
            )
        from_record = self._records.get_record(write.from_entity_type, write.from_record_id)
        to_record = self._records.get_record(write.to_entity_type, write.to_record_id)
        if from_record is None:
            raise GenericRelationValidationError("from record not found")
        if to_record is None:
            raise GenericRelationValidationError("to record not found")

        record = GenericRelationRecord(
            relation_id=str(uuid.uuid4()),
            project_id=self._project.project_id,
            from_entity_type=write.from_entity_type,
            from_record_id=from_record.record_id,
            to_entity_type=write.to_entity_type,
            to_record_id=to_record.record_id,
            relation_type=write.relation_type,
            created_at=utc_now(),
            created_by=write.created_by,
        )
        connection = self._database.transaction()
        connection.execute(
            """
            INSERT INTO relations (
              relation_id, project_id, from_entity_type, from_entity_id, to_entity_type, to_entity_id,
              relation_type, created_at, created_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.relation_id,
                record.project_id,
                record.from_entity_type,
                record.from_record_id,
                record.to_entity_type,
                record.to_record_id,
                record.relation_type,
                record.created_at,
                record.created_by,
            ),
        )
        self._append_audit(record, actor_type)
        connection.commit()
        log_event(
            self._logger,
            logging.INFO,
            "generic_relation_created",
            project_id=record.project_id,
            relation_id=record.relation_id,
            relation_type=record.relation_type,
        )
        return record

    def list_relations(
        self,
        entity_type: str | None = None,
        record_id_or_slug: str | None = None,
        direction: str = "both",
    ) -> list[GenericRelationRecord]:
        if direction not in {"in", "out", "both"}:
            raise GenericRelationValidationError("direction must be one of: in, out, both")
        params: list[Any] = [self._project.project_id]
        filters = ["project_id = ?"]
        if entity_type and record_id_or_slug:
            record = self._records.get_record(entity_type, record_id_or_slug, include_archived=True)
            if record is None:
                raise GenericRelationValidationError("record not found")
            if direction == "out":
                filters.append("from_entity_type = ? AND from_entity_id = ?")
                params.extend([entity_type, record.record_id])
            elif direction == "in":
                filters.append("to_entity_type = ? AND to_entity_id = ?")
                params.extend([entity_type, record.record_id])
            else:
                filters.append("((from_entity_type = ? AND from_entity_id = ?) OR (to_entity_type = ? AND to_entity_id = ?))")
                params.extend([entity_type, record.record_id, entity_type, record.record_id])
        rows = self._database.connection.execute(
            f"""
            SELECT *
            FROM relations
            WHERE {' AND '.join(filters)}
            ORDER BY created_at DESC
            """,
            params,
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def traverse_related(self, entity_type: str, record_id_or_slug: str, hops: int = 1) -> list[dict[str, Any]]:
        if hops not in {1, 2}:
            raise GenericRelationValidationError("hops must be 1 or 2")
        start = self._records.get_record(entity_type, record_id_or_slug)
        if start is None:
            raise GenericRelationValidationError("record not found")
        seen: set[tuple[str, str]] = {(start.entity_type, start.record_id)}
        frontier = [(start.entity_type, start.record_id)]
        related: list[dict[str, Any]] = []
        for _ in range(hops):
            next_frontier: list[tuple[str, str]] = []
            for current_type, current_id in frontier:
                for relation in self.list_relations(current_type, current_id):
                    candidates = [
                        (relation.from_entity_type, relation.from_record_id),
                        (relation.to_entity_type, relation.to_record_id),
                    ]
                    for candidate_type, candidate_id in candidates:
                        key = (candidate_type, candidate_id)
                        if key in seen:
                            continue
                        seen.add(key)
                        record = self._records.get_record(candidate_type, candidate_id)
                        if record is None:
                            continue
                        next_frontier.append(key)
                        relation_type = self._relation_type(relation.relation_type)
                        relation_direction = "out" if key == (relation.to_entity_type, relation.to_record_id) else "in"
                        related.append(
                            {
                                "entity_type": candidate_type,
                                "record_id": candidate_id,
                                "title": None if record is None else record.title,
                                "relation_type": relation.relation_type,
                                "relation_directed": relation_type.directed,
                                "relation_direction": relation_direction,
                                "from_entity_type": relation.from_entity_type,
                                "from_record_id": relation.from_record_id,
                                "to_entity_type": relation.to_entity_type,
                                "to_record_id": relation.to_record_id,
                            }
                        )
            frontier = next_frontier
        return related

    def _relation_type(self, relation_type: str):
        try:
            return self._schema.relation(relation_type)
        except SchemaValidationError as exc:
            raise GenericRelationValidationError(str(exc)) from exc

    def _row_to_record(self, row: dict[str, Any]) -> GenericRelationRecord:
        return GenericRelationRecord(
            relation_id=str(row["relation_id"]),
            project_id=str(row["project_id"]),
            from_entity_type=str(row["from_entity_type"]),
            from_record_id=str(row["from_entity_id"]),
            to_entity_type=str(row["to_entity_type"]),
            to_record_id=str(row["to_entity_id"]),
            relation_type=str(row["relation_type"]),
            created_at=str(row["created_at"]),
            created_by=str(row["created_by"]),
        )

    def _append_audit(self, record: GenericRelationRecord, actor_type: str) -> None:
        self._database.connection.execute(
            """
            INSERT INTO audit_log (
              audit_id, project_id, entity_type, entity_id, action, actor_type, actor_id,
              source_origin, request_id, summary, created_at
            ) VALUES (?, ?, 'relation', ?, 'create_relation', ?, ?, 'manual', NULL, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                record.project_id,
                record.relation_id,
                actor_type,
                record.created_by,
                f"{record.from_entity_type}:{record.from_record_id} -> {record.to_entity_type}:{record.to_record_id}",
                utc_now(),
            ),
        )
