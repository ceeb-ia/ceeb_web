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



from ._base import InscripcionsSortFlowBaseMixin


class InscripcionsGroupsPreviewAndApplyTests(InscripcionsSortFlowBaseMixin, TestCase):
    def test_history_undo_redo_restores_sort_apply(self):
        i1 = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="I1",
            entitat="B",
            ordre_sortida=1,
        )
        i2 = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="I2",
            entitat="A",
            ordre_sortida=2,
        )
        base_payload = {
            "scope": "all",
            "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
            "group_by": [],
        }

        r_apply = self._post_json(
            "inscripcions_sort_apply",
            {**base_payload, "sort_key": "entitat", "sort_dir": "asc"},
        )
        self.assertEqual(r_apply.status_code, 200)
        self.assertTrue(r_apply.json().get("ok"))

        ordered_ids = list(
            Inscripcio.objects.filter(competicio=self.comp)
            .order_by("ordre_sortida", "id")
            .values_list("id", flat=True)
        )
        self.assertEqual(ordered_ids, [i2.id, i1.id])

        r_undo = self._post_history("undo")
        self.assertEqual(r_undo.status_code, 200)
        self.assertTrue(r_undo.json().get("ok"))
        self.assertTrue(r_undo.json().get("applied"))

        undone_ids = list(
            Inscripcio.objects.filter(competicio=self.comp)
            .order_by("ordre_sortida", "id")
            .values_list("id", flat=True)
        )
        self.assertEqual(undone_ids, [i1.id, i2.id])

        r_redo = self._post_history("redo")
        self.assertEqual(r_redo.status_code, 200)
        self.assertTrue(r_redo.json().get("ok"))
        self.assertTrue(r_redo.json().get("applied"))

        redone_ids = list(
            Inscripcio.objects.filter(competicio=self.comp)
            .order_by("ordre_sortida", "id")
            .values_list("id", flat=True)
        )
        self.assertEqual(redone_ids, [i2.id, i1.id])

    def test_history_new_action_clears_redo_branch(self):
        i1 = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="I1",
            entitat="B",
            ordre_sortida=1,
        )
        i2 = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="I2",
            entitat="A",
            ordre_sortida=2,
        )
        base_payload = {
            "scope": "all",
            "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
            "group_by": [],
        }
        self._post_json(
            "inscripcions_sort_apply",
            {**base_payload, "sort_key": "entitat", "sort_dir": "asc"},
        )
        self._post_history("undo")

        r_reorder = self._post_json(
            "inscripcions_reorder",
            {
                "ids": [i2.id, i1.id],
                "moved_id": i2.id,
                "new_index": 0,
                "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "group_by": [],
            },
        )
        self.assertEqual(r_reorder.status_code, 200)
        self.assertTrue(r_reorder.json().get("ok"))
        self.assertFalse(r_reorder.json().get("history", {}).get("can_redo"))

        r_redo = self._post_history("redo")
        self.assertEqual(r_redo.status_code, 200)
        self.assertTrue(r_redo.json().get("ok"))
        self.assertFalse(r_redo.json().get("applied"))

    def test_sort_undo_compat_wrapper_uses_global_history(self):
        i1 = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="I1",
            entitat="B",
            ordre_sortida=1,
        )
        i2 = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="I2",
            entitat="A",
            ordre_sortida=2,
        )
        base_payload = {
            "scope": "all",
            "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
            "group_by": [],
        }
        self._post_json(
            "inscripcions_sort_apply",
            {**base_payload, "sort_key": "entitat", "sort_dir": "asc"},
        )

        r_compat = self._post_json(
            "inscripcions_sort_undo",
            {"filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""}, "group_by": []},
        )
        self.assertEqual(r_compat.status_code, 200)
        data = r_compat.json()
        self.assertTrue(data.get("ok"))
        self.assertEqual(data.get("restored"), 1)

        ids_after = list(
            Inscripcio.objects.filter(competicio=self.comp)
            .order_by("ordre_sortida", "id")
            .values_list("id", flat=True)
        )
        self.assertEqual(ids_after, [i1.id, i2.id])

    def test_reorder_cleans_orphan_group_labels(self):
        i1 = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="I1",
            ordre_sortida=1,
            grup=1,
        )
        i2 = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="I2",
            ordre_sortida=2,
            grup=2,
        )
        self.comp.inscripcions_view = {"group_names": {"1": "Un", "2": "Dos"}}
        self.comp.save(update_fields=["inscripcions_view"])

        resp = self._post_json(
            "inscripcions_reorder",
            {
                "ids": [i2.id, i1.id],
                "moved_id": i1.id,
                "new_index": 1,
                "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "group_by": [],
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get("ok"))

        i1.refresh_from_db()
        self.assertEqual(i1.grup, 1)

        self.comp.refresh_from_db()
        self.assertEqual(self.comp.inscripcions_view.get("group_names"), {"1": "Un", "2": "Dos"})

    def test_reorder_prefers_target_group_over_previous_row_group(self):
        i1 = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="I1",
            ordre_sortida=1,
            grup=1,
        )
        i2 = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="I2",
            ordre_sortida=2,
            grup=1,
        )
        i3 = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="I3",
            ordre_sortida=3,
            grup=2,
        )
        i4 = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="I4",
            ordre_sortida=4,
            grup=2,
        )

        resp = self._post_json(
            "inscripcions_reorder",
            {
                "ids": [i2.id, i1.id, i3.id, i4.id],
                "moved_id": i1.id,
                "new_index": 1,
                "target_group": 2,
                "mode": "group_edit",
                "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "group_by": [],
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get("ok"))

        i1.refresh_from_db()
        self.assertEqual(i1.grup, 2)
        self.assertEqual(i1.ordre_competicio, 3)

    def test_reorder_without_header_target_keeps_legacy_edge_behavior(self):
        i1 = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="I1",
            ordre_sortida=1,
            grup=1,
        )
        i2 = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="I2",
            ordre_sortida=2,
            grup=2,
        )

        resp = self._post_json(
            "inscripcions_reorder",
            {
                "ids": [i2.id, i1.id],
                "moved_id": i2.id,
                "new_index": 0,
                "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "group_by": [],
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get("ok"))

        i2.refresh_from_db()
        self.assertEqual(i2.grup, 2)

    def test_save_group_competition_order_updates_only_real_order(self):
        i1 = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="I1",
            ordre_sortida=1,
            grup=1,
        )
        i2 = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="I2",
            ordre_sortida=2,
            grup=1,
        )

        resp = self._post_json(
            "inscripcions_save_group_competition_order",
            {
                "group_num": 1,
                "ids": [i2.id, i1.id],
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get("ok"))

        i1.refresh_from_db()
        i2.refresh_from_db()
        self.assertEqual(i1.ordre_sortida, 1)
        self.assertEqual(i2.ordre_sortida, 2)
        self.assertEqual(i2.ordre_competicio, 1)
        self.assertEqual(i1.ordre_competicio, 2)

    def test_groups_preview_marks_existing_group_as_reduced_when_members_remain_outside_filter(self):
        moving = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Visible",
            entitat="Club A",
            ordre_sortida=1,
            grup=1,
        )
        staying = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Resta",
            entitat="Club B",
            ordre_sortida=2,
            grup=1,
        )

        resp = self._post_json(
            "inscripcions_groups_from_sort",
            self._groups_payload(filters={"q": "", "categoria": "", "subcategoria": "", "entitat": "Club A"}),
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("ok"))

        preview = data.get("preview") or {}
        existing_groups = preview.get("existing_groups") or []
        self.assertEqual(len(existing_groups), 1)
        existing = existing_groups[0]
        self.assertEqual(existing.get("group_num"), 1)
        self.assertEqual(existing.get("impact_kind"), "reduced")
        self.assertEqual(existing.get("members_count"), 2)
        self.assertEqual(existing.get("moving_members_count"), 1)
        self.assertEqual(existing.get("remaining_members_count"), 1)
        self.assertEqual(existing.get("moving_member_names_preview"), [moving.nom_i_cognoms])

        sources = existing.get("sources") or []
        self.assertEqual(sum(int(row.get("moving_count") or 0) for row in sources), 1)
        self.assertEqual(sum(int(row.get("remaining_count") or 0) for row in sources), 1)
        self.assertEqual(preview.get("existing_members_total"), 2)

        self.assertEqual(staying.grup, 1)

    def test_groups_preview_selected_scope_uses_selected_ids_even_outside_filters(self):
        club_a = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Club A",
            entitat="Club A",
            ordre_sortida=1,
            grup=None,
        )
        club_b = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Club B",
            entitat="Club B",
            ordre_sortida=2,
            grup=None,
        )

        resp = self._post_json(
            "inscripcions_groups_from_sort",
            self._groups_payload(
                scope="selected",
                selected_ids=[club_b.id],
                filters={"q": "", "categoria": "", "subcategoria": "", "entitat": "Club A"},
            ),
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("ok"))

        preview = data.get("preview") or {}
        self.assertEqual(preview.get("members_total"), 1)
        groups = preview.get("groups") or []
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].get("member_names_preview"), [club_b.nom_i_cognoms])
        self.assertEqual(club_a.grup, None)
        self.assertEqual(club_b.grup, None)

    def test_groups_preview_selected_scope_can_use_sort_context_filters_for_bucket_resolution(self):
        ins_free_a = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Free A",
            ordre_sortida=1,
            grup=None,
            categoria="Alevi",
        )
        ins_free_b = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Free B",
            ordre_sortida=2,
            grup=None,
            categoria="Infantil",
        )

        sort_resp = self._post_json(
            "inscripcions_sort_apply",
            {
                "scope": "all",
                "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "group_by": [],
                "sort_key": "categoria",
                "sort_dir": "asc",
            },
        )
        self.assertEqual(sort_resp.status_code, 200)
        self.assertTrue(sort_resp.json().get("ok"))

        resp = self._post_json(
            "inscripcions_groups_from_sort",
            self._groups_payload(
                strategy="per_bucket",
                scope="selected",
                selected_ids=[ins_free_a.id, ins_free_b.id],
                filters={"q": "", "categoria": "", "subcategoria": "", "entitat": "Club Inexistent"},
                sort_context_filters={"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
            ),
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("ok"))

        preview = data.get("preview") or {}
        groups = preview.get("groups") or []
        self.assertEqual(len(groups), 2)
        self.assertEqual(sorted(group.get("members_count") for group in groups), [1, 1])

    def test_groups_preview_marks_existing_group_as_removed_when_all_members_move(self):
        first = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Primer",
            ordre_sortida=1,
            grup=1,
        )
        second = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Segon",
            ordre_sortida=2,
            grup=1,
        )
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Sense grup",
            ordre_sortida=3,
            grup=None,
        )

        resp = self._post_json(
            "inscripcions_groups_from_sort",
            self._groups_payload(),
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("ok"))

        preview = data.get("preview") or {}
        existing_groups = preview.get("existing_groups") or []
        self.assertEqual(len(existing_groups), 1)
        existing = existing_groups[0]
        self.assertEqual(existing.get("group_num"), 1)
        self.assertEqual(existing.get("impact_kind"), "removed")
        self.assertEqual(existing.get("members_count"), 2)
        self.assertEqual(existing.get("moving_members_count"), 2)
        self.assertEqual(existing.get("remaining_members_count"), 0)
        self.assertEqual(existing.get("moving_member_names_preview"), [first.nom_i_cognoms, second.nom_i_cognoms])
        self.assertEqual(preview.get("existing_groups_total"), 1)

    def test_groups_preview_existing_group_exposes_existing_name_label(self):
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Primer",
            ordre_sortida=1,
            grup=1,
        )
        renumber_groups_for_competicio(self.comp)
        group = GrupCompeticio.objects.get(competicio=self.comp, display_num=1)
        group.nom = "Final"
        group.save(update_fields=["nom"])

        resp = self._post_json(
            "inscripcions_groups_from_sort",
            self._groups_payload(),
        )
        self.assertEqual(resp.status_code, 200)

        preview = resp.json().get("preview") or {}
        existing_groups = preview.get("existing_groups") or []
        self.assertEqual(len(existing_groups), 1)
        self.assertEqual(existing_groups[0].get("group_label"), "Final")

    def test_groups_preview_suggests_name_from_single_sort_bucket(self):
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="A1",
            entitat="Club A",
            ordre_sortida=1,
            grup=None,
        )
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="A2",
            entitat="Club A",
            ordre_sortida=2,
            grup=None,
        )

        sort_payload = {
            "scope": "all",
            "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
            "group_by": [],
            "sort_key": "entitat",
            "sort_dir": "asc",
        }
        sort_resp = self._post_json("inscripcions_sort_apply", sort_payload)
        self.assertEqual(sort_resp.status_code, 200)
        self.assertTrue(sort_resp.json().get("ok"))

        resp = self._post_json(
            "inscripcions_groups_from_sort",
            self._groups_payload(strategy="per_bucket"),
        )
        self.assertEqual(resp.status_code, 200)

        groups = (resp.json().get("preview") or {}).get("groups") or []
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].get("suggested_name"), "Club A")

    def test_groups_preview_suggests_name_from_single_tab_bucket(self):
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="A1",
            categoria="Alevi",
            ordre_sortida=1,
            grup=None,
        )
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="A2",
            categoria="Alevi",
            ordre_sortida=2,
            grup=None,
        )

        resp = self._post_json(
            "inscripcions_groups_from_sort",
            self._groups_payload(strategy="per_bucket", group_by=["categoria"]),
        )
        self.assertEqual(resp.status_code, 200)

        groups = (resp.json().get("preview") or {}).get("groups") or []
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].get("suggested_name"), "Alevi")

    def test_groups_preview_auto_resolution_combines_group_by_and_sort(self):
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Alevi A",
            categoria="Alevi",
            entitat="Club A",
            ordre_sortida=1,
            grup=None,
        )
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Alevi B",
            categoria="Alevi",
            entitat="Club B",
            ordre_sortida=2,
            grup=None,
        )
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Infantil A",
            categoria="Infantil",
            entitat="Club A",
            ordre_sortida=3,
            grup=None,
        )

        sort_resp = self._post_json(
            "inscripcions_sort_apply",
            {
                "scope": "all",
                "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "group_by": ["categoria"],
                "sort_key": "entitat",
                "sort_dir": "asc",
            },
        )
        self.assertEqual(sort_resp.status_code, 200)
        self.assertTrue(sort_resp.json().get("ok"))

        resp = self._post_json(
            "inscripcions_groups_from_sort",
            self._groups_payload(strategy="per_bucket", group_by=["categoria"]),
        )
        self.assertEqual(resp.status_code, 200)

        data = resp.json()
        self.assertEqual(data.get("resolution_mode"), "auto")
        self.assertEqual(data.get("layers_used"), ["tabs", "sort"])
        self.assertEqual(data.get("effective_bucket_count"), 3)

        preview = data.get("preview") or {}
        groups = preview.get("groups") or []
        self.assertEqual(len(groups), 3)
        self.assertEqual(preview.get("layers_used"), ["tabs", "sort"])
        self.assertEqual(preview.get("effective_bucket_count"), 3)
        self.assertEqual(
            [group.get("suggested_name") for group in groups],
            ["Alevi · Club A", "Infantil · Club A", "Alevi · Club B"],
        )

    def test_groups_preview_auto_resolution_uses_tabs_only_without_sort(self):
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Alevi 1",
            categoria="Alevi",
            ordre_sortida=1,
            grup=None,
        )
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Alevi 2",
            categoria="Alevi",
            ordre_sortida=2,
            grup=None,
        )
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Infantil 1",
            categoria="Infantil",
            ordre_sortida=3,
            grup=None,
        )

        resp = self._post_json(
            "inscripcions_groups_from_sort",
            self._groups_payload(strategy="per_bucket", group_by=["categoria"]),
        )
        self.assertEqual(resp.status_code, 200)

        data = resp.json()
        self.assertEqual(data.get("layers_used"), ["tabs"])
        self.assertEqual(data.get("effective_bucket_count"), 2)
        groups = (data.get("preview") or {}).get("groups") or []
        self.assertEqual([group.get("suggested_name") for group in groups], ["Alevi", "Infantil"])

    def test_groups_preview_auto_resolution_uses_sort_only_without_group_by(self):
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Club A 1",
            entitat="Club A",
            ordre_sortida=1,
            grup=None,
        )
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Club A 2",
            entitat="Club A",
            ordre_sortida=2,
            grup=None,
        )
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Club B 1",
            entitat="Club B",
            ordre_sortida=3,
            grup=None,
        )

        sort_resp = self._post_json(
            "inscripcions_sort_apply",
            {
                "scope": "all",
                "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "group_by": [],
                "sort_key": "entitat",
                "sort_dir": "asc",
            },
        )
        self.assertEqual(sort_resp.status_code, 200)
        self.assertTrue(sort_resp.json().get("ok"))

        resp = self._post_json(
            "inscripcions_groups_from_sort",
            self._groups_payload(strategy="per_bucket"),
        )
        self.assertEqual(resp.status_code, 200)

        data = resp.json()
        self.assertEqual(data.get("layers_used"), ["sort"])
        self.assertEqual(data.get("effective_bucket_count"), 2)
        groups = (data.get("preview") or {}).get("groups") or []
        self.assertEqual([group.get("suggested_name") for group in groups], ["Club A", "Club B"])

    def test_groups_preview_auto_resolution_deduplicates_redundant_sort_partition(self):
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Alevi 1",
            categoria="Alevi",
            ordre_sortida=1,
            grup=None,
        )
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Infantil 1",
            categoria="Infantil",
            ordre_sortida=2,
            grup=None,
        )

        sort_resp = self._post_json(
            "inscripcions_sort_apply",
            {
                "scope": "all",
                "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "group_by": ["categoria"],
                "sort_key": "categoria",
                "sort_dir": "asc",
            },
        )
        self.assertEqual(sort_resp.status_code, 200)
        self.assertTrue(sort_resp.json().get("ok"))

        resp = self._post_json(
            "inscripcions_groups_from_sort",
            self._groups_payload(strategy="per_bucket", group_by=["categoria"]),
        )
        self.assertEqual(resp.status_code, 200)

        data = resp.json()
        self.assertEqual(data.get("layers_used"), ["tabs"])
        self.assertEqual(data.get("effective_bucket_count"), 2)

    def test_groups_preview_selected_keys_accept_combined_bucket_key(self):
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Alevi A",
            categoria="Alevi",
            entitat="Club A",
            ordre_sortida=1,
            grup=None,
        )
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Alevi B",
            categoria="Alevi",
            entitat="Club B",
            ordre_sortida=2,
            grup=None,
        )

        sort_resp = self._post_json(
            "inscripcions_sort_apply",
            {
                "scope": "all",
                "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "group_by": ["categoria"],
                "sort_key": "entitat",
                "sort_dir": "asc",
            },
        )
        self.assertEqual(sort_resp.status_code, 200)
        self.assertTrue(sort_resp.json().get("ok"))

        records = list(
            _build_inscripcions_filtered_qs(
                self.comp,
                {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
            ).order_by("ordre_sortida", "id")
        )
        resolution = _resolve_group_creation_buckets(
            self.comp,
            records,
            group_codes=["categoria"],
            partition_codes=["entitat"],
        )
        combined_key = ((resolution.get("buckets") or [])[0] or {}).get("key")

        resp = self._post_json(
            "inscripcions_groups_from_sort",
            self._groups_payload(
                strategy="per_bucket",
                group_by=["categoria"],
                selected_keys=[combined_key],
            ),
        )
        self.assertEqual(resp.status_code, 200)

        data = resp.json()
        self.assertEqual(data.get("buckets_applied"), 1)
        preview = data.get("preview") or {}
        self.assertEqual(preview.get("members_total"), 1)
        groups = preview.get("groups") or []
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].get("suggested_name"), "Alevi · Club A")

    def test_groups_preview_tab_merges_apply_before_combining_with_sort(self):
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Alevi A",
            categoria="Alevi",
            entitat="Club A",
            ordre_sortida=1,
            grup=None,
        )
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Infantil A",
            categoria="Infantil",
            entitat="Club A",
            ordre_sortida=2,
            grup=None,
        )
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Alevi B",
            categoria="Alevi",
            entitat="Club B",
            ordre_sortida=3,
            grup=None,
        )
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Infantil B",
            categoria="Infantil",
            entitat="Club B",
            ordre_sortida=4,
            grup=None,
        )
        self.comp.tab_merges = {
            "categoria": [[json.dumps(["Alevi"], ensure_ascii=False), json.dumps(["Infantil"], ensure_ascii=False)]]
        }
        self.comp.save(update_fields=["tab_merges"])

        sort_resp = self._post_json(
            "inscripcions_sort_apply",
            {
                "scope": "all",
                "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "group_by": ["categoria"],
                "sort_key": "entitat",
                "sort_dir": "asc",
            },
        )
        self.assertEqual(sort_resp.status_code, 200)
        self.assertTrue(sort_resp.json().get("ok"))

        resp = self._post_json(
            "inscripcions_groups_from_sort",
            self._groups_payload(strategy="per_bucket", group_by=["categoria"]),
        )
        self.assertEqual(resp.status_code, 200)

        data = resp.json()
        self.assertEqual(data.get("layers_used"), ["tabs", "sort"])
        self.assertEqual(data.get("effective_bucket_count"), 2)
        groups = (data.get("preview") or {}).get("groups") or []
        self.assertEqual(
            [group.get("suggested_name") for group in groups],
            ["Alevi + Infantil · Club A", "Alevi + Infantil · Club B"],
        )

    def test_groups_preview_existing_groups_use_combined_sources(self):
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Alevi A",
            categoria="Alevi",
            entitat="Club A",
            ordre_sortida=1,
            grup=1,
        )
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Alevi B",
            categoria="Alevi",
            entitat="Club B",
            ordre_sortida=2,
            grup=1,
        )

        sort_resp = self._post_json(
            "inscripcions_sort_apply",
            {
                "scope": "all",
                "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "group_by": ["categoria"],
                "sort_key": "entitat",
                "sort_dir": "asc",
            },
        )
        self.assertEqual(sort_resp.status_code, 200)
        self.assertTrue(sort_resp.json().get("ok"))

        records = list(
            _build_inscripcions_filtered_qs(
                self.comp,
                {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
            ).order_by("ordre_sortida", "id")
        )
        resolution = _resolve_group_creation_buckets(
            self.comp,
            records,
            group_codes=["categoria"],
            partition_codes=["entitat"],
        )
        combined_key = ((resolution.get("buckets") or [])[0] or {}).get("key")

        resp = self._post_json(
            "inscripcions_groups_from_sort",
            self._groups_payload(
                strategy="per_bucket",
                group_by=["categoria"],
                selected_keys=[combined_key],
            ),
        )
        self.assertEqual(resp.status_code, 200)

        preview = resp.json().get("preview") or {}
        existing_groups = preview.get("existing_groups") or []
        self.assertEqual(len(existing_groups), 1)
        existing = existing_groups[0]
        self.assertEqual(existing.get("impact_kind"), "reduced")
        source_map = {row.get("label"): row for row in existing.get("sources") or []}
        self.assertEqual(source_map["Alevi / Club A"]["moving_count"], 1)
        self.assertEqual(source_map["Alevi / Club A"]["remaining_count"], 0)
        self.assertEqual(source_map["Alevi / Club B"]["moving_count"], 0)
        self.assertEqual(source_map["Alevi / Club B"]["remaining_count"], 1)

    def test_groups_preview_builds_composed_name_from_weighted_sources(self):
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="A1",
            entitat="Club A",
            ordre_sortida=1,
            grup=None,
        )
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="A2",
            entitat="Club A",
            ordre_sortida=2,
            grup=None,
        )
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="B1",
            entitat="Club B",
            ordre_sortida=3,
            grup=None,
        )

        resp = self._post_json(
            "inscripcions_groups_from_sort",
            self._groups_payload(
                source="tabs",
                strategy="count",
                group_count=1,
                group_by=["entitat"],
            ),
        )
        self.assertEqual(resp.status_code, 200)

        groups = (resp.json().get("preview") or {}).get("groups") or []
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].get("suggested_name"), "Club A + Club B")

    def test_groups_preview_selected_scope_adds_main_filter_components_to_name(self):
        club_a = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="A1",
            categoria="Alevi",
            entitat="Club A",
            ordre_sortida=1,
            grup=None,
        )
        club_b = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="B1",
            categoria="Alevi",
            entitat="Club B",
            ordre_sortida=2,
            grup=None,
        )

        resp = self._post_json(
            "inscripcions_groups_from_sort",
            {
                "resolution_mode": "auto",
                "strategy": "count",
                "group_count": 1,
                "preview_only": True,
                "scope": "selected",
                "selected_ids": [club_a.id, club_b.id],
                "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "sort_context_filters": {"q": "", "categoria": "Alevi", "subcategoria": "", "entitat": ""},
                "group_by": ["entitat"],
            },
        )
        self.assertEqual(resp.status_code, 200)

        groups = (resp.json().get("preview") or {}).get("groups") or []
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].get("suggested_name"), "Alevi · Club A + Club B")

    def test_groups_preview_deduplicates_filters_already_present_in_bucket_name(self):
        ins = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="A1",
            categoria="Alevi",
            entitat="Club A",
            ordre_sortida=1,
            grup=None,
        )

        resp = self._post_json(
            "inscripcions_groups_from_sort",
            {
                "resolution_mode": "auto",
                "strategy": "count",
                "group_count": 1,
                "preview_only": True,
                "scope": "selected",
                "selected_ids": [ins.id],
                "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "sort_context_filters": {"q": "", "categoria": "Alevi", "subcategoria": "", "entitat": ""},
                "group_by": ["categoria", "entitat"],
            },
        )
        self.assertEqual(resp.status_code, 200)

        groups = (resp.json().get("preview") or {}).get("groups") or []
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].get("suggested_name"), "Alevi · Club A")

    def test_groups_preview_workspace_filters_override_main_filters_for_same_field(self):
        ins = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="A1",
            categoria="Alevi",
            entitat="Club A",
            ordre_sortida=1,
            grup=None,
        )

        resp = self._post_json(
            "inscripcions_groups_from_sort",
            {
                "resolution_mode": "auto",
                "strategy": "count",
                "group_count": 1,
                "preview_only": True,
                "scope": "selected",
                "selected_ids": [ins.id],
                "filters": {"q": "", "categoria": "Infantil", "subcategoria": "", "entitat": ""},
                "sort_context_filters": {"q": "", "categoria": "Alevi", "subcategoria": "", "entitat": ""},
                "group_by": ["entitat"],
            },
        )
        self.assertEqual(resp.status_code, 200)

        groups = (resp.json().get("preview") or {}).get("groups") or []
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].get("suggested_name"), "Infantil · Club A")

    def test_groups_preview_compacts_multiselect_filter_values_after_three_labels(self):
        ins = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="A1",
            ordre_sortida=1,
            grup=None,
        )

        resp = self._post_json(
            "inscripcions_groups_from_sort",
            {
                "resolution_mode": "auto",
                "strategy": "count",
                "group_count": 1,
                "preview_only": True,
                "scope": "selected",
                "selected_ids": [ins.id],
                "filters": {
                    "q": "",
                    "categoria": "",
                    "subcategoria": "",
                    "entitat": "",
                    "entitats": ["Club A", "Club B", "Club C", "Club D"],
                },
                "sort_context_filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "group_by": [],
            },
        )
        self.assertEqual(resp.status_code, 200)

        groups = (resp.json().get("preview") or {}).get("groups") or []
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].get("suggested_name"), "Club A + Club B + Club C + 1 més")

    def test_groups_preview_disambiguates_duplicate_suggested_names(self):
        for idx in range(1, 5):
            Inscripcio.objects.create(
                competicio=self.comp,
                nom_i_cognoms=f"A{idx}",
                entitat="Club A",
                ordre_sortida=idx,
                grup=None,
            )

        resp = self._post_json(
            "inscripcions_groups_from_sort",
            self._groups_payload(
                source="tabs",
                strategy="count",
                group_count=2,
                group_by=["entitat"],
            ),
        )
        self.assertEqual(resp.status_code, 200)

        groups = (resp.json().get("preview") or {}).get("groups") or []
        self.assertEqual(
            [group.get("suggested_name") for group in groups],
            ["Club A (1)", "Club A (2)"],
        )

    def test_groups_preview_ignores_generic_fallback_labels(self):
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Sense Nom 1",
            ordre_sortida=1,
            grup=None,
        )
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Sense Nom 2",
            ordre_sortida=2,
            grup=None,
        )

        resp = self._post_json("inscripcions_groups_from_sort", self._groups_payload())
        self.assertEqual(resp.status_code, 200)

        groups = (resp.json().get("preview") or {}).get("groups") or []
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].get("suggested_name"), "")

    def test_groups_apply_persists_suggested_name_without_overwriting_existing_manual_names(self):
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Manual",
            entitat="Club X",
            ordre_sortida=1,
            grup=1,
        )
        renumber_groups_for_competicio(self.comp)
        existing_group = GrupCompeticio.objects.get(competicio=self.comp, display_num=1)
        existing_group.nom = "Manual"
        existing_group.save(update_fields=["nom"])
        self.comp.inscripcions_view = {"group_names": {"1": "Manual"}}
        self.comp.save(update_fields=["inscripcions_view"])

        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Nou 1",
            entitat="Club A",
            ordre_sortida=2,
            grup=None,
        )
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Nou 2",
            entitat="Club A",
            ordre_sortida=3,
            grup=None,
        )

        resp = self._post_json(
            "inscripcions_groups_from_sort",
            self._groups_payload(
                source="tabs",
                strategy="per_bucket",
                preview_only=False,
                group_by=["entitat"],
                filters={"q": "", "categoria": "", "subcategoria": "", "entitat": "Club A"},
            ),
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get("ok"))

        existing_group.refresh_from_db()
        self.assertEqual(existing_group.nom, "Manual")

        new_group = GrupCompeticio.objects.get(competicio=self.comp, display_num=2)
        self.assertEqual(new_group.nom, "Club A")

        self.comp.refresh_from_db()
        self.assertEqual(
            self.comp.inscripcions_view.get("group_names"),
            {"1": "Manual", "2": "Club A"},
        )

    def test_groups_apply_deactivates_group_that_becomes_empty(self):
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Primer",
            ordre_sortida=1,
            grup=1,
        )
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Segon",
            ordre_sortida=2,
            grup=1,
        )
        renumber_groups_for_competicio(self.comp)
        old_group = GrupCompeticio.objects.get(competicio=self.comp, display_num=1)
        self.assertTrue(old_group.actiu)

        resp = self._post_json(
            "inscripcions_groups_from_sort",
            self._groups_payload(preview_only=False),
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("ok"))

        old_group.refresh_from_db()
        self.assertFalse(old_group.actiu)
        self.assertTrue(
            GrupCompeticio.objects.filter(competicio=self.comp, display_num=2, actiu=True).exists()
        )

    def test_groups_apply_with_rotations_keeps_programmed_group_when_members_remain(self):
        first = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Primer",
            entitat="Club A",
            ordre_sortida=1,
            grup=1,
        )
        second = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Segon",
            entitat="Club B",
            ordre_sortida=2,
            grup=1,
        )
        group = first.grup_competicio
        franja = RotacioFranja.objects.create(
            competicio=self.comp,
            hora_inici="09:00",
            hora_fi="09:30",
            ordre=1,
            titol="Franja 1",
        )
        estacio = RotacioEstacio.objects.create(
            competicio=self.comp,
            tipus="descans",
            ordre=1,
            actiu=True,
        )
        assignacio = RotacioAssignacio.objects.create(
            competicio=self.comp,
            franja=franja,
            estacio=estacio,
        )
        RotacioAssignacioGrup.objects.create(assignacio=assignacio, grup=group, ordre=1)

        resp = self._post_json(
            "inscripcions_groups_from_sort",
            self._groups_payload(
                preview_only=False,
                filters={"q": "", "categoria": "", "subcategoria": "", "entitat": "Club A"},
            ),
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("ok"))

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.grup, 2)
        self.assertEqual(second.grup, 1)
        self.assertTrue(
            GrupCompeticio.objects.filter(competicio=self.comp, display_num=2, actiu=True).exists()
        )

    def test_groups_apply_with_rotations_rejects_emptying_programmed_group(self):
        first = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Primer",
            ordre_sortida=1,
            grup=1,
        )
        second = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Segon",
            ordre_sortida=2,
            grup=1,
        )
        group = first.grup_competicio
        franja = RotacioFranja.objects.create(
            competicio=self.comp,
            hora_inici="09:00",
            hora_fi="09:30",
            ordre=1,
            titol="Franja 1",
        )
        estacio = RotacioEstacio.objects.create(
            competicio=self.comp,
            tipus="descans",
            ordre=1,
            actiu=True,
        )
        assignacio = RotacioAssignacio.objects.create(
            competicio=self.comp,
            franja=franja,
            estacio=estacio,
        )
        RotacioAssignacioGrup.objects.create(assignacio=assignacio, grup=group, ordre=1)

        resp = self._post_json(
            "inscripcions_groups_from_sort",
            self._groups_payload(preview_only=False),
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("No es pot deixar buit un grup inclos al programa de rotacions", resp.content.decode("utf-8"))

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.grup, 1)
        self.assertEqual(second.grup, 1)


