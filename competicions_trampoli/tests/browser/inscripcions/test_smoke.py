from django.urls import reverse

from ..base import BrowserInscripcionsBase
from ..fixtures import BrowserInscripcionsFixturesMixin
from ..helpers import (
    COMPETITION_ORDER_TAIL_TOGGLE_ID,
    HISTORY_REDO_BUTTON_ID,
    HISTORY_UNDO_BUTTON_ID,
    INSCRIPCIONS_ACTIONS_SIDEBAR_ID,
    INSCRIPCIONS_BACK_TO_TOP_ID,
    INSCRIPCIONS_DRAWER_TOGGLE_ID,
    INSCRIPCIONS_PAGE_SHELL_ID,
    SEARCH_BUTTON_ID,
    SEARCH_INPUT_ID,
)


class BrowserInscripcionsSmokeTests(BrowserInscripcionsFixturesMixin, BrowserInscripcionsBase):
    def setUp(self):
        super().setUp()
        self.comp = self._create_browser_competicio("Browser Smoke")
        self._create_compact_inscripcions(self.comp, total=6)
        self.user = self.login_competicio_user(
            self.comp,
            role=self._owner_role(),
            username_prefix="browser_smoke",
        )

    @staticmethod
    def _owner_role():
        from ....models import CompeticioMembership

        return CompeticioMembership.Role.OWNER

    def test_inscripcions_page_loads_without_browser_errors(self):
        self.open_inscripcions_page(self.comp)

        shell = self.page.locator(f"#{INSCRIPCIONS_PAGE_SHELL_ID}")
        self.assertTrue(shell.is_visible())
        self.page.locator(f"#{INSCRIPCIONS_ACTIONS_SIDEBAR_ID}").wait_for(state="visible")
        self.page.locator(f"#{SEARCH_INPUT_ID}").wait_for(state="visible")

        current_url = self.page.url
        self.assertIn(reverse("inscripcions_list", kwargs={"pk": self.comp.id}), current_url)

        app_info = self.page.evaluate(
            """() => ({
                hasApp: !!window.InscripcionsApp,
                hasOpenPanel: !!window.InscripcionsApp && typeof window.InscripcionsApp.openPanel === 'function',
                hasRefresh: !!window.InscripcionsApp && typeof window.InscripcionsApp.refreshHtmlFragments === 'function',
                hasSelectionApi: !!window.__inscripcionsSelectionApi,
            })"""
        )
        self.assertEqual(
            app_info,
            {
                "hasApp": True,
                "hasOpenPanel": True,
                "hasRefresh": True,
                "hasSelectionApi": True,
            },
        )

    def test_global_shell_controls_are_interactive(self):
        self.open_inscripcions_page(self.comp)

        drawer_toggle = self.page.locator(f"#{INSCRIPCIONS_DRAWER_TOGGLE_ID}")
        sidebar = self.page.locator(f"#{INSCRIPCIONS_ACTIONS_SIDEBAR_ID}")
        back_to_top = self.page.locator(f"#{INSCRIPCIONS_BACK_TO_TOP_ID}")

        initial_expanded = drawer_toggle.get_attribute("aria-expanded")
        self.assertIn(initial_expanded, {"true", "false"})
        drawer_toggle.click()
        self.page.wait_for_timeout(150)
        self.assertNotEqual(drawer_toggle.get_attribute("aria-expanded"), initial_expanded)
        self.assertTrue(sidebar.is_visible())
        self.page.locator(f"#{INSCRIPCIONS_BACK_TO_TOP_ID}").wait_for(state="attached")

        search_input = self.page.locator(f"#{SEARCH_INPUT_ID}")
        search_button = self.page.locator(f"#{SEARCH_BUTTON_ID}")
        search_input.fill("Inscripcio 1")
        search_button.click()
        self.page.wait_for_function("() => window.location.search.includes('q=Inscripcio+1')")

        self.page.locator("#clear-search-btn").click()
        self.page.wait_for_function("() => !window.location.search.includes('q=')")

    def test_history_controls_do_not_break_frontend_state(self):
        self.open_inscripcions_page(self.comp)

        undo_button = self.page.locator(f"#{HISTORY_UNDO_BUTTON_ID}")
        redo_button = self.page.locator(f"#{HISTORY_REDO_BUTTON_ID}")
        tail_toggle = self.page.locator(f"#{COMPETITION_ORDER_TAIL_TOGGLE_ID}")

        self.assertTrue(undo_button.is_visible())
        self.assertTrue(redo_button.is_visible())
        self.assertTrue(tail_toggle.is_visible())

        undo_disabled_before = undo_button.is_disabled()
        redo_disabled_before = redo_button.is_disabled()
        tail_disabled_before = tail_toggle.is_disabled()

        if not tail_disabled_before:
            tail_toggle.click()
            self.page.wait_for_timeout(150)

        if not undo_disabled_before:
            undo_button.click()
            self.page.wait_for_timeout(250)

        if not redo_disabled_before:
            redo_button.click()
            self.page.wait_for_timeout(250)

        self.page.locator(f"#{INSCRIPCIONS_PAGE_SHELL_ID}").wait_for(state="visible")
        self.wait_for_inscripcions_app()
