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
from ..models.judging import (
    JudgeConversation,
    JudgeConversationMessage,
    JudgeDeviceToken,
    PublicLiveToken,
)
from ..models.classificacions import ClassificacioConfig, ClassificacioTemplateGlobal
from ..models.rotacions import (
    RotacioAssignacio,
    RotacioAssignacioGrup,
    RotacioAssignacioSerieEquip,
    RotacioEstacio,
    RotacioFranja,
)
from ..models.scoring import (
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
from ..models.competicio import (
    Aparell,
    CompeticioAparell,
    CompeticioAparellEquipContextSource,
    InscripcioAparellExclusio,
)
from ..models import CompeticioMembership
from ..scoring_engine import ScoringEngine
from ..services.inscripcions.groups import renumber_groups_for_competicio
from ..services.inscripcions.sorting import (
    _split_custom_sort_tokens,
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
from ..services.classificacions.classificacio_templates import (
    normalize_particions_schema as _normalize_particions_schema,
    schema_to_template_schema as _schema_to_template_schema,
    template_schema_to_competicio_schema as _template_schema_to_competicio_schema_service,
)
from ..services.classificacions.builder import scoreable_codes_by_app_id as _scoreable_codes_by_app_id
from ..services.classificacions.compute import DEFAULT_SCHEMA, compute_classificacio
from ..services.classificacions.export import _normalize_excel_cell
from ..services.classificacions.partitions import normalize_schema_legacy_team_birth_partition
from ..services.classificacions.validation import (
    build_metric_meta_for_comp_aparell as _build_metric_meta_for_comp_aparell,
    build_scoreable_meta_for_schema as _build_scoreable_meta_for_schema,
    validate_particions_schema as _validate_particions_schema,
    validate_schema_for_competicio as _validate_schema_for_competicio,
)
from ..views.classificacions.builder import ClassificacionsHome
from ..services.shared.competition_groups import (
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
from ..services.scoring.team_scoring import (
    build_permission_label,
    build_team_subjects_for_comp_aparell,
    resolve_permission_runtime_entries,
    runtime_schema_for_comp_aparell,
)
from ..services.teams.team_series import safe_deactivate_empty_serie
from ..views.judge.admin import _member_slot_choices, _validate_permission_row
from ..templatetags.competicio_extras import (
    DEFAULT_COMPETITION_BACKGROUND,
    get_competicio_background_url_from_request,
)

from .base import _BaseTrampoliDataMixin


def _template_schema_to_competicio_schema(*args, **kwargs):
    schema_local, mapping_warnings, mapping, _compat_meta = _template_schema_to_competicio_schema_service(
        *args,
        **kwargs,
    )
    return schema_local, mapping_warnings, mapping


class CompetitionAccessControlTests(_BaseTrampoliDataMixin, TestCase):
    def setUp(self):
        self.comp = self._create_competicio("Comp Accessos")
        self.other_comp = self._create_competicio("Comp Privada")
        self.app = self._create_aparell("TRAMP_ACCESS", "Tramp Access")
        self.comp_app = self._create_comp_aparell(self.comp, self.app, ordre=1, actiu=True)

        User = get_user_model()
        self.judge_admin_user = User.objects.create_user(
            username="judge_admin_user",
            password="testpass123",
            email="judge-admin@example.com",
        )
        self.readonly_user = User.objects.create_user(
            username="readonly_user",
            password="testpass123",
            email="readonly@example.com",
        )
        self.manager_user = User.objects.create_user(
            username="manager_user",
            password="testpass123",
            email="manager@example.com",
        )

        for group_name in GLOBAL_AUTH_GROUPS.keys():
            Group.objects.get_or_create(name=group_name)

        competitions_group = Group.objects.get(name="competicions_manager")
        self.manager_user.groups.add(competitions_group)

        CompeticioMembership.objects.create(
            user=self.judge_admin_user,
            competicio=self.comp,
            role=CompeticioMembership.Role.JUDGE_ADMIN,
            is_active=True,
        )
        CompeticioMembership.objects.create(
            user=self.readonly_user,
            competicio=self.comp,
            role=CompeticioMembership.Role.READONLY,
            is_active=True,
        )

    def test_judge_admin_membership_can_manage_qr_but_readonly_cannot(self):
        url = reverse("judges_qr_home", kwargs={"competicio_id": self.comp.id})

        self.client.force_login(self.judge_admin_user)
        ok_res = self.client.get(url)
        self.assertEqual(ok_res.status_code, 200)
        self.client.logout()

        self.client.force_login(self.readonly_user)
        denied_res = self.client.get(url)
        self.assertEqual(denied_res.status_code, 403)

        self.assertTrue(
            user_has_competicio_capability(
                self.judge_admin_user,
                self.comp,
                "judge_tokens.manage",
            )
        )
        self.assertFalse(
            user_has_competicio_capability(
                self.readonly_user,
                self.comp,
                "judge_tokens.manage",
            )
        )

    def test_global_competitions_manager_can_access_global_competitions_pages(self):
        url = reverse("competicions_home")
        self.client.force_login(self.manager_user)
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)

    def test_created_list_shows_only_user_membership_competitions(self):
        url = reverse("created")
        self.client.force_login(self.readonly_user)
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, self.comp.nom)
        self.assertNotContains(res, self.other_comp.nom)

    def test_competicions_manager_group_without_membership_cannot_open_foreign_competition(self):
        url = reverse("inscripcions_list", kwargs={"pk": self.other_comp.id})
        self.client.force_login(self.manager_user)
        res = self.client.get(url)
        self.assertEqual(res.status_code, 403)

    def test_regular_user_cannot_create_competition_from_global_route(self):
        url = reverse("create")
        self.client.force_login(self.readonly_user)
        res = self.client.post(
            url,
            data={
                "nom": "Comp Creada Usuari",
                "tipus": Competicio.Tipus.TRAMPOLI,
                "data": "",
            },
        )
        self.assertEqual(res.status_code, 403)
        self.assertFalse(Competicio.objects.filter(nom="Comp Creada Usuari").exists())

    def test_competicions_manager_create_competition_assigns_owner_membership_to_creator(self):
        url = reverse("create")
        self.client.force_login(self.manager_user)
        res = self.client.post(
            url,
            data={
                "nom": "Comp Creada Usuari",
                "tipus": Competicio.Tipus.TRAMPOLI,
                "data": "",
            },
        )
        self.assertEqual(res.status_code, 302)

        created_comp = Competicio.objects.get(nom="Comp Creada Usuari")
        membership = CompeticioMembership.objects.get(
            user=self.manager_user,
            competicio=created_comp,
        )
        self.assertEqual(membership.role, CompeticioMembership.Role.OWNER)
        self.assertTrue(membership.is_active)
        self.assertEqual(membership.granted_by_id, self.manager_user.id)

    def test_public_live_token_creation_persists_media_permission(self):
        url = reverse("public_live_qr_home", kwargs={"competicio_id": self.comp.id})
        self.client.force_login(self.judge_admin_user)

        res_with_media = self.client.post(
            url,
            data={
                "action": "create",
                "label": "Public A",
                "can_view_media": "1",
            },
        )
        self.assertEqual(res_with_media.status_code, 302)
        token_with_media = PublicLiveToken.objects.get(competicio=self.comp, label="Public A")
        self.assertTrue(token_with_media.can_view_media)

        res_without_media = self.client.post(
            url,
            data={
                "action": "create",
                "label": "Public B",
            },
        )
        self.assertEqual(res_without_media.status_code, 302)
        token_without_media = PublicLiveToken.objects.get(competicio=self.comp, label="Public B")
        self.assertFalse(token_without_media.can_view_media)


class AparellOwnershipIsolationTests(_BaseTrampoliDataMixin, TestCase):
    def setUp(self):
        User = get_user_model()
        self.user_a = User.objects.create_user(
            username="ap_owner_a",
            password="testpass123",
            email="ap-owner-a@example.com",
        )
        self.user_b = User.objects.create_user(
            username="ap_owner_b",
            password="testpass123",
            email="ap-owner-b@example.com",
        )
        manager_group = Group.objects.get_or_create(name="competicions_manager")[0]
        self.user_a.groups.add(manager_group)
        self.user_b.groups.add(manager_group)

        self.comp = self._create_competicio("Comp Aparell Owners")
        CompeticioMembership.objects.create(
            user=self.user_a,
            competicio=self.comp,
            role=CompeticioMembership.Role.EDITOR,
            is_active=True,
        )

    def test_two_users_can_create_same_aparell_code(self):
        ap_a = self._create_aparell("TRA", "Aparell TRA A", owner=self.user_a)
        ap_b = self._create_aparell("TRA", "Aparell TRA B", owner=self.user_b)
        self.assertNotEqual(ap_a.id, ap_b.id)

    def test_cannot_attach_foreign_aparell_to_competition(self):
        self._create_aparell("TRA", "Aparell propi", owner=self.user_a)
        foreign = self._create_aparell("TRA", "Aparell aliè", owner=self.user_b)

        self.client.force_login(self.user_a)
        url = reverse("trampoli_aparell_create", kwargs={"pk": self.comp.id})
        res = self.client.post(url, data={"aparell": foreign.id, "nombre_exercicis": 1})
        self.assertEqual(res.status_code, 200)
        self.assertIn("form", res.context)
        self.assertIn("aparell", res.context["form"].errors)
        self.assertFalse(
            CompeticioAparell.objects.filter(competicio=self.comp, aparell=foreign).exists()
        )

    def test_cannot_edit_foreign_aparell_catalog_entry(self):
        foreign = self._create_aparell("TRA", "Aparell aliè", owner=self.user_b)
        self.client.force_login(self.user_a)
        url = reverse("aparell_update", kwargs={"pk": foreign.id})
        res = self.client.get(url)
        self.assertEqual(res.status_code, 404)

    def test_can_delete_own_global_aparell_when_unused(self):
        own = self._create_aparell("DEL", "Aparell eliminable", owner=self.user_a)
        self.client.force_login(self.user_a)
        url = reverse("aparell_delete", kwargs={"pk": own.id})
        res = self.client.post(url)
        self.assertEqual(res.status_code, 302)
        self.assertEqual(res.url, reverse("aparells_list"))
        self.assertFalse(Aparell.objects.filter(pk=own.id).exists())

    def test_cannot_delete_own_global_aparell_when_used_in_competition(self):
        own = self._create_aparell("USE", "Aparell en us", owner=self.user_a)
        self._create_comp_aparell(self.comp, own, ordre=1, actiu=True)
        self.client.force_login(self.user_a)
        url = reverse("aparell_delete", kwargs={"pk": own.id})
        res = self.client.post(url)
        self.assertEqual(res.status_code, 302)
        self.assertEqual(res.url, reverse("aparells_list"))
        self.assertTrue(Aparell.objects.filter(pk=own.id).exists())

    def test_cannot_delete_foreign_global_aparell(self):
        foreign = self._create_aparell("ALI", "Aparell alie", owner=self.user_b)
        self.client.force_login(self.user_a)
        url = reverse("aparell_delete", kwargs={"pk": foreign.id})
        res = self.client.post(url)
        self.assertEqual(res.status_code, 404)
        self.assertTrue(Aparell.objects.filter(pk=foreign.id).exists())

    def test_superuser_sees_owner_in_global_aparell_catalog(self):
        self._create_aparell("OWN1", "Aparell owner b", owner=self.user_b)
        User = get_user_model()
        admin = User.objects.create_superuser(
            username="ap_owner_admin_global",
            password="testpass123",
            email="ap-owner-admin-global@example.com",
        )
        self.client.force_login(admin)
        res = self.client.get(reverse("aparells_list"))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Creat per")
        self.assertContains(res, self.user_b.username)

    def test_superuser_sees_owner_in_competicio_aparells_list(self):
        app_b = self._create_aparell("OWN2", "Aparell owner b comp", owner=self.user_b)
        self._create_comp_aparell(self.comp, app_b, ordre=1, actiu=True)
        User = get_user_model()
        admin = User.objects.create_superuser(
            username="ap_owner_admin_comp",
            password="testpass123",
            email="ap-owner-admin-comp@example.com",
        )
        self.client.force_login(admin)
        res = self.client.get(reverse("trampoli_aparells_list", kwargs={"pk": self.comp.id}))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Creat per")
        self.assertContains(res, self.user_b.username)


class PublicLiveTokenViewsTests(_BaseTrampoliDataMixin, TestCase):
    def setUp(self):
        self.comp = self._create_competicio("Comp Public Live")
        self.token = PublicLiveToken.objects.create(
            competicio=self.comp,
            label="Pantalla principal",
            is_active=True,
        )

    def test_public_live_portal_renders_public_live_page(self):
        url = reverse("public_live_portal", kwargs={"token": self.token.id})
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        body = res.content.decode("utf-8")
        self.assertIn("Classificacions", body)
        self.assertIn(reverse("public_live_classificacions_data", kwargs={"token": self.token.id}), body)
        self.assertIn("function renderTeamRawDetailCell(v, col)", body)
        self.assertIn("team-raw-summary", body)
        self.assertIn('v._kind === "team_raw_detail"', body)

    def test_public_live_portal_rejects_revoked_token(self):
        self.token.is_active = False
        self.token.revoked_at = timezone.now()
        self.token.save(update_fields=["is_active", "revoked_at"])

        url = reverse("public_live_portal", kwargs={"token": self.token.id})
        res = self.client.get(url)
        self.assertEqual(res.status_code, 403)

    def test_public_live_qr_png_returns_png(self):
        url = reverse("public_live_qr_png", kwargs={"token": self.token.id})
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res["Content-Type"], "image/png")

    def test_public_live_data_requires_valid_token(self):
        url = reverse("public_live_classificacions_data", kwargs={"token": self.token.id})
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json().get("ok"))
        self.assertEqual(
            res.json().get("permissions", {}).get("can_view_media"),
            False,
        )

    def test_public_live_data_exposes_media_permission_flag(self):
        self.token.can_view_media = True
        self.token.save(update_fields=["can_view_media"])

        url = reverse("public_live_classificacions_data", kwargs={"token": self.token.id})
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json().get("ok"))
        self.assertEqual(
            res.json().get("permissions", {}).get("can_view_media"),
            True,
        )
