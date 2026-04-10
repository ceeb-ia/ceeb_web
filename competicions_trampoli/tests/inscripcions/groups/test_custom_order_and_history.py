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


class InscripcionsSortOrderingAndHistoryTests(InscripcionsSortFlowBaseMixin, TestCase):
    def test_competition_order_tail_toggle_applies_and_persists_to_ordre_sortida(self):
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
        self.assertTrue(apply_resp.json().get("ok"))

        toggle_resp = self._toggle_competition_tail(True)
        self.assertEqual(toggle_resp.status_code, 200)
        data = toggle_resp.json()
        self.assertTrue(data.get("ok"))
        self.assertTrue(data.get("applied"))
        self.assertTrue(data.get("competition_order_tail"))

        actual_ids = list(
            Inscripcio.objects.filter(competicio=self.comp)
            .order_by("ordre_sortida", "id")
            .values_list("id", flat=True)
        )
        self.assertEqual(actual_ids, [g1_second.id, g1_first.id, g2_second.id, g2_first.id])

    def test_competition_order_tail_toggle_disable_restores_stack_only_order(self):
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
        self.assertTrue(apply_resp.json().get("ok"))

        toggle_on_resp = self._toggle_competition_tail(True)
        self.assertEqual(toggle_on_resp.status_code, 200)
        self.assertTrue(toggle_on_resp.json().get("competition_order_tail"))

        disable_resp = self._toggle_competition_tail(False)
        self.assertEqual(disable_resp.status_code, 200)
        data = disable_resp.json()
        self.assertTrue(data.get("ok"))
        self.assertFalse(data.get("competition_order_tail"))

        actual_ids = list(
            Inscripcio.objects.filter(competicio=self.comp)
            .order_by("ordre_sortida", "id")
            .values_list("id", flat=True)
        )
        self.assertEqual(actual_ids, [g1_first.id, g1_second.id, g2_first.id, g2_second.id])

    def test_competition_order_tail_manual_disable_is_respected_on_next_sort_apply(self):
        g1_first = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Alpha",
            categoria="Mateixa",
            subcategoria="Compartida",
            grup=1,
            ordre_sortida=1,
            ordre_competicio=2,
        )
        g1_second = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Beta",
            categoria="Mateixa",
            subcategoria="Compartida",
            grup=1,
            ordre_sortida=2,
            ordre_competicio=1,
        )
        g2_first = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Charlie",
            categoria="Mateixa",
            subcategoria="Compartida",
            grup=2,
            ordre_sortida=3,
            ordre_competicio=2,
        )
        g2_second = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Delta",
            categoria="Mateixa",
            subcategoria="Compartida",
            grup=2,
            ordre_sortida=4,
            ordre_competicio=1,
        )

        first_apply = self._post_json(
            "inscripcions_sort_apply",
            {
                "sort_key": "categoria",
                "sort_dir": "asc",
                "scope": "all_groups",
                "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "group_by": [],
            },
        )
        self.assertEqual(first_apply.status_code, 200)
        self.assertTrue(first_apply.json().get("competition_order_tail"))

        disable_resp = self._toggle_competition_tail(False)
        self.assertEqual(disable_resp.status_code, 200)
        self.assertFalse(disable_resp.json().get("competition_order_tail"))

        second_apply = self._post_json(
            "inscripcions_sort_apply",
            {
                "sort_key": "subcategoria",
                "sort_dir": "asc",
                "scope": "all_groups",
                "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "group_by": [],
            },
        )
        self.assertEqual(second_apply.status_code, 200)
        data = second_apply.json()
        self.assertTrue(data.get("ok"))
        self.assertFalse(data.get("competition_order_tail"))

        actual_ids = list(
            Inscripcio.objects.filter(competicio=self.comp)
            .order_by("ordre_sortida", "id")
            .values_list("id", flat=True)
        )
        self.assertEqual(actual_ids, [g1_first.id, g1_second.id, g2_first.id, g2_second.id])

    def test_competition_order_tail_places_missing_saved_order_last_and_stable(self):
        first_missing = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Alpha",
            categoria="Mateixa",
            grup=1,
            ordre_sortida=1,
        )
        second_with = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Beta",
            categoria="Mateixa",
            grup=1,
            ordre_sortida=2,
            ordre_competicio=2,
        )
        third_with = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Charlie",
            categoria="Mateixa",
            grup=1,
            ordre_sortida=3,
            ordre_competicio=1,
        )
        second_missing = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Delta",
            categoria="Mateixa",
            grup=1,
            ordre_sortida=4,
        )
        Inscripcio.objects.filter(pk__in=[first_missing.pk, second_missing.pk]).update(
            ordre_competicio=None
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
        self.assertTrue(apply_resp.json().get("ok"))

        toggle_resp = self._toggle_competition_tail(True)
        self.assertEqual(toggle_resp.status_code, 200)
        self.assertTrue(toggle_resp.json().get("competition_order_tail"))

        actual_ids = list(
            Inscripcio.objects.filter(competicio=self.comp)
            .order_by("ordre_sortida", "id")
            .values_list("id", flat=True)
        )
        self.assertEqual(
            actual_ids,
            [third_with.id, second_with.id, first_missing.id, second_missing.id],
        )

    def test_sort_clear_resets_competition_order_tail_flag(self):
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Alpha",
            categoria="Mateixa",
            grup=1,
            ordre_sortida=1,
            ordre_competicio=2,
        )
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Beta",
            categoria="Mateixa",
            grup=1,
            ordre_sortida=2,
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
        self.assertTrue(apply_resp.json().get("ok"))
        self.assertTrue(self._toggle_competition_tail(True).json().get("competition_order_tail"))

        clear_resp = self._post_json(
            "inscripcions_sort_clear",
            {
                "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "group_by": [],
            },
        )
        self.assertEqual(clear_resp.status_code, 200)
        data = clear_resp.json()
        self.assertTrue(data.get("ok"))
        self.assertTrue(data.get("cleared"))
        self.assertFalse(data.get("competition_order_tail"))

    def test_competition_order_tail_applies_independently_per_group(self):
        g1_first = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Anna",
            categoria="Mateixa",
            grup=1,
            ordre_sortida=1,
            ordre_competicio=2,
        )
        g2_first = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Biel",
            categoria="Mateixa",
            grup=2,
            ordre_sortida=2,
            ordre_competicio=2,
        )
        g1_second = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Carla",
            categoria="Mateixa",
            grup=1,
            ordre_sortida=3,
            ordre_competicio=1,
        )
        g2_second = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="David",
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
                "scope": "all",
                "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "group_by": [],
            },
        )
        self.assertEqual(apply_resp.status_code, 200)
        self.assertTrue(apply_resp.json().get("ok"))

        toggle_resp = self._toggle_competition_tail(True)
        self.assertEqual(toggle_resp.status_code, 200)
        self.assertTrue(toggle_resp.json().get("competition_order_tail"))

        actual_ids = list(
            Inscripcio.objects.filter(competicio=self.comp)
            .order_by("ordre_sortida", "id")
            .values_list("id", flat=True)
        )
        self.assertEqual(actual_ids, [g1_second.id, g2_second.id, g1_first.id, g2_first.id])

    def test_custom_sort_save_does_not_reapply_if_mode_is_not_custom(self):
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
            {**base_payload, "sort_key": "categoria", "sort_dir": "asc"},
        )
        self.assertEqual(r_apply.status_code, 200)
        self.assertTrue(r_apply.json().get("ok"))

        after_apply_ids = list(
            Inscripcio.objects.filter(competicio=self.comp)
            .order_by("ordre_sortida", "id")
            .values_list("id", flat=True)
        )
        self.assertEqual(after_apply_ids, [i3.id, i1.id, i2.id])

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
        self.assertFalse(data.get("reapplied"))
        self.assertEqual(data.get("reapplied_updated"), 0)

        after_custom_save_ids = list(
            Inscripcio.objects.filter(competicio=self.comp)
            .order_by("ordre_sortida", "id")
            .values_list("id", flat=True)
        )
        self.assertEqual(after_custom_save_ids, [i3.id, i1.id, i2.id])

    def test_custom_sort_values_for_group_use_named_labels(self):
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="G1",
            grup=2,
            ordre_sortida=1,
        )
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="G2",
            grup=2,
            ordre_sortida=2,
        )
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="G3",
            grup=3,
            ordre_sortida=3,
        )
        group = GrupCompeticio.objects.get(competicio=self.comp, display_num=2)
        group.nom = "Final"
        group.save(update_fields=["nom"])

        response = self._post_json(
            "inscripcions_sort_custom_values",
            {
                "sort_key": "grup",
                "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "group_by": [],
            },
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data.get("ok"))

        values_by_token = {str(item["value"]): item for item in data.get("values", [])}
        self.assertEqual(values_by_token["2"]["label"], "Final")
        self.assertEqual(values_by_token["2"]["count"], 2)
        self.assertEqual(values_by_token["3"]["label"], "Grup 3")

    def test_custom_sort_values_for_equip_use_team_names_and_skip_empty(self):
        equip, _first = self._create_native_team_member("Equip Alpha", "E1", ordre_sortida=1)
        second = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="E2",
            ordre_sortida=2,
        )
        self._assign_equip(self.comp, second, equip)
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Sense equip",
            ordre_sortida=3,
        )

        response = self._post_json(
            "inscripcions_sort_custom_values",
            {
                "sort_key": "equip",
                "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "group_by": [],
            },
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data.get("ok"))
        self.assertEqual(
            data.get("values"),
            [
                {
                    "value": str(equip.id),
                    "label": "Equip Alpha",
                    "count": 2,
                    "detected": True,
                    "in_custom": False,
                }
            ],
        )

    def test_equip_sort_apply_uses_team_name_for_fallback(self):
        equip_beta, ins_beta = self._create_native_team_member("Beta", "Beta 1", ordre_sortida=1)
        equip_alpha, ins_alpha = self._create_native_team_member("Alpha", "Alpha 1", ordre_sortida=2)

        response = self._post_json(
            "inscripcions_sort_apply",
            {
                "sort_key": "equip",
                "sort_dir": "asc",
                "scope": "all",
                "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "group_by": [],
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json().get("ok"))

        actual_ids = list(
            Inscripcio.objects.filter(competicio=self.comp)
            .order_by("ordre_sortida", "id")
            .values_list("id", flat=True)
        )
        self.assertEqual(actual_ids, [ins_alpha.id, ins_beta.id])

    def test_equip_custom_sort_save_reapplies_active_stack_immediately(self):
        equip_alpha, ins_alpha = self._create_native_team_member("Alpha", "Alpha 1", ordre_sortida=1)
        equip_beta, ins_beta = self._create_native_team_member("Beta", "Beta 1", ordre_sortida=2)

        base_payload = {
            "scope": "all",
            "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
            "group_by": [],
        }

        r_apply = self._post_json(
            "inscripcions_sort_apply",
            {**base_payload, "sort_key": "equip", "sort_dir": "custom"},
        )
        self.assertEqual(r_apply.status_code, 200)
        self.assertTrue(r_apply.json().get("ok"))

        r_custom = self._post_json(
            "inscripcions_sort_custom_save",
            {
                "sort_key": "equip",
                "order": [str(equip_beta.id), str(equip_alpha.id)],
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
        self.assertEqual(actual_ids, [ins_beta.id, ins_alpha.id])

    def test_equip_custom_order_survives_team_rename(self):
        equip_alpha, ins_alpha = self._create_native_team_member("Alpha", "Alpha 1", ordre_sortida=1)
        equip_beta, ins_beta = self._create_native_team_member("Beta", "Beta 1", ordre_sortida=2)

        base_payload = {
            "scope": "all",
            "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
            "group_by": [],
        }

        self._post_json(
            "inscripcions_sort_apply",
            {**base_payload, "sort_key": "equip", "sort_dir": "custom"},
        )
        save_resp = self._post_json(
            "inscripcions_sort_custom_save",
            {
                "sort_key": "equip",
                "order": [str(equip_beta.id), str(equip_alpha.id)],
                "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "group_by": [],
                "preserve_missing_context": True,
            },
        )
        self.assertEqual(save_resp.status_code, 200)
        self.assertTrue(save_resp.json().get("ok"))

        equip_alpha.nom = "Alfa"
        equip_alpha.save(update_fields=["nom"])
        equip_beta.nom = "Zeta"
        equip_beta.save(update_fields=["nom"])

        asc_resp = self._post_json(
            "inscripcions_sort_apply",
            {**base_payload, "sort_key": "equip", "sort_dir": "asc"},
        )
        self.assertEqual(asc_resp.status_code, 200)
        self.assertTrue(asc_resp.json().get("ok"))

        custom_resp = self._post_json(
            "inscripcions_sort_apply",
            {**base_payload, "sort_key": "equip", "sort_dir": "custom"},
        )
        self.assertEqual(custom_resp.status_code, 200)
        self.assertTrue(custom_resp.json().get("ok"))

        actual_ids = list(
            Inscripcio.objects.filter(competicio=self.comp)
            .order_by("ordre_sortida", "id")
            .values_list("id", flat=True)
        )
        self.assertEqual(actual_ids, [ins_beta.id, ins_alpha.id])

