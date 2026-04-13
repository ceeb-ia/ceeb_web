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

from .... import live_cache
from ....access import user_has_competicio_capability
from ....forms import CompeticioAparellForm
from ....models import (
    Competicio,
    Equip,
    EquipContext,
    GrupCompeticio,
    Inscripcio,
    InscripcioEquipAssignacio,
    InscripcioMedia,
)
from ....models.judging import (
    JudgeConversation,
    JudgeConversationMessage,
    JudgeDeviceToken,
    PublicLiveToken,
)
from ....models.classificacions import ClassificacioConfig, ClassificacioTemplateGlobal
from ....models.rotacions import (
    RotacioAssignacio,
    RotacioAssignacioGrup,
    RotacioAssignacioSerieEquip,
    RotacioEstacio,
    RotacioFranja,
)
from ....models.scoring import (
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
from ....models.competicio import (
    Aparell,
    CompeticioAparell,
    CompeticioAparellEquipContextSource,
    InscripcioAparellExclusio,
)
from ....models import CompeticioMembership
from ....scoring_engine import ScoringEngine
from ....services.inscripcions.groups import renumber_groups_for_competicio
from ....services.inscripcions.sorting import (
    _split_custom_sort_tokens,
    sort_records_by_field_stable,
)
from ....services.inscripcions.history import (
    apply_inscripcions_history_snapshot,
    capture_inscripcions_history_snapshot,
)
from ....services.inscripcions.queries import (
    COLUMN_FILTER_EMPTY_TOKEN,
    _build_inscripcions_filtered_qs,
    _resolve_group_creation_buckets,
    build_inscripcions_sort_context_key,
    get_competicio_custom_sort_rank_map,
)
from ....services.classificacions.builder import scoreable_codes_by_app_id as _scoreable_codes_by_app_id
from ....services.classificacions.compute import DEFAULT_SCHEMA, compute_classificacio
from ....services.classificacions.export import _normalize_excel_cell
from ....services.classificacions.partitions import normalize_schema_legacy_team_birth_partition
from ....services.classificacions.validation import (
    build_metric_meta_for_comp_aparell as _build_metric_meta_for_comp_aparell,
    build_scoreable_meta_for_schema as _build_scoreable_meta_for_schema,
    validate_particions_schema as _validate_particions_schema,
    validate_schema_for_competicio as _validate_schema_for_competicio,
)
from ....services.classificacions.classificacio_templates import (
    normalize_particions_schema as _normalize_particions_schema,
    schema_to_template_schema as _schema_to_template_schema,
    template_schema_to_competicio_schema as _template_schema_to_competicio_schema,
)
from ....views.classificacions.builder import ClassificacionsHome
from ....services.shared.competition_groups import (
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
from ....services.scoring.team_scoring import (
    build_permission_label,
    build_team_subjects_for_comp_aparell,
    resolve_permission_runtime_entries,
    runtime_schema_for_comp_aparell,
)
from ....services.teams.team_series import safe_deactivate_empty_serie
from ....views.judge.admin import _member_slot_choices, _validate_permission_row
from ....templatetags.competicio_extras import (
    DEFAULT_COMPETITION_BACKGROUND,
    get_competicio_background_url_from_request,
)

from ...base import _BaseTrampoliDataMixin



class GroupManagerV1Tests(_BaseTrampoliDataMixin, TestCase):
    def setUp(self):
        self.comp = self._create_competicio("Comp Group Manager V1")

        self.programmed_group = GrupCompeticio.objects.create(
            competicio=self.comp,
            legacy_num=1,
            display_num=1,
            nom="Final",
            actiu=True,
        )
        self.other_group = GrupCompeticio.objects.create(
            competicio=self.comp,
            legacy_num=2,
            display_num=2,
            nom="",
            actiu=True,
        )
        self.empty_group = GrupCompeticio.objects.create(
            competicio=self.comp,
            legacy_num=3,
            display_num=3,
            nom="",
            actiu=True,
        )

        self.ins_programmed_a = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Programmed A",
            ordre_sortida=1,
            grup=1,
        )
        self.ins_programmed_b = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Programmed B",
            ordre_sortida=2,
            grup=1,
        )
        self.ins_other = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Other Group",
            ordre_sortida=3,
            grup=2,
        )
        self.ins_free_a = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Free A",
            ordre_sortida=4,
        )
        self.ins_free_b = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Free B",
            ordre_sortida=5,
        )

        self._attach_rotation_to_group(self.programmed_group)

        User = get_user_model()
        self.user = User.objects.create_user(
            username="group_manager_editor",
            password="testpass123",
            email="group-manager@example.com",
        )
        CompeticioMembership.objects.create(
            user=self.user,
            competicio=self.comp,
            role=CompeticioMembership.Role.EDITOR,
            is_active=True,
        )
        self.client.force_login(self.user)

    def _post_json(self, url_name, payload):
        url = reverse(url_name, kwargs={"pk": self.comp.id})
        return self.client.post(
            url,
            data=json.dumps(payload),
            content_type="application/json",
        )

    def _groups_payload(self, **overrides):
        payload = {
            "resolution_mode": "auto",
            "strategy": "count",
            "group_count": 1,
            "preview_only": True,
            "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
            "group_by": [],
        }
        payload.update(overrides)
        return payload

    def _attach_rotation_to_group(self, group):
        next_order = (RotacioFranja.objects.filter(competicio=self.comp).aggregate(max_ordre=Max("ordre")).get("max_ordre") or 0) + 1
        franja = RotacioFranja.objects.create(
            competicio=self.comp,
            hora_inici="09:00",
            hora_fi="09:30",
            ordre=next_order,
            titol=f"Franja {next_order}",
        )
        estacio = RotacioEstacio.objects.create(
            competicio=self.comp,
            tipus="descans",
            ordre=next_order,
            actiu=True,
        )
        assignacio = RotacioAssignacio.objects.create(
            competicio=self.comp,
            franja=franja,
            estacio=estacio,
        )
        RotacioAssignacioGrup.objects.create(assignacio=assignacio, grup=group, ordre=1)

    def _groups_contract_path(self, action):
        return f"/competicio/{self.comp.id}/inscripcions/groups/{action}/"

    def _post_groups_contract(self, action, payload):
        path = self._groups_contract_path(action)
        try:
            resolve(path.lstrip("/"))
        except Resolver404:
            self.skipTest(f"Pending groups endpoint not implemented yet: {path}")
        return self.client.post(
            path,
            data=json.dumps(payload),
            content_type="application/json",
        )

    def test_group_helpers_report_labels_counts_and_programmed_state(self):
        counts = get_group_participant_counts(self.comp)
        maps = get_group_maps(self.comp)
        programmed_ids = get_programmed_group_ids(self.comp)
        out_of_program_ids = get_out_of_program_group_ids(self.comp)

        self.assertEqual(group_label(self.programmed_group), "Final")
        self.assertEqual(group_label(self.other_group), "Grup 2")
        self.assertEqual(counts[self.programmed_group.id], 2)
        self.assertEqual(counts[self.other_group.id], 1)
        self.assertIn(self.programmed_group.id, programmed_ids)
        self.assertIn(self.other_group.id, out_of_program_ids)
        self.assertEqual(maps["by_display_num"][1].nom, "Final")
        self.assertEqual(maps["by_display_num"][2].display_num, 2)

    def test_assign_groups_by_display_num_creates_new_groups_and_updates_legacy_fields(self):
        new_group_num = next_group_display_num(self.comp)
        moved_ids = assign_groups_by_display_num(
            self.comp,
            {
                new_group_num: [self.ins_free_a.id, self.ins_free_b.id],
            },
        )

        self.assertEqual(moved_ids, {self.ins_free_a.id, self.ins_free_b.id})
        new_group = GrupCompeticio.objects.get(competicio=self.comp, display_num=new_group_num)
        self.ins_free_a.refresh_from_db()
        self.ins_free_b.refresh_from_db()

        self.assertEqual(self.ins_free_a.grup, new_group_num)
        self.assertEqual(self.ins_free_a.grup_competicio_id, new_group.id)
        self.assertEqual(self.ins_free_a.ordre_competicio, 1)
        self.assertEqual(self.ins_free_b.grup, new_group_num)
        self.assertEqual(self.ins_free_b.grup_competicio_id, new_group.id)
        self.assertEqual(self.ins_free_b.ordre_competicio, 2)
        self.assertEqual(group_label(new_group), f"Grup {new_group_num}")

    def test_move_inscripcio_to_group_appends_target_order_and_compacts_origin_group(self):
        moved = move_inscripcio_to_group(self.ins_programmed_b, self.other_group)

        self.assertTrue(moved)
        self.ins_programmed_a.refresh_from_db()
        self.ins_programmed_b.refresh_from_db()
        self.ins_other.refresh_from_db()

        self.assertEqual(self.ins_programmed_a.grup, 1)
        self.assertEqual(self.ins_programmed_a.ordre_competicio, 1)
        self.assertEqual(self.ins_programmed_b.grup, 2)
        self.assertEqual(self.ins_programmed_b.ordre_competicio, 2)
        self.assertEqual(self.ins_other.ordre_competicio, 1)

    def test_manual_unassign_requires_compacting_group_order(self):
        Inscripcio.objects.filter(pk=self.ins_programmed_b.pk).update(
            grup_competicio=None,
            grup=None,
            ordre_competicio=None,
        )
        compact_competition_order_for_group(self.programmed_group)

        self.ins_programmed_a.refresh_from_db()
        self.ins_programmed_b.refresh_from_db()

        self.assertEqual(self.ins_programmed_a.ordre_competicio, 1)
        self.assertIsNone(self.ins_programmed_b.grup)
        self.assertIsNone(self.ins_programmed_b.grup_competicio_id)
        self.assertIsNone(self.ins_programmed_b.ordre_competicio)

    def test_set_group_name_updates_view_and_returns_history_payload(self):
        resp = self.client.post(
            reverse("inscripcions_set_group_name", kwargs={"pk": self.comp.id}),
            data=json.dumps({"group": 1, "name": "Final A"}),
            content_type="application/json",
        )

        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertTrue(payload.get("ok"))
        self.assertIn("history", payload)
        self.assertEqual(payload.get("name"), "Final A")

        self.programmed_group.refresh_from_db()
        self.comp.refresh_from_db()
        self.assertEqual(self.programmed_group.nom, "Final A")
        self.assertEqual(self.comp.inscripcions_view.get("group_names"), {"1": "Final A"})

    def test_groups_workspace_contract_returns_summary_and_group_cards(self):
        payload = {
            "scope": "selected",
            "selected_ids": [self.ins_programmed_a.id, self.ins_free_a.id],
            "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
            "page": 1,
            "page_size": 25,
        }
        resp = self._post_groups_contract("workspace", payload)

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("ok"))
        self.assertIn("summary", data)
        self.assertIn("groups", data)
        self.assertIn("filters", data)
        self.assertIn("candidates", data)

        summary = data.get("summary") or {}
        self.assertGreaterEqual(int(summary.get("groups_total") or 0), 3)
        self.assertGreaterEqual(int(summary.get("groups_with_members") or 0), 1)
        self.assertGreaterEqual(int(summary.get("empty_groups") or 0), 1)
        self.assertEqual(int(summary.get("assigned_count") or 0), 3)
        self.assertEqual(int(summary.get("unassigned_count") or 0), 2)
        self.assertEqual(int(summary.get("programmed_groups") or 0), 1)
        self.assertEqual(int(summary.get("out_of_program_groups") or 0), 1)

    def test_groups_workspace_contract_includes_board_filter_facets_for_group_cards(self):
        self.ins_programmed_a.categoria = "Alevi"
        self.ins_programmed_a.subcategoria = "Sub A"
        self.ins_programmed_a.entitat = "Club A"
        self.ins_programmed_a.save(update_fields=["categoria", "subcategoria", "entitat"])
        self.ins_programmed_b.categoria = "Senior"
        self.ins_programmed_b.subcategoria = "Sub B"
        self.ins_programmed_b.entitat = "Club Z"
        self.ins_programmed_b.save(update_fields=["categoria", "subcategoria", "entitat"])

        resp = self._post_groups_contract(
            "workspace",
            {
                "scope": "filtered",
                "selected_ids": [],
                "filters": {
                    "q": "",
                    "categoria": "",
                    "subcategoria": "",
                    "entitat": "",
                    "group_state": "unassigned",
                },
                "page": 1,
                "page_size": 25,
            },
        )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("ok"))
        groups_by_id = {
            int(row.get("id") or 0): row
            for row in (data.get("groups") or [])
            if int(row.get("id") or 0) > 0
        }
        programmed_row = groups_by_id[self.programmed_group.id]

        self.assertEqual(programmed_row.get("categories"), ["Alevi", "Senior"])
        self.assertEqual(programmed_row.get("subcategories"), ["Sub A", "Sub B"])
        self.assertEqual(programmed_row.get("entitats"), ["Club A", "Club Z"])
        self.assertIn("Programmed A", programmed_row.get("search_text") or "")
        self.assertIn("Programmed B", programmed_row.get("search_text") or "")
        self.assertIn("Final", programmed_row.get("search_text") or "")

    def test_groups_workspace_contract_keeps_selection_and_omits_filtered_target_ids_by_default(self):
        resp = self._post_groups_contract(
            "workspace",
            {
                "selected_ids": [self.ins_programmed_a.id, self.ins_free_a.id],
                "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "page": 1,
                "page_size": 2,
            },
        )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("ok"))
        self.assertEqual(data.get("selected_ids"), [self.ins_programmed_a.id, self.ins_free_a.id])
        self.assertEqual(int((data.get("selection") or {}).get("count") or 0), 2)
        self.assertNotIn("target_ids", data)

    def test_groups_workspace_resolve_filtered_ids_operation_returns_full_filtered_set(self):
        resp = self._post_groups_contract(
            "workspace",
            {
                "operation": "resolve_filtered_ids",
                "filters": {
                    "q": "",
                    "categoria": "",
                    "subcategoria": "",
                    "entitat": "",
                    "group_state": "unassigned",
                },
                "page": 1,
                "page_size": 1,
            },
        )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("ok"))
        self.assertEqual(data.get("operation"), "resolve_filtered_ids")
        self.assertEqual(data.get("target_ids"), [self.ins_free_a.id, self.ins_free_b.id])
        self.assertEqual(int(data.get("total") or 0), 2)

    def test_groups_workspace_resolve_auto_context_returns_global_buckets_without_selection(self):
        self.ins_programmed_a.categoria = "Alevi"
        self.ins_programmed_a.save(update_fields=["categoria"])
        self.ins_free_a.categoria = "Alevi"
        self.ins_free_a.save(update_fields=["categoria"])
        self.ins_programmed_b.categoria = "Senior"
        self.ins_programmed_b.save(update_fields=["categoria"])
        self.ins_other.categoria = "Senior"
        self.ins_other.save(update_fields=["categoria"])
        self.ins_free_b.categoria = "Infantil"
        self.ins_free_b.save(update_fields=["categoria"])

        resp = self._post_groups_contract(
            "workspace",
            {
                "operation": "resolve_auto_context",
                "selected_ids": [],
                "sort_context_filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "workspace_filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "fallback_mode": "all_filtered",
                "group_by": ["categoria"],
                "source_scope": "competition_all",
            },
        )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("ok"))
        self.assertEqual(data.get("operation"), "resolve_auto_context")
        self.assertEqual(int(data.get("selection_count") or 0), 0)
        self.assertEqual(data.get("source_scope"), "competition_all")
        self.assertEqual(int(data.get("source_total") or 0), 5)
        self.assertEqual(int(data.get("buckets_total") or 0), 3)
        self.assertEqual(len(data.get("default_bucket_keys") or []), 3)
        self.assertFalse(data.get("used_fallback"))
        self.assertEqual(
            sorted(bucket.get("label") for bucket in (data.get("buckets") or [])),
            ["Alevi", "Infantil", "Senior"],
        )

    def test_groups_workspace_resolve_auto_context_combines_workspace_bucket_fields(self):
        rows = [
            (self.ins_programmed_a, "Alevi", "Club A"),
            (self.ins_free_a, "Alevi", "Club B"),
            (self.ins_programmed_b, "Senior", "Club A"),
            (self.ins_other, "Senior", "Club B"),
            (self.ins_free_b, "Infantil", "Club B"),
        ]
        for ins, categoria, entitat in rows:
            ins.categoria = categoria
            ins.entitat = entitat
            ins.save(update_fields=["categoria", "entitat"])

        resp = self._post_json(
            "groups_workspace",
            {
                "operation": "resolve_auto_context",
                "selected_ids": [],
                "sort_context_filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "workspace_filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "group_by": ["categoria"],
                "workspace_bucket_fields": ["categoria", "entitat"],
                "source_scope": "competition_all",
            },
        )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("ok"))
        self.assertEqual(data.get("workspace_bucket_fields"), ["entitat"])
        self.assertEqual(data.get("layers_used"), ["tabs", "workspace"])
        self.assertEqual(int(data.get("buckets_total") or 0), 5)
        self.assertEqual(
            sorted(bucket.get("label") for bucket in (data.get("buckets") or [])),
            [
                "Alevi / Club A",
                "Alevi / Club B",
                "Infantil / Club B",
                "Senior / Club A",
                "Senior / Club B",
            ],
        )
        self.assertEqual(
            data.get("detected_workspace_fields"),
            [{"code": "entitat", "label": "Entitat (Nativa)"}],
        )
        self.assertTrue(
            all(sorted(bucket.get("kinds") or []) == ["tabs", "workspace"] for bucket in (data.get("buckets") or []))
        )

    def test_groups_workspace_resolve_auto_context_supports_excel_workspace_bucket_fields(self):
        self.comp.inscripcions_schema = {
            "columns": [
                {"code": "nivell", "label": "Nivell", "kind": "extra"},
            ]
        }
        self.comp.save(update_fields=["inscripcions_schema"])
        self.ins_programmed_a.extra = {"nivell": "A"}
        self.ins_programmed_a.save(update_fields=["extra"])
        self.ins_free_a.extra = {"nivell": "A"}
        self.ins_free_a.save(update_fields=["extra"])
        self.ins_programmed_b.extra = {"nivell": "B"}
        self.ins_programmed_b.save(update_fields=["extra"])

        resp = self._post_json(
            "groups_workspace",
            {
                "operation": "resolve_auto_context",
                "selected_ids": [self.ins_programmed_a.id],
                "sort_context_filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "workspace_filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "group_by": [],
                "workspace_bucket_fields": ["excel__nivell"],
                "source_scope": "competition_all",
            },
        )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("ok"))
        self.assertEqual(data.get("layers_used"), ["workspace"])
        self.assertEqual(data.get("workspace_bucket_fields"), ["nivell"])
        self.assertEqual(
            sorted(bucket.get("label") for bucket in (data.get("buckets") or [])),
            ["(Sense valor)", "A", "B"],
        )

    def test_groups_workspace_resolve_auto_context_tracks_visible_and_selected_counts(self):
        self.ins_programmed_a.categoria = "Alevi"
        self.ins_programmed_a.save(update_fields=["categoria"])
        self.ins_free_a.categoria = "Alevi"
        self.ins_free_a.save(update_fields=["categoria"])
        self.ins_programmed_b.categoria = "Senior"
        self.ins_programmed_b.save(update_fields=["categoria"])
        self.ins_other.categoria = "Infantil"
        self.ins_other.save(update_fields=["categoria"])
        self.ins_free_b.categoria = "Senior"
        self.ins_free_b.save(update_fields=["categoria"])

        resp = self._post_groups_contract(
            "workspace",
            {
                "operation": "resolve_auto_context",
                "selected_ids": [self.ins_programmed_a.id, self.ins_free_b.id],
                "sort_context_filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "workspace_filters": {
                    "q": "",
                    "categoria": "",
                    "subcategoria": "",
                    "entitat": "",
                    "categories": ["Alevi"],
                },
                "fallback_mode": "all_filtered",
                "group_by": ["categoria"],
                "source_scope": "competition_all",
            },
        )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("ok"))
        self.assertEqual(int(data.get("selection_count") or 0), 2)
        self.assertEqual(int(data.get("buckets_total") or 0), 3)
        self.assertEqual(sorted(data.get("layers_used") or []), ["tabs"])
        buckets_by_label = {
            bucket.get("label"): bucket
            for bucket in (data.get("buckets") or [])
        }
        self.assertEqual(int((buckets_by_label["Alevi"] or {}).get("global_count") or 0), 2)
        self.assertEqual(int((buckets_by_label["Alevi"] or {}).get("visible_count") or 0), 2)
        self.assertEqual(int((buckets_by_label["Alevi"] or {}).get("selected_count") or 0), 1)
        self.assertEqual(int((buckets_by_label["Infantil"] or {}).get("visible_count") or 0), 0)
        self.assertEqual(int((buckets_by_label["Senior"] or {}).get("selected_count") or 0), 1)

    def test_groups_workspace_apply_auto_context_selection_supports_add_remove_and_set(self):
        self.ins_programmed_a.categoria = "Alevi"
        self.ins_programmed_a.save(update_fields=["categoria"])
        self.ins_free_a.categoria = "Alevi"
        self.ins_free_a.save(update_fields=["categoria"])
        self.ins_programmed_b.categoria = "Senior"
        self.ins_programmed_b.save(update_fields=["categoria"])
        self.ins_other.categoria = "Infantil"
        self.ins_other.save(update_fields=["categoria"])
        self.ins_free_b.categoria = "Senior"
        self.ins_free_b.save(update_fields=["categoria"])

        resolve_resp = self._post_groups_contract(
            "workspace",
            {
                "operation": "resolve_auto_context",
                "selected_ids": [self.ins_programmed_b.id],
                "sort_context_filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "workspace_filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "group_by": ["categoria"],
                "source_scope": "competition_all",
            },
        )
        self.assertEqual(resolve_resp.status_code, 200)
        resolve_data = resolve_resp.json()
        bucket_keys_by_label = {
            bucket.get("label"): bucket.get("key")
            for bucket in (resolve_data.get("buckets") or [])
        }

        add_resp = self._post_groups_contract(
            "workspace",
            {
                "operation": "apply_auto_context_selection",
                "selection_mode": "add",
                "bucket_keys": [bucket_keys_by_label["Alevi"]],
                "selected_ids": [self.ins_programmed_b.id],
                "sort_context_filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "workspace_filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "group_by": ["categoria"],
                "source_scope": "competition_all",
            },
        )
        self.assertEqual(add_resp.status_code, 200)
        add_data = add_resp.json()
        self.assertEqual(
            add_data.get("selected_ids"),
            [self.ins_programmed_b.id, self.ins_programmed_a.id, self.ins_free_a.id],
        )

        remove_resp = self._post_groups_contract(
            "workspace",
            {
                "operation": "apply_auto_context_selection",
                "selection_mode": "remove",
                "bucket_keys": [bucket_keys_by_label["Alevi"]],
                "selected_ids": add_data.get("selected_ids"),
                "sort_context_filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "workspace_filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "group_by": ["categoria"],
                "source_scope": "competition_all",
            },
        )
        self.assertEqual(remove_resp.status_code, 200)
        remove_data = remove_resp.json()
        self.assertEqual(remove_data.get("selected_ids"), [self.ins_programmed_b.id])

        set_resp = self._post_groups_contract(
            "workspace",
            {
                "operation": "apply_auto_context_selection",
                "selection_mode": "set",
                "bucket_keys": [bucket_keys_by_label["Infantil"]],
                "selected_ids": remove_data.get("selected_ids"),
                "sort_context_filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "workspace_filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "group_by": ["categoria"],
                "source_scope": "competition_all",
            },
        )
        self.assertEqual(set_resp.status_code, 200)
        set_data = set_resp.json()
        self.assertEqual(set_data.get("selected_ids"), [self.ins_other.id])

    def test_groups_workspace_filtered_scope_respects_column_filters(self):
        self.ins_free_a.entitat = "Club Filtrat"
        self.ins_free_a.save(update_fields=["entitat"])
        self.ins_free_b.entitat = "Club Altre"
        self.ins_free_b.save(update_fields=["entitat"])

        resp = self._post_groups_contract(
            "workspace",
            {
                "scope": "filtered",
                "selected_ids": [],
                "filters": {
                    "q": "",
                    "categoria": "",
                    "subcategoria": "",
                    "entitat": "",
                    "column_filters": {"entitat": ["Club Filtrat"]},
                    "group_state": "unassigned",
                },
                "page": 1,
                "page_size": 25,
            },
        )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("ok"))
        self.assertEqual(data.get("filters", {}).get("column_filters"), {"entitat": ["Club Filtrat"]})
        self.assertEqual(
            [row.get("id") for row in (data.get("candidates") or [])],
            [self.ins_free_a.id],
        )
        self.assertEqual(int((data.get("paging") or {}).get("total") or 0), 1)

    def test_groups_workspace_filtered_scope_supports_multiselect_fields_and_group_ids(self):
        self.ins_programmed_a.categoria = "Alevi"
        self.ins_programmed_a.entitat = "Club A"
        self.ins_programmed_a.save(update_fields=["categoria", "entitat"])
        self.ins_programmed_b.categoria = "Infantil"
        self.ins_programmed_b.entitat = "Club C"
        self.ins_programmed_b.save(update_fields=["categoria", "entitat"])
        self.ins_other.categoria = "Infantil"
        self.ins_other.entitat = "Club B"
        self.ins_other.save(update_fields=["categoria", "entitat"])
        self.ins_free_a.categoria = "Infantil"
        self.ins_free_a.entitat = "Club B"
        self.ins_free_a.save(update_fields=["categoria", "entitat"])

        resp = self._post_groups_contract(
            "workspace",
            {
                "scope": "filtered",
                "selected_ids": [],
                "filters": {
                    "q": "",
                    "categoria": "",
                    "subcategoria": "",
                    "entitat": "",
                    "categories": ["Alevi", "Infantil"],
                    "entitats": ["Club B"],
                    "group_ids": [self.programmed_group.id, self.other_group.id],
                    "group_state": "assigned",
                },
                "page": 1,
                "page_size": 25,
            },
        )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("ok"))
        self.assertEqual(data.get("filters", {}).get("categories"), ["Alevi", "Infantil"])
        self.assertEqual(data.get("filters", {}).get("entitats"), ["Club B"])
        self.assertEqual(data.get("filters", {}).get("group_ids"), [self.programmed_group.id, self.other_group.id])
        self.assertEqual(
            [row.get("id") for row in (data.get("candidates") or [])],
            [self.ins_other.id],
        )
        self.assertEqual(int((data.get("paging") or {}).get("total") or 0), 1)

    def test_groups_workspace_filter_options_keep_other_categories_visible_after_filtering_one(self):
        self.ins_programmed_a.categoria = "Alevi"
        self.ins_programmed_a.save(update_fields=["categoria"])
        self.ins_other.categoria = "Infantil"
        self.ins_other.save(update_fields=["categoria"])
        self.ins_free_a.categoria = "Juvenil"
        self.ins_free_a.save(update_fields=["categoria"])

        resp = self._post_groups_contract(
            "workspace",
            {
                "scope": "filtered",
                "selected_ids": [],
                "filters": {
                    "q": "",
                    "categoria": "",
                    "subcategoria": "",
                    "entitat": "",
                    "categories": ["Alevi"],
                    "group_state": "all",
                },
                "page": 1,
                "page_size": 25,
            },
        )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("ok"))
        self.assertEqual(
            sorted(data.get("filter_options", {}).get("categories") or []),
            ["Alevi", "Infantil", "Juvenil"],
        )
        self.assertEqual(
            [row.get("id") for row in (data.get("candidates") or [])],
            [self.ins_programmed_a.id],
        )

    def test_groups_detail_contract_returns_members_and_state_flags(self):
        resp = self._post_groups_contract(
            "detail",
            {"group_id": self.programmed_group.id},
        )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("ok"))
        group_data = data.get("group") or {}
        members = data.get("members") or group_data.get("members") or []

        self.assertEqual(int(group_data.get("id") or data.get("group_id") or 0), self.programmed_group.id)
        self.assertEqual(group_data.get("label") or group_data.get("nom") or data.get("group_label"), "Final")
        self.assertTrue(group_data.get("is_programmed", data.get("is_programmed")))
        self.assertEqual([member.get("nom") for member in members], ["Programmed A", "Programmed B"])

    def test_groups_detail_contract_supports_member_pagination(self):
        resp = self._post_groups_contract(
            "detail",
            {"group_id": self.programmed_group.id, "page": 2, "page_size": 1},
        )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("ok"))
        group_data = data.get("group") or {}
        members = data.get("members") or group_data.get("members") or []

        self.assertEqual(int(group_data.get("members_total") or 0), 2)
        self.assertEqual(int(group_data.get("members_page") or 0), 2)
        self.assertEqual(int(group_data.get("members_page_size") or 0), 1)
        self.assertEqual(int(group_data.get("members_total_pages") or 0), 2)
        self.assertTrue(group_data.get("members_has_prev"))
        self.assertFalse(group_data.get("members_has_next"))
        self.assertEqual([member.get("nom") for member in members], ["Programmed B"])

    def test_groups_detail_contract_returns_consistent_empty_pagination(self):
        empty_group = GrupCompeticio.objects.create(
            competicio=self.comp,
            legacy_num=9,
            display_num=9,
            nom="Empty detail",
            actiu=True,
        )

        resp = self._post_groups_contract(
            "detail",
            {"group_id": empty_group.id},
        )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("ok"))
        group_data = data.get("group") or {}

        self.assertEqual(group_data.get("members"), [])
        self.assertEqual(int(group_data.get("members_total") or 0), 0)
        self.assertEqual(int(group_data.get("members_page") or 0), 1)
        self.assertEqual(int(group_data.get("members_total_pages") or 0), 1)
        self.assertFalse(group_data.get("members_has_prev"))
        self.assertFalse(group_data.get("members_has_next"))

    def test_groups_preview_contract_reports_reduced_and_removed_programmed_groups(self):
        single_group = GrupCompeticio.objects.create(
            competicio=self.comp,
            legacy_num=4,
            display_num=4,
            nom="Single",
            actiu=True,
        )
        single_member = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Single Member",
            ordre_sortida=6,
            grup=4,
        )
        self._attach_rotation_to_group(single_group)

        resp = self._post_groups_contract(
            "preview",
            {
                "scope": "selected",
                "selected_ids": [self.ins_programmed_a.id],
                "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "action": "unassign",
            },
        )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("ok"))
        preview = data.get("preview") or data
        existing_groups = preview.get("existing_groups") or []
        self.assertTrue(existing_groups)
        self.assertTrue(
            any(row.get("impact_kind") == "reduced" for row in existing_groups)
            or any(row.get("impact_kind") == "removed" for row in existing_groups)
        )

        resp_removed = self._post_groups_contract(
            "preview",
            {
                "scope": "selected",
                "selected_ids": [single_member.id],
                "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "action": "unassign",
            },
        )
        self.assertEqual(resp_removed.status_code, 200)
        removed_preview = resp_removed.json().get("preview") or resp_removed.json()
        removed_groups = removed_preview.get("existing_groups") or []
        self.assertTrue(any(row.get("impact_kind") == "removed" for row in removed_groups))

    def test_groups_preview_uses_selected_ids_even_when_legacy_filtered_scope_is_sent(self):
        resp = self._post_groups_contract(
            "preview",
            {
                "scope": "filtered",
                "selected_ids": [self.ins_free_a.id],
                "filters": {
                    "q": "",
                    "categoria": "",
                    "subcategoria": "",
                    "entitat": "",
                    "group_state": "unassigned",
                },
                "action": "create",
            },
        )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("ok"))
        preview = data.get("preview") or {}
        self.assertEqual(int((preview.get("selection") or {}).get("count") or 0), 1)
        self.assertEqual(int(preview.get("target_ids_count") or 0), 1)
        self.assertEqual(
            [row.get("members_count") for row in (preview.get("planned_groups") or [])],
            [1],
        )

    def test_groups_preview_per_bucket_with_bucket_selection_mode_none_returns_empty_plan(self):
        self.ins_free_a.categoria = "Alevi"
        self.ins_free_a.save(update_fields=["categoria"])
        self.ins_free_b.categoria = "Infantil"
        self.ins_free_b.save(update_fields=["categoria"])

        resp = self._post_json(
            "inscripcions_groups_from_sort",
            self._groups_payload(
                strategy="per_bucket",
                preview_only=True,
                scope="selected",
                selected_ids=[self.ins_free_a.id, self.ins_free_b.id],
                group_by=["categoria"],
                selected_keys=[],
                bucket_selection_mode="none",
            ),
        )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("ok"))
        self.assertEqual(int(data.get("buckets_total") or 0), 2)
        self.assertEqual(int(data.get("buckets_applied") or 0), 0)
        preview = data.get("preview") or {}
        self.assertEqual(int(preview.get("groups_total") or 0), 0)
        self.assertEqual(int(preview.get("members_total") or 0), 0)

    def test_groups_create_contract_assigns_selected_ids_to_new_group(self):
        expected_group_num = next_group_display_num(self.comp)
        resp = self._post_groups_contract(
            "create",
            {
                "scope": "selected",
                "selected_ids": [self.ins_free_a.id, self.ins_free_b.id],
                "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
            },
        )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("ok"))
        self.assertIn("history", data)

        created_group = GrupCompeticio.objects.get(competicio=self.comp, display_num=expected_group_num)
        self.ins_free_a.refresh_from_db()
        self.ins_free_b.refresh_from_db()
        self.assertEqual(self.ins_free_a.grup, expected_group_num)
        self.assertEqual(self.ins_free_b.grup, expected_group_num)
        self.assertEqual(self.ins_free_a.ordre_competicio, 1)
        self.assertEqual(self.ins_free_b.ordre_competicio, 2)
        self.assertEqual(created_group.actiu, True)

    def test_groups_assign_contract_warns_when_programmed_group_is_reduced_but_not_emptied(self):
        resp = self._post_groups_contract(
            "assign",
            {
                "group_id": self.other_group.id,
                "scope": "selected",
                "selected_ids": [self.ins_programmed_a.id],
                "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
            },
        )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("ok"))
        self.assertIn("history", data)
        self.assertTrue(data.get("warnings") or data.get("warning") or data.get("notice"))

        self.ins_programmed_a.refresh_from_db()
        self.ins_programmed_b.refresh_from_db()
        self.assertEqual(self.ins_programmed_a.grup, 2)
        self.assertEqual(self.ins_programmed_b.grup, 1)

    def test_groups_unassign_contract_blocks_when_programmed_group_would_be_emptied(self):
        single_group = GrupCompeticio.objects.create(
            competicio=self.comp,
            legacy_num=5,
            display_num=5,
            nom="Programmed Single",
            actiu=True,
        )
        single_member = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Programmed Single Member",
            ordre_sortida=7,
            grup=5,
        )
        self._attach_rotation_to_group(single_group)

        resp = self._post_groups_contract(
            "unassign",
            {
                "scope": "selected",
                "selected_ids": [single_member.id],
                "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
            },
        )

        self.assertEqual(resp.status_code, 400)
        self.assertIn("program", resp.content.decode("utf-8").lower())

    def test_groups_delete_contract_deactivates_empty_group_only(self):
        resp = self._post_groups_contract(
            "delete",
            {"group_id": self.empty_group.id},
        )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("ok"))
        self.assertIn("history", data)

        self.empty_group.refresh_from_db()
        self.assertFalse(self.empty_group.actiu)

    def test_groups_delete_empty_contract_deactivates_all_empty_groups_only(self):
        extra_empty_group = GrupCompeticio.objects.create(
            competicio=self.comp,
            legacy_num=6,
            display_num=6,
            nom="Extra Empty",
            actiu=True,
        )

        resp = self._post_groups_contract("delete-empty", {})

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("ok"))
        self.assertEqual(data.get("deleted"), 2)

        self.empty_group.refresh_from_db()
        extra_empty_group.refresh_from_db()
        self.programmed_group.refresh_from_db()
        self.other_group.refresh_from_db()

        self.assertFalse(self.empty_group.actiu)
        self.assertFalse(extra_empty_group.actiu)
        self.assertTrue(self.programmed_group.actiu)
        self.assertTrue(self.other_group.actiu)

    def test_groups_delete_all_contract_deactivates_non_programmed_groups_only(self):
        resp = self._post_groups_contract("delete-all", {})

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("ok"))
        self.assertEqual(int(data.get("deleted") or 0), 2)
        self.assertEqual(int(data.get("protected") or 0), 1)
        self.assertEqual(
            [row.get("label") for row in (data.get("protected_groups") or [])],
            [group_label(self.programmed_group)],
        )

        self.programmed_group.refresh_from_db()
        self.other_group.refresh_from_db()
        self.empty_group.refresh_from_db()
        self.ins_programmed_a.refresh_from_db()
        self.ins_programmed_b.refresh_from_db()
        self.ins_other.refresh_from_db()

        self.assertTrue(self.programmed_group.actiu)
        self.assertFalse(self.other_group.actiu)
        self.assertFalse(self.empty_group.actiu)
        self.assertEqual(self.ins_programmed_a.grup_competicio_id, self.programmed_group.id)
        self.assertEqual(self.ins_programmed_b.grup_competicio_id, self.programmed_group.id)
        self.assertIsNone(self.ins_other.grup_competicio_id)
        self.assertIsNone(self.ins_other.grup)
        self.assertIsNone(self.ins_other.ordre_competicio)
