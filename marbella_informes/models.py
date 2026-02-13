from django.db import models
from django.utils import timezone
import os

instalacio_choices = [("marbella", "MARBELLA")] 
MEDIA_ROOT = os.getenv("MEDIA_ROOT", "media/")


class AnnualReport(models.Model):
    # Si tens un model Instal·lacio a la plataforma, canvia a FK
    instal_lacio_nom = models.CharField(max_length=32, choices=instalacio_choices)
    any = models.PositiveIntegerField(default=timezone.now().year)

    # Config “retocable” per l’usuari abans d’analitzar
    # (llindars, exclusions, noms d’espais, mapes, etc.)
    config = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=64, default="draft")
    progress = models.PositiveSmallIntegerField(default=0)  # 0..100
    analysis_error = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    analysis_result = models.JSONField(null=True, blank=True)  

    class Meta:
        unique_together = ("instal_lacio_nom", "any")
        ordering = ["-any", "instal_lacio_nom"]

    def __str__(self):
        return f"{self.instal_lacio_nom} · Informe {self.any}"





def annual_dataset_upload_path(instance, filename):
    return f"marbella/{instance.report.any}/{instance.tipus}/{filename}"

class AnnualDataset(models.Model):
    
    class DatasetType(models.TextChoices):
        CLIENTS = "clients", "Clients / abonats"
        RESERVES = "reserves", "Reserves d’espais"

    report = models.ForeignKey(AnnualReport, on_delete=models.CASCADE, related_name="datasets")
    tipus = models.CharField(max_length=32, choices=DatasetType.choices)
    fitxer = models.FileField(upload_to=annual_dataset_upload_path)
    notes = models.CharField(max_length=255, blank=True, default="")

    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("report", "tipus")
        ordering = ["tipus"]

    def __str__(self):
        return f"{self.report} · {self.get_tipus_display()}"
    


