import copy
import json
import logging

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.generic import UpdateView

from ...forms import ScoringSchemaForm
from ...models import Competicio
from ...models.competicio import Aparell, CompeticioAparell
from ...models.scoring import ScoringSchema
from ...scoring_engine import ScoringEngine, ScoringError
from ...services.scoring_subjects import subject_entry_model
from ...services.team_scoring import (
    is_team_context_app,
    logical_team_inputs_to_runtime_inputs,
    runtime_inputs_to_logical_team_inputs,
    runtime_schema_for_comp_aparell,
)
from ...services.team_subject_contract import build_team_subject_registry, runtime_schema_for_team_subjects
from .helpers import (
    _allowed_input_codes_for_schema,
    _logical_team_input_codes,
    _merge_inputs_preserving_orphans,
    _split_inputs_by_allowed_codes,
)


logger = logging.getLogger(__name__)


def _recalculate_scores_for_comp_aparell(
    competicio,
    comp_aparell,
    chunk_size: int = 200,
    *,
    schema_override: dict | None = None,
    apply_changes: bool = True,
) -> dict:
    """
    Recalculate all ScoreEntry rows for one competition + comp_aparell using the current
    global schema attached to the Aparell.
    """
    entry_model = subject_entry_model(comp_aparell)
    qs = (
        entry_model.objects
        .filter(competicio=competicio, comp_aparell=comp_aparell)
        .order_by("id")
    )
    if is_team_context_app(comp_aparell):
        qs = qs.select_related("team_subject")
    summary = {
        "total": qs.count(),
        "updated": 0,
        "failed": 0,
        "errors_preview": [],
    }

    ss, _ = ScoringSchema.objects.get_or_create(aparell=comp_aparell.aparell, defaults={"schema": {}})
    base_schema = copy.deepcopy(schema_override) if isinstance(schema_override, dict) else (ss.schema or {})
    is_team_app = is_team_context_app(comp_aparell)
    pending_updates = []
    if not is_team_app:
        try:
            engine = ScoringEngine(runtime_schema_for_comp_aparell(base_schema, comp_aparell))
        except Exception as exc:
            summary["engine_error"] = str(exc)
            logger.exception(
                "Schema recalc init failed for competicio=%s comp_aparell=%s: %s",
                getattr(competicio, "id", None),
                getattr(comp_aparell, "id", None),
                exc,
            )
            return summary
        allowed_inputs = _allowed_input_codes_for_schema(base_schema, comp_aparell)
    else:
        engine = None
        allowed_inputs = _logical_team_input_codes(base_schema)

    for entry in qs.iterator(chunk_size=chunk_size):
        try:
            raw_inputs = entry.inputs if isinstance(entry.inputs, dict) else {}
            known_inputs, orphan_inputs = _split_inputs_by_allowed_codes(raw_inputs, allowed_inputs)
            if is_team_app:
                team_subject = getattr(entry, "team_subject", None)
                member_count = len(getattr(team_subject, "member_ids", []) or []) if team_subject is not None else 0
                runtime_schema = runtime_schema_for_comp_aparell(base_schema, comp_aparell, member_count=member_count)
                runtime_inputs = logical_team_inputs_to_runtime_inputs(known_inputs, team_subject, base_schema)
                result = ScoringEngine(runtime_schema).compute(runtime_inputs)
                logical_inputs = runtime_inputs_to_logical_team_inputs(result.inputs, team_subject, base_schema)
                entry_inputs = _merge_inputs_preserving_orphans(logical_inputs, orphan_inputs)
            else:
                result = engine.compute(known_inputs)
                entry_inputs = _merge_inputs_preserving_orphans(result.inputs, orphan_inputs)
            pending_updates.append(
                {
                    "entry": entry,
                    "inputs": entry_inputs,
                    "outputs": result.outputs,
                    "total": result.total,
                }
            )
            summary["updated"] += 1
        except ScoringError as exc:
            summary["failed"] += 1
            if len(summary["errors_preview"]) < 5:
                summary["errors_preview"].append(f"{entry.id}: {exc}")
            logger.warning(
                "Schema recalc failed for ScoreEntry id=%s (domain): %s",
                entry.id,
                exc,
            )
        except Exception as exc:
            summary["failed"] += 1
            if len(summary["errors_preview"]) < 5:
                summary["errors_preview"].append(f"{entry.id}: error inesperat")
            logger.exception(
                "Schema recalc failed for ScoreEntry id=%s (unexpected): %s",
                entry.id,
                exc,
            )

    if apply_changes and summary["failed"] == 0:
        with transaction.atomic():
            for item in pending_updates:
                entry = item["entry"]
                entry.inputs = item["inputs"]
                entry.outputs = item["outputs"]
                entry.total = item["total"]
                entry.save(update_fields=["inputs", "outputs", "total", "updated_at"])

    summary["planned_updates"] = pending_updates

    logger.info(
        "Schema recalc summary competicio=%s comp_aparell=%s total=%s updated=%s failed=%s",
        getattr(competicio, "id", None),
        getattr(comp_aparell, "id", None),
        summary["total"],
        summary["updated"],
        summary["failed"],
    )
    return summary


class ScoringSchemaUpdate(UpdateView):
    model = ScoringSchema
    form_class = ScoringSchemaForm
    template_name = "competicio/scoring_schema_builder.html"

    def dispatch(self, request, *args, **kwargs):
        # per poder tornar on toca
        self.next_url = request.GET.get("next")

        self.competicio = None
        self.comp_aparell = None
        self.aparell = None

        # MODE VELL (ve de: competicio/<pk>/aparell/<ap_id>/schema/)
        if "ap_id" in kwargs:
            self.competicio = get_object_or_404(Competicio, pk=kwargs["pk"])
            self.comp_aparell = get_object_or_404(
                CompeticioAparell,
                pk=kwargs["ap_id"],
                competicio=self.competicio,
            )
            self.aparell = self.comp_aparell.aparell

        # MODE NOU (ve de: trampoli/aparells/<pk>/puntuacio/)
        else:
            self.aparell = get_object_or_404(Aparell, pk=kwargs["pk"])

        if not self._can_manage_aparell(self.aparell):
            raise PermissionDenied("No tens permisos per editar aquest aparell.")

        return super().dispatch(request, *args, **kwargs)

    def _can_manage_aparell(self, aparell: Aparell) -> bool:
        if self.request.user.is_superuser or self.request.user.groups.filter(name="platform_admin").exists():
            return True
        return aparell.created_by_id == self.request.user.id

    def get_object(self):
        # si estem en mode competició (competicio/<pk>/aparell/<ap_id>/schema/)
        if self.comp_aparell:
            obj, _ = ScoringSchema.objects.get_or_create(
                aparell=self.comp_aparell.aparell,
                defaults={"schema": {}},
            )
            return obj

        # si estem en mode global (trampoli/aparells/<pk>/puntuacio/)
        obj, _ = ScoringSchema.objects.get_or_create(
            aparell=self.aparell,
            defaults={"schema": {}},
        )
        return obj

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["comp_aparell"] = self.comp_aparell
        return kwargs

    def _saved_schema_payload(self):
        return self.object.schema if isinstance(getattr(self.object, "schema", None), dict) else {}

    def _schema_draft_storage_key(self):
        mode = "competition" if self.comp_aparell else "global"
        parts = [
            "scoring-schema-builder",
            mode,
            f"aparell:{getattr(self.aparell, 'id', 'unknown')}",
        ]
        if self.comp_aparell:
            parts.append(f"comp-aparell:{self.comp_aparell.id}")
        parts.append(self.request.path)
        return "::".join(str(part) for part in parts if part is not None)

    def _schema_bootstrap_payload(self):
        base = getattr(self, "_schema_bootstrap_payload_override", None)
        if isinstance(base, dict):
            payload = dict(base)
        else:
            saved_schema = self._saved_schema_payload()
            payload = {
                "schema_initial": saved_schema,
                "schema_saved": saved_schema,
                "schema_initial_source": "saved",
                "schema_raw_invalid_json": "",
            }
        payload["schema_draft_storage_key"] = self._schema_draft_storage_key()
        return payload

    def _build_invalid_schema_bootstrap(self, form):
        saved_schema = self._saved_schema_payload()
        raw_schema = ""
        if form is not None and hasattr(form, "get_raw_schema_json"):
            raw_schema = str(form.get_raw_schema_json() or "")
        if not raw_schema and form is not None:
            raw_schema = str((form.data.get("schema_json") if hasattr(form, "data") else "") or "")
        raw_schema = raw_schema.strip()

        bootstrap = {
            "schema_initial": saved_schema,
            "schema_saved": saved_schema,
            "schema_initial_source": "saved",
            "schema_raw_invalid_json": "",
        }
        if not raw_schema:
            return bootstrap

        try:
            parsed = json.loads(raw_schema)
        except Exception:
            bootstrap["schema_initial_source"] = "raw_invalid_json"
            bootstrap["schema_raw_invalid_json"] = raw_schema
            return bootstrap

        if isinstance(parsed, dict):
            bootstrap["schema_initial"] = parsed
            bootstrap["schema_initial_source"] = "posted_invalid"
            return bootstrap

        bootstrap["schema_initial_source"] = "raw_invalid_json"
        bootstrap["schema_raw_invalid_json"] = raw_schema
        return bootstrap

    def form_invalid(self, form):
        self._schema_bootstrap_payload_override = self._build_invalid_schema_bootstrap(form)
        return self.render_to_response(self.get_context_data(form=form))

    def form_valid(self, form):
        schema_json = form.cleaned_data.get("schema_json")
        schema_changed = False

        if schema_json is not None:
            previous_schema = self.object.schema if isinstance(self.object.schema, dict) else {}
            schema_changed = previous_schema != schema_json

        # Auto recalc only in competition flow and only if schema really changed.
        if schema_changed and self.competicio and self.comp_aparell:
            summary = _recalculate_scores_for_comp_aparell(
                self.competicio,
                self.comp_aparell,
                schema_override=schema_json,
                apply_changes=False,
            )
            engine_error = summary.get("engine_error")

            if engine_error:
                messages.error(
                    self.request,
                    f"Schema no desat: validacio del recalc ha fallat ({engine_error}).",
                )
                return redirect(self.get_success_url())
            elif summary["failed"] > 0:
                preview = "; ".join(summary["errors_preview"])
                extra = f" Errors: {preview}" if preview else ""
                messages.error(
                    self.request,
                    f"Schema no desat. El recalc ha fallat per {summary['failed']}/{summary['total']} notes.{extra}",
                )
                return redirect(self.get_success_url())
            else:
                with transaction.atomic():
                    self.object.schema = schema_json
                    self.object.save()
                    for item in summary.get("planned_updates", []):
                        entry = item["entry"]
                        entry.inputs = item["inputs"]
                        entry.outputs = item["outputs"]
                        entry.total = item["total"]
                        entry.save(update_fields=["inputs", "outputs", "total", "updated_at"])

        elif schema_changed:
            self.object.schema = schema_json
            self.object.save()

        if schema_changed:
            messages.success(
                self.request,
                (
                    f"Schema desat. Recalculades {summary['updated']}/{summary['total']} notes."
                    if self.competicio and self.comp_aparell
                    else "Schema desat."
                ),
            )

        return redirect(self.get_success_url())

    def get_success_url(self):
        # 1) si venies d'algun lloc, torna-hi
        if self.next_url:
            return self.next_url

        # 2) si estàs en una competició, torna a notes-v2
        if self.competicio:
            return reverse("scoring_notes_home", kwargs={"pk": self.competicio.id})

        # 3) si és global, torna a editar l'aparell (o a la llista)
        return reverse("aparell_update", kwargs={"pk": self.aparell.id})
    
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        schema_bootstrap = self._schema_bootstrap_payload()
        ctx["schema_bootstrap"] = schema_bootstrap
        ctx["schema_initial"] = schema_bootstrap.get("schema_initial") or {}
        ctx["schema_initial_source"] = schema_bootstrap.get("schema_initial_source") or "saved"
        ctx["schema_raw_invalid_json"] = schema_bootstrap.get("schema_raw_invalid_json") or ""
        ctx["schema_draft_storage_key"] = schema_bootstrap.get("schema_draft_storage_key") or ""
        ctx["aparell"] = self.aparell

        next_url = self.request.GET.get("next") or self.next_url or self.get_success_url()
        if next_url:
            ctx["next"] = next_url

        # només si vens del flux antic
        if self.competicio:
            ctx["competicio"] = self.competicio
        if self.comp_aparell:
            ctx["comp_aparell"] = self.comp_aparell
            ctx["schema_builder_config"] = {
                "competition_unit": getattr(self.comp_aparell.aparell, "competition_unit", "individual"),
                "is_team_unit": bool(self.comp_aparell.is_team_competition_unit),
            }
        else:
            ctx["schema_builder_config"] = {
                "competition_unit": getattr(self.aparell, "competition_unit", "individual"),
                "is_team_unit": bool(getattr(self.aparell, "is_team_competition_unit", False)),
            }

        return ctx
