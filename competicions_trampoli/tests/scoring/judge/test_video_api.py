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
            "competicions_trampoli.views.judge.video._probe_uploaded_video_metadata",
            side_effect=self._fake_probe_uploaded_video_metadata,
        )
        self._probe_patcher.start()
        self.addCleanup(self._probe_patcher.stop)

    @staticmethod
    def _fake_probe_uploaded_video_metadata(uploaded_file):
        from competicions_trampoli.views.judge import VideoValidationError

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


