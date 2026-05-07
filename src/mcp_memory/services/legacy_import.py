from __future__ import annotations

import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any

from mcp_memory.config import ProjectConfig
from mcp_memory.logging_utils import get_logger, log_event
from mcp_memory.schema import copy_schema_payload, load_bundled_schema_payload
from mcp_memory.storage import open_database

from .evidence import EvidenceService
from .functions import FunctionService
from .generic_evidence import GenericEvidenceService, GenericEvidenceWrite
from .generic_relations import GenericRelationService, GenericRelationWrite
from .hypotheses import GlobalHypothesisService
from .records import RecordService, RecordWrite
from .relations import RelationService
from .structures import StructureService
from .transfer import ProjectTransferService


class LegacyImportValidationError(ValueError):
    """Raised when a legacy database cannot be imported."""


class LegacyDatabaseImporter:
    def __init__(self) -> None:
        self._logger = get_logger("services")

    def import_legacy_database(
        self,
        project: ProjectConfig,
        legacy_database_path: Path,
        source_project_id: str | None = None,
        replace_existing: bool = False,
    ) -> dict[str, Any]:
        legacy_database_path = legacy_database_path.expanduser().resolve()
        if not legacy_database_path.exists():
            raise LegacyImportValidationError(f"legacy database not found: {legacy_database_path}")

        copy_schema_payload(project.schema_path, load_bundled_schema_payload("reverse_engineering"))
        source_project_id = source_project_id or self._detect_source_project_id(legacy_database_path)

        with open_database(project.database_path) as target_database:
            if replace_existing:
                ProjectTransferService()._clear_project_data(target_database, project.project_id)

            record_service = RecordService(target_database, project)
            relation_service = GenericRelationService(target_database, project)
            evidence_service = GenericEvidenceService(target_database, project)

            with open_database(legacy_database_path) as source_database:
                functions = FunctionService(source_database).list_project_functions(source_project_id)
                structures = StructureService(source_database).list_project_structures(source_project_id)
                hypotheses = GlobalHypothesisService(source_database).list_hypotheses(source_project_id)
                evidence = EvidenceService(source_database).list_project_evidence(source_project_id)
                relations = RelationService(source_database).list_project_relations(source_project_id)

            id_map: dict[tuple[str, str], str] = {}
            for item in functions:
                record = record_service.upsert_record(RecordWrite("function", self._function_payload(item), created_by="legacy-import", updated_by="legacy-import"))
                id_map[("function", item.function_id)] = record.record_id
            for item in structures:
                record = record_service.upsert_record(RecordWrite("structure", self._structure_payload(item), created_by="legacy-import", updated_by="legacy-import"))
                id_map[("structure", item.structure_id)] = record.record_id
            for item in hypotheses:
                record = record_service.upsert_record(RecordWrite("hypothesis", self._hypothesis_payload(item), created_by="legacy-import", updated_by="legacy-import"))
                id_map[("global_hypothesis", item.hypothesis_id)] = record.record_id
                id_map[("hypothesis", item.hypothesis_id)] = record.record_id

            imported_relations = 0
            for item in relations:
                from_type = self._map_entity_type(item.from_entity_type)
                to_type = self._map_entity_type(item.to_entity_type)
                from_record_id = id_map.get((item.from_entity_type, item.from_entity_id)) or id_map.get((from_type, item.from_entity_id))
                to_record_id = id_map.get((item.to_entity_type, item.to_entity_id)) or id_map.get((to_type, item.to_entity_id))
                if from_record_id is None or to_record_id is None:
                    continue
                relation_type = item.relation_type if item.relation_type in {"calls", "uses_structure", "supports", "refutes", "related_to"} else "related_to"
                relation_service.create_relation(
                    GenericRelationWrite(
                        from_entity_type=from_type,
                        from_record_id=from_record_id,
                        to_entity_type=to_type,
                        to_record_id=to_record_id,
                        relation_type=relation_type,
                        created_by=item.created_by,
                    )
                )
                imported_relations += 1

            imported_evidence = 0
            for item in evidence:
                entity_type = self._map_entity_type(item.entity_type)
                record_id = id_map.get((item.entity_type, item.entity_id)) or id_map.get((entity_type, item.entity_id))
                if record_id is None:
                    continue
                evidence_service.create_evidence(
                    GenericEvidenceWrite(
                        entity_type=entity_type,
                        record_id=record_id,
                        evidence_type=item.evidence_type,
                        description=item.description,
                        evidence_id=item.evidence_id,
                        excerpt=item.excerpt,
                        attachment_path=item.attachment_path,
                        media_type=item.media_type,
                        size_bytes=item.size_bytes,
                        source_origin=item.source_origin,
                        created_by=item.created_by,
                    )
                )
                imported_evidence += 1

        result = {
            "legacy_database_path": str(legacy_database_path),
            "source_project_id": source_project_id,
            "replace_existing": replace_existing,
            "counts": {
                "functions": len(functions),
                "structures": len(structures),
                "hypotheses": len(hypotheses),
                "records": len(functions) + len(structures) + len(hypotheses),
                "relations": imported_relations,
                "evidence": imported_evidence,
            },
        }
        log_event(
            self._logger,
            logging.INFO,
            "legacy_database_imported",
            project_id=project.project_id,
            source_project_id=source_project_id,
            record_count=result["counts"]["records"],
        )
        return result

    def _detect_source_project_id(self, database_path: Path) -> str:
        with open_database(database_path) as database:
            project_ids: list[str] = []
            for table in ("functions", "structures", "hypotheses", "evidence", "relations"):
                exists = database.connection.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone()
                if exists is None:
                    continue
                rows = database.connection.execute(f"SELECT DISTINCT project_id FROM {table} WHERE project_id IS NOT NULL").fetchall()
                project_ids.extend(str(row["project_id"]) for row in rows)
        unique_ids = sorted(set(project_ids))
        if not unique_ids:
            raise LegacyImportValidationError("legacy database does not contain project data")
        if len(unique_ids) > 1:
            raise LegacyImportValidationError("legacy database has multiple project_ids; pass --source-project-id")
        return unique_ids[0]

    def _function_payload(self, item: Any) -> dict[str, Any]:
        return {
            "slug": item.function_id,
            "binary_id": item.binary_id,
            "address": item.address,
            "raw_name": item.raw_name,
            "current_name": item.current_name,
            "summary": item.summary,
            "behavior_description": item.behavior_description,
            "tags": list(item.tags),
            "metadata": {
                "legacy_id": item.function_id,
                "important_variables": list(item.important_variables),
                "used_apis": list(item.used_apis),
                "strings": list(item.strings),
                "constants": list(item.constants),
                "confidence": item.confidence,
                "observed_facts": [asdict(fact) for fact in item.observed_facts],
                "hypotheses": [asdict(hypothesis) for hypothesis in item.hypotheses],
                "source_origin": item.source_origin,
            },
        }

    def _structure_payload(self, item: Any) -> dict[str, Any]:
        return {
            "slug": item.structure_id,
            "binary_id": item.binary_id,
            "raw_name": item.raw_name,
            "current_name": item.current_name,
            "summary": item.summary,
            "fields": [asdict(field) for field in item.fields],
            "tags": list(item.tags),
            "observed_facts": [asdict(fact) for fact in item.observed_facts],
            "hypotheses": [asdict(hypothesis) for hypothesis in item.hypotheses],
            "source_origin": item.source_origin,
        }

    def _hypothesis_payload(self, item: Any) -> dict[str, Any]:
        return {
            "slug": item.hypothesis_id,
            "title": item.title,
            "statement": item.statement,
            "status": item.status.value,
            "confidence": item.confidence,
            "binary_id": item.binary_id,
            "tags": list(item.tags),
            "observed_facts": [asdict(fact) for fact in item.observed_facts],
            "source_origin": item.source_origin,
        }

    def _map_entity_type(self, entity_type: str) -> str:
        return "hypothesis" if entity_type == "global_hypothesis" else entity_type
