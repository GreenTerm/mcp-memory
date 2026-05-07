from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any


TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


class _FallbackTemplate:
    def __init__(self, text: str) -> None:
        self._text = text

    def render(self, **context: Any) -> str:
        rendered = self._text
        for key, value in context.items():
            rendered = rendered.replace("{{ " + key + "|safe }}", str(value))
            rendered = rendered.replace("{{" + key + "|safe}}", str(value))
            rendered = rendered.replace("{{ " + key + " }}", escape(str(value)))
            rendered = rendered.replace("{{" + key + "}}", escape(str(value)))
        return rendered


class TemplateRenderer:
    def __init__(self) -> None:
        try:
            from jinja2 import Environment, FileSystemLoader, select_autoescape
        except ImportError:
            self._env = None
        else:
            self._env = Environment(
                loader=FileSystemLoader(TEMPLATES_DIR),
                autoescape=select_autoescape(["html"]),
            )

    def render(self, template_name: str, **context: Any) -> str:
        if self._env is not None:
            return self._env.get_template(template_name).render(**context)
        return _FallbackTemplate((TEMPLATES_DIR / template_name).read_text(encoding="utf-8")).render(**context)


renderer = TemplateRenderer()
