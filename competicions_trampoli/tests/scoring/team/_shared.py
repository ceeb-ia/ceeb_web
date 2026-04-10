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

from .... import live_cache
from ....access import user_has_competicio_capability
from ....forms import CompeticioAparellForm
from ....models import (
    Competicio,
    Equip,
    EquipContext,
    GrupCompeticio,
    Inscripcio,
    InscripcioEquipAssignacio,
    InscripcioMedia,
)
from ....models.judging import (
    JudgeConversation,
    JudgeConversationMessage,
    JudgeDeviceToken,
    PublicLiveToken,
)
from ....models.classificacions import ClassificacioConfig, ClassificacioTemplateGlobal
from ....models.rotacions import (
    RotacioAssignacio,
    RotacioAssignacioGrup,
    RotacioAssignacioSerieEquip,
    RotacioEstacio,
    RotacioFranja,
)
from ....models.scoring import (
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
from ....models.competicio import (
    Aparell,
    CompeticioAparell,
    CompeticioAparellEquipContextSource,
    InscripcioAparellExclusio,
)
from ....models import CompeticioMembership
from ....scoring_engine import ScoringEngine
from ....services.inscripcions.groups import renumber_groups_for_competicio
from ....services.inscripcions.sorting import (
    _split_custom_sort_tokens,
    sort_records_by_field_stable,
)
from ....services.inscripcions.history import (
    apply_inscripcions_history_snapshot,
    capture_inscripcions_history_snapshot,
)
from ....services.inscripcions.queries import (
    COLUMN_FILTER_EMPTY_TOKEN,
    _build_inscripcions_filtered_qs,
    build_inscripcions_sort_context_key,
    get_competicio_custom_sort_rank_map,
)
from ....services.classificacions.classificacio_templates import (
    normalize_particions_schema as _normalize_particions_schema,
    schema_to_template_schema as _schema_to_template_schema,
    template_schema_to_competicio_schema as _template_schema_to_competicio_schema_service,
)
from ....services.classificacions.builder import scoreable_codes_by_app_id as _scoreable_codes_by_app_id
from ....services.classificacions.compute import DEFAULT_SCHEMA, compute_classificacio
from ....services.classificacions.export import _normalize_excel_cell
from ....services.classificacions.partitions import normalize_schema_legacy_team_birth_partition
from ....services.classificacions.runtime import prepare_schema_for_persistence
from ....services.classificacions.validation import (
    build_metric_meta_for_comp_aparell as _build_metric_meta_for_comp_aparell,
    build_scoreable_meta_for_schema as _build_scoreable_meta_for_schema,
    validate_particions_schema as _validate_particions_schema,
    validate_schema_for_competicio as _validate_schema_for_competicio,
)
from ....views.classificacions.builder import ClassificacionsHome
from ....services.shared.competition_groups import (
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
from ....services.scoring.schema_resolution import resolve_scoring_schema_for_comp_aparell
from ....services.scoring.team_scoring import (
    build_permission_label,
    build_team_subjects_for_comp_aparell,
    resolve_permission_runtime_entries,
    runtime_schema_for_comp_aparell,
)
from ....services.teams.team_series import safe_deactivate_empty_serie
from ....views.judge.admin import _member_slot_choices, _validate_permission_row
from ....templatetags.competicio_extras import (
    DEFAULT_COMPETITION_BACKGROUND,
    get_competicio_background_url_from_request,
)

from ...base import _BaseTrampoliDataMixin


def _template_schema_to_competicio_schema(*args, **kwargs):
    schema_local, mapping_warnings, mapping, _compat_meta = _template_schema_to_competicio_schema_service(
        *args,
        **kwargs,
    )
    return schema_local, mapping_warnings, mapping




class TeamContextScoringFlowTestBase(_BaseTrampoliDataMixin, TestCase):
    def setUp(self):
        self.comp = self._create_competicio("Comp team scoring")
        User = get_user_model()
        self.user = User.objects.create_user(
            username="team_context_scoring_owner",
            password="testpass123",
            email="team-context-scoring-owner@example.com",
        )
        CompeticioMembership.objects.create(
            user=self.user,
            competicio=self.comp,
            role=CompeticioMembership.Role.OWNER,
            is_active=True,
        )
        self.client.force_login(self.user)
        self.app = self._create_aparell("SYNC", "Sincronitzat")
        self.app.competition_unit = Aparell.CompetitionUnit.TEAM
        self.app.save(update_fields=["competition_unit"])
        self.comp_app = self._create_comp_aparell(self.comp, self.app, ordre=1)
        self.ctx = EquipContext.objects.create(
            competicio=self.comp,
            code="parelles",
            nom="Parelles",
        )
        self.other_ctx = EquipContext.objects.create(
            competicio=self.comp,
            code="altre",
            nom="Altre",
        )
        self.equip = self._create_equip(self.comp, "Parella 1", context=self.ctx)
        self.ins1 = self._create_inscripcio(self.comp, "Maria", ordre=1, grup=1)
        self.ins2 = self._create_inscripcio(self.comp, "Laia", ordre=2, grup=1)
        InscripcioEquipAssignacio.objects.create(
            competicio=self.comp,
            context=self.ctx,
            inscripcio=self.ins1,
            equip=self.equip,
        )
        InscripcioEquipAssignacio.objects.create(
            competicio=self.comp,
            context=self.ctx,
            inscripcio=self.ins2,
            equip=self.equip,
        )
        CompeticioAparellEquipContextSource.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            context=self.ctx,
        )

    def _create_team_with_members(self, team_name, member_names, *, context=None, start_order=10):
        context = context or self.ctx
        equip = self._create_equip(self.comp, team_name, context=context)
        members = []
        for idx, name in enumerate(member_names, start=0):
            ins = self._create_inscripcio(self.comp, name, ordre=start_order + idx, grup=1)
            InscripcioEquipAssignacio.objects.create(
                competicio=self.comp,
                context=context,
                inscripcio=ins,
                equip=equip,
            )
            members.append(ins)
        return equip, members

    def _team_subject(self, equip=None):
        equip = equip or self.equip
        subjects, _issues = build_team_subjects_for_comp_aparell(self.comp, self.comp_app)
        for subject in subjects:
            if int(subject.get("equip_id") or 0) == int(equip.id):
                subject_obj = TeamCompetitiveSubject.objects.get(pk=int(subject["subject_id"]))
                return subject_obj, subject
        self.fail(f"No s'ha trobat team_subject per a l'equip {equip.id}")

    def _team_payload(self, equip=None, **extra):
        subject_obj, _subject = self._team_subject(equip)
        payload = {
            "subject_kind": "team_unit",
            "subject_id": subject_obj.id,
        }
        payload.update(extra)
        return payload

    def _create_individual_comp_aparell(self, codi="TRIND", nom="Tramp Individual", ordre=9):
        app = self._create_aparell(codi, nom)
        comp_aparell = self._create_comp_aparell(self.comp, app, ordre=ordre)
        return app, comp_aparell

    def _post_json(self, url_name, payload, **kwargs):
        return self.client.post(
            reverse(url_name, kwargs={"pk": self.comp.id, **kwargs}),
            data=json.dumps(payload),
            content_type="application/json",
        )

    def _classificacio_payload(self, *, tipus="equips", app_ids=None, context_code="parelles", team_mode=None):
        ids = list(app_ids or [self.comp_app.id])
        schema = {
            "puntuacio": {
                "aparells": {"mode": "seleccionar", "ids": ids},
                "camps_per_aparell": {str(app_id): ["total"] for app_id in ids},
                "agregacio_camps": "sum",
                "exercicis": {"mode": "tots"},
                "agregacio_exercicis": "sum",
                "agregacio_aparells": "sum",
                "ordre": "desc",
            },
        }
        if tipus == "equips":
            equips_cfg = {
                "context_code": context_code,
                "incloure_sense_equip": False,
            }
            if team_mode is not None:
                equips_cfg["team_mode"] = team_mode
            schema["equips"] = equips_cfg
        return {
            "nom": "Cfg test",
            "activa": True,
            "ordre": 1,
            "tipus": tipus,
            "schema": schema,
        }

    def test_build_metric_meta_marks_native_team_displayable_fields(self):
        schema_obj = {
            "meta": {"subject_mode": "team"},
            "fields": [
                {
                    "code": "E",
                    "label": "Execucio",
                    "scope": "member",
                    "type": "matrix",
                    "shape": "judge_x_item",
                    "judges": {"count": 3},
                    "items": {"count": 5},
                },
                {
                    "code": "S",
                    "label": "Sync",
                    "scope": "shared",
                    "type": "number",
                },
            ],
            "computed": [
                {
                    "code": "E_mem",
                    "label": "Execucio membre",
                    "formula": "row_custom_compute('E', '1 - x')",
                },
                {
                    "code": "E_by_judge",
                    "label": "Execucio by judge",
                    "formula": "row_custom_compute('E', '1 - x', return_mode='by_judge')",
                },
            ],
        }

        meta = _build_metric_meta_for_comp_aparell(self.comp_app, schema_obj, strict_unknown=True)

        self.assertFalse(meta["E"]["scoreable"])
        self.assertTrue(meta["E"]["member_dependent"])
        self.assertTrue(meta["E"]["detail_displayable"])
        self.assertEqual(meta["E"]["detail_display_kind"], "judge_rows")
        self.assertTrue(meta["E_mem"]["detail_displayable"])
        self.assertEqual(meta["E_mem"]["detail_display_kind"], "scalar")
        self.assertTrue(meta["E_mem"]["member_dependent"])
        self.assertFalse(meta["E_by_judge"]["detail_displayable"])
        self.assertEqual(meta["E_by_judge"]["detail_display_kind"], "none")

    def test_builder_context_exposes_displayable_member_fields_for_native_team(self):
        ScoringSchema.objects.create(
            aparell=self.app,
            schema={
                "meta": {"subject_mode": "team"},
                "fields": [
                    {
                        "code": "E",
                        "label": "Execucio",
                        "scope": "member",
                        "type": "matrix",
                        "shape": "judge_x_item",
                        "judges": {"count": 3},
                        "items": {"count": 5},
                    },
                    {
                        "code": "S",
                        "label": "Sync",
                        "scope": "shared",
                        "type": "number",
                    },
                ],
                "computed": [
                    {
                        "code": "E_mem",
                        "label": "Execucio membre",
                        "formula": "row_custom_compute('E', '1 - x')",
                    },
                ],
            },
        )

        request = RequestFactory().get("/competicio/test/classificacions/")
        request.user = self.user
        view = ClassificacionsHome()
        view.request = request
        view.kwargs = {"pk": self.comp.id}
        view.competicio = self.comp

        ctx = view.get_context_data()
        options = ctx["aparell_field_options"][str(self.comp_app.id)]
        by_code = {item["code"]: item for item in options}

        self.assertIn("E", by_code)
        self.assertFalse(by_code["E"]["scoreable"])
        self.assertTrue(by_code["E"]["member_dependent"])
        self.assertTrue(by_code["E"]["detail_displayable"])
        self.assertEqual(by_code["E"]["detail_display_kind"], "judge_rows")
        self.assertTrue(by_code["E_mem"]["detail_displayable"])
        self.assertEqual(by_code["E_mem"]["detail_display_kind"], "scalar")

    def _native_team_schema_with_tie(self, tie):
        return {
            "puntuacio": {
                "aparells": {"mode": "seleccionar", "ids": [self.comp_app.id]},
                "camps_per_aparell": {str(self.comp_app.id): ["total"]},
                "agregacio_camps": "sum",
                "exercicis": {"mode": "tots"},
                "agregacio_exercicis": "sum",
                "agregacio_aparells": "sum",
                "ordre": "desc",
            },
            "desempat": [tie],
            "equips": {
                "context_code": "parelles",
                "team_mode": "native_team",
                "incloure_sense_equip": False,
            },
        }

    def _birth_range_partition_cfg(self, *, compliance_mode="strict", max_outside=0):
        return {
            "particions": ["any_naixement_forquilla"],
            "particions_v2": [
                {"code": "any_naixement_forquilla", "apply_mode": "all", "parent_values": []},
            ],
            "particions_config": {
                "any_naixement_forquilla": {
                    "ranges": [
                        {
                            "label": "U13",
                            "from_date": "2012-01-01",
                            "until_date": "2014-12-31",
                        },
                    ],
                    "sense_data_label": "Sense data",
                    "fora_rang_label": "Fora de forquilla",
                    "team_rules": {
                        "reference_mode": "oldest_member_birthdate",
                        "compliance_mode": compliance_mode,
                        "max_members_outside_range": max_outside,
                        "missing_birthdate_policy": "outside_range",
                    },
                }
            },
        }


__all__ = [name for name in globals() if not name.startswith("__")]


