from __future__ import annotations

import json
import unittest
import zipfile
from pathlib import Path

from tests.support import ProjectSandbox

from mcp_memory.domain import EvidenceWrite, FunctionWrite, ObservedFact
from mcp_memory.services import (
    EvidenceService,
    FunctionService,
    GenericEvidenceService,
    GenericEvidenceWrite,
    LegacyDatabaseImporter,
    ProjectArchiveService,
    ProjectService,
    ProjectTransferService,
    RecordService,
    RecordWrite,
    RelationService,
    RelationWrite,
)


class TransferAndArchiveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sandbox = ProjectSandbox()
        with self.sandbox.open_database() as database:
            FunctionService(database).upsert_function(
                FunctionWrite(
                    project_id="test-project",
                    binary_id="bin-main",
                    function_id="fn_main",
                    address="0x401000",
                    raw_name="sub_401000",
                    current_name="main_handler",
                    summary="Summary",
                    behavior_description="Behavior",
                    observed_facts=[ObservedFact(fact="fact one", source_origin="test")],
                    created_by="tester",
                    updated_by="tester",
                    source_origin="test",
                )
            )
            EvidenceService(database).create_evidence(
                EvidenceWrite(
                    project_id="test-project",
                    evidence_id="e1",
                    entity_type="function",
                    entity_id="fn_main",
                    evidence_type="block",
                    description="Description",
                    created_by="tester",
                    source_origin="test",
                )
            )
            note = RecordService(database, self.sandbox.project).upsert_record(
                RecordWrite(
                    entity_type="note",
                    payload={
                        "slug": "transfer-note",
                        "title": "Transfer Note",
                        "summary": "Generic record",
                        "body": "Generic transfer body",
                        "tags": ["transfer"],
                    },
                    created_by="tester",
                    updated_by="tester",
                    source_origin="test",
                )
            )
            GenericEvidenceService(database, self.sandbox.project).create_evidence(
                GenericEvidenceWrite(
                    entity_type="note",
                    record_id=note.record_id,
                    evidence_type="excerpt",
                    description="Generic evidence",
                    created_by="tester",
                )
            )

    def tearDown(self) -> None:
        self.sandbox.cleanup()

    def test_export_import_roundtrip(self) -> None:
        transfer = ProjectTransferService()
        export_path = self.sandbox.root / "bundle.json"
        export_result = transfer.export_project(self.sandbox.project, export_path)
        self.assertEqual(export_result["counts"]["records"], 1)
        self.assertTrue(export_path.exists())

        imported_root = self.sandbox.root / "imported_project"
        imported_project = self.sandbox.project_service.create_project(
            "imported-project",
            "Imported Project",
            imported_root,
            18766,
            19877,
        )
        import_result = transfer.import_project(imported_project, export_path, replace_existing=True)
        self.assertEqual(import_result["counts"]["records"], 1)

        with open(import_result["input_path"], "r", encoding="utf-8") as handle:
            bundle = json.load(handle)
        self.assertEqual(bundle["records"]["items"][0]["slug"], "transfer-note")

        with open_database(imported_project.database_path) as database:
            loaded = RecordService(database, imported_project).get_record("note", "transfer-note")
            self.assertIsNotNone(loaded)
            evidence = GenericEvidenceService(database, imported_project).list_evidence("note", loaded.record_id)
            self.assertEqual(len(evidence), 1)

    def test_backup_and_restore_roundtrip(self) -> None:
        attachments_file = self.sandbox.project.attachments_dir / "note.txt"
        attachments_file.write_text("attachment-data", encoding="utf-8")

        archive = ProjectArchiveService(self.sandbox.registry)
        backup_path = self.sandbox.root / "backup.zip"
        backup_result = archive.create_backup(self.sandbox.project, backup_path)
        self.assertEqual(backup_result["file_count"], 3)
        self.assertTrue(backup_path.exists())

        restored_root = self.sandbox.root / "restored_project"
        restored = archive.restore_backup(
            backup_path,
            restored_root,
            project_id="restored-project",
            display_name="Restored Project",
            http_port=20000,
            mcp_port=20001,
        )
        self.assertEqual(restored.project_id, "restored-project")
        self.assertTrue((restored_root / "project.db").exists())
        self.assertTrue((restored_root / "attachments" / "note.txt").exists())
        self.assertIsNotNone(self.sandbox.registry.get_project("restored-project"))

    def test_transfer_and_archive_edge_cases(self) -> None:
        transfer = ProjectTransferService()
        archive = ProjectArchiveService(self.sandbox.registry)

        export_result = transfer.export_project(self.sandbox.project)
        self.assertTrue(Path(export_result["output_path"]).exists())

        with self.assertRaisesRegex(ValueError, "Bundle schema must be an object"):
            transfer.import_bundle(self.sandbox.project, {"bundle_version": 2, "records": {}}, replace_existing=False)

        with self.assertRaisesRegex(ValueError, "Bundle records must be an object"):
            transfer.import_bundle(self.sandbox.project, {"bundle_version": 1, "records": []}, replace_existing=False)

        default_backup = archive.create_backup(self.sandbox.project)
        self.assertTrue(Path(default_backup["output_path"]).exists())

        duplicate_root = self.sandbox.root / "duplicate_project"
        with self.assertRaisesRegex(ValueError, "project_id already exists"):
            archive.restore_backup(Path(default_backup["output_path"]), duplicate_root, project_id="test-project")
        reserved_root = self.sandbox.root / "reserved_project"
        with self.assertRaisesRegex(ValueError, "project_id is reserved"):
            archive.restore_backup(Path(default_backup["output_path"]), reserved_root, project_id="assets")

        malformed_zip = self.sandbox.root / "malformed.zip"
        with zipfile.ZipFile(malformed_zip, "w") as handle:
            handle.writestr(
                "manifest.json",
                json.dumps(
                    {
                        "project": {
                            "project_id": "malformed",
                            "display_name": "Malformed",
                            "http_host": "127.0.0.1",
                            "http_port": 10000,
                            "mcp_host": "127.0.0.1",
                            "mcp_port": 10001,
                            "write_mode": "confirm",
                        }
                    }
                ),
            )
            handle.writestr("other.txt", "ignored")
        restored_root = self.sandbox.root / "malformed_restored"
        restored = archive.restore_backup(malformed_zip, restored_root, project_id="malformed-restored")
        self.assertTrue(restored_root.exists())
        self.assertEqual(restored.project_id, "malformed-restored")

    def test_import_legacy_database_to_generic_reverse_engineering_schema(self) -> None:
        imported_root = self.sandbox.root / "legacy_imported_project"
        imported_project = self.sandbox.project_service.create_project(
            "legacy-imported",
            "Legacy Imported",
            imported_root,
            18777,
            19888,
        )
        with self.sandbox.open_database() as database:
            RelationService(database).create_relation(
                RelationWrite(
                    project_id="test-project",
                    from_entity_type="function",
                    from_entity_id="fn_main",
                    to_entity_type="function",
                    to_entity_id="fn_main",
                    relation_type="calls",
                    created_by="tester",
                )
            )

        result = LegacyDatabaseImporter().import_legacy_database(
            imported_project,
            self.sandbox.project.database_path,
            source_project_id="test-project",
            replace_existing=True,
        )
        self.assertEqual(result["counts"]["records"], 1)
        self.assertEqual(result["counts"]["evidence"], 1)
        self.assertEqual(result["counts"]["relations"], 1)

        with open_database(imported_project.database_path) as database:
            record = RecordService(database, imported_project).get_record("function", "fn_main")
            self.assertIsNotNone(record)
            self.assertEqual(record.payload["current_name"], "main_handler")
            evidence = GenericEvidenceService(database, imported_project).list_evidence("function", record.record_id)
            self.assertEqual(len(evidence), 1)


from mcp_memory.storage import open_database


if __name__ == "__main__":
    unittest.main()
