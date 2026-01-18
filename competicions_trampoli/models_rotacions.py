from django.db import models
from django.core.exceptions import ValidationError
from .models import Competicio  # el teu model base
from .models_trampoli import CompeticioAparell  # el que m'has adjuntat
from django.db.models import Q

class RotacioEstacio(models.Model):
    TIPUS_CHOICES = [
        ("aparell", "Aparell"),
        ("descans", "Descans"),
    ]

    competicio = models.ForeignKey(Competicio, on_delete=models.CASCADE, related_name="rot_estacions")
    tipus = models.CharField(max_length=10, choices=TIPUS_CHOICES, default="aparell")
    # Si és "aparell": apunta al CompeticioAparell real (configurat per la competició)
    comp_aparell = models.ForeignKey(
        CompeticioAparell,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="rot_estacions",
    )

    nom_override = models.CharField(max_length=120, blank=True, default="")
    ordre = models.PositiveIntegerField(default=1, db_index=True)
    actiu = models.BooleanField(default=True)

    class Meta:
        ordering = ["ordre", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["competicio", "comp_aparell"],
                condition=Q(comp_aparell__isnull=False),
                name="uniq_rot_estacio_per_comp_aparell_notnull",
            )
        ]

    def clean(self):
        super().clean()
        if self.tipus == "aparell" and not self.comp_aparell:
            raise ValidationError("Una estació d'aparell requereix comp_aparell.")
        if self.tipus == "descans":
            self.comp_aparell = None

    @property
    def nom(self):
        if self.nom_override.strip():
            return self.nom_override.strip()
        if self.tipus == "descans":
            return "Descans"
        # comp_aparell -> aparell -> nom
        return getattr(getattr(self.comp_aparell, "aparell", None), "nom", "Aparell")

    def __str__(self):
        return f"{self.competicio} | {self.nom}"


class RotacioFranja(models.Model):
    competicio = models.ForeignKey(Competicio, on_delete=models.CASCADE, related_name="rot_franges")
    hora_inici = models.TimeField()
    hora_fi = models.TimeField()
    ordre = models.PositiveIntegerField(default=1, db_index=True)
    titol = models.CharField(max_length=120, blank=True, default="")

    class Meta:
        ordering = ["ordre", "id"]
        constraints = [
            models.UniqueConstraint(fields=["competicio", "ordre"], name="uniq_rot_franja_ordre"),
        ]

    def clean(self):
        super().clean()
        if self.hora_fi <= self.hora_inici:
            raise ValidationError("L'hora fi ha de ser posterior a l'hora inici.")

    def __str__(self):
        label = self.titol.strip() or "Franja"
        return f"{label} {self.hora_inici}-{self.hora_fi}"


class RotacioAssignacio(models.Model):
    competicio = models.ForeignKey(Competicio, on_delete=models.CASCADE, related_name="rot_assignacions")
    franja = models.ForeignKey(RotacioFranja, on_delete=models.CASCADE, related_name="assignacions")
    estacio = models.ForeignKey(RotacioEstacio, on_delete=models.CASCADE, related_name="assignacions")

    # grup = número de grup (com ja uses a Inscripcio.grup)
    grup = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["franja", "estacio"], name="uniq_rot_cell"),
        ]
        indexes = [
            models.Index(fields=["competicio", "grup"]),
        ]

    def __str__(self):
        return f"{self.competicio} | {self.franja} | {self.estacio} => G{self.grup or '-'}"
