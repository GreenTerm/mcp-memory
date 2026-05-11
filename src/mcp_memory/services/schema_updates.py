from __future__ import annotations

import json
from typing import Any

from mcp_memory.config import ProjectConfig
from mcp_memory.schema import EntityTypeDefinition, ProjectSchema, SchemaValidationError, copy_schema_payload
from mcp_memory.storage import Database, open_database


class SchemaUpdateValidationError(ValueError):
    """Raised when a schema update would orphan existing project data."""


def update_project_schema(project: ProjectConfig, payload: dict[str, Any]) -> ProjectSchema:
    schema = ProjectSchema.from_dict(payload)
    with open_database(project.database_path) as database:
        validate_schema_compatible_with_project_data(database, schema)
    copy_schema_payload(project.schema_path, payload)
    return schema


def validate_schema_compatible_with_project_data(database: Database, schema: ProjectSchema) -> None:
    _validate_records(database, schema)
    _validate_evidence(database, schema)
    _validate_relations(database, schema)


def validate_record_payload(entity: EntityTypeDefinition, payload: dict[str, Any], record_id: str = "<record>") -> None:
    if not isinstance(payload, dict):
        raise SchemaUpdateValidationError(f"{entity.name}:{record_id} payload must be an object")
    field_map = entity.field_map()
    for field_name in entity.required:
        if _is_empty(payload.get(field_name)):
            raise SchemaUpdateValidationError(f"{entity.name}:{record_id} missing required field: {field_name}")
    for field_name, value in payload.items():
        field = field_map.get(field_name)
        if field is None:
            continue
        if field.widget == "number" and not _is_empty(value) and not isinstance(value, (int, float)):
            raise SchemaUpdateValidationError(f"{entity.name}:{record_id} field {field_name} must be a number")
        if field.widget == "bool" and not isinstance(value, bool):
            raise SchemaUpdateValidationError(f"{entity.name}:{record_id} field {field_name} must be a boolean")
        if field.widget == "enum" and not _is_empty(value) and str(value) not in field.options:
            raise SchemaUpdateValidationError(f"{entity.name}:{record_id} field {field_name} must be one of: {', '.join(field.options)}")
        if field.widget == "tags":
            _coerce_tags(value, entity.name, record_id, field_name)
    json.dumps(payload, ensure_ascii=False)


def _validate_records(database: Database, schema: ProjectSchema) -> None:
    rows = database.connection.execute(
        "SELECT entity_type, record_id, payload_json FROM records ORDER BY entity_type, record_id"
    ).fetchall()
    for row in rows:
        entity_type = str(row["entity_type"])
        record_id = str(row["record_id"])
        try:
            entity = schema.entity(entity_type)
        except SchemaValidationError as exc:
            raise SchemaUpdateValidationError(f"schema must keep entity type with records: {entity_type}") from exc
        validate_record_payload(entity, json.loads(str(row["payload_json"])), record_id)


def _validate_evidence(database: Database, schema: ProjectSchema) -> None:
    rows = database.connection.execute(
        "SELECT DISTINCT entity_type FROM evidence ORDER BY entity_type"
    ).fetchall()
    for row in rows:
        entity_type = str(row["entity_type"])
        try:
            schema.entity(entity_type)
        except SchemaValidationError as exc:
            raise SchemaUpdateValidationError(f"schema must keep entity type with evidence: {entity_type}") from exc


def _validate_relations(database: Database, schema: ProjectSchema) -> None:
    rows = database.connection.execute(
        """
        SELECT relation_type, from_entity_type, to_entity_type
        FROM relations
        ORDER BY relation_type, from_entity_type, to_entity_type
        """
    ).fetchall()
    for row in rows:
        relation_name = str(row["relation_type"])
        from_entity_type = str(row["from_entity_type"])
        to_entity_type = str(row["to_entity_type"])
        try:
            relation = schema.relation(relation_name)
        except SchemaValidationError as exc:
            raise SchemaUpdateValidationError(f"schema must keep relation type with relations: {relation_name}") from exc
        if not relation.allows(from_entity_type, to_entity_type):
            raise SchemaUpdateValidationError(
                f"relation {relation_name} must still allow {from_entity_type} -> {to_entity_type}"
            )


def _coerce_tags(value: Any, entity_name: str, record_id: str, field_name: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.replace(",", "\n").splitlines() if item.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, (int, float, bool)):
        return [str(value)]
    raise SchemaUpdateValidationError(f"{entity_name}:{record_id} field {field_name} must be strings or arrays")


def _is_empty(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip()) or value == []
