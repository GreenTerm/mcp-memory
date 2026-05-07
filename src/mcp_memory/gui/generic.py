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

from .i18n import resolve_language, with_lang
from .render import badge, empty_state, key_value_grid, section, table
from .templates import renderer


def generic_workspace_response(project: ProjectConfig, registry: ProjectRegistry, raw_path: str, workspace_page_html) -> tuple[HTTPStatus, str] | None:
    _ = registry
    path, _, query_string = raw_path.partition("?")
    query = parse_qs(query_string)
    lang = resolve_language(query.get("lang", ["en"])[0])
    if path == "/ui/entities":
        return HTTPStatus.OK, workspace_page_html(project, "Entity Types", _render_entity_types(project, lang), raw_path, lang)
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
    schema = load_project_schema(project.schema_path)
    rows = []
    for entity in schema.entity_types:
        rows.append(
            [
                f'<a href="{escape(with_lang(f"/ui/records?entity_type={entity.name}", lang), quote=True)}">{escape(entity.label)}</a>',
                escape(entity.name),
                escape(", ".join(entity.required)),
                f'<a class="button button-secondary" href="{escape(with_lang(f"/ui/records/{entity.name}/new", lang), quote=True)}">New</a>',
            ]
        )
    return renderer.render(
        "generic_shell.html",
        header_html="<section class=\"entity-hero\"><h2>Entity Types</h2><p class=\"entity-subtitle\">Schema-defined record types for this project.</p></section>",
        body_html=section("Types", table(["Label", "Name", "Required", "Action"], rows)),
    )


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
    content = create_link + (table(["Type", "Title", "Slug", "Summary"], rows) if rows else empty_state("No records yet", "Create the first record for this schema."))
    return renderer.render(
        "generic_shell.html",
        header_html="<section class=\"entity-hero\"><h2>Records</h2><p class=\"entity-subtitle\">Generic schema-backed records.</p></section>",
        body_html=section("Records", content),
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
        header_html="<section class=\"entity-hero\"><h2>Search</h2><p class=\"entity-subtitle\">Schema-backed FTS over generic records.</p></section>",
        body_html=section("Search Workspace", form) + section("Results", results_html),
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
        + section("Graph Filters", _graph_filter_form(schema, focus_type, focus_id, entity_type, lang), "Focus by record id or slug.")
        + "<div class=\"detail-layout\">"
        + f"<section class=\"panel-section graph-panel\"><div class=\"section-heading\"><h2>Relation Graph</h2></div>{graph_html}</section>"
        + f"<aside class=\"detail-panel\"><h2>Graph Nodes</h2>{side_html}</aside>"
        + "</div>"
        + section("Create Relation", _relation_form(schema, lang), "Relation types are validated against schema.json.")
    )
    return renderer.render(
        "generic_shell.html",
        header_html="<section class=\"entity-hero\"><h2>Graph</h2><p class=\"entity-subtitle\">Typed relations between generic records.</p></section>",
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
    payload = "<pre class=\"shell-command\"><code>{}</code></pre>".format(escape(json.dumps(record.payload, ensure_ascii=False, indent=2)))
    meta = key_value_grid([("Type", record.entity_type), ("Record ID", record.record_id), ("Slug", record.slug or ""), ("Status", record.status)])
    actions = (
        f'<a class="button button-primary" href="{escape(with_lang(f"/ui/records/{record.entity_type}/{record.record_id}/edit", lang), quote=True)}">Edit</a>'
        f'<form method="post" action="{escape(with_lang(f"/ui/records/{record.entity_type}/{record.record_id}/archive", lang), quote=True)}"><button class="button button-secondary" type="submit">Archive</button></form>'
    )
    relation_rows = [[escape(item.relation_type), escape(item.from_record_id), escape(item.to_record_id)] for item in relations]
    evidence_rows = [[escape(item.evidence_type), escape(item.description), escape(item.created_by), escape(item.created_at)] for item in evidence]
    body = (
        f"<section class=\"entity-hero\"><h2>{escape(record.title)}</h2><p class=\"entity-subtitle\">{escape(record.summary)}</p>{meta}<div class=\"form-actions\">{actions}</div></section>"
        + section("Payload", payload)
        + section("Relations", table(["Type", "From", "To"], relation_rows) if relation_rows else empty_state("No relations yet", "Create relations through API or MCP."))
        + section("Evidence", table(["Type", "Description", "By", "At"], evidence_rows) if evidence_rows else empty_state("No evidence yet", "Attach evidence from this page or through MCP."))
        + section("Add Evidence", _evidence_form(record, lang))
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
        if field.widget in {"textarea", "json", "tags"}:
            control = f'<textarea name="{escape(field.name, quote=True)}"{required}>{escape(str(value))}</textarea>'
        elif field.widget == "bool":
            checked = " checked" if value is True else ""
            control = f'<input type="checkbox" name="{escape(field.name, quote=True)}" value="true"{checked}>'
        elif field.widget == "enum":
            options = "".join(f'<option value="{escape(option, quote=True)}"{" selected" if str(value) == option else ""}>{escape(option)}</option>' for option in field.options)
            control = f'<select name="{escape(field.name, quote=True)}"{required}>{options}</select>'
        else:
            input_type = "number" if field.widget == "number" else "text"
            control = f'<input type="{input_type}" name="{escape(field.name, quote=True)}" value="{escape(str(value), quote=True)}"{required}>'
        fields.append(f'<label class="form-field"><span class="field-label">{escape(field.label)}</span>{control}</label>')
    error_html = f'<div class="flash flash-warning">{escape(error)}</div>' if error else ""
    return section(
        "Record Form",
        f'{error_html}<form class="project-form" method="post" action="{escape(action, quote=True)}"><div class="form-grid">{"".join(fields)}</div><div class="form-actions"><button class="button button-primary" type="submit">Save</button></div></form>',
        f"{entity.label} fields are generated from schema.json.",
    )


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
        header_html="<section class=\"entity-hero\"><h2>Schema Builder</h2><p class=\"entity-subtitle\">Edit project schema metadata.</p></section>",
        body_html=(
            section("Schema Overview", _schema_overview(schema))
            + section("Add Entity Type", _entity_type_builder_form(lang))
            + section("Add Field", _field_builder_form(schema, lang))
            + section("Add Relation Type", _relation_type_builder_form(schema, lang))
            + section("Schema JSON", form)
        ),
    )


def _schema_payload_from_form(form_data: dict[str, str]) -> dict[str, Any]:
    return json.loads(form_data.get("schema_json", "{}"))


def _schema_overview(schema: ProjectSchema) -> str:
    entity_rows = []
    for entity in schema.entity_types:
        entity_rows.append(
            [
                escape(entity.label),
                escape(entity.name),
                escape(", ".join(field.name for field in entity.fields)),
                escape(", ".join(entity.required)),
            ]
        )
    relation_rows = [
        [escape(relation.label), escape(relation.name), escape(", ".join(relation.from_types)), escape(", ".join(relation.to_types))]
        for relation in schema.relation_types
    ]
    return section("Entity Types", table(["Label", "Name", "Fields", "Required"], entity_rows)) + section(
        "Relation Types",
        table(["Label", "Name", "From", "To"], relation_rows) if relation_rows else empty_state("No relation types yet", "Add relation types below."),
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


def _render_evidence_page(project: ProjectConfig, query: dict[str, list[str]], error: str | None, lang: str) -> str:
    entity_type = query.get("entity_type", [""])[0].strip()
    record_id = query.get("record_id", [""])[0].strip()
    error_html = f'<div class="flash flash-warning">{escape(error)}</div>' if error else ""
    if not entity_type or not record_id:
        schema = load_project_schema(project.schema_path)
        return renderer.render(
            "generic_shell.html",
            header_html="<section class=\"entity-hero\"><h2>Evidence</h2><p class=\"entity-subtitle\">Attach evidence to any generic record.</p></section>",
            body_html=error_html + section("Select Record", _evidence_lookup_form(schema, entity_type, record_id, lang)),
        )
    with open_database(project.database_path) as database:
        record = RecordService(database, project).get_record(entity_type, record_id)
        if record is None:
            return renderer.render(
                "generic_shell.html",
                header_html="<section class=\"entity-hero\"><h2>Evidence</h2><p class=\"entity-subtitle\">Evidence attached to generic records.</p></section>",
                body_html=error_html + empty_state("Record not found", record_id),
            )
        evidence = GenericEvidenceService(database, project).list_evidence(entity_type, record.record_id)
    rows = [[escape(item.evidence_type), escape(item.description), escape(item.excerpt or ""), escape(item.created_at)] for item in evidence]
    body = (
        error_html
        + section("Record", key_value_grid([("Type", record.entity_type), ("Title", record.title), ("Record ID", record.record_id), ("Slug", record.slug or "")]))
        + section("Evidence", table(["Type", "Description", "Excerpt", "At"], rows) if rows else empty_state("No evidence yet", "Add the first evidence item below."))
        + section("Add Evidence", _evidence_form(record, lang))
    )
    return renderer.render(
        "generic_shell.html",
        header_html="<section class=\"entity-hero\"><h2>Evidence</h2><p class=\"entity-subtitle\">Evidence attached to generic records.</p></section>",
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
