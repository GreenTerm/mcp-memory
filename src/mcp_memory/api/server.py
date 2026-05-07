from __future__ import annotations

import json
import logging
import traceback
from dataclasses import asdict, is_dataclass
from enum import Enum
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from mcp_memory.config import ProjectConfig, ProjectRegistry
from mcp_memory.gui.workspace import render_workspace_response, workspace_asset_response, workspace_post_action
from mcp_memory.domain import EvidenceWrite, FunctionWrite, GlobalHypothesisWrite, HypothesisItem, ObservedFact, StructureMember, StructureWrite
from mcp_memory.logging_utils import configure_logging, get_logger, log_event, start_request_log
from mcp_memory.protocol import (
    GetRelatedQuery,
    GetRecordQuery,
    GetSchemaQuery,
    ListEntityTypesQuery,
    ListRecordsQuery,
    ProjectDispatcher,
    SearchRecordsQuery,
)
from mcp_memory.schema import SchemaValidationError, load_project_schema
from mcp_memory.services import (
    EvidenceService,
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
    RelationWrite,
    SearchQuery,
    SearchService,
    StructureService,
    StructureValidationError,
    GenericRelationService,
    GenericEvidenceService,
    GenericWorkflowService,
    GenericPendingValidationError,
    GenericRelationValidationError,
    GenericEvidenceValidationError,
    RecordService,
    RecordValidationError,
)
from mcp_memory.storage import open_database


def serve_project_http_api(
    project: ProjectConfig,
    registry: ProjectRegistry,
    host: str,
    port: int,
    log_level: str = "INFO",
) -> None:
    logger = configure_logging("api", log_level, project.logs_dir / "http-api.log")
    configure_logging("ui", log_level, project.logs_dir / "http-api.log")
    configure_logging("services", log_level, project.logs_dir / "http-api.log")
    handler = build_handler(project, registry, logger=logger)
    server = HTTPServer((host, port), handler)
    log_event(logger, logging.INFO, "server_start", project_id=project.project_id, host=host, port=port)
    server.serve_forever()


def build_handler(
    project: ProjectConfig,
    registry: ProjectRegistry,
    logger: logging.Logger | None = None,
) -> type[BaseHTTPRequestHandler]:
    request_logger = logger or get_logger("api")

    class RequestHandler(BaseHTTPRequestHandler):
        server_version = "mcp-memory-http/0.1"

        def do_GET(self) -> None:
            request_log = start_request_log("GET", self.path)
            self._response_status = HTTPStatus.OK
            parsed = urlparse(self.path)
            path = parsed.path
            query = parse_qs(parsed.query)

            try:
                asset = workspace_asset_response(path)
                if asset is not None:
                    content_type, body = asset
                    self._send_bytes(body, content_type)
                    return

                ui_response = render_workspace_response(project, registry, self.path)
                if ui_response is not None:
                    status, ui_html = ui_response
                    self._send_html(ui_html, status=status)
                    return

                if path == "/health":
                    self._send_json({"status": "ok", "project_id": project.project_id})
                    return

                if path == "/schema":
                    self._send_json(load_project_schema(project.schema_path).to_dict())
                    return

                if path == "/entity-types":
                    with open_database(project.database_path) as database:
                        result = ProjectDispatcher(database, project).dispatch(ListEntityTypesQuery())
                    self._send_json({"items": serialize(result.data)})
                    return

                if path == "/records":
                    entity_type = self._optional_query_value(query, "entity_type")
                    include_archived = self._optional_query_value(query, "include_archived") == "true"
                    limit = int(self._optional_query_value(query, "limit") or "100")
                    with open_database(project.database_path) as database:
                        result = ProjectDispatcher(database, project).dispatch(
                            ListRecordsQuery(entity_type=entity_type, include_archived=include_archived, limit=limit)
                        )
                    self._send_json(serialize(result.data))
                    return

                if path.startswith("/records/"):
                    parts = [segment for segment in path.split("/") if segment]
                    if len(parts) != 3:
                        self._send_error_json(HTTPStatus.NOT_FOUND, "not_found", "Unknown record route")
                        return
                    _, entity_type, record_id_or_slug = parts
                    include_archived = self._optional_query_value(query, "include_archived") == "true"
                    with open_database(project.database_path) as database:
                        result = ProjectDispatcher(database, project).dispatch(
                            GetRecordQuery(entity_type, record_id_or_slug, include_archived=include_archived)
                        )
                    if result.data is None:
                        self._send_error_json(HTTPStatus.NOT_FOUND, "not_found", "Record not found")
                        return
                    self._send_json(serialize(result.data))
                    return

                if path == "/relations":
                    entity_type = self._optional_query_value(query, "entity_type")
                    record_id = self._optional_query_value(query, "record_id")
                    direction = self._optional_query_value(query, "direction") or "both"
                    with open_database(project.database_path) as database:
                        items = GenericRelationService(database, project).list_relations(entity_type, record_id, direction)
                    self._send_json({"items": serialize(items)})
                    return

                if path == "/related":
                    entity_type = self._required_query_value(query, "entity_type")
                    record_id = self._optional_query_value(query, "record_id")
                    if record_id is None and self._optional_query_value(query, "entity_id") is not None:
                        entity_id = self._required_query_value(query, "entity_id")
                        hops = int(self._optional_query_value(query, "hops") or "1")
                        with open_database(project.database_path) as database:
                            data = RelationService(database).traverse_related(project.project_id, entity_type, entity_id, hops)
                        self._send_json({"items": data})
                        return
                    if record_id is None:
                        raise ValueError("Missing required query parameter: record_id")
                    hops = int(self._optional_query_value(query, "hops") or "1")
                    with open_database(project.database_path) as database:
                        result = ProjectDispatcher(database, project).dispatch(GetRelatedQuery(entity_type, record_id, hops))
                    self._send_json(serialize(result.data))
                    return

                if path == "/evidence":
                    entity_type = self._required_query_value(query, "entity_type")
                    record_id = self._optional_query_value(query, "record_id")
                    if record_id is None and self._optional_query_value(query, "entity_id") is not None:
                        entity_id = self._required_query_value(query, "entity_id")
                        with open_database(project.database_path) as database:
                            data = EvidenceService(database).list_evidence(project.project_id, entity_type, entity_id)
                        self._send_json({"items": serialize(data)})
                        return
                    if record_id is None:
                        raise ValueError("Missing required query parameter: record_id")
                    with open_database(project.database_path) as database:
                        items = GenericEvidenceService(database, project).list_evidence(entity_type, record_id)
                    self._send_json({"items": serialize(items)})
                    return

                if path == "/project/config":
                    self._send_json(
                        {
                            "project": serialize(project),
                            "registry_path": str(registry.config_path),
                        }
                    )
                    return

                if path == "/functions":
                    binary_id = self._required_query_value(query, "binary_id")
                    with open_database(project.database_path) as database:
                        data = FunctionService(database).list_functions(project.project_id, binary_id)
                    self._send_json({"items": serialize(data)})
                    return

                if path.startswith("/functions/"):
                    parts = [segment for segment in path.split("/") if segment]
                    if len(parts) != 3:
                        self._send_error_json(HTTPStatus.NOT_FOUND, "not_found", "Unknown function route")
                        return
                    _, binary_id, function_id = parts
                    with open_database(project.database_path) as database:
                        record = FunctionService(database).get_function(project.project_id, binary_id, function_id)
                    if record is None:
                        self._send_error_json(HTTPStatus.NOT_FOUND, "not_found", "Function not found")
                        return
                    self._send_json(serialize(record))
                    return

                if path == "/structures":
                    binary_id = self._optional_query_value(query, "binary_id")
                    with open_database(project.database_path) as database:
                        data = StructureService(database).list_structures(project.project_id, binary_id)
                    self._send_json({"items": serialize(data)})
                    return

                if path.startswith("/structures/"):
                    structure_id = path.rsplit("/", 1)[-1]
                    with open_database(project.database_path) as database:
                        record = StructureService(database).get_structure(project.project_id, structure_id)
                    if record is None:
                        self._send_error_json(HTTPStatus.NOT_FOUND, "not_found", "Structure not found")
                        return
                    self._send_json(serialize(record))
                    return

                if path == "/global-hypotheses":
                    with open_database(project.database_path) as database:
                        data = GlobalHypothesisService(database).list_hypotheses(project.project_id)
                    self._send_json({"items": serialize(data)})
                    return

                if path.startswith("/global-hypotheses/"):
                    hypothesis_id = path.rsplit("/", 1)[-1]
                    with open_database(project.database_path) as database:
                        record = GlobalHypothesisService(database).get_hypothesis(project.project_id, hypothesis_id)
                    if record is None:
                        self._send_error_json(HTTPStatus.NOT_FOUND, "not_found", "Global hypothesis not found")
                        return
                    self._send_json(serialize(record))
                    return

                if path == "/evidence":
                    entity_type = self._required_query_value(query, "entity_type")
                    entity_id = self._required_query_value(query, "entity_id")
                    with open_database(project.database_path) as database:
                        data = EvidenceService(database).list_evidence(project.project_id, entity_type, entity_id)
                    self._send_json({"items": serialize(data)})
                    return

                if path == "/relations":
                    entity_type = self._required_query_value(query, "entity_type")
                    entity_id = self._required_query_value(query, "entity_id")
                    direction = self._optional_query_value(query, "direction") or "both"
                    with open_database(project.database_path) as database:
                        data = RelationService(database).list_relations(project.project_id, entity_type, entity_id, direction)
                    self._send_json({"items": serialize(data)})
                    return

                if path == "/pending-changes":
                    status = self._optional_query_value(query, "status") or "pending"
                    if status == "all":
                        status = None
                    with open_database(project.database_path) as database:
                        data = GenericWorkflowService(database, project).list_pending_changes(status=status)
                    self._send_json({"items": serialize(data)})
                    return

                if path == "/related":
                    entity_type = self._required_query_value(query, "entity_type")
                    entity_id = self._required_query_value(query, "entity_id")
                    hops = int(self._optional_query_value(query, "hops") or "1")
                    with open_database(project.database_path) as database:
                        data = RelationService(database).traverse_related(project.project_id, entity_type, entity_id, hops)
                    self._send_json({"items": data})
                    return

                self._send_error_json(HTTPStatus.NOT_FOUND, "not_found", "Unknown route")
            except (
                RelationValidationError,
                GenericRelationValidationError,
                GenericEvidenceValidationError,
                RecordValidationError,
                SchemaValidationError,
                ValueError,
            ) as exc:
                log_event(
                    request_logger,
                    logging.WARNING,
                    "request_validation_error",
                    project_id=project.project_id,
                    method="GET",
                    path=path,
                    error=str(exc),
                )
                self._send_error_json(HTTPStatus.BAD_REQUEST, "validation_error", str(exc))
            except Exception:
                log_event(
                    request_logger,
                    logging.ERROR,
                    "request_exception",
                    project_id=project.project_id,
                    method="GET",
                    path=path,
                    error=traceback.format_exc(),
                )
                self._send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, "internal_error", "Internal server error")
            finally:
                request_log.finish(request_logger, "request_complete", int(self._response_status), project_id=project.project_id)

        def do_POST(self) -> None:
            request_log = start_request_log("POST", self.path)
            self._response_status = HTTPStatus.OK
            parsed = urlparse(self.path)
            path = parsed.path

            try:
                form_data = self._read_form_body()
                ui_action = workspace_post_action(project, registry, self.path, form_data)
                if ui_action is not None:
                    if "location" in ui_action:
                        self._redirect(str(ui_action["location"]))
                    else:
                        self._send_html(str(ui_action["html"]), status=ui_action.get("status", HTTPStatus.OK))
                    return

                payload = self._read_json_body()
                if payload is None:
                    return

                if path == "/search":
                    with open_database(project.database_path) as database:
                        result = ProjectDispatcher(database, project).dispatch(
                            SearchRecordsQuery(
                                q=str(payload.get("q", "")).strip(),
                                entity_types=[str(item) for item in payload.get("entity_types", [])] or None,
                                tag=None if payload.get("tag") is None else str(payload["tag"]),
                                limit=int(payload.get("limit", 10)),
                            )
                        )
                    self._send_json(serialize(result.data))
                    return

                if path.startswith("/records/") and path.endswith("/archive"):
                    parts = [segment for segment in path.split("/") if segment]
                    if len(parts) != 4:
                        self._send_error_json(HTTPStatus.NOT_FOUND, "not_found", "Unknown record archive route")
                        return
                    _, entity_type, record_id_or_slug, _ = parts
                    result = self._generic_workflow(
                        "archive_record",
                        {
                            "entity_type": entity_type,
                            "record_id_or_slug": record_id_or_slug,
                            "archived_by": str(payload.get("archived_by", "api")),
                        },
                        created_by=str(payload.get("archived_by", "api")),
                    )
                    self._send_json(serialize(result), status=HTTPStatus.ACCEPTED if project.write_mode == "confirm" else HTTPStatus.OK)
                    return

                if path.startswith("/records/"):
                    parts = [segment for segment in path.split("/") if segment]
                    if len(parts) != 2:
                        self._send_error_json(HTTPStatus.NOT_FOUND, "not_found", "Unknown record route")
                        return
                    _, entity_type = parts
                    record_payload = payload.get("payload", payload)
                    if not isinstance(record_payload, dict):
                        raise ValueError("payload must be an object")
                    result = self._generic_workflow(
                        "upsert_record",
                        {
                            "entity_type": entity_type,
                            "record_id": payload.get("record_id"),
                            "payload": record_payload,
                            "source_origin": str(payload.get("source_origin", "api")),
                            "created_by": str(payload.get("created_by", "api")),
                            "updated_by": str(payload.get("updated_by", payload.get("created_by", "api"))),
                        },
                        created_by=str(payload.get("created_by", "api")),
                    )
                    self._send_json(serialize(result), status=HTTPStatus.ACCEPTED if project.write_mode == "confirm" else HTTPStatus.CREATED)
                    return

                if path == "/relations":
                    if "from_record_id" not in payload and "from_entity_id" in payload:
                        with open_database(project.database_path) as database:
                            result = _apply_or_queue_relation(project, database, payload)
                        self._send_json(serialize(result["body"]), status=result["status"])
                        return
                    result = self._generic_workflow("create_relation", payload, created_by=str(payload.get("created_by", "api")))
                    self._send_json(serialize(result), status=HTTPStatus.ACCEPTED if project.write_mode == "confirm" else HTTPStatus.CREATED)
                    return

                if path == "/evidence":
                    if "record_id" not in payload and "entity_id" in payload:
                        with open_database(project.database_path) as database:
                            result = _apply_or_queue_evidence(project, database, payload)
                        self._send_json(serialize(result["body"]), status=result["status"])
                        return
                    result = self._generic_workflow("add_evidence", payload, created_by=str(payload.get("created_by", "api")))
                    self._send_json(serialize(result), status=HTTPStatus.ACCEPTED if project.write_mode == "confirm" else HTTPStatus.CREATED)
                    return

                if path == "/functions":
                    with open_database(project.database_path) as database:
                        result = _apply_or_queue_function(project, database, payload)
                    self._send_json(serialize(result["body"]), status=result["status"])
                    return

                if path == "/structures":
                    with open_database(project.database_path) as database:
                        result = _apply_or_queue_structure(project, database, payload)
                    self._send_json(serialize(result["body"]), status=result["status"])
                    return

                if path == "/global-hypotheses":
                    with open_database(project.database_path) as database:
                        result = _apply_or_queue_global_hypothesis(project, database, payload)
                    self._send_json(serialize(result["body"]), status=result["status"])
                    return

                if path == "/evidence":
                    with open_database(project.database_path) as database:
                        result = _apply_or_queue_evidence(project, database, payload)
                    self._send_json(serialize(result["body"]), status=result["status"])
                    return

                if path == "/relations":
                    with open_database(project.database_path) as database:
                        result = _apply_or_queue_relation(project, database, payload)
                    self._send_json(serialize(result["body"]), status=result["status"])
                    return

                if path.startswith("/pending-changes/") and path.endswith("/confirm"):
                    pending_change_id = _pending_change_id_from_path(path, "confirm")
                    with open_database(project.database_path) as database:
                        result = _confirm_pending_change(project, database, pending_change_id, str(payload.get("confirmed_by", "api")))
                    self._send_json(serialize(result), status=HTTPStatus.CREATED)
                    return

                if path.startswith("/pending-changes/") and path.endswith("/reject"):
                    pending_change_id = _pending_change_id_from_path(path, "reject")
                    with open_database(project.database_path) as database:
                        result = _reject_pending_change(project, database, pending_change_id, str(payload.get("rejected_by", "api")))
                    self._send_json(serialize(result), status=HTTPStatus.CREATED)
                    return

                if path == "/export/json":
                    result = ProjectTransferService().export_project(
                        project,
                        None if payload.get("output_path") is None else Path(str(payload["output_path"])).expanduser().resolve(),
                    )
                    self._send_json(result, status=HTTPStatus.CREATED)
                    return

                if path == "/import/json":
                    result = ProjectTransferService().import_project(
                        project,
                        Path(str(payload["input_path"])).expanduser().resolve(),
                        replace_existing=bool(payload.get("replace_existing", False)),
                    )
                    self._send_json(result, status=HTTPStatus.CREATED)
                    return

                if path == "/backup":
                    result = ProjectArchiveService(registry).create_backup(
                        project,
                        None if payload.get("output_path") is None else Path(str(payload["output_path"])).expanduser().resolve(),
                    )
                    self._send_json(result, status=HTTPStatus.CREATED)
                    return

                if path == "/restore":
                    config = ProjectArchiveService(registry).restore_backup(
                        input_path=Path(str(payload["input_path"])).expanduser().resolve(),
                        project_root=Path(str(payload["project_root"])).expanduser().resolve(),
                        project_id=None if payload.get("project_id") is None else str(payload["project_id"]),
                        display_name=None if payload.get("display_name") is None else str(payload["display_name"]),
                        http_port=None if payload.get("http_port") is None else int(payload["http_port"]),
                        mcp_port=None if payload.get("mcp_port") is None else int(payload["mcp_port"]),
                        write_mode=None if payload.get("write_mode") is None else str(payload["write_mode"]),
                    )
                    self._send_json(serialize(config), status=HTTPStatus.CREATED)
                    return

                self._send_error_json(HTTPStatus.NOT_FOUND, "not_found", "Unknown route")
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
                SchemaValidationError,
                KeyError,
                ValueError,
            ) as exc:
                log_event(
                    request_logger,
                    logging.WARNING,
                    "request_validation_error",
                    project_id=project.project_id,
                    method="POST",
                    path=path,
                    error=str(exc),
                )
                self._send_error_json(HTTPStatus.BAD_REQUEST, "validation_error", str(exc))
                return
            except Exception:
                log_event(
                    request_logger,
                    logging.ERROR,
                    "request_exception",
                    project_id=project.project_id,
                    method="POST",
                    path=path,
                    error=traceback.format_exc(),
                )
                self._send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, "internal_error", "Internal server error")
                return
            finally:
                request_log.finish(request_logger, "request_complete", int(self._response_status), project_id=project.project_id)

        def log_message(self, format: str, *args: object) -> None:
            log_event(request_logger, logging.INFO, "server_message", project_id=project.project_id, message=format % args if args else format)

        def do_PUT(self) -> None:
            request_log = start_request_log("PUT", self.path)
            self._response_status = HTTPStatus.OK
            parsed = urlparse(self.path)
            path = parsed.path
            try:
                payload = self._read_json_body()
                if payload is None:
                    return
                if path == "/schema":
                    from mcp_memory.schema import ProjectSchema, copy_schema_payload

                    ProjectSchema.from_dict(payload)
                    copy_schema_payload(project.schema_path, payload)
                    self._send_json({"status": "updated", "schema_path": str(project.schema_path)})
                    return
                if path.startswith("/records/"):
                    parts = [segment for segment in path.split("/") if segment]
                    if len(parts) != 3:
                        self._send_error_json(HTTPStatus.NOT_FOUND, "not_found", "Unknown record route")
                        return
                    _, entity_type, record_id_or_slug = parts
                    record_payload = payload.get("payload", payload)
                    if not isinstance(record_payload, dict):
                        raise ValueError("payload must be an object")
                    with open_database(project.database_path) as database:
                        existing = RecordService(database, project).get_record(entity_type, record_id_or_slug, include_archived=True)
                    record_id = record_id_or_slug if existing is None else existing.record_id
                    result = self._generic_workflow(
                        "upsert_record",
                        {
                            "entity_type": entity_type,
                            "record_id": record_id,
                            "payload": record_payload,
                            "source_origin": str(payload.get("source_origin", "api")),
                            "created_by": str(payload.get("created_by", "api")),
                            "updated_by": str(payload.get("updated_by", payload.get("created_by", "api"))),
                        },
                        created_by=str(payload.get("updated_by", payload.get("created_by", "api"))),
                    )
                    self._send_json(serialize(result), status=HTTPStatus.ACCEPTED if project.write_mode == "confirm" else HTTPStatus.OK)
                    return
                self._send_error_json(HTTPStatus.NOT_FOUND, "not_found", "Unknown route")
            except (GenericPendingValidationError, RecordValidationError, SchemaValidationError, KeyError, ValueError) as exc:
                self._send_error_json(HTTPStatus.BAD_REQUEST, "validation_error", str(exc))
            except Exception:
                log_event(
                    request_logger,
                    logging.ERROR,
                    "request_exception",
                    project_id=project.project_id,
                    method="PUT",
                    path=path,
                    error=traceback.format_exc(),
                )
                self._send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, "internal_error", "Internal server error")
            finally:
                request_log.finish(request_logger, "request_complete", int(self._response_status), project_id=project.project_id)

        def _generic_workflow(self, operation: str, payload: dict[str, Any], created_by: str) -> Any:
            with open_database(project.database_path) as database:
                result = GenericWorkflowService(database, project).apply_or_queue(operation, payload, created_by=created_by)
                return result.data if hasattr(result, "data") else result

        def _read_json_body(self) -> dict[str, Any] | None:
            content_length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(content_length)
            try:
                return json.loads(raw_body.decode("utf-8")) if raw_body else {}
            except json.JSONDecodeError:
                self._send_error_json(HTTPStatus.BAD_REQUEST, "invalid_json", "Request body must be valid JSON")
                return None

        def _required_query_value(self, query: dict[str, list[str]], name: str) -> str:
            values = query.get(name)
            if not values or not values[0].strip():
                raise ValueError(f"Missing required query parameter: {name}")
            return values[0]

        def _optional_query_value(self, query: dict[str, list[str]], name: str) -> str | None:
            values = query.get(name)
            if not values:
                return None
            value = values[0].strip()
            return value or None

        def _send_json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
            body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
            self._send_bytes(body, "application/json; charset=utf-8", status=status)

        def _send_html(self, html: str, status: HTTPStatus = HTTPStatus.OK) -> None:
            self._send_bytes(html.encode("utf-8"), "text/html; charset=utf-8", status=status)

        def _send_bytes(self, body: bytes, content_type: str, status: HTTPStatus = HTTPStatus.OK) -> None:
            self._response_status = status
            self.send_response(status.value)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_error_json(self, status: HTTPStatus, code: str, message: str) -> None:
            self._send_json({"error": code, "message": message}, status=status)

        def _redirect(self, location: str) -> None:
            self._response_status = HTTPStatus.SEE_OTHER
            self.send_response(HTTPStatus.SEE_OTHER.value)
            self.send_header("Location", location)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _read_form_body(self) -> dict[str, str]:
            if self.command != "POST":
                return {}
            content_type = self.headers.get("Content-Type", "")
            if "application/x-www-form-urlencoded" not in content_type:
                return {}
            content_length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(content_length)
            parsed = parse_qs(raw_body.decode("utf-8"))
            return {key: values[0] for key, values in parsed.items() if values}

    return RequestHandler


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


def _pending_change_id_from_path(path: str, action: str) -> str:
    suffix = f"/{action}"
    pending_change_id = path[: -len(suffix)].rsplit("/", 1)[-1].strip()
    if not pending_change_id:
        raise ValueError("Missing pending change id")
    return pending_change_id


def _confirm_pending_change(project: ProjectConfig, database: Any, pending_change_id: str, confirmed_by: str) -> Any:
    generic_workflow = GenericWorkflowService(database, project)
    pending = generic_workflow.get_pending_change(pending_change_id)
    if pending is not None and pending.operation in {"upsert_record", "archive_record", "create_relation", "add_evidence"}:
        return generic_workflow.confirm_change(pending_change_id, confirmed_by=confirmed_by, actor_type="user")
    return PendingChangeService(database).confirm_change(
        project.project_id,
        pending_change_id,
        confirmed_by=confirmed_by,
        actor_type="user",
    )


def _reject_pending_change(project: ProjectConfig, database: Any, pending_change_id: str, rejected_by: str) -> Any:
    generic_workflow = GenericWorkflowService(database, project)
    pending = generic_workflow.get_pending_change(pending_change_id)
    if pending is not None and pending.operation in {"upsert_record", "archive_record", "create_relation", "add_evidence"}:
        return generic_workflow.reject_change(pending_change_id, rejected_by=rejected_by)
    return PendingChangeService(database).reject_change(project.project_id, pending_change_id, rejected_by=rejected_by)


def _queue_pending_change(
    project: ProjectConfig,
    database: Any,
    entity_type: str,
    entity_id: str,
    operation: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    record = PendingChangeService(database).create_pending_change(
        project.project_id,
        entity_type,
        entity_id,
        operation,
        payload,
        created_by=str(payload.get("created_by", "api")),
    )
    return {"status": HTTPStatus.ACCEPTED, "body": record}


def _apply_or_queue_function(project: ProjectConfig, database: Any, payload: dict[str, Any]) -> dict[str, Any]:
    if project.write_mode == "confirm":
        return _queue_pending_change(
            project,
            database,
            "function",
            str(payload["function_id"]),
            "upsert_function",
            payload,
        )
    record = FunctionService(database).upsert_function(function_write_from_payload(project.project_id, payload))
    return {"status": HTTPStatus.CREATED, "body": record}


def _apply_or_queue_structure(project: ProjectConfig, database: Any, payload: dict[str, Any]) -> dict[str, Any]:
    if project.write_mode == "confirm":
        return _queue_pending_change(
            project,
            database,
            "structure",
            str(payload["structure_id"]),
            "upsert_structure",
            payload,
        )
    record = StructureService(database).upsert_structure(structure_write_from_payload(project.project_id, payload))
    return {"status": HTTPStatus.CREATED, "body": record}


def _apply_or_queue_global_hypothesis(project: ProjectConfig, database: Any, payload: dict[str, Any]) -> dict[str, Any]:
    if project.write_mode == "confirm":
        return _queue_pending_change(
            project,
            database,
            "global_hypothesis",
            str(payload["hypothesis_id"]),
            "upsert_global_hypothesis",
            payload,
        )
    record = GlobalHypothesisService(database).upsert_hypothesis(global_hypothesis_write_from_payload(project.project_id, payload))
    return {"status": HTTPStatus.CREATED, "body": record}


def _apply_or_queue_evidence(project: ProjectConfig, database: Any, payload: dict[str, Any]) -> dict[str, Any]:
    if project.write_mode == "confirm":
        return _queue_pending_change(
            project,
            database,
            "evidence",
            str(payload["evidence_id"]),
            "create_evidence",
            payload,
        )
    record = EvidenceService(database).create_evidence(evidence_write_from_payload(project.project_id, payload))
    return {"status": HTTPStatus.CREATED, "body": record}


def _apply_or_queue_relation(project: ProjectConfig, database: Any, payload: dict[str, Any]) -> dict[str, Any]:
    if project.write_mode == "confirm":
        entity_id = f"{payload['from_entity_type']}:{payload['from_entity_id']}->{payload['to_entity_type']}:{payload['to_entity_id']}"
        return _queue_pending_change(
            project,
            database,
            "relation",
            entity_id,
            "create_relation",
            payload,
        )
    relation = RelationWrite(
        project_id=project.project_id,
        from_entity_type=str(payload["from_entity_type"]),
        from_entity_id=str(payload["from_entity_id"]),
        to_entity_type=str(payload["to_entity_type"]),
        to_entity_id=str(payload["to_entity_id"]),
        relation_type=str(payload["relation_type"]),
        created_by=str(payload.get("created_by", "api")),
    )
    record = RelationService(database).create_relation(relation)
    return {"status": HTTPStatus.CREATED, "body": record}


def function_write_from_payload(project_id: str, payload: dict[str, Any]) -> FunctionWrite:
    return FunctionWrite(
        project_id=project_id,
        binary_id=str(payload["binary_id"]),
        function_id=str(payload["function_id"]),
        address=str(payload["address"]),
        raw_name=str(payload["raw_name"]),
        current_name=str(payload["current_name"]),
        summary=str(payload["summary"]),
        behavior_description=str(payload["behavior_description"]),
        important_variables=[str(item) for item in payload.get("important_variables", [])],
        used_apis=[str(item) for item in payload.get("used_apis", [])],
        strings=[str(item) for item in payload.get("strings", [])],
        constants=[str(item) for item in payload.get("constants", [])],
        confidence=float(payload["confidence"]) if payload.get("confidence") is not None else None,
        tags=[str(item) for item in payload.get("tags", [])],
        observed_facts=[
            ObservedFact(fact=str(item["fact"]), source_origin=str(item.get("source_origin", "api")))
            for item in payload.get("observed_facts", [])
        ],
        hypotheses=_build_hypotheses(payload.get("hypotheses", [])),
        source_origin=str(payload.get("source_origin", "api")),
        created_by=str(payload.get("created_by", "api")),
        updated_by=str(payload.get("updated_by", payload.get("created_by", "api"))),
        allow_conflict=bool(payload.get("allow_conflict", False)),
    )


def _build_hypotheses(items: list[dict[str, Any]]) -> list[HypothesisItem]:
    from mcp_memory.domain import HypothesisStatus

    return [
        HypothesisItem(
            statement=str(item["statement"]),
            status=HypothesisStatus(str(item.get("status", "new"))),
            confidence=float(item["confidence"]) if item.get("confidence") is not None else None,
            source_origin=str(item.get("source_origin", "api")),
        )
        for item in items
    ]


def structure_write_from_payload(project_id: str, payload: dict[str, Any]) -> StructureWrite:
    return StructureWrite(
        project_id=project_id,
        binary_id=str(payload["binary_id"]),
        structure_id=str(payload["structure_id"]),
        raw_name=str(payload["raw_name"]),
        current_name=str(payload["current_name"]),
        summary=str(payload["summary"]),
        fields=[
            StructureMember(
                name=str(item["name"]),
                offset=str(item["offset"]),
                data_type=str(item["data_type"]),
                size=int(item["size"]) if item.get("size") is not None else None,
                comment=str(item.get("comment", "")),
            )
            for item in payload.get("fields", [])
        ],
        tags=[str(item) for item in payload.get("tags", [])],
        observed_facts=[
            ObservedFact(fact=str(item["fact"]), source_origin=str(item.get("source_origin", "api")))
            for item in payload.get("observed_facts", [])
        ],
        hypotheses=_build_hypotheses(payload.get("hypotheses", [])),
        source_origin=str(payload.get("source_origin", "api")),
        created_by=str(payload.get("created_by", "api")),
        updated_by=str(payload.get("updated_by", payload.get("created_by", "api"))),
    )


def global_hypothesis_write_from_payload(project_id: str, payload: dict[str, Any]) -> GlobalHypothesisWrite:
    from mcp_memory.domain import HypothesisStatus

    return GlobalHypothesisWrite(
        project_id=project_id,
        hypothesis_id=str(payload["hypothesis_id"]),
        title=str(payload["title"]),
        statement=str(payload["statement"]),
        status=HypothesisStatus(str(payload.get("status", "new"))),
        confidence=float(payload["confidence"]) if payload.get("confidence") is not None else None,
        binary_id=None if payload.get("binary_id") is None else str(payload["binary_id"]),
        tags=[str(item) for item in payload.get("tags", [])],
        observed_facts=[
            ObservedFact(fact=str(item["fact"]), source_origin=str(item.get("source_origin", "api")))
            for item in payload.get("observed_facts", [])
        ],
        source_origin=str(payload.get("source_origin", "api")),
        created_by=str(payload.get("created_by", "api")),
        updated_by=str(payload.get("updated_by", payload.get("created_by", "api"))),
    )


def evidence_write_from_payload(project_id: str, payload: dict[str, Any]) -> EvidenceWrite:
    return EvidenceWrite(
        project_id=project_id,
        evidence_id=str(payload["evidence_id"]),
        entity_type=str(payload["entity_type"]),
        entity_id=str(payload["entity_id"]),
        evidence_type=str(payload["evidence_type"]),
        description=str(payload["description"]),
        address_start=None if payload.get("address_start") is None else str(payload["address_start"]),
        address_end=None if payload.get("address_end") is None else str(payload["address_end"]),
        xref=None if payload.get("xref") is None else str(payload["xref"]),
        block_ref=None if payload.get("block_ref") is None else str(payload["block_ref"]),
        excerpt=None if payload.get("excerpt") is None else str(payload["excerpt"]),
        attachment_path=None if payload.get("attachment_path") is None else str(payload["attachment_path"]),
        media_type=None if payload.get("media_type") is None else str(payload["media_type"]),
        size_bytes=int(payload["size_bytes"]) if payload.get("size_bytes") is not None else None,
        source_origin=str(payload.get("source_origin", "api")),
        created_by=str(payload.get("created_by", "api")),
    )
