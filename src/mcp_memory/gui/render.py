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
        f"<html lang=\"{escape(html_lang)}\">"
        "<head>"
        "<meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>{escape(title)}</title>"
        f"<link rel=\"stylesheet\" href=\"{escape(stylesheet_href)}\">"
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
