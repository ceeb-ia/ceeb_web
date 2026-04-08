from django.db.models import Count, Exists, OuterRef
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.generic import TemplateView

from ...models import Competicio, Inscripcio, InscripcioMedia
from ...models.competicio import CompeticioAparell, InscripcioAparellExclusio
from ...models.rotacions import RotacioAssignacio, RotacioAssignacioSerieEquip, RotacioFranja
from ...models.scoring import ScoreEntry, ScoreEntryVideo, ScoringSchema, TeamScoreEntry, TeamScoreEntryVideo
from ...services.shared.competition_groups import (
    get_group_maps,
    get_inscripcio_competition_order,
    get_inscripcio_group_display_num,
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
from ...services.scoring.scoring_subjects import score_store_key
from ...services.scoring.team_scoring import is_team_context_app, runtime_schema_for_comp_aparell
from ...services.teams.team_series import team_subject_bucket_key, team_subject_bucket_label
from ...services.scoring.team_subject_contract import build_team_subject_registry, runtime_schema_for_team_subjects
from .helpers import (
    _allowed_input_codes_for_schema,
    _bucket_app_id,
    _logical_schema_for_notes_ui,
    _logical_team_input_codes,
    _sanitize_inputs_for_client,
)


def _is_competitive_franja(franja):
    return getattr(franja, "tipus", RotacioFranja.TIPUS_COMPETITION) == RotacioFranja.TIPUS_COMPETITION


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
        competition_franges = [fr for fr in franges if _is_competitive_franja(fr)]
        competition_franja_ids = {fr.id for fr in competition_franges}
        franja_modes = get_rotacions_order_modes(competicio)
        group_maps = get_group_maps(competicio)
        groups_by_id = group_maps["by_id"]
        group_labels_map = {"0": "Sense grup"}
        for group in group_maps["groups"]:
            group_labels_map[str(group.id)] = group_label(group)
        team_group_rows_by_key = {}
        team_programmed_group_keys = []
        team_out_of_program_group_keys = []

        franja_selected_id = None
        fr_raw = self.request.GET.get("franja")
        if fr_raw not in (None, ""):
            try:
                fr_int = int(fr_raw)
            except Exception:
                fr_int = None
            if fr_int and fr_int in competition_franja_ids:
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
            .filter(franja_id__in=competition_franja_ids)
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
        render_out_of_program_groups = show_out_of_program_groups or not programmed_groups
        visible_groups = programmed_groups + (out_of_program_groups if render_out_of_program_groups else [])
        visible_individual_groups = list(visible_groups)


        # Aparells de la competició
        aparells_cfg = (
            CompeticioAparell.objects
            .filter(competicio=competicio, actiu=True)
            .select_related("aparell")
            .order_by("ordre", "id")
        )
        aparells_cfg = list(aparells_cfg)
        apparells_cfg_by_id = {int(ca.id): ca for ca in aparells_cfg}
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
        logical_schemas = {}
        team_registry_by_app_id = {}
        for ca in aparells_cfg:
            ss, _ = ScoringSchema.objects.get_or_create(
                aparell=ca.aparell,
                defaults={"schema": {}},
            )
            logical_schemas[str(ca.id)] = _logical_schema_for_notes_ui(ss.schema or {}, ca)
            if is_team_context_app(ca):
                registry = build_team_subject_registry(competicio, ca)
                team_registry_by_app_id[int(ca.id)] = registry
                schemas[str(ca.id)] = runtime_schema_for_team_subjects(ss.schema or {}, ca, registry["subjects"])
            else:
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
            ca = apparells_cfg_by_id.get(int(s.comp_aparell_id))
            allowed_inputs = _allowed_input_codes_for_schema(logical_schemas.get(str(s.comp_aparell_id), {}), ca)
            key = score_store_key("inscripcio", s.inscripcio_id, s.exercici, s.comp_aparell_id)
            scores[key] = {
                "inputs": _sanitize_inputs_for_client(s.inputs or {}, allowed_inputs),
                "outputs": s.outputs or {},
                "total": float(s.total),
            }

        team_subjects = []
        team_issues_by_app = {}
        eligible_team_ids_by_app = {}
        for ca in aparells_cfg:
            if not is_team_context_app(ca):
                continue
            registry = team_registry_by_app_id.get(int(ca.id)) or build_team_subject_registry(competicio, ca)
            app_subjects = list(registry["subjects"])
            issues = list(registry["issues"])
            rows_by_bucket = defaultdict(list)
            programmed_series_ids = set(
                RotacioAssignacioSerieEquip.objects
                .filter(assignacio__competicio=competicio, serie__comp_aparell=ca)
                .values_list("serie_id", flat=True)
                .distinct()
            )
            app_name = str(getattr(ca.aparell, "nom", "") or "").strip()
            for raw_subject in app_subjects:
                subject = dict(raw_subject)
                bucket_key = team_subject_bucket_key(subject, ca.id)
                subject["group"] = bucket_key
                subject["group_label"] = team_subject_bucket_label(subject, app_name)
                rows_by_bucket[bucket_key].append(subject)
                if subject.get("serie_id"):
                    if int(subject["serie_id"]) in programmed_series_ids:
                        if bucket_key not in team_programmed_group_keys:
                            team_programmed_group_keys.append(bucket_key)
                    elif bucket_key not in team_out_of_program_group_keys:
                        team_out_of_program_group_keys.append(bucket_key)
                elif bucket_key not in team_out_of_program_group_keys:
                    team_out_of_program_group_keys.append(bucket_key)
                group_labels_map[str(bucket_key)] = subject["group_label"]
                team_subjects.append(subject)
            for bucket_key, rows in rows_by_bucket.items():
                team_group_rows_by_key[str(bucket_key)] = rows
            team_issues_by_app[str(ca.id)] = issues
            eligible_team_ids_by_app[int(ca.id)] = [
                int(subject["subject_id"])
                for subject in app_subjects
                if int(ca.id) in (subject.get("allowed_app_ids") or [])
            ]
        team_programmed_groups = [
            (group_key, team_group_rows_by_key[group_key])
            for group_key in team_programmed_group_keys
            if group_key in team_group_rows_by_key
        ]
        team_out_of_program_groups = [
            (group_key, team_group_rows_by_key[group_key])
            for group_key in team_out_of_program_group_keys
            if group_key in team_group_rows_by_key and group_key not in team_programmed_group_keys
        ]
        programmed_groups.extend(team_programmed_groups)
        out_of_program_groups.extend(team_out_of_program_groups)
        visible_groups = programmed_groups + (out_of_program_groups if render_out_of_program_groups else [])

        team_score_app_ids = [app_id for app_id, ids in eligible_team_ids_by_app.items() if ids]
        team_subject_ids = [team_id for ids in eligible_team_ids_by_app.values() for team_id in ids]
        if team_score_app_ids and team_subject_ids:
            team_scores_qs = TeamScoreEntry.objects.filter(
                competicio=competicio,
                comp_aparell_id__in=team_score_app_ids,
                team_subject_id__in=team_subject_ids,
                exercici__in=exercicis,
            ).select_related("team_subject")
            for s in team_scores_qs:
                allowed_inputs = _logical_team_input_codes(logical_schemas.get(str(s.comp_aparell_id), {}))
                key = score_store_key("team_unit", s.team_subject_id, s.exercici, s.comp_aparell_id)
                scores[key] = {
                    "inputs": _sanitize_inputs_for_client(s.inputs or {}, allowed_inputs),
                    "outputs": s.outputs or {},
                    "total": float(s.total),
                }

        # ─────────────────────────────
        # INSCRIPCIONS (llista plana per JS)
        # ─────────────────────────────
        # inscripcions: llista plana per al JS
        inscripcions = []
        for g, rows in visible_individual_groups:
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
        if team_subject_ids and team_score_app_ids and exercicis:
            team_judge_video_rows = (
                TeamScoreEntryVideo.objects
                .filter(
                    team_score_entry__competicio=competicio,
                    team_score_entry__team_subject_id__in=team_subject_ids,
                    team_score_entry__comp_aparell_id__in=team_score_app_ids,
                    team_score_entry__exercici__in=exercicis,
                )
                .exclude(video_file="")
                .values_list(
                    "team_score_entry__team_subject_id",
                    "team_score_entry__exercici",
                    "team_score_entry__comp_aparell_id",
                )
            )
            for team_subject_id, exercici_id, app_id in team_judge_video_rows:
                judge_video_presence_by_key[score_store_key("team_unit", team_subject_id, exercici_id, app_id)] = 1

        rotation_rank_map = {}
        rotation_groups_by_app = {}
        if franja_selected_id:
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
            rotation_group_step_map = build_group_rotation_step_map(all_assigns, franja_modes)
            rotation_series_step_map = build_series_rotation_step_map(all_assigns, franja_modes)
            assigns = [a for a in all_assigns if a.franja_id == franja_selected_id]
            app_groups_map = {}
            for a in assigns:
                app_id = a.estacio.comp_aparell_id
                if app_id in team_app_ids:
                    groups_for_cell = [
                        f"app-{app_id}-serie-{serie_id}"
                        for serie_id in assignacio_series(a)
                    ]
                else:
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
                        if int(app_id) not in (subject.get("allowed_app_ids") or []) and not subject.get("invalid_reasons"):
                            continue
                        key = str(subject.get("group") or "")
                        if key not in app_groups:
                            continue
                        subject_rows_by_group.setdefault(key, []).append(subject)
                else:
                    for g, rows in programmed_groups:
                        if isinstance(g, str):
                            continue
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
                            (
                                rotation_series_step_map.get((int(str(g).rsplit("-", 1)[-1]), franja_selected_id), 0)
                                if app_id in team_app_ids and str(g).startswith(f"app-{app_id}-serie-")
                                else rotation_group_step_map.get((g, franja_selected_id), 0)
                            ),
                        ),
                        seed_prefix=f"notes|{competicio.id}|{franja_selected_id}|{app_id}|{g}",
                    )
                    for subject_id, _r in ordered:
                        key = f"{app_id}|{subject_id}"
                        if key in rotation_rank_map:
                            continue
                        rotation_rank_map[key] = rank
                        rank += 1

        def _group_visible_for_app(group_key, app_id):
            visible_group_keys = rotation_groups_by_app.get(str(app_id)) or []
            if not visible_group_keys:
                return True
            return str(group_key) in {str(item) for item in visible_group_keys}

        def _apps_for_individual_group(group_key, rows):
            visible_apps = []
            for ca in aparells_cfg:
                if int(ca.id) in team_app_ids:
                    continue
                if not _group_visible_for_app(group_key, ca.id):
                    continue
                has_rows = any(int(ca.id) not in excluded_by_ins.get(row.id, set()) for row in rows)
                if has_rows:
                    visible_apps.append(ca)
            return visible_apps

        def _apps_for_team_bucket(group_key, rows):
            app_id = _bucket_app_id(group_key)
            if app_id is None or not _group_visible_for_app(group_key, app_id):
                return []
            ca = apparells_cfg_by_id.get(int(app_id))
            if ca is None:
                return []
            return [ca]

        def _render_groups_payload(group_rows):
            rendered = []
            for group_key, rows in group_rows:
                key_str = str(group_key)
                if isinstance(group_key, str):
                    visible_apps = _apps_for_team_bucket(group_key, rows)
                    kind = "team_bucket"
                else:
                    visible_apps = _apps_for_individual_group(group_key, rows)
                    kind = "individual_group"
                if not visible_apps:
                    continue
                rendered.append({
                    "key": key_str,
                    "label": group_labels_map.get(key_str, "Sense grup"),
                    "kind": kind,
                    "count": len(rows),
                    "apps": visible_apps,
                })
            return rendered

        groups_render = _render_groups_payload(programmed_groups)
        out_of_program_groups_render = (
            _render_groups_payload(out_of_program_groups)
            if render_out_of_program_groups
            else []
        )

        ctx.update({
            "competicio": competicio,
            "groups": programmed_groups,
            "out_of_program_groups": out_of_program_groups if show_out_of_program_groups else [],
            "groups_render": groups_render,
            "out_of_program_groups_render": out_of_program_groups_render,
            "show_out_of_program_in_competition_views": show_out_of_program_groups,
            "group_labels_map": group_labels_map,
            "aparells_cfg": aparells_cfg,
            "exercicis": exercicis,
            "exercicis_by_aparell": exercicis_by_aparell,
            "franges": competition_franges,
            "competition_franges": competition_franges,
            "franja_selected_id": franja_selected_id,
            "rotation_rank_map": rotation_rank_map,
            "rotation_groups_by_app": rotation_groups_by_app,

            # per json_script
            "schemas": schemas,
            "logical_schemas": logical_schemas,
            "scores": scores,
            "inscripcions": inscripcions,
            "media_counts_by_inscripcio": media_counts_by_inscripcio,
            "judge_video_presence_by_key": judge_video_presence_by_key,
            "team_issues_by_app": team_issues_by_app,
            "updates_cursor_init": timezone.now().isoformat(),
        })
        return ctx

