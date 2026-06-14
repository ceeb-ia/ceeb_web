from __future__ import annotations

from typing import Dict, Iterable, Optional, Tuple

from django.db import IntegrityError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404

from ...models import Competicio, Inscripcio
from ...models.scoring import (
    ScoreEntry,
    ScoreEntryVideo,
    ScoreEntryVideoEvent,
    TeamCompetitiveSubject,
    TeamScoreEntry,
    TeamScoreEntryVideo,
    TeamScoreEntryVideoEvent,
)
from ...models.competicio import CompeticioAparell, CompeticioAparellFase
from ...services.inscripcions.admission import inscripcio_exclosa_en_aparell
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


def score_store_key(subject_kind: str, subject_id, exercici, comp_aparell_id, fase_id=None) -> str:
    base = f"{subject_key(subject_kind, subject_id)}|{int(exercici)}|{int(comp_aparell_id)}"
    if fase_id in (None, "", 0, "0"):
        return base
    return f"{base}|{int(fase_id)}"


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
        if subject_kind != "team_unit" or not subject_id:
            return None, JsonResponse(
                {"ok": False, "error": "Aquest aparell nomes accepta subject_kind=team_unit."},
                status=400,
            )
        team_subject = get_object_or_404(
            TeamCompetitiveSubject.objects.select_related("context", "equip"),
            pk=subject_id,
            competicio=competicio,
            comp_aparell=comp_aparell,
        )
        eligible_ids = set(
            int(x)
            for x in (
                eligible_team_ids
                if eligible_team_ids is not None
                else eligible_team_ids_for_comp_aparell(competicio, comp_aparell)
            )
        )
        if team_subject.id not in eligible_ids:
            return None, JsonResponse(
                {"ok": False, "error": "Aquesta unitat competitiva d'equip no es elegible en aquest aparell."},
                status=403,
            )
        return {
            "subject_kind": "team_unit",
            "subject_id": int(team_subject.id),
            "team_subject": team_subject,
            "equip": team_subject.equip,
            "context": team_subject.context,
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


def resolve_scoring_phase(
    competicio: Competicio,
    comp_aparell: CompeticioAparell,
    raw_phase_id,
):
    if raw_phase_id in (None, "", 0, "0"):
        return None, None
    try:
        phase_id = int(raw_phase_id)
    except Exception:
        return None, JsonResponse({"ok": False, "error": "fase_id invalid."}, status=400)
    phase = get_object_or_404(
        CompeticioAparellFase,
        pk=phase_id,
        competicio=competicio,
        comp_aparell=comp_aparell,
    )
    return phase, None


def get_or_create_subject_entry_locked(
    *,
    competicio: Competicio,
    comp_aparell: CompeticioAparell,
    exercici: int,
    subject: Dict[str, object],
    fase: CompeticioAparellFase | None = None,
    defaults: Optional[dict] = None,
) -> Tuple[object, bool]:
    defaults = defaults or {}
    lookup = {
        "competicio": competicio,
        "comp_aparell": comp_aparell,
        "exercici": exercici,
        "fase": fase,
    }
    if str(subject.get("subject_kind")) == "team_unit":
        lookup["team_subject"] = subject["team_subject"]
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
