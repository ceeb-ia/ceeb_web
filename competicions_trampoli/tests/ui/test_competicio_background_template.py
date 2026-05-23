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
    DEFAULT_COMPETITION_WALLPAPER,
    get_competicio_background_url_from_request,
)

class CompeticioBackgroundTemplateTagTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _request_with_kwargs(self, kwargs, path="/competicio/1/inscripcions/", url_name=""):
        request = self.factory.get(path)
        request.resolver_match = SimpleNamespace(kwargs=kwargs, url_name=url_name)
        return request

    def test_returns_section_wallpaper_for_competition_route(self):
        comp = Competicio.objects.create(
            nom="Comp fons natacio",
            tipus=Competicio.Tipus.NATACIO,
        )

        result = get_competicio_background_url_from_request(
            self._request_with_kwargs({"pk": comp.id}, url_name="inscripcions_list")
        )

        self.assertTrue(result.endswith("/static/general/wallpapers/inscripcions.png"))

    def test_returns_section_wallpapers_for_competition_domains(self):
        cases = (
            ("inscripcions_list", "inscripcions"),
            ("fases_planner", "fases"),
            ("rotacions_planner", "rotacions"),
            ("classificacions_home", "classificacions"),
            ("scoring_notes_home", "notes"),
        )

        for url_name, wallpaper_name in cases:
            with self.subTest(url_name=url_name):
                result = get_competicio_background_url_from_request(
                    self._request_with_kwargs({}, url_name=url_name)
                )

                self.assertTrue(
                    result.endswith(f"/static/general/wallpapers/{wallpaper_name}.png")
                )

    def test_uses_general_wallpaper_when_section_is_not_specific(self):
        comp = Competicio.objects.create(
            nom="Comp fons artistica",
            tipus=Competicio.Tipus.ARTISTICA,
        )

        result = get_competicio_background_url_from_request(
            self._request_with_kwargs({"pk": comp.id}, path="/competicions/created/", url_name="created")
        )

        self.assertTrue(result.endswith(f"/static/{DEFAULT_COMPETITION_WALLPAPER}"))

    def test_uses_general_wallpaper_when_no_active_competicio_exists(self):
        result = get_competicio_background_url_from_request(
            self._request_with_kwargs({}, path="/competicions/created/", url_name="created")
        )

        self.assertTrue(result.endswith(f"/static/{DEFAULT_COMPETITION_WALLPAPER}"))

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
            "--ceeb-page-background-image: url('/static/general/wallpapers/inscripcions.png');",
        )

    def test_base_template_uses_general_wallpaper_for_competition_home(self):
        User = get_user_model()
        user = User.objects.create_user(
            username="bg_default_user",
            password="testpass123",
            email="bg-default@example.com",
        )
        group, _ = Group.objects.get_or_create(name="competicions_manager")
        user.groups.add(group)
        self.client.force_login(user)

        response = self.client.get(reverse("created"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            f"--ceeb-page-background-image: url('/static/{DEFAULT_COMPETITION_WALLPAPER}');",
        )


