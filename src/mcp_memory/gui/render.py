from __future__ import annotations

from html import escape
from pathlib import Path


ASSETS_DIR = Path(__file__).resolve().parent / "assets"


def load_asset_text(name: str) -> str:
    return (ASSETS_DIR / name).read_text(encoding="utf-8")


def html_page(title: str, body: str, stylesheet_href: str, page_class: str = "", html_lang: str = "en") -> str:
    page_class_attr = f' class="{escape(page_class)}"' if page_class else ""
    return (
        "<!DOCTYPE html>"
        f"<html lang=\"{escape(html_lang)}\" data-theme=\"dark\">"
        "<head>"
        "<meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>{escape(title)}</title>"
        f"<link rel=\"stylesheet\" href=\"{escape(stylesheet_href)}\">"
        "</head>"
        f"<body{page_class_attr}>"
        f"{body}"
        "<script src=\"/ui/assets/shell.js\"></script>"
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
        f"<h2>{escape(title)}</h2>"
        f"<p>{escape(body)}</p>"
        "</section>"
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


# ========================================
# PHASE 2: SHELL COMPONENTS
# ========================================

SIDEBAR_NAV_ITEMS = [
    ("Projects", "/ui/", "folder"),
    ("Functions", "/ui/functions", "code"),
    ("Structures", "/ui/structures", "layout"),
    ("Hypotheses", "/ui/global-hypotheses", "brain"),
    ("Graph", "/ui/graph", "share-2"),
    ("Search", "/ui/search", "search"),
    ("Pending", "/ui/pending", "clock"),
    ("Audit", "/ui/audit", "history"),
    ("Import / Export", "/ui/import", "download"),
    ("Backups", "/ui/backups", "archive"),
    ("Settings", "/ui/settings", "settings"),
]


def render_sidebar(current_path: str = "/ui/", collapsed: bool = False) -> str:
    items_html = ""
    for label, href, icon in SIDEBAR_NAV_ITEMS:
        is_active = href == current_path or (current_path.startswith(href) and href != "/ui/")
        active_class = " active" if is_active else ""
        items_html += (
            f"<a class=\"sidebar-link{active_class}\" href=\"{escape(href)}\">"
            f"<span class=\"sidebar-icon\">{icon_svg(icon)}</span>"
            f"<span class=\"sidebar-label\">{escape(label)}</span>"
            "</a>"
        )

    collapsed_attr = " collapsed" if collapsed else ""
    brand_text = "Warm Lab" if not collapsed else "WL"
    toggle_icon = "chevron-left" if not collapsed else "chevron-right"

    return (
        f"<aside class=\"sidebar{collapsed_attr}\">"
        "<div class=\"sidebar-header\">"
        f"<span class=\"sidebar-brand\">{escape(brand_text)}</span>"
        f"<button class=\"sidebar-toggle\" onclick=\"toggleSidebar()\">{icon_svg(toggle_icon)}</button>"
        "</div>"
        f"<nav class=\"sidebar-nav\">{items_html}</nav>"
        "</aside>"
    )


def render_top_bar(
    project_name: str,
    current_path: str,
    search_placeholder: str = "Search functions, structures, hypotheses...",
) -> str:
    return (
        "<header class=\"top-bar\">"
        "<div class=\"top-bar-search\">"
        f"<input type=\"text\" class=\"search-input\" placeholder=\"{escape(search_placeholder)}\" "
        "onclick=\"location.href='/ui/search'\">"
        "</div>"
        "<div class=\"top-bar-actions\">"
        f"<span>{escape(project_name)}</span>"
        "<button class=\"theme-toggle\" onclick=\"toggleTheme()\" title=\"Toggle theme\">"
        f"{icon_svg('sun')}"
        "</button>"
        "</div>"
        "</header>"
    )


def render_breadcrumbs(items: list[tuple[str, str]]) -> str:
    if not items:
        return ""

    crumb_html = ""
    for i, (label, href) in enumerate(items):
        if i == len(items) - 1:
            crumb_html += (
                f"<span class=\"breadcrumb-current\">{escape(label)}</span>"
            )
        else:
            crumb_html += (
                f"<a class=\"breadcrumb-link\" href=\"{escape(href)}\">{escape(label)}</a>"
                f"<span class=\"breadcrumb-separator\">/</span>"
            )

    return f"<div class=\"breadcrumbs\">{crumb_html}</div>"


def render_app_shell(
    project_name: str,
    current_path: str,
    breadcrumbs: list[tuple[str, str]],
    content: str,
    collapsed: bool = False,
) -> str:
    return (
        "<div class=\"app-shell\">"
        f"{render_sidebar(current_path, collapsed)}"
        "<main class=\"main-area\">"
        f"{render_top_bar(project_name, current_path)}"
        f"{render_breadcrumbs(breadcrumbs)}"
        f"<div class=\"content\">{content}</div>"
        "</main>"
        "</div>"
    )


# ========================================
# COMPONENT HELPERS
# ========================================

def icon_svg(name: str) -> str:
    icons = {
        "folder": '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>',
        "code": '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>',
        "layout": '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="9" y1="21" x2="9" y2="9"/></svg>',
        "brain": '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 5a3 3 0 0 0-3 3c0 1.1.6 2 1.5 2.5-.2.7-.5 1.4-1 2l-.1.5H5a2 2 0 0 0-2 2v2h2v-2a2 2 0 0 1 2-2h.4c.5.6 1 1 1.6 1.5V18h2v-1.5c.6-.5 1.1-.9 1.6-1.5h.4a2 2 0 0 1 2 2v2h2v-2a2 2 0 0 0-2-2h-.4c-.5-.1-1-.3-1.5-.5.9-.5 1.5-1.4 1.5-2.5a3 3 0 0 0-3-3Z"/><path d="M12 5a3 3 0 0 1 3 3c0 1.1-.6 2-1.5 2.5.2.7.5 1.4 1 2l.1.5H19a2 2 0 0 1 2 2v2h-2v-2a2 2 0 0 0-2-2h-.4c-.5.6-1 1-1.6 1.5V18h-2v-1.5c-.6-.5-1.1-.9-1.6-1.5H11a2 2 0 0 0-2-2v-2H7v2a2 2 0 0 0 2 2h.4c.5.1 1 .3 1.5.5-.9.5-1.5 1.4-1.5 2.5a3 3 0 0 1-3-3Z"/></svg>',
        "share-2": '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/><line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/></svg>',
        "search": '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>',
        "clock": '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>',
        "history": '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l4 2"/></svg>',
        "download": '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>',
        "archive": '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="21 8 21 21 3 21 3 8"/><rect x="1" y="3" width="22" height="5"/><line x1="10" y1="12" x2="14" y2="12"/></svg>',
        "settings": '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>',
        "chevron-left": '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="15 18 9 12 15 6"/></svg>',
        "chevron-right": '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg>',
        "sun": '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>',
        "moon": '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>',
    }
    return icons.get(name, "")
