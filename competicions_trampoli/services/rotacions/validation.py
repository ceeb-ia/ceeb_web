from collections import defaultdict

from ...models import Inscripcio
from ...models.competicio import ProgramUnit, ProgramUnitSlot
from ...models.inscripcions import GrupCompeticio
from ...models.rotacions import RotacioAssignacio, RotacioFranja
from ...models.scoring import SerieEquip, SerieEquipItem, TeamCompetitiveSubject
from .rotacions_ordering import assignacio_grups, assignacio_program_units, assignacio_series


def _item(severity, code, message, *, franja_id=None, estacio_id=None, program_key=""):
    return {
        "severity": severity,
        "code": code,
        "message": message,
        "franja_id": int(franja_id) if franja_id else None,
        "estacio_id": int(estacio_id) if estacio_id else None,
        "program_key": str(program_key or ""),
    }


def _station_mode(estacio):
    if getattr(estacio, "tipus", "") != "aparell" or not getattr(estacio, "comp_aparell_id", None):
        return "none"
    aparell = getattr(getattr(estacio, "comp_aparell", None), "aparell", None)
    if aparell is not None and getattr(aparell, "competition_unit", "") == "team":
        return "series"
    return "group"


def _assignacio_keys(assignacio):
    return (
        [f"g:{group_id}" for group_id in assignacio_grups(assignacio)]
        + [f"s:{serie_id}" for serie_id in assignacio_series(assignacio)]
        + [f"pu:{unit_id}" for unit_id in assignacio_program_units(assignacio)]
    )


def _labels(competicio):
    group_labels = {
        f"g:{group.id}": (group.nom.strip() or f"Grup {group.display_num}")
        for group in GrupCompeticio.objects.filter(competicio=competicio)
    }
    series_labels = {
        f"s:{serie.id}": (serie.nom.strip() or f"Serie {serie.display_num}")
        for serie in SerieEquip.objects.filter(competicio=competicio)
    }
    unit_labels = {
        f"pu:{unit.id}": unit.nom
        for unit in ProgramUnit.objects.filter(fase__competicio=competicio)
    }
    return {**group_labels, **series_labels, **unit_labels}


def _program_key_subjects(competicio):
    subjects_by_key = defaultdict(set)

    for inscripcio in Inscripcio.objects.filter(competicio=competicio, grup_competicio_id__isnull=False).only(
        "id",
        "grup_competicio_id",
    ):
        subjects_by_key[f"g:{inscripcio.grup_competicio_id}"].add(f"ins:{inscripcio.id}")

    team_subject_members = {
        int(subject.id): {f"ins:{member_id}" for member_id in (subject.member_ids or []) if member_id}
        for subject in TeamCompetitiveSubject.objects.filter(competicio=competicio).only("id", "member_ids")
    }
    for item in SerieEquipItem.objects.filter(serie__competicio=competicio).select_related("team_subject").only(
        "serie_id",
        "team_subject_id",
        "team_subject__member_ids",
    ):
        members = team_subject_members.get(int(item.team_subject_id or 0), set())
        subjects_by_key[f"s:{item.serie_id}"].update(members or {f"team:{item.team_subject_id}"})

    for slot in ProgramUnitSlot.objects.filter(unit__fase__competicio=competicio, subject_id__isnull=False).only(
        "unit_id",
        "subject_kind",
        "subject_id",
    ):
        kind = str(slot.subject_kind or "").strip().lower()
        subject_id = int(slot.subject_id or 0)
        if subject_id <= 0:
            continue
        key = f"pu:{slot.unit_id}"
        if kind == "inscripcio":
            subjects_by_key[key].add(f"ins:{subject_id}")
        elif kind == "team_unit":
            subjects_by_key[key].update(team_subject_members.get(subject_id, set()) or {f"team:{subject_id}"})
        else:
            subjects_by_key[key].add(f"{kind or 'subject'}:{subject_id}")

    return subjects_by_key


def _is_allowed_in_station(program_key, estacio):
    mode = _station_mode(estacio)
    if program_key.startswith("g:"):
        return mode == "group"
    if program_key.startswith("s:"):
        return mode == "series"
    if program_key.startswith("pu:"):
        unit_id = int(program_key.split(":", 1)[1])
        try:
            unit = ProgramUnit.objects.select_related("fase").get(pk=unit_id, fase__competicio=estacio.competicio)
        except ProgramUnit.DoesNotExist:
            return False
        return mode in {"group", "series"} and int(unit.fase.comp_aparell_id or 0) == int(estacio.comp_aparell_id or 0)
    return False


def validate_rotacions_program(competicio):
    labels = _labels(competicio)
    subjects_by_key = _program_key_subjects(competicio)
    result = {"errors": [], "warnings": [], "info": []}

    franges = list(RotacioFranja.objects.filter(competicio=competicio).order_by("ordre", "id"))
    competitive_ids = {int(franja.id) for franja in franges if franja.is_competitive}
    assignacions = list(
        RotacioAssignacio.objects
        .filter(competicio=competicio, franja_id__in=competitive_ids)
        .select_related("franja", "estacio", "estacio__comp_aparell__aparell")
        .prefetch_related("grup_links", "serie_links", "program_unit_links")
    )

    appearances = defaultdict(list)
    keys_by_franja = defaultdict(list)
    subjects_by_franja = defaultdict(dict)
    assigned_keys = set()

    for assignacio in assignacions:
        keys = _assignacio_keys(assignacio)
        if not keys:
            continue
        for key in keys:
            assigned_keys.add(key)
            keys_by_franja[int(assignacio.franja_id)].append(key)
            appearances[key].append(assignacio)
            if not _is_allowed_in_station(key, assignacio.estacio):
                label = labels.get(key, key)
                result["errors"].append(
                    _item(
                        "error",
                        "incompatible_station",
                        f"{label} no es compatible amb aquesta estacio.",
                        franja_id=assignacio.franja_id,
                        estacio_id=assignacio.estacio_id,
                        program_key=key,
                    )
                )
            for subject_key in subjects_by_key.get(key, {key}):
                owner = subjects_by_franja[int(assignacio.franja_id)].setdefault(subject_key, assignacio)
                if int(owner.estacio_id) != int(assignacio.estacio_id):
                    label = labels.get(key, key)
                    result["errors"].append(
                        _item(
                            "error",
                            "simultaneous_subject",
                            f"{label} coincideix amb un altre element de la mateixa franja.",
                            franja_id=assignacio.franja_id,
                            estacio_id=assignacio.estacio_id,
                            program_key=key,
                        )
                    )

    for key, rows in appearances.items():
        if len(rows) <= 1:
            continue
        label = labels.get(key, key)
        franja_ids = {int(row.franja_id) for row in rows}
        code = "duplicate_program_item_same_franja" if len(franja_ids) == 1 else "duplicate_program_item"
        result["errors"].append(
            _item(
                "error",
                code,
                f"{label} apareix en mes d'una cel.la del programa.",
                franja_id=rows[0].franja_id,
                estacio_id=rows[0].estacio_id,
                program_key=key,
            )
        )

    for franja in franges:
        if franja.is_competitive and not keys_by_franja.get(int(franja.id)):
            result["warnings"].append(
                _item(
                    "warning",
                    "empty_franja",
                    f"{franja.display_label} no te cap programable assignat.",
                    franja_id=franja.id,
                )
            )

    all_program_keys = set(labels.keys())
    pending_count = len(all_program_keys - assigned_keys)
    if pending_count:
        result["warnings"].append(
            _item(
                "warning",
                "pending_program_items",
                f"Queden {pending_count} programables pendents de situar al programa.",
            )
        )
    else:
        result["info"].append(
            _item("info", "all_program_items_assigned", "Tots els programables estan situats al programa.")
        )

    return result
