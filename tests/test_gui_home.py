from __future__ import annotations

import json
import socket
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock
from urllib import error, parse, request

from tests.support import ProjectSandbox

from mcp_memory.config import ProjectRegistry
from mcp_memory.api.server import build_handler as build_api_handler
from mcp_memory.gui.home import (
    build_home_handler,
    build_project_edit_state,
    build_project_form_state,
    effective_project_root,
    normalize_base_url,
    parse_project_create_form,
    parse_project_edit_form,
    probe_project_http_health,
    public_base_url,
    render_home_flash,
    render_home_page,
    render_project_actions,
    render_project_create_page,
    render_project_hint,
    render_setup_page,
    serve_ui_home,
    set_app_base_url,
)
from mcp_memory.logging_utils import configure_logging, shutdown_logging
from mcp_memory.mcp.server import build_handler as build_mcp_handler
from mcp_memory.runtime import ProjectRuntimeInfo, ProjectRuntimeManager
from mcp_memory.schema import load_project_schema


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
        self.assertIn("Setup Guide", html)
        self.assertIn("/setup?lang=en", html)
        self.assertNotIn("Warm Lab", html)

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
                with request.urlopen(base_url + "/assets/ui.js") as response:
                    js = response.read().decode("utf-8")

                self.assertIn("Pick up your reverse-engineering workspace", html)
                self.assertIn('data-theme="dark"', html)
                self.assertIn('<script src="/assets/ui.js" defer></script>', html)
                self.assertIn("Test Project", html)
                self.assertIn("DB Path", html)
                self.assertIn("Copy MCP config", html)
                self.assertIn("mcp-config-test-project", html)
                self.assertIn("Running", html)
                self.assertIn(f"{base_url}/test-project/ui/", html)
                self.assertIn(f"{base_url}/test-project/mcp", html)
                self.assertIn("Gateway HTTP", html)
                self.assertIn("Gateway MCP", html)
                self.assertIn("New Project", html)
                self.assertNotIn("Warm Lab", html)
                self.assertIn("lang=ru", russian_html)
                self.assertIn("badge-success", russian_html)
                self.assertIn("/projects/new?lang=ru", russian_html)
                self.assertIn("--paper", css)
                self.assertIn("--bg", css)
                self.assertIn("data-theme=\"light\"", css)
                self.assertIn("mcp-memory-theme", js)
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

    def test_home_handler_saves_base_url_setting(self) -> None:
        sandbox = ProjectSandbox()
        server = None
        thread = None
        try:
            handler = build_home_handler(sandbox.registry, sandbox.app_home, ProjectRuntimeManager(sandbox.app_home))
            server = HTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base_url = f"http://127.0.0.1:{server.server_port}"
            payload = parse.urlencode({"base_url": "http://mcp-memory.local:8764/"}).encode("utf-8")

            with request.urlopen(
                request.Request(base_url + "/settings/base-url?lang=en", data=payload, method="POST")
            ) as response:
                html = response.read().decode("utf-8")

            self.assertIn("flash=base_url_saved", response.geturl())
            self.assertEqual(sandbox.registry.load().base_url, "http://mcp-memory.local:8764")
            self.assertIn("http://mcp-memory.local:8764/test-project/ui/", html)
        finally:
            if server is not None:
                server.shutdown()
                server.server_close()
            if thread is not None:
                thread.join(timeout=5)
            sandbox.cleanup()

    def test_gateway_routes_proxy_project_http_and_mcp(self) -> None:
        sandbox = ProjectSandbox()
        api_server = None
        api_thread = None
        mcp_server = None
        mcp_thread = None
        home_server = None
        home_thread = None
        try:
            sandbox.project.http_port = _allocate_port()
            sandbox.project.mcp_port = _allocate_port()
            while sandbox.project.mcp_port == sandbox.project.http_port:
                sandbox.project.mcp_port = _allocate_port()
            sandbox.project.write_mode = "auto"
            sandbox.registry.upsert_project(sandbox.project)

            api_server = HTTPServer(("127.0.0.1", sandbox.project.http_port), build_api_handler(sandbox.project, sandbox.registry))
            api_thread = threading.Thread(target=api_server.serve_forever, daemon=True)
            api_thread.start()
            mcp_server = ThreadingHTTPServer(("127.0.0.1", sandbox.project.mcp_port), build_mcp_handler(sandbox.project, sandbox.registry))
            mcp_thread = threading.Thread(target=mcp_server.serve_forever, daemon=True)
            mcp_thread.start()

            handler = build_home_handler(sandbox.registry, sandbox.app_home, ProjectRuntimeManager(sandbox.app_home))
            home_server = HTTPServer(("127.0.0.1", 0), handler)
            home_thread = threading.Thread(target=home_server.serve_forever, daemon=True)
            home_thread.start()
            base_url = f"http://127.0.0.1:{home_server.server_port}"

            with request.urlopen(base_url + "/test-project/ui/?lang=en") as response:
                dashboard_html = response.read().decode("utf-8")
            with request.urlopen(base_url + "/test-project/schema") as response:
                schema_payload = json.loads(response.read().decode("utf-8"))

            record_body = json.dumps({"payload": {"slug": "via-gateway", "title": "Via Gateway"}, "created_by": "tester"}).encode("utf-8")
            record_request = request.Request(
                base_url + "/test-project/records/note",
                data=record_body,
                method="POST",
                headers={"Content-Type": "application/json; charset=utf-8"},
            )
            with request.urlopen(record_request) as response:
                record_payload = json.loads(response.read().decode("utf-8"))

            initialize_request = request.Request(
                base_url + "/test-project/mcp",
                data=json.dumps(
                    {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26"}}
                ).encode("utf-8"),
                method="POST",
                headers={"Content-Type": "application/json; charset=utf-8", "Accept": "application/json, text/event-stream"},
            )
            with request.urlopen(initialize_request) as response:
                mcp_payload = json.loads(response.read().decode("utf-8"))
                session_id = response.headers.get("Mcp-Session-Id")

            self.assertIn('href="/test-project/ui/entities?lang=en"', dashboard_html)
            self.assertIn('src="/test-project/ui/assets/ui.js"', dashboard_html)
            self.assertIn("entity_types", schema_payload)
            self.assertEqual(record_payload["slug"], "via-gateway")
            self.assertEqual(mcp_payload["result"]["serverInfo"]["name"], "mcp-memory")
            self.assertTrue(session_id)
        finally:
            for server, thread in (
                (home_server, home_thread),
                (mcp_server, mcp_thread),
                (api_server, api_thread),
            ):
                if server is not None:
                    server.shutdown()
                    server.server_close()
                if thread is not None:
                    thread.join(timeout=5)
            sandbox.cleanup()

    def test_gateway_unknown_and_stopped_project_errors_are_clear(self) -> None:
        sandbox = ProjectSandbox()
        server = None
        thread = None
        try:
            runtime_manager = mock.Mock()
            runtime_manager.get_project_runtime.return_value = ProjectRuntimeInfo("test-project", "stopped", "not running", False)
            handler = build_home_handler(sandbox.registry, sandbox.app_home, runtime_manager)
            server = HTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base_url = f"http://127.0.0.1:{server.server_port}"

            with self.assertRaises(error.HTTPError) as missing_ctx:
                request.urlopen(base_url + "/missing-project/ui/")
            with self.assertRaises(error.HTTPError) as stopped_ctx:
                request.urlopen(base_url + "/test-project/ui/")
            with self.assertRaises(error.HTTPError) as stopped_mcp_ctx:
                request.urlopen(
                    request.Request(
                        base_url + "/test-project/mcp",
                        data=b"{}",
                        method="POST",
                        headers={"Accept": "application/json"},
                    )
                )

            self.assertEqual(missing_ctx.exception.code, 404)
            self.assertEqual(stopped_ctx.exception.code, 503)
            self.assertIn("Start Project", stopped_ctx.exception.read().decode("utf-8"))
            self.assertEqual(stopped_mcp_ctx.exception.code, 503)
            self.assertIn("project_unavailable", stopped_mcp_ctx.exception.read().decode("utf-8"))
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
            self.assertIn("Schema Template", html)
            self.assertIn("reverse_engineering", html)
            self.assertIn('action="/projects/new?lang=en"', html)
        finally:
            if server is not None:
                server.shutdown()
                server.server_close()
            if thread is not None:
                thread.join(timeout=5)
            sandbox.cleanup()

    def test_home_handler_renders_project_card_menu_and_edit_form(self) -> None:
        sandbox = ProjectSandbox()
        server = None
        thread = None
        try:
            handler = build_home_handler(sandbox.registry, sandbox.app_home, ProjectRuntimeManager(sandbox.app_home))
            server = HTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base_url = f"http://127.0.0.1:{server.server_port}"

            with request.urlopen(base_url + "/?lang=en") as response:
                home_html = response.read().decode("utf-8")
            with request.urlopen(base_url + "/projects/test-project/edit?lang=en") as response:
                edit_html = response.read().decode("utf-8")

            self.assertIn("project-card-menu", home_html)
            self.assertIn("/projects/test-project/edit?lang=en", home_html)
            self.assertIn("/projects/test-project/delete?lang=en", home_html)
            self.assertIn("Edit Project", edit_html)
            self.assertIn('action="/projects/test-project/edit?lang=en"', edit_html)
            self.assertIn('value="Test Project"', edit_html)
        finally:
            if server is not None:
                server.shutdown()
                server.server_close()
            if thread is not None:
                thread.join(timeout=5)
            sandbox.cleanup()

    def test_home_handler_missing_project_and_unknown_routes(self) -> None:
        sandbox = ProjectSandbox()
        server = None
        thread = None
        try:
            handler = build_home_handler(sandbox.registry, sandbox.app_home, ProjectRuntimeManager(sandbox.app_home))
            server = HTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base_url = f"http://127.0.0.1:{server.server_port}"

            with self.assertRaises(error.HTTPError) as missing_edit:
                request.urlopen(base_url + "/projects/missing-project/edit?lang=en")
            self.assertEqual(missing_edit.exception.code, 404)

            with self.assertRaises(error.HTTPError) as unknown_get:
                request.urlopen(base_url + "/missing-page")
            self.assertEqual(unknown_get.exception.code, 404)

            with request.urlopen(
                request.Request(base_url + "/projects/missing-project/edit?lang=en", data=b"", method="POST")
            ) as response:
                self.assertIn("flash=failed", response.geturl())

            with request.urlopen(
                request.Request(base_url + "/projects/missing-project/delete?lang=en", data=b"", method="POST")
            ) as response:
                self.assertIn("flash=failed", response.geturl())

            with request.urlopen(
                request.Request(base_url + "/projects/missing-project/start?lang=en", data=b"", method="POST")
            ) as response:
                self.assertIn("flash=failed", response.geturl())

            with self.assertRaises(error.HTTPError) as unknown_post:
                request.urlopen(request.Request(base_url + "/missing-post", data=b"", method="POST"))
            self.assertEqual(unknown_post.exception.code, 404)
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
                    "schema_template": "research_notes",
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
            self.assertEqual(load_project_schema(created_project.schema_path).entity("source").name, "source")
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

    def test_home_handler_edit_form_validation_and_service_error(self) -> None:
        sandbox = ProjectSandbox()
        server = None
        thread = None
        try:
            handler = build_home_handler(sandbox.registry, sandbox.app_home, ProjectRuntimeManager(sandbox.app_home))
            server = HTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base_url = f"http://127.0.0.1:{server.server_port}"

            invalid_form = parse.urlencode(
                {
                    "display_name": "",
                    "http_host": "",
                    "http_port": "bad",
                    "mcp_host": "",
                    "mcp_port": "0",
                    "write_mode": "broken",
                }
            ).encode("utf-8")
            with self.assertRaises(error.HTTPError) as invalid_ctx:
                request.urlopen(
                    request.Request(base_url + "/projects/test-project/edit?lang=en", data=invalid_form, method="POST")
                )
            invalid_html = invalid_ctx.exception.read().decode("utf-8")

            self.assertEqual(invalid_ctx.exception.code, 400)
            self.assertIn("Display Name is required.", invalid_html)
            self.assertIn("HTTP Host is required.", invalid_html)
            self.assertIn("MCP Host is required.", invalid_html)
            self.assertIn("http_port must be a valid integer.", invalid_html)
            self.assertIn("mcp_port must be between 1 and 65535.", invalid_html)
            self.assertIn("Write Mode must be confirm or auto.", invalid_html)

            with mock.patch("mcp_memory.gui.home.ProjectService.update_project", side_effect=ValueError("update failed")):
                valid_form = parse.urlencode(
                    {
                        "display_name": "Still Valid",
                        "http_host": "127.0.0.1",
                        "http_port": "18770",
                        "mcp_host": "127.0.0.1",
                        "mcp_port": "19880",
                        "write_mode": "confirm",
                    }
                ).encode("utf-8")
                with self.assertRaises(error.HTTPError) as service_ctx:
                    request.urlopen(
                        request.Request(
                            base_url + "/projects/test-project/edit?lang=en",
                            data=valid_form,
                            method="POST",
                        )
                    )
                service_html = service_ctx.exception.read().decode("utf-8")

            self.assertEqual(service_ctx.exception.code, 400)
            self.assertIn("update failed", service_html)
        finally:
            if server is not None:
                server.shutdown()
                server.server_close()
            if thread is not None:
                thread.join(timeout=5)
            sandbox.cleanup()

    def test_home_handler_updates_and_deletes_project_from_card_menu(self) -> None:
        sandbox = ProjectSandbox()
        server = None
        thread = None
        runtime_manager = mock.Mock()
        runtime_manager.get_project_runtime.return_value = ProjectRuntimeInfo("test-project", "stopped", "not running", False)
        runtime_manager.stop_project.return_value = ProjectRuntimeInfo("test-project", "stopped", "stopped", True, None, None)
        try:
            handler = build_home_handler(sandbox.registry, sandbox.app_home, runtime_manager)
            server = HTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base_url = f"http://127.0.0.1:{server.server_port}"

            edit_form = parse.urlencode(
                {
                    "display_name": "Edited Project",
                    "http_host": "127.0.0.2",
                    "http_port": "18888",
                    "mcp_host": "127.0.0.3",
                    "mcp_port": "19999",
                    "write_mode": "auto",
                }
            ).encode("utf-8")
            with request.urlopen(
                request.Request(base_url + "/projects/test-project/edit?lang=en", data=edit_form, method="POST")
            ) as response:
                updated_html = response.read().decode("utf-8")
                updated_url = response.geturl()

            updated_project = sandbox.registry.get_project("test-project")
            self.assertIn("flash=updated", updated_url)
            self.assertIn("Edited Project", updated_html)
            self.assertIsNotNone(updated_project)
            self.assertEqual(updated_project.display_name, "Edited Project")
            self.assertEqual(updated_project.http_host, "127.0.0.2")
            self.assertEqual(updated_project.http_port, 18888)
            self.assertEqual(updated_project.mcp_host, "127.0.0.3")
            self.assertEqual(updated_project.mcp_port, 19999)
            self.assertEqual(updated_project.write_mode, "auto")

            with request.urlopen(
                request.Request(base_url + "/projects/test-project/delete?lang=en", data=b"", method="POST")
            ) as response:
                deleted_html = response.read().decode("utf-8")
                deleted_url = response.geturl()

            self.assertIn("flash=deleted", deleted_url)
            self.assertIn("Project removed from the shelf.", deleted_html)
            self.assertIsNone(sandbox.registry.get_project("test-project"))
            runtime_manager.stop_project.assert_called_with("test-project")
        finally:
            if server is not None:
                server.shutdown()
                server.server_close()
            if thread is not None:
                thread.join(timeout=5)
            sandbox.cleanup()

    def test_setup_wizard_renders_and_creates_project(self) -> None:
        sandbox = ProjectSandbox()
        server = None
        thread = None
        try:
            handler = build_home_handler(sandbox.registry, sandbox.app_home, ProjectRuntimeManager(sandbox.app_home))
            server = HTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base_url = f"http://127.0.0.1:{server.server_port}"
            project_root = sandbox.root / "setup-project"

            with request.urlopen(base_url + "/setup?lang=en") as response:
                setup_html = response.read().decode("utf-8")

            form_data = parse.urlencode(
                {
                    "project_id": "setup-project",
                    "display_name": "Setup Project",
                    "project_root": str(project_root),
                    "http_port": "23001",
                    "mcp_port": "23002",
                    "write_mode": "confirm",
                    "schema_template": "infrastructure_deployment",
                }
            ).encode("utf-8")
            with request.urlopen(
                request.Request(base_url + "/setup/project?lang=en", data=form_data, method="POST")
            ) as response:
                created_html = response.read().decode("utf-8")
                final_url = response.geturl()

            self.assertIn("Setup Guide", setup_html)
            self.assertIn('action="/setup/project?lang=en"', setup_html)
            self.assertIn("Local Home", setup_html)
            self.assertIn("DNS Gateway", setup_html)
            self.assertIn("MCP Endpoint", setup_html)
            self.assertIn("flash=created", final_url)
            self.assertIn("/setup?", final_url)
            self.assertIn("Project created successfully.", created_html)
            self.assertIn("Copy MCP config", created_html)
            self.assertIn(f"{base_url}/setup-project/mcp", created_html)
            setup_project = sandbox.registry.get_project("setup-project")
            self.assertIsNotNone(setup_project)
            self.assertEqual(load_project_schema(setup_project.schema_path).entity("server").name, "server")
        finally:
            if server is not None:
                server.shutdown()
                server.server_close()
            if thread is not None:
                thread.join(timeout=5)
            sandbox.cleanup()

    def test_setup_wizard_preserves_russian_language_links(self) -> None:
        sandbox = ProjectSandbox()
        server = None
        thread = None
        try:
            handler = build_home_handler(sandbox.registry, sandbox.app_home, ProjectRuntimeManager(sandbox.app_home))
            server = HTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base_url = f"http://127.0.0.1:{server.server_port}"

            with request.urlopen(base_url + "/setup?lang=ru") as response:
                html = response.read().decode("utf-8")

            self.assertIn('lang="ru"', html)
            self.assertIn('action="/setup/project?lang=ru"', html)
            self.assertIn('href="/?lang=ru"', html)
        finally:
            if server is not None:
                server.shutdown()
                server.server_close()
            if thread is not None:
                thread.join(timeout=5)
            sandbox.cleanup()

    def test_setup_wizard_rejects_invalid_project_form(self) -> None:
        sandbox = ProjectSandbox()
        server = None
        thread = None
        try:
            handler = build_home_handler(sandbox.registry, sandbox.app_home, ProjectRuntimeManager(sandbox.app_home))
            server = HTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base_url = f"http://127.0.0.1:{server.server_port}"
            form_data = parse.urlencode(
                {
                    "project_id": "",
                    "display_name": "",
                    "project_root": "",
                    "http_port": "bad",
                    "mcp_port": "23002",
                    "write_mode": "confirm",
                }
            ).encode("utf-8")

            with self.assertRaises(error.HTTPError) as ctx:
                request.urlopen(
                    request.Request(base_url + "/setup/project?lang=en", data=form_data, method="POST")
                )
            html = ctx.exception.read().decode("utf-8")

            self.assertEqual(ctx.exception.code, 400)
            self.assertIn('action="/setup/project?lang=en"', html)
            self.assertIn("Project ID is required.", html)
            self.assertIn("Display Name is required.", html)
            self.assertIn("http_port must be a valid integer.", html)
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

            reserved_state = parse_project_create_form(
                {
                    "project_id": "ui",
                    "display_name": "Reserved Project",
                    "project_root": "",
                    "http_port": "12000",
                    "mcp_port": "12001",
                    "write_mode": "confirm",
                },
                app_home,
                registry,
            )
            self.assertIn("project_id", reserved_state.errors)
            self.assertIn("reserved", reserved_state.errors["project_id"])

    def test_project_form_state_uses_next_available_ports(self) -> None:
        sandbox = ProjectSandbox()
        try:
            sandbox.project.http_port = 8765
            sandbox.project.mcp_port = 9876
            sandbox.registry.upsert_project(sandbox.project)
            state = build_project_form_state(registry=sandbox.registry)
            self.assertEqual(state.values["http_port"], "8766")
            self.assertEqual(state.values["mcp_port"], "9877")
        finally:
            sandbox.cleanup()

    def test_parse_project_create_form_rejects_file_root(self) -> None:
        with TemporaryDirectory() as tmp:
            app_home = Path(tmp) / "app"
            registry = ProjectRegistry(app_home / "app_config.json")
            file_root = Path(tmp) / "occupied.txt"
            file_root.write_text("not a directory", encoding="utf-8")

            state = parse_project_create_form(
                {
                    "project_id": "file-root-project",
                    "display_name": "File Root Project",
                    "project_root": str(file_root),
                    "http_port": "12000",
                    "mcp_port": "12001",
                    "write_mode": "confirm",
                },
                app_home,
                registry,
            )

            self.assertEqual(state.errors["project_root"], "Project Root must point to a directory.")

    def test_parse_project_edit_form_rejects_invalid_fields(self) -> None:
        sandbox = ProjectSandbox()
        try:
            state = parse_project_edit_form(
                sandbox.project,
                {
                    "display_name": "",
                    "http_host": "",
                    "http_port": "bad",
                    "mcp_host": "",
                    "mcp_port": "70000",
                    "write_mode": "broken",
                },
            )
            self.assertEqual(state.errors["display_name"], "Display Name is required.")
            self.assertEqual(state.errors["http_host"], "HTTP Host is required.")
            self.assertEqual(state.errors["mcp_host"], "MCP Host is required.")
            self.assertEqual(state.errors["http_port"], "http_port must be a valid integer.")
            self.assertEqual(state.errors["mcp_port"], "mcp_port must be between 1 and 65535.")
            self.assertEqual(state.errors["write_mode"], "Write Mode must be confirm or auto.")

            same_port_state = parse_project_edit_form(
                sandbox.project,
                {
                    "display_name": "Edited",
                    "http_host": "127.0.0.1",
                    "http_port": "18888",
                    "mcp_host": "127.0.0.1",
                    "mcp_port": "18888",
                    "write_mode": "confirm",
                },
            )
            self.assertEqual(same_port_state.errors["mcp_port"], "HTTP Port and MCP Port must be different.")
        finally:
            sandbox.cleanup()

    def test_render_project_actions_and_hints_cover_runtime_variants(self) -> None:
        sandbox = ProjectSandbox()
        try:
            running_managed = ProjectRuntimeInfo("test-project", "running", "ok", True, 1, 2)
            running_unmanaged = ProjectRuntimeInfo("test-project", "running", "ok", False)
            failed = ProjectRuntimeInfo("test-project", "failed", "boom", True)
            starting = ProjectRuntimeInfo("test-project", "starting", "booting", True)
            stopped = ProjectRuntimeInfo("test-project", "stopped", "down", False)

            running_actions = render_project_actions(sandbox.project, running_managed, "en", "http://mcp-memory.local:8764")
            self.assertIn("Open Workspace", running_actions)
            self.assertIn("http://mcp-memory.local:8764/test-project/ui/", running_actions)
            self.assertIn("Stop", running_actions)
            self.assertIn("Restart", running_actions)
            self.assertIn("Starting", render_project_actions(sandbox.project, starting, "en", "http://mcp-memory.local:8764"))

            self.assertIn("outside home UI", render_project_hint(sandbox.project, sandbox.app_home, running_unmanaged, ""))
            self.assertIn("http-api.log", render_project_hint(sandbox.project, sandbox.app_home, failed, ""))
            self.assertIn("booting", render_project_hint(sandbox.project, sandbox.app_home, starting, ""))
            self.assertIn("Project created successfully.", render_project_hint(sandbox.project, sandbox.app_home, stopped, "created"))
            self.assertIn("Project updated successfully.", render_project_hint(sandbox.project, sandbox.app_home, stopped, "updated"))
            unknown_runtime = ProjectRuntimeInfo("test-project", "mystery", "???", False)
            self.assertEqual(render_project_hint(sandbox.project, sandbox.app_home, unknown_runtime, "unknown"), "")
            self.assertIn("run-ui-home", render_project_hint(sandbox.project, sandbox.app_home, stopped, ""))
        finally:
            sandbox.cleanup()

    def test_build_project_edit_state_and_home_flash_helpers(self) -> None:
        sandbox = ProjectSandbox()
        try:
            state = build_project_edit_state(
                sandbox.project,
                values={"display_name": "Edited Name"},
                errors={"display_name": "bad"},
                form_error="problem",
            )
            self.assertEqual(state.project_id, "test-project")
            self.assertEqual(state.values["display_name"], "Edited Name")
            self.assertEqual(state.errors["display_name"], "bad")
            self.assertEqual(state.form_error, "problem")

            failed_flash = render_home_flash("failed", "en")
            self.assertIn("flash-warning", failed_flash)
            self.assertIn("Project action failed.", failed_flash)
            self.assertEqual(render_home_flash("", "en"), "")
        finally:
            sandbox.cleanup()

    def test_base_url_helpers_validate_and_fallback_to_host(self) -> None:
        with TemporaryDirectory() as tmp:
            registry = ProjectRegistry(Path(tmp) / "app" / "app_config.json")
            self.assertEqual(public_base_url(registry, "127.0.0.1:1234"), "http://127.0.0.1:1234")
            self.assertEqual(set_app_base_url(registry, "http://mcp-memory.local:8764/"), "http://mcp-memory.local:8764")
            self.assertEqual(public_base_url(registry, "127.0.0.1:1234"), "http://mcp-memory.local:8764")
            self.assertEqual(normalize_base_url(""), "")
            with self.assertRaisesRegex(ValueError, "without path"):
                normalize_base_url("http://mcp-memory.local:8764/project")


if __name__ == "__main__":
    unittest.main()
