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


class RotationOrderingDisplayTests(_BaseTrampoliDataMixin, TestCase):
    def setUp(self):
        self.comp = self._create_competicio("Comp Rotations Display")
        self.app_prior = self._create_aparell("ROT_PRIOR", "Rotation Prior")
        self.app = self._create_aparell("ROT_APP", "Rotation App")
        self.comp_app_prior = self._create_comp_aparell(self.comp, self.app_prior, ordre=1, actiu=True)
        self.comp_app = self._create_comp_aparell(self.comp, self.app, ordre=1, actiu=True)

        self.ins_1 = self._create_inscripcio(self.comp, "Participant 1", ordre=1, grup=1)
        self.ins_2 = self._create_inscripcio(self.comp, "Participant 2", ordre=2, grup=1)
        self.ins_3 = self._create_inscripcio(self.comp, "Participant 3", ordre=3, grup=1)

        group = self.ins_1.grup_competicio
        Inscripcio.objects.filter(pk=self.ins_1.pk).update(ordre_competicio=2)
        Inscripcio.objects.filter(pk=self.ins_2.pk).update(ordre_competicio=1)
        Inscripcio.objects.filter(pk=self.ins_3.pk).update(ordre_competicio=3)
        self.ins_1.refresh_from_db()
        self.ins_2.refresh_from_db()
        self.ins_3.refresh_from_db()

        self.franja_1 = RotacioFranja.objects.create(
            competicio=self.comp,
            hora_inici="09:00",
            hora_fi="09:30",
            ordre=1,
            titol="Franja 1",
        )
        self.franja_2 = RotacioFranja.objects.create(
            competicio=self.comp,
            hora_inici="09:30",
            hora_fi="10:00",
            ordre=2,
            titol="Franja 2",
        )
        self.franja_3 = RotacioFranja.objects.create(
            competicio=self.comp,
            hora_inici="10:00",
            hora_fi="10:30",
            ordre=3,
            titol="Franja 3",
        )
        self.estacio_prior = RotacioEstacio.objects.create(
            competicio=self.comp,
            tipus="aparell",
            comp_aparell=self.comp_app_prior,
            ordre=1,
            actiu=True,
        )
        self.estacio = RotacioEstacio.objects.create(
            competicio=self.comp,
            tipus="aparell",
            comp_aparell=self.comp_app,
            ordre=2,
            actiu=True,
        )
        assignacio_0 = RotacioAssignacio.objects.create(
            competicio=self.comp,
            franja=self.franja_1,
            estacio=self.estacio_prior,
        )
        RotacioAssignacioGrup.objects.create(assignacio=assignacio_0, grup=group, ordre=1)
        assignacio = RotacioAssignacio.objects.create(
            competicio=self.comp,
            franja=self.franja_2,
            estacio=self.estacio,
        )
        RotacioAssignacioGrup.objects.create(assignacio=assignacio, grup=group, ordre=1)
        assignacio_2 = RotacioAssignacio.objects.create(
            competicio=self.comp,
            franja=self.franja_3,
            estacio=self.estacio,
        )
        RotacioAssignacioGrup.objects.create(assignacio=assignacio_2, grup=group, ordre=1)

        self.comp.inscripcions_view = {
            "rotacions_order_modes": {
                str(self.franja_2.id): "rotate",
                str(self.franja_3.id): "rotate",
            }
        }
        self.comp.save(update_fields=["inscripcions_view"])

        self.token = JudgeDeviceToken.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            label="Judge Rotation",
            permissions=[{"field_code": "E", "judge_index": 1}],
            is_active=True,
        )
        User = get_user_model()
        self.user = User.objects.create_user(
            username="rotation_display_owner",
            password="testpass123",
            email="rotation-display-owner@example.com",
        )
        CompeticioMembership.objects.create(
            user=self.user,
            competicio=self.comp,
            role=CompeticioMembership.Role.OWNER,
            is_active=True,
        )
        self.client.force_login(self.user)

    def _assign_group_to_app_franja(self, group, franja):
        assignacio, _created = RotacioAssignacio.objects.get_or_create(
            competicio=self.comp,
            franja=franja,
            estacio=self.estacio,
        )
        next_ordre = (
            RotacioAssignacioGrup.objects
            .filter(assignacio=assignacio)
            .count() + 1
        )
        RotacioAssignacioGrup.objects.create(assignacio=assignacio, grup=group, ordre=next_ordre)
        return assignacio

    def _franja_stub(self, franja, *, tipus="competition"):
        return SimpleNamespace(
            id=franja.id,
            competicio_id=self.comp.id,
            hora_inici=franja.hora_inici,
            hora_fi=franja.hora_fi,
            ordre=franja.ordre,
            titol=franja.titol,
            tipus=tipus,
        )

    def test_judge_portal_uses_first_app_franja_order_by_default_and_allows_override(self):
        portal_url = reverse("judge_portal", kwargs={"token": self.token.id})
        portal_res = self.client.get(portal_url)
        self.assertEqual(portal_res.status_code, 200)
        self.assertIsNone(portal_res.context["franja_override_id"])

        block = portal_res.context["group_blocks"][0]
        self.assertEqual(block["franja_id"], self.franja_2.id)
        self.assertEqual(
            [ins["nom_i_cognoms"] for ins in block["list"]],
            ["Participant 1", "Participant 3", "Participant 2"],
        )
        self.assertEqual(
            [ins["rotation_order_display"] for ins in block["list"]],
            [1, 2, 3],
        )

        body = portal_res.content.decode("utf-8")
        self.assertIn("Participant 1", body)
        self.assertIn("Ordre 1", body)
        self.assertIn("Ordre 2", body)
        self.assertIn("Base 3", body)

        third_res = self.client.get(portal_url, {"franja": self.franja_3.id})
        self.assertEqual(third_res.status_code, 200)
        self.assertEqual(third_res.context["franja_override_id"], self.franja_3.id)

        third_block = third_res.context["group_blocks"][0]
        self.assertEqual(third_block["franja_id"], self.franja_3.id)
        self.assertEqual(
            [ins["nom_i_cognoms"] for ins in third_block["list"]],
            ["Participant 3", "Participant 2", "Participant 1"],
        )
        self.assertEqual(
            [ins["rotation_order_display"] for ins in third_block["list"]],
            [1, 2, 3],
        )

    def test_judge_portal_shows_all_programmed_groups_with_each_group_ordered_by_own_franja(self):
        extra_1 = self._create_inscripcio(self.comp, "Participant 4", ordre=4, grup=2)
        extra_2 = self._create_inscripcio(self.comp, "Participant 5", ordre=5, grup=2)
        Inscripcio.objects.filter(pk=extra_1.pk).update(ordre_competicio=1)
        Inscripcio.objects.filter(pk=extra_2.pk).update(ordre_competicio=2)
        extra_1.refresh_from_db()
        extra_2.refresh_from_db()
        self._assign_group_to_app_franja(extra_1.grup_competicio, self.franja_3)

        portal_url = reverse("judge_portal", kwargs={"token": self.token.id})
        portal_res = self.client.get(portal_url)
        self.assertEqual(portal_res.status_code, 200)

        blocks = portal_res.context["group_blocks"]
        self.assertEqual(
            [block["key"] for block in blocks],
            [self.ins_1.grup_competicio_id, extra_1.grup_competicio_id],
        )
        self.assertEqual(blocks[0]["franja_id"], self.franja_2.id)
        self.assertEqual(
            [ins["nom_i_cognoms"] for ins in blocks[0]["list"]],
            ["Participant 1", "Participant 3", "Participant 2"],
        )
        self.assertEqual(blocks[1]["franja_id"], self.franja_3.id)
        self.assertEqual(
            [ins["nom_i_cognoms"] for ins in blocks[1]["list"]],
            ["Participant 5", "Participant 4"],
        )

    def test_judge_portal_franja_override_only_affects_groups_present_in_that_franja(self):
        extra_1 = self._create_inscripcio(self.comp, "Participant 6", ordre=6, grup=3)
        extra_2 = self._create_inscripcio(self.comp, "Participant 7", ordre=7, grup=3)
        Inscripcio.objects.filter(pk=extra_1.pk).update(ordre_competicio=1)
        Inscripcio.objects.filter(pk=extra_2.pk).update(ordre_competicio=2)
        extra_1.refresh_from_db()
        extra_2.refresh_from_db()
        self._assign_group_to_app_franja(extra_1.grup_competicio, self.franja_2)

        portal_url = reverse("judge_portal", kwargs={"token": self.token.id})
        portal_res = self.client.get(portal_url, {"franja": self.franja_3.id})
        self.assertEqual(portal_res.status_code, 200)

        blocks = portal_res.context["group_blocks"]
        self.assertEqual(
            [block["key"] for block in blocks],
            [self.ins_1.grup_competicio_id, extra_1.grup_competicio_id],
        )
        self.assertEqual(blocks[0]["franja_id"], self.franja_3.id)
        self.assertEqual(
            [ins["nom_i_cognoms"] for ins in blocks[0]["list"]],
            ["Participant 3", "Participant 2", "Participant 1"],
        )
        self.assertEqual(blocks[1]["franja_id"], self.franja_2.id)
        self.assertEqual(
            [ins["nom_i_cognoms"] for ins in blocks[1]["list"]],
            ["Participant 7", "Participant 6"],
        )

    def test_judge_portal_uses_group_query_for_active_group(self):
        extra_1 = self._create_inscripcio(self.comp, "Participant 4", ordre=4, grup=2)
        extra_2 = self._create_inscripcio(self.comp, "Participant 5", ordre=5, grup=2)
        Inscripcio.objects.filter(pk=extra_1.pk).update(ordre_competicio=1)
        Inscripcio.objects.filter(pk=extra_2.pk).update(ordre_competicio=2)
        extra_1.refresh_from_db()
        self._assign_group_to_app_franja(extra_1.grup_competicio, self.franja_3)

        portal_url = reverse("judge_portal", kwargs={"token": self.token.id})
        portal_res = self.client.get(portal_url, {"group": extra_1.grup_competicio_id})
        self.assertEqual(portal_res.status_code, 200)
        self.assertEqual(portal_res.context["active_group_key"], extra_1.grup_competicio_id)

        body = portal_res.content.decode("utf-8")
        self.assertRegex(
            body,
            rf'class="nav-link active"\s+data-group-target="group-{extra_1.grup_competicio_id}"',
        )
        self.assertRegex(
            body,
            rf'class="group-pane\s*"\s+data-group-pane="group-{extra_1.grup_competicio_id}"',
        )

    def test_judge_portal_invalid_group_query_falls_back_to_first_visible_group(self):
        extra_1 = self._create_inscripcio(self.comp, "Participant 4", ordre=4, grup=2)
        extra_2 = self._create_inscripcio(self.comp, "Participant 5", ordre=5, grup=2)
        Inscripcio.objects.filter(pk=extra_1.pk).update(ordre_competicio=1)
        Inscripcio.objects.filter(pk=extra_2.pk).update(ordre_competicio=2)
        extra_1.refresh_from_db()
        self._assign_group_to_app_franja(extra_1.grup_competicio, self.franja_3)

        portal_url = reverse("judge_portal", kwargs={"token": self.token.id})
        portal_res = self.client.get(portal_url, {"group": 999999})
        self.assertEqual(portal_res.status_code, 200)
        self.assertEqual(portal_res.context["active_group_key"], portal_res.context["group_blocks"][0]["key"])

    def test_judge_portal_preserves_group_and_initial_exercise_with_franja(self):
        self.comp_app.nombre_exercicis = 3
        self.comp_app.save(update_fields=["nombre_exercicis"])
        portal_url = reverse("judge_portal", kwargs={"token": self.token.id})
        portal_res = self.client.get(
            portal_url,
            {
                "ex": 2,
                "group": self.ins_1.grup_competicio_id,
                "franja": self.franja_3.id,
            },
        )
        self.assertEqual(portal_res.status_code, 200)
        self.assertEqual(portal_res.context["active_group_key"], self.ins_1.grup_competicio_id)
        self.assertEqual(portal_res.context["franja_override_id"], self.franja_3.id)

        body = portal_res.content.decode("utf-8")
        self.assertIn("const EXERCICI_HINT = 2;", body)
        self.assertIn('data-exercise-chip="1"', body)
        self.assertNotIn("data-exercise-link", body)

    def test_judge_portal_uses_compact_display_mode_by_default(self):
        self.comp_app.nombre_exercicis = 2
        self.comp_app.save(update_fields=["nombre_exercicis"])

        portal_url = reverse("judge_portal", kwargs={"token": self.token.id})
        portal_res = self.client.get(portal_url)

        self.assertEqual(portal_res.status_code, 200)
        self.assertEqual(portal_res.context["portal_display_mode"], "compact")
        body = portal_res.content.decode("utf-8")
        self.assertIn('id="insNavDrawer"', body)
        self.assertIn('id="insNavListDrawer"', body)
        self.assertIn('data-exercise-chip="1"', body)
        self.assertNotIn('data-competition-order-panel="1"', body)
        self.assertNotIn('id="insNavListDesktop"', body)
        self.assertNotIn('id="insNavListMobile"', body)
        self.assertIn('id="portalViewModeSelect"', body)

    def test_judge_portal_competition_order_display_groups_by_exercise_then_rotation_order(self):
        extra_1 = self._create_inscripcio(self.comp, "Participant 4", ordre=4, grup=1)
        extra_2 = self._create_inscripcio(self.comp, "Participant 5", ordre=5, grup=1)
        Inscripcio.objects.filter(pk=extra_1.pk).update(ordre_competicio=4)
        Inscripcio.objects.filter(pk=extra_2.pk).update(ordre_competicio=5)
        extra_1.refresh_from_db()
        extra_2.refresh_from_db()
        self.comp_app.nombre_exercicis = 2
        self.comp_app.save(update_fields=["nombre_exercicis"])

        portal_url = reverse("judge_portal", kwargs={"token": self.token.id})
        portal_res = self.client.get(portal_url, {"view_mode": "competition_order"})

        self.assertEqual(portal_res.status_code, 200)
        self.assertEqual(portal_res.context["portal_display_mode"], "competition_order")
        expected_order = [self.ins_1, self.ins_3, extra_1, extra_2, self.ins_2]
        self.assertEqual(
            [ins["subject_id"] for ins in portal_res.context["group_blocks"][0]["list"]],
            [ins.id for ins in expected_order],
        )

        body = portal_res.content.decode("utf-8")
        self.assertNotIn('<button type="button" class="judge-exercise-chip"', body)
        self.assertIn('data-competition-order-panel="1"', body)
        ordered_markers = [
            *(f'id="card-{ins.id}-1"' for ins in expected_order),
            *(f'id="card-{ins.id}-2"' for ins in expected_order),
        ]
        marker_positions = [body.index(marker) for marker in ordered_markers]
        self.assertEqual(marker_positions, sorted(marker_positions))

    def test_judge_portal_invalid_view_mode_falls_back_to_compact(self):
        self.comp_app.nombre_exercicis = 2
        self.comp_app.save(update_fields=["nombre_exercicis"])

        portal_url = reverse("judge_portal", kwargs={"token": self.token.id})
        portal_res = self.client.get(portal_url, {"view_mode": "not-a-mode"})

        self.assertEqual(portal_res.status_code, 200)
        self.assertEqual(portal_res.context["portal_display_mode"], "compact")
        body = portal_res.content.decode("utf-8")
        self.assertIn('data-exercise-chip="1"', body)
        self.assertNotIn('data-competition-order-panel="1"', body)

    def test_judge_portal_bootstraps_polling_contract_and_support_updates_url(self):
        self.token.can_record_video = True
        self.token.save(update_fields=["can_record_video"])
        portal_url = reverse("judge_portal", kwargs={"token": self.token.id})
        portal_res = self.client.get(portal_url)

        self.assertEqual(portal_res.status_code, 200)
        self.assertEqual(
            portal_res.context["save_url"],
            reverse("judge_save_partial", kwargs={"token": self.token.id}),
        )
        self.assertEqual(
            portal_res.context["updates_url"],
            reverse("judge_updates", kwargs={"token": self.token.id}),
        )
        self.assertEqual(
            portal_res.context["video_status_url"],
            reverse("judge_video_status", kwargs={"token": self.token.id}),
        )
        self.assertTrue(portal_res.context["updates_cursor_init"])

        body = portal_res.content.decode("utf-8")
        self.assertIn(reverse("judge_save_partial", kwargs={"token": self.token.id}), body)
        self.assertIn(reverse("judge_updates", kwargs={"token": self.token.id}), body)
        self.assertIn(reverse("judge_video_status", kwargs={"token": self.token.id}), body)
        self.assertIn(reverse("judge_messages_updates", kwargs={"token": self.token.id}), body)
        self.assertIn('id="updates-cursor-init"', body)

    def test_scoring_notes_home_bootstraps_updates_url_and_cursor_contract(self):
        scoring_url = reverse("scoring_notes_home", kwargs={"pk": self.comp.id})
        scoring_res = self.client.get(scoring_url)

        self.assertEqual(scoring_res.status_code, 200)
        self.assertTrue(scoring_res.context["updates_cursor_init"])
        body = scoring_res.content.decode("utf-8")
        self.assertIn(reverse("scoring_updates", kwargs={"pk": self.comp.id}), body)
        self.assertIn('id="updates-cursor-init"', body)
        self.assertIn("const UPDATES_URL = ", body)

    def test_scoring_notes_home_supports_franja_selection_for_programmed_groups(self):
        scoring_url = reverse("scoring_notes_home", kwargs={"pk": self.comp.id})

        default_res = self.client.get(scoring_url)
        self.assertEqual(default_res.status_code, 200)
        default_body = default_res.content.decode("utf-8")
        self.assertNotIn('id="franjaSelect"', default_body)
        self.assertNotIn(">Franja</label>", default_body)
        self.assertIsNone(default_res.context["franja_selected_id"])

        scoring_res = self.client.get(scoring_url, {"franja": self.franja_3.id})
        self.assertEqual(scoring_res.status_code, 200)
        self.assertEqual(scoring_res.context["franja_selected_id"], self.franja_3.id)

        app_key = str(self.comp_app.id)
        self.assertEqual(
            scoring_res.context["rotation_groups_by_app"].get(app_key),
            [self.ins_1.grup_competicio_id],
        )

        rank_map = scoring_res.context["rotation_rank_map"]
        self.assertEqual(rank_map.get(f"{self.comp_app.id}|{self.ins_3.id}"), 1)
        self.assertEqual(rank_map.get(f"{self.comp_app.id}|{self.ins_2.id}"), 2)
        self.assertEqual(rank_map.get(f"{self.comp_app.id}|{self.ins_1.id}"), 3)

    def test_scoring_notes_home_ignores_non_competitive_franja_selection(self):
        scoring_url = reverse("scoring_notes_home", kwargs={"pk": self.comp.id})
        default_res = self.client.get(scoring_url)
        self.assertEqual(default_res.status_code, 200)

        fake_franges = [
            self._franja_stub(self.franja_1, tipus="competition"),
            self._franja_stub(self.franja_2, tipus="competition"),
            self._franja_stub(self.franja_3, tipus="break"),
        ]

        with patch(
            "competicions_trampoli.views.scoring.notes.RotacioFranja.objects.filter"
        ) as mock_filter:
            mock_qs = mock_filter.return_value
            mock_qs.order_by.return_value = fake_franges
            scoring_res = self.client.get(scoring_url, {"franja": self.franja_3.id})

        self.assertEqual(scoring_res.status_code, 200)
        self.assertIsNone(scoring_res.context["franja_selected_id"])
        self.assertEqual(scoring_res.context["rotation_rank_map"], default_res.context["rotation_rank_map"])
        self.assertEqual(
            scoring_res.context["rotation_groups_by_app"],
            default_res.context["rotation_groups_by_app"],
        )

    def test_judge_portal_ignores_non_competitive_franja_override(self):
        portal_url = reverse("judge_portal", kwargs={"token": self.token.id})
        default_res = self.client.get(portal_url)
        self.assertEqual(default_res.status_code, 200)

        fake_franges = [
            self._franja_stub(self.franja_1, tipus="competition"),
            self._franja_stub(self.franja_2, tipus="competition"),
            self._franja_stub(self.franja_3, tipus="awards"),
        ]

        with patch(
            "competicions_trampoli.views.judge.portal.RotacioFranja.objects.filter"
        ) as mock_filter:
            mock_qs = mock_filter.return_value
            mock_qs.order_by.return_value = fake_franges
            portal_res = self.client.get(portal_url, {"franja": self.franja_3.id})

        self.assertEqual(portal_res.status_code, 200)
        self.assertIsNone(portal_res.context["franja_override_id"])
        self.assertEqual(portal_res.context["group_blocks"], default_res.context["group_blocks"])
        self.assertEqual(
            portal_res.context["out_of_program_group_blocks"],
            default_res.context["out_of_program_group_blocks"],
        )
        self.assertEqual(portal_res.context["active_group_key"], default_res.context["active_group_key"])

    def test_out_of_program_visibility_toggle_controls_notes_and_judge_views(self):
        extra_group = GrupCompeticio.objects.create(
            competicio=self.comp,
            display_num=2,
            legacy_num=2,
            nom="Fora Programa",
            actiu=True,
        )
        extra_ins = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Participant Fora Programa",
            ordre_sortida=4,
            grup=2,
            grup_competicio=extra_group,
            ordre_competicio=1,
        )
        ungrouped_ins = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Participant Sense Grup",
            ordre_sortida=5,
            grup=0,
            grup_competicio=None,
            ordre_competicio=1,
        )

        scoring_url = reverse("scoring_notes_home", kwargs={"pk": self.comp.id})
        scoring_res = self.client.get(scoring_url)
        self.assertEqual(scoring_res.status_code, 200)
        self.assertFalse(scoring_res.context["show_out_of_program_in_competition_views"])
        self.assertEqual([g for g, _rows in scoring_res.context["groups"]], [self.ins_1.grup_competicio_id, 0])
        self.assertEqual(scoring_res.context["out_of_program_groups"], [])
        scoring_body = scoring_res.content.decode("utf-8")
        self.assertIn("Sense grup", scoring_body)
        self.assertNotIn("Fora Programa", scoring_body)

        planner_url = reverse("rotacions_planner", kwargs={"pk": self.comp.id})
        planner_res = self.client.get(planner_url)
        self.assertEqual(planner_res.status_code, 200)
        self.assertEqual(planner_res.context["out_of_program_groups_count"], 1)
        self.assertEqual(planner_res.context["out_of_program_members_total"], 1)
        self.assertFalse(planner_res.context["show_out_of_program_in_competition_views"])
        planner_body = planner_res.content.decode("utf-8")
        self.assertIn("Fora de programa", planner_body)
        self.assertIn("Fora Programa", planner_body)

        portal_url = reverse("judge_portal", kwargs={"token": self.token.id})
        portal_res = self.client.get(portal_url)
        self.assertEqual(portal_res.status_code, 200)
        self.assertFalse(portal_res.context["show_out_of_program_in_competition_views"])
        self.assertEqual([block["key"] for block in portal_res.context["group_blocks"]], [self.ins_1.grup_competicio_id, 0])
        self.assertEqual(portal_res.context["out_of_program_group_blocks"], [])
        portal_body = portal_res.content.decode("utf-8")
        self.assertIn(ungrouped_ins.nom_i_cognoms, portal_body)
        self.assertIn("Sense grup", portal_body)
        self.assertNotIn(extra_ins.nom_i_cognoms, portal_body)

        grouped_portal_res = self.client.get(portal_url, {"group": 0})
        self.assertEqual(grouped_portal_res.status_code, 200)
        self.assertEqual(grouped_portal_res.context["active_group_key"], 0)

        toggle_url = reverse("rotacions_out_of_program_visibility_save", kwargs={"pk": self.comp.id})
        toggle_res = self.client.post(
            toggle_url,
            data=json.dumps({"value": True}),
            content_type="application/json",
        )
        self.assertEqual(toggle_res.status_code, 200)
        self.assertJSONEqual(
            toggle_res.content.decode("utf-8"),
            {"ok": True, "value": True},
        )
        self.comp.refresh_from_db()
        self.assertTrue(
            self.comp.inscripcions_view.get("show_out_of_program_in_competition_views")
        )

        scoring_res = self.client.get(scoring_url)
        self.assertEqual(scoring_res.status_code, 200)
        self.assertTrue(scoring_res.context["show_out_of_program_in_competition_views"])
        self.assertEqual([g for g, _rows in scoring_res.context["groups"]], [self.ins_1.grup_competicio_id, 0])
        self.assertEqual([g for g, _rows in scoring_res.context["out_of_program_groups"]], [extra_group.id])
        scoring_body = scoring_res.content.decode("utf-8")
        self.assertIn("Fora de programa", scoring_body)
        self.assertIn("Fora Programa", scoring_body)

        portal_res = self.client.get(portal_url)
        self.assertEqual(portal_res.status_code, 200)
        self.assertTrue(portal_res.context["show_out_of_program_in_competition_views"])
        self.assertEqual([block["key"] for block in portal_res.context["group_blocks"]], [self.ins_1.grup_competicio_id, 0])
        self.assertEqual([block["key"] for block in portal_res.context["out_of_program_group_blocks"]], [extra_group.id])
        portal_body = portal_res.content.decode("utf-8")
        self.assertIn("Fora de programa", portal_body)
        self.assertIn(extra_ins.nom_i_cognoms, portal_body)

    def test_rotacions_planner_sidebar_uses_three_panels_and_updated_labels(self):
        planner_url = reverse("rotacions_planner", kwargs={"pk": self.comp.id})
        planner_res = self.client.get(planner_url)
        self.assertEqual(planner_res.status_code, 200)

        body = planner_res.content.decode("utf-8")
        self.assertContains(planner_res, 'data-drawer-panel-target="programables"')
        self.assertContains(planner_res, 'data-drawer-panel-target="franges"')
        self.assertContains(planner_res, 'data-drawer-panel-target="globals"')
        self.assertContains(planner_res, "Programables")
        self.assertContains(planner_res, "Franges")
        self.assertContains(planner_res, "Operacions globals")
        self.assertContains(planner_res, "No buits")
        self.assertNotContains(planner_res, "Amb subjectes")
        self.assertContains(planner_res, "Mostrar grups fora de programa a notes i jutges")
        self.assertContains(planner_res, "+ Descans")
        self.assertRegex(body, r"Netejar\s+[Pp]rograma")

    def test_rotacions_planner_uses_canonical_sidebar_keys_in_programmed_detection(self):
        planner_url = reverse("rotacions_planner", kwargs={"pk": self.comp.id})
        planner_res = self.client.get(planner_url)
        self.assertEqual(planner_res.status_code, 200)

        body = planner_res.content.decode("utf-8")
        self.assertRegex(body, r'"key"\s*:\s*"g:')
        self.assertRegex(body, r"assigned\.has\([^)]*item\.key")
        self.assertNotIn("Number(item?.id", body)


