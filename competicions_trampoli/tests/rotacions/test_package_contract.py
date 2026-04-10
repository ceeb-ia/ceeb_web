import json
from importlib import import_module
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


class RotacionsPackageContractTests(TestCase):
    ROUTE_EXPORTS = [
        "estacio_delete",
        "estacio_descans_create",
        "estacions_reorder",
        "franges_auto_create",
        "franges_export_excel",
        "franges_reorder",
        "franges_reorder_visual",
        "franja_create",
        "franja_delete",
        "franja_insert_after",
        "franja_order_mode_set",
        "franja_update_inline",
        "rotacions_clear_all",
        "rotacions_extrapolar",
        "rotacions_export_logo_clear",
        "rotacions_export_logo_upload",
        "rotacions_export_meta_save",
        "rotacions_out_of_program_visibility_save",
        "rotacions_planner",
        "rotacions_save",
    ]

    def test_rotacions_package_and_submodules_are_importable(self):
        package = import_module("competicions_trampoli.views.rotacions")
        self.assertEqual(set(package.__all__), set(self.ROUTE_EXPORTS))

        for module_name in (
            "competicions_trampoli.views.rotacions._shared",
            "competicions_trampoli.views.rotacions.assignments",
            "competicions_trampoli.views.rotacions.estacions",
            "competicions_trampoli.views.rotacions.export",
            "competicions_trampoli.views.rotacions.franges",
            "competicions_trampoli.views.rotacions.planner",
        ):
            self.assertIsNotNone(import_module(module_name))

    def test_rotacions_package_exports_route_entrypoints(self):
        package = import_module("competicions_trampoli.views.rotacions")

        for export_name in self.ROUTE_EXPORTS:
            self.assertTrue(callable(getattr(package, export_name)))
            self.assertIn(export_name, package.__all__)

    def test_rotacions_routes_reverse_and_resolve_keep_public_names(self):
        route_cases = [
            ("rotacions_planner", {"pk": 1}),
            ("rotacions_save", {"pk": 1}),
            ("rotacions_franges_auto_create", {"pk": 1}),
            ("rotacions_franja_create", {"pk": 1}),
            ("rotacions_franja_delete", {"pk": 1, "franja_id": 1}),
            ("rotacions_estacio_descans_create", {"pk": 1}),
            ("rotacions_estacio_delete", {"pk": 1, "estacio_id": 1}),
            ("rotacions_extrapolar", {"pk": 1, "franja_id": 1}),
            ("rotacions_estacions_reorder", {"pk": 1}),
            ("rotacions_clear_all", {"pk": 1}),
            ("rotacions_out_of_program_visibility_save", {"pk": 1}),
            ("rotacions_franja_insert_after", {"pk": 1, "franja_id": 1}),
            ("rotacions_franges_reorder", {"pk": 1}),
            ("rotacions_franges_reorder_visual", {"pk": 1}),
            ("rotacions_franja_update_inline", {"pk": 1, "franja_id": 1}),
            ("rotacions_franja_order_mode_set", {"pk": 1, "franja_id": 1}),
            ("rotacions_export_meta_save", {"pk": 1}),
            ("rotacions_export_logo_upload", {"pk": 1}),
            ("rotacions_export_logo_clear", {"pk": 1}),
            ("rotacions_franges_export_excel", {"pk": 1}),
        ]

        for route_name, kwargs in route_cases:
            match = resolve(reverse(route_name, kwargs=kwargs))
            self.assertEqual(match.view_name, route_name)
            self.assertEqual(match.url_name, route_name)
