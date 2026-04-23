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


class ClassificacioTemplateFlowTests(_BaseTrampoliDataMixin, TestCase):
    def setUp(self):
        self.comp_source = self._create_competicio("Comp Templates Source")
        self.comp_target = self._create_competicio("Comp Templates Target")

        self.app = self._create_aparell("TPL_APP", "Template App")
        self.source_app = self._create_comp_aparell(self.comp_source, self.app, ordre=1, actiu=True)
        self.target_app = self._create_comp_aparell(self.comp_target, self.app, ordre=1, actiu=True)

        ScoringSchema.objects.create(
            aparell=self.app,
            schema={
                "fields": [
                    {"code": "E_total", "type": "number"},
                ],
                "computed": [],
            },
        )

        self.cfg_source = ClassificacioConfig.objects.create(
            competicio=self.comp_source,
            nom="Cfg Source",
            activa=True,
            ordre=1,
            tipus="individual",
            schema={
                "particions": ["categoria"],
                "filtres": {},
                "puntuacio": {
                    "aparells": {"mode": "seleccionar", "ids": [self.source_app.id]},
                    "camps_per_aparell": {str(self.source_app.id): ["E_total"]},
                    "agregacio_camps": "sum",
                    "exercicis": {"mode": "tots"},
                    "exercicis_best_n": 1,
                    "mode_seleccio_exercicis": "per_aparell_global",
                    "exercicis_per_aparell": {},
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
                        {"type": "builtin", "key": "posicio", "label": "#", "align": "left"},
                        {"type": "builtin", "key": "participant", "label": "Nom", "align": "left"},
                        {"type": "builtin", "key": "punts", "label": "Punts", "align": "right", "decimals": 3},
                    ],
                },
            },
        )

        User = get_user_model()
        self.editor_user = User.objects.create_user(
            username="tpl_editor_user",
            password="testpass123",
            email="tpl-editor@example.com",
        )
        self.other_user = User.objects.create_user(
            username="tpl_other_user",
            password="testpass123",
            email="tpl-other@example.com",
        )

        CompeticioMembership.objects.create(
            user=self.editor_user,
            competicio=self.comp_source,
            role=CompeticioMembership.Role.EDITOR,
            is_active=True,
        )
        CompeticioMembership.objects.create(
            user=self.editor_user,
            competicio=self.comp_target,
            role=CompeticioMembership.Role.EDITOR,
            is_active=True,
        )
        CompeticioMembership.objects.create(
            user=self.other_user,
            competicio=self.comp_source,
            role=CompeticioMembership.Role.EDITOR,
            is_active=True,
        )
        CompeticioMembership.objects.create(
            user=self.other_user,
            competicio=self.comp_target,
            role=CompeticioMembership.Role.EDITOR,
            is_active=True,
        )

    def _post_json_as(self, user, url_name, comp_id, payload):
        self.client.force_login(user)
        url = reverse(url_name, kwargs={"pk": comp_id})
        return self.client.post(url, data=json.dumps(payload), content_type="application/json")

    def test_editor_with_classificacions_edit_can_save_global_template(self):
        res = self._post_json_as(
            self.editor_user,
            "classificacio_template_save",
            self.comp_source.id,
            {"cfg_id": self.cfg_source.id, "nom": "TPL 1"},
        )
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json().get("ok"))

    def test_template_schema_helpers_preserve_victories_config(self):
        schema = json.loads(json.dumps(self.cfg_source.schema or {}))
        schema["equips"] = {
            "context_code": "native",
            "assignment_source": {"mode": "context", "context_code": "native", "fallback": "native"},
            "team_mode": "derived_from_individual",
        }
        schema["puntuacio"]["mode_resultat_aparells"] = "victories"
        schema["puntuacio"]["victories"] = {
            "punts_victoria": 1,
            "punts_empat": 0,
            "sense_nota_mode": "skip",
            "mode_camps": "separat",
            "mode_exercicis": "separat",
            "mode_seleccio_exercicis_camps_separats": "global",
            "agregacio_victories_camps": "avg",
            "agregacio_victories_exercicis": "max",
            "desempat_comparacio": [
                {
                    "camp": "E_total",
                    "camps": ["E_total"],
                    "agregacio_camps": "hereta",
                    "ordre": "desc",
                    "scope": {"exercicis": {"mode": "hereta"}},
                }
            ],
        }

        schema_tpl, warnings = _schema_to_template_schema(self.comp_source, schema)
        self.assertFalse(warnings)
        self.assertEqual(
            ((schema_tpl.get("puntuacio") or {}).get("mode_resultat_aparells")),
            "victories",
        )

        self._ensure_native_equip_context(self.comp_target)
        schema_local, mapping_warnings, mapping = _template_schema_to_competicio_schema(self.comp_target, schema_tpl)
        self.assertFalse(mapping_warnings)
        self.assertEqual(mapping.get(self.app.codi), self.target_app.id)
        punt = (schema_local.get("puntuacio") or {})
        self.assertEqual(punt.get("mode_resultat_aparells"), "victories")
        self.assertEqual((punt.get("aparells") or {}).get("ids"), [self.target_app.id])
        self.assertEqual((punt.get("victories") or {}).get("mode_camps"), "separat")
        self.assertEqual((punt.get("victories") or {}).get("mode_exercicis"), "separat")
        self.assertEqual(
            (punt.get("victories") or {}).get("mode_seleccio_exercicis_camps_separats"),
            "global",
        )

    def test_template_schema_helpers_roundtrip_per_app_exercise_aggregation_maps(self):
        schema = json.loads(json.dumps(self.cfg_source.schema or {}))
        schema["puntuacio"]["aparells"] = {"mode": "seleccionar", "ids": [self.source_app.id]}
        schema["puntuacio"]["camps_per_aparell"] = {str(self.source_app.id): ["E_total"]}
        schema["puntuacio"]["mode_seleccio_exercicis"] = "per_aparell_override"
        schema["puntuacio"]["exercicis_per_aparell"] = {str(self.source_app.id): {"mode": "millor_1"}}
        schema["puntuacio"]["agregacio_exercicis_per_aparell"] = {str(self.source_app.id): "max"}
        schema["desempat"] = [
            {
                "camps": ["E_total"],
                "agregacio_camps": "hereta",
                "ordre": "desc",
                "mode_seleccio_exercicis": "per_aparell_override",
                "exercicis_per_aparell": {str(self.source_app.id): {"mode": "millor_1"}},
                "agregacio_exercicis_per_aparell": {str(self.source_app.id): "max"},
                "scope": {"aparells": {"mode": "seleccionar", "ids": [self.source_app.id]}},
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
                    "camps": ["E_total"],
                    "agregacio_camps": "hereta",
                    "ordre": "desc",
                    "mode_seleccio_exercicis": "per_aparell_override",
                    "exercicis_per_aparell": {str(self.source_app.id): {"mode": "millor_1"}},
                    "agregacio_exercicis_per_aparell": {str(self.source_app.id): "max"},
                    "scope": {"exercicis": {"mode": "tots"}},
                }
            ],
        }

        schema_tpl, warnings = _schema_to_template_schema(self.comp_source, schema)
        self.assertEqual(
            warnings,
            ["equips.assignment_source.mode='native' detectat; es normalitza al context Base."],
        )
        punt_tpl = schema_tpl.get("puntuacio") or {}
        self.assertEqual(
            punt_tpl.get("agregacio_exercicis_per_aparell"),
            {self.app.codi: "max"},
        )

        self._ensure_native_equip_context(self.comp_target)
        schema_local, mapping_warnings, mapping = _template_schema_to_competicio_schema(self.comp_target, schema_tpl)
        self.assertFalse(mapping_warnings)
        self.assertEqual(mapping.get(self.app.codi), self.target_app.id)
        punt_local = schema_local.get("puntuacio") or {}
        self.assertEqual(
            punt_local.get("agregacio_exercicis_per_aparell"),
            {str(self.target_app.id): "max"},
        )
        tie_local = (schema_local.get("desempat") or [])[0] or {}
        self.assertEqual(
            tie_local.get("agregacio_exercicis_per_aparell"),
            {str(self.target_app.id): "max"},
        )
        victory_tie_local = ((((punt_local.get("victories") or {}).get("desempat_comparacio")) or [])[0] or {})
        self.assertEqual(
            victory_tie_local.get("agregacio_exercicis_per_aparell"),
            {str(self.target_app.id): "max"},
        )
        self.assertEqual(
            ((((punt_local.get("victories") or {}).get("desempat_comparacio")) or [])[0] or {}).get("camps"),
            ["E_total"],
        )

    def test_template_schema_helpers_roundtrip_per_exercise_scoring_field_maps_and_prune_extra_exercises(self):
        self.source_app.nombre_exercicis = 2
        self.source_app.save(update_fields=["nombre_exercicis"])
        self.target_app.nombre_exercicis = 1
        self.target_app.save(update_fields=["nombre_exercicis"])

        schema = json.loads(json.dumps(self.cfg_source.schema or {}))
        schema["puntuacio"]["aparells"] = {"mode": "seleccionar", "ids": [self.source_app.id]}
        schema["puntuacio"]["camps_per_aparell"] = {str(self.source_app.id): ["E_total"]}
        schema["puntuacio"]["agregacio_camps_per_aparell"] = {str(self.source_app.id): "sum"}
        schema["puntuacio"]["camps_mode_per_aparell"] = {str(self.source_app.id): "per_exercici"}
        schema["puntuacio"]["camps_per_exercici_per_aparell"] = {
            str(self.source_app.id): {
                "1": ["E_total"],
                "2": ["E_total"],
            }
        }
        schema["puntuacio"]["agregacio_camps_per_exercici_per_aparell"] = {
            str(self.source_app.id): {
                "1": "sum",
                "2": "avg",
            }
        }

        schema_tpl, warnings = _schema_to_template_schema(self.comp_source, schema)
        self.assertFalse(
            [warning for warning in warnings if "assignment_source.mode='native'" not in warning]
        )
        punt_tpl = schema_tpl.get("puntuacio") or {}
        self.assertEqual(
            punt_tpl.get("camps_mode_per_aparell"),
            {self.app.codi: "per_exercici"},
        )
        self.assertEqual(
            punt_tpl.get("camps_per_exercici_per_aparell"),
            {self.app.codi: {"1": ["E_total"], "2": ["E_total"]}},
        )
        self.assertEqual(
            punt_tpl.get("agregacio_camps_per_exercici_per_aparell"),
            {self.app.codi: {"1": "sum", "2": "avg"}},
        )

        schema_local, mapping_warnings, mapping = _template_schema_to_competicio_schema(self.comp_target, schema_tpl)
        self.assertFalse(
            [warning for warning in mapping_warnings if "equips.context_code 'native'" not in warning]
        )
        self.assertEqual(mapping.get(self.app.codi), self.target_app.id)
        punt_local = schema_local.get("puntuacio") or {}
        self.assertEqual(
            punt_local.get("camps_mode_per_aparell"),
            {str(self.target_app.id): "per_exercici"},
        )
        self.assertEqual(
            punt_local.get("camps_per_exercici_per_aparell"),
            {str(self.target_app.id): {"1": ["E_total"]}},
        )
        self.assertEqual(
            punt_local.get("agregacio_camps_per_exercici_per_aparell"),
            {str(self.target_app.id): {"1": "sum"}},
        )

    def test_template_schema_helpers_roundtrip_tie_pipeline_input_source(self):
        schema = json.loads(json.dumps(self.cfg_source.schema or {}))
        schema["puntuacio"]["aparells"] = {"mode": "seleccionar", "ids": [self.source_app.id]}
        schema["puntuacio"]["camps_per_aparell"] = {str(self.source_app.id): ["E_total"]}
        schema["desempat"] = [
            {
                "id": "tie_input_source",
                "nom": "Desempat contributors",
                "ordre": "desc",
                "pipeline_version": 1,
                "pipeline": {
                    "aparells": {"mode": "seleccionar", "ids": [self.source_app.id]},
                    "camps_per_aparell": {str(self.source_app.id): ["E_total"]},
                    "agregacio_camps_per_aparell": {str(self.source_app.id): "sum"},
                    "agregacio_camps": "sum",
                    "candidate_source_mode": "raw_exercise",
                    "candidate_source_cfg": {"mode": "tots", "agregacio_exercicis": "sum"},
                    "candidate_source_per_aparell": {
                        str(self.source_app.id): {"mode": "raw_exercise"}
                    },
                    "exercicis": {"mode": "tots"},
                    "mode_seleccio_exercicis": "per_aparell_global",
                    "agregacio_exercicis": "sum",
                    "agregacio_aparells": "sum",
                    "mode_resultat_aparells": "score",
                    "input_source": {"mode": "main_selected_contributors"},
                    "ordre": "desc",
                },
            }
        ]

        schema_tpl, warnings = _schema_to_template_schema(self.comp_source, schema)
        self.assertFalse(
            [warning for warning in warnings if "assignment_source.mode='native'" not in warning]
        )
        tie_tpl = (schema_tpl.get("desempat") or [])[0] or {}
        self.assertEqual(
            (((tie_tpl.get("pipeline") or {}).get("input_source")) or {}).get("mode"),
            "main_selected_contributors",
        )

        self._ensure_native_equip_context(self.comp_target)
        schema_local, mapping_warnings, mapping = _template_schema_to_competicio_schema(self.comp_target, schema_tpl)
        self.assertFalse(mapping_warnings)
        self.assertEqual(mapping.get(self.app.codi), self.target_app.id)
        tie_local = (schema_local.get("desempat") or [])[0] or {}
        self.assertEqual(
            (((tie_local.get("pipeline") or {}).get("input_source")) or {}).get("mode"),
            "main_selected_contributors",
        )

    def test_template_schema_helpers_roundtrip_member_selection_step(self):
        schema = json.loads(json.dumps(self.cfg_source.schema or {}))
        schema["equips"] = {
            "context_code": "native",
            "assignment_source": {"mode": "context", "context_code": "native", "fallback": "native"},
            "team_mode": "derived_from_individual",
        }
        schema["puntuacio"]["exercise_selection_scope"] = "per_member"
        schema["puntuacio"]["participants_per_aparell"] = {str(self.source_app.id): {"mode": "millor_1"}}
        schema["puntuacio"]["agregacio_participants_per_aparell"] = {str(self.source_app.id): "avg"}

        schema_tpl, warnings = _schema_to_template_schema(self.comp_source, schema)
        self.assertFalse(warnings)
        punt_tpl = schema_tpl.get("puntuacio") or {}
        self.assertEqual(
            punt_tpl.get("participants_per_aparell"),
            {self.app.codi: {"mode": "millor_1"}},
        )
        self.assertEqual(
            punt_tpl.get("agregacio_participants_per_aparell"),
            {self.app.codi: "avg"},
        )

        self._ensure_native_equip_context(self.comp_target)
        schema_local, mapping_warnings, mapping = _template_schema_to_competicio_schema(self.comp_target, schema_tpl)
        self.assertFalse(mapping_warnings)
        self.assertEqual(mapping.get(self.app.codi), self.target_app.id)
        punt_local = schema_local.get("puntuacio") or {}
        self.assertEqual(
            punt_local.get("participants_per_aparell"),
            {str(self.target_app.id): {"mode": "millor_1"}},
        )
        self.assertEqual(
            punt_local.get("agregacio_participants_per_aparell"),
            {str(self.target_app.id): "avg"},
        )

    def test_template_schema_helpers_roundtrip_presentacio_detall_columns(self):
        schema = {
            "puntuacio": {
                "aparells": {"mode": "seleccionar", "ids": [self.source_app.id]},
                "camps_per_aparell": {str(self.source_app.id): ["E_total"]},
                "agregacio_camps": "sum",
                "exercicis": {"mode": "tots"},
                "agregacio_exercicis": "sum",
                "agregacio_aparells": "sum",
                "ordre": "desc",
            },
            "equips": {
                "context_code": "ctx-finals",
                "assignment_source": {"mode": "context", "context_code": "ctx-finals", "fallback": "native"},
                "team_mode": "derived_from_individual",
            },
            "presentacio": {
                "columnes": [
                    {"type": "builtin", "key": "participant", "label": "Nom", "align": "left"},
                ],
                "detall": {
                    "enabled": True,
                    "default_open": True,
                    "sections": [
                        {
                            "type": "members_table",
                            "label": "Detall",
                            "columns": [
                                {"type": "builtin", "key": "participant", "label": "Participant", "align": "left"},
                                {
                                    "type": "raw",
                                    "key": "detail_exec",
                                    "label": "Execucio",
                                    "align": "right",
                                    "decimals": 3,
                                    "source": {
                                        "aparell_id": self.source_app.id,
                                        "exercici": 1,
                                        "camp": "E_total",
                                        "jutges": {"ids": []},
                                    },
                                },
                            ],
                        }
                    ],
                },
            },
        }

        schema_tpl, warnings = _schema_to_template_schema(self.comp_source, schema)
        self.assertFalse(warnings)
        detail_section_tpl = (((((schema_tpl.get("presentacio") or {}).get("detall") or {}).get("sections")) or [])[0] or {})
        detail_tpl = detail_section_tpl.get("columns") or []
        self.assertEqual(detail_tpl[1]["source"]["aparell_codi"], self.app.codi)

        EquipContext.objects.create(competicio=self.comp_target, code="ctx-finals", nom="Finals")
        schema_local, mapping_warnings, mapping = _template_schema_to_competicio_schema(self.comp_target, schema_tpl)
        self.assertFalse(mapping_warnings)
        self.assertEqual(mapping.get(self.app.codi), self.target_app.id)
        detail_section_local = (((((schema_local.get("presentacio") or {}).get("detall") or {}).get("sections")) or [])[0] or {})
        detail_local = detail_section_local.get("columns") or []
        self.assertEqual(detail_local[1]["source"]["aparell_id"], self.target_app.id)

    def test_template_schema_helpers_keep_assignment_source_context_authoritative(self):
        self._ensure_native_equip_context(self.comp_source)
        self._ensure_native_equip_context(self.comp_target)
        EquipContext.objects.create(competicio=self.comp_source, code="ctx-finals", nom="Finals")
        EquipContext.objects.create(competicio=self.comp_target, code="ctx-finals", nom="Finals")

        schema = {
            "puntuacio": {
                "aparells": {"mode": "seleccionar", "ids": [self.source_app.id]},
                "camps_per_aparell": {str(self.source_app.id): ["E_total"]},
                "agregacio_camps": "sum",
                "exercicis": {"mode": "tots"},
                "agregacio_exercicis": "sum",
                "agregacio_aparells": "sum",
                "ordre": "desc",
            },
            "equips": {
                "context_code": "native",
                "assignment_source": {"mode": "context", "context_code": "ctx-finals", "fallback": "native"},
                "team_mode": "derived_from_individual",
            },
        }

        schema_tpl, warnings = _schema_to_template_schema(self.comp_source, schema)
        self.assertFalse(warnings)
        self.assertEqual((schema_tpl.get("equips") or {}).get("context_code"), "ctx-finals")
        self.assertEqual(
            (((schema_tpl.get("equips") or {}).get("assignment_source")) or {}).get("context_code"),
            "ctx-finals",
        )

        schema_local, mapping_warnings, _mapping = _template_schema_to_competicio_schema(self.comp_target, schema_tpl)
        self.assertFalse(mapping_warnings)
        self.assertEqual((schema_local.get("equips") or {}).get("context_code"), "ctx-finals")
        self.assertEqual(
            (((schema_local.get("equips") or {}).get("assignment_source")) or {}).get("context_code"),
            "ctx-finals",
        )

    def test_global_template_can_be_saved_validated_and_applied(self):
        save_res = self._post_json_as(
            self.editor_user,
            "classificacio_template_save",
            self.comp_source.id,
            {"cfg_id": self.cfg_source.id, "nom": "TPL Rapid"},
        )
        self.assertEqual(save_res.status_code, 200)
        save_body = save_res.json()
        self.assertTrue(save_body.get("ok"))
        template_id = save_body.get("template", {}).get("id")
        self.assertTrue(template_id)

        tpl = ClassificacioTemplateGlobal.objects.get(pk=template_id)
        tpl_schema = (tpl.payload or {}).get("schema") or {}
        self.assertEqual(
            ((tpl_schema.get("puntuacio") or {}).get("aparells") or {}).get("ids"),
            [self.app.codi],
        )

        validate_res = self._post_json_as(
            self.editor_user,
            "classificacio_template_validate",
            self.comp_target.id,
            {"template_id": template_id},
        )
        self.assertEqual(validate_res.status_code, 200)
        validate_body = validate_res.json()
        self.assertTrue(validate_body.get("compatible"))

        apply_res = self._post_json_as(
            self.editor_user,
            "classificacio_template_apply",
            self.comp_target.id,
            {"template_id": template_id, "nom": "Aplicada Target", "activa": False},
        )
        self.assertEqual(apply_res.status_code, 200)
        apply_body = apply_res.json()
        self.assertTrue(apply_body.get("ok"))
        cfg = apply_body.get("cfg") or {}
        self.assertEqual(cfg.get("nom"), "Aplicada Target")

        punt = ((cfg.get("schema") or {}).get("puntuacio") or {})
        self.assertEqual((punt.get("aparells") or {}).get("ids"), [self.target_app.id])
        self.assertEqual((punt.get("camps_per_aparell") or {}).get(str(self.target_app.id)), ["E_total"])

        tpl.refresh_from_db()
        self.assertEqual(tpl.uses_count, 1)
        self.assertIsNotNone(tpl.last_used_at)

    def test_template_apply_requires_ack_for_non_strict_fallback(self):
        save_res = self._post_json_as(
            self.editor_user,
            "classificacio_template_save",
            self.comp_source.id,
            {"cfg_id": self.cfg_source.id, "nom": "TPL Ack"},
        )
        self.assertEqual(save_res.status_code, 200)
        template_id = save_res.json().get("template", {}).get("id")
        self.assertTrue(template_id)

        res = self._post_json_as(
            self.editor_user,
            "classificacio_template_apply",
            self.comp_target.id,
            {
                "template_id": template_id,
                "nom": "Aplicada sense ack",
                "activa": False,
                "fallback_mode": "assistit",
            },
        )
        self.assertEqual(res.status_code, 400)
        body = res.json()
        self.assertFalse(body.get("ok"))
        self.assertEqual(body.get("phase"), "assistit")
        self.assertIn("confirmar", str(body.get("error", "")).lower())

    def test_template_apply_fallback_chain_strict_assistit_force(self):
        save_res = self._post_json_as(
            self.editor_user,
            "classificacio_template_save",
            self.comp_source.id,
            {"cfg_id": self.cfg_source.id, "nom": "TPL Fallback Chain"},
        )
        self.assertEqual(save_res.status_code, 200)
        template_id = save_res.json().get("template", {}).get("id")
        self.assertTrue(template_id)

        tpl = ClassificacioTemplateGlobal.objects.get(pk=template_id)
        payload = json.loads(json.dumps(tpl.payload or {}))
        schema = payload.get("schema") or {}
        schema["particions"] = ["categoria"]
        schema["particions_custom"] = {
            "categoria": {
                "mode": "custom",
                "grups": [
                    {"label": "Bloc 1", "values": ["ALEVI"]},
                    {"label": "Bloc 2", "values": ["ALEVI"]},
                ],
            }
        }
        payload["schema"] = schema
        tpl.payload = payload
        tpl.save(update_fields=["payload", "updated_at"])

        strict_res = self._post_json_as(
            self.editor_user,
            "classificacio_template_apply",
            self.comp_target.id,
            {
                "template_id": template_id,
                "nom": "Aplicada strict",
                "activa": False,
                "fallback_mode": "strict",
            },
        )
        self.assertEqual(strict_res.status_code, 400)
        strict_body = strict_res.json()
        self.assertFalse(strict_body.get("compatible"))
        self.assertEqual(strict_body.get("phase"), "strict")
        self.assertEqual(strict_body.get("next_fallback"), "assistit")
        self.assertTrue(strict_body.get("can_try_next"))

        assistit_res = self._post_json_as(
            self.editor_user,
            "classificacio_template_apply",
            self.comp_target.id,
            {
                "template_id": template_id,
                "nom": "Aplicada assistit",
                "activa": False,
                "fallback_mode": "assistit",
                "ack_warning": True,
            },
        )
        self.assertEqual(assistit_res.status_code, 400)
        assistit_body = assistit_res.json()
        self.assertFalse(assistit_body.get("compatible"))
        self.assertEqual(assistit_body.get("phase"), "assistit")
        self.assertEqual(assistit_body.get("next_fallback"), "force")
        self.assertTrue(assistit_body.get("can_try_next"))

        force_res = self._post_json_as(
            self.editor_user,
            "classificacio_template_apply",
            self.comp_target.id,
            {
                "template_id": template_id,
                "nom": "Aplicada force",
                "activa": False,
                "fallback_mode": "force",
                "ack_warning": True,
            },
        )
        self.assertEqual(force_res.status_code, 200)
        force_body = force_res.json()
        self.assertTrue(force_body.get("ok"))
        cfg = force_body.get("cfg") or {}
        self.assertEqual(cfg.get("nom"), "Aplicada force")
        self.assertEqual(
            (((cfg.get("schema") or {}).get("puntuacio") or {}).get("aparells") or {}).get("ids"),
            [self.target_app.id],
        )
        self.assertEqual(
            (((cfg.get("schema") or {}).get("puntuacio") or {}).get("camps_per_aparell") or {}).get(str(self.target_app.id)),
            ["total"],
        )

    def test_global_template_apply_persists_mode_resolution_for_team_schema(self):
        self._ensure_native_equip_context(self.comp_source)
        self._ensure_native_equip_context(self.comp_target)
        team_cfg = ClassificacioConfig.objects.create(
            competicio=self.comp_source,
            nom="Cfg Source Team",
            activa=True,
            ordre=2,
            tipus="equips",
            schema={
                **json.loads(json.dumps(self.cfg_source.schema or {})),
                "equips": {
                    "context_code": "native",
                    "assignment_source": {"mode": "context", "context_code": "native", "fallback": "native"},
                    "team_mode": "derived_from_individual",
                },
            },
        )

        save_res = self._post_json_as(
            self.editor_user,
            "classificacio_template_save",
            self.comp_source.id,
            {"cfg_id": team_cfg.id, "nom": "TPL Team Mode Resolution"},
        )
        self.assertEqual(save_res.status_code, 200)
        template_id = save_res.json().get("template", {}).get("id")
        self.assertTrue(template_id)

        apply_res = self._post_json_as(
            self.editor_user,
            "classificacio_template_apply",
            self.comp_target.id,
            {"template_id": template_id, "nom": "Aplicada Team", "activa": False},
        )
        self.assertEqual(apply_res.status_code, 200)
        cfg = apply_res.json().get("cfg") or {}
        mode_resolution = (((cfg.get("schema") or {}).get("equips") or {}).get("mode_resolution")) or {}
        self.assertTrue(mode_resolution.get("resolved_at"))
        self.assertIn("eligible_team_app_ids_at_save", mode_resolution)

        saved_cfg = ClassificacioConfig.objects.get(pk=cfg.get("id"))
        self.assertTrue((((saved_cfg.schema.get("equips") or {}).get("mode_resolution")) or {}).get("resolved_at"))

    def test_template_validation_distinguishes_strict_vs_assistit_for_missing_team_context(self):
        schema_tpl, warnings = _schema_to_template_schema(self.comp_source, self.cfg_source.schema or {})
        self.assertEqual(
            warnings,
            ["equips.assignment_source.mode='native' detectat; es normalitza al context Base."],
        )
        schema_tpl["equips"] = {
            "context_code": "ctx-finals",
            "assignment_source": {"mode": "context", "context_code": "ctx-finals", "fallback": "native"},
            "team_mode": "derived_from_individual",
            "particions_manuals": [
                {"key": "manual_1", "label": "Bloc A", "equips_noms": ["Equip Finals"]},
            ],
        }
        tpl = ClassificacioTemplateGlobal.objects.create(
            nom="TPL Missing Context",
            slug="tpl-missing-context",
            tipus="equips",
            activa=True,
            payload={"schema": schema_tpl},
            requirements={},
            created_by=self.editor_user,
        )

        strict_res = self._post_json_as(
            self.editor_user,
            "classificacio_template_validate",
            self.comp_target.id,
            {"template_id": tpl.id, "fallback_mode": "strict"},
        )
        self.assertEqual(strict_res.status_code, 200)
        strict_body = strict_res.json()
        self.assertFalse(strict_body.get("compatible"))
        self.assertTrue(any("equips.context_code no existeix" in err for err in strict_body.get("blocking_errors", [])))
        self.assertTrue(any("Equip Finals" in err for err in strict_body.get("blocking_errors", [])))

        assistit_res = self._post_json_as(
            self.editor_user,
            "classificacio_template_validate",
            self.comp_target.id,
            {"template_id": tpl.id, "fallback_mode": "assistit"},
        )
        self.assertEqual(assistit_res.status_code, 200)
        assistit_body = assistit_res.json()
        self.assertTrue(assistit_body.get("compatible"))
        self.assertTrue(assistit_body.get("portable"))
        self.assertTrue(assistit_body.get("adaptable"))
        self.assertTrue(any("context Base" in msg for msg in assistit_body.get("warnings", [])))
        self.assertTrue(any("Equip Finals" in msg for msg in assistit_body.get("warnings", [])))
        self.assertTrue(any("equips.context_code" in msg for msg in assistit_body.get("dropped_rules", [])))

    def test_template_list_only_shows_owner_templates(self):
        own = self._post_json_as(
            self.editor_user,
            "classificacio_template_save",
            self.comp_source.id,
            {"cfg_id": self.cfg_source.id, "nom": "TPL Owner"},
        )
        self.assertEqual(own.status_code, 200)
        own_id = own.json().get("template", {}).get("id")
        self.assertTrue(own_id)

        foreign = self._post_json_as(
            self.other_user,
            "classificacio_template_save",
            self.comp_source.id,
            {"cfg_id": self.cfg_source.id, "nom": "TPL Foreign"},
        )
        self.assertEqual(foreign.status_code, 200)
        foreign_id = foreign.json().get("template", {}).get("id")
        self.assertTrue(foreign_id)

        self.client.force_login(self.editor_user)
        list_url = reverse("classificacio_template_list", kwargs={"pk": self.comp_source.id})
        res = self.client.get(list_url)
        self.assertEqual(res.status_code, 200)
        ids = {int(t["id"]) for t in (res.json().get("templates") or [])}
        self.assertIn(int(own_id), ids)
        self.assertNotIn(int(foreign_id), ids)

    def test_cannot_use_or_update_foreign_template_by_id(self):
        foreign = self._post_json_as(
            self.other_user,
            "classificacio_template_save",
            self.comp_source.id,
            {"cfg_id": self.cfg_source.id, "nom": "TPL Foreign Locked"},
        )
        self.assertEqual(foreign.status_code, 200)
        foreign_id = foreign.json().get("template", {}).get("id")
        self.assertTrue(foreign_id)

        validate_res = self._post_json_as(
            self.editor_user,
            "classificacio_template_validate",
            self.comp_target.id,
            {"template_id": foreign_id},
        )
        self.assertEqual(validate_res.status_code, 404)

        apply_res = self._post_json_as(
            self.editor_user,
            "classificacio_template_apply",
            self.comp_target.id,
            {"template_id": foreign_id, "nom": "No hauria d'aplicar"},
        )
        self.assertEqual(apply_res.status_code, 404)

        update_res = self._post_json_as(
            self.editor_user,
            "classificacio_template_save",
            self.comp_source.id,
            {"cfg_id": self.cfg_source.id, "template_id": foreign_id, "nom": "No hauria d'editar"},
        )
        self.assertEqual(update_res.status_code, 404)

    def test_classificacions_home_renders_builder_json_contract(self):
        self.client.force_login(self.editor_user)
        url = reverse("classificacions_home", kwargs={"pk": self.comp_source.id})
        res = self.client.get(url)
        content = res.content.decode("utf-8")
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'id="can-manage-global-templates"')
        self.assertContains(res, 'id="builder-save-url"')
        self.assertContains(res, 'id="builder-delete-url-pattern"')
        self.assertContains(res, 'id="builder-preview-url-pattern"')
        self.assertContains(res, 'id="builder-enable-template-library"')
        self.assertContains(res, 'id="builder-can-preview"')
        self.assertContains(res, 'id="victoryConfigBox"')
        self.assertContains(res, 'id="sVictoryModeCamps"')
        self.assertContains(res, 'id="sVictoryModeExercicis"')
        self.assertContains(res, 'id="puntuacioSummaryText"')
        self.assertNotContains(res, 'id="participantSelectionCard"')
        self.assertContains(res, 'data-app-participants-mode')
        self.assertContains(res, 'data-app-agregacio-participants')
        self.assertContains(res, 'class="builder-summary-box__text"')
        self.assertNotContains(res, 'id="exSelectionSummary"')
        self.assertContains(res, 'id="candidateScopeHint"')
        self.assertContains(res, 'id="classifHelpDrawer"')
        self.assertContains(res, 'id="classif-builder-back-to-top"')
        self.assertContains(res, "classificacions_builder_help.css")
        self.assertContains(res, "classificacions_builder_help.js")
        self.assertContains(res, 'data-help-key="global_overview"')
        self.assertContains(res, 'data-help-key="victories_overview"')
        self.assertNotContains(res, '<option value="entitat">Per entitat</option>', html=True)
        self.assertContains(res, 'id="appStaleBanner"')
        self.assertContains(res, "function pruneSchemaAppReferences(schema, allowedIds)")
        self.assertContains(res, "function renderAppStaleWarningBanner(schema, selectedIds)")
        self.assertContains(res, "function filterRawColumnsByAllowedApps(rawCols, allowedIds)")
        self.assertContains(res, "function pruneDetailSectionsByAllowedApps(rawSections, allowedIds)")
        self.assertContains(res, "const selectedCompatibleIds = sanitizeCompatibleAppIds(idsBase);")
        self.assertContains(res, 'buildAparellChecks(selectedCompatibleIds, { includeStale: false });')
        self.assertContains(res, 'const selected = getSingleCompatibleAppId(selectedAppId);')
        self.assertContains(res, '<option value="" ${selected ? "" : "selected"}>Selecciona aparell</option>')
        self.assertContains(res, 'const appIds = sanitizeCompatibleAppIds(getCurrentBuilderAppIds(schema));')
        self.assertContains(res, "renderAppStaleWarningBanner(schema, selectedCompatibleIds);")
        self.assertContains(res, "refreshTipusUI({ includeStale: false, dropInvalidSelection: true });")
        self.assertContains(res, 'function runSafeHydrationRender(label, renderFn)')
        self.assertContains(res, 'runSafeHydrationRender("columnes", () => {')
        self.assertContains(res, 'runSafeHydrationRender("desempat", () => {')
        self.assertContains(res, 'runSafeHydrationRender("per aparell", () => {')
        self.assertContains(res, 'state.rehydrationIssues = [];')
        self.assertContains(res, "function buildTieCanonicalForSaveFromRow(")
        self.assertContains(res, "function readTieBuilderState(")
        self.assertContains(res, "function readTieCanonicalForSave(")
        self.assertContains(res, 'data-k="input_source_mode"')
        self.assertContains(res, "Entrada: contributors de la puntuacio")
        self.assertContains(res, "Criteri i entrada")
        self.assertContains(res, "Flux del conjunt")
        self.assertContains(res, "Membres / pool final")
        self.assertContains(res, "1. Conjunt inicial del desempat")
        self.assertContains(res, "2. Valoracio dels exercicis")
        self.assertContains(res, "3. Base i pretractament")
        self.assertContains(res, "4. Seleccio del conjunt")
        self.assertContains(res, "function isMemberSelectionAggregationAvailable()")
        self.assertContains(res, "function isTeamPoolPerExerciseConfigurationAvailable()")
        self.assertContains(res, "function _getPerAppParticipantsForUi(punt, appId)")
        self.assertContains(res, "function _getPerAppTeamPoolModeForUi(punt, appId)")
        self.assertContains(res, "function _copyPuntuacioParticipantsCfg(rawCfg)")
        self.assertContains(res, "function _buildMemberSelectionSegment(perAppEntries)")
        self.assertContains(res, "function _buildTeamPoolModeSegment(showScope, isTeamPool, perAppEntries)")
        self.assertContains(res, "let desempat = readTieCanonicalForSave(true);")
        self.assertContains(res, "renderTieUI(readTieBuilderState(true));")
        self.assertNotContains(res, "renderTieUI(readTieUI(true));")
        self.assertContains(res, "delete canonical.pipeline.exercicis;")
        self.assertContains(res, "delete canonical.pipeline.exercicis_per_aparell;")
        self.assertContains(res, "delete canonical.pipeline.mode_seleccio_exercicis;")
        self.assertContains(res, "delete canonical.pipeline.participants;")
        self.assertContains(res, "participants_per_aparell")
        self.assertContains(res, "agregacio_participants_per_aparell")
        self.assertContains(res, "team_pool_mode_per_aparell")
        self.assertContains(res, "team_pool_participants_per_exercici_per_aparell")
        self.assertContains(res, "team_pool_agregacio_participants_per_exercici_per_aparell")
        self.assertContains(res, 'data-app-team-pool-mode')
        self.assertContains(res, 'data-app-team-pool-participants-mode')
        self.assertContains(res, 'data-app-team-pool-agregacio-participants')
        self.assertEqual(content.count("function buildTieAppScopeOptionsHTML("), 1)
        self.assertContains(res, "function _buildPretractamentSegment(punt, perAppEntries)")
        self.assertContains(res, "function _buildScoreSelectionSegment({")
        self.assertContains(res, "function _buildVictoriesComparisonSegment(victoriesCfg)")
        self.assertNotContains(res, "function buildPuntuacioLiveSummary({")
        self.assertContains(res, "3a. Mode del pool d'equip")
        self.assertContains(res, "3b. Bosses per exercici")
        self.assertContains(res, "Preseleccio o agregacio previa per membre desactivada en aquest context.")
        self.assertContains(res, "5. Seleccio i agregacio entre membres")
        self.assertContains(res, "5. Combinacio final entre aparells")
        self.assertContains(res, "AgregaciÃ³ camps: Mateixa que puntuaciÃ³")
        self.assertContains(res, "Base: Mateixa que puntuaciÃ³")
        self.assertContains(res, "SelecciÃ³ ex: Mateixa que puntuaciÃ³")
        self.assertContains(res, "Tractament: Mateix que puntuaciÃ³")
        self.assertContains(res, "Mateixos aparells que la puntuaciÃ³")
        self.assertNotContains(res, "Hereta (puntuaciÃ³)")
        self.assertNotContains(res, "Hereta (tots)")
        self.assertContains(res, "function previewRenderTeamRawDetailCell(v, col)")
        self.assertContains(res, "team-raw-summary")
        self.assertContains(res, 'v._kind === "team_raw_detail"')
        self.assertContains(res, 'id="previewBox"')
        self.assertContains(res, "builder-preview-shell")
        self.assertContains(res, 'id="detailConfigAlert"')
        self.assertContains(res, 'id="eqAssignmentContextHint"')
        self.assertContains(res, 'id="saveMsg"')
        self.assertContains(res, "En equips derivats, les columnes de camp mostren un resum i el detall per membres de l'equip.")
        self.assertContains(res, "En equips amb nota nativa, les columnes de camp mostren el valor d'equip i nomÃ©s sÃ³n representables per aparells d'equip.")

    def test_classificacions_home_exposes_contextual_filter_copy_contract(self):
        self.client.force_login(self.editor_user)
        url = reverse("classificacions_home", kwargs={"pk": self.comp_source.id})
        res = self.client.get(url)

        self.assertContains(res, "Entren nomÃ©s els participants que compleixin aquests filtres abans de calcular resultats o mostrar particions.")
        self.assertContains(res, "Primer es filtren participants i desprÃ©s s'agrega el resultat per entitat.")
        self.assertContains(res, "Primer es filtren membres i desprÃ©s es calcula l'equip amb els membres resultants.")
        self.assertContains(res, "Un equip nomÃ©s entra si tots els seus membres compleixen aquests filtres abans de calcular la nota nativa d'equip.")

    def test_classificacions_home_preserves_legacy_field_refs_for_builder_rehydration(self):
        schema = json.loads(json.dumps(self.cfg_source.schema or {}))
        schema["puntuacio"]["camps_per_aparell"] = {
            str(self.source_app.id): ["E_total", "ex"],
        }
        schema["desempat"] = [
            {
                "camp": "ex",
                "camps": ["ex"],
                "agregacio_camps": "hereta",
                "ordre": "desc",
                "scope": {
                    "aparells": {"mode": "hereta"},
                    "exercicis": {"mode": "hereta"},
                },
            },
            {
                "camp": "E_total",
                "camps": ["E_total"],
                "agregacio_camps": "hereta",
                "ordre": "desc",
                "scope": {
                    "aparells": {"mode": "hereta"},
                    "exercicis": {"mode": "hereta"},
                },
            },
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
                    "camp": "ex",
                    "camps": ["ex"],
                    "agregacio_camps": "hereta",
                    "ordre": "desc",
                    "scope": {"exercicis": {"mode": "hereta"}},
                },
                {
                    "camp": "E_total",
                    "camps": ["E_total"],
                    "agregacio_camps": "hereta",
                    "ordre": "desc",
                    "scope": {"exercicis": {"mode": "hereta"}},
                },
            ],
        }
        schema["presentacio"]["columnes"] = [
            {"type": "builtin", "key": "participant", "label": "Nom", "align": "left"},
            {
                "type": "raw",
                "key": "raw_valid",
                "label": "Valid",
                "align": "right",
                "decimals": 3,
                "source": {
                    "aparell_id": self.source_app.id,
                    "exercici": 1,
                    "camp": "E_total",
                    "jutges": {"ids": []},
                },
            },
            {
                "type": "raw",
                "key": "raw_legacy",
                "label": "Legacy",
                "align": "right",
                "decimals": 3,
                "source": {
                    "aparell_id": self.source_app.id,
                    "exercici": 1,
                    "camp": "ex",
                    "jutges": {"ids": []},
                },
            },
        ]
        self.cfg_source.schema = schema
        self.cfg_source.save(update_fields=["schema"])

        self.client.force_login(self.editor_user)
        url = reverse("classificacions_home", kwargs={"pk": self.comp_source.id})
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)

        cfg_payload = next(cfg for cfg in res.context["cfgs"] if cfg["id"] == self.cfg_source.id)
        hydrated = cfg_payload["schema"]
        status = (res.context["cfg_status"] or {}).get(str(self.cfg_source.id)) or {}
        punt = hydrated.get("puntuacio") or {}
        self.assertNotIn("camp", punt)
        self.assertNotIn("agregacio", punt)
        self.assertNotIn("best_n", punt)
        self.assertEqual((punt.get("camps_per_aparell") or {}).get(str(self.source_app.id)), ["E_total", "ex"])

        desempat = hydrated.get("desempat") or []
        self.assertEqual(len(desempat), 2)
        self.assertEqual(desempat[0].get("camps"), ["ex"])
        self.assertEqual(desempat[1].get("camps"), ["E_total"])

        compare = (((punt.get("victories") or {}).get("desempat_comparacio")) or [])
        self.assertEqual(len(compare), 2)
        self.assertEqual(compare[0].get("camps"), ["ex"])
        self.assertEqual(compare[1].get("camps"), ["E_total"])

        raw_columns = [c for c in ((hydrated.get("presentacio") or {}).get("columnes") or []) if c.get("type") == "raw"]
        self.assertEqual(len(raw_columns), 2)
        self.assertEqual({((col.get("source") or {}).get("camp")) for col in raw_columns}, {"E_total", "ex"})

        self.assertTrue(status.get("is_stale"))
        errors = status.get("compatibility_errors") or []
        self.assertTrue(any("puntuacio.camps_per_aparell" in err and "'ex' no existeix" in err for err in errors))
        self.assertTrue(any("desempat[0]" in err and "'ex' no existeix" in err for err in errors))
        self.assertTrue(any("presentacio.columnes" in err and "'ex' no existeix" in err for err in errors))

        self.cfg_source.refresh_from_db()
        original = self.cfg_source.schema or {}
        self.assertEqual((original.get("puntuacio") or {}).get("camps_per_aparell", {}).get(str(self.source_app.id)), ["E_total", "ex"])
        self.assertEqual(len(original.get("desempat") or []), 2)
        self.assertEqual(len((((original.get("puntuacio") or {}).get("victories") or {}).get("desempat_comparacio")) or []), 2)

    def test_classificacions_home_preserves_missing_app_refs_for_builder_rehydration(self):
        schema = json.loads(json.dumps(self.cfg_source.schema or {}))
        missing_app_id = self.source_app.id + 9999
        schema["puntuacio"]["aparells"] = {"mode": "seleccionar", "ids": [self.source_app.id, missing_app_id]}
        schema["puntuacio"]["camps_per_aparell"] = {
            str(self.source_app.id): ["E_total"],
            str(missing_app_id): ["E_total"],
        }
        schema["puntuacio"]["exercicis_per_aparell"] = {
            str(self.source_app.id): {"mode": "tots"},
            str(missing_app_id): {"mode": "tots"},
        }
        schema["desempat"] = [
            {
                "camps": ["E_total"],
                "agregacio_camps": "hereta",
                "ordre": "desc",
                "scope": {"aparells": {"mode": "seleccionar", "ids": [missing_app_id]}},
            }
        ]
        schema["presentacio"]["columnes"] = [
            {"type": "builtin", "key": "participant", "label": "Nom", "align": "left"},
            {
                "type": "raw",
                "key": "raw_missing_app",
                "label": "No App",
                "align": "right",
                "decimals": 3,
                "source": {"aparell_id": missing_app_id, "exercici": 1, "camp": "E_total", "jutges": {"ids": []}},
            },
        ]
        self.cfg_source.schema = schema
        self.cfg_source.save(update_fields=["schema"])

        self.client.force_login(self.editor_user)
        res = self.client.get(reverse("classificacions_home", kwargs={"pk": self.comp_source.id}))
        self.assertEqual(res.status_code, 200)

        cfg_payload = next(cfg for cfg in res.context["cfgs"] if cfg["id"] == self.cfg_source.id)
        hydrated = cfg_payload["schema"]
        status = (res.context["cfg_status"] or {}).get(str(self.cfg_source.id)) or {}
        punt = hydrated.get("puntuacio") or {}
        self.assertEqual((punt.get("aparells") or {}).get("ids"), [self.source_app.id, missing_app_id])
        self.assertEqual(set((punt.get("camps_per_aparell") or {}).keys()), {str(self.source_app.id), str(missing_app_id)})
        self.assertEqual(set((punt.get("exercicis_per_aparell") or {}).keys()), {str(self.source_app.id), str(missing_app_id)})
        self.assertEqual((((hydrated.get("desempat") or [])[0].get("scope") or {}).get("aparells") or {}).get("ids"), [missing_app_id])
        raw_columns = [c for c in ((hydrated.get("presentacio") or {}).get("columnes") or []) if c.get("type") == "raw"]
        self.assertEqual(len(raw_columns), 1)
        self.assertEqual((((raw_columns[0].get("source") or {}).get("aparell_id"))), missing_app_id)

        self.assertTrue(status.get("is_stale"))
        errors = status.get("compatibility_errors") or []
        self.assertTrue(any(f"puntuacio.aparells.ids: l'aparell {missing_app_id} no valid o no actiu." in err for err in errors))
        self.assertTrue(any("puntuacio.camps_per_aparell: aparell" in err and str(missing_app_id) in err for err in errors))
        self.assertTrue(any("presentacio.columnes[1] raw: aparell" in err and str(missing_app_id) in err for err in errors))

