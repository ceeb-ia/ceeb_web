import json
from importlib import import_module
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


class CompetitiveFranjaTimingTests(_BaseTrampoliDataMixin, TestCase):
    def setUp(self):
        self.comp = self._create_competicio("Comp Franja Timing")
        User = get_user_model()
        self.user = User.objects.create_user(
            username="franja_timing_owner",
            password="testpass123",
            email="franja-timing-owner@example.com",
        )
        CompeticioMembership.objects.create(
            user=self.user,
            competicio=self.comp,
            role=CompeticioMembership.Role.OWNER,
            is_active=True,
        )
        self.client.force_login(self.user)
        self.f1 = RotacioFranja.objects.create(
            competicio=self.comp,
            hora_inici="09:00",
            hora_fi="09:30",
            ordre=1,
            titol="Franja 1",
            tipus=RotacioFranja.TIPUS_COMPETITION,
        )
        self.f2 = RotacioFranja.objects.create(
            competicio=self.comp,
            hora_inici="09:30",
            hora_fi="10:00",
            ordre=2,
            titol="Franja 2",
            tipus=RotacioFranja.TIPUS_COMPETITION,
        )
        self.f3 = RotacioFranja.objects.create(
            competicio=self.comp,
            hora_inici="10:00",
            hora_fi="10:30",
            ordre=3,
            titol="Franja 3",
            tipus=RotacioFranja.TIPUS_COMPETITION,
        )

    def _post_json(self, url, payload):
        return self.client.post(
            url,
            data=json.dumps(payload),
            content_type="application/json",
        )

    def test_competitive_create_preview_and_confirm_shift_following_franges(self):
        url = reverse("rotacions_franja_create", kwargs={"pk": self.comp.id})
        preview_res = self._post_json(
            url,
            {
                "hora_inici": "09:30",
                "hora_fi": "09:45",
                "titol": "Nova",
                "tipus": "competition",
                "preview_only": True,
            },
        )
        self.assertEqual(preview_res.status_code, 200)
        preview = preview_res.json()
        self.assertTrue(preview["requires_confirmation"])
        self.assertEqual(preview["origin"]["new_start"], "09:30")
        self.assertEqual(preview["origin"]["new_end"], "09:45")
        self.assertEqual([item["franja_id"] for item in preview["affected"]], [self.f2.id, self.f3.id])
        self.assertEqual(preview["affected"][0]["new_start"], "09:45")
        self.assertEqual(preview["affected"][0]["new_end"], "10:15")

        apply_res = self._post_json(
            url,
            {
                "hora_inici": "09:30",
                "hora_fi": "09:45",
                "titol": "Nova",
                "tipus": "competition",
                "confirm_reorder": True,
            },
        )
        self.assertEqual(apply_res.status_code, 200)
        franges = list(RotacioFranja.objects.filter(competicio=self.comp).order_by("ordre", "id"))
        self.assertEqual(
            [(fr.titol, str(fr.hora_inici), str(fr.hora_fi), fr.ordre) for fr in franges],
            [
                ("Franja 1", "09:00:00", "09:30:00", 1),
                ("Nova", "09:30:00", "09:45:00", 2),
                ("Franja 2", "09:45:00", "10:15:00", 3),
                ("Franja 3", "10:15:00", "10:45:00", 4),
            ],
        )

    def test_competitive_create_rejects_overlap_with_previous_competitive_franja(self):
        url = reverse("rotacions_franja_create", kwargs={"pk": self.comp.id})
        res = self._post_json(
            url,
            {
                "hora_inici": "09:15",
                "hora_fi": "09:45",
                "titol": "Solapa",
                "tipus": "competition",
                "preview_only": True,
            },
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("solapa", res.content.decode("utf-8").lower())

    def test_competitive_row_reorder_preview_and_confirm_preserve_durations(self):
        url = reverse("rotacions_franges_reorder", kwargs={"pk": self.comp.id})
        preview_res = self._post_json(
            url,
            {
                "dragged_id": self.f3.id,
                "target_id": self.f2.id,
                "position": "before",
                "preview_only": True,
            },
        )
        self.assertEqual(preview_res.status_code, 200)
        preview = preview_res.json()
        self.assertTrue(preview["requires_confirmation"])
        self.assertEqual(preview["origin"]["franja_id"], self.f3.id)
        self.assertEqual(preview["origin"]["new_start"], "09:30")
        self.assertEqual(preview["origin"]["new_end"], "10:00")
        self.assertEqual([item["franja_id"] for item in preview["affected"]], [self.f3.id, self.f2.id])

        apply_res = self._post_json(
            url,
            {
                "dragged_id": self.f3.id,
                "target_id": self.f2.id,
                "position": "before",
                "confirm_reorder": True,
            },
        )
        self.assertEqual(apply_res.status_code, 200)
        franges = list(RotacioFranja.objects.filter(competicio=self.comp).order_by("ordre", "id"))
        self.assertEqual(
            [(fr.titol, str(fr.hora_inici), str(fr.hora_fi), fr.ordre) for fr in franges],
            [
                ("Franja 1", "09:00:00", "09:30:00", 1),
                ("Franja 3", "09:30:00", "10:00:00", 2),
                ("Franja 2", "10:00:00", "10:30:00", 3),
            ],
        )


