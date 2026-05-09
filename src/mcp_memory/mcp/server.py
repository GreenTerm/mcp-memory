from __future__ import annotations

import json
import logging
import traceback
import uuid
from dataclasses import asdict, dataclass, is_dataclass
from enum import Enum
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from mcp_memory.config import ProjectConfig, ProjectRegistry
from mcp_memory.logging_utils import configure_logging, get_logger, log_event, start_request_log
from mcp_memory.protocol import GetRecordQuery, GetRelatedQuery, GetSchemaQuery, ListEntityTypesQuery, ProjectDispatcher, SearchRecordsQuery
from mcp_memory.schema import ProjectSchema, load_project_schema
from mcp_memory.services import (
    EvidenceValidationError,
    FunctionService,
    FunctionValidationError,
    GlobalHypothesisService,
    GlobalHypothesisValidationError,
    PendingChangeService,
    PendingChangeValidationError,
    ProjectArchiveService,
    ProjectTransferService,
    RelationService,
    RelationValidationError,
    SearchQuery,
    SearchService,
    StructureService,
    StructureValidationError,
    GenericWorkflowService,
    GenericPendingValidationError,
    GenericRelationValidationError,
    GenericEvidenceValidationError,
    RecordValidationError,
)
from mcp_memory.storage import open_database


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[[ProjectConfig, ProjectRegistry, dict[str, Any]], Any]


@dataclass(frozen=True)
class PromptSpec:
    name: str
    description: str
    arguments: list[dict[str, Any]]
    renderer: Callable[[ProjectConfig, dict[str, str]], str]


class McpRequestError(ValueError):
    """Raised when an MCP request is malformed."""


def serialize(value: Any) -> Any:
    if is_dataclass(value):
        return serialize(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {key: serialize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [serialize(item) for item in value]
    return value


def serve_project_mcp_api(
    project: ProjectConfig,
    registry: ProjectRegistry,
    host: str,
    port: int,
    log_level: str = "INFO",
) -> None:
    logger = configure_logging("mcp", log_level, project.logs_dir / "mcp.log")
    configure_logging("services", log_level, project.logs_dir / "mcp.log")
    handler = build_handler(project, registry, logger=logger)
    server = ThreadingHTTPServer((host, port), handler)
    log_event(logger, logging.INFO, "server_start", project_id=project.project_id, host=host, port=port)
    server.serve_forever()


def build_handler(
    project: ProjectConfig,
    registry: ProjectRegistry,
    logger: logging.Logger | None = None,
) -> type[BaseHTTPRequestHandler]:
    tools = _build_tools()
    prompts = _build_prompts()
    request_logger = logger or get_logger("mcp")
    sessions: set[str] = set()

    class RequestHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "mcp-memory-mcp/0.1"

        def do_GET(self) -> None:
            request_log = start_request_log("GET", self.path)
            self._response_status = HTTPStatus.OK
            parsed = urlparse(self.path)
            if parsed.path == "/health":
                self._send_json({"status": "ok", "project_id": project.project_id})
            elif parsed.path == "/mcp":
                self._send_json(
                    {"error": {"code": "method_not_allowed", "message": "SSE streams are not available"}},
                    status=HTTPStatus.METHOD_NOT_ALLOWED,
                )
            else:
                self._send_json({"error": {"code": "not_found", "message": "Unknown route"}}, status=HTTPStatus.NOT_FOUND)
            request_log.finish(request_logger, "request_complete", int(self._response_status), project_id=project.project_id)

        def do_DELETE(self) -> None:
            request_log = start_request_log("DELETE", self.path)
            self._response_status = HTTPStatus.METHOD_NOT_ALLOWED
            parsed = urlparse(self.path)
            if parsed.path == "/mcp":
                self._send_json(
                    {"error": {"code": "method_not_allowed", "message": "Session deletion is not available"}},
                    status=HTTPStatus.METHOD_NOT_ALLOWED,
                )
            else:
                self._send_json({"error": {"code": "not_found", "message": "Unknown route"}}, status=HTTPStatus.NOT_FOUND)
            request_log.finish(request_logger, "request_complete", int(self._response_status), project_id=project.project_id)

        def do_POST(self) -> None:
            request_log = start_request_log("POST", self.path)
            self._response_status = HTTPStatus.OK
            parsed = urlparse(self.path)
            if parsed.path not in ("", "/", "/mcp"):
                self._send_json({"error": {"code": "not_found", "message": "Unknown route"}}, status=HTTPStatus.NOT_FOUND)
                request_log.finish(request_logger, "request_complete", int(self._response_status), project_id=project.project_id)
                return

            payload = self._read_json_body()
            if payload is None:
                request_log.finish(request_logger, "request_complete", int(self._response_status), project_id=project.project_id)
                return

            try:
                method = None if "method" not in payload else str(payload["method"])
                session_id = self.headers.get("Mcp-Session-Id")
                if session_id and session_id not in sessions and method != "initialize":
                    self._send_json(
                        {"error": {"code": "session_not_found", "message": "Unknown MCP session"}},
                        status=HTTPStatus.NOT_FOUND,
                    )
                    return

                if method is None:
                    self._send_accepted()
                    return

                if "id" not in payload:
                    self._send_accepted()
                    return

                request_id = payload.get("id")
                params = payload.get("params", {})
                if not isinstance(params, dict):
                    raise McpRequestError("params must be an object")

                if method == "initialize":
                    session_id = uuid.uuid4().hex
                    sessions.add(session_id)
                    self._send_rpc_result(
                        request_id,
                        {
                            "protocolVersion": "2025-03-26",
                            "serverInfo": {"name": "mcp-memory", "version": "0.1.0"},
                            "capabilities": {
                                "tools": {"listChanged": False},
                                "resources": {"subscribe": False, "listChanged": False},
                                "prompts": {"listChanged": False},
                            },
                        },
                        headers={"Mcp-Session-Id": session_id},
                    )
                    return

                if method == "ping":
                    self._send_rpc_result(request_id, {})
                    return

                if method == "tools/list":
                    self._send_rpc_result(
                        request_id,
                        {
                            "tools": [
                                {
                                    "name": spec.name,
                                    "description": spec.description,
                                    "inputSchema": spec.input_schema,
                                }
                                for spec in tools.values()
                            ]
                        },
                    )
                    return

                if method == "resources/list":
                    self._send_rpc_result(request_id, {"resources": []})
                    return

                if method == "resources/templates/list":
                    self._send_rpc_result(request_id, {"resourceTemplates": []})
                    return

                if method == "prompts/list":
                    self._send_rpc_result(
                        request_id,
                        {
                            "prompts": [
                                {
                                    "name": spec.name,
                                    "description": spec.description,
                                    "arguments": spec.arguments,
                                }
                                for spec in prompts.values()
                            ]
                        },
                    )
                    return

                if method == "prompts/get":
                    prompt_name = str(params["name"])
                    prompt_arguments = params.get("arguments", {})
                    if not isinstance(prompt_arguments, dict):
                        raise McpRequestError("prompt arguments must be an object")
                    spec = prompts.get(prompt_name)
                    if spec is None:
                        raise McpRequestError(f"Unknown prompt: {prompt_name}")
                    rendered_arguments = {str(key): str(value) for key, value in prompt_arguments.items()}
                    self._send_rpc_result(
                        request_id,
                        {
                            "description": spec.description,
                            "messages": [
                                {
                                    "role": "user",
                                    "content": {
                                        "type": "text",
                                        "text": spec.renderer(project, rendered_arguments),
                                    },
                                }
                            ],
                        },
                    )
                    return

                if method == "tools/call":
                    tool_name = str(params["name"])
                    arguments = params.get("arguments", {})
                    if not isinstance(arguments, dict):
                        raise McpRequestError("tool arguments must be an object")
                    spec = tools.get(tool_name)
                    if spec is None:
                        raise McpRequestError(f"Unknown tool: {tool_name}")
                    log_event(
                        request_logger,
                        logging.INFO,
                        "tool_call",
                        project_id=project.project_id,
                        tool_name=tool_name,
                    )
                    result = spec.handler(project, registry, arguments)
                    self._send_rpc_result(
                        request_id,
                        {
                            "content": [{"type": "text", "text": json.dumps(serialize(result), ensure_ascii=False, indent=2)}],
                            "structuredContent": serialize(result),
                            "isError": False,
                        },
                    )
                    return

                self._send_rpc_error(request_id, -32601, f"Unknown method: {method}")
            except (
                FunctionValidationError,
                StructureValidationError,
                GlobalHypothesisValidationError,
                EvidenceValidationError,
                RelationValidationError,
                PendingChangeValidationError,
                GenericPendingValidationError,
                GenericRelationValidationError,
                GenericEvidenceValidationError,
                RecordValidationError,
                McpRequestError,
                KeyError,
                ValueError,
            ) as exc:
                log_event(
                    request_logger,
                    logging.WARNING,
                    "request_validation_error",
                    project_id=project.project_id,
                    method="POST",
                    path=parsed.path,
                    error=str(exc),
                )
                self._send_rpc_error(payload.get("id"), -32602, str(exc))
            except Exception:
                log_event(
                    request_logger,
                    logging.ERROR,
                    "request_exception",
                    project_id=project.project_id,
                    method="POST",
                    path=parsed.path,
                    error=traceback.format_exc(),
                )
                self._send_rpc_error(payload.get("id"), -32603, "Internal server error")
            finally:
                request_log.finish(request_logger, "request_complete", int(self._response_status), project_id=project.project_id)

        def log_message(self, format: str, *args: object) -> None:
            log_event(request_logger, logging.INFO, "server_message", project_id=project.project_id, message=format % args if args else format)

        def _read_json_body(self) -> dict[str, Any] | None:
            content_length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(content_length)
            try:
                parsed = json.loads(raw_body.decode("utf-8")) if raw_body else {}
            except json.JSONDecodeError:
                self._send_rpc_error(None, -32700, "Request body must be valid JSON")
                return None
            if not isinstance(parsed, dict):
                self._send_rpc_error(None, -32600, "MCP request must be a JSON object")
                return None
            return parsed

        def _send_json(
            self,
            payload: Any,
            status: HTTPStatus = HTTPStatus.OK,
            headers: dict[str, str] | None = None,
        ) -> None:
            body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
            self._response_status = status
            self.send_response(status.value)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            for name, value in (headers or {}).items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        def _send_accepted(self) -> None:
            self._response_status = HTTPStatus.ACCEPTED
            self.send_response(HTTPStatus.ACCEPTED.value)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _send_rpc_result(self, request_id: Any, result: Any, headers: dict[str, str] | None = None) -> None:
            self._send_json({"jsonrpc": "2.0", "id": request_id, "result": result}, headers=headers)

        def _send_rpc_error(self, request_id: Any, code: int, message: str) -> None:
            self._send_json({"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}})

    return RequestHandler


def _build_prompts() -> dict[str, PromptSpec]:
    common_arguments = [
        {"name": "task", "description": "Current analysis task or user goal.", "required": False},
        {"name": "binary_id", "description": "Binary/workspace identifier to prefer in examples.", "required": False},
        {"name": "focus_entity", "description": "Record id or slug the agent should focus on.", "required": False},
    ]
    return {
        "agent_workspace_guide": PromptSpec(
            name="agent_workspace_guide",
            description="Guide an agent through safe mcp-memory workspace discovery and writes.",
            arguments=common_arguments,
            renderer=lambda project, arguments: _render_agent_workspace_guide(project, arguments),
        ),
        "record_function_analysis": PromptSpec(
            name="record_function_analysis",
            description="Explain how to create or update function analysis records.",
            arguments=common_arguments,
            renderer=lambda project, arguments: _render_function_prompt(project, arguments),
        ),
        "record_structure_analysis": PromptSpec(
            name="record_structure_analysis",
            description="Explain how to record structures and their fields.",
            arguments=common_arguments,
            renderer=lambda project, arguments: _render_structure_prompt(project, arguments),
        ),
        "record_hypothesis_evidence": PromptSpec(
            name="record_hypothesis_evidence",
            description="Explain how to keep facts, hypotheses, evidence, and relations separate.",
            arguments=common_arguments,
            renderer=lambda project, arguments: _render_hypothesis_evidence_prompt(project, arguments),
        ),
        "search_and_graph_workflow": PromptSpec(
            name="search_and_graph_workflow",
            description="Explain how to search records and build context through graph relations.",
            arguments=common_arguments,
            renderer=lambda project, arguments: _render_search_graph_prompt(project, arguments),
        ),
    }


def _prompt_context(project: ProjectConfig, arguments: dict[str, str]) -> str:
    task = arguments.get("task", "").strip() or "No task argument provided."
    binary_id = arguments.get("binary_id", "").strip() or "<binary_id>"
    focus_entity = arguments.get("focus_entity", "").strip() or "<record_id_or_slug>"
    write_mode_note = (
        "Writes are applied immediately."
        if project.write_mode == "auto"
        else "Writes return pending changes; call list_pending_changes and confirm_change before assuming data was committed."
    )
    return "\n".join(
        [
            "Active mcp-memory project:",
            f"- project_id: {project.project_id}",
            f"- display_name: {project.display_name}",
            f"- write_mode: {project.write_mode}",
            f"- http_endpoint: http://{project.http_host}:{project.http_port}",
            f"- mcp_endpoint: http://{project.mcp_host}:{project.mcp_port}/mcp",
            f"- write_mode_rule: {write_mode_note}",
            f"- task: {task}",
            f"- preferred_binary_id: {binary_id}",
            f"- focus_entity: {focus_entity}",
        ]
    )


def _json_example(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _schema_agent_reference(project: ProjectConfig) -> str:
    schema = load_project_schema(project.schema_path)
    lines = ["Active project schema:"]
    for entity in schema.entity_types:
        fields = ", ".join(f"{field.name}({field.widget})" for field in entity.fields) or "<none>"
        required = ", ".join(entity.required) or "<none>"
        slug = entity.slug_field or "<none>"
        title = entity.title_field or "<none>"
        summary = entity.summary_field or "<none>"
        search = ", ".join(entity.search_fields) or "<none>"
        tags = ", ".join(entity.tag_fields) or "<none>"
        lines.extend(
            [
                f"- entity_type={entity.name} label={entity.label}",
                f"  required payload fields: {required}",
                f"  all payload fields: {fields}",
                f"  title_field={title}; summary_field={summary}; slug_field={slug}",
                f"  search_fields={search}; tag_fields={tags}",
            ]
        )
    if schema.relation_types:
        lines.append("Allowed relation types:")
        for relation in schema.relation_types:
            from_types = ", ".join(relation.from_types)
            to_types = ", ".join(relation.to_types)
            direction = "directed" if relation.directed else "undirected"
            lines.append(f"- {relation.name}: from [{from_types}] to [{to_types}], {direction}")
    else:
        lines.append("Allowed relation types: <none>")
    return "\n".join(lines)


def entity_payload_reference(schema: ProjectSchema) -> str:
    lines = ["Entity payload fields for upsert_record:"]
    for entity in schema.entity_types:
        all_fields = [field.name for field in entity.fields]
        optional = [field_name for field_name in all_fields if field_name not in set(entity.required)]
        required = ", ".join(entity.required) or "<none>"
        optional_text = ", ".join(optional) or "<none>"
        slug = entity.slug_field or "<none>"
        title = entity.title_field or "<none>"
        summary = entity.summary_field or "<none>"
        lines.extend(
            [
                f"entity_type={entity.name}",
                f"required payload fields: {required}",
                f"optional payload fields: {optional_text}",
                f"slug_field={slug}; title_field={title}; summary_field={summary}",
                "example upsert_record:",
                _json_example(
                    {
                        "entity_type": entity.name,
                        "payload": _example_payload_for_entity(schema, entity.name),
                        "created_by": "agent",
                        "updated_by": "agent",
                    }
                ),
            ]
        )
    return "\n".join(lines)


def tool_usage_reference(project: ProjectConfig, focus_entity: str = "") -> str:
    schema = load_project_schema(project.schema_path)
    specs = _tool_usage_specs()
    lines = ["Tool usage examples:"]
    for tool_name, fields in specs.items():
        required = ", ".join(fields["required"]) or "<none>"
        optional = ", ".join(fields["optional"]) or "<none>"
        lines.extend(
            [
                f"tool: {tool_name}",
                f"required top-level fields: {required}",
                f"optional top-level fields: {optional}",
                "example:",
                _json_example(tool_example(tool_name, schema, project, focus_entity)),
            ]
        )
        if tool_name == "create_relation" and not schema.relation_types:
            lines.append("relation_type note: choose or create a relation type in schema before calling create_relation.")
    return "\n".join(lines)


def tool_example(tool_name: str, schema: ProjectSchema, project: ProjectConfig, focus_entity: str = "") -> dict[str, Any]:
    entity_type = _first_entity(schema)
    record_id = focus_entity.strip() or f"{entity_type}-example"
    relation = schema.relation_types[0] if schema.relation_types else None
    from_entity_type = _relation_example_type(relation.from_types if relation else [], entity_type)
    to_entity_type = _relation_example_type(relation.to_types if relation else [], entity_type)
    examples: dict[str, dict[str, Any]] = {
        "get_project_config": {},
        "get_schema": {},
        "list_entity_types": {},
        "search_records": {"q": "startup", "entity_types": [entity_type], "limit": 20},
        "get_record": {"entity_type": entity_type, "record_id": record_id},
        "upsert_record": {
            "entity_type": entity_type,
            "payload": _example_payload_for_entity(schema, entity_type),
            "created_by": "agent",
            "updated_by": "agent",
        },
        "archive_record": {"entity_type": entity_type, "record_id": record_id, "archived_by": "agent"},
        "get_related": {"entity_type": entity_type, "record_id": record_id, "hops": 1},
        "add_evidence": {
            "entity_type": entity_type,
            "record_id": record_id,
            "evidence_type": "excerpt",
            "description": "Short source excerpt that supports this record.",
            "excerpt": "Relevant source text or observation.",
            "created_by": "agent",
        },
        "create_relation": {
            "from_entity_type": from_entity_type,
            "from_record_id": f"{from_entity_type}-source",
            "to_entity_type": to_entity_type,
            "to_record_id": f"{to_entity_type}-target",
            "relation_type": relation.name if relation else "<schema_relation_type>",
            "created_by": "agent",
        },
        "list_pending_changes": {"status": "pending"},
        "confirm_change": {"pending_change_id": "pending-change-id", "confirmed_by": "agent"},
        "reject_change": {"pending_change_id": "pending-change-id", "rejected_by": "agent"},
        "export_json": {"output_path": str(project.exports_dir / "agent-export.json")},
        "import_json": {"input_path": str(project.exports_dir / "agent-export.json"), "replace_existing": False},
        "backup_project": {"output_path": str(project.backups_dir / "agent-backup.zip")},
        "restore_project": {
            "input_path": str(project.backups_dir / "agent-backup.zip"),
            "project_root": str(project.project_root.parent / "restored-project"),
            "project_id": "restored-project",
            "display_name": "Restored Project",
        },
    }
    return examples[tool_name]


def _tool_usage_specs() -> dict[str, dict[str, list[str]]]:
    return {
        "get_project_config": {"required": [], "optional": []},
        "get_schema": {"required": [], "optional": []},
        "list_entity_types": {"required": [], "optional": []},
        "search_records": {"required": [], "optional": ["q", "entity_types", "tag", "limit"]},
        "get_record": {"required": ["entity_type", "record_id"], "optional": ["include_archived"]},
        "upsert_record": {"required": ["entity_type", "payload"], "optional": ["record_id", "source_origin", "created_by", "updated_by"]},
        "archive_record": {"required": ["entity_type", "record_id"], "optional": ["archived_by"]},
        "get_related": {"required": ["entity_type", "record_id"], "optional": ["hops"]},
        "add_evidence": {
            "required": ["entity_type", "record_id", "evidence_type", "description"],
            "optional": ["evidence_id", "excerpt", "source_url", "attachment_refs", "created_by"],
        },
        "create_relation": {
            "required": ["from_entity_type", "from_record_id", "to_entity_type", "to_record_id", "relation_type"],
            "optional": ["created_by"],
        },
        "list_pending_changes": {"required": [], "optional": ["status"]},
        "confirm_change": {"required": ["pending_change_id"], "optional": ["confirmed_by"]},
        "reject_change": {"required": ["pending_change_id"], "optional": ["rejected_by"]},
        "export_json": {"required": [], "optional": ["output_path"]},
        "import_json": {"required": ["input_path"], "optional": ["replace_existing"]},
        "backup_project": {"required": [], "optional": ["output_path"]},
        "restore_project": {
            "required": ["input_path", "project_root"],
            "optional": ["project_id", "display_name", "http_port", "mcp_port", "write_mode"],
        },
    }


def _relation_example_type(candidates: list[str], fallback: str) -> str:
    if not candidates or candidates[0] == "*":
        return fallback
    return candidates[0]


def _first_entity(schema: ProjectSchema) -> str:
    return schema.entity_types[0].name


def _example_payload_for_entity(schema: ProjectSchema, entity_type: str) -> dict[str, Any]:
    entity = schema.entity(entity_type)
    payload: dict[str, Any] = {}
    for field in entity.fields:
        if field.widget == "tags":
            value: Any = ["agent-note"]
        elif field.widget == "number":
            value = 1
        elif field.widget == "bool":
            value = True
        elif field.widget == "json":
            value = {"source": "agent"}
        elif field.widget == "enum":
            value = field.options[0] if field.options else "value"
        elif field.name == entity.slug_field:
            value = f"{entity.name}-example"
        elif field.name == entity.title_field or field.name in entity.required:
            value = f"{entity.label} example"
        elif field.name == entity.summary_field:
            value = f"Short summary for {entity.label.lower()}."
        else:
            value = f"{field.label} value"
        payload[field.name] = value
    for required_field in entity.required:
        payload.setdefault(required_field, f"{required_field} value")
    return payload


def _render_agent_workspace_guide(project: ProjectConfig, arguments: dict[str, str]) -> str:
    schema = load_project_schema(project.schema_path)
    entity_type = _first_entity(schema)
    focus_entity = arguments.get("focus_entity", "").strip() or f"{entity_type}-example"
    return f"""{_prompt_context(project, arguments)}

Use this server as a local offline-first schema-first knowledge base. The project schema defines which entity types exist and which payload fields are required.

{_schema_agent_reference(project)}

{entity_payload_reference(schema)}

Recommended workflow:
1. Call get_project_config first and check write_mode.
2. Call get_schema or list_entity_types before writing. Never invent entity types or relation types outside the schema.
3. Search before writing: use search_records with q, tag, entity_types, and limit.
4. Read exact records with get_record before updating them.
4. Expand local context with get_related for 1-2 hops.
5. Keep records, evidence, and relations separate. Put claims in records; attach supporting excerpts/files with add_evidence; connect records with create_relation.
6. In confirm mode, create/update tools return pending changes. Confirm with confirm_change only after reviewing list_pending_changes.
7. In auto mode, create/update tools commit immediately.

Required top-level fields by write tool:
- upsert_record: entity_type, payload. Payload must include every required field listed above for that entity type. record_id is optional on create and generated as UUID when omitted. If the entity has slug_field, that payload field is optional but must be unique when present.
- archive_record: entity_type, record_id.
- add_evidence: entity_type, record_id, evidence_type, description.
- create_relation: from_entity_type, from_record_id, to_entity_type, to_record_id, relation_type. relation_type must be allowed by the schema for the from/to entity pair.
- confirm_change/reject_change: pending_change_id.
- import_json: input_path.
- restore_project: input_path, project_root.

{tool_usage_reference(project, focus_entity)}

Safe search example:
{_json_example({"q": "startup", "entity_types": [entity_type], "limit": 20})}

Focused read example:
{_json_example({"entity_type": entity_type, "record_id": focus_entity})}

Create/update example:
{_json_example({
    "entity_type": entity_type,
    "payload": _example_payload_for_entity(schema, entity_type),
    "created_by": "agent",
    "updated_by": "agent",
})}

FTS warning: avoid raw hyphenated query text such as gui-seed. Search individual words like gui seed, or use tag='gui-seed' until FTS escaping is fixed."""


def _render_function_prompt(project: ProjectConfig, arguments: dict[str, str]) -> str:
    schema = load_project_schema(project.schema_path)
    entity_type = "function" if any(item.name == "function" for item in schema.entity_types) else _first_entity(schema)
    return f"""{_prompt_context(project, arguments)}

Use upsert_record to create or update analysis records. The old fixed create_function/update_function tools are not part of the generic MCP surface.

{_schema_agent_reference(project)}

{entity_payload_reference(schema)}

For upsert_record, required top-level fields are entity_type and payload. The payload must include the required payload fields listed for that entity type above. Include created_by and updated_by for audit clarity.

Good upsert_record payload:
{_json_example({
    "entity_type": entity_type,
    "payload": _example_payload_for_entity(schema, entity_type),
    "created_by": "agent",
    "updated_by": "agent",
})}

If write_mode is confirm, capture pending_change_id and ask for/perform confirm_change only after review."""


def _render_structure_prompt(project: ProjectConfig, arguments: dict[str, str]) -> str:
    schema = load_project_schema(project.schema_path)
    entity_type = "structure" if any(item.name == "structure" for item in schema.entity_types) else _first_entity(schema)
    return f"""{_prompt_context(project, arguments)}

Use upsert_record for recovered layouts or any other schema-defined entity. The old fixed create_structure/update_structure tools are not part of the generic MCP surface.

{_schema_agent_reference(project)}

{entity_payload_reference(schema)}

For upsert_record, required top-level fields are entity_type and payload. The payload must include the required payload fields listed for that entity type above.

Good upsert_record payload:
{_json_example({
    "entity_type": entity_type,
    "payload": _example_payload_for_entity(schema, entity_type),
    "created_by": "agent",
    "updated_by": "agent",
})}

Link records with create_relation only using relation types allowed by the active schema."""


def _render_hypothesis_evidence_prompt(project: ProjectConfig, arguments: dict[str, str]) -> str:
    schema = load_project_schema(project.schema_path)
    entity_type = "hypothesis" if any(item.name == "hypothesis" for item in schema.entity_types) else _first_entity(schema)
    focus_entity = arguments.get("focus_entity", "").strip() or f"{entity_type}-example"
    return f"""{_prompt_context(project, arguments)}

Use records for claims and notes, add_evidence for concrete support such as blocks, excerpts, xrefs, or attachments, and create_relation for graph edges between records.

{_schema_agent_reference(project)}

{entity_payload_reference(schema)}

Required top-level fields:
- upsert_record: entity_type, payload. Payload must include the required fields for the chosen entity type.
- add_evidence: entity_type, record_id, evidence_type, description.
- create_relation: from_entity_type, from_record_id, to_entity_type, to_record_id, relation_type.

Record example:
{_json_example({
    "entity_type": entity_type,
    "payload": _example_payload_for_entity(schema, entity_type),
    "created_by": "agent",
    "updated_by": "agent",
})}

Evidence example:
{_json_example({
    "evidence_id": "ev_startup_log_001",
    "entity_type": entity_type,
    "record_id": focus_entity,
    "evidence_type": "log",
    "description": "Startup log excerpt that supports this record.",
    "excerpt": "GET /health ... POST /mcp",
    "created_by": "agent",
})}

Relation example:
{_json_example({
    "from_entity_type": entity_type,
    "from_record_id": focus_entity,
    "to_entity_type": entity_type,
    "to_record_id": focus_entity,
    "relation_type": schema.relation_types[0].name if schema.relation_types else "related_to",
    "created_by": "agent",
})}"""


def _render_search_graph_prompt(project: ProjectConfig, arguments: dict[str, str]) -> str:
    schema = load_project_schema(project.schema_path)
    entity_type = _first_entity(schema)
    focus_entity = arguments.get("focus_entity", "").strip() or f"{entity_type}-example"
    return f"""{_prompt_context(project, arguments)}

Use search_records for discovery, get_record for exact reads, and get_related for graph expansion. Prefer a small loop: search -> read -> related -> read linked records -> write only what is supported.

{_schema_agent_reference(project)}

{entity_payload_reference(schema)}

Search examples:
{_json_example({"q": "Synthetic", "limit": 50})}
{_json_example({"tag": "gui-seed", "limit": 50})}
{_json_example({"q": "startup", "entity_types": [entity_type], "limit": 10})}

Graph context examples:
{_json_example({"entity_type": entity_type, "record_id": focus_entity, "hops": 1})}
{_json_example({"entity_type": entity_type, "record_id": focus_entity, "hops": 2})}

When adding graph edges, use only relation types allowed by the active schema."""


def _build_tools() -> dict[str, ToolSpec]:
    return _build_generic_tools()


def _build_generic_tools() -> dict[str, ToolSpec]:
    return {
        "get_project_config": ToolSpec(
            name="get_project_config",
            description="Return active project configuration and local endpoints.",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            handler=_tool_get_project_config,
        ),
        "get_schema": ToolSpec(
            name="get_schema",
            description="Return the active project schema.",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            handler=_tool_get_schema,
        ),
        "list_entity_types": ToolSpec(
            name="list_entity_types",
            description="List entity types from the active project schema.",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            handler=_tool_list_entity_types,
        ),
        "search_records": ToolSpec(
            name="search_records",
            description="Search generic project records using SQLite FTS.",
            input_schema={
                "type": "object",
                "properties": {
                    "q": {"type": "string"},
                    "entity_types": {"type": "array", "items": {"type": "string"}},
                    "tag": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "additionalProperties": False,
            },
            handler=_tool_search_records,
        ),
        "get_record": ToolSpec(
            name="get_record",
            description="Fetch a generic record by entity type and UUID or slug.",
            input_schema={
                "type": "object",
                "properties": {
                    "entity_type": {"type": "string"},
                    "record_id": {"type": "string"},
                    "include_archived": {"type": "boolean"},
                },
                "required": ["entity_type", "record_id"],
                "additionalProperties": False,
            },
            handler=_tool_get_record,
        ),
        "upsert_record": ToolSpec(
            name="upsert_record",
            description=(
                "Create or update a generic record. Required top-level fields: entity_type, payload. "
                "Optional top-level fields: record_id, source_origin, created_by, updated_by. "
                "Payload fields are schema-specific; call prompts/get agent_workspace_guide or get_schema before writing."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "entity_type": {"type": "string", "description": "Schema entity type name."},
                    "record_id": {"type": "string", "description": "Optional UUID or existing record id/slug to update."},
                    "payload": {
                        "type": "object",
                        "description": (
                            "Schema-specific record fields. Must include every required payload field for this entity_type. "
                            "Optional payload fields also come from get_schema or prompts/get agent_workspace_guide."
                        ),
                    },
                    "source_origin": {"type": "string"},
                    "created_by": {"type": "string"},
                    "updated_by": {"type": "string"},
                },
                "required": ["entity_type", "payload"],
                "additionalProperties": False,
            },
            handler=_tool_upsert_record,
        ),
        "archive_record": ToolSpec(
            name="archive_record",
            description=(
                "Soft-archive a generic record. Required top-level fields: entity_type, record_id. "
                "Optional top-level fields: archived_by. In confirm mode, returns a pending change."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "entity_type": {"type": "string"},
                    "record_id": {"type": "string"},
                    "archived_by": {"type": "string"},
                },
                "required": ["entity_type", "record_id"],
                "additionalProperties": False,
            },
            handler=_tool_archive_record,
        ),
        "get_related": ToolSpec(
            name="get_related",
            description="Traverse generic typed relations for a record by one or two hops.",
            input_schema={
                "type": "object",
                "properties": {
                    "entity_type": {"type": "string"},
                    "record_id": {"type": "string"},
                    "hops": {"type": "integer"},
                },
                "required": ["entity_type", "record_id"],
                "additionalProperties": False,
            },
            handler=_tool_get_related,
        ),
        "add_evidence": ToolSpec(
            name="add_evidence",
            description=(
                "Attach evidence to a generic record. Required top-level fields: entity_type, record_id, "
                "evidence_type, description. Optional top-level fields: evidence_id, excerpt, source_url, "
                "attachment_refs, created_by."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "entity_type": {"type": "string"},
                    "record_id": {"type": "string"},
                    "evidence_id": {"type": "string"},
                    "evidence_type": {"type": "string"},
                    "description": {"type": "string"},
                    "excerpt": {"type": "string"},
                    "source_url": {"type": "string"},
                    "attachment_refs": {"type": "array", "items": {"type": "object"}},
                    "created_by": {"type": "string"},
                },
                "required": ["entity_type", "record_id", "evidence_type", "description"],
                "additionalProperties": False,
            },
            handler=_tool_add_evidence,
        ),
        "create_relation": ToolSpec(
            name="create_relation",
            description=(
                "Create a typed relation between two generic records. Required top-level fields: "
                "from_entity_type, from_record_id, to_entity_type, to_record_id, relation_type. "
                "Optional top-level fields: created_by. relation_type must be allowed by the active schema."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "from_entity_type": {"type": "string"},
                    "from_record_id": {"type": "string"},
                    "to_entity_type": {"type": "string"},
                    "to_record_id": {"type": "string"},
                    "relation_type": {"type": "string"},
                    "created_by": {"type": "string"},
                },
                "required": [
                    "from_entity_type",
                    "from_record_id",
                    "to_entity_type",
                    "to_record_id",
                    "relation_type",
                ],
                "additionalProperties": False,
            },
            handler=_tool_create_relation,
        ),
        "list_pending_changes": ToolSpec(
            name="list_pending_changes",
            description="List pending change proposals for the active project.",
            input_schema={
                "type": "object",
                "properties": {"status": {"type": "string"}},
                "additionalProperties": False,
            },
            handler=_tool_list_pending_changes,
        ),
        "confirm_change": ToolSpec(
            name="confirm_change",
            description="Apply a pending change proposal.",
            input_schema={
                "type": "object",
                "properties": {
                    "pending_change_id": {"type": "string"},
                    "confirmed_by": {"type": "string"},
                },
                "required": ["pending_change_id"],
                "additionalProperties": False,
            },
            handler=_tool_confirm_change,
        ),
        "reject_change": ToolSpec(
            name="reject_change",
            description="Reject a pending change proposal.",
            input_schema={
                "type": "object",
                "properties": {
                    "pending_change_id": {"type": "string"},
                    "rejected_by": {"type": "string"},
                },
                "required": ["pending_change_id"],
                "additionalProperties": False,
            },
            handler=_tool_reject_change,
        ),
        "export_json": ToolSpec(
            name="export_json",
            description="Export project records into a JSON bundle on disk.",
            input_schema={
                "type": "object",
                "properties": {"output_path": {"type": "string"}},
                "additionalProperties": False,
            },
            handler=_tool_export_json,
        ),
        "import_json": ToolSpec(
            name="import_json",
            description="Import project records from a JSON bundle on disk.",
            input_schema={
                "type": "object",
                "properties": {
                    "input_path": {"type": "string"},
                    "replace_existing": {"type": "boolean"},
                },
                "required": ["input_path"],
                "additionalProperties": False,
            },
            handler=_tool_import_json,
        ),
        "backup_project": ToolSpec(
            name="backup_project",
            description="Create a zip backup of the active project workspace.",
            input_schema={
                "type": "object",
                "properties": {"output_path": {"type": "string"}},
                "additionalProperties": False,
            },
            handler=_tool_backup_project,
        ),
        "restore_project": ToolSpec(
            name="restore_project",
            description="Restore a project workspace from a zip backup.",
            input_schema={
                "type": "object",
                "properties": {
                    "input_path": {"type": "string"},
                    "project_root": {"type": "string"},
                    "project_id": {"type": "string"},
                    "display_name": {"type": "string"},
                    "http_port": {"type": "integer"},
                    "mcp_port": {"type": "integer"},
                    "write_mode": {"type": "string"},
                },
                "required": ["input_path", "project_root"],
                "additionalProperties": False,
            },
            handler=_tool_restore_project,
        ),
    }


def _tool_get_project_config(project: ProjectConfig, registry: ProjectRegistry, arguments: dict[str, Any]) -> dict[str, Any]:
    _ = registry
    _ = arguments
    return {
        "project": serialize(project),
        "connection": {
            "http": {"host": project.http_host, "port": project.http_port},
            "mcp": {"host": project.mcp_host, "port": project.mcp_port},
        },
    }


def _tool_get_schema(project: ProjectConfig, registry: ProjectRegistry, arguments: dict[str, Any]) -> dict[str, Any]:
    _ = registry
    _ = arguments
    with open_database(project.database_path) as database:
        return ProjectDispatcher(database, project).dispatch(GetSchemaQuery()).data


def _tool_list_entity_types(project: ProjectConfig, registry: ProjectRegistry, arguments: dict[str, Any]) -> dict[str, Any]:
    _ = registry
    _ = arguments
    with open_database(project.database_path) as database:
        return {"items": ProjectDispatcher(database, project).dispatch(ListEntityTypesQuery()).data}


def _tool_search_records(project: ProjectConfig, registry: ProjectRegistry, arguments: dict[str, Any]) -> dict[str, Any]:
    _ = registry
    with open_database(project.database_path) as database:
        result = ProjectDispatcher(database, project).dispatch(
            SearchRecordsQuery(
                q=str(arguments.get("q", "")).strip(),
                entity_types=[str(item) for item in arguments.get("entity_types", [])] or None,
                tag=None if arguments.get("tag") is None else str(arguments["tag"]),
                limit=int(arguments.get("limit", 10)),
            )
        )
    return result.data


def _tool_get_record(project: ProjectConfig, registry: ProjectRegistry, arguments: dict[str, Any]) -> Any:
    _ = registry
    entity_type = str(arguments["entity_type"])
    record_id = str(arguments["record_id"])
    with open_database(project.database_path) as database:
        record = ProjectDispatcher(database, project).dispatch(
            GetRecordQuery(entity_type, record_id, include_archived=bool(arguments.get("include_archived", False)))
        ).data
    if record is None:
        raise McpRequestError("Record not found")
    return serialize(record)


def _tool_get_related(project: ProjectConfig, registry: ProjectRegistry, arguments: dict[str, Any]) -> dict[str, Any]:
    _ = registry
    with open_database(project.database_path) as database:
        result = ProjectDispatcher(database, project).dispatch(
            GetRelatedQuery(str(arguments["entity_type"]), str(arguments["record_id"]), int(arguments.get("hops", 1)))
        )
    return result.data


def _tool_upsert_record(project: ProjectConfig, registry: ProjectRegistry, arguments: dict[str, Any]) -> Any:
    _ = registry
    payload = arguments.get("payload", arguments)
    if not isinstance(payload, dict):
        raise McpRequestError("payload must be an object")
    workflow_payload = {
        "entity_type": str(arguments["entity_type"]),
        "record_id": arguments.get("record_id"),
        "payload": payload,
        "source_origin": str(arguments.get("source_origin", "mcp")),
        "created_by": str(arguments.get("created_by", "mcp")),
        "updated_by": str(arguments.get("updated_by", arguments.get("created_by", "mcp"))),
    }
    with open_database(project.database_path) as database:
        result = GenericWorkflowService(database, project).apply_or_queue(
            "upsert_record",
            workflow_payload,
            created_by=str(arguments.get("created_by", "mcp")),
        )
    return result.data if hasattr(result, "data") else result


def _tool_archive_record(project: ProjectConfig, registry: ProjectRegistry, arguments: dict[str, Any]) -> Any:
    _ = registry
    with open_database(project.database_path) as database:
        result = GenericWorkflowService(database, project).apply_or_queue(
            "archive_record",
            {
                "entity_type": str(arguments["entity_type"]),
                "record_id_or_slug": str(arguments["record_id"]),
                "archived_by": str(arguments.get("archived_by", "mcp")),
            },
            created_by=str(arguments.get("archived_by", "mcp")),
        )
    return result.data if hasattr(result, "data") else result


def _tool_add_evidence(project: ProjectConfig, registry: ProjectRegistry, arguments: dict[str, Any]) -> Any:
    _ = registry
    with open_database(project.database_path) as database:
        result = GenericWorkflowService(database, project).apply_or_queue(
            "add_evidence",
            arguments,
            created_by=str(arguments.get("created_by", "mcp")),
        )
    return result.data if hasattr(result, "data") else result


def _tool_create_relation(project: ProjectConfig, registry: ProjectRegistry, arguments: dict[str, Any]) -> Any:
    _ = registry
    with open_database(project.database_path) as database:
        result = GenericWorkflowService(database, project).apply_or_queue(
            "create_relation",
            arguments,
            created_by=str(arguments.get("created_by", "mcp")),
        )
    return result.data if hasattr(result, "data") else result


def _tool_list_pending_changes(project: ProjectConfig, registry: ProjectRegistry, arguments: dict[str, Any]) -> dict[str, Any]:
    _ = registry
    status = None if arguments.get("status") == "all" else arguments.get("status", "pending")
    with open_database(project.database_path) as database:
        items = GenericWorkflowService(database, project).list_pending_changes(status=status)
    return {"items": serialize(items)}


def _tool_confirm_change(project: ProjectConfig, registry: ProjectRegistry, arguments: dict[str, Any]) -> dict[str, Any]:
    _ = registry
    with open_database(project.database_path) as database:
        return serialize(
            GenericWorkflowService(database, project).confirm_change(
                str(arguments["pending_change_id"]),
                confirmed_by=str(arguments.get("confirmed_by", "mcp")),
                actor_type="agent",
            )
        )


def _tool_reject_change(project: ProjectConfig, registry: ProjectRegistry, arguments: dict[str, Any]) -> Any:
    _ = registry
    with open_database(project.database_path) as database:
        return serialize(
            GenericWorkflowService(database, project).reject_change(
                str(arguments["pending_change_id"]),
                rejected_by=str(arguments.get("rejected_by", "mcp")),
            )
        )


def _tool_export_json(project: ProjectConfig, registry: ProjectRegistry, arguments: dict[str, Any]) -> dict[str, Any]:
    _ = registry
    return ProjectTransferService().export_project(
        project,
        None if arguments.get("output_path") is None else Path(str(arguments["output_path"])).expanduser().resolve(),
    )


def _tool_import_json(project: ProjectConfig, registry: ProjectRegistry, arguments: dict[str, Any]) -> dict[str, Any]:
    _ = registry
    return ProjectTransferService().import_project(
        project,
        Path(str(arguments["input_path"])).expanduser().resolve(),
        replace_existing=bool(arguments.get("replace_existing", False)),
    )


def _tool_backup_project(project: ProjectConfig, registry: ProjectRegistry, arguments: dict[str, Any]) -> dict[str, Any]:
    return ProjectArchiveService(registry).create_backup(
        project,
        None if arguments.get("output_path") is None else Path(str(arguments["output_path"])).expanduser().resolve(),
    )


def _tool_restore_project(project: ProjectConfig, registry: ProjectRegistry, arguments: dict[str, Any]) -> dict[str, Any]:
    _ = project
    config = ProjectArchiveService(registry).restore_backup(
        input_path=Path(str(arguments["input_path"])).expanduser().resolve(),
        project_root=Path(str(arguments["project_root"])).expanduser().resolve(),
        project_id=None if arguments.get("project_id") is None else str(arguments["project_id"]),
        display_name=None if arguments.get("display_name") is None else str(arguments["display_name"]),
        http_port=None if arguments.get("http_port") is None else int(arguments["http_port"]),
        mcp_port=None if arguments.get("mcp_port") is None else int(arguments["mcp_port"]),
        write_mode=None if arguments.get("write_mode") is None else str(arguments["write_mode"]),
    )
    return serialize(config)
