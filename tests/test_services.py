from __future__ import annotations

import unittest

from tests.support import ProjectSandbox

from mcp_memory.domain import (
    EvidenceWrite,
    FunctionWrite,
    GlobalHypothesisWrite,
    HypothesisItem,
    ObservedFact,
    StructureMember,
    StructureWrite,
)
from mcp_memory.services import (
    EvidenceService,
    EvidenceValidationError,
    FunctionService,
    FunctionValidationError,
    GlobalHypothesisService,
    GlobalHypothesisValidationError,
    PendingChangeService,
    PendingChangeValidationError,
    ProjectService,
    RelationService,
    RelationValidationError,
    RelationWrite,
    SearchQuery,
    SearchService,
    StructureService,
    StructureValidationError,
)
from mcp_memory.storage import bootstrap_project_database


class ServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sandbox = ProjectSandbox()

    def tearDown(self) -> None:
        self.sandbox.cleanup()

    def _function_write(self, function_id: str = "fn_main", address: str = "0x401000", allow_conflict: bool = False) -> FunctionWrite:
        return FunctionWrite(
            project_id="test-project",
            binary_id="bin-main",
            function_id=function_id,
            address=address,
            raw_name=f"sub_{address[2:]}",
            current_name=function_id,
            summary="Summary",
            behavior_description="Behavior",
            tags=["tag1"],
            observed_facts=[ObservedFact(fact="fact one", source_origin="test")],
            hypotheses=[HypothesisItem(statement="hypothesis one", source_origin="test")],
            source_origin="test",
            created_by="tester",
            updated_by="tester",
            allow_conflict=allow_conflict,
        )

    def test_storage_bootstrap_is_idempotent_and_database_context_manager_closes(self) -> None:
        database = self.sandbox.open_database()
        try:
            bootstrap_project_database(database)
        finally:
            database.close()
        with self.sandbox.open_database() as database:
            row = database.connection.execute(
                "SELECT COUNT(*) AS count FROM schema_migrations WHERE version = '001_initial'"
            ).fetchone()
            self.assertEqual(row["count"], 1)

    def test_project_service_update_project_and_validation(self) -> None:
        service = ProjectService(self.sandbox.registry)
        with self.assertRaisesRegex(ValueError, "between 1 and 65535"):
            service.create_project(
                project_id="bad-port-project",
                display_name="Bad Port",
                project_root=self.sandbox.root / "bad-port-project",
                http_port=70000,
                mcp_port=30002,
            )

        updated = service.update_project(
            project_id="test-project",
            display_name="Updated Project",
            write_mode="auto",
            http_host="127.0.0.2",
            http_port=28765,
            mcp_host="127.0.0.3",
            mcp_port=29876,
        )
        reloaded = self.sandbox.registry.get_project("test-project")
        self.assertEqual(updated.display_name, "Updated Project")
        self.assertEqual(updated.write_mode, "auto")
        self.assertEqual(updated.http_host, "127.0.0.2")
        self.assertEqual(updated.http_port, 28765)
        self.assertEqual(updated.mcp_host, "127.0.0.3")
        self.assertEqual(updated.mcp_port, 29876)
        self.assertIsNotNone(reloaded)
        self.assertEqual(reloaded.project_root, self.sandbox.project_root)
        self.assertEqual(reloaded.database_path, self.sandbox.project.database_path)

        invalid_cases = [
            {"display_name": " ", "write_mode": "auto", "http_host": "127.0.0.1", "http_port": 30001, "mcp_host": "127.0.0.1", "mcp_port": 30002},
            {"display_name": "Valid", "write_mode": "broken", "http_host": "127.0.0.1", "http_port": 30001, "mcp_host": "127.0.0.1", "mcp_port": 30002},
            {"display_name": "Valid", "write_mode": "auto", "http_host": " ", "http_port": 30001, "mcp_host": "127.0.0.1", "mcp_port": 30002},
            {"display_name": "Valid", "write_mode": "auto", "http_host": "127.0.0.1", "http_port": 30001, "mcp_host": " ", "mcp_port": 30002},
            {"display_name": "Valid", "write_mode": "auto", "http_host": "127.0.0.1", "http_port": 0, "mcp_host": "127.0.0.1", "mcp_port": 30002},
            {"display_name": "Valid", "write_mode": "auto", "http_host": "127.0.0.1", "http_port": 70000, "mcp_host": "127.0.0.1", "mcp_port": 30002},
            {"display_name": "Valid", "write_mode": "auto", "http_host": "127.0.0.1", "http_port": 30001, "mcp_host": "127.0.0.1", "mcp_port": 30001},
        ]
        for case in invalid_cases:
            with self.assertRaises(ValueError):
                service.update_project(project_id="test-project", **case)

        with self.assertRaises(ValueError):
            service.update_project(
                project_id="missing-project",
                display_name="Valid",
                write_mode="auto",
                http_host="127.0.0.1",
                http_port=30001,
                mcp_host="127.0.0.1",
                mcp_port=30002,
            )

    def test_project_service_delete_project_and_missing_error(self) -> None:
        service = ProjectService(self.sandbox.registry)
        service.delete_project("test-project")
        self.assertIsNone(self.sandbox.registry.get_project("test-project"))

        with self.assertRaises(ValueError):
            service.delete_project("missing-project")

    def test_function_service_upsert_get_list(self) -> None:
        with self.sandbox.open_database() as database:
            service = FunctionService(database)
            created = service.upsert_function(self._function_write())
            loaded = service.get_function("test-project", "bin-main", "fn_main")
            listing = service.list_functions("test-project", "bin-main")
            self.assertEqual(created.function_id, "fn_main")
            self.assertEqual(loaded.current_name, "fn_main")
            self.assertEqual(len(listing), 1)

    def test_function_service_rejects_invalid_and_conflicting_data(self) -> None:
        with self.sandbox.open_database() as database:
            service = FunctionService(database)
            with self.assertRaises(FunctionValidationError):
                service.upsert_function(self._function_write(address="not-hex"))
            service.upsert_function(self._function_write(function_id="fn_main", address="0x401000"))
            with self.assertRaises(FunctionValidationError):
                service.upsert_function(self._function_write(function_id="fn_other", address="0x401000"))
            service.upsert_function(self._function_write(function_id="fn_other", address="0x401000", allow_conflict=True))
            duplicates = database.connection.execute(
                "SELECT COUNT(*) AS count FROM duplicate_candidates"
            ).fetchone()
            self.assertEqual(duplicates["count"], 2)

    def test_function_service_update_and_validation_branches(self) -> None:
        with self.sandbox.open_database() as database:
            service = FunctionService(database)
            original = self._function_write()
            service.upsert_function(original)

            updated = self._function_write()
            updated.current_name = "renamed_fn"
            updated.important_variables = ["ctx"]
            updated.used_apis = ["CreateFileA"]
            updated.strings = ["hello"]
            updated.constants = ["0x20"]
            updated.confidence = 0.7
            updated.tags = ["tag1", "tag2"]
            updated.observed_facts = [ObservedFact(fact="fact one", source_origin="test")]
            updated.hypotheses = [HypothesisItem(statement="hypothesis one", confidence=0.5, source_origin="test")]
            loaded = service.upsert_function(updated)
            self.assertEqual(loaded.current_name, "renamed_fn")
            self.assertEqual(len(service.list_functions("test-project", "bin-main")), 1)
            self.assertIsNone(service.get_function("test-project", "bin-main", "missing"))

            invalid_cases = [
                self._function_write(function_id="fn_empty_summary"),
                self._function_write(function_id="fn_empty_behavior"),
                self._function_write(function_id="fn_bad_var"),
                self._function_write(function_id="fn_bad_api"),
                self._function_write(function_id="fn_bad_string"),
                self._function_write(function_id="fn_bad_constant"),
                self._function_write(function_id="fn_bad_tags"),
                self._function_write(function_id="fn_bad_facts"),
                self._function_write(function_id="fn_bad_hypos"),
                self._function_write(function_id="fn_bad_hypo_conf"),
                self._function_write(function_id="fn_bad_conf"),
                self._function_write(function_id="fn_blank_addr", address=" "),
            ]
            invalid_cases[0].summary = " "
            invalid_cases[1].behavior_description = " "
            invalid_cases[2].important_variables = [" "]
            invalid_cases[3].used_apis = [" "]
            invalid_cases[4].strings = [" "]
            invalid_cases[5].constants = [" "]
            invalid_cases[6].tags = ["x"] * 101
            invalid_cases[7].observed_facts = [ObservedFact(fact="x", source_origin="test")] * 101
            invalid_cases[8].hypotheses = [HypothesisItem(statement="x", source_origin="test")] * 101
            invalid_cases[9].hypotheses = [HypothesisItem(statement="x", confidence=1.5, source_origin="test")]
            invalid_cases[10].confidence = 1.5

            for payload in invalid_cases:
                with self.assertRaises(FunctionValidationError):
                    service.upsert_function(payload)

    def test_structure_service_upsert_and_validation(self) -> None:
        with self.sandbox.open_database() as database:
            service = StructureService(database)
            record = service.upsert_structure(
                StructureWrite(
                    project_id="test-project",
                    binary_id="bin-main",
                    structure_id="struct_ctx",
                    raw_name="ctx_t",
                    current_name="ctx_t",
                    summary="State structure",
                    fields=[StructureMember(name="mode", offset="0x0", data_type="uint32_t")],
                    tags=["parser"],
                    observed_facts=[ObservedFact(fact="Used by fn_main")],
                    hypotheses=[HypothesisItem(statement="Shared across helpers")],
                    source_origin="test",
                    created_by="tester",
                    updated_by="tester",
                )
            )
            loaded = service.get_structure("test-project", "struct_ctx")
            listing = service.list_structures("test-project", "bin-main")
            self.assertEqual(record.structure_id, "struct_ctx")
            self.assertEqual(loaded.current_name, "ctx_t")
            self.assertEqual(len(listing), 1)
            with self.assertRaises(StructureValidationError):
                service.upsert_structure(
                    StructureWrite(
                        project_id="test-project",
                        binary_id="bin-main",
                        structure_id="broken",
                        raw_name="raw",
                        current_name="current",
                        summary="x" * 5000,
                        source_origin="test",
                        created_by="tester",
                        updated_by="tester",
                    )
                )

    def test_structure_service_lists_all_and_rejects_validation_edges(self) -> None:
        with self.sandbox.open_database() as database:
            service = StructureService(database)
            service.upsert_structure(
                StructureWrite(
                    project_id="test-project",
                    binary_id="bin-main",
                    structure_id="struct_ctx",
                    raw_name="ctx_t",
                    current_name="ctx_t",
                    summary="Summary",
                    source_origin="test",
                    created_by="tester",
                    updated_by="tester",
                )
            )
            self.assertEqual(len(service.list_structures("test-project")), 1)
            self.assertIsNone(service.get_structure("test-project", "missing"))

            invalid_cases = [
                StructureWrite(project_id="test-project", binary_id="bin-main", structure_id="s1", raw_name="raw", current_name="current", summary="Summary", tags=["x"] * 101, source_origin="test", created_by="tester", updated_by="tester"),
                StructureWrite(project_id="test-project", binary_id="bin-main", structure_id="s2", raw_name="raw", current_name="current", summary="Summary", observed_facts=[ObservedFact(fact="x")] * 101, source_origin="test", created_by="tester", updated_by="tester"),
                StructureWrite(project_id="test-project", binary_id="bin-main", structure_id="s3", raw_name="raw", current_name="current", summary="Summary", hypotheses=[HypothesisItem(statement="x")] * 101, source_origin="test", created_by="tester", updated_by="tester"),
                StructureWrite(project_id="test-project", binary_id="bin-main", structure_id="s4", raw_name="raw", current_name="current", summary="Summary", fields=[StructureMember(name=" ", offset="0x0", data_type="int")], source_origin="test", created_by="tester", updated_by="tester"),
                StructureWrite(project_id="test-project", binary_id="bin-main", structure_id="s5", raw_name="raw", current_name="current", summary="Summary", fields=[StructureMember(name="field", offset=" ", data_type="int")], source_origin="test", created_by="tester", updated_by="tester"),
                StructureWrite(project_id="test-project", binary_id="bin-main", structure_id="s6", raw_name="raw", current_name="current", summary="Summary", fields=[StructureMember(name="field", offset="0x0", data_type=" ")], source_origin="test", created_by="tester", updated_by="tester"),
                StructureWrite(project_id="test-project", binary_id="bin-main", structure_id="s7", raw_name="raw", current_name="current", summary="Summary", fields=[StructureMember(name="field", offset="0x0", data_type="int", comment=" ")] , source_origin="test", created_by="tester", updated_by="tester"),
                StructureWrite(project_id="test-project", binary_id="bin-main", structure_id="s8", raw_name="raw", current_name="current", summary="Summary", hypotheses=[HypothesisItem(statement="x", confidence=2.0)], source_origin="test", created_by="tester", updated_by="tester"),
            ]
            for payload in invalid_cases:
                with self.assertRaises(StructureValidationError):
                    service.upsert_structure(payload)

    def test_global_hypothesis_service_upsert_and_validation(self) -> None:
        with self.sandbox.open_database() as database:
            service = GlobalHypothesisService(database)
            record = service.upsert_hypothesis(
                GlobalHypothesisWrite(
                    project_id="test-project",
                    hypothesis_id="gh1",
                    title="Title",
                    statement="Statement",
                    tags=["parser"],
                    observed_facts=[ObservedFact(fact="Observed evidence")],
                    source_origin="test",
                    created_by="tester",
                    updated_by="tester",
                )
            )
            loaded = service.get_hypothesis("test-project", "gh1")
            listing = service.list_hypotheses("test-project")
            self.assertEqual(record.hypothesis_id, "gh1")
            self.assertEqual(loaded.title, "Title")
            self.assertEqual(len(listing), 1)
            with self.assertRaises(GlobalHypothesisValidationError):
                service.upsert_hypothesis(
                    GlobalHypothesisWrite(
                        project_id="test-project",
                        hypothesis_id="gh2",
                        title="",
                        statement="Statement",
                    )
                )

    def test_global_hypothesis_service_update_missing_and_validation_edges(self) -> None:
        with self.sandbox.open_database() as database:
            service = GlobalHypothesisService(database)
            first = GlobalHypothesisWrite(
                project_id="test-project",
                hypothesis_id="gh1",
                title="Title",
                statement="Statement",
                source_origin="test",
                created_by="tester",
                updated_by="tester",
            )
            service.upsert_hypothesis(first)
            updated = GlobalHypothesisWrite(
                project_id="test-project",
                hypothesis_id="gh1",
                title="Updated",
                statement="Updated statement",
                confidence=0.6,
                binary_id="bin-main",
                tags=["parser"],
                observed_facts=[ObservedFact(fact="new fact")],
                source_origin="test",
                created_by="tester",
                updated_by="tester",
            )
            loaded = service.upsert_hypothesis(updated)
            self.assertEqual(loaded.title, "Updated")
            self.assertIsNone(service.get_hypothesis("test-project", "missing"))

            invalid_cases = [
                GlobalHypothesisWrite(project_id="test-project", hypothesis_id="gh2", title="Title", statement="Statement", confidence=1.5),
                GlobalHypothesisWrite(project_id="test-project", hypothesis_id="gh3", title="Title", statement="Statement", observed_facts=[ObservedFact(fact=" ")]),
                GlobalHypothesisWrite(project_id="test-project", hypothesis_id="gh4", title="Title", statement="Statement", tags=[" "]),
                GlobalHypothesisWrite(project_id="test-project", hypothesis_id="gh5", title=" ", statement="Statement"),
            ]
            for payload in invalid_cases:
                with self.assertRaises(GlobalHypothesisValidationError):
                    service.upsert_hypothesis(payload)

    def test_evidence_service_create_list_and_validation(self) -> None:
        with self.sandbox.open_database() as database:
            service = EvidenceService(database)
            record = service.create_evidence(
                EvidenceWrite(
                    project_id="test-project",
                    evidence_id="e1",
                    entity_type="function",
                    entity_id="fn_main",
                    evidence_type="block",
                    description="Evidence description",
                    attachment_path="attachments/e1.txt",
                    media_type="text/plain",
                    size_bytes=10,
                    source_origin="test",
                    created_by="tester",
                )
            )
            items = service.list_evidence("test-project", "function", "fn_main")
            self.assertEqual(record.evidence_id, "e1")
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0].attachment_path, "attachments/e1.txt")
            with self.assertRaises(EvidenceValidationError):
                service.create_evidence(
                    EvidenceWrite(
                        project_id="test-project",
                        evidence_id="e2",
                        entity_type="function",
                        entity_id="fn_main",
                        evidence_type="block",
                        description="Evidence description",
                        size_bytes=-1,
                    )
                )

    def test_evidence_service_without_attachment_and_validation_edges(self) -> None:
        with self.sandbox.open_database() as database:
            service = EvidenceService(database)
            record = service.create_evidence(
                EvidenceWrite(
                    project_id="test-project",
                    evidence_id="e2",
                    entity_type="structure",
                    entity_id="struct_ctx",
                    evidence_type="xref",
                    description="Description",
                    created_by="tester",
                    source_origin="test",
                )
            )
            self.assertIsNone(record.attachment_id)
            self.assertEqual(len(service.list_evidence("test-project", "structure", "struct_ctx")), 1)

            invalid_cases = [
                EvidenceWrite(project_id="test-project", evidence_id="e3", entity_type="function", entity_id="fn_main", evidence_type="block", description="Description", excerpt=" "),
                EvidenceWrite(project_id="test-project", evidence_id="e4", entity_type="function", entity_id="fn_main", evidence_type="block", description="Description", attachment_path=" "),
            ]
            for payload in invalid_cases:
                with self.assertRaises(EvidenceValidationError):
                    service.create_evidence(payload)

    def test_relation_service_create_list_traverse_and_validation(self) -> None:
        with self.sandbox.open_database() as database:
            service = RelationService(database)
            first = service.create_relation(
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
            service.create_relation(
                RelationWrite(
                    project_id="test-project",
                    from_entity_type="structure",
                    from_entity_id="struct_ctx",
                    to_entity_type="global_hypothesis",
                    to_entity_id="gh1",
                    relation_type="supports",
                    created_by="tester",
                )
            )
            both = service.list_relations("test-project", "function", "fn_main", direction="both")
            related_one = service.traverse_related("test-project", "function", "fn_main", hops=1)
            related_two = service.traverse_related("test-project", "function", "fn_main", hops=2)
            self.assertEqual(first.from_entity_id, "fn_main")
            self.assertEqual(len(both), 1)
            self.assertEqual(len(related_one), 1)
            self.assertEqual(len(related_two), 2)
            with self.assertRaises(RelationValidationError):
                service.list_relations("test-project", "function", "fn_main", direction="sideways")
            with self.assertRaises(RelationValidationError):
                service.traverse_related("test-project", "function", "fn_main", hops=3)
            inbound = service.list_relations("test-project", "structure", "struct_ctx", direction="in")
            outbound = service.list_relations("test-project", "function", "fn_main", direction="out")
            self.assertEqual(len(inbound), 1)
            self.assertEqual(len(outbound), 1)

    def test_relation_service_rejects_blank_fields(self) -> None:
        with self.sandbox.open_database() as database:
            service = RelationService(database)
            with self.assertRaises(RelationValidationError):
                service.create_relation(
                    RelationWrite(
                        project_id="test-project",
                        from_entity_type="function",
                        from_entity_id="fn_main",
                        to_entity_type="structure",
                        to_entity_id="struct_ctx",
                        relation_type="uses",
                        created_by=" ",
                    )
                )

    def test_search_service_filters_by_query_type_tag_binary_and_address(self) -> None:
        with self.sandbox.open_database() as database:
            function_service = FunctionService(database)
            structure_service = StructureService(database)
            function_service.upsert_function(self._function_write(function_id="fn_main", address="0x401000"))
            structure_service.upsert_structure(
                StructureWrite(
                    project_id="test-project",
                    binary_id="bin-main",
                    structure_id="struct_ctx",
                    raw_name="ctx_t",
                    current_name="ctx_t",
                    summary="Parser context",
                    tags=["parser"],
                    source_origin="test",
                    created_by="tester",
                    updated_by="tester",
                )
            )
            search = SearchService(database)
            self.assertEqual(len(search.search(SearchQuery(project_id="test-project", query_text="fn_main"))), 1)
            self.assertEqual(len(search.search(SearchQuery(project_id="test-project", entity_types=["structure"]))), 1)
            self.assertEqual(len(search.search(SearchQuery(project_id="test-project", binary_id="bin-main"))), 2)
            self.assertEqual(len(search.search(SearchQuery(project_id="test-project", tag="parser"))), 1)
            self.assertEqual(len(search.search(SearchQuery(project_id="test-project", address="401000"))), 1)

    def test_pending_change_service_create_confirm_and_reject(self) -> None:
        with self.sandbox.open_database() as database:
            service = PendingChangeService(database)
            created = service.create_pending_change(
                "test-project",
                "function",
                "fn_pending",
                "upsert_function",
                {
                    "binary_id": "bin-main",
                    "function_id": "fn_pending",
                    "address": "0x401200",
                    "raw_name": "sub_401200",
                    "current_name": "pending_fn",
                    "summary": "Summary",
                    "behavior_description": "Behavior",
                    "created_by": "tester",
                    "updated_by": "tester",
                },
                created_by="tester",
            )
            listed = service.list_pending_changes("test-project")
            self.assertEqual(len(listed), 1)
            confirmed = service.confirm_change("test-project", created.pending_change_id, confirmed_by="tester", actor_type="user")
            self.assertEqual(confirmed["pending_change"].status, "confirmed")
            function = FunctionService(database).get_function("test-project", "bin-main", "fn_pending")
            self.assertIsNotNone(function)

            rejected = service.create_pending_change(
                "test-project",
                "function",
                "fn_rejected",
                "upsert_function",
                {
                    "binary_id": "bin-main",
                    "function_id": "fn_rejected",
                    "address": "0x401300",
                    "raw_name": "sub_401300",
                    "current_name": "rejected_fn",
                    "summary": "Summary",
                    "behavior_description": "Behavior",
                    "created_by": "tester",
                    "updated_by": "tester",
                },
                created_by="tester",
            )
            rejected_result = service.reject_change("test-project", rejected.pending_change_id, rejected_by="tester")
            self.assertEqual(rejected_result.status, "rejected")
            self.assertEqual(len(service.list_pending_changes("test-project", status=None)), 2)
            self.assertEqual(len(service.list_pending_changes("test-project")), 0)

            with self.assertRaises(PendingChangeValidationError):
                service.confirm_change("test-project", rejected.pending_change_id)

    def test_pending_change_service_other_operations_and_errors(self) -> None:
        with self.sandbox.open_database() as database:
            service = PendingChangeService(database)
            structure_pending = service.create_pending_change(
                "test-project",
                "structure",
                "struct_pending",
                "upsert_structure",
                {
                    "binary_id": "bin-main",
                    "structure_id": "struct_pending",
                    "raw_name": "pending_t",
                    "current_name": "pending_t",
                    "summary": "Summary",
                    "created_by": "tester",
                    "updated_by": "tester",
                },
                created_by="tester",
            )
            hypothesis_pending = service.create_pending_change(
                "test-project",
                "global_hypothesis",
                "gh_pending",
                "upsert_global_hypothesis",
                {
                    "hypothesis_id": "gh_pending",
                    "title": "Title",
                    "statement": "Statement",
                    "created_by": "tester",
                    "updated_by": "tester",
                },
                created_by="tester",
            )
            evidence_pending = service.create_pending_change(
                "test-project",
                "evidence",
                "e_pending",
                "create_evidence",
                {
                    "evidence_id": "e_pending",
                    "entity_type": "function",
                    "entity_id": "fn_main",
                    "evidence_type": "block",
                    "description": "Description",
                    "created_by": "tester",
                },
                created_by="tester",
            )
            relation_pending = service.create_pending_change(
                "test-project",
                "relation",
                "function:fn_main->structure:struct_pending",
                "create_relation",
                {
                    "from_entity_type": "function",
                    "from_entity_id": "fn_main",
                    "to_entity_type": "structure",
                    "to_entity_id": "struct_pending",
                    "relation_type": "uses_structure",
                    "created_by": "tester",
                },
                created_by="tester",
            )

            self.assertEqual(service.confirm_change("test-project", structure_pending.pending_change_id)["applied"].structure_id, "struct_pending")
            self.assertEqual(service.confirm_change("test-project", hypothesis_pending.pending_change_id)["applied"].hypothesis_id, "gh_pending")
            self.assertEqual(service.confirm_change("test-project", evidence_pending.pending_change_id)["applied"].evidence_id, "e_pending")
            self.assertEqual(service.confirm_change("test-project", relation_pending.pending_change_id)["applied"].relation_type, "uses_structure")
            self.assertIsNone(service.get_pending_change("test-project", "missing"))

            bad_operation = service.create_pending_change(
                "test-project",
                "unknown",
                "bad",
                "unsupported_operation",
                {},
                created_by="tester",
            )
            with self.assertRaises(PendingChangeValidationError):
                service.confirm_change("test-project", bad_operation.pending_change_id)
            with self.assertRaises(PendingChangeValidationError):
                service.reject_change("test-project", "missing")
            with self.assertRaises(PendingChangeValidationError):
                service.create_pending_change("test-project", "function", "fn_bad", "upsert_function", {}, created_by=" ")


if __name__ == "__main__":
    unittest.main()
