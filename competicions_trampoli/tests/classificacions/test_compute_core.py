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

    def test_compute_classificacio_uses_input_matrix_1x1_as_scalar(self):
        ScoringSchema.objects.create(
            aparell=self.app_a,
            schema={
                "fields": [
                    {"code": "X", "type": "matrix", "shape": "judge_x_item", "judges": {"count": 1}, "items": {"count": 1}}
                ],
                "computed": [],
            },
        )
        ScoringSchema.objects.create(
            aparell=self.app_b,
            schema={
                "fields": [
                    {"code": "Y", "type": "matrix", "shape": "judge_x_item", "judges": {"count": 1}, "items": {"count": 1}}
                ],
                "computed": [],
            },
        )

        ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins_a,
            exercici=1,
            comp_aparell=self.comp_app_a,
            inputs={"X": [[7.5]]},
            outputs={},
            total=0,
        )
        ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins_b,
            exercici=1,
            comp_aparell=self.comp_app_b,
            inputs={"Y": [[8.2]]},
            outputs={},
            total=0,
        )

        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Global A/B",
            activa=True,
            ordre=1,
            tipus="individual",
            schema=self._base_cfg_schema(),
        )
        out = compute_classificacio(self.comp, cfg)
        rows = out.get("global", [])
        points_by_name = {r["participant"]: r["punts"] for r in rows}

        self.assertEqual(points_by_name.get("Participant A"), 7.5)
        self.assertEqual(points_by_name.get("Participant B"), 8.2)

    def test_compute_classificacio_keeps_zero_for_non_1x1_matrix(self):
        ScoringSchema.objects.create(
            aparell=self.app_a,
            schema={
                "fields": [
                    {"code": "X", "type": "matrix", "shape": "judge_x_item", "judges": {"count": 1}, "items": {"count": 2}}
                ],
                "computed": [],
            },
        )
        ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins_a,
            exercici=1,
            comp_aparell=self.comp_app_a,
            inputs={"X": [[7.0, 8.0]]},
            outputs={},
            total=0,
        )

        schema = self._base_cfg_schema()
        schema["puntuacio"]["aparells"] = {"mode": "seleccionar", "ids": [self.comp_app_a.id]}
        schema["puntuacio"]["camps_per_aparell"] = {str(self.comp_app_a.id): ["X"]}
        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="No 1x1",
            activa=True,
            ordre=1,
            tipus="individual",
            schema=schema,
        )
        out = compute_classificacio(self.comp, cfg)
        rows = out.get("global", [])
        points_by_name = {r["participant"]: r["punts"] for r in rows}
        self.assertEqual(points_by_name.get("Participant A"), 0.0)
        self.assertEqual(points_by_name.get("Participant B"), 0.0)

    def test_compute_classificacio_individual_candidate_source_modes_preserve_expected_scores(self):
        self.comp_app_a.nombre_exercicis = 3
        self.comp_app_a.save(update_fields=["nombre_exercicis"])

        for inscripcio, exercici, total in (
            (self.ins_a, 1, 1.0),
            (self.ins_a, 2, 10.0),
            (self.ins_a, 3, 2.0),
            (self.ins_b, 1, 4.0),
            (self.ins_b, 2, 9.0),
            (self.ins_b, 3, 1.0),
        ):
            ScoreEntry.objects.create(
                competicio=self.comp,
                inscripcio=inscripcio,
                exercici=exercici,
                comp_aparell=self.comp_app_a,
                inputs={},
                outputs={},
                total=total,
            )

        raw_schema = self._selected_total_schema([self.comp_app_a.id])
        raw_schema["puntuacio"].update(
            {
                "candidate_source_mode": "raw_exercise",
                "candidate_source_cfg": {
                    "mode": "tots",
                    "best_n": 1,
                    "index": 1,
                    "ids": [],
                    "agregacio_exercicis": "sum",
                },
                "exercicis": {"mode": "tots"},
                "agregacio_exercicis": "sum",
            }
        )
        raw_cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Individual raw source",
            activa=True,
            ordre=1,
            tipus="individual",
            schema=raw_schema,
        )

        aggregate_schema = self._selected_total_schema([self.comp_app_a.id])
        aggregate_schema["puntuacio"].update(
            {
                "candidate_source_mode": "participant_aggregate",
                "candidate_source_cfg": {
                    "mode": "millor_n",
                    "best_n": 1,
                    "index": 1,
                    "ids": [],
                    "agregacio_exercicis": "sum",
                },
                "exercicis": {"mode": "millor_n", "best_n": 1},
                "agregacio_exercicis": "sum",
            }
        )
        aggregate_cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Individual aggregate source",
            activa=True,
            ordre=1,
            tipus="individual",
            schema=aggregate_schema,
        )

        raw_rows = compute_classificacio(self.comp, raw_cfg).get("global", [])
        aggregate_rows = compute_classificacio(self.comp, aggregate_cfg).get("global", [])
        raw_scores = {row["participant"]: row["score"] for row in raw_rows}
        aggregate_scores = {row["participant"]: row["score"] for row in aggregate_rows}

        self.assertEqual(raw_scores.get("Participant A"), 13.0)
        self.assertEqual(raw_scores.get("Participant B"), 14.0)
        self.assertEqual(aggregate_scores.get("Participant A"), 10.0)
        self.assertEqual(aggregate_scores.get("Participant B"), 9.0)

    def test_classificacio_save_rejects_non_1x1_matrix_field(self):
        ScoringSchema.objects.create(
            aparell=self.app_a,
            schema={
                "fields": [
                    {"code": "X", "type": "matrix", "shape": "judge_x_item", "judges": {"count": 2}, "items": {"count": 1}}
                ],
                "computed": [],
            },
        )

        payload = {
            "nom": "Cfg invalida",
            "activa": True,
            "ordre": 1,
            "tipus": "individual",
            "schema": {
                "particions": [],
                "filtres": {},
                "puntuacio": {
                    "aparells": {"mode": "seleccionar", "ids": [self.comp_app_a.id]},
                    "camps_per_aparell": {str(self.comp_app_a.id): ["X"]},
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
        self.assertTrue(any("no es puntuable directament" in e for e in body.get("errors", [])))

    def test_compute_classificacio_uses_input_list_1_as_scalar(self):
        ScoringSchema.objects.create(
            aparell=self.app_a,
            schema={
                "fields": [
                    {"code": "L", "type": "list", "shape": "judge", "judges": {"count": 1}}
                ],
                "computed": [],
            },
        )
        ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins_a,
            exercici=1,
            comp_aparell=self.comp_app_a,
            inputs={"L": [7.2]},
            outputs={},
            total=0,
        )

        schema = self._base_cfg_schema()
        schema["puntuacio"]["aparells"] = {"mode": "seleccionar", "ids": [self.comp_app_a.id]}
        schema["puntuacio"]["camps_per_aparell"] = {str(self.comp_app_a.id): ["L"]}
        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Llista 1x1",
            activa=True,
            ordre=1,
            tipus="individual",
            schema=schema,
        )
        out = compute_classificacio(self.comp, cfg)
        rows = out.get("global", [])
        points_by_name = {r["participant"]: r["punts"] for r in rows}
        self.assertEqual(points_by_name.get("Participant A"), 7.2)
        self.assertEqual(points_by_name.get("Participant B"), 0.0)

    def test_classificacio_save_accepts_non_scalar_computed_main_field_under_current_validator(self):
        ScoringSchema.objects.create(
            aparell=self.app_a,
            schema={
                "fields": [
                    {"code": "X", "type": "matrix", "shape": "judge_x_item", "judges": {"count": 1}, "items": {"count": 2}}
                ],
                "computed": [
                    {"code": "X_copy", "label": "X copy", "formula": "X"},
                ],
            },
        )

        payload = {
            "nom": "Cfg computed no escalar",
            "activa": True,
            "ordre": 1,
            "tipus": "individual",
            "schema": {
                "particions": [],
                "filtres": {},
                "puntuacio": {
                    "aparells": {"mode": "seleccionar", "ids": [self.comp_app_a.id]},
                    "camps_per_aparell": {str(self.comp_app_a.id): ["X_copy"]},
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
        self.assertEqual(res.status_code, 200)
        cfg = ClassificacioConfig.objects.get(pk=res.json()["id"])
        self.assertEqual(
            (((cfg.schema.get("puntuacio") or {}).get("camps_per_aparell")) or {}).get(str(self.comp_app_a.id)),
            ["X_copy"],
        )

    def test_classificacio_save_accepts_non_scalar_computed_tie_field_under_current_validator(self):
        ScoringSchema.objects.create(
            aparell=self.app_a,
            schema={
                "fields": [
                    {"code": "X", "type": "matrix", "shape": "judge_x_item", "judges": {"count": 1}, "items": {"count": 2}}
                ],
                "computed": [
                    {"code": "X_copy", "label": "X copy", "formula": "X"},
                ],
            },
        )

        payload = {
            "nom": "Cfg tie computed no escalar",
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
                        "camps": ["X_copy"],
                        "ordre": "desc",
                        "scope": {
                            "aparells": {"mode": "seleccionar", "ids": [self.comp_app_a.id]},
                            "exercicis": {"mode": "hereta"},
                        },
                    }
                ],
                "presentacio": {"top_n": 0, "mostrar_empats": True},
            },
        }
        url = reverse("classificacio_save", kwargs={"pk": self.comp.id})
        res = self.client.post(url, data=json.dumps(payload), content_type="application/json")
        self.assertEqual(res.status_code, 200)
        cfg = ClassificacioConfig.objects.get(pk=res.json()["id"])
        self.assertEqual((((cfg.schema.get("desempat") or [])[0]) or {}).get("camps"), ["X_copy"])

    def test_classificacio_save_requires_real_camps_for_selected_apps(self):
        payload = {
            "nom": "Cfg sense camps reals",
            "activa": True,
            "ordre": 1,
            "tipus": "individual",
            "schema": {
                "particions": [],
                "filtres": {},
                "puntuacio": {
                    "aparells": {"mode": "seleccionar", "ids": [self.comp_app_a.id]},
                    "camps_per_aparell": {},
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
        self.assertTrue(any("camps_per_aparell" in e and "camp real" in e for e in body.get("errors", [])))

    def test_classificacio_save_rejects_invalid_raw_column_field(self):
        ScoringSchema.objects.create(
            aparell=self.app_a,
            schema={
                "fields": [
                    {"code": "E_total", "label": "Execucio", "type": "number"},
                ],
                "computed": [],
            },
        )

        payload = {
            "nom": "Cfg raw invalid",
            "activa": True,
            "ordre": 1,
            "tipus": "individual",
            "schema": {
                "particions": [],
                "filtres": {},
                "puntuacio": {
                    "aparells": {"mode": "seleccionar", "ids": [self.comp_app_a.id]},
                    "camps_per_aparell": {str(self.comp_app_a.id): ["E_total"]},
                    "agregacio_camps": "sum",
                    "exercicis": {"mode": "tots"},
                    "exercicis_best_n": 1,
                    "agregacio_exercicis": "sum",
                    "agregacio_aparells": "sum",
                    "ordre": "desc",
                },
                "desempat": [],
                "presentacio": {
                    "top_n": 0,
                    "mostrar_empats": True,
                    "columnes": [
                        {
                            "type": "raw",
                            "key": "raw_exec",
                            "label": "Exec",
                            "align": "right",
                            "decimals": 3,
                            "source": {
                                "aparell_id": self.comp_app_a.id,
                                "exercici": 1,
                                "camp": "EX",
                                "jutges": {"ids": []},
                            },
                        }
                    ],
                },
            },
        }
        url = reverse("classificacio_save", kwargs={"pk": self.comp.id})
        res = self.client.post(url, data=json.dumps(payload), content_type="application/json")
        self.assertEqual(res.status_code, 400)
        body = res.json()
        self.assertFalse(body.get("ok"))
        self.assertTrue(any("presentacio.columnes[0]" in e and "'EX'" in e for e in body.get("errors", [])))

    def test_classificacio_save_keeps_tie_schema_canonical_without_legacy_camp(self):
        ScoringSchema.objects.create(
            aparell=self.app_a,
            schema={
                "fields": [
                    {"code": "E_total", "label": "Execucio", "type": "number"},
                ],
                "computed": [],
            },
        )

        payload = {
            "nom": "Cfg canonical tie",
            "activa": True,
            "ordre": 1,
            "tipus": "individual",
            "schema": {
                "particions": [],
                "filtres": {},
                "puntuacio": {
                    "aparells": {"mode": "seleccionar", "ids": [self.comp_app_a.id]},
                    "camps_per_aparell": {str(self.comp_app_a.id): ["E_total"]},
                    "agregacio_camps": "sum",
                    "exercicis": {"mode": "tots"},
                    "exercicis_best_n": 1,
                    "agregacio_exercicis": "sum",
                    "agregacio_aparells": "sum",
                    "ordre": "desc",
                },
                "desempat": [
                    {
                        "camps": ["E_total"],
                        "agregacio_camps": "hereta",
                        "ordre": "desc",
                        "scope": {
                            "aparells": {"mode": "hereta"},
                            "exercicis": {"mode": "hereta"},
                        },
                    }
                ],
                "presentacio": {"top_n": 0, "mostrar_empats": True},
            },
        }
        url = reverse("classificacio_save", kwargs={"pk": self.comp.id})
        res = self.client.post(url, data=json.dumps(payload), content_type="application/json")
        self.assertEqual(res.status_code, 200)
        cfg = ClassificacioConfig.objects.get(pk=res.json()["id"])
        self.assertEqual((cfg.schema.get("puntuacio") or {}).get("camp"), "total")
        self.assertEqual((cfg.schema.get("puntuacio") or {}).get("agregacio"), "sum")
        self.assertEqual((cfg.schema.get("puntuacio") or {}).get("best_n"), 1)
        self.assertEqual((cfg.schema.get("desempat") or [])[0].get("camps"), ["E_total"])
        self.assertNotIn("camp", (cfg.schema.get("desempat") or [])[0])

    def test_classificacio_save_persists_tie_pipeline_canonical_format(self):
        ScoringSchema.objects.create(
            aparell=self.app_a,
            schema={
                "fields": [
                    {"code": "E_total", "label": "Execucio", "type": "number"},
                ],
                "computed": [],
            },
        )
        app_key = str(self.comp_app_a.id)
        payload = {
            "nom": "Cfg tie pipeline",
            "activa": True,
            "ordre": 1,
            "tipus": "individual",
            "schema": {
                "particions": [],
                "filtres": {},
                "puntuacio": {
                    "aparells": {"mode": "seleccionar", "ids": [self.comp_app_a.id]},
                    "camps_per_aparell": {app_key: ["E_total"]},
                    "agregacio_camps": "sum",
                    "exercicis": {"mode": "tots"},
                    "agregacio_exercicis": "sum",
                    "agregacio_aparells": "sum",
                    "ordre": "desc",
                },
                "desempat": [
                    {
                        "id": "tie_exec",
                        "nom": "Millor execucio",
                        "ordre": "desc",
                        "pipeline_version": 1,
                        "pipeline": {
                            "aparells": {"mode": "seleccionar", "ids": [self.comp_app_a.id]},
                            "camps_per_aparell": {app_key: ["E_total"]},
                            "agregacio_camps_per_aparell": {app_key: "sum"},
                            "agregacio_camps": "sum",
                            "candidate_source_mode": "raw_exercise",
                            "candidate_source_cfg": {
                                "mode": "tots",
                                "best_n": 1,
                                "index": 1,
                                "ids": [],
                                "agregacio_exercicis": "sum",
                            },
                            "candidate_source_per_aparell": {app_key: {"mode": "raw_exercise"}},
                            "exercicis": {"mode": "tots", "index": 1, "ids": [], "max_per_participant": 0},
                            "exercise_selection_scope": "per_member",
                            "mode_seleccio_exercicis": "per_aparell_global",
                            "exercicis_per_aparell": {},
                            "agregacio_exercicis": "sum",
                            "agregacio_aparells": "sum",
                            "mode_resultat_aparells": "score",
                            "ordre": "desc",
                        },
                    }
                ],
                "presentacio": {"top_n": 0, "mostrar_empats": True},
            },
        }
        res = self.client.post(
            reverse("classificacio_save", kwargs={"pk": self.comp.id}),
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)
        cfg = ClassificacioConfig.objects.get(pk=res.json()["id"])
        tie = (cfg.schema.get("desempat") or [])[0]
        self.assertEqual(tie.get("id"), "tie_exec")
        self.assertEqual(tie.get("nom"), "Millor execucio")
        self.assertEqual(tie.get("ordre"), "desc")
        self.assertEqual(tie.get("pipeline_version"), 1)
        self.assertEqual((((tie.get("pipeline") or {}).get("aparells") or {}).get("ids")), [self.comp_app_a.id])
        self.assertEqual((((tie.get("pipeline") or {}).get("camps_per_aparell") or {}).get(app_key)), ["E_total"])

    def test_classificacio_save_promotes_legacy_tie_pipeline_best_n_alias_and_cleans_clone_keys(self):
        ScoringSchema.objects.create(
            aparell=self.app_a,
            schema={
                "fields": [
                    {"code": "E_total", "label": "Execucio", "type": "number"},
                ],
                "computed": [],
            },
        )
        app_key = str(self.comp_app_a.id)
        payload = {
            "nom": "Cfg tie pipeline legacy alias",
            "activa": True,
            "ordre": 1,
            "tipus": "individual",
            "schema": {
                "particions": [],
                "filtres": {},
                "puntuacio": {
                    "aparells": {"mode": "seleccionar", "ids": [self.comp_app_a.id]},
                    "camps_per_aparell": {app_key: ["E_total"]},
                    "agregacio_camps": "sum",
                    "exercicis": {"mode": "tots"},
                    "agregacio_exercicis": "sum",
                    "agregacio_aparells": "sum",
                    "ordre": "desc",
                },
                "desempat": [
                    {
                        "id": "tie_exec_legacy",
                        "ordre": "desc",
                        "pipeline_version": 1,
                        "pipeline": {
                            "aparells": {"mode": "seleccionar", "ids": [self.comp_app_a.id]},
                            "camps_per_aparell": {app_key: ["E_total"]},
                            "agregacio_camps_per_aparell": {app_key: "sum"},
                            "agregacio_camps": "sum",
                            "exercicis": {"mode": "millor_n", "index": 1, "ids": [], "max_per_participant": 0},
                            "exercicis_best_n": 2,
                            "exercise_selection_scope": "per_member",
                            "mode_seleccio_exercicis": "per_aparell_global",
                            "agregacio_exercicis": "sum",
                            "agregacio_aparells": "sum",
                            "mode_resultat_aparells": "score",
                            "camp": "E_total",
                            "agregacio": "sum",
                            "best_n": 7,
                            "ordre": "desc",
                        },
                    }
                ],
                "presentacio": {"top_n": 0, "mostrar_empats": True},
            },
        }
        res = self.client.post(
            reverse("classificacio_save", kwargs={"pk": self.comp.id}),
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)
        cfg = ClassificacioConfig.objects.get(pk=res.json()["id"])
        pipeline = (((cfg.schema.get("desempat") or [])[0] or {}).get("pipeline") or {})
        self.assertEqual(((pipeline.get("exercicis") or {}).get("best_n")), 2)
        self.assertNotIn("exercicis_best_n", pipeline)
        self.assertNotIn("camp", pipeline)
        self.assertNotIn("agregacio", pipeline)
        self.assertNotIn("best_n", pipeline)

    def test_classificacio_save_tie_pipeline_canonical_best_n_precedence_wins_over_legacy_alias(self):
        ScoringSchema.objects.create(
            aparell=self.app_a,
            schema={
                "fields": [
                    {"code": "E_total", "label": "Execucio", "type": "number"},
                ],
                "computed": [],
            },
        )
        app_key = str(self.comp_app_a.id)
        payload = {
            "nom": "Cfg tie pipeline precedence",
            "activa": True,
            "ordre": 1,
            "tipus": "individual",
            "schema": {
                "particions": [],
                "filtres": {},
                "puntuacio": {
                    "aparells": {"mode": "seleccionar", "ids": [self.comp_app_a.id]},
                    "camps_per_aparell": {app_key: ["E_total"]},
                    "agregacio_camps": "sum",
                    "exercicis": {"mode": "tots"},
                    "agregacio_exercicis": "sum",
                    "agregacio_aparells": "sum",
                    "ordre": "desc",
                },
                "desempat": [
                    {
                        "id": "tie_exec_precedence",
                        "ordre": "desc",
                        "pipeline_version": 1,
                        "pipeline": {
                            "aparells": {"mode": "seleccionar", "ids": [self.comp_app_a.id]},
                            "camps_per_aparell": {app_key: ["E_total"]},
                            "agregacio_camps_per_aparell": {app_key: "sum"},
                            "agregacio_camps": "sum",
                            "exercicis": {"mode": "millor_n", "best_n": 3, "index": 1, "ids": [], "max_per_participant": 0},
                            "exercicis_best_n": 2,
                            "exercise_selection_scope": "per_member",
                            "mode_seleccio_exercicis": "per_aparell_global",
                            "agregacio_exercicis": "sum",
                            "agregacio_aparells": "sum",
                            "mode_resultat_aparells": "score",
                            "ordre": "desc",
                        },
                    }
                ],
                "presentacio": {"top_n": 0, "mostrar_empats": True},
            },
        }
        res = self.client.post(
            reverse("classificacio_save", kwargs={"pk": self.comp.id}),
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)
        cfg = ClassificacioConfig.objects.get(pk=res.json()["id"])
        pipeline = (((cfg.schema.get("desempat") or [])[0] or {}).get("pipeline") or {})
        self.assertEqual(((pipeline.get("exercicis") or {}).get("best_n")), 3)
        self.assertNotIn("exercicis_best_n", pipeline)

    def test_classificacio_save_rejects_forbidden_tie_pipeline_keys(self):
        payload = {
            "nom": "Cfg tie pipeline invalid",
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
                    "agregacio_exercicis": "sum",
                    "agregacio_aparells": "sum",
                    "ordre": "desc",
                },
                "desempat": [
                    {
                        "id": "tie_invalid",
                        "ordre": "desc",
                        "pipeline_version": 1,
                        "pipeline": {
                            "aparells": {"mode": "seleccionar", "ids": [self.comp_app_a.id]},
                            "camps_per_aparell": {str(self.comp_app_a.id): ["total"]},
                            "agregacio_camps_per_aparell": {str(self.comp_app_a.id): "sum"},
                            "agregacio_camps": "sum",
                            "exercicis": {"mode": "tots"},
                            "exercise_selection_scope": "per_member",
                            "mode_seleccio_exercicis": "per_aparell_global",
                            "agregacio_exercicis": "sum",
                            "agregacio_aparells": "sum",
                            "mode_resultat_aparells": "score",
                            "victories": {},
                        },
                    }
                ],
                "presentacio": {"top_n": 0, "mostrar_empats": True},
            },
        }
        res = self.client.post(
            reverse("classificacio_save", kwargs={"pk": self.comp.id}),
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 400)
        body = res.json()
        self.assertTrue(any("desempat[0].pipeline.victories" in err for err in body.get("errors", [])))

    def test_classificacio_save_rejects_unknown_tie_pipeline_keys_after_legacy_cleanup(self):
        payload = {
            "nom": "Cfg tie pipeline unknown key",
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
                    "agregacio_exercicis": "sum",
                    "agregacio_aparells": "sum",
                    "ordre": "desc",
                },
                "desempat": [
                    {
                        "id": "tie_unknown",
                        "ordre": "desc",
                        "pipeline_version": 1,
                        "pipeline": {
                            "aparells": {"mode": "seleccionar", "ids": [self.comp_app_a.id]},
                            "camps_per_aparell": {str(self.comp_app_a.id): ["total"]},
                            "agregacio_camps_per_aparell": {str(self.comp_app_a.id): "sum"},
                            "agregacio_camps": "sum",
                            "exercicis": {"mode": "tots"},
                            "exercise_selection_scope": "per_member",
                            "mode_seleccio_exercicis": "per_aparell_global",
                            "agregacio_exercicis": "sum",
                            "agregacio_aparells": "sum",
                            "mode_resultat_aparells": "score",
                            "unexpected_key": True,
                        },
                    }
                ],
                "presentacio": {"top_n": 0, "mostrar_empats": True},
            },
        }
        res = self.client.post(
            reverse("classificacio_save", kwargs={"pk": self.comp.id}),
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 400)
        body = res.json()
        self.assertTrue(any("desempat[0].pipeline.unexpected_key" in err for err in body.get("errors", [])))

    def test_prepare_schema_for_builder_hydration_materializes_legacy_tie_pipeline(self):
        schema = self._base_cfg_schema()
        schema["puntuacio"]["aparells"] = {"mode": "seleccionar", "ids": [self.comp_app_a.id]}
        schema["puntuacio"]["camps_per_aparell"] = {str(self.comp_app_a.id): ["total"]}
        schema["desempat"] = [
            {
                "camp": "total",
                "camps": ["total"],
                "ordre": "desc",
                "scope": {
                    "aparells": {"mode": "seleccionar", "ids": [self.comp_app_a.id]},
                    "exercicis": {"mode": "tots"},
                },
            }
        ]
        hydrated = prepare_schema_for_builder_hydration(self.comp, schema, tipus="individual")
        tie = (hydrated.get("desempat") or [])[0]
        self.assertEqual(tie.get("id"), "tie_1")
        self.assertEqual(tie.get("pipeline_version"), 1)
        self.assertEqual((((tie.get("pipeline") or {}).get("aparells") or {}).get("ids")), [self.comp_app_a.id])
        self.assertEqual((((tie.get("pipeline") or {}).get("camps_per_aparell") or {}).get(str(self.comp_app_a.id))), ["total"])

    def test_prepare_schema_for_builder_hydration_promotes_legacy_tie_pipeline_best_n_alias(self):
        schema = self._base_cfg_schema()
        schema["puntuacio"]["aparells"] = {"mode": "seleccionar", "ids": [self.comp_app_a.id]}
        schema["puntuacio"]["camps_per_aparell"] = {str(self.comp_app_a.id): ["total"]}
        schema["desempat"] = [
            {
                "id": "tie_legacy_best_n",
                "ordre": "desc",
                "pipeline_version": 1,
                "pipeline": {
                    "aparells": {"mode": "seleccionar", "ids": [self.comp_app_a.id]},
                    "camps_per_aparell": {str(self.comp_app_a.id): ["total"]},
                    "agregacio_camps_per_aparell": {str(self.comp_app_a.id): "sum"},
                    "agregacio_camps": "sum",
                    "exercicis": {"mode": "millor_n"},
                    "exercicis_best_n": 2,
                    "exercise_selection_scope": "per_member",
                    "mode_seleccio_exercicis": "per_aparell_global",
                    "agregacio_exercicis": "sum",
                    "agregacio_aparells": "sum",
                    "mode_resultat_aparells": "score",
                    "camp": "total",
                    "agregacio": "sum",
                    "best_n": 9,
                    "ordre": "desc",
                },
            }
        ]
        hydrated = prepare_schema_for_builder_hydration(self.comp, schema, tipus="individual")
        pipeline = (((hydrated.get("desempat") or [])[0] or {}).get("pipeline") or {})
        self.assertEqual(((pipeline.get("exercicis") or {}).get("best_n")), 2)
        self.assertNotIn("exercicis_best_n", pipeline)
        self.assertNotIn("camp", pipeline)
        self.assertNotIn("agregacio", pipeline)
        self.assertNotIn("best_n", pipeline)

    def test_compute_classificacio_pipeline_tie_supports_per_app_override_exercicis(self):
        self.comp_app_a.nombre_exercicis = 2
        self.comp_app_a.save(update_fields=["nombre_exercicis"])
        self.comp_app_b.nombre_exercicis = 2
        self.comp_app_b.save(update_fields=["nombre_exercicis"])

        for inscripcio, comp_aparell, exercici, total in (
            (self.ins_a, self.comp_app_a, 1, 9.0),
            (self.ins_a, self.comp_app_a, 2, 1.0),
            (self.ins_a, self.comp_app_b, 1, 5.0),
            (self.ins_a, self.comp_app_b, 2, 5.0),
            (self.ins_b, self.comp_app_a, 1, 6.0),
            (self.ins_b, self.comp_app_a, 2, 4.0),
            (self.ins_b, self.comp_app_b, 1, 8.0),
            (self.ins_b, self.comp_app_b, 2, 2.0),
        ):
            ScoreEntry.objects.create(
                competicio=self.comp,
                inscripcio=inscripcio,
                exercici=exercici,
                comp_aparell=comp_aparell,
                inputs={},
                outputs={},
                total=total,
            )

        schema = self._base_cfg_schema()
        schema["puntuacio"]["aparells"] = {"mode": "seleccionar", "ids": [self.comp_app_a.id, self.comp_app_b.id]}
        schema["puntuacio"]["camps_per_aparell"] = {
            str(self.comp_app_a.id): ["total"],
            str(self.comp_app_b.id): ["total"],
        }
        schema["puntuacio"]["agregacio_camps_per_aparell"] = {
            str(self.comp_app_a.id): "sum",
            str(self.comp_app_b.id): "sum",
        }
        schema["puntuacio"]["candidate_source_per_aparell"] = {
            str(self.comp_app_a.id): {"mode": "raw_exercise"},
            str(self.comp_app_b.id): {"mode": "raw_exercise"},
        }
        schema["puntuacio"]["exercicis"] = {"mode": "tots"}
        schema["desempat"] = [
            {
                "id": "tie_pipeline_override",
                "ordre": "desc",
                "pipeline_version": 1,
                "pipeline": {
                    "aparells": {"mode": "seleccionar", "ids": [self.comp_app_a.id, self.comp_app_b.id]},
                    "camps_per_aparell": {
                        str(self.comp_app_a.id): ["total"],
                        str(self.comp_app_b.id): ["total"],
                    },
                    "agregacio_camps_per_aparell": {
                        str(self.comp_app_a.id): "sum",
                        str(self.comp_app_b.id): "sum",
                    },
                    "agregacio_camps": "sum",
                    "candidate_source_mode": "raw_exercise",
                    "candidate_source_cfg": {
                        "mode": "tots",
                        "best_n": 1,
                        "index": 1,
                        "ids": [],
                        "agregacio_exercicis": "sum",
                    },
                    "candidate_source_per_aparell": {
                        str(self.comp_app_a.id): {"mode": "raw_exercise"},
                        str(self.comp_app_b.id): {"mode": "raw_exercise"},
                    },
                    "exercicis": {"mode": "tots", "index": 1, "ids": [], "max_per_participant": 0},
                    "exercise_selection_scope": "per_member",
                    "mode_seleccio_exercicis": "per_aparell_override",
                    "exercicis_per_aparell": {
                        str(self.comp_app_a.id): {"mode": "millor_1", "index": 1, "ids": [], "max_per_participant": 0},
                        str(self.comp_app_b.id): {"mode": "pitjor_1", "index": 1, "ids": [], "max_per_participant": 0},
                    },
                    "agregacio_exercicis": "sum",
                    "agregacio_aparells": "sum",
                    "mode_resultat_aparells": "score",
                    "ordre": "desc",
                },
            }
        ]

        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Tie pipeline per app override",
            activa=True,
            ordre=1,
            tipus="individual",
            schema=schema,
        )
        rows = compute_classificacio(self.comp, cfg).get("global", [])
        self.assertEqual([row["participant"] for row in rows], ["Participant A", "Participant B"])

    def test_compute_classificacio_main_score_supports_per_app_exercise_aggregation(self):
        self.comp_app_a.nombre_exercicis = 2
        self.comp_app_a.save(update_fields=["nombre_exercicis"])
        self.comp_app_b.nombre_exercicis = 2
        self.comp_app_b.save(update_fields=["nombre_exercicis"])

        for inscripcio, comp_aparell, exercici, total in (
            (self.ins_a, self.comp_app_a, 1, 9.0),
            (self.ins_a, self.comp_app_a, 2, 1.0),
            (self.ins_a, self.comp_app_b, 1, 5.0),
            (self.ins_a, self.comp_app_b, 2, 5.0),
            (self.ins_b, self.comp_app_a, 1, 6.0),
            (self.ins_b, self.comp_app_a, 2, 6.0),
            (self.ins_b, self.comp_app_b, 1, 8.0),
            (self.ins_b, self.comp_app_b, 2, 2.0),
        ):
            ScoreEntry.objects.create(
                competicio=self.comp,
                inscripcio=inscripcio,
                exercici=exercici,
                comp_aparell=comp_aparell,
                inputs={},
                outputs={},
                total=total,
            )

        schema = self._base_cfg_schema()
        schema["puntuacio"]["aparells"] = {"mode": "seleccionar", "ids": [self.comp_app_a.id, self.comp_app_b.id]}
        schema["puntuacio"]["camps_per_aparell"] = {
            str(self.comp_app_a.id): ["total"],
            str(self.comp_app_b.id): ["total"],
        }
        schema["puntuacio"]["agregacio_camps_per_aparell"] = {
            str(self.comp_app_a.id): "sum",
            str(self.comp_app_b.id): "sum",
        }
        schema["puntuacio"]["candidate_source_per_aparell"] = {
            str(self.comp_app_a.id): {"mode": "raw_exercise"},
            str(self.comp_app_b.id): {"mode": "raw_exercise"},
        }
        schema["puntuacio"]["exercicis"] = {"mode": "tots"}
        schema["puntuacio"]["mode_seleccio_exercicis"] = "per_aparell_override"
        schema["puntuacio"]["exercicis_per_aparell"] = {
            str(self.comp_app_a.id): {"mode": "tots"},
            str(self.comp_app_b.id): {"mode": "tots"},
        }
        schema["puntuacio"]["agregacio_exercicis_per_aparell"] = {
            str(self.comp_app_a.id): "max",
            str(self.comp_app_b.id): "sum",
        }
        schema["puntuacio"]["agregacio_exercicis"] = "sum"
        schema["puntuacio"]["agregacio_aparells"] = "sum"

        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Puntuacio agg ex per app",
            activa=True,
            ordre=1,
            tipus="individual",
            schema=schema,
        )
        rows = compute_classificacio(self.comp, cfg).get("global", [])
        self.assertEqual([row["participant"] for row in rows], ["Participant A", "Participant B"])
        self.assertEqual((rows[0].get("by_app") or {}).get(self.comp_app_a.id), 9.0)
        self.assertEqual((rows[0].get("by_app") or {}).get(self.comp_app_b.id), 10.0)
        self.assertEqual(rows[0].get("score"), 19.0)

    def test_prepare_schema_for_builder_hydration_preserves_per_app_exercise_aggregation_maps(self):
        schema = self._base_cfg_schema()
        schema["puntuacio"]["aparells"] = {"mode": "seleccionar", "ids": [self.comp_app_a.id, self.comp_app_b.id]}
        schema["puntuacio"]["camps_per_aparell"] = {
            str(self.comp_app_a.id): ["total"],
            str(self.comp_app_b.id): ["total"],
        }
        schema["puntuacio"]["exercicis_per_aparell"] = {
            str(self.comp_app_a.id): {"mode": "millor_1"},
            str(self.comp_app_b.id): {"mode": "tots"},
        }
        schema["puntuacio"]["agregacio_exercicis_per_aparell"] = {
            str(self.comp_app_a.id): "max",
            str(self.comp_app_b.id): "sum",
        }
        schema["desempat"] = [
            {
                "camp": "total",
                "camps": ["total"],
                "ordre": "desc",
                "mode_seleccio_exercicis": "per_aparell_override",
                "exercicis_per_aparell": {
                    str(self.comp_app_a.id): {"mode": "millor_1"},
                    str(self.comp_app_b.id): {"mode": "pitjor_1"},
                },
                "agregacio_exercicis_per_aparell": {
                    str(self.comp_app_a.id): "max",
                    str(self.comp_app_b.id): "min",
                },
                "scope": {
                    "aparells": {"mode": "seleccionar", "ids": [self.comp_app_a.id, self.comp_app_b.id]},
                    "exercicis": {"mode": "tots"},
                },
            }
        ]
        schema["puntuacio"]["victories"] = {
            "punts_victoria": 1,
            "punts_empat": 0.5,
            "sense_nota_mode": "skip",
            "mode_camps": "agregat",
            "mode_exercicis": "agregat",
            "mode_seleccio_exercicis_camps_separats": "per_camp",
            "agregacio_victories_camps": "sum",
            "agregacio_victories_exercicis": "sum",
            "desempat_comparacio": [
                {
                    "camp": "total",
                    "camps": ["total"],
                    "ordre": "desc",
                    "mode_seleccio_exercicis": "per_aparell_override",
                    "exercicis_per_aparell": {
                        str(self.comp_app_a.id): {"mode": "millor_1"},
                        str(self.comp_app_b.id): {"mode": "tots"},
                    },
                    "agregacio_exercicis_per_aparell": {
                        str(self.comp_app_a.id): "max",
                        str(self.comp_app_b.id): "sum",
                    },
                    "scope": {"exercicis": {"mode": "tots"}},
                }
            ],
        }

        hydrated = prepare_schema_for_builder_hydration(self.comp, schema, tipus="individual")
        punt = hydrated.get("puntuacio") or {}
        self.assertEqual(
            punt.get("agregacio_exercicis_per_aparell"),
            {
                str(self.comp_app_a.id): "max",
                str(self.comp_app_b.id): "sum",
            },
        )
        tie = (hydrated.get("desempat") or [])[0] or {}
        self.assertEqual(
            tie.get("agregacio_exercicis_per_aparell"),
            {
                str(self.comp_app_a.id): "max",
                str(self.comp_app_b.id): "min",
            },
        )
        self.assertEqual(
            (((tie.get("pipeline") or {}).get("agregacio_exercicis_per_aparell")) or {}),
            {
                str(self.comp_app_a.id): "max",
                str(self.comp_app_b.id): "min",
            },
        )
        victory_tie = ((((punt.get("victories") or {}).get("desempat_comparacio")) or [])[0] or {})
        self.assertEqual(
            victory_tie.get("agregacio_exercicis_per_aparell"),
            {
                str(self.comp_app_a.id): "max",
                str(self.comp_app_b.id): "sum",
            },
        )

    def test_classificacio_save_returns_persisted_team_schema_with_mode_resolution(self):
        self._ensure_native_equip_context(self.comp)
        payload = {
            "nom": "Cfg equips persisted",
            "activa": True,
            "ordre": 1,
            "tipus": "equips",
            "schema": {
                **self._selected_total_schema([self.comp_app_a.id]),
                "equips": {
                    "context_code": "native",
                    "assignment_source": {"mode": "context", "context_code": "native", "fallback": "native"},
                    "team_mode": "derived_from_individual",
                },
            },
        }

        res = self.client.post(
            reverse("classificacio_save", kwargs={"pk": self.comp.id}),
            data=json.dumps(payload),
            content_type="application/json",
        )

        self.assertEqual(res.status_code, 200)
        body = res.json()
        cfg_payload = body.get("cfg") or {}
        self.assertEqual(cfg_payload.get("tipus"), "equips")
        mode_resolution = (((cfg_payload.get("schema") or {}).get("equips") or {}).get("mode_resolution")) or {}
        self.assertTrue(mode_resolution.get("resolved_at"))
        self.assertIn("eligible_team_app_ids_at_save", mode_resolution)

        cfg = ClassificacioConfig.objects.get(pk=body["id"])
        saved_resolution = (((cfg.schema.get("equips") or {}).get("mode_resolution")) or {})
        self.assertEqual(saved_resolution.get("resolved_at"), mode_resolution.get("resolved_at"))

    def test_classificacio_save_roundtrip_preserves_legacy_global_pool_and_member_cap(self):
        self._ensure_native_equip_context(self.comp)
        payload = {
            "nom": "Cfg equips legacy exercise selection",
            "activa": True,
            "ordre": 1,
            "tipus": "equips",
            "schema": {
                **self._selected_total_schema([self.comp_app_a.id, self.comp_app_b.id]),
                "puntuacio": {
                    **self._selected_total_schema([self.comp_app_a.id, self.comp_app_b.id])["puntuacio"],
                    "aparells": {"mode": "seleccionar", "ids": [self.comp_app_a.id, self.comp_app_b.id]},
                    "camps_per_aparell": {
                        str(self.comp_app_a.id): ["total"],
                        str(self.comp_app_b.id): ["total"],
                    },
                    "exercicis": {"mode": "millor_n", "best_n": 4, "max_per_participant": 1},
                    "exercise_selection_scope": "team_pool",
                    "mode_seleccio_exercicis": "per_aparell_global",
                    "exercicis_per_aparell": {
                        str(self.comp_app_a.id): {"mode": "millor_n", "best_n": 4, "max_per_participant": 1},
                        str(self.comp_app_b.id): {"mode": "millor_n", "best_n": 3, "max_per_participant": 1},
                    },
                    "agregacio_exercicis": "sum",
                    "agregacio_aparells": "sum",
                    "ordre": "desc",
                },
                "equips": {
                    "context_code": "native",
                    "assignment_source": {"mode": "context", "context_code": "native", "fallback": "native"},
                    "team_mode": "derived_from_individual",
                    "incloure_sense_equip": False,
                },
            },
        }

        res = self.client.post(
            reverse("classificacio_save", kwargs={"pk": self.comp.id}),
            data=json.dumps(payload),
            content_type="application/json",
        )

        self.assertEqual(res.status_code, 200)
        body = res.json()
        cfg = ClassificacioConfig.objects.get(pk=body["id"])
        punt = cfg.schema.get("puntuacio") or {}
        self.assertEqual(punt.get("mode_seleccio_exercicis"), "per_aparell_global")
        self.assertEqual(punt.get("exercise_selection_scope"), "team_pool")
        self.assertEqual((punt.get("exercicis") or {}).get("max_per_participant"), 1)
        self.assertEqual(sorted((punt.get("exercicis_per_aparell") or {}).keys()), [str(self.comp_app_a.id), str(self.comp_app_b.id)])

        hydrated = prepare_schema_for_builder_hydration(self.comp, cfg.schema or {}, tipus="equips")
        hydrated_punt = hydrated.get("puntuacio") or {}
        self.assertEqual(hydrated_punt.get("mode_seleccio_exercicis"), "per_aparell_global")
        self.assertEqual(hydrated_punt.get("exercise_selection_scope"), "team_pool")
        self.assertEqual((hydrated_punt.get("exercicis") or {}).get("max_per_participant"), 1)
        self.assertEqual((hydrated_punt.get("aparells") or {}).get("ids"), [self.comp_app_a.id, self.comp_app_b.id])

    def test_classificacio_save_roundtrip_preserves_candidate_source_contract(self):
        payload_schema = self._selected_total_schema([self.comp_app_a.id, self.comp_app_b.id])
        payload_schema["puntuacio"] = {
            **payload_schema["puntuacio"],
            "candidate_source_mode": "participant_aggregate",
            "candidate_source_cfg": {
                "mode": "millor_n",
                "best_n": 2,
                "index": 1,
                "ids": [],
                "agregacio_exercicis": "sum",
            },
        }
        payload = {
            "nom": "Cfg candidate source",
            "activa": True,
            "ordre": 1,
            "tipus": "individual",
            "schema": payload_schema,
        }

        res = self.client.post(
            reverse("classificacio_save", kwargs={"pk": self.comp.id}),
            data=json.dumps(payload),
            content_type="application/json",
        )

        self.assertEqual(res.status_code, 200)
        body = res.json()
        cfg = ClassificacioConfig.objects.get(pk=body["id"])
        punt = cfg.schema.get("puntuacio") or {}
        self.assertEqual(punt.get("candidate_source_mode"), "participant_aggregate")
        self.assertEqual((punt.get("candidate_source_cfg") or {}).get("mode"), "millor_n")
        self.assertEqual((punt.get("candidate_source_cfg") or {}).get("best_n"), 2)

        hydrated = prepare_schema_for_builder_hydration(self.comp, cfg.schema or {}, tipus="individual")
        hydrated_punt = hydrated.get("puntuacio") or {}
        self.assertEqual(hydrated_punt.get("candidate_source_mode"), "participant_aggregate")
        self.assertEqual((hydrated_punt.get("candidate_source_cfg") or {}).get("mode"), "millor_n")
        self.assertEqual((hydrated_punt.get("candidate_source_cfg") or {}).get("best_n"), 2)

    def test_classificacio_save_roundtrip_applies_candidate_source_per_app_fallback_cfg(self):
        payload_schema = self._selected_total_schema([self.comp_app_a.id, self.comp_app_b.id])
        payload_schema["puntuacio"] = {
            **payload_schema["puntuacio"],
            "candidate_source_mode": "participant_aggregate",
            "candidate_source_cfg": {
                "mode": "millor_n",
                "best_n": 2,
                "index": 3,
                "ids": [1, 2],
                "agregacio_exercicis": "avg",
            },
            "candidate_source_per_aparell": {
                str(self.comp_app_a.id): {
                    "mode": "participant_aggregate",
                },
                str(self.comp_app_b.id): {
                    "mode": "participant_aggregate",
                    "cfg": {
                        "mode": "index",
                    },
                },
            },
        }
        payload = {
            "nom": "Cfg candidate source fallback",
            "activa": True,
            "ordre": 1,
            "tipus": "individual",
            "schema": payload_schema,
        }

        res = self.client.post(
            reverse("classificacio_save", kwargs={"pk": self.comp.id}),
            data=json.dumps(payload),
            content_type="application/json",
        )

        self.assertEqual(res.status_code, 200)
        body = res.json()
        cfg = ClassificacioConfig.objects.get(pk=body["id"])
        punt = cfg.schema.get("puntuacio") or {}
        per_app = punt.get("candidate_source_per_aparell") or {}

        self.assertEqual((per_app.get(str(self.comp_app_a.id)) or {}).get("mode"), "participant_aggregate")
        self.assertEqual(((per_app.get(str(self.comp_app_a.id)) or {}).get("cfg") or {}).get("mode"), "millor_n")
        self.assertEqual(((per_app.get(str(self.comp_app_a.id)) or {}).get("cfg") or {}).get("best_n"), 2)
        self.assertEqual(((per_app.get(str(self.comp_app_a.id)) or {}).get("cfg") or {}).get("index"), 3)
        self.assertEqual(((per_app.get(str(self.comp_app_a.id)) or {}).get("cfg") or {}).get("agregacio_exercicis"), "avg")

        self.assertEqual((per_app.get(str(self.comp_app_b.id)) or {}).get("mode"), "participant_aggregate")
        self.assertEqual(((per_app.get(str(self.comp_app_b.id)) or {}).get("cfg") or {}).get("mode"), "index")
        self.assertEqual(((per_app.get(str(self.comp_app_b.id)) or {}).get("cfg") or {}).get("index"), 3)
        self.assertEqual(((per_app.get(str(self.comp_app_b.id)) or {}).get("cfg") or {}).get("agregacio_exercicis"), "avg")

        hydrated = prepare_schema_for_builder_hydration(self.comp, cfg.schema or {}, tipus="individual")
        hydrated_per_app = ((hydrated.get("puntuacio") or {}).get("candidate_source_per_aparell") or {})
        self.assertEqual((((hydrated_per_app.get(str(self.comp_app_a.id)) or {}).get("cfg")) or {}).get("mode"), "millor_n")
        self.assertEqual((((hydrated_per_app.get(str(self.comp_app_b.id)) or {}).get("cfg")) or {}).get("mode"), "index")

    def test_classificacio_preview_returns_consistent_error_when_compute_fails(self):
        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Preview runtime error",
            activa=True,
            ordre=1,
            tipus="individual",
            schema=self._selected_total_schema([self.comp_app_a.id]),
        )

        with patch("competicions_trampoli.views.classificacions.builder.compute_classificacio", side_effect=RuntimeError("boom preview")):
            res = self.client.post(
                reverse("classificacio_preview", kwargs={"pk": self.comp.id, "cid": cfg.id}),
                data=json.dumps({}),
                content_type="application/json",
            )

        self.assertEqual(res.status_code, 400)
        body = res.json()
        self.assertEqual(body.get("error"), "No s'ha pogut previsualitzar la classificacio.")
        self.assertEqual(body.get("errors"), ["boom preview"])
        self.assertTrue(body.get("error_details"))

