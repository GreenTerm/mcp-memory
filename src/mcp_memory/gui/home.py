from __future__ import annotations

from dataclasses import dataclass, field
from html import escape
import logging
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib import error, request
from urllib.parse import parse_qs, urlparse

from mcp_memory.config import ProjectConfig, ProjectRegistry
from mcp_memory.logging_utils import configure_logging, get_logger, log_event, start_request_log
from mcp_memory.runtime import ProjectRuntimeInfo, ProjectRuntimeManager
from mcp_memory.services import ProjectService

from .i18n import language_switcher, localize_markup, resolve_language, translate_text
from .render import badge, empty_state, html_page, key_value_grid, load_asset_text, shell_command


DEFAULT_HTTP_PORT = "8765"
DEFAULT_MCP_PORT = "9876"
DEFAULT_WRITE_MODE = "confirm"


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

            if parsed.path == "/":
                self._send_html(render_home_page(registry, app_home, runtime_manager, self.path, lang))
            elif parsed.path == "/projects/new":
                log_event(request_logger, logging.INFO, "project_create_form_opened")
                self._send_html(render_project_create_page(app_home, self.path, lang, build_project_form_state()))
            elif parsed.path == "/assets/app.css":
                self._send_asset("text/css; charset=utf-8", load_asset_text("app.css").encode("utf-8"))
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

            if parsed.path == "/projects/new":
                state = parse_project_create_form(self._read_form_payload(), app_home, registry)
                log_event(
                    request_logger,
                    logging.INFO,
                    "project_create_submitted",
                    project_id=state.values["project_id"],
                    project_root=state.values["project_root"] or "<default>",
                    http_port=state.values["http_port"],
                    mcp_port=state.values["mcp_port"],
                    write_mode=state.values["write_mode"],
                )
                if state.errors or state.form_error:
                    log_event(
                        request_logger,
                        logging.WARNING,
                        "project_create_validation_failed",
                        project_id=state.values["project_id"] or "<empty>",
                    )
                    self._send_html(
                        render_project_create_page(app_home, self.path, lang, state),
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
                        render_project_create_page(app_home, self.path, lang, state),
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
                self._redirect(f"/?flash=created&project_id={project.project_id}&lang={lang}")
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

    return RequestHandler


def build_project_form_state(values: dict[str, str] | None = None, errors: dict[str, str] | None = None, form_error: str = "") -> ProjectCreateFormState:
    merged = {
        "project_id": "",
        "display_name": "",
        "project_root": "",
        "http_port": DEFAULT_HTTP_PORT,
        "mcp_port": DEFAULT_MCP_PORT,
        "write_mode": DEFAULT_WRITE_MODE,
    }
    if values:
        merged.update(values)
    error_map = errors or {}
    open_advanced = bool(form_error) or any(key in error_map for key in {"http_port", "mcp_port", "write_mode"})
    return ProjectCreateFormState(values=merged, errors=error_map, form_error=form_error, open_advanced=open_advanced)


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
        }
    )

    if not state.values["project_id"]:
        state.errors["project_id"] = "Project ID is required."
    elif registry.get_project(state.values["project_id"]) is not None:
        state.errors["project_id"] = "Project ID already exists."

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

    if state.values["project_id"] and not state.errors.get("project_id"):
        effective_root = effective_project_root(app_home, state.values["project_id"], state.values["project_root"])
        if effective_root.exists() and not effective_root.is_dir():
            state.errors["project_root"] = "Project Root must point to a directory."
        elif effective_root.exists() and any(effective_root.iterdir()):
            state.errors["project_root"] = (
                "Project Root already exists and is not empty. Home GUI create only supports a new workspace folder."
            )

    state.open_advanced = state.open_advanced or any(
        key in state.errors for key in ("http_port", "mcp_port", "write_mode")
    )
    return state


def render_home_page(
    registry: ProjectRegistry,
    app_home: Path,
    runtime_manager: ProjectRuntimeManager,
    current_url: str = "/",
    lang: str = "en",
) -> str:
    projects = registry.list_projects()
    parsed = urlparse(current_url)
    query = parse_qs(parsed.query)
    flash = query.get("flash", [""])[0]
    flash_project_id = query.get("project_id", [""])[0]
    create_url = f"/projects/new?lang={lang}"

    if projects:
        content = "".join(
            render_project_card(
                project,
                app_home,
                runtime_manager.get_project_runtime(project),
                flash=flash if flash_project_id == project.project_id else "",
                lang=lang,
            )
            for project in projects
        )
        body = (
            "<main class=\"home-shell\">"
            f"{language_switcher(current_url, lang)}"
            "<section class=\"hero-card\">"
            "<p class=\"eyebrow\">Warm Lab</p>"
            f"<h1>{translate_text(lang, 'Pick up your reverse-engineering workspace.')}</h1>"
            f"<p class=\"hero-copy\">{translate_text(lang, 'Every project stays local, searchable, and easy to reopen. This screen helps you find the right workspace and see whether it is already running.')}</p>"
            "<div class=\"hero-actions\">"
            f"<a class=\"button button-primary\" href=\"{escape(create_url, quote=True)}\">{translate_text(lang, 'New Project')}</a>"
            "</div>"
            "</section>"
            f"<section class=\"project-grid\">{content}</section>"
            "</main>"
        )
    else:
        body = (
            "<main class=\"home-shell\">"
            f"{language_switcher(current_url, lang)}"
            "<section class=\"hero-card\">"
            "<p class=\"eyebrow\">Warm Lab</p>"
            f"<h1>{translate_text(lang, 'Your project shelf is empty.')}</h1>"
            f"<p class=\"hero-copy\">{translate_text(lang, 'Create the first workspace from the browser, then start it when you are ready.')}</p>"
            "<div class=\"hero-actions\">"
            f"<a class=\"button button-primary\" href=\"{escape(create_url, quote=True)}\">{translate_text(lang, 'New Project')}</a>"
            "</div>"
            "</section>"
            f"{empty_state(translate_text(lang, 'No registered projects yet'), translate_text(lang, 'Once you create a project, it will appear here with a direct workspace link.'))}"
            "</main>"
        )
    html = html_page("mcp-memory Projects", body, "/assets/app.css", page_class="warm-lab", html_lang=lang)
    return localize_markup(html, lang)


def render_project_card(
    project: ProjectConfig,
    app_home: Path,
    runtime: ProjectRuntimeInfo,
    flash: str = "",
    lang: str = "en",
) -> str:
    status_badge = {
        "running": badge("Running", "success"),
        "starting": badge("Starting", "warning"),
        "failed": badge("Failed", "danger"),
        "stopped": badge("Offline", "warning"),
    }.get(runtime.status, badge("Offline", "warning"))
    mcp_url = f"http://{project.mcp_host}:{project.mcp_port}/mcp"
    actions = render_project_actions(project, runtime, lang)
    hint = render_project_hint(project, app_home, runtime, flash)
    meta = key_value_grid(
        [
            ("Project ID", project.project_id),
            ("Project Root", str(project.project_root)),
            ("Write Mode", project.write_mode),
            ("HTTP", f"{project.http_host}:{project.http_port}"),
            ("MCP", mcp_url),
        ]
    )
    return (
        "<article class=\"project-card\">"
        f"<div class=\"card-topline\">{status_badge}</div>"
        f"<h2>{project.display_name}</h2>"
        f"<p class=\"project-subtitle\">{project.project_id}</p>"
        f"{meta}"
        "<div class=\"project-actions\">"
        f"{actions}"
        "</div>"
        f"{hint}"
        "</article>"
    )


def render_project_actions(project: ProjectConfig, runtime: ProjectRuntimeInfo, lang: str) -> str:
    workspace_url = f"http://{project.http_host}:{project.http_port}/ui/"
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
        "<p class=\"eyebrow\">Warm Lab</p>"
        f"<h1>{translate_text(lang, 'Create Project')}</h1>"
        f"<p class=\"hero-copy\">{translate_text(lang, 'Set up a fresh local workspace that will appear on your project shelf right away.')}</p>"
        "</section>"
        "<section class=\"panel-section\">"
        f"{form_error_html}"
        f'<form class="project-form" method="post" action="/projects/new?lang={escape(lang, quote=True)}">'
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
