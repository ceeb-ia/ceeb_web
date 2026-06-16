import uuid
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from .base import Competicio
from .competicio import CompeticioAparell, CompeticioAparellFase


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


class JudgePortalAssignment(models.Model):
    """
    Acces puntuable concret dins d'un QR de jutge.

    El token identifica el dispositiu/jutge; aquesta fila identifica que pot
    puntuar en un moment concret: aparell local, fase opcional i camps.
    """

    judge_token = models.ForeignKey(
        JudgeDeviceToken,
        on_delete=models.CASCADE,
        related_name="portal_assignments",
    )
    competicio = models.ForeignKey(
        Competicio,
        on_delete=models.CASCADE,
        related_name="judge_portal_assignments",
    )
    comp_aparell = models.ForeignKey(
        CompeticioAparell,
        on_delete=models.CASCADE,
        related_name="judge_portal_assignments",
    )
    fase = models.ForeignKey(
        CompeticioAparellFase,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="judge_portal_assignments",
    )
    label = models.CharField(max_length=160, blank=True, default="")
    ordre = models.PositiveSmallIntegerField(default=1)
    permissions = models.JSONField(default=list, blank=True)
    subject_scope = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["judge_token_id", "ordre", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["judge_token", "ordre"],
                name="uniq_judge_assignment_token_ordre",
            ),
        ]
        indexes = [
            models.Index(fields=["competicio", "comp_aparell"], name="judgeassign_comp_app_idx"),
            models.Index(fields=["judge_token", "is_active"], name="judgeassign_token_active_idx"),
            models.Index(fields=["fase", "is_active"], name="judgeassign_fase_active_idx"),
        ]

    def clean(self):
        super().clean()
        errors = {}
        self.label = str(self.label or "").strip()
        if self.judge_token_id and self.competicio_id and self.judge_token.competicio_id != self.competicio_id:
            errors["competicio"] = "L'assignacio ha de pertanyer a la mateixa competicio que el token."
        if self.comp_aparell_id and self.competicio_id and self.comp_aparell.competicio_id != self.competicio_id:
            errors["comp_aparell"] = "L'aparell no pertany a la mateixa competicio."
        if self.fase_id:
            if self.competicio_id and self.fase.competicio_id != self.competicio_id:
                errors["fase"] = "La fase no pertany a la mateixa competicio."
            elif self.comp_aparell_id and self.fase.comp_aparell_id != self.comp_aparell_id:
                errors["fase"] = "La fase no pertany a aquest aparell local."
        if not isinstance(self.permissions, list):
            errors["permissions"] = "Els permisos de l'assignacio han de ser una llista JSON."
        if not isinstance(self.subject_scope, dict):
            errors["subject_scope"] = "L'abast de participants ha de ser un objecte JSON."
        elif self.competicio_id:
            raw_group_ids = self.subject_scope.get("group_ids") or []
            if raw_group_ids and not isinstance(raw_group_ids, list):
                errors["subject_scope"] = "Els grups de l'abast han de ser una llista."
            else:
                try:
                    group_ids = {int(value) for value in raw_group_ids if int(value) > 0}
                except (TypeError, ValueError):
                    errors["subject_scope"] = "Els identificadors de grup de l'abast no son valids."
                else:
                    if group_ids:
                        from .inscripcions import GrupCompeticio

                        valid_count = GrupCompeticio.objects.filter(
                            competicio_id=self.competicio_id,
                            id__in=group_ids,
                        ).count()
                        if valid_count != len(group_ids):
                            errors["subject_scope"] = "Algun grup de l'abast no pertany a la competicio."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            update_fields = set(update_fields)
            kwargs["update_fields"] = update_fields
        self.label = str(self.label or "").strip()
        if self.judge_token_id and not self.competicio_id:
            self.competicio_id = self.judge_token.competicio_id
            if update_fields is not None:
                update_fields.add("competicio")
        super().save(*args, **kwargs)

    @property
    def is_preliminary(self) -> bool:
        return self.fase_id is None

    def __str__(self):
        phase = self.fase_id or "preliminar"
        return f"{self.judge_token_id} / {self.comp_aparell_id} / {phase} / {self.label or self.ordre}"


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
