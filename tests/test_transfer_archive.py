from __future__ import annotations

import json
import unittest
import zipfile
from pathlib import Path
from unittest import mock

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
        with self.assertRaisesRegex(ValueError, "Unsafe backup member path"):
            archive.restore_backup(malformed_zip, restored_root, project_id="malformed-restored")
        self.assertFalse(restored_root.exists())
        self.assertIsNone(self.sandbox.registry.get_project("malformed-restored"))

    def test_restore_rejects_non_empty_target_without_touching_sentinel(self) -> None:
        archive = ProjectArchiveService(self.sandbox.registry)
        backup_path = self.sandbox.root / "backup.zip"
        archive.create_backup(self.sandbox.project, backup_path)

        restored_root = self.sandbox.root / "non_empty_restore"
        restored_root.mkdir()
        sentinel = restored_root / "sentinel.txt"
        sentinel.write_text("keep me", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "project_root already exists and is not empty"):
            archive.restore_backup(backup_path, restored_root, project_id="non-empty-restore")

        self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep me")
        self.assertIsNone(self.sandbox.registry.get_project("non-empty-restore"))

    def test_restore_rejects_unsafe_zip_without_target_or_registry_entry(self) -> None:
        archive = ProjectArchiveService(self.sandbox.registry)
        unsafe_zip = self.sandbox.root / "unsafe.zip"
        with zipfile.ZipFile(unsafe_zip, "w") as handle:
            handle.writestr(
                "manifest.json",
                json.dumps(
                    {
                        "project": {
                            "project_id": "unsafe-source",
                            "display_name": "Unsafe Source",
                            "http_host": "127.0.0.1",
                            "http_port": 10000,
                            "mcp_host": "127.0.0.1",
                            "mcp_port": 10001,
                            "write_mode": "confirm",
                        }
                    }
                ),
            )
            handle.writestr("project/../escape.txt", "escape")

        restored_root = self.sandbox.root / "unsafe_restored"
        with self.assertRaisesRegex(ValueError, "Unsafe backup member path"):
            archive.restore_backup(unsafe_zip, restored_root, project_id="unsafe-restored")

        self.assertFalse(restored_root.exists())
        self.assertIsNone(self.sandbox.registry.get_project("unsafe-restored"))

    def test_backup_skips_backups_dir_and_restore_accepts_empty_target(self) -> None:
        archive = ProjectArchiveService(self.sandbox.registry)
        nested_backup_file = self.sandbox.project.backups_dir / "old.zip"
        nested_backup_file.write_text("old backup", encoding="utf-8")

        backup_path = self.sandbox.root / "backup.zip"
        archive.create_backup(self.sandbox.project, backup_path)
        with zipfile.ZipFile(backup_path, "r") as handle:
            names = set(handle.namelist())
        self.assertNotIn("project/backups/old.zip", names)

        restored_root = self.sandbox.root / "empty_restore"
        restored_root.mkdir()
        restored = archive.restore_backup(backup_path, restored_root, project_id="empty-target-restore")
        self.assertEqual(restored.project_root, restored_root)
        self.assertTrue((restored_root / "project.db").exists())

    def test_restore_rejects_file_target_and_bad_member_shapes(self) -> None:
        archive = ProjectArchiveService(self.sandbox.registry)
        backup_path = self.sandbox.root / "backup.zip"
        archive.create_backup(self.sandbox.project, backup_path)

        file_target = self.sandbox.root / "restore_target_file"
        file_target.write_text("not a directory", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "project_root must point to a directory"):
            archive.restore_backup(backup_path, file_target, project_id="file-target")

        manifest = json.dumps(
            {
                "project": {
                    "project_id": "bad-members-source",
                    "display_name": "Bad Members",
                    "http_host": "127.0.0.1",
                    "http_port": 10000,
                    "mcp_host": "127.0.0.1",
                    "mcp_port": 10001,
                    "write_mode": "confirm",
                }
            }
        )
        cases = [
            ("duplicate.zip", [("manifest.json", manifest), ("project/schema.json", "{}"), ("project/SCHEMA.json", "{}")], "Duplicate backup member path"),
            ("directory.zip", [("manifest.json", manifest), (zipfile.ZipInfo("project/empty/"), "")], "Backup member must be a project file"),
            ("missing_manifest.zip", [("project/schema.json", "{}")], "Backup manifest is missing"),
        ]
        for filename, members, message in cases:
            with self.subTest(filename=filename):
                bad_zip = self.sandbox.root / filename
                with zipfile.ZipFile(bad_zip, "w") as handle:
                    for name, content in members:
                        handle.writestr(name, content)
                restored_root = self.sandbox.root / f"{filename}_restore"
                with self.assertRaisesRegex(ValueError, message):
                    archive.restore_backup(bad_zip, restored_root, project_id=f"{filename}-restore")
                self.assertFalse(restored_root.exists())

    def test_restore_cleans_up_when_registry_update_fails_after_publish(self) -> None:
        archive = ProjectArchiveService(self.sandbox.registry)
        backup_path = self.sandbox.root / "backup.zip"
        archive.create_backup(self.sandbox.project, backup_path)
        restored_root = self.sandbox.root / "cleanup_restore"
        restored_root.mkdir()

        with mock.patch.object(self.sandbox.registry, "upsert_project", side_effect=RuntimeError("registry failed")):
            with self.assertRaisesRegex(RuntimeError, "registry failed"):
                archive.restore_backup(backup_path, restored_root, project_id="cleanup-restore")

        self.assertTrue(restored_root.exists())
        self.assertEqual(list(restored_root.iterdir()), [])
        self.assertIsNone(self.sandbox.registry.get_project("cleanup-restore"))

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
