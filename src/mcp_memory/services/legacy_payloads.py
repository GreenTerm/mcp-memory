from __future__ import annotations

from typing import Any

from mcp_memory.domain import EvidenceWrite, FunctionWrite, GlobalHypothesisWrite, HypothesisItem, ObservedFact, StructureMember, StructureWrite


def function_write_from_payload(project_id: str, payload: dict[str, Any]) -> FunctionWrite:
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
        confidence=float(payload["confidence"]) if payload.get("confidence") is not None else None,
        tags=[str(item) for item in payload.get("tags", [])],
        observed_facts=[
            ObservedFact(fact=str(item["fact"]), source_origin=str(item.get("source_origin", "api")))
            for item in payload.get("observed_facts", [])
        ],
        hypotheses=_build_hypotheses(payload.get("hypotheses", [])),
        source_origin=str(payload.get("source_origin", "api")),
        created_by=str(payload.get("created_by", "api")),
        updated_by=str(payload.get("updated_by", payload.get("created_by", "api"))),
        allow_conflict=bool(payload.get("allow_conflict", False)),
    )


def structure_write_from_payload(project_id: str, payload: dict[str, Any]) -> StructureWrite:
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
                size=int(item["size"]) if item.get("size") is not None else None,
                comment=str(item.get("comment", "")),
            )
            for item in payload.get("fields", [])
        ],
        tags=[str(item) for item in payload.get("tags", [])],
        observed_facts=[
            ObservedFact(fact=str(item["fact"]), source_origin=str(item.get("source_origin", "api")))
            for item in payload.get("observed_facts", [])
        ],
        hypotheses=_build_hypotheses(payload.get("hypotheses", [])),
        source_origin=str(payload.get("source_origin", "api")),
        created_by=str(payload.get("created_by", "api")),
        updated_by=str(payload.get("updated_by", payload.get("created_by", "api"))),
    )


def global_hypothesis_write_from_payload(project_id: str, payload: dict[str, Any]) -> GlobalHypothesisWrite:
    from mcp_memory.domain import HypothesisStatus

    return GlobalHypothesisWrite(
        project_id=project_id,
        hypothesis_id=str(payload["hypothesis_id"]),
        title=str(payload["title"]),
        statement=str(payload["statement"]),
        status=HypothesisStatus(str(payload.get("status", "new"))),
        confidence=float(payload["confidence"]) if payload.get("confidence") is not None else None,
        binary_id=None if payload.get("binary_id") is None else str(payload["binary_id"]),
        tags=[str(item) for item in payload.get("tags", [])],
        observed_facts=[
            ObservedFact(fact=str(item["fact"]), source_origin=str(item.get("source_origin", "api")))
            for item in payload.get("observed_facts", [])
        ],
        source_origin=str(payload.get("source_origin", "api")),
        created_by=str(payload.get("created_by", "api")),
        updated_by=str(payload.get("updated_by", payload.get("created_by", "api"))),
    )


def evidence_write_from_payload(project_id: str, payload: dict[str, Any]) -> EvidenceWrite:
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
        size_bytes=int(payload["size_bytes"]) if payload.get("size_bytes") is not None else None,
        source_origin=str(payload.get("source_origin", "api")),
        created_by=str(payload.get("created_by", "api")),
    )


def _build_hypotheses(items: list[dict[str, Any]]) -> list[HypothesisItem]:
    from mcp_memory.domain import HypothesisStatus

    return [
        HypothesisItem(
            statement=str(item["statement"]),
            status=HypothesisStatus(str(item.get("status", "new"))),
            confidence=float(item["confidence"]) if item.get("confidence") is not None else None,
            source_origin=str(item.get("source_origin", "api")),
        )
        for item in items
    ]
