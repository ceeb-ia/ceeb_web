from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from .base import Competicio
from .inscripcions import EquipContext, Inscripcio

NUM_SALTS = 11  # S1..S11


class Aparell(models.Model):
    class CompetitionUnit(models.TextChoices):
        INDIVIDUAL = "individual", "Individual"
        TEAM = "team", "Equip"

    codi = models.CharField(max_length=20)  # TRAMP, DMT, TUMB...
    nom = models.CharField(max_length=60)  # "Trampoli", "DMT", ...
    competition_unit = models.CharField(
        max_length=20,
        choices=CompetitionUnit.choices,
        default=CompetitionUnit.INDIVIDUAL,
    )
    actiu = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="aparells_creats",
    )

    class Meta:
        ordering = ["nom"]
        constraints = [
            models.UniqueConstraint(
                fields=["created_by", "codi"],
                name="uniq_aparell_created_by_codi",
            )
        ]
        indexes = [
            models.Index(fields=["created_by", "nom"], name="competicion_created_c5f6cf_idx"),
            models.Index(fields=["created_by", "actiu"], name="competicion_created_0e666d_idx"),
        ]

    def __str__(self):
        return self.nom

    def save(self, *args, **kwargs):
        self.codi = str(self.codi or "").strip().upper()
        super().save(*args, **kwargs)

    @property
    def is_team_competition_unit(self) -> bool:
        return self.competition_unit == self.CompetitionUnit.TEAM


class CompeticioAparell(models.Model):
    competicio = models.ForeignKey(Competicio, on_delete=models.CASCADE, related_name="aparells_cfg")
    aparell = models.ForeignKey(Aparell, on_delete=models.PROTECT, related_name="competicio_cfg")
    nom_local = models.CharField(max_length=120, blank=True, default="")
    codi_local = models.CharField(max_length=40, blank=True, default="", db_index=True)
    nombre_exercicis = models.PositiveSmallIntegerField(default=1, verbose_name="Nombre d'exercicis")
    judge_ui_config = models.JSONField(default=dict, blank=True)
    participation_config = models.JSONField(default=dict, blank=True)

    # CREC QUE REDUNDANT A PARTIR D'AQUI; INUTIL JA
    ordre = models.PositiveSmallIntegerField(default=1)

    # Nombre d'elements (ex: salts)
    nombre_elements = models.PositiveSmallIntegerField(default=11)

    # Items de puntuacio disponibles
    te_execucio = models.BooleanField(default=True)
    te_dificultat = models.BooleanField(default=True)
    te_tof = models.BooleanField(default=True)
    te_hd = models.BooleanField(default=True)
    te_penalitzacio = models.BooleanField(default=True)

    MODE_EXECUCIO_CHOICES = [("salts", "Per elements"), ("manual", "Execucio global manual")]
    mode_execucio = models.CharField(max_length=10, choices=MODE_EXECUCIO_CHOICES, default="salts")
    actiu = models.BooleanField(default=True)

    class Meta:
        ordering = ["ordre", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["competicio", "codi_local"],
                condition=~models.Q(codi_local=""),
                name="uniq_competicio_comp_app_codi_local",
            )
        ]

    def clean(self):
        super().clean()
        self.nom_local = str(self.nom_local or "").strip()
        self.codi_local = str(self.codi_local or "").strip().upper()
        if self.aparell_id and self.aparell.created_by_id is None:
            raise ValidationError({"aparell": "L'aparell seleccionat no es valid."})

    @property
    def display_nom(self) -> str:
        return str(self.nom_local or "").strip() or str(getattr(self.aparell, "nom", "") or "Aparell")

    @property
    def display_codi(self) -> str:
        return str(self.codi_local or "").strip() or str(getattr(self.aparell, "codi", "") or "")

    def _candidate_local_code(self) -> str:
        base = str(self.codi_local or getattr(self.aparell, "codi", "") or "APP").strip().upper()
        if not self.competicio_id:
            return base
        candidate = base
        suffix = 2
        qs = CompeticioAparell.objects.filter(competicio_id=self.competicio_id, codi_local=candidate)
        if self.pk:
            qs = qs.exclude(pk=self.pk)
        while qs.exists():
            candidate = f"{base}-{suffix}"
            qs = CompeticioAparell.objects.filter(competicio_id=self.competicio_id, codi_local=candidate)
            if self.pk:
                qs = qs.exclude(pk=self.pk)
            suffix += 1
        return candidate

    def save(self, *args, **kwargs):
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            update_fields = set(update_fields)
            kwargs["update_fields"] = update_fields
        self.nom_local = str(self.nom_local or "").strip()
        self.codi_local = str(self.codi_local or "").strip().upper()
        if not self.nom_local and self.aparell_id:
            self.nom_local = str(getattr(self.aparell, "nom", "") or "").strip()
            if update_fields is not None:
                update_fields.add("nom_local")
        if not self.codi_local and self.aparell_id:
            self.codi_local = self._candidate_local_code()
            if update_fields is not None:
                update_fields.add("codi_local")
        super().save(*args, **kwargs)

    def __str__(self):
        code = self.display_codi
        label = self.display_nom
        return f"{label} ({code})" if code else label

    @property
    def is_team_context_mode(self) -> bool:
        return self.is_team_competition_unit

    @property
    def is_team_competition_unit(self) -> bool:
        return bool(self.aparell_id and self.aparell.is_team_competition_unit)


class CompeticioAparellFase(models.Model):
    class Estat(models.TextChoices):
        PLANNED = "planned", "Planificada"
        GENERATED = "generated", "Generada"
        PARTIALLY_CONFIRMED = "partially_confirmed", "Parcialment confirmada"
        CONFIRMED = "confirmed", "Confirmada"
        PUBLISHED = "published", "Publicada"
        CLOSED = "closed", "Tancada"
        STALE = "stale", "Obsoleta"

    competicio = models.ForeignKey(
        Competicio,
        on_delete=models.CASCADE,
        related_name="aparell_fases",
    )
    comp_aparell = models.ForeignKey(
        CompeticioAparell,
        on_delete=models.CASCADE,
        related_name="fases",
    )
    parent = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="children",
    )
    nom = models.CharField(max_length=120)
    codi = models.CharField(max_length=40, db_index=True)
    ordre = models.PositiveSmallIntegerField(default=1)
    estat = models.CharField(max_length=30, choices=Estat.choices, default=Estat.PLANNED)
    config = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["comp_aparell_id", "ordre", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["competicio", "comp_aparell", "codi"],
                name="uniq_comp_app_fase_codi",
            ),
        ]
        indexes = [
            models.Index(fields=["competicio", "comp_aparell", "ordre"], name="compfase_comp_app_ordre_idx"),
            models.Index(fields=["competicio", "estat"], name="compfase_comp_estat_idx"),
        ]

    def clean(self):
        super().clean()
        errors = {}
        self.nom = str(self.nom or "").strip()
        self.codi = str(self.codi or "").strip().upper()
        if not self.nom:
            errors["nom"] = "Cal informar el nom de la fase."
        if not self.codi:
            errors["codi"] = "Cal informar el codi de la fase."
        elif self.codi == "DEFAULT":
            errors["codi"] = "La fase default/preliminar es implicita i es gestiona des d'inscripcions i rotacions."
        if self.comp_aparell_id and self.comp_aparell.competicio_id != self.competicio_id:
            errors["comp_aparell"] = "L'aparell no pertany a la mateixa competicio."
        if self.parent_id:
            if self.pk and self.parent_id == self.pk:
                errors["parent"] = "Una fase no pot ser pare de si mateixa."
            elif self.parent.comp_aparell_id != self.comp_aparell_id:
                errors["parent"] = "La fase pare ha de pertanyer al mateix aparell local."
            elif self.parent.competicio_id != self.competicio_id:
                errors["parent"] = "La fase pare ha de pertanyer a la mateixa competicio."
            elif self.pk:
                ancestor = self.parent
                seen = set()
                while ancestor is not None and ancestor.pk:
                    if ancestor.pk in seen:
                        errors["parent"] = "L'arbre de fases conte un cicle."
                        break
                    if ancestor.pk == self.pk:
                        errors["parent"] = "L'arbre de fases no pot contenir cicles."
                        break
                    seen.add(ancestor.pk)
                    ancestor = ancestor.parent
        if not isinstance(self.config, dict):
            errors["config"] = "La configuracio de fase ha de ser un objecte JSON."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            update_fields = set(update_fields)
            kwargs["update_fields"] = update_fields
        self.nom = str(self.nom or "").strip()
        self.codi = str(self.codi or "").strip().upper()
        if self.comp_aparell_id and not self.competicio_id:
            self.competicio_id = self.comp_aparell.competicio_id
            if update_fields is not None:
                update_fields.add("competicio")
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.comp_aparell.display_nom} / {self.nom}"


class ProgramUnit(models.Model):
    class Tipus(models.TextChoices):
        GROUP = "group", "Grup"
        SERIE = "serie", "Serie"
        BLOCK = "block", "Bloc"
        TEAM = "team", "Equip"
        CUSTOM = "custom", "Custom"

    class Status(models.TextChoices):
        PLANNED = "planned", "Planificada"
        GENERATED = "generated", "Generada"
        CONFIRMED = "confirmed", "Confirmada"
        PUBLISHED = "published", "Publicada"

    fase = models.ForeignKey(
        CompeticioAparellFase,
        on_delete=models.CASCADE,
        related_name="program_units",
    )
    nom = models.CharField(max_length=180)
    tipus = models.CharField(max_length=30, choices=Tipus.choices, default=Tipus.CUSTOM)
    ordre = models.PositiveIntegerField(default=1)
    partition_key = models.CharField(max_length=255, blank=True, default="")
    partition_values = models.JSONField(default=dict, blank=True)
    capacity = models.PositiveIntegerField(null=True, blank=True)
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.PLANNED)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["fase_id", "ordre", "id"]
        constraints = [
            models.UniqueConstraint(fields=["fase", "ordre"], name="uniq_program_unit_fase_ordre"),
        ]
        indexes = [
            models.Index(fields=["fase", "status"], name="programunit_fase_status_idx"),
            models.Index(fields=["fase", "tipus"], name="programunit_fase_tipus_idx"),
        ]

    def clean(self):
        super().clean()
        errors = {}
        self.nom = str(self.nom or "").strip()
        self.partition_key = str(self.partition_key or "").strip()
        if not self.nom:
            errors["nom"] = "Cal informar el nom de la unitat programable."
        if not isinstance(self.partition_values, dict):
            errors["partition_values"] = "Els valors de particio han de ser un objecte JSON."
        if not isinstance(self.metadata, dict):
            errors["metadata"] = "La metadata ha de ser un objecte JSON."
        if self.capacity is not None and int(self.capacity) <= 0:
            errors["capacity"] = "La capacitat ha de ser positiva."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.nom = str(self.nom or "").strip()
        self.partition_key = str(self.partition_key or "").strip()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.fase} / {self.nom}"


class ProgramUnitSlot(models.Model):
    class Status(models.TextChoices):
        EMPTY = "empty", "Buida"
        FILLED = "filled", "Omplerta"
        RESERVE = "reserve", "Reserva"
        PENDING_DECISION = "pending_decision", "Pendent de decisio"
        WITHDRAWN = "withdrawn", "Baixa"
        MANUAL = "manual", "Manual"

    unit = models.ForeignKey(
        ProgramUnit,
        on_delete=models.CASCADE,
        related_name="slots",
    )
    slot_index = models.PositiveIntegerField()
    ordre = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.EMPTY)
    subject_kind = models.CharField(max_length=50, blank=True, default="")
    subject_id = models.PositiveBigIntegerField(null=True, blank=True)
    source_classificacio = models.ForeignKey(
        "competicions_trampoli.ClassificacioConfig",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="program_unit_slots",
    )
    source_particio_key = models.CharField(max_length=255, blank=True, default="")
    source_position = models.PositiveIntegerField(null=True, blank=True)
    source_score = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    source_row = models.JSONField(default=dict, blank=True)
    locked = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["unit_id", "ordre", "id"]
        constraints = [
            models.UniqueConstraint(fields=["unit", "slot_index"], name="uniq_program_slot_unit_index"),
            models.UniqueConstraint(fields=["unit", "ordre"], name="uniq_program_slot_unit_ordre"),
        ]
        indexes = [
            models.Index(fields=["unit", "status"], name="programslot_unit_status_idx"),
            models.Index(fields=["subject_kind", "subject_id"], name="programslot_subject_idx"),
        ]

    def clean(self):
        super().clean()
        errors = {}
        self.subject_kind = str(self.subject_kind or "").strip().lower()
        self.source_particio_key = str(self.source_particio_key or "").strip()
        if self.status in {self.Status.FILLED, self.Status.RESERVE, self.Status.MANUAL}:
            if not self.subject_kind or not self.subject_id:
                errors["subject_id"] = "Aquest estat de slot requereix subjecte."
        if self.status == self.Status.EMPTY and (self.subject_kind or self.subject_id):
            errors["status"] = "Un slot buit no pot tenir subjecte assignat."
        if not isinstance(self.source_row, dict):
            errors["source_row"] = "La fila d'origen ha de ser un objecte JSON."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.subject_kind = str(self.subject_kind or "").strip().lower()
        self.source_particio_key = str(self.source_particio_key or "").strip()
        super().save(*args, **kwargs)

    def __str__(self):
        subject = f"{self.subject_kind}:{self.subject_id}" if self.subject_kind and self.subject_id else "-"
        return f"{self.unit} / slot {self.slot_index} / {subject}"


class QualificationRun(models.Model):
    class Status(models.TextChoices):
        PREVIEWED = "previewed", "Previsualitzada"
        APPLIED = "applied", "Aplicada"
        STALE = "stale", "Obsoleta"

    fase = models.ForeignKey(
        CompeticioAparellFase,
        on_delete=models.CASCADE,
        related_name="qualification_runs",
    )
    source_classificacio = models.ForeignKey(
        "competicions_trampoli.ClassificacioConfig",
        on_delete=models.PROTECT,
        related_name="qualification_runs",
    )
    source_phase = models.ForeignKey(
        CompeticioAparellFase,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="qualification_source_runs",
    )
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.PREVIEWED)
    snapshot_hash = models.CharField(max_length=64, db_index=True)
    summary = models.JSONField(default=dict, blank=True)
    warnings = models.JSONField(default=list, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    applied_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["fase", "status"], name="qualification_fase_status_idx"),
            models.Index(fields=["source_classificacio", "status"], name="qualification_src_status_idx"),
        ]

    def clean(self):
        super().clean()
        errors = {}
        if self.fase_id and self.source_classificacio_id:
            if self.source_classificacio.competicio_id != self.fase.competicio_id:
                errors["source_classificacio"] = "La classificacio font no pertany a la mateixa competicio."
        if self.source_phase_id:
            if self.source_phase.competicio_id != self.fase.competicio_id:
                errors["source_phase"] = "La fase origen no pertany a la mateixa competicio."
        if not isinstance(self.summary, dict):
            errors["summary"] = "El resum ha de ser un objecte JSON."
        if not isinstance(self.warnings, list):
            errors["warnings"] = "Els avisos han de ser una llista JSON."
        if not isinstance(self.payload, dict):
            errors["payload"] = "El payload ha de ser un objecte JSON."
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"{self.fase} / {self.status} / {self.snapshot_hash[:8]}"


class FasePartitionState(models.Model):
    class Status(models.TextChoices):
        GENERATED = "generated", "Generada"
        CONFIRMED = "confirmed", "Confirmada"
        STALE = "stale", "Obsoleta"

    fase = models.ForeignKey(
        CompeticioAparellFase,
        on_delete=models.CASCADE,
        related_name="partition_states",
    )
    partition_key = models.CharField(max_length=255)
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.GENERATED)
    qualification_run = models.ForeignKey(
        QualificationRun,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="partition_states",
    )
    source_snapshot_hash = models.CharField(max_length=64, blank=True, default="")
    warnings = models.JSONField(default=list, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["fase_id", "partition_key"]
        constraints = [
            models.UniqueConstraint(fields=["fase", "partition_key"], name="uniq_fase_partition_state"),
        ]
        indexes = [
            models.Index(fields=["fase", "status"], name="fasepart_fase_status_idx"),
        ]

    def clean(self):
        super().clean()
        self.partition_key = str(self.partition_key or "").strip() or "global"
        self.source_snapshot_hash = str(self.source_snapshot_hash or "").strip()
        if not isinstance(self.warnings, list):
            raise ValidationError({"warnings": "Els avisos han de ser una llista JSON."})

    def save(self, *args, **kwargs):
        self.partition_key = str(self.partition_key or "").strip() or "global"
        self.source_snapshot_hash = str(self.source_snapshot_hash or "").strip()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.fase} / {self.partition_key} / {self.status}"


class CompeticioAparellEquipContextSource(models.Model):
    competicio = models.ForeignKey(
        Competicio,
        on_delete=models.CASCADE,
        related_name="aparell_equip_context_sources",
    )
    comp_aparell = models.ForeignKey(
        CompeticioAparell,
        on_delete=models.CASCADE,
        related_name="team_context_sources",
    )
    context = models.ForeignKey(
        EquipContext,
        on_delete=models.CASCADE,
        related_name="comp_aparell_sources",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["comp_aparell_id", "context_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["comp_aparell", "context"],
                name="uniq_comp_aparell_context_source",
            )
        ]
        indexes = [
            models.Index(fields=["competicio", "context"]),
            models.Index(fields=["competicio", "comp_aparell"]),
        ]

    def clean(self):
        super().clean()
        errors = {}
        if self.comp_aparell_id and self.comp_aparell.competicio_id != self.competicio_id:
            errors["comp_aparell"] = "L'aparell no pertany a la mateixa competicio."
        if self.context_id and self.context.competicio_id != self.competicio_id:
            errors["context"] = "El context no pertany a la mateixa competicio."
        if self.comp_aparell_id and not self.comp_aparell.is_team_competition_unit:
            errors["comp_aparell"] = "Aquest aparell no es un aparell global d'equip."
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"Source comp_aparell={self.comp_aparell_id} context={self.context_id}"


class InscripcioAparellExclusio(models.Model):
    """
    Exclusio explicita d'una inscripcio en un aparell concret de la competicio.
    Si no existeix registre, la inscripcio s'assumeix admesa a l'aparell.
    """

    inscripcio = models.ForeignKey(
        Inscripcio,
        on_delete=models.CASCADE,
        related_name="aparells_exclosos",
    )
    comp_aparell = models.ForeignKey(
        CompeticioAparell,
        on_delete=models.CASCADE,
        related_name="inscripcions_excloses",
    )
    motiu = models.CharField(max_length=250, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["inscripcio", "comp_aparell"],
                name="uniq_inscripcio_comp_aparell_exclusio",
            ),
        ]
        indexes = [
            models.Index(fields=["comp_aparell", "inscripcio"]),
            models.Index(fields=["inscripcio", "comp_aparell"]),
        ]

    def clean(self):
        super().clean()
        ins_comp_id = getattr(self.inscripcio, "competicio_id", None)
        app_comp_id = getattr(self.comp_aparell, "competicio_id", None)
        if ins_comp_id and app_comp_id and ins_comp_id != app_comp_id:
            raise ValidationError(
                "La inscripcio i el comp_aparell han de pertanyer a la mateixa competicio."
            )

    def __str__(self):
        return f"Exclusio inscripcio={self.inscripcio_id} comp_aparell={self.comp_aparell_id}"


class InscripcioBaixa(models.Model):
    """
    Baixa administrativa d'una inscripcio.
    Si comp_aparell es buit, la baixa afecta tota la competicio.
    """

    competicio = models.ForeignKey(
        Competicio,
        on_delete=models.CASCADE,
        related_name="inscripcions_baixes",
    )
    inscripcio = models.ForeignKey(
        Inscripcio,
        on_delete=models.CASCADE,
        related_name="baixes",
    )
    comp_aparell = models.ForeignKey(
        CompeticioAparell,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="baixes",
    )
    motiu = models.CharField(max_length=250, blank=True, default="")
    notes = models.TextField(blank=True, default="")
    marcada_per = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="inscripcions_baixes_marcades",
    )
    anul_lada_at = models.DateTimeField(null=True, blank=True)
    anul_lada_per = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="inscripcions_baixes_anullades",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["competicio", "inscripcio"],
                condition=models.Q(comp_aparell__isnull=True) & models.Q(anul_lada_at__isnull=True),
                name="uniq_baixa_global_activa_inscripcio",
            ),
            models.UniqueConstraint(
                fields=["competicio", "inscripcio", "comp_aparell"],
                condition=models.Q(comp_aparell__isnull=False) & models.Q(anul_lada_at__isnull=True),
                name="uniq_baixa_aparell_activa_inscripcio",
            ),
        ]
        indexes = [
            models.Index(fields=["competicio", "inscripcio"], name="baixacomp_inscripcio_idx"),
            models.Index(fields=["competicio", "comp_aparell"], name="baixacomp_aparell_idx"),
            models.Index(fields=["competicio", "anul_lada_at"], name="baixacomp_activa_idx"),
        ]

    @property
    def activa(self):
        return self.anul_lada_at is None

    @property
    def es_global(self):
        return self.comp_aparell_id is None

    def clean(self):
        super().clean()
        errors = {}
        ins_comp_id = getattr(self.inscripcio, "competicio_id", None)
        app_comp_id = getattr(self.comp_aparell, "competicio_id", None)
        if ins_comp_id and self.competicio_id and ins_comp_id != self.competicio_id:
            errors["inscripcio"] = "La inscripcio no pertany a aquesta competicio."
        if app_comp_id and self.competicio_id and app_comp_id != self.competicio_id:
            errors["comp_aparell"] = "L'aparell no pertany a aquesta competicio."
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        scope = "global" if self.comp_aparell_id is None else f"aparell={self.comp_aparell_id}"
        return f"Baixa ins={self.inscripcio_id} {scope}"


# OBSOLETA
class TrampoliConfiguracio(models.Model):
    competicio = models.OneToOneField(Competicio, on_delete=models.CASCADE, related_name="cfg_trampoli")
    nombre_jutges_execucio = models.PositiveSmallIntegerField(default=3)
    nombre_jutges_dificultat = models.PositiveSmallIntegerField(default=1)
    pes_execucio = models.DecimalField(max_digits=5, decimal_places=2, default=1.00)
    pes_dificultat = models.DecimalField(max_digits=5, decimal_places=2, default=1.00)
    sistema_classificacio = models.CharField(max_length=50, default="suma")
    nombre_exercicis = models.PositiveSmallIntegerField(default=1, verbose_name="Nombre d'exercicis de cada gimnasta")

    nombre_notes_valides_execucio = models.PositiveSmallIntegerField(
        default=3,
        verbose_name="Nombre de notes d'execucio valides",
    )
    CRITERI_EXEC_CHOICES = [
        ("totes", "Totes (mitjana)"),
        ("eliminar_extrems", "Eliminar extrems"),
        ("maximes", "Notes maximes"),
        ("minimes", "Notes minimes"),
    ]
    criteri_execucio = models.CharField(
        max_length=20,
        choices=CRITERI_EXEC_CHOICES,
        default="totes",
        verbose_name="Criteri seleccio execucio",
    )
    MODE_EXECUCIO_CHOICES = [
        ("salts", "Per salts (S1..S11)"),
        ("manual", "Execucio global manual"),
    ]
    mode_execucio = models.CharField(max_length=10, choices=MODE_EXECUCIO_CHOICES, default="salts")

    mostrar_salts = models.BooleanField(default=True, verbose_name="Mostrar Notes per Salts")
    mostrar_dificultat = models.BooleanField(default=True, verbose_name="Mostrar Dificultat")
    mostrar_tof = models.BooleanField(default=True, verbose_name="Mostrar TOF")
    mostrar_hd = models.BooleanField(default=True, verbose_name="Mostrar HD")
    mostrar_penalitzacio = models.BooleanField(default=True, verbose_name="Mostrar Penalitzacio")
    mostrar_total = models.BooleanField(default=True, verbose_name="Mostrar Total")

    def clean(self):
        super().clean()
        if self.nombre_notes_valides_execucio and self.nombre_jutges_execucio:
            if self.nombre_notes_valides_execucio > self.nombre_jutges_execucio:
                raise ValidationError({
                    "nombre_notes_valides_execucio": "Ha de ser menor o igual al nombre de jutges d'execucio."
                })


# CASI OBSOLETA, SUBSTITUIDA PER SCOREENTRY
class TrampoliNota(models.Model):
    competicio = models.ForeignKey(Competicio, on_delete=models.CASCADE, related_name="notes_trampoli")
    inscripcio = models.ForeignKey(Inscripcio, on_delete=models.CASCADE, related_name="notes_trampoli")
    exercici = models.PositiveSmallIntegerField(default=1)
    comp_aparell = models.ForeignKey(
        CompeticioAparell,
        on_delete=models.CASCADE,
        related_name="notes",
    )

    execucio_manual = models.DecimalField(max_digits=7, decimal_places=3, null=True, blank=True)
    execucio_manuals = models.JSONField(default=list, blank=True)
    notes_execucio = models.JSONField(default=list, blank=True)
    crash_execucio = models.JSONField(default=list, blank=True)
    execucio_total = models.DecimalField(max_digits=7, decimal_places=3, default=0)
    dificultat = models.DecimalField(max_digits=6, decimal_places=3, default=0)
    tof = models.DecimalField(max_digits=6, decimal_places=3, default=0)
    hdc = models.DecimalField(max_digits=6, decimal_places=3, default=0)
    penalitzacio = models.DecimalField(max_digits=6, decimal_places=3, default=0)
    total = models.DecimalField(max_digits=7, decimal_places=3, default=0)

    updated_at = models.DateTimeField(auto_now=True)

    def suma_execucio(self) -> float:
        total = 0.0
        for row in self.notes_execucio or []:
            for v in row or []:
                try:
                    total += float(v or 0)
                except Exception:
                    pass
        return total

    def recalcular_total_simple(self):
        self.total = (
            self.suma_execucio()
            + float(self.dificultat or 0)
            + float(self.tof or 0)
            + float(self.hdc or 0)
            - float(self.penalitzacio or 0)
        )

    def clean(self):
        super().clean()
        n_jutges = 3
        try:
            cfg = getattr(self.competicio, "cfg_trampoli", None)
            if cfg and cfg.nombre_jutges_execucio:
                n_jutges = int(cfg.nombre_jutges_execucio)
        except Exception:
            n_jutges = 3

        if not isinstance(self.notes_execucio, list):
            self.notes_execucio = []

        while len(self.notes_execucio) < n_jutges:
            self.notes_execucio.append([0] * NUM_SALTS)
        if len(self.notes_execucio) > n_jutges:
            self.notes_execucio = self.notes_execucio[:n_jutges]

        for i in range(n_jutges):
            row = self.notes_execucio[i]
            if not isinstance(row, list):
                row = []
            row = (row + [0] * NUM_SALTS)[:NUM_SALTS]
            self.notes_execucio[i] = row

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["competicio", "inscripcio", "exercici", "comp_aparell"],
                name="uniq_nota_trampoli_per_exercici_aparell",
            )
        ]
