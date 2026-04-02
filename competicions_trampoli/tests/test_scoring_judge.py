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
from ..views import (
    COLUMN_FILTER_EMPTY_TOKEN,
    _build_inscripcions_filtered_qs,
    apply_inscripcions_history_snapshot,
    build_inscripcions_sort_context_key,
    _split_custom_sort_tokens,
    capture_inscripcions_history_snapshot,
    renumber_groups_for_competicio,
    get_competicio_custom_sort_rank_map,
    sort_records_by_field_stable,
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

from .base import _BaseTrampoliDataMixin


class ScoringMediaPlaybackContextTests(_BaseTrampoliDataMixin, TestCase):
    def setUp(self):
        self.comp = self._create_competicio("Comp Media Notes")
        self.ins = self._create_inscripcio(self.comp, "Participant Reproductor")

        self.app = self._create_aparell("TRAMP_MEDIA", "Tramp Media")
        self.comp_app = self._create_comp_aparell(self.comp, self.app, ordre=1, actiu=True)

        User = get_user_model()
        self.user = User.objects.create_user(
            username="scoring_media_owner",
            password="testpass123",
            email="scoring-media-owner@example.com",
        )
        CompeticioMembership.objects.create(
            user=self.user,
            competicio=self.comp,
            role=CompeticioMembership.Role.OWNER,
            is_active=True,
        )
        self.client.force_login(self.user)

    def test_media_context_orders_tracks_and_keeps_judge_video_separate(self):
        InscripcioMedia.objects.create(
            competicio=self.comp,
            inscripcio=self.ins,
            fitxer=SimpleUploadedFile("a-main.mp3", b"aaa", content_type="audio/mpeg"),
            tipus=InscripcioMedia.Tipus.AUDIO,
            mime_type="audio/mpeg",
            original_filename="a-main.mp3",
            file_size_bytes=3,
            is_primary=True,
        )
        InscripcioMedia.objects.create(
            competicio=self.comp,
            inscripcio=self.ins,
            fitxer=SimpleUploadedFile("a-alt.mp3", b"bbb", content_type="audio/mpeg"),
            tipus=InscripcioMedia.Tipus.AUDIO,
            mime_type="audio/mpeg",
            original_filename="a-alt.mp3",
            file_size_bytes=3,
            is_primary=False,
        )
        InscripcioMedia.objects.create(
            competicio=self.comp,
            inscripcio=self.ins,
            fitxer=SimpleUploadedFile("v-main.mp4", b"1111", content_type="video/mp4"),
            tipus=InscripcioMedia.Tipus.VIDEO,
            mime_type="video/mp4",
            original_filename="v-main.mp4",
            file_size_bytes=4,
            is_primary=True,
        )
        InscripcioMedia.objects.create(
            competicio=self.comp,
            inscripcio=self.ins,
            fitxer=SimpleUploadedFile("v-alt.mp4", b"2222", content_type="video/mp4"),
            tipus=InscripcioMedia.Tipus.VIDEO,
            mime_type="video/mp4",
            original_filename="v-alt.mp4",
            file_size_bytes=4,
            is_primary=False,
        )

        entry = ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins,
            exercici=1,
            comp_aparell=self.comp_app,
            inputs={},
            outputs={},
            total=0,
        )
        ScoreEntryVideo.objects.create(
            score_entry=entry,
            video_file=SimpleUploadedFile("judge.mp4", b"3333", content_type="video/mp4"),
            status=ScoreEntryVideo.Status.READY,
            file_size_bytes=4,
            mime_type="video/mp4",
            original_filename="judge.mp4",
        )

        url = reverse("scoring_media_context", kwargs={"pk": self.comp.id})
        res = self.client.get(
            url,
            {
                "inscripcio_id": self.ins.id,
                "comp_aparell_id": self.comp_app.id,
                "exercici": 1,
            },
        )
        self.assertEqual(res.status_code, 200)
        payload = res.json()
        self.assertTrue(payload.get("ok"))

        media = payload.get("media", {})
        self.assertEqual((media.get("audio_primary") or {}).get("original_filename"), "a-main.mp3")
        self.assertEqual(
            [x.get("original_filename") for x in media.get("audio_others", [])],
            ["a-alt.mp3"],
        )
        self.assertEqual((media.get("video_primary") or {}).get("original_filename"), "v-main.mp4")
        self.assertEqual(
            [x.get("original_filename") for x in media.get("video_others", [])],
            ["v-alt.mp4"],
        )
        self.assertEqual((payload.get("judge_video") or {}).get("original_filename"), "judge.mp4")
        self.assertIn(reverse("scoring_media_file", kwargs={"pk": self.comp.id, "media_id": media["audio_primary"]["id"]}), (media.get("audio_primary") or {}).get("url", ""))
        self.assertIn(
            reverse("scoring_judge_video_file", kwargs={"pk": self.comp.id, "video_kind": "individual", "video_id": payload["judge_video"]["id"]}),
            (payload.get("judge_video") or {}).get("url", ""),
        )

    def test_media_context_rejects_foreign_comp_aparell(self):
        other_comp = self._create_competicio("Comp Altre Media")
        other_app = self._create_aparell("TRAMP_MEDIA_X", "Tramp Media X")
        other_comp_app = self._create_comp_aparell(other_comp, other_app, ordre=1, actiu=True)

        url = reverse("scoring_media_context", kwargs={"pk": self.comp.id})
        res = self.client.get(
            url,
            {
                "inscripcio_id": self.ins.id,
                "comp_aparell_id": other_comp_app.id,
                "exercici": 1,
            },
        )
        self.assertEqual(res.status_code, 400)

    def test_scoring_notes_home_context_includes_media_counts_and_judge_presence(self):
        ins_without_media = self._create_inscripcio(self.comp, "Participant Sense Media", ordre=2, grup=1)

        InscripcioMedia.objects.create(
            competicio=self.comp,
            inscripcio=self.ins,
            fitxer=SimpleUploadedFile("ctx-audio.mp3", b"aaa", content_type="audio/mpeg"),
            tipus=InscripcioMedia.Tipus.AUDIO,
            mime_type="audio/mpeg",
            original_filename="ctx-audio.mp3",
            file_size_bytes=3,
            is_primary=True,
        )
        InscripcioMedia.objects.create(
            competicio=self.comp,
            inscripcio=self.ins,
            fitxer=SimpleUploadedFile("ctx-video.mp4", b"bbbb", content_type="video/mp4"),
            tipus=InscripcioMedia.Tipus.VIDEO,
            mime_type="video/mp4",
            original_filename="ctx-video.mp4",
            file_size_bytes=4,
            is_primary=True,
        )

        entry = ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins,
            exercici=1,
            comp_aparell=self.comp_app,
            inputs={},
            outputs={},
            total=0,
        )
        ScoreEntryVideo.objects.create(
            score_entry=entry,
            video_file=SimpleUploadedFile("ctx-judge.mp4", b"cccc", content_type="video/mp4"),
            status=ScoreEntryVideo.Status.READY,
            file_size_bytes=4,
            mime_type="video/mp4",
            original_filename="ctx-judge.mp4",
        )

        url = reverse("scoring_notes_home", kwargs={"pk": self.comp.id})
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)

        media_counts = res.context["media_counts_by_inscripcio"]
        self.assertEqual(media_counts[str(self.ins.id)]["audio"], 1)
        self.assertEqual(media_counts[str(self.ins.id)]["video"], 1)
        self.assertEqual(media_counts[str(ins_without_media.id)]["audio"], 0)
        self.assertEqual(media_counts[str(ins_without_media.id)]["video"], 0)

        judge_map = res.context["judge_video_presence_by_key"]
        self.assertEqual(int(judge_map.get(f"{self.ins.id}|1|{self.comp_app.id}") or 0), 1)
        self.assertEqual(int(judge_map.get(f"{ins_without_media.id}|1|{self.comp_app.id}") or 0), 0)

    def test_scoring_notes_home_queues_remote_rerender_while_local_row_is_editing(self):
        url = reverse("scoring_notes_home", kwargs={"pk": self.comp.id})
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)

        body = res.content.decode("utf-8")
        self.assertIn("const pendingRemoteScoreKeys = new Set();", body)
        self.assertIn("function isEditingScoreKey(scoreKey){", body)
        self.assertIn("markScoreKeyPendingRemoteRerender(scoreKey);", body)
        self.assertIn("setTimeout(()=>flushPendingRemoteRerender(scoreKey), 0);", body)
        self.assertIn("rerenderTablesForScoreKey(scoreKey);", body)


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


class JudgeVideoApiTests(_BaseTrampoliDataMixin, TestCase):
    def setUp(self):
        self.comp = self._create_competicio("Comp Video")
        self.app = self._create_aparell("TRAMP_VIDEO", "Tramp Video")
        self.comp_app = self._create_comp_aparell(self.comp, self.app, ordre=1, actiu=True)

        self.ins_allowed = self._create_inscripcio(self.comp, "Allowed", ordre=1)
        self.ins_blocked = self._create_inscripcio(self.comp, "Blocked", ordre=2)
        InscripcioAparellExclusio.objects.create(
            inscripcio=self.ins_blocked,
            comp_aparell=self.comp_app,
        )

        self.token = JudgeDeviceToken.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            label="Judge Video",
            permissions=[{"field_code": "E", "judge_index": 1}],
            can_record_video=True,
            is_active=True,
        )
        self._probe_patcher = patch(
            "competicions_trampoli.views_judge._probe_uploaded_video_metadata",
            side_effect=self._fake_probe_uploaded_video_metadata,
        )
        self._probe_patcher.start()
        self.addCleanup(self._probe_patcher.stop)

    @staticmethod
    def _fake_probe_uploaded_video_metadata(uploaded_file):
        from ..views_judge import VideoValidationError

        name = (getattr(uploaded_file, "name", "") or "").lower()
        if name.endswith(".txt"):
            raise VideoValidationError(
                "Tipus MIME no permes: text/plain",
                reason="mime_not_allowed",
                payload={"mime_type": "text/plain", "format_name": "text"},
            )
        return {
            "duration_seconds": 12,
            "mime_type": "video/mp4",
            "format_name": "mp4",
            "video_codec": "h264",
        }

    def _sample_video(self, name="routine.mp4", size=1024):
        return SimpleUploadedFile(name, b"\x00" * size, content_type="video/mp4")

    def test_video_upload_creates_scoreentry_and_video(self):
        upload_url = reverse("judge_video_upload", kwargs={"token": self.token.id})
        r = self.client.post(
            upload_url,
            data={
                "inscripcio_id": self.ins_allowed.id,
                "exercici": 1,
                "duration_seconds": 12,
                "video_file": self._sample_video(),
            },
        )
        self.assertEqual(r.status_code, 200)
        payload = r.json()
        self.assertTrue(payload.get("ok"))
        self.assertTrue(payload.get("created"))
        self.assertIn(
            reverse(
                "judge_video_file",
                kwargs={
                    "token": self.token.id,
                    "subject_kind": "inscripcio",
                    "subject_id": self.ins_allowed.id,
                    "exercici": 1,
                },
            ),
            ((payload.get("video") or {}).get("url") or ""),
        )

        entry = ScoreEntry.objects.get(
            competicio=self.comp,
            inscripcio=self.ins_allowed,
            exercici=1,
            comp_aparell=self.comp_app,
        )
        video = ScoreEntryVideo.objects.get(score_entry=entry)
        self.assertEqual(video.status, ScoreEntryVideo.Status.READY)
        self.assertEqual(video.mime_type, "video/mp4")
        self.assertEqual(video.duration_seconds, 12)
        self.assertEqual(video.judge_token_id, self.token.id)
        ev = ScoreEntryVideoEvent.objects.filter(
            action=ScoreEntryVideoEvent.Action.UPLOAD,
            score_entry=entry,
            video=video,
            ok=True,
        ).first()
        self.assertIsNotNone(ev)

    def test_video_status_returns_false_when_absent(self):
        status_url = reverse("judge_video_status", kwargs={"token": self.token.id})
        r = self.client.get(status_url, {"inscripcio_id": self.ins_allowed.id, "exercici": 1})
        self.assertEqual(r.status_code, 200)
        payload = r.json()
        self.assertTrue(payload.get("ok"))
        self.assertFalse(payload.get("has_video"))

    def test_video_endpoints_return_403_when_token_video_disabled(self):
        token_no_video = JudgeDeviceToken.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            label="Judge No Video",
            permissions=[{"field_code": "E", "judge_index": 1}],
            is_active=True,
        )
        status_url = reverse("judge_video_status", kwargs={"token": token_no_video.id})
        upload_url = reverse("judge_video_upload", kwargs={"token": token_no_video.id})
        delete_url = reverse("judge_video_delete", kwargs={"token": token_no_video.id})

        status_res = self.client.get(status_url, {"inscripcio_id": self.ins_allowed.id, "exercici": 1})
        self.assertEqual(status_res.status_code, 403)
        self.assertEqual(status_res.json().get("reason"), "video_disabled")

        upload_res = self.client.post(
            upload_url,
            data={
                "inscripcio_id": self.ins_allowed.id,
                "exercici": 1,
                "video_file": self._sample_video(),
            },
        )
        self.assertEqual(upload_res.status_code, 403)
        self.assertEqual(upload_res.json().get("reason"), "video_disabled")

        delete_res = self.client.post(
            delete_url,
            data={
                "inscripcio_id": self.ins_allowed.id,
                "exercici": 1,
            },
        )
        self.assertEqual(delete_res.status_code, 403)
        self.assertEqual(delete_res.json().get("reason"), "video_disabled")

    def test_video_upload_rejects_excluded_inscripcio(self):
        upload_url = reverse("judge_video_upload", kwargs={"token": self.token.id})
        r = self.client.post(
            upload_url,
            data={
                "inscripcio_id": self.ins_blocked.id,
                "exercici": 1,
                "video_file": self._sample_video(),
            },
        )
        self.assertEqual(r.status_code, 403)
        self.assertTrue(
            ScoreEntryVideoEvent.objects.filter(
                action=ScoreEntryVideoEvent.Action.UPLOAD_REJECTED,
                inscripcio=self.ins_blocked,
                ok=False,
            ).exists()
        )

    def test_video_upload_rejects_invalid_mime(self):
        upload_url = reverse("judge_video_upload", kwargs={"token": self.token.id})
        bad_file = SimpleUploadedFile("routine.txt", b"abc", content_type="text/plain")
        r = self.client.post(
            upload_url,
            data={
                "inscripcio_id": self.ins_allowed.id,
                "exercici": 1,
                "video_file": bad_file,
            },
        )
        self.assertEqual(r.status_code, 400)
        self.assertTrue(
            ScoreEntryVideoEvent.objects.filter(
                action=ScoreEntryVideoEvent.Action.UPLOAD_REJECTED,
                inscripcio=self.ins_allowed,
                ok=False,
            ).exists()
        )

    def test_video_upload_rejects_file_too_large(self):
        old_limit = ScoreEntryVideo.VIDEO_MAX_SIZE_BYTES
        try:
            ScoreEntryVideo.VIDEO_MAX_SIZE_BYTES = 100
            upload_url = reverse("judge_video_upload", kwargs={"token": self.token.id})
            r = self.client.post(
                upload_url,
                data={
                    "inscripcio_id": self.ins_allowed.id,
                    "exercici": 1,
                    "video_file": self._sample_video(size=256),
                },
            )
            self.assertEqual(r.status_code, 400)
            self.assertTrue(
                ScoreEntryVideoEvent.objects.filter(
                    action=ScoreEntryVideoEvent.Action.UPLOAD_REJECTED,
                    inscripcio=self.ins_allowed,
                    ok=False,
                ).exists()
            )
        finally:
            ScoreEntryVideo.VIDEO_MAX_SIZE_BYTES = old_limit

    def test_second_upload_creates_replace_event(self):
        upload_url = reverse("judge_video_upload", kwargs={"token": self.token.id})
        r1 = self.client.post(
            upload_url,
            data={
                "inscripcio_id": self.ins_allowed.id,
                "exercici": 1,
                "video_file": self._sample_video(name="first.mp4", size=1024),
            },
        )
        self.assertEqual(r1.status_code, 200)

        r2 = self.client.post(
            upload_url,
            data={
                "inscripcio_id": self.ins_allowed.id,
                "exercici": 1,
                "video_file": self._sample_video(name="second.mp4", size=1024),
            },
        )
        self.assertEqual(r2.status_code, 200)

        entry = ScoreEntry.objects.get(
            competicio=self.comp,
            inscripcio=self.ins_allowed,
            exercici=1,
            comp_aparell=self.comp_app,
        )
        self.assertTrue(
            ScoreEntryVideoEvent.objects.filter(
                action=ScoreEntryVideoEvent.Action.REPLACE,
                score_entry=entry,
                ok=True,
            ).exists()
        )

    def test_other_token_cannot_replace_or_delete_existing_video(self):
        upload_url = reverse("judge_video_upload", kwargs={"token": self.token.id})
        self.assertEqual(
            self.client.post(
                upload_url,
                data={
                    "inscripcio_id": self.ins_allowed.id,
                    "exercici": 1,
                    "video_file": self._sample_video(name="owner.mp4", size=1024),
                },
            ).status_code,
            200,
        )

        other_token = JudgeDeviceToken.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            label="Judge Video 2",
            permissions=[{"field_code": "E", "judge_index": 2}],
            can_record_video=True,
            is_active=True,
        )
        other_upload_url = reverse("judge_video_upload", kwargs={"token": other_token.id})
        other_delete_url = reverse("judge_video_delete", kwargs={"token": other_token.id})

        upload_res = self.client.post(
            other_upload_url,
            data={
                "inscripcio_id": self.ins_allowed.id,
                "exercici": 1,
                "video_file": self._sample_video(name="other.mp4", size=1024),
            },
        )
        self.assertEqual(upload_res.status_code, 403)

        delete_res = self.client.post(
            other_delete_url,
            data={"inscripcio_id": self.ins_allowed.id, "exercici": 1},
        )
        self.assertEqual(delete_res.status_code, 403)

    def test_video_delete_removes_existing_capture(self):
        upload_url = reverse("judge_video_upload", kwargs={"token": self.token.id})
        delete_url = reverse("judge_video_delete", kwargs={"token": self.token.id})

        r_upload = self.client.post(
            upload_url,
            data={
                "inscripcio_id": self.ins_allowed.id,
                "exercici": 1,
                "video_file": self._sample_video(),
            },
        )
        self.assertEqual(r_upload.status_code, 200)

        r_delete = self.client.post(
            delete_url,
            data={
                "inscripcio_id": self.ins_allowed.id,
                "exercici": 1,
            },
        )
        self.assertEqual(r_delete.status_code, 200)
        payload = r_delete.json()
        self.assertTrue(payload.get("ok"))
        self.assertTrue(payload.get("deleted"))

        entry = ScoreEntry.objects.get(
            competicio=self.comp,
            inscripcio=self.ins_allowed,
            exercici=1,
            comp_aparell=self.comp_app,
        )
        self.assertFalse(ScoreEntryVideo.objects.filter(score_entry=entry).exists())
        self.assertTrue(
            ScoreEntryVideoEvent.objects.filter(
                action=ScoreEntryVideoEvent.Action.DELETE,
                score_entry=entry,
                ok=True,
            ).exists()
        )


class JudgeMessagingFlowTests(_BaseTrampoliDataMixin, TestCase):
    def setUp(self):
        self.comp = self._create_competicio("Comp Missatgeria")
        self.app = self._create_aparell("TRAMP_MSG", "Trampoli Msg")
        self.comp_app = self._create_comp_aparell(self.comp, self.app, ordre=1, actiu=True)

        self.token = JudgeDeviceToken.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            label="Judge Msg A",
            permissions=[{"field_code": "E", "judge_index": 1}],
            is_active=True,
        )

        User = get_user_model()
        self.manager_user = User.objects.create_user(
            username="judge_msg_manager",
            password="testpass123",
            email="judge-msg-manager@example.com",
        )
        self.readonly_user = User.objects.create_user(
            username="judge_msg_readonly",
            password="testpass123",
            email="judge-msg-readonly@example.com",
        )
        CompeticioMembership.objects.create(
            user=self.manager_user,
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

    def test_quick_support_creates_requested_conversation_without_explicit_text(self):
        url = reverse("judge_request_support", kwargs={"token": self.token.id})
        res = self.client.post(
            url,
            data=json.dumps({}),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)
        payload = res.json()
        self.assertTrue(payload.get("ok"))
        self.assertTrue(payload.get("quick"))

        conv = JudgeConversation.objects.get(judge_token=self.token)
        self.assertEqual(conv.status, JudgeConversation.Status.REQUESTED)
        self.assertGreaterEqual(conv.unread_for_org, 1)

        msg = JudgeConversationMessage.objects.get(conversation=conv)
        self.assertEqual(msg.message_type, JudgeConversationMessage.MessageType.SUPPORT_REQUEST_QUICK)
        self.assertIn("assistencia", (msg.text or "").lower())

    def test_quick_support_has_cooldown(self):
        url = reverse("judge_request_support", kwargs={"token": self.token.id})
        first = self.client.post(url, data=json.dumps({}), content_type="application/json")
        self.assertEqual(first.status_code, 200)

        second = self.client.post(url, data=json.dumps({}), content_type="application/json")
        self.assertEqual(second.status_code, 429)
        self.assertEqual(second.json().get("reason"), "cooldown")

    def test_judge_updates_include_org_instruction(self):
        request_url = reverse("judge_request_support", kwargs={"token": self.token.id})
        self.client.post(request_url, data=json.dumps({}), content_type="application/json")

        send_url = reverse("judge_messages_send_org", kwargs={"competicio_id": self.comp.id})
        self.client.force_login(self.manager_user)
        send_res = self.client.post(
            send_url,
            data=json.dumps(
                {
                    "judge_token_id": str(self.token.id),
                    "message_type": "instruction",
                    "text": "Reinicia tauleta i revisa connexio.",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(send_res.status_code, 200)
        self.client.logout()

        updates_url = reverse("judge_messages_updates", kwargs={"token": self.token.id})
        updates_res = self.client.get(updates_url)
        self.assertEqual(updates_res.status_code, 200)
        rows = updates_res.json().get("messages", [])
        self.assertTrue(any("Reinicia tauleta" in (x.get("text") or "") for x in rows))

    def test_org_hub_requires_judge_messages_capability(self):
        hub_url = reverse("judge_messages_hub", kwargs={"competicio_id": self.comp.id})

        self.client.force_login(self.manager_user)
        ok_res = self.client.get(hub_url)
        self.assertEqual(ok_res.status_code, 200)
        self.client.logout()

        self.client.force_login(self.readonly_user)
        denied_res = self.client.get(hub_url)
        self.assertEqual(denied_res.status_code, 403)

    def test_org_can_open_conversation_by_token_and_mark_resolved(self):
        send_url = reverse("judge_messages_send_org", kwargs={"competicio_id": self.comp.id})
        self.client.force_login(self.manager_user)
        send_res = self.client.post(
            send_url,
            data=json.dumps(
                {
                    "judge_token_id": str(self.token.id),
                    "message_type": "instruction",
                    "text": "Passa al mode offline.",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(send_res.status_code, 200)
        conv_id = send_res.json().get("conversation", {}).get("id")
        self.assertTrue(conv_id)

        status_url = reverse("judge_messages_set_status_org", kwargs={"competicio_id": self.comp.id})
        status_res = self.client.post(
            status_url,
            data=json.dumps({"conversation_id": conv_id, "status": "resolved"}),
            content_type="application/json",
        )
        self.assertEqual(status_res.status_code, 200)
        conv = JudgeConversation.objects.get(pk=conv_id)
        self.assertEqual(conv.status, JudgeConversation.Status.RESOLVED)
        self.assertTrue(conv.resolved_at is not None)

    def test_judge_messages_updates_use_cursor_after_id_for_same_timestamp(self):
        self.client.post(
            reverse("judge_request_support", kwargs={"token": self.token.id}),
            data=json.dumps({}),
            content_type="application/json",
        )
        conversation = JudgeConversation.objects.get(judge_token=self.token)
        JudgeConversationMessage.objects.filter(conversation=conversation).delete()
        base_time = timezone.now()
        msg_1 = JudgeConversationMessage.objects.create(
            conversation=conversation,
            sender_type=JudgeConversationMessage.SenderType.ORGANIZATION,
            message_type=JudgeConversationMessage.MessageType.REPLY,
            text="M1",
        )
        msg_2 = JudgeConversationMessage.objects.create(
            conversation=conversation,
            sender_type=JudgeConversationMessage.SenderType.ORGANIZATION,
            message_type=JudgeConversationMessage.MessageType.REPLY,
            text="M2",
        )
        msg_3 = JudgeConversationMessage.objects.create(
            conversation=conversation,
            sender_type=JudgeConversationMessage.SenderType.ORGANIZATION,
            message_type=JudgeConversationMessage.MessageType.REPLY,
            text="M3",
        )
        JudgeConversationMessage.objects.filter(pk__in=[msg_1.id, msg_2.id, msg_3.id]).update(created_at=base_time)

        updates_url = reverse("judge_messages_updates", kwargs={"token": self.token.id})
        with patch("competicions_trampoli.views_judge_messages.JUDGE_MESSAGES_DELTA_LIMIT", 2):
            first_res = self.client.get(
                updates_url,
                {"since": (base_time - timedelta(seconds=1)).isoformat()},
            )
            self.assertEqual(first_res.status_code, 200)
            first_body = first_res.json()
            self.assertTrue(first_body.get("has_more"))
            self.assertEqual([row["text"] for row in first_body.get("messages", [])], ["M1", "M2"])

            second_res = self.client.get(
                updates_url,
                {
                    "since": first_body.get("next_since"),
                    "after_id": first_body.get("next_after_id"),
                },
            )
        self.assertEqual(second_res.status_code, 200)
        self.assertEqual([row["text"] for row in second_res.json().get("messages", [])], ["M3"])


class ScoringUpdatesCursorTests(_BaseTrampoliDataMixin, TestCase):
    def setUp(self):
        self.comp = self._create_competicio("Comp Scoring Cursor")
        self.app = self._create_aparell("TRAMP_CURSOR", "Tramp Cursor")
        self.comp_app = self._create_comp_aparell(self.comp, self.app, ordre=1, actiu=True)
        self.ins_1 = self._create_inscripcio(self.comp, "P1", ordre=1)
        self.ins_2 = self._create_inscripcio(self.comp, "P2", ordre=2)
        self.ins_3 = self._create_inscripcio(self.comp, "P3", ordre=3)
        User = get_user_model()
        self.user = User.objects.create_user(
            username="scoring_cursor_user",
            password="testpass123",
            email="scoring-cursor@example.com",
        )
        CompeticioMembership.objects.create(
            user=self.user,
            competicio=self.comp,
            role=CompeticioMembership.Role.SCORING,
            is_active=True,
        )
        self.client.force_login(self.user)

    def test_scoring_updates_use_after_id_for_same_timestamp(self):
        base_time = timezone.now()
        e1 = ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins_1,
            exercici=1,
            comp_aparell=self.comp_app,
            inputs={},
            outputs={},
            total=1,
        )
        e2 = ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins_2,
            exercici=1,
            comp_aparell=self.comp_app,
            inputs={},
            outputs={},
            total=2,
        )
        e3 = ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins_3,
            exercici=1,
            comp_aparell=self.comp_app,
            inputs={},
            outputs={},
            total=3,
        )
        ScoreEntry.objects.filter(pk__in=[e1.id, e2.id, e3.id]).update(updated_at=base_time)

        url = reverse("scoring_updates", kwargs={"pk": self.comp.id})
        with patch("competicions_trampoli.views_scoring.SCORING_UPDATES_LIMIT", 2):
            first_res = self.client.get(url, {"since": (base_time - timedelta(seconds=1)).isoformat()})
            self.assertEqual(first_res.status_code, 200)
            first_body = first_res.json()
            self.assertTrue(first_body.get("has_more"))
            self.assertEqual([row.get("inscripcio_id") for row in first_body.get("updates", [])], [self.ins_1.id, self.ins_2.id])

            second_res = self.client.get(
                url,
                {
                    "since": first_body.get("next_since"),
                    "after_id": first_body.get("next_after_id"),
                },
            )
        self.assertEqual(second_res.status_code, 200)
        self.assertEqual([row.get("inscripcio_id") for row in second_res.json().get("updates", [])], [self.ins_3.id])
