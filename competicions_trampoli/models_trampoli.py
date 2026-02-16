# models_trampoli.py
from django.db import models
from django.core.exceptions import ValidationError
from .models import Competicio, Inscripcio

NUM_SALTS = 11  # S1..S11


class Aparell(models.Model):
    codi = models.CharField(max_length=20, unique=True)   # TRAMP, DMT, TUMB...
    nom = models.CharField(max_length=60)                # "Trampolí", "DMT", ...
    actiu = models.BooleanField(default=True)

    class Meta:
        ordering = ["nom"]

    def __str__(self):
        return self.nom


class CompeticioAparell(models.Model):
    competicio = models.ForeignKey(Competicio, on_delete=models.CASCADE, related_name="aparells_cfg")
    aparell = models.ForeignKey(Aparell, on_delete=models.PROTECT, related_name="competicio_cfg")
    nombre_exercicis = models.PositiveSmallIntegerField(default=1, verbose_name="Nombre d'exercicis")

    #CREC QUE REDUNDANT A PARTIR D'AQUI; INUTIL JA
    ordre = models.PositiveSmallIntegerField(default=1)

    # Nombre d'elements (ex: salts)
    nombre_elements = models.PositiveSmallIntegerField(default=11)

    # Ítems de puntuació disponibles
    te_execucio = models.BooleanField(default=True)
    te_dificultat = models.BooleanField(default=True)
    te_tof = models.BooleanField(default=True)
    te_hd = models.BooleanField(default=True)
    te_penalitzacio = models.BooleanField(default=True)

    MODE_EXECUCIO_CHOICES = [("salts", "Per elements"), ("manual", "Execució global manual")]
    mode_execucio = models.CharField(max_length=10, choices=MODE_EXECUCIO_CHOICES, default="salts")

    actiu = models.BooleanField(default=True)

    class Meta:
        ordering = ["ordre", "id"]
        constraints = [
            models.UniqueConstraint(fields=["competicio", "aparell"], name="uniq_competicio_aparell")
        ]


# OBSOLETA
class TrampoliConfiguracio(models.Model):
    competicio = models.OneToOneField(Competicio, on_delete=models.CASCADE, related_name="cfg_trampoli")
    nombre_jutges_execucio = models.PositiveSmallIntegerField(default=3)
    nombre_jutges_dificultat = models.PositiveSmallIntegerField(default=1)
    pes_execucio = models.DecimalField(max_digits=5, decimal_places=2, default=1.00)
    pes_dificultat = models.DecimalField(max_digits=5, decimal_places=2, default=1.00)
    sistema_classificacio = models.CharField(max_length=50, default="suma")
    nombre_exercicis = models.PositiveSmallIntegerField(default=1, verbose_name="Nombre d'exercicis de cada gimnasta")

    # quantes notes d'execució compten (<= nombre_jutges_execucio)
    nombre_notes_valides_execucio = models.PositiveSmallIntegerField(
        default=3,
        verbose_name="Nombre de notes d'execució vàlides"
    )
    # criteri de selecció
    CRITERI_EXEC_CHOICES = [
        ("totes", "Totes (mitjana)"),
        ("eliminar_extrems", "Eliminar extrems"),
        ("maximes", "Notes màximes"),
        ("minimes", "Notes mínimes"),
    ]
    criteri_execucio = models.CharField(
        max_length=20,
        choices=CRITERI_EXEC_CHOICES,
        default="totes",
        verbose_name="Criteri selecció execució",
    )
    MODE_EXECUCIO_CHOICES = [
        ("salts", "Per salts (S1..S11)"),
        ("manual", "Execució global manual"),
    ]
    mode_execucio = models.CharField(max_length=10, choices=MODE_EXECUCIO_CHOICES, default="salts")

    mostrar_salts = models.BooleanField(default=True, verbose_name="Mostrar Notes per Salts")
    mostrar_dificultat = models.BooleanField(default=True, verbose_name="Mostrar Dificultat")
    mostrar_tof = models.BooleanField(default=True, verbose_name="Mostrar TOF")
    mostrar_hd = models.BooleanField(default=True, verbose_name="Mostrar HD")
    mostrar_penalitzacio = models.BooleanField(default=True, verbose_name="Mostrar Penalització")
    mostrar_total = models.BooleanField(default=True, verbose_name="Mostrar Total")


    def clean(self):
        super().clean()
        if self.nombre_notes_valides_execucio and self.nombre_jutges_execucio:
            if self.nombre_notes_valides_execucio > self.nombre_jutges_execucio:
                raise ValidationError({
                    "nombre_notes_valides_execucio": "Ha de ser menor o igual al nombre de jutges d'execució."
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
    execucio_manuals = models.JSONField(default=list, blank=True)  # NOU: [J1..Jn]
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

        # 1) quants jutges d'execució toca tenir
        n_jutges = 3
        try:
            cfg = getattr(self.competicio, "cfg_trampoli", None)
            if cfg and cfg.nombre_jutges_execucio:
                n_jutges = int(cfg.nombre_jutges_execucio)
        except Exception:
            n_jutges = 3

        # 2) normalitza estructura
        if not isinstance(self.notes_execucio, list):
            self.notes_execucio = []

        # assegura longitud n_jutges
        while len(self.notes_execucio) < n_jutges:
            self.notes_execucio.append([0] * NUM_SALTS)
        if len(self.notes_execucio) > n_jutges:
            self.notes_execucio = self.notes_execucio[:n_jutges]

        # 3) per cada jutge: assegura llista i 11 salts
        for i in range(n_jutges):
            row = self.notes_execucio[i]
            if not isinstance(row, list):
                row = []
            row = (row + [0] * NUM_SALTS)[:NUM_SALTS]
            self.notes_execucio[i] = row

        # IMPORTANT: NO llencem ValidationError si hi ha zeros
        # (ja és un estat "encara no complet" i és útil en directe)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["competicio", "inscripcio", "exercici", "comp_aparell"],
                name="uniq_nota_trampoli_per_exercici_aparell",
            )
        ]

