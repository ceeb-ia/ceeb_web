import json
import re
from io import BytesIO, StringIO
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.sessions.backends.db import SessionStore
from django.core.management import call_command
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.models import Max
from django.test import RequestFactory, TestCase
from django.urls import Resolver404, resolve, reverse
from django.utils import timezone
from openpyxl import load_workbook

from ceeb_web.auth_groups import GLOBAL_AUTH_GROUPS

from ... import live_cache
from ...access import user_has_competicio_capability
from ...forms import CompeticioAparellForm
from ...models import (
    Competicio,
    Equip,
    EquipContext,
    GrupCompeticio,
    Inscripcio,
    InscripcioEquipAssignacio,
    InscripcioMedia,
)
from ...models.judging import (
    JudgeConversation,
    JudgeConversationMessage,
    JudgeDeviceToken,
    PublicLiveToken,
)
from ...models.classificacions import ClassificacioConfig, ClassificacioTemplateGlobal
from ...models.rotacions import (
    RotacioAssignacio,
    RotacioAssignacioGrup,
    RotacioAssignacioSerieEquip,
    RotacioEstacio,
    RotacioFranja,
)
from ...models.scoring import (
    ScoringSchema,
    ScoreEntry,
    ScoreEntryVideo,
    ScoreEntryVideoEvent,
    SerieEquip,
    SerieEquipItem,
    TeamScoreEntry,
    TeamCompetitiveSubject,
    TeamScoreEntryVideo,
    TeamScoreEntryVideoEvent,
)
from ...models.competicio import (
    Aparell,
    CompeticioAparell,
    CompeticioAparellEquipContextSource,
    InscripcioAparellExclusio,
)
from ...models import CompeticioMembership
from ...scoring_engine import ScoringEngine
from ...services.inscripcions.groups import renumber_groups_for_competicio
from ...services.inscripcions.sorting import (
    _split_custom_sort_tokens,
    sort_records_by_field_stable,
)
from ...services.inscripcions.history import (
    apply_inscripcions_history_snapshot,
    capture_inscripcions_history_snapshot,
)
from ...services.inscripcions.queries import (
    COLUMN_FILTER_EMPTY_TOKEN,
    _build_inscripcions_filtered_qs,
    build_inscripcions_sort_context_key,
    get_competicio_custom_sort_rank_map,
)
from ...services.classificacions.builder import scoreable_codes_by_app_id as _scoreable_codes_by_app_id
from ...services.classificacions.compute import DEFAULT_SCHEMA, compute_classificacio
from ...services.classificacions.export import _normalize_excel_cell
from ...services.classificacions.partitions import normalize_schema_legacy_team_birth_partition
from ...services.classificacions.validation import (
    build_metric_meta_for_comp_aparell as _build_metric_meta_for_comp_aparell,
    build_scoreable_meta_for_schema as _build_scoreable_meta_for_schema,
    validate_particions_schema as _validate_particions_schema,
    validate_schema_for_competicio as _validate_schema_for_competicio,
)
from ...services.classificacions.classificacio_templates import (
    normalize_particions_schema as _normalize_particions_schema,
    schema_to_template_schema as _schema_to_template_schema,
    template_schema_to_competicio_schema as _template_schema_to_competicio_schema,
)
from ...views.classificacions.builder import ClassificacionsHome
from ...services.shared.competition_groups import (
    assign_groups_by_display_num,
    compact_competition_order_for_group,
    ensure_group_for_display_num,
    get_group_maps,
    get_group_participant_counts,
    get_out_of_program_group_ids,
    get_programmed_group_ids,
    group_label,
    move_inscripcio_to_group,
    next_group_display_num,
)
from ...services.scoring.team_scoring import (
    build_permission_label,
    build_team_subjects_for_comp_aparell,
    resolve_permission_runtime_entries,
    runtime_schema_for_comp_aparell,
)
from ...services.teams.team_series import safe_deactivate_empty_serie
from ...views.judge.admin import _member_slot_choices, _validate_permission_row
from ...templatetags.competicio_extras import (
    DEFAULT_COMPETITION_BACKGROUND,
    get_competicio_background_url_from_request,
)

from ..base import _BaseTrampoliDataMixin


class EquipPreviewUiTests(_BaseTrampoliDataMixin, TestCase):
    def setUp(self):
        self.comp = self._create_competicio("Comp Team Preview UI")
        self.base_ctx = self._ensure_native_equip_context(self.comp)
        self.ctx = EquipContext.objects.create(competicio=self.comp, code="finals", nom="Finals")
        self.team_aparell = Aparell.objects.create(
            codi="TEAMCTX",
            nom="Aparell Equip",
            competition_unit=Aparell.CompetitionUnit.TEAM,
            actiu=True,
            created_by=self._ensure_default_aparell_owner(),
        )
        self.comp_team_aparell = self._create_comp_aparell(self.comp, self.team_aparell, ordre=1, actiu=True)
        self.team_existing_native = Equip.objects.create(competicio=self.comp, context=self.base_ctx, nom="Club A")
        self.team_existing = Equip.objects.create(competicio=self.comp, context=self.ctx, nom="Club A")
        self.team_other = Equip.objects.create(competicio=self.comp, context=self.base_ctx, nom="Alt Equip")

        self.ins_keep = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Anna Keep",
            entitat="Club A",
            ordre_sortida=1,
        )
        self.ins_move = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Berta Move",
            entitat="Club A",
            ordre_sortida=2,
        )
        self.ins_new = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Carla New",
            entitat="Club C",
            ordre_sortida=3,
        )
        self.ins_ctx = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Dina Context",
            entitat="Club A",
            ordre_sortida=4,
        )
        InscripcioEquipAssignacio.objects.create(
            competicio=self.comp,
            context=self.base_ctx,
            inscripcio=self.ins_keep,
            equip=self.team_existing_native,
        )
        InscripcioEquipAssignacio.objects.create(
            competicio=self.comp,
            context=self.base_ctx,
            inscripcio=self.ins_move,
            equip=self.team_other,
        )
        InscripcioEquipAssignacio.objects.create(
            competicio=self.comp,
            context=self.base_ctx,
            inscripcio=self.ins_ctx,
            equip=self.team_other,
        )
        InscripcioEquipAssignacio.objects.create(
            competicio=self.comp,
            context=self.ctx,
            inscripcio=self.ins_ctx,
            equip=self.team_existing,
        )

        User = get_user_model()
        self.user = User.objects.create_user(
            username="equip_preview_user",
            password="testpass123",
            email="equip-preview@example.com",
        )
        CompeticioMembership.objects.create(
            user=self.user,
            competicio=self.comp,
            role=CompeticioMembership.Role.OWNER,
            is_active=True,
        )
        self.client.force_login(self.user)

    def test_inscripcions_list_renders_expandable_team_workbench(self):
        response = self.client.get(reverse("inscripcions_list", kwargs={"pk": self.comp.id}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="teams-main-card"')
        self.assertContains(response, 'data-expand-target="teams-main-card"')
        self.assertContains(response, 'id="team-workspace-shell"')
        self.assertContains(response, 'id="btn-team-workspace-board-mode"')
        self.assertContains(response, 'id="team-filter-q"')
        self.assertContains(response, 'id="btn-team-workspace-preview"')
        self.assertContains(response, 'id="team-auto-buckets-grid"')
        self.assertContains(response, 'id="btn-team-auto-buckets-all"')
        self.assertContains(response, 'id="btn-team-auto-buckets-none"')
        self.assertContains(response, 'id="team-preview-status"')
        self.assertContains(response, 'id="team-preview-existing-list"')
        self.assertContains(response, 'id="team-preview-list"')
        self.assertContains(response, 'id="team-context-unassigned-dropzone"')
        self.assertContains(response, 'id="team-board-filter-q"')
        self.assertContains(response, 'id="team-board-filter-categoria"')
        self.assertContains(response, 'id="team-board-filter-count"')
        self.assertContains(response, 'id="btn-team-board-filters-toggle"')
        self.assertContains(response, 'id="team-board-filters-panel"')
        self.assertContains(response, "Flux complet d'equips")

    def test_inscripcions_list_renders_team_context_metric_anchors(self):
        response = self.client.get(reverse("inscripcions_list", kwargs={"pk": self.comp.id}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="team-context-metric-teams-with-members"')
        self.assertContains(response, 'id="team-context-metric-assigned"')
        self.assertContains(response, 'id="team-context-metric-unassigned"')
        self.assertContains(response, 'id="team-context-metric-total"')

    def test_inscripcions_list_renders_team_compact_actions(self):
        response = self.client.get(reverse("inscripcions_list", kwargs={"pk": self.comp.id}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="team-workspace-context-select"')
        self.assertContains(response, 'id="btn-team-workspace-context-create"')
        self.assertContains(response, 'id="btn-team-workspace-context-rename"')
        self.assertContains(response, 'id="btn-team-workspace-context-delete"')
        self.assertContains(response, 'id="btn-team-context-sources-save"')
        self.assertContains(response, 'id="btn-team-workspace-preview"')
        self.assertContains(response, 'id="btn-team-workspace-create-manual"')
        self.assertContains(response, 'id="btn-team-workspace-unassign"')
        self.assertContains(response, 'id="team-context-teams-list"')

    def test_inscripcions_list_renders_series_team_panel_navigation_and_shortcut(self):
        response = self.client.get(reverse("inscripcions_list", kwargs={"pk": self.comp.id}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-panel-target="series-equips"')
        self.assertContains(response, 'id="panel-series-equips"')
        self.assertContains(response, 'id="series-workspace-shell"')
        self.assertContains(response, 'id="series-board-list"')
        self.assertContains(response, 'id="btn-series-workspace-delete-empty"')
        self.assertContains(response, "SÃ¨ries d'equip")
        self.assertContains(response, "Obrir sÃ¨ries d'equip")

    def test_inscripcions_list_renders_bulk_empty_cleanup_buttons(self):
        response = self.client.get(reverse("inscripcions_list", kwargs={"pk": self.comp.id}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="btn-groups-delete-empty"')
        self.assertContains(response, 'id="btn-groups-delete-all"')
        self.assertContains(response, 'id="btn-team-workspace-delete-empty"')
        self.assertContains(response, 'id="btn-series-workspace-delete-empty"')

    def test_inscripcions_list_exposes_shared_selection_api_for_workspaces(self):
        response = self.client.get(reverse("inscripcions_list", kwargs={"pk": self.comp.id}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "window.__inscripcionsSelectionApi")
        self.assertContains(response, "source: 'groups_workspace'")
        self.assertContains(response, "source: 'team_workspace'")

    def test_inscripcions_list_renders_sidebar_badges_for_teams_and_series_without_loading_text(self):
        response = self.client.get(reverse("inscripcions_list", kwargs={"pk": self.comp.id}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="teams-nav-badge"')
        self.assertContains(response, 'id="teams-nav-badge">1<', html=False)
        self.assertContains(response, 'id="series-nav-badge"')
        self.assertContains(response, 'id="series-nav-badge">0<', html=False)
        self.assertNotContains(response, '<span class="badge badge-light">Carregant</span>', html=False)

    def test_inscripcions_list_exposes_team_workspace_selection_bridge(self):
        response = self.client.get(reverse("inscripcions_list", kwargs={"pk": self.comp.id}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "__teamsWorkspaceSelectionBridgeBound")
        self.assertContains(response, "detail.source === 'team_workspace'")
        self.assertContains(response, "workspaceApi.setExternalSelection(ids, { source: 'main' })")

    def test_equips_workspace_returns_context_summary_candidates_and_filters(self):
        response = self.client.post(
            reverse("inscripcions_equips_workspace", kwargs={"pk": self.comp.id}),
            data=json.dumps(
                {
                    "context_code": "finals",
                    "filters": {
                        "q": "",
                        "categoria": "",
                        "subcategoria": "",
                        "entitat": "Club A",
                        "assignment_state": "assigned",
                        "equip_id": str(self.team_existing.id),
                    },
                    "page": 1,
                    "page_size": 25,
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload.get("ok"))
        self.assertEqual(payload.get("context_code"), "finals")
        self.assertEqual(payload.get("context", {}).get("nom"), "Finals")
        self.assertEqual(payload.get("summary", {}).get("assigned_count"), 1)
        self.assertEqual(payload.get("summary", {}).get("filtered_count"), 1)
        self.assertEqual(payload.get("candidates", {}).get("total"), 1)
        self.assertEqual(payload.get("candidates", {}).get("items", [])[0].get("nom"), "Dina Context")
        self.assertEqual(payload.get("candidates", {}).get("items", [])[0].get("current_team_name"), "Club A")
        self.assertTrue(any(row.get("name") == "Club A" for row in (payload.get("filter_options", {}).get("teams") or [])))
        self.assertTrue(any(ctx.get("code") == "finals" for ctx in (payload.get("contexts") or [])))
        teams_by_name = {row.get("nom"): row for row in (payload.get("teams") or [])}
        self.assertEqual([m.get("nom") for m in teams_by_name["Club A"]["members"]], ["Dina Context"])
        self.assertEqual(teams_by_name["Club A"]["members"][0]["native_team_name"], "Alt Equip")

    def test_equips_workspace_preserves_column_filters(self):
        response = self.client.post(
            reverse("inscripcions_equips_workspace", kwargs={"pk": self.comp.id}),
            data=json.dumps(
                {
                    "context_code": "finals",
                    "filters": {
                        "q": "",
                        "categoria": "",
                        "subcategoria": "",
                        "entitat": "",
                        "column_filters": {"entitat": ["Club C"]},
                        "assignment_state": "all",
                        "equip_id": "",
                    },
                    "page": 1,
                    "page_size": 25,
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload.get("ok"))
        self.assertEqual(payload.get("filters", {}).get("column_filters"), {"entitat": ["Club C"]})
        self.assertEqual(payload.get("summary", {}).get("filtered_count"), 1)
        self.assertEqual(
            [row.get("nom") for row in (payload.get("candidates", {}).get("items") or [])],
            ["Carla New"],
        )

    def test_equips_workspace_filter_options_keep_other_categories_visible_after_filtering_one(self):
        self.ins_keep.categoria = "Alevi"
        self.ins_keep.save(update_fields=["categoria"])
        self.ins_move.categoria = "Infantil"
        self.ins_move.save(update_fields=["categoria"])
        self.ins_new.categoria = "Juvenil"
        self.ins_new.save(update_fields=["categoria"])

        response = self.client.post(
            reverse("inscripcions_equips_workspace", kwargs={"pk": self.comp.id}),
            data=json.dumps(
                {
                    "context_code": "finals",
                    "filters": {
                        "q": "",
                        "categoria": "",
                        "subcategoria": "",
                        "entitat": "",
                        "categories": ["Alevi"],
                        "assignment_state": "all",
                        "equip_id": "",
                    },
                    "page": 1,
                    "page_size": 25,
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload.get("ok"))
        self.assertEqual(
            sorted(payload.get("filter_options", {}).get("categories") or []),
            ["Alevi", "Infantil", "Juvenil"],
        )
        self.assertEqual(
            [row.get("nom") for row in (payload.get("candidates", {}).get("items") or [])],
            ["Anna Keep"],
        )

    def test_equips_workspace_filter_options_keep_other_entitats_visible_after_filtering_one(self):
        response = self.client.post(
            reverse("inscripcions_equips_workspace", kwargs={"pk": self.comp.id}),
            data=json.dumps(
                {
                    "context_code": "finals",
                    "filters": {
                        "q": "",
                        "categoria": "",
                        "subcategoria": "",
                        "entitat": "",
                        "entitats": ["Club C"],
                        "assignment_state": "all",
                        "equip_id": "",
                    },
                    "page": 1,
                    "page_size": 25,
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload.get("ok"))
        self.assertEqual(
            sorted(payload.get("filter_options", {}).get("entitats") or []),
            ["Club A", "Club C"],
        )
        self.assertEqual(
            [row.get("nom") for row in (payload.get("candidates", {}).get("items") or [])],
            ["Carla New"],
        )

    def test_equips_workspace_filter_options_keep_assignment_scope_when_clearing_facets(self):
        self.ins_keep.categoria = "Alevi"
        self.ins_keep.save(update_fields=["categoria"])
        self.ins_ctx.categoria = "Senior"
        self.ins_ctx.save(update_fields=["categoria"])

        response = self.client.post(
            reverse("inscripcions_equips_workspace", kwargs={"pk": self.comp.id}),
            data=json.dumps(
                {
                    "context_code": "finals",
                    "filters": {
                        "q": "",
                        "categoria": "",
                        "subcategoria": "",
                        "entitat": "",
                        "categories": ["Alevi"],
                        "assignment_state": "assigned",
                        "equip_ids": [str(self.team_existing.id)],
                    },
                    "page": 1,
                    "page_size": 25,
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload.get("ok"))
        self.assertEqual(payload.get("candidates", {}).get("total"), 0)
        self.assertEqual(payload.get("filter_options", {}).get("categories") or [], ["Senior"])

    def test_equips_workspace_can_resolve_filtered_ids_for_full_selection_strip(self):
        response = self.client.post(
            reverse("inscripcions_equips_workspace", kwargs={"pk": self.comp.id}),
            data=json.dumps(
                {
                    "context_code": "finals",
                    "operation": "resolve_filtered_ids",
                    "filters": {
                        "q": "",
                        "categories": [],
                        "subcategories": [],
                        "entitats": [],
                        "assignment_state": "assigned",
                        "equip_ids": [str(self.team_existing.id)],
                    },
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload.get("ok"))
        self.assertEqual(payload.get("operation"), "resolve_filtered_ids")
        self.assertEqual(payload.get("target_ids"), [self.ins_ctx.id])
        self.assertEqual(payload.get("total"), 1)

    def test_equips_workspace_can_resolve_auto_context_from_selected_ids(self):
        response = self.client.post(
            reverse("inscripcions_equips_workspace", kwargs={"pk": self.comp.id}),
            data=json.dumps(
                {
                    "context_code": "finals",
                    "operation": "resolve_auto_context",
                    "selected_ids": [self.ins_keep.id, self.ins_new.id],
                    "filters": {
                        "q": "",
                        "categoria": "",
                        "subcategoria": "",
                        "entitat": "",
                    },
                    "fields": ["entitat"],
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload.get("ok"))
        self.assertEqual(payload.get("operation"), "resolve_auto_context")
        self.assertEqual(payload.get("target_scope"), "selected")
        self.assertEqual(int(payload.get("target_count") or 0), 2)
        self.assertEqual(int(payload.get("buckets_total") or 0), 2)
        self.assertEqual(
            sorted(bucket.get("label") for bucket in (payload.get("buckets") or [])),
            ["Club A", "Club C"],
        )
        self.assertEqual(len(payload.get("default_bucket_keys") or []), 2)

    def test_equips_workspace_can_resolve_auto_context_from_filtered_rows(self):
        self.ins_keep.categoria = "Alevi"
        self.ins_keep.save(update_fields=["categoria"])
        self.ins_move.categoria = "Infantil"
        self.ins_move.save(update_fields=["categoria"])
        self.ins_ctx.categoria = "Alevi"
        self.ins_ctx.save(update_fields=["categoria"])

        response = self.client.post(
            reverse("inscripcions_equips_workspace", kwargs={"pk": self.comp.id}),
            data=json.dumps(
                {
                    "context_code": "finals",
                    "operation": "resolve_auto_context",
                    "selected_ids": [],
                    "filters": {
                        "q": "",
                        "categoria": "",
                        "subcategoria": "",
                        "entitat": "",
                        "column_filters": {"entitat": ["Club A"]},
                    },
                    "fields": ["categoria"],
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload.get("ok"))
        self.assertEqual(payload.get("target_scope"), "filtered")
        self.assertEqual(int(payload.get("target_count") or 0), 3)
        self.assertEqual(int(payload.get("buckets_total") or 0), 2)
        self.assertEqual(
            sorted(bucket.get("label") for bucket in (payload.get("buckets") or [])),
            ["Alevi", "Infantil"],
        )

    def test_equips_workspace_resolve_auto_context_supports_excel_fields(self):
        self.comp.inscripcions_schema = {
            "columns": [
                {"code": "excel__bloc", "label": "Bloc", "kind": "extra"},
            ]
        }
        self.comp.save(update_fields=["inscripcions_schema"])
        self.ins_keep.extra = {"excel__bloc": "Nord"}
        self.ins_keep.save(update_fields=["extra"])
        self.ins_new.extra = {"excel__bloc": "Sud"}
        self.ins_new.save(update_fields=["extra"])

        response = self.client.post(
            reverse("inscripcions_equips_workspace", kwargs={"pk": self.comp.id}),
            data=json.dumps(
                {
                    "context_code": "native",
                    "operation": "resolve_auto_context",
                    "selected_ids": [self.ins_keep.id, self.ins_new.id],
                    "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                    "fields": ["excel__bloc"],
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload.get("ok"))
        self.assertEqual(
            sorted(bucket.get("label") for bucket in (payload.get("buckets") or [])),
            ["Nord", "Sud"],
        )

    def test_equips_workspace_team_members_ignore_candidate_filters_and_keep_stable_order(self):
        ins_early = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Aina Context",
            entitat="Club Z",
            ordre_sortida=0,
            equip=self.team_other,
        )
        InscripcioEquipAssignacio.objects.create(
            competicio=self.comp,
            context=self.ctx,
            inscripcio=ins_early,
            equip=self.team_existing,
        )

        response = self.client.post(
            reverse("inscripcions_equips_workspace", kwargs={"pk": self.comp.id}),
            data=json.dumps(
                {
                    "context_code": "finals",
                    "filters": {
                        "q": "",
                        "categoria": "",
                        "subcategoria": "",
                        "entitat": "Club C",
                        "assignment_state": "all",
                        "equip_id": "",
                    },
                    "page": 1,
                    "page_size": 25,
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload.get("candidates", {}).get("total"), 1)
        self.assertEqual(payload.get("candidates", {}).get("items", [])[0].get("nom"), "Carla New")
        teams_by_name = {row.get("nom"): row for row in (payload.get("teams") or [])}
        self.assertEqual(
            [m.get("nom") for m in teams_by_name["Club A"]["members"]],
            ["Aina Context", "Dina Context"],
        )

    def test_equips_workspace_returns_native_team_members_ordered(self):
        assignacio = InscripcioEquipAssignacio.objects.get(
            competicio=self.comp,
            context=self.base_ctx,
            inscripcio=self.ins_ctx,
        )
        assignacio.equip = self.team_existing_native
        assignacio.save(update_fields=["equip", "updated_at"])

        response = self.client.post(
            reverse("inscripcions_equips_workspace", kwargs={"pk": self.comp.id}),
            data=json.dumps(
                {
                    "context_code": "native",
                    "filters": {
                        "q": "",
                        "categoria": "",
                        "subcategoria": "",
                        "entitat": "",
                        "assignment_state": "all",
                        "equip_id": "",
                    },
                    "page": 1,
                    "page_size": 25,
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        teams_by_name = {row.get("nom"): row for row in (payload.get("teams") or [])}
        self.assertEqual(
            [m.get("nom") for m in teams_by_name["Club A"]["members"]],
            ["Anna Keep", "Dina Context"],
        )

    def test_equips_workspace_members_refresh_after_assign_and_unassign(self):
        assign_response = self.client.post(
            reverse("inscripcions_equips_assign", kwargs={"pk": self.comp.id}),
            data=json.dumps(
                {
                    "context_code": "finals",
                    "equip_id": self.team_existing.id,
                    "inscripcio_ids": [self.ins_new.id],
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(assign_response.status_code, 200)

        workspace_after_assign = self.client.post(
            reverse("inscripcions_equips_workspace", kwargs={"pk": self.comp.id}),
            data=json.dumps(
                {
                    "context_code": "finals",
                    "filters": {
                        "q": "",
                        "categoria": "",
                        "subcategoria": "",
                        "entitat": "",
                        "assignment_state": "all",
                        "equip_id": "",
                    },
                    "page": 1,
                    "page_size": 25,
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(workspace_after_assign.status_code, 200)
        teams_by_name = {row.get("nom"): row for row in (workspace_after_assign.json().get("teams") or [])}
        self.assertEqual(
            [m.get("nom") for m in teams_by_name["Club A"]["members"]],
            ["Carla New", "Dina Context"],
        )

        unassign_response = self.client.post(
            reverse("inscripcions_equips_unassign", kwargs={"pk": self.comp.id}),
            data=json.dumps(
                {
                    "context_code": "finals",
                    "inscripcio_ids": [self.ins_new.id],
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(unassign_response.status_code, 200)

        workspace_after_unassign = self.client.post(
            reverse("inscripcions_equips_workspace", kwargs={"pk": self.comp.id}),
            data=json.dumps(
                {
                    "context_code": "finals",
                    "filters": {
                        "q": "",
                        "categoria": "",
                        "subcategoria": "",
                        "entitat": "",
                        "assignment_state": "all",
                        "equip_id": "",
                    },
                    "page": 1,
                    "page_size": 25,
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(workspace_after_unassign.status_code, 200)
        teams_by_name = {row.get("nom"): row for row in (workspace_after_unassign.json().get("teams") or [])}
        self.assertEqual(
            [m.get("nom") for m in teams_by_name["Club A"]["members"]],
            ["Dina Context"],
        )

    def test_equips_delete_empty_removes_only_globally_empty_teams_in_custom_context(self):
        globally_empty = Equip.objects.create(competicio=self.comp, context=self.ctx, nom="Ghost Team")
        native_only = Equip.objects.create(competicio=self.comp, context=self.base_ctx, nom="Native Only")
        InscripcioEquipAssignacio.objects.create(
            competicio=self.comp,
            context=self.base_ctx,
            inscripcio=self.ins_new,
            equip=native_only,
        )

        response = self.client.post(
            reverse("inscripcions_equips_delete_empty", kwargs={"pk": self.comp.id}),
            data=json.dumps({"context_code": "finals"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data.get("ok"))
        self.assertEqual(data.get("deleted"), 1)
        self.assertFalse(Equip.objects.filter(pk=globally_empty.id).exists())
        self.assertTrue(Equip.objects.filter(pk=native_only.id).exists())
        self.assertEqual(data.get("deleted_ids"), [globally_empty.id])

    def test_equips_workspace_native_ignores_legacy_team_without_base_assignment(self):
        legacy_only = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Eva Legacy",
            entitat="Club A",
            ordre_sortida=5,
            equip=self.team_existing_native,
        )

        response = self.client.post(
            reverse("inscripcions_equips_workspace", kwargs={"pk": self.comp.id}),
            data=json.dumps(
                {
                    "context_code": "native",
                    "filters": {
                        "q": "",
                        "categoria": "",
                        "subcategoria": "",
                        "entitat": "",
                        "assignment_state": "all",
                        "equip_id": "",
                    },
                    "page": 1,
                    "page_size": 25,
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        teams_by_name = {row.get("nom"): row for row in (payload.get("teams") or [])}
        self.assertEqual(
            [m.get("nom") for m in teams_by_name["Club A"]["members"]],
            ["Anna Keep"],
        )
        candidate = next(
            row for row in (payload.get("candidates", {}).get("items") or [])
            if int(row.get("id") or 0) == legacy_only.id
        )
        self.assertIsNone(candidate.get("current_team_id"))
        self.assertEqual(candidate.get("native_team_name"), "")

    def test_equips_unassign_native_hides_team_even_if_legacy_field_stays_informed(self):
        legacy_backed = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Fiona Native",
            entitat="Club A",
            ordre_sortida=5,
            equip=self.team_existing_native,
        )
        InscripcioEquipAssignacio.objects.create(
            competicio=self.comp,
            context=self.base_ctx,
            inscripcio=legacy_backed,
            equip=self.team_existing_native,
        )

        response = self.client.post(
            reverse("inscripcions_equips_unassign", kwargs={"pk": self.comp.id}),
            data=json.dumps(
                {
                    "context_code": "native",
                    "inscripcio_ids": [legacy_backed.id],
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)

        workspace = self.client.post(
            reverse("inscripcions_equips_workspace", kwargs={"pk": self.comp.id}),
            data=json.dumps(
                {
                    "context_code": "native",
                    "filters": {
                        "q": "",
                        "categoria": "",
                        "subcategoria": "",
                        "entitat": "",
                        "assignment_state": "all",
                        "equip_id": "",
                    },
                    "page": 1,
                    "page_size": 25,
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(workspace.status_code, 200)
        payload = workspace.json()
        teams_by_name = {row.get("nom"): row for row in (payload.get("teams") or [])}
        self.assertEqual(
            [m.get("nom") for m in teams_by_name["Club A"]["members"]],
            ["Anna Keep"],
        )
        candidate = next(
            row for row in (payload.get("candidates", {}).get("items") or [])
            if int(row.get("id") or 0) == legacy_backed.id
        )
        self.assertIsNone(candidate.get("current_team_id"))
        self.assertEqual(candidate.get("native_team_name"), "")
        legacy_backed.refresh_from_db()
        self.assertEqual(legacy_backed.equip_id, self.team_existing_native.id)

    def test_equips_delete_all_native_does_not_resurrect_legacy_teams(self):
        legacy_backed = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Gina Delete All",
            entitat="Club A",
            ordre_sortida=5,
            equip=self.team_other,
        )
        InscripcioEquipAssignacio.objects.create(
            competicio=self.comp,
            context=self.base_ctx,
            inscripcio=legacy_backed,
            equip=self.team_other,
        )

        response = self.client.post(
            reverse("inscripcions_equips_delete_all", kwargs={"pk": self.comp.id}),
            data=json.dumps({"context_code": "native"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)

        workspace = self.client.post(
            reverse("inscripcions_equips_workspace", kwargs={"pk": self.comp.id}),
            data=json.dumps(
                {
                    "context_code": "native",
                    "filters": {
                        "q": "",
                        "categoria": "",
                        "subcategoria": "",
                        "entitat": "",
                        "assignment_state": "all",
                        "equip_id": "",
                    },
                    "page": 1,
                    "page_size": 25,
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(workspace.status_code, 200)
        payload = workspace.json()
        self.assertEqual(payload.get("summary", {}).get("assigned_count"), 0)
        self.assertTrue(all(not row.get("members") for row in (payload.get("teams") or [])))
        candidate = next(
            row for row in (payload.get("candidates", {}).get("items") or [])
            if int(row.get("id") or 0) == legacy_backed.id
        )
        self.assertIsNone(candidate.get("current_team_id"))
        self.assertEqual(candidate.get("native_team_name"), "")

    def test_equips_preview_returns_rich_contract_for_native_context(self):
        response = self.client.post(
            reverse("inscripcions_equips_preview", kwargs={"pk": self.comp.id}),
            data=json.dumps(
                {
                    "context_code": "native",
                    "fields": ["entitat"],
                    "replace_existing": True,
                    "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                    "selected_ids": [],
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload.get("ok"))
        self.assertIn("selection_summary", payload)
        self.assertIn("existing_summary", payload)
        by_name = {row["nom_suggerit"]: row for row in (payload.get("preview") or [])}
        self.assertIn("Club A", by_name)
        self.assertIn("Club C", by_name)
        self.assertEqual(by_name["Club A"]["existing_team_name"], "Club A")
        self.assertTrue(by_name["Club A"]["will_keep"])
        self.assertTrue(by_name["Club A"]["will_reassign"])
        self.assertFalse(by_name["Club A"]["will_create"])
        self.assertEqual(by_name["Club C"]["member_samples"], ["Carla New"])
        self.assertTrue(by_name["Club C"]["will_create"])
        self.assertEqual(payload["selection_summary"]["mode"], "all")
        affected_names = {row["team_name"] for row in payload["existing_summary"]["affected_teams"]}
        self.assertIn("Alt Equip", affected_names)

    def test_equips_preview_supports_custom_context_and_selected_summary(self):
        response = self.client.post(
            reverse("inscripcions_equips_preview", kwargs={"pk": self.comp.id}),
            data=json.dumps(
                {
                    "context_code": "finals",
                    "fields": ["entitat"],
                    "replace_existing": False,
                    "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                    "selected_ids": [self.ins_ctx.id],
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload.get("ok"))
        self.assertEqual(payload["selection_summary"]["mode"], "selected")
        self.assertFalse(payload["selection_summary"]["replace_existing"])
        self.assertEqual(payload["total_inscripcions"], 1)
        self.assertEqual(payload["preview"][0]["existing_team_name"], "Club A")
        self.assertTrue(payload["preview"][0]["will_keep"])
        self.assertFalse(payload["preview"][0]["will_create"])

    def test_equips_preview_respects_column_filters(self):
        response = self.client.post(
            reverse("inscripcions_equips_preview", kwargs={"pk": self.comp.id}),
            data=json.dumps(
                {
                    "context_code": "native",
                    "fields": ["entitat"],
                    "replace_existing": True,
                    "filters": {
                        "q": "",
                        "categoria": "",
                        "subcategoria": "",
                        "entitat": "",
                        "column_filters": {"entitat": ["Club C"]},
                    },
                    "selected_ids": [],
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload.get("ok"))
        self.assertEqual(payload.get("total_inscripcions"), 1)
        self.assertEqual(payload.get("selection_summary", {}).get("mode"), "filtered")
        self.assertEqual([row.get("nom_suggerit") for row in (payload.get("preview") or [])], ["Club C"])

    def test_equips_preview_respects_assignment_filters_from_workspace(self):
        response = self.client.post(
            reverse("inscripcions_equips_preview", kwargs={"pk": self.comp.id}),
            data=json.dumps(
                {
                    "context_code": "finals",
                    "fields": ["entitat"],
                    "replace_existing": True,
                    "filters": {
                        "q": "",
                        "categories": [],
                        "subcategories": [],
                        "entitats": [],
                        "assignment_state": "assigned",
                        "equip_ids": [str(self.team_existing.id)],
                    },
                    "selected_ids": [],
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload.get("ok"))
        self.assertEqual(payload.get("total_inscripcions"), 1)
        self.assertEqual([row.get("nom_suggerit") for row in (payload.get("preview") or [])], ["Club A"])

    def test_equips_preview_can_limit_scope_with_bucket_keys(self):
        response = self.client.post(
            reverse("inscripcions_equips_preview", kwargs={"pk": self.comp.id}),
            data=json.dumps(
                {
                    "context_code": "native",
                    "fields": ["entitat"],
                    "replace_existing": True,
                    "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                    "selected_ids": [],
                    "bucket_keys": [json.dumps(["Club C"], ensure_ascii=False)],
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload.get("ok"))
        self.assertEqual(payload.get("total_inscripcions"), 1)
        self.assertEqual(payload.get("bucket_summary", {}).get("selected_count"), 1)
        self.assertEqual([row.get("nom_suggerit") for row in (payload.get("preview") or [])], ["Club C"])

    def test_equips_auto_create_respects_column_filters(self):
        response = self.client.post(
            reverse("inscripcions_equips_auto_create", kwargs={"pk": self.comp.id}),
            data=json.dumps(
                {
                    "context_code": "finals",
                    "fields": ["entitat"],
                    "replace_existing": False,
                    "filters": {
                        "q": "",
                        "categoria": "",
                        "subcategoria": "",
                        "entitat": "",
                        "column_filters": {"entitat": ["Club C"]},
                    },
                    "selected_ids": [],
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload.get("ok"))
        self.assertEqual(payload.get("created"), 1)
        assignacio = InscripcioEquipAssignacio.objects.get(
            competicio=self.comp,
            context=self.ctx,
            inscripcio=self.ins_new,
        )
        self.assertEqual(assignacio.equip.nom, "Club C")
        self.assertFalse(
            InscripcioEquipAssignacio.objects.filter(
                competicio=self.comp,
                context=self.ctx,
                inscripcio=self.ins_keep,
            ).exists()
        )

    def test_equips_auto_create_can_limit_scope_with_bucket_keys(self):
        response = self.client.post(
            reverse("inscripcions_equips_auto_create", kwargs={"pk": self.comp.id}),
            data=json.dumps(
                {
                    "context_code": "finals",
                    "fields": ["entitat"],
                    "replace_existing": False,
                    "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                    "selected_ids": [],
                    "bucket_keys": [json.dumps(["Club C"], ensure_ascii=False)],
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload.get("ok"))
        self.assertEqual(payload.get("created"), 1)
        assignacio = InscripcioEquipAssignacio.objects.get(
            competicio=self.comp,
            context=self.ctx,
            inscripcio=self.ins_new,
        )
        self.assertEqual(assignacio.equip.nom, "Club C")
        self.assertFalse(
            InscripcioEquipAssignacio.objects.filter(
                competicio=self.comp,
                context=self.ctx,
                inscripcio=self.ins_keep,
            ).exists()
        )
        self.assertFalse(
            InscripcioEquipAssignacio.objects.filter(
                competicio=self.comp,
                context=self.ctx,
                inscripcio=self.ins_move,
            ).exists()
        )


