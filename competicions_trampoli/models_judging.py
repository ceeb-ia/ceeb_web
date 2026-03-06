import uuid
from django.conf import settings
from django.db import models
from django.utils import timezone

from .models import Competicio
from .models_trampoli import CompeticioAparell


class JudgeDeviceToken(models.Model):
    """
    Token per QR (clau d'accés). Sense usuari.
    Un token pot puntuar múltiples camps del mateix aparell.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    competicio = models.ForeignKey(Competicio, on_delete=models.CASCADE, related_name="judge_tokens")
    comp_aparell = models.ForeignKey(CompeticioAparell, on_delete=models.CASCADE, related_name="judge_tokens")

    label = models.CharField(max_length=120, blank=True, default="")  # ex: "Jutge 2 - Taula A"

    # Llista de permisos (JSON):
    # [
    #   {"field_code":"E","judge_index":1,"item_start":1,"item_count":None},
    #   {"field_code":"D","judge_index":2}
    # ]
    permissions = models.JSONField(default=list, blank=True)
    can_record_video = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    is_active = models.BooleanField(default=True)

    def is_valid(self) -> bool:
        return self.is_active and self.revoked_at is None

    def touch(self):
        self.last_used_at = timezone.now()
        self.save(update_fields=["last_used_at"])

    def __str__(self):
        return f"{self.competicio_id} / {self.comp_aparell_id} / {self.label or self.id}"


class PublicLiveToken(models.Model):
    """
    Token per compartir Classificacions Live amb el públic (sense autenticació).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    competicio = models.ForeignKey(
        Competicio,
        on_delete=models.CASCADE,
        related_name="public_live_tokens",
    )
    label = models.CharField(max_length=120, blank=True, default="")
    can_view_media = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    def is_valid(self) -> bool:
        return self.is_active and self.revoked_at is None

    def touch(self):
        self.last_used_at = timezone.now()
        self.save(update_fields=["last_used_at"])

    def __str__(self):
        return f"{self.competicio_id} / LIVE / {self.label or self.id}"


class JudgeConversation(models.Model):
    class Status(models.TextChoices):
        IDLE = "idle", "Idle"
        REQUESTED = "requested", "Requested"
        ACK = "ack", "Ack"
        RESOLVED = "resolved", "Resolved"

    class Priority(models.TextChoices):
        NORMAL = "normal", "Normal"
        HIGH = "high", "High"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    competicio = models.ForeignKey(
        Competicio,
        on_delete=models.CASCADE,
        related_name="judge_conversations",
    )
    comp_aparell = models.ForeignKey(
        CompeticioAparell,
        on_delete=models.CASCADE,
        related_name="judge_conversations",
    )
    judge_token = models.OneToOneField(
        JudgeDeviceToken,
        on_delete=models.CASCADE,
        related_name="conversation",
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.IDLE,
    )
    priority = models.CharField(
        max_length=20,
        choices=Priority.choices,
        default=Priority.NORMAL,
    )

    unread_for_org = models.PositiveIntegerField(default=0)
    unread_for_judge = models.PositiveIntegerField(default=0)

    requested_at = models.DateTimeField(null=True, blank=True)
    acked_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    org_last_read_at = models.DateTimeField(null=True, blank=True)
    judge_last_read_at = models.DateTimeField(null=True, blank=True)

    last_message_at = models.DateTimeField(null=True, blank=True)
    last_message_preview = models.CharField(max_length=180, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["competicio", "status", "last_message_at"]),
            models.Index(fields=["competicio", "unread_for_org", "last_message_at"]),
            models.Index(fields=["judge_token", "updated_at"]),
        ]

    def __str__(self):
        return f"JudgeConversation {self.competicio_id} / {self.judge_token_id} / {self.status}"


class JudgeConversationMessage(models.Model):
    class SenderType(models.TextChoices):
        JUDGE = "judge", "Judge"
        ORGANIZATION = "organization", "Organization"
        SYSTEM = "system", "System"

    class MessageType(models.TextChoices):
        SUPPORT_REQUEST = "support_request", "Support Request"
        SUPPORT_REQUEST_QUICK = "support_request_quick", "Support Request Quick"
        REPLY = "reply", "Reply"
        INSTRUCTION = "instruction", "Instruction"
        SYSTEM = "system", "System"

    conversation = models.ForeignKey(
        JudgeConversation,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    competicio = models.ForeignKey(
        Competicio,
        on_delete=models.CASCADE,
        related_name="judge_conversation_messages",
    )
    comp_aparell = models.ForeignKey(
        CompeticioAparell,
        on_delete=models.CASCADE,
        related_name="judge_conversation_messages",
    )
    judge_token = models.ForeignKey(
        JudgeDeviceToken,
        on_delete=models.CASCADE,
        related_name="conversation_messages",
    )
    sender_type = models.CharField(max_length=20, choices=SenderType.choices)
    sender_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="judge_conversation_messages",
    )
    message_type = models.CharField(
        max_length=30,
        choices=MessageType.choices,
        default=MessageType.REPLY,
    )
    text = models.TextField(blank=True, default="")
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["conversation", "created_at"]),
            models.Index(fields=["competicio", "created_at"]),
            models.Index(fields=["judge_token", "created_at"]),
            models.Index(fields=["message_type", "created_at"]),
        ]

    def __str__(self):
        return (
            f"JudgeConversationMessage conv={self.conversation_id} "
            f"type={self.message_type} sender={self.sender_type}"
        )
