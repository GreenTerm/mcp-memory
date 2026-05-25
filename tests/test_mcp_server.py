from __future__ import annotations

import json
import os
import socket
import threading
import unittest
from http import HTTPStatus
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib import error, request
from unittest import mock

from tests.support import ProjectSandbox

from mcp_memory import __version__
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
        self.assertEqual(response["result"]["serverInfo"]["version"], __version__)
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
        self.assertIn("upsert_record", tool_names)

    def test_generic_mcp_tools_create_search_read_and_archive_record(self) -> None:
        tools = self._rpc("tools/list", {}, request_id=2)["result"]["tools"]
        tool_names = {item["name"] for item in tools}
        self.assertIn("get_schema", tool_names)
        self.assertIn("list_entity_types", tool_names)
        self.assertNotIn("create_function", tool_names)
        by_name = {item["name"]: item for item in tools}
        self.assertEqual(by_name["upsert_record"]["inputSchema"]["required"], ["entity_type", "payload"])
        self.assertIn("required payload field", by_name["upsert_record"]["inputSchema"]["properties"]["payload"]["description"])
        self.assertIn("Optional top-level fields", by_name["upsert_record"]["description"])
        self.assertIn("prompts/get agent_workspace_guide", by_name["upsert_record"]["description"])
        self.assertEqual(
            by_name["add_evidence"]["inputSchema"]["required"],
            ["entity_type", "record_id", "evidence_type", "description"],
        )
        add_evidence_props = by_name["add_evidence"]["inputSchema"]["properties"]
        self.assertIn("attachment_path", add_evidence_props)
        self.assertIn("media_type", add_evidence_props)
        self.assertIn("size_bytes", add_evidence_props)
        self.assertNotIn("source_url", add_evidence_props)
        self.assertNotIn("attachment_refs", add_evidence_props)
        self.assertIn("Required top-level fields", by_name["add_evidence"]["description"])
        self.assertIn("attachment_path", by_name["add_evidence"]["description"])
        self.assertIn("Optional top-level fields", by_name["create_relation"]["description"])
        self.assertIn("relation_type must be allowed", by_name["create_relation"]["description"])
        self.assertIn("archived_by", by_name["archive_record"]["description"])

        created = self._call_tool(
            "upsert_record",
            {
                "entity_type": "note",
                "payload": {
                    "slug": "mcp-note",
                    "title": "MCP Note",
                    "summary": "Created through MCP",
                    "body": "mcp searchable text",
                    "tags": ["mcp"],
                },
                "created_by": "tester",
                "updated_by": "tester",
            },
        )["result"]["structuredContent"]
        self.assertEqual(created["slug"], "mcp-note")

        search = self._call_tool("search_records", {"q": "searchable", "entity_types": ["note"]})
        self.assertEqual(len(search["result"]["structuredContent"]["items"]), 1)

        loaded = self._call_tool("get_record", {"entity_type": "note", "record_id": "mcp-note"})
        self.assertEqual(loaded["result"]["structuredContent"]["title"], "MCP Note")

        archived = self._call_tool("archive_record", {"entity_type": "note", "record_id": "mcp-note", "archived_by": "tester"})
        self.assertEqual(archived["result"]["structuredContent"]["status"], "archived")

    def test_generic_mcp_relation_evidence_and_pending_tools(self) -> None:
        first = self._call_tool("upsert_record", {"entity_type": "note", "payload": {"slug": "mcp-first", "title": "First"}})["result"]["structuredContent"]
        second = self._call_tool("upsert_record", {"entity_type": "note", "payload": {"slug": "mcp-second", "title": "Second"}})["result"]["structuredContent"]
        relation = self._call_tool(
            "create_relation",
            {
                "from_entity_type": "note",
                "from_record_id": first["record_id"],
                "to_entity_type": "note",
                "to_record_id": second["record_id"],
                "relation_type": "related_to",
                "created_by": "tester",
            },
        )["result"]["structuredContent"]
        self.assertEqual(relation["relation_type"], "related_to")
        related = self._call_tool("get_related", {"entity_type": "note", "record_id": first["record_id"]})
        self.assertEqual(len(related["result"]["structuredContent"]["items"]), 1)

        evidence = self._call_tool(
            "add_evidence",
            {
                "entity_type": "note",
                "record_id": first["record_id"],
                "evidence_type": "excerpt",
                "description": "MCP evidence",
                "created_by": "tester",
            },
        )["result"]["structuredContent"]
        self.assertEqual(evidence["description"], "MCP evidence")

        self.sandbox.project.write_mode = "confirm"
        pending = self._call_tool("upsert_record", {"entity_type": "note", "payload": {"slug": "queued-mcp", "title": "Queued MCP"}})["result"]["structuredContent"]
        self.assertEqual(pending["status"], "pending")
        listed = self._call_tool("list_pending_changes", {})
        self.assertEqual(len(listed["result"]["structuredContent"]["items"]), 1)
        confirmed = self._call_tool("confirm_change", {"pending_change_id": pending["pending_change_id"], "confirmed_by": "tester"})
        self.assertEqual(confirmed["result"]["structuredContent"]["pending_change"]["status"], "confirmed")
        self.assertEqual(confirmed["result"]["structuredContent"]["applied"]["slug"], "queued-mcp")

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
        self.assertIn("Active project schema", text)
        self.assertIn("entity_type=note", text)
        self.assertIn("required payload fields: title", text)
        self.assertIn("optional payload fields: slug, summary, body, tags", text)
        self.assertIn("slug_field=slug; title_field=title; summary_field=summary", text)
        self.assertIn("upsert_record: entity_type, payload", text)
        self.assertIn("add_evidence: entity_type, record_id, evidence_type, description", text)
        self.assertIn("Entity payload fields for upsert_record", text)
        self.assertIn("Tool usage examples", text)
        for tool_name in (
            "get_project_config",
            "get_schema",
            "list_entity_types",
            "search_records",
            "get_record",
            "upsert_record",
            "archive_record",
            "delete_record",
            "get_related",
            "add_evidence",
            "create_relation",
            "list_pending_changes",
            "confirm_change",
            "reject_change",
            "export_json",
            "import_json",
            "backup_project",
            "restore_project",
        ):
            self.assertIn(f"tool: {tool_name}", text)
        self.assertIn("required top-level fields: <none>", text)
        self.assertIn("optional top-level fields: q, entity_types, tag, include_archived, limit", text)
        self.assertIn("required top-level fields: entity_type, payload", text)
        self.assertIn('"title": "Note example"', text)
        self.assertIn('"relation_type": "related_to"', text)
        self.assertIn('"evidence_type": "excerpt"', text)
        self.assertIn('"record_id"', text)
        self.assertNotIn('"entity_id"', text)

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
        self.assertIn("get_schema", tool_names)
        self.assertIn("list_entity_types", tool_names)
        self.assertIn("search_records", tool_names)
        self.assertIn("upsert_record", tool_names)
        self.assertIn("archive_record", tool_names)
        self.assertIn("delete_record", tool_names)
        self.assertNotIn("create_function", tool_names)
        self.assertIn("export_json", tool_names)
        self.assertIn("backup_project", tool_names)
        self.assertIn("confirm_change", tool_names)

        config = self._call_tool("get_project_config", {})
        self.assertEqual(config["result"]["structuredContent"]["project"]["project_id"], "test-project")

        created = self._call_tool(
            "upsert_record",
            {
                "entity_type": "note",
                "payload": {
                    "slug": "mcp-helper",
                    "title": "MCP Helper",
                    "summary": "Helper",
                    "body": "Does helper work",
                    "tags": ["tool"],
                },
                "created_by": "tester",
                "updated_by": "tester",
            },
        )
        created_record = created["result"]["structuredContent"]
        self.assertEqual(created_record["slug"], "mcp-helper")

        search = self._call_tool("search_records", {"q": "helper", "entity_types": ["note"]})
        self.assertEqual(len(search["result"]["structuredContent"]["items"]), 1)

        record = self._call_tool("get_record", {"entity_type": "note", "record_id": "mcp-helper"})
        self.assertEqual(record["result"]["structuredContent"]["title"], "MCP Helper")
        second = self._call_tool(
            "upsert_record",
            {"entity_type": "note", "payload": {"slug": "mcp-linked", "title": "MCP Linked"}, "created_by": "tester"},
        )["result"]["structuredContent"]

        relation = self._call_tool(
            "create_relation",
            {
                "from_entity_type": "note",
                "from_record_id": created_record["record_id"],
                "to_entity_type": "note",
                "to_record_id": second["record_id"],
                "relation_type": "related_to",
                "created_by": "tester",
            },
        )
        self.assertEqual(relation["result"]["structuredContent"]["relation_type"], "related_to")

        related = self._call_tool("get_related", {"entity_type": "note", "record_id": created_record["record_id"], "hops": 1})
        self.assertEqual(len(related["result"]["structuredContent"]["items"]), 1)

        export_path = self.sandbox.root / "bundle.json"
        backup_path = self.sandbox.root / "backup.zip"
        restored_root = self.sandbox.root / "restored_project"

        exported = self._call_tool("export_json", {"output_path": str(export_path)})
        self.assertTrue(export_path.exists())
        self.assertEqual(exported["result"]["structuredContent"]["counts"]["records"], 2)

        imported = self._call_tool("import_json", {"input_path": str(export_path), "replace_existing": True})
        self.assertEqual(imported["result"]["structuredContent"]["counts"]["records"], 2)

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

    def test_delete_record_tool_requires_archived_record_and_purges_it(self) -> None:
        created = self._call_tool(
            "upsert_record",
            {"entity_type": "note", "payload": {"slug": "mcp-delete", "title": "MCP Delete", "body": "delete searchable"}},
        )["result"]["structuredContent"]

        active_delete = self._call_tool("delete_record", {"entity_type": "note", "record_id": "mcp-delete", "deleted_by": "tester"})
        self.assertEqual(active_delete["error"]["code"], -32602)
        self.assertIn("archived", active_delete["error"]["message"])

        self._call_tool("archive_record", {"entity_type": "note", "record_id": "mcp-delete", "archived_by": "tester"})
        default_search = self._call_tool("search_records", {"q": "delete"})
        self.assertEqual(len(default_search["result"]["structuredContent"]["items"]), 0)
        archived_search = self._call_tool("search_records", {"q": "delete", "include_archived": True})
        self.assertEqual(len(archived_search["result"]["structuredContent"]["items"]), 1)

        deleted = self._call_tool("delete_record", {"entity_type": "note", "record_id": "mcp-delete", "deleted_by": "tester"})
        self.assertEqual(deleted["result"]["structuredContent"]["record_id"], created["record_id"])
        self.assertEqual(deleted["result"]["structuredContent"]["status"], "archived")

        missing = self._call_tool("get_record", {"entity_type": "note", "record_id": "mcp-delete", "include_archived": True})
        self.assertEqual(missing["error"]["code"], -32602)
        self.assertEqual(len(self._call_tool("search_records", {"q": "delete", "include_archived": True})["result"]["structuredContent"]["items"]), 0)

    def test_confirm_mode_tools_queue_and_apply_pending_changes(self) -> None:
        self.sandbox.project.write_mode = "confirm"
        created = self._call_tool(
            "upsert_record",
            {
                "entity_type": "note",
                "payload": {"slug": "pending-mcp", "title": "Pending MCP"},
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

        record = self._call_tool("get_record", {"entity_type": "note", "record_id": "pending-mcp"})
        self.assertEqual(record["result"]["structuredContent"]["title"], "Pending MCP")

        pending_relation = self._call_tool(
            "create_relation",
            {
                "from_entity_type": "note",
                "from_record_id": record["result"]["structuredContent"]["record_id"],
                "to_entity_type": "note",
                "to_record_id": record["result"]["structuredContent"]["record_id"],
                "relation_type": "related_to",
                "created_by": "tester",
            },
        )
        rejected = self._call_tool("reject_change", {"pending_change_id": pending_relation["result"]["structuredContent"]["pending_change_id"]})
        self.assertEqual(rejected["result"]["structuredContent"]["status"], "rejected")

    def test_confirm_mode_delete_record_tool_queues_and_applies_pending_change(self) -> None:
        self.sandbox.project.write_mode = "auto"
        self._call_tool(
            "upsert_record",
            {"entity_type": "note", "payload": {"slug": "pending-delete", "title": "Pending Delete"}},
        )
        self._call_tool("archive_record", {"entity_type": "note", "record_id": "pending-delete", "archived_by": "tester"})

        self.sandbox.project.write_mode = "confirm"
        pending = self._call_tool("delete_record", {"entity_type": "note", "record_id": "pending-delete", "deleted_by": "tester"})
        pending_body = pending["result"]["structuredContent"]
        self.assertEqual(pending_body["status"], "pending")
        self.assertEqual(pending_body["operation"], "delete_record")

        confirmed = self._call_tool("confirm_change", {"pending_change_id": pending_body["pending_change_id"], "confirmed_by": "tester"})
        self.assertEqual(confirmed["result"]["structuredContent"]["pending_change"]["status"], "confirmed")
        self.assertEqual(confirmed["result"]["structuredContent"]["applied"]["status"], "archived")

        missing = self._call_tool("get_record", {"entity_type": "note", "record_id": "pending-delete", "include_archived": True})
        self.assertEqual(missing["error"]["code"], -32602)

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

        unexpected_argument = self._rpc(
            "tools/call",
            {"name": "search_records", "arguments": {"q": "startup", "unexpected": True}},
            request_id=12,
        )
        self.assertEqual(unexpected_argument["error"]["code"], -32602)
        self.assertIn("Unexpected fields", unexpected_argument["error"]["message"])

        unsupported_record = self._rpc(
            "tools/call",
            {"name": "get_record", "arguments": {"entity_type": "unknown", "entity_id": "x"}},
            request_id=10,
        )
        self.assertEqual(unsupported_record["error"]["code"], -32602)

        ping = self._rpc("ping", {}, request_id=11)
        self.assertEqual(ping["result"], {})

    def test_search_records_limit_schema_and_validation(self) -> None:
        tools = self._rpc("tools/list", {}, request_id=20)["result"]["tools"]
        search_schema = next(tool["inputSchema"] for tool in tools if tool["name"] == "search_records")
        limit_schema = search_schema["properties"]["limit"]
        self.assertEqual(limit_schema["minimum"], 0)
        self.assertEqual(limit_schema["maximum"], 1000)

        zero_limit = self._call_tool("search_records", {"limit": 0})
        self.assertEqual(zero_limit["result"]["structuredContent"]["items"], [])

        negative_limit = self._call_tool("search_records", {"limit": -1})
        self.assertEqual(negative_limit["error"]["code"], -32602)

        huge_limit = self._call_tool("search_records", {"limit": 1001})
        self.assertEqual(huge_limit["error"]["code"], -32602)

    def test_malformed_content_length_returns_json_rpc_error(self) -> None:
        for content_length in (b"bad", b"-1"):
            with self.subTest(content_length=content_length):
                status_line, body = self._raw_http(
                    b"POST /mcp HTTP/1.1\r\n"
                    b"Host: 127.0.0.1\r\n"
                    b"Content-Type: application/json\r\n"
                    b"Content-Length: " + content_length + b"\r\n"
                    b"Connection: close\r\n"
                    b"\r\n"
                )
                self.assertIn("200", status_line)
                response = json.loads(body.decode("utf-8"))
                self.assertEqual(response["error"]["code"], -32600)
                self.assertIn("Content-Length", response["error"]["message"])

    def test_additional_tool_handlers(self) -> None:
        created_structure = self._call_tool(
            "upsert_record",
            {
                "entity_type": "note",
                "payload": {"slug": "struct-extra", "title": "Extra Structure", "summary": "Summary"},
                "created_by": "tester",
                "updated_by": "tester",
            },
        )
        created_hypothesis = self._call_tool(
            "upsert_record",
            {
                "entity_type": "note",
                "payload": {"slug": "gh-extra", "title": "Title", "body": "Statement"},
                "created_by": "tester",
                "updated_by": "tester",
            },
        )
        added_evidence = self._call_tool(
            "add_evidence",
            {
                "evidence_id": "e_extra",
                "entity_type": "note",
                "record_id": created_structure["result"]["structuredContent"]["record_id"],
                "evidence_type": "block",
                "description": "Description",
                "created_by": "tester",
            },
        )
        all_pending = self._call_tool("list_pending_changes", {"status": "all"})
        self.assertEqual(created_structure["result"]["structuredContent"]["slug"], "struct-extra")
        self.assertEqual(created_hypothesis["result"]["structuredContent"]["slug"], "gh-extra")
        self.assertEqual(added_evidence["result"]["structuredContent"]["description"], "Description")
        self.assertEqual(all_pending["result"]["structuredContent"]["items"], [])

    def test_serve_project_mcp_api_constructs_server(self) -> None:
        fake_server = mock.Mock()
        with mock.patch.dict(os.environ, {"MCP_MEMORY_MCP_TRANSPORT": "legacy"}):
            with mock.patch("mcp_memory.mcp.server.ThreadingHTTPServer", return_value=fake_server) as server_cls:
                serve_project_mcp_api(self.sandbox.project, self.sandbox.registry, "127.0.0.1", 9998)
        server_cls.assert_called_once()
        fake_server.serve_forever.assert_called_once()

    def test_serve_project_mcp_api_uses_sdk_transport_by_default(self) -> None:
        with mock.patch.dict(os.environ, {"MCP_MEMORY_MCP_TRANSPORT": "sdk"}):
            with mock.patch("mcp_memory.mcp.sdk_server.serve_project_mcp_sdk_api") as serve_sdk:
                serve_project_mcp_api(self.sandbox.project, self.sandbox.registry, "127.0.0.1", 9998)
        serve_sdk.assert_called_once_with(self.sandbox.project, self.sandbox.registry, "127.0.0.1", 9998, log_level="INFO")

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

    def _raw_http(self, payload: bytes) -> tuple[str, bytes]:
        with socket.create_connection(("127.0.0.1", self.server.server_port), timeout=5) as sock:
            sock.sendall(payload)
            chunks: list[bytes] = []
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                chunks.append(chunk)
        raw_response = b"".join(chunks)
        header_bytes, _, body = raw_response.partition(b"\r\n\r\n")
        status_line = header_bytes.splitlines()[0].decode("ascii")
        return status_line, body


if __name__ == "__main__":
    unittest.main()
