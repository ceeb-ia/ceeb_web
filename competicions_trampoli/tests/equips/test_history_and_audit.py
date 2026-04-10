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


class EquipContextHistorySnapshotTests(_BaseTrampoliDataMixin, TestCase):
    def setUp(self):
        self.comp = self._create_competicio("Comp Snapshot Context")
        self.base_ctx = self._ensure_native_equip_context(self.comp)
        self.ctx = EquipContext.objects.create(competicio=self.comp, code="ctx-alt", nom="Context Alt")
        self.team_native = Equip.objects.create(competicio=self.comp, context=self.base_ctx, nom="Equip Base")
        self.team_context = Equip.objects.create(competicio=self.comp, context=self.ctx, nom="Equip Alt")
        self.ins = self._create_inscripcio(self.comp, "Participant Snapshot", ordre=1)
        InscripcioEquipAssignacio.objects.create(
            competicio=self.comp,
            context=self.base_ctx,
            inscripcio=self.ins,
            equip=self.team_native,
        )
        InscripcioEquipAssignacio.objects.create(
            competicio=self.comp,
            context=self.ctx,
            inscripcio=self.ins,
            equip=self.team_context,
        )

    def test_snapshot_restores_contexts_and_assignacions(self):
        rf = RequestFactory()
        request = rf.get("/")
        request.session = SessionStore()

        snap = capture_inscripcions_history_snapshot(request, self.comp)
        EquipContext.objects.filter(pk=self.ctx.id).delete()
        InscripcioEquipAssignacio.objects.filter(competicio=self.comp, inscripcio=self.ins).delete()

        apply_inscripcions_history_snapshot(request, self.comp, snap)

        self.ins.refresh_from_db()
        self.assertIsNone(self.ins.equip_id)
        self.assertTrue(EquipContext.objects.filter(competicio=self.comp, code="ctx-alt").exists())
        self.assertTrue(EquipContext.objects.filter(competicio=self.comp, code="native").exists())
        self.assertTrue(
            InscripcioEquipAssignacio.objects.filter(
                competicio=self.comp,
                context__code="native",
                inscripcio=self.ins,
                equip=self.team_native,
            ).exists()
        )
        self.assertTrue(
            InscripcioEquipAssignacio.objects.filter(
                competicio=self.comp,
                context__code="ctx-alt",
                inscripcio=self.ins,
                equip=self.team_context,
            ).exists()
        )

    def test_legacy_snapshot_with_equip_id_restores_native_assignment(self):
        rf = RequestFactory()
        request = rf.get("/")
        request.session = SessionStore()

        snap = capture_inscripcions_history_snapshot(request, self.comp)
        for row in snap["inscripcions_fields"]:
            if int(row.get("id") or 0) == self.ins.id:
                row["equip_id"] = self.team_native.id
        snap["equip_assignacions_state"] = []
        snap["equip_contexts_state"] = []

        EquipContext.objects.filter(competicio=self.comp).delete()
        InscripcioEquipAssignacio.objects.filter(competicio=self.comp).delete()

        apply_inscripcions_history_snapshot(request, self.comp, snap)

        self.assertTrue(EquipContext.objects.filter(competicio=self.comp, code="native").exists())
        self.assertTrue(
            InscripcioEquipAssignacio.objects.filter(
                competicio=self.comp,
                context__code="native",
                inscripcio=self.ins,
                equip_id=self.team_native.id,
            ).exists()
        )


class BaseTeamContextAuditCommandTests(_BaseTrampoliDataMixin, TestCase):
    def test_command_reports_missing_contexts_orphans_and_divergences_without_mutating_data(self):
        comp_missing = self._create_competicio("Comp Missing")
        missing_ctx = EquipContext.objects.create(competicio=comp_missing, code="legacy-only", nom="Legacy Only")
        missing_team = Equip.objects.create(competicio=comp_missing, context=missing_ctx, nom="Legacy Missing")
        Inscripcio.objects.create(
            competicio=comp_missing,
            nom_i_cognoms="Orfe Legacy",
            equip=missing_team,
            ordre_sortida=1,
        )
        self.assertFalse(EquipContext.objects.filter(competicio=comp_missing, code="native").exists())

        comp_div = self._create_competicio("Comp Divergence")
        base_ctx = self._ensure_native_equip_context(comp_div)
        legacy_team = Equip.objects.create(competicio=comp_div, context=base_ctx, nom="Legacy Team")
        native_team = Equip.objects.create(competicio=comp_div, context=base_ctx, nom="Native Team")
        ins_div = Inscripcio.objects.create(
            competicio=comp_div,
            nom_i_cognoms="Divergent",
            equip=legacy_team,
            ordre_sortida=1,
        )
        InscripcioEquipAssignacio.objects.create(
            competicio=comp_div,
            context=base_ctx,
            inscripcio=ins_div,
            equip=native_team,
        )

        out = StringIO()
        call_command("audit_base_team_context", stdout=out)
        report = out.getvalue()

        self.assertIn("competitions_scanned: 2", report)
        self.assertIn("competitions_without_native_context: 1", report)
        self.assertIn("legacy_team_without_native_assignment: 1", report)
        self.assertIn("legacy_native_divergences: 1", report)
        self.assertIn(f"competicio_id={comp_missing.id}", report)
        self.assertIn(f"inscripcio_id={ins_div.id}", report)
        self.assertFalse(EquipContext.objects.filter(competicio=comp_missing, code="native").exists())
