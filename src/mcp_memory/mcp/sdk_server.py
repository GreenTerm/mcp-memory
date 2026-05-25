from __future__ import annotations

import contextlib
import json
import logging
import traceback
from collections.abc import AsyncIterator
from http import HTTPStatus
from typing import Any

import uvicorn
from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.shared.exceptions import McpError
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from mcp_memory import __version__
from mcp_memory.config import ProjectConfig, ProjectRegistry
from mcp_memory.logging_utils import configure_logging, get_logger, log_event
from mcp_memory.services import (
    EvidenceValidationError,
    FunctionValidationError,
    GenericEvidenceValidationError,
    GenericPendingValidationError,
    GenericRelationValidationError,
    GlobalHypothesisValidationError,
    PendingChangeValidationError,
    RecordValidationError,
    RelationValidationError,
    StructureValidationError,
)

from .server import McpRequestError, _build_prompts, _build_tools, _validate_tool_arguments, serialize


_VALIDATION_EXCEPTIONS = (
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
)


class _StreamableHTTPASGIApp:
    def __init__(self, session_manager: StreamableHTTPSessionManager) -> None:
        self._session_manager = session_manager

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        await self._session_manager.handle_request(scope, receive, send)


def build_sdk_app(
    project: ProjectConfig,
    registry: ProjectRegistry,
    logger: logging.Logger | None = None,
    log_level: str = "INFO",
) -> Starlette:
    request_logger = logger or get_logger("mcp")
    tools = _build_tools()
    prompts = _build_prompts()
    mcp_server = Server("mcp-memory", version=__version__)

    @mcp_server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name=spec.name,
                description=spec.description,
                inputSchema=spec.input_schema,
            )
            for spec in tools.values()
        ]

    @mcp_server.list_resources()
    async def list_resources() -> list[types.Resource]:
        return []

    @mcp_server.list_resource_templates()
    async def list_resource_templates() -> list[types.ResourceTemplate]:
        return []

    @mcp_server.list_prompts()
    async def list_prompts() -> list[types.Prompt]:
        return [
            types.Prompt(
                name=spec.name,
                description=spec.description,
                arguments=[
                    types.PromptArgument(
                        name=str(argument["name"]),
                        description=None if argument.get("description") is None else str(argument["description"]),
                        required=bool(argument.get("required", False)),
                    )
                    for argument in spec.arguments
                ],
            )
            for spec in prompts.values()
        ]

    @mcp_server.get_prompt()
    async def get_prompt(name: str, arguments: dict[str, str] | None) -> types.GetPromptResult:
        spec = prompts.get(name)
        if spec is None:
            raise McpError(types.ErrorData(code=types.INVALID_PARAMS, message=f"Unknown prompt: {name}"))
        if arguments is not None and not isinstance(arguments, dict):
            raise McpError(types.ErrorData(code=types.INVALID_PARAMS, message="prompt arguments must be an object"))
        rendered_arguments = {str(key): str(value) for key, value in (arguments or {}).items()}
        return types.GetPromptResult(
            description=spec.description,
            messages=[
                types.PromptMessage(
                    role="user",
                    content=types.TextContent(type="text", text=spec.renderer(project, rendered_arguments)),
                )
            ],
        )

    async def call_tool(req: types.CallToolRequest) -> types.ServerResult:
        tool_name = str(req.params.name)
        arguments = req.params.arguments or {}
        if not isinstance(arguments, dict):
            raise McpError(types.ErrorData(code=types.INVALID_PARAMS, message="tool arguments must be an object"))
        spec = tools.get(tool_name)
        if spec is None:
            raise McpError(types.ErrorData(code=types.INVALID_PARAMS, message=f"Unknown tool: {tool_name}"))
        try:
            _validate_tool_arguments(tool_name, spec, arguments)
            log_event(request_logger, logging.INFO, "tool_call", project_id=project.project_id, tool_name=tool_name)
            result = serialize(spec.handler(project, registry, arguments))
        except _VALIDATION_EXCEPTIONS as exc:
            log_event(
                request_logger,
                logging.WARNING,
                "request_validation_error",
                project_id=project.project_id,
                method="POST",
                path="/mcp",
                error=str(exc),
            )
            raise McpError(types.ErrorData(code=types.INVALID_PARAMS, message=str(exc))) from exc
        except Exception as exc:
            log_event(
                request_logger,
                logging.ERROR,
                "request_exception",
                project_id=project.project_id,
                method="POST",
                path="/mcp",
                error=traceback.format_exc(),
            )
            raise McpError(types.ErrorData(code=types.INTERNAL_ERROR, message="Internal server error")) from exc
        return types.ServerResult(
            types.CallToolResult(
                content=[types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))],
                structuredContent=result if isinstance(result, dict) else {"value": result},
                isError=False,
            )
        )

    mcp_server.request_handlers[types.CallToolRequest] = call_tool
    session_manager = StreamableHTTPSessionManager(
        mcp_server,
        json_response=True,
        stateless=False,
        session_idle_timeout=3600,
    )

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        _ = app
        async with session_manager.run():
            yield

    async def health(request: Request) -> JSONResponse:
        _ = request
        return JSONResponse({"status": "ok", "project_id": project.project_id}, status_code=HTTPStatus.OK.value)

    return Starlette(
        routes=[
            Route("/health", endpoint=health, methods=["GET"]),
            Route("/mcp", endpoint=_StreamableHTTPASGIApp(session_manager)),
        ],
        lifespan=lifespan,
    )


def serve_project_mcp_sdk_api(
    project: ProjectConfig,
    registry: ProjectRegistry,
    host: str,
    port: int,
    log_level: str = "INFO",
) -> None:
    logger = configure_logging("mcp", log_level, project.logs_dir / "mcp.log")
    configure_logging("services", log_level, project.logs_dir / "mcp.log")
    app = build_sdk_app(project, registry, logger=logger, log_level=log_level)
    log_event(
        logger,
        logging.INFO,
        "server_start",
        project_id=project.project_id,
        host=host,
        port=port,
        transport="sdk_streamable_http",
    )
    uvicorn.run(app, host=host, port=port, log_level=log_level.lower(), access_log=False)
