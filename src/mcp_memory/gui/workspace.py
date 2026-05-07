from __future__ import annotations

import json
import logging
import math
import zipfile
from html import escape
from http import HTTPStatus
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from mcp_memory.config import ProjectConfig, ProjectRegistry
from mcp_memory.domain import (
    FunctionWrite,
    GlobalHypothesisWrite,
    HypothesisItem,
    HypothesisStatus,
    ObservedFact,
    StructureMember,
    StructureWrite,
)
from mcp_memory.logging_utils import get_logger, log_event
from mcp_memory.services import (
    EvidenceService,
    FunctionService,
    FunctionValidationError,
    GlobalHypothesisService,
    GlobalHypothesisValidationError,
    PendingChangeService,
    ProjectArchiveService,
    ProjectService,
    ProjectTransferService,
    RelationService,
    SearchQuery,
    SearchService,
    StructureService,
    StructureValidationError,
    GenericWorkflowService,
    Record,
    RecordService,
)
from mcp_memory.schema import load_project_schema
from mcp_memory.storage import Database, open_database
from .generic import generic_workspace_post_action, generic_workspace_response


logger = get_logger("ui")

from .render import (
    app_shell,
    badge,
    breadcrumbs,
    empty_state,
    flash_banner,
    html_page,
    key_value_grid,
    load_asset_text,
    mcp_config_block,
    section,
    shell_command,
    sidebar_nav,
    table,
    top_search,
    write_mode_badge,
)
from .i18n import language_switcher, localize_markup, resolve_language, translate_text, with_lang


def workspace_asset_response(path: str) -> tuple[str, bytes] | None:
    if path == "/ui/assets/app.css":
        return ("text/css; charset=utf-8", load_asset_text("app.css").encode("utf-8"))
    if path == "/ui/assets/ui.js":
        return ("text/javascript; charset=utf-8", load_asset_text("ui.js").encode("utf-8"))
    return None


def workspace_page_html(
    project: ProjectConfig,
    page_title: str,
    main_content: str,
    current_url: str,
    lang: str,
    title_suffix: str | None = None,
    breadcrumb_items: list[tuple[str, str | None]] | None = None,
) -> str:
    _, _, query_string = current_url.partition("?")
    query = parse_qs(query_string)
    search_query = query.get("q", [""])[0]
    sidebar = workspace_sidebar(current_url, lang)
    topbar = top_search(
        with_lang("/ui/search", lang),
        search_query,
        lang,
        write_mode_badge(project.write_mode) + language_switcher(current_url, lang),
    )
    trail = breadcrumbs(
        breadcrumb_items
        or [
            ("Project", with_lang("/ui/", lang)),
            (page_title, None),
        ]
    )
    body = app_shell(sidebar, topbar, trail, main_content)
    html_title = title_suffix or f"{page_title} - {project.display_name}"
    return localize_markup(
        html_page(html_title, body, "/ui/assets/app.css", page_class="workspace-page has-app-shell", html_lang=lang),
        lang,
    )


def workspace_sidebar(current_url: str, lang: str) -> str:
    items = [
        ("Entities", with_lang("/ui/entities", lang), "workspace"),
        ("Records", with_lang("/ui/records", lang), "workspace"),
        ("Binaries", with_lang("/ui/search?entity_type=binary", lang), "entities"),
        ("Functions", with_lang("/ui/functions", lang), "entities"),
        ("Structures", with_lang("/ui/structures", lang), "entities"),
        ("Hypotheses", with_lang("/ui/global-hypotheses", lang), "entities"),
        ("Search", with_lang("/ui/search", lang), "workspace"),
        ("Graph", with_lang("/ui/graph", lang), "workspace"),
        ("Import/Export", with_lang("/ui/import-export", lang), "project"),
        ("Backups", with_lang("/ui/backups", lang), "project"),
        ("Schema", with_lang("/ui/schema", lang), "project"),
        ("Settings", with_lang("/ui/settings", lang), "project"),
    ]
    path, _, _ = current_url.partition("?")
    return sidebar_nav(items, active_href=path, brand_href=with_lang("/ui/", lang))


def render_workspace_response(project: ProjectConfig, registry: ProjectRegistry, raw_path: str) -> tuple[HTTPStatus, str] | None:
    path, _, query_string = raw_path.partition("?")
    query = parse_qs(query_string)
    lang = resolve_language(query.get("lang", ["en"])[0])

    generic_response = generic_workspace_response(project, registry, raw_path, workspace_page_html)
    if generic_response is not None:
        return generic_response

    if path in ("/ui", "/ui/"):
        return (HTTPStatus.OK, render_workspace_dashboard(project, lang))
    if path == "/ui/search":
        return (HTTPStatus.OK, render_search_page(project, query, raw_path, lang))
    if path == "/ui/graph":
        return (HTTPStatus.OK, render_graph_page(project, query, raw_path, lang))
    if path == "/ui/pending":
        return (HTTPStatus.OK, render_pending_page(project, query, raw_path, lang))
    if path == "/ui/audit":
        return (HTTPStatus.OK, render_audit_page(project, query, raw_path, lang))
    if path == "/ui/settings":
        return (HTTPStatus.OK, render_project_settings_page(project, raw_path, project_settings_form_defaults(project), None, False, lang))
    if path == "/ui/import-export":
        return (HTTPStatus.OK, render_import_export_page(project, query, raw_path, None, lang))
    if path == "/ui/backups":
        return (HTTPStatus.OK, render_backups_page(project, query, raw_path, None, lang))
    if path == "/ui/functions":
        return (HTTPStatus.OK, render_functions_list_page(project, query, raw_path, lang))
    if path == "/ui/functions/new":
        return (HTTPStatus.OK, render_function_form_page(project, "new", function_form_defaults(project), None, lang))
    if path.startswith("/ui/functions/") and path.endswith("/history"):
        return render_function_history_response(project, path, lang)
    if path.startswith("/ui/functions/") and path.endswith("/edit"):
        return render_function_edit_response(project, path, lang)
    if path.startswith("/ui/functions/"):
        return render_function_response(project, path, query, raw_path, lang)
    if path == "/ui/structures":
        return (HTTPStatus.OK, render_structures_list_page(project, query, raw_path, lang))
    if path == "/ui/structures/new":
        return (HTTPStatus.OK, render_structure_form_page(project, "new", structure_form_defaults(project), None, lang))
    if path.startswith("/ui/structures/") and path.endswith("/history"):
        return render_structure_history_response(project, path.rsplit("/", 2)[-2], lang)
    if path.startswith("/ui/structures/") and path.endswith("/edit"):
        return render_structure_edit_response(project, path, lang)
    if path.startswith("/ui/structures/"):
        return render_structure_response(project, path.rsplit("/", 1)[-1], query, raw_path, lang)
    if path == "/ui/global-hypotheses":
        return (HTTPStatus.OK, render_global_hypotheses_list_page(project, query, raw_path, lang))
    if path == "/ui/global-hypotheses/new":
        return (
            HTTPStatus.OK,
            render_global_hypothesis_form_page(project, "new", global_hypothesis_form_defaults(project), None, lang),
        )
    if path.startswith("/ui/global-hypotheses/") and path.endswith("/history"):
        return render_global_hypothesis_history_response(project, path.rsplit("/", 2)[-2], lang)
    if path.startswith("/ui/global-hypotheses/") and path.endswith("/edit"):
        return render_global_hypothesis_edit_response(project, path, lang)
    if path.startswith("/ui/global-hypotheses/"):
        return render_global_hypothesis_response(project, path.rsplit("/", 1)[-1], query, raw_path, lang)
    if path.startswith("/ui/"):
        return (HTTPStatus.NOT_FOUND, render_not_found(project, "That workspace page does not exist.", lang))
    return None


def render_workspace_page(project: ProjectConfig, registry: ProjectRegistry, raw_path: str) -> str | None:
    response = render_workspace_response(project, registry, raw_path)
    if response is None:
        return None
    return response[1]


def workspace_post_action(project: ProjectConfig, registry: ProjectRegistry, raw_path: str, form_data: dict[str, str]) -> dict[str, Any] | None:
    path, _, query_string = raw_path.partition("?")
    query = parse_qs(query_string)
    lang = resolve_language(query.get("lang", [form_data.get("lang", "en")])[0])
    generic_action = generic_workspace_post_action(project, registry, raw_path, form_data)
    if generic_action is not None:
        return generic_action
    if path.startswith("/ui/pending/") and path.endswith("/confirm"):
        pending_change_id = path[: -len("/confirm")].rsplit("/", 1)[-1]
        with open_database(project.database_path) as database:
            generic_workflow = GenericWorkflowService(database, project)
            generic_pending = generic_workflow.get_pending_change(pending_change_id)
            if generic_pending is not None and generic_pending.operation in {"upsert_record", "archive_record", "create_relation", "add_evidence"}:
                generic_workflow.confirm_change(pending_change_id, confirmed_by=form_data.get("confirmed_by", "ui"), actor_type="user")
            else:
                PendingChangeService(database).confirm_change(
                    project.project_id,
                    pending_change_id,
                    confirmed_by=form_data.get("confirmed_by", "ui"),
                    actor_type="user",
                )
        log_event(logger, logging.INFO, "pending_confirmed", project_id=project.project_id, pending_change_id=pending_change_id)
        return {"location": with_lang("/ui/pending?flash=confirmed", lang)}

    if path.startswith("/ui/pending/") and path.endswith("/reject"):
        pending_change_id = path[: -len("/reject")].rsplit("/", 1)[-1]
        with open_database(project.database_path) as database:
            generic_workflow = GenericWorkflowService(database, project)
            generic_pending = generic_workflow.get_pending_change(pending_change_id)
            if generic_pending is not None and generic_pending.operation in {"upsert_record", "archive_record", "create_relation", "add_evidence"}:
                generic_workflow.reject_change(pending_change_id, rejected_by=form_data.get("rejected_by", "ui"))
            else:
                PendingChangeService(database).reject_change(
                    project.project_id,
                    pending_change_id,
                    rejected_by=form_data.get("rejected_by", "ui"),
                )
        log_event(logger, logging.WARNING, "pending_rejected", project_id=project.project_id, pending_change_id=pending_change_id)
        return {"location": with_lang("/ui/pending?flash=rejected", lang)}

    if path == "/ui/settings":
        return submit_project_settings_form(project, registry, form_data, lang)

    if path == "/ui/import-export/export":
        return submit_import_export_export(project, form_data, lang)

    if path == "/ui/import-export/import":
        return submit_import_export_import(project, form_data, lang)

    if path == "/ui/backups/create":
        return submit_backup_create(project, registry, form_data, lang)

    if path == "/ui/backups/restore":
        return submit_backup_restore(project, registry, form_data, lang)

    if path == "/ui/functions/new":
        return submit_function_form(project, form_data, is_edit=False, lang=lang)

    if path.startswith("/ui/functions/") and path.endswith("/edit"):
        return submit_function_form(project, form_data, is_edit=True, lang=lang)

    if path == "/ui/structures/new":
        return submit_structure_form(project, form_data, is_edit=False, lang=lang)

    if path.startswith("/ui/structures/") and path.endswith("/edit"):
        return submit_structure_form(project, form_data, is_edit=True, lang=lang)

    if path == "/ui/global-hypotheses/new":
        return submit_global_hypothesis_form(project, form_data, is_edit=False, lang=lang)

    if path.startswith("/ui/global-hypotheses/") and path.endswith("/edit"):
        return submit_global_hypothesis_form(project, form_data, is_edit=True, lang=lang)

    return None


def render_workspace_dashboard(project: ProjectConfig, lang: str) -> str:
    with open_database(project.database_path) as database:
        record_service = RecordService(database, project)
        schema = load_project_schema(project.schema_path)
        records = record_service.list_records(limit=1000)
        recent_records = record_service.list_records(limit=5)
        archived_count = database.connection.execute(
            "SELECT COUNT(*) AS count FROM records WHERE project_id = ? AND status = 'archived'",
            (project.project_id,),
        ).fetchone()["count"]
        relation_count = database.connection.execute(
            "SELECT COUNT(*) AS count FROM relations WHERE project_id = ?",
            (project.project_id,),
        ).fetchone()["count"]
        pending_count = len(GenericWorkflowService(database, project).list_pending_changes("pending"))

    mcp_endpoint = f"http://{project.mcp_host}:{project.mcp_port}/mcp"
    overview = key_value_grid(
        [
            ("Project ID", project.project_id),
            ("Schema Version", schema.schema_version),
            ("Entity Types", str(len(schema.entity_types))),
            ("Write Mode", project.write_mode),
            ("HTTP Endpoint", f"http://{project.http_host}:{project.http_port}"),
            ("MCP Endpoint", mcp_endpoint),
        ]
    )
    project_summary = "Local offline-first schema-backed knowledge base for people and agents."
    body = (
        "<main class=\"workspace-shell\">"
        f"{workspace_header(project, 'Project Overview', '/ui/', lang)}"
        "<section class=\"entity-hero\">"
        f"{render_header_meta([badge('Project', 'accent')])}"
        f"<h2>{escape(project.display_name)}</h2>"
        f"<p class=\"entity-subtitle\">{escape(project_summary)}</p>"
        f"{overview}"
        f"{mcp_config_block(mcp_endpoint, project.project_id)}"
        "</section>"
        f"{section('Project Stats', generic_metric_grid(len(schema.entity_types), len(records), int(archived_count), int(relation_count), pending_count), 'The current shape of this generic workspace.')}"
        f"{section('Quick Entries', overview_quick_entries(schema), 'Open the working surface you need next.')}"
        f"{section('Storage Paths', overview_storage_paths(project), 'Everything stays local to this project workspace.')}"
        f"{section('Recent Updates', render_recent_records(recent_records, lang), 'Latest generic records from this project.')}"
        "</main>"
    )
    return workspace_page_html(project, "Project Overview", body, "/ui/", lang, title_suffix=f"{project.display_name} Workspace")


def render_search_page(project: ProjectConfig, query: dict[str, list[str]], current_url: str, lang: str) -> str:
    q = query.get("q", [""])[0].strip()
    entity_type = query.get("entity_type", [""])[0].strip()
    binary_id = query.get("binary_id", [""])[0].strip()
    tag = query.get("tag", [""])[0].strip()

    results_html = empty_state(
        "Search across your project",
        "Try queries like main_handler, parser, helper_worker, or a tag such as parser.",
    )
    if q or entity_type or binary_id or tag:
        with open_database(project.database_path) as database:
            items = SearchService(database).search(
                SearchQuery(
                    project_id=project.project_id,
                    query_text=q,
                    entity_types=[entity_type] if entity_type else None,
                    binary_id=binary_id or None,
                    tag=tag or None,
                    limit=25,
                )
            )
        if items:
            grouped: dict[str, list[dict[str, Any]]] = {}
            for item in items:
                grouped.setdefault(str(item["entity_type"]), []).append(item)
            sections = []
            for group_name in ("function", "structure", "global_hypothesis"):
                group_items = grouped.get(group_name, [])
                if not group_items:
                    continue
                cards = "".join(render_search_result_card(project, entry) for entry in group_items)
                sections.append(section(human_entity_type(group_name), f"<div class=\"result-list\">{cards}</div>"))
            results_html = "".join(sections)
        else:
            results_html = empty_state("No matches yet", "Try a broader phrase, remove one filter, or search by tag only.")

    body = (
        "<main class=\"workspace-shell\">"
        f"{workspace_header(project, 'Search', current_url, lang)}"
        f"{section('Search Workspace', search_form(q, entity_type, binary_id, tag, lang), 'One search box, then small filters only when they help.')}"
        f"{results_html}"
        "</main>"
    )
    return workspace_page_html(project, "Search", body, current_url, lang, title_suffix=f"{project.display_name} Search")


def render_graph_page(project: ProjectConfig, query: dict[str, list[str]], current_url: str, lang: str) -> str:
    focus_type = query_value(query, "focus_type")
    focus_id = query_value(query, "focus_id")
    binary_id = query_value(query, "binary_id")
    entity_type = query_value(query, "entity_type")
    status = query_value(query, "status")
    min_confidence_text = query_value(query, "min_confidence")
    hops_text = query_value(query, "hops") or "1"
    flash_html = ""
    hops = 1
    if hops_text in {"1", "2"}:
        hops = int(hops_text)
    else:
        flash_html = flash_banner("Hops must be 1 or 2.", "warning")

    min_confidence: float | None = None
    if min_confidence_text:
        try:
            min_confidence = float(min_confidence_text)
        except ValueError:
            flash_html = flash_banner("Min confidence must be a number.", "warning")

    with open_database(project.database_path) as database:
        functions = FunctionService(database).list_project_functions(project.project_id)
        structures = StructureService(database).list_project_structures(project.project_id)
        hypotheses = GlobalHypothesisService(database).list_hypotheses(project.project_id)
        relations = RelationService(database).list_project_relations(project.project_id)

    nodes = graph_nodes(project, functions, structures, hypotheses, relations)
    selected_edges = graph_edges_for_focus(relations, focus_type, focus_id, hops) if focus_type and focus_id else relations[:80]
    selected_keys = graph_node_keys(selected_edges)
    if focus_type and focus_id:
        selected_keys.add((focus_type, focus_id))
    if not focus_type and not focus_id:
        selected_keys = graph_node_keys_limited(selected_edges, 50)

    filtered_keys = {
        key
        for key in selected_keys
        if graph_node_matches(nodes.get(key), entity_type, binary_id, status, min_confidence)
    }
    filtered_edges = [
        edge
        for edge in selected_edges
        if (edge.from_entity_type, edge.from_entity_id) in filtered_keys
        and (edge.to_entity_type, edge.to_entity_id) in filtered_keys
    ][:80]
    filtered_keys = graph_node_keys(filtered_edges) | {
        key
        for key in filtered_keys
        if key == (focus_type, focus_id)
    }
    graph_html = render_graph_svg(project, nodes, filtered_keys, filtered_edges, lang)
    side_list = render_graph_side_list(project, nodes, filtered_keys, lang)
    if not filtered_keys:
        graph_html = empty_state("No graph links yet", "Create relations first, or loosen one graph filter.")
        side_list = f"<div class=\"link-grid\"><a class=\"quick-link\" href=\"{escape(with_lang('/ui/search', lang), quote=True)}\">Open Search</a><a class=\"quick-link\" href=\"{escape(with_lang('/ui/functions', lang), quote=True)}\">Open Functions</a></div>"

    body = (
        "<main class=\"workspace-shell\">"
        f"{workspace_header(project, 'Graph', current_url, lang)}"
        f"{flash_html}"
        f"{section('Graph Filters', graph_filter_form(focus_type, focus_id, binary_id, entity_type, status, min_confidence_text, hops_text, lang), 'Focus one entity or scan recent relation clusters.')} "
        "<div class=\"detail-layout\">"
        f"<section class=\"panel-section graph-panel\"><div class=\"section-heading\"><h2>Relation Graph</h2></div>{graph_html}</section>"
        f"<aside class=\"detail-panel\"><h2>Graph Nodes</h2>{side_list}</aside>"
        "</div>"
        "</main>"
    )
    return workspace_page_html(project, "Graph", body, current_url, lang, title_suffix=f"{project.display_name} Graph")


def render_functions_list_page(project: ProjectConfig, query: dict[str, list[str]], current_url: str, lang: str) -> str:
    q = query_value(query, "q")
    binary_id = query_value(query, "binary_id")
    tag = query_value(query, "tag")
    sort = query_value(query, "sort") or "name"
    with open_database(project.database_path) as database:
        functions = FunctionService(database).list_project_functions(project.project_id)
    items = filter_functions(functions, q, binary_id, tag)
    items = sort_records(items, sort)
    content = (
        "<div class=\"result-list\">" + "".join(render_function_list_row(project, item) for item in items) + "</div>"
        if items
        else empty_state("No functions found", "Try a broader query or clear one filter.")
    )
    body = (
        "<main class=\"workspace-shell\">"
        f"{workspace_header(project, 'Functions', current_url, lang)}"
        f"{section('Functions', entity_list_filter_form('/ui/functions', q, binary_id, tag, '', sort, lang), 'Filter by text, binary, tag, or sort order.')}"
        f"{content}"
        "</main>"
    )
    return workspace_page_html(project, "Functions", body, current_url, lang, title_suffix=f"Functions - {project.display_name}")


def render_structures_list_page(project: ProjectConfig, query: dict[str, list[str]], current_url: str, lang: str) -> str:
    q = query_value(query, "q")
    binary_id = query_value(query, "binary_id")
    tag = query_value(query, "tag")
    sort = query_value(query, "sort") or "name"
    with open_database(project.database_path) as database:
        structures = StructureService(database).list_project_structures(project.project_id)
    items = filter_structures(structures, q, binary_id, tag)
    items = sort_records(items, sort)
    content = (
        "<div class=\"result-list\">" + "".join(render_structure_list_row(item) for item in items) + "</div>"
        if items
        else empty_state("No structures found", "Try a broader query or clear one filter.")
    )
    body = (
        "<main class=\"workspace-shell\">"
        f"{workspace_header(project, 'Structures', current_url, lang)}"
        f"{section('Structures', entity_list_filter_form('/ui/structures', q, binary_id, tag, '', sort, lang), 'Filter by text, binary, tag, or sort order.')}"
        f"{content}"
        "</main>"
    )
    return workspace_page_html(project, "Structures", body, current_url, lang, title_suffix=f"Structures - {project.display_name}")


def render_global_hypotheses_list_page(project: ProjectConfig, query: dict[str, list[str]], current_url: str, lang: str) -> str:
    q = query_value(query, "q")
    binary_id = query_value(query, "binary_id")
    tag = query_value(query, "tag")
    status = query_value(query, "status")
    sort = query_value(query, "sort") or "updated"
    with open_database(project.database_path) as database:
        hypotheses = GlobalHypothesisService(database).list_hypotheses(project.project_id)
    items = filter_global_hypotheses(hypotheses, q, binary_id, tag, status)
    items = sort_records(items, sort)
    content = (
        "<div class=\"result-list\">" + "".join(render_global_hypothesis_list_row(item) for item in items) + "</div>"
        if items
        else empty_state("No global hypotheses found", "Try a broader query or clear one filter.")
    )
    body = (
        "<main class=\"workspace-shell\">"
        f"{workspace_header(project, 'Global Hypotheses', current_url, lang)}"
        f"{section('Global Hypotheses', entity_list_filter_form('/ui/global-hypotheses', q, binary_id, tag, status, sort, lang), 'Filter by text, binary, tag, status, or sort order.')}"
        f"{content}"
        "</main>"
    )
    return workspace_page_html(
        project,
        "Global Hypotheses",
        body,
        current_url,
        lang,
        title_suffix=f"Global Hypotheses - {project.display_name}",
    )


def render_function_response(
    project: ProjectConfig,
    path: str,
    query: dict[str, list[str]],
    current_url: str,
    lang: str,
) -> tuple[HTTPStatus, str]:
    parts = [segment for segment in path.split("/") if segment]
    if len(parts) != 4:
            return (HTTPStatus.NOT_FOUND, render_not_found(project, "Function page not found.", lang))
    _, _, binary_id, function_id = parts
    with open_database(project.database_path) as database:
        function = FunctionService(database).get_function(project.project_id, binary_id, function_id)
        if function is None:
            return (HTTPStatus.NOT_FOUND, render_not_found(project, "Function not found.", lang))
        evidence = EvidenceService(database).list_evidence(project.project_id, "function", function.function_id)
        relations = RelationService(database).list_relations(project.project_id, "function", function.function_id)
        relation_html = render_relation_list(project, database, relations, "function", function.function_id)
        versions = list_entity_versions(project.project_id, database, "function", function.function_id)

    active_tab = detail_tab(query)
    base_url = f"/ui/functions/{function.binary_id}/{function.function_id}"
    signals = function.tags + function.used_apis + function.strings + function.constants
    summary_html = f"<p class=\"body-copy\">{escape(function.summary)}</p><p class=\"body-copy\">{escape(function.behavior_description)}</p>"
    metadata_html = key_value_grid(
        [
            ("Function ID", function.function_id),
            ("Address", function.address),
            ("Binary", function.binary_id),
            ("Raw Name", function.raw_name),
            ("Source", function.source_origin),
            ("Updated", function.updated_at),
            ("Confidence", "Unspecified" if function.confidence is None else f"{function.confidence:.2f}"),
        ]
    )
    timeline_html = entity_timeline_links(with_lang(f"{base_url}?tab=history", lang), with_lang("/ui/audit", lang))
    actions_html = entity_action_links(with_lang(f"{base_url}/edit", lang))
    tab_content = detail_tab_content(
        active_tab,
        facts=section("Summary", summary_html)
        + section("Signals", render_chip_list(signals))
        + section("Observed Facts", render_fact_list(function.observed_facts))
        + section("Evidence", render_evidence_list(evidence)),
        hypotheses=section("Hypotheses", render_hypothesis_list(function.hypotheses)),
        relations=section("Relations", focused_graph_link("function", function.function_id, lang) + relation_html),
        history=section("History", render_versions_inline(versions), "Each snapshot shows the stored record exactly as it was committed."),
    )
    side_panel = detail_side_panel("Function Metadata", metadata_html, actions_html + timeline_html)
    body = (
        "<main class=\"workspace-shell\">"
        f"{workspace_header(project, function.current_name, current_url, lang)}"
        "<article class=\"entity-hero\">"
        f"{render_header_meta([badge('Function', 'accent'), confidence_badge_markup(function.confidence), badge(function.binary_id, 'neutral')])}"
        f"<h2>{escape(function.current_name)}</h2>"
        f"<p class=\"entity-subtitle\">{escape(function.raw_name)} - {escape(function.address)}</p>"
        "</article>"
        f"{detail_tabs(base_url, active_tab, lang)}"
        f"<div class=\"detail-layout\"><div class=\"detail-main\">{tab_content}</div>{side_panel}</div>"
        "</main>"
    )
    html = workspace_page_html(
        project,
        function.current_name,
        body,
        current_url,
        lang,
        title_suffix=f"{function.current_name} - {project.display_name}",
        breadcrumb_items=[
            ("Project", with_lang("/ui/", lang)),
            ("Functions", with_lang("/ui/functions", lang)),
            (function.current_name, None),
        ],
    )
    return (HTTPStatus.OK, html)


def render_structure_response(
    project: ProjectConfig,
    structure_id: str,
    query: dict[str, list[str]],
    current_url: str,
    lang: str,
) -> tuple[HTTPStatus, str]:
    with open_database(project.database_path) as database:
        structure = StructureService(database).get_structure(project.project_id, structure_id)
        if structure is None:
            return (HTTPStatus.NOT_FOUND, render_not_found(project, "Structure not found.", lang))
        evidence = EvidenceService(database).list_evidence(project.project_id, "structure", structure.structure_id)
        relations = RelationService(database).list_relations(project.project_id, "structure", structure.structure_id)
        relation_html = render_relation_list(project, database, relations, "structure", structure.structure_id)
        versions = list_entity_versions(project.project_id, database, "structure", structure.structure_id)

    active_tab = detail_tab(query)
    base_url = f"/ui/structures/{structure.structure_id}"
    field_rows = [
        [
            escape(field.name),
            escape(field.offset),
            escape(field.data_type),
            "" if field.size is None else escape(str(field.size)),
            escape(field.comment),
        ]
        for field in structure.fields
    ]
    fields_table = (
        table(["Name", "Offset", "Type", "Size", "Comment"], field_rows)
        if field_rows
        else empty_state("No fields yet", "This structure has no member layout recorded yet.")
    )
    summary_html = f"<p class=\"body-copy\">{escape(structure.summary)}</p>"
    metadata_html = key_value_grid(
        [
            ("Structure ID", structure.structure_id),
            ("Binary", structure.binary_id),
            ("Raw Name", structure.raw_name),
            ("Fields", str(len(structure.fields))),
            ("Updated", structure.updated_at),
        ]
    )
    timeline_html = entity_timeline_links(with_lang(f"{base_url}?tab=history", lang), with_lang("/ui/audit", lang))
    actions_html = entity_action_links(with_lang(f"{base_url}/edit", lang))
    tab_content = detail_tab_content(
        active_tab,
        facts=section("Summary", summary_html)
        + section("Fields", fields_table)
        + section("Observed Facts", render_fact_list(structure.observed_facts))
        + section("Evidence", render_evidence_list(evidence)),
        hypotheses=section("Hypotheses", render_hypothesis_list(structure.hypotheses)),
        relations=section("Relations", focused_graph_link("structure", structure.structure_id, lang) + relation_html),
        history=section("History", render_versions_inline(versions), "Each snapshot shows the stored record exactly as it was committed."),
    )
    side_panel = detail_side_panel("Structure Metadata", metadata_html, actions_html + timeline_html)
    body = (
        "<main class=\"workspace-shell\">"
        f"{workspace_header(project, structure.current_name, current_url, lang)}"
        "<article class=\"entity-hero\">"
        f"{render_header_meta([badge('Structure', 'accent'), badge(structure.binary_id, 'neutral')])}"
        f"<h2>{escape(structure.current_name)}</h2>"
        f"<p class=\"entity-subtitle\">{escape(structure.raw_name)}</p>"
        "</article>"
        f"{detail_tabs(base_url, active_tab, lang)}"
        f"<div class=\"detail-layout\"><div class=\"detail-main\">{tab_content}</div>{side_panel}</div>"
        "</main>"
    )
    html = workspace_page_html(
        project,
        structure.current_name,
        body,
        current_url,
        lang,
        title_suffix=f"{structure.current_name} - {project.display_name}",
        breadcrumb_items=[
            ("Project", with_lang("/ui/", lang)),
            ("Structures", with_lang("/ui/structures", lang)),
            (structure.current_name, None),
        ],
    )
    return (HTTPStatus.OK, html)


def render_global_hypothesis_response(
    project: ProjectConfig,
    hypothesis_id: str,
    query: dict[str, list[str]],
    current_url: str,
    lang: str,
) -> tuple[HTTPStatus, str]:
    with open_database(project.database_path) as database:
        hypothesis = GlobalHypothesisService(database).get_hypothesis(project.project_id, hypothesis_id)
        if hypothesis is None:
            return (HTTPStatus.NOT_FOUND, render_not_found(project, "Global hypothesis not found.", lang))
        evidence = EvidenceService(database).list_evidence(project.project_id, "global_hypothesis", hypothesis.hypothesis_id)
        relations = RelationService(database).list_relations(project.project_id, "global_hypothesis", hypothesis.hypothesis_id)
        relation_html = render_relation_list(project, database, relations, "global_hypothesis", hypothesis.hypothesis_id)
        versions = list_entity_versions(project.project_id, database, "global_hypothesis", hypothesis.hypothesis_id)

    active_tab = detail_tab(query)
    base_url = f"/ui/global-hypotheses/{hypothesis.hypothesis_id}"
    confidence = "Unspecified" if hypothesis.confidence is None else f"{hypothesis.confidence:.2f}"
    statement_html = f"<p class=\"body-copy\">{escape(hypothesis.statement)}</p>"
    metadata_html = key_value_grid(
        [
            ("Hypothesis ID", hypothesis.hypothesis_id),
            ("Status", hypothesis.status.value),
            ("Confidence", confidence),
            ("Binary", hypothesis.binary_id or "Any"),
            ("Updated", hypothesis.updated_at),
        ]
    )
    timeline_html = entity_timeline_links(with_lang(f"{base_url}?tab=history", lang), with_lang("/ui/audit", lang))
    actions_html = entity_action_links(with_lang(f"{base_url}/edit", lang))
    tab_content = detail_tab_content(
        active_tab,
        facts=section("Statement", statement_html)
        + section("Supporting Facts", render_fact_list(hypothesis.observed_facts))
        + section("Evidence", render_evidence_list(evidence)),
        hypotheses=section("Hypothesis Status", metadata_html),
        relations=section("Relations", focused_graph_link("global_hypothesis", hypothesis.hypothesis_id, lang) + relation_html),
        history=section("History", render_versions_inline(versions), "Each snapshot shows the stored record exactly as it was committed."),
    )
    side_panel = detail_side_panel("Hypothesis Metadata", metadata_html, actions_html + timeline_html)
    body = (
        "<main class=\"workspace-shell\">"
        f"{workspace_header(project, hypothesis.title, current_url, lang)}"
        "<article class=\"entity-hero\">"
        f"{render_header_meta([badge('Global Hypothesis', 'accent'), badge(hypothesis.status.value.title(), hypothesis_tone(hypothesis.status.value)), confidence_badge_markup(hypothesis.confidence)])}"
        f"<h2>{escape(hypothesis.title)}</h2>"
        "</article>"
        f"{detail_tabs(base_url, active_tab, lang)}"
        f"<div class=\"detail-layout\"><div class=\"detail-main\">{tab_content}</div>{side_panel}</div>"
        "</main>"
    )
    html = workspace_page_html(
        project,
        hypothesis.title,
        body,
        current_url,
        lang,
        title_suffix=f"{hypothesis.title} - {project.display_name}",
        breadcrumb_items=[
            ("Project", with_lang("/ui/", lang)),
            ("Hypotheses", with_lang("/ui/global-hypotheses", lang)),
            (hypothesis.title, None),
        ],
    )
    return (HTTPStatus.OK, html)


def detail_tab(query: dict[str, list[str]]) -> str:
    tab = query_value(query, "tab") or "facts"
    return tab if tab in {"facts", "hypotheses", "relations", "history"} else "facts"


def detail_tabs(base_url: str, active_tab: str, lang: str) -> str:
    items = [
        ("facts", "Facts"),
        ("hypotheses", "Hypotheses"),
        ("relations", "Relations"),
        ("history", "History"),
    ]
    links = []
    for tab, label in items:
        class_name = "tab-link is-active" if tab == active_tab else "tab-link"
        current = " aria-current=\"page\"" if tab == active_tab else ""
        links.append(
            f"<a class=\"{class_name}\" href=\"{escape(with_lang(f'{base_url}?tab={tab}', lang), quote=True)}\"{current}>{escape(label)}</a>"
        )
    return f"<nav class=\"tab-list\" aria-label=\"Record sections\">{''.join(links)}</nav>"


def detail_tab_content(active_tab: str, facts: str, hypotheses: str, relations: str, history: str) -> str:
    return {
        "facts": facts,
        "hypotheses": hypotheses,
        "relations": relations,
        "history": history,
    }.get(active_tab, facts)


def detail_side_panel(title: str, metadata_html: str, actions_html: str) -> str:
    return (
        "<aside class=\"detail-panel\">"
        f"<h2>{escape(title)}</h2>"
        f"{metadata_html}"
        "<div class=\"detail-panel-actions\">"
        "<h3>Actions</h3>"
        f"{actions_html}"
        "</div>"
        "</aside>"
    )


def render_versions_inline(versions: list[dict[str, Any]]) -> str:
    if not versions:
        return empty_state("No versions yet", "This entity has not recorded any version snapshots yet.")
    return "<div class=\"pending-list\">" + "".join(render_version_card(version) for version in versions) + "</div>"


def focused_graph_link(entity_type: str, entity_id: str, lang: str) -> str:
    href = with_lang(f"/ui/graph?focus_type={entity_type}&focus_id={entity_id}", lang)
    return f"<div class=\"link-grid\"><a class=\"quick-link\" href=\"{escape(href, quote=True)}\">Open Focused Graph</a></div>"


def confidence_badge_markup(confidence: float | None) -> str:
    if confidence is None:
        return badge("Confidence unknown", "neutral")
    if confidence >= 0.75:
        tone = "success"
    elif confidence >= 0.4:
        tone = "warning"
    else:
        tone = "danger"
    return badge(f"Confidence {confidence:.2f}", tone)


def render_pending_page(project: ProjectConfig, query: dict[str, list[str]], current_url: str, lang: str) -> str:
    flash = query.get("flash", [""])[0].strip()
    with open_database(project.database_path) as database:
        items = PendingChangeService(database).list_pending_changes(project.project_id)
    flash_html = ""
    if flash == "confirmed":
        flash_html = flash_banner("Pending change confirmed and applied.", "success")
    elif flash == "rejected":
        flash_html = flash_banner("Pending change rejected.", "warning")
    elif flash == "queued":
        flash_html = flash_banner("Change queued for confirmation.", "info")
    content = (
        "<div class=\"pending-list\">" + "".join(render_pending_card(item) for item in items) + "</div>"
        if items
        else empty_state("Nothing is waiting right now", "New proposals will appear here when the project runs in confirm mode.")
    )
    body = (
        "<main class=\"workspace-shell\">"
        f"{workspace_header(project, 'Pending Changes', current_url, lang)}"
        f"{flash_html}"
        f"{section('Review Proposals', content, 'Confirm only what you want persisted into the knowledge base.')}"
        "</main>"
    )
    return workspace_page_html(
        project,
        "Pending Changes",
        body,
        current_url,
        lang,
        title_suffix=f"{project.display_name} Pending Changes",
    )


def render_audit_page(project: ProjectConfig, query: dict[str, list[str]], current_url: str, lang: str) -> str:
    entity_type = query.get("entity_type", [""])[0].strip()
    entity_id = query.get("entity_id", [""])[0].strip()
    with open_database(project.database_path) as database:
        audit_rows = list_audit_entries(project.project_id, database, entity_type or None, entity_id or None, limit=100)
    if audit_rows:
        content = "<div class=\"pending-list\">" + "".join(render_audit_card(project, row) for row in audit_rows) + "</div>"
    else:
        content = empty_state("No audit entries yet", "Once records are created or confirmed, the audit trail will appear here.")
    body = (
        "<main class=\"workspace-shell\">"
        f"{workspace_header(project, 'Audit Trail', current_url, lang)}"
        f"{section('Project Audit', audit_filter_form(entity_type, entity_id) + content, 'Review recent writes, confirmations, and provenance without leaving the workspace.')}"
        "</main>"
    )
    return workspace_page_html(
        project,
        "Audit Trail",
        body,
        current_url,
        lang,
        title_suffix=f"{project.display_name} Audit Trail",
    )


def render_function_history_response(project: ProjectConfig, path: str, lang: str) -> tuple[HTTPStatus, str]:
    parts = [segment for segment in path.split("/") if segment]
    if len(parts) != 5:
        return (HTTPStatus.NOT_FOUND, render_not_found(project, "Function history page not found.", lang))
    _, _, binary_id, function_id, _ = parts
    with open_database(project.database_path) as database:
        function = FunctionService(database).get_function(project.project_id, binary_id, function_id)
        if function is None:
            return (HTTPStatus.NOT_FOUND, render_not_found(project, "Function not found.", lang))
        versions = list_entity_versions(project.project_id, database, "function", function.function_id)
    return (HTTPStatus.OK, render_history_page(project, "Function Version History", function.current_name, versions, f"/ui/functions/{binary_id}/{function_id}", lang))


def render_function_edit_response(project: ProjectConfig, path: str, lang: str) -> tuple[HTTPStatus, str]:
    parts = [segment for segment in path.split("/") if segment]
    if len(parts) != 5:
        return (HTTPStatus.NOT_FOUND, render_not_found(project, "Function edit page not found.", lang))
    _, _, binary_id, function_id, _ = parts
    with open_database(project.database_path) as database:
        function = FunctionService(database).get_function(project.project_id, binary_id, function_id)
        if function is None:
            return (HTTPStatus.NOT_FOUND, render_not_found(project, "Function not found.", lang))
    form_data = function_form_from_record(function)
    return (HTTPStatus.OK, render_function_form_page(project, "edit", form_data, None, lang))


def render_structure_history_response(project: ProjectConfig, structure_id: str, lang: str) -> tuple[HTTPStatus, str]:
    with open_database(project.database_path) as database:
        structure = StructureService(database).get_structure(project.project_id, structure_id)
        if structure is None:
            return (HTTPStatus.NOT_FOUND, render_not_found(project, "Structure not found.", lang))
        versions = list_entity_versions(project.project_id, database, "structure", structure.structure_id)
    return (HTTPStatus.OK, render_history_page(project, "Structure Version History", structure.current_name, versions, f"/ui/structures/{structure.structure_id}", lang))


def render_structure_edit_response(project: ProjectConfig, path: str, lang: str) -> tuple[HTTPStatus, str]:
    structure_id = path.rsplit("/", 2)[-2]
    with open_database(project.database_path) as database:
        structure = StructureService(database).get_structure(project.project_id, structure_id)
        if structure is None:
            return (HTTPStatus.NOT_FOUND, render_not_found(project, "Structure not found.", lang))
    form_data = structure_form_from_record(structure)
    return (HTTPStatus.OK, render_structure_form_page(project, "edit", form_data, None, lang))


def render_global_hypothesis_history_response(project: ProjectConfig, hypothesis_id: str, lang: str) -> tuple[HTTPStatus, str]:
    with open_database(project.database_path) as database:
        hypothesis = GlobalHypothesisService(database).get_hypothesis(project.project_id, hypothesis_id)
        if hypothesis is None:
            return (HTTPStatus.NOT_FOUND, render_not_found(project, "Global hypothesis not found.", lang))
        versions = list_entity_versions(project.project_id, database, "global_hypothesis", hypothesis.hypothesis_id)
    return (
        HTTPStatus.OK,
        render_history_page(
            project,
            "Global Hypothesis Version History",
            hypothesis.title,
            versions,
            f"/ui/global-hypotheses/{hypothesis.hypothesis_id}",
            lang,
        ),
    )


def render_global_hypothesis_edit_response(project: ProjectConfig, path: str, lang: str) -> tuple[HTTPStatus, str]:
    hypothesis_id = path.rsplit("/", 2)[-2]
    with open_database(project.database_path) as database:
        hypothesis = GlobalHypothesisService(database).get_hypothesis(project.project_id, hypothesis_id)
        if hypothesis is None:
            return (HTTPStatus.NOT_FOUND, render_not_found(project, "Global hypothesis not found.", lang))
    form_data = global_hypothesis_form_from_record(hypothesis)
    return (HTTPStatus.OK, render_global_hypothesis_form_page(project, "edit", form_data, None, lang))


def render_history_page(
    project: ProjectConfig,
    page_title: str,
    entity_label: str,
    versions: list[dict[str, Any]],
    entity_url: str,
    lang: str,
) -> str:
    if versions:
        history_html = "<div class=\"pending-list\">" + "".join(render_version_card(version) for version in versions) + "</div>"
    else:
        history_html = empty_state("No versions yet", "This entity has not recorded any version snapshots yet.")
    back_link = f"<div class=\"link-grid\"><a class=\"quick-link\" href=\"{escape(entity_url)}\">Back To Record</a><a class=\"quick-link\" href=\"/ui/audit\">Open Audit Trail</a></div>"
    body = (
        "<main class=\"workspace-shell\">"
        f"{workspace_header(project, page_title, entity_url, lang)}"
        f"{section('Entity', key_value_grid([('Record', entity_label), ('Versions', str(len(versions)))]))}"
        f"{section('History', back_link + history_html, 'Each snapshot shows the stored record exactly as it was committed.')}"
        "</main>"
    )
    return workspace_page_html(
        project,
        page_title,
        body,
        entity_url,
        lang,
        title_suffix=f"{entity_label} History - {project.display_name}",
        breadcrumb_items=[
            ("Project", with_lang("/ui/", lang)),
            ("Record", with_lang(entity_url, lang)),
            ("History", None),
        ],
    )


def render_function_form_page(
    project: ProjectConfig,
    mode: str,
    form_data: dict[str, str],
    error_message: str | None,
    lang: str,
) -> str:
    title = "New Function" if mode == "new" else "Edit Function"
    flash_html = flash_banner(error_message, "warning") if error_message else ""
    readonly_attr = "" if mode == "new" else " readonly"
    action = "/ui/functions/new" if mode == "new" else f"/ui/functions/{escape(form_data['binary_id'])}/{escape(form_data['function_id'])}/edit"
    body = (
        "<main class=\"workspace-shell\">"
        f"{workspace_header(project, title, action, lang)}"
        f"{flash_html}"
        f"{section('Function Form', render_function_form(action, form_data, readonly_attr), 'Keep the form focused: enough detail to be useful, nothing more.')}"
        "</main>"
    )
    return workspace_page_html(project, title, body, action, lang, title_suffix=f"{title} - {project.display_name}")


def render_structure_form_page(
    project: ProjectConfig,
    mode: str,
    form_data: dict[str, str],
    error_message: str | None,
    lang: str,
) -> str:
    title = "New Structure" if mode == "new" else "Edit Structure"
    flash_html = flash_banner(error_message, "warning") if error_message else ""
    readonly_attr = "" if mode == "new" else " readonly"
    action = "/ui/structures/new" if mode == "new" else f"/ui/structures/{escape(form_data['structure_id'])}/edit"
    body = (
        "<main class=\"workspace-shell\">"
        f"{workspace_header(project, title, action, lang)}"
        f"{flash_html}"
        f"{section('Structure Form', render_structure_form(action, form_data, readonly_attr), 'Use one line per field member so the layout stays easy to scan and edit.')}"
        "</main>"
    )
    return workspace_page_html(project, title, body, action, lang, title_suffix=f"{title} - {project.display_name}")


def render_global_hypothesis_form_page(
    project: ProjectConfig,
    mode: str,
    form_data: dict[str, str],
    error_message: str | None,
    lang: str,
) -> str:
    title = "New Global Hypothesis" if mode == "new" else "Edit Global Hypothesis"
    flash_html = flash_banner(error_message, "warning") if error_message else ""
    readonly_attr = "" if mode == "new" else " readonly"
    action = (
        "/ui/global-hypotheses/new"
        if mode == "new"
        else f"/ui/global-hypotheses/{escape(form_data['hypothesis_id'])}/edit"
    )
    body = (
        "<main class=\"workspace-shell\">"
        f"{workspace_header(project, title, action, lang)}"
        f"{flash_html}"
        f"{section('Global Hypothesis Form', render_global_hypothesis_form(action, form_data, readonly_attr), 'Capture only the parts that matter to the current analytical claim.')}"
        "</main>"
    )
    return workspace_page_html(project, title, body, action, lang, title_suffix=f"{title} - {project.display_name}")


def render_project_settings_page(
    project: ProjectConfig,
    current_url: str,
    form_data: dict[str, str],
    error_message: str | None,
    restart_needed: bool,
    lang: str,
) -> str:
    path, _, query_string = current_url.partition("?")
    query = parse_qs(query_string)
    flash = query.get("flash", [""])[0].strip()
    flash_html = ""
    if error_message:
        flash_html = flash_banner(error_message, "warning")
    elif flash == "saved":
        flash_html = flash_banner("Project settings were saved successfully.", "success")
    elif flash == "saved_restart":
        flash_html = flash_banner(
            "Network settings were saved. Restart the project from Home UI to apply them.",
            "warning",
        )
    elif restart_needed:
        flash_html = flash_banner(
            "Network settings were saved. Restart the project from Home UI to apply them.",
            "warning",
        )

    mcp_endpoint = f"http://{form_data['mcp_host']}:{form_data['mcp_port']}/mcp"
    body = (
        "<main class=\"workspace-shell\">"
        f"{workspace_header(project, 'Project Settings', path or '/ui/settings', lang)}"
        f"{flash_html}"
        f"{section('Connection Target', shell_command(mcp_endpoint), 'Use the MCP endpoint as the primary connection target for agents.')}"
        f"{section('Project Settings', render_project_settings_form(form_data, lang), 'Adjust the project identity, write mode, and network endpoints without leaving the workspace.')}"
        "</main>"
    )
    return workspace_page_html(
        project,
        "Project Settings",
        body,
        current_url,
        lang,
        title_suffix=f"Project Settings - {project.display_name}",
    )


def render_import_export_page(
    project: ProjectConfig,
    query: dict[str, list[str]],
    current_url: str,
    error_message: str | None,
    lang: str,
) -> str:
    flash = query_value(query, "flash")
    flash_html = ""
    if error_message:
        flash_html = flash_banner(error_message, "warning")
    elif flash == "exported":
        flash_html = flash_banner("Project export completed.", "success")
    elif flash == "imported":
        flash_html = flash_banner("Project import completed.", "success")

    body = (
        "<main class=\"workspace-shell\">"
        f"{workspace_header(project, 'Import/Export', current_url, lang)}"
        f"{flash_html}"
        f"{section('Export Project', render_export_form(project, lang), 'Write a JSON bundle to a local path.')}"
        f"{section('Import Project', render_import_form(lang), 'Read a JSON bundle from a local path. Use replace only when you mean it.')}"
        "</main>"
    )
    return workspace_page_html(project, "Import/Export", body, current_url, lang, title_suffix=f"Import/Export - {project.display_name}")


def render_backups_page(
    project: ProjectConfig,
    query: dict[str, list[str]],
    current_url: str,
    error_message: str | None,
    lang: str,
) -> str:
    flash = query_value(query, "flash")
    flash_html = ""
    if error_message:
        flash_html = flash_banner(error_message, "warning")
    elif flash == "created":
        flash_html = flash_banner("Project backup created.", "success")
    elif flash == "restored":
        flash_html = flash_banner("Project backup restored as a new project.", "success")

    body = (
        "<main class=\"workspace-shell\">"
        f"{workspace_header(project, 'Backups', current_url, lang)}"
        f"{flash_html}"
        f"{section('Create Backup', render_backup_create_form(project, lang), 'Create a local zip archive for this project.')}"
        f"{section('Restore Backup', render_backup_restore_form(project, lang), 'Restore into an explicit new project target. The current project is not overwritten.')}"
        "</main>"
    )
    return workspace_page_html(project, "Backups", body, current_url, lang, title_suffix=f"Backups - {project.display_name}")


def render_export_form(project: ProjectConfig, lang: str) -> str:
    default_path = project.exports_dir / f"{project.project_id}-export.json"
    return (
        f'<form class="search-form" method="post" action="{escape(with_lang("/ui/import-export/export", lang), quote=True)}">'
        f'<label class="form-field"><span class="field-label">Output Path</span><input type="text" name="output_path" value="{escape(str(default_path), quote=True)}"></label>'
        '<div class="form-actions">'
        '<button class="button button-primary" type="submit">Export JSON</button>'
        "</div>"
        "</form>"
    )


def render_import_form(lang: str) -> str:
    return (
        f'<form class="search-form" method="post" action="{escape(with_lang("/ui/import-export/import", lang), quote=True)}">'
        '<label class="form-field"><span class="field-label">Input Path</span><input type="text" name="input_path" value="" placeholder="path to bundle.json"></label>'
        '<label class="checkbox-row"><input type="checkbox" name="replace_existing" value="true"> Replace existing records</label>'
        '<div class="form-actions">'
        '<button class="button button-primary" type="submit">Import JSON</button>'
        "</div>"
        "</form>"
    )


def render_backup_create_form(project: ProjectConfig, lang: str) -> str:
    default_path = project.backups_dir / f"{project.project_id}-backup.zip"
    return (
        f'<form class="search-form" method="post" action="{escape(with_lang("/ui/backups/create", lang), quote=True)}">'
        f'<label class="form-field"><span class="field-label">Output Path</span><input type="text" name="output_path" value="{escape(str(default_path), quote=True)}"></label>'
        '<div class="form-actions">'
        '<button class="button button-primary" type="submit">Create Backup</button>'
        "</div>"
        "</form>"
    )


def render_backup_restore_form(project: ProjectConfig, lang: str) -> str:
    default_root = project.project_root.parent / f"{project.project_id}-restored"
    return (
        f'<form class="search-form" method="post" action="{escape(with_lang("/ui/backups/restore", lang), quote=True)}">'
        '<div class="form-grid">'
        '<label class="form-field"><span class="field-label">Input Path</span><input type="text" name="input_path" value="" placeholder="path to backup.zip"></label>'
        f'<label class="form-field"><span class="field-label">Project Root</span><input type="text" name="project_root" value="{escape(str(default_root), quote=True)}"></label>'
        f'<label class="form-field"><span class="field-label">Project ID</span><input type="text" name="project_id" value="{escape(project.project_id + "-restored", quote=True)}"></label>'
        f'<label class="form-field"><span class="field-label">Display Name</span><input type="text" name="display_name" value="{escape(project.display_name + " Restored", quote=True)}"></label>'
        '<label class="form-field"><span class="field-label">HTTP Port</span><input type="text" name="http_port" value=""></label>'
        '<label class="form-field"><span class="field-label">MCP Port</span><input type="text" name="mcp_port" value=""></label>'
        f'<label class="form-field"><span class="field-label">Write Mode</span><select name="write_mode">{project_settings_write_mode_options(project.write_mode)}</select></label>'
        "</div>"
        '<div class="form-actions">'
        '<button class="button button-primary" type="submit">Restore Backup</button>'
        "</div>"
        "</form>"
    )


def render_project_settings_form(form_data: dict[str, str], lang: str) -> str:
    return (
        f'<form class="search-form" method="post" action="{escape(with_lang("/ui/settings", lang), quote=True)}">'
        '<div class="form-grid">'
        f'<label class="form-field"><span class="field-label">Display Name</span><input type="text" name="display_name" value="{escape(form_data["display_name"], quote=True)}"></label>'
        f'<label class="form-field"><span class="field-label">Write Mode</span><select name="write_mode">{project_settings_write_mode_options(form_data["write_mode"])}</select></label>'
        "</div>"
        '<details class="advanced-panel" open>'
        "<summary>Advanced Settings</summary>"
        '<div class="form-grid form-grid-advanced">'
        f'<label class="form-field"><span class="field-label">HTTP Host</span><input type="text" name="http_host" value="{escape(form_data["http_host"], quote=True)}"></label>'
        f'<label class="form-field"><span class="field-label">HTTP Port</span><input type="text" name="http_port" value="{escape(form_data["http_port"], quote=True)}"></label>'
        f'<label class="form-field"><span class="field-label">MCP Host</span><input type="text" name="mcp_host" value="{escape(form_data["mcp_host"], quote=True)}"></label>'
        f'<label class="form-field"><span class="field-label">MCP Port</span><input type="text" name="mcp_port" value="{escape(form_data["mcp_port"], quote=True)}"></label>'
        "</div>"
        '<div class="panel-note">'
        '<p>MCP is the primary endpoint for agent connections. HTTP is still used for the browser workspace.</p>'
        "</div>"
        "</details>"
        '<div class="form-actions">'
        '<button class="button button-primary" type="submit">Save Settings</button>'
        f'<a class="button button-secondary" href="{escape(with_lang("/ui/", lang), quote=True)}">Cancel</a>'
        "</div>"
        "</form>"
    )


def project_settings_write_mode_options(selected: str) -> str:
    options = [("confirm", "confirm"), ("auto", "auto")]
    rendered = []
    for value, label in options:
        selected_attr = " selected" if value == selected else ""
        rendered.append(f'<option value="{escape(value)}"{selected_attr}>{escape(label)}</option>')
    return "".join(rendered)


def render_not_found(project: ProjectConfig, message: str, lang: str) -> str:
    body = (
        "<main class=\"workspace-shell\">"
        f"{workspace_header(project, 'Not Found', '/ui/', lang)}"
        f"{empty_state('This page is not available', message)}"
        "</main>"
    )
    return workspace_page_html(project, "Not Found", body, "/ui/unknown", lang, title_suffix=f"{project.display_name} Not Found")


def workspace_header(project: ProjectConfig, title: str, current_url: str, lang: str) -> str:
    return (
        "<header class=\"workspace-header\">"
        "<div class=\"workspace-header-main\">"
        f"<h1>{escape(title)}</h1>"
        f"<p class=\"workspace-subtitle\">{escape(project.display_name)} - {escape(project.project_id)}</p>"
        "</div>"
        f"<a class=\"quick-link workspace-back-link\" href=\"{escape(with_lang('/', lang), quote=True)}\">Back to Projects</a>"
        "</header>"
    )


def metric_grid(binary_count: int, function_count: int, structure_count: int, hypothesis_count: int, pending_count: int) -> str:
    return (
        "<div class=\"metric-grid\">"
        f"{metric_card('Binaries', binary_count, 'Distinct binary IDs referenced by records.')}"
        f"{metric_card('Functions', function_count, 'Searchable function records in this workspace.')}"
        f"{metric_card('Structures', structure_count, 'Recovered layouts and type notes.')}"
        f"{metric_card('Hypotheses', hypothesis_count, 'Global analysis hypotheses.')}"
        f"{metric_card('Pending', pending_count, 'Changes waiting for confirmation.')}"
        "</div>"
    )


def generic_metric_grid(entity_type_count: int, record_count: int, archived_count: int, relation_count: int, pending_count: int) -> str:
    return (
        "<div class=\"metric-grid\">"
        f"{metric_card('Entity Types', entity_type_count, 'Types defined in this project schema.')}"
        f"{metric_card('Active Records', record_count, 'Records visible in default lists and search.')}"
        f"{metric_card('Archived', archived_count, 'Records kept as history but hidden by default.')}"
        f"{metric_card('Relations', relation_count, 'Typed links between records.')}"
        f"{metric_card('Pending', pending_count, 'Generic changes waiting for confirmation.')}"
        "</div>"
    )


def metric_card(title: str, value: int, description: str) -> str:
    return (
        "<article class=\"metric-card\">"
        f"<p class=\"metric-title\">{escape(title)}</p>"
        f"<p class=\"metric-value\">{escape(str(value))}</p>"
        f"<p class=\"metric-description\">{escape(description)}</p>"
        "</article>"
    )


def quick_links(project: ProjectConfig) -> str:
    return (
        "<div class=\"link-grid\">"
        "<a class=\"quick-link\" href=\"/ui/search\">Open Search</a>"
        "<a class=\"quick-link\" href=\"/ui/pending\">Review Pending Changes</a>"
        "<a class=\"quick-link\" href=\"/ui/audit\">Browse Audit Trail</a>"
        "<a class=\"quick-link\" href=\"/ui/settings\">Project Settings</a>"
        "<a class=\"quick-link\" href=\"/ui/functions/new\">New Function</a>"
        "<a class=\"quick-link\" href=\"/ui/structures/new\">New Structure</a>"
        "<a class=\"quick-link\" href=\"/ui/global-hypotheses/new\">New Global Hypothesis</a>"
        "</div>"
        "<div class=\"panel-note\">"
        "<p>CLI shortcuts for data management:</p>"
        f"{shell_command(f'mcp-memory export-json {project.project_id}')}"
        f"{shell_command(f'mcp-memory backup-project {project.project_id}')}"
        "</div>"
    )


def overview_quick_entries(schema: Any | None = None) -> str:
    entries = [
        ("Entity Types", "/ui/entities", "Browse the schema-defined record types."),
        ("Records", "/ui/records", "Scan generic records across the project."),
        ("Search", "/ui/search", "Find records by title, summary, text, or tags."),
        ("Graph", "/ui/graph", "Follow typed relationships between records."),
        ("Evidence", "/ui/evidence", "Attach source material to any record."),
        ("Schema", "/ui/schema", "Edit project schema JSON."),
        ("Settings", "/ui/settings", "Adjust identity, write mode, and endpoints."),
        ("Import/Export", "/ui/import-export", "Move local project data in and out."),
        ("Backups", "/ui/backups", "Create or restore local project archives."),
    ]
    if schema is not None:
        entries.extend(
            (f"New {entity.label}", f"/ui/records/{entity.name}/new", f"Create a new {entity.name} record.")
            for entity in schema.entity_types[:4]
        )
    cards = []
    for title, href, description in entries:
        cards.append(
            "<a class=\"quick-link action-card\" href=\"{0}\">"
            "<span class=\"action-card-title\">{1}</span>"
            "<span class=\"action-card-description\">{2}</span>"
            "</a>".format(escape(href, quote=True), escape(title), escape(description))
        )
    return f"<div class=\"link-grid\">{''.join(cards)}</div>"


def overview_storage_paths(project: ProjectConfig) -> str:
    return key_value_grid(
        [
            ("DB Path", str(project.database_path)),
            ("Exports Dir", str(project.exports_dir)),
            ("Backups Dir", str(project.backups_dir)),
            ("Project Root", str(project.project_root)),
        ]
    )


def render_recent_updates(project: ProjectConfig, items: list[dict[str, Any]]) -> str:
    if not items:
        return empty_state("No recent updates yet", "Created or updated records will appear here once the project has searchable content.")
    cards = []
    for item in items:
        title = str(item["title_text"]).strip() or str(item["entity_id"])
        body = str(item["body_text"]).strip()
        preview = body[:160] + ("..." if len(body) > 160 else "")
        cards.append(
            "<article class=\"mini-card\">"
            f"<div class=\"card-topline\">{badge(human_entity_type(str(item['entity_type'])), 'accent')}{badge(str(item['updated_at']), 'neutral')}</div>"
            f"<h3><a href=\"{escape(resolve_entity_link(project, str(item['entity_type']), str(item['entity_id'])))}\">{escape(title)}</a></h3>"
            f"<p class=\"body-copy\">{escape(preview or 'No summary available yet.')}</p>"
            "</article>"
        )
    return f"<div class=\"result-list\">{''.join(cards)}</div>"


def render_recent_records(items: list[Record], lang: str) -> str:
    if not items:
        return empty_state("No recent updates yet", "Created or updated records will appear here once the project has generic content.")
    cards = []
    for item in items:
        preview = item.summary[:160] + ("..." if len(item.summary) > 160 else "")
        href = with_lang(f"/ui/records/{item.entity_type}/{item.record_id}", lang)
        identity = item.slug or item.record_id
        cards.append(
            "<article class=\"mini-card\">"
            f"<div class=\"card-topline\">{badge(item.entity_type, 'accent')}{badge(item.updated_at, 'neutral')}</div>"
            f"<h3><a href=\"{escape(href, quote=True)}\">{escape(item.title)}</a></h3>"
            f"<p class=\"result-subtitle\">{escape(identity)}</p>"
            f"<p class=\"body-copy\">{escape(preview or 'No summary available yet.')}</p>"
            "</article>"
        )
    return f"<div class=\"result-list\">{''.join(cards)}</div>"


def search_form(q: str, entity_type: str, binary_id: str, tag: str, lang: str) -> str:
    return (
        "<form class=\"search-form\" method=\"get\" action=\"/ui/search\">"
        f"<input type=\"hidden\" name=\"lang\" value=\"{escape(lang, quote=True)}\">"
        f"<input type=\"text\" name=\"q\" value=\"{escape(q, quote=True)}\" placeholder=\"Search for functions, tags, or hypotheses\">"
        "<div class=\"search-form-grid\">"
        f"<input type=\"text\" name=\"binary_id\" value=\"{escape(binary_id, quote=True)}\" placeholder=\"binary_id (optional)\">"
        f"<input type=\"text\" name=\"tag\" value=\"{escape(tag, quote=True)}\" placeholder=\"tag (optional)\">"
        f"<select name=\"entity_type\">{entity_type_options(entity_type)}</select>"
        "</div>"
        "<div class=\"search-form-actions\">"
        "<button class=\"button button-primary\" type=\"submit\">Search Workspace</button>"
        f"<a class=\"button button-secondary\" href=\"{escape(with_lang('/ui/search', lang), quote=True)}\">Reset</a>"
        "</div>"
        "</form>"
    )


def entity_type_options(selected: str) -> str:
    options = [
        ("", "All entities"),
        ("function", "Functions"),
        ("structure", "Structures"),
        ("global_hypothesis", "Global hypotheses"),
    ]
    rendered = []
    for value, label in options:
        selected_attr = " selected" if value == selected else ""
        rendered.append(f"<option value=\"{escape(value)}\"{selected_attr}>{escape(label)}</option>")
    return "".join(rendered)


def render_search_result_card(project: ProjectConfig, item: dict[str, Any]) -> str:
    entity_type = str(item["entity_type"])
    link = resolve_entity_link(project, entity_type, str(item["entity_id"]))
    title = str(item["title_text"]).strip() or str(item["entity_id"])
    summary = str(item["body_text"]).strip()
    preview = summary[:220] + ("..." if len(summary) > 220 else "")
    tags = [segment for segment in str(item["tag_text"]).split() if segment][:3]
    badges = [badge(human_entity_type(entity_type), "accent")]
    if item["address_text"]:
        badges.append(badge(str(item["address_text"]), "neutral"))
    badges.extend(badge(tag, "soft") for tag in tags)
    return (
        "<article class=\"result-card\">"
        f"<div class=\"card-topline\">{''.join(badges)}</div>"
        f"<h3><a href=\"{escape(link)}\">{escape(title)}</a></h3>"
        f"<p class=\"result-subtitle\">{escape(str(item['entity_id']))}</p>"
        f"<p class=\"body-copy\">{escape(preview or 'No summary available yet.')}</p>"
        "</article>"
    )


def graph_filter_form(
    focus_type: str,
    focus_id: str,
    binary_id: str,
    entity_type: str,
    status: str,
    min_confidence: str,
    hops: str,
    lang: str,
) -> str:
    return (
        "<form class=\"search-form\" method=\"get\" action=\"/ui/graph\">"
        f"<input type=\"hidden\" name=\"lang\" value=\"{escape(lang, quote=True)}\">"
        "<div class=\"search-form-grid\">"
        f"<select name=\"focus_type\">{graph_entity_type_options(focus_type, 'Any focus type')}</select>"
        f"<input type=\"text\" name=\"focus_id\" value=\"{escape(focus_id, quote=True)}\" placeholder=\"focus entity id\">"
        f"<input type=\"text\" name=\"binary_id\" value=\"{escape(binary_id, quote=True)}\" placeholder=\"binary_id\">"
        f"<select name=\"entity_type\">{graph_entity_type_options(entity_type, 'Any entity type')}</select>"
        f"<select name=\"status\">{option('', 'Any status', status)}{option('new', 'New', status)}{option('probable', 'Probable', status)}{option('confirmed', 'Confirmed', status)}{option('rejected', 'Rejected', status)}</select>"
        f"<input type=\"text\" name=\"min_confidence\" value=\"{escape(min_confidence, quote=True)}\" placeholder=\"min confidence\">"
        f"<select name=\"hops\">{option('1', '1 hop', hops or '1')}{option('2', '2 hops', hops)}</select>"
        "</div>"
        "<div class=\"search-form-actions\">"
        "<button class=\"button button-primary\" type=\"submit\">Apply Filters</button>"
        f"<a class=\"button button-secondary\" href=\"{escape(with_lang('/ui/graph', lang), quote=True)}\">Reset</a>"
        "</div>"
        "</form>"
    )


def graph_entity_type_options(selected: str, empty_label: str) -> str:
    return (
        f"{option('', empty_label, selected)}"
        f"{option('function', 'Functions', selected)}"
        f"{option('structure', 'Structures', selected)}"
        f"{option('global_hypothesis', 'Global Hypotheses', selected)}"
    )


def graph_nodes(
    project: ProjectConfig,
    functions: list[Any],
    structures: list[Any],
    hypotheses: list[Any],
    relations: list[Any],
) -> dict[tuple[str, str], dict[str, Any]]:
    nodes: dict[tuple[str, str], dict[str, Any]] = {}
    for item in functions:
        nodes[("function", item.function_id)] = {
            "entity_type": "function",
            "entity_id": item.function_id,
            "label": item.current_name,
            "binary_id": item.binary_id,
            "status": "",
            "confidence": item.confidence,
            "link": f"/ui/functions/{item.binary_id}/{item.function_id}",
        }
    for item in structures:
        nodes[("structure", item.structure_id)] = {
            "entity_type": "structure",
            "entity_id": item.structure_id,
            "label": item.current_name,
            "binary_id": item.binary_id,
            "status": "",
            "confidence": None,
            "link": f"/ui/structures/{item.structure_id}",
        }
    for item in hypotheses:
        nodes[("global_hypothesis", item.hypothesis_id)] = {
            "entity_type": "global_hypothesis",
            "entity_id": item.hypothesis_id,
            "label": item.title,
            "binary_id": item.binary_id or "",
            "status": item.status.value,
            "confidence": item.confidence,
            "link": f"/ui/global-hypotheses/{item.hypothesis_id}",
        }
    for relation in relations:
        for entity_type, entity_id in (
            (relation.from_entity_type, relation.from_entity_id),
            (relation.to_entity_type, relation.to_entity_id),
        ):
            nodes.setdefault(
                (entity_type, entity_id),
                {
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "label": f"{human_entity_type(entity_type).rstrip('s')} {entity_id}",
                    "binary_id": "",
                    "status": "",
                    "confidence": None,
                    "link": resolve_entity_link(project, entity_type, entity_id),
                },
            )
    return nodes


def graph_edges_for_focus(relations: list[Any], focus_type: str, focus_id: str, hops: int) -> list[Any]:
    selected: list[Any] = []
    seen_nodes: set[tuple[str, str]] = {(focus_type, focus_id)}
    frontier: set[tuple[str, str]] = {(focus_type, focus_id)}
    for _ in range(hops):
        next_frontier: set[tuple[str, str]] = set()
        for relation in relations:
            from_key = (relation.from_entity_type, relation.from_entity_id)
            to_key = (relation.to_entity_type, relation.to_entity_id)
            if from_key not in frontier and to_key not in frontier:
                continue
            selected.append(relation)
            for key in (from_key, to_key):
                if key not in seen_nodes:
                    seen_nodes.add(key)
                    next_frontier.add(key)
        frontier = next_frontier
    return selected[:80]


def graph_node_keys(relations: list[Any]) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    for relation in relations:
        keys.add((relation.from_entity_type, relation.from_entity_id))
        keys.add((relation.to_entity_type, relation.to_entity_id))
    return keys


def graph_node_keys_limited(relations: list[Any], limit: int) -> set[tuple[str, str]]:
    ordered: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for relation in relations:
        for key in (
            (relation.from_entity_type, relation.from_entity_id),
            (relation.to_entity_type, relation.to_entity_id),
        ):
            if key in seen:
                continue
            seen.add(key)
            ordered.append(key)
            if len(ordered) >= limit:
                return set(ordered)
    return set(ordered)


def graph_node_matches(
    node: dict[str, Any] | None,
    entity_type: str,
    binary_id: str,
    status: str,
    min_confidence: float | None,
) -> bool:
    if node is None:
        return False
    if entity_type and node["entity_type"] != entity_type:
        return False
    if binary_id and node["binary_id"] != binary_id:
        return False
    if status and node["entity_type"] == "global_hypothesis" and node["status"] != status:
        return False
    if min_confidence is not None and node["confidence"] is not None and float(node["confidence"]) < min_confidence:
        return False
    return True


def render_graph_svg(
    project: ProjectConfig,
    nodes: dict[tuple[str, str], dict[str, Any]],
    node_keys: set[tuple[str, str]],
    relations: list[Any],
    lang: str,
) -> str:
    ordered_keys = sorted(node_keys, key=lambda key: (key[0], key[1]))[:50]
    if not ordered_keys:
        return empty_state("No graph links yet", "Create relations first, or loosen one graph filter.")
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

    edge_markup = []
    for relation in relations:
        from_key = (relation.from_entity_type, relation.from_entity_id)
        to_key = (relation.to_entity_type, relation.to_entity_id)
        if from_key not in positions or to_key not in positions:
            continue
        x1, y1 = positions[from_key]
        x2, y2 = positions[to_key]
        mid_x = (x1 + x2) / 2
        mid_y = (y1 + y2) / 2
        edge_markup.append(
            f"<line class=\"graph-edge\" x1=\"{x1:.1f}\" y1=\"{y1:.1f}\" x2=\"{x2:.1f}\" y2=\"{y2:.1f}\"></line>"
            f"<text class=\"graph-edge-label\" x=\"{mid_x:.1f}\" y=\"{mid_y:.1f}\">{escape(relation.relation_type)}</text>"
        )

    node_markup = []
    for key in ordered_keys:
        node = nodes[key]
        x, y = positions[key]
        label = str(node["label"])
        short_label = label[:24] + ("..." if len(label) > 24 else "")
        tone = str(node["entity_type"]).replace("_", "-")
        link = with_lang(str(node["link"]), lang)
        node_markup.append(
            f"<a href=\"{escape(link, quote=True)}\">"
            f"<g class=\"graph-node graph-node-{escape(tone)}\">"
            f"<circle cx=\"{x:.1f}\" cy=\"{y:.1f}\" r=\"25\"></circle>"
            f"<text x=\"{x:.1f}\" y=\"{(y + 43):.1f}\">{escape(short_label)}</text>"
            "</g>"
            "</a>"
        )

    return (
        "<div class=\"graph-canvas\">"
        f"<svg viewBox=\"0 0 {width} {height}\" role=\"img\" aria-label=\"Relation graph\">"
        f"{''.join(edge_markup)}"
        f"{''.join(node_markup)}"
        "</svg>"
        "</div>"
    )


def render_graph_side_list(
    project: ProjectConfig,
    nodes: dict[tuple[str, str], dict[str, Any]],
    node_keys: set[tuple[str, str]],
    lang: str,
) -> str:
    if not node_keys:
        return empty_state("No nodes selected", "Adjust the graph filters to show linked entities.")
    items = []
    for key in sorted(node_keys, key=lambda item: (item[0], item[1]))[:50]:
        node = nodes[key]
        meta = [human_entity_type(str(node["entity_type"])), str(node["entity_id"])]
        if node["binary_id"]:
            meta.append(str(node["binary_id"]))
        if node["status"]:
            meta.append(str(node["status"]))
        items.append(
            "<article class=\"mini-card\">"
            f"<div class=\"card-topline\">{badge(human_entity_type(str(node['entity_type'])), 'accent')}</div>"
            f"<h3><a href=\"{escape(with_lang(str(node['link']), lang), quote=True)}\">{escape(str(node['label']))}</a></h3>"
            f"<p class=\"result-subtitle\">{escape(' - '.join(meta))}</p>"
            "</article>"
        )
    return "<div class=\"result-list\">" + "".join(items) + "</div>"


def query_value(query: dict[str, list[str]], name: str) -> str:
    return query.get(name, [""])[0].strip()


def entity_list_filter_form(action: str, q: str, binary_id: str, tag: str, status: str, sort: str, lang: str) -> str:
    status_field = ""
    if action.endswith("global-hypotheses"):
        status_field = (
            '<select name="status">'
            f"{option('', 'Any status', status)}"
            f"{option('new', 'New', status)}"
            f"{option('probable', 'Probable', status)}"
            f"{option('confirmed', 'Confirmed', status)}"
            f"{option('rejected', 'Rejected', status)}"
            "</select>"
        )
    return (
        f"<form class=\"search-form\" method=\"get\" action=\"{escape(action, quote=True)}\">"
        f"<input type=\"hidden\" name=\"lang\" value=\"{escape(lang, quote=True)}\">"
        f"<input type=\"text\" name=\"q\" value=\"{escape(q, quote=True)}\" placeholder=\"Search by name or summary\">"
        "<div class=\"search-form-grid\">"
        f"<input type=\"text\" name=\"binary_id\" value=\"{escape(binary_id, quote=True)}\" placeholder=\"binary_id (optional)\">"
        f"<input type=\"text\" name=\"tag\" value=\"{escape(tag, quote=True)}\" placeholder=\"tag (optional)\">"
        f"{status_field}"
        '<select name="sort">'
        f"{option('name', 'Sort by name', sort)}"
        f"{option('updated', 'Sort by updated', sort)}"
        "</select>"
        "</div>"
        "<div class=\"search-form-actions\">"
        "<button class=\"button button-primary\" type=\"submit\">Apply Filters</button>"
        f"<a class=\"button button-secondary\" href=\"{escape(with_lang(action, lang), quote=True)}\">Reset</a>"
        "</div>"
        "</form>"
    )


def option(value: str, label: str, selected: str) -> str:
    selected_attr = " selected" if value == selected else ""
    return f"<option value=\"{escape(value, quote=True)}\"{selected_attr}>{escape(label)}</option>"


def filter_functions(items: list[Any], q: str, binary_id: str, tag: str) -> list[Any]:
    return [
        item
        for item in items
        if matches_text(q, [item.current_name, item.raw_name, item.summary, item.behavior_description, item.address])
        and matches_value(binary_id, item.binary_id)
        and matches_tag(tag, item.tags)
    ]


def filter_structures(items: list[Any], q: str, binary_id: str, tag: str) -> list[Any]:
    return [
        item
        for item in items
        if matches_text(q, [item.current_name, item.raw_name, item.summary])
        and matches_value(binary_id, item.binary_id)
        and matches_tag(tag, item.tags)
    ]


def filter_global_hypotheses(items: list[Any], q: str, binary_id: str, tag: str, status: str) -> list[Any]:
    return [
        item
        for item in items
        if matches_text(q, [item.title, item.statement])
        and matches_value(binary_id, item.binary_id or "")
        and matches_tag(tag, item.tags)
        and matches_value(status, item.status.value)
    ]


def matches_text(query: str, values: list[str]) -> bool:
    if not query:
        return True
    needle = query.casefold()
    return any(needle in value.casefold() for value in values if value)


def matches_value(expected: str, actual: str) -> bool:
    return not expected or expected == actual


def matches_tag(expected: str, tags: list[str]) -> bool:
    return not expected or expected in tags


def sort_records(items: list[Any], sort: str) -> list[Any]:
    if sort == "updated":
        return sorted(items, key=lambda item: getattr(item, "updated_at", ""), reverse=True)
    return sorted(items, key=lambda item: getattr(item, "current_name", getattr(item, "title", "")).casefold())


def render_function_list_row(project: ProjectConfig, item: Any) -> str:
    badges = [badge("Function", "accent")]
    if item.confidence is not None:
        badges.append(badge(f"Confidence {item.confidence:.2f}", "success" if item.confidence >= 0.75 else "warning"))
    badges.extend(badge(tag, "soft") for tag in item.tags[:3])
    return (
        "<article class=\"result-card list-row\">"
        f"<div class=\"card-topline\">{''.join(badges)}</div>"
        f"<h3><a href=\"/ui/functions/{escape(item.binary_id, quote=True)}/{escape(item.function_id, quote=True)}\">{escape(item.current_name)}</a></h3>"
        f"<p class=\"result-subtitle\">{escape(item.binary_id)} - {escape(item.address)} - {escape(item.updated_at)}</p>"
        f"<p class=\"body-copy\">{escape(item.summary or item.behavior_description or 'No summary available yet.')}</p>"
        "</article>"
    )


def render_structure_list_row(item: Any) -> str:
    badges = [badge("Structure", "accent"), badge(f"{len(item.fields)} fields", "neutral")]
    badges.extend(badge(tag, "soft") for tag in item.tags[:3])
    return (
        "<article class=\"result-card list-row\">"
        f"<div class=\"card-topline\">{''.join(badges)}</div>"
        f"<h3><a href=\"/ui/structures/{escape(item.structure_id, quote=True)}\">{escape(item.current_name)}</a></h3>"
        f"<p class=\"result-subtitle\">{escape(item.binary_id)} - {escape(item.updated_at)}</p>"
        f"<p class=\"body-copy\">{escape(item.summary or 'No summary available yet.')}</p>"
        "</article>"
    )


def render_global_hypothesis_list_row(item: Any) -> str:
    badges = [badge("Global Hypothesis", "accent"), badge(item.status.value.title(), hypothesis_tone(item.status.value))]
    if item.confidence is not None:
        badges.append(badge(f"Confidence {item.confidence:.2f}", "success" if item.confidence >= 0.75 else "warning"))
    badges.extend(badge(tag, "soft") for tag in item.tags[:3])
    binary = item.binary_id or "Any binary"
    return (
        "<article class=\"result-card list-row\">"
        f"<div class=\"card-topline\">{''.join(badges)}</div>"
        f"<h3><a href=\"/ui/global-hypotheses/{escape(item.hypothesis_id, quote=True)}\">{escape(item.title)}</a></h3>"
        f"<p class=\"result-subtitle\">{escape(binary)} - {escape(item.updated_at)}</p>"
        f"<p class=\"body-copy\">{escape(item.statement or 'No statement available yet.')}</p>"
        "</article>"
    )


def render_fact_list(items: list[Any]) -> str:
    if not items:
        return empty_state("No facts yet", "Observed facts will appear here once they are added.")
    return "<ul class=\"detail-list\">" + "".join(f"<li>{escape(item.fact)}</li>" for item in items) + "</ul>"


def render_hypothesis_list(items: list[Any]) -> str:
    if not items:
        return empty_state("No hypotheses yet", "There are no linked hypotheses for this entity yet.")
    rendered = []
    for item in items:
        status_badge = badge(item.status.value.title(), hypothesis_tone(item.status.value))
        confidence = "" if item.confidence is None else f" - confidence {item.confidence:.2f}"
        rendered.append(f"<li>{status_badge}<span>{escape(item.statement)}{escape(confidence)}</span></li>")
    return "<ul class=\"detail-list detail-list-rich\">" + "".join(rendered) + "</ul>"


def render_evidence_list(items: list[Any]) -> str:
    if not items:
        return empty_state("No evidence yet", "Evidence snippets and attachments will appear here once they are recorded.")
    cards = []
    for item in items:
        metadata = [item.evidence_type]
        if item.address_start:
            metadata.append(item.address_start)
        if item.attachment_path:
            metadata.append(item.attachment_path)
        cards.append(
            "<article class=\"mini-card\">"
            f"<p class=\"mini-card-title\">{escape(' - '.join(metadata))}</p>"
            f"<p class=\"body-copy\">{escape(item.description)}</p>"
            "</article>"
        )
    return "".join(cards)


def render_relation_list(
    project: ProjectConfig,
    database: Database,
    relations: list[Any],
    origin_type: str,
    origin_id: str,
) -> str:
    if not relations:
        return empty_state("No relations yet", "Linked entities will appear here once relationships are added.")
    function_service = FunctionService(database)
    structure_service = StructureService(database)
    hypothesis_service = GlobalHypothesisService(database)
    rows = []
    for relation in relations:
        if relation.from_entity_type == origin_type and relation.from_entity_id == origin_id:
            target_type = relation.to_entity_type
            target_id = relation.to_entity_id
        else:
            target_type = relation.from_entity_type
            target_id = relation.from_entity_id
        label = resolve_entity_label(
            project.project_id,
            function_service,
            structure_service,
            hypothesis_service,
            target_type,
            target_id,
        )
        rows.append(
            "<li>"
            f"{badge(relation.relation_type, 'soft')}"
            f"<a href=\"{escape(resolve_entity_link(project, target_type, target_id))}\">{escape(label)}</a>"
            "</li>"
        )
    return "<ul class=\"detail-list detail-list-rich\">" + "".join(rows) + "</ul>"


def render_pending_card(item: Any) -> str:
    payload_preview = json.dumps(item.payload, ensure_ascii=False, indent=2)
    return (
        "<article class=\"pending-card\">"
        f"<div class=\"card-topline\">{badge(item.operation.replace('_', ' '), 'accent')}{badge(item.entity_type, 'neutral')}</div>"
        f"<h3>{escape(item.entity_id)}</h3>"
        f"<p class=\"pending-meta\">Proposed by {escape(item.created_by)} - {escape(item.created_at)}</p>"
        "<details class=\"payload-preview\">"
        "<summary>View proposal payload</summary>"
        f"<pre><code>{escape(payload_preview)}</code></pre>"
        "</details>"
        "<div class=\"pending-actions\">"
        f"<form method=\"post\" action=\"/ui/pending/{escape(item.pending_change_id)}/confirm\"><button class=\"button button-primary\" type=\"submit\">Confirm</button></form>"
        f"<form method=\"post\" action=\"/ui/pending/{escape(item.pending_change_id)}/reject\"><button class=\"button button-secondary\" type=\"submit\">Reject</button></form>"
        "</div>"
        "</article>"
    )


def render_version_card(version: dict[str, Any]) -> str:
    snapshot_preview = json.dumps(version["snapshot"], ensure_ascii=False, indent=2)
    version_badge = badge(f"Version {version['version_number']}", "accent")
    return (
        "<article class=\"pending-card\">"
        f"<div class=\"card-topline\">{version_badge}{badge(version['created_by'], 'neutral')}</div>"
        f"<h3>{escape(version['created_at'])}</h3>"
        "<details class=\"payload-preview\">"
        "<summary>View snapshot</summary>"
        f"<pre><code>{escape(snapshot_preview)}</code></pre>"
        "</details>"
        "</article>"
    )


def render_audit_card(project: ProjectConfig, row: dict[str, str]) -> str:
    link = resolve_entity_link(project, row["entity_type"], row["entity_id"])
    return (
        "<article class=\"pending-card\">"
        f"<div class=\"card-topline\">{badge(row['action'], 'accent')}{badge(row['entity_type'], 'neutral')}{badge(row['actor_type'], 'soft')}</div>"
        f"<h3><a href=\"{escape(link)}\">{escape(row['summary'])}</a></h3>"
        f"<p class=\"pending-meta\">{escape(row['created_at'])} - actor {escape(row['actor_id'])} - source {escape(row['source_origin'])}</p>"
        "</article>"
    )


def audit_filter_form(entity_type: str, entity_id: str) -> str:
    return (
        "<form class=\"search-form\" method=\"get\" action=\"/ui/audit\">"
        "<div class=\"search-form-grid\">"
        f"<input type=\"text\" name=\"entity_type\" value=\"{escape(entity_type)}\" placeholder=\"entity_type (optional)\">"
        f"<input type=\"text\" name=\"entity_id\" value=\"{escape(entity_id)}\" placeholder=\"entity_id (optional)\">"
        "</div>"
        "<div class=\"search-form-actions\">"
        "<button class=\"button button-primary\" type=\"submit\">Filter Audit</button>"
        "<a class=\"button button-secondary\" href=\"/ui/audit\">Reset</a>"
        "</div>"
        "</form>"
    )


def entity_timeline_links(history_url: str, audit_url: str) -> str:
    return (
        "<div class=\"link-grid\">"
        f"<a class=\"quick-link\" href=\"{escape(history_url)}\">View Version History</a>"
        f"<a class=\"quick-link\" href=\"{escape(audit_url)}\">Open Audit Trail</a>"
        "</div>"
    )


def entity_action_links(edit_url: str) -> str:
    return (
        "<div class=\"link-grid\">"
        f"<a class=\"quick-link\" href=\"{escape(edit_url)}\">Edit Record</a>"
        "</div>"
    )


def render_function_form(action: str, form_data: dict[str, str], readonly_attr: str) -> str:
    allow_conflict_checked = " checked" if form_data.get("allow_conflict") == "true" else ""
    return (
        f"<form class=\"search-form\" method=\"post\" action=\"{escape(action)}\">"
        f"<input type=\"text\" name=\"binary_id\" value=\"{escape(form_data['binary_id'])}\" placeholder=\"binary_id\"{readonly_attr}>"
        f"<input type=\"text\" name=\"function_id\" value=\"{escape(form_data['function_id'])}\" placeholder=\"function_id\"{readonly_attr}>"
        f"<input type=\"text\" name=\"address\" value=\"{escape(form_data['address'])}\" placeholder=\"0x401000\">"
        f"<input type=\"text\" name=\"raw_name\" value=\"{escape(form_data['raw_name'])}\" placeholder=\"raw name\">"
        f"<input type=\"text\" name=\"current_name\" value=\"{escape(form_data['current_name'])}\" placeholder=\"display name\">"
        f"<textarea name=\"summary\" rows=\"3\" placeholder=\"summary\">{escape(form_data['summary'])}</textarea>"
        f"<textarea name=\"behavior_description\" rows=\"5\" placeholder=\"behavior description\">{escape(form_data['behavior_description'])}</textarea>"
        f"<textarea name=\"tags\" rows=\"3\" placeholder=\"one tag per line\">{escape(form_data['tags'])}</textarea>"
        f"<textarea name=\"used_apis\" rows=\"3\" placeholder=\"one API per line\">{escape(form_data['used_apis'])}</textarea>"
        f"<textarea name=\"strings\" rows=\"3\" placeholder=\"one string per line\">{escape(form_data['strings'])}</textarea>"
        f"<textarea name=\"constants\" rows=\"3\" placeholder=\"one constant per line\">{escape(form_data['constants'])}</textarea>"
        f"<textarea name=\"observed_facts\" rows=\"4\" placeholder=\"one observed fact per line\">{escape(form_data['observed_facts'])}</textarea>"
        f"<input type=\"text\" name=\"confidence\" value=\"{escape(form_data['confidence'])}\" placeholder=\"confidence 0.0 - 1.0 (optional)\">"
        f"<label class=\"checkbox-row\"><input type=\"checkbox\" name=\"allow_conflict\" value=\"true\"{allow_conflict_checked}> Allow address conflict</label>"
        "<div class=\"search-form-actions\">"
        "<button class=\"button button-primary\" type=\"submit\">Save Function</button>"
        "<a class=\"button button-secondary\" href=\"/ui/search\">Cancel</a>"
        "</div>"
        "</form>"
    )


def render_structure_form(action: str, form_data: dict[str, str], readonly_attr: str) -> str:
    return (
        f"<form class=\"search-form\" method=\"post\" action=\"{escape(action)}\">"
        f"<input type=\"text\" name=\"binary_id\" value=\"{escape(form_data['binary_id'])}\" placeholder=\"binary_id\">"
        f"<input type=\"text\" name=\"structure_id\" value=\"{escape(form_data['structure_id'])}\" placeholder=\"structure_id\"{readonly_attr}>"
        f"<input type=\"text\" name=\"raw_name\" value=\"{escape(form_data['raw_name'])}\" placeholder=\"raw name\">"
        f"<input type=\"text\" name=\"current_name\" value=\"{escape(form_data['current_name'])}\" placeholder=\"display name\">"
        f"<textarea name=\"summary\" rows=\"4\" placeholder=\"summary\">{escape(form_data['summary'])}</textarea>"
        f"<textarea name=\"fields\" rows=\"6\" placeholder=\"name|offset|type|size|comment\">{escape(form_data['fields'])}</textarea>"
        f"<textarea name=\"tags\" rows=\"3\" placeholder=\"one tag per line\">{escape(form_data['tags'])}</textarea>"
        f"<textarea name=\"observed_facts\" rows=\"4\" placeholder=\"one observed fact per line\">{escape(form_data['observed_facts'])}</textarea>"
        "<div class=\"search-form-actions\">"
        "<button class=\"button button-primary\" type=\"submit\">Save Structure</button>"
        "<a class=\"button button-secondary\" href=\"/ui/search\">Cancel</a>"
        "</div>"
        "</form>"
    )


def render_global_hypothesis_form(action: str, form_data: dict[str, str], readonly_attr: str) -> str:
    return (
        f"<form class=\"search-form\" method=\"post\" action=\"{escape(action)}\">"
        f"<input type=\"text\" name=\"hypothesis_id\" value=\"{escape(form_data['hypothesis_id'])}\" placeholder=\"hypothesis_id\"{readonly_attr}>"
        f"<input type=\"text\" name=\"title\" value=\"{escape(form_data['title'])}\" placeholder=\"title\">"
        f"<textarea name=\"statement\" rows=\"5\" placeholder=\"statement\">{escape(form_data['statement'])}</textarea>"
        f"<select name=\"status\">{hypothesis_status_options(form_data['status'])}</select>"
        f"<input type=\"text\" name=\"binary_id\" value=\"{escape(form_data['binary_id'])}\" placeholder=\"binary_id (optional)\">"
        f"<input type=\"text\" name=\"confidence\" value=\"{escape(form_data['confidence'])}\" placeholder=\"confidence 0.0 - 1.0 (optional)\">"
        f"<textarea name=\"tags\" rows=\"3\" placeholder=\"one tag per line\">{escape(form_data['tags'])}</textarea>"
        f"<textarea name=\"observed_facts\" rows=\"4\" placeholder=\"one observed fact per line\">{escape(form_data['observed_facts'])}</textarea>"
        "<div class=\"search-form-actions\">"
        "<button class=\"button button-primary\" type=\"submit\">Save Global Hypothesis</button>"
        "<a class=\"button button-secondary\" href=\"/ui/search\">Cancel</a>"
        "</div>"
        "</form>"
    )


def hypothesis_status_options(selected: str) -> str:
    options = [
        ("new", "New"),
        ("probable", "Probable"),
        ("confirmed", "Confirmed"),
        ("rejected", "Rejected"),
    ]
    rendered = []
    for value, label in options:
        selected_attr = " selected" if value == selected else ""
        rendered.append(f"<option value=\"{escape(value)}\"{selected_attr}>{escape(label)}</option>")
    return "".join(rendered)


def render_chip_list(items: list[str]) -> str:
    unique = [item for item in dict.fromkeys(items) if item]
    if not unique:
        return empty_state("No signal list yet", "Tags, APIs, strings, and constants will appear here when present.")
    return "<div class=\"chip-row\">" + "".join(badge(item, "soft") for item in unique) + "</div>"


def render_header_meta(items: list[str]) -> str:
    return "<div class=\"card-topline\">" + "".join(items) + "</div>"


def human_entity_type(entity_type: str) -> str:
    return {
        "function": "Functions",
        "structure": "Structures",
        "global_hypothesis": "Global Hypotheses",
    }.get(entity_type, entity_type.replace("_", " ").title())


def hypothesis_tone(status: str) -> str:
    return {
        "confirmed": "success",
        "rejected": "danger",
        "probable": "warning",
        "new": "accent",
    }.get(status, "neutral")


def resolve_entity_link(project: ProjectConfig, entity_type: str, entity_id: str) -> str:
    if entity_type == "structure":
        return f"/ui/structures/{entity_id}"
    if entity_type == "global_hypothesis":
        return f"/ui/global-hypotheses/{entity_id}"
    if entity_type == "function":
        with open_database(project.database_path) as database:
            for function in FunctionService(database).list_project_functions(project.project_id):
                if function.function_id == entity_id:
                    return f"/ui/functions/{function.binary_id}/{function.function_id}"
    return "/ui/search"


def resolve_entity_label(
    project_id: str,
    function_service: FunctionService,
    structure_service: StructureService,
    hypothesis_service: GlobalHypothesisService,
    entity_type: str,
    entity_id: str,
) -> str:
    if entity_type == "function":
        for function in function_service.list_project_functions(project_id):
            if function.function_id == entity_id:
                return function.current_name
    elif entity_type == "structure":
        structure = structure_service.get_structure(project_id, entity_id)
        if structure is not None:
            return structure.current_name
    elif entity_type == "global_hypothesis":
        hypothesis = hypothesis_service.get_hypothesis(project_id, entity_id)
        if hypothesis is not None:
            return hypothesis.title
    return f"{human_entity_type(entity_type).rstrip('s')} {entity_id}"


def function_form_defaults(project: ProjectConfig) -> dict[str, str]:
    return {
        "binary_id": "",
        "function_id": "",
        "address": "",
        "raw_name": "",
        "current_name": "",
        "summary": "",
        "behavior_description": "",
        "tags": "",
        "used_apis": "",
        "strings": "",
        "constants": "",
        "observed_facts": "",
        "confidence": "",
        "allow_conflict": "false",
    }


def structure_form_defaults(project: ProjectConfig) -> dict[str, str]:
    return {
        "binary_id": "",
        "structure_id": "",
        "raw_name": "",
        "current_name": "",
        "summary": "",
        "fields": "",
        "tags": "",
        "observed_facts": "",
    }


def function_form_from_record(record: Any) -> dict[str, str]:
    return {
        "binary_id": record.binary_id,
        "function_id": record.function_id,
        "address": record.address,
        "raw_name": record.raw_name,
        "current_name": record.current_name,
        "summary": record.summary,
        "behavior_description": record.behavior_description,
        "tags": "\n".join(record.tags),
        "used_apis": "\n".join(record.used_apis),
        "strings": "\n".join(record.strings),
        "constants": "\n".join(record.constants),
        "observed_facts": "\n".join(item.fact for item in record.observed_facts),
        "confidence": "" if record.confidence is None else str(record.confidence),
        "allow_conflict": "true" if getattr(record, "allow_conflict", False) else "false",
    }


def structure_form_from_record(record: Any) -> dict[str, str]:
    field_lines = []
    for item in record.fields:
        size_text = "" if item.size is None else str(item.size)
        field_lines.append("|".join([item.name, item.offset, item.data_type, size_text, item.comment]))
    return {
        "binary_id": record.binary_id,
        "structure_id": record.structure_id,
        "raw_name": record.raw_name,
        "current_name": record.current_name,
        "summary": record.summary,
        "fields": "\n".join(field_lines),
        "tags": "\n".join(record.tags),
        "observed_facts": "\n".join(item.fact for item in record.observed_facts),
    }


def global_hypothesis_form_defaults(project: ProjectConfig) -> dict[str, str]:
    return {
        "hypothesis_id": "",
        "title": "",
        "statement": "",
        "status": "new",
        "binary_id": "",
        "confidence": "",
        "tags": "",
        "observed_facts": "",
    }


def global_hypothesis_form_from_record(record: Any) -> dict[str, str]:
    return {
        "hypothesis_id": record.hypothesis_id,
        "title": record.title,
        "statement": record.statement,
        "status": record.status.value,
        "binary_id": "" if record.binary_id is None else record.binary_id,
        "confidence": "" if record.confidence is None else str(record.confidence),
        "tags": "\n".join(record.tags),
        "observed_facts": "\n".join(item.fact for item in record.observed_facts),
    }


def project_settings_form_defaults(project: ProjectConfig) -> dict[str, str]:
    return {
        "display_name": project.display_name,
        "write_mode": project.write_mode,
        "http_host": project.http_host,
        "http_port": str(project.http_port),
        "mcp_host": project.mcp_host,
        "mcp_port": str(project.mcp_port),
    }


def submit_project_settings_form(
    project: ProjectConfig,
    registry: ProjectRegistry,
    form_data: dict[str, str],
    lang: str,
) -> dict[str, Any]:
    values = merge_form_data(project_settings_form_defaults(project), form_data)
    display_name = values["display_name"].strip()
    write_mode = values["write_mode"].strip()
    http_host = values["http_host"].strip()
    mcp_host = values["mcp_host"].strip()
    changed = (
        display_name != project.display_name
        or write_mode != project.write_mode
        or http_host != project.http_host
        or values["http_port"].strip() != str(project.http_port)
        or mcp_host != project.mcp_host
        or values["mcp_port"].strip() != str(project.mcp_port)
    )
    log_event(
        logger,
        logging.INFO,
        "project_settings_submit",
        project_id=project.project_id,
        display_name=display_name,
        write_mode=write_mode,
        http_host=http_host,
        http_port=values["http_port"].strip(),
        mcp_host=mcp_host,
        mcp_port=values["mcp_port"].strip(),
    )
    try:
        http_port = parse_settings_port(values["http_port"], "HTTP Port")
        mcp_port = parse_settings_port(values["mcp_port"], "MCP Port")
        updated = ProjectService(registry).update_project(
            project_id=project.project_id,
            display_name=display_name,
            write_mode=write_mode,
            http_host=http_host,
            http_port=http_port,
            mcp_host=mcp_host,
            mcp_port=mcp_port,
        )
    except ValueError as exc:
        log_event(logger, logging.WARNING, "project_settings_validation_error", project_id=project.project_id, error=str(exc))
        html = render_project_settings_page(project, "/ui/settings", values, str(exc), False, lang)
        return {"status": HTTPStatus.BAD_REQUEST, "html": html}

    project.display_name = updated.display_name
    project.write_mode = updated.write_mode
    project.http_host = updated.http_host
    project.http_port = updated.http_port
    project.mcp_host = updated.mcp_host
    project.mcp_port = updated.mcp_port
    log_event(logger, logging.INFO, "project_settings_saved", project_id=project.project_id, restart_needed=changed)
    flash = "saved_restart" if changed else "saved"
    return {"location": with_lang(f"/ui/settings?flash={flash}", lang)}


def submit_import_export_export(project: ProjectConfig, form_data: dict[str, str], lang: str) -> dict[str, Any]:
    raw_path = form_data.get("output_path", "").strip()
    output_path = Path(raw_path) if raw_path else None
    try:
        ProjectTransferService().export_project(project, output_path)
    except (OSError, ValueError) as exc:
        query = {"flash": [""]}
        html = render_import_export_page(project, query, "/ui/import-export", str(exc), lang)
        return {"status": HTTPStatus.BAD_REQUEST, "html": html}
    return {"location": with_lang("/ui/import-export?flash=exported", lang)}


def submit_import_export_import(project: ProjectConfig, form_data: dict[str, str], lang: str) -> dict[str, Any]:
    raw_path = form_data.get("input_path", "").strip()
    if not raw_path:
        html = render_import_export_page(project, {}, "/ui/import-export", "Input Path is required.", lang)
        return {"status": HTTPStatus.BAD_REQUEST, "html": html}
    replace_existing = form_data.get("replace_existing") == "true"
    try:
        ProjectTransferService().import_project(project, Path(raw_path), replace_existing=replace_existing)
    except (OSError, ValueError, KeyError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
        html = render_import_export_page(project, {}, "/ui/import-export", str(exc), lang)
        return {"status": HTTPStatus.BAD_REQUEST, "html": html}
    return {"location": with_lang("/ui/import-export?flash=imported", lang)}


def submit_backup_create(project: ProjectConfig, registry: ProjectRegistry, form_data: dict[str, str], lang: str) -> dict[str, Any]:
    raw_path = form_data.get("output_path", "").strip()
    output_path = Path(raw_path) if raw_path else None
    try:
        ProjectArchiveService(registry).create_backup(project, output_path)
    except (OSError, ValueError) as exc:
        html = render_backups_page(project, {}, "/ui/backups", str(exc), lang)
        return {"status": HTTPStatus.BAD_REQUEST, "html": html}
    return {"location": with_lang("/ui/backups?flash=created", lang)}


def submit_backup_restore(project: ProjectConfig, registry: ProjectRegistry, form_data: dict[str, str], lang: str) -> dict[str, Any]:
    input_path = form_data.get("input_path", "").strip()
    project_root = form_data.get("project_root", "").strip()
    project_id = form_data.get("project_id", "").strip()
    display_name = form_data.get("display_name", "").strip()
    write_mode = form_data.get("write_mode", "").strip() or None
    if not input_path:
        html = render_backups_page(project, {}, "/ui/backups", "Input Path is required.", lang)
        return {"status": HTTPStatus.BAD_REQUEST, "html": html}
    if not project_root:
        html = render_backups_page(project, {}, "/ui/backups", "Project Root is required.", lang)
        return {"status": HTTPStatus.BAD_REQUEST, "html": html}
    try:
        http_port = parse_optional_settings_port(form_data.get("http_port", ""), "HTTP Port")
        mcp_port = parse_optional_settings_port(form_data.get("mcp_port", ""), "MCP Port")
        ProjectArchiveService(registry).restore_backup(
            Path(input_path),
            Path(project_root),
            project_id=project_id or None,
            display_name=display_name or None,
            http_port=http_port,
            mcp_port=mcp_port,
            write_mode=write_mode,
        )
    except (OSError, ValueError, KeyError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
        html = render_backups_page(project, {}, "/ui/backups", str(exc), lang)
        return {"status": HTTPStatus.BAD_REQUEST, "html": html}
    return {"location": with_lang("/ui/backups?flash=restored", lang)}


def parse_settings_port(raw_value: str, label: str) -> int:
    value = raw_value.strip()
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{label} must be a valid integer.") from exc


def parse_optional_settings_port(raw_value: str, label: str) -> int | None:
    value = raw_value.strip()
    if not value:
        return None
    return parse_settings_port(value, label)


def submit_function_form(project: ProjectConfig, form_data: dict[str, str], is_edit: bool, lang: str) -> dict[str, Any]:
    payload = function_payload_from_form(project.project_id, form_data)
    log_event(
        logger,
        logging.INFO,
        "function_form_submit",
        project_id=project.project_id,
        function_id=payload["function_id"],
        mode="edit" if is_edit else "new",
        write_mode=project.write_mode,
    )
    try:
        with open_database(project.database_path) as database:
            if project.write_mode == "confirm":
                PendingChangeService(database).create_pending_change(
                    project.project_id,
                    "function",
                    payload["function_id"],
                    "upsert_function",
                    payload,
                    created_by=str(payload["created_by"]),
                )
                log_event(logger, logging.INFO, "function_form_queued", project_id=project.project_id, function_id=payload["function_id"])
                return {"location": with_lang("/ui/pending?flash=queued", lang)}
            record = FunctionService(database).upsert_function(build_function_write(payload))
    except (FunctionValidationError, ValueError) as exc:
        log_event(
            logger,
            logging.WARNING,
            "function_form_validation_error",
            project_id=project.project_id,
            function_id=payload["function_id"],
            error=str(exc),
        )
        status = HTTPStatus.BAD_REQUEST
        html = render_function_form_page(
            project,
            "edit" if is_edit else "new",
            merge_form_data(function_form_defaults(project), form_data),
            str(exc),
            lang,
        )
        return {"status": status, "html": html}
    log_event(logger, logging.INFO, "function_form_saved", project_id=project.project_id, function_id=record.function_id)
    return {"location": with_lang(f"/ui/functions/{record.binary_id}/{record.function_id}", lang)}


def submit_structure_form(project: ProjectConfig, form_data: dict[str, str], is_edit: bool, lang: str) -> dict[str, Any]:
    payload = structure_payload_from_form(project.project_id, form_data)
    log_event(
        logger,
        logging.INFO,
        "structure_form_submit",
        project_id=project.project_id,
        structure_id=payload["structure_id"],
        mode="edit" if is_edit else "new",
        write_mode=project.write_mode,
    )
    try:
        with open_database(project.database_path) as database:
            if project.write_mode == "confirm":
                PendingChangeService(database).create_pending_change(
                    project.project_id,
                    "structure",
                    payload["structure_id"],
                    "upsert_structure",
                    payload,
                    created_by=str(payload["created_by"]),
                )
                log_event(logger, logging.INFO, "structure_form_queued", project_id=project.project_id, structure_id=payload["structure_id"])
                return {"location": with_lang("/ui/pending?flash=queued", lang)}
            record = StructureService(database).upsert_structure(build_structure_write(payload))
    except (StructureValidationError, ValueError) as exc:
        log_event(
            logger,
            logging.WARNING,
            "structure_form_validation_error",
            project_id=project.project_id,
            structure_id=payload["structure_id"],
            error=str(exc),
        )
        status = HTTPStatus.BAD_REQUEST
        html = render_structure_form_page(
            project,
            "edit" if is_edit else "new",
            merge_form_data(structure_form_defaults(project), form_data),
            str(exc),
            lang,
        )
        return {"status": status, "html": html}
    log_event(logger, logging.INFO, "structure_form_saved", project_id=project.project_id, structure_id=record.structure_id)
    return {"location": with_lang(f"/ui/structures/{record.structure_id}", lang)}


def submit_global_hypothesis_form(project: ProjectConfig, form_data: dict[str, str], is_edit: bool, lang: str) -> dict[str, Any]:
    payload = global_hypothesis_payload_from_form(project.project_id, form_data)
    log_event(
        logger,
        logging.INFO,
        "global_hypothesis_form_submit",
        project_id=project.project_id,
        hypothesis_id=payload["hypothesis_id"],
        mode="edit" if is_edit else "new",
        write_mode=project.write_mode,
    )
    try:
        with open_database(project.database_path) as database:
            if project.write_mode == "confirm":
                PendingChangeService(database).create_pending_change(
                    project.project_id,
                    "global_hypothesis",
                    payload["hypothesis_id"],
                    "upsert_global_hypothesis",
                    payload,
                    created_by=str(payload["created_by"]),
                )
                log_event(
                    logger,
                    logging.INFO,
                    "global_hypothesis_form_queued",
                    project_id=project.project_id,
                    hypothesis_id=payload["hypothesis_id"],
                )
                return {"location": with_lang("/ui/pending?flash=queued", lang)}
            record = GlobalHypothesisService(database).upsert_hypothesis(build_global_hypothesis_write(payload))
    except (GlobalHypothesisValidationError, ValueError) as exc:
        log_event(
            logger,
            logging.WARNING,
            "global_hypothesis_form_validation_error",
            project_id=project.project_id,
            hypothesis_id=payload["hypothesis_id"],
            error=str(exc),
        )
        status = HTTPStatus.BAD_REQUEST
        html = render_global_hypothesis_form_page(
            project,
            "edit" if is_edit else "new",
            merge_form_data(global_hypothesis_form_defaults(project), form_data),
            str(exc),
            lang,
        )
        return {"status": status, "html": html}
    log_event(logger, logging.INFO, "global_hypothesis_form_saved", project_id=project.project_id, hypothesis_id=record.hypothesis_id)
    return {"location": with_lang(f"/ui/global-hypotheses/{record.hypothesis_id}", lang)}


def function_payload_from_form(project_id: str, form_data: dict[str, str]) -> dict[str, Any]:
    return {
        "project_id": project_id,
        "binary_id": form_data.get("binary_id", "").strip(),
        "function_id": form_data.get("function_id", "").strip(),
        "address": form_data.get("address", "").strip(),
        "raw_name": form_data.get("raw_name", "").strip(),
        "current_name": form_data.get("current_name", "").strip(),
        "summary": form_data.get("summary", "").strip(),
        "behavior_description": form_data.get("behavior_description", "").strip(),
        "tags": parse_multiline_items(form_data.get("tags", "")),
        "used_apis": parse_multiline_items(form_data.get("used_apis", "")),
        "strings": parse_multiline_items(form_data.get("strings", "")),
        "constants": parse_multiline_items(form_data.get("constants", "")),
        "observed_facts": build_fact_payloads(form_data.get("observed_facts", "")),
        "confidence": parse_optional_float(form_data.get("confidence", "")),
        "source_origin": "ui",
        "created_by": "ui",
        "updated_by": "ui",
        "allow_conflict": form_data.get("allow_conflict") == "true",
    }


def structure_payload_from_form(project_id: str, form_data: dict[str, str]) -> dict[str, Any]:
    return {
        "project_id": project_id,
        "binary_id": form_data.get("binary_id", "").strip(),
        "structure_id": form_data.get("structure_id", "").strip(),
        "raw_name": form_data.get("raw_name", "").strip(),
        "current_name": form_data.get("current_name", "").strip(),
        "summary": form_data.get("summary", "").strip(),
        "fields": parse_structure_fields(form_data.get("fields", "")),
        "tags": parse_multiline_items(form_data.get("tags", "")),
        "observed_facts": build_fact_payloads(form_data.get("observed_facts", "")),
        "source_origin": "ui",
        "created_by": "ui",
        "updated_by": "ui",
    }


def global_hypothesis_payload_from_form(project_id: str, form_data: dict[str, str]) -> dict[str, Any]:
    binary_id = form_data.get("binary_id", "").strip()
    return {
        "project_id": project_id,
        "hypothesis_id": form_data.get("hypothesis_id", "").strip(),
        "title": form_data.get("title", "").strip(),
        "statement": form_data.get("statement", "").strip(),
        "status": form_data.get("status", "new").strip() or "new",
        "binary_id": binary_id or None,
        "confidence": parse_optional_float(form_data.get("confidence", "")),
        "tags": parse_multiline_items(form_data.get("tags", "")),
        "observed_facts": build_fact_payloads(form_data.get("observed_facts", "")),
        "source_origin": "ui",
        "created_by": "ui",
        "updated_by": "ui",
    }


def build_function_write(payload: dict[str, Any]) -> FunctionWrite:
    confidence = payload["confidence"]
    return FunctionWrite(
        project_id=str(payload["project_id"]),
        binary_id=str(payload["binary_id"]),
        function_id=str(payload["function_id"]),
        address=str(payload["address"]),
        raw_name=str(payload["raw_name"]),
        current_name=str(payload["current_name"]),
        summary=str(payload["summary"]),
        behavior_description=str(payload["behavior_description"]),
        used_apis=[str(item) for item in payload["used_apis"]],
        strings=[str(item) for item in payload["strings"]],
        constants=[str(item) for item in payload["constants"]],
        confidence=None if confidence is None else float(confidence),
        tags=[str(item) for item in payload["tags"]],
        observed_facts=[
            ObservedFact(fact=str(item["fact"]), source_origin=str(item.get("source_origin", "ui")))
            for item in payload["observed_facts"]
        ],
        hypotheses=[
            HypothesisItem(statement=str(item["statement"]), source_origin=str(item.get("source_origin", "ui")))
            for item in payload.get("hypotheses", [])
        ],
        source_origin=str(payload["source_origin"]),
        created_by=str(payload["created_by"]),
        updated_by=str(payload["updated_by"]),
        allow_conflict=bool(payload["allow_conflict"]),
    )


def build_structure_write(payload: dict[str, Any]) -> StructureWrite:
    return StructureWrite(
        project_id=str(payload["project_id"]),
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
                size=item["size"],
                comment=str(item["comment"]),
            )
            for item in payload["fields"]
        ],
        tags=[str(item) for item in payload["tags"]],
        observed_facts=[
            ObservedFact(fact=str(item["fact"]), source_origin=str(item.get("source_origin", "ui")))
            for item in payload["observed_facts"]
        ],
        source_origin=str(payload["source_origin"]),
        created_by=str(payload["created_by"]),
        updated_by=str(payload["updated_by"]),
    )


def build_global_hypothesis_write(payload: dict[str, Any]) -> GlobalHypothesisWrite:
    confidence = payload["confidence"]
    return GlobalHypothesisWrite(
        project_id=str(payload["project_id"]),
        hypothesis_id=str(payload["hypothesis_id"]),
        title=str(payload["title"]),
        statement=str(payload["statement"]),
        status=HypothesisStatus(str(payload["status"])),
        confidence=None if confidence is None else float(confidence),
        binary_id=None if payload["binary_id"] is None else str(payload["binary_id"]),
        tags=[str(item) for item in payload["tags"]],
        observed_facts=[
            ObservedFact(fact=str(item["fact"]), source_origin=str(item.get("source_origin", "ui")))
            for item in payload["observed_facts"]
        ],
        source_origin=str(payload["source_origin"]),
        created_by=str(payload["created_by"]),
        updated_by=str(payload["updated_by"]),
    )


def parse_multiline_items(raw_value: str) -> list[str]:
    return [line.strip() for line in raw_value.splitlines() if line.strip()]


def parse_structure_fields(raw_value: str) -> list[dict[str, Any]]:
    rows = []
    for line in raw_value.splitlines():
        text = line.strip()
        if not text:
            continue
        parts = [segment.strip() for segment in text.split("|")]
        while len(parts) < 5:
            parts.append("")
        name, offset, data_type, size_text, comment = parts[:5]
        size = None if not size_text else int(size_text)
        rows.append(
            {
                "name": name,
                "offset": offset,
                "data_type": data_type,
                "size": size,
                "comment": comment,
            }
        )
    return rows


def build_fact_payloads(raw_value: str) -> list[dict[str, str]]:
    return [{"fact": line, "source_origin": "ui"} for line in parse_multiline_items(raw_value)]


def parse_optional_float(raw_value: str) -> float | None:
    text = raw_value.strip()
    if not text:
        return None
    return float(text)


def merge_form_data(defaults: dict[str, str], values: dict[str, str]) -> dict[str, str]:
    merged = defaults.copy()
    merged.update(values)
    return merged


def list_entity_versions(project_id: str, database: Database, entity_type: str, entity_id: str) -> list[dict[str, Any]]:
    rows = database.connection.execute(
        """
        SELECT version_number, snapshot_json, created_at, created_by
        FROM entity_versions
        WHERE project_id = ? AND entity_type = ? AND entity_id = ?
        ORDER BY version_number DESC
        """,
        (project_id, entity_type, entity_id),
    ).fetchall()
    return [
        {
            "version_number": int(row["version_number"]),
            "snapshot": json.loads(str(row["snapshot_json"])),
            "created_at": str(row["created_at"]),
            "created_by": str(row["created_by"]),
        }
        for row in rows
    ]


def list_audit_entries(
    project_id: str,
    database: Database,
    entity_type: str | None,
    entity_id: str | None,
    limit: int = 100,
) -> list[dict[str, str]]:
    filters = ["project_id = ?"]
    params: list[Any] = [project_id]
    if entity_type:
        filters.append("entity_type = ?")
        params.append(entity_type)
    if entity_id:
        filters.append("entity_id = ?")
        params.append(entity_id)
    params.append(limit)
    rows = database.connection.execute(
        f"""
        SELECT entity_type, entity_id, action, actor_type, actor_id, source_origin, summary, created_at
        FROM audit_log
        WHERE {' AND '.join(filters)}
        ORDER BY created_at DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    return [
        {
            "entity_type": str(row["entity_type"]),
            "entity_id": str(row["entity_id"]),
            "action": str(row["action"]),
            "actor_type": str(row["actor_type"]),
            "actor_id": str(row["actor_id"]),
            "source_origin": str(row["source_origin"]),
            "summary": str(row["summary"]),
            "created_at": str(row["created_at"]),
        }
        for row in rows
    ]
