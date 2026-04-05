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
    nombre_exercicis = models.PositiveSmallIntegerField(default=1, verbose_name="Nombre d'exercicis")

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
            models.UniqueConstraint(fields=["competicio", "aparell"], name="uniq_competicio_aparell")
        ]

    def clean(self):
        super().clean()
        if self.aparell_id and self.aparell.created_by_id is None:
            raise ValidationError({"aparell": "L'aparell seleccionat no es valid."})

    @property
    def is_team_context_mode(self) -> bool:
        return self.is_team_competition_unit

    @property
    def is_team_competition_unit(self) -> bool:
        return bool(self.aparell_id and self.aparell.is_team_competition_unit)


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
