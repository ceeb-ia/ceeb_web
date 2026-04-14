from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from ...models import Inscripcio
from ...models.competicio import InscripcioAparellExclusio
from ...models.judging import JudgeDeviceToken, PublicLiveToken
from ...models.rotacions import RotacioAssignacio, RotacioFranja
from ...models.scoring import ScoreEntryVideo
from ...services.scoring.schema_resolution import resolve_scoring_schema_for_comp_aparell
from ...services.shared.competition_groups import (
    get_group_maps,
    get_inscripcio_competition_order,
    group_label,
    show_out_of_program_in_competition_views,
)
from ...services.rotacions.rotacions_ordering import (
    ORDER_MODE_MAINTAIN,
    assignacio_grups,
    assignacio_series,
    build_group_rotation_step_map,
    build_series_rotation_step_map,
    effective_rotate_steps,
    get_rotacions_order_modes,
    order_pairs_for_mode,
    unique_ordered,
)
from ...services.scoring.scoring_subjects import subject_entry_model
from ...services.scoring.team_scoring import (
    build_team_subjects_for_comp_aparell,
    is_team_context_app,
    logical_team_inputs_to_runtime_inputs,
    runtime_schema_for_comp_aparell,
)
from ...services.teams.team_series import team_subject_bucket_key, team_subject_bucket_label
from ...services.scoring.team_subject_contract import (
    build_team_subject_registry,
    runtime_schema_for_team_subjects,
)
from ._shared import (
    _clamp_exercici_for_aparell,
    _filter_inputs_for_allowed_codes,
    _judge_item_labels_map_for_comp_aparell,
    _judge_video_capture_enabled_for_token,
    _qr_png_response,
    _subject_dom_id,
)
from .permissions import (
    _allowed_input_codes_from_permissions,
    _normalize_permissions,
    _resolve_permissions_for_subject,
)


def _is_competitive_franja(franja):
    return getattr(franja, "tipus", RotacioFranja.TIPUS_COMPETITION) == RotacioFranja.TIPUS_COMPETITION

@require_http_methods(["GET"])
def judge_portal(request, token):
    tok = get_object_or_404(JudgeDeviceToken, pk=token)
    if not tok.is_valid():
        return render(request, "judge/invalid_token.html", {"token": tok}, status=403)

    tok.touch()

    comp_aparell = tok.comp_aparell
    competicio = tok.competicio
    video_capture_enabled = _judge_video_capture_enabled_for_token(tok)

    _schema_obj, base_schema = resolve_scoring_schema_for_comp_aparell(comp_aparell)

    permissions = _normalize_permissions(tok.permissions)

    franja_modes = get_rotacions_order_modes(competicio)

    team_subject_mode = is_team_context_app(comp_aparell)

    # Franges programades per aquest aparell. El portal mostra tots els grups
    # visibles i resol l'ordre de cada grup segons la seva franja associada.
    group_maps = get_group_maps(competicio)
    groups_by_id = group_maps["by_id"]
    franges = list(
        RotacioFranja.objects
        .filter(competicio=competicio)
        .order_by("ordre", "id")
    )
    competition_franges = [fr for fr in franges if _is_competitive_franja(fr)]
    competition_franja_ids = {fr.id for fr in competition_franges}
    franges_by_id = {fr.id: fr for fr in competition_franges}
    all_assigns = list(
        RotacioAssignacio.objects
        .filter(
            competicio=competicio,
            franja_id__in=competition_franja_ids,
            estacio__tipus="aparell",
            estacio__comp_aparell__isnull=False,
        )
        .select_related("franja", "estacio")
        .prefetch_related("grup_links__grup", "serie_links__serie")
        .order_by("franja__ordre", "franja_id", "estacio__ordre", "id")
    )
    rotation_step_map = (
        build_series_rotation_step_map(all_assigns, franja_modes)
        if team_subject_mode
        else build_group_rotation_step_map(all_assigns, franja_modes)
    )
    assigns = [
        a for a in all_assigns
        if getattr(a, "estacio", None) is not None and getattr(a.estacio, "comp_aparell_id", None) == comp_aparell.id
    ]
    app_franja_ids = unique_ordered(
        int(a.franja_id)
        for a in assigns
        if getattr(a, "franja_id", None)
    )
    app_programmed_group_ids = []
    app_groups_by_franja = {}
    group_first_app_franja_id = {}
    for a in assigns:
        fid = getattr(a, "franja_id", None)
        if not fid:
            continue
        if team_subject_mode:
            groups_for_assignacio = [
                team_subject_bucket_key({"serie_id": serie_id}, comp_aparell.id)
                for serie_id in assignacio_series(a)
            ]
        else:
            groups_for_assignacio = assignacio_grups(a)
        if not groups_for_assignacio:
            continue
        app_groups_by_franja[fid] = unique_ordered(
            list(app_groups_by_franja.get(fid, [])) + list(groups_for_assignacio)
        )
        app_programmed_group_ids = unique_ordered(list(app_programmed_group_ids) + list(groups_for_assignacio))
        for group_id in groups_for_assignacio:
            group_first_app_franja_id.setdefault(group_id, fid)

    raw_franja_override = request.GET.get("franja")
    try:
        franja_override_id = int(raw_franja_override) if raw_franja_override not in (None, "") else None
    except Exception:
        franja_override_id = None
    if franja_override_id not in app_franja_ids:
        franja_override_id = None
    franja_override = franges_by_id.get(franja_override_id) if franja_override_id else None

    if team_subject_mode:
        registry = build_team_subject_registry(competicio, comp_aparell)
        raw_subjects = list(registry["subjects"])
        schema = runtime_schema_for_team_subjects(base_schema, comp_aparell, raw_subjects)
        base_subjects = [
            dict(item)
            for item in raw_subjects
            if int(comp_aparell.id) in (item.get("allowed_app_ids") or []) or item.get("invalid_reasons")
        ]
        app_name = str(getattr(comp_aparell.aparell, "nom", "") or "").strip()
        for item in base_subjects:
            item.setdefault("nom_i_cognoms", item.get("name") or "")
            item.setdefault("ordre_sortida", item.get("order") or "")
            item["group"] = team_subject_bucket_key(item, comp_aparell.id)
            item["group_label"] = team_subject_bucket_label(item, app_name)
    else:
        schema = runtime_schema_for_comp_aparell(base_schema, comp_aparell)
        excluded_ins_ids = set(
            InscripcioAparellExclusio.objects
            .filter(comp_aparell=comp_aparell)
            .values_list("inscripcio_id", flat=True)
        )
        ins_base_qs = (
            Inscripcio.objects
            .filter(competicio=competicio)
            .exclude(id__in=excluded_ins_ids)
            .select_related("grup_competicio")
            .order_by("grup_competicio__display_num", "ordre_competicio", "ordre_sortida", "id")
        )
        base_subjects = []
        for ins in ins_base_qs:
            base_subjects.append({
                "id": int(ins.id),
                "subject_id": int(ins.id),
                "subject_kind": "inscripcio",
                "name": getattr(ins, "nom_i_cognoms", "") or "",
                "nom_i_cognoms": getattr(ins, "nom_i_cognoms", "") or "",
                "order": get_inscripcio_competition_order(ins) or "",
                "ordre_sortida": getattr(ins, "ordre_sortida", None),
                "group": 0 if ins.grup_competicio_id in (None, 0) else int(ins.grup_competicio_id),
                "meta": "",
            })

    # El portal mostra tots els grups programats de l'aparell i calcula la
    # posicio efectiva segons la primera franja assignada a cada grup, amb
    # suport d'override per query string quan arriba ?franja=...
    subject_list = []
    grouped = {}
    for subject in base_subjects:
        if team_subject_mode:
            key = str(subject.get("group") or team_subject_bucket_key(subject, comp_aparell.id))
        else:
            key = 0 if subject.get("group") in (None, 0) else int(subject.get("group") or 0)
        grouped.setdefault(key, []).append(subject)

    ordered_groups = [g for g in app_programmed_group_ids if g in grouped]
    if team_subject_mode:
        unassigned_key = team_subject_bucket_key({}, comp_aparell.id)
        remaining_groups = sorted(
            (g for g in grouped.keys() if g not in app_programmed_group_ids and g != unassigned_key),
            key=lambda value: str(value),
        )
    else:
        remaining_groups = sorted(g for g in grouped.keys() if g not in app_programmed_group_ids and g != 0)
    always_visible_group_ids = list(ordered_groups)
    if team_subject_mode:
        if unassigned_key in grouped and unassigned_key not in always_visible_group_ids:
            always_visible_group_ids.append(unassigned_key)
    else:
        if 0 in grouped and 0 not in always_visible_group_ids:
            always_visible_group_ids.append(0)
    show_out_of_program_groups = show_out_of_program_in_competition_views(competicio)

    override_group_ids = set(app_groups_by_franja.get(franja_override_id, [])) if franja_override_id else set()

    def resolve_group_franja_id(group_id):
        default_fid = group_first_app_franja_id.get(group_id)
        if not franja_override_id:
            return default_fid
        if group_id in override_group_ids:
            return franja_override_id
        return default_fid

    def group_label_for(group_id) -> str:
        if team_subject_mode:
            items = grouped.get(group_id, [])
            if items:
                return str(items[0].get("group_label") or "Sense serie")
            return "Sense serie"
        if group_id in (None, 0):
            return "Sense grup"
        return group_label(groups_by_id.get(group_id))

    def format_franja_time(value) -> str:
        if value in (None, ""):
            return ""
        if hasattr(value, "strftime"):
            return value.strftime("%H:%M")
        text = str(value).strip()
        return text[:5] if len(text) >= 5 else text

    def build_group_block(group_id):
        group_items = grouped.get(group_id, [])
        base_pairs = [(item["subject_id"], item) for item in group_items]
        fid = resolve_group_franja_id(group_id)
        mode_for_group = franja_modes.get(str(fid), ORDER_MODE_MAINTAIN) if fid else ORDER_MODE_MAINTAIN
        rotate_steps = effective_rotate_steps(
            mode_for_group,
            (
                rotation_step_map.get((int(str(group_id).rsplit("-", 1)[-1]), fid), 0)
                if team_subject_mode and str(group_id).startswith(f"app-{comp_aparell.id}-serie-") and fid
                else rotation_step_map.get((group_id, fid), 0) if fid else 0
            ),
        )
        seed_franja = fid if fid is not None else 0

        ordered_pairs = order_pairs_for_mode(
            base_pairs,
            mode_for_group,
            rotate_steps=rotate_steps,
            seed_prefix=f"judge|{competicio.id}|{seed_franja}|{comp_aparell.id}|{group_id}",
        )
        ordered_subjects = []
        for rank, (_subject_id, subject) in enumerate(ordered_pairs, start=1):
            item = dict(subject)
            item["rotation_order_display"] = rank
            item["rotation_base_order_display"] = subject.get("order") or ""
            ordered_subjects.append(item)
        return {
            "key": group_id,
            "label": group_label_for(group_id),
            "franja_id": fid,
            "franja_label": (
                f"{getattr(franges_by_id.get(fid), 'titol', None) or 'Franja'} · "
                f"{format_franja_time(franges_by_id[fid].hora_inici)}-{format_franja_time(franges_by_id[fid].hora_fi)}"
                if fid and fid in franges_by_id
                else ""
            ),
            "list": ordered_subjects,
        }

    programmed_group_blocks = []
    out_of_program_group_blocks = []
    for g in always_visible_group_ids:
        block = build_group_block(g)
        programmed_group_blocks.append(block)
        subject_list.extend(block["list"])
    if show_out_of_program_groups:
        for g in remaining_groups:
            block = build_group_block(g)
            out_of_program_group_blocks.append(block)
            subject_list.extend(block["list"])
    if not programmed_group_blocks and not out_of_program_group_blocks and grouped:
        fallback_group_ids = sorted(
            grouped.keys(),
            key=lambda group_id: ((group_id == 0) if not team_subject_mode else (str(group_id) == unassigned_key), str(group_id)),
        )
        for g in fallback_group_ids:
            block = build_group_block(g)
            programmed_group_blocks.append(block)
            subject_list.extend(block["list"])

    visible_group_keys = [block["key"] for block in programmed_group_blocks]
    visible_group_keys.extend(block["key"] for block in out_of_program_group_blocks)
    raw_group = request.GET.get("group")
    if team_subject_mode:
        requested_group_key = str(raw_group).strip() if raw_group not in (None, "") else None
    else:
        try:
            requested_group_key = int(raw_group) if raw_group not in (None, "") else None
        except Exception:
            requested_group_key = None
    if requested_group_key in visible_group_keys:
        active_group_key = requested_group_key
    elif visible_group_keys:
        active_group_key = visible_group_keys[0]
    else:
        active_group_key = None

    # Prefetch entries existents (per mostrar valors actuals)
    subject_ids = [int(item["subject_id"]) for item in subject_list]
    entry_model = subject_entry_model(comp_aparell)
    entry_filters = {
        "competicio": competicio,
        "comp_aparell": comp_aparell,
    }
    if team_subject_mode:
        entry_filters["team_subject_id__in"] = subject_ids
    else:
        entry_filters["inscripcio_id__in"] = subject_ids
    entries = entry_model.objects.filter(**entry_filters)
    if team_subject_mode:
        entries = entries.select_related("team_subject")
    entry_map = {}
    for e in entries:
        owner_id = int(e.team_subject_id if team_subject_mode else e.inscripcio_id)
        entry_map[(owner_id, e.exercici)] = e

    # Construïm un “snapshot” dels inputs rellevants per inscripció/exercici
    # Per simplicitat: assumim exercici=1 si al teu flux n’hi ha més, ho pots estendre.
    max_ex = max(1, int(getattr(comp_aparell, "nombre_exercicis", 1) or 1))
    exercicis = list(range(1, max_ex + 1))
    exercici_default = _clamp_exercici_for_aparell(comp_aparell, request.GET.get("ex"))
    scores_payload = {}
    for item in subject_list:
        subject_dom_id = _subject_dom_id(item) or str(item.get("subject_id") or "")
        resolved_permissions = _resolve_permissions_for_subject(permissions, comp_aparell, item)
        allowed_input_codes = _allowed_input_codes_from_permissions(resolved_permissions)
        exercise_map = {}
        for ex in exercicis:
            e = entry_map.get((int(item["subject_id"]), ex))
            if team_subject_mode and e and isinstance(e.inputs, dict):
                runtime_inputs = logical_team_inputs_to_runtime_inputs(e.inputs, e.team_subject, base_schema)
            else:
                runtime_inputs = e.inputs if e and isinstance(e.inputs, dict) else {}
            exercise_map[str(ex)] = {
                "inputs": (
                    _filter_inputs_for_allowed_codes(runtime_inputs, allowed_input_codes)
                    if runtime_inputs
                    else {}
                ),
                "outputs": (e.outputs if e and isinstance(e.outputs, dict) else {}),
                "total": (float(e.total) if e else 0.0),
                "updated_at": (e.updated_at.isoformat() if e else None),
            }
        scores_payload[subject_dom_id] = {
            "exercises": exercise_map,
        }

    save_url = reverse("judge_save_partial", kwargs={"token": str(tok.id)})
    try:
        updates_url = reverse("judge_updates", kwargs={"token": str(tok.id)})
    except NoReverseMatch:
        try:
            updates_url = reverse("competicions_trampoli:judge_updates", kwargs={"token": str(tok.id)})
        except NoReverseMatch:
            updates_url = save_url.replace("/api/save/", "/api/updates/")

    ctx = {
        "token_obj": tok,
        "token": str(tok.id),
        "competicio": competicio,
        "comp_aparell": comp_aparell,
        "hide_base_chrome": True,
        "judge_kiosk": True,
        "schema": schema,
        "judge_item_labels_map": _judge_item_labels_map_for_comp_aparell(comp_aparell),
        "permissions": permissions,
        "inscripcions": subject_list,
        "subjects_payload_json": subject_list,
        "group_blocks": programmed_group_blocks,
        "out_of_program_group_blocks": out_of_program_group_blocks,
        "active_group_key": active_group_key,
        "show_out_of_program_in_competition_views": show_out_of_program_groups,
        "franja_override_id": franja_override_id,
        "franja_override": franja_override,
        "scores_payload_json": scores_payload,
        "save_url": save_url,
        "updates_url": updates_url,
        "updates_cursor_init": timezone.now().isoformat(),
        "video_capture_enabled": video_capture_enabled,
        "video_status_url": (
            reverse("judge_video_status", kwargs={"token": str(tok.id)})
            if video_capture_enabled
            else ""
        ),
        "video_upload_url": (
            reverse("judge_video_upload", kwargs={"token": str(tok.id)})
            if video_capture_enabled
            else ""
        ),
        "video_delete_url": (
            reverse("judge_video_delete", kwargs={"token": str(tok.id)})
            if video_capture_enabled
            else ""
        ),
        "video_max_duration_seconds": ScoreEntryVideo.VIDEO_MAX_DURATION_SECONDS,
        "video_max_size_bytes": ScoreEntryVideo.VIDEO_MAX_SIZE_BYTES,
        "exercicis": exercicis,
        "exercici": exercici_default,
        "team_subject_mode": team_subject_mode,
        "franges": competition_franges,
    }
    return render(request, "judge/portal.html", ctx)


def judge_qr_png(request, token):
    tok = get_object_or_404(JudgeDeviceToken, pk=token)
    portal_url = reverse("judge_portal", kwargs={"token": str(tok.id)})
    req_ex = request.GET.get("ex")
    if req_ex not in (None, ""):
        ex = _clamp_exercici_for_aparell(tok.comp_aparell, req_ex)
        portal_url = f"{portal_url}?ex={ex}"
    req_franja = request.GET.get("franja")
    if req_franja not in (None, ""):
        try:
            franja_id = int(req_franja)
        except Exception:
            franja_id = None
        if franja_id and RotacioFranja.objects.filter(
            competicio=tok.competicio,
            pk=franja_id,
            tipus=RotacioFranja.TIPUS_COMPETITION,
        ).exists():
            sep = "&" if "?" in portal_url else "?"
            portal_url = f"{portal_url}{sep}franja={franja_id}"
    return _qr_png_response(request.build_absolute_uri(portal_url))


def public_live_qr_png(request, token):
    tok = get_object_or_404(PublicLiveToken, pk=token)
    url = request.build_absolute_uri(reverse("public_live_portal", kwargs={"token": str(tok.id)}))
    return _qr_png_response(url)

