from __future__ import annotations

import json
import threading
import unittest
from http.server import HTTPServer
from pathlib import Path
from urllib import error, parse, request
from unittest import mock

from tests.support import ProjectSandbox

from mcp_memory.domain import HypothesisStatus
from mcp_memory.api.server import (
    build_handler,
    evidence_write_from_payload,
    function_write_from_payload,
    global_hypothesis_write_from_payload,
    serialize,
    serve_project_http_api,
    structure_write_from_payload,
)
from mcp_memory.logging_utils import configure_logging
from mcp_memory.services import EvidenceService, FunctionService, GlobalHypothesisService, RelationService, RelationWrite, StructureService


class ApiServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sandbox = ProjectSandbox()
        self.sandbox.project.write_mode = "auto"
        self.log_path = self.sandbox.project.logs_dir / "http-api.log"
        configure_logging("api", "INFO", self.log_path)
        configure_logging("ui", "INFO", self.log_path)
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
        self.server = HTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.sandbox.cleanup()

    def test_payload_builders(self) -> None:
        function = function_write_from_payload(
            "test-project",
            {
                "binary_id": "bin-main",
                "function_id": "fn_payload",
                "address": "0x401100",
                "raw_name": "sub_401100",
                "current_name": "payload_fn",
                "summary": "Summary",
                "behavior_description": "Behavior",
                "confidence": 0.5,
                "observed_facts": [{"fact": "fact", "source_origin": "unit"}],
                "hypotheses": [{"statement": "maybe", "status": "confirmed", "confidence": 0.9}],
            },
        )
        structure = structure_write_from_payload(
            "test-project",
            {
                "binary_id": "bin-main",
                "structure_id": "struct_payload",
                "raw_name": "raw",
                "current_name": "current",
                "summary": "Summary",
                "fields": [{"name": "field", "offset": "0x0", "data_type": "int"}],
                "observed_facts": [{"fact": "used by parser"}],
                "hypotheses": [{"statement": "shared layout"}],
            },
        )
        hypothesis = global_hypothesis_write_from_payload(
            "test-project",
            {
                "hypothesis_id": "gh_payload",
                "title": "Title",
                "statement": "Statement",
                "status": "confirmed",
                "confidence": 0.75,
                "binary_id": "bin-main",
                "observed_facts": [{"fact": "seen in xrefs"}],
            },
        )
        evidence = evidence_write_from_payload(
            "test-project",
            {
                "evidence_id": "e_payload",
                "entity_type": "function",
                "entity_id": "fn_main",
                "evidence_type": "block",
                "description": "Description",
                "address_start": "0x401000",
                "address_end": "0x401010",
                "xref": "caller->fn_main",
                "block_ref": "block_0",
                "excerpt": "mov eax, ebx",
                "attachment_path": "attachments/e.txt",
                "media_type": "text/plain",
                "size_bytes": 42,
            },
        )
        self.assertEqual(function.function_id, "fn_payload")
        self.assertEqual(function.confidence, 0.5)
        self.assertEqual(function.hypotheses[0].status, HypothesisStatus.CONFIRMED)
        self.assertEqual(structure.fields[0].name, "field")
        self.assertEqual(structure.observed_facts[0].fact, "used by parser")
        self.assertEqual(hypothesis.hypothesis_id, "gh_payload")
        self.assertEqual(hypothesis.status, HypothesisStatus.CONFIRMED)
        self.assertEqual(evidence.entity_id, "fn_main")
        self.assertEqual(evidence.attachment_path, "attachments/e.txt")

    def test_serialize_handles_common_shapes(self) -> None:
        payload = serialize({"path": self.sandbox.project.project_root, "items": [1, 2]})
        self.assertIn("path", payload)
        self.assertEqual(payload["items"], [1, 2])

    def test_get_endpoints_and_not_found(self) -> None:
        self.assertEqual(self._get_json("/health")["status"], "ok")
        self.assertEqual(self._get_json("/project/config")["project"]["project_id"], "test-project")
        self.assertEqual(len(self._get_json("/functions?binary_id=bin-main")["items"]), 1)
        self.assertEqual(self._get_json("/functions/bin-main/fn_main")["function_id"], "fn_main")
        self.assertEqual(self._get_status("/functions/bin-main"), 404)
        self.assertEqual(self._get_status("/functions/bin-main/missing"), 404)
        self.assertEqual(len(self._get_json("/structures?binary_id=bin-main")["items"]), 0)
        self.assertEqual(self._get_status("/structures/missing-structure"), 404)
        self.assertEqual(len(self._get_json("/global-hypotheses")["items"]), 0)
        self.assertEqual(self._get_status("/global-hypotheses/missing-gh"), 404)
        self.assertEqual(len(self._get_json("/evidence?entity_type=function&entity_id=fn_main")["items"]), 0)
        self.assertEqual(self._get_status("/functions"), 400)
        self.assertEqual(self._get_status("/evidence?entity_type=function"), 400)
        self.assertEqual(self._get_status("/relations?entity_type=function&entity_id=fn_main&direction=sideways"), 400)
        self.assertEqual(self._get_status("/related?entity_type=function&entity_id=fn_main&hops=3"), 400)
        self.assertEqual(self._get_status("/unknown"), 404)

    def test_ui_get_endpoints(self) -> None:
        with self.sandbox.open_database() as database:
            StructureService(database).upsert_structure(
                structure_write_from_payload(
                    "test-project",
                    {
                        "binary_id": "bin-main",
                        "structure_id": "struct_ctx",
                        "raw_name": "ctx_t",
                        "current_name": "ctx_t",
                        "summary": "Context structure",
                        "fields": [{"name": "mode", "offset": "0x0", "data_type": "uint32_t"}],
                        "created_by": "tester",
                        "updated_by": "tester",
                    },
                )
            )
            GlobalHypothesisService(database).upsert_hypothesis(
                global_hypothesis_write_from_payload(
                    "test-project",
                    {
                        "hypothesis_id": "gh_ui",
                        "title": "UI Hypothesis",
                        "statement": "Interesting behavior.",
                        "created_by": "tester",
                        "updated_by": "tester",
                    },
                )
            )
            EvidenceService(database).create_evidence(
                evidence_write_from_payload(
                    "test-project",
                    {
                        "evidence_id": "e_ui",
                        "entity_type": "function",
                        "entity_id": "fn_main",
                        "evidence_type": "block",
                        "description": "Block evidence",
                        "created_by": "tester",
                    },
                )
            )
            RelationService(database).create_relation(
                RelationWrite(
                    project_id="test-project",
                    from_entity_type="function",
                    from_entity_id="fn_main",
                    to_entity_type="structure",
                    to_entity_id="struct_ctx",
                    relation_type="uses_structure",
                    created_by="tester",
                )
            )

        dashboard_html = self._get_text("/ui/")
        dashboard_ru_html = self._get_text("/ui/?lang=ru")
        new_function_form_html = self._get_text("/ui/functions/new")
        search_html = self._get_text("/ui/search?q=main_handler&entity_type=function")
        search_ru_html = self._get_text("/ui/search?q=main_handler&entity_type=function&lang=ru")
        function_html = self._get_text("/ui/functions/bin-main/fn_main")
        function_history_html = self._get_text("/ui/functions/bin-main/fn_main/history")
        function_edit_html = self._get_text("/ui/functions/bin-main/fn_main/edit")
        new_structure_form_html = self._get_text("/ui/structures/new")
        structure_html = self._get_text("/ui/structures/struct_ctx")
        structure_history_html = self._get_text("/ui/structures/struct_ctx/history")
        structure_edit_html = self._get_text("/ui/structures/struct_ctx/edit")
        new_hypothesis_form_html = self._get_text("/ui/global-hypotheses/new")
        hypothesis_html = self._get_text("/ui/global-hypotheses/gh_ui")
        hypothesis_history_html = self._get_text("/ui/global-hypotheses/gh_ui/history")
        hypothesis_edit_html = self._get_text("/ui/global-hypotheses/gh_ui/edit")
        settings_html = self._get_text("/ui/settings")
        pending_html = self._get_text("/ui/pending")
        audit_html = self._get_text("/ui/audit")
        css = self._get_text("/ui/assets/app.css")

        self.assertIn("Workspace Dashboard", dashboard_html)
        self.assertIn("Панель workspace", dashboard_ru_html)
        self.assertIn("Jump Back In", dashboard_html)
        self.assertIn("http://127.0.0.1:19876/mcp", dashboard_html)
        self.assertIn(">Settings<", dashboard_html)
        self.assertIn("New Function", new_function_form_html)
        self.assertIn("Save Function", new_function_form_html)
        self.assertIn("Search Workspace", search_html)
        self.assertIn("Поиск по workspace", search_ru_html)
        self.assertIn("main_handler", search_html)
        self.assertIn("Edit Function", function_edit_html)
        self.assertIn("View Version History", function_html)
        self.assertIn("Edit Record", function_html)
        self.assertIn("Observed Facts", function_html)
        self.assertIn("uses_structure", function_html)
        self.assertIn("Function Version History", function_history_html)
        self.assertIn("Version 1", function_history_html)
        self.assertIn("New Structure", new_structure_form_html)
        self.assertIn("Save Structure", new_structure_form_html)
        self.assertIn("Fields", structure_html)
        self.assertIn("Edit Structure", structure_edit_html)
        self.assertIn("Structure Version History", structure_history_html)
        self.assertIn("New Global Hypothesis", new_hypothesis_form_html)
        self.assertIn("UI Hypothesis", hypothesis_html)
        self.assertIn("Edit Global Hypothesis", hypothesis_edit_html)
        self.assertIn("Global Hypothesis Version History", hypothesis_history_html)
        self.assertIn("Project Settings", settings_html)
        self.assertIn("Save Settings", settings_html)
        self.assertIn("http://127.0.0.1:19876/mcp", settings_html)
        self.assertIn("Nothing is waiting right now", pending_html)
        self.assertIn("Audit Trail", audit_html)
        self.assertIn("upsert", audit_html)
        self.assertIn("--paper", css)

    def test_ui_not_found_routes_return_404(self) -> None:
        self.assertEqual(self._get_status("/ui/unknown"), 404)
        self.assertEqual(self._get_status("/ui/functions/bin-main/missing/edit"), 404)
        self.assertEqual(self._get_status("/ui/functions/bin-main/missing"), 404)
        self.assertEqual(self._get_status("/ui/functions/bin-main/missing/history"), 404)
        self.assertEqual(self._get_status("/ui/structures/missing/edit"), 404)
        self.assertEqual(self._get_status("/ui/structures/missing"), 404)
        self.assertEqual(self._get_status("/ui/structures/missing/history"), 404)
        self.assertEqual(self._get_status("/ui/global-hypotheses/missing/edit"), 404)
        self.assertEqual(self._get_status("/ui/global-hypotheses/missing"), 404)
        self.assertEqual(self._get_status("/ui/global-hypotheses/missing/history"), 404)

    def test_ui_settings_submit_updates_project_and_preserves_validation_errors(self) -> None:
        saved_html = self._post_form_text(
            "/ui/settings?lang=en",
            {
                "display_name": "Renamed Project",
                "write_mode": "auto",
                "http_host": "127.0.0.2",
                "http_port": "28765",
                "mcp_host": "127.0.0.3",
                "mcp_port": "29876",
            },
        )
        self.assertIn("Network settings were saved. Restart the project from Home UI to apply them.", saved_html)
        self.assertIn("127.0.0.3:29876/mcp", saved_html)
        updated = self.sandbox.registry.get_project("test-project")
        self.assertEqual(updated.display_name, "Renamed Project")
        self.assertEqual(updated.write_mode, "auto")
        self.assertEqual(updated.http_host, "127.0.0.2")
        self.assertEqual(updated.http_port, 28765)
        self.assertEqual(updated.mcp_host, "127.0.0.3")
        self.assertEqual(updated.mcp_port, 29876)

        invalid_html = self._post_form_text(
            "/ui/settings?lang=ru",
            {
                "display_name": "Renamed Project",
                "write_mode": "auto",
                "http_host": "127.0.0.2",
                "http_port": "broken",
                "mcp_host": "127.0.0.3",
                "mcp_port": "29876",
            },
        )
        self.assertIn('action="/ui/settings?lang=ru"', invalid_html)
        self.assertIn("broken", invalid_html)

    def test_post_entity_endpoints(self) -> None:
        created_function = self._post_json(
            "/functions",
            {
                "binary_id": "bin-main",
                "function_id": "fn_helper",
                "address": "0x401100",
                "raw_name": "sub_401100",
                "current_name": "helper",
                "summary": "Summary",
                "behavior_description": "Behavior",
                "created_by": "tester",
                "updated_by": "tester",
            },
        )
        created_structure = self._post_json(
            "/structures",
            {
                "binary_id": "bin-main",
                "structure_id": "struct_ctx",
                "raw_name": "ctx_t",
                "current_name": "ctx_t",
                "summary": "Summary",
                "created_by": "tester",
                "updated_by": "tester",
            },
        )
        created_hypothesis = self._post_json(
            "/global-hypotheses",
            {
                "hypothesis_id": "gh1",
                "title": "Title",
                "statement": "Statement",
                "created_by": "tester",
                "updated_by": "tester",
            },
        )
        created_evidence = self._post_json(
            "/evidence",
            {
                "evidence_id": "e1",
                "entity_type": "function",
                "entity_id": "fn_main",
                "evidence_type": "block",
                "description": "Description",
                "created_by": "tester",
            },
        )
        created_relation = self._post_json(
            "/relations",
            {
                "from_entity_type": "function",
                "from_entity_id": "fn_main",
                "to_entity_type": "structure",
                "to_entity_id": "struct_ctx",
                "relation_type": "uses_structure",
                "created_by": "tester",
            },
        )
        search_result = self._post_json(
            "/search",
            {"q": "helper", "limit": 5, "entity_types": ["function"]},
        )
        self.assertEqual(created_function["function_id"], "fn_helper")
        self.assertEqual(created_structure["structure_id"], "struct_ctx")
        self.assertEqual(created_hypothesis["hypothesis_id"], "gh1")
        self.assertEqual(created_evidence["evidence_id"], "e1")
        self.assertEqual(created_relation["relation_type"], "uses_structure")
        self.assertGreaterEqual(len(search_result["items"]), 1)
        self.assertEqual(len(self._get_json("/relations?entity_type=function&entity_id=fn_main")["items"]), 1)
        self.assertEqual(len(self._get_json("/related?entity_type=function&entity_id=fn_main&hops=1")["items"]), 1)
        self.assertEqual(self._get_json("/structures/struct_ctx")["structure_id"], "struct_ctx")
        self.assertEqual(self._get_json("/global-hypotheses/gh1")["hypothesis_id"], "gh1")
        self.assertEqual(len(self._get_json("/evidence?entity_type=function&entity_id=fn_main")["items"]), 1)

    def test_confirm_mode_queues_and_applies_pending_changes(self) -> None:
        self.sandbox.project.write_mode = "confirm"
        pending = self._post_json(
            "/functions",
            {
                "binary_id": "bin-main",
                "function_id": "fn_pending",
                "address": "0x401250",
                "raw_name": "sub_401250",
                "current_name": "pending_http",
                "summary": "Summary",
                "behavior_description": "Behavior",
                "created_by": "tester",
                "updated_by": "tester",
            },
        )
        self.assertEqual(pending["status"], "pending")
        self.assertEqual(len(self._get_json("/pending-changes")["items"]), 1)
        confirmed = self._post_json(
            f"/pending-changes/{pending['pending_change_id']}/confirm",
            {"confirmed_by": "tester"},
        )
        self.assertEqual(confirmed["pending_change"]["status"], "confirmed")
        self.assertEqual(self._get_json("/functions/bin-main/fn_pending")["function_id"], "fn_pending")

        pending_structure = self._post_json(
            "/structures",
            {
                "binary_id": "bin-main",
                "structure_id": "struct_pending",
                "raw_name": "pending_t",
                "current_name": "pending_t",
                "summary": "Summary",
                "created_by": "tester",
                "updated_by": "tester",
            },
        )
        rejected = self._post_json(
            f"/pending-changes/{pending_structure['pending_change_id']}/reject",
            {"rejected_by": "tester"},
        )
        self.assertEqual(rejected["status"], "rejected")
        self.assertEqual(len(self._get_json("/pending-changes?status=all")["items"]), 2)

    def test_post_unknown_route_returns_not_found(self) -> None:
        with self.assertRaises(error.HTTPError) as ctx:
            self._post_json("/unknown-post", {})
        self.assertEqual(ctx.exception.code, 404)

    def test_export_import_backup_and_restore_endpoints(self) -> None:
        export_path = self.sandbox.root / "bundle.json"
        backup_path = self.sandbox.root / "backup.zip"
        restored_root = self.sandbox.root / "restored_project"

        exported = self._post_json("/export/json", {"output_path": str(export_path)})
        self.assertEqual(exported["counts"]["functions"], 1)
        self.assertTrue(export_path.exists())

        imported = self._post_json("/import/json", {"input_path": str(export_path), "replace_existing": True})
        self.assertEqual(imported["counts"]["functions"], 1)

        backed_up = self._post_json("/backup", {"output_path": str(backup_path)})
        self.assertTrue(Path(backed_up["output_path"]).exists())

        restored = self._post_json(
            "/restore",
            {
                "input_path": str(backup_path),
                "project_root": str(restored_root),
                "project_id": "restored-project",
                "display_name": "Restored Project",
                "http_port": 20000,
                "mcp_port": 20001,
            },
        )
        self.assertEqual(restored["project_id"], "restored-project")
        self.assertTrue((restored_root / "project.db").exists())

    def test_invalid_json_and_validation_errors(self) -> None:
        req = request.Request(
            self.base_url + "/functions",
            data=b"{bad json",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(error.HTTPError) as ctx:
            request.urlopen(req)
        self.assertEqual(ctx.exception.code, 400)

        with self.assertRaises(error.HTTPError) as ctx:
            self._post_json("/functions", {"binary_id": "bin-main"})
        self.assertEqual(ctx.exception.code, 400)

        with self.assertRaises(error.HTTPError) as ctx:
            self._post_json("/relations", {"from_entity_type": "function"})
        self.assertEqual(ctx.exception.code, 400)

        with self.assertRaises(error.HTTPError) as ctx:
            self._post_json("/search", {"limit": "bad"})
        self.assertEqual(ctx.exception.code, 400)

        with self.assertRaises(error.HTTPError) as ctx:
            self._post_json("/pending-changes//confirm", {})
        self.assertEqual(ctx.exception.code, 400)

    def test_confirm_mode_queues_global_hypothesis_and_evidence(self) -> None:
        self.sandbox.project.write_mode = "confirm"
        hypothesis_pending = self._post_json(
            "/global-hypotheses",
            {
                "hypothesis_id": "gh_pending",
                "title": "Title",
                "statement": "Statement",
                "created_by": "tester",
                "updated_by": "tester",
            },
        )
        evidence_pending = self._post_json(
            "/evidence",
            {
                "evidence_id": "e_pending",
                "entity_type": "function",
                "entity_id": "fn_main",
                "evidence_type": "block",
                "description": "Description",
                "created_by": "tester",
            },
        )
        self.assertEqual(hypothesis_pending["status"], "pending")
        self.assertEqual(evidence_pending["status"], "pending")

    def test_ui_pending_confirm_and_reject_flow(self) -> None:
        self.sandbox.project.write_mode = "confirm"
        pending = self._post_json(
            "/functions",
            {
                "binary_id": "bin-main",
                "function_id": "fn_html_pending",
                "address": "0x401280",
                "raw_name": "sub_401280",
                "current_name": "html_pending",
                "summary": "Summary",
                "behavior_description": "Behavior",
                "created_by": "tester",
                "updated_by": "tester",
            },
        )
        confirmed_html = self._post_form_text(
            f"/ui/pending/{pending['pending_change_id']}/confirm?lang=ru",
            {"confirmed_by": "tester"},
        )
        self.assertIn("Ожидающее изменение подтверждено и применено.", confirmed_html)
        self.assertEqual(self._get_json("/functions/bin-main/fn_html_pending")["function_id"], "fn_html_pending")

        pending_reject = self._post_json(
            "/structures",
            {
                "binary_id": "bin-main",
                "structure_id": "struct_html_pending",
                "raw_name": "pending_t",
                "current_name": "pending_t",
                "summary": "Summary",
                "created_by": "tester",
                "updated_by": "tester",
            },
        )
        rejected_html = self._post_form_text(
            f"/ui/pending/{pending_reject['pending_change_id']}/reject?lang=ru",
            {"rejected_by": "tester"},
        )
        self.assertIn("Ожидающее изменение отклонено.", rejected_html)

    def test_ui_function_form_create_and_edit_in_auto_mode(self) -> None:
        created_html = self._post_form_text(
            "/ui/functions/new",
            {
                "binary_id": "bin-main",
                "function_id": "fn_form",
                "address": "0x401555",
                "raw_name": "sub_401555",
                "current_name": "form_fn",
                "summary": "Summary",
                "behavior_description": "Behavior",
                "tags": "tag-one\ntag-two",
                "used_apis": "CreateFileA",
                "strings": "hello",
                "constants": "0x20",
                "observed_facts": "created from form",
                "confidence": "0.7",
            },
        )
        updated_html = self._post_form_text(
            "/ui/functions/bin-main/fn_form/edit",
            {
                "binary_id": "bin-main",
                "function_id": "fn_form",
                "address": "0x401556",
                "raw_name": "sub_401555",
                "current_name": "form_fn_updated",
                "summary": "Updated Summary",
                "behavior_description": "Updated Behavior",
                "tags": "tag-three",
                "used_apis": "",
                "strings": "",
                "constants": "",
                "observed_facts": "",
                "confidence": "",
            },
        )
        self.assertIn("form_fn", created_html)
        self.assertIn("form_fn_updated", updated_html)
        self.assertEqual(self._get_json("/functions/bin-main/fn_form")["current_name"], "form_fn_updated")

    def test_ui_global_hypothesis_form_create_and_edit_in_auto_mode(self) -> None:
        created_html = self._post_form_text(
            "/ui/global-hypotheses/new",
            {
                "hypothesis_id": "gh_form",
                "title": "Form Hypothesis",
                "statement": "Created from HTML form.",
                "status": "probable",
                "binary_id": "bin-main",
                "confidence": "0.6",
                "tags": "parser",
                "observed_facts": "fact from form",
            },
        )
        updated_html = self._post_form_text(
            "/ui/global-hypotheses/gh_form/edit",
            {
                "hypothesis_id": "gh_form",
                "title": "Updated Hypothesis",
                "statement": "Updated through HTML form.",
                "status": "confirmed",
                "binary_id": "",
                "confidence": "",
                "tags": "",
                "observed_facts": "",
            },
        )
        self.assertIn("Form Hypothesis", created_html)
        self.assertIn("Updated Hypothesis", updated_html)
        self.assertEqual(self._get_json("/global-hypotheses/gh_form")["title"], "Updated Hypothesis")

    def test_ui_structure_form_create_and_edit_in_auto_mode(self) -> None:
        created_html = self._post_form_text(
            "/ui/structures/new",
            {
                "binary_id": "bin-main",
                "structure_id": "struct_form",
                "raw_name": "form_t",
                "current_name": "form_t",
                "summary": "Created from HTML form.",
                "fields": "mode|0x0|uint32_t|4|mode flag\nbuffer|0x8|char *|8|buffer pointer",
                "tags": "parser",
                "observed_facts": "seen in handler",
            },
        )
        updated_html = self._post_form_text(
            "/ui/structures/struct_form/edit",
            {
                "binary_id": "bin-main",
                "structure_id": "struct_form",
                "raw_name": "form_t",
                "current_name": "form_t_updated",
                "summary": "Updated from HTML form.",
                "fields": "mode|0x0|uint32_t|4|updated flag",
                "tags": "",
                "observed_facts": "",
            },
        )
        self.assertIn("form_t", created_html)
        self.assertIn("form_t_updated", updated_html)
        self.assertEqual(self._get_json("/structures/struct_form")["current_name"], "form_t_updated")

    def test_ui_form_validation_and_confirm_queue(self) -> None:
        invalid_html = self._post_form_text(
            "/ui/functions/new",
            {
                "binary_id": "bin-main",
                "function_id": "",
                "address": "0x401777",
                "raw_name": "sub_401777",
                "current_name": "bad_form",
                "summary": "Summary",
                "behavior_description": "Behavior",
                "tags": "",
                "used_apis": "",
                "strings": "",
                "constants": "",
                "observed_facts": "",
                "confidence": "",
            },
        )
        self.assertIn("must not be empty", invalid_html)

        invalid_structure_html = self._post_form_text(
            "/ui/structures/new",
            {
                "binary_id": "bin-main",
                "structure_id": "",
                "raw_name": "bad_t",
                "current_name": "bad_t",
                "summary": "Summary",
                "fields": "",
                "tags": "",
                "observed_facts": "",
            },
        )
        self.assertIn("must not be empty", invalid_structure_html)

        self.sandbox.project.write_mode = "confirm"
        queued_structure_html = self._post_form_text(
            "/ui/structures/new",
            {
                "binary_id": "bin-main",
                "structure_id": "struct_pending_form",
                "raw_name": "pending_t",
                "current_name": "pending_t",
                "summary": "Queued structure.",
                "fields": "mode|0x0|uint32_t|4|mode",
                "tags": "",
                "observed_facts": "",
            },
        )
        self.assertIn("Change queued for confirmation.", queued_structure_html)

        queued_html = self._post_form_text(
            "/ui/global-hypotheses/new",
            {
                "hypothesis_id": "gh_pending_form",
                "title": "Pending Form Hypothesis",
                "statement": "Will be queued.",
                "status": "new",
                "binary_id": "",
                "confidence": "",
                "tags": "",
                "observed_facts": "",
            },
        )
        self.assertIn("Change queued for confirmation.", queued_html)
        self.assertEqual(len(self._get_json("/pending-changes")["items"]), 2)

    def test_ui_audit_filter_form(self) -> None:
        audit_html = self._get_text("/ui/audit?entity_type=function&entity_id=fn_main")
        self.assertIn("Filter Audit", audit_html)
        self.assertIn("fn_main", audit_html)

    def test_serve_project_http_api_constructs_server(self) -> None:
        fake_server = mock.Mock()
        with mock.patch("mcp_memory.api.server.HTTPServer", return_value=fake_server) as server_cls:
            serve_project_http_api(self.sandbox.project, self.sandbox.registry, "127.0.0.1", 9999)
        server_cls.assert_called_once()
        fake_server.serve_forever.assert_called_once()

    def test_runtime_logs_are_written_for_http_and_ui_activity(self) -> None:
        self._get_json("/health")
        self._get_text("/ui/")
        self._post_json(
            "/functions",
            {
                "binary_id": "bin-main",
                "function_id": "fn_logged",
                "address": "0x401190",
                "raw_name": "sub_401190",
                "current_name": "logged_fn",
                "summary": "Summary",
                "behavior_description": "Behavior",
                "created_by": "tester",
                "updated_by": "tester",
            },
        )
        contents = self.log_path.read_text(encoding="utf-8")
        self.assertIn("request_complete", contents)
        self.assertIn("function_upserted", contents)

    def _get_json(self, path: str) -> dict:
        with request.urlopen(self.base_url + path) as response:
            return json.loads(response.read().decode("utf-8"))

    def _post_json(self, path: str, payload: dict) -> dict:
        req = request.Request(
            self.base_url + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        with request.urlopen(req) as response:
            return json.loads(response.read().decode("utf-8"))

    def _get_text(self, path: str) -> str:
        with request.urlopen(self.base_url + path) as response:
            return response.read().decode("utf-8")

    def _post_form_text(self, path: str, payload: dict[str, str]) -> str:
        req = request.Request(
            self.base_url + path,
            data=parse.urlencode(payload).encode("utf-8"),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with request.urlopen(req) as response:
                return response.read().decode("utf-8")
        except error.HTTPError as exc:
            return exc.read().decode("utf-8")

    def _get_status(self, path: str) -> int:
        try:
            self._get_text(path)
        except error.HTTPError as exc:
            return exc.code
        return 200


if __name__ == "__main__":
    unittest.main()
