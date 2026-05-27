from __future__ import annotations

import json

from django.contrib import messages
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
from .admin import (
    MAX_TOKEN_PERMISSIONS,
    _app_catalog_for_template,
    _assignment_summary_rows,
    _build_permissions_from_formset,
    _field_items_count,
    _permission_summary_rows,
    _save_comp_aparell_item_labels,
    _schema_context_for_app,
)


def _qr_admin_url(competicio, token=None):
    if token is None:
        return reverse("qr_admin_home", kwargs={"competicio_id": competicio.id})
    return reverse("qr_admin_detail", kwargs={"competicio_id": competicio.id, "token_id": token.id})


def _active_competicio_aparells(competicio):
    return list(
        CompeticioAparell.objects
        .filter(competicio=competicio, actiu=True)
        .select_related("aparell")
        .order_by("ordre", "id")
    )


def _token_rows(competicio, *, can_manage_public_live=False, selected_token=None, selected_public_token=None):
    judge_tokens = (
        JudgeDeviceToken.objects
        .filter(competicio=competicio)
        .prefetch_related("portal_assignments__comp_aparell", "portal_assignments__fase")
        .order_by("-created_at")
    )
    rows = []
    for token in judge_tokens:
        assignments = list(token.portal_assignments.all())
        rows.append({
            "kind": "judge",
            "id": str(token.id),
            "token": token,
            "label": token.label or "(sense etiqueta)",
            "is_active": bool(token.is_active and not token.revoked_at),
            "assignment_count": sum(1 for item in assignments if item.is_active),
            "url": _qr_admin_url(competicio, token),
            "is_selected": bool(selected_token and selected_token.id == token.id),
        })
    if can_manage_public_live:
        public_tokens = (
            PublicLiveToken.objects
            .filter(competicio=competicio)
            .order_by("-created_at")
        )
        for token in public_tokens:
            rows.append({
                "kind": "public",
                "id": str(token.id),
                "token": token,
                "label": token.label or "(sense etiqueta)",
                "is_active": bool(token.is_active and not token.revoked_at),
                "assignment_count": None,
                "url": f"{_qr_admin_url(competicio)}?public_token={token.id}",
                "is_selected": bool(selected_public_token and selected_public_token.id == token.id),
            })
    return rows


def _selected_judge_token(competicio, token_id):
    if token_id in (None, ""):
        return None
    return get_object_or_404(
        JudgeDeviceToken.objects
        .filter(competicio=competicio)
        .prefetch_related("portal_assignments__comp_aparell", "portal_assignments__fase"),
        pk=token_id,
    )


def _selected_public_token(competicio, request):
    token_id = request.GET.get("public_token")
    if token_id in (None, ""):
        return None
    return get_object_or_404(PublicLiveToken, pk=token_id, competicio=competicio)


def _permission_formset(permission_formset_cls, request, competicio, comp_aparell, *, bind=False):
    app_context = _schema_context_for_app(competicio, comp_aparell)
    kwargs = {"form_kwargs": {"field_choices": app_context["field_choices"]}}
    if bind:
        return permission_formset_cls(request.POST, **kwargs), app_context
    return permission_formset_cls(**kwargs), app_context


@require_http_methods(["GET", "POST"])
def qr_admin_home(request, competicio_id, token_id=None):
    competicio = get_object_or_404(Competicio, pk=competicio_id)
    can_manage_public_live = user_has_competicio_capability(request.user, competicio, "public_live.manage")
    comp_aparells = _active_competicio_aparells(competicio)
    base_comp_aparell = comp_aparells[0] if comp_aparells else None
    selected_token = _selected_judge_token(competicio, token_id)
    selected_public_token = None if selected_token else _selected_public_token(competicio, request)
    selected_app = base_comp_aparell

    PermissionFS = formset_factory(
        PermissionRowForm,
        extra=3,
        can_delete=True,
        max_num=MAX_TOKEN_PERMISSIONS,
        validate_max=True,
    )
    create_form = JudgeTokenCreateForm()
    assignment_formset, selected_app_context = _permission_formset(
        PermissionFS,
        request,
        competicio,
        selected_app,
    )

    if request.method == "POST":
        action = str(request.POST.get("action") or "").strip().lower()

        if action == "create_judge_qr":
            create_form = JudgeTokenCreateForm(request.POST)
            if not base_comp_aparell:
                create_form.add_error(None, "Cal tenir almenys un aparell actiu per crear un QR de jutge.")
            if create_form.is_valid() and not create_form.errors:
                token = JudgeDeviceToken.objects.create(
                    competicio=competicio,
                    comp_aparell=base_comp_aparell,
                    label=create_form.cleaned_data.get("label") or "",
                    permissions=[],
                    can_record_video=bool(create_form.cleaned_data.get("can_record_video")),
                    is_active=True,
                )
                messages.success(request, "QR de jutge creat.")
                return redirect(_qr_admin_url(competicio, token))

        elif action == "create_public_qr":
            if not can_manage_public_live:
                messages.error(request, "No tens permisos per gestionar QRs publics.")
                return redirect(_qr_admin_url(competicio, selected_token))
            token = PublicLiveToken.objects.create(
                competicio=competicio,
                label=str(request.POST.get("label") or "").strip(),
                can_view_media=str(request.POST.get("can_view_media") or "").strip().lower() in {"1", "true", "yes", "on"},
                is_active=True,
            )
            messages.success(request, "QR public creat.")
            return redirect(f"{_qr_admin_url(competicio)}?public_token={token.id}")

        elif action == "revoke_judge_qr":
            token = get_object_or_404(JudgeDeviceToken, pk=request.POST.get("token_id"), competicio=competicio)
            token.revoked_at = timezone.now()
            token.is_active = False
            token.save(update_fields=["revoked_at", "is_active"])
            messages.success(request, "QR de jutge revocat.")
            return redirect(_qr_admin_url(competicio, token))

        elif action == "update_judge_qr_label":
            token = get_object_or_404(JudgeDeviceToken, pk=request.POST.get("token_id"), competicio=competicio)
            label = str(request.POST.get("label") or "").strip()
            if len(label) > 120:
                messages.error(request, "El titol del QR no pot superar 120 caracters.")
                return redirect(_qr_admin_url(competicio, token))
            token.label = label
            token.save(update_fields=["label"])
            messages.success(request, "Titol del QR actualitzat.")
            return redirect(_qr_admin_url(competicio, token))

        elif action == "revoke_public_qr":
            if not can_manage_public_live:
                messages.error(request, "No tens permisos per gestionar QRs publics.")
                return redirect(_qr_admin_url(competicio, selected_token))
            token = get_object_or_404(PublicLiveToken, pk=request.POST.get("token_id"), competicio=competicio)
            token.revoked_at = timezone.now()
            token.is_active = False
            token.save(update_fields=["revoked_at", "is_active"])
            messages.success(request, "QR public revocat.")
            return redirect(f"{_qr_admin_url(competicio)}?public_token={token.id}")

        elif action == "update_public_qr_label":
            if not can_manage_public_live:
                messages.error(request, "No tens permisos per gestionar QRs publics.")
                return redirect(_qr_admin_url(competicio, selected_token))
            token = get_object_or_404(PublicLiveToken, pk=request.POST.get("token_id"), competicio=competicio)
            label = str(request.POST.get("label") or "").strip()
            if len(label) > 120:
                messages.error(request, "El titol del QR public no pot superar 120 caracters.")
                return redirect(f"{_qr_admin_url(competicio)}?public_token={token.id}")
            token.label = label
            token.save(update_fields=["label"])
            messages.success(request, "Titol del QR public actualitzat.")
            return redirect(f"{_qr_admin_url(competicio)}?public_token={token.id}")

        elif action == "delete_judge_qr":
            token = get_object_or_404(JudgeDeviceToken, pk=request.POST.get("token_id"), competicio=competicio)
            if token.is_active and not token.revoked_at:
                messages.error(request, "Primer cal revocar el QR de jutge abans d'eliminar-lo.")
                return redirect(_qr_admin_url(competicio, token))
            token.delete()
            messages.success(request, "QR de jutge eliminat.")
            return redirect(_qr_admin_url(competicio))

        elif action == "delete_public_qr":
            if not can_manage_public_live:
                messages.error(request, "No tens permisos per gestionar QRs publics.")
                return redirect(_qr_admin_url(competicio, selected_token))
            token = get_object_or_404(PublicLiveToken, pk=request.POST.get("token_id"), competicio=competicio)
            if token.is_active and not token.revoked_at:
                messages.error(request, "Primer cal revocar el QR public abans d'eliminar-lo.")
                return redirect(f"{_qr_admin_url(competicio)}?public_token={token.id}")
            token.delete()
            messages.success(request, "QR public eliminat.")
            return redirect(_qr_admin_url(competicio))

        elif action == "deactivate_assignment":
            assignment = get_object_or_404(
                JudgePortalAssignment,
                pk=request.POST.get("assignment_id"),
                competicio=competicio,
            )
            assignment.is_active = False
            assignment.save(update_fields=["is_active", "updated_at"])
            messages.success(request, "Assignacio desactivada.")
            return redirect(_qr_admin_url(competicio, assignment.judge_token))

        elif action == "delete_assignment":
            assignment = get_object_or_404(
                JudgePortalAssignment,
                pk=request.POST.get("assignment_id"),
                competicio=competicio,
            )
            token = assignment.judge_token
            if assignment.is_active:
                messages.error(request, "Primer cal desactivar l'acces abans d'eliminar-lo.")
                return redirect(_qr_admin_url(competicio, token))
            assignment.delete()
            messages.success(request, "Acces eliminat.")
            return redirect(_qr_admin_url(competicio, token))

        elif action == "add_assignment":
            token = get_object_or_404(JudgeDeviceToken, pk=request.POST.get("token_id"), competicio=competicio)
            selected_token = token
            selected_app = get_object_or_404(
                CompeticioAparell,
                pk=request.POST.get("assignment_comp_aparell_id"),
                competicio=competicio,
                actiu=True,
            )
            assignment_formset, selected_app_context = _permission_formset(
                PermissionFS,
                request,
                competicio,
                selected_app,
                bind=True,
            )
            if assignment_formset.is_valid():
                try:
                    permissions = _build_permissions_from_formset(
                        assignment_formset,
                        selected_app_context["schema_by_code"],
                        selected_app,
                        team_context_mode=selected_app_context["team_context_mode"],
                    )
                    phase = None
                    raw_phase_id = request.POST.get("fase_id")
                    if raw_phase_id not in (None, "", "0"):
                        phase = get_object_or_404(
                            CompeticioAparellFase,
                            pk=raw_phase_id,
                            competicio=competicio,
                            comp_aparell=selected_app,
                        )
                    try:
                        ordre = int(request.POST.get("ordre") or 1)
                    except (TypeError, ValueError):
                        ordre = 1
                    ordre = max(1, ordre)
                    while JudgePortalAssignment.objects.filter(judge_token=token, ordre=ordre).exists():
                        ordre += 1
                    JudgePortalAssignment.objects.create(
                        judge_token=token,
                        competicio=competicio,
                        comp_aparell=selected_app,
                        fase=phase,
                        label=str(request.POST.get("assignment_label") or "").strip(),
                        ordre=ordre,
                        permissions=permissions,
                        is_active=True,
                    )
                    messages.success(request, "Assignacio afegida al QR.")
                    return redirect(_qr_admin_url(competicio, token))
                except ValueError as exc:
                    messages.error(request, str(exc))
            else:
                messages.error(request, "Revisa els errors de permisos.")

        elif action == "save_item_labels":
            raw_app_id = request.POST.get("item_labels_comp_aparell_id") or request.POST.get("comp_aparell_id")
            item_comp_aparell = selected_app
            if raw_app_id not in (None, ""):
                item_comp_aparell = get_object_or_404(
                    CompeticioAparell,
                    pk=raw_app_id,
                    competicio=competicio,
                    actiu=True,
                )
            if item_comp_aparell is None:
                messages.error(request, "No hi ha cap aparell seleccionat.")
                return redirect(_qr_admin_url(competicio, selected_token))
            item_context = _schema_context_for_app(competicio, item_comp_aparell)
            field_code = str(request.POST.get("field_code") or "").strip()
            field = item_context["schema_by_code"].get(field_code)
            if not field:
                messages.error(request, "El camp seleccionat no existeix al schema.")
                return redirect(_qr_admin_url(competicio, selected_token))
            if str(field.get("type") or "number").strip().lower() != "matrix":
                messages.error(request, "Nomes es poden configurar noms d'items per camps matrix.")
                return redirect(_qr_admin_url(competicio, selected_token))
            try:
                raw_labels = json.loads(request.POST.get("item_labels_json") or "[]")
            except (TypeError, ValueError):
                messages.error(request, "El format dels noms d'items no es valid.")
                return redirect(_qr_admin_url(competicio, selected_token))
            if not isinstance(raw_labels, list):
                messages.error(request, "Els noms d'items han de ser una llista.")
                return redirect(_qr_admin_url(competicio, selected_token))
            max_items = _field_items_count(field)
            if len(raw_labels) > max_items:
                messages.error(request, f"No es poden desar mes de {max_items} noms d'items.")
                return redirect(_qr_admin_url(competicio, selected_token))
            clean_labels = []
            for idx in range(max_items):
                raw_label = raw_labels[idx] if idx < len(raw_labels) else ""
                clean_labels.append("" if raw_label in (None, "") else str(raw_label).strip())
            _save_comp_aparell_item_labels(item_comp_aparell, field_code, clean_labels)
            messages.success(request, "Noms d'items desats.")
            return redirect(_qr_admin_url(competicio, selected_token))

    selected_assignments = []
    if selected_token:
        assignments = list(selected_token.portal_assignments.all())
        selected_assignments = _assignment_summary_rows(assignments)
        selected_token.permission_summaries = _permission_summary_rows(selected_token.permissions)

    return render(
        request,
        "judge/qr_admin.html",
        {
            "competicio": competicio,
            "comp_aparells": comp_aparells,
            "base_comp_aparell": base_comp_aparell,
            "assignment_comp_aparell": selected_app,
            "selected_app": selected_app,
            "selected_token": selected_token,
            "selected_public_token": selected_public_token,
            "selected_assignments": selected_assignments,
            "token_rows": _token_rows(
                competicio,
                can_manage_public_live=can_manage_public_live,
                selected_token=selected_token,
                selected_public_token=selected_public_token,
            ),
            "create_form": create_form,
            "assignment_formset": assignment_formset,
            "app_catalog": _app_catalog_for_template(competicio, comp_aparells),
            "phase_choices": selected_app_context["phase_choices"],
            "schema_field_catalog": selected_app_context["field_catalog"],
            "max_permissions": MAX_TOKEN_PERMISSIONS,
            "can_manage_public_live": can_manage_public_live,
        },
    )


__all__ = ["qr_admin_home"]
