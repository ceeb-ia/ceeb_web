from django.forms import formset_factory
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from ...forms_judge import JudgeTokenCreateForm, PermissionRowForm
from ...models import Competicio
from ...models.competicio import CompeticioAparell
from ...models.judging import JudgeDeviceToken, PublicLiveToken
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

MAX_TOKEN_PERMISSIONS = 15


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


def _schema_field_catalog(schema: dict, *, team_context_mode: bool = False):
    items = []
    for f in (schema.get("fields") or []):
        if not isinstance(f, dict) or not f.get("code"):
            continue
        code = str(f.get("code") or "").strip()
        label = str(f.get("label") or code).strip() or code
        items.append({
            "code": code,
            "label": label,
            "type": str(f.get("type") or "number").strip().lower() or "number",
            "scope": _schema_field_scope(f, team_context_mode=team_context_mode),
        })
    return items


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
        rows.append({
            "label": build_permission_label(perm),
            "judge_index": int(perm.get("judge_index") or 1),
            "item_start": int(perm.get("item_start") or 1),
            "item_count": (None if item_count in (None, "", "null") else int(item_count)),
        })
    return rows


def _validate_permission_row(schema_by_code: dict, row: dict, *, team_context_mode: bool = False):
    """
    Normalitza i limita judge_index / items segons schema real.
    """
    code = row["field_code"]
    f = schema_by_code.get(code)
    if not f:
        raise ValueError("Camp no existeix al schema")
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
    }
    if scope == "member":
        result["member_mode"] = member_mode
        if member_mode != "all":
            result["member_slots"] = member_slots
    return result


@require_http_methods(["GET", "POST"])
def judges_qr_home(request, competicio_id):
    competicio = get_object_or_404(Competicio, pk=competicio_id)

    # aparell seleccionat
    comp_aparell_qs = CompeticioAparell.objects.filter(competicio=competicio, actiu=True).select_related("aparell")
    comp_aparell_id = request.GET.get("comp_aparell")
    comp_aparell = None
    if comp_aparell_id:
        comp_aparell = get_object_or_404(comp_aparell_qs, pk=comp_aparell_id)
    else:
        comp_aparell = comp_aparell_qs.first()

    if comp_aparell:
        max_ex = max(1, int(getattr(comp_aparell, "nombre_exercicis", 1) or 1))
        exercicis = list(range(1, max_ex + 1))
        try:
            exercici = int(request.GET.get("ex") or 1)
        except Exception:
            exercici = 1
        exercici = max(1, min(max_ex, exercici))
    else:
        exercicis = [1]
        exercici = 1

    schema = {}
    runtime_schema = {}
    field_catalog = []
    team_context_mode = bool(comp_aparell and is_team_context_app(comp_aparell))
    if comp_aparell:
        _schema_obj, schema = resolve_scoring_schema_for_comp_aparell(comp_aparell)
        runtime_schema = runtime_schema_for_comp_aparell(schema, comp_aparell)
        field_catalog = _schema_field_catalog(schema, team_context_mode=team_context_mode)

    field_choices = _schema_field_choices(schema)
    schema_by_code = _schema_field_by_code(schema)
    member_slot_choices = _member_slot_choices(competicio, comp_aparell)

    PermissionFS = formset_factory(
        PermissionRowForm,
        extra=3,
        can_delete=True,
        max_num=MAX_TOKEN_PERMISSIONS,
        validate_max=True,
    )

    if request.method == "POST":
        action = request.POST.get("action") or ""
        if action == "revoke":
            token_id = request.POST.get("token_id")
            tok = get_object_or_404(JudgeDeviceToken, pk=token_id, competicio=competicio)
            tok.revoked_at = timezone.now()
            tok.is_active = False
            tok.save(update_fields=["revoked_at", "is_active"])
            return redirect(
                f"{reverse('judges_qr_home', kwargs={'competicio_id': competicio.id})}"
                f"?comp_aparell={comp_aparell.id}"
            )

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
                label = token_form.cleaned_data.get("label") or ""
                can_record_video = bool(token_form.cleaned_data.get("can_record_video"))
                JudgeDeviceToken.objects.create(
                    competicio=competicio,
                    comp_aparell=comp_aparell,
                    label=label,
                    permissions=perms,
                    can_record_video=can_record_video,
                    is_active=True,
                )
                return redirect(
                    f"{reverse('judges_qr_home', kwargs={'competicio_id': competicio.id})}"
                    f"?comp_aparell={comp_aparell.id}"
                )
        elif token_form_valid and not formset_valid:
            token_form.add_error(None, "Revisa els errors marcats a la taula de permisos.")
    else:
        token_form = JudgeTokenCreateForm()
        formset = PermissionFS(form_kwargs={"field_choices": field_choices})

    tokens = []
    if comp_aparell:
        tokens = (JudgeDeviceToken.objects
                  .filter(competicio=competicio, comp_aparell=comp_aparell)
                  .order_by("-created_at"))
        for token in tokens:
            token.permission_summaries = _permission_summary_rows(token.permissions)

    ctx = {
        "competicio": competicio,
        "comp_aparell": comp_aparell,
        "comp_aparell_qs": comp_aparell_qs,
        "schema": schema,
        "runtime_schema": runtime_schema,
        "tokens": tokens,
        "token_form": token_form,
        "formset": formset,
        "max_permissions": MAX_TOKEN_PERMISSIONS,
        "exercicis": exercicis,
        "exercici": exercici,
        "is_team_context_mode": team_context_mode,
        "member_slot_choices": member_slot_choices,
        "schema_field_catalog": field_catalog,
    }
    return render(request, "judge/admin_tokens.html", ctx)


@require_http_methods(["GET"])
def judges_qr_print(request, competicio_id):
    competicio = get_object_or_404(Competicio, pk=competicio_id)
    comp_aparell_id = request.GET.get("comp_aparell")
    comp_aparell = get_object_or_404(CompeticioAparell, pk=comp_aparell_id, competicio=competicio, actiu=True)
    raw_franja = request.GET.get("franja")
    try:
        franja_id = int(raw_franja) if raw_franja not in (None, "") else None
    except Exception:
        franja_id = None
    max_ex = max(1, int(getattr(comp_aparell, "nombre_exercicis", 1) or 1))
    try:
        exercici = int(request.GET.get("ex") or 1)
    except Exception:
        exercici = 1
    exercici = max(1, min(max_ex, exercici))

    tokens = (JudgeDeviceToken.objects
              .filter(competicio=competicio, comp_aparell=comp_aparell, is_active=True, revoked_at__isnull=True)
              .order_by("label", "created_at"))
    for token in tokens:
        token.permission_summaries = _permission_summary_rows(token.permissions)

    ctx = {
        "competicio": competicio,
        "comp_aparell": comp_aparell,
        "tokens": tokens,
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
