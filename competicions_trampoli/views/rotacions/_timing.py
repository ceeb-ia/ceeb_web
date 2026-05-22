from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from ...models.rotacions import RotacioFranja


FRANJA_FALLBACK_DURATION_MINUTES = 15
FRANJA_DAY = date(2000, 1, 1)


@dataclass
class TimeChange:
    franja: RotacioFranja
    old_start: time
    old_end: time
    new_start: time
    new_end: time
    duration_minutes: int


def time_to_dt(value: time) -> datetime:
    return datetime.combine(FRANJA_DAY, value)


def dt_to_time(value: datetime) -> time:
    return value.time()


def format_time(value: Optional[time]) -> str:
    if value is None:
        return ""
    return value.strftime("%H:%M")


def franja_duration_delta(
    franja: RotacioFranja,
    fallback_minutes: int = FRANJA_FALLBACK_DURATION_MINUTES,
) -> timedelta:
    start_dt = time_to_dt(franja.hora_inici)
    end_dt = time_to_dt(franja.hora_fi)
    if end_dt > start_dt:
        return end_dt - start_dt
    return timedelta(minutes=max(1, int(fallback_minutes or FRANJA_FALLBACK_DURATION_MINUTES)))


def franja_duration_minutes(
    franja: RotacioFranja,
    fallback_minutes: int = FRANJA_FALLBACK_DURATION_MINUTES,
) -> int:
    return int(franja_duration_delta(franja, fallback_minutes=fallback_minutes).total_seconds() // 60)


def sort_franges_temporally(franges: Sequence[RotacioFranja]) -> List[RotacioFranja]:
    return sorted(
        list(franges or []),
        key=lambda fr: (
            time_to_dt(fr.hora_inici),
            time_to_dt(fr.hora_fi),
            int(getattr(fr, "id", 0) or 0),
        ),
    )


def sort_franges_visually(franges: Sequence[RotacioFranja]) -> List[RotacioFranja]:
    return sorted(
        list(franges or []),
        key=lambda fr: (
            int(getattr(fr, "ordre_visual", 0) or getattr(fr, "ordre", 0) or 0),
            int(getattr(fr, "id", 0) or 0),
        ),
    )


def is_competitive_franja(franja: RotacioFranja) -> bool:
    return getattr(franja, "tipus", RotacioFranja.TIPUS_COMPETITION) == RotacioFranja.TIPUS_COMPETITION


def resequence_franja_orders(franges: Iterable[RotacioFranja]) -> List[RotacioFranja]:
    ordered = sort_franges_temporally(list(franges or []))
    for idx, franja in enumerate(ordered, start=1):
        franja.ordre = idx
    return ordered


def resequence_franja_visual_orders(franges: Iterable[RotacioFranja]) -> List[RotacioFranja]:
    ordered = sort_franges_visually(list(franges or []))
    for idx, franja in enumerate(ordered, start=1):
        franja.ordre_visual = idx
    return ordered


def build_competitive_visual_sync_sequence(franges: Sequence[RotacioFranja]) -> List[RotacioFranja]:
    visual = sort_franges_visually(franges)
    competitive = [
        fr
        for fr in sorted(
            list(franges or []),
            key=lambda fr: (int(getattr(fr, "ordre", 0) or 0), int(getattr(fr, "id", 0) or 0)),
        )
        if is_competitive_franja(fr)
    ]
    globals_by_slot = {
        idx: fr
        for idx, fr in enumerate(visual)
        if not is_competitive_franja(fr)
    }
    competitive_iter = iter(competitive)
    sequence: List[RotacioFranja] = []
    for idx in range(len(visual)):
        frozen = globals_by_slot.get(idx)
        if frozen is not None:
            sequence.append(frozen)
            continue
        next_competitive = next(competitive_iter, None)
        if next_competitive is not None:
            sequence.append(next_competitive)
    sequence.extend(list(competitive_iter))
    return sequence


def build_visual_reorder_sequence(
    franges: Sequence[RotacioFranja],
    *,
    dragged_id: int,
    target_id: int,
    position: str,
) -> List[RotacioFranja]:
    ordered = sort_franges_visually(franges)
    dragged = next((fr for fr in ordered if int(fr.id) == int(dragged_id)), None)
    target = next((fr for fr in ordered if int(fr.id) == int(target_id)), None)
    if dragged is None or target is None or int(dragged.id) == int(target.id):
        return ordered
    clean_position = "after" if str(position or "").lower() == "after" else "before"
    remaining = [fr for fr in ordered if int(fr.id) != int(dragged.id)]
    target_idx = next((idx for idx, fr in enumerate(remaining) if int(fr.id) == int(target.id)), None)
    if target_idx is None:
        return ordered
    insert_idx = target_idx + 1 if clean_position == "after" else target_idx
    remaining.insert(insert_idx, dragged)
    return remaining


def serialize_time_change(change: TimeChange) -> Dict[str, object]:
    franja_id = getattr(change.franja, "id", None)
    return {
        "franja_id": int(franja_id) if franja_id else None,
        "title": str(change.franja.display_label or change.franja.tipus_label or "Franja"),
        "type": str(getattr(change.franja, "tipus", RotacioFranja.TIPUS_COMPETITION) or RotacioFranja.TIPUS_COMPETITION),
        "old_start": format_time(change.old_start),
        "old_end": format_time(change.old_end),
        "new_start": format_time(change.new_start),
        "new_end": format_time(change.new_end),
        "duration_minutes": int(change.duration_minutes),
    }


def build_competitive_shift_plan(
    franges: Sequence[RotacioFranja],
    *,
    candidate_id: Optional[int],
    candidate_start: time,
    candidate_end: time,
    fallback_minutes: int = FRANJA_FALLBACK_DURATION_MINUTES,
) -> Tuple[List[TimeChange], Optional[RotacioFranja]]:
    competitive = [
        fr
        for fr in sort_franges_temporally(franges)
        if is_competitive_franja(fr) and int(getattr(fr, "id", 0) or 0) != int(candidate_id or 0)
    ]

    candidate_start_dt = time_to_dt(candidate_start)
    candidate_end_dt = time_to_dt(candidate_end)

    insert_idx = len(competitive)
    for idx, fr in enumerate(competitive):
        fr_start_dt = time_to_dt(fr.hora_inici)
        fr_end_dt = time_to_dt(fr.hora_fi)
        fr_key = (fr_start_dt, fr_end_dt, int(getattr(fr, "id", 0) or 0))
        candidate_key = (candidate_start_dt, candidate_end_dt, int(candidate_id or 0))
        if candidate_key < fr_key:
            insert_idx = idx
            break

    previous = competitive[insert_idx - 1] if insert_idx > 0 else None
    if previous is not None and time_to_dt(previous.hora_fi) > candidate_start_dt:
        raise ValueError(
            f"La franja competitiva solapa amb l'anterior ({previous.display_label} {format_time(previous.hora_inici)}-{format_time(previous.hora_fi)})."
        )

    changes: List[TimeChange] = []
    current_end = candidate_end_dt
    has_shift_started = False
    for fr in competitive[insert_idx:]:
        start_dt = time_to_dt(fr.hora_inici)
        end_dt = time_to_dt(fr.hora_fi)
        if not has_shift_started and current_end <= start_dt:
            break
        has_shift_started = True
        duration = franja_duration_delta(fr, fallback_minutes=fallback_minutes)
        new_start = current_end
        new_end = new_start + duration
        changes.append(
            TimeChange(
                franja=fr,
                old_start=fr.hora_inici,
                old_end=fr.hora_fi,
                new_start=dt_to_time(new_start),
                new_end=dt_to_time(new_end),
                duration_minutes=int(duration.total_seconds() // 60),
            )
        )
        current_end = new_end

    return changes, previous


def build_delete_shift_plan(
    franges: Sequence[RotacioFranja],
    *,
    delete_id: int,
    fallback_minutes: int = FRANJA_FALLBACK_DURATION_MINUTES,
) -> List[TimeChange]:
    competitive = [
        fr
        for fr in sort_franges_temporally(franges)
        if is_competitive_franja(fr)
    ]
    target_idx = next((idx for idx, fr in enumerate(competitive) if int(fr.id) == int(delete_id)), None)
    if target_idx is None:
        return []

    deleted = competitive[target_idx]
    current_start = time_to_dt(deleted.hora_inici)
    changes: List[TimeChange] = []
    for fr in competitive[target_idx + 1:]:
        duration = franja_duration_delta(fr, fallback_minutes=fallback_minutes)
        new_start = current_start
        new_end = new_start + duration
        changes.append(
            TimeChange(
                franja=fr,
                old_start=fr.hora_inici,
                old_end=fr.hora_fi,
                new_start=dt_to_time(new_start),
                new_end=dt_to_time(new_end),
                duration_minutes=int(duration.total_seconds() // 60),
            )
        )
        current_start = new_end
    return changes


def build_competitive_reorder_plan(
    franges: Sequence[RotacioFranja],
    *,
    dragged_id: int,
    target_id: int,
    position: str,
    fallback_minutes: int = FRANJA_FALLBACK_DURATION_MINUTES,
) -> List[TimeChange]:
    competitive = [
        fr
        for fr in sort_franges_temporally(franges)
        if is_competitive_franja(fr)
    ]
    if len(competitive) <= 1:
        return []

    dragged = next((fr for fr in competitive if int(fr.id) == int(dragged_id)), None)
    target = next((fr for fr in competitive if int(fr.id) == int(target_id)), None)
    if dragged is None or target is None or int(dragged.id) == int(target.id):
        return []

    ordered = [fr for fr in competitive if int(fr.id) != int(dragged.id)]
    target_idx = next((idx for idx, fr in enumerate(ordered) if int(fr.id) == int(target.id)), None)
    if target_idx is None:
        return []

    clean_position = "after" if str(position or "").lower() == "after" else "before"
    insert_idx = target_idx + 1 if clean_position == "after" else target_idx
    ordered.insert(insert_idx, dragged)

    anchor_start = min(time_to_dt(fr.hora_inici) for fr in competitive)
    current_start = anchor_start
    changes: List[TimeChange] = []
    for fr in ordered:
        duration = franja_duration_delta(fr, fallback_minutes=fallback_minutes)
        new_start = current_start
        new_end = new_start + duration
        if dt_to_time(new_start) != fr.hora_inici or dt_to_time(new_end) != fr.hora_fi:
            changes.append(
                TimeChange(
                    franja=fr,
                    old_start=fr.hora_inici,
                    old_end=fr.hora_fi,
                    new_start=dt_to_time(new_start),
                    new_end=dt_to_time(new_end),
                    duration_minutes=int(duration.total_seconds() // 60),
                )
            )
        current_start = new_end
    return changes
