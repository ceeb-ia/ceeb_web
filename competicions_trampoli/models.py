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

    def te_notes(self) -> bool:
            # per ara: totes tenen notes (o pots limitar-ho si vols)
            return self.tipus in {
                self.Tipus.TRAMPOLI,
            }

    def __str__(self):
        return self.nom


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
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["categoria", "subcategoria", "entitat", "sexe", "data_naixement", "nom_i_cognoms"]
        indexes = [
            models.Index(fields=["competicio", "categoria", "subcategoria"]),
        ]

    def __str__(self):
        return f"{self.nom_i_cognoms} ({self.competicio})"
