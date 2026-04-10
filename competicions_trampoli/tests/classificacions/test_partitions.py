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

    def test_compute_classificacio_supports_custom_partition_groups_for_categoria(self):
        self.ins_a.categoria = "ALEVI"
        self.ins_a.save(update_fields=["categoria"])
        self.ins_b.categoria = "PREBENJAMI"
        self.ins_b.save(update_fields=["categoria"])

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
            total=8.0,
        )

        schema = self._valid_partition_schema()
        schema["particions"] = ["categoria"]
        schema["particions_custom"] = {
            "categoria": {
                "mode": "custom",
                "grups": [
                    {"key": "base", "label": "Base", "values": ["ALEVI", "PREBENJAMI"]},
                ],
            }
        }
        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Particio custom categoria",
            activa=True,
            ordre=1,
            tipus="individual",
            schema=schema,
        )

        out = compute_classificacio(self.comp, cfg)
        self.assertEqual(list(out.keys()), ["categoria:Base"])
        self.assertEqual(len(out["categoria:Base"]), 2)

    def test_compute_classificacio_supports_partition_by_schema_extra_field(self):
        self.comp.inscripcions_schema = {
            "columns": [
                {"code": "nivell", "label": "Nivell", "kind": "extra"},
            ]
        }
        self.comp.save(update_fields=["inscripcions_schema"])

        self.ins_a.extra = {"nivell": "N1"}
        self.ins_a.save(update_fields=["extra"])
        self.ins_b.extra = {"nivell": "N2"}
        self.ins_b.save(update_fields=["extra"])

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
            total=8.0,
        )

        schema = self._valid_partition_schema()
        schema["particions"] = ["nivell"]
        schema["particions_custom"] = {
            "nivell": {
                "mode": "custom",
                "grups": [
                    {"key": "bloc_1", "label": "Bloc 1", "values": ["N1", "N2"]},
                ],
            }
        }
        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Particio extra",
            activa=True,
            ordre=1,
            tipus="individual",
            schema=schema,
        )

        out = compute_classificacio(self.comp, cfg)
        self.assertEqual(list(out.keys()), ["nivell:Bloc 1"])
        self.assertEqual(len(out["nivell:Bloc 1"]), 2)

    def test_compute_classificacio_supports_conditional_partition_on_parent_group(self):
        ins_c = self._create_inscripcio(self.comp, "Participant C", ordre=3)

        self.ins_a.categoria = "ALEVI"
        self.ins_a.subcategoria = "N1"
        self.ins_a.save(update_fields=["categoria", "subcategoria"])
        self.ins_b.categoria = "PREBENJAMI"
        self.ins_b.subcategoria = "N2"
        self.ins_b.save(update_fields=["categoria", "subcategoria"])
        ins_c.categoria = "INFANTIL"
        ins_c.subcategoria = "N3"
        ins_c.save(update_fields=["categoria", "subcategoria"])

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
            total=8.0,
        )
        ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=ins_c,
            exercici=1,
            comp_aparell=self.comp_app_a,
            inputs={},
            outputs={},
            total=7.0,
        )

        schema = self._valid_partition_schema()
        schema["particions"] = ["categoria", "subcategoria"]
        schema["particions_v2"] = [
            {"code": "categoria", "apply_mode": "all"},
            {"code": "subcategoria", "apply_mode": "some_parents", "parent_values": ["Base"]},
        ]
        schema["particions_custom"] = {
            "categoria": {
                "mode": "custom",
                "grups": [
                    {"key": "base", "label": "Base", "values": ["ALEVI", "PREBENJAMI"]},
                    {"key": "grans", "label": "Grans", "values": ["INFANTIL"]},
                ],
            }
        }
        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Particio condicional",
            activa=True,
            ordre=1,
            tipus="individual",
            schema=schema,
        )

        out = compute_classificacio(self.comp, cfg)
        self.assertEqual(
            set(out.keys()),
            {"categoria:Base|subcategoria:N1", "categoria:Base|subcategoria:N2", "categoria:Grans"},
        )
        self.assertEqual(out["categoria:Grans"][0]["participant"], "Participant C")

    def test_normalize_particions_schema_populates_particions_v2_from_legacy_list(self):
        schema = self._valid_partition_schema()
        schema["particions"] = ["categoria", "subcategoria"]

        normalized = _normalize_particions_schema(schema)
        self.assertEqual(normalized.get("particions"), ["categoria", "subcategoria"])
        self.assertEqual(
            normalized.get("particions_v2"),
            [
                {"code": "categoria", "apply_mode": "all", "parent_values": []},
                {"code": "subcategoria", "apply_mode": "all", "parent_values": []},
            ],
        )

    def test_compute_classificacio_partitions_by_birth_year_ranges(self):
        self.ins_a.data_naixement = date(2008, 5, 4)
        self.ins_b.data_naixement = date(2011, 2, 10)
        self.ins_a.save(update_fields=["data_naixement"])
        self.ins_b.save(update_fields=["data_naixement"])

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
            total=8.0,
        )

        schema = self._valid_partition_schema()
        schema["particions"] = ["any_naixement_forquilla"]
        schema["particions_v2"] = [
            {"code": "any_naixement_forquilla", "apply_mode": "all", "parent_values": []},
        ]
        schema["particions_config"] = {
            "any_naixement_forquilla": {
                "ranges": [
                    {"label": "2007-2009", "from_year": 2007, "to_year": 2009},
                    {"label": "2010-2012", "from_year": 2010, "to_year": 2012},
                ],
                "sense_data_label": "Sense data",
                "fora_rang_label": "Fora de forquilla",
            }
        }
        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Forquilles naixement",
            activa=True,
            ordre=1,
            tipus="individual",
            schema=schema,
        )

        out = compute_classificacio(self.comp, cfg)
        self.assertEqual(
            set(out.keys()),
            {"any_naixement_forquilla:2007-2009", "any_naixement_forquilla:2010-2012"},
        )
        self.assertEqual(out["any_naixement_forquilla:2007-2009"][0]["participant"], "Participant A")
        self.assertEqual(out["any_naixement_forquilla:2010-2012"][0]["participant"], "Participant B")

    def test_classificacio_save_rejects_overlapping_birth_year_ranges(self):
        schema = self._valid_partition_schema()
        schema["particions"] = ["any_naixement_forquilla"]
        schema["particions_v2"] = [
            {"code": "any_naixement_forquilla", "apply_mode": "all", "parent_values": []},
        ]
        schema["particions_config"] = {
            "any_naixement_forquilla": {
                "ranges": [
                    {"label": "2007-2009", "from_year": 2007, "to_year": 2009},
                    {"label": "2009-2011", "from_year": 2009, "to_year": 2011},
                ]
            }
        }

        _, errors = _validate_schema_for_competicio(self.comp, schema, tipus="individual")
        self.assertTrue(any("solapament" in e for e in errors))

    def test_classificacio_save_accepts_birth_year_ranges_for_team_rankings(self):
        schema = self._valid_partition_schema()
        schema["particions"] = ["any_naixement_forquilla"]
        schema["particions_v2"] = [
            {"code": "any_naixement_forquilla", "apply_mode": "all", "parent_values": []},
        ]
        schema["particions_config"] = {
            "any_naixement_forquilla": {
                "ranges": [
                    {"label": "2007-2009", "from_year": 2007, "to_year": 2009},
                ],
                "team_rules": {
                    "reference_mode": "oldest_member_birthdate",
                    "compliance_mode": "strict",
                    "max_members_outside_range": 0,
                    "missing_birthdate_policy": "outside_range",
                },
            }
        }

        _, errors = _validate_schema_for_competicio(self.comp, schema, tipus="equips")
        self.assertEqual(errors, [])

    def test_validate_particions_schema_rejects_conditional_partition_without_parent_values(self):
        schema = self._valid_partition_schema()
        schema["particions_v2"] = [
            {"code": "categoria", "apply_mode": "all"},
            {"code": "subcategoria", "apply_mode": "some_parents", "parent_values": []},
        ]
        normalized = _normalize_particions_schema(schema)
        errors = _validate_particions_schema(self.comp, normalized)
        self.assertTrue(any("parent_values" in e for e in errors))

    def test_classificacio_save_rejects_unknown_partition_field(self):
        payload = {
            "nom": "Cfg particio desconeguda",
            "activa": True,
            "ordre": 1,
            "tipus": "individual",
            "schema": self._valid_partition_schema(),
        }
        payload["schema"]["particions"] = ["camp_inexistent"]
        payload["schema"]["particions_custom"] = {
            "camp_inexistent": {
                "mode": "custom",
                "grups": [{"label": "X", "values": ["A"]}],
            }
        }

        url = reverse("classificacio_save", kwargs={"pk": self.comp.id})
        res = self.client.post(url, data=json.dumps(payload), content_type="application/json")
        self.assertEqual(res.status_code, 400)
        body = res.json()
        self.assertFalse(body.get("ok"))
        self.assertTrue(any("camp no perm" in e for e in body.get("errors", [])))

    def test_classificacio_save_rejects_duplicate_custom_partition_values(self):
        payload = {
            "nom": "Cfg particio custom duplicada",
            "activa": True,
            "ordre": 1,
            "tipus": "individual",
            "schema": self._valid_partition_schema(),
        }
        payload["schema"]["particions"] = ["categoria"]
        payload["schema"]["particions_custom"] = {
            "categoria": {
                "mode": "custom",
                "grups": [
                    {"label": "Bloc 1", "values": ["ALEVI"]},
                    {"label": "Bloc 2", "values": ["ALEVI"]},
                ],
            }
        }

        url = reverse("classificacio_save", kwargs={"pk": self.comp.id})
        res = self.client.post(url, data=json.dumps(payload), content_type="application/json")
        self.assertEqual(res.status_code, 400)
        body = res.json()
        self.assertFalse(body.get("ok"))
        self.assertTrue(any("valor repetit entre grups" in e for e in body.get("errors", [])))
