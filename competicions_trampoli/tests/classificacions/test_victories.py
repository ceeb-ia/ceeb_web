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


class ClassificacioMatrixScalarTests(_BaseTrampoliDataMixin, TestCase):
    def setUp(self):
        self.comp = self._create_competicio("Comp Classificacio")
        self.user = self._login_competicio_user(
            self.comp,
            role=CompeticioMembership.Role.EDITOR,
            username_prefix="classif_editor",
        )
        self.app_a = self._create_aparell("APP_A", "Aparell A")
        self.app_b = self._create_aparell("APP_B", "Aparell B")
        self.comp_app_a = self._create_comp_aparell(self.comp, self.app_a, ordre=1, actiu=True)
        self.comp_app_b = self._create_comp_aparell(self.comp, self.app_b, ordre=2, actiu=True)

        self.ins_a = self._create_inscripcio(self.comp, "Participant A", ordre=1)
        self.ins_b = self._create_inscripcio(self.comp, "Participant B", ordre=2)

    def _base_cfg_schema(self):
        return {
            "particions": [],
            "filtres": {},
            "puntuacio": {
                "aparells": {"mode": "tots", "ids": []},
                "camps_per_aparell": {
                    str(self.comp_app_a.id): ["X"],
                    str(self.comp_app_b.id): ["Y"],
                },
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
            "presentacio": {"top_n": 0, "mostrar_empats": True},
        }

    def _valid_partition_schema(self):
        schema = self._base_cfg_schema()
        schema["puntuacio"]["aparells"] = {"mode": "seleccionar", "ids": [self.comp_app_a.id]}
        schema["puntuacio"]["camps_per_aparell"] = {str(self.comp_app_a.id): ["total"]}
        return schema

    def _selected_total_schema(self, app_ids=None, mode_resultat="score"):
        selected = list(app_ids or [self.comp_app_a.id, self.comp_app_b.id])
        schema = self._base_cfg_schema()
        schema["puntuacio"]["aparells"] = {"mode": "seleccionar", "ids": selected}
        schema["puntuacio"]["camps_per_aparell"] = {str(app_id): ["total"] for app_id in selected}
        schema["puntuacio"]["mode_resultat_aparells"] = mode_resultat
        schema["puntuacio"]["victories"] = {
            "punts_victoria": 1,
            "punts_empat": 0.5,
            "sense_nota_mode": "skip",
            "mode_camps": "agregat",
            "mode_exercicis": "agregat",
            "mode_seleccio_exercicis_camps_separats": "per_camp",
            "agregacio_victories_camps": "sum",
            "agregacio_victories_exercicis": "sum",
            "desempat_comparacio": [],
        }
        return schema

    def test_compute_classificacio_victories_single_app_matches_order(self):
        schema = self._selected_total_schema([self.comp_app_a.id], mode_resultat="victories")

        ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins_a,
            exercici=1,
            comp_aparell=self.comp_app_a,
            inputs={},
            outputs={},
            total=9.0,
        )
        ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins_b,
            exercici=1,
            comp_aparell=self.comp_app_a,
            inputs={},
            outputs={},
            total=7.0,
        )

        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Victories 1 app",
            activa=True,
            ordre=1,
            tipus="individual",
            schema=schema,
        )

        rows = compute_classificacio(self.comp, cfg).get("global", [])
        self.assertEqual([r["participant"] for r in rows], ["Participant A", "Participant B"])
        self.assertEqual(rows[0]["by_app_base"][self.comp_app_a.id], 9.0)
        self.assertEqual(rows[0]["by_app"][self.comp_app_a.id], 1.0)
        self.assertEqual(rows[0]["punts"], 1.0)
        self.assertEqual(rows[1]["by_app"][self.comp_app_a.id], 0.0)
        self.assertEqual(rows[1]["punts"], 0.0)

    def test_compute_classificacio_victories_multiple_apps_aggregates_after_duels(self):
        ins_c = self._create_inscripcio(self.comp, "Participant C", ordre=3)
        schema = self._selected_total_schema(
            [self.comp_app_a.id, self.comp_app_b.id],
            mode_resultat="victories",
        )

        scores = {
            self.ins_a.id: {self.comp_app_a.id: 100.0, self.comp_app_b.id: 1.0},
            self.ins_b.id: {self.comp_app_a.id: 60.0, self.comp_app_b.id: 60.0},
            ins_c.id: {self.comp_app_a.id: 59.0, self.comp_app_b.id: 59.0},
        }
        for ins_id, per_app in scores.items():
            ins = Inscripcio.objects.get(pk=ins_id)
            for app_id, total in per_app.items():
                comp_app = self.comp_app_a if app_id == self.comp_app_a.id else self.comp_app_b
                ScoreEntry.objects.create(
                    competicio=self.comp,
                    inscripcio=ins,
                    exercici=1,
                    comp_aparell=comp_app,
                    inputs={},
                    outputs={},
                    total=total,
                )

        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Victories 2 apps",
            activa=True,
            ordre=1,
            tipus="individual",
            schema=schema,
        )

        rows = compute_classificacio(self.comp, cfg).get("global", [])
        self.assertEqual([r["participant"] for r in rows], ["Participant B", "Participant A", "Participant C"])
        self.assertEqual(rows[0]["punts"], 3.0)
        self.assertEqual(rows[1]["punts"], 2.0)
        self.assertEqual(rows[2]["punts"], 1.0)

    def test_compute_classificacio_victories_internal_tie_break_uses_compare_tie(self):
        schema = self._selected_total_schema([self.comp_app_a.id], mode_resultat="victories")
        schema["puntuacio"]["victories"]["desempat_comparacio"] = [
            {
                "camp": "E",
                "camps": ["E"],
                "agregacio_camps": "hereta",
                "ordre": "desc",
                "scope": {"exercicis": {"mode": "hereta"}},
            }
        ]

        ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins_a,
            exercici=1,
            comp_aparell=self.comp_app_a,
            inputs={"E": 9.0},
            outputs={},
            total=10.0,
        )
        ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins_b,
            exercici=1,
            comp_aparell=self.comp_app_a,
            inputs={"E": 8.0},
            outputs={},
            total=10.0,
        )

        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Victories compare tie",
            activa=True,
            ordre=1,
            tipus="individual",
            schema=schema,
        )

        rows = compute_classificacio(self.comp, cfg).get("global", [])
        self.assertEqual([r["participant"] for r in rows], ["Participant A", "Participant B"])
        self.assertEqual(rows[0]["punts"], 1.0)
        self.assertEqual(rows[1]["punts"], 0.0)

    def test_compute_classificacio_victories_unresolved_tie_gives_half_points(self):
        schema = self._selected_total_schema([self.comp_app_a.id], mode_resultat="victories")

        ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins_a,
            exercici=1,
            comp_aparell=self.comp_app_a,
            inputs={},
            outputs={},
            total=10.0,
        )
        ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins_b,
            exercici=1,
            comp_aparell=self.comp_app_a,
            inputs={},
            outputs={},
            total=10.0,
        )

        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Victories tied",
            activa=True,
            ordre=1,
            tipus="individual",
            schema=schema,
        )

        rows = compute_classificacio(self.comp, cfg).get("global", [])
        self.assertEqual(rows[0]["punts"], 0.5)
        self.assertEqual(rows[1]["punts"], 0.5)
        self.assertEqual(rows[0]["by_app"][self.comp_app_a.id], 0.5)
        self.assertEqual(rows[1]["by_app"][self.comp_app_a.id], 0.5)

    def test_compute_classificacio_victories_separated_fields_aggregate_per_app(self):
        schema = self._selected_total_schema([self.comp_app_a.id], mode_resultat="victories")
        schema["puntuacio"]["camps_per_aparell"] = {str(self.comp_app_a.id): ["E", "D"]}
        schema["puntuacio"]["victories"]["mode_camps"] = "separat"
        schema["puntuacio"]["victories"]["agregacio_victories_camps"] = "sum"

        for exercici, e_val, d_val in ((1, 10.0, 1.0), (2, 10.0, 1.0)):
            ScoreEntry.objects.create(
                competicio=self.comp,
                inscripcio=self.ins_a,
                exercici=exercici,
                comp_aparell=self.comp_app_a,
                inputs={"E": e_val, "D": d_val},
                outputs={},
                total=e_val + d_val,
            )
            ScoreEntry.objects.create(
                competicio=self.comp,
                inscripcio=self.ins_b,
                exercici=exercici,
                comp_aparell=self.comp_app_a,
                inputs={"E": 8.0, "D": 8.0},
                outputs={},
                total=16.0,
            )

        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Victories fields separated",
            activa=True,
            ordre=1,
            tipus="individual",
            schema=schema,
        )

        rows = compute_classificacio(self.comp, cfg).get("global", [])
        by_name = {row["participant"]: row["by_app"][self.comp_app_a.id] for row in rows}
        self.assertEqual(by_name.get("Participant A"), 1.0)
        self.assertEqual(by_name.get("Participant B"), 1.0)

    def test_compute_classificacio_victories_separated_exercises_aggregate_per_app(self):
        self.comp_app_a.nombre_exercicis = 2
        self.comp_app_a.save(update_fields=["nombre_exercicis"])
        schema = self._selected_total_schema([self.comp_app_a.id], mode_resultat="victories")
        schema["puntuacio"]["victories"]["mode_exercicis"] = "separat"
        schema["puntuacio"]["victories"]["agregacio_victories_exercicis"] = "sum"

        for exercici, total_a, total_b in ((1, 10.0, 9.0), (2, 1.0, 2.0)):
            ScoreEntry.objects.create(
                competicio=self.comp,
                inscripcio=self.ins_a,
                exercici=exercici,
                comp_aparell=self.comp_app_a,
                inputs={},
                outputs={},
                total=total_a,
            )
            ScoreEntry.objects.create(
                competicio=self.comp,
                inscripcio=self.ins_b,
                exercici=exercici,
                comp_aparell=self.comp_app_a,
                inputs={},
                outputs={},
                total=total_b,
            )

        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Victories exercises separated",
            activa=True,
            ordre=1,
            tipus="individual",
            schema=schema,
        )

        rows = compute_classificacio(self.comp, cfg).get("global", [])
        by_name = {row["participant"]: row["by_app"][self.comp_app_a.id] for row in rows}
        self.assertEqual(by_name.get("Participant A"), 1.0)
        self.assertEqual(by_name.get("Participant B"), 1.0)

    def test_compute_classificacio_victories_separated_fields_and_exercises_use_intermediate_aggregation(self):
        self.comp_app_a.nombre_exercicis = 2
        self.comp_app_a.save(update_fields=["nombre_exercicis"])
        schema = self._selected_total_schema([self.comp_app_a.id], mode_resultat="victories")
        schema["puntuacio"]["camps_per_aparell"] = {str(self.comp_app_a.id): ["E", "D"]}
        schema["puntuacio"]["victories"]["mode_camps"] = "separat"
        schema["puntuacio"]["victories"]["mode_exercicis"] = "separat"
        schema["puntuacio"]["victories"]["agregacio_victories_camps"] = "avg"
        schema["puntuacio"]["victories"]["agregacio_victories_exercicis"] = "sum"

        per_ex = {
            1: {"a": {"E": 10.0, "D": 1.0}, "b": {"E": 9.0, "D": 9.0}},
            2: {"a": {"E": 8.0, "D": 1.0}, "b": {"E": 7.0, "D": 9.0}},
        }
        for exercici, vals in per_ex.items():
            ScoreEntry.objects.create(
                competicio=self.comp,
                inscripcio=self.ins_a,
                exercici=exercici,
                comp_aparell=self.comp_app_a,
                inputs=vals["a"],
                outputs={},
                total=sum(vals["a"].values()),
            )
            ScoreEntry.objects.create(
                competicio=self.comp,
                inscripcio=self.ins_b,
                exercici=exercici,
                comp_aparell=self.comp_app_a,
                inputs=vals["b"],
                outputs={},
                total=sum(vals["b"].values()),
            )

        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Victories separated all levels",
            activa=True,
            ordre=1,
            tipus="individual",
            schema=schema,
        )

        rows = compute_classificacio(self.comp, cfg).get("global", [])
        by_name = {row["participant"]: row["by_app"][self.comp_app_a.id] for row in rows}
        self.assertEqual(by_name.get("Participant A"), 1.0)
        self.assertEqual(by_name.get("Participant B"), 1.0)

    def test_compute_classificacio_victories_separated_fields_supports_global_or_per_field_exercise_selection(self):
        self.comp_app_a.nombre_exercicis = 2
        self.comp_app_a.save(update_fields=["nombre_exercicis"])
        schema = self._selected_total_schema([self.comp_app_a.id], mode_resultat="victories")
        schema["puntuacio"]["camps_per_aparell"] = {str(self.comp_app_a.id): ["E", "D"]}
        schema["puntuacio"]["exercicis"] = {"mode": "millor_1"}
        schema["puntuacio"]["victories"]["mode_camps"] = "separat"
        schema["puntuacio"]["victories"]["agregacio_victories_camps"] = "sum"

        for exercici, vals_a, vals_b in (
            (1, {"E": 10.0, "D": 1.0}, {"E": 9.0, "D": 9.0}),
            (2, {"E": 1.0, "D": 10.0}, {"E": 8.0, "D": 8.0}),
        ):
            ScoreEntry.objects.create(
                competicio=self.comp,
                inscripcio=self.ins_a,
                exercici=exercici,
                comp_aparell=self.comp_app_a,
                inputs=vals_a,
                outputs={},
                total=sum(vals_a.values()),
            )
            ScoreEntry.objects.create(
                competicio=self.comp,
                inscripcio=self.ins_b,
                exercici=exercici,
                comp_aparell=self.comp_app_a,
                inputs=vals_b,
                outputs={},
                total=sum(vals_b.values()),
            )

        schema_global = json.loads(json.dumps(schema))
        schema_global["puntuacio"]["victories"]["mode_seleccio_exercicis_camps_separats"] = "global"
        cfg_global = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Victories fields global select",
            activa=True,
            ordre=1,
            tipus="individual",
            schema=schema_global,
        )
        global_rows = compute_classificacio(self.comp, cfg_global).get("global", [])
        global_points = {row["participant"]: row["by_app"][self.comp_app_a.id] for row in global_rows}

        schema_per_field = json.loads(json.dumps(schema))
        schema_per_field["puntuacio"]["victories"]["mode_seleccio_exercicis_camps_separats"] = "per_camp"
        cfg_per_field = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Victories fields per field select",
            activa=True,
            ordre=2,
            tipus="individual",
            schema=schema_per_field,
        )
        per_field_rows = compute_classificacio(self.comp, cfg_per_field).get("global", [])
        per_field_points = {row["participant"]: row["by_app"][self.comp_app_a.id] for row in per_field_rows}

        self.assertEqual(global_points.get("Participant A"), 1.0)
        self.assertEqual(global_points.get("Participant B"), 1.0)
        self.assertEqual(per_field_points.get("Participant A"), 2.0)
        self.assertEqual(per_field_points.get("Participant B"), 0.0)

    def test_compute_classificacio_victories_internal_tie_break_respects_separated_exercise_unit(self):
        self.comp_app_a.nombre_exercicis = 2
        self.comp_app_a.save(update_fields=["nombre_exercicis"])
        schema = self._selected_total_schema([self.comp_app_a.id], mode_resultat="victories")
        schema["puntuacio"]["victories"]["mode_exercicis"] = "separat"
        schema["puntuacio"]["victories"]["desempat_comparacio"] = [
            {
                "camp": "E",
                "camps": ["E"],
                "agregacio_camps": "hereta",
                "ordre": "desc",
                "scope": {"exercicis": {"mode": "hereta"}},
            }
        ]

        for exercici, e_a, e_b in ((1, 9.0, 8.0), (2, 1.0, 9.0)):
            ScoreEntry.objects.create(
                competicio=self.comp,
                inscripcio=self.ins_a,
                exercici=exercici,
                comp_aparell=self.comp_app_a,
                inputs={"E": e_a},
                outputs={},
                total=10.0,
            )
            ScoreEntry.objects.create(
                competicio=self.comp,
                inscripcio=self.ins_b,
                exercici=exercici,
                comp_aparell=self.comp_app_a,
                inputs={"E": e_b},
                outputs={},
                total=10.0,
            )

        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Victories tie per exercise",
            activa=True,
            ordre=1,
            tipus="individual",
            schema=schema,
        )

        rows = compute_classificacio(self.comp, cfg).get("global", [])
        by_name = {row["participant"]: row["by_app"][self.comp_app_a.id] for row in rows}
        self.assertEqual(by_name.get("Participant A"), 1.0)
        self.assertEqual(by_name.get("Participant B"), 1.0)

    def test_classificacio_save_rejects_invalid_victories_granular_modes(self):
        schema = self._selected_total_schema([self.comp_app_a.id], mode_resultat="victories")
        schema["puntuacio"]["victories"]["mode_camps"] = "invalid"
        schema["puntuacio"]["victories"]["mode_exercicis"] = "broken"
        schema["puntuacio"]["victories"]["mode_seleccio_exercicis_camps_separats"] = "oops"
        _, errors = _validate_schema_for_competicio(self.comp, schema, tipus="individual")
        self.assertTrue(any("mode_camps invalid" in e for e in errors))
        self.assertTrue(any("mode_exercicis invalid" in e for e in errors))
        self.assertTrue(any("mode_seleccio_exercicis_camps_separats invalid" in e for e in errors))

    def test_classificacio_save_ignores_invalid_victories_granular_modes_in_score_mode(self):
        schema = self._selected_total_schema([self.comp_app_a.id], mode_resultat="score")
        schema["puntuacio"]["victories"]["mode_camps"] = "invalid"
        schema["puntuacio"]["victories"]["mode_exercicis"] = "broken"
        schema["puntuacio"]["victories"]["mode_seleccio_exercicis_camps_separats"] = "oops"
        _, errors = _validate_schema_for_competicio(self.comp, schema, tipus="individual")
        self.assertFalse(any("mode_camps invalid" in e for e in errors))
        self.assertFalse(any("mode_exercicis invalid" in e for e in errors))
        self.assertFalse(any("mode_seleccio_exercicis_camps_separats invalid" in e for e in errors))

    def test_classificacio_save_rejects_victories_for_non_individual(self):
        schema = self._selected_total_schema([self.comp_app_a.id], mode_resultat="victories")
        _, errors = _validate_schema_for_competicio(self.comp, schema, tipus="entitat")
        self.assertTrue(any("mode_resultat_aparells='victories'" in e for e in errors))

    def test_classificacio_save_rejects_victories_compare_tie_scope_aparells(self):
        schema = self._selected_total_schema([self.comp_app_a.id], mode_resultat="victories")
        schema["puntuacio"]["victories"]["desempat_comparacio"] = [
            {
                "camps": ["total"],
                "ordre": "desc",
                "scope": {
                    "aparells": {"mode": "seleccionar", "ids": [self.comp_app_a.id]},
                    "exercicis": {"mode": "hereta"},
                },
            }
        ]
        _, errors = _validate_schema_for_competicio(self.comp, schema, tipus="individual")
        self.assertTrue(any("scope.aparells no esta permes" in e for e in errors))

    def test_classificacio_save_rejects_victories_compare_tie_scope_participants(self):
        schema = self._selected_total_schema([self.comp_app_a.id], mode_resultat="victories")
        schema["puntuacio"]["victories"]["desempat_comparacio"] = [
            {
                "camps": ["total"],
                "ordre": "desc",
                "scope": {
                    "participants": {"mode": "tots"},
                    "exercicis": {"mode": "hereta"},
                },
            }
        ]
        _, errors = _validate_schema_for_competicio(self.comp, schema, tipus="individual")
        self.assertTrue(any("scope.participants no esta permes" in e for e in errors))
