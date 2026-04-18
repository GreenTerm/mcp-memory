from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict, fields

from mcp_memory.domain import HypothesisItem, HypothesisStatus, ObservedFact, StructureMember, StructureRecord, StructureWrite
from mcp_memory.domain.models import utc_now
from mcp_memory.logging_utils import get_logger, log_event
from mcp_memory.storage import Database


class StructureValidationError(ValueError):
    """Raised when a structure payload breaks local storage rules."""


class StructureService:
    def __init__(self, database: Database) -> None:
        self._database = database
        self._logger = get_logger("services")

    def upsert_structure(self, payload: StructureWrite, actor_type: str = "system") -> StructureRecord:
        self._validate(payload)
        existing = self.get_structure(payload.project_id, payload.structure_id)
        now = utc_now()
        record_payload = {
            field.name: getattr(payload, field.name)
            for field in fields(StructureWrite)
        }
        record = StructureRecord(
            **record_payload,
            created_at=existing.created_at if existing else now,
            updated_at=now,
        )

        connection = self._database.transaction()
        connection.execute(
            """
            INSERT INTO structures (
              project_id, binary_id, structure_id, raw_name, current_name, summary, fields_json,
              source_origin, created_at, updated_at, created_by, updated_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_id, structure_id) DO UPDATE SET
              binary_id=excluded.binary_id,
              raw_name=excluded.raw_name,
              current_name=excluded.current_name,
              summary=excluded.summary,
              fields_json=excluded.fields_json,
              source_origin=excluded.source_origin,
              updated_at=excluded.updated_at,
              updated_by=excluded.updated_by
            """,
            (
                record.project_id,
                record.binary_id,
                record.structure_id,
                record.raw_name,
                record.current_name,
                record.summary,
                json.dumps([asdict(item) for item in record.fields], ensure_ascii=False),
                record.source_origin,
                record.created_at,
                record.updated_at,
                record.created_by,
                record.updated_by,
            ),
        )
        self._replace_facts(record.project_id, record.structure_id, record.observed_facts, record.updated_at, record.updated_by)
        self._replace_hypotheses(record, record.updated_at)
        self._replace_tags(record.project_id, "structure", record.structure_id, record.tags, record.updated_at)
        self._upsert_search_document(record)
        self._append_version(record)
        self._append_audit(record, actor_type)
        connection.commit()
        log_event(
            self._logger,
            logging.INFO,
            "structure_upserted",
            project_id=record.project_id,
            binary_id=record.binary_id,
            structure_id=record.structure_id,
            field_count=len(record.fields),
            actor_type=actor_type,
        )
        return record

    def get_structure(self, project_id: str, structure_id: str) -> StructureRecord | None:
        row = self._database.connection.execute(
            """
            SELECT *
            FROM structures
            WHERE project_id = ? AND structure_id = ?
            """,
            (project_id, structure_id),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    def list_structures(self, project_id: str, binary_id: str | None = None) -> list[StructureRecord]:
        if binary_id is None:
            rows = self._database.connection.execute(
                "SELECT * FROM structures WHERE project_id = ? ORDER BY current_name",
                (project_id,),
            ).fetchall()
        else:
            rows = self._database.connection.execute(
                "SELECT * FROM structures WHERE project_id = ? AND binary_id = ? ORDER BY current_name",
                (project_id, binary_id),
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def list_project_structures(self, project_id: str) -> list[StructureRecord]:
        rows = self._database.connection.execute(
            "SELECT * FROM structures WHERE project_id = ? ORDER BY binary_id, current_name",
            (project_id,),
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def _replace_facts(
        self,
        project_id: str,
        structure_id: str,
        facts: list[ObservedFact],
        created_at: str,
        created_by: str,
    ) -> None:
        self._database.connection.execute(
            "DELETE FROM entity_facts WHERE project_id = ? AND entity_type = 'structure' AND entity_id = ?",
            (project_id, structure_id),
        )
        for fact in facts:
            self._database.connection.execute(
                """
                INSERT INTO entity_facts (
                  fact_id, project_id, entity_type, entity_id, fact_text, source_origin, created_at, created_by
                ) VALUES (?, ?, 'structure', ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    project_id,
                    structure_id,
                    fact.fact,
                    fact.source_origin,
                    created_at,
                    created_by,
                ),
            )

    def _replace_hypotheses(self, record: StructureRecord, updated_at: str) -> None:
        self._database.connection.execute(
            """
            DELETE FROM hypotheses
            WHERE project_id = ? AND subject_entity_type = 'structure' AND subject_entity_id = ?
            """,
            (record.project_id, record.structure_id),
        )
        for item in record.hypotheses:
            self._database.connection.execute(
                """
                INSERT INTO hypotheses (
                  hypothesis_id, project_id, binary_id, subject_entity_type, subject_entity_id, title,
                  statement, status, confidence, source_origin, created_at, updated_at, created_by, updated_by
                ) VALUES (?, ?, ?, 'structure', ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    record.project_id,
                    record.binary_id,
                    record.structure_id,
                    item.statement,
                    item.status.value,
                    item.confidence,
                    item.source_origin,
                    updated_at,
                    updated_at,
                    record.updated_by,
                    record.updated_by,
                ),
            )

    def _replace_tags(self, project_id: str, entity_type: str, entity_id: str, tags: list[str], created_at: str) -> None:
        self._database.connection.execute(
            "DELETE FROM entity_tags WHERE project_id = ? AND entity_type = ? AND entity_id = ?",
            (project_id, entity_type, entity_id),
        )
        for tag in sorted(set(tags)):
            self._database.connection.execute(
                "INSERT OR IGNORE INTO tags(project_id, tag_name, created_at) VALUES (?, ?, ?)",
                (project_id, tag, created_at),
            )
            self._database.connection.execute(
                """
                INSERT INTO entity_tags(project_id, entity_type, entity_id, tag_name, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (project_id, entity_type, entity_id, tag, created_at),
            )

    def _upsert_search_document(self, record: StructureRecord) -> None:
        document_id = f"structure:{record.project_id}:{record.structure_id}"
        tag_text = " ".join(sorted(set(record.tags)))
        body_text = " ".join(
            filter(
                None,
                [
                    record.summary,
                    " ".join(f"{item.name} {item.offset} {item.data_type} {item.comment}".strip() for item in record.fields),
                    " ".join(fact.fact for fact in record.observed_facts),
                    " ".join(item.statement for item in record.hypotheses),
                ],
            )
        )
        self._database.connection.execute(
            """
            INSERT INTO search_documents (
              document_id, project_id, entity_type, entity_id, title_text, body_text, tag_text, address_text, updated_at
            ) VALUES (?, ?, 'structure', ?, ?, ?, ?, '', ?)
            ON CONFLICT(document_id) DO UPDATE SET
              title_text=excluded.title_text,
              body_text=excluded.body_text,
              tag_text=excluded.tag_text,
              updated_at=excluded.updated_at
            """,
            (
                document_id,
                record.project_id,
                record.structure_id,
                f"{record.current_name} {record.raw_name}",
                body_text,
                tag_text,
                record.updated_at,
            ),
        )
        self._database.connection.execute("DELETE FROM search_documents_fts WHERE document_id = ?", (document_id,))
        self._database.connection.execute(
            """
            INSERT INTO search_documents_fts(
              document_id, project_id, entity_type, entity_id, title_text, body_text, tag_text, address_text
            ) VALUES (?, ?, 'structure', ?, ?, ?, ?, '')
            """,
            (
                document_id,
                record.project_id,
                record.structure_id,
                f"{record.current_name} {record.raw_name}",
                body_text,
                tag_text,
            ),
        )

    def _append_version(self, record: StructureRecord) -> None:
        next_version = self._database.connection.execute(
            """
            SELECT COALESCE(MAX(version_number), 0) + 1 AS next_version
            FROM entity_versions
            WHERE project_id = ? AND entity_type = 'structure' AND entity_id = ?
            """,
            (record.project_id, record.structure_id),
        ).fetchone()["next_version"]
        self._database.connection.execute(
            """
            INSERT INTO entity_versions (
              version_id, project_id, entity_type, entity_id, version_number, snapshot_json, created_at, created_by
            ) VALUES (?, ?, 'structure', ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                record.project_id,
                record.structure_id,
                next_version,
                json.dumps(asdict(record), ensure_ascii=False),
                record.updated_at,
                record.updated_by,
            ),
        )

    def _append_audit(self, record: StructureRecord, actor_type: str) -> None:
        self._database.connection.execute(
            """
            INSERT INTO audit_log (
              audit_id, project_id, entity_type, entity_id, action, actor_type, actor_id, source_origin,
              request_id, summary, created_at
            ) VALUES (?, ?, 'structure', ?, 'upsert', ?, ?, ?, NULL, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                record.project_id,
                record.structure_id,
                actor_type,
                record.updated_by,
                record.source_origin,
                record.current_name,
                record.updated_at,
            ),
        )

    def _row_to_record(self, row: dict[str, object]) -> StructureRecord:
        facts_rows = self._database.connection.execute(
            """
            SELECT fact_text, source_origin
            FROM entity_facts
            WHERE project_id = ? AND entity_type = 'structure' AND entity_id = ?
            ORDER BY created_at
            """,
            (row["project_id"], row["structure_id"]),
        ).fetchall()
        hypotheses_rows = self._database.connection.execute(
            """
            SELECT statement, status, confidence, source_origin
            FROM hypotheses
            WHERE project_id = ? AND subject_entity_type = 'structure' AND subject_entity_id = ?
            ORDER BY created_at
            """,
            (row["project_id"], row["structure_id"]),
        ).fetchall()
        tags_rows = self._database.connection.execute(
            """
            SELECT tag_name
            FROM entity_tags
            WHERE project_id = ? AND entity_type = 'structure' AND entity_id = ?
            ORDER BY tag_name
            """,
            (row["project_id"], row["structure_id"]),
        ).fetchall()
        return StructureRecord(
            project_id=str(row["project_id"]),
            binary_id=str(row["binary_id"]),
            structure_id=str(row["structure_id"]),
            raw_name=str(row["raw_name"]),
            current_name=str(row["current_name"]),
            summary=str(row["summary"]),
            fields=[
                StructureMember(
                    name=str(item["name"]),
                    offset=str(item["offset"]),
                    data_type=str(item["data_type"]),
                    size=item.get("size"),
                    comment=str(item.get("comment", "")),
                )
                for item in json.loads(str(row["fields_json"]))
            ],
            tags=[str(item["tag_name"]) for item in tags_rows],
            observed_facts=[
                ObservedFact(fact=str(item["fact_text"]), source_origin=str(item["source_origin"]))
                for item in facts_rows
            ],
            hypotheses=[
                HypothesisItem(
                    statement=str(item["statement"]),
                    status=HypothesisStatus(str(item["status"])),
                    confidence=item["confidence"] if item["confidence"] is None else float(item["confidence"]),
                    source_origin=str(item["source_origin"]),
                )
                for item in hypotheses_rows
            ],
            evidence_refs=[],
            source_origin=str(row["source_origin"]),
            created_by=str(row["created_by"]),
            updated_by=str(row["updated_by"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    def _validate(self, payload: StructureWrite) -> None:
        required_fields = {
            "project_id": payload.project_id,
            "binary_id": payload.binary_id,
            "structure_id": payload.structure_id,
            "raw_name": payload.raw_name,
            "current_name": payload.current_name,
            "summary": payload.summary,
            "created_by": payload.created_by,
            "updated_by": payload.updated_by,
            "source_origin": payload.source_origin,
        }
        for field_name, value in required_fields.items():
            if not str(value).strip():
                raise StructureValidationError(f"{field_name} must not be empty")
        if len(payload.tags) > 100:
            raise StructureValidationError("tags exceed the maximum size of 100")
        if len(payload.observed_facts) > 100:
            raise StructureValidationError("observed_facts exceed the maximum size of 100")
        if len(payload.hypotheses) > 100:
            raise StructureValidationError("hypotheses exceed the maximum size of 100")
        self._bounded_text("summary", payload.summary, 4096)
        for item in payload.fields:
            self._bounded_text("field name", item.name, 128)
            self._bounded_text("field offset", item.offset, 64)
            self._bounded_text("field data_type", item.data_type, 128)
            if item.comment:
                self._bounded_text("field comment", item.comment, 512)
        for fact in payload.observed_facts:
            self._bounded_text("observed fact", fact.fact, 2048)
        for item in payload.hypotheses:
            self._bounded_text("hypothesis", item.statement, 2048)
            if item.confidence is not None and not 0.0 <= item.confidence <= 1.0:
                raise StructureValidationError("hypothesis confidence must be within [0.0, 1.0]")

    def _bounded_text(self, field_name: str, value: str, max_length: int) -> None:
        text = str(value).strip()
        if not text:
            raise StructureValidationError(f"{field_name} must not be empty")
        if len(text) > max_length:
            raise StructureValidationError(f"{field_name} exceeds max length {max_length}")
