from __future__ import annotations

import json
import logging
import socket
import threading
import time
import unittest
from http import HTTPStatus
from unittest import mock
from urllib import error, request

import uvicorn

from tests.support import ProjectSandbox

from mcp_memory import __version__
from mcp_memory.mcp.server import ToolSpec
from mcp_memory.mcp.sdk_server import build_sdk_app, serve_project_mcp_sdk_api


def _allocate_port() -> int:
    sock = socket.socket()
    try:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
    finally:
        sock.close()


class SdkMcpServer:
    def __init__(self, sandbox: ProjectSandbox) -> None:
        self.port = _allocate_port()
        self.base_url = f"http://127.0.0.1:{self.port}"
        app = build_sdk_app(sandbox.project, sandbox.registry, log_level="ERROR")
        config = uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="error", access_log=False)
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def start(self) -> None:
        self.thread.start()
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                with request.urlopen(self.base_url + "/health", timeout=1) as response:
                    if response.status == HTTPStatus.OK:
                        return
            except OSError:
                time.sleep(0.05)
        raise RuntimeError("SDK MCP server did not start")

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=10)


class SdkMcpServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sandbox = ProjectSandbox()
        self.sandbox.project.write_mode = "auto"
        self.sdk_server = SdkMcpServer(self.sandbox)
        self.sdk_server.start()
        self.base_url = self.sdk_server.base_url
        self.session_id = self._initialize()

    def tearDown(self) -> None:
        self.sdk_server.stop()
        self.sandbox.cleanup()

    def test_streamable_http_handshake_tools_prompts_and_empty_resources(self) -> None:
        health = self._get_json("/health")
        self.assertEqual(health["status"], "ok")
        self.assertEqual(health["project_id"], "test-project")

        tools = self._rpc("tools/list", {})["result"]["tools"]
        tool_names = {item["name"] for item in tools}
        self.assertIn("search_records", tool_names)
        self.assertIn("upsert_record", tool_names)
        self.assertIn("delete_record", tool_names)
        self.assertEqual({item["name"]: item for item in tools}["upsert_record"]["inputSchema"]["required"], ["entity_type", "payload"])

        search_schema = {item["name"]: item for item in tools}["search_records"]["inputSchema"]
        self.assertIn("include_archived", search_schema["properties"])

        prompts = self._rpc("prompts/list", {})["result"]["prompts"]
        prompt_names = {item["name"] for item in prompts}
        self.assertIn("agent_workspace_guide", prompt_names)
        guide = self._rpc(
            "prompts/get",
            {"name": "agent_workspace_guide", "arguments": {"task": "SDK smoke", "focus_entity": "note-1"}},
        )["result"]
        self.assertEqual(guide["messages"][0]["role"], "user")
        self.assertIn("SDK smoke", guide["messages"][0]["content"]["text"])

        self.assertEqual(self._rpc("resources/list", {})["result"]["resources"], [])
        self.assertEqual(self._rpc("resources/templates/list", {})["result"]["resourceTemplates"], [])

    def test_sdk_transport_round_trips_4kb_and_16kb_record_payloads(self) -> None:
        for size in (4096, 16384):
            with self.subTest(size=size):
                body = "A" * size
                slug = f"sdk-long-{size}"
                created = self._call_tool(
                    "upsert_record",
                    {"entity_type": "note", "payload": {"slug": slug, "title": f"SDK Long {size}", "body": body}},
                )["result"]["structuredContent"]
                self.assertEqual(created["payload"]["body"], body)

                loaded = self._call_tool("get_record", {"entity_type": "note", "record_id": slug})["result"]["structuredContent"]
                self.assertEqual(loaded["payload"]["body"], body)

    def test_sdk_transport_deletes_archived_record(self) -> None:
        self._call_tool(
            "upsert_record",
            {"entity_type": "note", "payload": {"slug": "sdk-delete", "title": "SDK Delete", "body": "sdk purge"}},
        )
        active_delete = self._call_tool("delete_record", {"entity_type": "note", "record_id": "sdk-delete"})
        self.assertEqual(active_delete["error"]["code"], -32602)

        self._call_tool("archive_record", {"entity_type": "note", "record_id": "sdk-delete"})
        self.assertEqual(len(self._call_tool("search_records", {"q": "purge"})["result"]["structuredContent"]["items"]), 0)
        self.assertEqual(len(self._call_tool("search_records", {"q": "purge", "include_archived": True})["result"]["structuredContent"]["items"]), 1)

        deleted = self._call_tool("delete_record", {"entity_type": "note", "record_id": "sdk-delete"})
        self.assertEqual(deleted["result"]["structuredContent"]["status"], "archived")
        self.assertEqual(len(self._call_tool("search_records", {"q": "purge", "include_archived": True})["result"]["structuredContent"]["items"]), 0)

    def test_sdk_transport_returns_json_rpc_validation_errors(self) -> None:
        unknown_tool = self._rpc("tools/call", {"name": "missing_tool", "arguments": {}})
        self.assertEqual(unknown_tool["error"]["code"], -32602)
        self.assertIn("Unknown tool", unknown_tool["error"]["message"])

        unexpected = self._rpc("tools/call", {"name": "search_records", "arguments": {"unexpected": True}})
        self.assertEqual(unexpected["error"]["code"], -32602)
        self.assertIn("Unexpected fields", unexpected["error"]["message"])

        invalid_limit = self._rpc("tools/call", {"name": "search_records", "arguments": {"limit": 4096}})
        self.assertEqual(invalid_limit["error"]["code"], -32602)
        self.assertIn("limit must be between 0 and 1000", invalid_limit["error"]["message"])

        unknown_prompt = self._rpc("prompts/get", {"name": "missing_prompt", "arguments": {}})
        self.assertEqual(unknown_prompt["error"]["code"], -32602)
        self.assertIn("Unknown prompt", unknown_prompt["error"]["message"])

    def _initialize(self) -> str:
        payload = self._rpc(
            "initialize",
            {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "mcp-memory-tests", "version": __version__},
            },
            request_id=1,
            session_id=None,
            include_session=False,
        )
        self.assertEqual(payload["result"]["serverInfo"]["name"], "mcp-memory")
        self.assertEqual(payload["result"]["serverInfo"]["version"], __version__)
        session_id = payload["_headers"].get("Mcp-Session-Id") or payload["_headers"].get("mcp-session-id")
        self.assertTrue(session_id)
        status, _, body = self._post_rpc(
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            session_id=str(session_id),
        )
        self.assertEqual(status, HTTPStatus.ACCEPTED)
        self.assertEqual(body, b"")
        return str(session_id)

    def _get_json(self, path: str) -> dict:
        with request.urlopen(self.base_url + path, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))

    def _rpc(
        self,
        method: str,
        params: dict,
        request_id: int | None = 2,
        session_id: str | None = None,
        include_session: bool = True,
    ) -> dict:
        payload = {"jsonrpc": "2.0", "method": method, "params": params}
        if request_id is not None:
            payload["id"] = request_id
        status, headers, body = self._post_rpc(
            payload,
            session_id=self.session_id if include_session and session_id is None else session_id,
        )
        self.assertEqual(status, HTTPStatus.OK)
        decoded = json.loads(body.decode("utf-8"))
        decoded["_headers"] = headers
        return decoded

    def _call_tool(self, name: str, arguments: dict) -> dict:
        return self._rpc("tools/call", {"name": name, "arguments": arguments})

    def _post_rpc(self, payload: dict, session_id: str | None = None) -> tuple[int, dict[str, str], bytes]:
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json, text/event-stream",
        }
        if session_id:
            headers["Mcp-Session-Id"] = session_id
        req = request.Request(
            self.base_url + "/mcp",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=5) as response:
                return response.status, dict(response.headers.items()), response.read()
        except error.HTTPError as exc:
            return exc.code, dict(exc.headers.items()), exc.read()


class SdkMcpRunnerTests(unittest.TestCase):
    def test_sdk_tool_handles_internal_errors_and_non_dict_results(self) -> None:
        sandbox = ProjectSandbox()
        server = None
        try:
            def list_value(project, registry, arguments):
                _ = project
                _ = registry
                _ = arguments
                return ["ok"]

            def boom(project, registry, arguments):
                _ = project
                _ = registry
                _ = arguments
                raise RuntimeError("boom")

            tools = {
                "list_value": ToolSpec(
                    "list_value",
                    "Return a non-dict value.",
                    {"type": "object", "properties": {}, "additionalProperties": False},
                    list_value,
                ),
                "boom": ToolSpec(
                    "boom",
                    "Raise an unexpected exception.",
                    {"type": "object", "properties": {}, "additionalProperties": False},
                    boom,
                ),
            }
            with mock.patch("mcp_memory.mcp.sdk_server._build_tools", return_value=tools):
                server = SdkMcpServer(sandbox)
                server.start()
                client = _RawSdkClient(server.base_url)
                client.initialize()

                non_dict = client.rpc("tools/call", {"name": "list_value", "arguments": {}})
                self.assertEqual(non_dict["result"]["structuredContent"], {"value": ["ok"]})

                failed = client.rpc("tools/call", {"name": "boom", "arguments": {}})
                self.assertEqual(failed["error"]["code"], -32603)
                self.assertEqual(failed["error"]["message"], "Internal server error")
        finally:
            if server is not None:
                server.stop()
            sandbox.cleanup()

    def test_serve_project_mcp_sdk_api_configures_uvicorn(self) -> None:
        sandbox = ProjectSandbox()
        try:
            fake_logger = logging.getLogger("mcp_memory.test_sdk_runner")
            fake_app = mock.Mock()
            with mock.patch("mcp_memory.mcp.sdk_server.configure_logging", return_value=fake_logger) as configure_logging:
                with mock.patch("mcp_memory.mcp.sdk_server.build_sdk_app", return_value=fake_app) as build_app:
                    with mock.patch("mcp_memory.mcp.sdk_server.uvicorn.run") as uvicorn_run:
                        serve_project_mcp_sdk_api(sandbox.project, sandbox.registry, "127.0.0.1", 9999, log_level="DEBUG")

            self.assertEqual(configure_logging.call_count, 2)
            build_app.assert_called_once_with(sandbox.project, sandbox.registry, logger=fake_logger, log_level="DEBUG")
            uvicorn_run.assert_called_once_with(fake_app, host="127.0.0.1", port=9999, log_level="debug", access_log=False)
        finally:
            sandbox.cleanup()


class _RawSdkClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url
        self.session_id: str | None = None

    def initialize(self) -> None:
        response = self.rpc(
            "initialize",
            {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "mcp-memory-tests", "version": __version__},
            },
            include_session=False,
        )
        self.session_id = response["_headers"].get("Mcp-Session-Id") or response["_headers"].get("mcp-session-id")
        status, _, body = self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        if status != HTTPStatus.ACCEPTED or body:
            raise AssertionError(f"initialized notification failed: status={status} body={body!r}")

    def rpc(self, method: str, params: dict, include_session: bool = True) -> dict:
        status, headers, body = self._post(
            {"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
            include_session=include_session,
        )
        if status != HTTPStatus.OK:
            raise AssertionError(f"RPC failed: status={status} body={body!r}")
        payload = json.loads(body.decode("utf-8"))
        payload["_headers"] = headers
        return payload

    def _post(self, payload: dict, include_session: bool = True) -> tuple[int, dict[str, str], bytes]:
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json, text/event-stream",
        }
        if include_session and self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        req = request.Request(
            self.base_url + "/mcp",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with request.urlopen(req, timeout=5) as response:
            return response.status, dict(response.headers.items()), response.read()


if __name__ == "__main__":
    unittest.main()
