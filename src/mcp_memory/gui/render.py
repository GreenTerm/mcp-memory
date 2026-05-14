from __future__ import annotations

from html import escape
from pathlib import Path


ASSETS_DIR = Path(__file__).resolve().parent / "assets"


def load_asset_text(name: str) -> str:
    return (ASSETS_DIR / name).read_text(encoding="utf-8")


def html_page(
    title: str,
    body: str,
    stylesheet_href: str,
    page_class: str = "",
    html_lang: str = "en",
    script_href: str | None = None,
    theme: str = "dark",
) -> str:
    page_class_attr = f' class="{escape(page_class)}"' if page_class else ""
    script = ""
    if script_href is None and stylesheet_href.endswith("/app.css"):
        script_href = stylesheet_href[: -len("app.css")] + "ui.js"
    if script_href:
        script = f"<script src=\"{escape(script_href)}\" defer></script>"
    return (
        "<!DOCTYPE html>"
        f"<html lang=\"{escape(html_lang)}\" data-theme=\"{escape(theme)}\">"
        "<head>"
        "<meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>{escape(title)}</title>"
        f"<link rel=\"stylesheet\" href=\"{escape(stylesheet_href)}\">"
        f"{script}"
        "</head>"
        f"<body{page_class_attr}>"
        f"{body}"
        "</body>"
        "</html>"
    )


def shell_command(command: str) -> str:
    return f"<pre class=\"shell-command\"><code>{escape(command)}</code></pre>"


def flash_banner(message: str, tone: str = "info") -> str:
    return f"<div class=\"flash flash-{escape(tone)}\">{escape(message)}</div>"


def badge(label: str, tone: str = "neutral") -> str:
    return f"<span class=\"badge badge-{escape(tone)}\">{escape(label)}</span>"


def empty_state(title: str, body: str) -> str:
    return (
        "<section class=\"empty-state\">"
        "<div class=\"empty-state-body\">"
        f"<h2 class=\"empty-state-title\">{escape(title)}</h2>"
        f"<p class=\"empty-state-copy\">{escape(body)}</p>"
        "</div>"
        "</section>"
    )


def inner_empty_state(title: str, body: str) -> str:
    return (
        "<div class=\"inner-empty-state\">"
        f"<h3>{escape(title)}</h3>"
        f"<p>{escape(body)}</p>"
        "</div>"
    )


def app_shell(
    sidebar: str,
    topbar: str,
    breadcrumbs: str,
    main_content: str,
    right_panel: str = "",
) -> str:
    right_panel_html = f"<aside class=\"app-right-panel\">{right_panel}</aside>" if right_panel else ""
    return (
        "<a class=\"skip-link\" href=\"#main-content\">Skip to content</a>"
        "<div class=\"app-shell\">"
        f"{sidebar}"
        "<main id=\"main-content\" class=\"app-workspace\" tabindex=\"-1\">"
        f"{topbar}"
        f"{breadcrumbs}"
        f"{main_content}"
        "</main>"
        f"{right_panel_html}"
        "</div>"
    )


def sidebar_nav(
    items: list[tuple[str, str, str] | tuple[str, str, str, str]],
    active_href: str = "",
    brand_href: str = "/ui/",
    footer_html: str = "",
    brand_label: str = "mcp-memory",
) -> str:
    sections: list[str] = []
    links: list[str] = []
    current_group = ""
    group_labels = {
        "home": "Home",
        "workspace": "Knowledge",
        "project": "Operations",
    }
    active_path = active_href.split("?", 1)[0].rstrip("/") or "/"
    for item in items:
        label, href, group = item[:3]
        icon_label = item[3] if len(item) > 3 else label
        if group != current_group:
            if links:
                sections.append(
                    f"<section class=\"sidebar-section\" data-nav-section=\"{escape(current_group)}\">{''.join(links)}</section>"
                )
                links = []
            current_group = group
            group_label = group_labels.get(group, group.replace("_", " ").title())
            links.append(f"<p class=\"sidebar-section-title\">{escape(group_label)}</p>")
        href_path = href.split("?", 1)[0].rstrip("/") or "/"
        active_class = (
            " is-active"
            if href_path == active_path or (href_path not in {"/", "/ui"} and active_path.startswith(href_path + "/"))
            else ""
        )
        links.append(
            f"<a class=\"sidebar-link{active_class}\" href=\"{escape(href, quote=True)}\" data-nav-group=\"{escape(group)}\" title=\"{escape(label, quote=True)}\" aria-label=\"{escape(label, quote=True)}\">"
            f"{sidebar_icon(icon_label)}"
            f"<span class=\"app-sidebar-label\">{escape(label)}</span>"
            "</a>"
        )
    if links:
        sections.append(f"<section class=\"sidebar-section\" data-nav-section=\"{escape(current_group)}\">{''.join(links)}</section>")
    return (
        "<aside class=\"app-sidebar\">"
        "<div class=\"sidebar-head\">"
        f"<a class=\"brand-mark\" href=\"{escape(brand_href, quote=True)}\">{escape(brand_label)}</a>"
        "<button class=\"button button-secondary sidebar-toggle\" type=\"button\" data-sidebar-toggle aria-expanded=\"true\" aria-label=\"Toggle sidebar\" title=\"Toggle sidebar\">"
        f"{sidebar_icon('Toggle sidebar')}"
        "</button>"
        "</div>"
        f"<nav class=\"sidebar-nav\" aria-label=\"Workspace navigation\">{''.join(sections)}</nav>"
        f"{footer_html}"
        "</aside>"
    )


def icon_span(label: str, class_name: str) -> str:
    paths = {
        "Projects": "<path d=\"M4 7h6l2 2h8v9a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2z\"/><path d=\"M2 11h20\"/>",
        "Binaries": "<rect x=\"4\" y=\"4\" width=\"16\" height=\"16\" rx=\"3\"/><path d=\"M9 4v3M15 4v3M9 17v3M15 17v3M4 9h3M17 9h3M4 15h3M17 15h3\"/>",
        "Functions": "<path d=\"M9 4h8\"/><path d=\"M7 20c2.5-4.5 2.5-11.5 0-16\"/><path d=\"M11 10l6 6M17 10l-6 6\"/>",
        "Structures": "<path d=\"M5 5h14v5H5zM5 14h14v5H5z\"/><path d=\"M9 5v14\"/>",
        "Hypotheses": "<path d=\"M12 3a6 6 0 0 0-3 11v3h6v-3a6 6 0 0 0-3-11z\"/><path d=\"M9 21h6\"/>",
        "Entities": "<path d=\"M4 5h16v14H4z\"/><path d=\"M8 9h8M8 13h8\"/><path d=\"M8 17h5\"/>",
        "Entity Types": "<path d=\"M4 5h16v14H4z\"/><path d=\"M8 9h8M8 13h8\"/><path d=\"M8 17h5\"/>",
        "Records": "<path d=\"M7 3h8l4 4v14H7z\"/><path d=\"M15 3v5h5\"/><path d=\"M10 12h7M10 16h7\"/>",
        "Schema": "<path d=\"M5 5h6v6H5zM13 5h6v6h-6zM5 13h6v6H5zM13 13h6v6h-6z\"/>",
        "Search": "<circle cx=\"10.5\" cy=\"10.5\" r=\"5.5\"/><path d=\"M15 15l5 5\"/>",
        "Graph": "<circle cx=\"6\" cy=\"7\" r=\"3\"/><circle cx=\"18\" cy=\"7\" r=\"3\"/><circle cx=\"12\" cy=\"18\" r=\"3\"/><path d=\"M9 8h6M8 10l3 5M16 10l-3 5\"/>",
        "Evidence": "<path d=\"M7 4h10a2 2 0 0 1 2 2v14H5V6a2 2 0 0 1 2-2z\"/><path d=\"M8 9h8M8 13h8\"/><path d=\"M9 17h6\"/>",
        "Import/Export": "<path d=\"M12 3v12\"/><path d=\"M8 7l4-4 4 4\"/><path d=\"M8 17l4 4 4-4\"/><path d=\"M4 12h16\"/>",
        "Backups": "<path d=\"M5 6h14v14H5z\"/><path d=\"M8 3h8v3H8z\"/><path d=\"M8 11h8M8 15h6\"/>",
        "Settings": "<circle cx=\"12\" cy=\"12\" r=\"3\"/><path d=\"M19 12a7 7 0 0 0-.1-1l2-1.5-2-3.4-2.4 1a7 7 0 0 0-1.8-1L14.4 3h-4.8l-.3 3.1a7 7 0 0 0-1.8 1l-2.4-1-2 3.4L5.1 11a7 7 0 0 0 0 2l-2 1.5 2 3.4 2.4-1a7 7 0 0 0 1.8 1l.3 3.1h4.8l.3-3.1a7 7 0 0 0 1.8-1l2.4 1 2-3.4-2-1.5a7 7 0 0 0 .1-1z\"/>",
        "New Function": "<path d=\"M9 4h8\"/><path d=\"M7 20c2.5-4.5 2.5-11.5 0-16\"/><path d=\"M11 10l6 6M17 10l-6 6\"/><path d=\"M18 17v4M16 19h4\"/>",
        "New Structure": "<path d=\"M5 5h14v5H5zM5 14h14v5H5z\"/><path d=\"M9 5v14\"/><path d=\"M18 17v4M16 19h4\"/>",
        "New Hypothesis": "<path d=\"M12 3a6 6 0 0 0-3 11v3h6v-3a6 6 0 0 0-3-11z\"/><path d=\"M9 21h6\"/><path d=\"M18 17v4M16 19h4\"/>",
        "Add Field": "<path d=\"M4 5h16v14H4z\"/><path d=\"M8 9h8M8 13h8\"/><path d=\"M12 16v4M10 18h4\"/>",
        "Add Relation Type": "<circle cx=\"6\" cy=\"7\" r=\"3\"/><circle cx=\"18\" cy=\"7\" r=\"3\"/><path d=\"M9 7h6\"/><path d=\"M12 14v6M9 17h6\"/>",
        "Edit": "<path d=\"M4 20h4l10-10-4-4L4 16v4z\"/><path d=\"M13 7l4 4\"/>",
        "Delete": "<path d=\"M5 7h14\"/><path d=\"M10 11v6M14 11v6\"/><path d=\"M8 7l1-3h6l1 3\"/><path d=\"M7 7l1 13h8l1-13\"/>",
        "Toggle sidebar": "<path d=\"M4 5h16v14H4z\"/><path d=\"M9 5v14\"/><path d=\"M13 10l3 2-3 2\"/>",
    }
    path = paths.get(label, "<path d=\"M5 12h14\"/><path d=\"M12 5v14\"/>")
    return (
        f"<span class=\"{escape(class_name)}\" aria-hidden=\"true\">"
        "<svg viewBox=\"0 0 24 24\" focusable=\"false\">"
        f"{path}"
        "</svg>"
        "</span>"
    )


def sidebar_icon(label: str) -> str:
    return icon_span(label, "sidebar-icon")


def top_search(action: str, query: str = "", lang: str = "en", extra_html: str = "") -> str:
    hidden_lang = f"<input type=\"hidden\" name=\"lang\" value=\"{escape(lang, quote=True)}\">"
    return (
        "<header class=\"app-topbar\">"
        f"<form class=\"top-search\" method=\"get\" action=\"{escape(action, quote=True)}\">"
        f"{hidden_lang}"
        f"<input type=\"search\" name=\"q\" value=\"{escape(query, quote=True)}\" placeholder=\"Search workspace\" aria-label=\"Search workspace\">"
        "</form>"
        "<div class=\"topbar-actions\">"
        "<button class=\"button button-secondary\" type=\"button\" data-theme-toggle aria-pressed=\"false\" aria-label=\"Toggle color theme\" title=\"Theme\">Theme</button>"
        f"{extra_html}"
        "</div>"
        "</header>"
    )


def breadcrumbs(items: list[tuple[str, str | None]]) -> str:
    rendered = []
    for label, href in items:
        if href:
            rendered.append(f"<li><a class=\"breadcrumb-link\" href=\"{escape(href, quote=True)}\">{escape(label)}</a></li>")
        else:
            rendered.append(f"<li aria-current=\"page\">{escape(label)}</li>")
    return f"<nav aria-label=\"Breadcrumbs\"><ol class=\"breadcrumb-list\">{''.join(rendered)}</ol></nav>"


def entity_type_badge(entity_type: str) -> str:
    return badge(entity_type.replace("_", " ").title(), "accent")


def confidence_badge(confidence: float | None) -> str:
    if confidence is None:
        return badge("Confidence unknown", "neutral")
    if confidence >= 0.75:
        tone = "success"
    elif confidence >= 0.4:
        tone = "warning"
    else:
        tone = "danger"
    return badge(f"Confidence {confidence:.2f}", tone)


def status_badge(status: str) -> str:
    normalized = status.strip().lower()
    tone = "success" if normalized == "confirmed" else "danger" if normalized == "rejected" else "warning"
    return badge(status.replace("_", " ").title(), tone)


def write_mode_badge(write_mode: str) -> str:
    label = "Confirm mode" if write_mode == "confirm" else "Auto mode"
    return badge(label, "warning" if write_mode == "confirm" else "success")


def mcp_config_block(endpoint: str, project_id: str) -> str:
    config_id = f"mcp-config-{escape(project_id)}"
    command = f'{{"mcpServers":{{"{project_id}":{{"url":"{endpoint}"}}}}}}'
    return (
        "<div class=\"mcp-config-block\">"
        "<div class=\"card-topline\">"
        f"{badge('MCP', 'accent')}"
        f"<button class=\"button button-secondary\" type=\"button\" data-copy-target=\"#{config_id}\" data-copied-label=\"Copied\">Copy MCP config</button>"
        "</div>"
        f"<pre id=\"{config_id}\" class=\"shell-command\"><code>{escape(command)}</code></pre>"
        "</div>"
    )


def page_header(title: str, subtitle: str = "", meta_html: str = "", actions_html: str = "") -> str:
    meta = f"<div class=\"page-header-meta\">{meta_html}</div>" if meta_html else ""
    subtitle_html = f"<p class=\"page-header-subtitle\">{escape(subtitle)}</p>" if subtitle else ""
    actions = f"<div class=\"page-header-actions\">{actions_html}</div>" if actions_html else ""
    return (
        "<header class=\"page-header\">"
        "<div class=\"page-header-main\">"
        f"{meta}"
        f"<h1>{escape(title)}</h1>"
        f"{subtitle_html}"
        "</div>"
        f"{actions}"
        "</header>"
    )


def panel(title: str, content: str, subtitle: str | None = None, class_name: str = "") -> str:
    subtitle_html = f"<p class=\"section-subtitle\">{escape(subtitle)}</p>" if subtitle else ""
    extra_class = f" {escape(class_name)}" if class_name else ""
    return (
        f"<section class=\"ui-panel panel-section{extra_class}\">"
        f"<div class=\"section-heading\"><h2>{escape(title)}</h2>{subtitle_html}</div>"
        f"{content}"
        "</section>"
    )


def section(title: str, content: str, subtitle: str | None = None) -> str:
    return panel(title, content, subtitle)


def property_grid(items: list[tuple[str, str]]) -> str:
    rows = []
    for label, value in items:
        rows.append(
            "<div class=\"property-row key-value-item\">"
            f"<span class=\"key-label\">{escape(label)}</span>"
            f"<span class=\"key-value\">{escape(value)}</span>"
            "</div>"
        )
    return f"<div class=\"property-grid key-value-grid\">{''.join(rows)}</div>"


def key_value_grid(items: list[tuple[str, str]]) -> str:
    return property_grid(items)


def nav_tile_grid(items: list[tuple[str, str, str, str]]) -> str:
    tiles = []
    for title, href, description, icon_label in items:
        tiles.append(
            "<a class=\"action-card\" href=\"{0}\">"
            "<span class=\"action-card-head\">"
            "{1}"
            "<span class=\"action-card-title\">{2}</span>"
            "</span>"
            "<span class=\"action-card-description\">{3}</span>"
            "</a>".format(
                escape(href, quote=True),
                icon_span(icon_label or title, "action-card-icon"),
                escape(title),
                escape(description),
            )
        )
    return f"<div class=\"nav-tile-grid action-grid\">{''.join(tiles)}</div>"


def icon_button(label: str, icon_label: str | None = None, tone: str = "secondary", onclick: str = "") -> str:
    onclick_attr = f' onclick="{escape(onclick, quote=True)}"' if onclick else ""
    return (
        f'<button type="button" class="icon-button icon-button-{escape(tone)}"{onclick_attr} '
        f'title="{escape(label, quote=True)}" aria-label="{escape(label, quote=True)}">'
        f"{icon_span(icon_label or label, 'button-icon')}"
        "</button>"
    )


def table(headers: list[str], rows: list[list[str]]) -> str:
    head = "".join(f"<th>{escape(header)}</th>" for header in headers)
    body_rows = []
    for row in rows:
        body_rows.append("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>")
    return (
        "<div class=\"table-wrap\">"
        "<table>"
        f"<thead><tr>{head}</tr></thead>"
        f"<tbody>{''.join(body_rows)}</tbody>"
        "</table>"
        "</div>"
    )
