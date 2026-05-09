from __future__ import annotations

from dataclasses import dataclass, field
from html import escape
import http.client
import json
import logging
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib import error, request
from urllib.parse import parse_qs, urlparse, urlsplit, urlunsplit

from mcp_memory.config import ProjectConfig, ProjectRegistry
from mcp_memory.logging_utils import configure_logging, get_logger, log_event, start_request_log
from mcp_memory.runtime import ProjectRuntimeInfo, ProjectRuntimeManager
from mcp_memory.schema import list_bundled_schema_templates
from mcp_memory.services import ProjectService
from mcp_memory.services.projects import validate_project_id

from .i18n import language_switcher, localize_markup, resolve_language, translate_text
from .render import badge, empty_state, html_page, key_value_grid, load_asset_text, mcp_config_block, shell_command


DEFAULT_HTTP_PORT = "8765"
DEFAULT_MCP_PORT = "9876"
DEFAULT_WRITE_MODE = "confirm"
ROOT_PATHS = {"", "assets", "projects", "setup", "settings", "health", "mcp", "ui"}


def _next_available_ports(registry: ProjectRegistry | None = None) -> tuple[str, str]:
    """Return the first HTTP and MCP port pair not used by existing projects."""
    base_http = int(DEFAULT_HTTP_PORT)
    base_mcp = int(DEFAULT_MCP_PORT)
    if registry is None:
        return DEFAULT_HTTP_PORT, DEFAULT_MCP_PORT
    used: set[int] = set()
    for project in registry.list_projects():
        used.add(project.http_port)
        used.add(project.mcp_port)
    http_port = base_http
    while http_port in used:
        http_port += 1
    mcp_port = base_mcp
    while mcp_port in used or mcp_port == http_port:
        mcp_port += 1
    return str(http_port), str(mcp_port)


@dataclass(slots=True)
class ProjectStatus:
    state: str
    reason: str


@dataclass(slots=True)
class ProjectCreateFormState:
    values: dict[str, str]
    errors: dict[str, str] = field(default_factory=dict)
    form_error: str = ""
    open_advanced: bool = False


@dataclass(slots=True)
class ProjectEditFormState:
    project_id: str
    values: dict[str, str]
    errors: dict[str, str] = field(default_factory=dict)
    form_error: str = ""
    open_advanced: bool = True


def probe_project_http_health(project: ProjectConfig, timeout_seconds: float = 0.35) -> ProjectStatus:
    logger = get_logger("ui_home")
    url = f"http://{project.http_host}:{project.http_port}/health"
    try:
        with request.urlopen(url, timeout=timeout_seconds) as response:
            if response.status == 200:
                log_event(logger, logging.INFO, "project_probe", project_id=project.project_id, state="running", url=url)
                return ProjectStatus("running", "Workspace HTTP server is responding.")
    except (error.URLError, TimeoutError, OSError):
        log_event(logger, logging.INFO, "project_probe", project_id=project.project_id, state="offline", url=url)
    return ProjectStatus("offline", "Workspace HTTP server is not running yet.")


def serve_ui_home(
    registry: ProjectRegistry,
    host: str,
    port: int,
    app_home: Path,
    log_level: str = "INFO",
) -> None:
    log_path = app_home / "logs" / "ui-home.log"
    logger = configure_logging("ui_home", log_level, log_path)
    runtime_manager = ProjectRuntimeManager(app_home=app_home, logger=logger)
    handler = build_home_handler(registry, app_home, runtime_manager, logger=logger)
    server = HTTPServer((host, port), handler)
    log_event(logger, logging.INFO, "server_start", host=host, port=port, app_home=app_home)
    try:
        server.serve_forever()
    finally:
        runtime_manager.shutdown_all()
        server.server_close()


def build_home_handler(
    registry: ProjectRegistry,
    app_home: Path,
    runtime_manager: ProjectRuntimeManager,
    logger=None,
) -> type[BaseHTTPRequestHandler]:
    request_logger = logger or get_logger("ui_home")
    project_service = ProjectService(registry)

    class RequestHandler(BaseHTTPRequestHandler):
        server_version = "mcp-memory-ui-home/0.1"

        def do_GET(self) -> None:
            request_log = start_request_log("GET", self.path)
            self._response_status = HTTPStatus.OK
            parsed = urlparse(self.path)
            lang = resolve_language(parse_qs(parsed.query).get("lang", ["en"])[0])

            routed = self._project_gateway_route(parsed)
            if routed is not None:
                request_log.finish(request_logger, "request_complete", int(self._response_status), page=parsed.path)
                return

            if parsed.path == "/":
                self._send_html(render_home_page(registry, app_home, runtime_manager, self.path, lang, public_base_url(registry, self.headers.get("Host", "127.0.0.1:8764"))))
            elif parsed.path == "/setup":
                self._send_html(render_setup_page(registry, app_home, self.path, lang, build_project_form_state(registry=registry), public_base_url(registry, self.headers.get("Host", "127.0.0.1:8764"))))
            elif len([segment for segment in parsed.path.split("/") if segment]) == 3 and parsed.path.endswith("/edit"):
                project_id = [segment for segment in parsed.path.split("/") if segment][1]
                project = registry.get_project(project_id)
                if project is None:
                    self._send_html("Not Found", status=HTTPStatus.NOT_FOUND)
                else:
                    self._send_html(render_project_edit_page(project, self.path, lang, build_project_edit_state(project)))
            elif parsed.path == "/projects/new":
                log_event(request_logger, logging.INFO, "project_create_form_opened")
                self._send_html(render_project_create_page(app_home, self.path, lang, build_project_form_state(registry=registry)))
            elif parsed.path == "/assets/app.css":
                self._send_asset("text/css; charset=utf-8", load_asset_text("app.css").encode("utf-8"))
            elif parsed.path == "/assets/ui.js":
                self._send_asset("text/javascript; charset=utf-8", load_asset_text("ui.js").encode("utf-8"))
            elif parsed.path == "/health":
                self._send_json({"status": "ok", "service": "home"})
            else:
                self._send_html("Not Found", status=HTTPStatus.NOT_FOUND)
            request_log.finish(request_logger, "request_complete", int(self._response_status), page=parsed.path)

        def do_POST(self) -> None:
            request_log = start_request_log("POST", self.path)
            self._response_status = HTTPStatus.OK
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            lang = resolve_language(query.get("lang", ["en"])[0])
            parts = [segment for segment in parsed.path.split("/") if segment]

            routed = self._project_gateway_route(parsed)
            if routed is not None:
                request_log.finish(request_logger, "request_complete", int(self._response_status), page=parsed.path)
                return

            if parsed.path in {"/projects/new", "/setup/project"}:
                state = parse_project_create_form(self._read_form_payload(), app_home, registry)
                is_setup = parsed.path == "/setup/project"
                log_event(
                    request_logger,
                    logging.INFO,
                    "project_create_submitted",
                    project_id=state.values["project_id"],
                    project_root=state.values["project_root"] or "<default>",
                    http_port=state.values["http_port"],
                    mcp_port=state.values["mcp_port"],
                    write_mode=state.values["write_mode"],
                    schema_template=state.values["schema_template"],
                )
                if state.errors or state.form_error:
                    log_event(
                        request_logger,
                        logging.WARNING,
                        "project_create_validation_failed",
                        project_id=state.values["project_id"] or "<empty>",
                    )
                    self._send_html(
                        render_setup_page(registry, app_home, self.path, lang, state)
                        if is_setup
                        else render_project_create_page(app_home, self.path, lang, state),
                        status=HTTPStatus.BAD_REQUEST,
                    )
                    request_log.finish(request_logger, "request_complete", int(self._response_status), page=parsed.path)
                    return

                project_root = effective_project_root(app_home, state.values["project_id"], state.values["project_root"])
                try:
                    project = project_service.create_project(
                        project_id=state.values["project_id"],
                        display_name=state.values["display_name"],
                        project_root=project_root,
                        http_port=int(state.values["http_port"]),
                        mcp_port=int(state.values["mcp_port"]),
                        write_mode=state.values["write_mode"],
                        schema_template=state.values["schema_template"],
                    )
                except ValueError as exc:
                    state.form_error = str(exc)
                    state.open_advanced = True
                    log_event(
                        request_logger,
                        logging.WARNING,
                        "project_create_validation_failed",
                        project_id=state.values["project_id"] or "<empty>",
                    )
                    self._send_html(
                        render_setup_page(registry, app_home, self.path, lang, state)
                        if is_setup
                        else render_project_create_page(app_home, self.path, lang, state),
                        status=HTTPStatus.BAD_REQUEST,
                    )
                    request_log.finish(request_logger, "request_complete", int(self._response_status), page=parsed.path)
                    return

                log_event(
                    request_logger,
                    logging.INFO,
                    "project_created_from_home",
                    project_id=project.project_id,
                    project_root=project.project_root,
                    http_port=project.http_port,
                    mcp_port=project.mcp_port,
                    write_mode=project.write_mode,
                )
                if is_setup:
                    self._redirect(f"/setup?flash=created&project_id={project.project_id}&lang={lang}")
                else:
                    self._redirect(f"/?flash=created&project_id={project.project_id}&lang={lang}")
                request_log.finish(request_logger, "request_complete", int(self._response_status), page=parsed.path)
                return

            if parsed.path == "/settings/base-url":
                payload = self._read_form_payload()
                try:
                    set_app_base_url(registry, payload.get("base_url", ""))
                    self._redirect(f"/?flash=base_url_saved&lang={lang}")
                except ValueError:
                    self._redirect(f"/?flash=failed&lang={lang}")
                request_log.finish(request_logger, "request_complete", int(self._response_status), page=parsed.path)
                return

            if len(parts) == 3 and parts[0] == "projects" and parts[2] == "edit":
                project = registry.get_project(parts[1])
                if project is None:
                    self._redirect(f"/?flash=failed&lang={lang}")
                    request_log.finish(request_logger, "request_complete", int(self._response_status), page=parsed.path)
                    return
                state = parse_project_edit_form(project, self._read_form_payload())
                if state.errors or state.form_error:
                    self._send_html(render_project_edit_page(project, self.path, lang, state), status=HTTPStatus.BAD_REQUEST)
                    request_log.finish(request_logger, "request_complete", int(self._response_status), page=parsed.path)
                    return
                try:
                    updated = project_service.update_project(
                        project_id=project.project_id,
                        display_name=state.values["display_name"],
                        write_mode=state.values["write_mode"],
                        http_host=state.values["http_host"],
                        http_port=int(state.values["http_port"]),
                        mcp_host=state.values["mcp_host"],
                        mcp_port=int(state.values["mcp_port"]),
                    )
                except ValueError as exc:
                    state.form_error = str(exc)
                    self._send_html(render_project_edit_page(project, self.path, lang, state), status=HTTPStatus.BAD_REQUEST)
                    request_log.finish(request_logger, "request_complete", int(self._response_status), page=parsed.path)
                    return
                self._redirect(f"/?flash=updated&project_id={updated.project_id}&lang={lang}")
                request_log.finish(request_logger, "request_complete", int(self._response_status), page=parsed.path)
                return

            if len(parts) == 3 and parts[0] == "projects" and parts[2] == "delete":
                project = registry.get_project(parts[1])
                if project is None:
                    self._redirect(f"/?flash=failed&lang={lang}")
                    request_log.finish(request_logger, "request_complete", int(self._response_status), page=parsed.path)
                    return
                runtime_manager.stop_project(project.project_id)
                project_service.delete_project(project.project_id)
                self._redirect(f"/?flash=deleted&lang={lang}")
                request_log.finish(request_logger, "request_complete", int(self._response_status), page=parsed.path)
                return

            if len(parts) == 3 and parts[0] == "projects" and parts[2] in {"start", "stop", "restart"}:
                project = registry.get_project(parts[1])
                if project is None:
                    self._redirect(f"/?flash=failed&lang={lang}")
                    request_log.finish(request_logger, "request_complete", int(self._response_status), page=parsed.path)
                    return
                if parts[2] == "start":
                    result = runtime_manager.start_project(project)
                    flash = "started" if result.status == "running" else "failed"
                elif parts[2] == "stop":
                    runtime_manager.stop_project(project.project_id)
                    flash = "stopped"
                else:
                    result = runtime_manager.restart_project(project)
                    flash = "restarted" if result.status == "running" else "failed"
                self._redirect(f"/?flash={flash}&project_id={project.project_id}&lang={lang}")
                request_log.finish(request_logger, "request_complete", int(self._response_status), page=parsed.path)
                return

            self._send_html("Not Found", status=HTTPStatus.NOT_FOUND)
            request_log.finish(request_logger, "request_complete", int(self._response_status), page=parsed.path)

        def do_DELETE(self) -> None:
            request_log = start_request_log("DELETE", self.path)
            self._response_status = HTTPStatus.OK
            parsed = urlparse(self.path)
            routed = self._project_gateway_route(parsed)
            if routed is None:
                self._send_json({"error": {"code": "not_found", "message": "Unknown route"}}, status=HTTPStatus.NOT_FOUND)
            request_log.finish(request_logger, "request_complete", int(self._response_status), page=parsed.path)

        def do_PUT(self) -> None:
            request_log = start_request_log("PUT", self.path)
            self._response_status = HTTPStatus.OK
            parsed = urlparse(self.path)
            routed = self._project_gateway_route(parsed)
            if routed is None:
                self._send_json({"error": {"code": "not_found", "message": "Unknown route"}}, status=HTTPStatus.NOT_FOUND)
            request_log.finish(request_logger, "request_complete", int(self._response_status), page=parsed.path)

        def do_PATCH(self) -> None:
            request_log = start_request_log("PATCH", self.path)
            self._response_status = HTTPStatus.OK
            parsed = urlparse(self.path)
            routed = self._project_gateway_route(parsed)
            if routed is None:
                self._send_json({"error": {"code": "not_found", "message": "Unknown route"}}, status=HTTPStatus.NOT_FOUND)
            request_log.finish(request_logger, "request_complete", int(self._response_status), page=parsed.path)

        def log_message(self, format: str, *args: object) -> None:
            log_event(request_logger, logging.INFO, "server_message", message=format % args if args else format)

        def _send_html(self, html: str, status: HTTPStatus = HTTPStatus.OK) -> None:
            body = html.encode("utf-8")
            self._response_status = status
            self.send_response(status.value)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_json(self, payload: dict[str, object], status: HTTPStatus = HTTPStatus.OK) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self._response_status = status
            self.send_response(status.value)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_asset(self, content_type: str, body: bytes) -> None:
            self._response_status = HTTPStatus.OK
            self.send_response(HTTPStatus.OK.value)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _redirect(self, location: str) -> None:
            self._response_status = HTTPStatus.SEE_OTHER
            self.send_response(HTTPStatus.SEE_OTHER.value)
            self.send_header("Location", location)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _read_form_payload(self) -> dict[str, str]:
            content_length = int(self.headers.get("Content-Length", "0") or "0")
            raw = self.rfile.read(content_length).decode("utf-8")
            payload = parse_qs(raw, keep_blank_values=True)
            return {key: values[-1] if values else "" for key, values in payload.items()}

        def _project_gateway_route(self, parsed) -> bool | None:
            parts = [segment for segment in parsed.path.split("/") if segment]
            if not parts or parts[0] in ROOT_PATHS:
                return None
            project_id = parts[0]
            project = registry.get_project(project_id)
            if project is None:
                self._send_html("Project Not Found", status=HTTPStatus.NOT_FOUND)
                return True
            public_root = public_base_url(registry, self.headers.get("Host", "127.0.0.1:8764"))
            if len(parts) == 1:
                query = parsed.query or "lang=en"
                self._redirect(f"/{project_id}/ui/?{query}")
                return True
            runtime = runtime_manager.get_project_runtime(project)
            if runtime.status != "running":
                self._send_gateway_unavailable(project, runtime, public_root)
                return True
            stripped_path = "/" + "/".join(parts[1:])
            if stripped_path == "/mcp":
                self._proxy_to_project(project, public_root, stripped_path, parsed.query, use_mcp=True)
            else:
                self._proxy_to_project(project, public_root, stripped_path, parsed.query, use_mcp=False)
            return True

        def _send_gateway_unavailable(self, project: ProjectConfig, runtime: ProjectRuntimeInfo, public_root: str) -> None:
            if self._gateway_request_wants_json():
                self._send_json(
                    {"error": {"code": "project_unavailable", "message": runtime.reason, "project_id": project.project_id}},
                    status=HTTPStatus.SERVICE_UNAVAILABLE,
                )
                return
            start_url = f"/projects/{project.project_id}/start"
            body = (
                "<main class=\"home-shell\">"
                "<section class=\"panel-section\">"
                f"<h1>{escape(project.display_name)}</h1>"
                f"<p>{escape(runtime.reason)}</p>"
                f'<form method="post" action="{escape(start_url, quote=True)}"><button class="button button-primary" type="submit">Start Project</button></form>'
                f'<p><a href="{escape(public_root, quote=True)}">Back to Projects</a></p>'
                "</section>"
                "</main>"
            )
            self._send_html(
                html_page("Project unavailable", body, "/assets/app.css", page_class="warm-lab"),
                status=HTTPStatus.SERVICE_UNAVAILABLE,
            )

        def _gateway_request_wants_json(self) -> bool:
            if self.path.endswith("/mcp"):
                return True
            if "application/json" in self.headers.get("Accept", ""):
                return True
            if "application/json" in self.headers.get("Content-Type", ""):
                return True
            path = urlparse(self.path).path
            parts = [segment for segment in path.split("/") if segment]
            stripped_path = "/" + "/".join(parts[1:]) if len(parts) > 1 else ""
            api_roots = (
                "/schema",
                "/entity-types",
                "/records",
                "/relations",
                "/related",
                "/evidence",
                "/search",
                "/pending-changes",
                "/export",
                "/import",
                "/backup",
                "/restore",
            )
            return any(stripped_path == root or stripped_path.startswith(f"{root}/") for root in api_roots)

        def _proxy_to_project(self, project: ProjectConfig, public_root: str, path: str, query: str, use_mcp: bool) -> None:
            body = b""
            if self.command in {"POST", "PUT", "PATCH"}:
                body = self.rfile.read(int(self.headers.get("Content-Length", "0") or "0"))
            host = project.mcp_host if use_mcp else project.http_host
            port = project.mcp_port if use_mcp else project.http_port
            target = path + (f"?{query}" if query else "")
            headers = proxy_request_headers(self.headers, host, port)
            connection = http.client.HTTPConnection(host, port, timeout=10)
            try:
                connection.request(self.command, target, body=body or None, headers=headers)
                response = connection.getresponse()
                response_body = response.read()
            except OSError as exc:
                self._send_json({"error": {"code": "proxy_error", "message": str(exc)}}, status=HTTPStatus.BAD_GATEWAY)
                return
            finally:
                connection.close()
            self._send_proxy_response(project, public_root, response.status, response.getheaders(), response_body, use_mcp)

        def _send_proxy_response(self, project: ProjectConfig, public_root: str, status: int, headers: list[tuple[str, str]], body: bytes, use_mcp: bool) -> None:
            header_map = {key.lower(): value for key, value in headers}
            content_type = header_map.get("content-type", "application/octet-stream")
            if "text/html" in content_type:
                body = rewrite_gateway_html(body, project, public_root)
            self._response_status = status
            self.send_response(status)
            skip_headers = {"content-length", "connection", "transfer-encoding", "server", "date"}
            for key, value in headers:
                lower = key.lower()
                if lower in skip_headers:
                    continue
                if lower == "location":
                    value = rewrite_gateway_location(value, project, public_root, use_mcp)
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return RequestHandler


def normalize_base_url(value: str) -> str:
    raw = value.strip().rstrip("/")
    if not raw:
        return ""
    parts = urlsplit(raw)
    if parts.scheme not in {"http", "https"} or not parts.netloc or parts.path not in {"", "/"} or parts.query or parts.fragment:
        raise ValueError("base_url must be an http(s) root URL without path, query, or fragment")
    return urlunsplit((parts.scheme, parts.netloc, "", "", "")).rstrip("/")


def set_app_base_url(registry: ProjectRegistry, value: str) -> str:
    normalized = normalize_base_url(value)
    config = registry.load()
    config.base_url = normalized
    registry.save(config)
    return normalized


def public_base_url(registry: ProjectRegistry, host_header: str) -> str:
    configured = registry.load().base_url.strip().rstrip("/")
    if configured:
        return configured
    return f"http://{host_header.strip() or '127.0.0.1:8764'}".rstrip("/")


def project_gateway_url(public_root: str, project: ProjectConfig, path: str = "") -> str:
    clean_path = path if path.startswith("/") else f"/{path}" if path else ""
    return f"{public_root}/{project.project_id}{clean_path}"


def proxy_request_headers(headers, host: str, port: int) -> dict[str, str]:
    result: dict[str, str] = {"Host": f"{host}:{port}"}
    skip = {"host", "content-length", "connection", "transfer-encoding", "server", "date"}
    for key, value in headers.items():
        if key.lower() not in skip:
            result[key] = value
    return result


def rewrite_gateway_html(body: bytes, project: ProjectConfig, public_root: str) -> bytes:
    text = body.decode("utf-8", errors="replace")
    prefix = f"/{project.project_id}"
    for attr in ("href", "src", "action"):
        for root in ("/ui", "/schema", "/entity-types", "/records", "/relations", "/related", "/evidence", "/search", "/pending-changes", "/project"):
            text = text.replace(f'{attr}="{root}', f'{attr}="{prefix}{root}')
    text = text.replace("http://127.0.0.1:8764/", f"{public_root}/")
    return text.encode("utf-8")


def rewrite_gateway_location(location: str, project: ProjectConfig, public_root: str, use_mcp: bool) -> str:
    parts = urlsplit(location)
    if parts.scheme and parts.netloc:
        local_http = f"{project.http_host}:{project.http_port}"
        local_mcp = f"{project.mcp_host}:{project.mcp_port}"
        if parts.netloc not in {local_http, local_mcp}:
            return location
        path = parts.path
        query = f"?{parts.query}" if parts.query else ""
        return project_gateway_url(public_root, project, path) + query
    if location.startswith("/"):
        return f"/{project.project_id}{location}"
    return location


def build_project_form_state(
    values: dict[str, str] | None = None,
    errors: dict[str, str] | None = None,
    form_error: str = "",
    registry: ProjectRegistry | None = None,
) -> ProjectCreateFormState:
    default_http, default_mcp = _next_available_ports(registry)
    merged = {
        "project_id": "",
        "display_name": "",
        "project_root": "",
        "http_port": default_http,
        "mcp_port": default_mcp,
        "write_mode": DEFAULT_WRITE_MODE,
        "schema_template": "general_knowledge",
    }
    if values:
        merged.update(values)
    error_map = errors or {}
    open_advanced = bool(form_error) or any(key in error_map for key in {"http_port", "mcp_port", "write_mode"})
    return ProjectCreateFormState(values=merged, errors=error_map, form_error=form_error, open_advanced=open_advanced)


def build_project_edit_state(
    project: ProjectConfig,
    values: dict[str, str] | None = None,
    errors: dict[str, str] | None = None,
    form_error: str = "",
) -> ProjectEditFormState:
    merged = {
        "display_name": project.display_name,
        "http_host": project.http_host,
        "http_port": str(project.http_port),
        "mcp_host": project.mcp_host,
        "mcp_port": str(project.mcp_port),
        "write_mode": project.write_mode,
    }
    if values:
        merged.update(values)
    error_map = errors or {}
    return ProjectEditFormState(project_id=project.project_id, values=merged, errors=error_map, form_error=form_error, open_advanced=True)


def effective_project_root(app_home: Path, project_id: str, raw_project_root: str) -> Path:
    if raw_project_root.strip():
        return Path(raw_project_root).expanduser().resolve()
    return (app_home / "projects" / project_id).resolve()


def parse_project_create_form(payload: dict[str, str], app_home: Path, registry: ProjectRegistry) -> ProjectCreateFormState:
    state = build_project_form_state(
        values={
            "project_id": payload.get("project_id", "").strip(),
            "display_name": payload.get("display_name", "").strip(),
            "project_root": payload.get("project_root", "").strip(),
            "http_port": payload.get("http_port", DEFAULT_HTTP_PORT).strip() or DEFAULT_HTTP_PORT,
            "mcp_port": payload.get("mcp_port", DEFAULT_MCP_PORT).strip() or DEFAULT_MCP_PORT,
            "write_mode": payload.get("write_mode", DEFAULT_WRITE_MODE).strip() or DEFAULT_WRITE_MODE,
            "schema_template": payload.get("schema_template", "general_knowledge").strip() or "general_knowledge",
        }
    )

    if not state.values["project_id"]:
        state.errors["project_id"] = "Project ID is required."
    elif registry.get_project(state.values["project_id"]) is not None:
        state.errors["project_id"] = "Project ID already exists."
    else:
        try:
            validate_project_id(state.values["project_id"])
        except ValueError as exc:
            state.errors["project_id"] = str(exc)

    if not state.values["display_name"]:
        state.errors["display_name"] = "Display Name is required."

    for field_name in ("http_port", "mcp_port"):
        value = state.values[field_name]
        try:
            parsed = int(value)
        except ValueError:
            state.errors[field_name] = f"{field_name} must be a valid integer."
            continue
        if parsed <= 0 or parsed > 65535:
            state.errors[field_name] = f"{field_name} must be between 1 and 65535."

    if not state.errors.get("http_port") and not state.errors.get("mcp_port"):
        if int(state.values["http_port"]) == int(state.values["mcp_port"]):
            state.errors["mcp_port"] = "HTTP Port and MCP Port must be different."

    if state.values["write_mode"] not in {"confirm", "auto"}:
        state.errors["write_mode"] = "Write Mode must be confirm or auto."
    if state.values["schema_template"] not in set(list_bundled_schema_templates()):
        state.errors["schema_template"] = "Schema Template must be one of the bundled templates."

    if state.values["project_id"] and not state.errors.get("project_id"):
        effective_root = effective_project_root(app_home, state.values["project_id"], state.values["project_root"])
        if effective_root.exists() and not effective_root.is_dir():
            state.errors["project_root"] = "Project Root must point to a directory."
        elif effective_root.exists() and any(effective_root.iterdir()):
            state.errors["project_root"] = (
                "Project Root already exists and is not empty. Home GUI create only supports a new workspace folder."
            )

    state.open_advanced = state.open_advanced or any(
        key in state.errors for key in ("http_port", "mcp_port", "write_mode", "schema_template")
    )
    return state


def parse_project_edit_form(project: ProjectConfig, payload: dict[str, str]) -> ProjectEditFormState:
    state = build_project_edit_state(
        project,
        values={
            "display_name": payload.get("display_name", "").strip(),
            "http_host": payload.get("http_host", project.http_host).strip(),
            "http_port": payload.get("http_port", str(project.http_port)).strip() or str(project.http_port),
            "mcp_host": payload.get("mcp_host", project.mcp_host).strip(),
            "mcp_port": payload.get("mcp_port", str(project.mcp_port)).strip() or str(project.mcp_port),
            "write_mode": payload.get("write_mode", project.write_mode).strip() or project.write_mode,
        },
    )

    if not state.values["display_name"]:
        state.errors["display_name"] = "Display Name is required."
    if not state.values["http_host"]:
        state.errors["http_host"] = "HTTP Host is required."
    if not state.values["mcp_host"]:
        state.errors["mcp_host"] = "MCP Host is required."

    for field_name in ("http_port", "mcp_port"):
        value = state.values[field_name]
        try:
            parsed = int(value)
        except ValueError:
            state.errors[field_name] = f"{field_name} must be a valid integer."
            continue
        if parsed <= 0 or parsed > 65535:
            state.errors[field_name] = f"{field_name} must be between 1 and 65535."

    if not state.errors.get("http_port") and not state.errors.get("mcp_port"):
        if int(state.values["http_port"]) == int(state.values["mcp_port"]):
            state.errors["mcp_port"] = "HTTP Port and MCP Port must be different."

    if state.values["write_mode"] not in {"confirm", "auto"}:
        state.errors["write_mode"] = "Write Mode must be confirm or auto."

    return state


def render_home_page(
    registry: ProjectRegistry,
    app_home: Path,
    runtime_manager: ProjectRuntimeManager,
    current_url: str = "/",
    lang: str = "en",
    public_root: str = "http://127.0.0.1:8764",
) -> str:
    projects = registry.list_projects()
    parsed = urlparse(current_url)
    query = parse_qs(parsed.query)
    flash = query.get("flash", [""])[0]
    flash_project_id = query.get("project_id", [""])[0]
    create_url = f"/projects/new?lang={lang}"
    setup_url = f"/setup?lang={lang}"
    global_flash_html = render_home_flash(flash, lang) if flash and not flash_project_id else ""
    topbar = render_home_topbar(current_url, lang, create_url, setup_url)

    if projects:
        content = "".join(
            render_project_card(
                project,
                app_home,
                runtime_manager.get_project_runtime(project),
                flash=flash if flash_project_id == project.project_id else "",
                lang=lang,
                public_root=public_root,
            )
            for project in projects
        )
        body = (
            "<main class=\"home-shell home-hub\">"
            f"{topbar}"
            "<section class=\"hero-card home-hero\">"
            "<p class=\"eyebrow\">mcp-memory</p>"
            f"<h1>{translate_text(lang, 'Open a local knowledge workspace.')}</h1>"
            f"<p class=\"hero-copy\">{translate_text(lang, 'Projects stay local, schema-driven, searchable, and available through one DNS/path gateway for people and agents.')}</p>"
            "<div class=\"hero-actions\">"
            f"<a class=\"button button-primary\" href=\"{escape(create_url, quote=True)}\">{translate_text(lang, 'New Project')}</a>"
            f"<a class=\"button button-secondary\" href=\"{escape(setup_url, quote=True)}\">{translate_text(lang, 'Setup Guide')}</a>"
            "</div>"
            "</section>"
            f"{global_flash_html}"
            f"{render_base_url_settings(registry, public_root, lang)}"
            "<section class=\"panel-section project-shelf-section\">"
            "<div class=\"section-heading\"><h2>Projects</h2><p class=\"section-subtitle\">Start, open, and route each local workspace from one place.</p></div>"
            f"<div class=\"project-grid\">{content}</div>"
            "</section>"
            "</main>"
        )
    else:
        body = (
            "<main class=\"home-shell home-hub\">"
            f"{topbar}"
            "<section class=\"hero-card home-hero\">"
            "<p class=\"eyebrow\">mcp-memory</p>"
            f"<h1>{translate_text(lang, 'Your project shelf is empty.')}</h1>"
            f"<p class=\"hero-copy\">{translate_text(lang, 'Create the first local schema-driven workspace, then open it through the Home gateway when you are ready.')}</p>"
            "<div class=\"hero-actions\">"
            f"<a class=\"button button-primary\" href=\"{escape(create_url, quote=True)}\">{translate_text(lang, 'New Project')}</a>"
            f"<a class=\"button button-secondary\" href=\"{escape(setup_url, quote=True)}\">{translate_text(lang, 'Setup Guide')}</a>"
            "</div>"
            "</section>"
            f"{global_flash_html}"
            f"{render_base_url_settings(registry, public_root, lang)}"
            f"{empty_state(translate_text(lang, 'No registered projects yet'), translate_text(lang, 'Once you create a project, it will appear here with a direct workspace link.'))}"
            "</main>"
        )
    html = html_page("mcp-memory Projects", body, "/assets/app.css", page_class="warm-lab", html_lang=lang)
    return localize_markup(html, lang)


def render_home_topbar(current_url: str, lang: str, create_url: str, setup_url: str) -> str:
    return (
        "<header class=\"home-topbar\">"
        "<a class=\"brand-mark\" href=\"/\">mcp-memory</a>"
        "<nav class=\"home-topbar-actions\" aria-label=\"Home actions\">"
        f"<a class=\"button button-secondary\" href=\"{escape(setup_url, quote=True)}\">Setup Guide</a>"
        f"<a class=\"button button-primary\" href=\"{escape(create_url, quote=True)}\">New Project</a>"
        f"{language_switcher(current_url, lang)}"
        "</nav>"
        "</header>"
    )


def render_project_card(
    project: ProjectConfig,
    app_home: Path,
    runtime: ProjectRuntimeInfo,
    flash: str = "",
    lang: str = "en",
    public_root: str = "http://127.0.0.1:8764",
) -> str:
    status_badge = {
        "running": badge("Running", "success"),
        "starting": badge("Starting", "warning"),
        "failed": badge("Failed", "danger"),
        "stopped": badge("Offline", "warning"),
    }.get(runtime.status, badge("Offline", "warning"))
    http_url = f"http://{project.http_host}:{project.http_port}"
    local_mcp_url = f"http://{project.mcp_host}:{project.mcp_port}/mcp"
    gateway_http_url = project_gateway_url(public_root, project, "/ui/")
    gateway_mcp_url = project_gateway_url(public_root, project, "/mcp")
    actions = render_project_actions(project, runtime, lang, public_root)
    hint = render_project_hint(project, app_home, runtime, flash)
    gateway_meta = key_value_grid([("Gateway HTTP", gateway_http_url), ("Gateway MCP", gateway_mcp_url)])
    local_meta = key_value_grid(
        [("Project ID", project.project_id), ("Write Mode", project.write_mode), ("Local HTTP", http_url), ("Local MCP", local_mcp_url)]
    )
    storage_meta = key_value_grid([("DB Path", str(project.database_path))])
    menu = render_project_card_menu(project, lang)
    return (
        "<article class=\"project-card\">"
        f"<div class=\"card-topline card-topline-between\">{status_badge}{menu}</div>"
        f"<h2>{escape(project.display_name)}</h2>"
        f"<p class=\"project-subtitle\">{escape(project.project_id)}</p>"
        "<div class=\"project-card-sections\">"
        f"<section class=\"project-card-section\"><h3>Gateway</h3>{gateway_meta}</section>"
        f"<section class=\"project-card-section\"><h3>Local Runtime</h3>{local_meta}</section>"
        f"<section class=\"project-card-section\"><h3>Storage</h3>{storage_meta}</section>"
        "</div>"
        f"{mcp_config_block(gateway_mcp_url, project.project_id)}"
        "<div class=\"project-actions\">"
        f"{actions}"
        "</div>"
        f"{hint}"
        "</article>"
    )


def render_project_card_menu(project: ProjectConfig, lang: str) -> str:
    edit_url = f"/projects/{project.project_id}/edit?lang={lang}"
    delete_action = f"/projects/{project.project_id}/delete?lang={lang}"
    return (
        '<details class="project-card-menu">'
        '<summary class="project-menu-toggle" aria-label="Project actions" title="Project actions">'
        '<span class="project-menu-dots" aria-hidden="true"><span></span><span></span><span></span></span>'
        "</summary>"
        '<div class="project-menu-actions">'
        f'<a class="button button-secondary project-menu-button" href="{escape(edit_url, quote=True)}">Edit</a>'
        f'<form method="post" action="{escape(delete_action, quote=True)}" onsubmit="return confirm(\'Delete this project from the shelf?\');">'
        '<button class="button button-secondary project-menu-button project-menu-delete" type="submit">Delete</button>'
        "</form>"
        "</div>"
        "</details>"
    )


def render_project_actions(project: ProjectConfig, runtime: ProjectRuntimeInfo, lang: str, public_root: str) -> str:
    workspace_url = project_gateway_url(public_root, project, "/ui/")
    current_lang = f"?lang={lang}"
    if runtime.status == "running":
        controls = [
            '<a class="button button-primary" href="{0}{1}">Open Workspace</a>'.format(
                workspace_url,
                current_lang,
            ),
        ]
        if runtime.managed:
            controls.append(
                '<form method="post" action="/projects/{0}/stop?lang={1}"><button class="button button-secondary" type="submit">Stop</button></form>'.format(
                    project.project_id,
                    lang,
                )
            )
            controls.append(
                '<form method="post" action="/projects/{0}/restart?lang={1}"><button class="button button-secondary" type="submit">Restart</button></form>'.format(
                    project.project_id,
                    lang,
                )
            )
        return "".join(controls)
    if runtime.status == "starting":
        return "<span class=\"button button-disabled\">Starting</span>"
    return '<form method="post" action="/projects/{0}/start?lang={1}"><button class="button button-primary" type="submit">Start</button></form>'.format(
        project.project_id,
        lang,
    )


def render_project_hint(project: ProjectConfig, app_home: Path, runtime: ProjectRuntimeInfo, flash: str) -> str:
    if flash:
        flash_message = {
            "created": "Project created successfully.",
            "updated": "Project updated successfully.",
            "started": "Project services started successfully.",
            "stopped": "Project services were stopped.",
            "restarted": "Project services restarted successfully.",
            "failed": "Project services failed to start. Check the project logs for details.",
        }.get(flash, "")
        if flash_message:
            return f"<div class=\"project-hint\"><p>{flash_message}</p></div>"

    if runtime.status == "failed":
        log_hint_command = 'type "{0}"'.format(project.logs_dir / "http-api.log")
        return (
            "<div class=\"project-hint\">"
            f"<p>{runtime.reason}</p>"
            f"{shell_command(log_hint_command)}"
            "</div>"
        )
    if runtime.status == "starting":
        return f"<div class=\"project-hint\"><p>{runtime.reason}</p></div>"
    if runtime.status == "running" and not runtime.managed:
        return "<div class=\"project-hint\"><p>Project services are running outside home UI.</p></div>"
    if runtime.status == "stopped":
        home_command = 'mcp-memory --app-home "{0}" run-ui-home'.format(app_home)
        return (
            "<div class=\"project-hint\">"
            "<p>Start the project here to launch both HTTP and MCP services.</p>"
            f"{shell_command(home_command)}"
            "</div>"
        )
    return ""


def render_base_url_settings(registry: ProjectRegistry, public_root: str, lang: str) -> str:
    config = registry.load()
    return (
        '<section class="panel-section gateway-panel">'
        '<div class="section-heading"><h2>DNS Gateway</h2>'
        '<p class="section-subtitle">Use one root URL for all projects. Project workspaces are available at /project_id/ and MCP at /project_id/mcp.</p></div>'
        f"{render_dns_instructions(public_root)}"
        f'<form class="project-form" method="post" action="/settings/base-url?lang={escape(lang, quote=True)}">'
        '<div class="form-grid">'
        '<label class="form-field"><span class="field-label">Base URL</span>'
        f'<input name="base_url" value="{escape(config.base_url, quote=True)}" placeholder="http://mcp-memory.local:8764"></label>'
        "</div>"
        '<div class="form-actions">'
        '<button class="button button-secondary" type="submit">Save Base URL</button>'
        "</div>"
        "</form>"
        "</section>"
    )


def render_dns_instructions(public_root: str) -> str:
    return key_value_grid(
        [
            ("Root URL", public_root),
            ("Project URL", f"{public_root}/<project_id>/"),
            ("MCP URL", f"{public_root}/<project_id>/mcp"),
        ]
    )


def render_home_flash(flash: str, lang: str) -> str:
    tone = "info"
    message = {
        "deleted": "Project removed from the shelf.",
        "failed": "Project action failed.",
        "base_url_saved": "Base URL saved.",
    }.get(flash, "")
    if flash == "failed":
        tone = "warning"
    if not message:
        return ""
    return f'<div class="flash flash-{tone}">{escape(translate_text(lang, message))}</div>'


def render_project_create_page(
    app_home: Path,
    current_url: str,
    lang: str,
    state: ProjectCreateFormState,
) -> str:
    project_root_hint = str((app_home / "projects").resolve())
    project_root_hint_text = (
        f"{translate_text(lang, 'Leave blank to use the default project folder under')} {project_root_hint}"
    )
    advanced_attr = " open" if state.open_advanced else ""
    form_error_html = (
        f'<div class="flash flash-warning">{escape(state.form_error)}</div>'
        if state.form_error
        else ""
    )
    body = (
        "<main class=\"home-shell\">"
        f"{language_switcher(current_url, lang)}"
        "<section class=\"hero-card\">"
        f"<h1>{translate_text(lang, 'Create Project')}</h1>"
        f"<p class=\"hero-copy\">{translate_text(lang, 'Set up a fresh local workspace that will appear on your project shelf right away.')}</p>"
        "</section>"
        "<section class=\"panel-section\">"
        f"{form_error_html}"
        f'<form class="project-form" method="post" action="/projects/new?lang={escape(lang, quote=True)}">'
        '<div class="form-grid project-identity-grid">'
        f"{render_form_field('project_id', 'Project ID', state, required=True)}"
        f"{render_form_field('display_name', 'Display Name', state, required=True)}"
        f"{render_form_field('project_root', 'Project Root', state, hint=project_root_hint_text)}"
        "</div>"
        f'<details class="advanced-panel"{advanced_attr}>'
        f"<summary>{escape(translate_text(lang, 'Advanced Settings'))}</summary>"
        '<div class="form-grid form-grid-advanced">'
        f"{render_form_field('http_port', 'HTTP Port', state)}"
        f"{render_form_field('mcp_port', 'MCP Port', state)}"
        f"{render_write_mode_field(state, lang)}"
        f"{render_schema_template_field(state, lang)}"
        "</div>"
        "</details>"
        '<div class="form-actions">'
        f'<button class="button button-primary" type="submit">{escape(translate_text(lang, "Create Project"))}</button>'
        f'<a class="button button-secondary" href="/?lang={escape(lang, quote=True)}">{escape(translate_text(lang, "Cancel"))}</a>'
        "</div>"
        "</form>"
        "</section>"
        "</main>"
    )
    html = html_page("Create Project", body, "/assets/app.css", page_class="warm-lab", html_lang=lang)
    return localize_markup(html, lang)


def render_project_edit_page(
    project: ProjectConfig,
    current_url: str,
    lang: str,
    state: ProjectEditFormState,
) -> str:
    form_error_html = (
        f'<div class="flash flash-warning">{escape(state.form_error)}</div>'
        if state.form_error
        else ""
    )
    body = (
        "<main class=\"home-shell\">"
        f"{language_switcher(current_url, lang)}"
        "<section class=\"hero-card\">"
        f"<h1>{translate_text(lang, 'Edit Project')}</h1>"
        f"<p class=\"hero-copy\">{translate_text(lang, 'Adjust the project name, write mode, and local endpoints from Home UI.')}</p>"
        "</section>"
        "<section class=\"panel-section\">"
        f"{form_error_html}"
        f'<form class="project-form" method="post" action="/projects/{escape(project.project_id, quote=True)}/edit?lang={escape(lang, quote=True)}">'
        '<div class="form-grid project-identity-grid">'
        f'<label class="form-field"><span class="field-label">Project ID</span><input value="{escape(project.project_id, quote=True)}" readonly></label>'
        f"{render_project_edit_field('display_name', 'Display Name', state, required=True)}"
        "</div>"
        '<details class="advanced-panel" open>'
        f"<summary>{escape(translate_text(lang, 'Advanced Settings'))}</summary>"
        '<div class="form-grid form-grid-advanced">'
        f"{render_project_edit_field('http_host', 'HTTP Host', state, required=True)}"
        f"{render_project_edit_field('http_port', 'HTTP Port', state, required=True)}"
        f"{render_project_edit_field('mcp_host', 'MCP Host', state, required=True)}"
        f"{render_project_edit_field('mcp_port', 'MCP Port', state, required=True)}"
        f"{render_project_edit_write_mode_field(state, lang)}"
        "</div>"
        "</details>"
        '<div class="form-actions">'
        f'<button class="button button-primary" type="submit">{escape(translate_text(lang, "Save Project"))}</button>'
        f'<a class="button button-secondary" href="/?lang={escape(lang, quote=True)}">{escape(translate_text(lang, "Cancel"))}</a>'
        "</div>"
        "</form>"
        "</section>"
        "</main>"
    )
    html = html_page("Edit Project", body, "/assets/app.css", page_class="warm-lab", html_lang=lang)
    return localize_markup(html, lang)


def render_setup_page(
    registry: ProjectRegistry,
    app_home: Path,
    current_url: str,
    lang: str,
    state: ProjectCreateFormState,
    public_root: str = "http://127.0.0.1:8764",
) -> str:
    parsed = urlparse(current_url)
    query = parse_qs(parsed.query)
    flash = query.get("flash", [""])[0]
    project_id = query.get("project_id", [""])[0]
    project = registry.get_project(project_id) if project_id else None
    flash_html = flash_banner_html("Project created successfully.", "success") if flash == "created" else ""
    project_root_hint = str((app_home / "projects").resolve())
    project_root_hint_text = (
        f"{translate_text(lang, 'Leave blank to use the default project folder under')} {project_root_hint}"
    )
    advanced_attr = " open" if state.open_advanced else ""
    form_error_html = flash_banner_html(state.form_error, "warning") if state.form_error else ""
    mcp_html = ""
    paths_html = key_value_grid([("Registry Path", str(registry.config_path)), ("App Home", str(app_home))])
    if project is not None:
        mcp_endpoint = project_gateway_url(public_root, project, "/mcp")
        mcp_html = mcp_config_block(mcp_endpoint, project.project_id)
        paths_html = key_value_grid(
            [
                ("DB Path", str(project.database_path)),
                ("Exports Dir", str(project.exports_dir)),
                ("Backups Dir", str(project.backups_dir)),
            ]
        )

    body = (
        "<main class=\"home-shell\">"
        f"{language_switcher(current_url, lang)}"
        "<section class=\"hero-card\">"
        f"<h1>{translate_text(lang, 'Setup Guide')}</h1>"
        f"<p class=\"hero-copy\">{translate_text(lang, 'Create one local workspace, copy the MCP endpoint, then open the project tools when you are ready.')}</p>"
        "</section>"
        f"{flash_html}"
        "<section class=\"setup-steps\">"
        f"{setup_step('1', 'Local Home', key_value_grid([('App Home', str(app_home)), ('Registry Path', str(registry.config_path))]), 'Everything stays on this machine.')}"
        f"{setup_step('DNS', 'DNS Gateway', render_dns_instructions(public_root), 'Point a local DNS name at the root Home UI, then route projects by path.')}"
        f"{setup_step('2', 'Create Project', form_error_html + render_setup_project_form(state, lang, project_root_hint_text, advanced_attr), 'Use the same local project creation flow as the main form.')}"
        f"{setup_step('3', 'MCP Endpoint', mcp_html or empty_state('No project selected yet', 'Create a project first, then the MCP config will appear here.'), 'Connect agents through the MCP endpoint.')}"
        f"{setup_step('4', 'Local Paths', paths_html, 'Backups and exports stay beside the project workspace.')}"
        "</section>"
        "</main>"
    )
    html = html_page("Setup Guide", body, "/assets/app.css", page_class="warm-lab", html_lang=lang)
    return localize_markup(html, lang)


def render_setup_project_form(state: ProjectCreateFormState, lang: str, project_root_hint_text: str, advanced_attr: str) -> str:
    return (
        f'<form class="project-form" method="post" action="/setup/project?lang={escape(lang, quote=True)}">'
        '<div class="form-grid">'
        f"{render_form_field('project_id', 'Project ID', state, required=True)}"
        f"{render_form_field('display_name', 'Display Name', state, required=True)}"
        f"{render_form_field('project_root', 'Project Root', state, hint=project_root_hint_text)}"
        "</div>"
        f'<details class="advanced-panel"{advanced_attr}>'
        f"<summary>{escape(translate_text(lang, 'Advanced Settings'))}</summary>"
        '<div class="form-grid form-grid-advanced">'
        f"{render_form_field('http_port', 'HTTP Port', state)}"
        f"{render_form_field('mcp_port', 'MCP Port', state)}"
        f"{render_write_mode_field(state, lang)}"
        f"{render_schema_template_field(state, lang)}"
        "</div>"
        "</details>"
        '<div class="form-actions">'
        f'<button class="button button-primary" type="submit">{escape(translate_text(lang, "Create Project"))}</button>'
        f'<a class="button button-secondary" href="/?lang={escape(lang, quote=True)}">{escape(translate_text(lang, "Cancel"))}</a>'
        "</div>"
        "</form>"
    )


def render_project_edit_field(
    field_name: str,
    label: str,
    state: ProjectEditFormState,
    required: bool = False,
) -> str:
    value = state.values.get(field_name, "")
    error_message = state.errors.get(field_name, "")
    error_class = " field-error" if error_message else ""
    required_attr = " required" if required else ""
    error_html = f'<p class="field-error-text">{escape(error_message)}</p>' if error_message else ""
    return (
        f'<label class="form-field{error_class}">'
        f'<span class="field-label">{escape(label)}</span>'
        f'<input name="{escape(field_name, quote=True)}" value="{escape(value, quote=True)}"{required_attr}>'
        f"{error_html}"
        "</label>"
    )


def render_project_edit_write_mode_field(state: ProjectEditFormState, lang: str) -> str:
    selected = state.values.get("write_mode", DEFAULT_WRITE_MODE)
    error_message = state.errors.get("write_mode", "")
    error_class = " field-error" if error_message else ""
    error_html = f'<p class="field-error-text">{escape(error_message)}</p>' if error_message else ""
    confirm_selected = " selected" if selected == "confirm" else ""
    auto_selected = " selected" if selected == "auto" else ""
    return (
        f'<label class="form-field{error_class}">'
        f'<span class="field-label">{escape(translate_text(lang, "Write Mode"))}</span>'
        '<select name="write_mode">'
        f'<option value="confirm"{confirm_selected}>confirm</option>'
        f'<option value="auto"{auto_selected}>auto</option>'
        "</select>"
        f"{error_html}"
        "</label>"
    )


def setup_step(number: str, title: str, content: str, subtitle: str) -> str:
    return (
        "<article class=\"panel-section setup-step\">"
        f"<div class=\"card-topline\">{badge(number, 'accent')}</div>"
        f"<h2>{escape(title)}</h2>"
        f"<p class=\"section-subtitle\">{escape(subtitle)}</p>"
        f"{content}"
        "</article>"
    )


def flash_banner_html(message: str, tone: str) -> str:
    return f"<div class=\"flash flash-{escape(tone)}\">{escape(message)}</div>"


def render_form_field(
    field_name: str,
    label: str,
    state: ProjectCreateFormState,
    required: bool = False,
    hint: str = "",
) -> str:
    value = state.values.get(field_name, "")
    error_message = state.errors.get(field_name, "")
    error_class = " field-error" if error_message else ""
    required_attr = " required" if required else ""
    hint_html = f'<p class="field-hint">{escape(hint)}</p>' if hint else ""
    error_html = f'<p class="field-error-text">{escape(error_message)}</p>' if error_message else ""
    return (
        f'<label class="form-field{error_class}">'
        f'<span class="field-label">{escape(label)}</span>'
        f'<input name="{escape(field_name, quote=True)}" value="{escape(value, quote=True)}"{required_attr}>'
        f"{hint_html}"
        f"{error_html}"
        "</label>"
    )


def render_write_mode_field(state: ProjectCreateFormState, lang: str) -> str:
    selected = state.values.get("write_mode", DEFAULT_WRITE_MODE)
    error_message = state.errors.get("write_mode", "")
    error_class = " field-error" if error_message else ""
    error_html = f'<p class="field-error-text">{escape(error_message)}</p>' if error_message else ""
    confirm_selected = " selected" if selected == "confirm" else ""
    auto_selected = " selected" if selected == "auto" else ""
    return (
        f'<label class="form-field{error_class}">'
        f'<span class="field-label">{escape(translate_text(lang, "Write Mode"))}</span>'
        '<select name="write_mode">'
        f'<option value="confirm"{confirm_selected}>confirm</option>'
        f'<option value="auto"{auto_selected}>auto</option>'
        "</select>"
        f"{error_html}"
        "</label>"
    )


def render_schema_template_field(state: ProjectCreateFormState, lang: str) -> str:
    selected = state.values.get("schema_template", "general_knowledge")
    error_message = state.errors.get("schema_template", "")
    error_class = " field-error" if error_message else ""
    error_html = f'<p class="field-error-text">{escape(error_message)}</p>' if error_message else ""
    options = "".join(
        f'<option value="{escape(name, quote=True)}"{" selected" if selected == name else ""}>{escape(name)}</option>'
        for name in list_bundled_schema_templates()
    )
    return (
        f'<label class="form-field{error_class}">'
        f'<span class="field-label">{escape(translate_text(lang, "Schema Template"))}</span>'
        f'<select name="schema_template">{options}</select>'
        f"{error_html}"
        "</label>"
    )
