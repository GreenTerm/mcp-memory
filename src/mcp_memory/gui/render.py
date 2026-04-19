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


def sidebar_nav(items: list[tuple[str, str, str]], active_href: str = "", brand_href: str = "/ui/") -> str:
    links = []
    active_path = active_href.split("?", 1)[0].rstrip("/") or "/"
    for label, href, group in items:
        href_path = href.split("?", 1)[0].rstrip("/") or "/"
        active_class = " is-active" if href_path == active_path else ""
        links.append(
            f"<a class=\"sidebar-link{active_class}\" href=\"{escape(href, quote=True)}\" data-nav-group=\"{escape(group)}\" title=\"{escape(label, quote=True)}\" aria-label=\"{escape(label, quote=True)}\">"
            f"{sidebar_icon(label)}"
            f"<span class=\"app-sidebar-label\">{escape(label)}</span>"
            "</a>"
        )
    return (
        "<aside class=\"app-sidebar\">"
        "<div class=\"sidebar-head\">"
        f"<a class=\"brand-mark\" href=\"{escape(brand_href, quote=True)}\">mcp-memory</a>"
        "<button class=\"button button-secondary sidebar-toggle\" type=\"button\" data-sidebar-toggle aria-expanded=\"true\" aria-label=\"Toggle sidebar\" title=\"Toggle sidebar\">"
        f"{sidebar_icon('Toggle sidebar')}"
        "</button>"
        "</div>"
        f"<nav class=\"sidebar-nav\" aria-label=\"Workspace navigation\">{''.join(links)}</nav>"
        "</aside>"
    )


def sidebar_icon(label: str) -> str:
    paths = {
        "Projects": "<path d=\"M4 7h6l2 2h8v9a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2z\"/><path d=\"M2 11h20\"/>",
        "Binaries": "<rect x=\"4\" y=\"4\" width=\"16\" height=\"16\" rx=\"3\"/><path d=\"M9 4v3M15 4v3M9 17v3M15 17v3M4 9h3M17 9h3M4 15h3M17 15h3\"/>",
        "Functions": "<path d=\"M9 4h8\"/><path d=\"M7 20c2.5-4.5 2.5-11.5 0-16\"/><path d=\"M11 10l6 6M17 10l-6 6\"/>",
        "Structures": "<path d=\"M5 5h14v5H5zM5 14h14v5H5z\"/><path d=\"M9 5v14\"/>",
        "Hypotheses": "<path d=\"M12 3a6 6 0 0 0-3 11v3h6v-3a6 6 0 0 0-3-11z\"/><path d=\"M9 21h6\"/>",
        "Search": "<circle cx=\"10.5\" cy=\"10.5\" r=\"5.5\"/><path d=\"M15 15l5 5\"/>",
        "Graph": "<circle cx=\"6\" cy=\"7\" r=\"3\"/><circle cx=\"18\" cy=\"7\" r=\"3\"/><circle cx=\"12\" cy=\"18\" r=\"3\"/><path d=\"M9 8h6M8 10l3 5M16 10l-3 5\"/>",
        "Import/Export": "<path d=\"M12 3v12\"/><path d=\"M8 7l4-4 4 4\"/><path d=\"M8 17l4 4 4-4\"/><path d=\"M4 12h16\"/>",
        "Backups": "<path d=\"M5 6h14v14H5z\"/><path d=\"M8 3h8v3H8z\"/><path d=\"M8 11h8M8 15h6\"/>",
        "Settings": "<circle cx=\"12\" cy=\"12\" r=\"3\"/><path d=\"M19 12a7 7 0 0 0-.1-1l2-1.5-2-3.4-2.4 1a7 7 0 0 0-1.8-1L14.4 3h-4.8l-.3 3.1a7 7 0 0 0-1.8 1l-2.4-1-2 3.4L5.1 11a7 7 0 0 0 0 2l-2 1.5 2 3.4 2.4-1a7 7 0 0 0 1.8 1l.3 3.1h4.8l.3-3.1a7 7 0 0 0 1.8-1l2.4 1 2-3.4-2-1.5a7 7 0 0 0 .1-1z\"/>",
        "Toggle sidebar": "<path d=\"M4 5h16v14H4z\"/><path d=\"M9 5v14\"/><path d=\"M13 10l3 2-3 2\"/>",
    }
    path = paths.get(label, "<circle cx=\"12\" cy=\"12\" r=\"7\"/>")
    return (
        "<span class=\"sidebar-icon\" aria-hidden=\"true\">"
        "<svg viewBox=\"0 0 24 24\" focusable=\"false\">"
        f"{path}"
        "</svg>"
        "</span>"
    )


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


def section(title: str, content: str, subtitle: str | None = None) -> str:
    subtitle_html = f"<p class=\"section-subtitle\">{escape(subtitle)}</p>" if subtitle else ""
    return (
        "<section class=\"panel-section\">"
        f"<div class=\"section-heading\"><h2>{escape(title)}</h2>{subtitle_html}</div>"
        f"{content}"
        "</section>"
    )


def key_value_grid(items: list[tuple[str, str]]) -> str:
    rows = []
    for label, value in items:
        rows.append(
            "<div class=\"key-value-item\">"
            f"<span class=\"key-label\">{escape(label)}</span>"
            f"<span class=\"key-value\">{escape(value)}</span>"
            "</div>"
        )
    return f"<div class=\"key-value-grid\">{''.join(rows)}</div>"


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
