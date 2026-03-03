# models_scoring.py
from django.db import models
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from .models import Competicio, Inscripcio
from .models_trampoli import Aparell, CompeticioAparell


class ScoringSchema(models.Model):
    """
    Schema de puntuació per a cada aparell dins d'una competició (CompeticioAparell).
    Conté camps, paràmetres, fórmules i configuració de UI.
    """
    comp_aparell = models.OneToOneField(
        CompeticioAparell,
        null=True, blank=True,
        on_delete=models.CASCADE,
        related_name="scoring_schema",
    )

    aparell = models.OneToOneField(
        Aparell,
        null=True, blank=True,
        on_delete=models.CASCADE,
        related_name="scoring_schema",
    )


    schema = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        super().clean()
        if not isinstance(self.schema, dict):
            raise ValidationError({"schema": _("El schema ha de ser un objecte JSON (dict).")})

        # Convivencia temporal: aparell es canonic i comp_aparell es opcional legacy.
        if self.comp_aparell_id and not self.aparell_id:
            self.aparell = self.comp_aparell.aparell

        if not self.aparell_id:
            raise ValidationError({"aparell": _("Cal informar l'aparell.")})

        if self.comp_aparell_id and self.comp_aparell.aparell_id != self.aparell_id:
            # En mode transitori prioritzem l'aparell global i descartem l'enllac legacy inconsistent.
            self.comp_aparell = None
        # Validacions mínimes (la validació forta la fem també a l'engine)
        fields = self.schema.get("fields", [])
        computed = self.schema.get("computed", [])
        if fields and not isinstance(fields, list):
            raise ValidationError({"schema": _("'fields' ha de ser una llista.")})
        if computed and not isinstance(computed, list):
            raise ValidationError({"schema": _("'computed' ha de ser una llista.")})

        # codes únics
        codes = []
        for f in fields:
            if isinstance(f, dict) and f.get("code"):
                codes.append(f["code"])
        for c in computed:
            if isinstance(c, dict) and c.get("code"):
                codes.append(c["code"])
        if len(codes) != len(set(codes)):
            raise ValidationError({"schema": _("Hi ha 'code' duplicats a fields/computed.")})

    def __str__(self):
        if self.comp_aparell_id:
            return f"Schema {self.comp_aparell.competicio_id} / {self.comp_aparell.aparell.codi}"
        return f"Schema GLOBAL / {self.aparell.codi if self.aparell_id else '???'}"


class ScoreEntry(models.Model):
    """
    Entrada de puntuació genèrica per (inscripció, exercici, aparell en competició).
    - inputs: el que entra l'usuari
    - outputs: el que calcula l'engine
    - total: numèric principal per ordenar/classificar
    """
    competicio = models.ForeignKey(Competicio, on_delete=models.CASCADE, related_name="scores")
    inscripcio = models.ForeignKey(Inscripcio, on_delete=models.CASCADE, related_name="scores")
    exercici = models.PositiveSmallIntegerField(default=1)
    comp_aparell = models.ForeignKey(CompeticioAparell, on_delete=models.CASCADE, related_name="scores")

    inputs = models.JSONField(default=dict, blank=True)
    outputs = models.JSONField(default=dict, blank=True)
    total = models.DecimalField(max_digits=10, decimal_places=3, default=0)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["competicio", "inscripcio", "exercici", "comp_aparell"],
                name="uniq_scoreentry_per_exercici_aparell",
            )
        ]

    def __str__(self):
        return f"ScoreEntry ins={self.inscripcio_id} ex={self.exercici} app={self.comp_aparell_id}"


class ScoreEntryVideo(models.Model):
    """
    Video capture linked to one concrete score entry.
    MVP decision: one active video per (inscripcio, exercici, comp_aparell),
    enforced through OneToOne with ScoreEntry.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pendent"
        READY = "ready", "Disponible"
        FAILED = "failed", "Error"

    # Step 1 (functional scope) captured as constants for upcoming API/UI layers.
    VIDEO_MAX_DURATION_SECONDS = 180
    VIDEO_MAX_SIZE_BYTES = 120 * 1024 * 1024
    ALLOWED_MIME_TYPES = (
        "video/mp4",
        "video/webm",
        "video/quicktime",
    )

    score_entry = models.OneToOneField(
        ScoreEntry,
        on_delete=models.CASCADE,
        related_name="video_capture",
    )
    video_file = models.FileField(upload_to="trampoli/score_videos/%Y/%m/%d/")
    judge_token = models.ForeignKey(
        "competicions_trampoli.JudgeDeviceToken",
        on_delete=models.SET_NULL,
        related_name="score_videos",
        null=True,
        blank=True,
    )

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    duration_seconds = models.PositiveIntegerField(null=True, blank=True)
    file_size_bytes = models.PositiveBigIntegerField(default=0)
    mime_type = models.CharField(max_length=100, blank=True, default="")
    original_filename = models.CharField(max_length=255, blank=True, default="")
    error_message = models.CharField(max_length=300, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["judge_token", "created_at"]),
        ]

    def clean(self):
        super().clean()
        if self.duration_seconds and self.duration_seconds > self.VIDEO_MAX_DURATION_SECONDS:
            raise ValidationError(
                {"duration_seconds": _("La durada supera el maxim configurat per l'MVP.")}
            )
        if self.file_size_bytes and self.file_size_bytes > self.VIDEO_MAX_SIZE_BYTES:
            raise ValidationError(
                {"file_size_bytes": _("La mida supera el maxim configurat per l'MVP.")}
            )
        if self.mime_type and self.mime_type not in self.ALLOWED_MIME_TYPES:
            raise ValidationError({"mime_type": _("Tipus MIME de video no permès.")})

        if self.judge_token_id and self.score_entry_id:
            if self.judge_token.competicio_id != self.score_entry.competicio_id:
                raise ValidationError(
                    {"judge_token": _("El token no pertany a la mateixa competicio del score.")}
                )
            if self.judge_token.comp_aparell_id != self.score_entry.comp_aparell_id:
                raise ValidationError(
                    {"judge_token": _("El token no pertany al mateix aparell del score.")}
                )

    def __str__(self):
        return f"ScoreEntryVideo score={self.score_entry_id} status={self.status}"


class ScoreEntryVideoEvent(models.Model):
    """
    Immutable audit trail for judge video operations.
    Events remain even if the concrete video row is deleted/replaced.
    """

    class Action(models.TextChoices):
        UPLOAD = "upload", "Upload"
        REPLACE = "replace", "Replace"
        DELETE = "delete", "Delete"
        UPLOAD_REJECTED = "upload_rejected", "Upload Rejected"

    score_entry = models.ForeignKey(
        ScoreEntry,
        on_delete=models.SET_NULL,
        related_name="video_events",
        null=True,
        blank=True,
    )
    video = models.ForeignKey(
        ScoreEntryVideo,
        on_delete=models.SET_NULL,
        related_name="events",
        null=True,
        blank=True,
    )
    competicio = models.ForeignKey(
        Competicio,
        on_delete=models.CASCADE,
        related_name="score_video_events",
    )
    inscripcio = models.ForeignKey(
        Inscripcio,
        on_delete=models.CASCADE,
        related_name="score_video_events",
    )
    comp_aparell = models.ForeignKey(
        CompeticioAparell,
        on_delete=models.CASCADE,
        related_name="score_video_events",
    )
    judge_token = models.ForeignKey(
        "competicions_trampoli.JudgeDeviceToken",
        on_delete=models.SET_NULL,
        related_name="score_video_events",
        null=True,
        blank=True,
    )
    action = models.CharField(max_length=30, choices=Action.choices)
    ok = models.BooleanField(default=True)
    http_status = models.PositiveSmallIntegerField(default=200)
    detail = models.CharField(max_length=255, blank=True, default="")
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["competicio", "created_at"]),
            models.Index(fields=["action", "created_at"]),
            models.Index(fields=["judge_token", "created_at"]),
            models.Index(fields=["score_entry", "created_at"]),
        ]

    def __str__(self):
        return (
            f"ScoreEntryVideoEvent action={self.action} "
            f"score={self.score_entry_id or '-'} ok={self.ok} status={self.http_status}"
        )
