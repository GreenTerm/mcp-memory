from __future__ import annotations

import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
import traceback
from pathlib import Path
from urllib import error, request


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def allocate_port() -> int:
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
    from mcp_memory.services import GenericEvidenceService, GenericEvidenceWrite, GenericRelationService, GenericRelationWrite, RecordService, RecordWrite
    from mcp_memory.storage import open_database

    print("imports=ok")

    artifacts_dir = ROOT / "artifacts"
    run_root = artifacts_dir / f"smoke_run_{int(time.time() * 1000)}_{os.getpid()}"
    app_home = run_root / "app_home"
    project_root = run_root / "project"
    http_port = allocate_port()
    mcp_port = allocate_port()
    ui_home_port = allocate_port()
    restored_http_port = allocate_port()
    restored_mcp_port = allocate_port()

    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC)

    def run_cli(args: list[str]) -> dict:
        result = subprocess.run(
            [sys.executable, "-X", "utf8", "-m", "mcp_memory.cli", "--app-home", str(app_home), *args],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )
        print("cli_" + args[0].replace("-", "_") + "=" + result.stdout.strip())
        return json.loads(result.stdout)

    run_cli(["init-app"])
    project_payload = run_cli(
        [
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
            "--schema-template",
            "general_knowledge",
            "--write-mode",
            "auto",
        ]
    )
    run_cli(["validate-schema", "--project-id", "smoke-project"])
    run_cli(["show-schema", "smoke-project"])

    registry = ProjectRegistry(app_home / "app_config.json")
    project = registry.get_project("smoke-project")
    if project is None:
        raise RuntimeError("smoke-project was not registered")
    print(f"project_db={project.database_path}")

    with open_database(project.database_path) as database:
        records = RecordService(database, project)
        first = records.upsert_record(
            RecordWrite(
                "note",
                {
                    "slug": "smoke-note",
                    "title": "Smoke Note",
                    "summary": "Generic smoke record",
                    "body": "Smoke check searchable body",
                    "tags": ["smoke", "generic"],
                },
                created_by="local-check",
                updated_by="local-check",
            )
        )
        second = records.upsert_record(
            RecordWrite(
                "note",
                {"slug": "smoke-linked", "title": "Smoke Linked", "summary": "Linked record"},
                created_by="local-check",
                updated_by="local-check",
            )
        )
        GenericRelationService(database, project).create_relation(
            GenericRelationWrite("note", first.record_id, "note", second.record_id, "related_to", created_by="local-check")
        )
        GenericEvidenceService(database, project).create_evidence(
            GenericEvidenceWrite("note", first.record_id, "excerpt", "Smoke evidence", excerpt="local smoke excerpt", created_by="local-check")
        )
        loaded = records.get_record("note", "smoke-note")
        if loaded is None:
            raise RuntimeError("generic record was not saved")
        print(f"service_record={loaded.record_id}:{loaded.slug}")

    export_path = artifacts_dir / "smoke_export.json"
    backup_path = artifacts_dir / "smoke_backup.zip"
    restored_root = artifacts_dir / "smoke_restored_project"
    if restored_root.exists():
        shutil.rmtree(restored_root)
    export_result = run_cli(["export-json", "smoke-project", "--output", str(export_path)])
    if export_result["counts"]["records"] < 2:
        raise RuntimeError("generic export did not include records")
    run_cli(["import-json", "smoke-project", "--input", str(export_path), "--replace-existing"])
    run_cli(["backup-project", "smoke-project", "--output", str(backup_path)])
    run_cli(
        [
            "restore-project",
            "--input",
            str(backup_path),
            "--project-root",
            str(restored_root),
            "--project-id",
            "smoke-restored",
            "--name",
            "Smoke Restored",
            "--http-port",
            str(restored_http_port),
            "--mcp-port",
            str(restored_mcp_port),
        ]
    )

    http_proc = subprocess.Popen(
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
        ],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=(artifacts_dir / "http-api.stderr.txt").open("w", encoding="utf-8"),
    )
    mcp_proc = subprocess.Popen(
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
        ],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=(artifacts_dir / "mcp.stderr.txt").open("w", encoding="utf-8"),
    )
    ui_proc = subprocess.Popen(
        [
            sys.executable,
            "-X",
            "utf8",
            "-m",
            "mcp_memory.cli",
            "--app-home",
            str(app_home),
            "run-ui-home",
            "--port",
            str(ui_home_port),
        ],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=(artifacts_dir / "ui-home.stderr.txt").open("w", encoding="utf-8"),
    )
    try:
        wait_for_json(f"http://127.0.0.1:{http_port}/health")
        wait_for_json(f"http://127.0.0.1:{mcp_port}/health")
        wait_for_text(f"http://127.0.0.1:{ui_home_port}/")
        gateway_base = f"http://127.0.0.1:{ui_home_port}/smoke-project"
        gateway_ui = wait_for_text(f"{gateway_base}/ui/?lang=en")
        if "Smoke Project" not in gateway_ui and "Project Overview" not in gateway_ui:
            raise RuntimeError("Home gateway did not render project UI")

        schema = get_json(f"http://127.0.0.1:{http_port}/schema")
        if schema["entity_types"][0]["name"] != "note":
            raise RuntimeError("HTTP schema did not expose default note entity")
        gateway_schema = get_json(f"{gateway_base}/schema")
        if gateway_schema["entity_types"][0]["name"] != "note":
            raise RuntimeError("Home gateway schema proxy did not expose default note entity")
        created = post_json(
            f"http://127.0.0.1:{http_port}/records/note",
            {"payload": {"slug": "http-note", "title": "HTTP Note", "body": "HTTP searchable body"}, "created_by": "smoke"},
        )
        search = post_json(f"http://127.0.0.1:{http_port}/search", {"q": "searchable", "entity_types": ["note"]})
        if not search["items"]:
            raise RuntimeError("HTTP generic search returned no results")
        print(f"http_record={created['record_id']}")

        mcp_client = McpHttpClient(f"http://127.0.0.1:{mcp_port}/mcp")
        mcp_client.initialize()
        gateway_mcp_client = McpHttpClient(f"{gateway_base}/mcp")
        gateway_mcp_client.initialize()

        tools = mcp_client.rpc("tools/list", {})["result"]["tools"]
        tool_names = {item["name"] for item in tools}
        if {"get_schema", "upsert_record", "search_records"} - tool_names:
            raise RuntimeError("MCP generic tools are missing")
        gateway_tools = gateway_mcp_client.rpc("tools/list", {})["result"]["tools"]
        gateway_tool_names = {item["name"] for item in gateway_tools}
        if {"get_schema", "upsert_record", "search_records"} - gateway_tool_names:
            raise RuntimeError("Home gateway MCP proxy is missing generic tools")
        mcp_created = mcp_client.call_tool(
            "upsert_record",
            {"entity_type": "note", "payload": {"slug": "mcp-note", "title": "MCP Note", "body": "MCP body"}},
        )
        print(f"mcp_record={mcp_created['record_id']}")

        long_body = "D" * 4096
        mcp_long = mcp_client.call_tool(
            "upsert_record",
            {"entity_type": "note", "payload": {"slug": "mcp-long-direct", "title": "MCP Long Direct", "body": long_body}},
        )
        if mcp_long["payload"]["body"] != long_body:
            raise RuntimeError("MCP direct 4KB payload did not round-trip")
        gateway_body = "G" * 4096
        gateway_long = gateway_mcp_client.call_tool(
            "upsert_record",
            {"entity_type": "note", "payload": {"slug": "mcp-long-gateway", "title": "MCP Long Gateway", "body": gateway_body}},
        )
        if gateway_long["payload"]["body"] != gateway_body:
            raise RuntimeError("Home gateway MCP 4KB payload did not round-trip")
        print("mcp_long_payloads=ok")
    finally:
        for proc in (http_proc, mcp_proc, ui_proc):
            proc.terminate()
        for proc in (http_proc, mcp_proc, ui_proc):
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()

    print("\nSMOKE CHECK PASSED")
    print(f"run_root={run_root}")
    return 0


def wait_for_json(url: str, timeout: float = 20.0) -> dict:
    deadline = time.time() + timeout
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            return get_json(url)
        except Exception as exc:
            last_error = exc
            time.sleep(0.25)
    raise RuntimeError(f"timed out waiting for {url}: {last_error}")


def wait_for_text(url: str, timeout: float = 20.0) -> str:
    deadline = time.time() + timeout
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            with request.urlopen(url, timeout=2) as response:
                return response.read().decode("utf-8", errors="replace")
        except Exception as exc:
            last_error = exc
            time.sleep(0.25)
    raise RuntimeError(f"timed out waiting for {url}: {last_error}")


def get_json(url: str) -> dict:
    with request.urlopen(url, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def post_json(url: str, payload: dict) -> dict:
    req = request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
    with request.urlopen(req, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


class McpHttpClient:
    def __init__(self, url: str) -> None:
        self.url = url
        self.session_id: str | None = None
        self.next_id = 1

    def initialize(self) -> None:
        response = self.rpc(
            "initialize",
            {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "mcp-memory-smoke", "version": "local"},
            },
            include_session=False,
        )
        self.session_id = response["_headers"].get("Mcp-Session-Id") or response["_headers"].get("mcp-session-id")
        if not self.session_id:
            raise RuntimeError("MCP initialize did not return a session id")
        status, _, body = self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        if status != 202 or body:
            raise RuntimeError(f"MCP initialized notification returned unexpected response: status={status} body={body!r}")

    def rpc(self, method: str, params: dict, include_session: bool = True) -> dict:
        request_id = self.next_id
        self.next_id += 1
        status, headers, body = self._post(
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
            include_session=include_session,
        )
        if status != 200:
            raise RuntimeError(f"MCP request failed: status={status} body={body!r}")
        response = json.loads(body.decode("utf-8"))
        response["_headers"] = headers
        return response

    def call_tool(self, name: str, arguments: dict) -> dict:
        response = self.rpc("tools/call", {"name": name, "arguments": arguments})
        if "error" in response:
            raise RuntimeError(response["error"])
        return response["result"]["structuredContent"]

    def _post(self, payload: dict, include_session: bool = True) -> tuple[int, dict[str, str], bytes]:
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json, text/event-stream",
        }
        if include_session and self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        req = request.Request(
            self.url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=10) as response:
                return response.status, dict(response.headers.items()), response.read()
        except error.HTTPError as exc:
            return exc.code, dict(exc.headers.items()), exc.read()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        traceback.print_exc()
        raise
