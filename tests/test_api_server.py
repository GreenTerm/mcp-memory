from __future__ import annotations

import json
import socket
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
from mcp_memory.services import (
    EvidenceService,
    FunctionService,
    GenericRelationWrite,
    GenericRelationService,
    GlobalHypothesisService,
    RecordService,
    RecordWrite,
    RelationService,
    RelationWrite,
    StructureService,
)


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

    def test_generic_http_record_routes(self) -> None:
        schema = self._get_json("/schema")
        self.assertEqual(schema["entity_types"][0]["name"], "note")
        self.assertEqual(self._get_json("/entity-types")["items"][0]["name"], "note")

        created = self._post_json(
            "/records/note",
            {
                "payload": {
                    "slug": "api-note",
                    "title": "API Note",
                    "summary": "Created through generic API",
                    "body": "generic api searchable text",
                    "tags": ["api"],
                },
                "created_by": "tester",
                "updated_by": "tester",
            },
        )
        self.assertEqual(created["slug"], "api-note")
        self.assertEqual(self._get_json("/records?entity_type=note")["items"][0]["slug"], "api-note")
        self.assertEqual(self._get_json("/records/note/api-note")["title"], "API Note")
        self.assertEqual(len(self._post_json("/search", {"q": "searchable", "entity_types": ["note"]})["items"]), 1)

        archived = self._post_json("/records/note/api-note/archive", {"archived_by": "tester"})
        self.assertEqual(archived["status"], "archived")
        self.assertEqual(self._get_status("/records/note/api-note"), 404)

    def test_generic_http_put_and_bad_record_routes(self) -> None:
        schema = self._get_json("/schema")
        updated_schema = self._put_json("/schema", schema)
        self.assertEqual(updated_schema["status"], "updated")

        created = self._post_json(
            "/records/note",
            {"payload": {"slug": "put-note", "title": "Before PUT"}, "created_by": "tester"},
        )
        updated = self._put_json(
            "/records/note/put-note",
            {"payload": {"slug": "put-note", "title": "After PUT", "summary": "Updated"}, "updated_by": "tester"},
        )
        self.assertEqual(updated["record_id"], created["record_id"])
        self.assertEqual(updated["title"], "After PUT")

        created_by_put = self._put_json(
            "/records/note/explicit-put-id",
            {"payload": {"slug": "put-created", "title": "Created by PUT"}, "created_by": "tester"},
        )
        self.assertEqual(created_by_put["record_id"], "explicit-put-id")
        self.assertEqual(created_by_put["slug"], "put-created")

        self.assertEqual(self._get_status("/records/note/too/many"), 404)
        self.assertEqual(self._post_status("/records/note/id/extra/archive", {}), 404)
        self.assertEqual(self._post_status("/records/note/id", {"payload": {"title": "Bad route"}}), 404)
        self.assertEqual(self._post_status("/records/note", {"payload": []}), 400)
        self.assertEqual(self._put_status("/records/note/put-note", {"payload": []}), 400)
        self.assertEqual(self._put_status("/records/note/put-note/extra", {"payload": {"title": "Bad"}}), 404)
        self.assertEqual(self._put_status("/missing", {}), 404)

        invalid_req = request.Request(
            self.base_url + "/schema",
            data=b"{bad json",
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="PUT",
        )
        with self.assertRaises(error.HTTPError) as ctx:
            request.urlopen(invalid_req)
        self.assertEqual(ctx.exception.code, 400)

    def test_generic_http_relation_evidence_and_pending_routes(self) -> None:
        first = self._post_json("/records/note", {"payload": {"slug": "first", "title": "First"}, "created_by": "tester"})
        second = self._post_json("/records/note", {"payload": {"slug": "second", "title": "Second"}, "created_by": "tester"})
        relation = self._post_json(
            "/relations",
            {
                "from_entity_type": "note",
                "from_record_id": first["record_id"],
                "to_entity_type": "note",
                "to_record_id": second["record_id"],
                "relation_type": "related_to",
                "created_by": "tester",
            },
        )
        self.assertEqual(relation["relation_type"], "related_to")
        self.assertEqual(len(self._get_json(f"/related?entity_type=note&record_id={first['record_id']}")["items"]), 1)

        evidence = self._post_json(
            "/evidence",
            {
                "entity_type": "note",
                "record_id": first["record_id"],
                "evidence_type": "excerpt",
                "description": "Evidence",
                "excerpt": "text",
                "created_by": "tester",
            },
        )
        self.assertEqual(evidence["description"], "Evidence")
        self.assertEqual(len(self._get_json(f"/evidence?entity_type=note&record_id={first['record_id']}")["items"]), 1)

        self.sandbox.project.write_mode = "confirm"
        pending = self._post_json("/records/note", {"payload": {"slug": "queued-api", "title": "Queued API"}, "created_by": "tester"})
        self.assertEqual(pending["status"], "pending")
        self.assertEqual(len(self._get_json("/pending-changes")["items"]), 1)
        confirmed = self._post_json(f"/pending-changes/{pending['pending_change_id']}/confirm", {"confirmed_by": "tester"})
        self.assertEqual(confirmed["pending_change"]["status"], "confirmed")
        self.assertEqual(confirmed["applied"]["slug"], "queued-api")

    def test_generic_http_export_import_round_trip(self) -> None:
        self._post_json("/records/note", {"payload": {"slug": "exported", "title": "Exported Record"}, "created_by": "tester"})
        export_path = self.sandbox.root / "generic-export.json"
        exported = self._post_json("/export/json", {"output_path": str(export_path)})
        self.assertEqual(exported["counts"]["records"], 1)
        self.assertTrue(export_path.exists())

        self._post_json("/records/note/exported/archive", {"archived_by": "tester"})
        self.assertEqual(self._get_status("/records/note/exported"), 404)

        imported = self._post_json("/import/json", {"input_path": str(export_path), "replace_existing": True})
        self.assertEqual(imported["counts"]["records"], 1)
        self.assertEqual(self._get_json("/records/note/exported")["title"], "Exported Record")

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
        functions_list_html = self._get_text("/ui/functions?q=main&binary_id=bin-main&sort=updated")
        new_function_form_html = self._get_text("/ui/functions/new")
        search_blank_html = self._get_text("/ui/search")
        search_html = self._get_text("/ui/search?q=main_handler&entity_type=function")
        search_ru_html = self._get_text("/ui/search?q=main_handler&entity_type=function&lang=ru")
        graph_html = self._get_text("/ui/graph")
        focused_graph_html = self._get_text("/ui/graph")
        invalid_graph_html = self._get_text("/ui/graph?hops=3")
        invalid_confidence_graph_html = self._get_text("/ui/graph?min_confidence=high")
        empty_graph_html = self._get_text("/ui/graph?binary_id=missing")
        function_html = self._get_text("/ui/functions/bin-main/fn_main")
        function_relations_html = self._get_text("/ui/functions/bin-main/fn_main?tab=relations")
        function_history_tab_html = self._get_text("/ui/functions/bin-main/fn_main?tab=history")
        function_history_html = self._get_text("/ui/functions/bin-main/fn_main/history")
        function_edit_html = self._get_text("/ui/functions/bin-main/fn_main/edit")
        structures_list_html = self._get_text("/ui/structures?q=ctx&binary_id=bin-main")
        new_structure_form_html = self._get_text("/ui/structures/new")
        structure_html = self._get_text("/ui/structures/struct_ctx")
        structure_history_html = self._get_text("/ui/structures/struct_ctx/history")
        structure_edit_html = self._get_text("/ui/structures/struct_ctx/edit")
        hypotheses_list_html = self._get_text("/ui/global-hypotheses?status=new")
        new_hypothesis_form_html = self._get_text("/ui/global-hypotheses/new")
        hypothesis_html = self._get_text("/ui/global-hypotheses/gh_ui")
        hypothesis_history_html = self._get_text("/ui/global-hypotheses/gh_ui/history")
        hypothesis_edit_html = self._get_text("/ui/global-hypotheses/gh_ui/edit")
        settings_html = self._get_text("/ui/settings")
        settings_ru_html = self._get_text("/ui/settings?lang=ru")
        import_export_html = self._get_text("/ui/import-export")
        backups_html = self._get_text("/ui/backups")
        pending_html = self._get_text("/ui/pending")
        audit_html = self._get_text("/ui/audit")
        css = self._get_text("/ui/assets/app.css")
        js = self._get_text("/ui/assets/ui.js")
        with self.assertRaises(error.HTTPError) as missing_page_ctx:
            request.urlopen(self.base_url + "/ui/missing-page")
        not_found_html = missing_page_ctx.exception.read().decode("utf-8")

        self.assertIn("Project Overview", dashboard_html)
        self.assertIn('data-theme="dark"', dashboard_html)
        self.assertIn('<script src="/ui/assets/ui.js" defer></script>', dashboard_html)
        self.assertIn('class="app-shell"', dashboard_html)
        self.assertIn('class="app-sidebar"', dashboard_html)
        self.assertIn('class="sidebar-icon"', dashboard_html)
        self.assertIn('aria-label="Toggle sidebar"', dashboard_html)
        self.assertIn('<a class="brand-mark" href="http://127.0.0.1:8764/?lang=en">Home</a>', dashboard_html)
        self.assertIn('aria-label="Test Project"', dashboard_html)
        self.assertIn('<span class="app-sidebar-label">Test Project</span>', dashboard_html)
        self.assertNotIn('<span class="app-sidebar-label">Projects</span>', dashboard_html)
        self.assertNotIn(">Nav</button>", dashboard_html)
        self.assertIn('class="top-search"', dashboard_html)
        self.assertIn('href="#main-content"', dashboard_html)
        self.assertIn('id="main-content"', dashboard_html)
        self.assertIn('aria-label="Search workspace"', dashboard_html)
        self.assertIn('aria-label="Language selector"', dashboard_html)
        self.assertIn('aria-label="Workspace navigation"', dashboard_html)
        self.assertIn('class="sidebar-section-title">Knowledge</p>', dashboard_html)
        self.assertIn('class="sidebar-section-title">Operations</p>', dashboard_html)
        self.assertIn('aria-label="Breadcrumbs"', dashboard_html)
        self.assertIn('data-theme-toggle', dashboard_html)
        self.assertEqual(dashboard_html.count("language-switcher"), 1)
        self.assertEqual(dashboard_html.count("Auto mode"), 1)
        self.assertIn('class="quick-link workspace-back-link"', dashboard_html)
        self.assertIn('href="http://127.0.0.1:8764/?lang=en"', dashboard_html)
        self.assertIn('data-nav-group="home"', dashboard_html)
        self.assertNotIn("Warm Lab", dashboard_html)
        self.assertIn("/ui/entities", dashboard_html)
        self.assertIn("/ui/graph", dashboard_html)
        self.assertIn("/ui/import-export", dashboard_html)
        self.assertIn("Обзор проекта", dashboard_ru_html)
        self.assertIn("Project Stats", dashboard_html)
        self.assertIn("Quick Entries", dashboard_html)
        self.assertIn('class="action-card"', dashboard_html)
        self.assertIn('class="action-card-head"', dashboard_html)
        self.assertIn('class="action-card-icon"', dashboard_html)
        self.assertIn('class="action-card-title">Entity Types</span>', dashboard_html)
        self.assertNotIn('class="quick-link action-card"', dashboard_html)
        self.assertIn("Storage Paths", dashboard_html)
        self.assertIn('class="path-list"', dashboard_html)
        self.assertIn('<code class="key-value">', dashboard_html)
        self.assertIn("Recent Updates", dashboard_html)
        self.assertIn("Copy MCP config", dashboard_html)
        self.assertIn("http://127.0.0.1:19876/mcp", dashboard_html)
        self.assertIn("/ui/settings", dashboard_html)
        self.assertIn("Functions", functions_list_html)
        self.assertIn("main_handler", functions_list_html)
        self.assertIn('value="main"', functions_list_html)
        self.assertIn("/ui/functions/bin-main/fn_main", functions_list_html)
        self.assertIn("New Function", new_function_form_html)
        self.assertIn("Save Function", new_function_form_html)
        self.assertIn('class="empty-state-body"', search_blank_html)
        self.assertIn("Search Workspace", search_html)
        self.assertIn("Поиск по проекту", search_ru_html)
        self.assertIn("main_handler", search_html)
        self.assertNotIn("Warm Lab", search_html)
        self.assertIn("Relation Graph", graph_html)
        self.assertIn("Graph Filters", graph_html)
        self.assertIn("No graph links yet", graph_html)
        self.assertIn("Create Relation", graph_html)
        self.assertIn("Relation Graph", focused_graph_html)
        self.assertIn("Graph Filters", focused_graph_html)
        self.assertIn("Relation Graph", invalid_graph_html)
        self.assertIn("Relation Graph", invalid_confidence_graph_html)
        self.assertIn("No graph links yet", empty_graph_html)
        self.assertIn("Create Relation", empty_graph_html)
        self.assertIn("Edit Function", function_edit_html)
        self.assertIn('class="detail-layout"', function_html)
        self.assertIn('class="tab-link is-active"', function_html)
        self.assertIn("Function Metadata", function_html)
        self.assertIn("View Version History", function_html)
        self.assertIn("Edit Record", function_html)
        self.assertIn("Observed Facts", function_html)
        self.assertIn("Open Focused Graph", function_relations_html)
        self.assertIn("uses_structure", function_relations_html)
        self.assertIn("Version 1", function_history_tab_html)
        self.assertIn("Function Version History", function_history_html)
        self.assertIn("Version 1", function_history_html)
        self.assertIn("Structures", structures_list_html)
        self.assertIn("ctx_t", structures_list_html)
        self.assertIn("/ui/structures/struct_ctx", structures_list_html)
        self.assertIn("New Structure", new_structure_form_html)
        self.assertIn("Save Structure", new_structure_form_html)
        self.assertIn('class="detail-layout"', structure_html)
        self.assertIn("Structure Metadata", structure_html)
        self.assertIn("Fields", structure_html)
        self.assertIn("Edit Structure", structure_edit_html)
        self.assertIn("Structure Version History", structure_history_html)
        self.assertIn("Global Hypotheses", hypotheses_list_html)
        self.assertIn("UI Hypothesis", hypotheses_list_html)
        self.assertIn("/ui/global-hypotheses/gh_ui", hypotheses_list_html)
        self.assertIn("New Global Hypothesis", new_hypothesis_form_html)
        self.assertIn("UI Hypothesis", hypothesis_html)
        self.assertIn("Hypothesis Metadata", hypothesis_html)
        self.assertIn("Edit Global Hypothesis", hypothesis_edit_html)
        self.assertIn("Global Hypothesis Version History", hypothesis_history_html)
        self.assertIn("Project Settings", settings_html)
        self.assertIn("Save Settings", settings_html)
        self.assertIn("http://127.0.0.1:19876/mcp", settings_html)
        self.assertIn("Export Project", import_export_html)
        self.assertIn("Import Project", import_export_html)
        self.assertIn("Export JSON", import_export_html)
        self.assertIn("Create Backup", backups_html)
        self.assertIn("Restore Backup", backups_html)
        self.assertIn("Настройки проекта", settings_ru_html)
        self.assertIn("Точка подключения", settings_ru_html)
        self.assertIn("Сохранить настройки", settings_ru_html)
        self.assertIn("HTTP хост", settings_ru_html)
        self.assertIn("MCP хост", settings_ru_html)
        self.assertIn("Режим: авто", settings_ru_html)
        self.assertIn('aria-label="Выбор языка"', settings_ru_html)
        self.assertIn('aria-label="Поиск по проекту"', settings_ru_html)
        self.assertIn('href="/ui/?lang=ru"', settings_ru_html)
        self.assertIn('action="/ui/settings?lang=ru"', settings_ru_html)
        self.assertEqual(settings_ru_html.count("language-switcher"), 1)
        self.assertEqual(settings_ru_html.count("Режим: авто"), 1)
        self.assertNotIn("РќР°", settings_ru_html)
        self.assertNotIn("РЎРѕ", settings_ru_html)
        self.assertNotIn("СЃС‚СЂ", settings_ru_html)
        self.assertNotIn("Warm Lab", function_html)
        self.assertNotIn("Warm Lab", not_found_html)
        self.assertIn('class="quick-link workspace-back-link"', not_found_html)
        self.assertIn('href="http://127.0.0.1:8764/?lang=en"', not_found_html)
        self.assertIn("Nothing is waiting right now", pending_html)
        self.assertIn("Audit Trail", audit_html)
        self.assertIn("upsert", audit_html)
        self.assertIn("--paper", css)
        self.assertIn("--bg", css)
        self.assertIn("data-theme=\"light\"", css)
        self.assertIn("@keyframes page-enter", css)
        self.assertIn("transition: grid-template-columns", css)
        self.assertIn(".skip-link", css)
        self.assertIn(".sidebar-collapsed .sidebar-link", css)
        self.assertIn(".sidebar-collapsed .app-sidebar", css)
        self.assertIn(".sidebar-section-title", css)
        self.assertIn(".graph-canvas", css)
        self.assertIn(".workspace-back-link", css)
        self.assertIn(".empty-state-body", css)
        self.assertIn(".action-card-title", css)
        self.assertIn(".action-card-icon", css)
        self.assertIn(".record-form-grid", css)
        self.assertIn(".record-form .record-field-control", css)
        self.assertIn("mcp-memory-theme", js)

    def test_project_pages_show_gateway_mcp_endpoint_when_base_url_is_configured(self) -> None:
        config = self.sandbox.registry.load()
        config.base_url = "http://mcp-memory.local:8764"
        self.sandbox.registry.save(config)

        dashboard_html = self._get_text("/ui/")
        settings_html = self._get_text("/ui/settings")

        gateway_mcp = "http://mcp-memory.local:8764/test-project/mcp"
        direct_mcp = "http://127.0.0.1:19876/mcp"
        self.assertIn(gateway_mcp, dashboard_html)
        self.assertIn(gateway_mcp, settings_html)
        self.assertNotIn(direct_mcp, dashboard_html)
        self.assertNotIn(direct_mcp, settings_html)

    def test_generic_ui_record_flow_and_schema_page(self) -> None:
        entities_html = self._get_text("/ui/entities")
        self.assertIn("Entity Types", entities_html)
        self.assertIn("Note", entities_html)

        new_html = self._get_text("/ui/records/note/new")
        self.assertIn("Record Form", new_html)
        self.assertIn('class="project-form record-form"', new_html)
        self.assertIn('class="form-grid record-form-grid"', new_html)
        self.assertIn('class="form-field record-form-field"', new_html)
        self.assertIn('class="record-field-control"', new_html)
        self.assertIn("hint-wrap", new_html)
        self.assertIn("friendly unique slug", new_html)
        self.assertIn("Required field.", new_html)
        self.assertIn('name="title"', new_html)

        posted = self._post_form_text(
            "/ui/records/note/new",
            {
                "slug": "ui-note",
                "title": "UI Note",
                "summary": "Created from GUI",
                "body": "body text",
                "tags": "ui\nnote",
            },
        )
        self.assertIn("UI Note", posted)
        records_html = self._get_text("/ui/records?entity_type=note")
        self.assertIn("UI Note", records_html)
        dashboard_html = self._get_text("/ui/")
        self.assertIn("Active Records", dashboard_html)
        self.assertIn("Entity Types", dashboard_html)
        self.assertIn("UI Note", dashboard_html)
        self.assertIn("/ui/records/note/new", dashboard_html)

        detail = self._get_text("/ui/records/note/ui-note")
        self.assertIn("UI Note", detail)
        self.assertIn("Record Fields", detail)
        self.assertIn('class="record-field-values"', detail)
        self.assertIn('data-field-name="summary"', detail)
        self.assertIn("Created from GUI", detail)
        self.assertIn('data-field-name="body"', detail)
        self.assertIn("body text", detail)
        self.assertIn('data-field-name="tags"', detail)
        self.assertIn("Payload", detail)
        self.assertIn("Add Evidence", detail)

        self._post_json("/records/note", {"payload": {"slug": "ui-second", "title": "UI Second"}, "created_by": "tester"})
        search_html = self._get_text("/ui/search?q=body&entity_type=note")
        self.assertIn("Schema-backed FTS", search_html)
        self.assertIn("UI Note", search_html)

        relation_html = self._post_form_text(
            "/ui/relations",
            {
                "from_entity_type": "note",
                "from_record_id": "ui-note",
                "to_entity_type": "note",
                "to_record_id": "ui-second",
                "relation_type": "related_to",
            },
        )
        self.assertIn("Relation Graph", relation_html)
        self.assertIn("related_to", relation_html)

        evidence_html = self._post_form_text(
            "/ui/evidence",
            {
                "entity_type": "note",
                "record_id": "ui-note",
                "evidence_type": "excerpt",
                "description": "GUI evidence",
                "excerpt": "important excerpt",
            },
        )
        self.assertIn("GUI evidence", evidence_html)
        self.assertIn("important excerpt", evidence_html)

        schema_html = self._get_text("/ui/schema")
        self.assertIn("Schema Builder", schema_html)
        self.assertIn("schema-card", schema_html)
        self.assertIn("schema-chip", schema_html)
        self.assertNotIn("Add Entity Type", schema_html)
        self.assertNotIn("Add Field", schema_html)
        self.assertNotIn("Add Relation Type", schema_html)
        self.assertIn("schema_json", schema_html)

    def test_generic_ui_schema_builder_forms_update_schema(self) -> None:
        entity_html = self._post_form_text(
            "/ui/schema/entity-types",
            {"name": "task", "label": "Task", "description": "Action item"},
        )
        self.assertIn("Task", entity_html)

        field_html = self._post_form_text(
            "/ui/schema/fields",
            {
                "entity_type": "task",
                "name": "status",
                "label": "Status",
                "widget": "enum",
                "options": "todo, done",
                "required": "true",
                "search_field": "true",
            },
        )
        self.assertIn("status", field_html)

        relation_html = self._post_form_text(
            "/ui/schema/relations",
            {"name": "blocks", "label": "Blocks", "from": "task", "to": "task", "directed": "true"},
        )
        self.assertIn("blocks", relation_html)

        schema = self._get_json("/schema")
        task = next(item for item in schema["entity_types"] if item["name"] == "task")
        self.assertIn("status", [field["name"] for field in task["fields"]])
        self.assertIn("status", task["required"])
        self.assertIn("blocks", [item["name"] for item in schema["relation_types"]])

    def test_generic_ui_entity_type_constructor_page(self) -> None:
        entities_html = self._get_text("/ui/entities")
        self.assertIn("New Entity Type", entities_html)
        self.assertIn("/ui/entities/new", entities_html)
        self.assertIn("/ui/entities/note/edit", entities_html)
        self.assertIn("/ui/entities/note/delete", entities_html)
        self.assertIn("entity-type-card", entities_html)
        self.assertIn("entity-type-grid", entities_html)
        self.assertIn("Required Fields", entities_html)
        self.assertIn("New Record", entities_html)
        self.assertIn("button-danger", entities_html)

        constructor_html = self._get_text("/ui/entities/new")
        self.assertIn("New Entity Type", constructor_html)
        self.assertIn("hint-wrap", constructor_html)
        self.assertIn("constructor-table", constructor_html)
        self.assertIn("constructor-role-pills", constructor_html)
        self.assertIn("constructor-add-button", constructor_html)
        self.assertIn("icon-button-danger", constructor_html)
        self.assertIn('name="name"', constructor_html)
        self.assertIn('name="label"', constructor_html)
        self.assertIn('name="description"', constructor_html)
        self.assertIn("field_name_0", constructor_html)
        self.assertIn("field_widget_0", constructor_html)
        self.assertIn("addConstructorFieldRow", constructor_html)
        self.assertIn("addConstructorRelationRow", constructor_html)
        self.assertIn("Create Entity Type", constructor_html)

    def test_generic_ui_entity_type_constructor_creates_entity(self) -> None:
        result_html = self._post_form_text(
            "/ui/entities/new",
            {
                "name": "bug",
                "label": "Bug",
                "description": "A reported bug",
                "field_name_0": "title",
                "field_label_0": "Title",
                "field_widget_0": "text",
                "field_required_0": "true",
                "field_title_0": "true",
                "field_search_0": "true",
                "field_name_1": "priority",
                "field_label_1": "Priority",
                "field_widget_1": "enum",
                "field_options_1": "low, medium, high",
                "field_required_1": "true",
                "field_name_2": "description",
                "field_label_2": "Description",
                "field_widget_2": "textarea",
                "field_summary_2": "true",
                "field_search_2": "true",
            },
        )
        self.assertIn("Bug", result_html)
        entities_html = self._get_text("/ui/entities")
        self.assertIn("bug", entities_html)
        schema = self._get_json("/schema")
        bug_entity = next(item for item in schema["entity_types"] if item["name"] == "bug")
        self.assertEqual(bug_entity["label"], "Bug")
        self.assertEqual(bug_entity["description"], "A reported bug")
        field_names = [field["name"] for field in bug_entity["fields"]]
        self.assertIn("title", field_names)
        self.assertIn("priority", field_names)
        self.assertIn("description", field_names)
        self.assertIn("title", bug_entity["required"])
        self.assertIn("priority", bug_entity["required"])
        self.assertEqual(bug_entity["title_field"], "title")
        self.assertEqual(bug_entity["summary_field"], "description")
        self.assertIn("description", bug_entity["search_fields"])
        priority_field = next(field for field in bug_entity["fields"] if field["name"] == "priority")
        self.assertEqual(priority_field["widget"], "enum")
        self.assertIn("low", priority_field["options"])

    def test_generic_ui_entity_type_constructor_with_relations(self) -> None:
        result_html = self._post_form_text(
            "/ui/entities/new",
            {
                "name": "milestone",
                "label": "Milestone",
                "description": "Project milestone",
                "field_name_0": "title",
                "field_label_0": "Title",
                "field_widget_0": "text",
                "field_required_0": "true",
                "field_title_0": "true",
                "field_search_0": "true",
                "rel_name_0": "belongs_to",
                "rel_label_0": "Belongs To",
                "rel_from_0": "milestone",
                "rel_to_0": "note",
                "rel_directed_0": "true",
            },
        )
        self.assertIn("Milestone", result_html)
        schema = self._get_json("/schema")
        self.assertIn("milestone", [item["name"] for item in schema["entity_types"]])
        self.assertIn("belongs_to", [item["name"] for item in schema["relation_types"]])

    def test_generic_ui_entity_type_constructor_accepts_sparse_dynamic_rows(self) -> None:
        result_html = self._post_form_text(
            "/ui/entities/new",
            {
                "name": "incident",
                "label": "Incident",
                "field_name_0": "title",
                "field_label_0": "Title",
                "field_widget_0": "text",
                "field_title_0": "true",
                "field_name_2": "impact",
                "field_label_2": "Impact",
                "field_widget_2": "textarea",
                "field_summary_2": "true",
                "rel_name_1": "caused_by",
                "rel_label_1": "Caused By",
                "rel_from_1": "incident",
                "rel_to_1": "note",
            },
        )
        self.assertIn("Incident", result_html)
        schema = self._get_json("/schema")
        incident = next(item for item in schema["entity_types"] if item["name"] == "incident")
        self.assertIn("impact", [field["name"] for field in incident["fields"]])
        self.assertIn("caused_by", [item["name"] for item in schema["relation_types"]])

    def test_generic_ui_entity_type_edit_and_delete(self) -> None:
        self._post_form_text(
            "/ui/entities/new",
            {
                "name": "ticket",
                "label": "Ticket",
                "field_name_0": "title",
                "field_label_0": "Title",
                "field_widget_0": "text",
                "field_title_0": "true",
            },
        )
        edit_html = self._get_text("/ui/entities/ticket/edit")
        self.assertIn("Edit Entity Type", edit_html)
        self.assertIn("Ticket", edit_html)
        self.assertIn("entity-editor-form", edit_html)
        self.assertIn("entity-editor-fields", edit_html)
        self.assertIn("entity-editor-relations", edit_html)
        self.assertIn("Relation Types (optional)", edit_html)
        self.assertIn("raw-schema-panel", edit_html)
        self.assertIn("Edit raw schema JSON", edit_html)
        self.assertIn('name="field_label_0"', edit_html)

        updated_html = self._post_form_text(
            "/ui/entities/ticket/edit",
            {
                "form_mode": "gui",
                "name": "ticket",
                "label": "Support Ticket",
                "description": "Updated",
                "field_name_0": "title",
                "field_label_0": "Ticket Title",
                "field_widget_0": "text",
                "field_description_0": "Visible title for the support ticket.",
                "field_title_0": "true",
                "field_search_0": "true",
                "rel_name_0": "ticket_relates_to",
                "rel_label_0": "Ticket Relates To",
                "rel_from_0": "ticket",
                "rel_to_0": "note",
                "rel_directed_0": "true",
            },
        )
        self.assertIn("Support Ticket", updated_html)
        schema_after_gui = self._get_json("/schema")
        ticket_after_gui = next(item for item in schema_after_gui["entity_types"] if item["name"] == "ticket")
        self.assertEqual(ticket_after_gui["fields"][0]["label"], "Ticket Title")
        self.assertEqual(ticket_after_gui["fields"][0]["description"], "Visible title for the support ticket.")
        self.assertIn("ticket_relates_to", [item["name"] for item in schema_after_gui["relation_types"]])

        raw_payload = dict(ticket_after_gui)
        raw_payload["description"] = "Raw updated"
        raw_updated_html = self._post_form_text("/ui/entities/ticket/edit", {"form_mode": "raw", "entity_json": json.dumps(raw_payload)})
        self.assertIn("Raw updated", raw_updated_html)

        delete_page = self._get_text("/ui/entities/ticket/delete")
        self.assertIn("Delete Entity Type", delete_page)
        self.assertIn("danger-zone", delete_page)

        deleted_html = self._post_form_text("/ui/entities/ticket/delete", {})
        self.assertNotIn("Support Ticket", deleted_html)
        schema = self._get_json("/schema")
        self.assertNotIn("ticket", [item["name"] for item in schema["entity_types"]])

        failed_delete_html = self._post_form_text("/ui/entities/note/delete", {})
        self.assertIn("<!DOCTYPE html>", failed_delete_html)
        self.assertIn("schema must keep at least one entity type", failed_delete_html)

    def test_generic_ui_entity_type_constructor_rejects_invalid(self) -> None:
        result_html = self._post_form_text(
            "/ui/entities/new",
            {
                "name": "",
                "label": "",
                "field_name_0": "title",
                "field_label_0": "Title",
                "field_widget_0": "text",
            },
        )
        self.assertIn("Name is required", result_html)

    def test_generic_ui_confirm_mode_uses_generic_pending_dispatch(self) -> None:
        self.sandbox.project.write_mode = "confirm"
        pending_html = self._post_form_text(
            "/ui/records/note/new",
            {
                "slug": "queued-ui-note",
                "title": "Queued UI Note",
                "summary": "Needs confirmation",
                "body": "queued body",
            },
        )
        self.assertIn("Review Proposals", pending_html)
        self.assertIn("upsert record", pending_html)

        with self.sandbox.open_database() as database:
            pending_id = database.connection.execute(
                "SELECT pending_change_id FROM pending_changes WHERE project_id = ? AND operation = 'upsert_record'",
                (self.sandbox.project.project_id,),
            ).fetchone()["pending_change_id"]

        confirmed_html = self._post_form_text(f"/ui/pending/{pending_id}/confirm", {})
        self.assertIn("Pending change confirmed and applied.", confirmed_html)
        self.sandbox.project.write_mode = "auto"
        record_html = self._get_text("/ui/records/note/queued-ui-note")
        self.assertIn("Queued UI Note", record_html)

    def test_ui_graph_caps_rendered_nodes_for_unfocused_view(self) -> None:
        with self.sandbox.open_database() as database:
            record_service = RecordService(database, self.sandbox.project)
            relation_service = GenericRelationService(database, self.sandbox.project)
            root = record_service.upsert_record(RecordWrite("note", {"slug": "graph-root", "title": "Graph Root"}, created_by="tester"))
            for index in range(60):
                record = record_service.upsert_record(
                    RecordWrite("note", {"slug": f"graph-note-{index:02d}", "title": f"Graph Note {index}"}, created_by="tester")
                )
                relation_service.create_relation(
                    GenericRelationWrite(
                        from_entity_type="note",
                        from_record_id=root.record_id,
                        to_entity_type="note",
                        to_record_id=record.record_id,
                        relation_type="related_to",
                        created_by="tester",
                    )
                )

        graph_html = self._get_text("/ui/graph")
        self.assertEqual(graph_html.count('class="graph-node graph-node-'), 50)
        self.assertIn("Graph Note", graph_html)

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
        self.assertEqual(len(self._get_json("/relations?entity_type=function&entity_id=missing")["items"]), 0)
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
        self._post_json("/records/note", {"payload": {"slug": "api-export", "title": "API Export"}, "created_by": "tester"})
        export_path = self.sandbox.root / "bundle.json"
        backup_path = self.sandbox.root / "backup.zip"
        restored_root = self.sandbox.root / "restored_project"

        exported = self._post_json("/export/json", {"output_path": str(export_path)})
        self.assertEqual(exported["counts"]["records"], 1)
        self.assertTrue(export_path.exists())

        imported = self._post_json("/import/json", {"input_path": str(export_path), "replace_existing": True})
        self.assertEqual(imported["counts"]["records"], 1)

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

    def test_ui_import_export_and_backup_flows(self) -> None:
        export_path = self.sandbox.root / "ui-bundle.json"
        backup_path = self.sandbox.root / "ui-backup.zip"
        restored_root = self.sandbox.root / "ui-restored-project"

        exported_html = self._post_form_text("/ui/import-export/export?lang=en", {"output_path": str(export_path)})
        self.assertIn("Project export completed.", exported_html)
        self.assertTrue(export_path.exists())

        imported_html = self._post_form_text(
            "/ui/import-export/import?lang=en",
            {"input_path": str(export_path), "replace_existing": "true"},
        )
        self.assertIn("Project import completed.", imported_html)

        invalid_import_html = self._post_form_text("/ui/import-export/import?lang=en", {"input_path": ""})
        self.assertIn("Input Path is required.", invalid_import_html)

        backup_html = self._post_form_text("/ui/backups/create?lang=en", {"output_path": str(backup_path)})
        self.assertIn("Project backup created.", backup_html)
        self.assertTrue(backup_path.exists())

        restored_html = self._post_form_text(
            "/ui/backups/restore?lang=en",
            {
                "input_path": str(backup_path),
                "project_root": str(restored_root),
                "project_id": "ui-restored-project",
                "display_name": "UI Restored Project",
                "http_port": "21000",
                "mcp_port": "21001",
                "write_mode": "confirm",
            },
        )
        self.assertIn("Project backup restored as a new project.", restored_html)
        self.assertTrue((restored_root / "project.db").exists())
        self.assertIsNotNone(self.sandbox.registry.get_project("ui-restored-project"))

        invalid_restore_html = self._post_form_text(
            "/ui/backups/restore?lang=en",
            {
                "input_path": str(backup_path),
                "project_root": str(self.sandbox.root / "bad-restore"),
                "project_id": "ui-restored-project",
                "display_name": "Duplicate",
                "http_port": "bad",
                "mcp_port": "",
                "write_mode": "confirm",
            },
        )
        self.assertIn("HTTP Port must be a valid integer.", invalid_restore_html)

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
            self._post_json("/search", {"limit": -1})
        self.assertEqual(ctx.exception.code, 400)

        with self.assertRaises(error.HTTPError) as ctx:
            self._post_json("/search", {"limit": 1001})
        self.assertEqual(ctx.exception.code, 400)

        with self.assertRaises(error.HTTPError) as ctx:
            self._get_json("/records?limit=-1")
        self.assertEqual(ctx.exception.code, 400)

        with self.assertRaises(error.HTTPError) as ctx:
            self._get_json("/records?limit=1001")
        self.assertEqual(ctx.exception.code, 400)

        with self.assertRaises(error.HTTPError) as ctx:
            self._post_json("/pending-changes//confirm", {})
        self.assertEqual(ctx.exception.code, 400)

    def test_zero_limit_returns_empty_results(self) -> None:
        self.assertEqual(self._post_json("/search", {"limit": 0})["items"], [])
        self.assertEqual(self._get_json("/records?limit=0")["items"], [])

    def test_api_post_reads_json_once_without_form_preparse(self) -> None:
        req = request.Request(
            self.base_url + "/search",
            data=json.dumps({"q": "definitely-not-present", "limit": 100}).encode("utf-8"),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with request.urlopen(req) as response:
            result = json.loads(response.read().decode("utf-8"))
        self.assertEqual(result["items"], [])

    def test_malformed_content_length_returns_bad_request(self) -> None:
        for content_length in (b"bad", b"-1"):
            with self.subTest(content_length=content_length):
                status_line, body = self._raw_http(
                    b"POST /search HTTP/1.1\r\n"
                    b"Host: 127.0.0.1\r\n"
                    b"Content-Type: application/json\r\n"
                    b"Content-Length: " + content_length + b"\r\n"
                    b"Connection: close\r\n"
                    b"\r\n"
                )
                self.assertIn("400", status_line)
                self.assertEqual(json.loads(body.decode("utf-8"))["error"], "invalid_content_length")

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

    def _put_json(self, path: str, payload: dict) -> dict:
        req = request.Request(
            self.base_url + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="PUT",
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

    def _post_status(self, path: str, payload: dict) -> int:
        try:
            self._post_json(path, payload)
        except error.HTTPError as exc:
            return exc.code
        return 200

    def _put_status(self, path: str, payload: dict) -> int:
        try:
            self._put_json(path, payload)
        except error.HTTPError as exc:
            return exc.code
        return 200

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
