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


class InscripcionsSortFilteringAndDisplayTests(InscripcionsSortFlowBaseMixin, TestCase):
    def test_sort_apply_tab_preserves_tab_block_order(self):
        beta_1 = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="David",
            categoria="Beta",
            ordre_sortida=1,
        )
        beta_2 = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Carla",
            categoria="Beta",
            ordre_sortida=2,
        )
        alpha_1 = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Biel",
            categoria="Alpha",
            ordre_sortida=3,
        )
        alpha_2 = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Anna",
            categoria="Alpha",
            ordre_sortida=4,
        )

        response = self._post_json(
            "inscripcions_sort_apply",
            {
                "sort_key": "nom_i_cognoms",
                "sort_dir": "asc",
                "scope": "tab",
                "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "group_by": ["categoria"],
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json().get("ok"))

        actual_ids = list(
            Inscripcio.objects.filter(competicio=self.comp)
            .order_by("ordre_sortida", "id")
            .values_list("id", flat=True)
        )
        self.assertEqual(actual_ids, [beta_2.id, beta_1.id, alpha_2.id, alpha_1.id])

    def test_sort_apply_all_can_reorder_tab_blocks(self):
        beta_1 = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="David",
            categoria="Beta",
            ordre_sortida=1,
        )
        beta_2 = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Carla",
            categoria="Beta",
            ordre_sortida=2,
        )
        alpha_1 = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Biel",
            categoria="Alpha",
            ordre_sortida=3,
        )
        alpha_2 = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Anna",
            categoria="Alpha",
            ordre_sortida=4,
        )

        response = self._post_json(
            "inscripcions_sort_apply",
            {
                "sort_key": "nom_i_cognoms",
                "sort_dir": "asc",
                "scope": "all",
                "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "group_by": ["categoria"],
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json().get("ok"))

        actual_ids = list(
            Inscripcio.objects.filter(competicio=self.comp)
            .order_by("ordre_sortida", "id")
            .values_list("id", flat=True)
        )
        self.assertEqual(actual_ids, [alpha_2.id, alpha_1.id, beta_2.id, beta_1.id])

    def test_sort_apply_group_reorders_full_group_even_outside_filter(self):
        visible = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Zulu",
            entitat="Club A",
            ordre_sortida=1,
            grup=1,
        )
        hidden = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Alpha",
            entitat="Club B",
            ordre_sortida=2,
            grup=1,
        )
        other = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Resta",
            ordre_sortida=3,
            grup=2,
        )

        response = self._post_json(
            "inscripcions_sort_apply",
            {
                "sort_key": "nom_i_cognoms",
                "sort_dir": "asc",
                "scope": "group",
                "group_num": 1,
                "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": "Club A"},
                "group_by": [],
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json().get("ok"))

        visible.refresh_from_db()
        hidden.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual(hidden.ordre_sortida, 1)
        self.assertEqual(visible.ordre_sortida, 2)
        self.assertEqual(other.ordre_sortida, 3)

    def test_sort_apply_all_groups_reorders_full_visible_groups_only(self):
        g1_visible = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Zulu",
            entitat="Club A",
            ordre_sortida=1,
            grup=1,
        )
        g1_hidden = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Alpha",
            entitat="Club B",
            ordre_sortida=2,
            grup=1,
        )
        g2_visible = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Yara",
            entitat="Club A",
            ordre_sortida=3,
            grup=2,
        )
        g2_hidden = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Beta",
            entitat="Club B",
            ordre_sortida=4,
            grup=2,
        )
        g3_first = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Omega",
            entitat="Club C",
            ordre_sortida=5,
            grup=3,
        )
        g3_second = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Gamma",
            entitat="Club D",
            ordre_sortida=6,
            grup=3,
        )

        response = self._post_json(
            "inscripcions_sort_apply",
            {
                "sort_key": "nom_i_cognoms",
                "sort_dir": "asc",
                "scope": "all_groups",
                "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": "Club A"},
                "group_by": [],
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json().get("ok"))

        g1_visible.refresh_from_db()
        g1_hidden.refresh_from_db()
        g2_visible.refresh_from_db()
        g2_hidden.refresh_from_db()
        g3_first.refresh_from_db()
        g3_second.refresh_from_db()

        self.assertEqual(g1_hidden.ordre_sortida, 1)
        self.assertEqual(g1_visible.ordre_sortida, 2)
        self.assertEqual(g2_hidden.ordre_sortida, 3)
        self.assertEqual(g2_visible.ordre_sortida, 4)
        self.assertEqual(g3_first.ordre_sortida, 5)
        self.assertEqual(g3_second.ordre_sortida, 6)

    def test_group_competition_order_preview_returns_saved_order_for_full_group(self):
        first = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Participant 1",
            entitat="Club A",
            grup=2,
            ordre_sortida=1,
        )
        second = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Participant 2",
            entitat="Club B",
            grup=2,
            ordre_sortida=2,
        )
        third = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Participant 3",
            entitat="Club C",
            grup=2,
            ordre_sortida=3,
        )
        group = GrupCompeticio.objects.get(competicio=self.comp, display_num=2)
        group.nom = "Final"
        group.save(update_fields=["nom"])
        Inscripcio.objects.filter(pk=first.pk).update(ordre_competicio=2)
        Inscripcio.objects.filter(pk=second.pk).update(ordre_competicio=1)
        Inscripcio.objects.filter(pk=third.pk).update(ordre_competicio=3)

        response = self._post_json(
            "inscripcions_group_competition_order_preview",
            {"group_num": 2},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data.get("ok"))
        self.assertEqual(data.get("group_label"), "Final")
        self.assertEqual(data.get("total_count"), 3)
        self.assertTrue(data.get("can_edit"))
        self.assertEqual(
            data.get("rows"),
            [
                {
                    "id": second.id,
                    "label": "Participant 2",
                    "secondary_label": "Club B",
                    "saved_order": 1,
                },
                {
                    "id": first.id,
                    "label": "Participant 1",
                    "secondary_label": "Club A",
                    "saved_order": 2,
                },
                {
                    "id": third.id,
                    "label": "Participant 3",
                    "secondary_label": "Club C",
                    "saved_order": 3,
                },
            ],
        )

    def test_group_competition_order_preview_falls_back_to_group_number_when_unnamed(self):
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Sense nom de grup",
            grup=3,
            ordre_sortida=1,
        )

        response = self._post_json(
            "inscripcions_group_competition_order_preview",
            {"group_num": 3},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data.get("ok"))
        self.assertEqual(data.get("group_label"), "Grup 3")

    def test_group_competition_order_preview_allows_readonly_and_save_remains_protected(self):
        first = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Readonly 1",
            grup=1,
            ordre_sortida=1,
        )
        second = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Readonly 2",
            grup=1,
            ordre_sortida=2,
        )

        self.client.force_login(self.readonly_user)

        preview_res = self._post_json(
            "inscripcions_group_competition_order_preview",
            {"group_num": 1},
        )
        self.assertEqual(preview_res.status_code, 200)
        self.assertFalse(preview_res.json().get("can_edit"))

        save_url = reverse("inscripcions_save_group_competition_order", kwargs={"pk": self.comp.id})
        save_res = self.client.post(
            save_url,
            data=json.dumps({"group_num": 1, "ids": [second.id, first.id]}),
            content_type="application/json",
        )
        self.assertEqual(save_res.status_code, 403)

    def test_bulk_group_competition_order_reorders_each_group_by_native_field(self):
        g1_z = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Zulu",
            entitat="Club Z",
            grup=1,
            ordre_sortida=1,
        )
        g1_a = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Alpha",
            entitat="Club A",
            grup=1,
            ordre_sortida=2,
        )
        g2_d = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Delta",
            entitat="Club D",
            grup=2,
            ordre_sortida=3,
        )
        g2_b = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Beta",
            entitat="Club B",
            grup=2,
            ordre_sortida=4,
        )

        preview = self._post_json(
            "inscripcions_bulk_group_competition_order_preview",
            {"sort_key": "nom_i_cognoms", "sort_dir": "asc", "scope": "all"},
        )
        self.assertEqual(preview.status_code, 200)
        preview_data = preview.json().get("preview")
        self.assertEqual(preview_data.get("groups_total"), 2)
        self.assertEqual(preview_data.get("changed_groups"), 2)

        response = self._post_json(
            "inscripcions_bulk_group_competition_order_apply",
            {"sort_key": "nom_i_cognoms", "sort_dir": "asc", "scope": "all"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json().get("ok"))

        actual_g1 = list(
            Inscripcio.objects.filter(competicio=self.comp, grup=1)
            .order_by("ordre_competicio", "id")
            .values_list("id", flat=True)
        )
        actual_g2 = list(
            Inscripcio.objects.filter(competicio=self.comp, grup=2)
            .order_by("ordre_competicio", "id")
            .values_list("id", flat=True)
        )
        self.assertEqual(actual_g1, [g1_a.id, g1_z.id])
        self.assertEqual(actual_g2, [g2_b.id, g2_d.id])

        g1_z.refresh_from_db()
        g1_a.refresh_from_db()
        g2_d.refresh_from_db()
        g2_b.refresh_from_db()
        self.assertEqual((g1_z.ordre_sortida, g1_a.ordre_sortida, g2_d.ordre_sortida, g2_b.ordre_sortida), (1, 2, 3, 4))

    def test_bulk_group_competition_order_supports_excel_extra_fields_and_selected_scope(self):
        self.comp.inscripcions_schema = {
            "columns": [
                {"code": "excel__nivell", "label": "Nivell", "kind": "extra"},
            ]
        }
        self.comp.save(update_fields=["inscripcions_schema"])
        g1 = ensure_group_for_display_num(self.comp, 1)
        g2 = ensure_group_for_display_num(self.comp, 2)
        g1_low = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Baix",
            extra={"excel__nivell": "B"},
            grup=1,
            ordre_sortida=1,
        )
        g1_high = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Alt",
            extra={"excel__nivell": "A"},
            grup=1,
            ordre_sortida=2,
        )
        g2_low = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Resta baix",
            extra={"excel__nivell": "B"},
            grup=2,
            ordre_sortida=3,
        )
        g2_high = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Resta alt",
            extra={"excel__nivell": "A"},
            grup=2,
            ordre_sortida=4,
        )

        response = self._post_json(
            "inscripcions_bulk_group_competition_order_apply",
            {
                "sort_key": "excel__nivell",
                "sort_dir": "asc",
                "scope": "selected",
                "group_ids": [g1.id],
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json().get("ok"))

        actual_g1 = list(
            Inscripcio.objects.filter(competicio=self.comp, grup=1)
            .order_by("ordre_competicio", "id")
            .values_list("id", flat=True)
        )
        actual_g2 = list(
            Inscripcio.objects.filter(competicio=self.comp, grup=2)
            .order_by("ordre_competicio", "id")
            .values_list("id", flat=True)
        )
        self.assertEqual(actual_g1, [g1_high.id, g1_low.id])
        self.assertEqual(actual_g2, [g2_low.id, g2_high.id])

        undo = self._post_history("undo")
        self.assertEqual(undo.status_code, 200)
        actual_g1_after_undo = list(
            Inscripcio.objects.filter(competicio=self.comp, grup=1)
            .order_by("ordre_competicio", "id")
            .values_list("id", flat=True)
        )
        self.assertEqual(actual_g1_after_undo, [g1_low.id, g1_high.id])

    def test_sort_apply_reapplying_existing_criterion_keeps_priority(self):
        i1 = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="I1",
            entitat="B",
            categoria="beta",
            ordre_sortida=1,
        )
        i2 = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="I2",
            entitat="A",
            categoria="alpha",
            ordre_sortida=2,
        )
        i3 = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="I3",
            entitat="A",
            categoria="beta",
            ordre_sortida=3,
        )
        i4 = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="I4",
            entitat="B",
            categoria="alpha",
            ordre_sortida=4,
        )

        base_payload = {
            "scope": "all",
            "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
            "group_by": [],
        }

        r1 = self._post_json(
            "inscripcions_sort_apply",
            {**base_payload, "sort_key": "entitat", "sort_dir": "asc"},
        )
        self.assertEqual(r1.status_code, 200)
        self.assertTrue(r1.json().get("ok"))

        r2 = self._post_json(
            "inscripcions_sort_apply",
            {**base_payload, "sort_key": "categoria", "sort_dir": "asc"},
        )
        self.assertEqual(r2.status_code, 200)
        self.assertTrue(r2.json().get("ok"))

        # Reapliquem el primer criteri amb una direccio diferent.
        # Ha de mantenir la prioritat original (primer criteri = mes important).
        r3 = self._post_json(
            "inscripcions_sort_apply",
            {**base_payload, "sort_key": "entitat", "sort_dir": "desc"},
        )
        self.assertEqual(r3.status_code, 200)
        self.assertTrue(r3.json().get("ok"))
        self.assertEqual(r3.json().get("stack_count"), 2)

        actual_ids = list(
            Inscripcio.objects.filter(competicio=self.comp)
            .order_by("ordre_sortida", "id")
            .values_list("id", flat=True)
        )
        self.assertEqual(actual_ids, [i4.id, i1.id, i2.id, i3.id])

    def test_custom_sort_save_reapplies_active_stack_immediately(self):
        i1 = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="I1",
            categoria="B",
            ordre_sortida=1,
        )
        i2 = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="I2",
            categoria="C",
            ordre_sortida=2,
        )
        i3 = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="I3",
            categoria="A",
            ordre_sortida=3,
        )

        base_payload = {
            "scope": "all",
            "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
            "group_by": [],
        }

        r_apply = self._post_json(
            "inscripcions_sort_apply",
            {**base_payload, "sort_key": "categoria", "sort_dir": "custom"},
        )
        self.assertEqual(r_apply.status_code, 200)
        self.assertTrue(r_apply.json().get("ok"))

        r_custom = self._post_json(
            "inscripcions_sort_custom_save",
            {
                "sort_key": "categoria",
                "order": ["C", "B", "A"],
                "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "group_by": [],
                "preserve_missing_context": True,
            },
        )
        self.assertEqual(r_custom.status_code, 200)
        data = r_custom.json()
        self.assertTrue(data.get("ok"))
        self.assertTrue(data.get("reapplied"))
        self.assertEqual(data.get("stack_count"), 1)

        actual_ids = list(
            Inscripcio.objects.filter(competicio=self.comp)
            .order_by("ordre_sortida", "id")
            .values_list("id", flat=True)
        )
        self.assertEqual(actual_ids, [i2.id, i1.id, i3.id])

    def test_competition_order_tail_toggle_requires_active_stack(self):
        first = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Alpha",
            grup=1,
            ordre_sortida=1,
            ordre_competicio=2,
        )
        second = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Beta",
            grup=1,
            ordre_sortida=2,
            ordre_competicio=1,
        )

        response = self._toggle_competition_tail(True)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data.get("ok"))
        self.assertFalse(data.get("applied"))
        self.assertEqual(data.get("reason"), "no_stack")
        self.assertFalse(data.get("competition_order_tail"))

        actual_ids = list(
            Inscripcio.objects.filter(competicio=self.comp)
            .order_by("ordre_sortida", "id")
            .values_list("id", flat=True)
        )
        self.assertEqual(actual_ids, [first.id, second.id])

    def test_competition_order_tail_is_less_prioritary_than_active_stack(self):
        g1_first = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Alpha",
            grup=1,
            ordre_sortida=1,
            ordre_competicio=2,
        )
        g1_second = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Beta",
            grup=1,
            ordre_sortida=2,
            ordre_competicio=1,
        )
        g2_first = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Charlie",
            grup=2,
            ordre_sortida=3,
            ordre_competicio=2,
        )
        g2_second = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Delta",
            grup=2,
            ordre_sortida=4,
            ordre_competicio=1,
        )

        apply_resp = self._post_json(
            "inscripcions_sort_apply",
            {
                "sort_key": "nom_i_cognoms",
                "sort_dir": "asc",
                "scope": "all_groups",
                "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "group_by": [],
            },
        )
        self.assertEqual(apply_resp.status_code, 200)
        data = apply_resp.json()
        self.assertTrue(data.get("ok"))
        self.assertTrue(data.get("competition_order_tail"))

        actual_ids = list(
            Inscripcio.objects.filter(competicio=self.comp)
            .order_by("ordre_sortida", "id")
            .values_list("id", flat=True)
        )
        self.assertEqual(actual_ids, [g1_first.id, g1_second.id, g2_first.id, g2_second.id])

    def test_sort_apply_enables_competition_order_tail_by_default(self):
        g1_first = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Alpha",
            categoria="Mateixa",
            grup=1,
            ordre_sortida=1,
            ordre_competicio=2,
        )
        g1_second = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Beta",
            categoria="Mateixa",
            grup=1,
            ordre_sortida=2,
            ordre_competicio=1,
        )
        g2_first = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Charlie",
            categoria="Mateixa",
            grup=2,
            ordre_sortida=3,
            ordre_competicio=2,
        )
        g2_second = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Delta",
            categoria="Mateixa",
            grup=2,
            ordre_sortida=4,
            ordre_competicio=1,
        )

        apply_resp = self._post_json(
            "inscripcions_sort_apply",
            {
                "sort_key": "categoria",
                "sort_dir": "asc",
                "scope": "all_groups",
                "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "group_by": [],
            },
        )
        self.assertEqual(apply_resp.status_code, 200)
        data = apply_resp.json()
        self.assertTrue(data.get("ok"))
        self.assertTrue(data.get("competition_order_tail"))

        actual_ids = list(
            Inscripcio.objects.filter(competicio=self.comp)
            .order_by("ordre_sortida", "id")
            .values_list("id", flat=True)
        )
        self.assertEqual(actual_ids, [g1_second.id, g1_first.id, g2_second.id, g2_first.id])

