from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mcp_memory.config import ProjectConfig
from mcp_memory.domain import (
    EvidenceWrite,
    FunctionWrite,
    GlobalHypothesisWrite,
    HypothesisItem,
    HypothesisStatus,
    ObservedFact,
    StructureMember,
    StructureWrite,
)
from mcp_memory.services.evidence import EvidenceService
from mcp_memory.services.functions import FunctionService
from mcp_memory.services.generic_evidence import GenericEvidenceService, GenericEvidenceWrite
from mcp_memory.services.generic_relations import GenericRelationService, GenericRelationWrite
from mcp_memory.services.hypotheses import GlobalHypothesisService
from mcp_memory.services.relations import RelationService, RelationWrite
from mcp_memory.services.records import RecordService, RecordWrite
from mcp_memory.services.structures import StructureService
from mcp_memory.logging_utils import get_logger, log_event
from mcp_memory.schema import ProjectSchema, copy_schema_payload, load_project_schema
from mcp_memory.storage import Database, open_database


class ProjectTransferService:
    def __init__(self) -> None:
        self._logger = get_logger("services")

    def export_project(
        self,
        project: ProjectConfig,
        output_path: Path | None = None,
    ) -> dict[str, Any]:
        bundle = self.export_bundle(project)
        final_path = output_path or self._default_export_path(project)
        final_path.parent.mkdir(parents=True, exist_ok=True)
        final_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
        log_event(
            self._logger,
            logging.INFO,
            "project_exported",
            project_id=project.project_id,
            output_path=final_path,
            record_count=bundle["counts"]["records"],
            relation_count=bundle["counts"]["relations"],
        )
        return {
            "output_path": str(final_path),
            "counts": bundle["counts"],
        }

    def export_bundle(self, project: ProjectConfig) -> dict[str, Any]:
        with open_database(project.database_path) as database:
            records = [asdict(item) for item in RecordService(database, project).list_records(include_archived=True, limit=100000)]
            record_keys = {(item["entity_type"], item["record_id"]) for item in records}
            relations = [
                asdict(item)
                for item in GenericRelationService(database, project).list_relations()
                if (item.from_entity_type, item.from_record_id) in record_keys and (item.to_entity_type, item.to_record_id) in record_keys
            ]
            evidence = [
                item
                for item in self._generic_evidence_rows(database, project.project_id)
                if (item["entity_type"], item["record_id"]) in record_keys
            ]
            attachment_paths = {item["attachment_path"] for item in evidence if item.get("attachment_path")}
            attachments = [
                item
                for item in self._attachment_rows(database, project.project_id)
                if item["relative_path"] in attachment_paths
            ]

        return {
            "bundle_version": 2,
            "project": {
                "project_id": project.project_id,
                "display_name": project.display_name,
                "write_mode": project.write_mode,
            },
            "schema": load_project_schema(project.schema_path).to_dict(),
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "counts": {
                "records": len(records),
                "evidence": len(evidence),
                "relations": len(relations),
                "attachments": len(attachments),
            },
            "records": {
                "items": records,
                "evidence": evidence,
                "relations": relations,
                "attachments": attachments,
            },
        }

    def import_project(
        self,
        project: ProjectConfig,
        input_path: Path,
        replace_existing: bool = False,
    ) -> dict[str, Any]:
        bundle = json.loads(input_path.read_text(encoding="utf-8"))
        return self.import_bundle(project, bundle, replace_existing=replace_existing, input_path=input_path)

    def import_bundle(
        self,
        project: ProjectConfig,
        bundle: dict[str, Any],
        replace_existing: bool = False,
        input_path: Path | None = None,
    ) -> dict[str, Any]:
        bundle_version = int(bundle.get("bundle_version", 0))
        if bundle_version == 1:
            return self._import_legacy_v1_bundle(project, bundle, replace_existing=replace_existing, input_path=input_path)
        if bundle_version != 2:
            raise ValueError(f"Unsupported bundle_version: {bundle_version}")

        records = bundle.get("records")
        if not isinstance(records, dict):
            raise ValueError("Bundle records must be an object")
        schema_payload = bundle.get("schema")
        if not isinstance(schema_payload, dict):
            raise ValueError("Bundle schema must be an object")
        ProjectSchema.from_dict(schema_payload)
        copy_schema_payload(project.schema_path, schema_payload)

        with open_database(project.database_path) as database:
            if replace_existing:
                self._clear_project_data(database, project.project_id)

            record_service = RecordService(database, project)
            relation_service = GenericRelationService(database, project)
            evidence_service = GenericEvidenceService(database, project)
            record_items = records.get("items", [])
            evidence_items = records.get("evidence", [])
            relation_items = records.get("relations", [])

            for item in record_items:
                record = record_service.upsert_record(self._record_write(item))
                if str(item.get("status", "active")) == "archived":
                    record_service.archive_record(record.entity_type, record.record_id, archived_by=str(item.get("updated_by", "import")))
            for item in relation_items:
                relation_service.create_relation(self._generic_relation_write(item))
            for item in evidence_items:
                evidence_service.create_evidence(self._generic_evidence_write(item))

        log_event(
            self._logger,
            logging.INFO,
            "project_imported",
            project_id=project.project_id,
            input_path=input_path,
            replace_existing=replace_existing,
            record_count=len(record_items),
            relation_count=len(relation_items),
        )
        return {
            "input_path": None if input_path is None else str(input_path),
            "replace_existing": replace_existing,
            "counts": {
                "records": len(record_items),
                "evidence": len(evidence_items),
                "relations": len(relation_items),
                "attachments": len(records.get("attachments", [])),
            },
        }

    def _clear_project_data(self, database: Database, project_id: str) -> None:
        connection = database.transaction()
        connection.execute("DELETE FROM duplicate_candidates WHERE project_id = ?", (project_id,))
        connection.execute("DELETE FROM entity_versions WHERE project_id = ?", (project_id,))
        connection.execute("DELETE FROM audit_log WHERE project_id = ?", (project_id,))
        connection.execute("DELETE FROM relations WHERE project_id = ?", (project_id,))
        connection.execute("DELETE FROM evidence WHERE project_id = ?", (project_id,))
        connection.execute("DELETE FROM attachments WHERE project_id = ?", (project_id,))
        connection.execute("DELETE FROM entity_facts WHERE project_id = ?", (project_id,))
        connection.execute("DELETE FROM entity_tags WHERE project_id = ?", (project_id,))
        connection.execute("DELETE FROM tags WHERE project_id = ?", (project_id,))
        connection.execute("DELETE FROM hypotheses WHERE project_id = ?", (project_id,))
        connection.execute("DELETE FROM functions WHERE project_id = ?", (project_id,))
        connection.execute("DELETE FROM structures WHERE project_id = ?", (project_id,))
        connection.execute("DELETE FROM search_documents_fts WHERE project_id = ?", (project_id,))
        connection.execute("DELETE FROM search_documents WHERE project_id = ?", (project_id,))
        connection.execute("DELETE FROM records WHERE project_id = ?", (project_id,))
        connection.commit()

    def _generic_evidence_rows(self, database: Database, project_id: str) -> list[dict[str, Any]]:
        rows = database.connection.execute(
            """
            SELECT e.*, a.relative_path, a.media_type, a.size_bytes
            FROM evidence e
            LEFT JOIN attachments a ON a.attachment_id = e.attachment_id
            WHERE e.project_id = ?
            ORDER BY e.created_at
            """,
            (project_id,),
        ).fetchall()
        return [
            {
                "evidence_id": str(row["evidence_id"]),
                "entity_type": str(row["entity_type"]),
                "record_id": str(row["entity_id"]),
                "evidence_type": str(row["evidence_type"]),
                "description": str(row["description"]),
                "excerpt": None if row["excerpt"] is None else str(row["excerpt"]),
                "attachment_path": None if row["relative_path"] is None else str(row["relative_path"]),
                "media_type": None if row["media_type"] is None else str(row["media_type"]),
                "size_bytes": None if row["size_bytes"] is None else int(row["size_bytes"]),
                "source_origin": str(row["source_origin"]),
                "created_by": str(row["created_by"]),
            }
            for row in rows
        ]

    def _attachment_rows(self, database: Database, project_id: str) -> list[dict[str, Any]]:
        rows = database.connection.execute(
            "SELECT attachment_id, relative_path, media_type, size_bytes, created_at, created_by FROM attachments WHERE project_id = ? ORDER BY created_at",
            (project_id,),
        ).fetchall()
        return [
            {
                "attachment_id": str(row["attachment_id"]),
                "relative_path": str(row["relative_path"]),
                "media_type": None if row["media_type"] is None else str(row["media_type"]),
                "size_bytes": None if row["size_bytes"] is None else int(row["size_bytes"]),
                "created_at": str(row["created_at"]),
                "created_by": str(row["created_by"]),
            }
            for row in rows
        ]

    def _record_write(self, payload: dict[str, Any]) -> RecordWrite:
        return RecordWrite(
            entity_type=str(payload["entity_type"]),
            record_id=str(payload["record_id"]),
            payload=dict(payload.get("payload", {})),
            source_origin=str(payload.get("source_origin", "import")),
            created_by=str(payload.get("created_by", "import")),
            updated_by=str(payload.get("updated_by", "import")),
        )

    def _generic_relation_write(self, payload: dict[str, Any]) -> GenericRelationWrite:
        return GenericRelationWrite(
            from_entity_type=str(payload["from_entity_type"]),
            from_record_id=str(payload["from_record_id"]),
            to_entity_type=str(payload["to_entity_type"]),
            to_record_id=str(payload["to_record_id"]),
            relation_type=str(payload["relation_type"]),
            created_by=str(payload.get("created_by", "import")),
        )

    def _generic_evidence_write(self, payload: dict[str, Any]) -> GenericEvidenceWrite:
        return GenericEvidenceWrite(
            evidence_id=str(payload["evidence_id"]),
            entity_type=str(payload["entity_type"]),
            record_id=str(payload["record_id"]),
            evidence_type=str(payload["evidence_type"]),
            description=str(payload["description"]),
            excerpt=None if payload.get("excerpt") is None else str(payload["excerpt"]),
            attachment_path=None if payload.get("attachment_path") is None else str(payload["attachment_path"]),
            media_type=None if payload.get("media_type") is None else str(payload["media_type"]),
            size_bytes=None if payload.get("size_bytes") is None else int(payload["size_bytes"]),
            created_by=str(payload.get("created_by", "import")),
            source_origin=str(payload.get("source_origin", "import")),
        )

    def _import_legacy_v1_bundle(
        self,
        project: ProjectConfig,
        bundle: dict[str, Any],
        replace_existing: bool,
        input_path: Path | None,
    ) -> dict[str, Any]:
        records = bundle.get("records")
        if not isinstance(records, dict):
            raise ValueError("Bundle records must be an object")

        with open_database(project.database_path) as database:
            if replace_existing:
                self._clear_project_data(database, project.project_id)

            function_service = FunctionService(database)
            structure_service = StructureService(database)
            hypothesis_service = GlobalHypothesisService(database)
            evidence_service = EvidenceService(database)
            relation_service = RelationService(database)

            functions = records.get("functions", [])
            structures = records.get("structures", [])
            global_hypotheses = records.get("global_hypotheses", [])
            evidence = records.get("evidence", [])
            relations = records.get("relations", [])

            for item in functions:
                function_service.upsert_function(self._function_write(project.project_id, item))
            for item in structures:
                structure_service.upsert_structure(self._structure_write(project.project_id, item))
            for item in global_hypotheses:
                hypothesis_service.upsert_hypothesis(self._global_hypothesis_write(project.project_id, item))
            for item in evidence:
                evidence_service.create_evidence(self._evidence_write(project.project_id, item))
            for item in relations:
                relation_service.create_relation(self._relation_write(project.project_id, item))

        return {
            "input_path": None if input_path is None else str(input_path),
            "replace_existing": replace_existing,
            "counts": {
                "functions": len(functions),
                "structures": len(structures),
                "global_hypotheses": len(global_hypotheses),
                "evidence": len(evidence),
                "relations": len(relations),
            },
        }

    def _default_export_path(self, project: ProjectConfig) -> Path:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        return project.exports_dir / f"{project.project_id}-{timestamp}.json"

    def _function_write(self, project_id: str, payload: dict[str, Any]) -> FunctionWrite:
        return FunctionWrite(
            project_id=project_id,
            binary_id=str(payload["binary_id"]),
            function_id=str(payload["function_id"]),
            address=str(payload["address"]),
            raw_name=str(payload["raw_name"]),
            current_name=str(payload["current_name"]),
            summary=str(payload["summary"]),
            behavior_description=str(payload["behavior_description"]),
            important_variables=[str(item) for item in payload.get("important_variables", [])],
            used_apis=[str(item) for item in payload.get("used_apis", [])],
            strings=[str(item) for item in payload.get("strings", [])],
            constants=[str(item) for item in payload.get("constants", [])],
            confidence=None if payload.get("confidence") is None else float(payload["confidence"]),
            tags=[str(item) for item in payload.get("tags", [])],
            observed_facts=self._observed_facts(payload.get("observed_facts", [])),
            hypotheses=self._hypotheses(payload.get("hypotheses", [])),
            source_origin=str(payload.get("source_origin", "import")),
            created_by=str(payload.get("created_by", "import")),
            updated_by=str(payload.get("updated_by", payload.get("created_by", "import"))),
            allow_conflict=bool(payload.get("allow_conflict", False)),
        )

    def _structure_write(self, project_id: str, payload: dict[str, Any]) -> StructureWrite:
        return StructureWrite(
            project_id=project_id,
            binary_id=str(payload["binary_id"]),
            structure_id=str(payload["structure_id"]),
            raw_name=str(payload["raw_name"]),
            current_name=str(payload["current_name"]),
            summary=str(payload["summary"]),
            fields=[
                StructureMember(
                    name=str(item["name"]),
                    offset=str(item["offset"]),
                    data_type=str(item["data_type"]),
                    size=None if item.get("size") is None else int(item["size"]),
                    comment=str(item.get("comment", "")),
                )
                for item in payload.get("fields", [])
            ],
            tags=[str(item) for item in payload.get("tags", [])],
            observed_facts=self._observed_facts(payload.get("observed_facts", [])),
            hypotheses=self._hypotheses(payload.get("hypotheses", [])),
            source_origin=str(payload.get("source_origin", "import")),
            created_by=str(payload.get("created_by", "import")),
            updated_by=str(payload.get("updated_by", payload.get("created_by", "import"))),
        )

    def _global_hypothesis_write(self, project_id: str, payload: dict[str, Any]) -> GlobalHypothesisWrite:
        return GlobalHypothesisWrite(
            project_id=project_id,
            hypothesis_id=str(payload["hypothesis_id"]),
            title=str(payload["title"]),
            statement=str(payload["statement"]),
            status=HypothesisStatus(str(payload.get("status", "new"))),
            confidence=None if payload.get("confidence") is None else float(payload["confidence"]),
            binary_id=None if payload.get("binary_id") is None else str(payload["binary_id"]),
            tags=[str(item) for item in payload.get("tags", [])],
            observed_facts=self._observed_facts(payload.get("observed_facts", [])),
            source_origin=str(payload.get("source_origin", "import")),
            created_by=str(payload.get("created_by", "import")),
            updated_by=str(payload.get("updated_by", payload.get("created_by", "import"))),
        )

    def _evidence_write(self, project_id: str, payload: dict[str, Any]) -> EvidenceWrite:
        return EvidenceWrite(
            project_id=project_id,
            evidence_id=str(payload["evidence_id"]),
            entity_type=str(payload["entity_type"]),
            entity_id=str(payload["entity_id"]),
            evidence_type=str(payload["evidence_type"]),
            description=str(payload["description"]),
            address_start=None if payload.get("address_start") is None else str(payload["address_start"]),
            address_end=None if payload.get("address_end") is None else str(payload["address_end"]),
            xref=None if payload.get("xref") is None else str(payload["xref"]),
            block_ref=None if payload.get("block_ref") is None else str(payload["block_ref"]),
            excerpt=None if payload.get("excerpt") is None else str(payload["excerpt"]),
            attachment_path=None if payload.get("attachment_path") is None else str(payload["attachment_path"]),
            media_type=None if payload.get("media_type") is None else str(payload["media_type"]),
            size_bytes=None if payload.get("size_bytes") is None else int(payload["size_bytes"]),
            source_origin=str(payload.get("source_origin", "import")),
            created_by=str(payload.get("created_by", "import")),
        )

    def _relation_write(self, project_id: str, payload: dict[str, Any]) -> RelationWrite:
        return RelationWrite(
            project_id=project_id,
            from_entity_type=str(payload["from_entity_type"]),
            from_entity_id=str(payload["from_entity_id"]),
            to_entity_type=str(payload["to_entity_type"]),
            to_entity_id=str(payload["to_entity_id"]),
            relation_type=str(payload["relation_type"]),
            created_by=str(payload.get("created_by", "import")),
        )

    def _observed_facts(self, items: list[dict[str, Any]]) -> list[ObservedFact]:
        return [
            ObservedFact(
                fact=str(item["fact"]),
                source_origin=str(item.get("source_origin", "import")),
            )
            for item in items
        ]

    def _hypotheses(self, items: list[dict[str, Any]]) -> list[HypothesisItem]:
        return [
            HypothesisItem(
                statement=str(item["statement"]),
                status=HypothesisStatus(str(item.get("status", "new"))),
                confidence=None if item.get("confidence") is None else float(item["confidence"]),
                source_origin=str(item.get("source_origin", "import")),
            )
            for item in items
        ]
