import importlib
import json
from pathlib import Path
from datetime import date, datetime
from io import BytesIO

from django.test import TestCase
from django.urls import resolve, reverse
from openpyxl import Workbook

from ..models import Competicio, CompeticioMembership, Inscripcio, InscripcioMedia
from ..services.inscripcions.import_excel import importar_inscripcions_excel
from ..views.inscripcions.listing import _serialize_listing_media_item
from .base import _BaseTrampoliDataMixin


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

        package_root = Path(__file__).resolve().parents[1]
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
        package_root = Path(__file__).resolve().parents[1]
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
            "groups_workspace_legacy",
            "groups_detail_legacy",
            "groups_preview_legacy",
            "groups_create_legacy",
            "groups_assign_legacy",
            "groups_unassign_legacy",
            "groups_delete_legacy",
            "groups_delete_all_legacy",
            "groups_delete_empty_legacy",
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
            "inscripcions_media_match_preview",
            "inscripcions_media_match_apply",
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
        self.assertContains(response, 'id="btn-groups-preview-confirm"', html=False)
        self.assertContains(response, 'id="btn-groups-preview-clear"', html=False)
        self.assertContains(response, 'id="btn-groups-preview-count"', html=False)
        self.assertContains(response, 'id="btn-groups-create-count"', html=False)
        self.assertContains(response, 'id="btn-groups-preview-size"', html=False)
        self.assertContains(response, 'id="btn-groups-create-size"', html=False)
        self.assertContains(response, 'id="btn-groups-preview-range-balanced"', html=False)
        self.assertContains(response, 'id="btn-groups-create-range-balanced"', html=False)
        self.assertContains(response, 'id="btn-groups-preview-count-range"', html=False)
        self.assertContains(response, 'id="btn-groups-create-count-range"', html=False)
        self.assertContains(response, 'id="btn-groups-preview-per-bucket"', html=False)
        self.assertContains(response, 'id="btn-groups-create-per-bucket"', html=False)
        self.assertContains(response, '/static/js/vendor/Sortable.min.js', html=False)
        self.assertNotContains(response, 'cdn.jsdelivr.net/npm/sortablejs', html=False)
        self.assertNotIn("mediaMatchInscripcionsOptions", response.context["inscripcions_page_boot"]["initial"])
        self.assertNotContains(response, '"mediaMatchInscripcionsOptions":', html=False)

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
        package_root = Path(__file__).resolve().parents[1]
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
        self.assertIn("function runOnceForPanel", source)
        self.assertIn("function readStoredUiState()", source)
        self.assertIn("const existingState = readStoredUiState();", source)
        self.assertIn("const shellState = captureUiState();", source)
        self.assertIn("Object.assign({}, existingState, shellState, extra || {})", source)
        self.assertRegex(
            source,
            r"function reloadWithUiState\(extra\)[\s\S]*saveUiState\(extra\);[\s\S]*window\.location\.reload\(\);",
        )
        self.assertRegex(source, r"window\.addEventListener\('beforeunload',\s*\(\)\s*=>\s*saveUiState\(\)\);")

    def test_core_ui_state_save_merges_existing_state_instead_of_overwriting_namespaces(self):
        package_root = Path(__file__).resolve().parents[1]
        source = (package_root / "templates" / "competicio" / "inscripcions" / "scripts" / "_core.html").read_text(encoding="utf-8")

        self.assertIn("function readStoredUiState()", source)
        self.assertIn("return state && typeof state === 'object' ? state : {};", source)
        self.assertIn("const existingState = readStoredUiState();", source)
        self.assertIn("const shellState = captureUiState();", source)
        self.assertIn("JSON.stringify(Object.assign({}, existingState, shellState, extra || {}))", source)
        self.assertIn("let state = readStoredUiState();", source)
        self.assertNotIn("sessionStorage.setItem(getUiStateKey(), JSON.stringify(captureUiState(extra)));", source)

    def test_panel_scripts_expose_lazy_initializers_instead_of_eager_refreshes(self):
        package_root = Path(__file__).resolve().parents[1]
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

        self.assertIn("window.initGroupsPanel", groups_preview)
        self.assertNotIn("document.addEventListener('DOMContentLoaded', initGroupsPanel)", groups_preview)
        self.assertIn("window.initGroupsWorkspace = async function ()", groups_workspace)
        self.assertIn("await fetchWorkspace();", groups_workspace)
        self.assertIn("inscripcions:panel-activated", groups_wrapper)
        self.assertIn("window.initTeamsWorkspace = async function ()", teams_script)
        self.assertIn("function setTeamPreviewLoading", teams_script)
        self.assertIn("function renderTeamPreview", teams_script)
        self.assertIn("window.__teamPreviewApi = {", teams_script)
        self.assertIn("inscripcions:panel-activated", teams_wrapper)
        self.assertIn("window.initTeamsWorkspace?.()", teams_wrapper)
        self.assertIn("window.initSeriesWorkspace = async function ()", series_script)
        self.assertNotIn("refreshWorkspace({ preservePage: false }).catch", series_script)
        self.assertIn("inscripcions:panel-activated", series_wrapper)

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
        self.assertIn("inscripcions_options", media_payload)


class InscripcionsExcelImportServiceTests(_BaseTrampoliDataMixin, TestCase):
    def _build_workbook_file(self, headers, row):
        wb = Workbook()
        ws = wb.active
        ws.append(headers)
        ws.append(row)
        content = BytesIO()
        wb.save(content)
        content.seek(0)
        return content

    def test_import_accepts_datetime_values_in_extra_columns_and_real_headers(self):
        comp = self._create_competicio("Comp Import Excel")
        fitxer = self._build_workbook_file(
            [
                "Id Adjunt",
                "Id Inscripció",
                "Lliga",
                "Grup",
                "Club",
                "Nom",
                "Cognoms",
                "Data Naixement",
                "Competició",
                "Estat inscripció",
                "Data Introducció",
                "Modalitat",
                "Categoria",
                "SubCategoria",
                "Link Adjunt",
            ],
            [
                991,
                225,
                "CEEB",
                "A",
                "Club Example",
                "Laia",
                "Garcia",
                date(2014, 5, 3),
                "Competició prova",
                "Pendent",
                datetime(2026, 4, 5, 10, 30, 15),
                "Individual",
                "Benjamí",
                "Nivell 1",
                "https://example.invalid/file",
            ],
        )

        result = importar_inscripcions_excel(fitxer, comp)

        self.assertEqual(result["errors"], 0)
        self.assertEqual(result["creats"], 1)

        inscripcio = Inscripcio.objects.get(competicio=comp)
        self.assertEqual(inscripcio.nom_i_cognoms, "Laia Garcia")
        self.assertEqual(inscripcio.entitat, "Club Example")
        self.assertEqual(inscripcio.categoria, "Benjamí")
        self.assertEqual(inscripcio.subcategoria, "Nivell 1")
        self.assertEqual(inscripcio.data_naixement, date(2014, 5, 3))
        self.assertEqual(inscripcio.extra["data_introduccio"], "2026-04-05T10:30:15")
        self.assertEqual(inscripcio.extra["modalitat"], "Individual")
        self.assertEqual(inscripcio.extra["excel__grup"], "A")


class InscripcionsListingMediaUrlTests(_BaseTrampoliDataMixin, TestCase):
    def test_listing_media_item_uses_registered_route(self):
        item = InscripcioMedia(
            id=9,
            competicio_id=43,
            inscripcio_id=12,
            tipus=InscripcioMedia.Tipus.AUDIO,
            mime_type="audio/mpeg",
            original_filename="prova.mp3",
            file_size_bytes=123,
            is_primary=True,
            source=InscripcioMedia.Source.MANUAL,
        )

        payload = _serialize_listing_media_item(item)

        self.assertEqual(
            payload["url"],
            reverse("inscripcions_media_file", kwargs={"pk": 43, "media_id": 9}),
        )
