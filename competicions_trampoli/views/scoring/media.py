from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET

from ...models import Competicio, Inscripcio, InscripcioMedia
from ...models.competicio import CompeticioAparell
from ...models.scoring import ScoreEntry, ScoreEntryVideo, TeamScoreEntry, TeamScoreEntryVideo
from ...services.scoring.scoring_subjects import resolve_scoring_subject, serialize_subject_payload
from ...services.scoring.team_scoring import is_team_context_app
from .helpers import (
    _eligible_team_subject_map,
    _parse_positive_int,
    _protected_file_response,
    _serialize_inscripcio_media_for_playback,
    _serialize_judge_video_for_playback,
    _split_media_for_playback,
)


@require_GET
def scoring_media_file(request, pk, media_id):
    competicio = get_object_or_404(Competicio, pk=pk)
    item = get_object_or_404(
        InscripcioMedia.objects.select_related("inscripcio"),
        pk=media_id,
        competicio=competicio,
    )
    return _protected_file_response(
        item.fitxer,
        original_filename=item.original_filename,
        mime_type=item.mime_type,
    )


@require_GET
def scoring_media_context(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)

    subject_kind = str(request.GET.get("subject_kind") or "").strip().lower()
    subject_id = _parse_positive_int(request.GET.get("subject_id"))
    ins_id = _parse_positive_int(request.GET.get("inscripcio_id"))
    comp_aparell_id = _parse_positive_int(request.GET.get("comp_aparell_id"))
    exercici = _parse_positive_int(request.GET.get("exercici"))

    comp_aparell = None
    if comp_aparell_id:
        comp_aparell = (
            CompeticioAparell.objects
            .filter(pk=comp_aparell_id, competicio=competicio)
            .select_related("aparell")
            .first()
        )
    if comp_aparell_id and comp_aparell is None:
        return JsonResponse({"ok": False, "error": "comp_aparell_id invalid per aquesta competicio."}, status=400)

    if comp_aparell and is_team_context_app(comp_aparell):
        eligible_subjects = _eligible_team_subject_map(competicio, comp_aparell)
        subject, error_response = resolve_scoring_subject(
            competicio,
            comp_aparell,
            {
                "subject_kind": subject_kind,
                "subject_id": subject_id,
                "inscripcio_id": ins_id,
            },
            eligible_team_ids=eligible_subjects.keys(),
        )
        if error_response is not None:
            return error_response
        team_subject_obj = subject["team_subject"]
        equip = team_subject_obj.equip
        team_subject = eligible_subjects.get(int(team_subject_obj.id), {})
        judge_video_payload = None
        if exercici:
            score = (
                TeamScoreEntry.objects
                .filter(
                    competicio=competicio,
                    team_subject=team_subject_obj,
                    comp_aparell=comp_aparell,
                    exercici=exercici,
                    fase__isnull=True,
                )
                .first()
            )
            if score:
                video_obj = TeamScoreEntryVideo.objects.filter(team_score_entry=score).first()
                judge_video_payload = _serialize_judge_video_for_playback(video_obj, competicio.id)

        return JsonResponse({
            "ok": True,
            **serialize_subject_payload("team_unit", team_subject_obj.id),
            "subject": {
                "kind": "team_unit",
                "id": team_subject_obj.id,
                "name": f"{team_subject.get('context_name') or ''} · {team_subject.get('name') or team_subject_obj.label}".strip(" ·"),
                "meta": " · ".join(
                    part for part in [
                        team_subject.get("members_text", ""),
                        team_subject.get("serie_label", ""),
                    ] if part
                ),
            },
            "context": {
                "comp_aparell_id": comp_aparell_id,
                "exercici": exercici,
                "serie_id": team_subject.get("serie_id"),
                "serie_label": team_subject.get("serie_label"),
            },
            "media": _split_media_for_playback([]),
            "judge_video": judge_video_payload,
        })

    ins_id = subject_id or ins_id
    if subject_kind and subject_kind != "inscripcio":
        return JsonResponse({"ok": False, "error": "Aquest context nomes accepta subject_kind=inscripcio."}, status=400)
    if not ins_id:
        return JsonResponse({"ok": False, "error": "Falta subject_id/inscripcio_id valid."}, status=400)

    inscripcio = get_object_or_404(Inscripcio, pk=ins_id, competicio=competicio)

    media_qs = (
        InscripcioMedia.objects
        .filter(competicio=competicio, inscripcio=inscripcio)
        .order_by("tipus", "-is_primary", "-created_at", "id")
    )
    media_items = [_serialize_inscripcio_media_for_playback(m) for m in media_qs]
    media_payload = _split_media_for_playback(media_items)

    judge_video_payload = None
    if comp_aparell_id and exercici:
        score = (
            ScoreEntry.objects
            .filter(
                competicio=competicio,
                inscripcio=inscripcio,
                comp_aparell_id=comp_aparell_id,
                exercici=exercici,
                fase__isnull=True,
            )
            .first()
        )
        if score:
            video_obj = ScoreEntryVideo.objects.filter(score_entry=score).first()
            judge_video_payload = _serialize_judge_video_for_playback(video_obj, competicio.id)

    meta_parts = []
    if getattr(inscripcio, "entitat", None):
        meta_parts.append(str(inscripcio.entitat))
    if getattr(inscripcio, "categoria", None):
        meta_parts.append(str(inscripcio.categoria))
    if getattr(inscripcio, "subcategoria", None):
        meta_parts.append(str(inscripcio.subcategoria))

    return JsonResponse({
        "ok": True,
        **serialize_subject_payload("inscripcio", inscripcio.id),
        "subject": {
            "kind": "inscripcio",
            "id": inscripcio.id,
            "name": inscripcio.nom_i_cognoms or "",
            "meta": " · ".join(meta_parts) if meta_parts else "",
        },
        "context": {
            "comp_aparell_id": comp_aparell_id,
            "exercici": exercici,
        },
        "media": media_payload,
        "judge_video": judge_video_payload,
    })


@require_GET
def scoring_judge_video_file(request, pk, video_kind, video_id):
    competicio = get_object_or_404(Competicio, pk=pk)
    normalized_kind = str(video_kind or "").strip().lower()
    if normalized_kind == "team":
        video_obj = get_object_or_404(
            TeamScoreEntryVideo.objects.select_related("team_score_entry"),
            pk=video_id,
            team_score_entry__competicio=competicio,
        )
    elif normalized_kind == "individual":
        video_obj = get_object_or_404(
            ScoreEntryVideo.objects.select_related("score_entry"),
            pk=video_id,
            score_entry__competicio=competicio,
        )
    else:
        raise Http404("Tipus de video invalid")
    return _protected_file_response(
        video_obj.video_file,
        original_filename=video_obj.original_filename,
        mime_type=video_obj.mime_type,
    )

