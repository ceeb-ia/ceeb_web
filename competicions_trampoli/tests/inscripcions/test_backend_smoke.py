import importlib
import json
from pathlib import Path
from datetime import date, datetime
from io import BytesIO

from django.test import TestCase
from django.urls import resolve, reverse
from openpyxl import Workbook

from ...models import Competicio, CompeticioMembership, Inscripcio, InscripcioMedia
from ...models.competicio import Aparell
from ...services.inscripcions.import_excel import importar_inscripcions_excel
from ...views.inscripcions.listing import _serialize_listing_media_item
from ..base import _BaseTrampoliDataMixin



class InscripcionsBackendSmokeTests(_BaseTrampoliDataMixin, TestCase):
    def setUp(self):
        self.comp = self._create_competicio("Comp Inscripcions Smoke")
        self.user = self._create_competicio_user(
            self.comp,
            role=CompeticioMembership.Role.OWNER,
            username_prefix="insc_smoke",
        )
        self.client.force_login(self.user)
        self.ins = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Lucia Smoke",
            entitat="Club Smoke",
            ordre_sortida=1,
        )

    def test_entrypoint_modules_import_and_do_not_depend_on_legacy_monoliths(self):
        modules = [
            "competicions_trampoli.views",
            "competicions_trampoli.views.inscripcions.base",
            "competicions_trampoli.views.inscripcions.crud",
            "competicions_trampoli.views.inscripcions.equips",
            "competicions_trampoli.views.inscripcions.listing",
            "competicions_trampoli.views.inscripcions.team_series",
            "competicions_trampoli.views.inscripcions.sorting",
            "competicions_trampoli.views.inscripcions.groups",
            "competicions_trampoli.views.inscripcions.media",
        ]
        for module_name in modules:
            importlib.import_module(module_name)

        package_root = Path(__file__).resolve().parents[2]
        for rel_path in [
            "views/inscripcions/base.py",
            "views/inscripcions/crud.py",
            "views/inscripcions/equips.py",
            "views/inscripcions/listing.py",
            "views/inscripcions/team_series.py",
            "views/inscripcions/sorting.py",
            "views/inscripcions/groups.py",
            "views/inscripcions/media.py",
        ]:
            source = (package_root / rel_path).read_text(encoding="utf-8")
            self.assertNotIn("views_inscripcions_", source)
            self.assertNotIn("views_equips", source)
            self.assertNotIn("views_team_series", source)
            self.assertNotIn("inscripcions_views_shared", source)
            self.assertNotIn("inscripcions_list_new", source)

    def test_legacy_files_are_facades_only(self):
        package_root = Path(__file__).resolve().parents[2]
        views_source = (package_root / "views" / "__init__.py").read_text(encoding="utf-8")

        self.assertIn("Compatibility facade", views_source)
        self.assertIn("from .inscripcions.sorting import", views_source)
        self.assertNotIn("def inscripcions_sort_apply", views_source)
        self.assertNotIn("class InscripcionsListView(", views_source)

    def test_reverse_and_resolve_all_inscripcions_routes(self):
        route_kwargs = {
            "inscripcio_edit": {"pk": 1, "ins_id": 1},
            "inscripcio_delete": {"pk": 1, "ins_id": 1},
            "inscripcions_media_file": {"pk": 1, "media_id": 1},
            "inscripcions_equip_context_rename": {"pk": 1, "context_code": "finals"},
            "inscripcions_equip_context_delete": {"pk": 1, "context_code": "finals"},
            "inscripcions_equips_rename": {"pk": 1, "equip_id": 1},
            "inscripcions_equips_delete": {"pk": 1, "equip_id": 1},
        }
        route_names = [
            "import",
            "inscripcions_list",
            "inscripcions_reorder",
            "inscripcions_save_group_competition_order",
            "inscripcions_group_competition_order_preview",
            "groups_workspace",
            "groups_detail",
            "groups_preview",
            "groups_create",
            "groups_assign",
            "groups_unassign",
            "groups_delete",
            "groups_delete_all",
            "groups_delete_empty",
            "groups_transform_preview",
            "groups_transform_apply",
            "groups_workspace_legacy",
            "groups_detail_legacy",
            "groups_preview_legacy",
            "groups_create_legacy",
            "groups_assign_legacy",
            "groups_unassign_legacy",
            "groups_delete_legacy",
            "groups_delete_all_legacy",
            "groups_delete_empty_legacy",
            "groups_transform_preview_legacy",
            "groups_transform_apply_legacy",
            "inscripcions_sort_apply",
            "inscripcions_sort_remove",
            "inscripcions_sort_clear",
            "inscripcions_sort_competition_tail_toggle",
            "inscripcions_filter_values",
            "inscripcions_sort_custom_values",
            "inscripcions_sort_custom_save",
            "inscripcions_history_undo",
            "inscripcions_history_redo",
            "inscripcions_sort_undo",
            "inscripcions_groups_from_sort",
            "inscripcions_save_table_columns",
            "inscripcions_save_birth_year_range_config",
            "inscripcions_set_group_name",
            "inscripcions_set_aparells",
            "inscripcions_media_upload",
            "inscripcions_media_delete",
            "inscripcions_media_set_primary",
            "inscripcions_media_match_config_save",
            "inscripcions_media_match_preview",
            "inscripcions_media_match_apply",
            "inscripcions_media_workspace",
            "inscripcions_media_reassign",
            "inscripcions_media_file",
            "inscripcions_equips_preview",
            "inscripcions_equips_workspace",
            "inscripcions_equips_auto_create",
            "inscripcions_equips_create_manual",
            "inscripcions_equips_assign",
            "inscripcions_equips_unassign",
            "inscripcions_equip_context_create",
            "inscripcions_equip_context_rename",
            "inscripcions_equip_context_delete",
            "inscripcions_equip_context_sources_save",
            "inscripcions_equips_rename",
            "inscripcions_equips_delete",
            "inscripcions_equips_delete_all",
            "inscripcions_equips_delete_empty",
            "inscripcions_series_equips_workspace",
            "inscripcions_series_equips_detail",
            "inscripcions_series_equips_preview",
            "inscripcions_series_equips_create",
            "inscripcions_series_equips_assign",
            "inscripcions_series_equips_unassign",
            "inscripcions_series_equips_delete",
            "inscripcions_series_equips_delete_empty",
            "inscripcions_series_equips_rename",
            "inscripcions_series_equips_reorder",
            "inscripcions_series_equips_start_list_export",
            "inscripcions_series_equips_work_sheet_export",
            "inscripcio_edit",
            "inscripcio_delete",
            "inscripcio_add",
            "inscripcions_merge_tabs",
        ]

        for route_name in route_names:
            kwargs = route_kwargs.get(route_name, {"pk": 1})
            url = reverse(route_name, kwargs=kwargs)
            match = resolve(url)
            self.assertEqual(match.view_name, route_name)

    def test_render_smoke_uses_new_template_and_context_contract(self):
        response = self.client.get(reverse("inscripcions_list", kwargs={"pk": self.comp.id}))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "competicio/inscripcions/inscripcions_page.html")
        self.assertIn("selected_table_columns", response.context)
        self.assertIn("sort_field_options", response.context)
        self.assertIn("table_colspan", response.context)
        self.assertIn("inscripcions_page_boot", response.context)
        self.assertIn("urls", response.context["inscripcions_page_boot"])
        self.assertContains(response, reverse("inscripcio_add", kwargs={"pk": self.comp.id}))
        self.assertContains(response, reverse("scoring_notes_home", kwargs={"pk": self.comp.id}))
        self.assertContains(response, reverse("rotacions_planner", kwargs={"pk": self.comp.id}))
        self.assertContains(response, 'id="panel-grups"', html=False)
        self.assertContains(response, 'data-panel-lazy="1"', html=False)
        self.assertContains(response, 'id="panel-media"', html=False)
        self.assertContains(response, 'data-panel-key="media"', html=False)
        self.assertNotContains(response, 'id="btn-groups-preview-confirm"', html=False)
        self.assertNotContains(response, 'id="media-folder-input"', html=False)
        panel_response = self.client.get(
            reverse("inscripcions_list", kwargs={"pk": self.comp.id}),
            {"__fragments": "panel", "__panel_key": "grups"},
        )
        self.assertEqual(panel_response.status_code, 200)
        panel_html = panel_response.json()["fragments"]["panel"]["html"]
        self.assertIn('id="btn-groups-preview-confirm"', panel_html)
        self.assertIn('id="btn-groups-preview-clear"', panel_html)
        self.assertIn('id="btn-groups-preview-count"', panel_html)
        self.assertIn('id="btn-groups-create-count"', panel_html)
        self.assertIn('id="btn-groups-preview-size"', panel_html)
        self.assertIn('id="btn-groups-create-size"', panel_html)
        self.assertIn('id="btn-groups-preview-range-balanced"', panel_html)
        self.assertIn('id="btn-groups-create-range-balanced"', panel_html)
        self.assertIn('id="btn-groups-preview-count-range"', panel_html)
        self.assertIn('id="btn-groups-create-count-range"', panel_html)
        self.assertIn('id="btn-groups-preview-per-bucket"', panel_html)
        self.assertIn('id="btn-groups-create-per-bucket"', panel_html)
        self.assertContains(response, '/static/js/vendor/Sortable.min.js', html=False)
        self.assertNotContains(response, 'cdn.jsdelivr.net/npm/sortablejs', html=False)
        self.assertNotIn("mediaMatchInscripcionsOptions", response.context["inscripcions_page_boot"]["initial"])
        self.assertIn("mediaMatchingConfig", response.context["inscripcions_page_boot"]["initial"])
        self.assertIn("mediaWorkspace", response.context["inscripcions_page_boot"]["urls"])
        self.assertIn("mediaSaveMatchingConfig", response.context["inscripcions_page_boot"]["urls"])
        self.assertIn("mediaReassign", response.context["inscripcions_page_boot"]["urls"])
        self.assertNotContains(response, '"mediaMatchInscripcionsOptions":', html=False)

    def test_fragment_html_contract_returns_header_toolbar_history_table(self):
        response = self.client.get(
            reverse("inscripcions_list", kwargs={"pk": self.comp.id}),
            {"__fragments": "header,toolbar,history,table"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload.get("ok"))
        self.assertIn("boot", payload)
        self.assertIn("fragments", payload)

        fragments = payload["fragments"]
        self.assertEqual(set(fragments.keys()), {"header", "toolbar", "history", "table"})
        self.assertIn('id="inscripcions-header-fragment"', fragments["header"])
        self.assertIn('id="inscripcions-toolbar-fragment"', fragments["toolbar"])
        self.assertIn('id="inscripcions-history-fragment"', fragments["history"])
        self.assertIn('id="inscripcions-table-fragment"', fragments["table"])

    def test_lazy_panel_fragments_return_real_workspace_panels(self):
        markers_by_panel = {
            "grups": ['id="groups-workspace-shell"', 'id="btn-groups-preview-confirm"'],
            "equips": ['id="team-workspace-shell"', 'id="btn-team-compact-open-workspace"'],
            "series-equips": ['id="series-workspace-shell"', 'id="series-comp-aparell-select"'],
            "media": ['id="media-folder-input"', 'id="btn-media-match-preview"'],
        }

        for panel_key, markers in markers_by_panel.items():
            with self.subTest(panel_key=panel_key):
                response = self.client.get(
                    reverse("inscripcions_list", kwargs={"pk": self.comp.id}),
                    {"__fragments": "panel", "__panel_key": panel_key},
                )

                self.assertEqual(response.status_code, 200)
                payload = response.json()
                self.assertTrue(payload.get("ok"))
                fragment = payload["fragments"]["panel"]
                self.assertEqual(fragment["panel_key"], panel_key)
                for marker in markers:
                    self.assertIn(marker, fragment["html"])

    def test_lazy_series_panel_lists_all_team_aparells_only(self):
        team_app_a = self._create_aparell("TEAM-A-SMOKE", "Team A Smoke")
        team_app_a.competition_unit = Aparell.CompetitionUnit.TEAM
        team_app_a.save(update_fields=["competition_unit"])
        team_app_b = self._create_aparell("TEAM-B-SMOKE", "Team B Smoke")
        team_app_b.competition_unit = Aparell.CompetitionUnit.TEAM
        team_app_b.save(update_fields=["competition_unit"])
        individual_app = self._create_aparell("IND-SMOKE", "Individual Smoke")
        comp_app_a = self._create_comp_aparell(self.comp, team_app_a, ordre=1)
        self._create_comp_aparell(self.comp, individual_app, ordre=2)
        comp_app_b = self._create_comp_aparell(self.comp, team_app_b, ordre=3)

        response = self.client.get(
            reverse("inscripcions_list", kwargs={"pk": self.comp.id}),
            {"__fragments": "panel", "__panel_key": "series-equips"},
        )

        self.assertEqual(response.status_code, 200)
        html = response.json()["fragments"]["panel"]["html"]
        self.assertIn("Team A Smoke", html)
        self.assertIn("Team B Smoke", html)
        self.assertNotIn("Individual Smoke", html)
        self.assertEqual(html.count(f'value="{comp_app_a.id}"'), 2)
        self.assertEqual(html.count(f'value="{comp_app_b.id}"'), 2)

    def test_lazy_grouped_table_renders_active_rows_and_complete_order_payload(self):
        self.ins.categoria = "A"
        self.ins.save(update_fields=["categoria"])
        second = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Berta Smoke",
            entitat="Club Smoke",
            categoria="B",
            ordre_sortida=2,
        )
        third = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Carla Smoke",
            entitat="Club Smoke",
            categoria="B",
            ordre_sortida=3,
        )

        response = self.client.get(
            reverse("inscripcions_list", kwargs={"pk": self.comp.id}),
            {"group_by": "categoria"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["lazy_group_tabs_enabled"])
        payload = response.context["lazy_group_order_payload"]
        self.assertIn("tab_order", payload)
        self.assertIn("group_ids_by_key", payload)

        payload_ids = []
        for tab_key in payload["tab_order"]:
            payload_ids.extend(payload["group_ids_by_key"][tab_key])
        self.assertEqual(payload_ids, [self.ins.id, second.id, third.id])

        active_group_key = response.context["active_group_key"]
        grouped_by_key = {
            group_key: group_records
            for _group_label, group_records, group_key in response.context["records_grouped"]
        }
        self.assertEqual([record.id for record in grouped_by_key[active_group_key]], [self.ins.id])
        inactive_keys = [key for key in grouped_by_key if key != active_group_key]
        self.assertTrue(inactive_keys)
        self.assertTrue(all(grouped_by_key[key] == [] for key in inactive_keys))
        self.assertContains(response, 'id="inscripcions-lazy-group-order-data"', html=False)
        self.assertContains(response, "inscripcions-tab-placeholder", html=False)
        self.assertEqual(response.content.decode("utf-8").count('class="inscripcio-row"'), 1)

    def test_render_smoke_keeps_later_payloads_out_of_initial_get_context(self):
        response = self.client.get(reverse("inscripcions_list", kwargs={"pk": self.comp.id}))

        self.assertEqual(response.status_code, 200)

        heavy_context_keys = [
            "equips_existing",
            "team_context_summary",
            "series_team_aparells",
            "inscripcio_aparells_excluded_map",
            "inscripcio_media_map",
            "media_matching_config",
        ]
        for key in heavy_context_keys:
            with self.subTest(context_key=key):
                self.assertNotIn(key, response.context)

        boot = response.context["inscripcions_page_boot"]
        self.assertIn("ids", boot)
        self.assertIn("flags", boot)
        self.assertIn("urls", boot)
        self.assertIn("initial", boot)
        self.assertNotIn("equipsExisting", boot["initial"])
        self.assertNotIn("teamContextSummary", boot["initial"])
        self.assertNotIn("seriesTeamAparells", boot["initial"])
        self.assertNotIn("inscripcioAparellsExcludedMap", boot["initial"])
        self.assertNotIn("inscripcioMediaMap", boot["initial"])
        self.assertNotIn("mediaMatchInscripcionsOptions", boot["initial"])
        self.assertIn("mediaMatchingConfig", boot["initial"])
        self.assertIn("mediaWorkspace", boot["urls"])
        self.assertIn("mediaSaveMatchingConfig", boot["urls"])
        self.assertIn("mediaReassign", boot["urls"])

    def test_column_filter_query_params_accept_canonical_and_legacy_prefixes(self):
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Marta Altres",
            entitat="Club Altres",
            ordre_sortida=2,
        )

        base_url = reverse("inscripcions_list", kwargs={"pk": self.comp.id})
        for param_name in ("cf_entitat", "cf__entitat"):
            with self.subTest(param_name=param_name):
                response = self.client.get(base_url, {param_name: "Club Smoke"})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context["column_filter_tokens_by_code"].get("entitat"), ["Club Smoke"])
                self.assertEqual(response.context["inscrits_filtered_count"], 1)
                self.assertContains(response, 'name="cf_entitat"', html=False)
                self.assertNotContains(response, 'name="cf__entitat"', html=False)

    def test_core_script_delegates_to_global_dialogs_without_preempting_them(self):
        package_root = Path(__file__).resolve().parents[2]
        source = (package_root / "templates" / "competicio" / "inscripcions" / "scripts" / "_core.html").read_text(encoding="utf-8")

        self.assertIn("function getDialogDelegate", source)
        self.assertIn("function ensureDialogGlobals", source)
        self.assertIn("const delegate = getDialogDelegate('showAlert', showAlert);", source)
        self.assertIn("const delegate = getDialogDelegate('showConfirm', showConfirm);", source)
        self.assertIn("const delegate = getDialogDelegate('showPrompt', showPrompt);", source)
        self.assertIn("if (typeof window.showAlert !== 'function') {", source)
        self.assertIn("if (typeof window.showConfirm !== 'function') {", source)
        self.assertIn("if (typeof window.showPrompt !== 'function') {", source)
        self.assertIn("ensureDialogGlobals();", source)
        self.assertIn("inscripcions:panel-activated", source)
        self.assertIn("inscripcions:panel-loaded", source)
        self.assertIn("function runOnceForPanel", source)
        self.assertIn("panelInitRuns.delete(panelKey);", source)
        self.assertIn("const btn = event.target.closest('.js-expand-tab-select');", source)
        self.assertIn("function readStoredUiState()", source)
        self.assertIn("const existingState = readStoredUiState();", source)
        self.assertIn("const shellState = captureUiState();", source)
        self.assertIn("Object.assign({}, existingState, shellState, extra || {})", source)
        self.assertIn("function updateUrlAndRefresh", source)
        self.assertIn("window.history.replaceState", source)
        self.assertIn("refreshHtmlFragments(", source)
        self.assertIn("updateUrlAndRefresh(url", source)
        self.assertIn("function getActiveGroupKey", source)
        self.assertIn("fragments.includes('table') ? getActiveGroupKey() : ''", source)
        self.assertIn("getActiveGroupKey,", source)
        self.assertIn("function clearExpandedGroupCardState()", source)
        self.assertIn("function isExpandedGroupCardInPanel(panelKey)", source)
        self.assertIn("function prepareExpandedGroupCardRefresh(panelKey)", source)
        self.assertIn("if (!expandedModalState.parent.isConnected) {", source)
        self.assertIn("const expandedGroupCardId = fragments.includes('panel') ? prepareExpandedGroupCardRefresh(activePanelKey) : '';", source)
        self.assertIn("setExpandedGroupCard('', { skipSave: true });", source)
        self.assertIn("const mode = app.selection.has(id) ? 'remove' : 'add';", source)
        self.assertIn("updateMainInscripcioSelection([id], mode);", source)
        self.assertNotIn("updateMainInscripcioSelection([id], checkbox.checked ? 'add' : 'remove');", source)
        self.assertNotIn("navigateWithUiState(url.toString())", source)
        self.assertRegex(source, r"window\.addEventListener\('beforeunload',\s*\(\)\s*=>\s*saveUiState\(\)\);")

    def test_core_ui_state_save_merges_existing_state_instead_of_overwriting_namespaces(self):
        package_root = Path(__file__).resolve().parents[2]
        source = (package_root / "templates" / "competicio" / "inscripcions" / "scripts" / "_core.html").read_text(encoding="utf-8")

        self.assertIn("function readStoredUiState()", source)
        self.assertIn("return state && typeof state === 'object' ? state : {};", source)
        self.assertIn("const existingState = readStoredUiState();", source)
        self.assertIn("const shellState = captureUiState();", source)
        self.assertIn("JSON.stringify(Object.assign({}, existingState, shellState, extra || {}))", source)
        self.assertIn("let state = readStoredUiState();", source)
        self.assertIn("const savedSelection = Array.isArray(state.selectedIds) ? state.selectedIds : null;", source)
        self.assertIn("if (savedSelection !== null) {", source)
        self.assertNotIn("sessionStorage.setItem(getUiStateKey(), JSON.stringify(captureUiState(extra)));", source)

    def test_sorting_script_uses_fragment_refresh_for_column_filters(self):
        package_root = Path(__file__).resolve().parents[2]
        source = (
            package_root / "templates" / "competicio" / "inscripcions" / "scripts" / "_sorting.html"
        ).read_text(encoding="utf-8")

        self.assertIn("function saveColumnFilterValues", source)
        self.assertIn("API.updateUrlAndRefresh", source)
        self.assertNotIn("API.navigateWithUiState(url.toString())", source)

    def test_groups_preview_script_refreshes_lightly_after_group_creation(self):
        package_root = Path(__file__).resolve().parents[2]
        source = (
            package_root / "templates" / "competicio" / "inscripcions" / "scripts" / "_groups_preview.html"
        ).read_text(encoding="utf-8")

        self.assertIn("postJson(groupsFromSortUrl, payload)", source)
        self.assertIn("API.refreshLightMutation({ includeActivePanel: false })", source)
        self.assertIn("window.__groupsWorkspaceApi.refresh", source)
        self.assertIn("function getMainSelectedInscripcioIds", source)
        self.assertIn("window.__inscripcionsSelectionApi.getSelectedIds()", source)
        self.assertIn("window.getSelectedInscripcioIds().map(String).filter(Boolean)", source)
        self.assertIn(": getMainSelectedInscripcioIds();", source)
        self.assertNotIn("reloadWithUiState()", source)

    def test_groups_workspace_syncs_external_selection_and_refreshes_list_after_manual_mutations(self):
        package_root = Path(__file__).resolve().parents[2]
        source = (
            package_root / "templates" / "competicio" / "inscripcions" / "scripts" / "_groups_workspace_script.html"
        ).read_text(encoding="utf-8")

        self.assertIn("inscripcions:selection-changed", source)
        self.assertIn("window.__groupsWorkspaceSelectionBridgeBound", source)
        self.assertIn("if (detail.source === 'groups_workspace') return;", source)
        self.assertIn("workspaceApi.setExternalSelection(ids, { source: 'main' });", source)
        self.assertIn("setExternalSelection: syncExternalSelection", source)
        self.assertIn("async function refreshInscripcionsListAfterGroupMutation(action)", source)
        self.assertIn("['create', 'assign', 'unassign'].includes(String(action || ''))", source)
        self.assertIn("const api = window.InscripcionsApp || null;", source)
        self.assertIn("await api.refreshLightMutation({ includeActivePanel: false });", source)
        self.assertIn("await refreshInscripcionsListAfterGroupMutation(action);", source)
        self.assertIn("async function refreshAfterGroupRename(details = {})", source)
        self.assertIn("refreshAfterRename: refreshAfterGroupRename,", source)
        self.assertIn("if (opts.openWorkspace === true) openWorkspaceCard();", source)
        self.assertIn("const viewportState = preserveViewport ? captureWorkspaceViewportState() : null;", source)
        self.assertIn("restoreWorkspaceViewportState(viewportState);", source)
        self.assertIn("await selectGroup(groupId, { openWorkspace: true, scroll: true, resetPage: !preservePage, forceReload: true });", source)
        self.assertIn("window.__inscripcionsPostGroupRenameRefresh", source)
        self.assertIn("groups-transform-target-search", source)
        self.assertIn("data-group-transform-toggle", source)
        self.assertIn("function applyGroupTransformTargetSearch()", source)
        self.assertNotIn("const opts = options || {};\n    openWorkspaceCard();", source)

    def test_group_rename_and_series_panel_scripts_use_selective_refresh_helpers(self):
        package_root = Path(__file__).resolve().parents[2]
        table_source = (
            package_root / "templates" / "competicio" / "inscripcions" / "scripts" / "_table.html"
        ).read_text(encoding="utf-8")
        sidebar_source = (
            package_root / "templates" / "competicio" / "inscripcions" / "_sidebar.html"
        ).read_text(encoding="utf-8")
        groups_source = (
            package_root / "templates" / "competicio" / "inscripcions" / "scripts" / "_groups_workspace_script.html"
        ).read_text(encoding="utf-8")
        team_source = (
            package_root / "templates" / "competicio" / "inscripcions" / "scripts" / "_team_workspace_script.html"
        ).read_text(encoding="utf-8")
        series_source = (
            package_root / "templates" / "competicio" / "inscripcions" / "scripts" / "_series_workspace_script.html"
        ).read_text(encoding="utf-8")

        self.assertIn("async function refreshGroupRenameAfterMutation(details = {})", table_source)
        self.assertIn("window.__inscripcionsPostGroupRenameRefresh = refreshGroupRenameAfterMutation;", table_source)
        self.assertIn("await refreshGroupRenameAfterMutation({ groupNum });", table_source)
        self.assertIn('id="groups-nav-badge"', sidebar_source)
        self.assertIn("text('groups-nav-badge', Number(summary.groups_total || 0));", groups_source)
        self.assertIn("async function refreshWorkspaceInPlace(options = {})", series_source)
        self.assertIn("refreshInPlace: refreshWorkspaceInPlace,", series_source)
        self.assertIn("const seriesApi = window.__seriesWorkspaceApi || null;", team_source)
        self.assertIn("await seriesApi.refreshInPlace();", team_source)

    def test_panel_scripts_expose_lazy_initializers_instead_of_eager_refreshes(self):
        package_root = Path(__file__).resolve().parents[2]
        groups_preview = (
            package_root / "templates" / "competicio" / "inscripcions" / "scripts" / "_groups_preview.html"
        ).read_text(encoding="utf-8")
        groups_wrapper = (
            package_root / "templates" / "competicio" / "inscripcions" / "scripts" / "_groups.html"
        ).read_text(encoding="utf-8")
        groups_workspace = (
            package_root / "templates" / "competicio" / "inscripcions" / "scripts" / "_groups_workspace_script.html"
        ).read_text(encoding="utf-8")
        teams_script = (
            package_root / "templates" / "competicio" / "inscripcions" / "scripts" / "_team_workspace_script.html"
        ).read_text(encoding="utf-8")
        teams_wrapper = (
            package_root / "templates" / "competicio" / "inscripcions" / "scripts" / "_teams.html"
        ).read_text(encoding="utf-8")
        series_script = (
            package_root / "templates" / "competicio" / "inscripcions" / "scripts" / "_series_workspace_script.html"
        ).read_text(encoding="utf-8")
        series_wrapper = (
            package_root / "templates" / "competicio" / "inscripcions" / "scripts" / "_series.html"
        ).read_text(encoding="utf-8")
        media_script = (
            package_root / "templates" / "competicio" / "inscripcions" / "scripts" / "_media.html"
        ).read_text(encoding="utf-8")

        self.assertIn("window.initGroupsPanel", groups_preview)
        self.assertIn("window.__groupsPanelRoot", groups_preview)
        self.assertNotIn("document.addEventListener('DOMContentLoaded', initGroupsPanel)", groups_preview)
        self.assertIn("window.initGroupsWorkspace = async function ()", groups_workspace)
        self.assertIn("window.__groupsWorkspaceRoot", groups_workspace)
        self.assertIn("await fetchWorkspace();", groups_workspace)
        self.assertIn("inscripcions:panel-activated", groups_wrapper)
        self.assertIn("inscripcions:panel-loaded", groups_wrapper)
        self.assertIn("window.initTeamsWorkspace = async function ()", teams_script)
        self.assertIn("window.__teamWorkspaceRoot", teams_script)
        self.assertIn("function setTeamPreviewLoading", teams_script)
        self.assertIn("function renderTeamPreview", teams_script)
        self.assertIn("window.__teamPreviewApi = {", teams_script)
        self.assertIn("inscripcions:panel-activated", teams_wrapper)
        self.assertIn("inscripcions:panel-loaded", teams_wrapper)
        self.assertIn("window.initTeamsWorkspace?.()", teams_wrapper)
        self.assertIn("window.initSeriesWorkspace = async function ()", series_script)
        self.assertIn("window.__seriesWorkspaceRoot", series_script)
        self.assertIn("function readCompAparellIdFromDom()", series_script)
        self.assertIn("document.getElementById('series-comp-aparell-select')?.value", series_script)
        self.assertNotIn("refreshWorkspace({ preservePage: false }).catch", series_script)
        self.assertIn("inscripcions:panel-activated", series_wrapper)
        self.assertIn("inscripcions:panel-loaded", series_wrapper)
        self.assertIn("window.initMediaWorkspace = initMediaWorkspace", media_script)
        self.assertIn("API.runOnceForPanel('media'", media_script)
        self.assertIn("inscripcions:panel-activated", media_script)
        self.assertIn("inscripcions:panel-loaded", media_script)

    def test_table_script_keeps_drag_drop_enabled_with_lazy_group_tabs(self):
        package_root = Path(__file__).resolve().parents[2]
        source = (
            package_root / "templates" / "competicio" / "inscripcions" / "scripts" / "_table.html"
        ).read_text(encoding="utf-8")

        self.assertIn("function getLazyGroupOrderPayload()", source)
        self.assertIn("group_ids_by_key", source)
        self.assertIn("idsFromPaneId(paneId)", source)
        self.assertIn("refreshCentralBlockKeepingActiveTab", source)
        self.assertIn("activeGroupKey: key", source)
        self.assertNotIn("if (hasLazyGroupTabs()) return;", source)

    def test_ajax_payload_contract_smoke_for_sorting_groups_and_media(self):
        sorting_response = self.client.post(
            reverse("inscripcions_filter_values", kwargs={"pk": self.comp.id}),
            data=json.dumps({"column_code": "entitat", "filters": {}}),
            content_type="application/json",
        )
        self.assertEqual(sorting_response.status_code, 200)
        sorting_payload = sorting_response.json()
        self.assertTrue(sorting_payload.get("ok"))
        self.assertEqual(sorting_payload.get("column_code"), "entitat")
        self.assertIn("values", sorting_payload)

        groups_response = self.client.post(
            reverse("groups_workspace", kwargs={"pk": self.comp.id}),
            data=json.dumps({"filters": {}, "page": 1, "page_size": 25}),
            content_type="application/json",
        )
        self.assertEqual(groups_response.status_code, 200)
        groups_payload = groups_response.json()
        self.assertTrue(groups_payload.get("ok"))
        self.assertIn("workspace", groups_payload)
        self.assertIn("summary", groups_payload)
        self.assertIn("candidates", groups_payload)

        media_response = self.client.post(
            reverse("inscripcions_media_match_preview", kwargs={"pk": self.comp.id}),
            data=json.dumps(
                {
                    "detail_level": "expanded",
                    "files": [
                        {
                            "key": "smoke-0",
                            "filename": "1 - LUCIA SMOKE.mp3",
                            "relative_path": "audio/1 - LUCIA SMOKE.mp3",
                            "size": 1234,
                        }
                    ]
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(media_response.status_code, 200)
        media_payload = media_response.json()
        self.assertTrue(media_payload.get("ok"))
        self.assertIn("rows", media_payload)
        self.assertIn("counts", media_payload)
        self.assertIn("config", media_payload)
        self.assertEqual(media_payload.get("detail_level"), "expanded")
        self.assertIn("breakdown", media_payload["rows"][0])
        self.assertNotIn("inscripcions_options", media_payload)

        media_workspace_response = self.client.post(
            reverse("inscripcions_media_workspace", kwargs={"pk": self.comp.id}),
            data=json.dumps({"filters": {"media_state": "all"}, "page": 1, "page_size": 25}),
            content_type="application/json",
        )
        self.assertEqual(media_workspace_response.status_code, 200)
        media_workspace_payload = media_workspace_response.json()
        self.assertTrue(media_workspace_payload.get("ok"))
        self.assertIn("workspace", media_workspace_payload)
        self.assertIn("rows", media_workspace_payload["workspace"])

        team_app = self._create_aparell("TEAMSMOKE", "Team Smoke")
        team_app.competition_unit = Aparell.CompetitionUnit.TEAM
        team_app.save(update_fields=["competition_unit"])
        comp_app = self._create_comp_aparell(self.comp, team_app, ordre=1)

        series_response = self.client.post(
            reverse("inscripcions_series_equips_workspace", kwargs={"pk": self.comp.id}),
            data=json.dumps({"comp_aparell_id": comp_app.id}),
            content_type="application/json",
        )
        self.assertEqual(series_response.status_code, 200)
        series_payload = series_response.json()
        self.assertTrue(series_payload.get("ok"))
        self.assertIn("workspace", series_payload)


