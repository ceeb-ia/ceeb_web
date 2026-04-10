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


class ScoringUpdatesCursorTests(_BaseTrampoliDataMixin, TestCase):
    def setUp(self):
        self.comp = self._create_competicio("Comp Scoring Cursor")
        self.app = self._create_aparell("TRAMP_CURSOR", "Tramp Cursor")
        self.comp_app = self._create_comp_aparell(self.comp, self.app, ordre=1, actiu=True)
        self.ins_1 = self._create_inscripcio(self.comp, "P1", ordre=1)
        self.ins_2 = self._create_inscripcio(self.comp, "P2", ordre=2)
        self.ins_3 = self._create_inscripcio(self.comp, "P3", ordre=3)
        User = get_user_model()
        self.user = User.objects.create_user(
            username="scoring_cursor_user",
            password="testpass123",
            email="scoring-cursor@example.com",
        )
        CompeticioMembership.objects.create(
            user=self.user,
            competicio=self.comp,
            role=CompeticioMembership.Role.SCORING,
            is_active=True,
        )
        self.client.force_login(self.user)

    def test_scoring_updates_use_after_id_for_same_timestamp(self):
        base_time = timezone.now()
        e1 = ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins_1,
            exercici=1,
            comp_aparell=self.comp_app,
            inputs={},
            outputs={},
            total=1,
        )
        e2 = ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins_2,
            exercici=1,
            comp_aparell=self.comp_app,
            inputs={},
            outputs={},
            total=2,
        )
        e3 = ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins_3,
            exercici=1,
            comp_aparell=self.comp_app,
            inputs={},
            outputs={},
            total=3,
        )
        ScoreEntry.objects.filter(pk__in=[e1.id, e2.id, e3.id]).update(updated_at=base_time)

        url = reverse("scoring_updates", kwargs={"pk": self.comp.id})
        with patch("competicions_trampoli.views.scoring.updates.SCORING_UPDATES_LIMIT", 2):
            first_res = self.client.get(url, {"since": (base_time - timedelta(seconds=1)).isoformat()})
            self.assertEqual(first_res.status_code, 200)
            first_body = first_res.json()
            self.assertTrue(first_body.get("has_more"))
            self.assertEqual([row.get("inscripcio_id") for row in first_body.get("updates", [])], [self.ins_1.id, self.ins_2.id])

            second_res = self.client.get(
                url,
                {
                    "since": first_body.get("next_since"),
                    "after_id": first_body.get("next_after_id"),
                },
            )
        self.assertEqual(second_res.status_code, 200)
        self.assertEqual([row.get("inscripcio_id") for row in second_res.json().get("updates", [])], [self.ins_3.id])

    def test_scoring_updates_without_since_returns_empty_feed_contract(self):
        url = reverse("scoring_updates", kwargs={"pk": self.comp.id})
        res = self.client.get(url)

        self.assertEqual(res.status_code, 200)
        self.assertJSONEqual(
            res.content.decode("utf-8"),
            {
                "ok": True,
                "now": None,
                "updates": [],
                "next_since": None,
                "next_after_id": "",
                "has_more": False,
            },
        )


