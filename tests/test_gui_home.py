from __future__ import annotations

import socket
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock
from urllib import error, parse, request

from tests.support import ProjectSandbox

from mcp_memory.config import ProjectRegistry
from mcp_memory.gui.home import (
    build_home_handler,
    build_project_form_state,
    effective_project_root,
    parse_project_create_form,
    probe_project_http_health,
    render_home_page,
    render_project_actions,
    render_project_create_page,
    render_project_hint,
    serve_ui_home,
)
from mcp_memory.logging_utils import configure_logging, shutdown_logging
from mcp_memory.runtime import ProjectRuntimeInfo, ProjectRuntimeManager


class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/health":
            body = b'{"status":"ok"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        return


def _allocate_port() -> int:
    sock = socket.socket()
    try:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
    finally:
        sock.close()


class GuiHomeTests(unittest.TestCase):
    def tearDown(self) -> None:
        shutdown_logging()

    def test_render_home_page_empty_registry(self) -> None:
        with TemporaryDirectory() as tmp:
            app_home = Path(tmp) / "app"
            try:
                configure_logging("ui_home", "INFO", app_home / "logs" / "ui-home.log")
                registry = ProjectRegistry(app_home / "app_config.json")
                html = render_home_page(registry, app_home, ProjectRuntimeManager(app_home))
            finally:
                shutdown_logging()
        self.assertIn("Your project shelf is empty", html)
        self.assertIn("New Project", html)

    def test_render_home_page_russian_language(self) -> None:
        with TemporaryDirectory() as tmp:
            app_home = Path(tmp) / "app"
            try:
                configure_logging("ui_home", "INFO", app_home / "logs" / "ui-home.log")
                registry = ProjectRegistry(app_home / "app_config.json")
                html = render_home_page(registry, app_home, ProjectRuntimeManager(app_home), "/?lang=ru", "ru")
            finally:
                shutdown_logging()
        self.assertIn('lang="ru"', html)
        self.assertIn("/projects/new?lang=ru", html)
        self.assertNotIn("Your project shelf is empty.", html)

    def test_probe_project_http_health_running_and_offline(self) -> None:
        sandbox = ProjectSandbox()
        try:
            sandbox.project.http_port = _allocate_port()
            log_path = sandbox.app_home / "logs" / "ui-home.log"
            configure_logging("ui_home", "INFO", log_path)
            offline = probe_project_http_health(sandbox.project, timeout_seconds=0.05)
            self.assertEqual(offline.state, "offline")

            server = HTTPServer((sandbox.project.http_host, sandbox.project.http_port), _HealthHandler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                running = probe_project_http_health(sandbox.project, timeout_seconds=0.2)
                self.assertEqual(running.state, "running")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
            self.assertIn("project_probe", log_path.read_text(encoding="utf-8"))
        finally:
            sandbox.cleanup()

    def test_render_home_page_shows_start_for_stopped_project(self) -> None:
        sandbox = ProjectSandbox()
        try:
            html = render_home_page(sandbox.registry, sandbox.app_home, ProjectRuntimeManager(sandbox.app_home))
        finally:
            sandbox.cleanup()
        self.assertIn(">Start<", html)
        self.assertIn("launch both HTTP and MCP services", html)

    def test_home_http_handler_renders_project_and_assets(self) -> None:
        sandbox = ProjectSandbox()
        server = None
        thread = None
        mcp_server = None
        mcp_thread = None
        try:
            health_server = HTTPServer((sandbox.project.http_host, sandbox.project.http_port), _HealthHandler)
            health_thread = threading.Thread(target=health_server.serve_forever, daemon=True)
            health_thread.start()
            mcp_server = HTTPServer((sandbox.project.mcp_host, sandbox.project.mcp_port), _HealthHandler)
            mcp_thread = threading.Thread(target=mcp_server.serve_forever, daemon=True)
            mcp_thread.start()
            try:
                handler = build_home_handler(sandbox.registry, sandbox.app_home, ProjectRuntimeManager(sandbox.app_home))
                server = HTTPServer(("127.0.0.1", 0), handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                base_url = f"http://127.0.0.1:{server.server_port}"

                with request.urlopen(base_url + "/") as response:
                    html = response.read().decode("utf-8")
                with request.urlopen(base_url + "/?lang=ru") as response:
                    russian_html = response.read().decode("utf-8")
                with request.urlopen(base_url + "/assets/app.css") as response:
                    css = response.read().decode("utf-8")

                self.assertIn("Pick up your reverse-engineering workspace", html)
                self.assertIn("Test Project", html)
                self.assertIn("Running", html)
                self.assertIn("/ui/", html)
                self.assertIn("New Project", html)
                self.assertIn("lang=ru", russian_html)
                self.assertIn("badge-success", russian_html)
                self.assertIn("/projects/new?lang=ru", russian_html)
                self.assertIn("--paper", css)
            finally:
                health_server.shutdown()
                health_server.server_close()
                health_thread.join(timeout=5)
                if mcp_server is not None:
                    mcp_server.shutdown()
                    mcp_server.server_close()
                if mcp_thread is not None:
                    mcp_thread.join(timeout=5)
        finally:
            if server is not None:
                server.shutdown()
                server.server_close()
            if thread is not None:
                thread.join(timeout=5)
            sandbox.cleanup()

    def test_home_handler_post_actions(self) -> None:
        sandbox = ProjectSandbox()
        server = None
        thread = None
        try:
            runtime_manager = mock.Mock()
            runtime_manager.get_project_runtime.return_value = ProjectRuntimeInfo("test-project", "stopped", "not running", False)
            runtime_manager.start_project.return_value = ProjectRuntimeInfo("test-project", "running", "started", True, 1, 2)
            runtime_manager.stop_project.return_value = ProjectRuntimeInfo("test-project", "stopped", "stopped", True, None, None)
            runtime_manager.restart_project.return_value = ProjectRuntimeInfo("test-project", "running", "restarted", True, 3, 4)
            handler = build_home_handler(sandbox.registry, sandbox.app_home, runtime_manager)
            server = HTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base_url = f"http://127.0.0.1:{server.server_port}"

            start_response = request.urlopen(
                request.Request(base_url + "/projects/test-project/start?lang=en", data=b"", method="POST")
            )
            stop_response = request.urlopen(
                request.Request(base_url + "/projects/test-project/stop?lang=en", data=b"", method="POST")
            )
            restart_response = request.urlopen(
                request.Request(base_url + "/projects/test-project/restart?lang=ru", data=b"", method="POST")
            )

            self.assertIn("flash=started", start_response.geturl())
            self.assertIn("flash=stopped", stop_response.geturl())
            self.assertIn("flash=restarted", restart_response.geturl())
            self.assertIn("lang=ru", restart_response.geturl())
            runtime_manager.start_project.assert_called_once()
            runtime_manager.stop_project.assert_called_once_with("test-project")
            runtime_manager.restart_project.assert_called_once()
        finally:
            if server is not None:
                server.shutdown()
                server.server_close()
            if thread is not None:
                thread.join(timeout=5)
            sandbox.cleanup()

    def test_home_handler_renders_create_project_form(self) -> None:
        sandbox = ProjectSandbox()
        server = None
        thread = None
        try:
            handler = build_home_handler(sandbox.registry, sandbox.app_home, ProjectRuntimeManager(sandbox.app_home))
            server = HTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base_url = f"http://127.0.0.1:{server.server_port}"

            with request.urlopen(base_url + "/projects/new?lang=en") as response:
                html = response.read().decode("utf-8")

            self.assertIn("Create Project", html)
            self.assertIn("Project ID", html)
            self.assertIn("Advanced Settings", html)
            self.assertIn('action="/projects/new?lang=en"', html)
        finally:
            if server is not None:
                server.shutdown()
                server.server_close()
            if thread is not None:
                thread.join(timeout=5)
            sandbox.cleanup()

    def test_home_handler_creates_project_from_form(self) -> None:
        sandbox = ProjectSandbox()
        server = None
        thread = None
        try:
            handler = build_home_handler(sandbox.registry, sandbox.app_home, ProjectRuntimeManager(sandbox.app_home))
            server = HTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base_url = f"http://127.0.0.1:{server.server_port}"
            project_root = sandbox.root / "created-project"
            form_data = parse.urlencode(
                {
                    "project_id": "created-project",
                    "display_name": "Created Project",
                    "project_root": str(project_root),
                    "http_port": "22001",
                    "mcp_port": "22002",
                    "write_mode": "auto",
                }
            ).encode("utf-8")

            with request.urlopen(
                request.Request(base_url + "/projects/new?lang=en", data=form_data, method="POST")
            ) as response:
                html = response.read().decode("utf-8")
                final_url = response.geturl()

            created_project = sandbox.registry.get_project("created-project")
            self.assertIsNotNone(created_project)
            self.assertEqual(created_project.display_name, "Created Project")
            self.assertEqual(created_project.write_mode, "auto")
            self.assertEqual(created_project.http_port, 22001)
            self.assertEqual(created_project.mcp_port, 22002)
            self.assertTrue(project_root.exists())
            self.assertIn("flash=created", final_url)
            self.assertIn("Project created successfully.", html)
            self.assertIn("Created Project", html)
            self.assertIn(">Start<", html)
        finally:
            if server is not None:
                server.shutdown()
                server.server_close()
            if thread is not None:
                thread.join(timeout=5)
            sandbox.cleanup()

    def test_home_handler_rejects_invalid_project_form(self) -> None:
        sandbox = ProjectSandbox()
        server = None
        thread = None
        try:
            occupied_root = sandbox.root / "occupied-project"
            occupied_root.mkdir(parents=True, exist_ok=True)
            (occupied_root / "marker.txt").write_text("busy", encoding="utf-8")

            handler = build_home_handler(sandbox.registry, sandbox.app_home, ProjectRuntimeManager(sandbox.app_home))
            server = HTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base_url = f"http://127.0.0.1:{server.server_port}"
            form_data = parse.urlencode(
                {
                    "project_id": "test-project",
                    "display_name": "",
                    "project_root": str(occupied_root),
                    "http_port": "9000",
                    "mcp_port": "9000",
                    "write_mode": "broken",
                }
            ).encode("utf-8")

            with self.assertRaises(error.HTTPError) as ctx:
                request.urlopen(
                    request.Request(base_url + "/projects/new?lang=en", data=form_data, method="POST")
                )
            html = ctx.exception.read().decode("utf-8")

            self.assertEqual(ctx.exception.code, 400)
            self.assertIn('action="/projects/new?lang=en"', html)
            self.assertIn("test-project", html)
            self.assertIn("Project ID already exists.", html)
            self.assertIn("Display Name is required.", html)
            self.assertIn("HTTP Port and MCP Port must be different.", html)
            self.assertIn("Write Mode must be confirm or auto.", html)
            self.assertIn(str(occupied_root), html)
        finally:
            if server is not None:
                server.shutdown()
                server.server_close()
            if thread is not None:
                thread.join(timeout=5)
            sandbox.cleanup()

    def test_serve_ui_home_constructs_server(self) -> None:
        with TemporaryDirectory() as tmp:
            app_home = Path(tmp) / "app"
            try:
                registry = ProjectRegistry(app_home / "app_config.json")
                fake_server = mock.Mock()
                fake_runtime = mock.Mock()
                with mock.patch("mcp_memory.gui.home.HTTPServer", return_value=fake_server) as server_cls:
                    with mock.patch("mcp_memory.gui.home.ProjectRuntimeManager", return_value=fake_runtime):
                        serve_ui_home(registry, "127.0.0.1", 8764, app_home)
            finally:
                shutdown_logging()
            server_cls.assert_called_once()
            fake_server.serve_forever.assert_called_once()
            fake_runtime.shutdown_all.assert_called_once()

    def test_project_form_helpers_cover_defaults_and_rendering(self) -> None:
        with TemporaryDirectory() as tmp:
            app_home = Path(tmp) / "app"
            state = build_project_form_state(
                values={"project_id": "demo", "display_name": "Demo"},
                errors={"http_port": "bad port"},
                form_error="top level",
            )
            self.assertTrue(state.open_advanced)
            self.assertEqual(effective_project_root(app_home, "demo", "").name, "demo")

            html = render_project_create_page(app_home, "/projects/new?lang=ru", "ru", state)
            self.assertIn('action="/projects/new?lang=ru"', html)
            self.assertIn("advanced-panel", html)
            self.assertIn("field-error-text", html)

    def test_parse_project_create_form_rejects_invalid_root_and_ports(self) -> None:
        with TemporaryDirectory() as tmp:
            app_home = Path(tmp) / "app"
            registry = ProjectRegistry(app_home / "app_config.json")
            occupied_root = Path(tmp) / "occupied"
            occupied_root.mkdir(parents=True, exist_ok=True)
            (occupied_root / "marker.txt").write_text("busy", encoding="utf-8")

            state = parse_project_create_form(
                {
                    "project_id": "fresh-project",
                    "display_name": "Fresh Project",
                    "project_root": str(occupied_root),
                    "http_port": "10000",
                    "mcp_port": "10000",
                    "write_mode": "confirm",
                },
                app_home,
                registry,
            )
            self.assertIn("mcp_port", state.errors)
            self.assertIn("project_root", state.errors)

            invalid_state = parse_project_create_form(
                {
                    "project_id": "",
                    "display_name": "",
                    "project_root": "",
                    "http_port": "bad",
                    "mcp_port": "70000",
                    "write_mode": "broken",
                },
                app_home,
                registry,
            )
            self.assertIn("project_id", invalid_state.errors)
            self.assertIn("display_name", invalid_state.errors)
            self.assertIn("http_port", invalid_state.errors)
            self.assertIn("mcp_port", invalid_state.errors)
            self.assertIn("write_mode", invalid_state.errors)

    def test_render_project_actions_and_hints_cover_runtime_variants(self) -> None:
        sandbox = ProjectSandbox()
        try:
            running_managed = ProjectRuntimeInfo("test-project", "running", "ok", True, 1, 2)
            running_unmanaged = ProjectRuntimeInfo("test-project", "running", "ok", False)
            failed = ProjectRuntimeInfo("test-project", "failed", "boom", True)
            starting = ProjectRuntimeInfo("test-project", "starting", "booting", True)
            stopped = ProjectRuntimeInfo("test-project", "stopped", "down", False)

            running_actions = render_project_actions(sandbox.project, running_managed, "en")
            self.assertIn("Open Workspace", running_actions)
            self.assertIn("Stop", running_actions)
            self.assertIn("Restart", running_actions)

            self.assertIn("outside home UI", render_project_hint(sandbox.project, sandbox.app_home, running_unmanaged, ""))
            self.assertIn("http-api.log", render_project_hint(sandbox.project, sandbox.app_home, failed, ""))
            self.assertIn("booting", render_project_hint(sandbox.project, sandbox.app_home, starting, ""))
            self.assertIn("Project created successfully.", render_project_hint(sandbox.project, sandbox.app_home, stopped, "created"))
            self.assertIn("run-ui-home", render_project_hint(sandbox.project, sandbox.app_home, stopped, ""))
        finally:
            sandbox.cleanup()


if __name__ == "__main__":
    unittest.main()
