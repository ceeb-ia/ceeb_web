import uuid
from django.db import models
from django.utils import timezone

from .models import Competicio
from .models_trampoli import CompeticioAparell


class JudgeDeviceToken(models.Model):
    """
    Token per QR (clau d'accés). Sense usuari.
    Un token pot puntuar múltiples camps del mateix aparell.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    competicio = models.ForeignKey(Competicio, on_delete=models.CASCADE, related_name="judge_tokens")
    comp_aparell = models.ForeignKey(CompeticioAparell, on_delete=models.CASCADE, related_name="judge_tokens")

    label = models.CharField(max_length=120, blank=True, default="")  # ex: "Jutge 2 - Taula A"

    # Llista de permisos (JSON):
    # [
    #   {"field_code":"E","judge_index":1,"item_start":1,"item_count":None},
    #   {"field_code":"D","judge_index":2}
    # ]
    permissions = models.JSONField(default=list, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    is_active = models.BooleanField(default=True)

    def is_valid(self) -> bool:
        return self.is_active and self.revoked_at is None

    def touch(self):
        self.last_used_at = timezone.now()
        self.save(update_fields=["last_used_at"])

    def __str__(self):
        return f"{self.competicio_id} / {self.comp_aparell_id} / {self.label or self.id}"