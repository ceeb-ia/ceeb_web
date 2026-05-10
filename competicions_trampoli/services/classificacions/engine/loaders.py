"""ORM loading and base indexing helpers for the classificacions engine."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Callable

from ....models import Inscripcio
from ....models.competicio import CompeticioAparell, ProgramUnitSlot
from ....models.scoring import ScoreEntry, TeamScoreEntry
from ..phase_scope import PHASE_SCOPE_PER_APP, normalize_phase_scope_payload
from ...scoring.team_scoring import is_team_context_app
from ...teams.equip_contexts import normalize_equip_context_code
from .common import (
    get_effective_team_context_code,
    infer_team_mode_from_comp_aparells,
    normalize_positive_int,
    normalize_team_mode,
)
from .filter_runtime import _inscripcio_matches_classificacio_filters
from .model_utils import is_relational_field


ScoreKey = tuple[int, int, int]
TeamScoreKey = tuple[int, int, int]
InscripcioMatcher = Callable[[Inscripcio], bool]


@dataclass(slots=True)
class EngineOrmData:
    aparells: list[CompeticioAparell]
    aparells_by_id: dict[int, CompeticioAparell]
    team_apps: list[CompeticioAparell]
    team_mode: str
    team_context_code: str
    all_ins_list: list[Inscripcio]
    all_ins_by_id: dict[int, Inscripcio]
    ins_list: list[Inscripcio]
    ins_by_id: dict[int, Inscripcio]
    notes: list[ScoreEntry]
    notes_by_app: dict[int, list[ScoreEntry]]
    notes_by_key: dict[ScoreKey, ScoreEntry]
    ins_ids_by_app: dict[int, set[int]]
    team_notes: list[TeamScoreEntry]
    team_notes_by_app: dict[int, list[TeamScoreEntry]]
    team_notes_by_key: dict[TeamScoreKey, TeamScoreEntry]
    team_ids_by_app: dict[int, set[int]]


def load_comp_aparells(competicio, *, punt=None) -> list[CompeticioAparell]:
    score_cfg = punt if isinstance(punt, dict) else {}
    app_cfg = score_cfg.get("aparells") if isinstance(score_cfg.get("aparells"), dict) else {}
    app_mode = str(app_cfg.get("mode") or "tots").strip().lower()

    selected_ids = []
    seen_ids = set()
    for raw_id in app_cfg.get("ids") or []:
        app_id = normalize_positive_int(raw_id)
        if app_id is None or app_id in seen_ids:
            continue
        seen_ids.add(app_id)
        selected_ids.append(app_id)

    qs = CompeticioAparell.objects.filter(competicio=competicio, actiu=True).select_related("aparell")
    if app_mode == "seleccionar" and selected_ids:
        qs = qs.filter(id__in=selected_ids)
    return list(qs.order_by("ordre", "id"))


def load_inscripcions(
    competicio,
    *,
    filtres=None,
    matches_filter: InscripcioMatcher | None = None,
) -> tuple[list[Inscripcio], dict[int, Inscripcio], list[Inscripcio], dict[int, Inscripcio]]:
    all_ins_qs = Inscripcio.objects.filter(competicio=competicio)

    select_related_fields = []
    for field_name in ("entitat", "categoria", "subcategoria", "equip", "grup_competicio"):
        if is_relational_field(Inscripcio, field_name):
            select_related_fields.append(field_name)
    if select_related_fields:
        all_ins_qs = all_ins_qs.select_related(*select_related_fields)

    all_ins_list = list(all_ins_qs)
    all_ins_by_id = {int(ins.id): ins for ins in all_ins_list}

    predicate = matches_filter or (lambda ins: _inscripcio_matches_classificacio_filters(ins, filtres))
    ins_list = [ins for ins in all_ins_list if predicate(ins)]
    ins_by_id = {int(ins.id): ins for ins in ins_list}
    return all_ins_list, all_ins_by_id, ins_list, ins_by_id


def load_score_entries(
    competicio,
    *,
    inscripcions=None,
    aparells=None,
    phase_id=None,
    include_all_phases: bool = False,
) -> list[ScoreEntry]:
    qs = (
        ScoreEntry.objects
        .filter(
            competicio=competicio,
            inscripcio__in=list(inscripcions or []),
            comp_aparell__in=list(aparells or []),
        )
        .select_related("inscripcio", "comp_aparell", "fase")
    )
    if not include_all_phases:
        if phase_id:
            qs = qs.filter(fase_id=phase_id)
        else:
            qs = qs.filter(fase__isnull=True)
    return list(qs)


def load_team_score_entries(
    competicio,
    *,
    aparells=None,
    tipus="",
    team_mode="",
    phase_id=None,
    include_all_phases: bool = False,
) -> tuple[list[CompeticioAparell], list[TeamScoreEntry]]:
    team_apps = [comp_aparell for comp_aparell in (aparells or []) if is_team_context_app(comp_aparell)]
    if tipus != "equips" or team_mode != "native_team" or not team_apps:
        return team_apps, []

    qs = (
        TeamScoreEntry.objects
        .filter(competicio=competicio, comp_aparell__in=team_apps)
        .select_related("team_subject__equip", "team_subject__context", "comp_aparell", "fase")
    )
    if not include_all_phases:
        if phase_id:
            qs = qs.filter(fase_id=phase_id)
        else:
            qs = qs.filter(fase__isnull=True)
    return team_apps, list(qs)


def phase_slot_subject_ids(competicio, phase_scope=None) -> tuple[set[int] | None, set[int] | None]:
    scope = normalize_phase_scope_payload(phase_scope or {})
    phase_id = scope.get("fase_id")
    if not phase_id:
        return None, None
    return phase_slot_subject_ids_for_phase(competicio, phase_id)


def phase_slot_subject_ids_for_phase(competicio, phase_id) -> tuple[set[int], set[int]]:
    inscripcio_ids = set()
    team_subject_ids = set()
    slots = (
        ProgramUnitSlot.objects
        .filter(
            unit__fase__competicio=competicio,
            unit__fase_id=phase_id,
            subject_id__isnull=False,
            status__in=[ProgramUnitSlot.Status.FILLED, ProgramUnitSlot.Status.MANUAL],
        )
        .values("subject_kind", "subject_id")
    )
    for slot in slots:
        subject_id = normalize_positive_int(slot.get("subject_id"))
        if subject_id is None:
            continue
        kind = str(slot.get("subject_kind") or "").strip().lower()
        if kind == "inscripcio":
            inscripcio_ids.add(subject_id)
        elif kind == "team_unit":
            team_subject_ids.add(subject_id)
    return inscripcio_ids, team_subject_ids


def phase_scope_subject_filters_by_app(
    competicio,
    phase_scope=None,
    app_ids=None,
) -> tuple[dict[int, set[int]], dict[int, set[int]], set[int]]:
    scope = normalize_phase_scope_payload(phase_scope or {})
    if scope.get("mode") != PHASE_SCOPE_PER_APP:
        return {}, {}, set()
    selected_app_ids = {
        app_id
        for app_id in (normalize_positive_int(raw_id) for raw_id in (app_ids or []))
        if app_id is not None
    }
    ins_filters = {}
    team_filters = {}
    explicit_app_ids = set()
    for raw_app_id, app_scope in (scope.get("apps") or {}).items():
        app_id = normalize_positive_int(raw_app_id)
        if app_id is None or (selected_app_ids and app_id not in selected_app_ids):
            continue
        phase_id = normalize_positive_int((app_scope or {}).get("fase_id"))
        if phase_id is None:
            continue
        ins_ids, team_ids = phase_slot_subject_ids_for_phase(competicio, phase_id)
        ins_filters[app_id] = ins_ids
        team_filters[app_id] = team_ids
        explicit_app_ids.add(app_id)
    return ins_filters, team_filters, explicit_app_ids


def build_score_indexes(
    notes=None,
) -> tuple[dict[int, list[ScoreEntry]], dict[ScoreKey, ScoreEntry], dict[int, set[int]]]:
    notes_by_app = defaultdict(list)
    notes_by_key = {}
    ins_ids_by_app = defaultdict(set)

    for note in notes or []:
        app_id = int(note.comp_aparell_id)
        ex_idx = int(getattr(note, "exercici", 1) or 1)
        ins_id = int(note.inscripcio_id)
        notes_by_app[app_id].append(note)
        notes_by_key[(ins_id, app_id, ex_idx)] = note
        ins_ids_by_app[app_id].add(ins_id)

    return notes_by_app, notes_by_key, ins_ids_by_app


def build_team_score_indexes(
    team_notes=None,
    *,
    team_context_code="",
) -> tuple[dict[int, list[TeamScoreEntry]], dict[TeamScoreKey, TeamScoreEntry], dict[int, set[int]]]:
    normalized_context_code = normalize_equip_context_code(team_context_code)
    team_notes_by_app = defaultdict(list)
    team_notes_by_key = {}
    team_ids_by_app = defaultdict(set)

    for note in team_notes or []:
        note_context_code = normalize_equip_context_code(
            getattr(getattr(getattr(note, "team_subject", None), "context", None), "code", "")
        )
        if note_context_code != normalized_context_code:
            continue

        equip_id = normalize_positive_int(getattr(note, "equip_id", None))
        if equip_id is None:
            continue

        app_id = int(note.comp_aparell_id)
        ex_idx = int(getattr(note, "exercici", 1) or 1)
        team_notes_by_app[app_id].append(note)
        team_notes_by_key[(equip_id, app_id, ex_idx)] = note
        team_ids_by_app[app_id].add(equip_id)

    return team_notes_by_app, team_notes_by_key, team_ids_by_app


def load_engine_orm_data(
    competicio,
    *,
    punt=None,
    tipus="",
    filtres=None,
    equips_cfg=None,
    phase_scope=None,
    matches_filter: InscripcioMatcher | None = None,
) -> EngineOrmData:
    aparells = load_comp_aparells(competicio, punt=punt)
    aparells_by_id = {int(comp_aparell.id): comp_aparell for comp_aparell in aparells}

    team_cfg = equips_cfg if isinstance(equips_cfg, dict) else {}
    team_mode = ""
    if tipus == "equips":
        team_mode = normalize_team_mode(team_cfg.get("team_mode")) or infer_team_mode_from_comp_aparells(aparells)
    team_context_code = get_effective_team_context_code(team_cfg)

    all_ins_list = []
    all_ins_by_id = {}
    ins_list = []
    ins_by_id = {}
    notes = []
    notes_by_app = defaultdict(list)
    notes_by_key = {}
    ins_ids_by_app = defaultdict(set)
    team_apps = [comp_aparell for comp_aparell in aparells if is_team_context_app(comp_aparell)]
    team_notes = []
    team_notes_by_app = defaultdict(list)
    team_notes_by_key = {}
    team_ids_by_app = defaultdict(set)

    if aparells:
        normalized_phase_scope = normalize_phase_scope_payload(phase_scope or {})
        phase_id = (
            normalize_positive_int(normalized_phase_scope.get("fase_id"))
            if normalized_phase_scope.get("mode") != PHASE_SCOPE_PER_APP
            else None
        )
        phase_ids_by_app = {}
        if normalized_phase_scope.get("mode") == PHASE_SCOPE_PER_APP:
            for raw_app_id, app_scope in (normalized_phase_scope.get("apps") or {}).items():
                app_id = normalize_positive_int(raw_app_id)
                app_phase_id = normalize_positive_int((app_scope or {}).get("fase_id"))
                if app_id is not None and app_phase_id is not None:
                    phase_ids_by_app[app_id] = app_phase_id
        phase_inscripcio_ids, phase_team_subject_ids = (
            (None, None)
            if normalized_phase_scope.get("mode") == PHASE_SCOPE_PER_APP
            else phase_slot_subject_ids(competicio, normalized_phase_scope)
        )
        app_ids = [int(comp_aparell.id) for comp_aparell in aparells]
        phase_ins_filters_by_app, phase_team_filters_by_app, phase_explicit_app_ids = phase_scope_subject_filters_by_app(
            competicio,
            normalized_phase_scope,
            app_ids=app_ids,
        )
        all_ins_list, all_ins_by_id, ins_list, ins_by_id = load_inscripcions(
            competicio,
            filtres=filtres,
            matches_filter=matches_filter,
        )
        if phase_inscripcio_ids is not None:
            ins_list = [ins for ins in ins_list if int(ins.id) in phase_inscripcio_ids]
            ins_by_id = {int(ins.id): ins for ins in ins_list}
        elif phase_explicit_app_ids and set(app_ids).issubset(phase_explicit_app_ids):
            scoped_ins_ids = set()
            for ids in phase_ins_filters_by_app.values():
                scoped_ins_ids.update(ids)
            ins_list = [ins for ins in ins_list if int(ins.id) in scoped_ins_ids]
            ins_by_id = {int(ins.id): ins for ins in ins_list}
        notes = load_score_entries(
            competicio,
            inscripcions=ins_list,
            aparells=aparells,
            phase_id=phase_id,
            include_all_phases=normalized_phase_scope.get("mode") == PHASE_SCOPE_PER_APP,
        )
        if normalized_phase_scope.get("mode") == PHASE_SCOPE_PER_APP:
            notes = [
                note for note in notes
                if (
                    int(note.comp_aparell_id) in phase_ids_by_app
                    and int(note.fase_id or 0) == phase_ids_by_app[int(note.comp_aparell_id)]
                )
                or (
                    int(note.comp_aparell_id) not in phase_ids_by_app
                    and note.fase_id is None
                )
            ]
        if phase_ins_filters_by_app:
            notes = [
                note for note in notes
                if int(note.comp_aparell_id) not in phase_explicit_app_ids
                or int(note.inscripcio_id) in phase_ins_filters_by_app.get(int(note.comp_aparell_id), set())
            ]
        notes_by_app, notes_by_key, ins_ids_by_app = build_score_indexes(notes)
        team_apps, team_notes = load_team_score_entries(
            competicio,
            aparells=aparells,
            tipus=tipus,
            team_mode=team_mode,
            phase_id=phase_id,
            include_all_phases=normalized_phase_scope.get("mode") == PHASE_SCOPE_PER_APP,
        )
        if normalized_phase_scope.get("mode") == PHASE_SCOPE_PER_APP:
            team_notes = [
                note for note in team_notes
                if (
                    int(note.comp_aparell_id) in phase_ids_by_app
                    and int(note.fase_id or 0) == phase_ids_by_app[int(note.comp_aparell_id)]
                )
                or (
                    int(note.comp_aparell_id) not in phase_ids_by_app
                    and note.fase_id is None
                )
            ]
        if phase_team_subject_ids is not None:
            team_notes = [
                note for note in team_notes
                if int(getattr(note, "team_subject_id", 0) or 0) in phase_team_subject_ids
            ]
        elif phase_team_filters_by_app:
            team_notes = [
                note for note in team_notes
                if int(note.comp_aparell_id) not in phase_explicit_app_ids
                or int(getattr(note, "team_subject_id", 0) or 0) in phase_team_filters_by_app.get(
                    int(note.comp_aparell_id),
                    set(),
                )
            ]
        team_notes_by_app, team_notes_by_key, team_ids_by_app = build_team_score_indexes(
            team_notes,
            team_context_code=team_context_code,
        )

    return EngineOrmData(
        aparells=aparells,
        aparells_by_id=aparells_by_id,
        team_apps=team_apps,
        team_mode=team_mode,
        team_context_code=team_context_code,
        all_ins_list=all_ins_list,
        all_ins_by_id=all_ins_by_id,
        ins_list=ins_list,
        ins_by_id=ins_by_id,
        notes=notes,
        notes_by_app=notes_by_app,
        notes_by_key=notes_by_key,
        ins_ids_by_app=ins_ids_by_app,
        team_notes=team_notes,
        team_notes_by_app=team_notes_by_app,
        team_notes_by_key=team_notes_by_key,
        team_ids_by_app=team_ids_by_app,
    )


__all__ = [
    "EngineOrmData",
    "build_score_indexes",
    "build_team_score_indexes",
    "load_comp_aparells",
    "load_engine_orm_data",
    "load_inscripcions",
    "load_score_entries",
    "load_team_score_entries",
    "phase_scope_subject_filters_by_app",
    "phase_slot_subject_ids",
    "phase_slot_subject_ids_for_phase",
]
