from __future__ import annotations

import unittest

from mcp_memory.gui.render import load_asset_text


class GuiAssetTests(unittest.TestCase):
    def test_ui_js_closes_constructor_role_menus_on_outside_click(self) -> None:
        js = load_asset_text("ui.js")

        self.assertIn("closeConstructorRoleMenus", js)
        self.assertIn('event.target.closest(".constructor-role-menu")', js)
        self.assertIn(".constructor-role-menu[open]", js)
        self.assertIn("menu.open = false", js)


if __name__ == "__main__":
    unittest.main()
