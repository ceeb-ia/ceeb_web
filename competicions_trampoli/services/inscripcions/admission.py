from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

from ...models.competicio import CompeticioAparell, InscripcioAparellExclusio, InscripcioBaixa


def _clean_ints(values: Iterable | None) -> set[int]:
    out = set()
    for value in values or []:
        try:
            clean = int(value)
        except Exception:
            continue
        if clean > 0:
            out.add(clean)
    return out


def active_baixes_qs(competicio):
    return (
        InscripcioBaixa.objects
        .filter(competicio=competicio, anul_lada_at__isnull=True)
        .select_related("inscripcio", "comp_aparell", "marcada_per")
    )


def active_individual_app_ids(competicio) -> list[int]:
    return list(
        CompeticioAparell.objects
        .filter(competicio=competicio, actiu=True, aparell__competition_unit="individual")
        .order_by("ordre", "id")
        .values_list("id", flat=True)
    )


def load_excluded_app_ids_by_inscripcio(competicio, app_ids=None) -> dict[int, set[int]]:
    clean_app_ids = _clean_ints(app_ids)
    if not clean_app_ids:
        return defaultdict(set)

    excluded = defaultdict(set)
    rows = (
        InscripcioAparellExclusio.objects
        .filter(inscripcio__competicio=competicio, comp_aparell_id__in=clean_app_ids)
        .values_list("inscripcio_id", "comp_aparell_id")
    )
    for inscripcio_id, app_id in rows:
        excluded[int(inscripcio_id)].add(int(app_id))

    baixa_rows = (
        InscripcioBaixa.objects
        .filter(competicio=competicio, anul_lada_at__isnull=True)
        .filter(comp_aparell_id__isnull=True)
        .values_list("inscripcio_id", flat=True)
    )
    for inscripcio_id in baixa_rows:
        excluded[int(inscripcio_id)].update(clean_app_ids)

    baixa_app_rows = (
        InscripcioBaixa.objects
        .filter(competicio=competicio, anul_lada_at__isnull=True, comp_aparell_id__in=clean_app_ids)
        .values_list("inscripcio_id", "comp_aparell_id")
    )
    for inscripcio_id, app_id in baixa_app_rows:
        excluded[int(inscripcio_id)].add(int(app_id))
    return excluded


def load_baixa_app_ids_by_inscripcio(competicio, app_ids=None, inscripcio_ids=None) -> dict[int, set[int]]:
    clean_app_ids = _clean_ints(app_ids)
    clean_ins_ids = _clean_ints(inscripcio_ids)
    if not clean_app_ids:
        return defaultdict(set)

    qs = InscripcioBaixa.objects.filter(competicio=competicio, anul_lada_at__isnull=True)
    if clean_ins_ids:
        qs = qs.filter(inscripcio_id__in=clean_ins_ids)

    out = defaultdict(set)
    for inscripcio_id in qs.filter(comp_aparell_id__isnull=True).values_list("inscripcio_id", flat=True):
        out[int(inscripcio_id)].update(clean_app_ids)
    for inscripcio_id, app_id in qs.filter(comp_aparell_id__in=clean_app_ids).values_list("inscripcio_id", "comp_aparell_id"):
        out[int(inscripcio_id)].add(int(app_id))
    return out


def inscripcio_exclosa_en_aparell(inscripcio_id: int, comp_aparell_id: int) -> bool:
    try:
        clean_ins_id = int(inscripcio_id)
        clean_app_id = int(comp_aparell_id)
    except Exception:
        return False
    if InscripcioAparellExclusio.objects.filter(inscripcio_id=clean_ins_id, comp_aparell_id=clean_app_id).exists():
        return True
    return InscripcioBaixa.objects.filter(
        inscripcio_id=clean_ins_id,
        anul_lada_at__isnull=True,
    ).filter(comp_aparell_id__isnull=True).exists() or InscripcioBaixa.objects.filter(
        inscripcio_id=clean_ins_id,
        comp_aparell_id=clean_app_id,
        anul_lada_at__isnull=True,
    ).exists()


def filter_score_entries_admeses(qs):
    baixa_qs = InscripcioBaixa.objects.filter(
        inscripcio_id=OuterRef("inscripcio_id"),
        anul_lada_at__isnull=True,
    ).filter(Q(comp_aparell_id__isnull=True) | Q(comp_aparell_id=OuterRef("comp_aparell_id")))
    exclusio_qs = InscripcioAparellExclusio.objects.filter(
        inscripcio_id=OuterRef("inscripcio_id"),
        comp_aparell_id=OuterRef("comp_aparell_id"),
    )
    return qs.annotate(
        _admission_excluded=Exists(exclusio_qs),
        _admission_baixa=Exists(baixa_qs),
    ).filter(_admission_excluded=False, _admission_baixa=False)


def baixa_summary_by_inscripcio(competicio, app_ids=None, inscripcio_ids=None) -> dict[str, dict]:
    clean_app_ids = _clean_ints(app_ids)
    clean_ins_ids = _clean_ints(inscripcio_ids)
    qs = active_baixes_qs(competicio)
    if clean_ins_ids:
        qs = qs.filter(inscripcio_id__in=clean_ins_ids)

    out = {}
    for baixa in qs.order_by("inscripcio_id", "comp_aparell_id", "id"):
        key = str(baixa.inscripcio_id)
        item = out.setdefault(
            key,
            {
                "global": False,
                "app_ids": [],
                "motiu": "",
                "notes": "",
                "label": "",
            },
        )
        if baixa.comp_aparell_id is None:
            item["global"] = True
            if clean_app_ids:
                item["app_ids"] = sorted(clean_app_ids)
            item["label"] = "Tota la competicio"
        else:
            app_id = int(baixa.comp_aparell_id)
            if clean_app_ids and app_id not in clean_app_ids:
                continue
            if app_id not in item["app_ids"]:
                item["app_ids"].append(app_id)
            app_label = str(getattr(baixa.comp_aparell, "display_nom", "") or baixa.comp_aparell_id)
            item["label"] = ", ".join(part for part in [item.get("label"), app_label] if part)
        if not item["motiu"]:
            item["motiu"] = baixa.motiu or ""
        if not item["notes"]:
            item["notes"] = baixa.notes or ""
    for item in out.values():
        item["app_ids"] = sorted(_clean_ints(item.get("app_ids")))
    return out


def set_inscripcio_baixa(competicio, inscripcio, *, app_ids=None, global_scope=False, motiu="", notes="", user=None):
    clean_app_ids = _clean_ints(app_ids)
    now = timezone.now()
    with transaction.atomic():
        InscripcioBaixa.objects.filter(
            competicio=competicio,
            inscripcio=inscripcio,
            anul_lada_at__isnull=True,
        ).update(anul_lada_at=now, anul_lada_per=user)
        created = []
        if global_scope:
            created.append(
                InscripcioBaixa.objects.create(
                    competicio=competicio,
                    inscripcio=inscripcio,
                    motiu=str(motiu or "").strip(),
                    notes=str(notes or "").strip(),
                    marcada_per=user,
                )
            )
        else:
            valid_app_ids = set(
                CompeticioAparell.objects
                .filter(competicio=competicio, id__in=clean_app_ids, actiu=True)
                .values_list("id", flat=True)
            )
            for app_id in sorted(valid_app_ids):
                created.append(
                    InscripcioBaixa.objects.create(
                        competicio=competicio,
                        inscripcio=inscripcio,
                        comp_aparell_id=app_id,
                        motiu=str(motiu or "").strip(),
                        notes=str(notes or "").strip(),
                        marcada_per=user,
                    )
                )
            if clean_app_ids and valid_app_ids != clean_app_ids:
                raise ValueError("Alguns aparells no son valids per aquesta competicio.")
    return created


def clear_inscripcio_baixa(competicio, inscripcio, *, user=None):
    return (
        InscripcioBaixa.objects
        .filter(competicio=competicio, inscripcio=inscripcio, anul_lada_at__isnull=True)
        .update(anul_lada_at=timezone.now(), anul_lada_per=user)
    )


__all__ = [
    "active_baixes_qs",
    "active_individual_app_ids",
    "baixa_summary_by_inscripcio",
    "clear_inscripcio_baixa",
    "filter_score_entries_admeses",
    "inscripcio_exclosa_en_aparell",
    "load_baixa_app_ids_by_inscripcio",
    "load_excluded_app_ids_by_inscripcio",
    "set_inscripcio_baixa",
]
