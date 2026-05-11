from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict, fields

from mcp_memory.domain import FunctionRecord, FunctionWrite, HypothesisStatus
from mcp_memory.domain.models import utc_now
from mcp_memory.logging_utils import get_logger, log_event
from mcp_memory.storage import Database


class FunctionValidationError(ValueError):
    """Raised when a function payload breaks local storage rules."""


class FunctionService:
    def __init__(self, database: Database) -> None:
        self._database = database
        self._logger = get_logger("services")

    def upsert_function(self, payload: FunctionWrite, actor_type: str = "system", commit: bool = True) -> FunctionRecord:
        self._validate(payload)
        existing = self.get_function(payload.project_id, payload.binary_id, payload.function_id)
        conflict = self._lookup_by_address(payload.project_id, payload.binary_id, payload.address)

        if conflict and conflict["function_id"] != payload.function_id and not payload.allow_conflict:
            raise FunctionValidationError(
                "address conflict detected for the same project and binary; set allow_conflict to store as conflict"
            )

        now = utc_now()
        record_payload = {
            field.name: getattr(payload, field.name)
            for field in fields(FunctionWrite)
        }
        record = FunctionRecord(
            **record_payload,
            created_at=existing.created_at if existing else now,
            updated_at=now,
        )

        if existing and not record.created_by:
            record.created_by = existing.created_by

        if conflict and conflict["function_id"] != payload.function_id:
            conflict_status = "conflict"
        else:
            conflict_status = "clean"

        connection = self._database.transaction()
        connection.execute(
            """
            INSERT INTO functions (
              project_id, binary_id, function_id, address, address_norm, raw_name, current_name,
              summary, behavior_description, important_variables_json, used_apis_json, strings_json,
              constants_json, confidence, source_origin, created_at, updated_at, created_by,
              updated_by, conflict_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_id, binary_id, function_id) DO UPDATE SET
              address=excluded.address,
              address_norm=excluded.address_norm,
              raw_name=excluded.raw_name,
              current_name=excluded.current_name,
              summary=excluded.summary,
              behavior_description=excluded.behavior_description,
              important_variables_json=excluded.important_variables_json,
              used_apis_json=excluded.used_apis_json,
              strings_json=excluded.strings_json,
              constants_json=excluded.constants_json,
              confidence=excluded.confidence,
              source_origin=excluded.source_origin,
              updated_at=excluded.updated_at,
              updated_by=excluded.updated_by,
              conflict_status=excluded.conflict_status
            """,
            (
                record.project_id,
                record.binary_id,
                record.function_id,
                record.address,
                self._normalize_address(record.address),
                record.raw_name,
                record.current_name,
                record.summary,
                record.behavior_description,
                json.dumps(record.important_variables, ensure_ascii=False),
                json.dumps(record.used_apis, ensure_ascii=False),
                json.dumps(record.strings, ensure_ascii=False),
                json.dumps(record.constants, ensure_ascii=False),
                record.confidence,
                record.source_origin,
                record.created_at,
                record.updated_at,
                record.created_by,
                record.updated_by,
                conflict_status,
            ),
        )

        if conflict and conflict["function_id"] != payload.function_id:
            connection.execute(
                """
                UPDATE functions
                SET conflict_status = 'conflict'
                WHERE project_id = ? AND binary_id = ? AND function_id = ?
                """,
                (record.project_id, record.binary_id, str(conflict["function_id"])),
            )
            self._record_duplicate_candidate(
                project_id=record.project_id,
                entity_id=record.function_id,
                duplicate_entity_id=str(conflict["function_id"]),
                reason=f"address collision on {self._normalize_address(record.address)}",
            )
            self._record_duplicate_candidate(
                project_id=record.project_id,
                entity_id=str(conflict["function_id"]),
                duplicate_entity_id=record.function_id,
                reason=f"address collision on {self._normalize_address(record.address)}",
            )

        connection.execute(
            "DELETE FROM entity_facts WHERE project_id = ? AND entity_type = 'function' AND entity_id = ?",
            (record.project_id, record.function_id),
        )
        for fact in record.observed_facts:
            connection.execute(
                """
                INSERT INTO entity_facts (
                  fact_id, project_id, entity_type, entity_id, fact_text, source_origin, created_at, created_by
                ) VALUES (?, ?, 'function', ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    record.project_id,
                    record.function_id,
                    fact.fact,
                    fact.source_origin,
                    record.updated_at,
                    record.updated_by,
                ),
            )

        connection.execute(
            """
            DELETE FROM hypotheses
            WHERE project_id = ? AND subject_entity_type = 'function' AND subject_entity_id = ?
            """,
            (record.project_id, record.function_id),
        )
        for item in record.hypotheses:
            connection.execute(
                """
                INSERT INTO hypotheses (
                  hypothesis_id, project_id, binary_id, subject_entity_type, subject_entity_id, title,
                  statement, status, confidence, source_origin, created_at, updated_at, created_by, updated_by
                ) VALUES (?, ?, ?, 'function', ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    record.project_id,
                    record.binary_id,
                    record.function_id,
                    item.statement,
                    item.status.value,
                    item.confidence,
                    item.source_origin,
                    record.updated_at,
                    record.updated_at,
                    record.updated_by,
                    record.updated_by,
                ),
            )

        connection.execute(
            "DELETE FROM entity_tags WHERE project_id = ? AND entity_type = 'function' AND entity_id = ?",
            (record.project_id, record.function_id),
        )
        for tag in sorted(set(record.tags)):
            connection.execute(
                "INSERT OR IGNORE INTO tags(project_id, tag_name, created_at) VALUES (?, ?, ?)",
                (record.project_id, tag, record.updated_at),
            )
            connection.execute(
                """
                INSERT INTO entity_tags(project_id, entity_type, entity_id, tag_name, created_at)
                VALUES (?, 'function', ?, ?, ?)
                """,
                (record.project_id, record.function_id, tag, record.updated_at),
            )

        self._upsert_search_document(record)
        self._append_version(record)
        self._append_audit(record, "upsert", actor_type)
        if commit:
            connection.commit()
        log_event(
            self._logger,
            logging.INFO,
            "function_upserted",
            project_id=record.project_id,
            binary_id=record.binary_id,
            function_id=record.function_id,
            address=record.address,
            mode="conflict" if conflict_status == "conflict" else "clean",
            actor_type=actor_type,
        )
        return record

    def get_function(self, project_id: str, binary_id: str, function_id: str) -> FunctionRecord | None:
        row = self._database.connection.execute(
            """
            SELECT *
            FROM functions
            WHERE project_id = ? AND binary_id = ? AND function_id = ?
            """,
            (project_id, binary_id, function_id),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    def list_functions(self, project_id: str, binary_id: str) -> list[FunctionRecord]:
        rows = self._database.connection.execute(
            """
            SELECT *
            FROM functions
            WHERE project_id = ? AND binary_id = ?
            ORDER BY current_name, address_norm
            """,
            (project_id, binary_id),
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def list_project_functions(self, project_id: str) -> list[FunctionRecord]:
        rows = self._database.connection.execute(
            """
            SELECT *
            FROM functions
            WHERE project_id = ?
            ORDER BY binary_id, current_name, address_norm
            """,
            (project_id,),
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def _lookup_by_address(self, project_id: str, binary_id: str, address: str) -> dict[str, object] | None:
        return self._database.connection.execute(
            """
            SELECT function_id, address, address_norm
            FROM functions
            WHERE project_id = ? AND binary_id = ? AND address_norm = ?
            """,
            (project_id, binary_id, self._normalize_address(address)),
        ).fetchone()

    def _append_version(self, record: FunctionRecord) -> None:
        next_version = self._database.connection.execute(
            """
            SELECT COALESCE(MAX(version_number), 0) + 1 AS next_version
            FROM entity_versions
            WHERE project_id = ? AND entity_type = 'function' AND entity_id = ?
            """,
            (record.project_id, record.function_id),
        ).fetchone()["next_version"]
        self._database.connection.execute(
            """
            INSERT INTO entity_versions (
              version_id, project_id, entity_type, entity_id, version_number, snapshot_json, created_at, created_by
            ) VALUES (?, ?, 'function', ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                record.project_id,
                record.function_id,
                next_version,
                json.dumps(asdict(record), ensure_ascii=False),
                record.updated_at,
                record.updated_by,
            ),
        )

    def _record_duplicate_candidate(
        self,
        project_id: str,
        entity_id: str,
        duplicate_entity_id: str,
        reason: str,
    ) -> None:
        self._database.connection.execute(
            """
            INSERT INTO duplicate_candidates (
              candidate_id, project_id, entity_type, entity_id, duplicate_entity_id, reason, created_at
            ) VALUES (?, ?, 'function', ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                project_id,
                entity_id,
                duplicate_entity_id,
                reason,
                utc_now(),
            ),
        )

    def _append_audit(self, record: FunctionRecord, action: str, actor_type: str) -> None:
        self._database.connection.execute(
            """
            INSERT INTO audit_log (
              audit_id, project_id, entity_type, entity_id, action, actor_type, actor_id, source_origin,
              request_id, summary, created_at
            ) VALUES (?, ?, 'function', ?, ?, ?, ?, ?, NULL, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                record.project_id,
                record.function_id,
                action,
                actor_type,
                record.updated_by,
                record.source_origin,
                f"{record.current_name} @ {record.address}",
                record.updated_at,
            ),
        )

    def _upsert_search_document(self, record: FunctionRecord) -> None:
        document_id = f"function:{record.project_id}:{record.function_id}"
        tag_text = " ".join(sorted(set(record.tags)))
        body_text = " ".join(
            filter(
                None,
                [
                    record.summary,
                    record.behavior_description,
                    " ".join(fact.fact for fact in record.observed_facts),
                    " ".join(item.statement for item in record.hypotheses),
                    " ".join(record.used_apis),
                    " ".join(record.strings),
                    " ".join(record.constants),
                ],
            )
        )
        self._database.connection.execute(
            """
            INSERT INTO search_documents (
              document_id, project_id, entity_type, entity_id, title_text, body_text, tag_text, address_text, updated_at
            ) VALUES (?, ?, 'function', ?, ?, ?, ?, ?, ?)
            ON CONFLICT(document_id) DO UPDATE SET
              title_text=excluded.title_text,
              body_text=excluded.body_text,
              tag_text=excluded.tag_text,
              address_text=excluded.address_text,
              updated_at=excluded.updated_at
            """,
            (
                document_id,
                record.project_id,
                record.function_id,
                f"{record.current_name} {record.raw_name}",
                body_text,
                tag_text,
                record.address,
                record.updated_at,
            ),
        )
        self._database.connection.execute(
            "DELETE FROM search_documents_fts WHERE document_id = ?",
            (
                document_id,
            ),
        )
        self._database.connection.execute(
            """
            INSERT INTO search_documents_fts(
              document_id, project_id, entity_type, entity_id, title_text, body_text, tag_text, address_text
            ) VALUES (?, ?, 'function', ?, ?, ?, ?, ?)
            """,
            (
                document_id,
                record.project_id,
                record.function_id,
                f"{record.current_name} {record.raw_name}",
                body_text,
                tag_text,
                record.address,
            ),
        )

    def _row_to_record(self, row: dict[str, object]) -> FunctionRecord:
        facts_rows = self._database.connection.execute(
            """
            SELECT fact_text, source_origin
            FROM entity_facts
            WHERE project_id = ? AND entity_type = 'function' AND entity_id = ?
            ORDER BY created_at
            """,
            (row["project_id"], row["function_id"]),
        ).fetchall()
        hypotheses_rows = self._database.connection.execute(
            """
            SELECT statement, status, confidence, source_origin
            FROM hypotheses
            WHERE project_id = ? AND subject_entity_type = 'function' AND subject_entity_id = ?
            ORDER BY created_at
            """,
            (row["project_id"], row["function_id"]),
        ).fetchall()
        tags_rows = self._database.connection.execute(
            """
            SELECT tag_name
            FROM entity_tags
            WHERE project_id = ? AND entity_type = 'function' AND entity_id = ?
            ORDER BY tag_name
            """,
            (row["project_id"], row["function_id"]),
        ).fetchall()

        from mcp_memory.domain import EvidenceRef, HypothesisItem, ObservedFact

        return FunctionRecord(
            project_id=str(row["project_id"]),
            binary_id=str(row["binary_id"]),
            function_id=str(row["function_id"]),
            address=str(row["address"]),
            raw_name=str(row["raw_name"]),
            current_name=str(row["current_name"]),
            summary=str(row["summary"]),
            behavior_description=str(row["behavior_description"]),
            important_variables=json.loads(str(row["important_variables_json"])),
            used_apis=json.loads(str(row["used_apis_json"])),
            strings=json.loads(str(row["strings_json"])),
            constants=json.loads(str(row["constants_json"])),
            confidence=row["confidence"] if row["confidence"] is None else float(row["confidence"]),
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
            allow_conflict=str(row["conflict_status"]) == "conflict",
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    def _validate(self, payload: FunctionWrite) -> None:
        required_fields = {
            "project_id": payload.project_id,
            "binary_id": payload.binary_id,
            "function_id": payload.function_id,
            "address": payload.address,
            "raw_name": payload.raw_name,
            "current_name": payload.current_name,
            "summary": payload.summary,
            "behavior_description": payload.behavior_description,
            "created_by": payload.created_by,
            "updated_by": payload.updated_by,
            "source_origin": payload.source_origin,
        }
        for field_name, value in required_fields.items():
            if not str(value).strip():
                raise FunctionValidationError(f"{field_name} must not be empty")

        self._bounded_text("summary", payload.summary, 1024)
        self._bounded_text("behavior_description", payload.behavior_description, 8192)

        for item in payload.important_variables:
            self._bounded_text("important_variables item", item, 256)
        for item in payload.used_apis:
            self._bounded_text("used_apis item", item, 256)
        for item in payload.strings:
            self._bounded_text("strings item", item, 256)
        for item in payload.constants:
            self._bounded_text("constants item", item, 256)

        if len(payload.tags) > 100:
            raise FunctionValidationError("tags exceed the maximum size of 100")
        for tag in payload.tags:
            self._bounded_text("tag", tag, 64)

        if len(payload.observed_facts) > 100:
            raise FunctionValidationError("observed_facts exceed the maximum size of 100")
        for fact in payload.observed_facts:
            self._bounded_text("observed fact", fact.fact, 2048)

        if len(payload.hypotheses) > 100:
            raise FunctionValidationError("hypotheses exceed the maximum size of 100")
        for item in payload.hypotheses:
            self._bounded_text("hypothesis", item.statement, 2048)
            if item.confidence is not None and not 0.0 <= item.confidence <= 1.0:
                raise FunctionValidationError("hypothesis confidence must be within [0.0, 1.0]")

        if payload.confidence is not None and not 0.0 <= payload.confidence <= 1.0:
            raise FunctionValidationError("confidence must be within [0.0, 1.0]")

        self._normalize_address(payload.address)

    def _bounded_text(self, field_name: str, value: str, max_length: int) -> None:
        text = str(value).strip()
        if not text:
            raise FunctionValidationError(f"{field_name} must not be empty")
        if len(text) > max_length:
            raise FunctionValidationError(f"{field_name} exceeds max length {max_length}")

    def _normalize_address(self, address: str) -> str:
        candidate = address.strip().lower()
        if not candidate:
            raise FunctionValidationError("address must not be empty")
        if candidate.startswith("0x"):
            candidate = candidate[2:]
        try:
            return f"0x{int(candidate, 16):x}"
        except ValueError as exc:
            raise FunctionValidationError("address must be a hexadecimal value") from exc
