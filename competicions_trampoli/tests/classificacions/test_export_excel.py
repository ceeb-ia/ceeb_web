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
from ...services.classificacions.builder import (
    prepare_schema_for_builder_hydration,
    scoreable_codes_by_app_id as _scoreable_codes_by_app_id,
)
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


class ClassificacionsExportExcelTests(_BaseTrampoliDataMixin, TestCase):
    def setUp(self):
        self.comp = self._create_competicio("Comp Export Classificacions")
        self.app = self._create_aparell("TRAMP_EXPORT", "Tramp Export")
        self.comp_app = self._create_comp_aparell(self.comp, self.app, ordre=1, actiu=True)

        self.ins_a = self._create_inscripcio(self.comp, "Participant A", ordre=1)
        self.ins_b = self._create_inscripcio(self.comp, "Participant B", ordre=2)
        self.ins_c = self._create_inscripcio(self.comp, "Participant C", ordre=3)

        self.ins_a.categoria = "Junior"
        self.ins_a.subcategoria = "Femeni"
        self.ins_a.save(update_fields=["categoria", "subcategoria"])

        self.ins_b.categoria = "Junior"
        self.ins_b.subcategoria = "Femeni"
        self.ins_b.save(update_fields=["categoria", "subcategoria"])

        self.ins_c.categoria = "Senior"
        self.ins_c.subcategoria = "Masculi"
        self.ins_c.save(update_fields=["categoria", "subcategoria"])

        ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins_a,
            exercici=1,
            comp_aparell=self.comp_app,
            inputs={},
            outputs={},
            total=9.6,
        )
        ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins_b,
            exercici=1,
            comp_aparell=self.comp_app,
            inputs={},
            outputs={},
            total=8.3,
        )
        ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins_c,
            exercici=1,
            comp_aparell=self.comp_app,
            inputs={},
            outputs={},
            total=7.1,
        )

        self.cfg_general = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="General",
            activa=True,
            ordre=1,
            tipus="individual",
            schema=self._schema_for_parts([]),
        )
        self.cfg_particions = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Per categories",
            activa=True,
            ordre=2,
            tipus="individual",
            schema=self._schema_for_parts(["categoria", "subcategoria"]),
        )

        User = get_user_model()
        self.user = User.objects.create_user(
            username="classif_export_user",
            password="testpass123",
            email="classif-export@example.com",
        )
        CompeticioMembership.objects.create(
            user=self.user,
            competicio=self.comp,
            role=CompeticioMembership.Role.READONLY,
            is_active=True,
        )

    def _schema_for_parts(self, parts):
        return {
            "particions": parts,
            "filtres": {},
            "puntuacio": {
                "aparells": {"mode": "seleccionar", "ids": [self.comp_app.id]},
                "camps_per_aparell": {str(self.comp_app.id): ["total"]},
                "agregacio_camps": "sum",
                "exercicis": {"mode": "tots"},
                "exercicis_best_n": 1,
                "agregacio_exercicis": "sum",
                "agregacio_aparells": "sum",
                "ordre": "desc",
                "camp": "total",
                "agregacio": "sum",
                "best_n": 1,
            },
            "desempat": [],
            "presentacio": {
                "top_n": 0,
                "mostrar_empats": True,
                "columnes": [
                    {"type": "builtin", "key": "posicio", "label": "Pos.", "align": "left"},
                    {"type": "builtin", "key": "participant", "label": "Nom", "align": "left"},
                    {"type": "builtin", "key": "punts", "label": "Punts", "align": "right", "decimals": 3},
                ],
            },
        }

    def test_export_excel_creates_one_sheet_per_classificacio(self):
        self.client.force_login(self.user)
        url = reverse("classificacions_live_export_excel", kwargs={"pk": self.comp.id})
        res = self.client.get(url)

        self.assertEqual(res.status_code, 200)
        self.assertIn(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            res["Content-Type"],
        )

        wb = load_workbook(filename=BytesIO(res.content))
        self.assertEqual(len(wb.sheetnames), 2)

        ws_general = wb[wb.sheetnames[0]]
        ws_parts = wb[wb.sheetnames[1]]

        self.assertIn("General", str(ws_general["A1"].value))
        self.assertIn("Particio:", str(ws_general["A4"].value))
        self.assertEqual(ws_general.freeze_panes, "A6")

        gold_fill = (ws_general["A6"].fill.fgColor.rgb or "").upper()
        silver_fill = (ws_general["A7"].fill.fgColor.rgb or "").upper()
        header_fill = (ws_general["A5"].fill.fgColor.rgb or "").upper()
        self.assertTrue(gold_fill.endswith("F6E27A"))
        self.assertTrue(silver_fill.endswith("E3E8EF"))
        self.assertTrue(header_fill.endswith("E9EEF7"))

        self.assertIn("Particio:", str(ws_parts["A4"].value))
        self.assertIn("/", str(ws_parts["A4"].value))

    def test_export_excel_can_filter_single_cfg_with_cfg_id(self):
        self.client.force_login(self.user)
        url = reverse("classificacions_live_export_excel", kwargs={"pk": self.comp.id})
        res = self.client.get(url, {"cfg_id": self.cfg_particions.id})

        self.assertEqual(res.status_code, 200)
        wb = load_workbook(filename=BytesIO(res.content))
        self.assertEqual(len(wb.sheetnames), 1)
        ws = wb[wb.sheetnames[0]]
        self.assertIn("Per categories", str(ws["A1"].value))

    def test_export_excel_rejects_invalid_cfg_id(self):
        self.client.force_login(self.user)
        url = reverse("classificacions_live_export_excel", kwargs={"pk": self.comp.id})
        res = self.client.get(url, {"cfg_id": "abc"})
        self.assertEqual(res.status_code, 400)

    def test_export_excel_returns_consistent_error_when_compute_fails(self):
        self.client.force_login(self.user)
        url = reverse("classificacions_live_export_excel", kwargs={"pk": self.comp.id})
        with patch("competicions_trampoli.views.classificacions.export.compute_classificacio", side_effect=RuntimeError("boom export")):
            res = self.client.get(url, {"cfg_id": self.cfg_general.id})

        self.assertEqual(res.status_code, 400)
        body = res.content.decode("utf-8")
        self.assertIn("No s'ha pogut renderitzar la classificacio.", body)
        self.assertIn("boom export", body)

