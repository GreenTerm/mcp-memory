from __future__ import annotations

import json
import re
import sys
from pathlib import Path
import tomllib


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


EXPECTED_VERSION = "1.0.3"


def main() -> int:
    artifacts_dir = ROOT / "artifacts"
    artifacts_dir.mkdir(exist_ok=True)
    report_path = artifacts_dir / "release_check.txt"
    lines: list[str] = []

    def record(message: str) -> None:
        lines.append(message)
        print(message)

    with (ROOT / "pyproject.toml").open("rb") as handle:
        pyproject = tomllib.load(handle)
    version = pyproject["project"]["version"]
    require(version == EXPECTED_VERSION, f"pyproject version is {version}, expected {EXPECTED_VERSION}")
    record(f"version={version}")

    init_text = (ROOT / "src" / "mcp_memory" / "__init__.py").read_text(encoding="utf-8")
    require(f'__version__ = "{EXPECTED_VERSION}"' in init_text, "__init__.py version mismatch")

    required_version_files = [
        "AGENTS.md",
        "README.md",
        "docs/temporary-release-roadmap.md",
        "docs/future-plans.md",
        "docs/modules.md",
        "docs/generic-knowledge-refactor-plan.md",
    ]
    for relative in required_version_files:
        text = (ROOT / relative).read_text(encoding="utf-8")
        require(EXPECTED_VERSION in text, f"{relative} does not mention {EXPECTED_VERSION}")
    record("version_docs=ok")

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for link_target in re.findall(r"\]\((docs/[^)]+)\)", readme):
        target = ROOT / link_target
        require(target.exists(), f"README link target is missing: {link_target}")
    record("readme_links=ok")

    from mcp_memory.schema import ProjectSchema, list_bundled_schema_templates, load_bundled_schema_payload

    templates = list_bundled_schema_templates()
    require(templates, "no bundled schema templates found")
    for template in templates:
        ProjectSchema.from_dict(load_bundled_schema_payload(template))
    record("bundled_schemas=ok:" + ",".join(templates))

    required_scripts = [
        "scripts/run_local_checks.ps1",
        "scripts/run_coverage.ps1",
        "scripts/local_smoke_check.py",
        "scripts/run_release_check.ps1",
    ]
    for relative in required_scripts:
        require((ROOT / relative).exists(), f"release script missing: {relative}")
    record("release_scripts=ok")

    roadmap = (ROOT / "docs" / "temporary-release-roadmap.md").read_text(encoding="utf-8")
    for version_label in ("0.9.0", "1.0.0"):
        require(f"- [x] `{version_label}`" in roadmap, f"roadmap does not mark {version_label} done")
    record("roadmap_status=ok")

    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    record(f"report={report_path}")
    return 0


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


if __name__ == "__main__":
    raise SystemExit(main())
