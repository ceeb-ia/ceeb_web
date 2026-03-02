from django.conf import settings
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
            # per ara: totes tenen notes (o pots limitar-ho si vols)
            return self.tipus in {
                self.Tipus.TRAMPOLI,
            }

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
            models.Index(fields=["competicio", "role", "is_active"]),
            models.Index(fields=["user", "is_active"]),
        ]

    def __str__(self):
        return f"{self.user} / {self.competicio} / {self.role}"


class Equip(models.Model):
    class Origen(models.TextChoices):
        MANUAL = "manual", "Manual"
        AUTO = "auto", "Automatic"

    competicio = models.ForeignKey(
        Competicio,
        on_delete=models.CASCADE,
        related_name="equips",
    )
    nom = models.CharField(max_length=180)
    origen = models.CharField(
        max_length=20,
        choices=Origen.choices,
        default=Origen.MANUAL,
    )
    criteri = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["nom", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["competicio", "nom"],
                name="uniq_equip_nom_per_competicio",
            )
        ]
        indexes = [
            models.Index(fields=["competicio", "nom"]),
        ]

    def __str__(self):
        return f"{self.nom} ({self.competicio})"


class Inscripcio(models.Model):
    competicio = models.ForeignKey(Competicio, on_delete=models.CASCADE, related_name="inscripcions")

    nom_i_cognoms = models.CharField(max_length=255)

    categoria = models.CharField(max_length=80, blank=True, null=True)
    subcategoria = models.CharField(max_length=120, blank=True, null=True)
    entitat = models.CharField(max_length=120, blank=True, null=True)
    document = models.CharField(max_length=32, blank=True, null=True)  # DNI/Passaport
    sexe = models.CharField(max_length=50, blank=True, null=True)
    data_naixement = models.DateField(blank=True, null=True)
    ordre_sortida = models.PositiveIntegerField(null=True, blank=True, db_index=True)
    group_by_default = models.JSONField(default=list, blank=True)
    grup = models.PositiveIntegerField(null=True, blank=True, db_index=True)
    equip = models.ForeignKey(
        Equip,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_index=True,
        related_name="membres",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    extra = models.JSONField(default=dict, blank=True)
    dedupe_key = models.CharField(max_length=64, blank=True, null=True, db_index=True)

    class Meta:
        ordering = ["categoria", "subcategoria", "entitat", "sexe", "data_naixement", "nom_i_cognoms"]
        constraints = [
            models.UniqueConstraint(
                fields=["competicio", "dedupe_key"],
                condition=models.Q(dedupe_key__isnull=False) & ~models.Q(dedupe_key=""),
                name="uniq_inscripcio_competicio_dedupe_key",
            ),
        ]
        indexes = [
            models.Index(fields=["competicio", "categoria", "subcategoria"]),
        ]

    def __str__(self):
        return f"{self.nom_i_cognoms} ({self.competicio})"
