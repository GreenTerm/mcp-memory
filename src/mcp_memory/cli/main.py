from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from mcp_memory.api.server import serialize
from mcp_memory.config import ProjectRegistry, resolve_app_home, resolve_registry_path
from mcp_memory.api.server import serve_project_http_api
from mcp_memory.gui import serve_ui_home
from mcp_memory.logging_utils import configure_logging, log_event
from mcp_memory.mcp import serve_project_mcp_api
from mcp_memory.schema import ProjectSchema, copy_schema_payload, list_bundled_schema_templates, load_schema_payload
from mcp_memory.services import LegacyDatabaseImporter, PendingChangeService, ProjectArchiveService, ProjectService, ProjectTransferService
from mcp_memory.storage import open_database


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mcp-memory")
    parser.add_argument(
        "--app-home",
        help="Override the app home directory. Defaults to MCP_MEMORY_HOME or LOCALAPPDATA\\mcp-memory.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Runtime log level for CLI and server commands. Defaults to INFO.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-app", help="Create the global app registry if it does not exist.")

    create_project = subparsers.add_parser("create-project", help="Create a project workspace and bootstrap its SQLite database.")
    create_project.add_argument("project_id")
    create_project.add_argument("--name", required=True, dest="display_name")
    create_project.add_argument(
        "--project-root",
        help="Project directory. Defaults to <app-home>/projects/<project_id>.",
    )
    create_project.add_argument("--http-port", type=int, default=8765)
    create_project.add_argument("--mcp-port", type=int, default=9876)
    create_project.add_argument("--schema")
    create_project.add_argument(
        "--schema-template",
        choices=tuple(list_bundled_schema_templates()),
        default="general_knowledge",
    )
    create_project.add_argument(
        "--write-mode",
        choices=("confirm", "auto"),
        default="confirm",
    )

    subparsers.add_parser("list-projects", help="Print registered projects as JSON.")

    show_schema = subparsers.add_parser("show-schema", help="Print a project schema as JSON.")
    show_schema.add_argument("project_id")

    validate_schema = subparsers.add_parser("validate-schema", help="Validate a schema file or project schema.")
    validate_schema.add_argument("--schema")
    validate_schema.add_argument("--project-id")

    update_schema = subparsers.add_parser("update-schema", help="Replace a project schema with a validated schema file.")
    update_schema.add_argument("project_id")
    update_schema.add_argument("--schema", required=True)

    export_json = subparsers.add_parser("export-json", help="Export project records into a JSON bundle.")
    export_json.add_argument("project_id")
    export_json.add_argument("--output")

    import_json = subparsers.add_parser("import-json", help="Import project records from a JSON bundle.")
    import_json.add_argument("project_id")
    import_json.add_argument("--input", required=True, dest="input_path")
    import_json.add_argument("--replace-existing", action="store_true")

    import_legacy_db = subparsers.add_parser("import-legacy-db", help="Import an old fixed RE project.db into generic records.")
    import_legacy_db.add_argument("project_id")
    import_legacy_db.add_argument("--input", required=True, dest="input_path")
    import_legacy_db.add_argument("--source-project-id")
    import_legacy_db.add_argument("--replace-existing", action="store_true")

    backup_project = subparsers.add_parser("backup-project", help="Create a zip backup of a project workspace.")
    backup_project.add_argument("project_id")
    backup_project.add_argument("--output")

    restore_project = subparsers.add_parser("restore-project", help="Restore a project workspace from a zip backup.")
    restore_project.add_argument("--input", required=True, dest="input_path")
    restore_project.add_argument("--project-root", required=True)
    restore_project.add_argument("--project-id")
    restore_project.add_argument("--name", dest="display_name")
    restore_project.add_argument("--http-port", type=int)
    restore_project.add_argument("--mcp-port", type=int)
    restore_project.add_argument("--write-mode")

    list_pending = subparsers.add_parser("list-pending", help="List pending change proposals for a project.")
    list_pending.add_argument("project_id")
    list_pending.add_argument("--status", default="pending")

    confirm_change = subparsers.add_parser("confirm-change", help="Apply a pending change proposal.")
    confirm_change.add_argument("project_id")
    confirm_change.add_argument("pending_change_id")
    confirm_change.add_argument("--confirmed-by", default="cli")

    reject_change = subparsers.add_parser("reject-change", help="Reject a pending change proposal.")
    reject_change.add_argument("project_id")
    reject_change.add_argument("pending_change_id")
    reject_change.add_argument("--rejected-by", default="cli")

    run_http_api = subparsers.add_parser("run-http-api", help="Run the local JSON HTTP API for a project.")
    run_http_api.add_argument("project_id")
    run_http_api.add_argument("--host")
    run_http_api.add_argument("--port", type=int)

    run_mcp = subparsers.add_parser("run-mcp", help="Run the local MCP HTTP API for a project.")
    run_mcp.add_argument("project_id")
    run_mcp.add_argument("--host")
    run_mcp.add_argument("--port", type=int)

    run_ui_home = subparsers.add_parser("run-ui-home", help="Run the home web UI for browsing registered projects.")
    run_ui_home.add_argument("--host", default="127.0.0.1")
    run_ui_home.add_argument("--port", type=int, default=8764)
    return parser


def _registry_from_args(app_home_raw: str | None) -> tuple[Path, ProjectRegistry]:
    app_home = resolve_app_home(app_home_raw)
    registry = ProjectRegistry(resolve_registry_path(app_home))
    return app_home, registry


def run(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    parser_actions = getattr(parser, "_actions", None)
    if not isinstance(parser_actions, list):
        parser.error(f"Unknown command: {args.command}")
    known_commands = {
        command
        for action in parser_actions
        if isinstance(action, argparse._SubParsersAction)
        for command in action.choices
    }
    if args.command not in known_commands:
        parser.error(f"Unknown command: {args.command}")

    app_home, registry = _registry_from_args(args.app_home)
    service = ProjectService(registry)
    logger = _configure_cli_logging(app_home, registry, args)
    log_event(logger, logging.INFO, "command_start", command=args.command)

    if args.command == "init-app":
        config = service.initialize_app()
        log_event(logger, logging.INFO, "command_finish", command=args.command, status="ok", project_count=len(config.projects))
        print(
            json.dumps(
                {
                    "status": "initialized",
                    "app_home": str(config.app_home),
                    "registry_path": str(config.registry_path),
                    "project_count": len(config.projects),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.command == "create-project":
        project_root = (
            Path(args.project_root).expanduser().resolve()
            if args.project_root
            else (app_home / "projects" / args.project_id).resolve()
        )
        project = service.create_project(
            project_id=args.project_id,
            display_name=args.display_name,
            project_root=project_root,
            http_port=args.http_port,
            mcp_port=args.mcp_port,
            write_mode=args.write_mode,
            schema_path=None if args.schema is None else Path(args.schema).expanduser().resolve(),
            schema_template=args.schema_template,
        )
        log_event(
            logger,
            logging.INFO,
            "command_finish",
            command=args.command,
            status="ok",
            project_id=project.project_id,
            write_mode=project.write_mode,
        )
        print(json.dumps(project.to_dict(), ensure_ascii=False, indent=2))
        return 0

    if args.command == "show-schema":
        project = registry.get_project(args.project_id)
        if project is None:
            parser.error(f"Unknown project_id: {args.project_id}")
        payload = load_schema_payload(project.schema_path)
        log_event(logger, logging.INFO, "command_finish", command=args.command, status="ok", project_id=project.project_id)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.command == "validate-schema":
        if args.schema:
            schema_path = Path(args.schema).expanduser().resolve()
        elif args.project_id:
            project = registry.get_project(args.project_id)
            if project is None:
                parser.error(f"Unknown project_id: {args.project_id}")
            schema_path = project.schema_path
        else:
            parser.error("validate-schema requires --schema or --project-id")
        payload = load_schema_payload(schema_path)
        ProjectSchema.from_dict(payload)
        log_event(logger, logging.INFO, "command_finish", command=args.command, status="ok", schema_path=schema_path)
        print(json.dumps({"status": "valid", "schema_path": str(schema_path)}, ensure_ascii=False, indent=2))
        return 0

    if args.command == "update-schema":
        project = registry.get_project(args.project_id)
        if project is None:
            parser.error(f"Unknown project_id: {args.project_id}")
        source_path = Path(args.schema).expanduser().resolve()
        payload = load_schema_payload(source_path)
        ProjectSchema.from_dict(payload)
        copy_schema_payload(project.schema_path, payload)
        log_event(
            logger,
            logging.INFO,
            "command_finish",
            command=args.command,
            status="ok",
            project_id=project.project_id,
            schema_path=project.schema_path,
        )
        print(json.dumps({"status": "updated", "schema_path": str(project.schema_path)}, ensure_ascii=False, indent=2))
        return 0

    if args.command == "list-projects":
        projects = service.list_projects()
        log_event(logger, logging.INFO, "command_finish", command=args.command, status="ok", project_count=len(projects))
        print(
            json.dumps(
                [project.to_dict() for project in projects],
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.command == "export-json":
        project = registry.get_project(args.project_id)
        if project is None:
            parser.error(f"Unknown project_id: {args.project_id}")
        result = ProjectTransferService().export_project(
            project,
            None if args.output is None else Path(args.output).expanduser().resolve(),
        )
        log_event(
            logger,
            logging.INFO,
            "command_finish",
            command=args.command,
            status="ok",
            project_id=project.project_id,
            output_path=result["output_path"],
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.command == "import-json":
        project = registry.get_project(args.project_id)
        if project is None:
            parser.error(f"Unknown project_id: {args.project_id}")
        result = ProjectTransferService().import_project(
            project,
            Path(args.input_path).expanduser().resolve(),
            replace_existing=bool(args.replace_existing),
        )
        log_event(
            logger,
            logging.INFO,
            "command_finish",
            command=args.command,
            status="ok",
            project_id=project.project_id,
            input_path=result["input_path"],
            replace_existing=result["replace_existing"],
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.command == "import-legacy-db":
        project = registry.get_project(args.project_id)
        if project is None:
            parser.error(f"Unknown project_id: {args.project_id}")
        result = LegacyDatabaseImporter().import_legacy_database(
            project,
            Path(args.input_path).expanduser().resolve(),
            source_project_id=None if args.source_project_id is None else str(args.source_project_id),
            replace_existing=bool(args.replace_existing),
        )
        log_event(
            logger,
            logging.INFO,
            "command_finish",
            command=args.command,
            status="ok",
            project_id=project.project_id,
            input_path=result["legacy_database_path"],
            replace_existing=result["replace_existing"],
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.command == "backup-project":
        project = registry.get_project(args.project_id)
        if project is None:
            parser.error(f"Unknown project_id: {args.project_id}")
        result = ProjectArchiveService(registry).create_backup(
            project,
            None if args.output is None else Path(args.output).expanduser().resolve(),
        )
        log_event(
            logger,
            logging.INFO,
            "command_finish",
            command=args.command,
            status="ok",
            project_id=project.project_id,
            output_path=result["output_path"],
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.command == "restore-project":
        config = ProjectArchiveService(registry).restore_backup(
            input_path=Path(args.input_path).expanduser().resolve(),
            project_root=Path(args.project_root).expanduser().resolve(),
            project_id=None if args.project_id is None else str(args.project_id),
            display_name=None if args.display_name is None else str(args.display_name),
            http_port=args.http_port,
            mcp_port=args.mcp_port,
            write_mode=None if args.write_mode is None else str(args.write_mode),
        )
        log_event(
            logger,
            logging.INFO,
            "command_finish",
            command=args.command,
            status="ok",
            project_id=config.project_id,
            project_root=config.project_root,
        )
        print(json.dumps(config.to_dict(), ensure_ascii=False, indent=2))
        return 0

    if args.command == "list-pending":
        project = registry.get_project(args.project_id)
        if project is None:
            parser.error(f"Unknown project_id: {args.project_id}")
        status = None if args.status == "all" else str(args.status)
        with open_database(project.database_path) as database:
            items = PendingChangeService(database).list_pending_changes(project.project_id, status=status)
        log_event(
            logger,
            logging.INFO,
            "command_finish",
            command=args.command,
            status="ok",
            project_id=project.project_id,
            pending_count=len(items),
        )
        print(json.dumps(serialize(items), ensure_ascii=False, indent=2))
        return 0

    if args.command == "confirm-change":
        project = registry.get_project(args.project_id)
        if project is None:
            parser.error(f"Unknown project_id: {args.project_id}")
        with open_database(project.database_path) as database:
            result = PendingChangeService(database).confirm_change(
                project.project_id,
                args.pending_change_id,
                confirmed_by=args.confirmed_by,
                actor_type="user",
            )
        log_event(
            logger,
            logging.INFO,
            "command_finish",
            command=args.command,
            status="ok",
            project_id=project.project_id,
            pending_change_id=args.pending_change_id,
        )
        print(json.dumps(serialize(result), ensure_ascii=False, indent=2))
        return 0

    if args.command == "reject-change":
        project = registry.get_project(args.project_id)
        if project is None:
            parser.error(f"Unknown project_id: {args.project_id}")
        with open_database(project.database_path) as database:
            result = PendingChangeService(database).reject_change(
                project.project_id,
                args.pending_change_id,
                rejected_by=args.rejected_by,
            )
        log_event(
            logger,
            logging.INFO,
            "command_finish",
            command=args.command,
            status="ok",
            project_id=project.project_id,
            pending_change_id=args.pending_change_id,
        )
        print(json.dumps(serialize(result), ensure_ascii=False, indent=2))
        return 0

    if args.command == "run-http-api":
        project = registry.get_project(args.project_id)
        if project is None:
            parser.error(f"Unknown project_id: {args.project_id}")
        host = args.host or project.http_host
        port = args.port or project.http_port
        log_event(logger, logging.INFO, "server_dispatch", command=args.command, project_id=project.project_id, host=host, port=port)
        serve_project_http_api(project, registry, host, port, log_level=args.log_level)
        return 0

    if args.command == "run-mcp":
        project = registry.get_project(args.project_id)
        if project is None:
            parser.error(f"Unknown project_id: {args.project_id}")
        host = args.host or project.mcp_host
        port = args.port or project.mcp_port
        log_event(logger, logging.INFO, "server_dispatch", command=args.command, project_id=project.project_id, host=host, port=port)
        serve_project_mcp_api(project, registry, host, port, log_level=args.log_level)
        return 0

    if args.command == "run-ui-home":
        log_event(logger, logging.INFO, "server_dispatch", command=args.command, host=args.host, port=args.port)
        serve_ui_home(registry, args.host, args.port, app_home, log_level=args.log_level)
        return 0

    parser.error(f"Unknown command: {args.command}")
    return 2


def _configure_cli_logging(app_home: Path, registry: ProjectRegistry, args: argparse.Namespace):
    log_root = app_home / "logs"
    project_id = getattr(args, "project_id", None)
    log_level = getattr(args, "log_level", "INFO")
    project = registry.get_project(project_id) if project_id else None
    if project is not None:
        log_path = project.logs_dir / "cli.log"
    else:
        log_path = log_root / "cli.log"
    configure_logging("services", log_level, log_path)
    return configure_logging("cli", log_level, log_path)
