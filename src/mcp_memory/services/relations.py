from __future__ import annotations

import uuid
import logging
from dataclasses import dataclass

from mcp_memory.domain.models import utc_now
from mcp_memory.logging_utils import get_logger, log_event
from mcp_memory.storage import Database


@dataclass(slots=True)
class RelationRecord:
    relation_id: str
    project_id: str
    from_entity_type: str
    from_entity_id: str
    to_entity_type: str
    to_entity_id: str
    relation_type: str
    created_at: str
    created_by: str


@dataclass(slots=True)
class RelationWrite:
    project_id: str
    from_entity_type: str
    from_entity_id: str
    to_entity_type: str
    to_entity_id: str
    relation_type: str
    created_by: str = "system"


class RelationValidationError(ValueError):
    """Raised when a relation payload breaks local storage rules."""


class RelationService:
    def __init__(self, database: Database) -> None:
        self._database = database
        self._logger = get_logger("services")

    def create_relation(self, payload: RelationWrite, actor_type: str = "system") -> RelationRecord:
        self._validate(payload)
        record = RelationRecord(
            relation_id=str(uuid.uuid4()),
            project_id=payload.project_id,
            from_entity_type=payload.from_entity_type,
            from_entity_id=payload.from_entity_id,
            to_entity_type=payload.to_entity_type,
            to_entity_id=payload.to_entity_id,
            relation_type=payload.relation_type,
            created_at=utc_now(),
            created_by=payload.created_by,
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
                record.from_entity_id,
                record.to_entity_type,
                record.to_entity_id,
                record.relation_type,
                record.created_at,
                record.created_by,
            ),
        )
        connection.execute(
            """
            INSERT INTO audit_log (
              audit_id, project_id, entity_type, entity_id, action, actor_type, actor_id, source_origin,
              request_id, summary, created_at
            ) VALUES (?, ?, 'relation', ?, 'create_relation', ?, ?, 'manual', NULL, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                record.project_id,
                record.relation_id,
                actor_type,
                record.created_by,
                f"{record.from_entity_type}:{record.from_entity_id} -> {record.to_entity_type}:{record.to_entity_id}",
                record.created_at,
            ),
        )
        connection.commit()
        log_event(
            self._logger,
            logging.INFO,
            "relation_created",
            project_id=record.project_id,
            relation_id=record.relation_id,
            from_entity_type=record.from_entity_type,
            from_entity_id=record.from_entity_id,
            to_entity_type=record.to_entity_type,
            to_entity_id=record.to_entity_id,
            relation_type=record.relation_type,
            actor_type=actor_type,
        )
        return record

    def list_relations(
        self,
        project_id: str,
        entity_type: str,
        entity_id: str,
        direction: str = "both",
    ) -> list[RelationRecord]:
        clauses: list[str] = []
        params: list[str] = [project_id]
        if direction in ("out", "both"):
            clauses.append("(from_entity_type = ? AND from_entity_id = ?)")
            params.extend([entity_type, entity_id])
        if direction in ("in", "both"):
            clauses.append("(to_entity_type = ? AND to_entity_id = ?)")
            params.extend([entity_type, entity_id])
        if not clauses:
            raise RelationValidationError("direction must be one of: in, out, both")
        sql = f"""
            SELECT *
            FROM relations
            WHERE project_id = ? AND ({' OR '.join(clauses)})
            ORDER BY created_at
        """
        rows = self._database.connection.execute(sql, params).fetchall()
        return [self._row_to_record(row) for row in rows]

    def list_project_relations(self, project_id: str) -> list[RelationRecord]:
        rows = self._database.connection.execute(
            """
            SELECT *
            FROM relations
            WHERE project_id = ?
            ORDER BY created_at
            """,
            (project_id,),
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def traverse_related(
        self,
        project_id: str,
        entity_type: str,
        entity_id: str,
        hops: int = 1,
    ) -> list[dict[str, str]]:
        if hops not in (1, 2):
            raise RelationValidationError("hops must be 1 or 2")
        seen: set[tuple[str, str]] = {(entity_type, entity_id)}
        frontier = [(entity_type, entity_id)]
        collected: list[dict[str, str]] = []
        for depth in range(hops):
            next_frontier: list[tuple[str, str]] = []
            for current_type, current_id in frontier:
                for relation in self.list_relations(project_id, current_type, current_id, direction="both"):
                    if relation.from_entity_type == current_type and relation.from_entity_id == current_id:
                        target = (relation.to_entity_type, relation.to_entity_id)
                    else:
                        target = (relation.from_entity_type, relation.from_entity_id)
                    if target in seen:
                        continue
                    seen.add(target)
                    next_frontier.append(target)
                    collected.append(
                        {
                            "entity_type": target[0],
                            "entity_id": target[1],
                            "via_relation_type": relation.relation_type,
                            "hop": str(depth + 1),
                        }
                    )
            frontier = next_frontier
        return collected

    def _row_to_record(self, row: dict[str, object]) -> RelationRecord:
        return RelationRecord(
            relation_id=str(row["relation_id"]),
            project_id=str(row["project_id"]),
            from_entity_type=str(row["from_entity_type"]),
            from_entity_id=str(row["from_entity_id"]),
            to_entity_type=str(row["to_entity_type"]),
            to_entity_id=str(row["to_entity_id"]),
            relation_type=str(row["relation_type"]),
            created_at=str(row["created_at"]),
            created_by=str(row["created_by"]),
        )

    def _validate(self, payload: RelationWrite) -> None:
        required = {
            "project_id": payload.project_id,
            "from_entity_type": payload.from_entity_type,
            "from_entity_id": payload.from_entity_id,
            "to_entity_type": payload.to_entity_type,
            "to_entity_id": payload.to_entity_id,
            "relation_type": payload.relation_type,
            "created_by": payload.created_by,
        }
        for field_name, value in required.items():
            if not str(value).strip():
                raise RelationValidationError(f"{field_name} must not be empty")
