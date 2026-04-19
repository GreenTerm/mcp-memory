from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import traceback
from contextlib import ExitStack
from pathlib import Path
from urllib import error, parse, request


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def allocate_port() -> int:
    import socket

    sock = socket.socket()
    try:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
    finally:
        sock.close()


def main() -> int:
    print("== Python ==")
    print(sys.version)
    print(f"executable={sys.executable}")

    print("\n== SQLite ==")
    print(f"sqlite_version={sqlite3.sqlite_version}")
    con = sqlite3.connect(":memory:")
    try:
        con.execute("create virtual table ft using fts5(x)")
        print("fts5=enabled")
    finally:
        con.close()

    print("\n== Imports ==")
    from mcp_memory.config import ProjectRegistry
    from mcp_memory.domain import (
        EvidenceWrite,
        FunctionWrite,
        GlobalHypothesisWrite,
        HypothesisItem,
        ObservedFact,
        StructureMember,
        StructureWrite,
    )
    from mcp_memory.services import EvidenceService, FunctionService, GlobalHypothesisService, RelationService, RelationWrite, SearchQuery, SearchService, StructureService
    from mcp_memory.storage import open_database

    print("imports=ok")

    print("\n== Smoke Check ==")
    artifacts_dir = ROOT / "artifacts"
    run_root = artifacts_dir / f"smoke_run_{int(time.time() * 1000)}_{os.getpid()}"
    app_home = run_root / "smoke_app"
    project_root = run_root / "smoke_project"
    app_home.mkdir(parents=True, exist_ok=True)

    http_port = allocate_port()
    mcp_port = allocate_port()
    ui_home_port = allocate_port()
    manual_mcp_port = allocate_port()
    restored_http_port = allocate_port()
    restored_mcp_port = allocate_port()

    cli_env = os.environ.copy()
    cli_env["PYTHONPATH"] = str(SRC)

    init_result = subprocess.run(
        [
            sys.executable,
            "-X",
            "utf8",
            "-m",
            "mcp_memory.cli",
            "--app-home",
            str(app_home),
            "init-app",
        ],
        cwd=ROOT,
        env=cli_env,
        text=True,
        capture_output=True,
        check=True,
    )
    print("cli_init_app=" + init_result.stdout.strip())

    create_result = subprocess.run(
        [
            sys.executable,
            "-X",
            "utf8",
            "-m",
            "mcp_memory.cli",
            "--app-home",
            str(app_home),
            "create-project",
            "smoke-project",
            "--name",
            "Smoke Project",
            "--project-root",
            str(project_root),
            "--http-port",
            str(http_port),
            "--mcp-port",
            str(mcp_port),
            "--write-mode",
            "confirm",
        ],
        cwd=ROOT,
        env=cli_env,
        text=True,
        capture_output=True,
        check=True,
    )
    print("cli_create_project=" + create_result.stdout.strip())

    list_result = subprocess.run(
        [
            sys.executable,
            "-X",
            "utf8",
            "-m",
            "mcp_memory.cli",
            "--app-home",
            str(app_home),
            "list-projects",
        ],
        cwd=ROOT,
        env=cli_env,
        text=True,
        capture_output=True,
        check=True,
    )
    print("cli_list_projects=" + list_result.stdout.strip())

    registry = ProjectRegistry(app_home / "app_config.json")
    project = registry.get_project("smoke-project")
    if project is None:
        raise RuntimeError("smoke-project was not registered by CLI")
    project.http_port = http_port
    project.mcp_port = mcp_port
    registry.upsert_project(project)
    print(f"project_db={project.database_path}")
    print(f"project_logs_dir={project.logs_dir}")

    database = open_database(project.database_path)
    try:
        function_service = FunctionService(database)
        structure_service = StructureService(database)
        global_hypothesis_service = GlobalHypothesisService(database)
        evidence_service = EvidenceService(database)
        relation_service = RelationService(database)

        record = function_service.upsert_function(
            FunctionWrite(
                project_id="smoke-project",
                binary_id="sample-binary",
                function_id="fn_main",
                address="0x401000",
                raw_name="sub_401000",
                current_name="main_handler",
                summary="Entry point handler",
                behavior_description="Parses input and dispatches work to helper routines.",
                important_variables=["ctx", "mode"],
                used_apis=["CreateFileA"],
                strings=["invalid input"],
                constants=["0x20"],
                confidence=0.8,
                tags=["entry", "parser"],
                observed_facts=[
                    ObservedFact(
                        fact="Calls CreateFileA before dispatching control flow.",
                        source_origin="smoke-test",
                    )
                ],
                hypotheses=[
                    HypothesisItem(
                        statement="Likely initializes parser state.",
                        source_origin="smoke-test",
                    )
                ],
                source_origin="smoke-test",
                created_by="local-check",
                updated_by="local-check",
            ),
            actor_type="system",
        )
        loaded = function_service.get_function("smoke-project", "sample-binary", "fn_main")
        listing = function_service.list_functions("smoke-project", "sample-binary")

        structure = structure_service.upsert_structure(
            StructureWrite(
                project_id="smoke-project",
                binary_id="sample-binary",
                structure_id="struct_parser_ctx",
                raw_name="parser_ctx",
                current_name="parser_ctx",
                summary="Parser state layout used by the entry handler.",
                fields=[
                    StructureMember(name="mode", offset="0x0", data_type="uint32_t", size=4),
                    StructureMember(name="buffer", offset="0x8", data_type="char *", size=8),
                ],
                tags=["structure", "parser"],
                observed_facts=[
                    ObservedFact(
                        fact="Referenced by main_handler through the ctx variable.",
                        source_origin="smoke-test",
                    )
                ],
                hypotheses=[
                    HypothesisItem(
                        statement="May be shared with downstream parser helpers.",
                        source_origin="smoke-test",
                    )
                ],
                source_origin="smoke-test",
                created_by="local-check",
                updated_by="local-check",
            ),
            actor_type="system",
        )

        global_hypothesis = global_hypothesis_service.upsert_hypothesis(
            GlobalHypothesisWrite(
                project_id="smoke-project",
                hypothesis_id="gh_parser_bootstrap",
                title="Parser bootstrap sequence",
                statement="The sample binary likely performs parser bootstrap before main dispatch.",
                binary_id="sample-binary",
                tags=["bootstrap", "parser"],
                observed_facts=[
                    ObservedFact(
                        fact="The entry function performs early setup before helper calls.",
                        source_origin="smoke-test",
                    )
                ],
                source_origin="smoke-test",
                created_by="local-check",
                updated_by="local-check",
            ),
            actor_type="system",
        )

        evidence = evidence_service.create_evidence(
            EvidenceWrite(
                project_id="smoke-project",
                evidence_id="evidence_fn_main_block0",
                entity_type="function",
                entity_id="fn_main",
                evidence_type="block",
                description="Initial basic block opens the file handle before dispatch.",
                address_start="0x401000",
                address_end="0x401020",
                excerpt="CreateFileA(...); if (handle == INVALID_HANDLE_VALUE) return 0;",
                source_origin="smoke-test",
                created_by="local-check",
            ),
            actor_type="system",
        )

        relation = relation_service.create_relation(
            RelationWrite(
                project_id="smoke-project",
                from_entity_type="function",
                from_entity_id="fn_main",
                to_entity_type="structure",
                to_entity_id="struct_parser_ctx",
                relation_type="uses_structure",
                created_by="local-check",
            ),
            actor_type="system",
        )

        structures = structure_service.list_structures("smoke-project", "sample-binary")
        global_hypotheses = global_hypothesis_service.list_hypotheses("smoke-project")
        evidence_rows = evidence_service.list_evidence("smoke-project", "function", "fn_main")
        relations = relation_service.list_relations("smoke-project", "function", "fn_main", direction="both")
        related = relation_service.traverse_related("smoke-project", "function", "fn_main", hops=1)
        search_results = SearchService(database).search(
            SearchQuery(
                project_id="smoke-project",
                query_text="main_handler",
                entity_types=["function"],
                binary_id="sample-binary",
                limit=10,
            )
        )
        versions = database.connection.execute(
            """
            select count(*) as count
            from entity_versions
            where project_id = ? and entity_type = 'function' and entity_id = ?
            """,
            ("smoke-project", "fn_main"),
        ).fetchone()["count"]
        audits = database.connection.execute(
            """
            select count(*) as count
            from audit_log
            where project_id = ? and entity_type = 'function' and entity_id = ?
            """,
            ("smoke-project", "fn_main"),
        ).fetchone()["count"]
        fts_rows = database.connection.execute(
            """
            select count(*) as count
            from search_documents_fts
            where search_documents_fts match 'main_handler'
            """
        ).fetchone()["count"]

        result = {
            "upserted_function_id": record.function_id,
            "loaded_current_name": loaded.current_name if loaded else None,
            "list_count": len(listing),
            "structure_id": structure.structure_id,
            "structure_count": len(structures),
            "global_hypothesis_id": global_hypothesis.hypothesis_id,
            "global_hypothesis_count": len(global_hypotheses),
            "evidence_id": evidence.evidence_id,
            "evidence_count": len(evidence_rows),
            "relation_id": relation.relation_id,
            "relation_count": len(relations),
            "related_count": len(related),
            "search_service_count": len(search_results),
            "version_rows": versions,
            "audit_rows": audits,
            "fts_match_rows": fts_rows,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))

        print("\n== HTTP API ==")
        stack = ExitStack()
        server_process, http_stdout_path, http_stderr_path = start_logged_process(
            stack,
            "http-api",
            [
                sys.executable,
                "-X",
                "utf8",
                "-m",
                "mcp_memory.cli",
                "--app-home",
                str(app_home),
                "run-http-api",
                "smoke-project",
                "--host",
                "127.0.0.1",
                "--port",
                str(http_port),
            ],
            cli_env,
        )
        try:
            base_url = f"http://127.0.0.1:{http_port}"
            wait_for_http(base_url + "/health", server_process, http_stdout_path, http_stderr_path, server_label="HTTP API")
            config_payload = read_json(base_url + "/project/config")
            functions_payload = read_json(base_url + "/functions?binary_id=sample-binary")
            function_detail = read_json(base_url + "/functions/sample-binary/fn_main")
            structures_payload = read_json(base_url + "/structures?binary_id=sample-binary")
            hypotheses_payload = read_json(base_url + "/global-hypotheses")
            evidence_payload = read_json(base_url + "/evidence?entity_type=function&entity_id=fn_main")
            relations_payload = read_json(base_url + "/relations?entity_type=function&entity_id=fn_main&direction=both")
            related_payload = read_json(base_url + "/related?entity_type=function&entity_id=fn_main&hops=1")
            pending_helper = post_json(
                base_url + "/functions",
                {
                    "binary_id": "sample-binary",
                    "function_id": "fn_helper",
                    "address": "0x401100",
                    "raw_name": "sub_401100",
                    "current_name": "helper_worker",
                    "summary": "Helper worker routine",
                    "behavior_description": "Performs secondary processing for parsed input.",
                    "tags": ["helper"],
                    "source_origin": "http-smoke-test",
                    "created_by": "http-check",
                    "updated_by": "http-check",
                },
            )
            pending_list = read_json(base_url + "/pending-changes")
            confirmed_helper = post_json(
                base_url + f"/pending-changes/{pending_helper['pending_change_id']}/confirm",
                {"confirmed_by": "http-check"},
            )
            search_payload = post_json(
                base_url + "/search",
                {
                    "q": "helper_worker",
                    "limit": 5,
                    "entity_types": ["function"],
                    "binary_id": "sample-binary",
                },
            )
            http_result = {
                "health_status": read_json(base_url + "/health")["status"],
                "config_project_id": config_payload["project"]["project_id"],
                "functions_count": len(functions_payload["items"]),
                "function_detail_name": function_detail["current_name"],
                "structures_count": len(structures_payload["items"]),
                "global_hypotheses_count": len(hypotheses_payload["items"]),
                "evidence_count": len(evidence_payload["items"]),
                "relations_count": len(relations_payload["items"]),
                "related_count": len(related_payload["items"]),
                "pending_count": len(pending_list["items"]),
                "created_helper_id": confirmed_helper["applied"]["function_id"],
                "search_count": len(search_payload["items"]),
            }
            print(json.dumps(http_result, ensure_ascii=False, indent=2))

            print("\n== Web UI ==")
            ui_home_process, ui_stdout_path, ui_stderr_path = start_logged_process(
                stack,
                "ui-home",
                [
                    sys.executable,
                    "-X",
                    "utf8",
                    "-m",
                    "mcp_memory.cli",
                    "--app-home",
                    str(app_home),
                    "run-ui-home",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(ui_home_port),
                ],
                cli_env,
            )
            try:
                ui_home_url = f"http://127.0.0.1:{ui_home_port}"
                wait_for_text(ui_home_url + "/", ui_home_process, ui_stdout_path, ui_stderr_path)
                home_html = read_text(ui_home_url + "/")
                home_ru_html = read_text(ui_home_url + "/?lang=ru")
                setup_html = read_text(ui_home_url + "/setup?lang=en")
                create_project_form_html = read_text(ui_home_url + "/projects/new?lang=en")
                gui_created_project_root = run_root / "gui_created_project"
                gui_created_project_id = "gui-created-project"
                created_home_html = post_form(
                    ui_home_url + "/projects/new?lang=en",
                    {
                        "project_id": gui_created_project_id,
                        "display_name": "GUI Created Project",
                        "project_root": str(gui_created_project_root),
                        "http_port": str(allocate_port()),
                        "mcp_port": str(allocate_port()),
                        "write_mode": "auto",
                    },
                )
                dashboard_html = read_text(base_url + "/ui/")
                dashboard_ru_html = read_text(base_url + "/ui/?lang=ru")
                functions_list_html = read_text(base_url + "/ui/functions?q=main")
                structures_list_html = read_text(base_url + "/ui/structures")
                hypotheses_list_html = read_text(base_url + "/ui/global-hypotheses")
                graph_html = read_text(base_url + "/ui/graph")
                focused_graph_html = read_text(base_url + "/ui/graph?focus_type=function&focus_id=fn_main")
                import_export_html = read_text(base_url + "/ui/import-export")
                backups_html = read_text(base_url + "/ui/backups")
                settings_html = read_text(base_url + "/ui/settings")
                updated_mcp_port = allocate_port()
                saved_settings_html = post_form(
                    base_url + "/ui/settings?lang=en",
                    {
                        "display_name": "Smoke Project Updated",
                        "write_mode": "confirm",
                        "http_host": "127.0.0.1",
                        "http_port": str(http_port),
                        "mcp_host": "127.0.0.1",
                        "mcp_port": str(updated_mcp_port),
                    },
                )
                project = registry.get_project("smoke-project") or project
                home_after_settings_html = read_text(ui_home_url + "/?lang=en")
                new_function_form_html = read_text(base_url + "/ui/functions/new")
                new_structure_form_html = read_text(base_url + "/ui/structures/new")
                search_html = read_text(base_url + "/ui/search?q=main_handler&entity_type=function")
                function_html = read_text(base_url + "/ui/functions/sample-binary/fn_main")
                function_history_html = read_text(base_url + "/ui/functions/sample-binary/fn_main/history")
                new_hypothesis_form_html = read_text(base_url + "/ui/global-hypotheses/new")
                pending_html = read_text(base_url + "/ui/pending")
                audit_html = read_text(base_url + "/ui/audit")
                queued_structure_html = post_form(
                    base_url + "/ui/structures/new",
                    {
                        "binary_id": "sample-binary",
                        "structure_id": "struct_form_pending",
                        "raw_name": "pending_t",
                        "current_name": "pending_t",
                        "summary": "Queued through HTML structure form.",
                        "fields": "mode|0x0|uint32_t|4|mode",
                        "tags": "",
                        "observed_facts": "",
                    },
                )
                queued_form_html = post_form(
                    base_url + "/ui/global-hypotheses/new",
                    {
                        "hypothesis_id": "gh_form_pending",
                        "title": "Form Pending Hypothesis",
                        "statement": "Queued through HTML form.",
                        "status": "new",
                        "binary_id": "",
                        "confidence": "",
                        "tags": "",
                        "observed_facts": "",
                    },
                )
                ui_pending = post_json(
                    base_url + "/functions",
                    {
                        "binary_id": "sample-binary",
                        "function_id": "fn_html_helper",
                        "address": "0x401180",
                        "raw_name": "sub_401180",
                        "current_name": "html_helper",
                        "summary": "HTML helper routine",
                        "behavior_description": "Created to verify the HTML confirm flow.",
                        "tags": ["html"],
                        "source_origin": "ui-smoke-test",
                        "created_by": "ui-check",
                        "updated_by": "ui-check",
                    },
                )
                confirmed_html = post_form(
                    base_url + f"/ui/pending/{ui_pending['pending_change_id']}/confirm",
                    {"confirmed_by": "ui-check"},
                )
                ui_result = {
                    "home_has_project": "Smoke Project" in home_html,
                    "home_ru_language": "Полка проектов" in home_ru_html or "Откройте нужное рабочее пространство" in home_ru_html,
                    "home_running_badge": "Running" in home_html,
                    "setup_wizard_loaded": "Setup Guide" in setup_html and "MCP Endpoint" in setup_html,
                    "create_project_form_loaded": "Create Project" in create_project_form_html,
                    "created_project_flash_seen": "Project created successfully." in created_home_html,
                    "created_project_visible": "GUI Created Project" in created_home_html,
                    "created_project_start_visible": gui_created_project_id in created_home_html and "Start" in created_home_html,
                    "created_project_root_exists": gui_created_project_root.exists(),
                    "dashboard_has_title": "Project Overview" in dashboard_html,
                    "dashboard_has_mcp_endpoint": f"http://127.0.0.1:{mcp_port}/mcp" in dashboard_html,
                    "functions_list_loaded": "Functions" in functions_list_html and "main_handler" in functions_list_html,
                    "structures_list_loaded": "Structures" in structures_list_html,
                    "hypotheses_list_loaded": "Global Hypotheses" in hypotheses_list_html,
                    "graph_page_loaded": "Relation Graph" in graph_html and "<svg" in graph_html,
                    "focused_graph_loaded": "main_handler" in focused_graph_html,
                    "import_export_page_loaded": "Export Project" in import_export_html and "Import Project" in import_export_html,
                    "backups_page_loaded": "Create Backup" in backups_html and "Restore Backup" in backups_html,
                    "settings_page_loaded": "Project Settings" in settings_html,
                    "settings_save_flash_seen": "Restart the project from Home UI to apply them." in saved_settings_html,
                    "settings_updated_mcp_visible": f"http://127.0.0.1:{updated_mcp_port}/mcp" in saved_settings_html,
                    "home_updated_mcp_visible": f"http://127.0.0.1:{updated_mcp_port}/mcp" in home_after_settings_html,
                    "dashboard_ru_title": "Обзор проекта" in dashboard_ru_html,
                    "function_form_loaded": "Save Function" in new_function_form_html,
                    "structure_form_loaded": "Save Structure" in new_structure_form_html,
                    "search_has_result": "main_handler" in search_html,
                    "function_has_summary": "Entry point handler" in function_html,
                    "history_page_loaded": "Function Version History" in function_history_html,
                    "hypothesis_form_loaded": "Save Global Hypothesis" in new_hypothesis_form_html,
                    "pending_page_loaded": "Pending Changes" in pending_html,
                    "audit_page_loaded": "Audit Trail" in audit_html,
                    "structure_queue_flash_seen": "Change queued for confirmation." in queued_structure_html,
                    "queue_flash_seen": "Change queued for confirmation." in queued_form_html,
                    "confirm_flash_seen": "Pending change confirmed and applied." in confirmed_html,
                }
                print(json.dumps(ui_result, ensure_ascii=False, indent=2))
            finally:
                ui_home_process.terminate()
                try:
                    ui_home_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    ui_home_process.kill()
                    ui_home_process.wait(timeout=5)
        finally:
            server_process.terminate()
            try:
                server_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server_process.kill()
                server_process.wait(timeout=5)
            stack.close()

        print("\n== MCP API ==")
        mcp_stack = ExitStack()
        mcp_process, mcp_stdout_path, mcp_stderr_path = start_logged_process(
            mcp_stack,
            "mcp",
            [
                sys.executable,
                "-X",
                "utf8",
                "-m",
                "mcp_memory.cli",
                "--app-home",
                str(app_home),
                "run-mcp",
                "smoke-project",
                "--host",
                "127.0.0.1",
                "--port",
                str(manual_mcp_port),
            ],
            cli_env,
        )
        try:
            mcp_url = f"http://127.0.0.1:{manual_mcp_port}"
            wait_for_http(mcp_url + "/health", mcp_process, mcp_stdout_path, mcp_stderr_path, server_label="MCP API")
            init_payload = rpc_json(
                mcp_url + "/mcp",
                "initialize",
                {"protocolVersion": "2025-03-26"},
                request_id=1,
            )
            tools_payload = rpc_json(mcp_url + "/mcp", "tools/list", {}, request_id=2)
            search_payload = rpc_json(
                mcp_url + "/mcp",
                "tools/call",
                {
                    "name": "search_records",
                    "arguments": {
                        "q": "main_handler",
                        "entity_types": ["function"],
                        "binary_id": "sample-binary",
                        "limit": 5,
                    },
                },
                request_id=3,
            )
            related_payload = rpc_json(
                mcp_url + "/mcp",
                "tools/call",
                {
                    "name": "get_related",
                    "arguments": {
                        "entity_type": "function",
                        "entity_id": "fn_main",
                        "hops": 1,
                    },
                },
                request_id=4,
            )
            pending_structure = rpc_json(
                mcp_url + "/mcp",
                "tools/call",
                {
                    "name": "create_structure",
                    "arguments": {
                        "binary_id": "sample-binary",
                        "structure_id": "struct_pending",
                        "raw_name": "pending_t",
                        "current_name": "pending_t",
                        "summary": "Pending structure from MCP",
                        "created_by": "mcp-check",
                        "updated_by": "mcp-check",
                    },
                },
                request_id=5,
            )
            pending_changes = rpc_json(
                mcp_url + "/mcp",
                "tools/call",
                {"name": "list_pending_changes", "arguments": {}},
                request_id=6,
            )
            confirmed_structure = rpc_json(
                mcp_url + "/mcp",
                "tools/call",
                {
                    "name": "confirm_change",
                    "arguments": {
                        "pending_change_id": pending_structure["result"]["structuredContent"]["pending_change_id"],
                        "confirmed_by": "mcp-check",
                    },
                },
                request_id=7,
            )
            mcp_result = {
                "health_status": read_json(mcp_url + "/health")["status"],
                "initialize_server_name": init_payload["result"]["serverInfo"]["name"],
                "tool_count": len(tools_payload["result"]["tools"]),
                "search_count": len(search_payload["result"]["structuredContent"]["items"]),
                "related_count": len(related_payload["result"]["structuredContent"]["items"]),
                "pending_count": len(pending_changes["result"]["structuredContent"]["items"]),
                "confirmed_structure_id": confirmed_structure["result"]["structuredContent"]["applied"]["structure_id"],
            }
            print(json.dumps(mcp_result, ensure_ascii=False, indent=2))
        finally:
            mcp_process.terminate()
            try:
                mcp_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                mcp_process.kill()
                mcp_process.wait(timeout=5)
            mcp_stack.close()

        print("\n== GUI Launch ==")
        ui_launch_stack = ExitStack()
        ui_launch_process, ui_launch_stdout_path, ui_launch_stderr_path = start_logged_process(
            ui_launch_stack,
            "ui-home-launch",
            [
                sys.executable,
                "-X",
                "utf8",
                "-m",
                "mcp_memory.cli",
                "--app-home",
                str(app_home),
                "run-ui-home",
                "--host",
                "127.0.0.1",
                "--port",
                str(ui_home_port),
            ],
            cli_env,
        )
        try:
            ui_home_url = f"http://127.0.0.1:{ui_home_port}"
            base_url = f"http://127.0.0.1:{http_port}"
            mcp_url = f"http://{project.mcp_host}:{project.mcp_port}"
            wait_for_text(ui_home_url + "/", ui_launch_process, ui_launch_stdout_path, ui_launch_stderr_path)
            home_before = read_text(ui_home_url + "/")
            started_home = post_form(ui_home_url + "/projects/smoke-project/start?lang=en", {})
            wait_for_http(base_url + "/health", ui_launch_process, ui_launch_stdout_path, ui_launch_stderr_path, server_label="GUI launched HTTP API")
            wait_for_http(mcp_url + "/health", ui_launch_process, ui_launch_stdout_path, ui_launch_stderr_path, server_label="GUI launched MCP API")
            restarted_home = post_form(ui_home_url + "/projects/smoke-project/restart?lang=en", {})
            wait_for_http(base_url + "/health", ui_launch_process, ui_launch_stdout_path, ui_launch_stderr_path, server_label="GUI restarted HTTP API")
            wait_for_http(mcp_url + "/health", ui_launch_process, ui_launch_stdout_path, ui_launch_stderr_path, server_label="GUI restarted MCP API")
            stopped_home = post_form(ui_home_url + "/projects/smoke-project/stop?lang=en", {})
            wait_until_unavailable(base_url + "/health")
            wait_until_unavailable(mcp_url + "/health")
            gui_launch_result = {
                "home_start_button_visible": "Start" in home_before,
                "start_flash_seen": "started successfully" in started_home,
                "restart_flash_seen": "restarted successfully" in restarted_home,
                "stop_flash_seen": "were stopped" in stopped_home,
            }
            print(json.dumps(gui_launch_result, ensure_ascii=False, indent=2))
        finally:
            ui_launch_process.terminate()
            try:
                ui_launch_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                ui_launch_process.kill()
                ui_launch_process.wait(timeout=5)
            ui_launch_stack.close()

        print("\n== Transfer And Backup ==")
        export_bundle_path = artifacts_dir / "smoke_export.json"
        backup_bundle_path = artifacts_dir / "smoke_backup.zip"
        restored_root = artifacts_dir / "smoke_restored_project"
        if restored_root.exists():
            shutil.rmtree(restored_root)

        export_result = subprocess.run(
            [
                sys.executable,
                "-X",
                "utf8",
                "-m",
                "mcp_memory.cli",
                "--app-home",
                str(app_home),
                "export-json",
                "smoke-project",
                "--output",
                str(export_bundle_path),
            ],
            cwd=ROOT,
            env=cli_env,
            text=True,
            capture_output=True,
            check=True,
        )
        import_result = subprocess.run(
            [
                sys.executable,
                "-X",
                "utf8",
                "-m",
                "mcp_memory.cli",
                "--app-home",
                str(app_home),
                "import-json",
                "smoke-project",
                "--input",
                str(export_bundle_path),
                "--replace-existing",
            ],
            cwd=ROOT,
            env=cli_env,
            text=True,
            capture_output=True,
            check=True,
        )
        backup_result = subprocess.run(
            [
                sys.executable,
                "-X",
                "utf8",
                "-m",
                "mcp_memory.cli",
                "--app-home",
                str(app_home),
                "backup-project",
                "smoke-project",
                "--output",
                str(backup_bundle_path),
            ],
            cwd=ROOT,
            env=cli_env,
            text=True,
            capture_output=True,
            check=True,
        )
        restore_result = subprocess.run(
            [
                sys.executable,
                "-X",
                "utf8",
                "-m",
                "mcp_memory.cli",
                "--app-home",
                str(app_home),
                "restore-project",
                "--input",
                str(backup_bundle_path),
                "--project-root",
                str(restored_root),
                "--project-id",
                "restored-smoke-project",
                "--name",
                "Restored Smoke Project",
                "--http-port",
                str(restored_http_port),
                "--mcp-port",
                str(restored_mcp_port),
            ],
            cwd=ROOT,
            env=cli_env,
            text=True,
            capture_output=True,
            check=True,
        )
        transfer_result = {
            "export": json.loads(export_result.stdout),
            "import": json.loads(import_result.stdout),
            "backup": json.loads(backup_result.stdout),
            "restore": json.loads(restore_result.stdout),
        }
        print(json.dumps(transfer_result, ensure_ascii=False, indent=2))
    finally:
        database.close()

    print("\n== Runtime Logs ==")
    cli_log = project.logs_dir / "cli.log"
    http_log = project.logs_dir / "http-api.log"
    mcp_log = project.logs_dir / "mcp.log"
    ui_home_log = app_home / "logs" / "ui-home.log"
    log_result = {
        "cli_log_exists": cli_log.exists(),
        "http_log_exists": http_log.exists(),
        "mcp_log_exists": mcp_log.exists(),
        "ui_home_log_exists": ui_home_log.exists(),
        "cli_has_command_finish": cli_log.exists() and "command_finish" in cli_log.read_text(encoding="utf-8"),
        "http_has_request_complete": http_log.exists() and "request_complete" in http_log.read_text(encoding="utf-8"),
        "http_has_function_upserted": http_log.exists() and "function_upserted" in http_log.read_text(encoding="utf-8"),
        "mcp_has_tool_call": mcp_log.exists() and "tool_call" in mcp_log.read_text(encoding="utf-8"),
        "ui_home_has_project_probe": ui_home_log.exists() and "project_probe" in ui_home_log.read_text(encoding="utf-8"),
        "ui_home_has_project_start": ui_home_log.exists() and "project_start_requested" in ui_home_log.read_text(encoding="utf-8"),
        "ui_home_has_project_stop": ui_home_log.exists() and "project_stopped" in ui_home_log.read_text(encoding="utf-8"),
    }
    print(json.dumps(log_result, ensure_ascii=False, indent=2))

    print("\n== Done ==")
    return 0

def start_logged_process(
    stack: ExitStack,
    name: str,
    args: list[str],
    env: dict[str, str],
) -> tuple[subprocess.Popen[str], Path, Path]:
    stdout_path = ROOT / "artifacts" / f"{name}.stdout.txt"
    stderr_path = ROOT / "artifacts" / f"{name}.stderr.txt"
    stdout_handle = stack.enter_context(stdout_path.open("w", encoding="utf-8"))
    stderr_handle = stack.enter_context(stderr_path.open("w", encoding="utf-8"))
    process = subprocess.Popen(
        args,
        cwd=ROOT,
        env=env,
        text=True,
        stdout=stdout_handle,
        stderr=stderr_handle,
    )
    return process, stdout_path, stderr_path


def wait_for_http(
    url: str,
    server_process: subprocess.Popen[str],
    stdout_path: Path,
    stderr_path: Path,
    server_label: str = "HTTP API",
    timeout_seconds: float = 10.0,
) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if server_process.poll() is not None:
            raise RuntimeError(
                f"{server_label} process exited early.\n"
                f"stdout:\n{stdout_path.read_text(encoding='utf-8')}\n"
                f"stderr:\n{stderr_path.read_text(encoding='utf-8')}"
            )
        try:
            read_json(url, timeout_seconds=0.5)
            return
        except Exception:
            time.sleep(0.2)
    raise RuntimeError(
        f"{server_label} did not become ready within "
        f"{timeout_seconds} seconds.\nstdout:\n{stdout_path.read_text(encoding='utf-8')}\n"
        f"stderr:\n{stderr_path.read_text(encoding='utf-8')}"
    )


def wait_for_text(
    url: str,
    server_process: subprocess.Popen[str],
    stdout_path: Path,
    stderr_path: Path,
    timeout_seconds: float = 10.0,
) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if server_process.poll() is not None:
            raise RuntimeError(
                "UI process exited early.\n"
                f"stdout:\n{stdout_path.read_text(encoding='utf-8')}\n"
                f"stderr:\n{stderr_path.read_text(encoding='utf-8')}"
            )
        try:
            read_text(url, timeout_seconds=2.0)
            return
        except Exception:
            time.sleep(0.2)
    raise RuntimeError(
        "UI did not become ready within "
        f"{timeout_seconds} seconds.\nstdout:\n{stdout_path.read_text(encoding='utf-8')}\n"
        f"stderr:\n{stderr_path.read_text(encoding='utf-8')}"
    )


def wait_until_unavailable(url: str, timeout_seconds: float = 10.0) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            read_json(url, timeout_seconds=0.5)
        except Exception:
            return
        time.sleep(0.2)
    raise RuntimeError(f"Service at {url} stayed available longer than expected.")


def read_json(url: str, timeout_seconds: float = 5.0) -> dict[str, object]:
    with request.urlopen(url, timeout=timeout_seconds) as response:
        return json.loads(response.read().decode("utf-8"))


def read_text(url: str, timeout_seconds: float = 5.0) -> str:
    with request.urlopen(url, timeout=timeout_seconds) as response:
        return response.read().decode("utf-8")


def post_json(url: str, payload: dict[str, object], timeout_seconds: float = 5.0) -> dict[str, object]:
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with request.urlopen(req, timeout=timeout_seconds) as response:
        return json.loads(response.read().decode("utf-8"))


def post_form(url: str, payload: dict[str, str], timeout_seconds: float = 5.0) -> str:
    data = parse.urlencode(payload).encode("utf-8")
    req = request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with request.urlopen(req, timeout=timeout_seconds) as response:
        return response.read().decode("utf-8")


def rpc_json(url: str, method: str, params: dict[str, object], request_id: int | None) -> dict[str, object]:
    payload = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": params,
    }
    return post_json(url, payload)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        print("\n== Unhandled Exception ==")
        traceback.print_exc()
        raise
