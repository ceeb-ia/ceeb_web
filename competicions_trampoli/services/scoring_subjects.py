from __future__ import annotations

from typing import Dict, Iterable, Optional, Tuple

from django.db import IntegrityError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404

from ..models import Competicio, Equip, Inscripcio
from ..models_scoring import (
    ScoreEntry,
    ScoreEntryVideo,
    ScoreEntryVideoEvent,
    TeamScoreEntry,
    TeamScoreEntryVideo,
    TeamScoreEntryVideoEvent,
)
from ..models_trampoli import CompeticioAparell, InscripcioAparellExclusio
from .team_scoring import eligible_team_ids_for_comp_aparell, is_team_context_app


def subject_entry_model(comp_aparell: CompeticioAparell):
    return TeamScoreEntry if is_team_context_app(comp_aparell) else ScoreEntry


def subject_video_models(comp_aparell: CompeticioAparell):
    if is_team_context_app(comp_aparell):
        return TeamScoreEntryVideo, TeamScoreEntryVideoEvent
    return ScoreEntryVideo, ScoreEntryVideoEvent


def subject_key(subject_kind: str, subject_id) -> str:
    kind = str(subject_kind or "inscripcio").strip().lower()
    return f"{kind}:{subject_id}"


def score_store_key(subject_kind: str, subject_id, exercici, comp_aparell_id) -> str:
    return f"{subject_key(subject_kind, subject_id)}|{int(exercici)}|{int(comp_aparell_id)}"


def inscripcio_exclosa_en_aparell(inscripcio_id: int, comp_aparell_id: int) -> bool:
    return InscripcioAparellExclusio.objects.filter(
        inscripcio_id=inscripcio_id,
        comp_aparell_id=comp_aparell_id,
    ).exists()


def resolve_scoring_subject(
    competicio: Competicio,
    comp_aparell: CompeticioAparell,
    payload: dict,
    *,
    eligible_team_ids: Optional[Iterable[int]] = None,
):
    if is_team_context_app(comp_aparell):
        subject_kind = str(payload.get("subject_kind") or "").strip().lower()
        subject_id = payload.get("subject_id")
        if subject_kind != "equip" or not subject_id:
            return None, JsonResponse(
                {"ok": False, "error": "Aquest aparell nomes accepta subject_kind=equip."},
                status=400,
            )
        equip = get_object_or_404(Equip, pk=subject_id, competicio=competicio)
        eligible_ids = set(
            int(x)
            for x in (
                eligible_team_ids
                if eligible_team_ids is not None
                else eligible_team_ids_for_comp_aparell(competicio, comp_aparell)
            )
        )
        if equip.id not in eligible_ids:
            return None, JsonResponse(
                {"ok": False, "error": "Aquest equip no es elegible en aquest aparell."},
                status=403,
            )
        return {
            "subject_kind": "equip",
            "subject_id": int(equip.id),
            "equip": equip,
        }, None

    subject_kind = str(payload.get("subject_kind") or "").strip().lower()
    subject_id = payload.get("subject_id") or payload.get("inscripcio_id")
    if subject_kind and subject_kind != "inscripcio":
        return None, JsonResponse(
            {"ok": False, "error": "Aquest aparell nomes accepta subject_kind=inscripcio."},
            status=400,
        )
    if not subject_id:
        return None, JsonResponse({"ok": False, "error": "Falta subject_id/inscripcio_id."}, status=400)

    inscripcio = get_object_or_404(Inscripcio, pk=subject_id, competicio=competicio)
    if inscripcio_exclosa_en_aparell(inscripcio.id, comp_aparell.id):
        return None, JsonResponse(
            {"ok": False, "error": "Aquesta inscripcio no competeix en aquest aparell."},
            status=403,
        )
    return {
        "subject_kind": "inscripcio",
        "subject_id": int(inscripcio.id),
        "inscripcio": inscripcio,
    }, None


def get_or_create_subject_entry_locked(
    *,
    competicio: Competicio,
    comp_aparell: CompeticioAparell,
    exercici: int,
    subject: Dict[str, object],
    defaults: Optional[dict] = None,
) -> Tuple[object, bool]:
    defaults = defaults or {}
    lookup = {
        "competicio": competicio,
        "comp_aparell": comp_aparell,
        "exercici": exercici,
    }
    if str(subject.get("subject_kind")) == "equip":
        lookup["equip"] = subject["equip"]
        model = TeamScoreEntry
    else:
        lookup["inscripcio"] = subject["inscripcio"]
        model = ScoreEntry

    entry = model.objects.select_for_update().filter(**lookup).first()
    if entry is not None:
        return entry, False

    try:
        entry = model.objects.create(**lookup, **defaults)
        return entry, True
    except IntegrityError:
        entry = model.objects.select_for_update().get(**lookup)
        return entry, False


def serialize_subject_payload(subject_kind: str, subject_id: int) -> dict:
    payload = {
        "subject_kind": str(subject_kind),
        "subject_id": int(subject_id),
    }
    if str(subject_kind) == "inscripcio":
        payload["inscripcio_id"] = int(subject_id)
    return payload
