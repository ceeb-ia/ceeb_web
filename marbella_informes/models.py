from django.db import models
from django.utils import timezone
import os
from django.db.models import Q

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

   # Estat de l'informe
    report_status = models.CharField(max_length=64, default="report_draft")
    report_progress = models.PositiveSmallIntegerField(default=0)
    report_error = models.TextField(blank=True, default="")

    # Fitxer final
    report_file = models.FileField(upload_to="marbella/%Y/reports/", null=True, blank=True)
    report_generated_at = models.DateTimeField(null=True, blank=True)


    class Meta:
        unique_together = ("instal_lacio_nom", "any")
        ordering = ["-any", "instal_lacio_nom"]

    def __str__(self):
        return f"{self.instal_lacio_nom} · Informe {self.any}"


class AnnualReportSection(models.Model):
    report = models.ForeignKey(AnnualReport, related_name="sections", on_delete=models.CASCADE)
    key = models.CharField(max_length=64)      # ex: "clients", "reserves"
    title = models.CharField(max_length=200)
    content = models.TextField(blank=True, default="")
    source = models.CharField(max_length=16, default="llm")  # llm/manual
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = (("report", "key"),)



def annual_dataset_upload_path(instance, filename):
    if instance.period:
        return f"marbella/{instance.report.any}/{instance.tipus}/{instance.period:02d}/{filename}"
    return f"marbella/{instance.report.any}/{instance.tipus}/{filename}"

class AnnualDataset(models.Model):
    
    class DatasetType(models.TextChoices):
        CLIENTS = "clients", "Clients / abonats"
        RESERVES = "reserves", "Reserves d’espais"
        OCASIONALS = "ocasionals", "Ocasionals (mensual)"


    report = models.ForeignKey(AnnualReport, on_delete=models.CASCADE, related_name="datasets")
    tipus = models.CharField(max_length=32, choices=DatasetType.choices)
    fitxer = models.FileField(upload_to=annual_dataset_upload_path, blank=True)  # blank=True per permetre crear instància sense fitxer i després pujar-lo
    notes = models.CharField(max_length=255, blank=True, default="")

    # opcional: si els datasets són mensuals, permet identificar el mes (1..12)
    period = models.PositiveSmallIntegerField(null=True, blank=True)  # 1..12


    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["tipus", "period", "uploaded_at"]
        constraints = [
            # Un únic "clients" per report (period null)
            models.UniqueConstraint(
                fields=["report", "tipus"],
                condition=Q(period__isnull=True),
                name="uniq_report_tipus_when_period_null",
            ),
            # Un únic (tipus, mes) quan period no és null
            models.UniqueConstraint(
                fields=["report", "tipus", "period"],
                condition=Q(period__isnull=False),
                name="uniq_report_tipus_period_when_period_not_null",
            ),
        ]
    def __str__(self):
        return f"{self.report} · {self.get_tipus_display()}"
    


