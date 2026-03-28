from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from .models import Competicio, Equip, EquipContext, Inscripcio
from .models_trampoli import Aparell, CompeticioAparell
from .services.scoring_schema_validation import validate_schema


class ScoringSchema(models.Model):
    """
    Schema de puntuacio global per aparell.
    """

    comp_aparell = models.OneToOneField(
        CompeticioAparell,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="scoring_schema",
    )
    aparell = models.OneToOneField(
        Aparell,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="scoring_schema",
    )
    schema = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        super().clean()
        if not isinstance(self.schema, dict):
            raise ValidationError({"schema": _("El schema ha de ser un objecte JSON (dict).")})

        if self.comp_aparell_id and not self.aparell_id:
            self.aparell = self.comp_aparell.aparell
        if not self.aparell_id:
            raise ValidationError({"aparell": _("Cal informar l'aparell.")})
        if self.comp_aparell_id and self.comp_aparell.aparell_id != self.aparell_id:
            self.comp_aparell = None

        fields = self.schema.get("fields", [])
        computed = self.schema.get("computed", [])
        if fields and not isinstance(fields, list):
            raise ValidationError({"schema": _("'fields' ha de ser una llista.")})
        if computed and not isinstance(computed, list):
            raise ValidationError({"schema": _("'computed' ha de ser una llista.")})

        codes = []
        for f in fields:
            if isinstance(f, dict) and f.get("code"):
                codes.append(f["code"])
        for c in computed:
            if isinstance(c, dict) and c.get("code"):
                codes.append(c["code"])
        if len(codes) != len(set(codes)):
            raise ValidationError({"schema": _("Hi ha 'code' duplicats a fields/computed.")})
        try:
            validate_schema(self.schema, aparell=self.aparell)
        except ValidationError as exc:
            raise ValidationError({"schema": exc.messages})

    def __str__(self):
        if self.comp_aparell_id:
            return f"Schema {self.comp_aparell.competicio_id} / {self.comp_aparell.aparell.codi}"
        return f"Schema GLOBAL / {self.aparell.codi if self.aparell_id else '???'}"


class ScoreEntry(models.Model):
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


class TeamCompetitiveSubject(models.Model):
    competicio = models.ForeignKey(
        Competicio,
        on_delete=models.CASCADE,
        related_name="team_subjects",
    )
    comp_aparell = models.ForeignKey(
        CompeticioAparell,
        on_delete=models.CASCADE,
        related_name="team_subjects",
    )
    context = models.ForeignKey(
        EquipContext,
        on_delete=models.CASCADE,
        related_name="team_subjects",
    )
    equip = models.ForeignKey(
        Equip,
        on_delete=models.CASCADE,
        related_name="competitive_subjects",
    )
    member_ids = models.JSONField(default=list, blank=True)
    member_names = models.JSONField(default=list, blank=True)
    label = models.CharField(max_length=255, blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["competicio", "comp_aparell", "context", "equip"],
                name="uniq_team_competitive_subject",
            )
        ]
        indexes = [
            models.Index(fields=["competicio", "comp_aparell"]),
            models.Index(fields=["competicio", "context"]),
        ]

    def clean(self):
        super().clean()
        errors = {}
        if self.comp_aparell_id and self.comp_aparell.competicio_id != self.competicio_id:
            errors["comp_aparell"] = _("L'aparell no pertany a la mateixa competicio.")
        if self.context_id and self.context.competicio_id != self.competicio_id:
            errors["context"] = _("El context no pertany a la mateixa competicio.")
        if self.equip_id and self.equip.competicio_id != self.competicio_id:
            errors["equip"] = _("L'equip no pertany a la mateixa competicio.")
        if self.comp_aparell_id and not self.comp_aparell.is_team_competition_unit:
            errors["comp_aparell"] = _("Aquest aparell no es un aparell global d'equip.")
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"TeamSubject app={self.comp_aparell_id} ctx={self.context_id} equip={self.equip_id}"


class SerieEquip(models.Model):
    competicio = models.ForeignKey(
        Competicio,
        on_delete=models.CASCADE,
        related_name="series_equip",
    )
    comp_aparell = models.ForeignKey(
        CompeticioAparell,
        on_delete=models.CASCADE,
        related_name="series_equip",
    )
    display_num = models.PositiveIntegerField()
    nom = models.CharField(max_length=180, blank=True, default="")
    actiu = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["comp_aparell_id", "display_num", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["competicio", "comp_aparell", "display_num"],
                name="uniq_serie_equip_display_num_per_app",
            ),
        ]
        indexes = [
            models.Index(fields=["competicio", "comp_aparell", "actiu"]),
        ]

    def clean(self):
        super().clean()
        errors = {}
        if self.comp_aparell_id and self.comp_aparell.competicio_id != self.competicio_id:
            errors["comp_aparell"] = _("L'aparell no pertany a la mateixa competicio.")
        if self.comp_aparell_id and not self.comp_aparell.is_team_competition_unit:
            errors["comp_aparell"] = _("Aquest aparell no es un aparell global d'equip.")
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        label = str(self.nom or "").strip() or f"Serie {self.display_num}"
        return f"{label} ({self.comp_aparell_id})"


class SerieEquipItem(models.Model):
    serie = models.ForeignKey(
        SerieEquip,
        on_delete=models.CASCADE,
        related_name="items",
    )
    team_subject = models.ForeignKey(
        TeamCompetitiveSubject,
        on_delete=models.CASCADE,
        related_name="serie_items",
    )
    ordre = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["ordre", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["serie", "team_subject"],
                name="uniq_serie_equip_item_subject",
            ),
        ]
        indexes = [
            models.Index(fields=["serie", "ordre"]),
            models.Index(fields=["team_subject"]),
        ]

    def clean(self):
        super().clean()
        errors = {}
        if self.serie_id and self.team_subject_id:
            if self.serie.competicio_id != self.team_subject.competicio_id:
                errors["team_subject"] = _("La unitat competitiva no pertany a la mateixa competicio.")
            if self.serie.comp_aparell_id != self.team_subject.comp_aparell_id:
                errors["team_subject"] = _("La unitat competitiva no pertany a aquest aparell.")
            conflict_qs = (
                SerieEquipItem.objects
                .filter(
                    team_subject=self.team_subject,
                    serie__competicio_id=self.serie.competicio_id,
                    serie__comp_aparell_id=self.serie.comp_aparell_id,
                    serie__actiu=True,
                )
                .exclude(pk=self.pk)
            )
            if conflict_qs.exists():
                errors["team_subject"] = _(
                    "La unitat competitiva ja esta assignada a una altra serie activa d'aquest aparell."
                )
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"SerieItem serie={self.serie_id} subject={self.team_subject_id}"


class TeamScoreEntry(models.Model):
    competicio = models.ForeignKey(Competicio, on_delete=models.CASCADE, related_name="team_scores")
    team_subject = models.ForeignKey(
        TeamCompetitiveSubject,
        on_delete=models.CASCADE,
        related_name="scores",
    )
    exercici = models.PositiveSmallIntegerField(default=1)
    comp_aparell = models.ForeignKey(CompeticioAparell, on_delete=models.CASCADE, related_name="team_scores")

    inputs = models.JSONField(default=dict, blank=True)
    outputs = models.JSONField(default=dict, blank=True)
    total = models.DecimalField(max_digits=10, decimal_places=3, default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["competicio", "team_subject", "exercici", "comp_aparell"],
                name="uniq_teamscoreentry_per_subject_exercici_aparell",
            )
        ]
        indexes = [
            models.Index(fields=["competicio", "comp_aparell", "exercici"]),
            models.Index(fields=["competicio", "team_subject"]),
        ]

    def clean(self):
        super().clean()
        errors = {}
        if self.team_subject_id:
            if self.team_subject.competicio_id != self.competicio_id:
                errors["team_subject"] = _("La unitat competitiva no pertany a la mateixa competicio.")
            if self.team_subject.comp_aparell_id != self.comp_aparell_id:
                errors["comp_aparell"] = _("La unitat competitiva no pertany a aquest aparell.")
        if self.comp_aparell_id and self.comp_aparell.competicio_id != self.competicio_id:
            errors["comp_aparell"] = _("L'aparell no pertany a la mateixa competicio.")
        if self.comp_aparell_id and not self.comp_aparell.is_team_competition_unit:
            errors["comp_aparell"] = _("Aquest aparell no es un aparell global d'equip.")
        if errors:
            raise ValidationError(errors)

    @property
    def equip_id(self):
        return getattr(self.team_subject, "equip_id", None)

    def __str__(self):
        return f"TeamScoreEntry subject={self.team_subject_id} ex={self.exercici} app={self.comp_aparell_id}"


class ScoreEntryVideo(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pendent"
        READY = "ready", "Disponible"
        FAILED = "failed", "Error"

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
            raise ValidationError({"mime_type": _("Tipus MIME de video no permes.")})
        if self.judge_token_id and self.score_entry_id:
            if self.judge_token.competicio_id != self.score_entry.competicio_id:
                raise ValidationError(
                    {"judge_token": _("El token no pertany a la mateixa competicio del score.")}
                )
            if self.judge_token.comp_aparell_id != self.score_entry.comp_aparell_id:
                raise ValidationError(
                    {"judge_token": _("El token no pertany al mateix aparell del score.")}
                )


class ScoreEntryVideoEvent(models.Model):
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
    competicio = models.ForeignKey(Competicio, on_delete=models.CASCADE, related_name="score_video_events")
    inscripcio = models.ForeignKey(Inscripcio, on_delete=models.CASCADE, related_name="score_video_events")
    comp_aparell = models.ForeignKey(CompeticioAparell, on_delete=models.CASCADE, related_name="score_video_events")
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


class TeamScoreEntryVideo(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pendent"
        READY = "ready", "Disponible"
        FAILED = "failed", "Error"

    VIDEO_MAX_DURATION_SECONDS = ScoreEntryVideo.VIDEO_MAX_DURATION_SECONDS
    VIDEO_MAX_SIZE_BYTES = ScoreEntryVideo.VIDEO_MAX_SIZE_BYTES
    ALLOWED_MIME_TYPES = ScoreEntryVideo.ALLOWED_MIME_TYPES

    team_score_entry = models.OneToOneField(
        TeamScoreEntry,
        on_delete=models.CASCADE,
        related_name="video_capture",
    )
    video_file = models.FileField(upload_to="trampoli/team_score_videos/%Y/%m/%d/")
    judge_token = models.ForeignKey(
        "competicions_trampoli.JudgeDeviceToken",
        on_delete=models.SET_NULL,
        related_name="team_score_videos",
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
            raise ValidationError({"mime_type": _("Tipus MIME de video no permes.")})
        if self.judge_token_id and self.team_score_entry_id:
            if self.judge_token.competicio_id != self.team_score_entry.competicio_id:
                raise ValidationError(
                    {"judge_token": _("El token no pertany a la mateixa competicio del score.")}
                )
            if self.judge_token.comp_aparell_id != self.team_score_entry.comp_aparell_id:
                raise ValidationError(
                    {"judge_token": _("El token no pertany al mateix aparell del score.")}
                )


class TeamScoreEntryVideoEvent(models.Model):
    class Action(models.TextChoices):
        UPLOAD = "upload", "Upload"
        REPLACE = "replace", "Replace"
        DELETE = "delete", "Delete"
        UPLOAD_REJECTED = "upload_rejected", "Upload Rejected"

    team_score_entry = models.ForeignKey(
        TeamScoreEntry,
        on_delete=models.SET_NULL,
        related_name="video_events",
        null=True,
        blank=True,
    )
    video = models.ForeignKey(
        TeamScoreEntryVideo,
        on_delete=models.SET_NULL,
        related_name="events",
        null=True,
        blank=True,
    )
    competicio = models.ForeignKey(
        Competicio,
        on_delete=models.CASCADE,
        related_name="team_score_video_events",
    )
    team_subject = models.ForeignKey(
        TeamCompetitiveSubject,
        on_delete=models.CASCADE,
        related_name="video_events",
    )
    equip = models.ForeignKey(
        Equip,
        on_delete=models.CASCADE,
        related_name="team_score_video_events",
    )
    comp_aparell = models.ForeignKey(
        CompeticioAparell,
        on_delete=models.CASCADE,
        related_name="team_score_video_events",
    )
    judge_token = models.ForeignKey(
        "competicions_trampoli.JudgeDeviceToken",
        on_delete=models.SET_NULL,
        related_name="team_score_video_events",
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
            models.Index(fields=["team_score_entry", "created_at"]),
        ]
