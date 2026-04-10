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
from ...services.classificacions.classificacio_templates import (
    normalize_particions_schema as _normalize_particions_schema,
    schema_to_template_schema as _schema_to_template_schema,
    template_schema_to_competicio_schema as _template_schema_to_competicio_schema_service,
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


def _template_schema_to_competicio_schema(*args, **kwargs):
    schema_local, mapping_warnings, mapping, _compat_meta = _template_schema_to_competicio_schema_service(
        *args,
        **kwargs,
    )
    return schema_local, mapping_warnings, mapping


class PublicLiveTokenViewsTests(_BaseTrampoliDataMixin, TestCase):
    def setUp(self):
        self.comp = self._create_competicio("Comp Public Live")
        self.token = PublicLiveToken.objects.create(
            competicio=self.comp,
            label="Pantalla principal",
            is_active=True,
        )

    def test_public_live_portal_renders_public_live_page(self):
        url = reverse("public_live_portal", kwargs={"token": self.token.id})
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        body = res.content.decode("utf-8")
        self.assertIn("Classificacions", body)
        self.assertIn(reverse("public_live_classificacions_data", kwargs={"token": self.token.id}), body)
        self.assertIn("function renderTeamRawDetailCell(v, col)", body)
        self.assertIn("team-raw-summary", body)
        self.assertIn('v._kind === "team_raw_detail"', body)

    def test_public_live_portal_rejects_revoked_token(self):
        self.token.is_active = False
        self.token.revoked_at = timezone.now()
        self.token.save(update_fields=["is_active", "revoked_at"])

        url = reverse("public_live_portal", kwargs={"token": self.token.id})
        res = self.client.get(url)
        self.assertEqual(res.status_code, 403)

    def test_public_live_qr_png_returns_png(self):
        url = reverse("public_live_qr_png", kwargs={"token": self.token.id})
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res["Content-Type"], "image/png")

    def test_public_live_data_requires_valid_token(self):
        url = reverse("public_live_classificacions_data", kwargs={"token": self.token.id})
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json().get("ok"))
        self.assertEqual(
            res.json().get("permissions", {}).get("can_view_media"),
            False,
        )

    def test_public_live_data_exposes_media_permission_flag(self):
        self.token.can_view_media = True
        self.token.save(update_fields=["can_view_media"])

        url = reverse("public_live_classificacions_data", kwargs={"token": self.token.id})
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json().get("ok"))
        self.assertEqual(
            res.json().get("permissions", {}).get("can_view_media"),
            True,
        )
