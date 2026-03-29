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


class Equip(models.Model):
    class Origen(models.TextChoices):
        MANUAL = "manual", "Manual"
        AUTO = "auto", "Automatic"

    competicio = models.ForeignKey(
        Competicio,
        on_delete=models.CASCADE,
        related_name="equips",
    )
    context = models.ForeignKey(
        "EquipContext",
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
                fields=["context", "nom"],
                name="uniq_equip_nom_per_context",
            )
        ]
        indexes = [
            models.Index(fields=["competicio", "context"], name="equip_competicio_context_idx"),
            models.Index(fields=["context", "nom"], name="equip_context_nom_idx"),
            models.Index(fields=["competicio", "nom"], name="equip_competicio_nom_idx"),
        ]

    def __str__(self):
        return f"{self.nom} ({self.competicio})"

    def clean(self):
        super().clean()
        errors = {}
        if self.context_id and self.context.competicio_id != self.competicio_id:
            errors["context"] = "El context no pertany a la mateixa competicio."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if not self.context_id and self.competicio_id:
            from .services.equip_contexts import ensure_base_equip_context

            self.context = ensure_base_equip_context(self.competicio)
        super().save(*args, **kwargs)


class EquipContext(models.Model):
    competicio = models.ForeignKey(
        Competicio,
        on_delete=models.CASCADE,
        related_name="equip_contexts",
    )
    code = models.SlugField(max_length=80)
    nom = models.CharField(max_length=180)
    description = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["nom", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["competicio", "code"],
                name="uniq_equip_context_code_per_competicio",
            ),
        ]
        indexes = [
            models.Index(fields=["competicio", "code"]),
        ]

    def __str__(self):
        return f"{self.nom} ({self.competicio})"


class GrupCompeticio(models.Model):
    competicio = models.ForeignKey(
        Competicio,
        on_delete=models.CASCADE,
        related_name="grups_competicio",
    )
    legacy_num = models.PositiveIntegerField(null=True, blank=True, db_index=True)
    display_num = models.PositiveIntegerField(db_index=True)
    nom = models.CharField(max_length=180, blank=True, default="")
    actiu = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["display_num", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["competicio", "display_num"],
                name="uniq_grup_competicio_display_num",
            ),
        ]
        indexes = [
            models.Index(fields=["competicio", "actiu", "display_num"]),
        ]

    def __str__(self):
        label = self.nom.strip() or f"Grup {self.display_num}"
        return f"{label} ({self.competicio})"


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
    grup_competicio = models.ForeignKey(
        GrupCompeticio,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="inscripcions",
    )
    ordre_competicio = models.PositiveIntegerField(null=True, blank=True, db_index=True)
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
            models.Index(fields=["competicio", "grup_competicio", "ordre_competicio"]),
        ]

    def __str__(self):
        return f"{self.nom_i_cognoms} ({self.competicio})"

    def save(self, *args, **kwargs):
        current_group = getattr(self, "grup_competicio", None)
        if self.grup_competicio_id and self.grup:
            display_num = getattr(current_group, "display_num", None)
            if display_num and int(display_num) != int(self.grup):
                from .services.competition_groups import ensure_group_for_display_num

                remapped_group = ensure_group_for_display_num(self.competicio, self.grup)
                if remapped_group is not None:
                    self.grup_competicio = remapped_group
                    current_group = remapped_group

        if self.grup_competicio_id and not self.grup:
            display_num = getattr(current_group, "display_num", None)
            if display_num:
                self.grup = display_num

        if self.grup and not self.grup_competicio_id and self.competicio_id:
            from .services.competition_groups import ensure_group_for_display_num

            group = ensure_group_for_display_num(self.competicio, self.grup)
            if group is not None:
                self.grup_competicio = group

        if self.grup_competicio_id and self.ordre_competicio is None:
            max_order = (
                Inscripcio.objects
                .filter(competicio_id=self.competicio_id, grup_competicio_id=self.grup_competicio_id)
                .exclude(pk=self.pk)
                .aggregate(models.Max("ordre_competicio"))["ordre_competicio__max"]
                or 0
            )
            self.ordre_competicio = max_order + 1

        if not self.grup_competicio_id:
            self.ordre_competicio = None

        super().save(*args, **kwargs)


class InscripcioEquipAssignacio(models.Model):
    class Origen(models.TextChoices):
        MANUAL = "manual", "Manual"
        AUTO = "auto", "Automatic"

    competicio = models.ForeignKey(
        Competicio,
        on_delete=models.CASCADE,
        related_name="equip_assignacions",
    )
    context = models.ForeignKey(
        EquipContext,
        on_delete=models.CASCADE,
        related_name="assignacions",
    )
    inscripcio = models.ForeignKey(
        Inscripcio,
        on_delete=models.CASCADE,
        related_name="equip_assignacions",
    )
    equip = models.ForeignKey(
        Equip,
        on_delete=models.CASCADE,
        related_name="assignacions_contextuals",
    )
    origen = models.CharField(
        max_length=20,
        choices=Origen.choices,
        default=Origen.MANUAL,
    )
    criteri = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["context_id", "inscripcio_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["context", "inscripcio"],
                name="uniq_equip_assignacio_context_inscripcio",
            ),
        ]
        indexes = [
            models.Index(fields=["competicio", "context"]),
            models.Index(fields=["competicio", "inscripcio"]),
        ]

    def clean(self):
        errors = {}
        competicio_id = self.competicio_id
        if self.context_id and self.context.competicio_id != competicio_id:
            errors["context"] = "El context no pertany a la mateixa competicio."
        if self.inscripcio_id and self.inscripcio.competicio_id != competicio_id:
            errors["inscripcio"] = "La inscripcio no pertany a la mateixa competicio."
        if self.equip_id and self.equip.competicio_id != competicio_id:
            errors["equip"] = "L'equip no pertany a la mateixa competicio."
        if self.context_id and self.equip_id and self.equip.context_id != self.context_id:
            errors["equip"] = "L'equip no pertany al context indicat."
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"{self.context_id} / {self.inscripcio_id} / {self.equip_id}"


class InscripcioMedia(models.Model):
    class Tipus(models.TextChoices):
        AUDIO = "audio", "Audio"
        VIDEO = "video", "Video"
        IMAGE = "image", "Imatge"
        OTHER = "other", "Altre"

    class Source(models.TextChoices):
        MANUAL = "manual", "Manual"
        ASSISTED = "assisted", "Assisted"

    competicio = models.ForeignKey(
        Competicio,
        on_delete=models.CASCADE,
        related_name="inscripcions_media",
    )
    inscripcio = models.ForeignKey(
        Inscripcio,
        on_delete=models.CASCADE,
        related_name="media_files",
    )
    fitxer = models.FileField(upload_to="inscripcions/media/%Y/%m/%d/")
    tipus = models.CharField(
        max_length=20,
        choices=Tipus.choices,
        default=Tipus.OTHER,
        db_index=True,
    )
    mime_type = models.CharField(max_length=120, blank=True, default="")
    original_filename = models.CharField(max_length=255, blank=True, default="")
    file_size_bytes = models.PositiveBigIntegerField(default=0)
    is_primary = models.BooleanField(default=False)
    source = models.CharField(
        max_length=20,
        choices=Source.choices,
        default=Source.MANUAL,
    )
    match_score = models.DecimalField(max_digits=5, decimal_places=4, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["inscripcio_id", "-is_primary", "-created_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["inscripcio", "tipus"],
                condition=models.Q(is_primary=True),
                name="uniq_primary_media_per_inscripcio_tipus",
            ),
        ]
        indexes = [
            models.Index(fields=["competicio", "inscripcio"]),
            models.Index(fields=["competicio", "tipus"]),
        ]

    def clean(self):
        super().clean()
        if self.inscripcio_id and self.competicio_id and self.inscripcio.competicio_id != self.competicio_id:
            raise ValidationError("La media i la inscripcio han de pertanyer a la mateixa competicio.")

    def __str__(self):
        return f"Media ins={self.inscripcio_id} tipus={self.tipus} id={self.id}"
