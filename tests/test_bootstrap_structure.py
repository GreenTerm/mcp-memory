from pathlib import Path


def test_expected_layout_files_exist() -> None:
    root = Path(__file__).resolve().parents[1]
    expected = [
        root / "pyproject.toml",
        root / "sql" / "migrations" / "001_initial.sql",
        root / "src" / "mcp_memory" / "cli" / "__main__.py",
        root / "src" / "mcp_memory" / "config" / "registry.py",
        root / "src" / "mcp_memory" / "domain" / "models.py",
        root / "src" / "mcp_memory" / "api" / "server.py",
        root / "src" / "mcp_memory" / "mcp" / "server.py",
        root / "src" / "mcp_memory" / "services" / "structures.py",
        root / "src" / "mcp_memory" / "services" / "hypotheses.py",
        root / "src" / "mcp_memory" / "services" / "evidence.py",
        root / "src" / "mcp_memory" / "services" / "relations.py",
        root / "src" / "mcp_memory" / "services" / "search.py",
        root / "src" / "mcp_memory" / "services" / "transfer.py",
        root / "src" / "mcp_memory" / "services" / "archive.py",
        root / "src" / "mcp_memory" / "services" / "functions.py",
    ]
    for path in expected:
        assert path.exists(), f"Missing expected bootstrap file: {path}"
