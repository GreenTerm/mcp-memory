from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mcp_memory.storage import Database


@dataclass(slots=True)
class SearchQuery:
    project_id: str
    query_text: str = ""
    entity_types: list[str] | None = None
    binary_id: str | None = None
    tag: str | None = None
    address: str | None = None
    limit: int = 10


class SearchService:
    def __init__(self, database: Database) -> None:
        self._database = database

    def search(self, query: SearchQuery) -> list[dict[str, Any]]:
        filters: list[str] = ["sd.project_id = ?"]
        params: list[Any] = [query.project_id]

        if query.query_text:
            filters.append("sd.document_id IN (SELECT document_id FROM search_documents_fts WHERE search_documents_fts MATCH ?)")
            params.append(query.query_text)

        if query.entity_types:
            placeholders = ", ".join("?" for _ in query.entity_types)
            filters.append(f"sd.entity_type IN ({placeholders})")
            params.extend(query.entity_types)

        if query.binary_id:
            filters.append(
                """
                (
                  (sd.entity_type = 'function' AND EXISTS (
                    SELECT 1 FROM functions f
                    WHERE f.project_id = sd.project_id AND f.function_id = sd.entity_id AND f.binary_id = ?
                  ))
                  OR
                  (sd.entity_type = 'structure' AND EXISTS (
                    SELECT 1 FROM structures s
                    WHERE s.project_id = sd.project_id AND s.structure_id = sd.entity_id AND s.binary_id = ?
                  ))
                  OR sd.entity_type = 'global_hypothesis'
                )
                """
            )
            params.extend([query.binary_id, query.binary_id])

        if query.tag:
            filters.append(
                """
                EXISTS (
                  SELECT 1 FROM entity_tags et
                  WHERE et.project_id = sd.project_id
                    AND et.entity_type = sd.entity_type
                    AND et.entity_id = sd.entity_id
                    AND et.tag_name = ?
                )
                """
            )
            params.append(query.tag)

        if query.address:
            filters.append("sd.address_text LIKE ?")
            params.append(f"%{query.address}%")

        params.append(query.limit)
        sql = f"""
            SELECT sd.document_id, sd.entity_type, sd.entity_id, sd.title_text, sd.body_text, sd.tag_text, sd.address_text, sd.updated_at
            FROM search_documents sd
            WHERE {' AND '.join(filters)}
            ORDER BY sd.updated_at DESC
            LIMIT ?
        """
        return self._database.connection.execute(sql, params).fetchall()
