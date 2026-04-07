from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

class Competicio(models.Model):
    
    class Tipus(models.TextChoices):
        NATACIO = "natacio", "Natació"
        PATINATGE = "patinatge", "Patinatge"
        TRAMPOLI = "trampoli", "Gimnàstica trampolí"
        ARTISTICA = "artistica", "Gimnàstica artística"
    nom = models.CharField(max_length=255)
    data = models.DateField(blank=True, null=True)
    tipus = models.CharField(max_length=20, choices=Tipus.choices, default=Tipus.TRAMPOLI)
    group_by_default = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    tab_merges = models.JSONField(default=dict, blank=True)
    inscripcions_schema = models.JSONField(default=dict, blank=True)
    inscripcions_view = models.JSONField(default=dict, blank=True)  # preferències UI (columnes, noms grups, etc.)

    def te_notes(self) -> bool:
            return True

    def __str__(self):
        return self.nom


class CompeticioMembership(models.Model):
    class Role(models.TextChoices):
        OWNER = "owner", "Owner"
        EDITOR = "editor", "Editor"
        JUDGE_ADMIN = "judge_admin", "Judge Admin"
        SCORING = "scoring", "Scoring"
        ROTACIONS = "rotacions", "Rotacions"
        CLASSIFICACIONS = "classificacions", "Classificacions"
        READONLY = "readonly", "Readonly"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="competicio_memberships",
    )
    competicio = models.ForeignKey(
        Competicio,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    role = models.CharField(
        max_length=30,
        choices=Role.choices,
        default=Role.READONLY,
    )
    is_active = models.BooleanField(default=True)
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="granted_competicio_memberships",
    )
    notes = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["competicio_id", "user_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "competicio"],
                name="uniq_competicio_membership_user_competicio",
            )
        ]
        indexes = [
            models.Index(
                fields=["competicio", "role", "is_active"],
                name="competicion_competi_043c1d_idx",
            ),
            models.Index(
                fields=["user", "is_active"],
                name="competicion_user_id_bf218f_idx",
            ),
        ]

    def __str__(self):
        return f"{self.user} / {self.competicio} / {self.role}"


