from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tests.support import ROOT

from mcp_memory.config import ProjectRegistry
from mcp_memory.schema import (
    ProjectSchema,
    SchemaValidationError,
    list_bundled_schema_templates,
    load_bundled_schema_payload,
    load_project_schema,
)
from mcp_memory.services import ProjectService

_ = ROOT


class SchemaTests(unittest.TestCase):
    def test_bundled_schemas_load_and_validate(self) -> None:
        names = list_bundled_schema_templates()
        self.assertIn("general_knowledge", names)
        self.assertIn("reverse_engineering", names)
        self.assertIn("infrastructure_deployment", names)
        self.assertIn("research_notes", names)

        for name in names:
            schema = ProjectSchema.from_dict(load_bundled_schema_payload(name))
            self.assertGreaterEqual(len(schema.entity_types), 1)

    def test_schema_validation_rejects_unknown_required_field(self) -> None:
        with self.assertRaisesRegex(SchemaValidationError, "requires unknown field"):
            ProjectSchema.from_dict(
                {
                    "schema_version": "1",
                    "entity_types": [
                        {
                            "name": "note",
                            "fields": [{"name": "title", "label": "Title", "widget": "text"}],
                            "required": ["missing"],
                        }
                    ],
                }
            )

    def test_project_creation_copies_schema_template(self) -> None:
        with TemporaryDirectory() as tmp:
            app_home = Path(tmp) / "app"
            project_root = Path(tmp) / "project"
            service = ProjectService(ProjectRegistry(app_home / "app_config.json"))
            service.initialize_app()

            project = service.create_project(
                "p1",
                "Project One",
                project_root,
                12000,
                12001,
                schema_template="research_notes",
            )

            self.assertEqual(project.schema_path, project_root / "schema.json")
            self.assertTrue(project.schema_path.exists())
            schema = load_project_schema(project.schema_path)
            self.assertEqual(schema.entity("source").name, "source")

    def test_project_creation_accepts_explicit_schema_file(self) -> None:
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            schema_path = tmp_path / "custom.schema.json"
            schema_path.write_text(
                json.dumps(
                    {
                        "schema_version": "1",
                        "entity_types": [
                            {
                                "name": "custom",
                                "label": "Custom",
                                "fields": [{"name": "title", "label": "Title", "widget": "text"}],
                                "required": ["title"],
                                "title_field": "title",
                                "search_fields": ["title"],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            service = ProjectService(ProjectRegistry(tmp_path / "app" / "app_config.json"))
            service.initialize_app()
            project = service.create_project(
                "p1",
                "Project One",
                tmp_path / "project",
                12000,
                12001,
                schema_path=schema_path,
            )
            schema = load_project_schema(project.schema_path)
            self.assertEqual(schema.entity("custom").label, "Custom")


if __name__ == "__main__":
    unittest.main()
