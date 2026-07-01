import json

from django.contrib import messages
from django.db import models
from django.forms import formset_factory
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from ...access import user_has_competicio_capability
from ...forms_judge import JudgeTokenCreateForm, PermissionRowForm
from ...models import Competicio
from ...models.competicio import CompeticioAparell, CompeticioAparellFase
from ...models.judging import JudgeDeviceToken, JudgePortalAssignment, PublicLiveToken
from ...services.scoring.schema_resolution import resolve_scoring_schema_for_comp_aparell
from ...services.scoring.team_scoring import (
    build_permission_label,
    build_team_subjects_for_comp_aparell,
    is_team_context_app,
    normalize_permission_target,
    parse_permission_member_slots,
    permission_runtime_code,
    runtime_schema_for_comp_aparell,
)
from ...services.judging.subject_scope import (
    subject_scope_from_post,
    subject_scope_options_for_competicio,
    subject_scope_summary,
)
from ...services.judging.supervision import validate_single_supervisor_per_field
from ._shared import _judge_item_labels_map_for_comp_aparell

MAX_TOKEN_PERMISSIONS = 15
PERMISSION_ROLES = {"standard", "supervisor"}


def _schema_field_scope(field: dict, *, team_context_mode: bool = False) -> str:
    raw_scope = str((field or {}).get("scope") or "").strip().lower()
    if raw_scope in {"shared", "member"}:
        return raw_scope
    return "member" if team_context_mode else "shared"


def _schema_field_choices(schema: dict):
    # [(code, "CODE — Label"), ...]
    out = [("", "—")]
    for f in (schema.get("fields") or []):
        if isinstance(f, dict) and f.get("code"):
            code = f["code"]
            label = f.get("label") or code
            out.append((code, f"{code} — {label}"))
    return out


def _schema_field_by_code(schema: dict):
    return {f.get("code"): f for f in (schema.get("fields") or []) if isinstance(f, dict) and f.get("code")}


def _field_items_count(field: dict) -> int:
    if str((field or {}).get("type") or "number").strip().lower() != "matrix":
        return 1
    return max(1, int((((field or {}).get("items") or {}).get("count")) or 1))


def _schema_field_catalog(schema: dict, *, comp_aparell=None, team_context_mode: bool = False):
    item_labels_map = _judge_item_labels_map_for_comp_aparell(comp_aparell)
    items = []
    for f in (schema.get("fields") or []):
        if not isinstance(f, dict) or not f.get("code"):
            continue
        code = str(f.get("code") or "").strip()
        label = str(f.get("label") or code).strip() or code
        items_count = _field_items_count(f)
        items.append({
            "code": code,
            "label": label,
            "type": str(f.get("type") or "number").strip().lower() or "number",
            "scope": _schema_field_scope(f, team_context_mode=team_context_mode),
            "items_count": items_count,
            "item_labels": list(item_labels_map.get(code) or [])[:items_count],
        })
    return items


def _save_comp_aparell_item_labels(comp_aparell, field_code: str, item_labels: list[str]) -> None:
    config = dict(comp_aparell.judge_ui_config if isinstance(comp_aparell.judge_ui_config, dict) else {})
    raw_field_map = config.get("field_item_labels")
    field_map = dict(raw_field_map) if isinstance(raw_field_map, dict) else {}
    if any(item_labels):
        field_map[field_code] = list(item_labels)
    else:
        field_map.pop(field_code, None)
    if field_map:
        config["field_item_labels"] = field_map
    else:
        config.pop("field_item_labels", None)
    comp_aparell.judge_ui_config = config
    comp_aparell.save(update_fields=["judge_ui_config"])


def _member_slot_choices(competicio, comp_aparell):
    if not comp_aparell or not is_team_context_app(comp_aparell):
        return []
    try:
        subjects, _issues = build_team_subjects_for_comp_aparell(competicio, comp_aparell)
    except Exception:
        return []
    max_slots = max((len(item.get("members") or []) for item in subjects), default=0)
    return list(range(1, max_slots + 1))


def _permission_summary_rows(perms):
    rows = []
    for raw_perm in perms or []:
        perm = normalize_permission_target(raw_perm)
        item_count = perm.get("item_count")
        role = str(perm.get("role") or "standard").strip().lower() or "standard"
        if role not in PERMISSION_ROLES:
            role = "standard"
        rows.append({
            "label": build_permission_label(perm),
            "judge_index": int(perm.get("judge_index") or 1),
            "item_start": int(perm.get("item_start") or 1),
            "item_count": (None if item_count in (None, "", "null") else int(item_count)),
            "role": role,
            "role_label": "Supervisor" if role == "supervisor" else "Standard",
            "is_supervisor": role == "supervisor",
        })
    return rows


def _redirect_qr_home(competicio, comp_aparell=None):
    url = reverse("qr_admin_home", kwargs={"competicio_id": competicio.id})
    if comp_aparell is not None:
        return f"{url}?comp_aparell={comp_aparell.id}"
    return url


def _qr_admin_url(competicio, *, selected_judge=None, selected_public=None):
    url = reverse("qr_admin_home", kwargs={"competicio_id": competicio.id})
    if selected_judge is not None:
        return reverse(
            "qr_admin_detail",
            kwargs={"competicio_id": competicio.id, "token_id": selected_judge.id},
        )
    if selected_public is not None:
        return f"{url}?public_token={selected_public.id}"
    return url


def _build_permissions_from_formset(formset, schema_by_code, comp_aparell, *, team_context_mode=False):
    perms = []
    for f in formset.cleaned_data:
        if not f or f.get("DELETE"):
            continue
        if not f.get("field_code"):
            continue
        perm = _validate_permission_row(
            schema_by_code,
            f,
            team_context_mode=team_context_mode,
        )
        perm["runtime_field_code"] = permission_runtime_code(perm, comp_aparell)
        perms.append(perm)
    if len(perms) > MAX_TOKEN_PERMISSIONS:
        raise ValueError(f"Maxim {MAX_TOKEN_PERMISSIONS} permisos per assignacio.")
    if not perms:
        raise ValueError("Has d'afegir almenys un permis (camp + jutge).")
    return perms


def _assignment_summary_rows(assignments):
    rows = []
    for assignment in assignments:
        phase = getattr(assignment, "fase", None)
        comp_aparell = getattr(assignment, "comp_aparell", None)
        rows.append({
            "assignment": assignment,
            "app_label": getattr(comp_aparell, "display_nom", None) or str(comp_aparell or ""),
            "phase_label": getattr(phase, "nom", None) or "Preliminar",
            "subject_scope_summary": subject_scope_summary(
                getattr(assignment, "subject_scope", None),
                competicio=getattr(assignment, "competicio", None),
            ),
            "permission_summaries": _permission_summary_rows(assignment.permissions),
        })
    return rows


def _schema_context_for_app(competicio, comp_aparell):
    if not comp_aparell:
        return {
            "schema": {},
            "runtime_schema": {},
            "field_catalog": [],
            "field_choices": _schema_field_choices({}),
            "schema_by_code": {},
            "team_context_mode": False,
            "member_slot_choices": [],
            "phase_choices": [],
        }
    _schema_obj, schema = resolve_scoring_schema_for_comp_aparell(comp_aparell)
    team_context_mode = bool(is_team_context_app(comp_aparell))
    return {
        "schema": schema,
        "runtime_schema": runtime_schema_for_comp_aparell(schema, comp_aparell),
        "field_catalog": _schema_field_catalog(
            schema,
            comp_aparell=comp_aparell,
            team_context_mode=team_context_mode,
        ),
        "field_choices": _schema_field_choices(schema),
        "schema_by_code": _schema_field_by_code(schema),
        "team_context_mode": team_context_mode,
        "member_slot_choices": _member_slot_choices(competicio, comp_aparell),
        "phase_choices": list(
            CompeticioAparellFase.objects
            .filter(competicio=competicio, comp_aparell=comp_aparell)
            .order_by("ordre", "id")
        ),
    }


def _app_catalog_for_template(competicio, comp_aparells):
    catalog = {}
    for comp_aparell in comp_aparells:
        app_context = _schema_context_for_app(competicio, comp_aparell)
        catalog[str(comp_aparell.id)] = {
            "id": comp_aparell.id,
            "label": getattr(comp_aparell, "display_nom", "") or str(comp_aparell),
            "fields": app_context["field_catalog"],
            "phases": [
                {"id": phase.id, "label": phase.nom}
                for phase in app_context["phase_choices"]
            ],
            "team_context": app_context["team_context_mode"],
            "member_slots": app_context["member_slot_choices"],
        }
    return catalog


def _validate_permission_row(schema_by_code: dict, row: dict, *, team_context_mode: bool = False):
    """
    Normalitza i limita judge_index / items segons schema real.
    """
    code = row["field_code"]
    f = schema_by_code.get(code)
    if not f:
        raise ValueError("Camp no existeix al schema")
    role = str(row.get("role") or "standard").strip().lower() or "standard"
    if role not in PERMISSION_ROLES:
        raise ValueError(f"{code}: rol invalid.")
    requested_scope = str(row.get("scope") or "shared").strip().lower() or "shared"
    if requested_scope not in {"shared", "member"}:
        raise ValueError(f"{code}: scope invalid.")
    if team_context_mode:
        scope = _schema_field_scope(f, team_context_mode=True)
        if requested_scope != scope:
            raise ValueError(
                f"{code}: aquest camp nomes admet abast {'individual' if scope == 'member' else 'compartit'}."
            )
    else:
        scope = "shared"

    # limit judges.count
    max_j = int(((f.get("judges") or {}).get("count")) or 1)
    j = int(row.get("judge_index") or 1)
    if j < 1 or j > max_j:
        raise ValueError(f"{code}: judge_index fora de rang (1..{max_j})")

    # si és matrix, valida rang items
    ftype = f.get("type") or "number"
    if ftype == "matrix":
        max_items = int(((f.get("items") or {}).get("count")) or 1)
        item_start = int(row.get("item_start") or 1)
        item_count = row.get("item_count")
        if item_start < 1 or item_start > max_items:
            raise ValueError(f"{code}: item_start fora de rang (1..{max_items})")
        if item_count is not None and item_count != "":
            item_count = int(item_count)
            if item_count < 1:
                raise ValueError(f"{code}: item_count invàlid")
            if item_start + item_count - 1 > max_items:
                raise ValueError(f"{code}: rang d'ítems supera {max_items}")
        else:
            item_count = None
    else:
        # per number/list, ignorem rang items
        item_start = 1
        item_count = None

    member_mode = None
    member_slots = []
    if scope == "member":
        member_mode = str(row.get("member_mode") or "").strip().lower() or "all"
        member_slots = parse_permission_member_slots(row.get("member_slots"))
        if member_mode not in {"single", "subset", "all"}:
            raise ValueError(f"{code}: mode de membre invalid.")
        if member_mode == "single":
            if len(member_slots) != 1:
                raise ValueError(f"{code}: has d'escollir exactament un membre.")
        elif member_mode == "subset":
            if not member_slots:
                raise ValueError(f"{code}: has d'escollir almenys un membre.")
            if len(set(member_slots)) != len(member_slots):
                raise ValueError(f"{code}: hi ha membres duplicats a la seleccio.")
        else:
            member_slots = []

    result = {
        "field_code": code,
        "scope": scope,
        "judge_index": j,
        "item_start": item_start,
        "item_count": item_count,
        "role": role,
    }
    if scope == "member":
        result["member_mode"] = member_mode
        if member_mode != "all":
            result["member_slots"] = member_slots
    return result


@require_http_methods(["GET", "POST"])
def qr_admin_home(request, competicio_id, token_id=None):
    competicio = get_object_or_404(Competicio, pk=competicio_id)

    comp_aparell_qs = CompeticioAparell.objects.filter(competicio=competicio, actiu=True).select_related("aparell")
    comp_aparells = list(comp_aparell_qs)
    comp_aparell_id = request.GET.get("comp_aparell")
    comp_aparell = None
    if comp_aparell_id:
        comp_aparell = get_object_or_404(comp_aparell_qs, pk=comp_aparell_id)
    base_comp_aparell = comp_aparell or (comp_aparells[0] if comp_aparells else None)

    if base_comp_aparell:
        max_ex = max(1, int(getattr(base_comp_aparell, "nombre_exercicis", 1) or 1))
        exercicis = list(range(1, max_ex + 1))
        try:
            exercici = int(request.GET.get("ex") or 1)
        except Exception:
            exercici = 1
        exercici = max(1, min(max_ex, exercici))
    else:
        exercicis = [1]
        exercici = 1

    assignment_comp_aparell = base_comp_aparell
    app_context = _schema_context_for_app(competicio, assignment_comp_aparell)
    schema = app_context["schema"]
    runtime_schema = app_context["runtime_schema"]
    field_catalog = app_context["field_catalog"]
    field_choices = app_context["field_choices"]
    schema_by_code = app_context["schema_by_code"]
    team_context_mode = app_context["team_context_mode"]
    member_slot_choices = app_context["member_slot_choices"]
    phase_choices = app_context["phase_choices"]

    PermissionFS = formset_factory(
        PermissionRowForm,
        extra=3,
        can_delete=True,
        max_num=MAX_TOKEN_PERMISSIONS,
        validate_max=True,
    )

    if request.method == "POST":
        action = str(request.POST.get("action") or "").strip().lower()
        if action in {"create_public_live", "create_public_qr", "create_public"}:
            if not user_has_competicio_capability(request.user, competicio, "public_live.manage"):
                messages.error(request, "No tens permisos per gestionar QRs publics.")
                return redirect(_redirect_qr_home(competicio, comp_aparell))
            label = (request.POST.get("label") or "").strip()
            can_view_media = str(request.POST.get("can_view_media") or "").strip().lower() in {
                "1",
                "true",
                "yes",
                "on",
            }
            tok = PublicLiveToken.objects.create(
                competicio=competicio,
                label=label,
                can_view_media=can_view_media,
                is_active=True,
            )
            messages.success(request, "QR public creat.")
            return redirect(_qr_admin_url(competicio, selected_public=tok))

        if action in {"revoke_public_live", "revoke_public_qr", "revoke_public"}:
            if not user_has_competicio_capability(request.user, competicio, "public_live.manage"):
                messages.error(request, "No tens permisos per gestionar QRs publics.")
                return redirect(_redirect_qr_home(competicio, comp_aparell))
            token_id = request.POST.get("token_id")
            tok = get_object_or_404(PublicLiveToken, pk=token_id, competicio=competicio)
            tok.revoked_at = timezone.now()
            tok.is_active = False
            tok.save(update_fields=["revoked_at", "is_active"])
            messages.success(request, "QR public revocat.")
            return redirect(_qr_admin_url(competicio, selected_public=tok))

        if action in {"revoke", "revoke_judge_qr", "revoke_judge"}:
            token_id = request.POST.get("token_id")
            tok = get_object_or_404(JudgeDeviceToken, pk=token_id, competicio=competicio)
            tok.revoked_at = timezone.now()
            tok.is_active = False
            tok.save(update_fields=["revoked_at", "is_active"])
            messages.success(request, "QR de jutge revocat.")
            return redirect(_qr_admin_url(competicio, selected_judge=tok))

        if action == "deactivate_assignment":
            assignment_id = request.POST.get("assignment_id")
            assignment = get_object_or_404(JudgePortalAssignment, pk=assignment_id, competicio=competicio)
            assignment.is_active = False
            assignment.save(update_fields=["is_active", "updated_at"])
            messages.success(request, "Assignacio desactivada.")
            return redirect(_qr_admin_url(competicio, selected_judge=assignment.judge_token))

        if action in {"create_device", "create_judge_qr", "create_judge"}:
            token_form = JudgeTokenCreateForm(request.POST)
            if not base_comp_aparell:
                token_form.add_error(None, "Cal tenir almenys un aparell actiu per crear un QR.")
            if token_form.is_valid() and not token_form.errors:
                token_obj = JudgeDeviceToken.objects.create(
                    competicio=competicio,
                    comp_aparell=base_comp_aparell,
                    label=token_form.cleaned_data.get("label") or "",
                    permissions=[],
                    can_record_video=bool(token_form.cleaned_data.get("can_record_video")),
                    is_active=True,
                )
                messages.success(request, "QR general creat.")
                return redirect(_qr_admin_url(competicio, selected_judge=token_obj))

        if action == "save_item_labels":
            raw_item_app_id = request.POST.get("item_labels_comp_aparell_id") or request.POST.get("comp_aparell_id")
            item_comp_aparell = comp_aparell
            if raw_item_app_id not in (None, ""):
                item_comp_aparell = get_object_or_404(comp_aparell_qs, pk=raw_item_app_id)
            if not item_comp_aparell:
                messages.error(request, "No hi ha cap aparell seleccionat.")
                return redirect(reverse("judges_qr_home", kwargs={"competicio_id": competicio.id}))

            item_context = _schema_context_for_app(competicio, item_comp_aparell)
            schema_by_code = item_context["schema_by_code"]
            field_code = str(request.POST.get("field_code") or "").strip()
            raw_labels_json = request.POST.get("item_labels_json") or "[]"
            field = schema_by_code.get(field_code)
            if not field:
                messages.error(request, "El camp seleccionat no existeix al schema.")
                return redirect(
                    f"{reverse('judges_qr_home', kwargs={'competicio_id': competicio.id})}"
                    f"?comp_aparell={item_comp_aparell.id}"
                )
            if str(field.get("type") or "number").strip().lower() != "matrix":
                messages.error(request, "Nomes es poden configurar noms d'items per camps matrix.")
                return redirect(
                    f"{reverse('judges_qr_home', kwargs={'competicio_id': competicio.id})}"
                    f"?comp_aparell={item_comp_aparell.id}"
                )
            try:
                raw_labels = json.loads(raw_labels_json)
            except Exception:
                messages.error(request, "El format dels noms d'items no es valid.")
                return redirect(
                    f"{reverse('judges_qr_home', kwargs={'competicio_id': competicio.id})}"
                    f"?comp_aparell={item_comp_aparell.id}"
                )
            if not isinstance(raw_labels, list):
                messages.error(request, "Els noms d'items han de ser una llista.")
                return redirect(
                    f"{reverse('judges_qr_home', kwargs={'competicio_id': competicio.id})}"
                    f"?comp_aparell={item_comp_aparell.id}"
                )

            max_items = _field_items_count(field)
            if len(raw_labels) > max_items:
                messages.error(request, f"No es poden desar mes de {max_items} noms d'items.")
                return redirect(
                    f"{reverse('judges_qr_home', kwargs={'competicio_id': competicio.id})}"
                    f"?comp_aparell={item_comp_aparell.id}"
                )

            clean_labels = []
            for idx in range(max_items):
                raw_label = raw_labels[idx] if idx < len(raw_labels) else ""
                clean_labels.append("" if raw_label in (None, "") else str(raw_label).strip())

            _save_comp_aparell_item_labels(item_comp_aparell, field_code, clean_labels)
            messages.success(request, "Noms d'items desats.")
            return redirect(_redirect_qr_home(competicio, item_comp_aparell))

        if action == "add_assignment":
            raw_assignment_app_id = (
                request.POST.get("assignment_comp_aparell_id")
                or request.POST.get("comp_aparell_id")
                or request.GET.get("comp_aparell")
            )
            assignment_comp_aparell = None
            if raw_assignment_app_id not in (None, ""):
                assignment_comp_aparell = get_object_or_404(comp_aparell_qs, pk=raw_assignment_app_id)
            if not assignment_comp_aparell:
                messages.error(request, "Selecciona un aparell per afegir una assignacio.")
                return redirect(_redirect_qr_home(competicio))
            app_context = _schema_context_for_app(competicio, assignment_comp_aparell)
            schema = app_context["schema"]
            runtime_schema = app_context["runtime_schema"]
            field_catalog = app_context["field_catalog"]
            field_choices = app_context["field_choices"]
            schema_by_code = app_context["schema_by_code"]
            team_context_mode = app_context["team_context_mode"]
            member_slot_choices = app_context["member_slot_choices"]
            phase_choices = app_context["phase_choices"]
            token_id = request.POST.get("token_id")
            tok = get_object_or_404(JudgeDeviceToken, pk=token_id, competicio=competicio)
            formset = PermissionFS(request.POST, form_kwargs={"field_choices": field_choices})
            if formset.is_valid():
                try:
                    perms = _build_permissions_from_formset(
                        formset,
                        schema_by_code,
                        assignment_comp_aparell,
                        team_context_mode=team_context_mode,
                    )
                    raw_phase_id = request.POST.get("fase_id")
                    phase = None
                    if raw_phase_id not in (None, "", "0"):
                        phase = get_object_or_404(
                            CompeticioAparellFase,
                            pk=raw_phase_id,
                            competicio=competicio,
                            comp_aparell=assignment_comp_aparell,
                        )
                    validate_single_supervisor_per_field(
                        competicio=competicio,
                        comp_aparell=assignment_comp_aparell,
                        phase=phase,
                        permissions=perms,
                    )
                    try:
                        ordre = int(request.POST.get("ordre") or 1)
                    except Exception:
                        ordre = 1
                    ordre = max(1, ordre)
                    while JudgePortalAssignment.objects.filter(judge_token=tok, ordre=ordre).exists():
                        ordre += 1
                    JudgePortalAssignment.objects.create(
                        judge_token=tok,
                        competicio=competicio,
                        comp_aparell=assignment_comp_aparell,
                        fase=phase,
                        label=str(request.POST.get("assignment_label") or "").strip(),
                        ordre=ordre,
                        permissions=perms,
                        subject_scope=subject_scope_from_post(request.POST),
                        is_active=True,
                    )
                    messages.success(request, "Assignacio afegida al QR.")
                    return redirect(_qr_admin_url(competicio, selected_judge=tok))
                except ValueError as e:
                    messages.error(request, str(e))
            else:
                messages.error(request, "Revisa els errors marcats a la taula de permisos.")

        # create token
        token_form = JudgeTokenCreateForm(request.POST)
        formset = PermissionFS(request.POST, form_kwargs={"field_choices": field_choices})

        token_form_valid = token_form.is_valid()
        formset_valid = formset.is_valid()

        if token_form_valid and formset_valid and comp_aparell:
            perms = []
            for f in formset.cleaned_data:
                if not f or f.get("DELETE"):
                    continue
                if not f.get("field_code"):
                    continue
                try:
                    perm = _validate_permission_row(
                        schema_by_code,
                        f,
                        team_context_mode=team_context_mode,
                    )
                    perm["runtime_field_code"] = permission_runtime_code(perm, comp_aparell)
                    perms.append(perm)
                except ValueError as e:
                    # re-render amb error “global”
                    token_form.add_error(None, str(e))
                    break

            if len(perms) > MAX_TOKEN_PERMISSIONS:
                token_form.add_error(None, f"Maxim {MAX_TOKEN_PERMISSIONS} permisos per token.")

            if not perms:
                token_form.add_error(None, "Has d'afegir almenys un permis (camp + jutge) per crear el QR.")

            if not token_form.errors:
                try:
                    validate_single_supervisor_per_field(
                        competicio=competicio,
                        comp_aparell=comp_aparell,
                        phase=None,
                        permissions=perms,
                    )
                except ValueError as e:
                    token_form.add_error(None, str(e))

            if not token_form.errors:
                label = token_form.cleaned_data.get("label") or ""
                can_record_video = bool(token_form.cleaned_data.get("can_record_video"))
                token_obj = JudgeDeviceToken.objects.create(
                    competicio=competicio,
                    comp_aparell=comp_aparell,
                    label=label,
                    permissions=perms,
                    can_record_video=can_record_video,
                    is_active=True,
                )
                if not token_obj.portal_assignments.exists():
                    JudgePortalAssignment.objects.create(
                        judge_token=token_obj,
                        competicio=competicio,
                        comp_aparell=comp_aparell,
                        fase=None,
                        label=label or getattr(comp_aparell, "display_nom", ""),
                        ordre=1,
                        permissions=perms,
                        subject_scope={},
                        is_active=True,
                    )
                return redirect(_qr_admin_url(competicio, selected_judge=token_obj))
        elif token_form_valid and not formset_valid:
            token_form.add_error(None, "Revisa els errors marcats a la taula de permisos.")
    else:
        token_form = JudgeTokenCreateForm()
        formset = PermissionFS(form_kwargs={"field_choices": field_choices})

    tokens_qs = (
        JudgeDeviceToken.objects
        .filter(competicio=competicio)
        .prefetch_related("portal_assignments__comp_aparell", "portal_assignments__fase")
        .order_by("-created_at")
    )
    tokens = list(tokens_qs)
    for token in tokens:
        assignments = list(token.portal_assignments.all())
        token.permission_summaries = _permission_summary_rows(token.permissions)
        token.assignment_summaries = _assignment_summary_rows(assignments)

    public_tokens = list(
        PublicLiveToken.objects
        .filter(competicio=competicio)
        .order_by("-created_at")
    )
    assignable_judge_tokens = [
        token
        for token in tokens
        if token.is_active and not token.revoked_at
    ]
    selected_judge_token = None
    selected_public_token = None
    raw_selected_kind = str(request.GET.get("selected_kind") or "").strip().lower()
    raw_selected_id = request.GET.get("selected_id")
    raw_selected_judge = token_id or request.GET.get("selected_judge") or request.POST.get("token_id")
    raw_selected_public = request.GET.get("selected_public")
    if raw_selected_kind == "judge" and raw_selected_id:
        raw_selected_judge = raw_selected_id
    elif raw_selected_kind == "public" and raw_selected_id:
        raw_selected_public = raw_selected_id
    if raw_selected_judge:
        selected_judge_token = next((token for token in tokens if str(token.id) == str(raw_selected_judge)), None)
    if selected_judge_token is None and raw_selected_public:
        selected_public_token = next((token for token in public_tokens if str(token.id) == str(raw_selected_public)), None)
    if selected_judge_token is None and selected_public_token is None and tokens:
        selected_judge_token = tokens[0]
    selected_kind = "judge" if selected_judge_token is not None else ("public" if selected_public_token is not None else "")
    selected_id = str(
        getattr(selected_judge_token or selected_public_token, "id", "") or ""
    )
    selected_assignment_rows = list(getattr(selected_judge_token, "assignment_summaries", []) or [])
    app_catalog = _app_catalog_for_template(competicio, comp_aparells)

    ctx = {
        "competicio": competicio,
        "comp_aparell": comp_aparell,
        "assignment_comp_aparell": assignment_comp_aparell,
        "base_comp_aparell": base_comp_aparell,
        "comp_aparell_qs": comp_aparells,
        "phase_choices": phase_choices,
        "schema": schema,
        "runtime_schema": runtime_schema,
        "tokens": tokens,
        "judge_tokens": tokens,
        "assignable_judge_tokens": assignable_judge_tokens,
        "public_tokens": public_tokens,
        "comp_aparells": comp_aparells,
        "selected_judge_token": selected_judge_token,
        "selected_public_token": selected_public_token,
        "selected_kind": selected_kind,
        "selected_id": selected_id,
        "selected_assignment_rows": selected_assignment_rows,
        "token_form": token_form,
        "formset": formset,
        "assignment_formset": formset,
        "max_permissions": MAX_TOKEN_PERMISSIONS,
        "exercicis": exercicis,
        "exercici": exercici,
        "is_team_context_mode": team_context_mode,
        "member_slot_choices": member_slot_choices,
        "schema_field_catalog": field_catalog,
        "app_catalog": app_catalog,
        "subject_scope_options": subject_scope_options_for_competicio(competicio),
        "can_manage_public_live": user_has_competicio_capability(request.user, competicio, "public_live.manage"),
        "can_manage_judge_tokens": True,
    }
    return render(request, "judge/admin_tokens.html", ctx)


def judges_qr_home(request, competicio_id):
    return qr_admin_home(request, competicio_id)


@require_http_methods(["GET"])
def judges_qr_print(request, competicio_id):
    competicio = get_object_or_404(Competicio, pk=competicio_id)
    comp_aparell_id = request.GET.get("comp_aparell")
    comp_aparell = None
    if comp_aparell_id not in (None, ""):
        comp_aparell = get_object_or_404(CompeticioAparell, pk=comp_aparell_id, competicio=competicio, actiu=True)
    raw_franja = request.GET.get("franja")
    try:
        franja_id = int(raw_franja) if raw_franja not in (None, "") else None
    except Exception:
        franja_id = None
    max_ex = max(1, int(getattr(comp_aparell, "nombre_exercicis", 1) or 1)) if comp_aparell else 1
    try:
        exercici = int(request.GET.get("ex") or 1)
    except Exception:
        exercici = 1
    exercici = max(1, min(max_ex, exercici))

    tokens = JudgeDeviceToken.objects.filter(
        competicio=competicio,
        is_active=True,
        revoked_at__isnull=True,
    )
    if comp_aparell:
        assignment_token_ids = (
            JudgePortalAssignment.objects
            .filter(competicio=competicio, comp_aparell=comp_aparell, is_active=True)
            .values_list("judge_token_id", flat=True)
        )
        tokens = tokens.filter(models.Q(comp_aparell=comp_aparell) | models.Q(id__in=assignment_token_ids)).distinct()
    tokens = tokens.order_by("label", "created_at")
    for token in tokens:
        token.permission_summaries = _permission_summary_rows(token.permissions)

    public_tokens = []
    if user_has_competicio_capability(request.user, competicio, "public_live.manage"):
        public_tokens = list(
            PublicLiveToken.objects
            .filter(competicio=competicio, is_active=True, revoked_at__isnull=True)
            .order_by("label", "created_at")
        )

    ctx = {
        "competicio": competicio,
        "comp_aparell": comp_aparell,
        "tokens": tokens,
        "public_tokens": public_tokens,
        "exercici": exercici,
        "franja_id": franja_id,
    }
    return render(request, "judge/print_tokens.html", ctx)


@require_http_methods(["GET", "POST"])
def public_live_qr_home(request, competicio_id):
    competicio = get_object_or_404(Competicio, pk=competicio_id)

    if request.method == "POST":
        action = (request.POST.get("action") or "").strip().lower()

        if action == "revoke":
            token_id = request.POST.get("token_id")
            tok = get_object_or_404(PublicLiveToken, pk=token_id, competicio=competicio)
            tok.revoked_at = timezone.now()
            tok.is_active = False
            tok.save(update_fields=["revoked_at", "is_active"])
            return redirect(reverse("public_live_qr_home", kwargs={"competicio_id": competicio.id}))

        if action == "create":
            label = (request.POST.get("label") or "").strip()
            can_view_media = str(request.POST.get("can_view_media") or "").strip().lower() in {
                "1",
                "true",
                "yes",
                "on",
            }
            PublicLiveToken.objects.create(
                competicio=competicio,
                label=label,
                can_view_media=can_view_media,
                is_active=True,
            )
            return redirect(reverse("public_live_qr_home", kwargs={"competicio_id": competicio.id}))

    tokens = (
        PublicLiveToken.objects
        .filter(competicio=competicio)
        .order_by("-created_at")
    )

    ctx = {
        "competicio": competicio,
        "tokens": tokens,
    }
    return render(request, "judge/admin_public_live_tokens.html", ctx)


@require_http_methods(["GET"])
def public_live_qr_print(request, competicio_id):
    competicio = get_object_or_404(Competicio, pk=competicio_id)
    tokens = (
        PublicLiveToken.objects
        .filter(competicio=competicio, is_active=True, revoked_at__isnull=True)
        .order_by("label", "created_at")
    )
    ctx = {
        "competicio": competicio,
        "tokens": tokens,
    }
    return render(request, "judge/print_public_live_tokens.html", ctx)
