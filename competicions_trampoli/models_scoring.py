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
        return f"Schema {self.comp_aparell.competicio_id} / {self.comp_aparell.aparell.codi}"


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
