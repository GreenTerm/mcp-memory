from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from sqlite3 import IntegrityError
from typing import Any

from mcp_memory.domain.models import utc_now
from mcp_memory.logging_utils import get_logger, log_event
from mcp_memory.schema import EntityTypeDefinition, ProjectSchema, SchemaValidationError, load_project_schema
from mcp_memory.storage import Database
from mcp_memory.config import ProjectConfig


class RecordValidationError(ValueError):
    """Raised when a generic record request is invalid."""


@dataclass(slots=True)
class RecordWrite:
    entity_type: str
    payload: dict[str, Any]
    record_id: str | None = None
    source_origin: str = "manual"
    created_by: str = "system"
    updated_by: str = "system"


@dataclass(slots=True)
class Record:
    project_id: str
    entity_type: str
    record_id: str
    slug: str | None
    title: str
    summary: str
    payload: dict[str, Any]
    status: str
    schema_version: str
    source_origin: str
    created_at: str
    updated_at: str
    created_by: str
    updated_by: str


class RecordService:
    def __init__(self, database: Database, project: ProjectConfig) -> None:
        self._database = database
        self._project = project
        self._schema = load_project_schema(project.schema_path)
        self._logger = get_logger("services")

    def list_entity_types(self) -> list[dict[str, Any]]:
        return [item.to_dict() for item in self._schema.entity_types]

    def upsert_record(self, write: RecordWrite, actor_type: str = "system") -> Record:
        entity = self._entity(write.entity_type)
        payload = self._normalized_payload(entity, write.payload)
        record_id = write.record_id or str(uuid.uuid4())
        slug = self._field_text(payload, entity.slug_field) if entity.slug_field else None
        title = self._field_text(payload, entity.title_field) if entity.title_field else record_id
        summary = self._field_text(payload, entity.summary_field) if entity.summary_field else ""
        now = utc_now()

        existing = self.get_record(entity.name, record_id, include_archived=True)
        if slug:
            slug_match = self.get_record(entity.name, slug, include_archived=True)
            if slug_match is not None and slug_match.record_id != record_id:
                raise RecordValidationError("slug must be unique within the entity type")

        created_at = existing.created_at if existing else now
        created_by = existing.created_by if existing else write.created_by
        status = existing.status if existing else "active"
        record = Record(
            project_id=self._project.project_id,
            entity_type=entity.name,
            record_id=record_id,
            slug=slug,
            title=title,
            summary=summary,
            payload=payload,
            status=status,
            schema_version=self._schema.schema_version,
            source_origin=write.source_origin,
            created_at=created_at,
            updated_at=now,
            created_by=created_by,
            updated_by=write.updated_by,
        )
        connection = self._database.transaction()
        try:
            connection.execute(
                """
                INSERT INTO records (
                  project_id, entity_type, record_id, slug, title, summary, payload_json,
                  status, schema_version, source_origin, created_at, updated_at, created_by, updated_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id, entity_type, record_id) DO UPDATE SET
                  slug = excluded.slug,
                  title = excluded.title,
                  summary = excluded.summary,
                  payload_json = excluded.payload_json,
                  status = excluded.status,
                  schema_version = excluded.schema_version,
                  source_origin = excluded.source_origin,
                  updated_at = excluded.updated_at,
                  updated_by = excluded.updated_by
                """,
                self._record_params(record),
            )
        except IntegrityError as exc:
            raise RecordValidationError("slug must be unique within the entity type") from exc
        self._replace_tags(record, self._tag_values(entity, payload))
        self._append_version(record)
        self._append_audit(record, "upsert_record", actor_type, write.updated_by)
        self._upsert_search_document(record, entity)
        connection.commit()
        log_event(
            self._logger,
            logging.INFO,
            "record_upserted",
            project_id=record.project_id,
            entity_type=record.entity_type,
            record_id=record.record_id,
        )
        return record

    def get_record(self, entity_type: str, record_id_or_slug: str, include_archived: bool = False) -> Record | None:
        params: list[Any] = [self._project.project_id, entity_type, record_id_or_slug, record_id_or_slug]
        status_filter = ""
        if not include_archived:
            status_filter = " AND status = 'active'"
        row = self._database.connection.execute(
            f"""
            SELECT *
            FROM records
            WHERE project_id = ? AND entity_type = ? AND (record_id = ? OR slug = ?){status_filter}
            """,
            params,
        ).fetchone()
        return None if row is None else self._row_to_record(row)

    def list_records(self, entity_type: str | None = None, include_archived: bool = False, limit: int = 100) -> list[Record]:
        params: list[Any] = [self._project.project_id]
        filters = ["project_id = ?"]
        if entity_type:
            self._entity(entity_type)
            filters.append("entity_type = ?")
            params.append(entity_type)
        if not include_archived:
            filters.append("status = 'active'")
        params.append(limit)
        rows = self._database.connection.execute(
            f"""
            SELECT *
            FROM records
            WHERE {' AND '.join(filters)}
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def archive_record(self, entity_type: str, record_id_or_slug: str, archived_by: str = "system", actor_type: str = "system") -> Record:
        record = self.get_record(entity_type, record_id_or_slug, include_archived=True)
        if record is None:
            raise RecordValidationError("record not found")
        if record.status == "archived":
            return record
        now = utc_now()
        connection = self._database.transaction()
        connection.execute(
            """
            UPDATE records
            SET status = 'archived', updated_at = ?, updated_by = ?
            WHERE project_id = ? AND entity_type = ? AND record_id = ?
            """,
            (now, archived_by, record.project_id, record.entity_type, record.record_id),
        )
        archived = self.get_record(entity_type, record.record_id, include_archived=True)
        if archived is None:
            raise RecordValidationError("record not found after archive")
        self._append_version(archived)
        self._append_audit(archived, "archive_record", actor_type, archived_by)
        self._delete_search_document(archived)
        connection.commit()
        return archived

    def _entity(self, entity_type: str) -> EntityTypeDefinition:
        try:
            return self._schema.entity(entity_type)
        except SchemaValidationError as exc:
            raise RecordValidationError(str(exc)) from exc

    def _normalized_payload(self, entity: EntityTypeDefinition, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise RecordValidationError("payload must be an object")
        field_map = entity.field_map()
        for field_name in entity.required:
            if self._is_empty(payload.get(field_name)):
                raise RecordValidationError(f"{field_name} is required")
        normalized = dict(payload)
        for field_name, value in list(normalized.items()):
            field = field_map.get(field_name)
            if field is None:
                continue
            if field.widget == "number" and not self._is_empty(value) and not isinstance(value, (int, float)):
                raise RecordValidationError(f"{field_name} must be a number")
            if field.widget == "bool" and not isinstance(value, bool):
                raise RecordValidationError(f"{field_name} must be a boolean")
            if field.widget == "enum" and not self._is_empty(value) and str(value) not in field.options:
                raise RecordValidationError(f"{field_name} must be one of: {', '.join(field.options)}")
            if field.widget == "tags":
                normalized[field_name] = self._coerce_tags(value)
        json.dumps(normalized, ensure_ascii=False)
        return normalized

    def _record_params(self, record: Record) -> tuple[Any, ...]:
        return (
            record.project_id,
            record.entity_type,
            record.record_id,
            record.slug,
            record.title,
            record.summary,
            json.dumps(record.payload, ensure_ascii=False),
            record.status,
            record.schema_version,
            record.source_origin,
            record.created_at,
            record.updated_at,
            record.created_by,
            record.updated_by,
        )

    def _row_to_record(self, row: dict[str, Any]) -> Record:
        return Record(
            project_id=str(row["project_id"]),
            entity_type=str(row["entity_type"]),
            record_id=str(row["record_id"]),
            slug=None if row["slug"] is None else str(row["slug"]),
            title=str(row["title"]),
            summary=str(row["summary"]),
            payload=json.loads(str(row["payload_json"])),
            status=str(row["status"]),
            schema_version=str(row["schema_version"]),
            source_origin=str(row["source_origin"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            created_by=str(row["created_by"]),
            updated_by=str(row["updated_by"]),
        )

    def _append_version(self, record: Record) -> None:
        row = self._database.connection.execute(
            """
            SELECT COALESCE(MAX(version_number), 0) AS max_version
            FROM entity_versions
            WHERE project_id = ? AND entity_type = ? AND entity_id = ?
            """,
            (record.project_id, record.entity_type, record.record_id),
        ).fetchone()
        version_number = int(row["max_version"]) + 1
        self._database.connection.execute(
            """
            INSERT INTO entity_versions (
              version_id, project_id, entity_type, entity_id, version_number, snapshot_json, created_at, created_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                record.project_id,
                record.entity_type,
                record.record_id,
                version_number,
                json.dumps(self._serialize_record(record), ensure_ascii=False),
                utc_now(),
                record.updated_by,
            ),
        )

    def _append_audit(self, record: Record, action: str, actor_type: str, actor_id: str) -> None:
        self._database.connection.execute(
            """
            INSERT INTO audit_log (
              audit_id, project_id, entity_type, entity_id, action, actor_type, actor_id,
              source_origin, request_id, summary, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                record.project_id,
                record.entity_type,
                record.record_id,
                action,
                actor_type,
                actor_id,
                record.source_origin,
                f"{action} {record.entity_type}:{record.title}",
                utc_now(),
            ),
        )

    def _replace_tags(self, record: Record, tags: list[str]) -> None:
        connection = self._database.connection
        connection.execute(
            "DELETE FROM entity_tags WHERE project_id = ? AND entity_type = ? AND entity_id = ?",
            (record.project_id, record.entity_type, record.record_id),
        )
        now = utc_now()
        for tag in tags:
            connection.execute(
                "INSERT OR IGNORE INTO tags(project_id, tag_name, created_at) VALUES (?, ?, ?)",
                (record.project_id, tag, now),
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO entity_tags(project_id, entity_type, entity_id, tag_name, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (record.project_id, record.entity_type, record.record_id, tag, now),
            )

    def _upsert_search_document(self, record: Record, entity: EntityTypeDefinition) -> None:
        document_id = f"{record.project_id}:{record.entity_type}:{record.record_id}"
        tags = self._tag_values(entity, record.payload)
        body_parts = [record.title, record.summary]
        for field_name in entity.search_fields:
            value = record.payload.get(field_name)
            if value is not None:
                body_parts.append(self._search_text(value))
        body_text = "\n".join(part for part in body_parts if part)
        tag_text = " ".join(tags)
        self._database.connection.execute(
            """
            INSERT INTO search_documents (
              document_id, project_id, entity_type, entity_id, title_text, body_text, tag_text, address_text, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, '', ?)
            ON CONFLICT(document_id) DO UPDATE SET
              title_text = excluded.title_text,
              body_text = excluded.body_text,
              tag_text = excluded.tag_text,
              updated_at = excluded.updated_at
            """,
            (document_id, record.project_id, record.entity_type, record.record_id, record.title, body_text, tag_text, record.updated_at),
        )
        self._database.connection.execute("DELETE FROM search_documents_fts WHERE document_id = ?", (document_id,))
        self._database.connection.execute(
            """
            INSERT INTO search_documents_fts(document_id, project_id, entity_type, entity_id, title_text, body_text, tag_text, address_text)
            VALUES (?, ?, ?, ?, ?, ?, ?, '')
            """,
            (document_id, record.project_id, record.entity_type, record.record_id, record.title, body_text, tag_text),
        )

    def _delete_search_document(self, record: Record) -> None:
        document_id = f"{record.project_id}:{record.entity_type}:{record.record_id}"
        self._database.connection.execute("DELETE FROM search_documents_fts WHERE document_id = ?", (document_id,))
        self._database.connection.execute("DELETE FROM search_documents WHERE document_id = ?", (document_id,))

    def _serialize_record(self, record: Record) -> dict[str, Any]:
        return {
            "project_id": record.project_id,
            "entity_type": record.entity_type,
            "record_id": record.record_id,
            "slug": record.slug,
            "title": record.title,
            "summary": record.summary,
            "payload": record.payload,
            "status": record.status,
            "schema_version": record.schema_version,
            "source_origin": record.source_origin,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
            "created_by": record.created_by,
            "updated_by": record.updated_by,
        }

    def _tag_values(self, entity: EntityTypeDefinition, payload: dict[str, Any]) -> list[str]:
        tags: list[str] = []
        for field_name in entity.tag_fields:
            tags.extend(self._coerce_tags(payload.get(field_name, [])))
        return sorted({tag for tag in tags if tag})

    def _coerce_tags(self, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [item.strip() for item in value.replace(",", "\n").splitlines() if item.strip()]
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        raise RecordValidationError("tags fields must be strings or arrays")

    def _field_text(self, payload: dict[str, Any], field_name: str) -> str:
        if not field_name:
            return ""
        value = payload.get(field_name)
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        return str(value)

    def _search_text(self, value: Any) -> str:
        if isinstance(value, list):
            return " ".join(self._search_text(item) for item in value)
        if isinstance(value, dict):
            return " ".join(self._search_text(item) for item in value.values())
        return str(value)

    def _is_empty(self, value: Any) -> bool:
        return value is None or (isinstance(value, str) and not value.strip()) or value == []
