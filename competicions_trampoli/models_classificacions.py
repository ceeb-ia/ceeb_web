# models_classificacions.py
from django.db import models
from django.utils import timezone
from .models import Competicio

class ClassificacioConfig(models.Model):
    """
    Config declarativa d'una classificació dins una competició.
    Tot el comportament "general" es guarda a JSON per evitar migracions contínues.
    """

    TIPUS_CHOICES = [
        ("individual", "Individual"),
        ("entitat", "Entitat"),
    ]

    competicio = models.ForeignKey(
        Competicio,
        on_delete=models.CASCADE,
        related_name="classificacions_cfg",
    )

    nom = models.CharField(max_length=120, default="Nova classificació")
    activa = models.BooleanField(default=True)
    ordre = models.PositiveSmallIntegerField(default=1)

    tipus = models.CharField(max_length=20, choices=TIPUS_CHOICES, default="individual")

    # Estructura recomanada (editable des del builder)
    # veure `DEFAULT_SCHEMA` al template i al service
    schema = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["ordre", "id"]

    def __str__(self):
        return f"{self.competicio_id} · {self.nom}"


class ClassificacioCache(models.Model):
    """
    Cache opcional: resultat calculat per cada partició.
    Si no el vols, pots no fer servir aquest model (cap view obliga).
    """
    classificacio = models.ForeignKey(
        ClassificacioConfig,
        on_delete=models.CASCADE,
        related_name="cache",
    )
    particio_key = models.CharField(max_length=255, db_index=True)  # ex: "categoria:BENJAMI|sub:..."
    resultat = models.JSONField(default=list, blank=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("classificacio", "particio_key")
        ordering = ["particio_key"]
