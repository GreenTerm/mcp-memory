from __future__ import annotations

import unittest

from tests import support  # noqa: F401

from mcp_memory.gui.render import load_asset_text


class GuiAssetTests(unittest.TestCase):
    def test_ui_js_closes_constructor_role_menus_on_outside_click(self) -> None:
        js = load_asset_text("ui.js")

        self.assertIn("closeConstructorRoleMenus", js)
        self.assertIn('event.target.closest(".constructor-role-menu")', js)
        self.assertIn(".constructor-role-menu[open]", js)
        self.assertIn("menu.open = false", js)

    def test_ui_js_updates_constructor_role_summary_without_closing_menu(self) -> None:
        js = load_asset_text("ui.js")

        self.assertIn("updateConstructorRoleSummary", js)
        self.assertIn(".constructor-role-chip input:checked", js)
        self.assertIn("constructor-role-badge-", js)
        self.assertIn("summary.replaceChildren", js)
        self.assertIn('document.addEventListener("change"', js)
        self.assertNotIn("details.open=false", js)

    def test_ui_js_initializes_interactive_graph_canvas(self) -> None:
        js = load_asset_text("ui.js")

        self.assertIn("initGraphCanvas", js)
        self.assertIn("[data-graph-canvas]", js)
        self.assertIn("[data-graph-cytoscape]", js)
        self.assertIn("[data-graph-elements]", js)
        self.assertIn("[data-graph-action]", js)
        self.assertIn("zoom-in", js)
        self.assertIn("window.cytoscape", js)
        self.assertIn("__graphCy", js)
        self.assertIn("layoutOptions", js)
        self.assertIn("breadthfirst", js)
        self.assertIn("[data-graph-layout-select]", js)
        self.assertIn("layoutSelect.addEventListener", js)
        self.assertIn("animationDuration: 320", js)
        self.assertIn('data-graph-action="fullscreen"', js)
        self.assertIn("setFullscreen", js)
        self.assertIn('cy.on("pan zoom"', js)
        self.assertIn("clearActiveTimer", js)
        self.assertIn("userPanningEnabled: false", js)
        self.assertIn('graphHost.addEventListener("pointerdown"', js)
        self.assertIn("cy.panBy", js)
        self.assertIn('canvas.addEventListener("selectstart"', js)
        self.assertIn('canvas.addEventListener("dragstart"', js)
        self.assertIn("setActiveNode", js)
        self.assertIn("normalizeGraphHref", js)
        self.assertIn('window.location.pathname.indexOf("/ui/")', js)
        self.assertIn("window.location.href = normalizeGraphHref(href)", js)

    def test_ui_js_toggles_project_details_state_without_reference_error(self) -> None:
        js = load_asset_text("ui.js")

        self.assertIn('const row = projectToggle.closest("[data-project-row]");', js)
        self.assertNotIn("row.querySelectorAll", js.split('const row = projectToggle.closest("[data-project-row]");', 1)[0])
        self.assertIn('toggle.setAttribute("aria-expanded", String(nextExpanded));', js)
        self.assertIn('target.classList.toggle("is-open", nextExpanded);', js)
        self.assertIn("window.requestAnimationFrame", js)
        self.assertIn("window.setTimeout", js)

    def test_home_css_animates_project_details_panel(self) -> None:
        css = load_asset_text("app.css")

        self.assertIn(".project-expanded-panel.is-open", css)
        self.assertIn("transition:", css)
        self.assertIn("opacity", css)
        self.assertIn("transform", css)

    def test_home_css_keeps_write_mode_badge_inline(self) -> None:
        css = load_asset_text("app.css")

        self.assertIn(".project-detail-item-inline", css)
        self.assertIn("padding-top: 12px;", css)
        self.assertIn(".project-detail-list:nth-of-type(2) .project-detail-item:first-child", css)
        self.assertIn(".project-detail-list:nth-of-type(2) .project-detail-item:nth-child(2)", css)
        self.assertIn(".project-detail-list:nth-of-type(2) .project-detail-item:nth-child(3)", css)
        self.assertIn("grid-template-columns: 24px 96px minmax(0, 1fr);", css)
        self.assertIn("align-items: start;", css)
        self.assertIn("grid-column: 3;", css)
        self.assertIn(".project-detail-item-path > div", css)
        self.assertIn("font-size: 0.86rem;", css)
        self.assertIn("line-height: 1.35;", css)

    def test_home_css_uses_subdued_primary_project_buttons(self) -> None:
        css = load_asset_text("app.css")

        self.assertIn(".home-projects-page .home-topbar .button-primary", css)
        self.assertIn(".project-row-action-start", css)
        self.assertIn("background: linear-gradient(180deg, #4f3cb0, #372680);", css)
        self.assertIn("border-color: color-mix(in srgb, #6e5bd0 44%, transparent);", css)
        self.assertNotIn("background: linear-gradient(180deg, #6b55d9, #4b32a6);", css)

    def test_home_css_uses_subdued_open_workspace_button(self) -> None:
        css = load_asset_text("app.css")

        self.assertIn(".project-row-actions > a.project-row-action", css)
        self.assertIn("background: linear-gradient(180deg, #2388b1, #135f86);", css)
        self.assertIn("border-color: color-mix(in srgb, #2d9ac5 48%, transparent);", css)
        self.assertNotIn("background: linear-gradient(180deg, #35bce6, #147fb3);", css)


if __name__ == "__main__":
    unittest.main()
