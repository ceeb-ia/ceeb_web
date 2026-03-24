# views_scoring.py
import json
import logging
from collections import defaultdict
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_GET
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.db.models import Count, Exists, OuterRef
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView, UpdateView
from django.utils import timezone
from .models import Competicio, Inscripcio, InscripcioMedia
from .models_trampoli import Aparell, CompeticioAparell, InscripcioAparellExclusio
from .models_rotacions import RotacioAssignacio, RotacioFranja
from .models import Equip
from .models_scoring import ScoringSchema, ScoreEntry, ScoreEntryVideo, TeamScoreEntry, TeamScoreEntryVideo
from .forms import ScoringSchemaForm
from .scoring_engine import ScoringEngine, ScoringError
from .services.scoring_subjects import (
    get_or_create_subject_entry_locked,
    inscripcio_exclosa_en_aparell,
    resolve_scoring_subject,
    score_store_key,
    serialize_subject_payload,
    subject_entry_model,
)
from .services.team_scoring import (
    build_team_subjects_for_comp_aparell,
    eligible_team_ids_for_comp_aparell,
    is_team_context_app,
    runtime_schema_for_comp_aparell,
)
from .services.competition_groups import (
    get_group_maps,
    get_inscripcio_competition_order,
    get_inscripcio_group_display_num,
    group_label,
    show_out_of_program_in_competition_views,
)
from .services.rotacions_ordering import (
    ORDER_MODE_MAINTAIN,
    assignacio_grups,
    build_group_rotation_step_map,
    effective_rotate_steps,
    get_rotacions_order_modes,
    order_pairs_for_mode,
    unique_ordered,
)


logger = logging.getLogger(__name__)


def _get_or_create_scoreentry_locked(*, competicio, inscripcio, exercici, comp_aparell, defaults=None):
    """
    Get-or-create with row lock to prevent lost updates under concurrent writes.
    Must be called inside transaction.atomic().
    """
    lookup = {
        "competicio": competicio,
        "inscripcio": inscripcio,
        "exercici": exercici,
        "comp_aparell": comp_aparell,
    }
    defaults = defaults or {}

    entry = (
        ScoreEntry.objects
        .select_for_update()
        .filter(**lookup)
        .first()
    )
    if entry is not None:
        return entry, False

    try:
        entry = ScoreEntry.objects.create(**lookup, **defaults)
        return entry, True
    except IntegrityError:
        # Another concurrent request created the row first.
        entry = (
            ScoreEntry.objects
            .select_for_update()
            .get(**lookup)
        )
        return entry, False


def _get_or_create_teamscoreentry_locked(*, competicio, equip, exercici, comp_aparell, defaults=None):
    lookup = {
        "competicio": competicio,
        "equip": equip,
        "exercici": exercici,
        "comp_aparell": comp_aparell,
    }
    defaults = defaults or {}
    entry = (
        TeamScoreEntry.objects
        .select_for_update()
        .filter(**lookup)
        .first()
    )
    if entry is not None:
        return entry, False

    try:
        entry = TeamScoreEntry.objects.create(**lookup, **defaults)
        return entry, True
    except IntegrityError:
        entry = (
            TeamScoreEntry.objects
            .select_for_update()
            .get(**lookup)
        )
        return entry, False


def _allowed_input_codes_for_schema(schema: dict, comp_aparell=None) -> set:
    runtime_schema = runtime_schema_for_comp_aparell(schema or {}, comp_aparell)
    allowed = set()
    for f in (runtime_schema.get("fields") or []):
        if isinstance(f, dict) and f.get("code"):
            allowed.add(f["code"])
            allowed.add(f"__crash__{f['code']}")
    return allowed


def _recalculate_scores_for_comp_aparell(competicio, comp_aparell, chunk_size: int = 200) -> dict:
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
    summary = {
        "total": qs.count(),
        "updated": 0,
        "failed": 0,
        "errors_preview": [],
    }

    ss, _ = ScoringSchema.objects.get_or_create(
        aparell=comp_aparell.aparell,
        defaults={"schema": {}},
    )

    try:
        engine = ScoringEngine(runtime_schema_for_comp_aparell(ss.schema or {}, comp_aparell))
    except Exception as exc:
        summary["engine_error"] = str(exc)
        logger.exception(
            "Schema recalc init failed for competicio=%s comp_aparell=%s: %s",
            getattr(competicio, "id", None),
            getattr(comp_aparell, "id", None),
            exc,
        )
        return summary

    for entry in qs.iterator(chunk_size=chunk_size):
        raw_inputs = entry.inputs if isinstance(entry.inputs, dict) else {}
        try:
            result = engine.compute(raw_inputs)
            entry.inputs = result.inputs
            entry.outputs = result.outputs
            entry.total = result.total
            entry.save(update_fields=["inputs", "outputs", "total", "updated_at"])
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

    logger.info(
        "Schema recalc summary competicio=%s comp_aparell=%s total=%s updated=%s failed=%s",
        getattr(competicio, "id", None),
        getattr(comp_aparell, "id", None),
        summary["total"],
        summary["updated"],
        summary["failed"],
    )
    return summary


def _safe_file_url(file_field):
    if not file_field:
        return ""
    try:
        return file_field.url
    except Exception:
        return ""


def _serialize_inscripcio_media_for_playback(item: InscripcioMedia) -> dict:
    return {
        "id": item.id,
        "tipus": item.tipus,
        "is_primary": bool(item.is_primary),
        "original_filename": item.original_filename or "",
        "mime_type": item.mime_type or "",
        "url": _safe_file_url(item.fitxer),
    }


def _split_media_for_playback(items: list) -> dict:
    grouped = {
        InscripcioMedia.Tipus.AUDIO: [],
        InscripcioMedia.Tipus.VIDEO: [],
        InscripcioMedia.Tipus.IMAGE: [],
        InscripcioMedia.Tipus.OTHER: [],
    }
    for item in items:
        tipus = str(item.get("tipus") or "")
        if tipus not in grouped:
            tipus = InscripcioMedia.Tipus.OTHER
        grouped[tipus].append(item)

    def _pick_primary_and_others(arr):
        primary = next((x for x in arr if x.get("is_primary")), None)
        if primary is None:
            return None, arr
        others = [x for x in arr if x.get("id") != primary.get("id")]
        return primary, others

    audio_primary, audio_others = _pick_primary_and_others(grouped[InscripcioMedia.Tipus.AUDIO])
    video_primary, video_others = _pick_primary_and_others(grouped[InscripcioMedia.Tipus.VIDEO])
    image_primary, image_others = _pick_primary_and_others(grouped[InscripcioMedia.Tipus.IMAGE])

    return {
        "audio_primary": audio_primary,
        "audio_others": audio_others,
        "video_primary": video_primary,
        "video_others": video_others,
        "image_primary": image_primary,
        "image_others": image_others,
        "other_files": grouped[InscripcioMedia.Tipus.OTHER],
    }


def _serialize_judge_video_for_playback(video_obj):
    if not video_obj or not video_obj.video_file:
        return None
    url = _safe_file_url(video_obj.video_file)
    if not url:
        return None
    return {
        "id": video_obj.id,
        "original_filename": video_obj.original_filename or "",
        "mime_type": video_obj.mime_type or "",
        "url": url,
        "status": video_obj.status,
    }


def _parse_positive_int(raw_value):
    try:
        n = int(raw_value)
    except Exception:
        return None
    return n if n > 0 else None


def _eligible_team_subject_map(competicio, comp_aparell):
    if not is_team_context_app(comp_aparell):
        return {}
    out = {}
    subjects, _issues = build_team_subjects_for_comp_aparell(competicio, comp_aparell)
    for subject in subjects:
        if int(comp_aparell.id) not in (subject.get("allowed_app_ids") or []):
            continue
        out[int(subject["subject_id"])] = subject
    return out


class ScoringNotesHome(TemplateView):
    """
    Pantalla de notes dinàmica basada en schema.
    Convivència amb la pantalla trampolí actual: és una home nova.
    """
    template_name = "competicio/scoring_notes_home.html"

    def get(self, request, *args, **kwargs):
        self.competicio = get_object_or_404(Competicio, pk=kwargs["pk"])
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        competicio = self.competicio
        franges = list(RotacioFranja.objects.filter(competicio=competicio).order_by("ordre", "id"))
        franja_modes = get_rotacions_order_modes(competicio)
        group_maps = get_group_maps(competicio)
        groups_by_id = group_maps["by_id"]
        group_labels_map = {"0": "Sense grup"}
        for group in group_maps["groups"]:
            group_labels_map[str(group.id)] = group_label(group)

        franja_selected_id = None
        fr_raw = self.request.GET.get("franja")
        if fr_raw not in (None, ""):
            try:
                fr_int = int(fr_raw)
            except Exception:
                fr_int = None
            if fr_int and any(f.id == fr_int for f in franges):
                franja_selected_id = fr_int

        ins = (
            Inscripcio.objects
            .filter(competicio=competicio)
            .select_related("grup_competicio")
            .order_by("grup_competicio__display_num", "ordre_competicio", "ordre_sortida", "id")
        )

        # Agrupació (igual que ja fas servir)
        from collections import defaultdict
        grouped = defaultdict(list)
        for r in ins:
            grouped[r.grup_competicio_id if r.grup_competicio_id is not None else 0].append(r)

        group_first_slot = {}
        assigns_for_order = (
            RotacioAssignacio.objects
            .filter(competicio=competicio)
            .select_related("franja")
            .prefetch_related("grup_links__grup")
            .order_by("franja__ordre", "franja_id", "estacio__ordre", "id")
        )
        for a in assigns_for_order:
            franja = getattr(a, "franja", None)
            franja_order = getattr(franja, "ordre", 10**9)
            fid = getattr(a, "franja_id", None) or 0
            for g in assignacio_grups(a):
                if g not in group_first_slot:
                    group_first_slot[g] = (franja_order, fid)

        numeric_group_keys = sorted([k for k in grouped.keys() if k != 0])
        competing_group_keys = [g for g in numeric_group_keys if g in group_first_slot]
        remaining_group_keys = [g for g in numeric_group_keys if g not in group_first_slot]
        competing_group_keys.sort(key=lambda g: (group_first_slot[g][0], group_first_slot[g][1], g))

        program_group_keys = list(competing_group_keys)
        out_of_program_group_keys = [g for g in remaining_group_keys if g != 0]
        always_visible_group_keys = list(program_group_keys)
        if 0 in grouped:
            always_visible_group_keys.append(0)

        programmed_groups = [(g, grouped[g]) for g in always_visible_group_keys]
        out_of_program_groups = [(g, grouped[g]) for g in out_of_program_group_keys]
        show_out_of_program_groups = show_out_of_program_in_competition_views(competicio)
        visible_groups = programmed_groups + (out_of_program_groups if show_out_of_program_groups else [])


        # Aparells de la competició
        aparells_cfg = (
            CompeticioAparell.objects
            .filter(competicio=competicio, actiu=True)
            .select_related("aparell")
            .order_by("ordre", "id")
        )
        aparells_cfg = list(aparells_cfg)
        active_app_ids = [ca.id for ca in aparells_cfg]
        team_app_ids = {ca.id for ca in aparells_cfg if is_team_context_app(ca)}
        excluded_by_ins = defaultdict(set)
        if active_app_ids:
            excl_pairs = (
                InscripcioAparellExclusio.objects
                .filter(
                    inscripcio__in=ins,
                    comp_aparell_id__in=active_app_ids,
                )
                .values_list("inscripcio_id", "comp_aparell_id")
            )
            for ins_id, app_id in excl_pairs:
                excluded_by_ins[ins_id].add(app_id)
        
        def clamp_ex(n):
            try:
                n = int(n or 1)
            except Exception:
                n = 1
            return max(1, min(4, n))


        # Exercicis
        exercicis_by_aparell = {}
        max_ex = 1
        for ca in aparells_cfg:
            n = clamp_ex(getattr(ca, "nombre_exercicis", 1))
            exercicis_by_aparell[str(ca.id)] = list(range(1, n + 1))
            max_ex = max(max_ex, n)

        exercicis = list(range(1, max_ex + 1))
        
        # ─────────────────────────────
        # SCHEMAS (dict simple)
        # ─────────────────────────────
        schemas = {}
        for ca in aparells_cfg:
            ss, _ = ScoringSchema.objects.get_or_create(
                aparell=ca.aparell,
                defaults={"schema": {}},
            )
            schemas[str(ca.id)] = runtime_schema_for_comp_aparell(ss.schema or {}, ca)

        # ─────────────────────────────
        # SCORES (dict clau -> dades)
        # ─────────────────────────────
        scores_qs = ScoreEntry.objects.filter(
            competicio=competicio,
            inscripcio__in=ins,
            exercici__in=exercicis,
            comp_aparell__in=[ca for ca in aparells_cfg if not is_team_context_app(ca)],
        )
        scores_qs = scores_qs.annotate(
            _excluded=Exists(
                InscripcioAparellExclusio.objects.filter(
                    inscripcio_id=OuterRef("inscripcio_id"),
                    comp_aparell_id=OuterRef("comp_aparell_id"),
                )
            )
        ).filter(_excluded=False)

        scores = {}
        for s in scores_qs:
            key = score_store_key("inscripcio", s.inscripcio_id, s.exercici, s.comp_aparell_id)
            scores[key] = {
                "inputs": s.inputs or {},
                "outputs": s.outputs or {},
                "total": float(s.total),
            }

        team_subjects = []
        team_issues_by_app = {}
        eligible_team_ids_by_app = {}
        for ca in aparells_cfg:
            if not is_team_context_app(ca):
                continue
            app_subjects, issues = build_team_subjects_for_comp_aparell(competicio, ca)
            team_subjects.extend(app_subjects)
            team_issues_by_app[str(ca.id)] = issues
            eligible_team_ids_by_app[int(ca.id)] = [
                int(subject["subject_id"])
                for subject in app_subjects
                if int(ca.id) in (subject.get("allowed_app_ids") or [])
            ]

        team_score_app_ids = [app_id for app_id, ids in eligible_team_ids_by_app.items() if ids]
        team_score_team_ids = [team_id for ids in eligible_team_ids_by_app.values() for team_id in ids]
        if team_score_app_ids and team_score_team_ids:
            team_scores_qs = TeamScoreEntry.objects.filter(
                competicio=competicio,
                comp_aparell_id__in=team_score_app_ids,
                equip_id__in=team_score_team_ids,
                exercici__in=exercicis,
            )
            for s in team_scores_qs:
                key = score_store_key("equip", s.equip_id, s.exercici, s.comp_aparell_id)
                scores[key] = {
                    "inputs": s.inputs or {},
                    "outputs": s.outputs or {},
                    "total": float(s.total),
                }

        # ─────────────────────────────
        # INSCRIPCIONS (llista plana per JS)
        # ─────────────────────────────
        # inscripcions: llista plana per al JS
        inscripcions = []
        for g, rows in visible_groups:
            for r in rows:
                meta_parts = []
                if getattr(r, "entitat", None):
                    meta_parts.append(str(r.entitat))
                if getattr(r, "categoria", None):
                    meta_parts.append(str(r.categoria))
                if getattr(r, "subcategoria", None):
                    meta_parts.append(str(r.subcategoria))
                allowed_app_ids = [
                    app_id for app_id in active_app_ids
                    if app_id not in excluded_by_ins.get(r.id, set()) and app_id not in team_app_ids
                ]

                inscripcions.append({
                    "id": r.id,
                    "subject_id": r.id,
                    "subject_kind": "inscripcio",
                    "order": get_inscripcio_competition_order(r) or "",
                    "name": getattr(r, "nom_i_cognoms", "") or "",
                    "group": getattr(r, "grup_competicio_id", 0) or 0,
                    "group_display_num": get_inscripcio_group_display_num(r) or "",
                    "allowed_app_ids": allowed_app_ids,
                    "meta": " · ".join(meta_parts) if meta_parts else "",
                })
        inscripcions.extend(team_subjects)


        # ─────────────────────────────
        # CONTEXT FINAL
        # ─────────────────────────────
        inscripcio_ids = [int(x["subject_id"]) for x in inscripcions if x.get("subject_kind") == "inscripcio"]
        media_counts_by_inscripcio = {
            str(ins_id): {"audio": 0, "video": 0}
            for ins_id in inscripcio_ids
        }
        if inscripcio_ids:
            media_counts_rows = (
                InscripcioMedia.objects
                .filter(
                    competicio=competicio,
                    inscripcio_id__in=inscripcio_ids,
                    tipus__in=[InscripcioMedia.Tipus.AUDIO, InscripcioMedia.Tipus.VIDEO],
                )
                .values("inscripcio_id", "tipus")
                .annotate(total=Count("id"))
            )
            for row in media_counts_rows:
                ins_id = str(row.get("inscripcio_id") or "")
                bucket = media_counts_by_inscripcio.setdefault(ins_id, {"audio": 0, "video": 0})
                tipus = str(row.get("tipus") or "")
                if tipus in ("audio", "video"):
                    bucket[tipus] = int(row.get("total") or 0)

        judge_video_presence_by_key = {}
        if inscripcio_ids and active_app_ids and exercicis:
            judge_video_rows = (
                ScoreEntryVideo.objects
                .filter(
                    score_entry__competicio=competicio,
                    score_entry__inscripcio_id__in=inscripcio_ids,
                    score_entry__comp_aparell_id__in=active_app_ids,
                    score_entry__exercici__in=exercicis,
                )
                .exclude(video_file="")
                .values_list(
                    "score_entry__inscripcio_id",
                    "score_entry__exercici",
                    "score_entry__comp_aparell_id",
                )
            )
            for ins_id, exercici_id, app_id in judge_video_rows:
                judge_video_presence_by_key[score_store_key("inscripcio", ins_id, exercici_id, app_id)] = 1
        if team_score_team_ids and team_score_app_ids and exercicis:
            team_judge_video_rows = (
                TeamScoreEntryVideo.objects
                .filter(
                    team_score_entry__competicio=competicio,
                    team_score_entry__equip_id__in=team_score_team_ids,
                    team_score_entry__comp_aparell_id__in=team_score_app_ids,
                    team_score_entry__exercici__in=exercicis,
                )
                .exclude(video_file="")
                .values_list(
                    "team_score_entry__equip_id",
                    "team_score_entry__exercici",
                    "team_score_entry__comp_aparell_id",
                )
            )
            for equip_id, exercici_id, app_id in team_judge_video_rows:
                judge_video_presence_by_key[score_store_key("equip", equip_id, exercici_id, app_id)] = 1

        rotation_rank_map = {}
        rotation_groups_by_app = {}
        if franja_selected_id:
            all_assigns = list(
                RotacioAssignacio.objects
                .filter(
                    competicio=competicio,
                    estacio__tipus="aparell",
                    estacio__comp_aparell__isnull=False,
                )
                .select_related("franja", "estacio")
                .prefetch_related("grup_links__grup")
                .order_by("franja__ordre", "franja_id", "estacio__ordre", "id")
            )
            rotation_step_map = build_group_rotation_step_map(all_assigns, franja_modes)
            assigns = [a for a in all_assigns if a.franja_id == franja_selected_id]
            app_groups_map = {}
            for a in assigns:
                app_id = a.estacio.comp_aparell_id
                groups_for_cell = assignacio_grups(a)
                prev = app_groups_map.get(app_id, [])
                app_groups_map[app_id] = unique_ordered(list(prev) + list(groups_for_cell))

            mode_for_franja = franja_modes.get(str(franja_selected_id), ORDER_MODE_MAINTAIN)

            for app_id in active_app_ids:
                app_key = str(app_id)
                app_groups = app_groups_map.get(app_id, [])
                rotation_groups_by_app[app_key] = app_groups
                rank = 1
                subject_rows_by_group = {}
                if app_id in team_app_ids:
                    for subject in team_subjects:
                        key = 0 if subject.get("group") in (None, 0) else int(subject.get("group") or 0)
                        if key not in app_groups:
                            continue
                        if app_id in (subject.get("allowed_app_ids") or []) or subject.get("invalid_reasons"):
                            subject_rows_by_group.setdefault(key, []).append(subject)
                else:
                    for g, rows in programmed_groups:
                        key = 0 if g in (None, 0) else int(g)
                        subject_rows_by_group[key] = list(rows)
                for g in app_groups:
                    base_pairs = []
                    for r in subject_rows_by_group.get(g, []):
                        if app_id in team_app_ids:
                            base_pairs.append((r["id"], r))
                            continue
                        if app_id in excluded_by_ins.get(r.id, set()):
                            continue
                        base_pairs.append((r.id, r))

                    ordered = order_pairs_for_mode(
                        base_pairs,
                        mode_for_franja,
                        rotate_steps=effective_rotate_steps(
                            mode_for_franja,
                            rotation_step_map.get((g, franja_selected_id), 0),
                        ),
                        seed_prefix=f"notes|{competicio.id}|{franja_selected_id}|{app_id}|{g}",
                    )
                    for subject_id, _r in ordered:
                        key = f"{app_id}|{subject_id}"
                        if key in rotation_rank_map:
                            continue
                        rotation_rank_map[key] = rank
                        rank += 1

        ctx.update({
            "competicio": competicio,
            "groups": programmed_groups,
            "out_of_program_groups": out_of_program_groups if show_out_of_program_groups else [],
            "show_out_of_program_in_competition_views": show_out_of_program_groups,
            "group_labels_map": group_labels_map,
            "aparells_cfg": aparells_cfg,
            "exercicis": exercicis,
            "exercicis_by_aparell": exercicis_by_aparell,
            "franges": franges,
            "franja_selected_id": franja_selected_id,
            "rotation_rank_map": rotation_rank_map,
            "rotation_groups_by_app": rotation_groups_by_app,

            # per json_script
            "schemas": schemas,
            "scores": scores,
            "inscripcions": inscripcions,
            "media_counts_by_inscripcio": media_counts_by_inscripcio,
            "judge_video_presence_by_key": judge_video_presence_by_key,
            "team_issues_by_app": team_issues_by_app,
            "updates_cursor_init": timezone.now().isoformat(),
        })
        return ctx


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

    def form_valid(self, form):
        schema_json = form.cleaned_data.get("schema_json")
        schema_changed = False

        if schema_json is not None:
            previous_schema = self.object.schema if isinstance(self.object.schema, dict) else {}
            schema_changed = previous_schema != schema_json
            self.object.schema = schema_json
            self.object.save()

        # Auto recalc only in competition flow and only if schema really changed.
        if schema_changed and self.competicio and self.comp_aparell:
            summary = _recalculate_scores_for_comp_aparell(self.competicio, self.comp_aparell)
            engine_error = summary.get("engine_error")

            if engine_error:
                messages.error(
                    self.request,
                    f"Schema desat, pero no s'han recalculat notes: {engine_error}",
                )
            elif summary["failed"] > 0:
                preview = "; ".join(summary["errors_preview"])
                extra = f" Errors: {preview}" if preview else ""
                messages.warning(
                    self.request,
                    f"Schema desat. Recalculades {summary['updated']}/{summary['total']} notes"
                    f" ({summary['failed']} fallades).{extra}",
                )
            else:
                messages.success(
                    self.request,
                    f"Schema desat. Recalculades {summary['updated']}/{summary['total']} notes.",
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
        ctx["schema_initial"] = self.object.schema or {}
        ctx["aparell"] = self.aparell

        next_url = self.request.GET.get("next")
        if next_url:
            ctx["next"] = next_url

        # només si vens del flux antic
        if self.competicio:
            ctx["competicio"] = self.competicio
        if self.comp_aparell:
            ctx["comp_aparell"] = self.comp_aparell
            ctx["schema_builder_config"] = {
                "participant_mode": self.comp_aparell.participant_mode,
                "team_scoring_mode": self.comp_aparell.team_scoring_mode,
                "expected_team_size": self.comp_aparell.expected_team_size,
                "team_context_name": getattr(self.comp_aparell.team_context, "nom", ""),
                "team_context_code": getattr(self.comp_aparell.team_context, "code", ""),
            }
        else:
            ctx["schema_builder_config"] = {
                "participant_mode": "individual",
                "team_scoring_mode": "",
                "expected_team_size": None,
                "team_context_name": "",
                "team_context_code": "",
            }

        return ctx

@require_POST
@transaction.atomic
def scoring_save(request, pk):
    """
    Guarda inputs i calcula outputs per un ScoreEntry.
    Payload:
    {
      "inscripcio_id": 10,
      "exercici": 1,
      "comp_aparell_id": 5,
      "inputs": {...}
    }
    """
    competicio = get_object_or_404(Competicio, pk=pk)

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"ok": False, "error": "JSON invàlid"}, status=400)

    comp_aparell_id = payload.get("comp_aparell_id")
    exercici = int(payload.get("exercici") or 1)
    inputs = payload.get("inputs", {})

    if not comp_aparell_id:
        return JsonResponse({"ok": False, "error": "Falta comp_aparell_id"}, status=400)

    comp_aparell = get_object_or_404(CompeticioAparell, pk=comp_aparell_id, competicio=competicio, actiu=True)
    subject, error_response = resolve_scoring_subject(
        competicio,
        comp_aparell,
        payload,
        eligible_team_ids=eligible_team_ids_for_comp_aparell(competicio, comp_aparell) if is_team_context_app(comp_aparell) else None,
    )
    if error_response is not None:
        return error_response

    ss, _ = ScoringSchema.objects.get_or_create(aparell=comp_aparell.aparell, defaults={"schema": {}})
    schema = runtime_schema_for_comp_aparell(ss.schema or {}, comp_aparell)
    allowed = _allowed_input_codes_for_schema(ss.schema or {}, comp_aparell)

    clean_inputs = {}
    if isinstance(inputs, dict):
        for k, v in inputs.items():
            if k in allowed:
                clean_inputs[k] = v

    try:
        engine = ScoringEngine(schema)
        result = engine.compute(clean_inputs)
    except ScoringError as e:
        return JsonResponse({"ok": False, "error": str(e)}, status=400)
    except Exception:
        return JsonResponse({"ok": False, "error": "Error inesperat calculant."}, status=500)

    max_ex = max(1, min(4, int(getattr(comp_aparell, "nombre_exercicis", 1) or 1)))
    exercici = max(1, min(max_ex, exercici))

    entry, _ = get_or_create_subject_entry_locked(
        competicio=competicio,
        comp_aparell=comp_aparell,
        exercici=exercici,
        subject=subject,
    )
    entry.inputs = result.inputs
    entry.outputs = result.outputs
    entry.total = result.total
    entry.save()

    response = {
        "ok": True,
        "exercici": entry.exercici,
        "comp_aparell_id": comp_aparell.id,
        "outputs": entry.outputs,
        "total": float(entry.total),
    }
    response.update(serialize_subject_payload(subject["subject_kind"], subject["subject_id"]))
    return JsonResponse(response)

    ss, _ = ScoringSchema.objects.get_or_create(aparell=comp_aparell.aparell, defaults={"schema": {}})
    schema = runtime_schema_for_comp_aparell(ss.schema or {}, comp_aparell)
    # --- FILTRA INPUTS DESCONeguts (evita "Nom desconegut: E_j") ---
    allowed = _allowed_input_codes_for_schema(ss.schema or {}, comp_aparell)
    if False:
            # també permet crash keys si les uses (__crash__X)
            allowed.add(f"__crash__{f['code']}")

    clean_inputs = {}
    if isinstance(inputs, dict):
        for k, v in inputs.items():
            if k in allowed:
                clean_inputs[k] = v

    try:
        engine = ScoringEngine(schema)
        result = engine.compute(clean_inputs)
    except ScoringError as e:
        return JsonResponse({"ok": False, "error": str(e)}, status=400)
    except Exception:
        return JsonResponse({"ok": False, "error": "Error inesperat calculant."}, status=500)

    max_ex = max(1, min(4, int(getattr(comp_aparell, "nombre_exercicis", 1) or 1)))
    exercici = int(payload.get("exercici") or 1)
    exercici = max(1, min(max_ex, exercici))

    entry, _ = _get_or_create_scoreentry_locked(
        competicio=competicio,
        inscripcio=ins,
        exercici=exercici,
        comp_aparell=comp_aparell,
    )
    entry.inputs = result.inputs
    entry.outputs = result.outputs
    entry.total = result.total
    entry.save()

    return JsonResponse({
        "ok": True,
        "inscripcio_id": ins.id,
        "exercici": entry.exercici,
        "comp_aparell_id": comp_aparell.id,
        "outputs": entry.outputs,
        "total": float(entry.total),
    })


@require_POST
@transaction.atomic
def scoring_save_partial(request, pk):
    """
    Igual que scoring_save, però:
    - rep inputs_patch (no inputs complet)
    - fa MERGE amb entry.inputs existent
    - recalcula amb ScoringEngine
    Payload:
    {
      "inscripcio_id": 10,
      "exercici": 1,
      "comp_aparell_id": 5,
      "inputs_patch": {...}
    }
    """
    competicio = get_object_or_404(Competicio, pk=pk)

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"ok": False, "error": "JSON invàlid"}, status=400)

    comp_aparell_id = payload.get("comp_aparell_id")
    exercici = int(payload.get("exercici") or 1)
    patch = payload.get("inputs_patch", {})

    if not comp_aparell_id:
        return JsonResponse({"ok": False, "error": "Falta comp_aparell_id"}, status=400)
    if not isinstance(patch, dict):
        return JsonResponse({"ok": False, "error": "inputs_patch ha de ser objecte JSON"}, status=400)

    comp_aparell = get_object_or_404(CompeticioAparell, pk=comp_aparell_id, competicio=competicio, actiu=True)
    subject, error_response = resolve_scoring_subject(
        competicio,
        comp_aparell,
        payload,
        eligible_team_ids=eligible_team_ids_for_comp_aparell(competicio, comp_aparell) if is_team_context_app(comp_aparell) else None,
    )
    if error_response is not None:
        return error_response

    max_ex = max(1, min(4, int(getattr(comp_aparell, "nombre_exercicis", 1) or 1)))
    exercici = max(1, min(max_ex, exercici))

    ss, _ = ScoringSchema.objects.get_or_create(aparell=comp_aparell.aparell, defaults={"schema": {}})
    schema = runtime_schema_for_comp_aparell(ss.schema or {}, comp_aparell)
    allowed = _allowed_input_codes_for_schema(ss.schema or {}, comp_aparell)

    entry, _ = get_or_create_subject_entry_locked(
        competicio=competicio,
        comp_aparell=comp_aparell,
        exercici=exercici,
        subject=subject,
        defaults={"inputs": {}, "outputs": {}, "total": 0},
    )
    current_inputs = entry.inputs if isinstance(entry.inputs, dict) else {}

    merged = dict(current_inputs)
    for k, v in patch.items():
        if k in allowed:
            merged[k] = v

    try:
        engine = ScoringEngine(schema)
        result = engine.compute(merged)
    except ScoringError as e:
        return JsonResponse({"ok": False, "error": str(e)}, status=400)
    except Exception:
        return JsonResponse({"ok": False, "error": "Error inesperat calculant."}, status=500)

    entry.inputs = result.inputs
    entry.outputs = result.outputs
    entry.total = result.total
    entry.save(update_fields=["inputs", "outputs", "total", "updated_at"])

    response = {
        "ok": True,
        "exercici": entry.exercici,
        "comp_aparell_id": comp_aparell.id,
        "inputs": entry.inputs,
        "outputs": entry.outputs,
        "total": float(entry.total),
        "updated_at": entry.updated_at.isoformat(),
    }
    response.update(serialize_subject_payload(subject["subject_kind"], subject["subject_id"]))
    return JsonResponse(response)

    # clamp exercici com ja fas
    max_ex = max(1, min(4, int(getattr(comp_aparell, "nombre_exercicis", 1) or 1)))
    exercici = max(1, min(max_ex, exercici))

    ss, _ = ScoringSchema.objects.get_or_create(aparell=comp_aparell.aparell, defaults={"schema": {}})
    schema = ss.schema or {}

    # allowed keys (igual que scoring_save)
    allowed = _allowed_input_codes_for_schema(ss.schema or {}, comp_aparell)
    for f in (schema.get("fields") or []):
        if isinstance(f, dict) and f.get("code"):
            allowed.add(f["code"])
            allowed.add(f"__crash__{f['code']}")

    # entry existent (o crea)
    entry, _ = _get_or_create_scoreentry_locked(
        competicio=competicio,
        inscripcio=ins,
        exercici=exercici,
        comp_aparell=comp_aparell,
        defaults={"inputs": {}, "outputs": {}, "total": 0},
    )
    current_inputs = entry.inputs if isinstance(entry.inputs, dict) else {}

    # MERGE: només claus permeses
    merged = dict(current_inputs)
    for k, v in patch.items():
        if k in allowed:
            merged[k] = v

    try:
        engine = ScoringEngine(schema)
        result = engine.compute(merged)
    except ScoringError as e:
        return JsonResponse({"ok": False, "error": str(e)}, status=400)
    except Exception:
        return JsonResponse({"ok": False, "error": "Error inesperat calculant."}, status=500)

    entry.inputs = result.inputs
    entry.outputs = result.outputs
    entry.total = result.total
    entry.save(update_fields=["inputs", "outputs", "total", "updated_at"])

    return JsonResponse({
        "ok": True,
        "inscripcio_id": ins.id,
        "exercici": entry.exercici,
        "comp_aparell_id": comp_aparell.id,
        "inputs": entry.inputs,     # útil per refrescar client
        "outputs": entry.outputs,
        "total": float(entry.total),
        "updated_at": entry.updated_at.isoformat(),
    })


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
            .select_related("team_context")
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
        equip = subject["equip"]
        team_subject = eligible_subjects.get(int(equip.id), {})
        judge_video_payload = None
        if exercici:
            score = (
                TeamScoreEntry.objects
                .filter(
                    competicio=competicio,
                    equip=equip,
                    comp_aparell=comp_aparell,
                    exercici=exercici,
                )
                .first()
            )
            if score:
                video_obj = TeamScoreEntryVideo.objects.filter(team_score_entry=score).first()
                judge_video_payload = _serialize_judge_video_for_playback(video_obj)

        return JsonResponse({
            "ok": True,
            "subject": {
                "kind": "equip",
                "id": equip.id,
                "name": equip.nom or f"Equip {equip.id}",
                "meta": " · ".join(
                    subject.get("members_text", "")
                    for subject in build_team_subjects_for_comp_aparell(competicio, comp_aparell)[0]
                    if int(subject.get("subject_id") or 0) == int(equip.id)
                    and subject.get("members_text")
                ),
            },
            "context": {
                "comp_aparell_id": comp_aparell_id,
                "exercici": exercici,
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
            )
            .first()
        )
        if score:
            video_obj = ScoreEntryVideo.objects.filter(score_entry=score).first()
            judge_video_payload = _serialize_judge_video_for_playback(video_obj)

    meta_parts = []
    if getattr(inscripcio, "entitat", None):
        meta_parts.append(str(inscripcio.entitat))
    if getattr(inscripcio, "categoria", None):
        meta_parts.append(str(inscripcio.categoria))
    if getattr(inscripcio, "subcategoria", None):
        meta_parts.append(str(inscripcio.subcategoria))

    return JsonResponse({
        "ok": True,
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
def scoring_updates(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)

    since = request.GET.get("since")
    comp_aparell_id = request.GET.get("comp_aparell_id")
    exercici = request.GET.get("exercici")
    group = request.GET.get("group")  # opcional

    dt = parse_datetime(since) if since else None
    if dt is None:
        # si no arriba since, no petem: retornem buit
        return JsonResponse({"ok": True, "now": None, "updates": []})

    updates = []
    team_app = None
    if comp_aparell_id:
        team_app = CompeticioAparell.objects.filter(pk=comp_aparell_id, competicio=competicio).first()

    if team_app and is_team_context_app(team_app):
        allowed_team_ids = list(_eligible_team_subject_map(competicio, team_app).keys())
        qs = TeamScoreEntry.objects.filter(
            competicio=competicio,
            comp_aparell=team_app,
            updated_at__gt=dt,
            equip_id__in=allowed_team_ids,
        )
        if exercici:
            try:
                qs = qs.filter(exercici=int(exercici))
            except Exception:
                pass
        if group is not None:
            try:
                qs = qs.filter(equip__membres__grup_competicio_id=int(group)).distinct()
            except Exception:
                pass
        for s in qs.select_related("equip")[:500]:
            updates.append({
                **serialize_subject_payload("equip", s.equip_id),
                "exercici": s.exercici,
                "comp_aparell_id": s.comp_aparell_id,
                "inputs": s.inputs or {},
                "outputs": s.outputs or {},
                "total": float(s.total),
                "updated_at": s.updated_at.isoformat(),
            })
    else:
        qs = ScoreEntry.objects.filter(competicio=competicio, updated_at__gt=dt)
        qs = qs.annotate(
            _excluded=Exists(
                InscripcioAparellExclusio.objects.filter(
                    inscripcio_id=OuterRef("inscripcio_id"),
                    comp_aparell_id=OuterRef("comp_aparell_id"),
                )
            )
        ).filter(_excluded=False)

        if comp_aparell_id:
            qs = qs.filter(comp_aparell_id=comp_aparell_id)
        if exercici:
            try:
                qs = qs.filter(exercici=int(exercici))
            except Exception:
                pass
        if group is not None:
            try:
                qs = qs.filter(inscripcio__grup_competicio_id=int(group))
            except Exception:
                pass

        for s in qs.select_related("inscripcio")[:500]:
            updates.append({
                **serialize_subject_payload("inscripcio", s.inscripcio_id),
                "exercici": s.exercici,
                "comp_aparell_id": s.comp_aparell_id,
                "inputs": s.inputs or {},
                "outputs": s.outputs or {},
                "total": float(s.total),
                "updated_at": s.updated_at.isoformat(),
            })

    # “now” del servidor per anar avançant el cursor
    return JsonResponse({"ok": True, "now": timezone.now().isoformat(), "updates": updates})
