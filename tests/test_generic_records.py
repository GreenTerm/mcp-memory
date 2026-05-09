from __future__ import annotations

import unittest

from tests.support import ProjectSandbox

from mcp_memory.services import (
    GenericRelationService,
    GenericRelationValidationError,
    GenericRelationWrite,
    GenericEvidenceService,
    GenericEvidenceValidationError,
    GenericEvidenceWrite,
    RecordService,
    RecordValidationError,
    RecordWrite,
    SearchQuery,
    SearchService,
    GenericWorkflowService,
    GenericPendingValidationError,
    ProjectTransferService,
    ProjectArchiveService,
)
from mcp_memory.protocol import (
    ArchiveRecordCommand,
    GetRecordQuery,
    ListEntityTypesQuery,
    ProjectDispatcher,
    UpsertRecordCommand,
)
from mcp_memory.storage import open_database


class GenericRecordTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sandbox = ProjectSandbox()

    def tearDown(self) -> None:
        self.sandbox.cleanup()

    def test_record_service_creates_updates_searches_and_archives_record(self) -> None:
        with self.sandbox.open_database() as database:
            service = RecordService(database, self.sandbox.project)
            created = service.upsert_record(
                RecordWrite(
                    entity_type="note",
                    payload={
                        "slug": "first-note",
                        "title": "First Note",
                        "summary": "Short summary",
                        "body": "Searchable body text",
                        "tags": ["alpha"],
                    },
                    created_by="tester",
                    updated_by="tester",
                )
            )
            self.assertTrue(created.record_id)
            self.assertEqual(created.slug, "first-note")
            self.assertEqual(created.title, "First Note")
            self.assertEqual(service.get_record("note", "first-note").record_id, created.record_id)

            updated = service.upsert_record(
                RecordWrite(
                    entity_type="note",
                    record_id=created.record_id,
                    payload={
                        "slug": "first-note",
                        "title": "Updated Note",
                        "summary": "Updated summary",
                        "body": "Searchable body text",
                        "tags": "alpha\nbeta",
                    },
                    updated_by="tester",
                )
            )
            self.assertEqual(updated.title, "Updated Note")
            self.assertEqual(len(service.list_records("note")), 1)

            results = SearchService(database).search(SearchQuery(project_id=self.sandbox.project.project_id, query_text="Searchable"))
            self.assertEqual(len(results), 1)
            hyphen_results = SearchService(database).search(SearchQuery(project_id=self.sandbox.project.project_id, query_text="alpha-beta"))
            self.assertEqual(len(hyphen_results), 1)
            punctuation_with_tag = SearchService(database).search(
                SearchQuery(project_id=self.sandbox.project.project_id, query_text="!!!", tag="alpha")
            )
            self.assertEqual(len(punctuation_with_tag), 1)
            punctuation_only = SearchService(database).search(
                SearchQuery(project_id=self.sandbox.project.project_id, query_text="!!!")
            )
            self.assertEqual(punctuation_only, [])

            archived = service.archive_record("note", "first-note", archived_by="tester")
            self.assertEqual(archived.status, "archived")
            self.assertIsNone(service.get_record("note", "first-note"))
            self.assertEqual(len(service.list_records("note")), 0)
            self.assertEqual(len(service.list_records("note", include_archived=True)), 1)
            self.assertEqual(SearchService(database).search(SearchQuery(project_id=self.sandbox.project.project_id, query_text="Searchable")), [])

            service.upsert_record(
                RecordWrite(
                    entity_type="note",
                    record_id=created.record_id,
                    payload={
                        "slug": "first-note",
                        "title": "Updated Archived Note",
                        "summary": "Updated archived summary",
                        "body": "Searchable body text",
                    },
                    updated_by="tester",
                )
            )
            self.assertEqual(SearchService(database).search(SearchQuery(project_id=self.sandbox.project.project_id, query_text="Searchable")), [])

    def test_record_service_validates_required_fields_and_slug_uniqueness(self) -> None:
        with self.sandbox.open_database() as database:
            service = RecordService(database, self.sandbox.project)
            with self.assertRaisesRegex(RecordValidationError, "title is required"):
                service.upsert_record(RecordWrite(entity_type="note", payload={"summary": "Missing title"}))

            service.upsert_record(RecordWrite(entity_type="note", payload={"slug": "dup", "title": "One"}))
            with self.assertRaisesRegex(RecordValidationError, "slug must be unique"):
                service.upsert_record(RecordWrite(entity_type="note", payload={"slug": "dup", "title": "Two"}))

    def test_generic_relation_service_enforces_schema_and_traverses(self) -> None:
        with self.sandbox.open_database() as database:
            records = RecordService(database, self.sandbox.project)
            first = records.upsert_record(
                RecordWrite(entity_type="note", payload={"slug": "one", "title": "One"})
            )
            second = records.upsert_record(
                RecordWrite(entity_type="note", payload={"slug": "two", "title": "Two"})
            )
            relations = GenericRelationService(database, self.sandbox.project)
            relation = relations.create_relation(
                GenericRelationWrite(
                    from_entity_type="note",
                    from_record_id=first.record_id,
                    to_entity_type="note",
                    to_record_id=second.record_id,
                    relation_type="related_to",
                    created_by="tester",
                )
            )
            self.assertEqual(relation.relation_type, "related_to")
            self.assertEqual(len(relations.list_relations("note", "one")), 1)
            related = relations.traverse_related("note", "one", hops=1)
            self.assertEqual(related[0]["record_id"], second.record_id)
            self.assertEqual(related[0]["relation_direction"], "out")
            self.assertFalse(related[0]["relation_directed"])
            self.assertEqual(related[0]["from_record_id"], first.record_id)
            self.assertEqual(related[0]["to_record_id"], second.record_id)
            records.archive_record("note", "two", archived_by="tester")
            self.assertEqual(relations.traverse_related("note", "one", hops=1), [])

            with self.assertRaisesRegex(GenericRelationValidationError, "unknown relation type"):
                relations.create_relation(
                    GenericRelationWrite(
                        from_entity_type="note",
                        from_record_id=first.record_id,
                        to_entity_type="note",
                        to_record_id=second.record_id,
                        relation_type="missing",
                    )
                )

    def test_generic_evidence_attaches_to_any_record(self) -> None:
        with self.sandbox.open_database() as database:
            record = RecordService(database, self.sandbox.project).upsert_record(
                RecordWrite(entity_type="note", payload={"slug": "evidence-note", "title": "Evidence Note"})
            )
            evidence_service = GenericEvidenceService(database, self.sandbox.project)
            evidence = evidence_service.create_evidence(
                GenericEvidenceWrite(
                    entity_type="note",
                    record_id=record.record_id,
                    evidence_type="excerpt",
                    description="Important excerpt",
                    excerpt="quoted text",
                    attachment_path="attachments/example.txt",
                    media_type="text/plain",
                    size_bytes=10,
                    created_by="tester",
                )
            )
            self.assertEqual(evidence.record_id, record.record_id)
            listed = evidence_service.list_evidence("note", "evidence-note")
            self.assertEqual(len(listed), 1)
            self.assertEqual(listed[0].attachment_path, "attachments/example.txt")

            with self.assertRaisesRegex(GenericEvidenceValidationError, "record not found"):
                evidence_service.create_evidence(
                    GenericEvidenceWrite(
                        entity_type="note",
                        record_id="missing",
                        evidence_type="excerpt",
                        description="Missing record",
                    )
                )

    def test_project_dispatcher_routes_generic_messages(self) -> None:
        with self.sandbox.open_database() as database:
            dispatcher = ProjectDispatcher(database, self.sandbox.project)
            entity_types = dispatcher.dispatch(ListEntityTypesQuery()).data
            self.assertEqual(entity_types[0]["name"], "note")

            created = dispatcher.dispatch(
                UpsertRecordCommand(
                    entity_type="note",
                    payload={"slug": "dispatch-note", "title": "Dispatch Note"},
                    created_by="tester",
                    updated_by="tester",
                )
            )
            self.assertEqual(created.status, "created")
            record_id = created.data.record_id

            loaded = dispatcher.dispatch(GetRecordQuery("note", "dispatch-note"))
            self.assertEqual(loaded.data.record_id, record_id)

            archived = dispatcher.dispatch(ArchiveRecordCommand("note", "dispatch-note", archived_by="tester"))
            self.assertEqual(archived.data.status, "archived")

    def test_generic_workflow_queues_confirms_and_rejects_changes(self) -> None:
        with self.sandbox.open_database() as database:
            workflow = GenericWorkflowService(database, self.sandbox.project)
            pending = workflow.apply_or_queue(
                "upsert_record",
                {
                    "entity_type": "note",
                    "payload": {"slug": "queued-note", "title": "Queued Note"},
                    "created_by": "tester",
                    "updated_by": "tester",
                },
                created_by="tester",
            )
            self.assertEqual(pending.status, "pending")
            self.assertEqual(len(workflow.list_pending_changes()), 1)

            confirmed = workflow.confirm_change(pending.pending_change_id, confirmed_by="tester", actor_type="user")
            self.assertEqual(confirmed["pending_change"].status, "confirmed")
            self.assertEqual(confirmed["applied"].slug, "queued-note")

            rejected_pending = workflow.create_pending_change(
                "upsert_record",
                {
                    "entity_type": "note",
                    "payload": {"slug": "rejected-note", "title": "Rejected Note"},
                },
                created_by="tester",
            )
            rejected = workflow.reject_change(rejected_pending.pending_change_id, rejected_by="tester")
            self.assertEqual(rejected.status, "rejected")

            with self.assertRaisesRegex(GenericPendingValidationError, "pending change is not in pending status"):
                workflow.confirm_change(rejected_pending.pending_change_id)

    def test_generic_transfer_round_trips_schema_records_relations_and_evidence(self) -> None:
        with self.sandbox.open_database() as database:
            records = RecordService(database, self.sandbox.project)
            first = records.upsert_record(
                RecordWrite(entity_type="note", payload={"slug": "transfer-one", "title": "Transfer One", "body": "portable"})
            )
            second = records.upsert_record(
                RecordWrite(entity_type="note", payload={"slug": "transfer-two", "title": "Transfer Two"})
            )
            GenericRelationService(database, self.sandbox.project).create_relation(
                GenericRelationWrite(
                    from_entity_type="note",
                    from_record_id=first.record_id,
                    to_entity_type="note",
                    to_record_id=second.record_id,
                    relation_type="related_to",
                )
            )
            GenericEvidenceService(database, self.sandbox.project).create_evidence(
                GenericEvidenceWrite(
                    entity_type="note",
                    record_id=first.record_id,
                    evidence_type="excerpt",
                    description="Transfer evidence",
                    excerpt="portable evidence",
                )
            )

        target = self.sandbox.project_service.create_project(
            project_id="transfer-target",
            display_name="Transfer Target",
            project_root=self.sandbox.root / "transfer-target",
            http_port=18766,
            mcp_port=19877,
        )
        transfer = ProjectTransferService()
        bundle = transfer.export_bundle(self.sandbox.project)
        self.assertEqual(bundle["bundle_version"], 2)
        self.assertEqual(bundle["counts"]["records"], 2)

        result = transfer.import_bundle(target, bundle, replace_existing=True)
        self.assertEqual(result["counts"]["records"], 2)
        self.assertEqual(result["counts"]["relations"], 1)
        self.assertEqual(result["counts"]["evidence"], 1)
        with open_database(target.database_path) as database:
            records = RecordService(database, target)
            self.assertEqual(records.get_record("note", "transfer-one").title, "Transfer One")
            self.assertEqual(len(GenericRelationService(database, target).list_relations("note", "transfer-one")), 1)
            self.assertEqual(len(GenericEvidenceService(database, target).list_evidence("note", "transfer-one")), 1)

    def test_backup_restore_preserves_generic_schema_and_records(self) -> None:
        with self.sandbox.open_database() as database:
            RecordService(database, self.sandbox.project).upsert_record(
                RecordWrite(entity_type="note", payload={"slug": "backup-note", "title": "Backup Note"})
            )
        backup_path = self.sandbox.root / "generic-backup.zip"
        restored_root = self.sandbox.root / "generic-restored"
        archive = ProjectArchiveService(self.sandbox.registry)
        archive.create_backup(self.sandbox.project, backup_path)
        restored = archive.restore_backup(
            backup_path,
            restored_root,
            project_id="generic-restored",
            display_name="Generic Restored",
            http_port=18767,
            mcp_port=19878,
        )
        self.assertEqual(restored.schema_path, restored_root / "schema.json")
        self.assertTrue(restored.schema_path.exists())
        with open_database(restored.database_path) as database:
            record = RecordService(database, restored).get_record("note", "backup-note")
            self.assertIsNotNone(record)
            self.assertEqual(record.title, "Backup Note")


if __name__ == "__main__":
    unittest.main()
