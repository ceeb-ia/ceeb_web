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
            competicio=conversation.competicio,
            comp_aparell=conversation.comp_aparell,
            judge_token=conversation.judge_token,
            sender_type=JudgeConversationMessage.SenderType.ORGANIZATION,
            message_type=JudgeConversationMessage.MessageType.REPLY,
            text="M1",
        )
        msg_2 = JudgeConversationMessage.objects.create(
            conversation=conversation,
            competicio=conversation.competicio,
            comp_aparell=conversation.comp_aparell,
            judge_token=conversation.judge_token,
            sender_type=JudgeConversationMessage.SenderType.ORGANIZATION,
            message_type=JudgeConversationMessage.MessageType.REPLY,
            text="M2",
        )
        msg_3 = JudgeConversationMessage.objects.create(
            conversation=conversation,
            competicio=conversation.competicio,
            comp_aparell=conversation.comp_aparell,
            judge_token=conversation.judge_token,
            sender_type=JudgeConversationMessage.SenderType.ORGANIZATION,
            message_type=JudgeConversationMessage.MessageType.REPLY,
            text="M3",
        )
        JudgeConversationMessage.objects.filter(pk__in=[msg_1.id, msg_2.id, msg_3.id]).update(created_at=base_time)

        updates_url = reverse("judge_messages_updates", kwargs={"token": self.token.id})
        with patch("competicions_trampoli.views.judge.messages.JUDGE_MESSAGES_DELTA_LIMIT", 2):
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

    def test_judge_messages_updates_without_since_returns_empty_snapshot_for_new_conversation(self):
        updates_url = reverse("judge_messages_updates", kwargs={"token": self.token.id})
        updates_res = self.client.get(updates_url)

        self.assertEqual(updates_res.status_code, 200)
        payload = updates_res.json()
        self.assertTrue(payload.get("ok"))
        self.assertEqual(payload.get("messages"), [])
        self.assertFalse(payload.get("has_more"))
        self.assertEqual(payload.get("next_after_id"), "")
        self.assertIn("conversation", payload)
        self.assertEqual(str(payload["conversation"]["token_id"]), str(self.token.id))

    def test_judge_messages_updates_reset_unread_and_return_cooldown_remaining(self):
        self.client.post(
            reverse("judge_request_support", kwargs={"token": self.token.id}),
            data=json.dumps({}),
            content_type="application/json",
        )
        self.client.force_login(self.manager_user)
        self.client.post(
            reverse("judge_messages_send_org", kwargs={"competicio_id": self.comp.id}),
            data=json.dumps(
                {
                    "judge_token_id": str(self.token.id),
                    "message_type": "instruction",
                    "text": "Confirma recepcio del dispositiu.",
                }
            ),
            content_type="application/json",
        )
        self.client.logout()

        conversation = JudgeConversation.objects.get(judge_token=self.token)
        self.assertGreater(conversation.unread_for_judge, 0)

        updates_url = reverse("judge_messages_updates", kwargs={"token": self.token.id})
        updates_res = self.client.get(updates_url)

        self.assertEqual(updates_res.status_code, 200)
        payload = updates_res.json()
        self.assertTrue(any("Confirma recepcio" in (row.get("text") or "") for row in payload.get("messages", [])))
        self.assertIsInstance(payload.get("cooldown_remaining"), int)
        self.assertGreaterEqual(payload.get("cooldown_remaining"), 0)
        conversation.refresh_from_db()
        self.assertEqual(conversation.unread_for_judge, 0)


