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

    def test_classificacio_save_accepts_row_compute_by_judge_when_single_judge(self):
        schema_obj = {
            "fields": [
                {"code": "E", "type": "matrix", "shape": "judge_x_item", "judges": {"count": 1}, "items": {"count": 3}}
            ],
            "computed": [
                {
                    "code": "E_by_judge",
                    "label": "E by judge",
                    "formula": "row_custom_compute('E', '1 - x', return_mode='by_judge')",
                },
            ],
        }
        meta = _build_scoreable_meta_for_schema(schema_obj, strict_unknown=True)
        self.assertTrue(meta.get("E_by_judge", {}).get("scoreable"))

    def test_classificacio_save_rejects_row_compute_by_judge_when_multiple_judges(self):
        schema_obj = {
            "fields": [
                {"code": "E", "type": "matrix", "shape": "judge_x_item", "judges": {"count": 2}, "items": {"count": 3}}
            ],
            "computed": [
                {
                    "code": "E_by_judge",
                    "label": "E by judge",
                    "formula": "row_custom_compute('E', '1 - x', return_mode='by_judge')",
                },
            ],
        }
        meta = _build_scoreable_meta_for_schema(schema_obj, strict_unknown=True)
        self.assertFalse(meta.get("E_by_judge", {}).get("scoreable"))
        self.assertIn("by_judge", str(meta.get("E_by_judge", {}).get("reason") or ""))

    def test_classificacio_save_accepts_column_compute_by_item_when_count_is_one(self):
        schema_obj = {
            "fields": [
                {"code": "E", "type": "matrix", "shape": "judge_x_item", "judges": {"count": 2}, "items": {"count": 4}}
            ],
            "computed": [
                {
                    "code": "E_by_item",
                    "label": "E by item",
                    "formula": "column_custom_compute('E', '1 - x', return_mode='by_item', count=1)",
                },
            ],
        }
        meta = _build_scoreable_meta_for_schema(schema_obj, strict_unknown=True)
        self.assertTrue(meta.get("E_by_item", {}).get("scoreable"))

    def test_classificacio_save_rejects_column_compute_by_item_when_multiple_items(self):
        schema_obj = {
            "fields": [
                {"code": "E", "type": "matrix", "shape": "judge_x_item", "judges": {"count": 2}, "items": {"count": 4}}
            ],
            "computed": [
                {
                    "code": "E_by_item",
                    "label": "E by item",
                    "formula": "column_custom_compute('E', '1 - x', return_mode='by_item')",
                },
            ],
        }
        meta = _build_scoreable_meta_for_schema(schema_obj, strict_unknown=True)
        self.assertFalse(meta.get("E_by_item", {}).get("scoreable"))
        self.assertIn("by_item", str(meta.get("E_by_item", {}).get("reason") or ""))

    def test_classificacio_save_tie_accepts_row_compute_by_judge_when_single_judge(self):
        schema_obj = {
            "fields": [
                {"code": "E", "type": "matrix", "shape": "judge_x_item", "judges": {"count": 1}, "items": {"count": 3}}
            ],
            "computed": [
                {
                    "code": "E_by_judge",
                    "label": "E by judge",
                    "formula": "row_custom_compute('E', '1 - x', return_mode='by_judge')",
                },
            ],
        }
        strict_meta = _build_scoreable_meta_for_schema(schema_obj, strict_unknown=True)
        ui_meta = _build_scoreable_meta_for_schema(schema_obj, strict_unknown=False)
        self.assertTrue(strict_meta.get("E_by_judge", {}).get("scoreable"))
        self.assertTrue(ui_meta.get("E_by_judge", {}).get("scoreable"))

    def test_classificacio_save_rejects_invalid_tie_exercicis_selection_mode(self):
        payload = {
            "nom": "Cfg tie invalida",
            "activa": True,
            "ordre": 1,
            "tipus": "individual",
            "schema": {
                "particions": [],
                "filtres": {},
                "puntuacio": {
                    "aparells": {"mode": "seleccionar", "ids": [self.comp_app_a.id]},
                    "camps_per_aparell": {str(self.comp_app_a.id): ["total"]},
                    "agregacio_camps": "sum",
                    "exercicis": {"mode": "tots"},
                    "exercicis_best_n": 1,
                    "agregacio_exercicis": "sum",
                    "agregacio_aparells": "sum",
                    "ordre": "desc",
                },
                "desempat": [
                    {
                        "camps": ["total"],
                        "ordre": "desc",
                        "scope": {
                            "aparells": {"mode": "tots"},
                            "exercicis": {"mode": "hereta"},
                        },
                        "mode_seleccio_exercicis": "invalid_mode",
                    }
                ],
                "presentacio": {"top_n": 0, "mostrar_empats": True},
            },
        }
        url = reverse("classificacio_save", kwargs={"pk": self.comp.id})
        res = self.client.post(url, data=json.dumps(payload), content_type="application/json")
        self.assertEqual(res.status_code, 400)
        body = res.json()
        self.assertFalse(body.get("ok"))
        self.assertTrue(any("desempat[0].mode_seleccio_exercicis" in e for e in body.get("errors", [])))

    def test_classificacio_save_rejects_main_aparells_mode_tots(self):
        payload = {
            "nom": "Cfg main tots invalid",
            "activa": True,
            "ordre": 1,
            "tipus": "individual",
            "schema": {
                "particions": [],
                "filtres": {},
                "puntuacio": {
                    "aparells": {"mode": "tots", "ids": []},
                    "camps_per_aparell": {
                        str(self.comp_app_a.id): ["total"],
                        str(self.comp_app_b.id): ["total"],
                    },
                    "agregacio_camps": "sum",
                    "exercicis": {"mode": "tots"},
                    "exercicis_best_n": 1,
                    "agregacio_exercicis": "sum",
                    "agregacio_aparells": "sum",
                    "ordre": "desc",
                },
                "desempat": [],
                "presentacio": {"top_n": 0, "mostrar_empats": True},
            },
        }
        url = reverse("classificacio_save", kwargs={"pk": self.comp.id})
        res = self.client.post(url, data=json.dumps(payload), content_type="application/json")
        self.assertEqual(res.status_code, 400)
        body = res.json()
        self.assertFalse(body.get("ok"))
        self.assertTrue(any("puntuacio.aparells.mode='tots'" in e for e in body.get("errors", [])))

    def test_classificacio_save_rejects_negative_exercicis_max_per_participant(self):
        User = get_user_model()
        user = User.objects.create_user(
            username="classif_max_pp_editor",
            password="testpass123",
            email="classif-max-pp-editor@example.com",
        )
        CompeticioMembership.objects.create(
            user=user,
            competicio=self.comp,
            role=CompeticioMembership.Role.EDITOR,
            is_active=True,
        )
        self.client.force_login(user)

        payload = {
            "nom": "Cfg max per participant invalid",
            "activa": True,
            "ordre": 1,
            "tipus": "individual",
            "schema": {
                "particions": [],
                "filtres": {},
                "puntuacio": {
                    "aparells": {"mode": "seleccionar", "ids": [self.comp_app_a.id]},
                    "camps_per_aparell": {str(self.comp_app_a.id): ["total"]},
                    "agregacio_camps": "sum",
                    "exercicis": {"mode": "millor_n", "best_n": 2, "max_per_participant": -1},
                    "exercicis_best_n": 2,
                    "agregacio_exercicis": "sum",
                    "agregacio_aparells": "sum",
                    "ordre": "desc",
                },
                "desempat": [],
                "presentacio": {"top_n": 0, "mostrar_empats": True},
            },
        }
        url = reverse("classificacio_save", kwargs={"pk": self.comp.id})
        res = self.client.post(url, data=json.dumps(payload), content_type="application/json")
        self.assertEqual(res.status_code, 400)
        body = res.json()
        self.assertFalse(body.get("ok"))
        self.assertTrue(any("puntuacio.exercicis.max_per_participant" in e for e in body.get("errors", [])))

    def test_classificacio_save_rejects_tie_aparells_mode_tots(self):
        payload = {
            "nom": "Cfg tie tots invalid",
            "activa": True,
            "ordre": 1,
            "tipus": "individual",
            "schema": {
                "particions": [],
                "filtres": {},
                "puntuacio": {
                    "aparells": {"mode": "seleccionar", "ids": [self.comp_app_a.id]},
                    "camps_per_aparell": {str(self.comp_app_a.id): ["total"]},
                    "agregacio_camps": "sum",
                    "exercicis": {"mode": "tots"},
                    "exercicis_best_n": 1,
                    "agregacio_exercicis": "sum",
                    "agregacio_aparells": "sum",
                    "ordre": "desc",
                },
                "desempat": [
                    {
                        "camps": ["total"],
                        "ordre": "desc",
                        "scope": {
                            "aparells": {"mode": "tots"},
                            "exercicis": {"mode": "hereta"},
                        },
                    }
                ],
                "presentacio": {"top_n": 0, "mostrar_empats": True},
            },
        }
        url = reverse("classificacio_save", kwargs={"pk": self.comp.id})
        res = self.client.post(url, data=json.dumps(payload), content_type="application/json")
        self.assertEqual(res.status_code, 400)
        body = res.json()
        self.assertFalse(body.get("ok"))
        self.assertTrue(any("desempat[0].scope.aparells.mode='tots'" in e for e in body.get("errors", [])))

    def test_compute_classificacio_tie_supports_per_app_override_exercicis(self):
        self.comp_app_a.nombre_exercicis = 2
        self.comp_app_a.save(update_fields=["nombre_exercicis"])
        self.comp_app_b.nombre_exercicis = 2
        self.comp_app_b.save(update_fields=["nombre_exercicis"])

        # Participant A
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
            inscripcio=self.ins_a,
            exercici=2,
            comp_aparell=self.comp_app_a,
            inputs={},
            outputs={},
            total=1.0,
        )
        ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins_a,
            exercici=1,
            comp_aparell=self.comp_app_b,
            inputs={},
            outputs={},
            total=5.0,
        )
        ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins_a,
            exercici=2,
            comp_aparell=self.comp_app_b,
            inputs={},
            outputs={},
            total=5.0,
        )

        # Participant B
        ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins_b,
            exercici=1,
            comp_aparell=self.comp_app_a,
            inputs={},
            outputs={},
            total=6.0,
        )
        ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins_b,
            exercici=2,
            comp_aparell=self.comp_app_a,
            inputs={},
            outputs={},
            total=4.0,
        )
        ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins_b,
            exercici=1,
            comp_aparell=self.comp_app_b,
            inputs={},
            outputs={},
            total=8.0,
        )
        ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins_b,
            exercici=2,
            comp_aparell=self.comp_app_b,
            inputs={},
            outputs={},
            total=2.0,
        )

        schema = self._base_cfg_schema()
        schema["puntuacio"]["aparells"] = {"mode": "tots", "ids": []}
        schema["puntuacio"]["camps_per_aparell"] = {
            str(self.comp_app_a.id): ["total"],
            str(self.comp_app_b.id): ["total"],
        }
        schema["puntuacio"]["exercicis"] = {"mode": "tots"}
        schema["puntuacio"]["agregacio_camps"] = "sum"
        schema["puntuacio"]["agregacio_exercicis"] = "sum"
        schema["puntuacio"]["agregacio_aparells"] = "sum"
        schema["desempat"] = [
            {
                "camps": ["total"],
                "ordre": "desc",
                "scope": {
                    "aparells": {"mode": "tots"},
                    "exercicis": {"mode": "hereta"},
                },
                "agregacio_camps": "sum",
                "agregacio_exercicis": "sum",
                "agregacio_aparells": "sum",
                "mode_seleccio_exercicis": "per_aparell_override",
                "exercicis_per_aparell": {
                    str(self.comp_app_a.id): {"mode": "millor_1"},
                    str(self.comp_app_b.id): {"mode": "pitjor_1"},
                },
            }
        ]

        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Tie per app override",
            activa=True,
            ordre=1,
            tipus="individual",
            schema=schema,
        )

        out = compute_classificacio(self.comp, cfg)
        rows = out.get("global", [])
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["participant"], "Participant A")
        self.assertEqual(rows[1]["participant"], "Participant B")

    def test_compute_classificacio_main_exercicis_respects_max_per_participant(self):
        self.comp_app_a.nombre_exercicis = 2
        self.comp_app_a.save(update_fields=["nombre_exercicis"])

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
            inscripcio=self.ins_a,
            exercici=2,
            comp_aparell=self.comp_app_a,
            inputs={},
            outputs={},
            total=8.0,
        )
        ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins_b,
            exercici=1,
            comp_aparell=self.comp_app_a,
            inputs={},
            outputs={},
            total=6.0,
        )
        ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins_b,
            exercici=2,
            comp_aparell=self.comp_app_a,
            inputs={},
            outputs={},
            total=5.0,
        )

        schema = self._base_cfg_schema()
        schema["puntuacio"]["aparells"] = {"mode": "seleccionar", "ids": [self.comp_app_a.id]}
        schema["puntuacio"]["camps_per_aparell"] = {str(self.comp_app_a.id): ["total"]}
        schema["puntuacio"]["exercicis"] = {
            "mode": "millor_n",
            "best_n": 2,
            "max_per_participant": 1,
        }
        schema["puntuacio"]["agregacio_camps"] = "sum"
        schema["puntuacio"]["agregacio_exercicis"] = "sum"
        schema["puntuacio"]["agregacio_aparells"] = "sum"

        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Main max per participant",
            activa=True,
            ordre=1,
            tipus="individual",
            schema=schema,
        )

        out = compute_classificacio(self.comp, cfg)
        rows = out.get("global", [])
        self.assertEqual(len(rows), 2)
        points_by_name = {r["participant"]: r["punts"] for r in rows}
        self.assertEqual(points_by_name.get("Participant A"), 9.0)
        self.assertEqual(points_by_name.get("Participant B"), 6.0)

    def test_compute_classificacio_tie_exercicis_respects_max_per_participant(self):
        self.comp_app_a.nombre_exercicis = 2
        self.comp_app_a.save(update_fields=["nombre_exercicis"])

        ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins_a,
            exercici=1,
            comp_aparell=self.comp_app_a,
            inputs={},
            outputs={},
            total=6.0,
        )
        ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins_a,
            exercici=2,
            comp_aparell=self.comp_app_a,
            inputs={},
            outputs={},
            total=4.0,
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
        ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins_b,
            exercici=2,
            comp_aparell=self.comp_app_a,
            inputs={},
            outputs={},
            total=3.0,
        )

        schema = self._base_cfg_schema()
        schema["puntuacio"]["aparells"] = {"mode": "seleccionar", "ids": [self.comp_app_a.id]}
        schema["puntuacio"]["camps_per_aparell"] = {str(self.comp_app_a.id): ["total"]}
        schema["puntuacio"]["exercicis"] = {"mode": "tots"}
        schema["puntuacio"]["agregacio_camps"] = "sum"
        schema["puntuacio"]["agregacio_exercicis"] = "sum"
        schema["puntuacio"]["agregacio_aparells"] = "sum"
        schema["desempat"] = [
            {
                "camps": ["total"],
                "ordre": "desc",
                "scope": {
                    "aparells": {"mode": "seleccionar", "ids": [self.comp_app_a.id]},
                    "exercicis": {"mode": "millor_n", "best_n": 2, "max_per_participant": 1},
                },
                "agregacio_camps": "sum",
                "agregacio_exercicis": "sum",
                "agregacio_aparells": "sum",
            }
        ]

        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Tie max per participant",
            activa=True,
            ordre=1,
            tipus="individual",
            schema=schema,
        )

