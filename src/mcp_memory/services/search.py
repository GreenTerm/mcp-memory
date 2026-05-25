from __future__ import annotations

from dataclasses import dataclass
import json
import re
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
    include_archived: bool = False
    limit: int = 10


class SearchService:
    def __init__(self, database: Database) -> None:
        self._database = database

    def search(self, query: SearchQuery) -> list[dict[str, Any]]:
        _validate_public_limit(query.limit)
        if query.include_archived:
            self._repair_missing_archived_documents(query.project_id)
        filters: list[str] = ["sd.project_id = ?"]
        params: list[Any] = [query.project_id]
        if not query.include_archived:
            filters.append("(r.record_id IS NULL OR r.status = 'active')")

        text_query_without_tokens = False
        non_text_filters = False
        if query.query_text:
            match_query = _fts_match_query(query.query_text)
            if match_query:
                filters.append("sd.document_id IN (SELECT document_id FROM search_documents_fts WHERE search_documents_fts MATCH ?)")
                params.append(match_query)
            else:
                text_query_without_tokens = True

        if query.entity_types:
            non_text_filters = True
            placeholders = ", ".join("?" for _ in query.entity_types)
            filters.append(f"sd.entity_type IN ({placeholders})")
            params.extend(query.entity_types)

        if query.binary_id:
            non_text_filters = True
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
            non_text_filters = True
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
            non_text_filters = True
            filters.append("sd.address_text LIKE ?")
            params.append(f"%{query.address}%")

        if text_query_without_tokens and not non_text_filters:
            return []

        params.append(query.limit)
        sql = f"""
            SELECT
              sd.document_id, sd.entity_type, sd.entity_id, sd.title_text, sd.body_text,
              sd.tag_text, sd.address_text, sd.updated_at, r.status
            FROM search_documents sd
            LEFT JOIN records r
              ON r.project_id = sd.project_id
             AND r.entity_type = sd.entity_type
             AND r.record_id = sd.entity_id
            WHERE {' AND '.join(filters)}
            ORDER BY sd.updated_at DESC
            LIMIT ?
        """
        return self._database.connection.execute(sql, params).fetchall()

    def _repair_missing_archived_documents(self, project_id: str) -> None:
        rows = self._database.connection.execute(
            """
            SELECT r.*
            FROM records r
            LEFT JOIN search_documents sd
              ON sd.project_id = r.project_id
             AND sd.entity_type = r.entity_type
             AND sd.entity_id = r.record_id
            WHERE r.project_id = ? AND r.status = 'archived' AND sd.document_id IS NULL
            ORDER BY r.updated_at DESC
            LIMIT 1000
            """,
            (project_id,),
        ).fetchall()
        for row in rows:
            record_id = str(row["record_id"])
            entity_type = str(row["entity_type"])
            document_id = f"{project_id}:{entity_type}:{record_id}"
            title = str(row["title"])
            summary = str(row["summary"])
            try:
                payload = json.loads(str(row["payload_json"]))
            except json.JSONDecodeError:
                payload = {}
            body_text = "\n".join(part for part in [title, summary, _search_text(payload)] if part)
            tag_rows = self._database.connection.execute(
                """
                SELECT tag_name
                FROM entity_tags
                WHERE project_id = ? AND entity_type = ? AND entity_id = ?
                ORDER BY tag_name
                """,
                (project_id, entity_type, record_id),
            ).fetchall()
            tag_text = " ".join(str(tag["tag_name"]) for tag in tag_rows)
            updated_at = str(row["updated_at"])
            self._database.connection.execute(
                """
                INSERT INTO search_documents (
                  document_id, project_id, entity_type, entity_id, title_text, body_text, tag_text, address_text, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, '', ?)
                """,
                (document_id, project_id, entity_type, record_id, title, body_text, tag_text, updated_at),
            )
            self._database.connection.execute(
                """
                INSERT INTO search_documents_fts(document_id, project_id, entity_type, entity_id, title_text, body_text, tag_text, address_text)
                VALUES (?, ?, ?, ?, ?, ?, ?, '')
                """,
                (document_id, project_id, entity_type, record_id, title, body_text, tag_text),
            )
        if rows:
            self._database.connection.commit()


def _fts_match_query(raw_query: str) -> str:
    tokens = re.findall(r"[\w-]+", raw_query, flags=re.UNICODE)
    return " ".join(f'"{token.replace(chr(34), chr(34) + chr(34))}"' for token in tokens)


def _search_text(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(_search_text(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(_search_text(item) for item in value)
    if value is None:
        return ""
    return str(value)


def _validate_public_limit(limit: int) -> None:
    if limit < 0 or limit > 1000:
        raise ValueError("limit must be between 0 and 1000")
