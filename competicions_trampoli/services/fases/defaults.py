from __future__ import annotations

from typing import Optional

from ...models.competicio import CompeticioAparell, CompeticioAparellFase

DEFAULT_PHASE_CODE = "DEFAULT"
DEFAULT_PHASE_NAME = "Fase unica"


def get_default_phase_for_comp_aparell(
    comp_aparell: CompeticioAparell,
) -> Optional[CompeticioAparellFase]:
    if comp_aparell is None or not getattr(comp_aparell, "id", None):
        return None
    return (
        CompeticioAparellFase.objects
        .filter(comp_aparell=comp_aparell, codi=DEFAULT_PHASE_CODE)
        .select_related("competicio", "comp_aparell", "comp_aparell__aparell")
        .first()
    )


def ensure_default_phase_for_comp_aparell(
    comp_aparell: CompeticioAparell,
) -> CompeticioAparellFase:
    if comp_aparell is None or not getattr(comp_aparell, "id", None):
        raise ValueError("Cal una instancia CompeticioAparell desada.")

    phase, _created = CompeticioAparellFase.objects.get_or_create(
        competicio=comp_aparell.competicio,
        comp_aparell=comp_aparell,
        codi=DEFAULT_PHASE_CODE,
        defaults={
            "nom": DEFAULT_PHASE_NAME,
            "ordre": 1,
            "estat": CompeticioAparellFase.Estat.PUBLISHED,
            "config": {
                "source_mode": "legacy_default",
                "implicit": True,
            },
        },
    )
    return phase
