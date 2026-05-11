from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict, fields

from mcp_memory.domain import GlobalHypothesisRecord, GlobalHypothesisWrite, HypothesisStatus, ObservedFact
from mcp_memory.domain.models import utc_now
from mcp_memory.logging_utils import get_logger, log_event
from mcp_memory.storage import Database


class GlobalHypothesisValidationError(ValueError):
    """Raised when a global hypothesis payload breaks local storage rules."""


class GlobalHypothesisService:
    def __init__(self, database: Database) -> None:
        self._database = database
        self._logger = get_logger("services")

    def upsert_hypothesis(
        self,
        payload: GlobalHypothesisWrite,
        actor_type: str = "system",
        commit: bool = True,
    ) -> GlobalHypothesisRecord:
        self._validate(payload)
        existing = self.get_hypothesis(payload.project_id, payload.hypothesis_id)
        now = utc_now()
        record_payload = {
            field.name: getattr(payload, field.name)
            for field in fields(GlobalHypothesisWrite)
        }
        record = GlobalHypothesisRecord(
            **record_payload,
            created_at=existing.created_at if existing else now,
            updated_at=now,
        )
        connection = self._database.transaction()
        connection.execute(
            """
            INSERT INTO hypotheses (
              hypothesis_id, project_id, binary_id, subject_entity_type, subject_entity_id, title,
              statement, status, confidence, source_origin, created_at, updated_at, created_by, updated_by
            ) VALUES (?, ?, ?, NULL, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(hypothesis_id) DO UPDATE SET
              binary_id=excluded.binary_id,
              title=excluded.title,
              statement=excluded.statement,
              status=excluded.status,
              confidence=excluded.confidence,
              source_origin=excluded.source_origin,
              updated_at=excluded.updated_at,
              updated_by=excluded.updated_by
            """,
            (
                record.hypothesis_id,
                record.project_id,
                record.binary_id,
                record.title,
                record.statement,
                record.status.value,
                record.confidence,
                record.source_origin,
                record.created_at,
                record.updated_at,
                record.created_by,
                record.updated_by,
            ),
        )
        self._replace_facts(record.project_id, record.hypothesis_id, record.observed_facts, record.updated_at, record.updated_by)
        self._replace_tags(record.project_id, record.hypothesis_id, record.tags, record.updated_at)
        self._upsert_search_document(record)
        self._append_version(record)
        self._append_audit(record, actor_type)
        if commit:
            connection.commit()
        log_event(
            self._logger,
            logging.INFO,
            "global_hypothesis_upserted",
            project_id=record.project_id,
            hypothesis_id=record.hypothesis_id,
            status=record.status.value,
            actor_type=actor_type,
        )
        return record

    def get_hypothesis(self, project_id: str, hypothesis_id: str) -> GlobalHypothesisRecord | None:
        row = self._database.connection.execute(
            """
            SELECT *
            FROM hypotheses
            WHERE project_id = ? AND hypothesis_id = ? AND subject_entity_type IS NULL
            """,
            (project_id, hypothesis_id),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    def list_hypotheses(self, project_id: str) -> list[GlobalHypothesisRecord]:
        rows = self._database.connection.execute(
            """
            SELECT *
            FROM hypotheses
            WHERE project_id = ? AND subject_entity_type IS NULL
            ORDER BY updated_at DESC
            """,
            (project_id,),
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def _replace_facts(
        self,
        project_id: str,
        hypothesis_id: str,
        facts: list[ObservedFact],
        created_at: str,
        created_by: str,
    ) -> None:
        self._database.connection.execute(
            "DELETE FROM entity_facts WHERE project_id = ? AND entity_type = 'global_hypothesis' AND entity_id = ?",
            (project_id, hypothesis_id),
        )
        for fact in facts:
            self._database.connection.execute(
                """
                INSERT INTO entity_facts (
                  fact_id, project_id, entity_type, entity_id, fact_text, source_origin, created_at, created_by
                ) VALUES (?, ?, 'global_hypothesis', ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    project_id,
                    hypothesis_id,
                    fact.fact,
                    fact.source_origin,
                    created_at,
                    created_by,
                ),
            )

    def _replace_tags(self, project_id: str, hypothesis_id: str, tags: list[str], created_at: str) -> None:
        self._database.connection.execute(
            "DELETE FROM entity_tags WHERE project_id = ? AND entity_type = 'global_hypothesis' AND entity_id = ?",
            (project_id, hypothesis_id),
        )
        for tag in sorted(set(tags)):
            self._database.connection.execute(
                "INSERT OR IGNORE INTO tags(project_id, tag_name, created_at) VALUES (?, ?, ?)",
                (project_id, tag, created_at),
            )
            self._database.connection.execute(
                """
                INSERT INTO entity_tags(project_id, entity_type, entity_id, tag_name, created_at)
                VALUES (?, 'global_hypothesis', ?, ?, ?)
                """,
                (project_id, hypothesis_id, tag, created_at),
            )

    def _upsert_search_document(self, record: GlobalHypothesisRecord) -> None:
        document_id = f"global_hypothesis:{record.project_id}:{record.hypothesis_id}"
        tag_text = " ".join(sorted(set(record.tags)))
        body_text = " ".join(filter(None, [record.statement, " ".join(f.fact for f in record.observed_facts)]))
        self._database.connection.execute(
            """
            INSERT INTO search_documents (
              document_id, project_id, entity_type, entity_id, title_text, body_text, tag_text, address_text, updated_at
            ) VALUES (?, ?, 'global_hypothesis', ?, ?, ?, ?, '', ?)
            ON CONFLICT(document_id) DO UPDATE SET
              title_text=excluded.title_text,
              body_text=excluded.body_text,
              tag_text=excluded.tag_text,
              updated_at=excluded.updated_at
            """,
            (
                document_id,
                record.project_id,
                record.hypothesis_id,
                record.title,
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
            ) VALUES (?, ?, 'global_hypothesis', ?, ?, ?, ?, '')
            """,
            (
                document_id,
                record.project_id,
                record.hypothesis_id,
                record.title,
                body_text,
                tag_text,
            ),
        )

    def _append_version(self, record: GlobalHypothesisRecord) -> None:
        next_version = self._database.connection.execute(
            """
            SELECT COALESCE(MAX(version_number), 0) + 1 AS next_version
            FROM entity_versions
            WHERE project_id = ? AND entity_type = 'global_hypothesis' AND entity_id = ?
            """,
            (record.project_id, record.hypothesis_id),
        ).fetchone()["next_version"]
        self._database.connection.execute(
            """
            INSERT INTO entity_versions (
              version_id, project_id, entity_type, entity_id, version_number, snapshot_json, created_at, created_by
            ) VALUES (?, ?, 'global_hypothesis', ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                record.project_id,
                record.hypothesis_id,
                next_version,
                json.dumps(asdict(record), ensure_ascii=False),
                record.updated_at,
                record.updated_by,
            ),
        )

    def _append_audit(self, record: GlobalHypothesisRecord, actor_type: str) -> None:
        self._database.connection.execute(
            """
            INSERT INTO audit_log (
              audit_id, project_id, entity_type, entity_id, action, actor_type, actor_id, source_origin,
              request_id, summary, created_at
            ) VALUES (?, ?, 'global_hypothesis', ?, 'upsert', ?, ?, ?, NULL, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                record.project_id,
                record.hypothesis_id,
                actor_type,
                record.updated_by,
                record.source_origin,
                record.title,
                record.updated_at,
            ),
        )

    def _row_to_record(self, row: dict[str, object]) -> GlobalHypothesisRecord:
        facts_rows = self._database.connection.execute(
            """
            SELECT fact_text, source_origin
            FROM entity_facts
            WHERE project_id = ? AND entity_type = 'global_hypothesis' AND entity_id = ?
            ORDER BY created_at
            """,
            (row["project_id"], row["hypothesis_id"]),
        ).fetchall()
        tags_rows = self._database.connection.execute(
            """
            SELECT tag_name
            FROM entity_tags
            WHERE project_id = ? AND entity_type = 'global_hypothesis' AND entity_id = ?
            ORDER BY tag_name
            """,
            (row["project_id"], row["hypothesis_id"]),
        ).fetchall()
        return GlobalHypothesisRecord(
            project_id=str(row["project_id"]),
            hypothesis_id=str(row["hypothesis_id"]),
            title=str(row["title"] or ""),
            statement=str(row["statement"]),
            status=HypothesisStatus(str(row["status"])),
            confidence=row["confidence"] if row["confidence"] is None else float(row["confidence"]),
            binary_id=None if row["binary_id"] is None else str(row["binary_id"]),
            tags=[str(item["tag_name"]) for item in tags_rows],
            observed_facts=[
                ObservedFact(fact=str(item["fact_text"]), source_origin=str(item["source_origin"]))
                for item in facts_rows
            ],
            evidence_refs=[],
            source_origin=str(row["source_origin"]),
            created_by=str(row["created_by"]),
            updated_by=str(row["updated_by"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    def _validate(self, payload: GlobalHypothesisWrite) -> None:
        required_fields = {
            "project_id": payload.project_id,
            "hypothesis_id": payload.hypothesis_id,
            "title": payload.title,
            "statement": payload.statement,
            "created_by": payload.created_by,
            "updated_by": payload.updated_by,
            "source_origin": payload.source_origin,
        }
        for field_name, value in required_fields.items():
            if not str(value).strip():
                raise GlobalHypothesisValidationError(f"{field_name} must not be empty")
        self._bounded_text("title", payload.title, 256)
        self._bounded_text("statement", payload.statement, 2048)
        if payload.confidence is not None and not 0.0 <= payload.confidence <= 1.0:
            raise GlobalHypothesisValidationError("confidence must be within [0.0, 1.0]")
        for fact in payload.observed_facts:
            self._bounded_text("observed fact", fact.fact, 2048)
        for tag in payload.tags:
            self._bounded_text("tag", tag, 64)

    def _bounded_text(self, field_name: str, value: str, max_length: int) -> None:
        text = str(value).strip()
        if not text:
            raise GlobalHypothesisValidationError(f"{field_name} must not be empty")
        if len(text) > max_length:
            raise GlobalHypothesisValidationError(f"{field_name} exceeds max length {max_length}")
