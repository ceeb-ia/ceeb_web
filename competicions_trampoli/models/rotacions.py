import re

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from .base import Competicio
from .competicio import CompeticioAparell, ProgramUnit
from .inscripcions import GrupCompeticio


HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
DEFAULT_FRANJA_BACKGROUND_COLORS = {
    "competition": "#DBEAFE",
    "break": "#DCFCE7",
    "awards": "#FEF3C7",
    "separator": "#E5E7EB",
}


def normalize_hex_color(value):
    raw = str(value or "").strip()
    if not raw:
        return ""
    if not HEX_COLOR_RE.match(raw):
        raise ValidationError("El color de fons ha de tenir format #RRGGBB.")
    return raw.upper()


def _hex_to_rgb(value):
    clean = normalize_hex_color(value).lstrip("#")
    return tuple(int(clean[idx:idx + 2], 16) for idx in (0, 2, 4))


def _rgb_to_hex(rgb):
    r, g, b = [max(0, min(255, int(channel))) for channel in rgb]
    return f"#{r:02X}{g:02X}{b:02X}"


def background_text_color(value):
    try:
        red, green, blue = _hex_to_rgb(value)
    except ValidationError:
        return "#0F172A"
    luminance = (0.299 * red) + (0.587 * green) + (0.114 * blue)
    return "#0F172A" if luminance >= 170 else "#FFFFFF"


def background_border_color(value):
    try:
        red, green, blue = _hex_to_rgb(value)
    except ValidationError:
        return "#CBD5E1"
    is_light = background_text_color(value) == "#0F172A"
    factor = 0.82 if is_light else 1.18
    adjusted = []
    for channel in (red, green, blue):
        if is_light:
            adjusted.append(channel * factor)
        else:
            adjusted.append(channel + ((255 - channel) * (factor - 1.0)))
    return _rgb_to_hex(adjusted)

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
    TIPUS_COMPETITION = "competition"
    TIPUS_BREAK = "break"
    TIPUS_AWARDS = "awards"
    TIPUS_SEPARATOR = "separator"
    TIPUS_CHOICES = [
        (TIPUS_COMPETITION, "Competicio"),
        (TIPUS_BREAK, "Descans"),
        (TIPUS_AWARDS, "Premis"),
        (TIPUS_SEPARATOR, "Separador"),
    ]
    TIPUS_LABELS = {
        TIPUS_COMPETITION: "Franja",
        TIPUS_BREAK: "Descans",
        TIPUS_AWARDS: "Premis",
        TIPUS_SEPARATOR: "Separador",
    }
    DEFAULT_BACKGROUND_COLORS = DEFAULT_FRANJA_BACKGROUND_COLORS

    competicio = models.ForeignKey(Competicio, on_delete=models.CASCADE, related_name="rot_franges")
    hora_inici = models.TimeField()
    hora_fi = models.TimeField()
    ordre = models.PositiveIntegerField(default=1, db_index=True)
    ordre_visual = models.PositiveIntegerField(default=1, db_index=True)
    titol = models.CharField(max_length=120, blank=True, default="")
    tipus = models.CharField(max_length=20, choices=TIPUS_CHOICES, default=TIPUS_COMPETITION, db_index=True)
    color_fons = models.CharField(max_length=7, blank=True, default="")

    class Meta:
        ordering = ["ordre", "id"]
        constraints = [
            models.UniqueConstraint(fields=["competicio", "ordre"], name="uniq_rot_franja_ordre"),
        ]

    def clean(self):
        super().clean()
        if self.tipus not in {choice[0] for choice in self.TIPUS_CHOICES}:
            raise ValidationError("Tipus de franja invalid.")
        if self.hora_fi <= self.hora_inici:
            raise ValidationError("L'hora fi ha de ser posterior a l'hora inici.")
        self.color_fons = normalize_hex_color(self.color_fons)

    @property
    def is_competitive(self):
        return self.tipus == self.TIPUS_COMPETITION

    @property
    def tipus_label(self):
        return self.TIPUS_LABELS.get(self.tipus, "Franja")

    @property
    def display_label(self):
        return self.titol.strip() or self.tipus_label

    @property
    def resolved_background_color(self):
        try:
            manual = normalize_hex_color(self.color_fons)
        except ValidationError:
            manual = ""
        return manual or self.DEFAULT_BACKGROUND_COLORS.get(self.tipus, self.DEFAULT_BACKGROUND_COLORS[self.TIPUS_COMPETITION])

    @property
    def resolved_text_color(self):
        return background_text_color(self.resolved_background_color)

    @property
    def resolved_border_color(self):
        return background_border_color(self.resolved_background_color)

    def __str__(self):
        label = self.display_label
        return f"{label} {self.hora_inici}-{self.hora_fi}"


class RotacioAssignacio(models.Model):
    competicio = models.ForeignKey(Competicio, on_delete=models.CASCADE, related_name="rot_assignacions")
    franja = models.ForeignKey(RotacioFranja, on_delete=models.CASCADE, related_name="assignacions")
    estacio = models.ForeignKey(RotacioEstacio, on_delete=models.CASCADE, related_name="assignacions")

    # grup = número de grup (com ja uses a Inscripcio.grup)
    grup = models.PositiveIntegerField(null=True, blank=True)
    # Nova representacio: diversos grups a una mateixa cel-la
    grups = models.JSONField(default=list, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["franja", "estacio"], name="uniq_rot_cell"),
        ]
        indexes = [
            models.Index(fields=["competicio", "grup"]),
        ]

    def __str__(self):
        if isinstance(self.grups, list) and self.grups:
            joined = ",".join(str(x) for x in self.grups)
            return f"{self.competicio} | {self.franja} | {self.estacio} => G{joined}"
        return f"{self.competicio} | {self.franja} | {self.estacio} => G{self.grup or '-'}"


class RotacioAssignacioGrup(models.Model):
    assignacio = models.ForeignKey(
        RotacioAssignacio,
        on_delete=models.CASCADE,
        related_name="grup_links",
    )
    grup = models.ForeignKey(
        GrupCompeticio,
        on_delete=models.CASCADE,
        related_name="rotacio_links",
    )
    ordre = models.PositiveIntegerField(default=1, db_index=True)

    class Meta:
        ordering = ["ordre", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["assignacio", "grup"],
                name="uniq_rot_assignacio_grup_link",
            ),
        ]
        indexes = [
            models.Index(fields=["grup", "ordre"]),
        ]

    def __str__(self):
        return f"{self.assignacio} -> {self.grup}"


class RotacioAssignacioSerieEquip(models.Model):
    assignacio = models.ForeignKey(
        RotacioAssignacio,
        on_delete=models.CASCADE,
        related_name="serie_links",
    )
    serie = models.ForeignKey(
        "competicions_trampoli.SerieEquip",
        on_delete=models.CASCADE,
        related_name="rotacio_links",
    )
    ordre = models.PositiveIntegerField(default=1, db_index=True)

    class Meta:
        ordering = ["ordre", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["assignacio", "serie"],
                name="uniq_rot_assignacio_serie_equip_link",
            ),
        ]
        indexes = [
            models.Index(fields=["serie", "ordre"]),
        ]

    def __str__(self):
        return f"{self.assignacio} -> {self.serie}"


class RotacioAssignacioProgramUnit(models.Model):
    assignacio = models.ForeignKey(
        RotacioAssignacio,
        on_delete=models.CASCADE,
        related_name="program_unit_links",
    )
    program_unit = models.ForeignKey(
        ProgramUnit,
        on_delete=models.CASCADE,
        related_name="rotacio_links",
    )
    ordre = models.PositiveIntegerField(default=1, db_index=True)

    class Meta:
        ordering = ["ordre", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["assignacio", "program_unit"],
                name="uniq_rot_assignacio_program_unit_link",
            ),
        ]
        indexes = [
            models.Index(fields=["program_unit", "ordre"], name="rot_assign_unit_ordre_idx"),
        ]

    def clean(self):
        super().clean()
        errors = {}
        assignacio = getattr(self, "assignacio", None)
        program_unit = getattr(self, "program_unit", None)
        fase = getattr(program_unit, "fase", None)
        estacio = getattr(assignacio, "estacio", None)
        if assignacio and program_unit and fase:
            if assignacio.competicio_id != fase.competicio_id:
                errors["program_unit"] = "La unitat programable no pertany a la mateixa competicio."
            if (
                getattr(estacio, "tipus", "") != "aparell"
                or not getattr(estacio, "comp_aparell_id", None)
                or estacio.comp_aparell_id != fase.comp_aparell_id
            ):
                errors["program_unit"] = "La unitat programable s'ha de col.locar a l'estacio del seu aparell."
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"{self.assignacio} -> {self.program_unit}"
