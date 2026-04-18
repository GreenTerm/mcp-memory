from __future__ import annotations

import json
import logging
import traceback
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from mcp_memory.api.server import (
    _apply_or_queue_evidence,
    _apply_or_queue_function,
    _apply_or_queue_global_hypothesis,
    _apply_or_queue_relation,
    _apply_or_queue_structure,
    serialize,
)
from mcp_memory.config import ProjectConfig, ProjectRegistry
from mcp_memory.logging_utils import configure_logging, get_logger, log_event, start_request_log
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
)
from mcp_memory.storage import open_database


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[[ProjectConfig, ProjectRegistry, dict[str, Any]], Any]


class McpRequestError(ValueError):
    """Raised when an MCP request is malformed."""


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
    server = HTTPServer((host, port), handler)
    log_event(logger, logging.INFO, "server_start", project_id=project.project_id, host=host, port=port)
    server.serve_forever()


def build_handler(
    project: ProjectConfig,
    registry: ProjectRegistry,
    logger: logging.Logger | None = None,
) -> type[BaseHTTPRequestHandler]:
    tools = _build_tools()
    request_logger = logger or get_logger("mcp")

    class RequestHandler(BaseHTTPRequestHandler):
        server_version = "mcp-memory-mcp/0.1"

        def do_GET(self) -> None:
            request_log = start_request_log("GET", self.path)
            self._response_status = HTTPStatus.OK
            parsed = urlparse(self.path)
            if parsed.path == "/health":
                self._send_json({"status": "ok", "project_id": project.project_id})
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
                request_id = payload.get("id")
                method = str(payload["method"])
                params = payload.get("params", {})
                if not isinstance(params, dict):
                    raise McpRequestError("params must be an object")

                if method == "initialize":
                    self._send_rpc_result(
                        request_id,
                        {
                            "protocolVersion": "2025-03-26",
                            "serverInfo": {"name": "mcp-memory", "version": "0.1.0"},
                            "capabilities": {"tools": {"listChanged": False}},
                        },
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

        def _send_json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
            body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
            self._response_status = status
            self.send_response(status.value)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_rpc_result(self, request_id: Any, result: Any) -> None:
            self._send_json({"jsonrpc": "2.0", "id": request_id, "result": result})

        def _send_rpc_error(self, request_id: Any, code: int, message: str) -> None:
            self._send_json({"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}})

    return RequestHandler


def _build_tools() -> dict[str, ToolSpec]:
    return {
        "get_project_config": ToolSpec(
            name="get_project_config",
            description="Return the active project configuration and connection details.",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            handler=_tool_get_project_config,
        ),
        "search_records": ToolSpec(
            name="search_records",
            description="Search project records using exact matches and SQLite FTS.",
            input_schema={
                "type": "object",
                "properties": {
                    "q": {"type": "string"},
                    "entity_types": {"type": "array", "items": {"type": "string"}},
                    "binary_id": {"type": "string"},
                    "tag": {"type": "string"},
                    "address": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "additionalProperties": False,
            },
            handler=_tool_search_records,
        ),
        "get_record": ToolSpec(
            name="get_record",
            description="Fetch a function, structure, or global hypothesis record by identifier.",
            input_schema={
                "type": "object",
                "properties": {
                    "entity_type": {"type": "string"},
                    "entity_id": {"type": "string"},
                    "binary_id": {"type": "string"},
                },
                "required": ["entity_type", "entity_id"],
                "additionalProperties": False,
            },
            handler=_tool_get_record,
        ),
        "get_related": ToolSpec(
            name="get_related",
            description="Traverse relations for an entity by one or two hops.",
            input_schema={
                "type": "object",
                "properties": {
                    "entity_type": {"type": "string"},
                    "entity_id": {"type": "string"},
                    "hops": {"type": "integer"},
                },
                "required": ["entity_type", "entity_id"],
                "additionalProperties": False,
            },
            handler=_tool_get_related,
        ),
        "create_function": ToolSpec(
            name="create_function",
            description="Create or update a function record.",
            input_schema={"type": "object", "properties": {}, "additionalProperties": True},
            handler=_tool_create_function,
        ),
        "update_function": ToolSpec(
            name="update_function",
            description="Update an existing function record.",
            input_schema={"type": "object", "properties": {}, "additionalProperties": True},
            handler=_tool_create_function,
        ),
        "create_structure": ToolSpec(
            name="create_structure",
            description="Create or update a structure record.",
            input_schema={"type": "object", "properties": {}, "additionalProperties": True},
            handler=_tool_create_structure,
        ),
        "update_structure": ToolSpec(
            name="update_structure",
            description="Update an existing structure record.",
            input_schema={"type": "object", "properties": {}, "additionalProperties": True},
            handler=_tool_create_structure,
        ),
        "create_hypothesis": ToolSpec(
            name="create_hypothesis",
            description="Create or update a global hypothesis record.",
            input_schema={"type": "object", "properties": {}, "additionalProperties": True},
            handler=_tool_create_hypothesis,
        ),
        "add_evidence": ToolSpec(
            name="add_evidence",
            description="Attach evidence to an entity.",
            input_schema={"type": "object", "properties": {}, "additionalProperties": True},
            handler=_tool_add_evidence,
        ),
        "create_relation": ToolSpec(
            name="create_relation",
            description="Create a relation between two entities.",
            input_schema={
                "type": "object",
                "properties": {
                    "from_entity_type": {"type": "string"},
                    "from_entity_id": {"type": "string"},
                    "to_entity_type": {"type": "string"},
                    "to_entity_id": {"type": "string"},
                    "relation_type": {"type": "string"},
                    "created_by": {"type": "string"},
                },
                "required": [
                    "from_entity_type",
                    "from_entity_id",
                    "to_entity_type",
                    "to_entity_id",
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


def _tool_search_records(project: ProjectConfig, registry: ProjectRegistry, arguments: dict[str, Any]) -> dict[str, Any]:
    _ = registry
    with open_database(project.database_path) as database:
        items = SearchService(database).search(
            SearchQuery(
                project_id=project.project_id,
                query_text=str(arguments.get("q", "")).strip(),
                entity_types=[str(item) for item in arguments.get("entity_types", [])] or None,
                binary_id=None if arguments.get("binary_id") is None else str(arguments["binary_id"]),
                tag=None if arguments.get("tag") is None else str(arguments["tag"]),
                address=None if arguments.get("address") is None else str(arguments["address"]),
                limit=int(arguments.get("limit", 10)),
            )
        )
    return {"items": items}


def _tool_get_record(project: ProjectConfig, registry: ProjectRegistry, arguments: dict[str, Any]) -> Any:
    _ = registry
    entity_type = str(arguments["entity_type"])
    entity_id = str(arguments["entity_id"])
    with open_database(project.database_path) as database:
        if entity_type == "function":
            binary_id = str(arguments["binary_id"])
            record = FunctionService(database).get_function(project.project_id, binary_id, entity_id)
        elif entity_type == "structure":
            record = StructureService(database).get_structure(project.project_id, entity_id)
        elif entity_type == "global_hypothesis":
            record = GlobalHypothesisService(database).get_hypothesis(project.project_id, entity_id)
        else:
            raise McpRequestError(f"Unsupported entity_type: {entity_type}")
    if record is None:
        raise McpRequestError("Record not found")
    return serialize(record)


def _tool_get_related(project: ProjectConfig, registry: ProjectRegistry, arguments: dict[str, Any]) -> dict[str, Any]:
    _ = registry
    with open_database(project.database_path) as database:
        items = RelationService(database).traverse_related(
            project.project_id,
            str(arguments["entity_type"]),
            str(arguments["entity_id"]),
            int(arguments.get("hops", 1)),
        )
    return {"items": items}


def _tool_create_function(project: ProjectConfig, registry: ProjectRegistry, arguments: dict[str, Any]) -> Any:
    _ = registry
    with open_database(project.database_path) as database:
        return _apply_or_queue_function(project, database, arguments)["body"]


def _tool_create_structure(project: ProjectConfig, registry: ProjectRegistry, arguments: dict[str, Any]) -> Any:
    _ = registry
    with open_database(project.database_path) as database:
        return _apply_or_queue_structure(project, database, arguments)["body"]


def _tool_create_hypothesis(project: ProjectConfig, registry: ProjectRegistry, arguments: dict[str, Any]) -> Any:
    _ = registry
    with open_database(project.database_path) as database:
        return _apply_or_queue_global_hypothesis(project, database, arguments)["body"]


def _tool_add_evidence(project: ProjectConfig, registry: ProjectRegistry, arguments: dict[str, Any]) -> Any:
    _ = registry
    with open_database(project.database_path) as database:
        return _apply_or_queue_evidence(project, database, arguments)["body"]


def _tool_create_relation(project: ProjectConfig, registry: ProjectRegistry, arguments: dict[str, Any]) -> Any:
    _ = registry
    with open_database(project.database_path) as database:
        return _apply_or_queue_relation(project, database, arguments)["body"]


def _tool_list_pending_changes(project: ProjectConfig, registry: ProjectRegistry, arguments: dict[str, Any]) -> dict[str, Any]:
    _ = registry
    status = None if arguments.get("status") == "all" else arguments.get("status", "pending")
    with open_database(project.database_path) as database:
        items = PendingChangeService(database).list_pending_changes(project.project_id, status=status)
    return {"items": serialize(items)}


def _tool_confirm_change(project: ProjectConfig, registry: ProjectRegistry, arguments: dict[str, Any]) -> dict[str, Any]:
    _ = registry
    with open_database(project.database_path) as database:
        return serialize(
            PendingChangeService(database).confirm_change(
                project.project_id,
                str(arguments["pending_change_id"]),
                confirmed_by=str(arguments.get("confirmed_by", "mcp")),
                actor_type="agent",
            )
        )


def _tool_reject_change(project: ProjectConfig, registry: ProjectRegistry, arguments: dict[str, Any]) -> Any:
    _ = registry
    with open_database(project.database_path) as database:
        return serialize(
            PendingChangeService(database).reject_change(
                project.project_id,
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
