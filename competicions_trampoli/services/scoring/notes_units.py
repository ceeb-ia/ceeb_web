from collections import defaultdict

from django.db.models import Count

from ...models import Inscripcio, InscripcioMedia
from ...models.competicio import CompeticioAparell, InscripcioAparellExclusio
from ...models.rotacions import RotacioAssignacio, RotacioAssignacioSerieEquip, RotacioFranja
from ...models.scoring import SerieEquipItem
from ...services.rotacions.rotacions_ordering import (
    ORDER_MODE_MAINTAIN,
    assignacio_grups,
    assignacio_series,
    build_rotation_unit_step_map,
    effective_rotate_steps,
    get_rotacions_order_modes,
    order_pairs_for_mode,
    rotation_unit_key,
    rotation_unit_label,
)
from ...services.shared.competition_groups import get_group_maps, group_label
from ...services.scoring.team_scoring import is_team_context_app
from ...services.scoring.team_subject_contract import build_team_subject_registry
from ...services.teams.team_series import team_subject_bucket_key, team_subject_bucket_label


def is_competitive_franja(franja):
    return getattr(franja, "tipus", RotacioFranja.TIPUS_COMPETITION) == RotacioFranja.TIPUS_COMPETITION


def normalize_unit_lookup_key(value):
    if value in (None, ""):
        return ""
    return str(value)


def clamp_exercici(value, comp_aparell=None):
    try:
        exercici = int(value or 1)
    except Exception:
        exercici = 1
    try:
        max_ex = int(getattr(comp_aparell, "nombre_exercicis", 1) or 1)
    except Exception:
        max_ex = 1
    return max(1, min(max_ex, exercici))


def serialize_franja(franja):
    return {
        "id": franja.id,
        "label": franja.display_label,
        "hora_inici": franja.hora_inici.isoformat() if franja.hora_inici else "",
        "hora_fi": franja.hora_fi.isoformat() if franja.hora_fi else "",
        "ordre": franja.ordre,
    }


def serialize_comp_aparell(comp_aparell):
    return {
        "id": comp_aparell.id,
        "label": str(getattr(comp_aparell, "display_nom", "") or getattr(comp_aparell.aparell, "nom", "") or "Aparell"),
        "code": str(getattr(comp_aparell, "display_codi", "") or getattr(comp_aparell.aparell, "codi", "") or ""),
        "ordre": comp_aparell.ordre,
        "subject_mode": "team" if is_team_context_app(comp_aparell) else "individual",
        "exercicis": list(range(1, clamp_exercici(999, comp_aparell) + 1)),
    }


def _inscripcions_by_group(competicio):
    grouped = defaultdict(list)
    rows = (
        Inscripcio.objects
        .filter(competicio=competicio)
        .select_related("grup_competicio")
        .order_by("grup_competicio__display_num", "ordre_competicio", "ordre_sortida", "id")
    )
    for inscripcio in rows:
        grouped[int(inscripcio.grup_competicio_id or 0)].append(inscripcio)
    return grouped


def _excluded_by_inscripcio(competicio, app_ids):
    excluded = defaultdict(set)
    if not app_ids:
        return excluded
    rows = (
        InscripcioAparellExclusio.objects
        .filter(inscripcio__competicio=competicio, comp_aparell_id__in=app_ids)
        .values_list("inscripcio_id", "comp_aparell_id")
    )
    for inscripcio_id, app_id in rows:
        excluded[int(inscripcio_id)].add(int(app_id))
    return excluded


def _team_subjects_by_bucket(competicio, comp_aparells):
    subjects_by_bucket = defaultdict(list)
    issues_by_app = {}
    for comp_aparell in comp_aparells:
        if not is_team_context_app(comp_aparell):
            continue
        registry = build_team_subject_registry(competicio, comp_aparell)
        app_name = str(getattr(comp_aparell, "display_nom", "") or getattr(comp_aparell.aparell, "nom", "") or "").strip()
        issues_by_app[str(comp_aparell.id)] = list(registry["issues"])
        for raw_subject in registry["subjects"]:
            subject = dict(raw_subject)
            bucket_key = team_subject_bucket_key(subject, comp_aparell.id)
            subject["group"] = bucket_key
            subject["group_label"] = team_subject_bucket_label(subject, app_name)
            subjects_by_bucket[str(bucket_key)].append(subject)
    return subjects_by_bucket, issues_by_app


def _series_labels_and_counts(series_ids):
    if not series_ids:
        return {}, {}
    label_by_id = {}
    for item in (
        RotacioAssignacioSerieEquip.objects
        .filter(serie_id__in=series_ids)
        .select_related("serie")
        .order_by("serie__display_num", "serie_id")
    ):
        serie = item.serie
        label_by_id[int(serie.id)] = str(serie.nom or "").strip() or f"Serie {serie.display_num}"
    count_rows = (
        SerieEquipItem.objects
        .filter(serie_id__in=series_ids)
        .values_list("serie_id", "team_subject_id")
    )
    counts = defaultdict(int)
    seen = set()
    for serie_id, subject_id in count_rows:
        key = (int(serie_id), int(subject_id))
        if key in seen:
            continue
        seen.add(key)
        counts[int(serie_id)] += 1
    return label_by_id, counts


def _unit_key_for_assignacio(assignacio, team_app_ids):
    app_id = int(getattr(getattr(assignacio, "estacio", None), "comp_aparell_id", 0) or 0)
    if app_id in team_app_ids:
        return rotation_unit_key([f"app-{app_id}-serie-{serie_id}" for serie_id in assignacio_series(assignacio)])
    return rotation_unit_key(assignacio_grups(assignacio))


def build_notes_units_context(competicio):
    comp_aparells = list(
        CompeticioAparell.objects
        .filter(competicio=competicio, actiu=True)
        .select_related("aparell")
        .order_by("ordre", "id")
    )
    app_ids = [int(app.id) for app in comp_aparells]
    apps_by_id = {int(app.id): app for app in comp_aparells}
    team_app_ids = {int(app.id) for app in comp_aparells if is_team_context_app(app)}

    franges = [
        franja
        for franja in RotacioFranja.objects.filter(competicio=competicio).order_by("ordre", "id")
        if is_competitive_franja(franja)
    ]
    franja_ids = {int(franja.id) for franja in franges}
    franges_by_id = {int(franja.id): franja for franja in franges}
    franja_modes = get_rotacions_order_modes(competicio)

    group_maps = get_group_maps(competicio)
    groups_by_id = group_maps["by_id"]
    grouped = _inscripcions_by_group(competicio)
    excluded_by_ins = _excluded_by_inscripcio(competicio, app_ids)
    team_subjects_by_bucket, team_issues_by_app = _team_subjects_by_bucket(competicio, comp_aparells)

    all_assigns = list(
        RotacioAssignacio.objects
        .filter(
            competicio=competicio,
            franja_id__in=franja_ids,
            estacio__tipus="aparell",
            estacio__comp_aparell__isnull=False,
        )
        .select_related("franja", "estacio", "estacio__comp_aparell", "estacio__comp_aparell__aparell")
        .prefetch_related("grup_links__grup", "serie_links__serie")
        .order_by("franja__ordre", "franja_id", "estacio__ordre", "id")
    )
    unit_step_map = build_rotation_unit_step_map(
        all_assigns,
        lambda assignacio: _unit_key_for_assignacio(assignacio, team_app_ids),
        franja_modes,
    )

    all_series_ids = []
    for assignacio in all_assigns:
        all_series_ids.extend(assignacio_series(assignacio))
    series_labels, series_counts = _series_labels_and_counts(all_series_ids)

    units = []
    programmed_member_keys_by_app = defaultdict(set)
    unit_by_lookup = {}
    for assignacio in all_assigns:
        app_id = int(assignacio.estacio.comp_aparell_id)
        comp_aparell = apps_by_id.get(app_id)
        if comp_aparell is None:
            continue
        franja = franges_by_id.get(int(assignacio.franja_id))
        if franja is None:
            continue

        if app_id in team_app_ids:
            serie_ids = assignacio_series(assignacio)
            member_keys = [f"app-{app_id}-serie-{serie_id}" for serie_id in serie_ids]
            label = rotation_unit_label(serie_ids, lambda serie_id: series_labels.get(int(serie_id), f"Serie {serie_id}"))
            count = sum(series_counts.get(int(serie_id), 0) for serie_id in serie_ids)
            kind = "team_rotation_cell" if len(member_keys) > 1 else "team_series"
            subject_kind = "team_unit"
        else:
            member_keys = assignacio_grups(assignacio)
            label = rotation_unit_label(member_keys, lambda group_id: group_label(groups_by_id.get(int(group_id))))
            count = 0
            for group_id in member_keys:
                for inscripcio in grouped.get(int(group_id), []):
                    if app_id not in excluded_by_ins.get(int(inscripcio.id), set()):
                        count += 1
            kind = "rotation_cell" if len(member_keys) > 1 else "group"
            subject_kind = "inscripcio"

        unit_key = rotation_unit_key(member_keys)
        if unit_key in (None, ""):
            continue
        for member_key in member_keys:
            programmed_member_keys_by_app[app_id].add(str(member_key))
        unit = {
            "key": unit_key,
            "kind": kind,
            "label": label,
            "franja_id": franja.id,
            "franja_label": franja.display_label,
            "comp_aparell_id": app_id,
            "app_label": str(getattr(comp_aparell, "display_nom", "") or getattr(comp_aparell.aparell, "nom", "") or "Aparell"),
            "member_keys": member_keys,
            "subject_kind": subject_kind,
            "count": count,
            "order_mode": franja_modes.get(str(franja.id), ORDER_MODE_MAINTAIN),
            "rotate_steps": unit_step_map.get((unit_key, franja.id), 0),
            "is_out_of_program": False,
        }
        units.append(unit)
        unit_by_lookup[(app_id, normalize_unit_lookup_key(unit_key), franja.id)] = unit
        unit_by_lookup[(app_id, normalize_unit_lookup_key(unit_key), None)] = unit

    out_of_program_units = []
    for app_id, comp_aparell in apps_by_id.items():
        if app_id in team_app_ids:
            for bucket_key, subjects in team_subjects_by_bucket.items():
                if not bucket_key.startswith(f"app-{app_id}-") or bucket_key in programmed_member_keys_by_app[app_id]:
                    continue
                unit = {
                    "key": bucket_key,
                    "kind": "team_bucket",
                    "label": subjects[0].get("group_label") if subjects else bucket_key,
                    "franja_id": None,
                    "franja_label": "",
                    "comp_aparell_id": app_id,
                    "app_label": str(getattr(comp_aparell, "display_nom", "") or getattr(comp_aparell.aparell, "nom", "") or "Aparell"),
                    "member_keys": [bucket_key],
                    "subject_kind": "team_unit",
                    "count": len(subjects),
                    "order_mode": ORDER_MODE_MAINTAIN,
                    "rotate_steps": 0,
                    "is_out_of_program": True,
                }
                out_of_program_units.append(unit)
                unit_by_lookup[(app_id, normalize_unit_lookup_key(bucket_key), None)] = unit
            continue

        for group_id, rows in grouped.items():
            if not group_id or str(group_id) in programmed_member_keys_by_app[app_id]:
                continue
            count = sum(1 for row in rows if app_id not in excluded_by_ins.get(int(row.id), set()))
            if count <= 0:
                continue
            label = group_label(groups_by_id.get(int(group_id)))
            unit = {
                "key": group_id,
                "kind": "group",
                "label": label,
                "franja_id": None,
                "franja_label": "",
                "comp_aparell_id": app_id,
                "app_label": str(getattr(comp_aparell, "display_nom", "") or getattr(comp_aparell.aparell, "nom", "") or "Aparell"),
                "member_keys": [group_id],
                "subject_kind": "inscripcio",
                "count": count,
                "order_mode": ORDER_MODE_MAINTAIN,
                "rotate_steps": 0,
                "is_out_of_program": True,
            }
            out_of_program_units.append(unit)
            unit_by_lookup[(app_id, normalize_unit_lookup_key(group_id), None)] = unit

    return {
        "apps": comp_aparells,
        "apps_by_id": apps_by_id,
        "team_app_ids": team_app_ids,
        "franges": franges,
        "franja_modes": franja_modes,
        "groups_by_id": groups_by_id,
        "grouped_inscripcions": grouped,
        "excluded_by_inscripcio": excluded_by_ins,
        "team_subjects_by_bucket": team_subjects_by_bucket,
        "team_issues_by_app": team_issues_by_app,
        "assignacions": all_assigns,
        "unit_step_map": unit_step_map,
        "units": units,
        "out_of_program_units": out_of_program_units,
        "unit_by_lookup": unit_by_lookup,
    }


def resolve_notes_unit(context, comp_aparell_id, *, unit_key=None, group=None, franja_id=None):
    app_id = int(comp_aparell_id)
    lookup_values = []
    if unit_key not in (None, ""):
        lookup_values.append(unit_key)
    if group not in (None, ""):
        lookup_values.append(group)
    for raw_value in lookup_values:
        key = normalize_unit_lookup_key(raw_value)
        if franja_id:
            unit = context["unit_by_lookup"].get((app_id, key, int(franja_id)))
            if unit is not None:
                return unit
        unit = context["unit_by_lookup"].get((app_id, key, None))
        if unit is not None:
            return unit
    return None


def subjects_for_unit(context, unit, comp_aparell):
    app_id = int(comp_aparell.id)
    member_keys = [str(item) for item in unit.get("member_keys") or []]
    if app_id in context["team_app_ids"]:
        rows = []
        for key in member_keys:
            rows.extend(context["team_subjects_by_bucket"].get(str(key), []))
        return rows

    excluded_by_ins = context["excluded_by_inscripcio"]
    rows = []
    for raw_group_id in member_keys:
        try:
            group_id = int(raw_group_id)
        except Exception:
            continue
        for inscripcio in context["grouped_inscripcions"].get(group_id, []):
            if app_id in excluded_by_ins.get(int(inscripcio.id), set()):
                continue
            rows.append(inscripcio)
    return rows


def order_subjects_for_unit(context, unit, subjects, comp_aparell):
    app_id = int(comp_aparell.id)
    mode = unit.get("order_mode") or ORDER_MODE_MAINTAIN
    rotate_steps = effective_rotate_steps(mode, unit.get("rotate_steps") or 0)
    if app_id in context["team_app_ids"]:
        pairs = [(int(subject["subject_id"]), subject) for subject in subjects]
    else:
        pairs = [(int(subject.id), subject) for subject in subjects]
    ordered = order_pairs_for_mode(
        pairs,
        mode,
        rotate_steps=rotate_steps,
        seed_prefix=f"notes|{comp_aparell.competicio_id}|{unit.get('franja_id') or 0}|{app_id}|{unit.get('key')}",
    )
    return [payload for _subject_id, payload in ordered]


def serialize_individual_subject(inscripcio, active_app_ids, excluded_by_ins):
    meta_parts = []
    if getattr(inscripcio, "entitat", None):
        meta_parts.append(str(inscripcio.entitat))
    if getattr(inscripcio, "categoria", None):
        meta_parts.append(str(inscripcio.categoria))
    if getattr(inscripcio, "subcategoria", None):
        meta_parts.append(str(inscripcio.subcategoria))
    return {
        "id": inscripcio.id,
        "subject_id": inscripcio.id,
        "subject_kind": "inscripcio",
        "order": getattr(inscripcio, "ordre_competicio", None) or getattr(inscripcio, "ordre_sortida", None) or "",
        "name": getattr(inscripcio, "nom_i_cognoms", "") or "",
        "group": getattr(inscripcio, "grup_competicio_id", 0) or 0,
        "group_display_num": getattr(getattr(inscripcio, "grup_competicio", None), "display_num", "") or "",
        "allowed_app_ids": [
            app_id
            for app_id in active_app_ids
            if app_id not in excluded_by_ins.get(int(inscripcio.id), set())
        ],
        "meta": " - ".join(meta_parts) if meta_parts else "",
    }


def media_counts_for_inscripcions(competicio, inscripcio_ids):
    counts = {str(ins_id): {"audio": 0, "video": 0} for ins_id in inscripcio_ids}
    if not inscripcio_ids:
        return counts
    rows = (
        InscripcioMedia.objects
        .filter(
            competicio=competicio,
            inscripcio_id__in=inscripcio_ids,
            tipus__in=[InscripcioMedia.Tipus.AUDIO, InscripcioMedia.Tipus.VIDEO],
        )
        .values("inscripcio_id", "tipus")
        .annotate(total=Count("id"))
    )
    for row in rows:
        bucket = counts.setdefault(str(row["inscripcio_id"]), {"audio": 0, "video": 0})
        tipus = str(row.get("tipus") or "")
        if tipus in bucket:
            bucket[tipus] = int(row.get("total") or 0)
    return counts
