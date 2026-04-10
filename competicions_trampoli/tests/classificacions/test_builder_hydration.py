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


class ClassificacioBuilderHydrationTests(_BaseTrampoliDataMixin, TestCase):
    def setUp(self):
        self.comp = self._create_competicio("Comp Builder Hydration")
        self.user = self._login_competicio_user(
            self.comp,
            role=CompeticioMembership.Role.EDITOR,
            username_prefix="builder_hydration",
        )
        self.native_ctx = self._ensure_native_equip_context(self.comp)
        self.ctx_finals = EquipContext.objects.create(competicio=self.comp, code="ctx-finals", nom="Finals")
        self.ctx_alt = EquipContext.objects.create(competicio=self.comp, code="ctx-alt", nom="Alt")

        self.ind_app = self._create_aparell("BH_IND", "Builder Hydration Individual")
        self.comp_ind_app = self._create_comp_aparell(self.comp, self.ind_app, ordre=1, actiu=True)

        self.team_app_finals = self._create_aparell("BH_TEAM_F", "Builder Hydration Team Finals")
        self.team_app_finals.competition_unit = Aparell.CompetitionUnit.TEAM
        self.team_app_finals.save(update_fields=["competition_unit"])
        self.comp_team_app_finals = self._create_comp_aparell(self.comp, self.team_app_finals, ordre=2, actiu=True)

        self.team_app_alt = self._create_aparell("BH_TEAM_A", "Builder Hydration Team Alt")
        self.team_app_alt.competition_unit = Aparell.CompetitionUnit.TEAM
        self.team_app_alt.save(update_fields=["competition_unit"])
        self.comp_team_app_alt = self._create_comp_aparell(self.comp, self.team_app_alt, ordre=3, actiu=True)

        CompeticioAparellEquipContextSource.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_team_app_finals,
            context=self.ctx_finals,
        )
        CompeticioAparellEquipContextSource.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_team_app_alt,
            context=self.ctx_alt,
        )

    def _builder_schema(self, *, context_code="native", team_mode=""):
        return {
            "particions": [],
            "particions_v2": [],
            "particions_custom": {},
            "particions_config": {},
            "filtres": {},
            "puntuacio": {
                "aparells": {"mode": "tots", "ids": []},
                "camps_per_aparell": {},
                "agregacio_camps": "sum",
                "exercicis": {"mode": "tots"},
                "agregacio_exercicis": "sum",
                "agregacio_aparells": "sum",
                "mode_resultat_aparells": "score",
                "victories": {
                    "punts_victoria": 1,
                    "punts_empat": 0.5,
                    "sense_nota_mode": "skip",
                    "mode_camps": "agregat",
                    "mode_exercicis": "agregat",
                    "mode_seleccio_exercicis_camps_separats": "per_camp",
                    "agregacio_victories_camps": "sum",
                    "agregacio_victories_exercicis": "sum",
                    "desempat_comparacio": [],
                },
                "ordre": "desc",
            },
            "desempat": [],
            "presentacio": {
                "top_n": 0,
                "mostrar_empats": True,
                "columnes": [{"type": "builtin", "key": "participant", "label": "Participant", "align": "left"}],
            },
            "equips": {
                "context_code": context_code,
                "assignment_source": {"mode": "context", "context_code": context_code, "fallback": "native"},
                "team_mode": team_mode,
            },
        }

    def test_prepare_schema_for_builder_hydration_mode_tots_filters_individual_tipus(self):
        hydrated = prepare_schema_for_builder_hydration(
            self.comp,
            self._builder_schema(),
            tipus="individual",
        )

        self.assertEqual((hydrated.get("puntuacio") or {}).get("aparells", {}).get("ids"), [self.comp_ind_app.id])

    def test_prepare_schema_for_builder_hydration_mode_tots_filters_derived_team_tipus(self):
        hydrated = prepare_schema_for_builder_hydration(
            self.comp,
            self._builder_schema(context_code="ctx-finals", team_mode="derived_from_individual"),
            tipus="equips",
        )

        self.assertEqual((hydrated.get("puntuacio") or {}).get("aparells", {}).get("ids"), [self.comp_ind_app.id])

    def test_prepare_schema_for_builder_hydration_mode_tots_filters_native_team_by_context(self):
        hydrated = prepare_schema_for_builder_hydration(
            self.comp,
            self._builder_schema(context_code="ctx-finals", team_mode="native_team"),
            tipus="equips",
        )

        self.assertEqual(
            (hydrated.get("puntuacio") or {}).get("aparells", {}).get("ids"),
            [self.comp_team_app_finals.id],
        )

    def test_prepare_schema_for_builder_hydration_prefers_assignment_source_context_code(self):
        schema = self._builder_schema(context_code="native", team_mode="derived_from_individual")
        schema["equips"]["assignment_source"] = {"mode": "context", "context_code": "ctx-finals", "fallback": "native"}

        hydrated = prepare_schema_for_builder_hydration(
            self.comp,
            schema,
            tipus="equips",
        )

        self.assertEqual((hydrated.get("equips") or {}).get("context_code"), "ctx-finals")
        self.assertEqual(
            (((hydrated.get("equips") or {}).get("assignment_source")) or {}).get("context_code"),
            "ctx-finals",
        )

    def test_prepare_schema_for_builder_hydration_preserves_candidate_source_contract(self):
        schema = self._builder_schema(context_code="ctx-finals", team_mode="derived_from_individual")
        schema["puntuacio"]["candidate_source_mode"] = "participant_aggregate"
        schema["puntuacio"]["candidate_source_cfg"] = {
            "mode": "millor_n",
            "best_n": 1,
            "index": 1,
            "ids": [],
            "agregacio_exercicis": "sum",
        }

        hydrated = prepare_schema_for_builder_hydration(
            self.comp,
            schema,
            tipus="equips",
        )

        punt = hydrated.get("puntuacio") or {}
        self.assertEqual(punt.get("candidate_source_mode"), "participant_aggregate")
        self.assertEqual((punt.get("candidate_source_cfg") or {}).get("mode"), "millor_n")
        self.assertEqual((punt.get("candidate_source_cfg") or {}).get("best_n"), 1)

    def test_prepare_schema_for_builder_hydration_preserves_native_team_candidate_source_contract(self):
        schema = self._builder_schema(context_code="ctx-finals", team_mode="native_team")
        schema["puntuacio"]["candidate_source_mode"] = "team_aggregate"
        schema["puntuacio"]["candidate_source_cfg"] = {
            "mode": "millor_n",
            "best_n": 2,
            "index": 1,
            "ids": [],
            "agregacio_exercicis": "sum",
        }
        schema["puntuacio"]["candidate_source_per_aparell"] = {
            str(self.comp_team_app_finals.id): {
                "mode": "team_aggregate",
                "cfg": {
                    "mode": "index",
                    "index": 2,
                    "best_n": 1,
                    "ids": [],
                    "agregacio_exercicis": "max",
                },
            },
        }

        hydrated = prepare_schema_for_builder_hydration(
            self.comp,
            schema,
            tipus="equips",
        )

        punt = hydrated.get("puntuacio") or {}
        self.assertEqual(punt.get("candidate_source_mode"), "team_aggregate")
        self.assertEqual((punt.get("candidate_source_cfg") or {}).get("mode"), "millor_n")
        self.assertEqual((punt.get("candidate_source_cfg") or {}).get("best_n"), 2)
        per_app = punt.get("candidate_source_per_aparell") or {}
        self.assertEqual((per_app.get(str(self.comp_team_app_finals.id)) or {}).get("mode"), "team_aggregate")
        self.assertEqual((((per_app.get(str(self.comp_team_app_finals.id)) or {}).get("cfg")) or {}).get("mode"), "index")
        self.assertEqual((((per_app.get(str(self.comp_team_app_finals.id)) or {}).get("cfg")) or {}).get("index"), 2)

