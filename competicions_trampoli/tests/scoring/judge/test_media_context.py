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
        self.assertEqual(int(judge_map.get(f"inscripcio:{self.ins.id}|1|{self.comp_app.id}") or 0), 1)
        self.assertEqual(int(judge_map.get(f"inscripcio:{ins_without_media.id}|1|{self.comp_app.id}") or 0), 0)

    def test_scoring_notes_home_queues_remote_rerender_while_local_row_is_editing(self):
        url = reverse("scoring_notes_home", kwargs={"pk": self.comp.id})
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)

        body = res.content.decode("utf-8")
        self.assertIn("const pendingRemoteScoreKeys = new Set();", body)
        self.assertIn("function isEditingScoreKey(scoreKey){", body)
        self.assertIn("markScoreKeyPendingRemoteRerender(scoreKey);", body)
        self.assertIn("function flushPendingRemoteRerendersForTable(table){", body)
        self.assertIn("setTimeout(()=>flushPendingRemoteRerendersForTable(table), 0);", body)
        self.assertIn("rerenderTablesForScoreKey(scoreKey);", body)
        self.assertIn("function updateTeamOutputs(scoreKey, resp){", body)
        self.assertIn("updateTeamOutputs(scoreKey, resp);", body)
        self.assertIn("if(isEditingScoreKey(scoreKey)){", body)


