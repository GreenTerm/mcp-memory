from __future__ import annotations

import json
from html import escape
from http import HTTPStatus
from typing import Any
from urllib.parse import parse_qs

from mcp_memory.config import ProjectConfig, ProjectRegistry
from mcp_memory.protocol import ListRecordsQuery, ProjectDispatcher, SearchRecordsQuery
from mcp_memory.schema import ProjectSchema, copy_schema_payload, load_project_schema
from mcp_memory.services import GenericEvidenceService, GenericRelationService, GenericWorkflowService, Record, RecordService
from mcp_memory.storage import open_database

from .i18n import resolve_language, translate_text, with_lang
from .render import badge, empty_state, icon_span, inner_empty_state, key_value_grid, page_header, panel, property_grid, section, table
from .templates import renderer


def generic_workspace_response(project: ProjectConfig, registry: ProjectRegistry, raw_path: str, workspace_page_html) -> tuple[HTTPStatus, str] | None:
    _ = registry
    path, _, query_string = raw_path.partition("?")
    query = parse_qs(query_string)
    lang = resolve_language(query.get("lang", ["en"])[0])
    if path == "/ui/entities":
        return HTTPStatus.OK, workspace_page_html(project, "Entity Types", _render_entity_types(project, lang), raw_path, lang)
    if path == "/ui/entities/new":
        return HTTPStatus.OK, workspace_page_html(project, "New Entity Type", _render_entity_type_constructor(project, None, lang), raw_path, lang)
    if path.startswith("/ui/entities/"):
        parts = [segment for segment in path.split("/") if segment]
        if len(parts) == 4 and parts[3] == "edit":
            return HTTPStatus.OK, workspace_page_html(project, "Edit Entity Type", _render_entity_type_edit(project, parts[2], None, lang), raw_path, lang)
        if len(parts) == 4 and parts[3] == "delete":
            return HTTPStatus.OK, workspace_page_html(project, "Delete Entity Type", _render_entity_type_delete(project, parts[2], None, lang), raw_path, lang)
    if path == "/ui/records":
        return HTTPStatus.OK, workspace_page_html(project, "Records", _render_records(project, query, lang), raw_path, lang)
    if path == "/ui/search":
        return HTTPStatus.OK, workspace_page_html(project, "Search", _render_search(project, query, lang), raw_path, lang)
    if path == "/ui/graph":
        return HTTPStatus.OK, workspace_page_html(project, "Graph", _render_graph(project, query, lang), raw_path, lang)
    if path == "/ui/evidence":
        return HTTPStatus.OK, workspace_page_html(project, "Evidence", _render_evidence_page(project, query, None, lang), raw_path, lang)
    if path.startswith("/ui/records/"):
        parts = [segment for segment in path.split("/") if segment]
        if len(parts) == 4 and parts[3] == "new":
            return HTTPStatus.OK, workspace_page_html(project, "New Record", _render_record_form(project, parts[2], None, None, lang), raw_path, lang)
        if len(parts) == 5 and parts[4] == "edit":
            return _record_edit_response(project, parts[2], parts[3], raw_path, lang, workspace_page_html)
        if len(parts) == 4:
            return _record_detail_response(project, parts[2], parts[3], raw_path, lang, workspace_page_html)
    if path == "/ui/schema":
        return HTTPStatus.OK, workspace_page_html(project, "Schema Builder", _render_schema_builder(project, None, lang), raw_path, lang)
    return None


def generic_workspace_post_action(project: ProjectConfig, registry: ProjectRegistry, raw_path: str, form_data: dict[str, str]) -> dict[str, Any] | None:
    _ = registry
    path, _, query_string = raw_path.partition("?")
    query = parse_qs(query_string)
    lang = resolve_language(query.get("lang", [form_data.get("lang", "en")])[0])
    if path == "/ui/entities/new":
        return _submit_entity_type_constructor(project, form_data, lang)
    if path.startswith("/ui/entities/"):
        parts = [segment for segment in path.split("/") if segment]
        if len(parts) == 4 and parts[3] == "edit":
            return _submit_entity_type_edit(project, parts[2], form_data, lang)
        if len(parts) == 4 and parts[3] == "delete":
            return _submit_entity_type_delete(project, parts[2], lang)
    if path.startswith("/ui/records/"):
        parts = [segment for segment in path.split("/") if segment]
        if len(parts) == 4 and parts[3] == "new":
            return _submit_record_form(project, parts[2], None, form_data, lang)
        if len(parts) == 5 and parts[4] == "edit":
            return _submit_record_form(project, parts[2], parts[3], form_data, lang)
        if len(parts) == 5 and parts[4] == "archive":
            with open_database(project.database_path) as database:
                result = GenericWorkflowService(database, project).apply_or_queue(
                    "archive_record",
                    {"entity_type": parts[2], "record_id_or_slug": parts[3], "archived_by": "ui"},
                    created_by="ui",
                )
            flash = "queued" if project.write_mode == "confirm" else "archived"
            return {"location": with_lang(f"/ui/records?entity_type={parts[2]}&flash={flash}", lang)}
    if path == "/ui/evidence":
        try:
            return _submit_evidence_form(project, form_data, lang)
        except ValueError as exc:
            query = {
                "entity_type": [form_data.get("entity_type", "")],
                "record_id": [form_data.get("record_id", "")],
            }
            return {"status": HTTPStatus.BAD_REQUEST, "html": _render_evidence_page(project, query, str(exc), lang)}
    if path == "/ui/relations":
        try:
            return _submit_relation_form(project, form_data, lang)
        except ValueError as exc:
            query = {
                "focus_type": [form_data.get("from_entity_type", "")],
                "focus_id": [form_data.get("from_record_id", "")],
            }
            return {"status": HTTPStatus.BAD_REQUEST, "html": _render_graph(project, query, lang, str(exc))}
    if path == "/ui/schema":
        try:
            payload = _schema_payload_from_form(form_data)
            ProjectSchema.from_dict(payload)
            copy_schema_payload(project.schema_path, payload)
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            return {"status": HTTPStatus.BAD_REQUEST, "html": _render_schema_builder(project, str(exc), lang)}
        return {"location": with_lang("/ui/schema?flash=updated", lang)}
    if path == "/ui/schema/entity-types":
        return _submit_schema_builder_action(project, lang, lambda payload: _add_entity_type(payload, form_data))
    if path == "/ui/schema/fields":
        return _submit_schema_builder_action(project, lang, lambda payload: _add_entity_field(payload, form_data))
    if path == "/ui/schema/relations":
        return _submit_schema_builder_action(project, lang, lambda payload: _add_relation_type(payload, form_data))
    return None


def _render_entity_types(project: ProjectConfig, lang: str) -> str:
    return renderer.render(
        "generic_shell.html",
        header_html=page_header("Entity Types", "Schema-defined record types for this project."),
        body_html=_entity_types_body(project, lang),
    )


def _entity_types_body(project: ProjectConfig, lang: str) -> str:
    schema = load_project_schema(project.schema_path)
    rows = []
    for entity in schema.entity_types:
        records_href = with_lang(f"/ui/records?entity_type={entity.name}", lang)
        edit_href = with_lang(f"/ui/entities/{entity.name}/edit", lang)
        new_href = with_lang(f"/ui/records/{entity.name}/new", lang)
        delete_action = with_lang(f"/ui/entities/{entity.name}/delete", lang)
        required_html = (
            '<div class="schema-chip-row">'
            + "".join(f'<span class="schema-chip schema-chip-required">{escape(field)}</span>' for field in entity.required)
            + "</div>"
            if entity.required
            else '<span class="muted">-</span>'
        )
        actions = (
            '<div class="inline-actions">'
            f'<a class="button button-primary button-small" href="{escape(new_href, quote=True)}">New Record</a>'
            f'<a class="button button-secondary button-small" href="{escape(edit_href, quote=True)}">Edit</a>'
            f'<form method="post" action="{escape(delete_action, quote=True)}">'
            '<button class="button button-secondary button-small button-danger" type="submit">Delete</button>'
            "</form>"
            "</div>"
        )
        field_chips = "".join(
            (
                f'<span class="schema-chip{" schema-chip-required" if field.name in entity.required else ""}">'
                f"{escape(field.name)}<small>{escape(field.widget)}{_schema_field_roles(entity, field.name)}</small>"
                "</span>"
            )
            for field in entity.fields
        )
        entity_cell = (
            "<div class=\"entity-type-name-block entity-type-card\">"
            f'<h3><a href="{escape(records_href, quote=True)}">{escape(entity.label)}</a></h3>'
            f"<p>{escape(entity.description or 'No description yet.')}</p>"
            f"<code>{escape(entity.name)}</code>"
            "</div>"
        )
        fields_cell = (
            '<div class="entity-type-fields">'
            f"<span class=\"entity-type-count\">{len(entity.fields)}</span>"
            f"<div class=\"schema-chip-row\">{field_chips}</div>"
            "</div>"
        )
        required_cell = (
            '<div class="entity-type-required">'
            f"{required_html}"
            "</div>"
        )
        rows.append(
            [
                entity_cell,
                fields_cell,
                required_cell,
                f'<div class="entity-type-card-actions">{actions}</div>',
            ]
        )
    create_button = f'<div class="page-actions"><a class="button button-primary" href="{escape(with_lang("/ui/entities/new", lang), quote=True)}">New Entity Type</a></div>'
    content = (
        f'<div class="entity-type-grid">{table(["Entity", "Fields", "Required Fields", "Actions"], rows)}</div>'
        if rows
        else inner_empty_state("No entity types yet", "Create an entity type to start adding records.")
    )
    return create_button + panel("Types", content, class_name="entity-types-panel")


def _render_records(project: ProjectConfig, query: dict[str, list[str]], lang: str) -> str:
    entity_type = query.get("entity_type", [""])[0].strip() or None
    q = query.get("q", [""])[0].strip()
    with open_database(project.database_path) as database:
        dispatcher = ProjectDispatcher(database, project)
        if q:
            data = dispatcher.dispatch(SearchRecordsQuery(q=q, entity_types=[entity_type] if entity_type else None, limit=50)).data["items"]
            records = [
                {"entity_type": item["entity_type"], "record_id": item["entity_id"], "title": item["title_text"], "summary": item["body_text"][:120], "slug": ""}
                for item in data
            ]
        else:
            records = dispatcher.dispatch(ListRecordsQuery(entity_type=entity_type, limit=100)).data["items"]
    rows = []
    for record in records:
        entity = record["entity_type"] if isinstance(record, dict) else record.entity_type
        record_id = record["record_id"] if isinstance(record, dict) else record.record_id
        title = record["title"] if isinstance(record, dict) else record.title
        slug = record.get("slug", "") if isinstance(record, dict) else record.slug or ""
        summary = record["summary"] if isinstance(record, dict) else record.summary
        rows.append(
            [
                badge(entity, "accent"),
                f'<a href="{escape(with_lang(f"/ui/records/{entity}/{record_id}", lang), quote=True)}">{escape(title)}</a>',
                escape(slug),
                escape(summary),
            ]
        )
    create_link = ""
    if entity_type:
        create_link = f'<a class="button button-primary" href="{escape(with_lang(f"/ui/records/{entity_type}/new", lang), quote=True)}">New Record</a>'
    records_content = table(["Type", "Title", "Slug", "Summary"], rows) if rows else inner_empty_state("No records yet", "Create the first record for this schema.")
    content = f'<div class="section-stack">{create_link}{records_content}</div>'
    return renderer.render(
        "generic_shell.html",
        header_html=page_header("Records", "Generic schema-backed records."),
        body_html=panel("Records", content),
    )


def _render_search(project: ProjectConfig, query: dict[str, list[str]], lang: str) -> str:
    q = query.get("q", [""])[0].strip()
    entity_type = query.get("entity_type", [""])[0].strip()
    schema = load_project_schema(project.schema_path)
    results_html = empty_state("Search generic records", "Use title, summary, body text, or tags from schema-configured fields.")
    if q or entity_type:
        with open_database(project.database_path) as database:
            dispatcher = ProjectDispatcher(database, project)
            if q:
                items = dispatcher.dispatch(SearchRecordsQuery(q=q, entity_types=[entity_type] if entity_type else None, limit=50)).data["items"]
            else:
                records = dispatcher.dispatch(ListRecordsQuery(entity_type=entity_type, limit=50)).data["items"]
                items = [
                    {
                        "entity_type": record.entity_type,
                        "entity_id": record.record_id,
                        "title_text": record.title,
                        "body_text": record.summary,
                        "tag_text": " ".join(str(tag) for tag in record.payload.get("tags", []) if isinstance(record.payload.get("tags", []), list)),
                    }
                    for record in records
                ]
        if items:
            cards = "".join(_render_search_result(item, lang) for item in items)
            results_html = f"<div class=\"result-list\">{cards}</div>"
        else:
            results_html = empty_state("No matches yet", "Try a broader phrase or remove the entity type filter.")
    form = _search_form(schema, q, entity_type, lang)
    return renderer.render(
        "generic_shell.html",
        header_html=page_header("Search", "Schema-backed FTS over generic records."),
        body_html=panel("Search Workspace", form) + panel("Results", results_html),
    )


def _render_search_result(item: dict[str, Any], lang: str) -> str:
    entity_type = str(item["entity_type"])
    record_id = str(item["entity_id"])
    title = str(item.get("title_text", "")).strip() or record_id
    body = str(item.get("body_text", "")).strip()
    tags = [tag for tag in str(item.get("tag_text", "")).split() if tag][:4]
    badges = badge(entity_type, "accent") + "".join(badge(tag, "soft") for tag in tags)
    href = with_lang(f"/ui/records/{entity_type}/{record_id}", lang)
    return (
        "<article class=\"result-card\">"
        f"<div class=\"card-topline\">{badges}</div>"
        f"<h3><a href=\"{escape(href, quote=True)}\">{escape(title)}</a></h3>"
        f"<p class=\"result-subtitle\">{escape(record_id)}</p>"
        f"<p class=\"body-copy\">{escape(body[:220] or 'No summary available yet.')}</p>"
        "</article>"
    )


def _search_form(schema: ProjectSchema, q: str, entity_type: str, lang: str) -> str:
    options = _entity_options(schema, entity_type, "All entity types")
    return (
        "<form class=\"search-form\" method=\"get\" action=\"/ui/search\">"
        f"<input type=\"hidden\" name=\"lang\" value=\"{escape(lang, quote=True)}\">"
        f"<input type=\"text\" name=\"q\" value=\"{escape(q, quote=True)}\" placeholder=\"Search records\">"
        "<div class=\"search-form-grid\">"
        f"<select name=\"entity_type\">{options}</select>"
        "</div>"
        "<div class=\"search-form-actions\">"
        "<button class=\"button button-primary\" type=\"submit\">Search Workspace</button>"
        f"<a class=\"button button-secondary\" href=\"{escape(with_lang('/ui/search', lang), quote=True)}\">Reset</a>"
        "</div>"
        "</form>"
    )


def _render_graph(project: ProjectConfig, query: dict[str, list[str]], lang: str, error: str | None = None) -> str:
    focus_type = query.get("focus_type", [""])[0].strip()
    focus_id = query.get("focus_id", [""])[0].strip()
    entity_type = query.get("entity_type", [""])[0].strip()
    schema = load_project_schema(project.schema_path)
    with open_database(project.database_path) as database:
        records = RecordService(database, project).list_records(entity_type or None, limit=100)
        relations = GenericRelationService(database, project).list_relations(focus_type or None, focus_id or None)
    record_map = {(record.entity_type, record.record_id): record for record in records}
    if focus_type and focus_id:
        with open_database(project.database_path) as database:
            focus = RecordService(database, project).get_record(focus_type, focus_id, include_archived=True)
        if focus is not None:
            record_map[(focus.entity_type, focus.record_id)] = focus
    relations = [
        relation
        for relation in relations
        if (relation.from_entity_type, relation.from_record_id) in record_map and (relation.to_entity_type, relation.to_record_id) in record_map
    ][:80]
    node_keys = set(record_map)
    if relations:
        node_keys = {
            key
            for relation in relations
            for key in ((relation.from_entity_type, relation.from_record_id), (relation.to_entity_type, relation.to_record_id))
        }
    graph_html = _render_generic_graph_svg(record_map, node_keys, relations, lang) if node_keys else empty_state("No graph links yet", "Create generic relations first.")
    side_html = _render_graph_nodes(record_map, node_keys, lang)
    error_html = f'<div class="flash flash-warning">{escape(error)}</div>' if error else ""
    body = (
        error_html
        + panel("Graph Filters", _graph_filter_form(schema, focus_type, focus_id, entity_type, lang), "Focus by record id or slug.")
        + "<div class=\"detail-layout\">"
        + f"<section class=\"panel-section graph-panel\"><div class=\"section-heading\"><h2>Relation Graph</h2></div>{graph_html}</section>"
        + f"<aside class=\"detail-panel\"><h2>Graph Nodes</h2>{side_html}</aside>"
        + "</div>"
        + panel("Create Relation", _relation_form(schema, lang), "Relation types are validated against schema.json.")
    )
    return renderer.render(
        "generic_shell.html",
        header_html=page_header("Graph", "Typed relations between generic records."),
        body_html=body,
    )


def _render_generic_graph_svg(record_map: dict[tuple[str, str], Record], node_keys: set[tuple[str, str]], relations: list[Any], lang: str) -> str:
    import math

    ordered_keys = sorted(node_keys, key=lambda key: (key[0], key[1]))[:50]
    width = 860
    height = 520
    center_x = width / 2
    center_y = height / 2
    radius_x = 320
    radius_y = 170
    positions: dict[tuple[str, str], tuple[float, float]] = {}
    if len(ordered_keys) == 1:
        positions[ordered_keys[0]] = (center_x, center_y)
    else:
        for index, key in enumerate(ordered_keys):
            angle = (2 * math.pi * index) / len(ordered_keys)
            positions[key] = (center_x + math.cos(angle) * radius_x, center_y + math.sin(angle) * radius_y)
    edges = []
    for relation in relations:
        from_key = (relation.from_entity_type, relation.from_record_id)
        to_key = (relation.to_entity_type, relation.to_record_id)
        if from_key not in positions or to_key not in positions:
            continue
        x1, y1 = positions[from_key]
        x2, y2 = positions[to_key]
        edges.append(
            f"<line class=\"graph-edge\" x1=\"{x1:.1f}\" y1=\"{y1:.1f}\" x2=\"{x2:.1f}\" y2=\"{y2:.1f}\"></line>"
            f"<text class=\"graph-edge-label\" x=\"{((x1 + x2) / 2):.1f}\" y=\"{((y1 + y2) / 2):.1f}\">{escape(relation.relation_type)}</text>"
        )
    nodes = []
    for key in ordered_keys:
        record = record_map[key]
        x, y = positions[key]
        short_label = record.title[:24] + ("..." if len(record.title) > 24 else "")
        link = with_lang(f"/ui/records/{record.entity_type}/{record.record_id}", lang)
        nodes.append(
            f"<a href=\"{escape(link, quote=True)}\"><g class=\"graph-node graph-node-{escape(record.entity_type)}\">"
            f"<circle cx=\"{x:.1f}\" cy=\"{y:.1f}\" r=\"25\"></circle>"
            f"<text x=\"{x:.1f}\" y=\"{(y + 43):.1f}\">{escape(short_label)}</text>"
            "</g></a>"
        )
    return f"<div class=\"graph-canvas\"><svg viewBox=\"0 0 {width} {height}\" role=\"img\" aria-label=\"Relation graph\">{''.join(edges)}{''.join(nodes)}</svg></div>"


def _render_graph_nodes(record_map: dict[tuple[str, str], Record], node_keys: set[tuple[str, str]], lang: str) -> str:
    if not node_keys:
        return empty_state("No nodes selected", "Adjust the graph filters or create a relation.")
    rows = []
    for key in sorted(node_keys, key=lambda item: (item[0], item[1]))[:50]:
        record = record_map[key]
        rows.append(
            [
                badge(record.entity_type, "accent"),
                f'<a href="{escape(with_lang(f"/ui/records/{record.entity_type}/{record.record_id}", lang), quote=True)}">{escape(record.title)}</a>',
                escape(record.slug or record.record_id),
            ]
        )
    return table(["Type", "Title", "ID"], rows)


def _graph_filter_form(schema: ProjectSchema, focus_type: str, focus_id: str, entity_type: str, lang: str) -> str:
    return (
        "<form class=\"search-form\" method=\"get\" action=\"/ui/graph\">"
        f"<input type=\"hidden\" name=\"lang\" value=\"{escape(lang, quote=True)}\">"
        "<div class=\"search-form-grid\">"
        f"<select name=\"focus_type\">{_entity_options(schema, focus_type, 'Any focus type')}</select>"
        f"<input type=\"text\" name=\"focus_id\" value=\"{escape(focus_id, quote=True)}\" placeholder=\"focus record id or slug\">"
        f"<select name=\"entity_type\">{_entity_options(schema, entity_type, 'Any entity type')}</select>"
        "</div>"
        "<div class=\"search-form-actions\">"
        "<button class=\"button button-primary\" type=\"submit\">Apply Filters</button>"
        f"<a class=\"button button-secondary\" href=\"{escape(with_lang('/ui/graph', lang), quote=True)}\">Reset</a>"
        "</div>"
        "</form>"
    )


def _relation_form(schema: ProjectSchema, lang: str) -> str:
    relation_options = "".join(f'<option value="{escape(item.name, quote=True)}">{escape(item.label)}</option>' for item in schema.relation_types)
    entity_options = _entity_options(schema, "", "Entity type")
    return (
        f'<form class="project-form" method="post" action="{escape(with_lang("/ui/relations", lang), quote=True)}">'
        '<div class="form-grid">'
        f'<label class="form-field"><span class="field-label">From Type</span><select name="from_entity_type" required>{entity_options}</select></label>'
        '<label class="form-field"><span class="field-label">From Record</span><input name="from_record_id" required></label>'
        f'<label class="form-field"><span class="field-label">To Type</span><select name="to_entity_type" required>{entity_options}</select></label>'
        '<label class="form-field"><span class="field-label">To Record</span><input name="to_record_id" required></label>'
        f'<label class="form-field"><span class="field-label">Relation</span><select name="relation_type" required>{relation_options}</select></label>'
        '</div><div class="form-actions"><button class="button button-primary" type="submit">Create Relation</button></div></form>'
    )


def _entity_options(schema: ProjectSchema, selected: str, empty_label: str) -> str:
    options = [f'<option value=""{" selected" if not selected else ""}>{escape(empty_label)}</option>']
    for entity in schema.entity_types:
        selected_attr = " selected" if selected == entity.name else ""
        options.append(f'<option value="{escape(entity.name, quote=True)}"{selected_attr}>{escape(entity.label)}</option>')
    return "".join(options)


def _record_detail_response(project: ProjectConfig, entity_type: str, record_id: str, raw_path: str, lang: str, workspace_page_html) -> tuple[HTTPStatus, str]:
    with open_database(project.database_path) as database:
        record = RecordService(database, project).get_record(entity_type, record_id)
        if record is None:
            return HTTPStatus.NOT_FOUND, workspace_page_html(project, "Not Found", empty_state("Record not found", record_id), raw_path, lang)
        relations = GenericRelationService(database, project).list_relations(entity_type, record.record_id)
        evidence = GenericEvidenceService(database, project).list_evidence(entity_type, record.record_id)
    payload = (
        '<details class="raw-schema-panel payload-details">'
        '<summary class="button button-secondary">Show Payload JSON</summary>'
        '<pre class="shell-command"><code>{}</code></pre>'
        "</details>"
    ).format(escape(json.dumps(record.payload, ensure_ascii=False, indent=2)))
    meta = property_grid([("Type", record.entity_type), ("Record ID", record.record_id), ("Slug", record.slug or ""), ("Status", record.status)])
    actions = (
        f'<a class="button button-primary" href="{escape(with_lang(f"/ui/records/{record.entity_type}/{record.record_id}/edit", lang), quote=True)}">Edit</a>'
        f'<form method="post" action="{escape(with_lang(f"/ui/records/{record.entity_type}/{record.record_id}/archive", lang), quote=True)}"><button class="button button-secondary" type="submit">Archive</button></form>'
    )
    relation_rows = [[escape(item.relation_type), escape(item.from_record_id), escape(item.to_record_id)] for item in relations]
    evidence_rows = [[escape(item.evidence_type), escape(item.description), escape(item.created_by), escape(item.created_at)] for item in evidence]
    header_actions = f'<div class="form-actions">{actions}</div>'
    body = (
        '<main class="workspace-shell">'
        + page_header(record.title, record.summary, meta_html=badge(record.entity_type, "accent"), actions_html=header_actions)
        + panel("Record", meta, class_name="record-summary-panel")
        + panel("Relations", table(["Type", "From", "To"], relation_rows) if relation_rows else inner_empty_state("No relations yet", "Create relations through API or MCP."))
        + panel("Evidence", table(["Type", "Description", "By", "At"], evidence_rows) if evidence_rows else inner_empty_state("No evidence yet", "Attach evidence from this page or through MCP."))
        + panel("Add Evidence", _evidence_form(record, lang))
        + panel("Payload", payload, class_name="payload-panel")
        + "</main>"
    )
    return HTTPStatus.OK, workspace_page_html(project, record.title, body, raw_path, lang)


def _record_edit_response(project: ProjectConfig, entity_type: str, record_id: str, raw_path: str, lang: str, workspace_page_html) -> tuple[HTTPStatus, str]:
    with open_database(project.database_path) as database:
        record = RecordService(database, project).get_record(entity_type, record_id, include_archived=True)
    if record is None:
        return HTTPStatus.NOT_FOUND, workspace_page_html(project, "Not Found", empty_state("Record not found", record_id), raw_path, lang)
    return HTTPStatus.OK, workspace_page_html(project, "Edit Record", _render_record_form(project, entity_type, record, None, lang), raw_path, lang)


def _render_record_form(project: ProjectConfig, entity_type: str, record, error: str | None, lang: str) -> str:
    schema = load_project_schema(project.schema_path)
    entity = schema.entity(entity_type)
    payload = {} if record is None else record.payload
    action = with_lang(f"/ui/records/{entity_type}/new" if record is None else f"/ui/records/{entity_type}/{record.record_id}/edit", lang)
    fields = []
    for field in entity.fields:
        value = payload.get(field.name, "")
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False, indent=2)
        required = " required" if field.name in entity.required else ""
        wide_class = " record-form-field-wide" if field.widget in {"textarea", "json", "tags"} else ""
        bool_class = " record-form-field-bool" if field.widget == "bool" else ""
        if field.widget in {"textarea", "json", "tags"}:
            control = f'<textarea class="record-field-control" name="{escape(field.name, quote=True)}"{required}>{escape(str(value))}</textarea>'
        elif field.widget == "bool":
            checked = " checked" if value is True else ""
            control = (
                '<span class="record-toggle-control">'
                f'<input class="record-field-control" type="checkbox" name="{escape(field.name, quote=True)}" value="true"{checked}>'
                f'<span>{escape(field.label)}</span>'
                "</span>"
            )
        elif field.widget == "enum":
            options = "".join(f'<option value="{escape(option, quote=True)}"{" selected" if str(value) == option else ""}>{escape(option)}</option>' for option in field.options)
            control = f'<select class="record-field-control" name="{escape(field.name, quote=True)}"{required}>{options}</select>'
        else:
            input_type = "number" if field.widget == "number" else "text"
            control = f'<input class="record-field-control" type="{input_type}" name="{escape(field.name, quote=True)}" value="{escape(str(value), quote=True)}"{required}>'
        fields.append(
            f'<label class="form-field record-form-field{wide_class}{bool_class}">'
            f'<span class="field-label">{escape(field.label)} {_hint(_record_field_hint(entity, field, lang), lang)}</span>'
            f"{control}"
            "</label>"
        )
    error_html = f'<div class="flash flash-warning">{escape(error)}</div>' if error else ""
    return (
        '<main class="workspace-shell">'
        + page_header("Record Form", f"{entity.label} fields are generated from schema.json.")
        + panel(
            "Record Form",
            f'{error_html}<form class="project-form record-form" method="post" action="{escape(action, quote=True)}">'
            f'<div class="form-grid record-form-grid">{"".join(fields)}</div>'
            f'<div class="form-actions"><button class="button button-primary" type="submit">{escape(translate_text(lang, "Save"))}</button></div>'
            '</form>',
            class_name="record-editor-panel",
        )
        + "</main>"
    )


def _record_field_hint(entity: Any, field: Any, lang: str = "en") -> str:
    if field.description.strip():
        return field.description.strip()
    def tr(text: str) -> str:
        return translate_text(lang, text)

    parts = [
        tr("Required field.") if field.name in entity.required else tr("Optional field."),
        _widget_hint(field.widget, lang),
    ]
    roles = []
    if field.name == entity.slug_field:
        roles.append(tr("friendly unique slug for human and agent links"))
    if field.name == entity.title_field:
        roles.append(tr("main display title"))
    if field.name == entity.summary_field:
        roles.append(tr("short summary shown in lists and search results"))
    if field.name in entity.search_fields:
        roles.append(tr("included in full-text search"))
    if field.name in entity.tag_fields:
        roles.append(tr("treated as tags"))
    if roles:
        parts.append(tr("This field is used as") + " " + ", ".join(roles) + ".")
    return " ".join(parts)


def _widget_hint(widget: str, lang: str = "en") -> str:
    hints = {
        "text": "Use a short single-line value.",
        "textarea": "Use multi-line text.",
        "number": "Use a numeric value.",
        "bool": "Use a true/false checkbox.",
        "enum": "Choose one value from the schema-defined list.",
        "tags": "Use tags separated by commas or new lines.",
        "json": "Use valid JSON.",
        "datetime": "Use a date/time value.",
        "url": "Use a URL.",
        "path": "Use a local file or directory path.",
    }
    return translate_text(lang, hints.get(widget, "Use a schema-defined value."))


def _submit_record_form(project: ProjectConfig, entity_type: str, record_id: str | None, form_data: dict[str, str], lang: str) -> dict[str, Any]:
    schema = load_project_schema(project.schema_path)
    entity = schema.entity(entity_type)
    payload: dict[str, Any] = {}
    for field in entity.fields:
        raw = form_data.get(field.name, "")
        if field.widget == "bool":
            payload[field.name] = form_data.get(field.name) == "true"
        elif field.widget == "number":
            payload[field.name] = None if not raw.strip() else float(raw)
        elif field.widget == "json":
            payload[field.name] = None if not raw.strip() else json.loads(raw)
        elif field.widget == "tags":
            payload[field.name] = [line.strip() for line in raw.replace(",", "\n").splitlines() if line.strip()]
        else:
            payload[field.name] = raw.strip()
    with open_database(project.database_path) as database:
        result = GenericWorkflowService(database, project).apply_or_queue(
            "upsert_record",
            {"entity_type": entity_type, "record_id": record_id, "payload": payload, "source_origin": "ui", "created_by": "ui", "updated_by": "ui"},
            created_by="ui",
        )
    if project.write_mode == "confirm":
        return {"location": with_lang("/ui/pending?flash=queued", lang)}
    record = result.data
    return {"location": with_lang(f"/ui/records/{record.entity_type}/{record.record_id}", lang)}


def _render_schema_builder(project: ProjectConfig, error: str | None, lang: str) -> str:
    schema = load_project_schema(project.schema_path)
    payload = json.dumps(schema.to_dict(), ensure_ascii=False, indent=2)
    error_html = f'<div class="flash flash-warning">{escape(error)}</div>' if error else ""
    form = (
        f'{error_html}<form class="project-form" method="post" action="{escape(with_lang("/ui/schema", lang), quote=True)}">'
        '<label class="form-field"><span class="field-label">schema.json</span>'
        f'<textarea name="schema_json" rows="28">{escape(payload)}</textarea></label>'
        '<div class="form-actions"><button class="button button-primary" type="submit">Save Schema</button></div></form>'
    )
    return renderer.render(
        "generic_shell.html",
        header_html=page_header("Schema Builder", "Edit project schema metadata."),
        body_html=(
            panel("Schema Overview", _schema_overview(schema))
            + panel("Schema JSON", form)
        ),
    )


def _schema_payload_from_form(form_data: dict[str, str]) -> dict[str, Any]:
    return json.loads(form_data.get("schema_json", "{}"))


def _schema_overview(schema: ProjectSchema) -> str:
    entity_cards = []
    for entity in schema.entity_types:
        fields = "".join(
            (
                f'<span class="schema-chip{" schema-chip-required" if field.name in entity.required else ""}">'
                f"{escape(field.name)}<small>{escape(field.widget)}{_schema_field_roles(entity, field.name)}</small>"
                "</span>"
            )
            for field in entity.fields
        )
        meta = [
            ("System Name", entity.name),
            ("Fields", str(len(entity.fields))),
            ("Required", ", ".join(entity.required) or "-"),
            ("Title", entity.title_field or "-"),
            ("Summary", entity.summary_field or "-"),
            ("Slug", entity.slug_field or "-"),
        ]
        entity_cards.append(
            "<article class=\"schema-card\">"
            f"<div class=\"schema-card-head\"><div><h3>{escape(entity.label)}</h3><p>{escape(entity.description or entity.name)}</p></div><code>{escape(entity.name)}</code></div>"
            f"{key_value_grid(meta)}"
            f"<div class=\"schema-chip-row\">{fields}</div>"
            "</article>"
        )
    relation_cards = []
    for relation in schema.relation_types:
        relation_cards.append(
            "<article class=\"schema-card schema-relation-card\">"
            f"<div class=\"schema-card-head\"><div><h3>{escape(relation.label)}</h3><p>{escape(relation.name)}</p></div>{badge('directed' if relation.directed else 'undirected', 'neutral')}</div>"
            f"{key_value_grid([('From', ', '.join(relation.from_types)), ('To', ', '.join(relation.to_types))])}"
            "</article>"
        )
    return (
        '<div class="schema-overview-stack">'
        + section(
            "Entity Types",
            f'<div class="schema-card-grid">{"".join(entity_cards)}</div>' if entity_cards else empty_state("No entity types yet", "Use the entity type constructor to define the first record shape."),
        )
        + section(
            "Relation Types",
            f'<div class="schema-card-grid schema-relation-grid">{"".join(relation_cards)}</div>' if relation_cards else empty_state("No relation types yet", "Create relation types from the entity type constructor."),
        )
        + "</div>"
    )


def _schema_field_roles(entity: Any, field_name: str) -> str:
    roles = []
    if field_name in entity.required:
        roles.append("required")
    if field_name == entity.title_field:
        roles.append("title")
    if field_name == entity.summary_field:
        roles.append("summary")
    if field_name == entity.slug_field:
        roles.append("slug")
    if field_name in entity.search_fields:
        roles.append("search")
    if field_name in entity.tag_fields:
        roles.append("tag")
    return f" / {escape(', '.join(roles))}" if roles else ""


def _render_entity_type_edit(project: ProjectConfig, entity_name: str, error: str | None, lang: str) -> str:
    schema = load_project_schema(project.schema_path)
    try:
        entity = schema.entity(entity_name)
    except ValueError as exc:
        return empty_state("Entity type not found", str(exc))
    entity_json = json.dumps(entity.to_dict(), ensure_ascii=False, indent=2)
    error_html = f'<div class="flash flash-warning">{escape(error)}</div>' if error else ""
    widgets = ["text", "textarea", "number", "bool", "enum", "tags", "json", "datetime", "url", "path"]
    field_rows = "".join(_entity_edit_field_row(idx, entity, field, widgets, lang) for idx, field in enumerate(entity.fields))
    next_idx = len(entity.fields)
    relation_rows = "".join(_entity_edit_relation_row(idx, relation, lang) for idx, relation in enumerate(schema.relation_types))
    next_rel_idx = len(schema.relation_types)
    gui_form = (
        f'{error_html}<form class="project-form entity-editor-form" method="post" action="{escape(with_lang(f"/ui/entities/{entity.name}/edit", lang), quote=True)}">'
        '<input type="hidden" name="form_mode" value="gui">'
        + _entity_basic_block(
            '<div class="form-grid project-identity-grid">'
            + _labeled_field(
                "System Name",
                "Stable API and URL identifier. GUI editing keeps this value unchanged so existing records stay connected.",
                f'<input name="name" value="{escape(entity.name, quote=True)}" readonly>',
                lang,
            )
            + _labeled_field(
                "Label",
                "Human-readable name shown in navigation, lists, and record forms.",
                f'<input name="label" value="{escape(entity.label, quote=True)}" required>',
                lang,
            )
            + _labeled_field(
                "Description",
                "Short explanation of what this entity type stores.",
                f'<textarea name="description" rows="4" class="description-textarea">{escape(entity.description)}</textarea>',
                lang,
            )
            + "</div>",
        )
        + _constructor_section(
            "Fields",
            '<button type="button" class="button button-secondary button-small constructor-add-button" onclick="addEntityEditFieldRow()">'
            + icon_span("Add Field", "button-icon")
            + "Add Field</button>",
            '<div class="constructor-table-wrap"><table class="constructor-table entity-editor-table">'
            f'<thead><tr><th></th><th>{escape(_ui_text("Field", lang))}</th><th>{escape(_ui_text("Label", lang))}</th><th>{escape(_ui_text("Type", lang))}</th><th>{escape(_ui_text("Required", lang))}</th><th>{escape(_ui_text("Role", lang))}</th><th>{escape(_ui_text("Actions", lang))}</th></tr></thead>'
            f'<tbody class="entity-editor-fields">{field_rows}</tbody></table></div>',
        )
        + _constructor_section(
            "Relation Types (optional)",
            '<button type="button" class="button button-secondary button-small constructor-add-button" onclick="addEntityEditRelationRow()">'
            + icon_span("Add Relation Type", "button-icon")
            + "Add Relation Type</button>",
            '<div class="constructor-table-wrap"><table class="constructor-table entity-editor-table">'
            f'<thead><tr><th></th><th>{escape(_ui_text("Relation Name", lang))}</th><th>{escape(_ui_text("Relation Label", lang))}</th><th>{escape(_ui_text("From", lang))}</th><th>{escape(_ui_text("To", lang))}</th><th>{escape(_ui_text("Directed", lang))}</th><th>{escape(_ui_text("Actions", lang))}</th></tr></thead>'
            f'<tbody class="entity-editor-relations">{relation_rows}</tbody></table></div>',
        )
        + '<div class="form-actions"><button class="button button-primary" type="submit">Save Entity Type</button>'
        + f'<a class="button button-secondary" href="{escape(with_lang("/ui/entities", lang), quote=True)}">Cancel</a></div>'
        "</form>"
        "<script>"
        f"var _eefIdx={next_idx};"
        f"var _eerIdx={next_rel_idx};"
        "function addEntityEditFieldRow(){"
        'var c=document.querySelector(".entity-editor-fields");'
        "c.insertAdjacentHTML('beforeend'," + json.dumps(_entity_edit_field_row_js_template(widgets, lang)) + ".replace(/__IDX__/g,_eefIdx));"
        "_eefIdx++;"
        "}"
        "function removeEntityEditFieldRow(btn){btn.closest('.constructor-field-row').remove();}"
        "function addEntityEditRelationRow(){"
        'var c=document.querySelector(".entity-editor-relations");'
        "c.insertAdjacentHTML('beforeend'," + json.dumps(_constructor_relation_row_js_template(lang)) + ".replace(/__IDX__/g,_eerIdx));"
        "_eerIdx++;"
        "}"
        "function removeEntityEditRelationRow(btn){btn.closest('.constructor-relation-row').remove();}"
        "function removeConstructorRelationRow(btn){removeEntityEditRelationRow(btn);}"
        "function toggleEnumOptions(sel){"
        'var row=sel.closest(".constructor-field-row");'
        'var el=row.querySelector(".constructor-enum-line");'
        'var value=sel.value||"";'
        'if(el)el.style.display=value==="enum"?"":"none";'
        "}"
        + _custom_select_script()
        + "</script>"
    )
    raw_form = (
        '<details class="raw-schema-panel">'
        '<summary class="button button-secondary">Edit raw schema JSON</summary>'
        f'<form class="project-form" method="post" action="{escape(with_lang(f"/ui/entities/{entity.name}/edit", lang), quote=True)}">'
        '<input type="hidden" name="form_mode" value="raw">'
        '<label class="form-field"><span class="field-label">Entity JSON</span>'
        f'<textarea name="entity_json" rows="22">{escape(entity_json)}</textarea></label>'
        '<div class="form-actions">'
        '<button class="button button-primary" type="submit">Save Raw JSON</button>'
        '</div></form></details>'
    )
    return renderer.render(
        "generic_shell.html",
        header_html=page_header("Edit Entity Type", f"{entity.label} / {entity.name}"),
        body_html=gui_form
        + panel("Advanced", raw_form, "Use raw JSON only when the GUI form cannot express the change you need.", "advanced-panel"),
    )


def _submit_entity_type_edit(project: ProjectConfig, entity_name: str, form_data: dict[str, str], lang: str) -> dict[str, Any]:
    try:
        if form_data.get("form_mode") == "raw" or "entity_json" in form_data:
            entity_payload = json.loads(form_data.get("entity_json", "{}"))
        else:
            entity_payload = _entity_payload_from_editor_form(entity_name, form_data)
        payload = load_project_schema(project.schema_path).to_dict()
        entities = payload.get("entity_types", [])
        for idx, entity in enumerate(entities):
            if str(entity.get("name", "")) == entity_name:
                entities[idx] = entity_payload
                break
        else:
            raise ValueError(f"unknown entity type: {entity_name}")
        if form_data.get("form_mode") != "raw" and any(key.startswith("rel_name_") for key in form_data):
            payload["relation_types"] = _relation_payloads_from_editor_form(form_data)
        ProjectSchema.from_dict(payload)
        copy_schema_payload(project.schema_path, payload)
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        return {"status": HTTPStatus.BAD_REQUEST, "html": _render_entity_type_edit(project, entity_name, str(exc), lang)}
    return {"location": with_lang("/ui/entities?flash=updated", lang)}


def _submit_entity_type_delete(project: ProjectConfig, entity_name: str, lang: str) -> dict[str, Any]:
    try:
        payload = load_project_schema(project.schema_path).to_dict()
        entities = payload.get("entity_types", [])
        if len(entities) <= 1:
            raise ValueError("schema must keep at least one entity type")
        with open_database(project.database_path) as database:
            count = database.connection.execute(
                "SELECT COUNT(*) AS count FROM records WHERE project_id = ? AND entity_type = ?",
                (project.project_id, entity_name),
            ).fetchone()["count"]
        if count:
            raise ValueError("entity type has records and cannot be deleted")
        payload["entity_types"] = [entity for entity in entities if str(entity.get("name", "")) != entity_name]
        if len(payload["entity_types"]) == len(entities):
            raise ValueError(f"unknown entity type: {entity_name}")
        payload["relation_types"] = [
            relation
            for relation in payload.get("relation_types", [])
            if entity_name not in relation.get("from", []) and entity_name not in relation.get("to", [])
        ]
        ProjectSchema.from_dict(payload)
        copy_schema_payload(project.schema_path, payload)
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        return {"status": HTTPStatus.BAD_REQUEST, "html": _render_entity_type_delete(project, entity_name, str(exc), lang)}
    return {"location": with_lang("/ui/entities?flash=deleted", lang)}


def _render_entity_type_delete(project: ProjectConfig, entity_name: str, error: str | None, lang: str) -> str:
    schema = load_project_schema(project.schema_path)
    try:
        entity = schema.entity(entity_name)
    except ValueError as exc:
        return empty_state("Entity type not found", str(exc))
    error_html = f'<div class="flash flash-warning">{escape(error)}</div>' if error else ""
    return renderer.render(
        "generic_shell.html",
        header_html=page_header("Delete Entity Type", f"{entity.label} / {entity.name}"),
        body_html=panel(
            "Confirm Delete",
            error_html
            + '<div class="danger-zone">'
            f'<p class="body-copy">Delete the <strong>{escape(entity.label)}</strong> entity type from schema.json. Existing records must be removed or archived first.</p>'
            f'<form method="post" action="{escape(with_lang(f"/ui/entities/{entity.name}/delete", lang), quote=True)}">'
            '<div class="form-actions">'
            '<button class="button button-secondary button-danger" type="submit">Delete Entity Type</button>'
            f'<a class="button button-secondary" href="{escape(with_lang("/ui/entities", lang), quote=True)}">Cancel</a>'
            "</div></form></div>",
        ),
    )


def _entity_edit_field_row(idx: int, entity: Any, field: Any, widgets: list[str], lang: str) -> str:
    options_value = ", ".join(field.options)
    enum_style = "" if field.widget == "enum" else "display:none"
    return (
        '<tr class="constructor-field-row entity-editor-field-row">'
        '<td class="constructor-drag-cell"><span class="drag-handle" aria-hidden="true"></span></td>'
        f'<td><input name="field_name_{idx}" required pattern="[a-z][a-z0-9_]*" value="{escape(field.name, quote=True)}"></td>'
        f'<td><div class="entity-editor-label-stack"><input name="field_label_{idx}" required value="{escape(field.label, quote=True)}">'
        f'<input name="field_description_{idx}" value="{escape(field.description, quote=True)}" placeholder="{escape(_ui_text("Description", lang), quote=True)}"></div></td>'
        f'<td>{_constructor_widget_select(f"field_widget_{idx}", widgets, field.widget, lang)}'
        f'<input class="constructor-enum-line" name="field_options_{idx}" value="{escape(options_value, quote=True)}" placeholder="one, two, three" style="{enum_style}"></td>'
        f'<td class="constructor-center"><input class="constructor-checkbox" type="checkbox" name="field_required_{idx}" value="true"{" checked" if field.name in entity.required else ""}></td>'
        "<td>"
        + _constructor_role_menu(
            _constructor_role_chip_checked("Title", "Use this field as the record title.", f"field_title_{idx}", field.name == entity.title_field, lang)
            + _constructor_role_chip_checked("Summary", "Use this field as the record summary.", f"field_summary_{idx}", field.name == entity.summary_field, lang)
            + _constructor_role_chip_checked("Slug", "Use this field as the human-friendly URL identifier.", f"field_slug_{idx}", field.name == entity.slug_field, lang)
            + _constructor_role_chip_checked("Search", "Include this field in full-text search.", f"field_search_{idx}", field.name in entity.search_fields, lang)
            + _constructor_role_chip_checked("Tag", "Use this field as tags.", f"field_tag_{idx}", field.name in entity.tag_fields, lang),
            [
                label
                for label, selected in (
                    ("Title", field.name == entity.title_field),
                    ("Summary", field.name == entity.summary_field),
                    ("Slug", field.name == entity.slug_field),
                    ("Search", field.name in entity.search_fields),
                    ("Tag", field.name in entity.tag_fields),
                )
                if selected
            ],
            lang,
        )
        + "</td>"
        f'<td><div class="constructor-row-actions">{_constructor_icon_button("Delete", "removeEntityEditFieldRow(this)", "danger")}</div></td>'
        "</tr>"
    )


def _entity_edit_field_row_js_template(widgets: list[str], lang: str) -> str:
    return (
        '<tr class="constructor-field-row entity-editor-field-row">'
        '<td class="constructor-drag-cell"><span class="drag-handle" aria-hidden="true"></span></td>'
        '<td><input name="field_name___IDX__" required pattern="[a-z][a-z0-9_]*" placeholder="title"></td>'
        '<td><div class="entity-editor-label-stack"><input name="field_label___IDX__" required placeholder="Title">'
        f'<input name="field_description___IDX__" placeholder="{escape(_ui_text("Description", lang), quote=True)}"></div></td>'
        f'<td>{_constructor_widget_select("field_widget___IDX__", widgets, "text", lang)}'
        '<input class="constructor-enum-line" name="field_options___IDX__" placeholder="one, two, three" style="display:none"></td>'
        '<td class="constructor-center"><input class="constructor-checkbox" type="checkbox" name="field_required___IDX__" value="true"></td>'
        "<td>"
        + _constructor_role_menu(
            _constructor_role_chip("Title", "Use this field as the record title.", "field_title_", "__IDX__", lang)
            + _constructor_role_chip("Summary", "Use this field as the record summary.", "field_summary_", "__IDX__", lang)
            + _constructor_role_chip("Slug", "Use this field as the human-friendly URL identifier.", "field_slug_", "__IDX__", lang)
            + _constructor_role_chip("Search", "Include this field in full-text search.", "field_search_", "__IDX__", lang)
            + _constructor_role_chip("Tag", "Use this field as tags.", "field_tag_", "__IDX__", lang),
            [],
            lang,
        )
        + "</td>"
        + f'<td><div class="constructor-row-actions">{_constructor_icon_button("Delete", "removeEntityEditFieldRow(this)", "danger")}</div></td>'
        + "</tr>"
    )


def _entity_edit_relation_row(idx: int, relation: Any, lang: str) -> str:
    directed_attr = " checked" if relation.directed else ""
    return (
        '<tr class="constructor-relation-row entity-editor-relation-row">'
        '<td class="constructor-drag-cell"><span class="drag-handle" aria-hidden="true"></span></td>'
        f'<td><input name="rel_name_{idx}" required pattern="[a-z][a-z0-9_]*" value="{escape(relation.name, quote=True)}"></td>'
        f'<td><input name="rel_label_{idx}" required value="{escape(relation.label, quote=True)}"></td>'
        f'<td><input name="rel_from_{idx}" required value="{escape(", ".join(relation.from_types), quote=True)}"></td>'
        f'<td><input name="rel_to_{idx}" required value="{escape(", ".join(relation.to_types), quote=True)}"></td>'
        f'<td class="constructor-center"><input class="constructor-checkbox" type="checkbox" name="rel_directed_{idx}" value="true"{directed_attr}></td>'
        f'<td><div class="constructor-row-actions">{_constructor_icon_button("Delete", "removeEntityEditRelationRow(this)", "danger")}</div></td>'
        "</tr>"
    )


def _entity_payload_from_editor_form(entity_name: str, form_data: dict[str, str]) -> dict[str, Any]:
    fields = []
    required = []
    title_field = ""
    summary_field = ""
    slug_field = ""
    search_fields = []
    tag_fields = []
    for idx in _indexed_form_suffixes(form_data, "field_name_"):
        field_name = form_data.get(f"field_name_{idx}", "").strip()
        if not field_name:
            continue
        widget = form_data.get(f"field_widget_{idx}", "text").strip() or "text"
        field_payload: dict[str, Any] = {
            "name": field_name,
            "label": form_data.get(f"field_label_{idx}", "").strip() or field_name,
            "widget": widget,
        }
        description = form_data.get(f"field_description_{idx}", "").strip()
        if description:
            field_payload["description"] = description
        options = _split_csv(form_data.get(f"field_options_{idx}", ""))
        if options:
            field_payload["options"] = options
        fields.append(field_payload)
        if form_data.get(f"field_required_{idx}") == "true":
            required.append(field_name)
        if form_data.get(f"field_title_{idx}") == "true":
            title_field = field_name
        if form_data.get(f"field_summary_{idx}") == "true":
            summary_field = field_name
        if form_data.get(f"field_slug_{idx}") == "true":
            slug_field = field_name
        if form_data.get(f"field_search_{idx}") == "true":
            search_fields.append(field_name)
        if form_data.get(f"field_tag_{idx}") == "true":
            tag_fields.append(field_name)
    if not fields:
        raise ValueError("at least one field is required")
    return {
        "name": entity_name,
        "label": form_data.get("label", "").strip() or entity_name,
        "description": form_data.get("description", "").strip(),
        "fields": fields,
        "required": required,
        "title_field": title_field,
        "summary_field": summary_field,
        "slug_field": slug_field,
        "search_fields": search_fields,
        "tag_fields": tag_fields,
    }


def _relation_payloads_from_editor_form(form_data: dict[str, str]) -> list[dict[str, Any]]:
    relation_types = []
    for idx in _indexed_form_suffixes(form_data, "rel_name_"):
        relation_name = form_data.get(f"rel_name_{idx}", "").strip()
        if not relation_name:
            continue
        relation_types.append(
            {
                "name": relation_name,
                "label": form_data.get(f"rel_label_{idx}", "").strip() or relation_name,
                "from": _split_csv(form_data.get(f"rel_from_{idx}", "")),
                "to": _split_csv(form_data.get(f"rel_to_{idx}", "")),
                "directed": form_data.get(f"rel_directed_{idx}") == "true",
            }
        )
    return relation_types


def _render_entity_types_with_error(project: ProjectConfig, error: str, lang: str) -> str:
    return renderer.render(
        "generic_shell.html",
        header_html=page_header("Entity Types", "Schema-defined record types for this project."),
        body_html=f'<div class="flash flash-warning">{escape(error)}</div>' + _entity_types_body(project, lang),
    )


def _entity_type_builder_form(lang: str) -> str:
    return (
        f'<form class="project-form" method="post" action="{escape(with_lang("/ui/schema/entity-types", lang), quote=True)}">'
        '<div class="form-grid">'
        '<label class="form-field"><span class="field-label">Name</span><input name="name" required></label>'
        '<label class="form-field"><span class="field-label">Label</span><input name="label" required></label>'
        '<label class="form-field"><span class="field-label">Description</span><textarea name="description"></textarea></label>'
        '</div><div class="form-actions"><button class="button button-primary" type="submit">Add Entity Type</button></div></form>'
    )


def _field_builder_form(schema: ProjectSchema, lang: str) -> str:
    return (
        f'<form class="project-form" method="post" action="{escape(with_lang("/ui/schema/fields", lang), quote=True)}">'
        '<div class="form-grid">'
        f'<label class="form-field"><span class="field-label">Entity Type</span><select name="entity_type" required>{_entity_options(schema, "", "Entity type")}</select></label>'
        '<label class="form-field"><span class="field-label">Name</span><input name="name" required></label>'
        '<label class="form-field"><span class="field-label">Label</span><input name="label" required></label>'
        f'<label class="form-field"><span class="field-label">Widget</span><select name="widget">{_widget_options("text")}</select></label>'
        '<label class="form-field"><span class="field-label">Enum Options</span><input name="options" placeholder="one, two, three"></label>'
        '<label class="form-field"><span class="field-label">Required</span><input type="checkbox" name="required" value="true"></label>'
        '<label class="form-field"><span class="field-label">Title Field</span><input type="checkbox" name="title_field" value="true"></label>'
        '<label class="form-field"><span class="field-label">Summary Field</span><input type="checkbox" name="summary_field" value="true"></label>'
        '<label class="form-field"><span class="field-label">Slug Field</span><input type="checkbox" name="slug_field" value="true"></label>'
        '<label class="form-field"><span class="field-label">Search Field</span><input type="checkbox" name="search_field" value="true"></label>'
        '<label class="form-field"><span class="field-label">Tag Field</span><input type="checkbox" name="tag_field" value="true"></label>'
        '</div><div class="form-actions"><button class="button button-primary" type="submit">Add Field</button></div></form>'
    )


def _relation_type_builder_form(schema: ProjectSchema, lang: str) -> str:
    return (
        f'<form class="project-form" method="post" action="{escape(with_lang("/ui/schema/relations", lang), quote=True)}">'
        '<div class="form-grid">'
        '<label class="form-field"><span class="field-label">Name</span><input name="name" required></label>'
        '<label class="form-field"><span class="field-label">Label</span><input name="label" required></label>'
        '<label class="form-field"><span class="field-label">From</span><input name="from" placeholder="note, source or *" required></label>'
        '<label class="form-field"><span class="field-label">To</span><input name="to" placeholder="note, source or *" required></label>'
        '<label class="form-field"><span class="field-label">Directed</span><input type="checkbox" name="directed" value="true" checked></label>'
        '</div><div class="form-actions"><button class="button button-primary" type="submit">Add Relation Type</button></div></form>'
    )


def _widget_options(selected: str) -> str:
    widgets = ["text", "textarea", "number", "bool", "enum", "tags", "json", "datetime", "url", "path"]
    return "".join(f'<option value="{widget}"{" selected" if selected == widget else ""}>{widget}</option>' for widget in widgets)


def _submit_schema_builder_action(project: ProjectConfig, lang: str, mutate) -> dict[str, Any]:
    try:
        payload = load_project_schema(project.schema_path).to_dict()
        mutate(payload)
        ProjectSchema.from_dict(payload)
        copy_schema_payload(project.schema_path, payload)
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        return {"status": HTTPStatus.BAD_REQUEST, "html": _render_schema_builder(project, str(exc), lang)}
    return {"location": with_lang("/ui/schema?flash=updated", lang)}


def _add_entity_type(payload: dict[str, Any], form_data: dict[str, str]) -> None:
    name = form_data.get("name", "").strip()
    label = form_data.get("label", "").strip() or name
    if not name:
        raise ValueError("entity type name is required")
    payload.setdefault("entity_types", []).append(
        {
            "name": name,
            "label": label,
            "description": form_data.get("description", "").strip(),
            "fields": [{"name": "title", "label": "Title", "widget": "text"}],
            "required": ["title"],
            "title_field": "title",
            "summary_field": "",
            "slug_field": "",
            "search_fields": ["title"],
            "tag_fields": [],
        }
    )


def _add_entity_field(payload: dict[str, Any], form_data: dict[str, str]) -> None:
    entity_name = form_data.get("entity_type", "").strip()
    field_name = form_data.get("name", "").strip()
    if not entity_name or not field_name:
        raise ValueError("entity type and field name are required")
    entity = _schema_entity_payload(payload, entity_name)
    field_payload: dict[str, Any] = {
        "name": field_name,
        "label": form_data.get("label", "").strip() or field_name,
        "widget": form_data.get("widget", "text").strip() or "text",
    }
    options = _split_csv(form_data.get("options", ""))
    if options:
        field_payload["options"] = options
    entity.setdefault("fields", []).append(field_payload)
    if form_data.get("required") == "true":
        entity.setdefault("required", []).append(field_name)
    for form_key, schema_key in (("title_field", "title_field"), ("summary_field", "summary_field"), ("slug_field", "slug_field")):
        if form_data.get(form_key) == "true":
            entity[schema_key] = field_name
    if form_data.get("search_field") == "true":
        entity.setdefault("search_fields", []).append(field_name)
    if form_data.get("tag_field") == "true":
        entity.setdefault("tag_fields", []).append(field_name)


def _add_relation_type(payload: dict[str, Any], form_data: dict[str, str]) -> None:
    name = form_data.get("name", "").strip()
    if not name:
        raise ValueError("relation type name is required")
    payload.setdefault("relation_types", []).append(
        {
            "name": name,
            "label": form_data.get("label", "").strip() or name,
            "from": _split_csv(form_data.get("from", "")),
            "to": _split_csv(form_data.get("to", "")),
            "directed": form_data.get("directed") == "true",
        }
    )


def _schema_entity_payload(payload: dict[str, Any], entity_name: str) -> dict[str, Any]:
    for entity in payload.get("entity_types", []):
        if str(entity.get("name", "")) == entity_name:
            return entity
    raise ValueError(f"unknown entity type: {entity_name}")


def _split_csv(raw: str) -> list[str]:
    return [item.strip() for item in raw.replace("\n", ",").split(",") if item.strip()]


def _indexed_form_suffixes(form_data: dict[str, str], prefix: str) -> list[int]:
    suffixes = []
    for key in form_data:
        if not key.startswith(prefix):
            continue
        suffix = key[len(prefix) :]
        if suffix.isdigit():
            suffixes.append(int(suffix))
    return sorted(set(suffixes))


def _render_entity_type_constructor(project: ProjectConfig, error: str | None, lang: str) -> str:
    error_html = f'<div class="flash flash-warning">{escape(error)}</div>' if error else ""
    widgets = ["text", "textarea", "number", "bool", "enum", "tags", "json", "datetime", "url", "path"]
    widget_options_html = "".join(f'<option value="{w}">{w}</option>' for w in widgets)
    body = (
        error_html
        + '<form class="project-form entity-constructor-form" method="post" action="' + escape(with_lang("/ui/entities/new", lang), quote=True) + '">'
        + _entity_basic_block(
            '<div class="form-grid project-identity-grid">'
            + _labeled_field(
                "Name",
                "Unique identifier for API and URLs. Lowercase letters, digits, underscores. Example: function, structure, note",
                '<input name="name" required pattern="[a-z][a-z0-9_]*" placeholder="my_entity">',
                lang,
            )
            + _labeled_field(
                "Label",
                "Human-readable name shown in the UI. Example: Function, Structure, Note",
                '<input name="label" required placeholder="My Entity">',
                lang,
            )
            + _labeled_field(
                "Description",
                "Short explanation of what this entity type represents.",
                '<textarea name="description" rows="3" class="description-textarea"></textarea>',
                lang,
            )
            + "</div>",
        )
        + _constructor_section(
            "Fields",
            '<button type="button" class="button button-secondary button-small constructor-add-button" onclick="addConstructorFieldRow()">'
            + icon_span("Add Field", "button-icon")
            + "Add Field</button>",
            '<div class="constructor-table-wrap"><table class="constructor-table">'
            f'<thead><tr><th></th><th>{escape(_ui_text("Field", lang))}</th><th>{escape(_ui_text("Label", lang))}</th><th>{escape(_ui_text("Type", lang))}</th><th>{escape(_ui_text("Required", lang))}</th><th>{escape(_ui_text("Role", lang))}</th><th>{escape(_ui_text("Actions", lang))}</th></tr></thead>'
            '<tbody id="constructor-fields">'
            + _constructor_field_row(0, widget_options_html, is_first=True, lang=lang)
            + "</tbody></table></div>",
        )
        + _constructor_section(
            "Relation Types (optional)",
            '<button type="button" class="button button-secondary button-small constructor-add-button" onclick="addConstructorRelationRow()">'
            + icon_span("Add Relation Type", "button-icon")
            + "Add Relation Type</button>",
            '<div class="constructor-table-wrap"><table class="constructor-table constructor-relation-table">'
            f'<thead><tr><th></th><th>{escape(_ui_text("Relation Name", lang))}</th><th>{escape(_ui_text("Relation Label", lang))}</th><th>{escape(_ui_text("From", lang))}</th><th>{escape(_ui_text("To", lang))}</th><th>{escape(_ui_text("Directed", lang))}</th><th>{escape(_ui_text("Actions", lang))}</th></tr></thead>'
            '<tbody id="constructor-relations"></tbody></table></div>',
        )
        + '<div class="form-actions"><button class="button button-primary" type="submit">Create Entity Type</button></div></form>'
        + "<script>"
        "var _cfIdx=1;var _crIdx=0;"
        "function addConstructorFieldRow(){"
        'var c=document.getElementById("constructor-fields");'
        "c.insertAdjacentHTML('beforeend'," + json.dumps(_constructor_field_row_js_template(lang)) + ".replace(/__IDX__/g,_cfIdx));"
        "_cfIdx++;"
        "}"
        "function removeConstructorFieldRow(btn){"
        'btn.closest(".constructor-field-row").remove();'
        "}"
        "function addConstructorRelationRow(){"
        'var c=document.getElementById("constructor-relations");'
        "c.insertAdjacentHTML('beforeend'," + json.dumps(_constructor_relation_row_js_template(lang)) + ".replace(/__IDX__/g,_crIdx));"
        "_crIdx++;"
        "}"
        "function removeConstructorRelationRow(btn){"
        'btn.closest(".constructor-relation-row").remove();'
        "}"
        "function toggleEnumOptions(sel){"
        'var row=sel.closest(".constructor-field-row");'
        'var el=row.querySelector(".constructor-enum-line");'
        'var value=sel.value||"";'
        'if(el)el.style.display=value==="enum"?"":"none";'
        "}"
        + _custom_select_script()
        + "</script>"
    )
    return renderer.render(
        "generic_shell.html",
        header_html=page_header("New Entity Type", "Create a new entity type for this project."),
        body_html=body,
    )


def _hint(text: str, lang: str = "en") -> str:
    translated = escape(translate_text(lang, text), quote=True)
    svg = '<svg class="hint-icon-svg" viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="8" cy="8" r="7"/><line x1="8" y1="7.5" x2="8" y2="11.5"/><circle cx="8" cy="5" r="0.5" fill="currentColor" stroke="none"/></svg>'
    return f'<span class="hint-wrap" aria-label="{translated}">{svg}<span class="hint-tooltip">{translated}</span></span>'


def _ui_text(text: str, lang: str = "en") -> str:
    if lang == "ru":
        fallback = {
            "Description": "Описание",
            "Field": "Поле",
            "Role": "Роль",
            "Relation Name": "Имя связи",
            "Relation Label": "Метка связи",
            "From": "От",
            "To": "К",
            "Text": "Текст",
            "Multiline Text": "Многострочный текст",
            "Number": "Число",
            "Boolean": "Флаг",
            "Enum": "Список",
            "Tags": "Теги",
            "Date and Time": "Дата и время",
            "Path": "Путь",
        }
        if text in fallback:
            return fallback[text]
    return translate_text(lang, text)


def _constructor_section(title: str, action_html: str, content: str) -> str:
    return (
        '<section class="ui-panel panel-section constructor-panel">'
        '<div class="section-heading constructor-section-heading">'
        f"<h2>{escape(title)}</h2>"
        f"{action_html}"
        "</div>"
        f"{content}"
        "</section>"
    )


def _entity_basic_block(content: str) -> str:
    return f'<section class="entity-basic-block">{content}</section>'


def _widget_label(widget: str, lang: str) -> str:
    labels = {
        "text": "Text",
        "textarea": "Multiline Text",
        "number": "Number",
        "bool": "Boolean",
        "enum": "Enum",
        "tags": "Tags",
        "json": "JSON",
        "datetime": "Date and Time",
        "url": "URL",
        "path": "Path",
    }
    return _ui_text(labels.get(widget, widget), lang)


def _constructor_widget_select(name: str, widgets: list[str], selected: str, lang: str) -> str:
    selected = selected if selected in widgets else "text"
    selected_label = escape(_widget_label(selected, lang))
    option_buttons = "".join(
        '<button type="button" class="custom-select-option'
        + (" is-selected" if widget == selected else "")
        + f'" data-value="{escape(widget, quote=True)}" onclick="chooseCustomSelectOption(this)">'
        + f'<span class="custom-select-option-mark" aria-hidden="true"></span><span>{escape(_widget_label(widget, lang))}</span>'
        + "</button>"
        for widget in widgets
    )
    return (
        '<div class="custom-select" data-custom-select>'
        f'<input type="hidden" name="{escape(name, quote=True)}" value="{escape(selected, quote=True)}" data-widget-value>'
        '<button type="button" class="custom-select-button" aria-haspopup="listbox" aria-expanded="false" onclick="toggleCustomSelect(this)">'
        f'<span class="custom-select-label">{selected_label}</span><span class="custom-select-chevron" aria-hidden="true"></span>'
        "</button>"
        f'<div class="custom-select-menu" role="listbox">{option_buttons}</div>'
        "</div>"
    )


def _custom_select_script() -> str:
    return (
        "function closeCustomSelects(except){document.querySelectorAll('.custom-select.is-open').forEach(function(el){"
        "if(el!==except){el.classList.remove('is-open');var b=el.querySelector('.custom-select-button');if(b)b.setAttribute('aria-expanded','false');}});}"
        "function toggleCustomSelect(btn){var root=btn.closest('.custom-select');var open=root.classList.contains('is-open');"
        "closeCustomSelects(root);root.classList.toggle('is-open',!open);btn.setAttribute('aria-expanded',String(!open));}"
        "function chooseCustomSelectOption(btn){var root=btn.closest('.custom-select');var value=btn.getAttribute('data-value')||'text';"
        "var input=root.querySelector('[data-widget-value]');var label=root.querySelector('.custom-select-label');"
        "input.value=value;label.textContent=btn.textContent.trim();root.querySelectorAll('.custom-select-option').forEach(function(option){option.classList.toggle('is-selected',option===btn);});"
        "root.classList.remove('is-open');root.querySelector('.custom-select-button').setAttribute('aria-expanded','false');toggleEnumOptions(input);}"
        "document.addEventListener('click',function(event){if(!event.target.closest('.custom-select'))closeCustomSelects(null);});"
        "document.addEventListener('change',function(event){var input=event.target.closest('.constructor-role-chip input');"
        "if(input){var details=input.closest('.constructor-role-menu');if(details){window.setTimeout(function(){details.open=false;},80);}}});"
        "document.addEventListener('keydown',function(event){if(event.key==='Escape'){closeCustomSelects(null);document.querySelectorAll('.constructor-role-menu[open]').forEach(function(el){el.open=false;});}});"
    )


def _labeled_field(label: str, hint: str, control_html: str, lang: str = "en") -> str:
    return f'<label class="form-field"><span class="field-label">{escape(_ui_text(label, lang))} {_hint(hint, lang)}</span>{control_html}</label>'


def _labeled_checkbox(label: str, hint: str, name: str, value: str, checked: bool = False, lang: str = "en") -> str:
    checked_attr = " checked" if checked else ""
    return f'<label class="form-field checkbox-field"><span class="field-label">{escape(_ui_text(label, lang))} {_hint(hint, lang)}</span><input type="checkbox" name="{escape(name, quote=True)}" value="{escape(value, quote=True)}"{checked_attr}></label>'


def _constructor_role_area(content_html: str, title: str = "Roles") -> str:
    return (
        '<div class="constructor-role-area">'
        f'<div class="field-label">{escape(title)}</div>'
        f'<div class="constructor-flag-grid">{content_html}</div>'
        "</div>"
    )


def _constructor_field_role_controls(idx: str, lang: str = "en") -> str:
    return (
        _labeled_checkbox("Required", "This field must be filled when creating a record.", f"field_required_{idx}", "true", lang=lang)
        + _labeled_checkbox("Title", "Value of this field is used as the record title in lists and search results. Only one field can be the title.", f"field_title_{idx}", "true", lang=lang)
        + _labeled_checkbox("Summary", "Value of this field is used as a short description in lists. Only one field can be the summary.", f"field_summary_{idx}", "true", lang=lang)
        + _labeled_checkbox("Slug", "Value of this field is used as a human-friendly URL identifier. Must be unique. Only one field can be the slug.", f"field_slug_{idx}", "true", lang=lang)
        + _labeled_checkbox("Search", "Value of this field is included in full-text search indexing.", f"field_search_{idx}", "true", lang=lang)
        + _labeled_checkbox("Tag", "Value of this field is indexed as tags for tag-based filtering.", f"field_tag_{idx}", "true", lang=lang)
    )


def _constructor_role_chip(label: str, hint: str, name: str, idx: str, lang: str = "en") -> str:
    translated_label = escape(translate_text(lang, label))
    translated_hint = escape(translate_text(lang, hint), quote=True)
    return (
        '<label class="constructor-role-chip" title="'
        + translated_hint
        + '">'
        f'<input type="checkbox" name="{escape(name + idx, quote=True)}" value="true">'
        f"<span>{translated_label}</span>"
        "</label>"
    )


def _constructor_role_chip_checked(label: str, hint: str, name: str, checked: bool, lang: str = "en") -> str:
    translated_label = escape(translate_text(lang, label))
    translated_hint = escape(translate_text(lang, hint), quote=True)
    checked_attr = " checked" if checked else ""
    return (
        '<label class="constructor-role-chip" title="'
        + translated_hint
        + '">'
        f'<input type="checkbox" name="{escape(name, quote=True)}" value="true"{checked_attr}>'
        f"<span>{translated_label}</span>"
        "</label>"
    )


def _constructor_role_summary(labels: list[str], lang: str) -> str:
    if not labels:
        return '<span class="constructor-role-empty">—</span>'
    return "".join(
        f'<span class="constructor-role-badge constructor-role-badge-{escape(label.lower(), quote=True)}">{escape(translate_text(lang, label))}</span>'
        for label in labels
    )


def _constructor_role_menu(controls_html: str, selected_labels: list[str], lang: str) -> str:
    return (
        '<details class="constructor-role-menu">'
        f'<summary>{_constructor_role_summary(selected_labels, lang)}</summary>'
        f'<div class="constructor-role-menu-popover"><div class="constructor-role-pills">{controls_html}</div></div>'
        "</details>"
    )


def _constructor_icon_button(label: str, onclick: str, tone: str = "secondary") -> str:
    icon = {
        "Edit": '<path d="M4 20h4l10-10-4-4L4 16v4z"/><path d="M13 7l4 4"/>',
        "Delete": '<path d="M5 7h14"/><path d="M10 11v6M14 11v6"/><path d="M8 7l1-3h6l1 3"/><path d="M7 7l1 13h8l1-13"/>',
    }.get(label, '<path d="M12 5v14M5 12h14"/>')
    return (
        f'<button type="button" class="icon-button icon-button-{escape(tone)}" onclick="{escape(onclick, quote=True)}" '
        f'title="{escape(label, quote=True)}" aria-label="{escape(label, quote=True)}">'
        '<svg viewBox="0 0 24 24" focusable="false">'
        f"{icon}"
        "</svg>"
        "</button>"
    )


def _constructor_field_row(idx: int, widget_options_html: str, is_first: bool = False, lang: str = "en") -> str:
    remove_btn = "" if is_first else _constructor_icon_button("Delete", "removeConstructorFieldRow(this)", "danger")
    required_attr = " checked" if is_first else ""
    name_value = ' value="title"' if is_first else ""
    label_value = ' value="Title"' if is_first else ""
    widgets = ["text", "textarea", "number", "bool", "enum", "tags", "json", "datetime", "url", "path"]
    return (
        '<tr class="constructor-field-row">'
        '<td class="constructor-drag-cell"><span class="drag-handle" aria-hidden="true"></span></td>'
        f'<td><input name="field_name_{idx}" required pattern="[a-z][a-z0-9_]*" placeholder="title"{name_value}></td>'
        f'<td><input name="field_label_{idx}" required placeholder="Title"{label_value}></td>'
        f'<td>{_constructor_widget_select(f"field_widget_{idx}", widgets, "text", lang)}'
        f'<input class="constructor-enum-line" name="field_options_{idx}" placeholder="one, two, three" style="display:none"></td>'
        f'<td class="constructor-center"><input class="constructor-checkbox" type="checkbox" name="field_required_{idx}" value="true"{required_attr}></td>'
        "<td>"
        + _constructor_role_menu(
            _constructor_role_chip_checked("Title", "Use this field as the record title.", f"field_title_{idx}", is_first, lang)
            + _constructor_role_chip_checked("Summary", "Use this field as the record summary.", f"field_summary_{idx}", False, lang)
            + _constructor_role_chip_checked("Slug", "Use this field as the human-friendly URL identifier.", f"field_slug_{idx}", False, lang)
            + _constructor_role_chip_checked("Search", "Include this field in full-text search.", f"field_search_{idx}", False, lang)
            + _constructor_role_chip_checked("Tag", "Use this field as tags.", f"field_tag_{idx}", False, lang),
            ["Title"] if is_first else [],
            lang,
        )
        + "</td>"
        f'<td><div class="constructor-row-actions">{remove_btn}</div></td>'
        "</tr>"
    )


def _constructor_field_row_js_template(lang: str = "en") -> str:
    widgets = ["text", "textarea", "number", "bool", "enum", "tags", "json", "datetime", "url", "path"]
    return (
        '<tr class="constructor-field-row">'
        '<td class="constructor-drag-cell"><span class="drag-handle" aria-hidden="true"></span></td>'
        '<td><input name="field_name___IDX__" required pattern="[a-z][a-z0-9_]*" placeholder="title"></td>'
        '<td><input name="field_label___IDX__" required placeholder="Title"></td>'
        f'<td>{_constructor_widget_select("field_widget___IDX__", widgets, "text", lang)}'
        '<input class="constructor-enum-line" name="field_options___IDX__" placeholder="one, two, three" style="display:none"></td>'
        '<td class="constructor-center"><input class="constructor-checkbox" type="checkbox" name="field_required___IDX__" value="true"></td>'
        "<td>"
        + _constructor_role_menu(
            _constructor_role_chip("Title", "Use this field as the record title.", "field_title_", "__IDX__", lang)
            + _constructor_role_chip("Summary", "Use this field as the record summary.", "field_summary_", "__IDX__", lang)
            + _constructor_role_chip("Slug", "Use this field as the human-friendly URL identifier.", "field_slug_", "__IDX__", lang)
            + _constructor_role_chip("Search", "Include this field in full-text search.", "field_search_", "__IDX__", lang)
            + _constructor_role_chip("Tag", "Use this field as tags.", "field_tag_", "__IDX__", lang),
            [],
            lang,
        )
        + "</td>"
        + f'<td><div class="constructor-row-actions">{_constructor_icon_button("Delete", "removeConstructorFieldRow(this)", "danger")}</div></td>'
        + "</tr>"
    )


def _constructor_relation_row_js_template(lang: str = "en") -> str:
    return (
        '<tr class="constructor-relation-row">'
        '<td class="constructor-drag-cell"><span class="drag-handle" aria-hidden="true"></span></td>'
        '<td><input name="rel_name___IDX__" required pattern="[a-z][a-z0-9_]*" placeholder="related_to"></td>'
        '<td><input name="rel_label___IDX__" required placeholder="Related To"></td>'
        '<td><input name="rel_from___IDX__" placeholder="note, source or *" required></td>'
        '<td><input name="rel_to___IDX__" placeholder="note, source or *" required></td>'
        '<td class="constructor-center"><input class="constructor-checkbox" type="checkbox" name="rel_directed___IDX__" value="true" checked></td>'
        f'<td><div class="constructor-row-actions">{_constructor_icon_button("Delete", "removeConstructorRelationRow(this)", "danger")}</div></td>'
        "</tr>"
    )


def _submit_entity_type_constructor(project: ProjectConfig, form_data: dict[str, str], lang: str) -> dict[str, Any]:
    name = form_data.get("name", "").strip()
    label = form_data.get("label", "").strip() or name
    description = form_data.get("description", "").strip()
    if not name:
        return {"status": HTTPStatus.BAD_REQUEST, "html": _render_entity_type_constructor(project, "Name is required", lang)}
    fields = []
    required = []
    title_field = ""
    summary_field = ""
    slug_field = ""
    search_fields = []
    tag_fields = []
    for idx in _indexed_form_suffixes(form_data, "field_name_"):
        field_name_key = f"field_name_{idx}"
        field_name = form_data.get(field_name_key, "").strip()
        if not field_name:
            continue
        field_label = form_data.get(f"field_label_{idx}", "").strip() or field_name
        widget = form_data.get(f"field_widget_{idx}", "text").strip() or "text"
        field_payload: dict[str, Any] = {"name": field_name, "label": field_label, "widget": widget}
        options = _split_csv(form_data.get(f"field_options_{idx}", ""))
        if options:
            field_payload["options"] = options
        fields.append(field_payload)
        if form_data.get(f"field_required_{idx}") == "true":
            required.append(field_name)
        if form_data.get(f"field_title_{idx}") == "true":
            title_field = field_name
        if form_data.get(f"field_summary_{idx}") == "true":
            summary_field = field_name
        if form_data.get(f"field_slug_{idx}") == "true":
            slug_field = field_name
        if form_data.get(f"field_search_{idx}") == "true":
            search_fields.append(field_name)
        if form_data.get(f"field_tag_{idx}") == "true":
            tag_fields.append(field_name)
    if not fields:
        fields = [{"name": "title", "label": "Title", "widget": "text"}]
        required = ["title"]
        title_field = "title"
        search_fields = ["title"]
    entity_type_payload: dict[str, Any] = {
        "name": name,
        "label": label,
        "description": description,
        "fields": fields,
        "required": required,
        "title_field": title_field,
        "summary_field": summary_field,
        "slug_field": slug_field,
        "search_fields": search_fields,
        "tag_fields": tag_fields,
    }
    relation_types = []
    for ridx in _indexed_form_suffixes(form_data, "rel_name_"):
        rel_name_key = f"rel_name_{ridx}"
        rel_name = form_data.get(rel_name_key, "").strip()
        if not rel_name:
            continue
        relation_types.append(
            {
                "name": rel_name,
                "label": form_data.get(f"rel_label_{ridx}", "").strip() or rel_name,
                "from": _split_csv(form_data.get(f"rel_from_{ridx}", "")),
                "to": _split_csv(form_data.get(f"rel_to_{ridx}", "")),
                "directed": form_data.get(f"rel_directed_{ridx}") == "true",
            }
        )
    try:
        payload = load_project_schema(project.schema_path).to_dict()
        payload.setdefault("entity_types", []).append(entity_type_payload)
        if relation_types:
            payload.setdefault("relation_types", []).extend(relation_types)
        ProjectSchema.from_dict(payload)
        copy_schema_payload(project.schema_path, payload)
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        return {"status": HTTPStatus.BAD_REQUEST, "html": _render_entity_type_constructor(project, str(exc), lang)}
    return {"location": with_lang("/ui/entities?flash=created", lang)}


def _render_evidence_page(project: ProjectConfig, query: dict[str, list[str]], error: str | None, lang: str) -> str:
    entity_type = query.get("entity_type", [""])[0].strip()
    record_id = query.get("record_id", [""])[0].strip()
    error_html = f'<div class="flash flash-warning">{escape(error)}</div>' if error else ""
    if not entity_type or not record_id:
        schema = load_project_schema(project.schema_path)
        return renderer.render(
            "generic_shell.html",
            header_html=page_header("Evidence", "Attach evidence to any generic record."),
            body_html=error_html + panel("Select Record", _evidence_lookup_form(schema, entity_type, record_id, lang)),
        )
    with open_database(project.database_path) as database:
        record = RecordService(database, project).get_record(entity_type, record_id)
        if record is None:
            return renderer.render(
                "generic_shell.html",
                header_html=page_header("Evidence", "Evidence attached to generic records."),
                body_html=error_html + empty_state("Record not found", record_id),
            )
        evidence = GenericEvidenceService(database, project).list_evidence(entity_type, record.record_id)
    rows = [[escape(item.evidence_type), escape(item.description), escape(item.excerpt or ""), escape(item.created_at)] for item in evidence]
    body = (
        error_html
        + panel("Record", property_grid([("Type", record.entity_type), ("Title", record.title), ("Record ID", record.record_id), ("Slug", record.slug or "")]))
        + panel("Evidence", table(["Type", "Description", "Excerpt", "At"], rows) if rows else inner_empty_state("No evidence yet", "Add the first evidence item below."))
        + panel("Add Evidence", _evidence_form(record, lang))
    )
    return renderer.render(
        "generic_shell.html",
        header_html=page_header("Evidence", "Evidence attached to generic records."),
        body_html=body,
    )


def _evidence_lookup_form(schema: ProjectSchema, entity_type: str, record_id: str, lang: str) -> str:
    return (
        "<form class=\"search-form\" method=\"get\" action=\"/ui/evidence\">"
        f"<input type=\"hidden\" name=\"lang\" value=\"{escape(lang, quote=True)}\">"
        "<div class=\"search-form-grid\">"
        f"<select name=\"entity_type\">{_entity_options(schema, entity_type, 'Entity type')}</select>"
        f"<input name=\"record_id\" value=\"{escape(record_id, quote=True)}\" placeholder=\"record id or slug\">"
        "</div><div class=\"search-form-actions\"><button class=\"button button-primary\" type=\"submit\">Open Evidence</button></div></form>"
    )


def _evidence_form(record: Record, lang: str) -> str:
    return (
        f'<form class="project-form" method="post" action="{escape(with_lang("/ui/evidence", lang), quote=True)}">'
        f'<input type="hidden" name="entity_type" value="{escape(record.entity_type, quote=True)}">'
        f'<input type="hidden" name="record_id" value="{escape(record.record_id, quote=True)}">'
        '<div class="form-grid">'
        '<label class="form-field"><span class="field-label">Evidence Type</span><input name="evidence_type" value="note" required></label>'
        '<label class="form-field"><span class="field-label">Description</span><input name="description" required></label>'
        '<label class="form-field"><span class="field-label">Excerpt</span><textarea name="excerpt"></textarea></label>'
        '<label class="form-field"><span class="field-label">Attachment Path</span><input name="attachment_path"></label>'
        '</div><div class="form-actions"><button class="button button-primary" type="submit">Add Evidence</button></div></form>'
    )


def _submit_evidence_form(project: ProjectConfig, form_data: dict[str, str], lang: str) -> dict[str, Any]:
    entity_type = form_data.get("entity_type", "").strip()
    record_id = form_data.get("record_id", "").strip()
    payload = {
        "entity_type": entity_type,
        "record_id": record_id,
        "evidence_type": form_data.get("evidence_type", "").strip(),
        "description": form_data.get("description", "").strip(),
        "excerpt": form_data.get("excerpt", "").strip() or None,
        "attachment_path": form_data.get("attachment_path", "").strip() or None,
        "created_by": "ui",
        "source_origin": "ui",
    }
    with open_database(project.database_path) as database:
        result = GenericWorkflowService(database, project).apply_or_queue("add_evidence", payload, created_by="ui")
    if project.write_mode == "confirm":
        return {"location": with_lang("/ui/pending?flash=queued", lang)}
    return {"location": with_lang(f"/ui/evidence?entity_type={entity_type}&record_id={record_id}&flash=added", lang)}


def _submit_relation_form(project: ProjectConfig, form_data: dict[str, str], lang: str) -> dict[str, Any]:
    payload = {
        "from_entity_type": form_data.get("from_entity_type", "").strip(),
        "from_record_id": form_data.get("from_record_id", "").strip(),
        "to_entity_type": form_data.get("to_entity_type", "").strip(),
        "to_record_id": form_data.get("to_record_id", "").strip(),
        "relation_type": form_data.get("relation_type", "").strip(),
        "created_by": "ui",
    }
    with open_database(project.database_path) as database:
        result = GenericWorkflowService(database, project).apply_or_queue("create_relation", payload, created_by="ui")
    if project.write_mode == "confirm":
        return {"location": with_lang("/ui/pending?flash=queued", lang)}
    return {"location": with_lang(f"/ui/graph?focus_type={payload['from_entity_type']}&focus_id={payload['from_record_id']}", lang)}
