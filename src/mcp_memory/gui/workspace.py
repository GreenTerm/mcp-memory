from __future__ import annotations

import json
import logging
from html import escape
from http import HTTPStatus
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
    ProjectService,
    RelationService,
    SearchQuery,
    SearchService,
    StructureService,
    StructureValidationError,
)
from mcp_memory.storage import Database, open_database


logger = get_logger("ui")

from .render import (
    badge,
    empty_state,
    flash_banner,
    html_page,
    key_value_grid,
    load_asset_text,
    section,
    shell_command,
    table,
)
from .i18n import language_switcher, localize_markup, resolve_language, translate_text, with_lang


def workspace_asset_response(path: str) -> tuple[str, bytes] | None:
    if path == "/ui/assets/app.css":
        return ("text/css; charset=utf-8", load_asset_text("app.css").encode("utf-8"))
    return None


def render_workspace_response(project: ProjectConfig, registry: ProjectRegistry, raw_path: str) -> tuple[HTTPStatus, str] | None:
    path, _, query_string = raw_path.partition("?")
    query = parse_qs(query_string)
    lang = resolve_language(query.get("lang", ["en"])[0])

    if path in ("/ui", "/ui/"):
        return (HTTPStatus.OK, render_workspace_dashboard(project, lang))
    if path == "/ui/search":
        return (HTTPStatus.OK, render_search_page(project, query, raw_path, lang))
    if path == "/ui/pending":
        return (HTTPStatus.OK, render_pending_page(project, query, raw_path, lang))
    if path == "/ui/audit":
        return (HTTPStatus.OK, render_audit_page(project, query, raw_path, lang))
    if path == "/ui/settings":
        return (HTTPStatus.OK, render_project_settings_page(project, raw_path, project_settings_form_defaults(project), None, False, lang))
    if path == "/ui/functions/new":
        return (HTTPStatus.OK, render_function_form_page(project, "new", function_form_defaults(project), None, lang))
    if path.startswith("/ui/functions/") and path.endswith("/history"):
        return render_function_history_response(project, path, lang)
    if path.startswith("/ui/functions/") and path.endswith("/edit"):
        return render_function_edit_response(project, path, lang)
    if path.startswith("/ui/functions/"):
        return render_function_response(project, path, lang)
    if path == "/ui/structures/new":
        return (HTTPStatus.OK, render_structure_form_page(project, "new", structure_form_defaults(project), None, lang))
    if path.startswith("/ui/structures/") and path.endswith("/history"):
        return render_structure_history_response(project, path.rsplit("/", 2)[-2], lang)
    if path.startswith("/ui/structures/") and path.endswith("/edit"):
        return render_structure_edit_response(project, path, lang)
    if path.startswith("/ui/structures/"):
        return render_structure_response(project, path.rsplit("/", 1)[-1], lang)
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
        return render_global_hypothesis_response(project, path.rsplit("/", 1)[-1], lang)
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
    if path.startswith("/ui/pending/") and path.endswith("/confirm"):
        pending_change_id = path[: -len("/confirm")].rsplit("/", 1)[-1]
        with open_database(project.database_path) as database:
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
            PendingChangeService(database).reject_change(
                project.project_id,
                pending_change_id,
                rejected_by=form_data.get("rejected_by", "ui"),
            )
        log_event(logger, logging.WARNING, "pending_rejected", project_id=project.project_id, pending_change_id=pending_change_id)
        return {"location": with_lang("/ui/pending?flash=rejected", lang)}

    if path == "/ui/settings":
        return submit_project_settings_form(project, registry, form_data, lang)

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
        function_count = len(FunctionService(database).list_project_functions(project.project_id))
        structure_count = len(StructureService(database).list_project_structures(project.project_id))
        hypothesis_count = len(GlobalHypothesisService(database).list_hypotheses(project.project_id))
        pending_count = len(PendingChangeService(database).list_pending_changes(project.project_id))

    overview = key_value_grid(
        [
            ("Project", project.display_name),
            ("Project ID", project.project_id),
            ("Write Mode", project.write_mode),
            ("MCP", f"http://{project.mcp_host}:{project.mcp_port}/mcp"),
        ]
    )
    connection_note = (
        "<div class=\"panel-note\">"
        f"<p>{escape(translate_text(lang, 'Use the MCP endpoint as the primary connection target for agents.'))}</p>"
        f"{shell_command(f'http://{project.mcp_host}:{project.mcp_port}/mcp')}"
        f"<p>{escape(translate_text(lang, 'Workspace HTTP remains available at'))} {escape(project.http_host)}:{escape(str(project.http_port))}</p>"
        "</div>"
    )
    body = (
        "<main class=\"workspace-shell\">"
        f"{workspace_header(project, 'Workspace Dashboard', '/ui/', lang)}"
        f"{section('Project Snapshot', overview + connection_note + metric_grid(function_count, structure_count, hypothesis_count, pending_count), 'A calm overview of what is already in this workspace.')}"
        f"{section('Jump Back In', search_form('', '', '', '') + quick_links(project), 'Start broad, then narrow down only when you need to.')}"
        "</main>"
    )
    html = html_page(f"{project.display_name} Workspace", body, "/ui/assets/app.css", page_class="warm-lab workspace-page", html_lang=lang)
    return localize_markup(html, lang)


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
        f"{section('Search Workspace', search_form(q, entity_type, binary_id, tag), 'One search box, then small filters only when they help.')}"
        f"{results_html}"
        "</main>"
    )
    html = html_page(f"{project.display_name} Search", body, "/ui/assets/app.css", page_class="warm-lab workspace-page", html_lang=lang)
    return localize_markup(html, lang)


def render_function_response(project: ProjectConfig, path: str, lang: str) -> tuple[HTTPStatus, str]:
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

    signals = function.tags + function.used_apis + function.strings + function.constants
    summary_html = f"<p class=\"body-copy\">{escape(function.summary)}</p><p class=\"body-copy\">{escape(function.behavior_description)}</p>"
    metadata_html = key_value_grid(
        [
            ("Address", function.address),
            ("Binary", function.binary_id),
            ("Source", function.source_origin),
        ]
    )
    timeline_html = entity_timeline_links(f"/ui/functions/{function.binary_id}/{function.function_id}/history", "/ui/audit")
    actions_html = entity_action_links(f"/ui/functions/{function.binary_id}/{function.function_id}/edit")
    body = (
        "<main class=\"workspace-shell\">"
        f"{workspace_header(project, function.current_name, path, lang)}"
        "<article class=\"entity-hero\">"
        f"{render_header_meta([badge('Function', 'accent'), badge(function.binary_id, 'neutral')])}"
        f"<h2>{escape(function.current_name)}</h2>"
        f"<p class=\"entity-subtitle\">{escape(function.raw_name)} - {escape(function.address)}</p>"
        "</article>"
        f"{section('Actions', actions_html)}"
        f"{section('Timeline', timeline_html, 'Use these pages when you need to understand how a record changed over time.')}"
        f"{section('Summary', summary_html)}"
        f"{section('Key Metadata', metadata_html)}"
        f"{section('Signals', render_chip_list(signals))}"
        f"{section('Observed Facts', render_fact_list(function.observed_facts))}"
        f"{section('Hypotheses', render_hypothesis_list(function.hypotheses))}"
        f"{section('Evidence', render_evidence_list(evidence))}"
        f"{section('Relations', relation_html)}"
        "</main>"
    )
    html = html_page(f"{function.current_name} - {project.display_name}", body, "/ui/assets/app.css", page_class="warm-lab workspace-page", html_lang=lang)
    html = localize_markup(html, lang)
    return (HTTPStatus.OK, html)


def render_structure_response(project: ProjectConfig, structure_id: str, lang: str) -> tuple[HTTPStatus, str]:
    with open_database(project.database_path) as database:
        structure = StructureService(database).get_structure(project.project_id, structure_id)
        if structure is None:
            return (HTTPStatus.NOT_FOUND, render_not_found(project, "Structure not found.", lang))
        evidence = EvidenceService(database).list_evidence(project.project_id, "structure", structure.structure_id)
        relations = RelationService(database).list_relations(project.project_id, "structure", structure.structure_id)
        relation_html = render_relation_list(project, database, relations, "structure", structure.structure_id)

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
    timeline_html = entity_timeline_links(f"/ui/structures/{structure.structure_id}/history", "/ui/audit")
    actions_html = entity_action_links(f"/ui/structures/{structure.structure_id}/edit")
    body = (
        "<main class=\"workspace-shell\">"
        f"{workspace_header(project, structure.current_name, f'/ui/structures/{structure.structure_id}', lang)}"
        "<article class=\"entity-hero\">"
        f"{render_header_meta([badge('Structure', 'accent'), badge(structure.binary_id, 'neutral')])}"
        f"<h2>{escape(structure.current_name)}</h2>"
        f"<p class=\"entity-subtitle\">{escape(structure.raw_name)}</p>"
        "</article>"
        f"{section('Actions', actions_html)}"
        f"{section('Timeline', timeline_html, 'Use these pages when you need to understand how a record changed over time.')}"
        f"{section('Summary', summary_html)}"
        f"{section('Fields', fields_table)}"
        f"{section('Observed Facts', render_fact_list(structure.observed_facts))}"
        f"{section('Hypotheses', render_hypothesis_list(structure.hypotheses))}"
        f"{section('Evidence', render_evidence_list(evidence))}"
        f"{section('Relations', relation_html)}"
        "</main>"
    )
    html = html_page(f"{structure.current_name} - {project.display_name}", body, "/ui/assets/app.css", page_class="warm-lab workspace-page", html_lang=lang)
    html = localize_markup(html, lang)
    return (HTTPStatus.OK, html)


def render_global_hypothesis_response(project: ProjectConfig, hypothesis_id: str, lang: str) -> tuple[HTTPStatus, str]:
    with open_database(project.database_path) as database:
        hypothesis = GlobalHypothesisService(database).get_hypothesis(project.project_id, hypothesis_id)
        if hypothesis is None:
            return (HTTPStatus.NOT_FOUND, render_not_found(project, "Global hypothesis not found.", lang))
        evidence = EvidenceService(database).list_evidence(project.project_id, "global_hypothesis", hypothesis.hypothesis_id)
        relations = RelationService(database).list_relations(project.project_id, "global_hypothesis", hypothesis.hypothesis_id)
        relation_html = render_relation_list(project, database, relations, "global_hypothesis", hypothesis.hypothesis_id)

    confidence = "Unspecified" if hypothesis.confidence is None else f"{hypothesis.confidence:.2f}"
    statement_html = f"<p class=\"body-copy\">{escape(hypothesis.statement)}</p>"
    status_html = key_value_grid(
        [
            ("Status", hypothesis.status.value),
            ("Confidence", confidence),
            ("Binary", hypothesis.binary_id or "Any"),
        ]
    )
    timeline_html = entity_timeline_links(f"/ui/global-hypotheses/{hypothesis.hypothesis_id}/history", "/ui/audit")
    actions_html = entity_action_links(f"/ui/global-hypotheses/{hypothesis.hypothesis_id}/edit")
    body = (
        "<main class=\"workspace-shell\">"
        f"{workspace_header(project, hypothesis.title, f'/ui/global-hypotheses/{hypothesis.hypothesis_id}', lang)}"
        "<article class=\"entity-hero\">"
        f"{render_header_meta([badge('Global Hypothesis', 'accent'), badge(hypothesis.status.value.title(), hypothesis_tone(hypothesis.status.value))])}"
        f"<h2>{escape(hypothesis.title)}</h2>"
        "</article>"
        f"{section('Actions', actions_html)}"
        f"{section('Timeline', timeline_html, 'Use these pages when you need to understand how a record changed over time.')}"
        f"{section('Statement', statement_html)}"
        f"{section('Status', status_html)}"
        f"{section('Supporting Facts', render_fact_list(hypothesis.observed_facts))}"
        f"{section('Evidence', render_evidence_list(evidence))}"
        f"{section('Relations', relation_html)}"
        "</main>"
    )
    html = html_page(f"{hypothesis.title} - {project.display_name}", body, "/ui/assets/app.css", page_class="warm-lab workspace-page", html_lang=lang)
    html = localize_markup(html, lang)
    return (HTTPStatus.OK, html)


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
    html = html_page(f"{project.display_name} Pending Changes", body, "/ui/assets/app.css", page_class="warm-lab workspace-page", html_lang=lang)
    return localize_markup(html, lang)


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
    html = html_page(f"{project.display_name} Audit Trail", body, "/ui/assets/app.css", page_class="warm-lab workspace-page", html_lang=lang)
    return localize_markup(html, lang)


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
    html = html_page(f"{entity_label} History - {project.display_name}", body, "/ui/assets/app.css", page_class="warm-lab workspace-page", html_lang=lang)
    return localize_markup(html, lang)


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
    html = html_page(f"{title} - {project.display_name}", body, "/ui/assets/app.css", page_class="warm-lab workspace-page", html_lang=lang)
    return localize_markup(html, lang)


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
    html = html_page(f"{title} - {project.display_name}", body, "/ui/assets/app.css", page_class="warm-lab workspace-page", html_lang=lang)
    return localize_markup(html, lang)


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
    html = html_page(f"{title} - {project.display_name}", body, "/ui/assets/app.css", page_class="warm-lab workspace-page", html_lang=lang)
    return localize_markup(html, lang)


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
        f"{section('Project Settings', render_project_settings_form(form_data), 'Adjust the project identity, write mode, and network endpoints without leaving the workspace.')}"
        "</main>"
    )
    html = html_page(f"Project Settings - {project.display_name}", body, "/ui/assets/app.css", page_class="warm-lab workspace-page", html_lang=lang)
    return localize_markup(html, lang)


def render_project_settings_form(form_data: dict[str, str]) -> str:
    return (
        '<form class="search-form" method="post" action="/ui/settings">'
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
        '<a class="button button-secondary" href="/ui/">Cancel</a>'
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
    html = html_page(f"{project.display_name} Not Found", body, "/ui/assets/app.css", page_class="warm-lab workspace-page", html_lang=lang)
    return localize_markup(html, lang)


def workspace_header(project: ProjectConfig, title: str, current_url: str, lang: str) -> str:
    tone = "warning" if project.write_mode == "confirm" else "success"
    return (
        "<header class=\"workspace-header\">"
        "<div class=\"workspace-brand\">"
        "<a class=\"brand-mark\" href=\"/ui/\">Warm Lab</a>"
        f"<h1>{escape(title)}</h1>"
        f"<p class=\"workspace-subtitle\">{escape(project.display_name)} - {escape(project.project_id)}</p>"
        "</div>"
        "<nav class=\"workspace-nav\">"
        "<a href=\"/ui/\">Dashboard</a>"
        "<a href=\"/ui/search\">Search</a>"
        "<a href=\"/ui/pending\">Pending</a>"
        "<a href=\"/ui/audit\">Audit</a>"
        "<a href=\"/ui/settings\">Settings</a>"
        f"{badge(project.write_mode.title(), tone)}"
        f"{language_switcher(current_url, lang)}"
        "</nav>"
        "</header>"
    )


def metric_grid(function_count: int, structure_count: int, hypothesis_count: int, pending_count: int) -> str:
    return (
        "<div class=\"metric-grid\">"
        f"{metric_card('Functions', function_count, 'Searchable function records in this workspace.')}"
        f"{metric_card('Structures', structure_count, 'Recovered layouts and type notes.')}"
        f"{metric_card('Hypotheses', hypothesis_count, 'Global analysis hypotheses.')}"
        f"{metric_card('Pending', pending_count, 'Changes waiting for confirmation.')}"
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


def search_form(q: str, entity_type: str, binary_id: str, tag: str) -> str:
    return (
        "<form class=\"search-form\" method=\"get\" action=\"/ui/search\">"
        f"<input type=\"text\" name=\"q\" value=\"{escape(q)}\" placeholder=\"Search for functions, tags, or hypotheses\">"
        "<div class=\"search-form-grid\">"
        f"<input type=\"text\" name=\"binary_id\" value=\"{escape(binary_id)}\" placeholder=\"binary_id (optional)\">"
        f"<input type=\"text\" name=\"tag\" value=\"{escape(tag)}\" placeholder=\"tag (optional)\">"
        f"<select name=\"entity_type\">{entity_type_options(entity_type)}</select>"
        "</div>"
        "<div class=\"search-form-actions\">"
        "<button class=\"button button-primary\" type=\"submit\">Search Workspace</button>"
        "<a class=\"button button-secondary\" href=\"/ui/search\">Reset</a>"
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


def parse_settings_port(raw_value: str, label: str) -> int:
    value = raw_value.strip()
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{label} must be a valid integer.") from exc


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
