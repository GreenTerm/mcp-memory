from __future__ import annotations

import json
import logging
import traceback
import uuid
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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


@dataclass(frozen=True)
class PromptSpec:
    name: str
    description: str
    arguments: list[dict[str, Any]]
    renderer: Callable[[ProjectConfig, dict[str, str]], str]


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
        {"name": "focus_entity", "description": "Entity id or address the agent should focus on.", "required": False},
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
    focus_entity = arguments.get("focus_entity", "").strip() or "<entity_id_or_address>"
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


def _render_agent_workspace_guide(project: ProjectConfig, arguments: dict[str, str]) -> str:
    binary_id = arguments.get("binary_id", "").strip() or "bin-main"
    focus_entity = arguments.get("focus_entity", "").strip() or "fn_main"
    return f"""{_prompt_context(project, arguments)}

Use this server as a local offline-first reverse engineering memory.

Recommended workflow:
1. Call get_project_config first and check write_mode.
2. Search before writing: use search_records with q, tag, address, binary_id, and entity_types.
3. Read exact records with get_record before updating them.
4. Expand local context with get_related for 1-2 hops.
5. Keep facts, hypotheses, evidence, and relations separate.
6. In confirm mode, create/update tools return pending changes. Confirm with confirm_change only after reviewing list_pending_changes.
7. In auto mode, create/update tools commit immediately.

Safe search example:
{_json_example({"q": "loader", "entity_types": ["function"], "binary_id": binary_id, "limit": 20})}

Focused read example:
{_json_example({"entity_type": "function", "entity_id": focus_entity, "binary_id": binary_id})}

FTS warning: avoid raw hyphenated query text such as gui-seed. Search individual words like gui seed, or use tag='gui-seed' until FTS escaping is fixed."""


def _render_function_prompt(project: ProjectConfig, arguments: dict[str, str]) -> str:
    binary_id = arguments.get("binary_id", "").strip() or "bin-main"
    focus_entity = arguments.get("focus_entity", "").strip() or "fn_example"
    return f"""{_prompt_context(project, arguments)}

Use create_function to create or replace a function analysis record. Use update_function for the same payload when the intent is explicitly an update.

Required fields: binary_id, function_id, address, raw_name, current_name, summary, behavior_description. Include created_by and updated_by for audit clarity.

Good function payload:
{_json_example({
    "binary_id": binary_id,
    "function_id": focus_entity,
    "address": "0x401000",
    "raw_name": "sub_401000",
    "current_name": "load_project_config",
    "summary": "Loads local project configuration and validates paths.",
    "behavior_description": "Reads project metadata, normalizes paths, and prepares runtime endpoints.",
    "important_variables": ["project_root", "database_path"],
    "used_apis": ["CreateFileW", "ReadFile"],
    "strings": ["project.db", "mcp"],
    "constants": ["0x401000"],
    "confidence": 0.82,
    "tags": ["config", "loader"],
    "observed_facts": [{"fact": "The function reads project configuration paths.", "source_origin": "agent"}],
    "hypotheses": [{"statement": "This function runs before HTTP and MCP startup.", "status": "new", "confidence": 0.66}],
    "source_origin": "agent",
    "created_by": "agent",
    "updated_by": "agent",
    "allow_conflict": True,
})}

If write_mode is confirm, capture pending_change_id and ask for/perform confirm_change only after review."""


def _render_structure_prompt(project: ProjectConfig, arguments: dict[str, str]) -> str:
    binary_id = arguments.get("binary_id", "").strip() or "bin-main"
    focus_entity = arguments.get("focus_entity", "").strip() or "PROJECT_CONTEXT"
    return f"""{_prompt_context(project, arguments)}

Use create_structure or update_structure for recovered data layouts. Keep field offsets stable and include comments when field purpose is inferred.

Required fields: binary_id, structure_id, raw_name, current_name, summary. Fields are optional but should include name, offset, data_type, optional size, and comment.

Good structure payload:
{_json_example({
    "binary_id": binary_id,
    "structure_id": focus_entity,
    "raw_name": "_PROJECT_CONTEXT_raw",
    "current_name": "PROJECT_CONTEXT",
    "summary": "Holds local project paths and runtime endpoint configuration.",
    "fields": [
        {"name": "flags", "offset": "0x0", "data_type": "uint32_t", "size": 4, "comment": "Runtime flags."},
        {"name": "database_path", "offset": "0x8", "data_type": "wchar_t *", "size": 8, "comment": "Path to project.db."},
    ],
    "tags": ["config", "structure"],
    "observed_facts": [{"fact": "The structure stores a database path pointer.", "source_origin": "agent"}],
    "hypotheses": [{"statement": "This structure is shared by HTTP and MCP startup paths.", "status": "new", "confidence": 0.7}],
    "source_origin": "agent",
    "created_by": "agent",
    "updated_by": "agent",
})}

Link structures to functions with create_relation relation_type='uses_structure' when a function reads or writes the layout."""


def _render_hypothesis_evidence_prompt(project: ProjectConfig, arguments: dict[str, str]) -> str:
    binary_id = arguments.get("binary_id", "").strip() or "bin-main"
    focus_entity = arguments.get("focus_entity", "").strip() or "fn_example"
    return f"""{_prompt_context(project, arguments)}

Use observed_facts for directly observed statements. Use hypotheses for interpretations that may change. Use add_evidence for concrete support such as blocks, excerpts, xrefs, or attachments. Use create_relation for graph edges between entities.

Global hypothesis example:
{_json_example({
    "hypothesis_id": "hyp_runtime_startup_order",
    "title": "Runtime starts HTTP before MCP",
    "statement": "The local launcher appears to validate HTTP health before exposing the MCP endpoint.",
    "status": "new",
    "confidence": 0.64,
    "binary_id": binary_id,
    "tags": ["runtime", "startup"],
    "observed_facts": [{"fact": "HTTP health is checked during startup logs.", "source_origin": "agent"}],
    "source_origin": "agent",
    "created_by": "agent",
    "updated_by": "agent",
})}

Evidence example:
{_json_example({
    "evidence_id": "ev_startup_log_001",
    "entity_type": "function",
    "entity_id": focus_entity,
    "evidence_type": "log",
    "description": "Startup log shows HTTP health before MCP tool calls.",
    "excerpt": "GET /health ... POST /mcp",
    "created_by": "agent",
})}

Relation example:
{_json_example({
    "from_entity_type": "function",
    "from_entity_id": focus_entity,
    "to_entity_type": "global_hypothesis",
    "to_entity_id": "hyp_runtime_startup_order",
    "relation_type": "supports",
    "created_by": "agent",
})}"""


def _render_search_graph_prompt(project: ProjectConfig, arguments: dict[str, str]) -> str:
    binary_id = arguments.get("binary_id", "").strip() or "bin-main"
    focus_entity = arguments.get("focus_entity", "").strip() or "fn_main"
    return f"""{_prompt_context(project, arguments)}

Use search_records for discovery, get_record for exact reads, and get_related for graph expansion. Prefer a small loop: search -> read -> related -> read linked records -> write only what is supported.

Search examples:
{_json_example({"q": "Synthetic", "limit": 50})}
{_json_example({"tag": "gui-seed", "limit": 50})}
{_json_example({"address": "0x401000", "binary_id": binary_id, "entity_types": ["function"], "limit": 10})}

Graph context examples:
{_json_example({"entity_type": "function", "entity_id": focus_entity, "hops": 1})}
{_json_example({"entity_type": "function", "entity_id": focus_entity, "hops": 2})}

When adding graph edges, use relation types that describe the analysis claim: calls, uses_structure, supports, refutes, aliases, dispatches_to, owns, reads, writes."""


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
