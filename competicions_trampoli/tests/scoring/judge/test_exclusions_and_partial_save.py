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
from ....services.classificacions.builder import scoreable_codes_by_app_id as _scoreable_codes_by_app_id
from ....services.classificacions.compute import DEFAULT_SCHEMA, compute_classificacio
from ....services.classificacions.export import _normalize_excel_cell
from ....services.classificacions.partitions import normalize_schema_legacy_team_birth_partition
from ....services.classificacions.validation import (
    build_metric_meta_for_comp_aparell as _build_metric_meta_for_comp_aparell,
    build_scoreable_meta_for_schema as _build_scoreable_meta_for_schema,
    validate_particions_schema as _validate_particions_schema,
    validate_schema_for_competicio as _validate_schema_for_competicio,
)
from ....services.classificacions.classificacio_templates import (
    normalize_particions_schema as _normalize_particions_schema,
    schema_to_template_schema as _schema_to_template_schema,
    template_schema_to_competicio_schema as _template_schema_to_competicio_schema,
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


class ScoringAndJudgeExclusionFlowTests(_BaseTrampoliDataMixin, TestCase):
    def setUp(self):
        self.comp = self._create_competicio("Comp Flux")
        self.app = self._create_aparell("TRAMP_FLOW", "Tramp Flow")
        self.comp_app = self._create_comp_aparell(self.comp, self.app, ordre=1, actiu=True)
        self.comp_app.nombre_exercicis = 3
        self.comp_app.save(update_fields=["nombre_exercicis"])
        ScoringSchema.objects.create(
            aparell=self.app,
            schema={
                "fields": [
                    {
                        "label": "Execucio",
                        "code": "E",
                        "type": "matrix",
                        "shape": "judge_x_item",
                        "judges": {"count": 2},
                        "items": {"count": 5},
                        "decimals": 1,
                        "crash": {"enabled": True},
                    },
                    {
                        "label": "Altre",
                        "code": "X",
                        "type": "matrix",
                        "shape": "judge_x_item",
                        "judges": {"count": 2},
                        "items": {"count": 5},
                        "decimals": 1,
                        "crash": {"enabled": True},
                    },
                ],
                "computed": [],
            },
        )

        self.ins_allowed = self._create_inscripcio(self.comp, "Allowed", ordre=1)
        self.ins_blocked = self._create_inscripcio(self.comp, "Blocked", ordre=2)
        InscripcioAparellExclusio.objects.create(
            inscripcio=self.ins_blocked,
            comp_aparell=self.comp_app,
        )

        self.token = JudgeDeviceToken.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            label="Judge A",
            permissions=[{"field_code": "E", "judge_index": 1}],
            can_record_video=True,
            is_active=True,
        )
        User = get_user_model()
        self.user = User.objects.create_user(
            username="scoring_exclusion_owner",
            password="testpass123",
            email="scoring-exclusion-owner@example.com",
        )
        CompeticioMembership.objects.create(
            user=self.user,
            competicio=self.comp,
            role=CompeticioMembership.Role.OWNER,
            is_active=True,
        )
        self.client.force_login(self.user)

    def test_scoring_save_partial_returns_403_for_excluded_inscripcio(self):
        url = reverse("scoring_save_partial", kwargs={"pk": self.comp.id})
        r = self.client.post(
            url,
            data=json.dumps(
                {
                    "inscripcio_id": self.ins_blocked.id,
                    "comp_aparell_id": self.comp_app.id,
                    "exercici": 1,
                    "inputs_patch": {},
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 403)

    def test_judge_portal_hides_excluded_and_save_returns_403(self):
        portal_url = reverse("judge_portal", kwargs={"token": self.token.id})
        portal_res = self.client.get(portal_url)
        self.assertEqual(portal_res.status_code, 200)
        body = portal_res.content.decode("utf-8")
        self.assertIn("Allowed", body)
        self.assertNotIn("Blocked", body)
        self.assertIn(reverse("judge_video_upload", kwargs={"token": self.token.id}), body)
        self.assertIn(reverse("judge_video_status", kwargs={"token": self.token.id}), body)
        self.assertIn(reverse("judge_video_delete", kwargs={"token": self.token.id}), body)

        save_url = reverse("judge_save_partial", kwargs={"token": self.token.id})
        save_res = self.client.post(
            save_url,
            data=json.dumps(
                {
                    "inscripcio_id": self.ins_blocked.id,
                    "exercici": 1,
                    "inputs_patch": {"E": 1},
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(save_res.status_code, 403)

    def test_judge_portal_supports_ex_query_and_multiex_payload(self):
        portal_url = reverse("judge_portal", kwargs={"token": self.token.id})
        portal_res = self.client.get(portal_url, {"ex": 2})
        self.assertEqual(portal_res.status_code, 200)

        payload = portal_res.context["scores_payload_json"][str(self.ins_allowed.id)]
        self.assertEqual(sorted(payload["exercises"].keys()), ["1", "2", "3"])

        body = portal_res.content.decode("utf-8")
        self.assertIn("const EXERCICI_HINT = 2;", body)
        self.assertIn('data-exercise-chip="1"', body)
        self.assertIn(f'id="editor-inner-{self.ins_allowed.id}-1"', body)
        self.assertIn(f'id="editor-inner-{self.ins_allowed.id}-2"', body)
        self.assertIn(f'id="editor-inner-{self.ins_allowed.id}-3"', body)
        self.assertIn("function getExerciseVisualState(insId, exercici)", body)
        self.assertIn("function getInsVisualState(insId)", body)
        self.assertIn("judge-nav-status", body)
        self.assertIn("judge-nav-ex-chip", body)
        self.assertIn(".judge-nav-link.is-complete", body)
        self.assertIn(".judge-nav-link.is-partial", body)
        self.assertNotIn(".judge-nav-link.is-saved", body)
        self.assertNotIn('href="?ex=1"', body)
        self.assertNotIn('href="?ex=3"', body)

    def test_judge_portal_renders_keyboard_navigation_helpers_for_score_inputs(self):
        portal_url = reverse("judge_portal", kwargs={"token": self.token.id})
        portal_res = self.client.get(portal_url, {"ex": 1})
        self.assertEqual(portal_res.status_code, 200)

        body = portal_res.content.decode("utf-8")
        self.assertIn("function getEditableInputs(insId, exercici)", body)
        self.assertIn("function focusNextEditableInput(currentInput)", body)
        self.assertIn("function focusPrevEditableInput(currentInput)", body)
        self.assertIn("function selectInputContents(input)", body)
        self.assertIn("function bindScoreInputNavigation(input, insId, exercici)", body)
        self.assertIn('input.dataset.insId = String(insId);', body)
        self.assertIn('input.dataset.exercici = exerciseKey(exercici);', body)
        self.assertIn('input.dataset.navScope = "score-input";', body)
        self.assertIn('input.addEventListener("keydown", (evt) => {', body)
        self.assertIn('if(evt.key !== "Enter" && evt.key !== "Tab") return;', body)
        self.assertIn('if(evt.key === "Tab" && evt.shiftKey){', body)
        self.assertIn("focusNextEditableInput(input);", body)
        self.assertIn("focusPrevEditableInput(input);", body)
        self.assertIn(".filter((input) => !input.disabled);", body)
        self.assertIn('[data-exercise-panel="1"][data-ins-id="${String(insId)}"][data-exercici="${exerciseKey(exercici)}"]', body)
        self.assertIn("selectInputContents(input);", body)
        self.assertIn("bindScoreInputNavigation(inp, insId, exercici);", body)
        self.assertNotIn("value.length", body)

    def test_judge_portal_nav_visual_status_uses_per_exercise_semantics(self):
        ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins_allowed,
            exercici=1,
            comp_aparell=self.comp_app,
            inputs={"E": [0.2, 0.3, 0.4, 0.5, 0.6]},
            outputs={},
            total=1,
        )
        portal_url = reverse("judge_portal", kwargs={"token": self.token.id})
        portal_res = self.client.get(portal_url)
        self.assertEqual(portal_res.status_code, 200)

        payload = portal_res.context["scores_payload_json"][str(self.ins_allowed.id)]
        self.assertEqual(payload["exercises"]["1"]["inputs"]["E"], [0.2, 0.3, 0.4, 0.5, 0.6])
        self.assertEqual(payload["exercises"]["2"]["inputs"], {})
        self.assertEqual(payload["exercises"]["3"]["inputs"], {})

        body = portal_res.content.decode("utf-8")
        self.assertIn('data-nav-status="1"', body)
        self.assertIn('data-nav-ex-chip="1"', body)
        self.assertIn("Complet", body)
        self.assertIn("Parcial", body)
        self.assertIn("Pendent", body)

    def test_judge_portal_hides_video_controls_when_video_disabled(self):
        self.token.can_record_video = False
        self.token.save(update_fields=["can_record_video"])
        portal_url = reverse("judge_portal", kwargs={"token": self.token.id})
        portal_res = self.client.get(portal_url, {"ex": 1})
        self.assertEqual(portal_res.status_code, 200)
        body = portal_res.content.decode("utf-8")
        self.assertNotIn('id="video-rec-btn-', body)
        self.assertIn("Gravacio desactivada per aquest QR.", body)

    def test_judge_save_partial_accepts_crash_for_authorized_field(self):
        save_url = reverse("judge_save_partial", kwargs={"token": self.token.id})
        save_res = self.client.post(
            save_url,
            data=json.dumps(
                {
                    "inscripcio_id": self.ins_allowed.id,
                    "exercici": 1,
                    "inputs_patch": {
                        "E": [0.2, 0.3, 0.4, 0.5, 0.6],
                        "__crash__E": [3, 2],
                    },
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(save_res.status_code, 200)
        payload = save_res.json()
        self.assertTrue(payload.get("ok"))
        self.assertEqual(payload.get("inputs", {}).get("__crash__E", [None])[0], 3)

        entry = ScoreEntry.objects.get(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            inscripcio=self.ins_allowed,
            exercici=1,
        )
        self.assertEqual(entry.inputs.get("__crash__E", [None, None])[0], 3)
        self.assertEqual(entry.inputs.get("__crash__E", [None, None])[1], 0)

    def test_judge_save_partial_rejects_crash_for_unauthorized_field(self):
        save_url = reverse("judge_save_partial", kwargs={"token": self.token.id})
        save_res = self.client.post(
            save_url,
            data=json.dumps(
                {
                    "inscripcio_id": self.ins_allowed.id,
                    "exercici": 1,
                    "inputs_patch": {"__crash__X": [2, 0]},
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(save_res.status_code, 403)

    def test_judge_save_partial_clamps_exercici_to_aparell_max(self):
        save_url = reverse("judge_save_partial", kwargs={"token": self.token.id})
        save_res = self.client.post(
            save_url,
            data=json.dumps(
                {
                    "inscripcio_id": self.ins_allowed.id,
                    "exercici": 99,
                    "inputs_patch": {
                        "E": [0.2, 0.3, 0.4, 0.5, 0.6],
                    },
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(save_res.status_code, 200)
        entry = ScoreEntry.objects.get(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            inscripcio=self.ins_allowed,
            exercici=3,
        )
        self.assertIsNotNone(entry)
        self.assertFalse(
            ScoreEntry.objects.filter(
                competicio=self.comp,
                comp_aparell=self.comp_app,
                inscripcio=self.ins_allowed,
                exercici=99,
            ).exists()
        )

    def test_scoring_updates_omits_excluded_entries(self):
        ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins_allowed,
            exercici=1,
            comp_aparell=self.comp_app,
            inputs={},
            outputs={},
            total=1,
        )
        ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins_blocked,
            exercici=1,
            comp_aparell=self.comp_app,
            inputs={},
            outputs={},
            total=2,
        )

        since = (timezone.now() - timedelta(minutes=10)).isoformat()
        url = reverse("scoring_updates", kwargs={"pk": self.comp.id})
        r = self.client.get(url, {"since": since})

        self.assertEqual(r.status_code, 200)
        payload = r.json()
        updated_ids = {u["inscripcio_id"] for u in payload.get("updates", [])}

        self.assertIn(self.ins_allowed.id, updated_ids)
        self.assertNotIn(self.ins_blocked.id, updated_ids)

    def test_judge_updates_accept_multiple_exercicis(self):
        ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins_allowed,
            exercici=1,
            comp_aparell=self.comp_app,
            inputs={"E": [0.2, 0, 0, 0, 0]},
            outputs={},
            total=1,
        )
        ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins_allowed,
            exercici=2,
            comp_aparell=self.comp_app,
            inputs={"E": [0.4, 0, 0, 0, 0]},
            outputs={},
            total=2,
        )
        ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins_blocked,
            exercici=2,
            comp_aparell=self.comp_app,
            inputs={"E": [0.6, 0, 0, 0, 0]},
            outputs={},
            total=3,
        )

        since = (timezone.now() - timedelta(minutes=10)).isoformat()
        url = reverse("judge_updates", kwargs={"token": self.token.id})
        res = self.client.get(url, {"since": since, "exercici": [1, 2]})

        self.assertEqual(res.status_code, 200)
        payload = res.json()
        updates = payload.get("updates", [])
        self.assertEqual({u["exercici"] for u in updates}, {1, 2})
        self.assertEqual({u["inscripcio_id"] for u in updates}, {self.ins_allowed.id})

    def test_judge_updates_without_since_returns_empty_feed_contract(self):
        url = reverse("judge_updates", kwargs={"token": self.token.id})
        res = self.client.get(url)

        self.assertEqual(res.status_code, 200)
        self.assertJSONEqual(
            res.content.decode("utf-8"),
            {
                "ok": True,
                "now": None,
                "updates": [],
                "next_since": None,
                "next_after_id": "",
                "has_more": False,
            },
        )

    def test_judge_updates_filter_inputs_by_token_permissions(self):
        ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins_allowed,
            exercici=1,
            comp_aparell=self.comp_app,
            inputs={
                "E": [0.2, 0.3, 0.4, 0.5, 0.6],
                "X": [1.0, 1.1, 1.2, 1.3, 1.4],
            },
            outputs={},
            total=2.0,
        )

        url = reverse("judge_updates", kwargs={"token": self.token.id})
        res = self.client.get(url, {"since": (timezone.now() - timedelta(minutes=10)).isoformat(), "exercici": 1})

        self.assertEqual(res.status_code, 200)
        updates = res.json().get("updates", [])
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0]["inscripcio_id"], self.ins_allowed.id)
        self.assertEqual(updates[0]["inputs"], {"E": [0.2, 0.3, 0.4, 0.5, 0.6]})
        self.assertNotIn("X", updates[0]["inputs"])


