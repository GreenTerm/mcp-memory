from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any


ALLOWED_WIDGETS = {"text", "textarea", "number", "bool", "enum", "tags", "json", "datetime", "url", "path"}
IDENTIFIER_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


class SchemaValidationError(ValueError):
    """Raised when a project schema is invalid."""


@dataclass(slots=True)
class FieldDefinition:
    name: str
    label: str
    widget: str = "text"
    description: str = ""
    options: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "FieldDefinition":
        name = _required_text(payload, "name")
        _validate_identifier(name, "field name")
        widget = str(payload.get("widget", "text")).strip() or "text"
        if widget not in ALLOWED_WIDGETS:
            raise SchemaValidationError(f"field {name} has unsupported widget: {widget}")
        options = [str(item) for item in payload.get("options", [])]
        if widget == "enum" and not options:
            raise SchemaValidationError(f"enum field {name} must define options")
        return cls(
            name=name,
            label=str(payload.get("label", name)).strip() or name,
            widget=widget,
            description=str(payload.get("description", "")),
            options=options,
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": self.name,
            "label": self.label,
            "widget": self.widget,
        }
        if self.description:
            payload["description"] = self.description
        if self.options:
            payload["options"] = self.options
        return payload


@dataclass(slots=True)
class EntityTypeDefinition:
    name: str
    label: str
    description: str = ""
    fields: list[FieldDefinition] = field(default_factory=list)
    required: list[str] = field(default_factory=list)
    title_field: str = ""
    summary_field: str = ""
    slug_field: str = ""
    search_fields: list[str] = field(default_factory=list)
    tag_fields: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "EntityTypeDefinition":
        name = _required_text(payload, "name")
        _validate_identifier(name, "entity type name")
        fields = [FieldDefinition.from_dict(item) for item in payload.get("fields", [])]
        names = [item.name for item in fields]
        if len(names) != len(set(names)):
            raise SchemaValidationError(f"entity {name} field names must be unique")
        field_names = {item.name for item in fields}
        required = [str(item) for item in payload.get("required", [])]
        for field_name in required:
            if field_name not in field_names:
                raise SchemaValidationError(f"entity {name} requires unknown field: {field_name}")
        for meta_field in ("title_field", "summary_field", "slug_field"):
            value = str(payload.get(meta_field, "")).strip()
            if value and value not in field_names:
                raise SchemaValidationError(f"entity {name} {meta_field} points to unknown field: {value}")
        search_fields = [str(item) for item in payload.get("search_fields", [])]
        tag_fields = [str(item) for item in payload.get("tag_fields", [])]
        for field_name in [*search_fields, *tag_fields]:
            if field_name not in field_names:
                raise SchemaValidationError(f"entity {name} references unknown search/tag field: {field_name}")
        return cls(
            name=name,
            label=str(payload.get("label", name)).strip() or name,
            description=str(payload.get("description", "")),
            fields=fields,
            required=required,
            title_field=str(payload.get("title_field", "")).strip(),
            summary_field=str(payload.get("summary_field", "")).strip(),
            slug_field=str(payload.get("slug_field", "")).strip(),
            search_fields=search_fields,
            tag_fields=tag_fields,
        )

    def field_map(self) -> dict[str, FieldDefinition]:
        return {item.name: item for item in self.fields}

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "description": self.description,
            "fields": [item.to_dict() for item in self.fields],
            "required": self.required,
            "title_field": self.title_field,
            "summary_field": self.summary_field,
            "slug_field": self.slug_field,
            "search_fields": self.search_fields,
            "tag_fields": self.tag_fields,
        }


@dataclass(slots=True)
class RelationTypeDefinition:
    name: str
    label: str
    from_types: list[str]
    to_types: list[str]
    directed: bool = True

    @classmethod
    def from_dict(cls, payload: dict[str, Any], entity_names: set[str]) -> "RelationTypeDefinition":
        name = _required_text(payload, "name")
        _validate_identifier(name, "relation type name")
        from_types = [str(item) for item in payload.get("from", [])]
        to_types = [str(item) for item in payload.get("to", [])]
        if not from_types or not to_types:
            raise SchemaValidationError(f"relation {name} must define from and to entity types")
        for entity_type in [*from_types, *to_types]:
            if entity_type != "*" and entity_type not in entity_names:
                raise SchemaValidationError(f"relation {name} references unknown entity type: {entity_type}")
        return cls(
            name=name,
            label=str(payload.get("label", name)).strip() or name,
            from_types=from_types,
            to_types=to_types,
            directed=bool(payload.get("directed", True)),
        )

    def allows(self, from_entity_type: str, to_entity_type: str) -> bool:
        return (self.from_types == ["*"] or from_entity_type in self.from_types) and (
            self.to_types == ["*"] or to_entity_type in self.to_types
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "from": self.from_types,
            "to": self.to_types,
            "directed": self.directed,
        }


@dataclass(slots=True)
class ProjectSchema:
    schema_version: str
    entity_types: list[EntityTypeDefinition]
    relation_types: list[RelationTypeDefinition] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ProjectSchema":
        version = str(payload.get("schema_version", "1")).strip() or "1"
        entity_types = [EntityTypeDefinition.from_dict(item) for item in payload.get("entity_types", [])]
        if not entity_types:
            raise SchemaValidationError("schema must define at least one entity type")
        names = [item.name for item in entity_types]
        if len(names) != len(set(names)):
            raise SchemaValidationError("entity type names must be unique")
        entity_names = set(names)
        relation_types = [RelationTypeDefinition.from_dict(item, entity_names) for item in payload.get("relation_types", [])]
        relation_names = [item.name for item in relation_types]
        if len(relation_names) != len(set(relation_names)):
            raise SchemaValidationError("relation type names must be unique")
        return cls(schema_version=version, entity_types=entity_types, relation_types=relation_types)

    def entity(self, name: str) -> EntityTypeDefinition:
        for item in self.entity_types:
            if item.name == name:
                return item
        raise SchemaValidationError(f"unknown entity type: {name}")

    def relation(self, name: str) -> RelationTypeDefinition:
        for item in self.relation_types:
            if item.name == name:
                return item
        raise SchemaValidationError(f"unknown relation type: {name}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "entity_types": [item.to_dict() for item in self.entity_types],
            "relation_types": [item.to_dict() for item in self.relation_types],
        }


def load_project_schema(path: Path) -> ProjectSchema:
    return ProjectSchema.from_dict(json.loads(path.read_text(encoding="utf-8")))


def save_project_schema(path: Path, schema: ProjectSchema) -> None:
    path.write_text(json.dumps(schema.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


def load_schema_payload(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_bundled_schema_payload(name: str) -> dict[str, Any]:
    resource_name = name if name.endswith(".schema.json") else f"{name}.schema.json"
    with resources.files("mcp_memory.schemas").joinpath(resource_name).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def list_bundled_schema_templates() -> list[str]:
    names = []
    for item in resources.files("mcp_memory.schemas").iterdir():
        name = item.name
        if name.endswith(".schema.json"):
            names.append(name[: -len(".schema.json")])
    return sorted(names)


def schema_payload_from_source(schema_path: Path | None = None, template_name: str = "general_knowledge") -> dict[str, Any]:
    if schema_path is not None:
        return load_schema_payload(schema_path)
    return load_bundled_schema_payload(template_name)


def copy_schema_payload(path: Path, payload: dict[str, Any]) -> None:
    ProjectSchema.from_dict(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _required_text(payload: dict[str, Any], name: str) -> str:
    value = str(payload.get(name, "")).strip()
    if not value:
        raise SchemaValidationError(f"{name} is required")
    return value


def _validate_identifier(value: str, label: str) -> None:
    if not IDENTIFIER_PATTERN.fullmatch(value):
        raise SchemaValidationError(f"{label} must start with a lowercase letter and contain only lowercase letters, digits, and underscores")
