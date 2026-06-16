from pathlib import Path

from django.conf import settings
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.template.loader import render_to_string
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from ...models import Inscripcio
from ...models.competicio import (
    CompeticioAparell,
    CompeticioAparellFase,
    ProgramUnit,
    ProgramUnitSlot,
)
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
    build_rotation_unit_step_map,
    get_rotacions_order_modes,
    order_rotation_cell_pairs,
    rotation_unit_key,
    rotation_unit_label,
    unique_ordered,
)
from ...services.fases.labels import program_unit_display_name
from ...services.scoring.scoring_subjects import subject_entry_model
from ...services.judging.assignments import (
    EffectiveJudgeAssignment,
    effective_assignments_for_token,
    resolve_effective_assignment,
)
from ...services.judging.subject_scope import (
    filter_inscripcions_queryset_by_subject_scope,
    filter_subject_dicts_by_subject_scope,
    subject_scope_summary,
)
from ...services.scoring.notes_units import effective_exercise_count
from ...services.inscripcions.admission import load_excluded_app_ids_by_inscripcio
from ...services.scoring.phase_eligibility import (
    is_program_unit_scoreable,
    scoreable_slot_statuses,
    scoreable_slots_qs,
)
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
    JUDGE_PORTAL_DISPLAY_COMPACT,
    JUDGE_PORTAL_DISPLAY_COMPETITION_ORDER,
    _sanitize_judge_portal_display_mode,
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


JUDGE_PWA_ASSET_DIR = Path(__file__).resolve().parents[2] / "assets" / "pwa" / "judge"
JUDGE_PWA_ICON_FILENAMES = {"apple-touch-icon.png", "icon-192.png", "icon-512.png"}
JUDGE_PWA_APP_NAME = "IA Score"
JUDGE_PWA_THEME_COLOR = "#0f766e"


def _is_competitive_franja(franja):
    return getattr(franja, "tipus", RotacioFranja.TIPUS_COMPETITION) == RotacioFranja.TIPUS_COMPETITION


def _absolute_icon_url(request, filename):
    return request.build_absolute_uri(reverse("judge_pwa_icon", kwargs={"filename": filename}))


def _judge_portal_home_url(token_obj):
    return f"{reverse('judge_portal', kwargs={'token': str(token_obj.id)})}?home=1"


def _judge_pwa_context(token_obj):
    return {
        "judge_pwa_enabled": True,
        "judge_pwa_app_name": JUDGE_PWA_APP_NAME,
        "judge_pwa_theme_color": JUDGE_PWA_THEME_COLOR,
        "judge_manifest_url": reverse("judge_manifest", kwargs={"token": str(token_obj.id)}),
        "judge_service_worker_url": reverse("judge_service_worker", kwargs={"token": str(token_obj.id)}),
        "judge_service_worker_scope": reverse("judge_portal", kwargs={"token": str(token_obj.id)}),
        "judge_pwa_icon_apple_url": reverse("judge_pwa_icon", kwargs={"filename": "apple-touch-icon.png"}),
        "judge_portal_home_url": _judge_portal_home_url(token_obj),
    }


def _assignment_url(token_obj, assignment: EffectiveJudgeAssignment):
    if assignment.id is None:
        return reverse("judge_portal", kwargs={"token": str(token_obj.id)})
    return reverse(
        "judge_portal_assignment",
        kwargs={"token": str(token_obj.id), "assignment_id": assignment.id},
    )


def _assignment_availability(assignment: EffectiveJudgeAssignment, phase: CompeticioAparellFase | None) -> dict:
    if not assignment.is_active:
        return {"state": "inactive", "label": "Inactiu", "is_open": False, "reason": "Aquest acces no esta actiu."}
    if assignment.fase_id is None:
        return {"state": "open", "label": "Obert", "is_open": True, "reason": ""}
    if phase is None:
        return {"state": "missing", "label": "No disponible", "is_open": False, "reason": "La fase no existeix."}
    if phase.estat == CompeticioAparellFase.Estat.CLOSED:
        return {"state": "closed", "label": "Tancada", "is_open": False, "reason": "La fase esta tancada."}

    qs = scoreable_slots_qs().filter(
        unit__fase=phase,
        unit__fase__comp_aparell_id=assignment.comp_aparell_id,
    )
    has_scoreable_slots = qs.filter(unit__status=ProgramUnit.Status.PUBLISHED).exists()
    if has_scoreable_slots:
        return {"state": "open", "label": "Obert", "is_open": True, "reason": ""}
    if phase.estat != CompeticioAparellFase.Estat.PUBLISHED:
        return {
            "state": "blocked",
            "label": "Bloquejada",
            "is_open": False,
            "reason": "La fase encara no esta publicada.",
        }
    return {
        "state": "empty",
        "label": "Pendent",
        "is_open": False,
        "reason": "La fase no te slots puntuables.",
    }


def _assignment_cards(request, token_obj, assignments: list[EffectiveJudgeAssignment]) -> list[dict]:
    app_ids = {item.comp_aparell_id for item in assignments}
    phase_ids = {item.fase_id for item in assignments if item.fase_id}
    apps = {
        int(app.id): app
        for app in (
            CompeticioAparell.objects
            .filter(competicio=token_obj.competicio, id__in=app_ids)
            .select_related("aparell")
        )
    }
    phases = {
        int(phase.id): phase
        for phase in (
            CompeticioAparellFase.objects
            .filter(competicio=token_obj.competicio, id__in=phase_ids)
            .select_related("comp_aparell", "comp_aparell__aparell")
        )
    }
    cards = []
    for assignment in assignments:
        app = apps.get(assignment.comp_aparell_id)
        phase = phases.get(assignment.fase_id) if assignment.fase_id else None
        availability = _assignment_availability(assignment, phase)
        app_label = str(getattr(app, "display_nom", "") or getattr(getattr(app, "aparell", None), "nom", "") or "Aparell")
        phase_label = str(getattr(phase, "nom", "") or "Preliminar")
        label = assignment.label or f"{app_label} / {phase_label}"
        cards.append({
            "assignment": assignment,
            "app": app,
            "phase": phase,
            "app_label": app_label,
            "phase_label": phase_label,
            "label": label,
            "subject_scope_summary": subject_scope_summary(assignment.subject_scope, competicio=token_obj.competicio),
            "availability": availability,
            "url": _assignment_url(token_obj, assignment) if availability["is_open"] else "",
        })
    return cards


def _render_judge_portal_home(request, token_obj, assignments, *, status=200, selected_assignment_id=None):
    cards = _assignment_cards(request, token_obj, assignments)
    open_count = sum(1 for card in cards if card["availability"].get("is_open"))
    blocked_count = sum(1 for card in cards if not card["availability"].get("is_open"))
    app_count = len({str(card.get("app_label") or "") for card in cards if card.get("app_label")})
    return render(
        request,
        "judge/portal_home.html",
        {
            "token_obj": token_obj,
            "token": str(token_obj.id),
            "competicio": token_obj.competicio,
            "assignment_cards": cards,
            "assignment_stats": {
                "open_count": open_count,
                "blocked_count": blocked_count,
                "app_count": app_count,
                "total_count": len(cards),
            },
            "selected_assignment_id": selected_assignment_id,
            "hide_base_chrome": True,
            "judge_kiosk": True,
            **_judge_pwa_context(token_obj),
        },
        status=status,
    )


def _phase_subjects_for_portal(competicio, comp_aparell, phase, subject_scope=None):
    subject_kind = "team_unit" if is_team_context_app(comp_aparell) else "inscripcio"
    units = (
        ProgramUnit.objects
        .filter(fase=phase)
        .prefetch_related("slots")
        .order_by("ordre", "id")
    )
    slots_by_unit = {}
    subject_ids = []
    statuses = scoreable_slot_statuses()
    for unit in units:
        if not is_program_unit_scoreable(unit):
            continue
        unit_slots = [
            slot
            for slot in unit.slots.all()
            if slot.status in statuses
            and slot.subject_id
            and str(slot.subject_kind or "").strip().lower() == subject_kind
        ]
        if not unit_slots:
            continue
        slots_by_unit[unit] = unit_slots
        subject_ids.extend(int(slot.subject_id) for slot in unit_slots)

    if subject_kind == "team_unit":
        registry = build_team_subject_registry(competicio, comp_aparell)
        scoped_subjects = filter_subject_dicts_by_subject_scope(
            [dict(item) for item in registry["subjects"]],
            subject_scope,
            competicio=competicio,
        )
        subjects_by_id = {int(item["subject_id"]): dict(item) for item in scoped_subjects}
    else:
        excluded_by_ins = load_excluded_app_ids_by_inscripcio(competicio, [comp_aparell.id])
        excluded_ins_ids = {ins_id for ins_id, app_ids in excluded_by_ins.items() if int(comp_aparell.id) in app_ids}
        ins_qs = (
            Inscripcio.objects
            .filter(competicio=competicio, id__in=subject_ids)
            .exclude(id__in=excluded_ins_ids)
            .select_related("grup_competicio")
        )
        ins_qs = filter_inscripcions_queryset_by_subject_scope(ins_qs, subject_scope)
        subjects_by_id = {int(ins.id): ins for ins in ins_qs}

    base_subjects = []
    unit_keys = []
    unit_labels = {}
    for unit, slots in slots_by_unit.items():
        unit_key = f"phase:{phase.id}:unit:{unit.id}"
        unit_keys.append(unit_key)
        unit_labels[unit_key] = program_unit_display_name(unit) or f"Unitat {unit.ordre}"
        for index, slot in enumerate(slots, start=1):
            subject = subjects_by_id.get(int(slot.subject_id))
            if subject is None:
                continue
            if subject_kind == "team_unit":
                item = dict(subject)
                item.setdefault("id", int(subject.get("subject_id") or slot.subject_id))
                item.setdefault("subject_id", int(subject.get("subject_id") or slot.subject_id))
                item.setdefault("subject_kind", "team_unit")
                item.setdefault("nom_i_cognoms", item.get("name") or "")
                item.setdefault("ordre_sortida", item.get("order") or index)
                item["group"] = unit_key
                item["group_label"] = unit_labels[unit_key]
            else:
                item = {
                    "id": int(subject.id),
                    "subject_id": int(subject.id),
                    "subject_kind": "inscripcio",
                    "name": getattr(subject, "nom_i_cognoms", "") or "",
                    "nom_i_cognoms": getattr(subject, "nom_i_cognoms", "") or "",
                    "order": getattr(subject, "ordre_competicio", None) or getattr(subject, "ordre_sortida", None) or index,
                    "ordre_sortida": getattr(subject, "ordre_sortida", None),
                    "group": unit_key,
                    "group_label": unit_labels[unit_key],
                    "categoria": str(getattr(subject, "categoria", "") or "").strip(),
                    "subcategoria": str(getattr(subject, "subcategoria", "") or "").strip(),
                    "grup_competicio_id": int(subject.grup_competicio_id or 0),
                    "meta": "",
                }
            base_subjects.append(item)
    return base_subjects, unit_keys, unit_labels


@require_http_methods(["GET"])
def judge_portal(request, token, assignment_id=None):
    tok = get_object_or_404(JudgeDeviceToken, pk=token)
    if not tok.is_valid():
        return render(request, "judge/invalid_token.html", {"token": tok}, status=403)

    tok.touch()

    assignments = effective_assignments_for_token(tok)
    has_explicit_assignments = tok.portal_assignments.exists()
    force_home = str(request.GET.get("home") or "").strip().lower() in {"1", "true", "yes"}
    if force_home:
        return _render_judge_portal_home(request, tok, assignments, selected_assignment_id=assignment_id)
    if assignment_id in (None, "", 0, "0"):
        if has_explicit_assignments:
            return _render_judge_portal_home(request, tok, assignments)
        if len(assignments) != 1:
            return _render_judge_portal_home(request, tok, assignments)
        selected_assignment = assignments[0]
        selected_cards = _assignment_cards(request, tok, [selected_assignment])
        if not selected_cards or not selected_cards[0]["availability"]["is_open"]:
            return _render_judge_portal_home(request, tok, assignments)
    else:
        selected_assignment = resolve_effective_assignment(tok, assignment_id)
        if selected_assignment is None:
            raise Http404("Assignacio de jutge no trobada")
        selected_cards = _assignment_cards(request, tok, [selected_assignment])
        if not selected_cards or not selected_cards[0]["availability"]["is_open"]:
            return _render_judge_portal_home(
                request,
                tok,
                assignments,
                status=403,
                selected_assignment_id=assignment_id,
            )

    comp_aparell = get_object_or_404(
        CompeticioAparell.objects.select_related("aparell"),
        pk=selected_assignment.comp_aparell_id,
        competicio=tok.competicio,
    )
    phase = None
    if selected_assignment.fase_id:
        phase = get_object_or_404(
            CompeticioAparellFase,
            pk=selected_assignment.fase_id,
            competicio=tok.competicio,
            comp_aparell=comp_aparell,
        )
    competicio = tok.competicio
    video_capture_enabled = _judge_video_capture_enabled_for_token(tok)

    _schema_obj, base_schema = resolve_scoring_schema_for_comp_aparell(comp_aparell)

    permissions = _normalize_permissions(selected_assignment.permissions)
    assignment_subject_scope_summary = subject_scope_summary(
        selected_assignment.subject_scope,
        competicio=competicio,
    )

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
    def subject_group_keys_for_assignacio(assignacio):
        if team_subject_mode:
            estacio = getattr(assignacio, "estacio", None)
            app_id = int(getattr(estacio, "comp_aparell_id", None) or comp_aparell.id)
            return [
                team_subject_bucket_key({"serie_id": serie_id}, app_id)
                for serie_id in assignacio_series(assignacio)
            ]
        return assignacio_grups(assignacio)

    def unit_key_for_assignacio(assignacio):
        return rotation_unit_key(subject_group_keys_for_assignacio(assignacio))

    rotation_step_map = build_rotation_unit_step_map(
        all_assigns,
        unit_key_for_assignacio,
        franja_modes,
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
    app_unit_keys = []
    app_units_by_key = {}
    app_units_by_franja = {}
    for a in assigns:
        fid = getattr(a, "franja_id", None)
        if not fid:
            continue
        groups_for_assignacio = subject_group_keys_for_assignacio(a)
        if not groups_for_assignacio:
            continue
        unit_key = rotation_unit_key(groups_for_assignacio)
        if unit_key in (None, ""):
            continue
        spec = app_units_by_key.get(unit_key)
        if spec is None:
            spec = {
                "key": unit_key,
                "member_keys": list(groups_for_assignacio),
                "first_franja_id": fid,
                "candidates_by_franja": {},
            }
            app_units_by_key[unit_key] = spec
            app_unit_keys.append(unit_key)
        spec["candidates_by_franja"].setdefault(
            fid,
            {
                "member_keys": list(groups_for_assignacio),
                "assignacio_id": int(getattr(a, "id", 0) or 0),
            },
        )
        app_units_by_franja[fid] = unique_ordered(
            list(app_units_by_franja.get(fid, [])) + [unit_key]
        )
        app_programmed_group_ids = unique_ordered(list(app_programmed_group_ids) + list(groups_for_assignacio))

    raw_franja_override = request.GET.get("franja")
    try:
        franja_override_id = int(raw_franja_override) if raw_franja_override not in (None, "") else None
    except Exception:
        franja_override_id = None
    if franja_override_id not in app_franja_ids:
        franja_override_id = None
    franja_override = franges_by_id.get(franja_override_id) if franja_override_id else None

    phase_unit_keys = []
    phase_unit_labels = {}
    if phase is not None:
        base_subjects, phase_unit_keys, phase_unit_labels = _phase_subjects_for_portal(
            competicio,
            comp_aparell,
            phase,
            selected_assignment.subject_scope,
        )
        if team_subject_mode:
            schema = runtime_schema_for_team_subjects(base_schema, comp_aparell, base_subjects)
        else:
            schema = runtime_schema_for_comp_aparell(base_schema, comp_aparell)
    elif team_subject_mode:
        registry = build_team_subject_registry(competicio, comp_aparell)
        raw_subjects = list(registry["subjects"])
        schema = runtime_schema_for_team_subjects(base_schema, comp_aparell, raw_subjects)
        scoped_subjects = filter_subject_dicts_by_subject_scope(
            raw_subjects,
            selected_assignment.subject_scope,
            competicio=competicio,
        )
        base_subjects = [
            dict(item)
            for item in scoped_subjects
            if int(comp_aparell.id) in (item.get("allowed_app_ids") or []) or item.get("invalid_reasons")
        ]
        app_name = str(getattr(comp_aparell, "display_nom", "") or getattr(comp_aparell.aparell, "nom", "") or "").strip()
        for item in base_subjects:
            item.setdefault("nom_i_cognoms", item.get("name") or "")
            item.setdefault("ordre_sortida", item.get("order") or "")
            item["group"] = team_subject_bucket_key(item, comp_aparell.id)
            item["group_label"] = team_subject_bucket_label(item, app_name)
    else:
        schema = runtime_schema_for_comp_aparell(base_schema, comp_aparell)
        excluded_by_ins = load_excluded_app_ids_by_inscripcio(competicio, [comp_aparell.id])
        excluded_ins_ids = {ins_id for ins_id, app_ids in excluded_by_ins.items() if int(comp_aparell.id) in app_ids}
        ins_base_qs = (
            Inscripcio.objects
            .filter(competicio=competicio)
            .exclude(id__in=excluded_ins_ids)
            .select_related("grup_competicio")
            .order_by("grup_competicio__display_num", "ordre_competicio", "ordre_sortida", "id")
        )
        ins_base_qs = filter_inscripcions_queryset_by_subject_scope(ins_base_qs, selected_assignment.subject_scope)
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
                "categoria": str(getattr(ins, "categoria", "") or "").strip(),
                "subcategoria": str(getattr(ins, "subcategoria", "") or "").strip(),
                "grup_competicio_id": int(ins.grup_competicio_id or 0),
                "meta": "",
            })

    if phase is not None:
        app_unit_keys = list(phase_unit_keys)
        app_units_by_key = {
            key: {
                "key": key,
                "member_keys": [key],
                "first_franja_id": None,
                "candidates_by_franja": {},
            }
            for key in app_unit_keys
        }
        app_units_by_franja = {}
        app_programmed_group_ids = list(phase_unit_keys)

    # El portal mostra totes les unitats programades de l'aparell. Una unitat
    # pot ser un sol grup o una cel-la de rotacio amb diversos grups que han
    # de competir com un bloc conjunt.
    subject_list = []
    grouped = {}
    for subject in base_subjects:
        if phase is not None:
            key = str(subject.get("group") or "")
        elif team_subject_mode:
            key = str(subject.get("group") or team_subject_bucket_key(subject, comp_aparell.id))
        else:
            key = 0 if subject.get("group") in (None, 0) else int(subject.get("group") or 0)
        grouped.setdefault(key, []).append(subject)

    ordered_groups = [
        unit_key
        for unit_key in app_unit_keys
        if any(member_key in grouped for member_key in app_units_by_key.get(unit_key, {}).get("member_keys", []))
    ]
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

    override_group_ids = set(app_units_by_franja.get(franja_override_id, [])) if franja_override_id else set()

    def resolve_group_franja_id(group_id):
        default_fid = (app_units_by_key.get(group_id) or {}).get("first_franja_id")
        if not franja_override_id:
            return default_fid
        if group_id in override_group_ids:
            return franja_override_id
        return default_fid

    def group_label_for(group_id) -> str:
        if group_id in phase_unit_labels:
            return phase_unit_labels[group_id]
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
        spec = app_units_by_key.get(group_id)
        if spec:
            fid = resolve_group_franja_id(group_id)
            candidate = (spec.get("candidates_by_franja") or {}).get(fid) if fid else None
            member_keys = list((candidate or {}).get("member_keys") or spec.get("member_keys") or [])
            label = rotation_unit_label(member_keys, group_label_for)
        else:
            fid = None
            member_keys = [group_id]
            label = group_label_for(group_id)

        group_items = []
        for member_key in member_keys:
            group_items.extend(grouped.get(member_key, []))
        base_pairs = [(item["subject_id"], item) for item in group_items]
        mode_for_group = franja_modes.get(str(fid), ORDER_MODE_MAINTAIN) if fid else ORDER_MODE_MAINTAIN
        seed_franja = fid if fid is not None else 0

        ordered_pairs = order_rotation_cell_pairs(
            base_pairs,
            competicio_id=competicio.id,
            franja_id=seed_franja,
            unit_key=group_id,
            mode=mode_for_group,
            rotate_step=rotation_step_map.get((group_id, fid), 0) if fid else 0,
            default_kind="g",
        )
        ordered_subjects = []
        for rank, (_subject_id, subject) in enumerate(ordered_pairs, start=1):
            item = dict(subject)
            item["rotation_order_display"] = rank
            item["rotation_base_order_display"] = subject.get("order") or ""
            ordered_subjects.append(item)
        return {
            "key": group_id,
            "label": label,
            "member_keys": member_keys,
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
    raw_group_text = str(raw_group).strip() if raw_group not in (None, "") else ""
    visible_key_by_text = {str(key): key for key in visible_group_keys}
    requested_group_key = visible_key_by_text.get(raw_group_text)
    requested_member_key = None
    if requested_group_key is None and raw_group_text:
        if team_subject_mode:
            requested_member_key = raw_group_text
        else:
            try:
                requested_member_key = int(raw_group_text)
            except Exception:
                requested_member_key = None
    all_visible_blocks = programmed_group_blocks + out_of_program_group_blocks
    if requested_group_key in visible_group_keys:
        active_group_key = requested_group_key
    elif requested_member_key is not None:
        containing_block = next(
            (
                block for block in all_visible_blocks
                if requested_member_key in (block.get("member_keys") or [])
            ),
            None,
        )
        active_group_key = containing_block["key"] if containing_block else (visible_group_keys[0] if visible_group_keys else None)
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
    if phase is not None:
        entry_filters["fase"] = phase
    else:
        entry_filters["fase__isnull"] = True
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
    max_ex = effective_exercise_count(comp_aparell, phase=phase)
    exercicis = list(range(1, max_ex + 1))
    try:
        exercici_default = int(request.GET.get("ex") or 1)
    except Exception:
        exercici_default = 1
    exercici_default = max(1, min(max_ex, exercici_default))
    portal_display_mode = _sanitize_judge_portal_display_mode(request.GET.get("view_mode"))
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

    def scoped_api_url(url):
        if selected_assignment.id is None:
            return url
        sep = "&" if "?" in url else "?"
        return f"{url}{sep}assignment_id={selected_assignment.id}"

    save_url = scoped_api_url(save_url)
    updates_url = scoped_api_url(updates_url)
    video_status_url = (
        scoped_api_url(reverse("judge_video_status", kwargs={"token": str(tok.id)}))
        if video_capture_enabled
        else ""
    )
    video_upload_url = (
        scoped_api_url(reverse("judge_video_upload", kwargs={"token": str(tok.id)}))
        if video_capture_enabled
        else ""
    )
    video_delete_url = (
        scoped_api_url(reverse("judge_video_delete", kwargs={"token": str(tok.id)}))
        if video_capture_enabled
        else ""
    )

    ctx = {
        "token_obj": tok,
        "token": str(tok.id),
        "competicio": competicio,
        "comp_aparell": comp_aparell,
        "judge_assignment": selected_assignment,
        "judge_assignment_id": selected_assignment.id,
        "judge_assignment_subject_scope_summary": assignment_subject_scope_summary,
        "fase": phase,
        "fase_id": phase.id if phase is not None else None,
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
        "video_status_url": video_status_url,
        "video_upload_url": video_upload_url,
        "video_delete_url": video_delete_url,
        "video_max_duration_seconds": ScoreEntryVideo.VIDEO_MAX_DURATION_SECONDS,
        "video_max_size_bytes": ScoreEntryVideo.VIDEO_MAX_SIZE_BYTES,
        "exercicis": exercicis,
        "exercici": exercici_default,
        "portal_display_mode": portal_display_mode,
        "portal_display_mode_options": [
            (JUDGE_PORTAL_DISPLAY_COMPACT, "Compacte"),
            (JUDGE_PORTAL_DISPLAY_COMPETITION_ORDER, "Ordre competicio"),
        ],
        "team_subject_mode": team_subject_mode,
        "franges": competition_franges,
        **_judge_pwa_context(tok),
    }
    return render(request, "judge/portal.html", ctx)


@require_http_methods(["GET"])
def judge_manifest(request, token):
    tok = get_object_or_404(JudgeDeviceToken, pk=token)
    if not tok.is_valid():
        return JsonResponse({"error": "invalid token"}, status=403)

    portal_url = reverse("judge_portal", kwargs={"token": str(tok.id)})

    payload = {
        "name": JUDGE_PWA_APP_NAME,
        "short_name": JUDGE_PWA_APP_NAME,
        "description": "Portal de puntuacio IA Score.",
        "id": portal_url,
        "start_url": _judge_portal_home_url(tok),
        "scope": reverse("judge_portal", kwargs={"token": str(tok.id)}),
        "display": "standalone",
        "background_color": "#f8fafc",
        "theme_color": JUDGE_PWA_THEME_COLOR,
        "icons": [
            {
                "src": _absolute_icon_url(request, "icon-192.png"),
                "sizes": "192x192",
                "type": "image/png",
                "purpose": "any maskable",
            },
            {
                "src": _absolute_icon_url(request, "icon-512.png"),
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "any maskable",
            },
        ],
    }
    response = JsonResponse(payload, content_type="application/manifest+json")
    response["Cache-Control"] = "no-store"
    return response


@require_http_methods(["GET"])
def judge_service_worker(request, token):
    tok = get_object_or_404(JudgeDeviceToken, pk=token)
    if not tok.is_valid():
        return HttpResponse("/* invalid token */", status=403, content_type="application/javascript; charset=utf-8")

    scope = reverse("judge_portal", kwargs={"token": str(tok.id)})
    body = render_to_string(
        "judge/pwa/service-worker.js",
        {
            "static_url": settings.STATIC_URL,
            "static_version": getattr(settings, "STATIC_VERSION", "dev"),
        },
    )
    response = HttpResponse(body, content_type="application/javascript; charset=utf-8")
    response["Cache-Control"] = "no-store"
    response["Service-Worker-Allowed"] = scope
    return response


@require_http_methods(["GET"])
def judge_pwa_icon(request, filename):
    if filename not in JUDGE_PWA_ICON_FILENAMES:
        raise Http404("Icona PWA no trobada")
    path = JUDGE_PWA_ASSET_DIR / filename
    if not path.exists():
        raise Http404("Icona PWA no trobada")
    response = FileResponse(path.open("rb"), content_type="image/png")
    response["Cache-Control"] = "public, max-age=31536000, immutable"
    return response


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

