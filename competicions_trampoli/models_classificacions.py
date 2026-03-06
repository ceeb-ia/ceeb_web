# models_classificacions.py
from django.conf import settings
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
        ("equips", "Equips"),
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


class ClassificacioTemplateGlobal(models.Model):
    """
    Plantilla global reutilitzable per generar ClassificacioConfig dins de competicions.
    El payload guarda schema canonic portable (sense IDs locals de competicio).
    """

    TIPUS_CHOICES = ClassificacioConfig.TIPUS_CHOICES

    nom = models.CharField(max_length=140)
    slug = models.SlugField(max_length=180, unique=True)
    descripcio = models.CharField(max_length=255, blank=True, default="")
    activa = models.BooleanField(default=True)
    tipus = models.CharField(max_length=20, choices=TIPUS_CHOICES, default="individual")

    payload = models.JSONField(default=dict, blank=True)
    requirements = models.JSONField(default=dict, blank=True)

    version = models.PositiveIntegerField(default=1)
    uses_count = models.PositiveIntegerField(default=0)
    last_used_at = models.DateTimeField(null=True, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="classificacio_templates_created",
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["nom", "id"]

    def __str__(self):
        return f"{self.nom} (v{self.version})"
