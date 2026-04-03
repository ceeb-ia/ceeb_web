import importlib
import json
from pathlib import Path

from django.test import TestCase
from django.urls import resolve, reverse

from ..models import Competicio, CompeticioMembership, Inscripcio
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
            "competicions_trampoli.views_inscripcions_listing",
            "competicions_trampoli.views_inscripcions_sorting",
            "competicions_trampoli.views_inscripcions_groups",
            "competicions_trampoli.views_inscripcions_media",
            "competicions_trampoli.inscripcions_views_shared",
        ]
        for module_name in modules:
            importlib.import_module(module_name)

        package_root = Path(__file__).resolve().parents[1]
        for rel_path in [
            "views_inscripcions_listing.py",
            "views_inscripcions_sorting.py",
            "views_inscripcions_groups.py",
            "views_inscripcions_media.py",
        ]:
            source = (package_root / rel_path).read_text(encoding="utf-8")
            self.assertNotIn("from .views import", source)
            self.assertNotIn("from .inscripcions_list_new import", source)

        shared_source = (package_root / "inscripcions_views_shared.py").read_text(encoding="utf-8")
        self.assertNotIn("from .views import", shared_source)

    def test_legacy_files_are_facades_only(self):
        package_root = Path(__file__).resolve().parents[1]
        views_source = (package_root / "views.py").read_text(encoding="utf-8")
        legacy_list_source = (package_root / "inscripcions_list_new.py").read_text(encoding="utf-8")

        self.assertIn("Compatibility facade", views_source)
        self.assertIn("from .views_inscripcions_sorting import", views_source)
        self.assertNotIn("def inscripcions_sort_apply", views_source)
        self.assertNotIn("class InscripcionsListView(", views_source)

        self.assertIn("Compatibility facade", legacy_list_source)
        self.assertIn("from .views_inscripcions_listing import", legacy_list_source)
        self.assertNotIn("class InscripcionsListNewView(", legacy_list_source)
        self.assertNotIn("def inscripcions_media_upload", legacy_list_source)

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
        self.assertTemplateUsed(response, "competicio/inscricpions_list_new.html")
        self.assertIn("selected_table_columns", response.context)
        self.assertIn("sort_field_options", response.context)
        self.assertIn("table_colspan", response.context)

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
