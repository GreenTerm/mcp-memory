from __future__ import annotations

import json
import threading
import unittest
from http import HTTPStatus
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib import error, request
from unittest import mock

from tests.support import ProjectSandbox

from mcp_memory.api.server import function_write_from_payload
from mcp_memory.logging_utils import configure_logging
from mcp_memory.mcp.server import build_handler, serve_project_mcp_api
from mcp_memory.services import FunctionService


class McpServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sandbox = ProjectSandbox()
        self.sandbox.project.write_mode = "auto"
        self.log_path = self.sandbox.project.logs_dir / "mcp.log"
        configure_logging("mcp", "INFO", self.log_path)
        configure_logging("services", "INFO", self.log_path)
        with self.sandbox.open_database() as database:
            FunctionService(database).upsert_function(
                function_write_from_payload(
                    "test-project",
                    {
                        "binary_id": "bin-main",
                        "function_id": "fn_main",
                        "address": "0x401000",
                        "raw_name": "sub_401000",
                        "current_name": "main_handler",
                        "summary": "Summary",
                        "behavior_description": "Behavior",
                        "created_by": "tester",
                        "updated_by": "tester",
                    },
                )
            )
        handler = build_handler(self.sandbox.project, self.sandbox.registry)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.sandbox.cleanup()

    def test_health_and_initialize(self) -> None:
        self.assertEqual(self._get_json("/health")["status"], "ok")
        status, headers, body = self._post_rpc(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26"}}
        )
        self.assertEqual(status, HTTPStatus.OK)
        self.assertTrue(headers.get("Mcp-Session-Id"))
        response = json.loads(body.decode("utf-8"))
        self.assertEqual(response["result"]["serverInfo"]["name"], "mcp-memory")
        self.assertIn("resources", response["result"]["capabilities"])
        self.assertIn("prompts", response["result"]["capabilities"])

    def test_streamable_http_handshake_for_codex_client(self) -> None:
        status, headers, body, version = self._post_rpc_response(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26"}},
            headers={"Accept": "application/json, text/event-stream"},
        )
        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(version, 11)
        self.assertEqual(json.loads(body.decode("utf-8"))["result"]["serverInfo"]["name"], "mcp-memory")
        session_id = headers.get("Mcp-Session-Id")
        self.assertTrue(session_id)

        status, _, body = self._post_rpc(
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            headers={"Accept": "application/json, text/event-stream", "Mcp-Session-Id": session_id},
        )
        self.assertEqual(status, HTTPStatus.ACCEPTED)
        self.assertEqual(body, b"")

        status, _, body = self._post_rpc(
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            headers={"Accept": "application/json, text/event-stream", "Mcp-Session-Id": session_id},
        )
        self.assertEqual(status, HTTPStatus.OK)
        tool_names = {item["name"] for item in json.loads(body.decode("utf-8"))["result"]["tools"]}
        self.assertIn("search_records", tool_names)

    def test_mcp_list_methods_return_empty_collections(self) -> None:
        self.assertEqual(self._rpc("resources/list", {}, request_id=20)["result"], {"resources": []})
        self.assertEqual(self._rpc("resources/templates/list", {}, request_id=21)["result"], {"resourceTemplates": []})
        prompts = self._rpc("prompts/list", {}, request_id=22)["result"]["prompts"]
        prompt_names = {item["name"] for item in prompts}
        self.assertEqual(
            prompt_names,
            {
                "agent_workspace_guide",
                "record_function_analysis",
                "record_structure_analysis",
                "record_hypothesis_evidence",
                "search_and_graph_workflow",
            },
        )
        workspace_prompt = next(item for item in prompts if item["name"] == "agent_workspace_guide")
        self.assertIn("description", workspace_prompt)
        self.assertIn("arguments", workspace_prompt)
        self.assertIn("task", {item["name"] for item in workspace_prompt["arguments"]})

    def test_prompts_get_returns_agent_instructions(self) -> None:
        response = self._rpc(
            "prompts/get",
            {
                "name": "agent_workspace_guide",
                "arguments": {
                    "task": "Review startup flow",
                    "binary_id": "bin-main",
                    "focus_entity": "fn_main",
                },
            },
            request_id=24,
        )
        result = response["result"]
        self.assertIn("safe mcp-memory workspace", result["description"])
        self.assertEqual(result["messages"][0]["role"], "user")
        self.assertEqual(result["messages"][0]["content"]["type"], "text")
        text = result["messages"][0]["content"]["text"]
        self.assertIn("project_id: test-project", text)
        self.assertIn("write_mode: auto", text)
        self.assertIn("Review startup flow", text)
        self.assertIn("bin-main", text)
        self.assertIn("fn_main", text)
        self.assertIn("get_project_config", text)
        self.assertIn("search_records", text)
        self.assertIn("get_record", text)
        self.assertIn("get_related", text)
        self.assertIn("confirm_change", text)
        self.assertIn("gui-seed", text)

    def test_prompts_get_validates_unknown_prompt_and_arguments(self) -> None:
        unknown = self._rpc("prompts/get", {"name": "missing_prompt"}, request_id=25)
        self.assertEqual(unknown["error"]["code"], -32602)
        self.assertIn("Unknown prompt", unknown["error"]["message"])

        bad_arguments = self._rpc("prompts/get", {"name": "agent_workspace_guide", "arguments": []}, request_id=26)
        self.assertEqual(bad_arguments["error"]["code"], -32602)
        self.assertIn("prompt arguments must be an object", bad_arguments["error"]["message"])

        missing_name = self._rpc("prompts/get", {}, request_id=27)
        self.assertEqual(missing_name["error"]["code"], -32602)

    def test_notifications_and_session_errors_follow_streamable_http(self) -> None:
        status, _, body = self._post_rpc({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self.assertEqual(status, HTTPStatus.ACCEPTED)
        self.assertEqual(body, b"")

        with self.assertRaises(error.HTTPError) as ctx:
            self._post_rpc(
                {"jsonrpc": "2.0", "id": 23, "method": "ping", "params": {}},
                headers={"Mcp-Session-Id": "missing-session"},
            )
        self.assertEqual(ctx.exception.code, HTTPStatus.NOT_FOUND)
        self.assertEqual(json.loads(ctx.exception.read().decode("utf-8"))["error"]["code"], "session_not_found")

    def test_mcp_get_and_delete_are_method_not_allowed(self) -> None:
        with self.assertRaises(error.HTTPError) as get_ctx:
            request.urlopen(self.base_url + "/mcp")
        self.assertEqual(get_ctx.exception.code, HTTPStatus.METHOD_NOT_ALLOWED)

        delete_request = request.Request(self.base_url + "/mcp", method="DELETE")
        with self.assertRaises(error.HTTPError) as delete_ctx:
            request.urlopen(delete_request)
        self.assertEqual(delete_ctx.exception.code, HTTPStatus.METHOD_NOT_ALLOWED)

    def test_tools_list_and_calls(self) -> None:
        listed = self._rpc("tools/list", {}, request_id=2)
        tool_names = {item["name"] for item in listed["result"]["tools"]}
        self.assertIn("search_records", tool_names)
        self.assertIn("create_function", tool_names)
        self.assertIn("export_json", tool_names)
        self.assertIn("backup_project", tool_names)
        self.assertIn("confirm_change", tool_names)

        config = self._call_tool("get_project_config", {})
        self.assertEqual(config["result"]["structuredContent"]["project"]["project_id"], "test-project")

        search = self._call_tool("search_records", {"q": "main_handler", "entity_types": ["function"]})
        self.assertEqual(len(search["result"]["structuredContent"]["items"]), 1)

        record = self._call_tool("get_record", {"entity_type": "function", "entity_id": "fn_main", "binary_id": "bin-main"})
        self.assertEqual(record["result"]["structuredContent"]["function_id"], "fn_main")

        created = self._call_tool(
            "create_function",
            {
                "binary_id": "bin-main",
                "function_id": "fn_helper",
                "address": "0x401100",
                "raw_name": "sub_401100",
                "current_name": "helper_worker",
                "summary": "Helper",
                "behavior_description": "Does helper work",
                "created_by": "tester",
                "updated_by": "tester",
            },
        )
        self.assertEqual(created["result"]["structuredContent"]["function_id"], "fn_helper")

        relation = self._call_tool(
            "create_relation",
            {
                "from_entity_type": "function",
                "from_entity_id": "fn_main",
                "to_entity_type": "function",
                "to_entity_id": "fn_helper",
                "relation_type": "calls",
                "created_by": "tester",
            },
        )
        self.assertEqual(relation["result"]["structuredContent"]["relation_type"], "calls")

        related = self._call_tool("get_related", {"entity_type": "function", "entity_id": "fn_main", "hops": 1})
        self.assertEqual(len(related["result"]["structuredContent"]["items"]), 1)

        export_path = self.sandbox.root / "bundle.json"
        backup_path = self.sandbox.root / "backup.zip"
        restored_root = self.sandbox.root / "restored_project"

        exported = self._call_tool("export_json", {"output_path": str(export_path)})
        self.assertTrue(export_path.exists())
        self.assertEqual(exported["result"]["structuredContent"]["counts"]["functions"], 2)

        imported = self._call_tool("import_json", {"input_path": str(export_path), "replace_existing": True})
        self.assertEqual(imported["result"]["structuredContent"]["counts"]["functions"], 2)

        backed_up = self._call_tool("backup_project", {"output_path": str(backup_path)})
        self.assertTrue(backup_path.exists())
        self.assertEqual(
            Path(backed_up["result"]["structuredContent"]["output_path"]).resolve(),
            backup_path.resolve(),
        )

        restored = self._call_tool(
            "restore_project",
            {
                "input_path": str(backup_path),
                "project_root": str(restored_root),
                "project_id": "restored-project",
                "display_name": "Restored Project",
                "http_port": 20000,
                "mcp_port": 20001,
            },
        )
        self.assertEqual(restored["result"]["structuredContent"]["project_id"], "restored-project")

    def test_confirm_mode_tools_queue_and_apply_pending_changes(self) -> None:
        self.sandbox.project.write_mode = "confirm"
        created = self._call_tool(
            "create_function",
            {
                "binary_id": "bin-main",
                "function_id": "fn_pending",
                "address": "0x401300",
                "raw_name": "sub_401300",
                "current_name": "pending_mcp",
                "summary": "Summary",
                "behavior_description": "Behavior",
                "created_by": "tester",
                "updated_by": "tester",
            },
        )
        pending_change_id = created["result"]["structuredContent"]["pending_change_id"]
        self.assertEqual(created["result"]["structuredContent"]["status"], "pending")

        listed = self._call_tool("list_pending_changes", {})
        self.assertEqual(len(listed["result"]["structuredContent"]["items"]), 1)

        confirmed = self._call_tool("confirm_change", {"pending_change_id": pending_change_id, "confirmed_by": "tester"})
        self.assertEqual(confirmed["result"]["structuredContent"]["pending_change"]["status"], "confirmed")

        record = self._call_tool("get_record", {"entity_type": "function", "entity_id": "fn_pending", "binary_id": "bin-main"})
        self.assertEqual(record["result"]["structuredContent"]["function_id"], "fn_pending")

        pending_relation = self._call_tool(
            "create_relation",
            {
                "from_entity_type": "function",
                "from_entity_id": "fn_main",
                "to_entity_type": "function",
                "to_entity_id": "fn_pending",
                "relation_type": "calls",
                "created_by": "tester",
            },
        )
        rejected = self._call_tool("reject_change", {"pending_change_id": pending_relation["result"]["structuredContent"]["pending_change_id"]})
        self.assertEqual(rejected["result"]["structuredContent"]["status"], "rejected")

    def test_invalid_requests_return_rpc_errors(self) -> None:
        invalid_json = request.Request(
            self.base_url + "/mcp",
            data=b"{bad json",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with request.urlopen(invalid_json) as response:
            parsed = json.loads(response.read().decode("utf-8"))
        self.assertEqual(parsed["error"]["code"], -32700)

        unknown_method = self._rpc("unknown/method", {}, request_id=4)
        self.assertEqual(unknown_method["error"]["code"], -32601)

        bad_tool = self._rpc("tools/call", {"name": "missing_tool", "arguments": {}}, request_id=5)
        self.assertEqual(bad_tool["error"]["code"], -32602)

        missing_record = self._rpc(
            "tools/call",
            {"name": "get_record", "arguments": {"entity_type": "function", "entity_id": "missing", "binary_id": "bin-main"}},
            request_id=6,
        )
        self.assertEqual(missing_record["error"]["code"], -32602)

        with self.assertRaises(error.HTTPError) as ctx:
            request.urlopen(self.base_url + "/missing")
        self.assertEqual(json.loads(ctx.exception.read().decode("utf-8"))["error"]["code"], "not_found")

        bad_path = request.Request(
            self.base_url + "/wrong",
            data=json.dumps({"jsonrpc": "2.0", "id": 7, "method": "ping", "params": {}}).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        with self.assertRaises(error.HTTPError) as ctx:
            request.urlopen(bad_path)
        self.assertEqual(json.loads(ctx.exception.read().decode("utf-8"))["error"]["code"], "not_found")

        not_object_body = request.Request(
            self.base_url + "/mcp",
            data=json.dumps(["bad"]).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        with request.urlopen(not_object_body) as response:
            self.assertEqual(json.loads(response.read().decode("utf-8"))["error"]["code"], -32600)

        bad_params = self._rpc("ping", [], request_id=8)
        self.assertEqual(bad_params["error"]["code"], -32602)

        bad_arguments = self._rpc("tools/call", {"name": "search_records", "arguments": []}, request_id=9)
        self.assertEqual(bad_arguments["error"]["code"], -32602)

        unsupported_record = self._rpc(
            "tools/call",
            {"name": "get_record", "arguments": {"entity_type": "unknown", "entity_id": "x"}},
            request_id=10,
        )
        self.assertEqual(unsupported_record["error"]["code"], -32602)

        ping = self._rpc("ping", {}, request_id=11)
        self.assertEqual(ping["result"], {})

    def test_additional_tool_handlers(self) -> None:
        created_structure = self._call_tool(
            "create_structure",
            {
                "binary_id": "bin-main",
                "structure_id": "struct_extra",
                "raw_name": "extra_t",
                "current_name": "extra_t",
                "summary": "Summary",
                "created_by": "tester",
                "updated_by": "tester",
            },
        )
        created_hypothesis = self._call_tool(
            "create_hypothesis",
            {
                "hypothesis_id": "gh_extra",
                "title": "Title",
                "statement": "Statement",
                "created_by": "tester",
                "updated_by": "tester",
            },
        )
        added_evidence = self._call_tool(
            "add_evidence",
            {
                "evidence_id": "e_extra",
                "entity_type": "function",
                "entity_id": "fn_main",
                "evidence_type": "block",
                "description": "Description",
                "created_by": "tester",
            },
        )
        all_pending = self._call_tool("list_pending_changes", {"status": "all"})
        self.assertEqual(created_structure["result"]["structuredContent"]["structure_id"], "struct_extra")
        self.assertEqual(created_hypothesis["result"]["structuredContent"]["hypothesis_id"], "gh_extra")
        self.assertEqual(added_evidence["result"]["structuredContent"]["evidence_id"], "e_extra")
        self.assertEqual(all_pending["result"]["structuredContent"]["items"], [])

    def test_serve_project_mcp_api_constructs_server(self) -> None:
        fake_server = mock.Mock()
        with mock.patch("mcp_memory.mcp.server.ThreadingHTTPServer", return_value=fake_server) as server_cls:
            serve_project_mcp_api(self.sandbox.project, self.sandbox.registry, "127.0.0.1", 9998)
        server_cls.assert_called_once()
        fake_server.serve_forever.assert_called_once()

    def test_runtime_logs_are_written_for_mcp_activity(self) -> None:
        self._rpc("ping", {}, request_id=12)
        self._call_tool("search_records", {"q": "main_handler", "entity_types": ["function"]})
        contents = self.log_path.read_text(encoding="utf-8")
        self.assertIn("request_complete", contents)
        self.assertIn("tool_call", contents)

    def _get_json(self, path: str) -> dict:
        with request.urlopen(self.base_url + path) as response:
            return json.loads(response.read().decode("utf-8"))

    def _rpc(self, method: str, params: dict, request_id: int | None) -> dict:
        payload = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        _, _, body = self._post_rpc(payload)
        return json.loads(body.decode("utf-8"))

    def _post_rpc(
        self,
        payload: dict,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        status, headers, body, _ = self._post_rpc_response(payload, headers=headers)
        return status, headers, body

    def _post_rpc_response(
        self,
        payload: dict,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, str], bytes, int]:
        request_headers = {"Content-Type": "application/json; charset=utf-8"}
        request_headers.update(headers or {})
        req = request.Request(
            self.base_url + "/mcp",
            data=json.dumps(payload).encode("utf-8"),
            headers=request_headers,
            method="POST",
        )
        with request.urlopen(req) as response:
            return response.status, dict(response.headers.items()), response.read(), response.version

    def _call_tool(self, name: str, arguments: dict) -> dict:
        return self._rpc("tools/call", {"name": name, "arguments": arguments}, request_id=3)


if __name__ == "__main__":
    unittest.main()
