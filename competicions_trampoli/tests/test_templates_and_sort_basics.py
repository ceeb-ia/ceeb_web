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

from .. import live_cache
from ..access import user_has_competicio_capability
from ..forms import CompeticioAparellForm
from ..models import (
    Competicio,
    Equip,
    EquipContext,
    GrupCompeticio,
    Inscripcio,
    InscripcioEquipAssignacio,
    InscripcioMedia,
)
from ..models_judging import (
    JudgeConversation,
    JudgeConversationMessage,
    JudgeDeviceToken,
    PublicLiveToken,
)
from ..models_classificacions import ClassificacioConfig, ClassificacioTemplateGlobal
from ..models_rotacions import (
    RotacioAssignacio,
    RotacioAssignacioGrup,
    RotacioAssignacioSerieEquip,
    RotacioEstacio,
    RotacioFranja,
)
from ..models_scoring import (
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
from ..models_trampoli import (
    Aparell,
    CompeticioAparell,
    CompeticioAparellEquipContextSource,
    InscripcioAparellExclusio,
)
from ..models import CompeticioMembership
from ..scoring_engine import ScoringEngine
from ..inscripcions_views_shared import (
    _split_custom_sort_tokens,
    renumber_groups_for_competicio,
    sort_records_by_field_stable,
)
from ..services.inscripcions.history import (
    apply_inscripcions_history_snapshot,
    capture_inscripcions_history_snapshot,
)
from ..services.inscripcions.queries import (
    COLUMN_FILTER_EMPTY_TOKEN,
    _build_inscripcions_filtered_qs,
    build_inscripcions_sort_context_key,
    get_competicio_custom_sort_rank_map,
)
from ..views_classificacions import (
    ClassificacionsHome,
    _build_metric_meta_for_comp_aparell,
    _normalize_excel_cell,
    _build_scoreable_meta_for_schema,
    _normalize_particions_schema,
    _scoreable_codes_by_app_id,
    _schema_to_template_schema,
    _template_schema_to_competicio_schema,
    _validate_schema_for_competicio,
    _validate_particions_schema,
)
from ..services.services_classificacions_2 import (
    DEFAULT_SCHEMA,
    compute_classificacio,
    normalize_schema_legacy_team_birth_partition,
)
from ..services.competition_groups import (
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
from ..services.team_scoring import (
    build_permission_label,
    build_team_subjects_for_comp_aparell,
    resolve_permission_runtime_entries,
    runtime_schema_for_comp_aparell,
)
from ..services.team_series import safe_deactivate_empty_serie
from ..views_judge_admin import _member_slot_choices, _validate_permission_row
from ..templatetags.competicio_extras import (
    DEFAULT_COMPETITION_BACKGROUND,
    get_competicio_background_url_from_request,
)

class CompeticioBackgroundTemplateTagTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _request_with_kwargs(self, kwargs, path="/competicio/1/inscripcions/"):
        request = self.factory.get(path)
        request.resolver_match = SimpleNamespace(kwargs=kwargs)
        return request

    def test_returns_mapped_background_for_existing_type_image(self):
        comp = Competicio.objects.create(
            nom="Comp fons natacio",
            tipus=Competicio.Tipus.NATACIO,
        )

        result = get_competicio_background_url_from_request(
            self._request_with_kwargs({"pk": comp.id})
        )

        self.assertTrue(result.endswith("/static/images/natacio.jpg"))

    def test_falls_back_to_default_when_mapped_image_file_is_missing(self):
        comp = Competicio.objects.create(
            nom="Comp fons artistica",
            tipus=Competicio.Tipus.ARTISTICA,
        )

        result = get_competicio_background_url_from_request(
            self._request_with_kwargs({"pk": comp.id})
        )

        self.assertTrue(result.endswith(f"/static/{DEFAULT_COMPETITION_BACKGROUND}"))

    def test_falls_back_to_default_when_no_active_competicio_exists(self):
        result = get_competicio_background_url_from_request(
            self._request_with_kwargs({}, path="/competicions/created/")
        )

        self.assertTrue(result.endswith(f"/static/{DEFAULT_COMPETITION_BACKGROUND}"))

    def test_falls_back_to_default_for_non_competition_route_even_with_pk(self):
        comp = Competicio.objects.create(
            nom="Comp no relacionada",
            tipus=Competicio.Tipus.NATACIO,
        )

        result = get_competicio_background_url_from_request(
            self._request_with_kwargs({"pk": comp.id}, path="/altres/modul/1/")
        )

        self.assertTrue(result.endswith(f"/static/{DEFAULT_COMPETITION_BACKGROUND}"))

    def test_base_template_injects_competicio_background_for_competition_route(self):
        comp = Competicio.objects.create(
            nom="Comp render natacio",
            tipus=Competicio.Tipus.NATACIO,
        )
        User = get_user_model()
        user = User.objects.create_user(
            username="bg_route_user",
            password="testpass123",
            email="bg-route@example.com",
        )
        CompeticioMembership.objects.create(
            user=user,
            competicio=comp,
            role=CompeticioMembership.Role.OWNER,
            is_active=True,
        )
        self.client.force_login(user)

        response = self.client.get(reverse("inscripcions_list", kwargs={"pk": comp.id}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "--ceeb-page-background-image: url('/static/images/natacio.jpg');",
        )

    def test_base_template_uses_default_background_outside_competition_routes(self):
        User = get_user_model()
        user = User.objects.create_user(
            username="bg_default_user",
            password="testpass123",
            email="bg-default@example.com",
        )
        self.client.force_login(user)

        response = self.client.get(reverse("created"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            f"--ceeb-page-background-image: url('/static/{DEFAULT_COMPETITION_BACKGROUND}');",
        )


class ScoringEngineAliasResolutionTests(TestCase):
    def test_computed_var_alias_can_be_used_before_definition_order(self):
        schema = {
            "fields": [
                {"code": "A", "var": "a", "type": "number"},
            ],
            "computed": [
                # Deliberadament abans que C1 per provar ordre topo + alias var.
                {"code": "C2", "formula": "u + 2"},
                {"code": "C1", "var": "u", "formula": "a + 1"},
                {"code": "TOTAL", "formula": "C2"},
            ],
        }

        result = ScoringEngine(schema).compute({"A": 3})

        self.assertEqual(result.outputs.get("C1"), 4)
        self.assertEqual(result.outputs.get("C2"), 6)
        self.assertEqual(float(result.total), 6.0)


class CustomSortOrderFallbackTests(TestCase):
    def _make_row(self, rid, categoria):
        return SimpleNamespace(id=rid, categoria=categoria, extra={})

    def test_custom_order_is_applied_before_default_fallback(self):
        comp = Competicio.objects.create(
            nom="Comp custom sort",
            tipus=Competicio.Tipus.TRAMPOLI,
            inscripcions_view={
                "custom_sort_orders": {
                    "categoria": ["alevi", "infantil", "cadet"],
                }
            },
        )

        rows = [
            self._make_row(1, "cadet"),
            self._make_row(2, "junior"),
            self._make_row(3, "infantil"),
            self._make_row(4, "alevi"),
            self._make_row(5, "benjami"),
        ]

        rank = get_competicio_custom_sort_rank_map(comp, "categoria")
        ordered = sort_records_by_field_stable(
            rows,
            "categoria",
            descending=False,
            custom_rank_map=rank,
        )

        self.assertEqual(
            [r.categoria for r in ordered],
            ["alevi", "infantil", "cadet", "benjami", "junior"],
        )

    def test_without_custom_order_fallback_matches_default_sort(self):
        comp = Competicio.objects.create(
            nom="Comp no custom sort",
            tipus=Competicio.Tipus.TRAMPOLI,
        )

        rows = [
            self._make_row(1, "zeta"),
            self._make_row(2, "beta"),
            self._make_row(3, "alfa"),
        ]

        rank = get_competicio_custom_sort_rank_map(comp, "categoria")
        ordered = sort_records_by_field_stable(
            rows,
            "categoria",
            descending=False,
            custom_rank_map=rank,
        )

        self.assertEqual([r.categoria for r in ordered], ["alfa", "beta", "zeta"])

    def test_split_custom_sort_tokens_separates_active_and_stale(self):
        active, stale = _split_custom_sort_tokens(
            ["alevi", "fantasma", "CADET", "fantasma"],
            {"alevi", "cadet"},
        )
        self.assertEqual(active, ["alevi", "CADET"])
        self.assertEqual(stale, ["fantasma"])
