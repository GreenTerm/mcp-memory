from __future__ import annotations

import argparse
import io
import json
import os
import runpy
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from tests.support import ROOT

from mcp_memory.cli.main import run
from mcp_memory.config import AppConfig, ProjectConfig, ProjectRegistry, resolve_app_home, resolve_registry_path
from mcp_memory.logging_utils import shutdown_logging
from mcp_memory.services import ProjectService


class ConfigAndCliTests(unittest.TestCase):
    def tearDown(self) -> None:
        shutdown_logging()

    def test_project_config_round_trip(self) -> None:
        project = ProjectConfig(
            project_id="p1",
            display_name="Project One",
            project_root=Path("C:/tmp/project"),
            database_path=Path("C:/tmp/project/project.db"),
            attachments_dir=Path("C:/tmp/project/attachments"),
            exports_dir=Path("C:/tmp/project/exports"),
            backups_dir=Path("C:/tmp/project/backups"),
            logs_dir=Path("C:/tmp/project/logs"),
            created_at="2026-05-22T12:00:00+00:00",
        )
        restored = ProjectConfig.from_dict(project.to_dict())
        self.assertEqual(restored.project_id, "p1")
        self.assertEqual(restored.project_root.name, "project")
        self.assertEqual(restored.created_at, "2026-05-22T12:00:00+00:00")
        restored_legacy = ProjectConfig.from_dict({key: value for key, value in project.to_dict().items() if key != "created_at"})
        self.assertEqual(restored_legacy.created_at, "")

    def test_app_config_round_trip(self) -> None:
        project = ProjectConfig(
            project_id="p1",
            display_name="Project One",
            project_root=Path("C:/tmp/project"),
            database_path=Path("C:/tmp/project/project.db"),
            attachments_dir=Path("C:/tmp/project/attachments"),
            exports_dir=Path("C:/tmp/project/exports"),
            backups_dir=Path("C:/tmp/project/backups"),
            logs_dir=Path("C:/tmp/project/logs"),
        )
        app = AppConfig(
            app_home=Path("C:/tmp/app"),
            registry_path=Path("C:/tmp/app/app_config.json"),
            projects=[project],
            base_url="http://mcp-memory.local:8764",
        )
        restored = AppConfig.from_dict(app.to_dict())
        self.assertEqual(restored.app_home.name, "app")
        self.assertEqual(len(restored.projects), 1)
        self.assertEqual(restored.base_url, "http://mcp-memory.local:8764")
        self.assertEqual(AppConfig.from_dict({"app_home": "C:/tmp/app", "registry_path": "C:/tmp/app/app_config.json"}).base_url, "")

    def test_resolve_app_home_priority(self) -> None:
        explicit = resolve_app_home("C:/explicit/home")
        self.assertEqual(explicit, Path("C:/explicit/home").resolve())

        with mock.patch.dict(os.environ, {"MCP_MEMORY_HOME": "C:/env/home"}, clear=True):
            self.assertEqual(resolve_app_home(), Path("C:/env/home").resolve())

        with mock.patch.dict(os.environ, {"LOCALAPPDATA": "C:/Users/Test/AppData/Local"}, clear=True):
            resolved = resolve_app_home()
            self.assertEqual(resolved, Path("C:/Users/Test/AppData/Local/mcp-memory").resolve())

        with mock.patch.dict(os.environ, {}, clear=True):
            resolved = resolve_app_home()
            self.assertEqual(resolved, (Path.cwd() / ".mcp-memory").resolve())

    def test_resolve_registry_path(self) -> None:
        self.assertEqual(resolve_registry_path(Path("C:/app")), Path("C:/app/app_config.json"))

    def test_registry_load_save_upsert_and_list(self) -> None:
        with TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "app_config.json"
            registry = ProjectRegistry(config_path)
            loaded = registry.load()
            self.assertEqual(loaded.projects, [])

            project = ProjectConfig(
                project_id="p1",
                display_name="Project One",
                project_root=Path(tmp) / "project",
                database_path=Path(tmp) / "project" / "project.db",
                attachments_dir=Path(tmp) / "project" / "attachments",
                exports_dir=Path(tmp) / "project" / "exports",
                backups_dir=Path(tmp) / "project" / "backups",
                logs_dir=Path(tmp) / "project" / "logs",
            )
            registry.upsert_project(project)
            self.assertIsNotNone(registry.get_project("p1"))
            self.assertEqual(len(registry.list_projects()), 1)

    def test_project_service_duplicate_project_id_raises(self) -> None:
        with TemporaryDirectory() as tmp:
            registry = ProjectRegistry(Path(tmp) / "app" / "app_config.json")
            service = ProjectService(registry)
            service.initialize_app()
            service.create_project("p1", "Project One", Path(tmp) / "project-a", 10001, 10002)
            with self.assertRaisesRegex(ValueError, "project_id already exists"):
                service.create_project("p1", "Project Again", Path(tmp) / "project-b", 10003, 10004)

    def test_project_service_create_project_sets_created_at(self) -> None:
        with TemporaryDirectory() as tmp:
            registry = ProjectRegistry(Path(tmp) / "app" / "app_config.json")
            service = ProjectService(registry)
            service.initialize_app()
            project = service.create_project("p1", "Project One", Path(tmp) / "project-a", 10001, 10002)
            self.assertRegex(project.created_at, r"^\d{4}-\d{2}-\d{2}T")
            self.assertEqual(registry.get_project("p1").created_at, project.created_at)

    def test_project_service_rejects_non_empty_project_root(self) -> None:
        with TemporaryDirectory() as tmp:
            registry = ProjectRegistry(Path(tmp) / "app" / "app_config.json")
            service = ProjectService(registry)
            service.initialize_app()
            project_root = Path(tmp) / "occupied-project"
            project_root.mkdir(parents=True, exist_ok=True)
            (project_root / "marker.txt").write_text("busy", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "not empty"):
                service.create_project("p1", "Project One", project_root, 10001, 10002)

    def test_project_service_rejects_other_invalid_inputs(self) -> None:
        with TemporaryDirectory() as tmp:
            registry = ProjectRegistry(Path(tmp) / "app" / "app_config.json")
            service = ProjectService(registry)
            service.initialize_app()
            file_root = Path(tmp) / "not-a-dir"
            file_root.write_text("x", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "project_id is required"):
                service.create_project("", "Project One", Path(tmp) / "project-a", 10001, 10002)
            with self.assertRaisesRegex(ValueError, "project_id is reserved"):
                service.create_project("assets", "Project One", Path(tmp) / "project-reserved", 10001, 10002)
            with self.assertRaisesRegex(ValueError, "may contain only"):
                service.create_project("bad/project", "Project One", Path(tmp) / "project-bad", 10001, 10002)
            with self.assertRaisesRegex(ValueError, "display_name is required"):
                service.create_project("p1", "", Path(tmp) / "project-a", 10001, 10002)
            with self.assertRaisesRegex(ValueError, "write_mode must be one of"):
                service.create_project("p1", "Project One", Path(tmp) / "project-a", 10001, 10002, write_mode="broken")
            with self.assertRaisesRegex(ValueError, "positive integers"):
                service.create_project("p1", "Project One", Path(tmp) / "project-a", 0, 10002)
            with self.assertRaisesRegex(ValueError, "must be different"):
                service.create_project("p1", "Project One", Path(tmp) / "project-a", 10001, 10001)
            with self.assertRaisesRegex(ValueError, "must point to a directory"):
                service.create_project("p1", "Project One", file_root, 10001, 10002)

    def test_cli_init_create_and_list(self) -> None:
        with TemporaryDirectory() as tmp:
            app_home = Path(tmp) / "app"
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = run(["--app-home", str(app_home), "init-app"])
            self.assertEqual(exit_code, 0)
            init_payload = json.loads(output.getvalue())
            self.assertEqual(init_payload["status"], "initialized")

            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = run(
                    [
                        "--app-home",
                        str(app_home),
                        "create-project",
                        "p1",
                        "--name",
                        "Project One",
                        "--project-root",
                        str(Path(tmp) / "project"),
                        "--http-port",
                        "12000",
                        "--mcp-port",
                        "12001",
                    ]
                )
            self.assertEqual(exit_code, 0)
            project_payload = json.loads(output.getvalue())
            self.assertEqual(project_payload["project_id"], "p1")

            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = run(["--app-home", str(app_home), "list-projects"])
            self.assertEqual(exit_code, 0)
            items = json.loads(output.getvalue())
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["project_id"], "p1")
            shutdown_logging()

    def test_cli_schema_commands(self) -> None:
        with TemporaryDirectory() as tmp:
            app_home = Path(tmp) / "app"
            project_root = Path(tmp) / "project"
            self.assertEqual(
                run(
                    [
                        "--app-home",
                        str(app_home),
                        "create-project",
                        "p1",
                        "--name",
                        "Project One",
                        "--project-root",
                        str(project_root),
                        "--schema-template",
                        "research_notes",
                    ]
                ),
                0,
            )

            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(run(["--app-home", str(app_home), "show-schema", "p1"]), 0)
            self.assertEqual(json.loads(output.getvalue())["entity_types"][0]["name"], "source")

            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(run(["--app-home", str(app_home), "validate-schema", "--project-id", "p1"]), 0)
            self.assertEqual(json.loads(output.getvalue())["status"], "valid")

            schema_path = Path(tmp) / "replacement.schema.json"
            schema_path.write_text(
                json.dumps(
                    {
                        "schema_version": "1",
                        "entity_types": [
                            {
                                "name": "replacement",
                                "fields": [{"name": "title", "label": "Title", "widget": "text"}],
                                "required": ["title"],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(run(["--app-home", str(app_home), "update-schema", "p1", "--schema", str(schema_path)]), 0)
            self.assertEqual(json.loads(output.getvalue())["status"], "updated")
            updated_payload = json.loads((project_root / "schema.json").read_text(encoding="utf-8"))
            self.assertEqual(updated_payload["entity_types"][0]["name"], "replacement")
            shutdown_logging()

    def test_cli_run_http_api_unknown_project_raises_system_exit(self) -> None:
        with TemporaryDirectory() as tmp:
            app_home = Path(tmp) / "app"
            ProjectService(ProjectRegistry(app_home / "app_config.json")).initialize_app()
            with self.assertRaises(SystemExit):
                run(["--app-home", str(app_home), "run-http-api", "missing-project"])
            shutdown_logging()

    def test_cli_run_http_api_uses_project_defaults(self) -> None:
        with TemporaryDirectory() as tmp:
            app_home = Path(tmp) / "app"
            project_root = Path(tmp) / "project"
            service = ProjectService(ProjectRegistry(app_home / "app_config.json"))
            service.initialize_app()
            service.create_project("p1", "Project One", project_root, 12000, 12001)
            try:
                with mock.patch("mcp_memory.cli.main.serve_project_http_api") as serve_mock:
                    exit_code = run(["--app-home", str(app_home), "--log-level", "WARNING", "run-http-api", "p1"])
                self.assertEqual(exit_code, 0)
                serve_mock.assert_called_once()
                project, registry, host, port = serve_mock.call_args.args
                self.assertEqual(project.project_id, "p1")
                self.assertEqual(registry.config_path.resolve(), service._registry.config_path.resolve())
                self.assertEqual(host, "127.0.0.1")
                self.assertEqual(port, 12000)
                self.assertEqual(serve_mock.call_args.kwargs["log_level"], "WARNING")
            finally:
                shutdown_logging()

    def test_cli_run_mcp_uses_project_defaults(self) -> None:
        with TemporaryDirectory() as tmp:
            app_home = Path(tmp) / "app"
            project_root = Path(tmp) / "project"
            service = ProjectService(ProjectRegistry(app_home / "app_config.json"))
            service.initialize_app()
            service.create_project("p1", "Project One", project_root, 12000, 12001)
            try:
                with mock.patch("mcp_memory.cli.main.serve_project_mcp_api") as serve_mock:
                    exit_code = run(["--app-home", str(app_home), "--log-level", "ERROR", "run-mcp", "p1"])
                self.assertEqual(exit_code, 0)
                serve_mock.assert_called_once()
                project, registry, host, port = serve_mock.call_args.args
                self.assertEqual(project.project_id, "p1")
                self.assertEqual(registry.config_path.resolve(), service._registry.config_path.resolve())
                self.assertEqual(host, "127.0.0.1")
                self.assertEqual(port, 12001)
                self.assertEqual(serve_mock.call_args.kwargs["log_level"], "ERROR")
            finally:
                shutdown_logging()

    def test_cli_run_ui_home_uses_defaults(self) -> None:
        with TemporaryDirectory() as tmp:
            app_home = Path(tmp) / "app"
            service = ProjectService(ProjectRegistry(app_home / "app_config.json"))
            service.initialize_app()
            try:
                with mock.patch("mcp_memory.cli.main.serve_ui_home") as serve_mock:
                    exit_code = run(["--app-home", str(app_home), "--log-level", "DEBUG", "run-ui-home"])
                self.assertEqual(exit_code, 0)
                serve_mock.assert_called_once()
                registry, host, port, passed_app_home = serve_mock.call_args.args
                self.assertEqual(registry.config_path.resolve(), service._registry.config_path.resolve())
                self.assertEqual(host, "127.0.0.1")
                self.assertEqual(port, 8764)
                self.assertEqual(passed_app_home.resolve(), app_home.resolve())
                self.assertEqual(serve_mock.call_args.kwargs["log_level"], "DEBUG")
            finally:
                shutdown_logging()

    def test_cli_commands_write_runtime_log_file(self) -> None:
        with TemporaryDirectory() as tmp:
            app_home = Path(tmp) / "app"
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = run(["--app-home", str(app_home), "init-app"])
            self.assertEqual(exit_code, 0)
            log_path = app_home / "logs" / "cli.log"
            self.assertTrue(log_path.exists())
            self.assertIn("command_finish", log_path.read_text(encoding="utf-8"))
            shutdown_logging()

    def test_cli_export_import_backup_and_restore_commands(self) -> None:
        with TemporaryDirectory() as tmp:
            app_home = Path(tmp) / "app"
            project_root = Path(tmp) / "project"
            service = ProjectService(ProjectRegistry(app_home / "app_config.json"))
            service.initialize_app()
            service.create_project("p1", "Project One", project_root, 12000, 12001)
            try:
                with mock.patch("mcp_memory.cli.main.ProjectTransferService") as transfer_cls:
                    transfer_cls.return_value.export_project.return_value = {"output_path": str(Path(tmp) / "bundle.json"), "counts": {"functions": 1}}
                    exit_code = run(["--app-home", str(app_home), "export-json", "p1"])
                    self.assertEqual(exit_code, 0)
                    transfer_cls.return_value.export_project.assert_called_once()

                with mock.patch("mcp_memory.cli.main.ProjectTransferService") as transfer_cls:
                    transfer_cls.return_value.import_project.return_value = {
                        "input_path": str(Path(tmp) / "bundle.json"),
                        "replace_existing": False,
                        "counts": {"functions": 1},
                    }
                    exit_code = run(["--app-home", str(app_home), "import-json", "p1", "--input", str(Path(tmp) / "bundle.json")])
                    self.assertEqual(exit_code, 0)
                    transfer_cls.return_value.import_project.assert_called_once()

                with mock.patch("mcp_memory.cli.main.LegacyDatabaseImporter") as legacy_cls:
                    legacy_cls.return_value.import_legacy_database.return_value = {
                        "legacy_database_path": str(Path(tmp) / "legacy.db"),
                        "source_project_id": "old-project",
                        "replace_existing": True,
                        "counts": {"records": 1},
                    }
                    exit_code = run(
                        [
                            "--app-home",
                            str(app_home),
                            "import-legacy-db",
                            "p1",
                            "--input",
                            str(Path(tmp) / "legacy.db"),
                            "--source-project-id",
                            "old-project",
                            "--replace-existing",
                        ]
                    )
                    self.assertEqual(exit_code, 0)
                    legacy_cls.return_value.import_legacy_database.assert_called_once()

                with mock.patch("mcp_memory.cli.main.ProjectArchiveService") as archive_cls:
                    archive_cls.return_value.create_backup.return_value = {"output_path": str(Path(tmp) / "backup.zip"), "file_count": 2}
                    exit_code = run(["--app-home", str(app_home), "backup-project", "p1"])
                    self.assertEqual(exit_code, 0)
                    archive_cls.return_value.create_backup.assert_called_once()

                with mock.patch("mcp_memory.cli.main.ProjectArchiveService") as archive_cls:
                    archive_cls.return_value.restore_backup.return_value = service.list_projects()[0]
                    exit_code = run(
                        [
                            "--app-home",
                            str(app_home),
                            "restore-project",
                            "--input",
                            str(Path(tmp) / "backup.zip"),
                            "--project-root",
                            str(Path(tmp) / "restored"),
                        ]
                    )
                    self.assertEqual(exit_code, 0)
                    archive_cls.return_value.restore_backup.assert_called_once()
            finally:
                shutdown_logging()

    def test_cli_pending_change_commands(self) -> None:
        with TemporaryDirectory() as tmp:
            app_home = Path(tmp) / "app"
            project_root = Path(tmp) / "project"
            service = ProjectService(ProjectRegistry(app_home / "app_config.json"))
            service.initialize_app()
            service.create_project("p1", "Project One", project_root, 12000, 12001)

            fake_pending = mock.Mock()
            fake_pending.list_pending_changes.return_value = []
            fake_pending.confirm_change.return_value = {"pending_change": {"status": "confirmed"}}
            fake_pending.reject_change.return_value = {"status": "rejected"}

            with mock.patch("mcp_memory.cli.main.PendingChangeService", return_value=fake_pending):
                self.assertEqual(run(["--app-home", str(app_home), "list-pending", "p1"]), 0)
                self.assertEqual(run(["--app-home", str(app_home), "confirm-change", "p1", "pc1"]), 0)
                self.assertEqual(run(["--app-home", str(app_home), "reject-change", "p1", "pc2"]), 0)
                fake_pending.list_pending_changes.assert_called_once()
                fake_pending.confirm_change.assert_called_once()
                fake_pending.reject_change.assert_called_once()
            shutdown_logging()

    def test_cli_additional_unknown_project_branches(self) -> None:
        with TemporaryDirectory() as tmp:
            app_home = Path(tmp) / "app"
            ProjectService(ProjectRegistry(app_home / "app_config.json")).initialize_app()
            failing_commands = [
                ["--app-home", str(app_home), "export-json", "missing-project"],
                ["--app-home", str(app_home), "import-json", "missing-project", "--input", str(Path(tmp) / "bundle.json")],
                ["--app-home", str(app_home), "import-legacy-db", "missing-project", "--input", str(Path(tmp) / "legacy.db")],
                ["--app-home", str(app_home), "backup-project", "missing-project"],
                ["--app-home", str(app_home), "list-pending", "missing-project"],
                ["--app-home", str(app_home), "confirm-change", "missing-project", "pc1"],
                ["--app-home", str(app_home), "reject-change", "missing-project", "pc1"],
                ["--app-home", str(app_home), "run-mcp", "missing-project"],
            ]
            for command in failing_commands:
                with self.assertRaises(SystemExit):
                    run(command)
            shutdown_logging()

    def test_cli_unknown_command_reaches_parser_error_branch(self) -> None:
        parser = mock.Mock()
        parser.parse_args.return_value = argparse.Namespace(command="unexpected", app_home=None, log_level="INFO")
        parser.error.side_effect = SystemExit(2)
        with mock.patch("mcp_memory.cli.main.build_parser", return_value=parser):
            with self.assertRaises(SystemExit) as ctx:
                run([])
        self.assertEqual(ctx.exception.code, 2)
        parser.error.assert_called_once()

    def test_cli_main_module_invokes_run(self) -> None:
        with mock.patch("mcp_memory.cli.main.run", return_value=0) as run_mock:
            with self.assertRaises(SystemExit) as ctx:
                runpy.run_module("mcp_memory.cli.__main__", run_name="__main__")
            self.assertEqual(ctx.exception.code, 0)
            run_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
