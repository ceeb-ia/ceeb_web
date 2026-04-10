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



class InscripcioAparellExclusioModelTests(_BaseTrampoliDataMixin, TestCase):
    def test_clean_rejects_cross_competition_pair(self):
        comp_a = self._create_competicio("Comp A")
        comp_b = self._create_competicio("Comp B")
        ins = self._create_inscripcio(comp_a, "Participant A")

        app_b = self._create_aparell("DMT_B", "DMT B")
        comp_app_b = self._create_comp_aparell(comp_b, app_b)

        ex = InscripcioAparellExclusio(inscripcio=ins, comp_aparell=comp_app_b)
        with self.assertRaises(ValidationError):
            ex.full_clean()



class InscripcionsSetAparellsViewTests(_BaseTrampoliDataMixin, TestCase):
    def setUp(self):
        self.comp = self._create_competicio()
        self.user = self._login_competicio_user(
            self.comp,
            role=CompeticioMembership.Role.EDITOR,
            username_prefix="set_aparells_editor",
        )
        app1 = self._create_aparell("TRAMP_I", "Tramp I")
        app2 = self._create_aparell("TRAMP_II", "Tramp II")

        self.comp_app_1 = self._create_comp_aparell(self.comp, app1, ordre=1, actiu=True)
        self.comp_app_2 = self._create_comp_aparell(self.comp, app2, ordre=2, actiu=True)

        self.ins = self._create_inscripcio(self.comp, "Ginmasta 1")

    def test_set_aparells_creates_and_replaces_exclusions(self):
        url = reverse("inscripcions_set_aparells", kwargs={"pk": self.comp.id})

        r1 = self.client.post(
            url,
            data=json.dumps(
                {
                    "inscripcio_id": self.ins.id,
                    "selected_comp_aparell_ids": [self.comp_app_1.id],
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(
            list(
                InscripcioAparellExclusio.objects.filter(inscripcio=self.ins)
                .values_list("comp_aparell_id", flat=True)
            ),
            [self.comp_app_2.id],
        )

        r2 = self.client.post(
            url,
            data=json.dumps(
                {
                    "inscripcio_id": self.ins.id,
                    "selected_comp_aparell_ids": [self.comp_app_1.id, self.comp_app_2.id],
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(r2.status_code, 200)
        self.assertFalse(
            InscripcioAparellExclusio.objects.filter(inscripcio=self.ins).exists()
        )

    def test_set_aparells_rejects_ids_outside_competition(self):
        other_comp = self._create_competicio("Comp Altre")
        other_app = self._create_aparell("TUMB_X", "Tumbling X")
        other_comp_app = self._create_comp_aparell(other_comp, other_app, ordre=1, actiu=True)

        url = reverse("inscripcions_set_aparells", kwargs={"pk": self.comp.id})
        r = self.client.post(
            url,
            data=json.dumps(
                {
                    "inscripcio_id": self.ins.id,
                    "selected_comp_aparell_ids": [self.comp_app_1.id, other_comp_app.id],
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 400)


