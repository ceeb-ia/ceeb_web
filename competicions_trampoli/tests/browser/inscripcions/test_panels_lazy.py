from ..base import BrowserInscripcionsBase
from ..fixtures import BrowserInscripcionsFixturesMixin
from ..helpers import (
    GROUPS_PANEL_ID,
    MEDIA_PANEL_ID,
    SERIES_PANEL_ID,
    TEAMS_PANEL_ID,
)


class BrowserInscripcionsLazyPanelsTests(BrowserInscripcionsFixturesMixin, BrowserInscripcionsBase):
    def setUp(self):
        super().setUp()
        self.comp = self._create_browser_competicio("Browser Lazy Panels")
        self.inscripcions = self._create_compact_inscripcions(self.comp, total=8)
        self.team_bundle = self._create_optional_team_context(
            self.comp,
            code="pairs",
            nom="Pairs",
            inscripcions=self.inscripcions[:4],
        )
        self.series_bundle = self._create_optional_series_app(
            self.comp,
            context=self.team_bundle.context,
            codi="SERB",
            nom="Series Browser",
        )
        self._create_optional_media(self.comp, inscripcions=self.inscripcions[:2], count=2)
        self.login_competicio_user(
            self.comp,
            role=self._owner_role(),
            username_prefix="browser_lazy",
        )

    @staticmethod
    def _owner_role():
        from ....models import CompeticioMembership

        return CompeticioMembership.Role.OWNER

    def _assert_panel_loaded(self, panel_id, required_selector, placeholder_text):
        panel = self.page.locator(f"#{panel_id}")
        panel.wait_for(state="visible")
        self.assertNotEqual(panel.get_attribute("data-panel-lazy"), "1")
        self.page.locator(required_selector).wait_for(state="attached")
        panel_text = panel.inner_text().lower()
        self.assertNotIn(placeholder_text.lower(), panel_text)

    def test_groups_panel_lazy_loads_real_workspace_content(self):
        self.open_inscripcions_page(self.comp)
        self.open_lazy_panel("grups")
        self._assert_panel_loaded(GROUPS_PANEL_ID, "#groups-workspace-shell", "El panell es carrega quan l'obres.")

    def test_teams_panel_lazy_loads_real_workspace_content(self):
        self.open_inscripcions_page(self.comp)
        self.open_lazy_panel("equips")
        self._assert_panel_loaded(TEAMS_PANEL_ID, "#team-workspace-shell", "El workspace es carrega quan l'obres.")

    def test_series_panel_lazy_loads_real_workspace_content(self):
        self.open_inscripcions_page(self.comp)
        self.open_lazy_panel("series-equips")
        self._assert_panel_loaded(SERIES_PANEL_ID, "#series-workspace-shell", "El workspace es carrega quan l'obres.")

    def test_media_panel_lazy_loads_real_workspace_content(self):
        self.open_inscripcions_page(self.comp)
        self.open_lazy_panel("media")
        self._assert_panel_loaded(MEDIA_PANEL_ID, "#media-workspace-shell", "El panell es carrega quan l'obres.")

    def test_switching_between_lazy_panels_preserves_stable_state(self):
        self.open_inscripcions_page(self.comp)

        self.open_lazy_panel("grups")
        self.page.locator("#groups-workspace-shell").wait_for(state="attached")

        self.open_lazy_panel("equips")
        self.page.locator("#team-workspace-shell").wait_for(state="attached")
        self.assertTrue(self.page.locator(f"#{TEAMS_PANEL_ID}").is_visible())
        self.assertTrue(self.page.locator(f"#{GROUPS_PANEL_ID}").is_hidden())

        self.open_lazy_panel("media")
        self.page.locator("#media-workspace-shell").wait_for(state="attached")
        self.assertTrue(self.page.locator(f"#{MEDIA_PANEL_ID}").is_visible())
        self.assertTrue(self.page.locator(f"#{TEAMS_PANEL_ID}").is_hidden())
