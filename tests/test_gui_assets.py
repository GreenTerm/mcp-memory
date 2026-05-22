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


if __name__ == "__main__":
    unittest.main()
