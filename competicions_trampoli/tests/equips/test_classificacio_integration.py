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


class EquipContextClassificacioTests(_BaseTrampoliDataMixin, TestCase):
    def setUp(self):
        self.comp = self._create_competicio("Comp Classif Context")
        self.app = self._create_aparell("CTX", "Aparell Context")
        self.comp_app = self._create_comp_aparell(self.comp, self.app, ordre=1, actiu=True)

        self.base_ctx = self._ensure_native_equip_context(self.comp)
        self.ctx = EquipContext.objects.create(competicio=self.comp, code="finals", nom="Finals")
        self.team_native = Equip.objects.create(competicio=self.comp, context=self.base_ctx, nom="Equip Base")
        self.team_context = Equip.objects.create(competicio=self.comp, context=self.ctx, nom="Equip Finals")

        self.ins_a = self._create_inscripcio(self.comp, "Participant A", ordre=1)
        self.ins_b = self._create_inscripcio(self.comp, "Participant B", ordre=2)
        InscripcioEquipAssignacio.objects.create(
            competicio=self.comp,
            context=self.base_ctx,
            inscripcio=self.ins_a,
            equip=self.team_native,
        )
        InscripcioEquipAssignacio.objects.create(
            competicio=self.comp,
            context=self.base_ctx,
            inscripcio=self.ins_b,
            equip=self.team_native,
        )

        InscripcioEquipAssignacio.objects.create(
            competicio=self.comp,
            context=self.ctx,
            inscripcio=self.ins_a,
            equip=self.team_context,
        )

        for ins, total in ((self.ins_a, 9.5), (self.ins_b, 8.0)):
            ScoreEntry.objects.create(
                competicio=self.comp,
                inscripcio=ins,
                exercici=1,
                comp_aparell=self.comp_app,
                inputs={},
                outputs={},
                total=total,
            )

    def test_compute_classificacio_uses_context_and_fallback_to_native(self):
        schema = {
            "puntuacio": {
                "aparells": {"mode": "seleccionar", "ids": [self.comp_app.id]},
                "camps_per_aparell": {str(self.comp_app.id): ["total"]},
                "agregacio_camps": "sum",
                "exercicis": {"mode": "tots"},
                "agregacio_exercicis": "sum",
                "agregacio_aparells": "sum",
                "ordre": "desc",
            },
            "presentacio": {"top_n": 0, "mostrar_empats": True},
            "equips": {
                "assignment_source": {"mode": "context", "context_code": "finals", "fallback": "native"},
                "incloure_sense_equip": False,
            },
        }
        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Per context",
            activa=True,
            ordre=1,
            tipus="equips",
            schema=schema,
        )

        rows = compute_classificacio(self.comp, cfg).get("global", [])
        by_name = {row["participant"]: row for row in rows}
        self.assertIn("Equip Finals", by_name)
        self.assertIn("Equip Base", by_name)
        self.assertEqual(by_name["Equip Finals"]["participants"], 1)
        self.assertEqual(by_name["Equip Base"]["participants"], 1)

    def test_compute_classificacio_keeps_legacy_native_fallback_compatibility(self):
        InscripcioEquipAssignacio.objects.filter(
            competicio=self.comp,
            context=self.base_ctx,
            inscripcio=self.ins_b,
        ).delete()
        self.ins_b.equip = self.team_native
        self.ins_b.save(update_fields=["equip"])

        schema = {
            "puntuacio": {
                "aparells": {"mode": "seleccionar", "ids": [self.comp_app.id]},
                "camps_per_aparell": {str(self.comp_app.id): ["total"]},
                "agregacio_camps": "sum",
                "exercicis": {"mode": "tots"},
                "agregacio_exercicis": "sum",
                "agregacio_aparells": "sum",
                "ordre": "desc",
            },
            "presentacio": {"top_n": 0, "mostrar_empats": True},
            "equips": {
                "assignment_source": {"mode": "context", "context_code": "finals", "fallback": "native"},
                "incloure_sense_equip": False,
            },
        }
        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Per context legacy",
            activa=True,
            ordre=1,
            tipus="equips",
            schema=schema,
        )

        rows = compute_classificacio(self.comp, cfg).get("global", [])
        by_name = {row["participant"]: row for row in rows}
        self.assertIn("Equip Finals", by_name)
        self.assertIn("Equip Base", by_name)
        self.assertEqual(by_name["Equip Base"]["participants"], 1)

    def test_normalize_schema_keeps_assignment_source_context_authoritative(self):
        normalized, info = normalize_schema_legacy_team_birth_partition(
            self.comp,
            {
                "equips": {
                    "context_code": "native",
                    "assignment_source": {
                        "mode": "context",
                        "context_code": "finals",
                        "fallback": "native",
                    },
                }
            },
            tipus="equips",
        )

        self.assertFalse(info["legacy_inferred"])
        self.assertEqual(normalized["equips"]["assignment_source"]["context_code"], "finals")
        self.assertEqual(normalized["equips"]["context_code"], "finals")


