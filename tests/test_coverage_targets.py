from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import unittest

from tests.support import ProjectSandbox

from mcp_memory.domain import HypothesisStatus
from mcp_memory.api.server import evidence_write_from_payload, function_write_from_payload, global_hypothesis_write_from_payload, structure_write_from_payload
from mcp_memory.gui import generic as generic_ui
from mcp_memory.gui import render as gui_render
from mcp_memory.gui import templates as gui_templates
from mcp_memory.gui import workspace
from mcp_memory.schema import FieldDefinition, ProjectSchema, SchemaValidationError, copy_schema_payload, load_project_schema, save_project_schema
from mcp_memory.storage.migrations import bootstrap_project_database
from mcp_memory.services import (
    EvidenceService,
    FunctionService,
    GenericEvidenceService,
    GenericEvidenceWrite,
    GenericRelationValidationError,
    GenericRelationService,
    GenericRelationWrite,
    GlobalHypothesisService,
    LegacyDatabaseImporter,
    LegacyImportValidationError,
    ProjectTransferService,
    RecordValidationError,
    RecordService,
    RecordWrite,
    RelationService,
    RelationWrite,
    StructureService,
)


def _relation(from_type: str, from_id: str, to_type: str, to_id: str, relation_type: str = "related_to") -> SimpleNamespace:
    return SimpleNamespace(
        from_entity_type=from_type,
        from_entity_id=from_id,
        from_record_id=from_id,
        to_entity_type=to_type,
        to_entity_id=to_id,
        to_record_id=to_id,
        relation_type=relation_type,
        created_by="tester",
        created_at="2026-01-01T00:00:00+00:00",
    )


class CoverageTargetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sandbox = ProjectSandbox()

    def tearDown(self) -> None:
        self.sandbox.cleanup()

    def test_workspace_graph_helpers_cover_filter_and_render_branches(self) -> None:
        function = SimpleNamespace(function_id="fn1", current_name="Function One With A Long Display Name", binary_id="bin", confidence=0.8)
        structure = SimpleNamespace(structure_id="struct1", current_name="Struct One", binary_id="bin")
        hypothesis = SimpleNamespace(
            hypothesis_id="hyp1",
            title="Hypothesis One",
            binary_id=None,
            status=HypothesisStatus.CONFIRMED,
            confidence=0.5,
        )
        relations = [
            _relation("function", "fn1", "structure", "struct1", "uses_structure"),
            _relation("structure", "struct1", "global_hypothesis", "hyp1", "supports"),
            _relation("unknown", "u1", "function", "fn1"),
        ]

        nodes = workspace.graph_nodes(self.sandbox.project, [function], [structure], [hypothesis], relations)
        self.assertIn(("unknown", "u1"), nodes)
        self.assertEqual(len(workspace.graph_edges_for_focus(relations, "function", "fn1", 2)), 5)
        self.assertEqual(workspace.graph_node_keys(relations), {("function", "fn1"), ("structure", "struct1"), ("global_hypothesis", "hyp1"), ("unknown", "u1")})
        self.assertEqual(len(workspace.graph_node_keys_limited(relations, 2)), 2)
        self.assertEqual(len(workspace.graph_node_keys_limited(relations, 99)), 4)
        self.assertFalse(workspace.graph_node_matches(None, "", "", "", None))
        self.assertFalse(workspace.graph_node_matches(nodes[("function", "fn1")], "structure", "", "", None))
        self.assertFalse(workspace.graph_node_matches(nodes[("function", "fn1")], "", "other-bin", "", None))
        self.assertFalse(workspace.graph_node_matches(nodes[("global_hypothesis", "hyp1")], "", "", "new", None))
        self.assertFalse(workspace.graph_node_matches(nodes[("global_hypothesis", "hyp1")], "", "", "", 0.9))
        self.assertTrue(workspace.graph_node_matches(nodes[("global_hypothesis", "hyp1")], "", "", "confirmed", 0.4))

        self.assertIn("No graph links yet", workspace.render_graph_svg(self.sandbox.project, nodes, set(), [], "en"))
        one_node = workspace.render_graph_svg(self.sandbox.project, nodes, {("function", "fn1")}, [], "en")
        self.assertIn("Function One With A Long Display Name", one_node)
        graph = workspace.render_graph_svg(self.sandbox.project, nodes, set(nodes), relations, "ru")
        self.assertIn("data-graph-canvas", graph)
        self.assertIn("data-graph-cytoscape", graph)
        self.assertIn("data-graph-elements", graph)
        self.assertIn('data-graph-action="zoom-in"', graph)
        self.assertIn("data-graph-layout-select", graph)
        self.assertIn('data-graph-action="fullscreen"', graph)
        self.assertIn('"group": "edges"', graph)
        self.assertIn("function:fn1", graph)
        self.assertIn("lang=ru", graph)
        self.assertIn("No nodes selected", workspace.render_graph_side_list(self.sandbox.project, nodes, set(), "en"))
        side = workspace.render_graph_side_list(self.sandbox.project, nodes, set(nodes), "en")
        self.assertIn("bin", side)
        self.assertIn("confirmed", side)

    def test_workspace_legacy_search_and_graph_pages(self) -> None:
        with self.sandbox.open_database() as database:
            FunctionService(database).upsert_function(
                function_write_from_payload(
                    self.sandbox.project.project_id,
                    {
                        "binary_id": "bin",
                        "function_id": "fn_graph",
                        "address": "0x401000",
                        "raw_name": "sub_401000",
                        "current_name": "graph_main",
                        "summary": "Graph search summary",
                        "behavior_description": "Legacy graph behavior",
                        "tags": ["graph"],
                    },
                )
            )
            StructureService(database).upsert_structure(
                structure_write_from_payload(
                    self.sandbox.project.project_id,
                    {
                        "binary_id": "bin",
                        "structure_id": "struct_graph",
                        "raw_name": "raw_graph",
                        "current_name": "graph_struct",
                        "summary": "Graph structure summary",
                    },
                )
            )
            GlobalHypothesisService(database).upsert_hypothesis(
                global_hypothesis_write_from_payload(
                    self.sandbox.project.project_id,
                    {
                        "hypothesis_id": "gh_graph",
                        "title": "Graph Hypothesis",
                        "statement": "Relations cross entities.",
                        "status": "confirmed",
                        "confidence": 0.75,
                        "binary_id": "bin",
                    },
                )
            )
            RelationService(database).create_relation(
                RelationWrite(
                    project_id=self.sandbox.project.project_id,
                    from_entity_type="function",
                    from_entity_id="fn_graph",
                    to_entity_type="structure",
                    to_entity_id="struct_graph",
                    relation_type="uses_structure",
                )
            )
            RelationService(database).create_relation(
                RelationWrite(
                    project_id=self.sandbox.project.project_id,
                    from_entity_type="structure",
                    from_entity_id="struct_graph",
                    to_entity_type="global_hypothesis",
                    to_entity_id="gh_graph",
                    relation_type="supports",
                )
            )

        blank_search = workspace.render_search_page(self.sandbox.project, {}, "/ui/search", "en")
        self.assertIn("Search across your project", blank_search)
        search_html = workspace.render_search_page(
            self.sandbox.project,
            {"q": ["graph"], "entity_type": ["function"], "binary_id": [""], "tag": [""]},
            "/ui/search?q=graph&entity_type=function",
            "en",
        )
        self.assertIn("graph_main", search_html)
        self.assertIn("Function", search_html)
        no_match = workspace.render_search_page(self.sandbox.project, {"q": ["missing"]}, "/ui/search?q=missing", "en")
        self.assertIn("No matches yet", no_match)

        graph_html = workspace.render_graph_page(self.sandbox.project, {}, "/ui/graph", "en")
        self.assertIn("data-graph-cytoscape", graph_html)
        focused_graph = workspace.render_graph_page(
            self.sandbox.project,
            {"focus_type": ["function"], "focus_id": ["fn_graph"], "hops": ["2"], "entity_type": [""], "binary_id": ["bin"], "status": [""], "min_confidence": ["0.7"]},
            "/ui/graph?focus_type=function&focus_id=fn_graph",
            "en",
        )
        self.assertIn("Graph Hypothesis", focused_graph)
        invalid_hops = workspace.render_graph_page(self.sandbox.project, {"hops": ["3"]}, "/ui/graph?hops=3", "en")
        self.assertIn("Hops must be 1 or 2", invalid_hops)
        invalid_confidence = workspace.render_graph_page(self.sandbox.project, {"min_confidence": ["bad"]}, "/ui/graph?min_confidence=bad", "en")
        self.assertIn("Min confidence must be a number", invalid_confidence)
        filtered_empty = workspace.render_graph_page(self.sandbox.project, {"binary_id": ["missing"]}, "/ui/graph?binary_id=missing", "en")
        self.assertIn("No graph links yet", filtered_empty)

    def test_workspace_render_and_parse_helpers_cover_empty_and_variant_branches(self) -> None:
        self.assertIn("No recent updates yet", workspace.render_recent_updates(self.sandbox.project, []))
        self.assertIn("No recent updates yet", workspace.render_recent_records([], "en"))
        self.assertIn("All entities", workspace.entity_type_options(""))
        self.assertIn("selected", workspace.entity_type_options("structure"))
        self.assertIn("selected", workspace.graph_entity_type_options("global_hypothesis", "Any"))
        self.assertIn("Any status", workspace.entity_list_filter_form("/ui/global-hypotheses", "", "", "", "new", "updated", "en"))
        self.assertEqual(workspace.parse_multiline_items("a\n\n b "), ["a", "b"])
        self.assertEqual(
            workspace.parse_structure_fields("field|0x0|int|4|comment\nbad"),
            [
                {"name": "field", "offset": "0x0", "data_type": "int", "size": 4, "comment": "comment"},
                {"name": "bad", "offset": "", "data_type": "", "size": None, "comment": ""},
            ],
        )
        self.assertEqual(workspace.build_fact_payloads("fact1\nfact2"), [{"fact": "fact1", "source_origin": "ui"}, {"fact": "fact2", "source_origin": "ui"}])
        self.assertIsNone(workspace.parse_optional_float(""))
        with self.assertRaises(ValueError):
            workspace.parse_optional_float("not-a-number")
        with self.assertRaises(ValueError):
            workspace.parse_settings_port("abc", "HTTP Port")
        self.assertIsNone(workspace.parse_optional_settings_port("", "MCP Port"))
        self.assertEqual(workspace.parse_optional_settings_port("1234", "MCP Port"), 1234)

        self.assertIn("No facts yet", workspace.render_fact_list([]))
        self.assertIn("No hypotheses yet", workspace.render_hypothesis_list([]))
        hypothesis = SimpleNamespace(status=HypothesisStatus.PROBABLE, confidence=0.42, statement="Maybe")
        self.assertIn("confidence 0.42", workspace.render_hypothesis_list([hypothesis]))
        self.assertIn("No evidence yet", workspace.render_evidence_list([]))
        evidence = SimpleNamespace(evidence_type="file", address_start="0x1", attachment_path="a.txt", description="Desc")
        self.assertIn("a.txt", workspace.render_evidence_list([evidence]))
        self.assertIn("Confidence unknown", workspace.confidence_badge_markup(None))
        self.assertIn("badge-warning", workspace.confidence_badge_markup(0.5))
        self.assertIn("badge-danger", workspace.confidence_badge_markup(0.1))
        self.assertIn("badge-success", gui_render.confidence_badge(0.8))
        self.assertIn("badge-warning", gui_render.confidence_badge(0.5))
        self.assertIn("badge-danger", gui_render.confidence_badge(0.2))
        self.assertIn("badge-success", gui_render.status_badge("confirmed"))
        self.assertIn("badge-danger", gui_render.status_badge("rejected"))
        self.assertIn("badge-warning", gui_render.status_badge("probable"))

    def test_workspace_submit_error_branches(self) -> None:
        invalid_settings = workspace.submit_project_settings_form(self.sandbox.project, self.sandbox.registry, {"http_port": "abc"}, "en")
        self.assertEqual(invalid_settings["status"], 400)
        unchanged_settings = workspace.submit_project_settings_form(self.sandbox.project, self.sandbox.registry, {}, "en")
        self.assertIn("flash=saved", unchanged_settings["location"])
        self.assertIn("Input Path is required", workspace.submit_import_export_import(self.sandbox.project, {}, "en")["html"])
        self.assertIn("Input Path is required", workspace.submit_backup_restore(self.sandbox.project, self.sandbox.registry, {}, "en")["html"])
        self.assertIn(
            "Project Root is required",
            workspace.submit_backup_restore(self.sandbox.project, self.sandbox.registry, {"input_path": "missing.zip"}, "en")["html"],
        )
        bad_restore = workspace.submit_backup_restore(
            self.sandbox.project,
            self.sandbox.registry,
            {"input_path": "missing.zip", "project_root": str(self.sandbox.root / "restored"), "http_port": "abc"},
            "en",
        )
        self.assertEqual(bad_restore["status"], 400)
        bad_import = workspace.submit_import_export_import(self.sandbox.project, {"input_path": str(self.sandbox.root / "missing.json")}, "en")
        self.assertEqual(bad_import["status"], 400)
        bad_export = workspace.submit_import_export_export(self.sandbox.project, {"output_path": str(self.sandbox.root)}, "en")
        self.assertEqual(bad_export["status"], 400)
        bad_backup = workspace.submit_backup_create(self.sandbox.project, self.sandbox.registry, {"output_path": str(self.sandbox.root)}, "en")
        self.assertEqual(bad_backup["status"], 400)

    def test_generic_ui_error_and_private_branches(self) -> None:
        self.assertIsNone(generic_ui.generic_workspace_response(self.sandbox.project, self.sandbox.registry, "/ui/unknown", lambda *args, **kwargs: ""))
        shell = lambda project, title, body, current_url, lang, **kwargs: body
        status, html = generic_ui.generic_workspace_response(self.sandbox.project, self.sandbox.registry, "/ui/entities/missing/edit", shell)
        self.assertEqual(status, 200)
        self.assertIn("Entity type not found", html)
        self.assertEqual(generic_ui.generic_workspace_post_action(self.sandbox.project, self.sandbox.registry, "/ui/unknown", {}), None)

        bad_schema = generic_ui.generic_workspace_post_action(self.sandbox.project, self.sandbox.registry, "/ui/schema", {"schema_json": "not-json"})
        self.assertEqual(bad_schema["status"], 400)
        self.assertIn("Expecting value", bad_schema["html"])
        self.sandbox.project.write_mode = "auto"
        self.assertEqual(generic_ui.generic_workspace_post_action(self.sandbox.project, self.sandbox.registry, "/ui/evidence", {})["status"], 400)
        self.assertEqual(generic_ui.generic_workspace_post_action(self.sandbox.project, self.sandbox.registry, "/ui/relations", {})["status"], 400)
        self.assertEqual(generic_ui.generic_workspace_post_action(self.sandbox.project, self.sandbox.registry, "/ui/schema/entity-types", {"name": ""})["status"], 400)
        self.assertEqual(generic_ui.generic_workspace_post_action(self.sandbox.project, self.sandbox.registry, "/ui/schema/fields", {"entity_type": "missing"})["status"], 400)
        self.assertEqual(generic_ui.generic_workspace_post_action(self.sandbox.project, self.sandbox.registry, "/ui/schema/relations", {"name": ""})["status"], 400)

        with self.sandbox.open_database() as database:
            record = RecordService(database, self.sandbox.project).upsert_record(RecordWrite("note", {"slug": "edit-me", "title": "Edit Me"}))
        edit_status, edit_html = generic_ui.generic_workspace_response(
            self.sandbox.project,
            self.sandbox.registry,
            f"/ui/records/note/{record.record_id}/edit",
            lambda project, title, body, current_url, lang, **kwargs: body,
        )
        self.assertEqual(edit_status, 200)
        self.assertIn("Record Form", edit_html)
        invalid_edit = generic_ui.generic_workspace_post_action(
            self.sandbox.project,
            self.sandbox.registry,
            f"/ui/records/note/{record.record_id}/edit",
            {"title": ""},
        )
        self.assertEqual(invalid_edit["status"], 400)
        self.assertIn("title is required", invalid_edit["html"])
        self.assertEqual(
            generic_ui.generic_workspace_post_action(self.sandbox.project, self.sandbox.registry, "/ui/entities/note/delete", {})["status"],
            400,
        )

    def test_generic_schema_form_record_and_confirm_branches(self) -> None:
        shell = lambda project, title, body, current_url, lang, **kwargs: body
        schema_payload = {
            "schema_version": "1",
            "entity_types": [
                {
                    "name": "complex",
                    "label": "Complex",
                    "fields": [
                        {"name": "slug", "label": "Slug", "widget": "text"},
                        {"name": "title", "label": "Title", "widget": "text"},
                        {"name": "body", "label": "Body", "widget": "textarea"},
                        {"name": "count", "label": "Count", "widget": "number"},
                        {"name": "flag", "label": "Flag", "widget": "bool"},
                        {"name": "state", "label": "State", "widget": "enum", "options": ["open", "done"]},
                        {"name": "tags", "label": "Tags", "widget": "tags"},
                        {"name": "meta", "label": "Meta", "widget": "json"},
                    ],
                    "required": ["title"],
                    "title_field": "title",
                    "summary_field": "body",
                    "slug_field": "slug",
                    "search_fields": ["title", "body", "meta"],
                    "tag_fields": ["tags"],
                },
                {"name": "other", "label": "Other", "fields": [{"name": "title", "label": "Title", "widget": "text"}], "title_field": "title"},
            ],
            "relation_types": [{"name": "links", "label": "Links", "from": ["complex"], "to": ["complex"], "directed": True}],
        }
        schema_saved = generic_ui.generic_workspace_post_action(
            self.sandbox.project,
            self.sandbox.registry,
            "/ui/schema?lang=en",
            {"schema_json": json.dumps(schema_payload)},
        )
        self.assertIn("flash=updated", schema_saved["location"])

        status, form_html = generic_ui.generic_workspace_response(self.sandbox.project, self.sandbox.registry, "/ui/records/complex/new", shell)
        self.assertEqual(status, 200)
        self.assertIn('type="checkbox"', form_html)
        self.assertIn("<select", form_html)
        self.assertIn("<textarea", form_html)

        self.sandbox.project.write_mode = "auto"
        created = generic_ui.generic_workspace_post_action(
            self.sandbox.project,
            self.sandbox.registry,
            "/ui/records/complex/new",
            {
                "slug": "complex-one",
                "title": "Complex One",
                "body": "Body text",
                "count": "3.5",
                "flag": "true",
                "state": "open",
                "tags": "alpha, beta",
                "meta": '{"nested": ["value"]}',
            },
        )
        self.assertIn("/ui/records/complex/", created["location"])
        record_id = created["location"].rsplit("/", 1)[-1].split("?", 1)[0]

        records_status, records_html = generic_ui.generic_workspace_response(
            self.sandbox.project,
            self.sandbox.registry,
            "/ui/records?q=Complex&entity_type=complex",
            shell,
        )
        self.assertEqual(records_status, 200)
        self.assertIn("Complex One", records_html)
        by_type_status, by_type_search = generic_ui.generic_workspace_response(
            self.sandbox.project,
            self.sandbox.registry,
            "/ui/search?entity_type=complex",
            shell,
        )
        self.assertEqual(by_type_status, 200)
        self.assertIn("Complex One", by_type_search)
        no_match_status, no_match = generic_ui.generic_workspace_response(
            self.sandbox.project,
            self.sandbox.registry,
            "/ui/search?q=missing&entity_type=complex",
            shell,
        )
        self.assertEqual(no_match_status, 200)
        self.assertIn("No matches yet", no_match)

        archived = generic_ui.generic_workspace_post_action(self.sandbox.project, self.sandbox.registry, f"/ui/records/complex/{record_id}/archive", {})
        self.assertIn("flash=archived", archived["location"])

        self.sandbox.project.write_mode = "confirm"
        with self.sandbox.open_database() as database:
            first = RecordService(database, self.sandbox.project).upsert_record(RecordWrite("complex", {"slug": "first", "title": "First"}))
            second = RecordService(database, self.sandbox.project).upsert_record(RecordWrite("complex", {"slug": "second", "title": "Second"}))
        queued_evidence = generic_ui.generic_workspace_post_action(
            self.sandbox.project,
            self.sandbox.registry,
            "/ui/evidence",
            {"entity_type": "complex", "record_id": first.record_id, "evidence_type": "note", "description": "Queued"},
        )
        self.assertIn("flash=queued", queued_evidence["location"])
        queued_relation = generic_ui.generic_workspace_post_action(
            self.sandbox.project,
            self.sandbox.registry,
            "/ui/relations",
            {
                "from_entity_type": "complex",
                "from_record_id": first.record_id,
                "to_entity_type": "complex",
                "to_record_id": second.record_id,
                "relation_type": "links",
            },
        )
        self.assertIn("flash=queued", queued_relation["location"])

        graph_status, single_graph = generic_ui.generic_workspace_response(
            self.sandbox.project,
            self.sandbox.registry,
            f"/ui/graph?focus_type=complex&focus_id={first.record_id}",
            shell,
        )
        self.assertEqual(graph_status, 200)
        self.assertIn("First", single_graph)
        missing_evidence = generic_ui.generic_workspace_response(
            self.sandbox.project,
            self.sandbox.registry,
            "/ui/evidence?entity_type=complex&record_id=missing",
            shell,
        )[1]
        self.assertIn("Record not found", missing_evidence)

    def test_entity_pages_filter_relation_types_for_entity(self) -> None:
        shell = lambda project, title, body, current_url, lang, **kwargs: body
        schema = ProjectSchema.from_dict(
            {
                "schema_version": "1",
                "entity_types": [
                    {
                        "name": "note",
                        "label": "Note",
                        "fields": [{"name": "title", "label": "Title", "widget": "text"}],
                        "required": ["title"],
                        "title_field": "title",
                    },
                    {
                        "name": "source",
                        "label": "Source",
                        "fields": [{"name": "title", "label": "Title", "widget": "text"}],
                        "title_field": "title",
                    },
                    {
                        "name": "claim",
                        "label": "Claim",
                        "fields": [{"name": "title", "label": "Title", "widget": "text"}],
                        "title_field": "title",
                    },
                ],
                "relation_types": [
                    {"name": "note_source", "label": "Note Source", "from": ["note"], "to": ["source"], "directed": True},
                    {"name": "claim_note", "label": "Claim Note", "from": ["claim"], "to": ["note"], "directed": True},
                    {"name": "any_to_claim", "label": "Any To Claim", "from": ["*"], "to": ["claim"], "directed": True},
                    {"name": "source_to_any", "label": "Source To Any", "from": ["source"], "to": ["*"], "directed": True},
                    {"name": "source_claim", "label": "Source Claim", "from": ["source"], "to": ["claim"], "directed": True},
                ],
            }
        )
        save_project_schema(self.sandbox.project.schema_path, schema)
        edit_status, edit_html = generic_ui.generic_workspace_response(
            self.sandbox.project,
            self.sandbox.registry,
            "/ui/entities/note/edit",
            shell,
        )

        self.assertEqual(edit_status, 200)
        self.assertIn("note_source", edit_html)
        self.assertIn("claim_note", edit_html)
        self.assertIn("any_to_claim", edit_html)
        self.assertIn("source_to_any", edit_html)
        self.assertNotIn("source_claim", edit_html)

        updated = generic_ui.generic_workspace_post_action(
            self.sandbox.project,
            self.sandbox.registry,
            "/ui/entities/note/edit",
            {
                "form_mode": "gui",
                "name": "note",
                "label": "Note",
                "field_name_0": "title",
                "field_label_0": "Title",
                "field_widget_0": "text",
                "field_required_0": "true",
                "field_title_0": "true",
                "rel_name_0": "note_source",
                "rel_label_0": "Note Source",
                "rel_from_0": "note",
                "rel_to_0": "source",
                "rel_directed_0": "true",
                "rel_name_1": "claim_note",
                "rel_label_1": "Claim Note",
                "rel_from_1": "claim",
                "rel_to_1": "note",
                "rel_directed_1": "true",
                "rel_name_2": "any_to_claim",
                "rel_label_2": "Any To Claim",
                "rel_from_2": "*",
                "rel_to_2": "claim",
                "rel_directed_2": "true",
                "rel_name_3": "source_to_any",
                "rel_label_3": "Source To Any",
                "rel_from_3": "source",
                "rel_to_3": "*",
                "rel_directed_3": "true",
            },
        )
        self.assertIn("flash=updated", updated["location"])
        saved_relation_names = {relation.name for relation in load_project_schema(self.sandbox.project.schema_path).relation_types}
        self.assertIn("source_claim", saved_relation_names)

        with self.sandbox.open_database() as database:
            record = RecordService(database, self.sandbox.project).upsert_record(RecordWrite("note", {"title": "Filtered Relations"}))

        status, html = generic_ui.generic_workspace_response(
            self.sandbox.project,
            self.sandbox.registry,
            f"/ui/records/note/{record.record_id}",
            shell,
        )

        self.assertEqual(status, 200)
        self.assertIn("note_source", html)
        self.assertIn("claim_note", html)
        self.assertIn("any_to_claim", html)
        self.assertIn("source_to_any", html)
        self.assertNotIn("source_claim", html)

    def test_generic_schema_builder_private_edges(self) -> None:
        self.assertIn("selected", generic_ui._widget_options("json"))
        self.assertIn("Add Entity Type", generic_ui._entity_type_builder_form("en"))
        self.assertIn("Add Field", generic_ui._field_builder_form(generic_ui.load_project_schema(self.sandbox.project.schema_path), "en"))
        self.assertIn("Add Relation Type", generic_ui._relation_type_builder_form(generic_ui.load_project_schema(self.sandbox.project.schema_path), "en"))

        default_created = generic_ui.generic_workspace_post_action(
            self.sandbox.project,
            self.sandbox.registry,
            "/ui/entities/new",
            {"name": "default_entity", "label": "Default Entity", "field_name_0": "", "rel_name_0": "", "rel_name_1": ""},
        )
        self.assertIn("flash=created", default_created["location"])

        sparse_relation = generic_ui.generic_workspace_post_action(
            self.sandbox.project,
            self.sandbox.registry,
            "/ui/entities/new",
            {
                "name": "with_sparse_relation",
                "label": "With Sparse Relation",
                "field_name_0": "title",
                "field_widget_0": "text",
                "rel_name_0": "",
                "rel_name_1": "sparse_link",
                "rel_label_1": "Sparse Link",
                "rel_from_1": "with_sparse_relation",
                "rel_to_1": "default_entity",
            },
        )
        self.assertIn("flash=created", sparse_relation["location"])

        invalid_constructor = generic_ui.generic_workspace_post_action(
            self.sandbox.project,
            self.sandbox.registry,
            "/ui/entities/new",
            {"name": "bad_enum", "label": "Bad Enum", "field_name_0": "status", "field_widget_0": "enum"},
        )
        self.assertEqual(invalid_constructor["status"], 400)
        self.assertIn("must define options", invalid_constructor["html"])

        edit_missing = generic_ui.generic_workspace_post_action(
            self.sandbox.project,
            self.sandbox.registry,
            "/ui/entities/missing/edit",
            {"entity_json": json.dumps({"name": "missing", "label": "Missing", "fields": [{"name": "title", "label": "Title", "widget": "text"}]})},
        )
        self.assertEqual(edit_missing["status"], 400)
        self.assertIn("unknown entity type", edit_missing["html"])

        with self.sandbox.open_database() as database:
            RecordService(database, self.sandbox.project).upsert_record(RecordWrite("default_entity", {"title": "Existing"}))
        delete_with_records = generic_ui.generic_workspace_post_action(self.sandbox.project, self.sandbox.registry, "/ui/entities/default_entity/delete", {})
        self.assertEqual(delete_with_records["status"], 400)
        self.assertIn("cannot be deleted", delete_with_records["html"])
        delete_missing = generic_ui.generic_workspace_post_action(self.sandbox.project, self.sandbox.registry, "/ui/entities/not_here/delete", {})
        self.assertEqual(delete_missing["status"], 400)
        self.assertIn("unknown entity type", delete_missing["html"])

        added_field = generic_ui.generic_workspace_post_action(
            self.sandbox.project,
            self.sandbox.registry,
            "/ui/schema/fields",
            {"entity_type": "with_sparse_relation", "name": "labels", "label": "Labels", "widget": "tags", "slug_field": "true", "tag_field": "true"},
        )
        self.assertIn("flash=updated", added_field["location"])

    def test_transfer_legacy_v1_and_attachment_branches(self) -> None:
        service = ProjectTransferService()
        with self.assertRaisesRegex(ValueError, "Unsupported bundle_version"):
            service.import_bundle(self.sandbox.project, {"bundle_version": 99})
        with self.assertRaisesRegex(ValueError, "Bundle records must be an object"):
            service.import_bundle(self.sandbox.project, {"bundle_version": 2, "schema": {}, "records": []})
        with self.assertRaisesRegex(ValueError, "Bundle schema must be an object"):
            service.import_bundle(self.sandbox.project, {"bundle_version": 2, "records": {}})
        with self.assertRaisesRegex(ValueError, "Bundle records must be an object"):
            service.import_bundle(self.sandbox.project, {"bundle_version": 1, "records": []})

        legacy_v1 = {
            "bundle_version": 1,
            "records": {
                "functions": [
                    {
                        "binary_id": "bin",
                        "function_id": "fn_v1",
                        "address": "0x1",
                        "raw_name": "sub_1",
                        "current_name": "fn_v1",
                        "summary": "summary",
                        "behavior_description": "behavior",
                        "confidence": 0.6,
                        "tags": ["legacy"],
                        "observed_facts": [{"fact": "fact"}],
                        "hypotheses": [{"statement": "hyp"}],
                    }
                ],
                "structures": [
                    {
                        "binary_id": "bin",
                        "structure_id": "struct_v1",
                        "raw_name": "raw",
                        "current_name": "struct_v1",
                        "summary": "summary",
                        "fields": [{"name": "x", "offset": "0x0", "data_type": "int", "size": 4}],
                        "observed_facts": [{"fact": "field fact"}],
                        "hypotheses": [{"statement": "layout"}],
                    }
                ],
                "global_hypotheses": [
                    {
                        "hypothesis_id": "gh_v1",
                        "title": "Hyp",
                        "statement": "Statement",
                        "status": "confirmed",
                        "confidence": 0.7,
                        "binary_id": "bin",
                        "observed_facts": [{"fact": "global fact"}],
                    }
                ],
                "evidence": [
                    {
                        "evidence_id": "ev_v1",
                        "entity_type": "function",
                        "entity_id": "fn_v1",
                        "evidence_type": "log",
                        "description": "Evidence",
                        "attachment_path": "attachments/ev.txt",
                        "media_type": "text/plain",
                        "size_bytes": 10,
                    }
                ],
                "relations": [
                    {
                        "from_entity_type": "function",
                        "from_entity_id": "fn_v1",
                        "to_entity_type": "structure",
                        "to_entity_id": "struct_v1",
                        "relation_type": "uses_structure",
                    }
                ],
            },
        }
        imported = service.import_bundle(self.sandbox.project, legacy_v1, replace_existing=True, input_path=self.sandbox.root / "legacy-v1.json")
        self.assertEqual(imported["counts"]["functions"], 1)

        with self.sandbox.open_database() as database:
            records = RecordService(database, self.sandbox.project)
            note = records.upsert_record(RecordWrite("note", {"slug": "attached", "title": "Attached"}))
            GenericEvidenceService(database, self.sandbox.project).create_evidence(
                GenericEvidenceWrite("note", note.record_id, "file", "Attachment", attachment_path="attachments/a.txt", media_type="text/plain", size_bytes=5)
            )
            second = records.upsert_record(RecordWrite("note", {"slug": "linked", "title": "Linked"}))
            GenericRelationService(database, self.sandbox.project).create_relation(
                GenericRelationWrite("note", note.record_id, "note", second.record_id, "related_to")
            )
        bundle = service.export_bundle(self.sandbox.project)
        self.assertEqual(bundle["counts"]["attachments"], 1)
        self.assertEqual(bundle["records"]["attachments"][0]["relative_path"], "attachments/a.txt")

    def test_legacy_import_detection_and_full_entity_mapping(self) -> None:
        importer = LegacyDatabaseImporter()
        with self.assertRaisesRegex(LegacyImportValidationError, "legacy database not found"):
            importer.import_legacy_database(self.sandbox.project, self.sandbox.root / "missing.db")

        empty_db = self.sandbox.root / "empty-legacy.db"
        with self.sandbox.open_database():
            pass
        from mcp_memory.storage import open_database

        with open_database(empty_db) as database:
            bootstrap_project_database(database)
        with self.assertRaisesRegex(LegacyImportValidationError, "does not contain project data"):
            importer.import_legacy_database(self.sandbox.project, empty_db)

        multi_db = self.sandbox.root / "multi-legacy.db"
        with open_database(multi_db) as database:
            bootstrap_project_database(database)
            FunctionService(database).upsert_function(
                function_write_from_payload(
                    "p1",
                    {
                        "binary_id": "bin",
                        "function_id": "fn1",
                        "address": "0x1",
                        "raw_name": "sub_1",
                        "current_name": "fn1",
                        "summary": "summary",
                        "behavior_description": "behavior",
                    },
                )
            )
            FunctionService(database).upsert_function(
                function_write_from_payload(
                    "p2",
                    {
                        "binary_id": "bin",
                        "function_id": "fn2",
                        "address": "0x2",
                        "raw_name": "sub_2",
                        "current_name": "fn2",
                        "summary": "summary",
                        "behavior_description": "behavior",
                    },
                )
            )
        with self.assertRaisesRegex(LegacyImportValidationError, "multiple project_ids"):
            importer.import_legacy_database(self.sandbox.project, multi_db)

        source_db = self.sandbox.root / "full-legacy.db"
        with open_database(source_db) as database:
            bootstrap_project_database(database)
            FunctionService(database).upsert_function(
                function_write_from_payload(
                    "legacy-project",
                    {
                        "binary_id": "bin",
                        "function_id": "fn_full",
                        "address": "0x10",
                        "raw_name": "sub_10",
                        "current_name": "fn_full",
                        "summary": "summary",
                        "behavior_description": "behavior",
                    },
                )
            )
            StructureService(database).upsert_structure(
                structure_write_from_payload(
                    "legacy-project",
                    {
                        "binary_id": "bin",
                        "structure_id": "struct_full",
                        "raw_name": "raw",
                        "current_name": "struct_full",
                        "summary": "summary",
                        "fields": [{"name": "field", "offset": "0x0", "data_type": "int"}],
                    },
                )
            )
            GlobalHypothesisService(database).upsert_hypothesis(
                global_hypothesis_write_from_payload(
                    "legacy-project",
                    {
                        "hypothesis_id": "gh_full",
                        "title": "Hypothesis",
                        "statement": "Statement",
                        "status": "confirmed",
                    },
                )
            )
            EvidenceService(database).create_evidence(
                evidence_write_from_payload(
                    "legacy-project",
                    {
                        "evidence_id": "e_missing",
                        "entity_type": "function",
                        "entity_id": "missing",
                        "evidence_type": "note",
                        "description": "Skipped",
                    },
                )
            )
            database.connection.execute(
                """
                INSERT INTO relations (
                  relation_id, project_id, from_entity_type, from_entity_id, to_entity_type, to_entity_id,
                  relation_type, created_at, created_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("rel_unknown", "legacy-project", "function", "fn_full", "structure", "struct_full", "custom", "2026-01-01T00:00:00+00:00", "tester"),
            )
            database.connection.commit()
        result = importer.import_legacy_database(self.sandbox.project, source_db, replace_existing=True)
        self.assertEqual(result["source_project_id"], "legacy-project")
        self.assertEqual(result["counts"]["records"], 3)
        self.assertEqual(result["counts"]["relations"], 1)
        self.assertEqual(result["counts"]["evidence"], 0)
        with self.sandbox.open_database() as database:
            records = RecordService(database, self.sandbox.project)
            self.assertIsNotNone(records.get_record("structure", "struct_full"))
            self.assertIsNotNone(records.get_record("hypothesis", "gh_full"))
            relations = GenericRelationService(database, self.sandbox.project).list_relations()
            self.assertEqual(relations[0].relation_type, "related_to")

    def test_schema_records_and_generic_relation_validation_edges(self) -> None:
        with self.assertRaisesRegex(SchemaValidationError, "unsupported widget"):
            ProjectSchema.from_dict({"entity_types": [{"name": "bad", "fields": [{"name": "x", "label": "X", "widget": "bad"}]}]})
        with self.assertRaisesRegex(SchemaValidationError, "must define options"):
            ProjectSchema.from_dict({"entity_types": [{"name": "bad", "fields": [{"name": "state", "label": "State", "widget": "enum"}]}]})
        with self.assertRaisesRegex(SchemaValidationError, "points to unknown field"):
            ProjectSchema.from_dict({"entity_types": [{"name": "bad", "fields": [{"name": "title", "label": "Title"}], "title_field": "missing"}]})
        with self.assertRaisesRegex(SchemaValidationError, "references unknown search/tag field"):
            ProjectSchema.from_dict({"entity_types": [{"name": "bad", "fields": [{"name": "title", "label": "Title"}], "search_fields": ["missing"]}]})
        with self.assertRaisesRegex(SchemaValidationError, "must define from and to"):
            ProjectSchema.from_dict({"entity_types": [{"name": "a", "fields": [{"name": "title", "label": "Title"}]}], "relation_types": [{"name": "rel", "from": [], "to": ["a"]}]})
        with self.assertRaisesRegex(SchemaValidationError, "unknown entity type"):
            ProjectSchema.from_dict({"entity_types": [{"name": "a", "fields": [{"name": "title", "label": "Title"}]}], "relation_types": [{"name": "rel", "from": ["a"], "to": ["missing"]}]})
        with self.assertRaisesRegex(SchemaValidationError, "schema must define"):
            ProjectSchema.from_dict({"entity_types": []})
        with self.assertRaisesRegex(SchemaValidationError, "must be unique"):
            ProjectSchema.from_dict(
                {
                    "entity_types": [
                        {"name": "a", "fields": [{"name": "title", "label": "Title"}]},
                        {"name": "a", "fields": [{"name": "title", "label": "Title"}]},
                    ]
                }
            )
        with self.assertRaisesRegex(SchemaValidationError, "relation type names must be unique"):
            ProjectSchema.from_dict(
                {
                    "entity_types": [{"name": "a", "fields": [{"name": "title", "label": "Title"}]}],
                    "relation_types": [
                        {"name": "rel", "from": ["a"], "to": ["a"]},
                        {"name": "rel", "from": ["a"], "to": ["a"]},
                    ],
                }
            )
        with self.assertRaisesRegex(SchemaValidationError, "name is required"):
            FieldDefinition.from_dict({"label": "Missing"})
        schema_file = self.sandbox.root / "saved-schema.json"
        save_project_schema(
            schema_file,
            ProjectSchema.from_dict({"entity_types": [{"name": "saved", "fields": [{"name": "title", "label": "Title", "description": "desc"}]}]}),
        )
        self.assertIn("description", schema_file.read_text(encoding="utf-8"))

        typed_schema = {
            "schema_version": "1",
            "entity_types": [
                {
                    "name": "typed",
                    "label": "Typed",
                    "fields": [
                        {"name": "slug", "label": "Slug", "widget": "text"},
                        {"name": "title", "label": "Title", "widget": "text"},
                        {"name": "summary", "label": "Summary", "widget": "textarea"},
                        {"name": "count", "label": "Count", "widget": "number"},
                        {"name": "flag", "label": "Flag", "widget": "bool"},
                        {"name": "state", "label": "State", "widget": "enum", "options": ["open", "done"]},
                        {"name": "tags", "label": "Tags", "widget": "tags"},
                        {"name": "meta", "label": "Meta", "widget": "json"},
                    ],
                    "required": ["title"],
                    "title_field": "title",
                    "summary_field": "summary",
                    "slug_field": "slug",
                    "search_fields": ["meta", "summary"],
                    "tag_fields": ["tags"],
                },
                {"name": "target", "label": "Target", "fields": [{"name": "title", "label": "Title"}], "title_field": "title"},
            ],
            "relation_types": [{"name": "typed_to_target", "label": "Typed To Target", "from": ["typed"], "to": ["target"], "directed": True}],
        }
        copy_schema_payload(self.sandbox.project.schema_path, typed_schema)
        with self.sandbox.open_database() as database:
            records = RecordService(database, self.sandbox.project)
            with self.assertRaisesRegex(RecordValidationError, "unknown entity type"):
                records.upsert_record(RecordWrite("missing", {"title": "x"}))
            with self.assertRaisesRegex(RecordValidationError, "payload must be an object"):
                records.upsert_record(RecordWrite("typed", []))
            with self.assertRaisesRegex(RecordValidationError, "title is required"):
                records.upsert_record(RecordWrite("typed", {"title": ""}))
            with self.assertRaisesRegex(RecordValidationError, "count must be a number"):
                records.upsert_record(RecordWrite("typed", {"title": "Bad", "count": "many"}))
            with self.assertRaisesRegex(RecordValidationError, "flag must be a boolean"):
                records.upsert_record(RecordWrite("typed", {"title": "Bad", "flag": "true"}))
            with self.assertRaisesRegex(RecordValidationError, "state must be one of"):
                records.upsert_record(RecordWrite("typed", {"title": "Bad", "state": "closed"}))
            with self.assertRaisesRegex(RecordValidationError, "tags fields must be strings or arrays"):
                records.upsert_record(RecordWrite("typed", {"title": "Bad", "tags": {"bad": "tag"}}))
            typed = records.upsert_record(
                RecordWrite(
                    "typed",
                    {
                        "slug": "typed-one",
                        "title": "Typed One",
                        "summary": None,
                        "count": 2,
                        "flag": True,
                        "state": "open",
                        "tags": "alpha, beta",
                        "meta": {"nested": ["needle"]},
                    },
                )
            )
            target = records.upsert_record(RecordWrite("target", {"title": "Target One"}))
            self.assertEqual(typed.summary, "")
            self.assertEqual(typed.payload["tags"], ["alpha", "beta"])
            with self.assertRaisesRegex(RecordValidationError, "record not found"):
                records.archive_record("typed", "missing")
            archived = records.archive_record("typed", typed.record_id)
            self.assertEqual(records.archive_record("typed", typed.record_id).record_id, archived.record_id)
            active = records.upsert_record(RecordWrite("typed", {"slug": "typed-two", "title": "Typed Two", "flag": True, "state": "open"}))

            relations = GenericRelationService(database, self.sandbox.project)
            with self.assertRaisesRegex(GenericRelationValidationError, "does not allow"):
                relations.create_relation(GenericRelationWrite("target", target.record_id, "typed", active.record_id, "typed_to_target"))
            with self.assertRaisesRegex(GenericRelationValidationError, "from record not found"):
                relations.create_relation(GenericRelationWrite("typed", "missing", "target", target.record_id, "typed_to_target"))
            with self.assertRaisesRegex(GenericRelationValidationError, "to record not found"):
                relations.create_relation(GenericRelationWrite("typed", active.record_id, "target", "missing", "typed_to_target"))
            with self.assertRaisesRegex(GenericRelationValidationError, "direction must be"):
                relations.list_relations(direction="sideways")
            with self.assertRaisesRegex(GenericRelationValidationError, "record not found"):
                relations.list_relations("typed", "missing")
            with self.assertRaisesRegex(GenericRelationValidationError, "hops must be"):
                relations.traverse_related("typed", archived.record_id, hops=3)
            with self.assertRaisesRegex(GenericRelationValidationError, "record not found"):
                relations.traverse_related("typed", "missing")
            relation = relations.create_relation(GenericRelationWrite("typed", active.record_id, "target", target.record_id, "typed_to_target"))
            self.assertEqual(relations.list_relations("typed", active.record_id, "out")[0].relation_id, relation.relation_id)
            self.assertEqual(relations.list_relations("target", target.record_id, "in")[0].relation_id, relation.relation_id)
            self.assertEqual(len(relations.traverse_related("typed", active.record_id, hops=1)), 1)

    def test_template_fallback_and_badges(self) -> None:
        fallback = gui_templates._FallbackTemplate("{{ plain }} {{ safe|safe }}")
        self.assertEqual(fallback.render(plain="<x>", safe="<b>"), "&lt;x&gt; <b>")
        renderer = gui_templates.TemplateRenderer()
        renderer._env = None
        self.assertIn("Body", renderer.render("generic_shell.html", header_html="<h1>Header</h1>", body_html="<p>Body</p>"))
        self.assertIn("Function", gui_render.entity_type_badge("function"))
