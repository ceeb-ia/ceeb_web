from dataclasses import dataclass
from typing import Sequence


Match = tuple[int, int]
Round = tuple[Match, ...]
CalendarPhase = tuple[Round, ...]


PRIMERA_FASE: CalendarPhase = (
    ((8, 5), (6, 4), (7, 3), (1, 2)),
    ((2, 8), (3, 1), (4, 7), (5, 6)),
    ((8, 6), (7, 5), (1, 4), (2, 3)),
    ((3, 8), (4, 2), (5, 1), (6, 7)),
    ((8, 7), (1, 6), (2, 5), (3, 4)),
    ((8, 4), (5, 3), (6, 2), (7, 1)),
    ((1, 8), (2, 7), (3, 6), (4, 5)),
)

PRIMERA_FASE_10: CalendarPhase = (
    ((10, 6), (7, 5), (8, 4), (9, 3), (1, 2)),
    ((2, 10), (3, 1), (4, 9), (5, 8), (6, 7)),
    ((10, 7), (8, 6), (9, 5), (1, 4), (2, 3)),
    ((3, 10), (4, 2), (5, 1), (6, 9), (7, 8)),
    ((10, 8), (9, 7), (1, 6), (2, 5), (3, 4)),
    ((4, 10), (5, 3), (6, 2), (7, 1), (8, 9)),
    ((10, 9), (1, 8), (2, 7), (3, 6), (4, 5)),
    ((10, 5), (6, 4), (7, 3), (8, 2), (9, 1)),
    ((1, 10), (2, 9), (3, 8), (4, 7), (5, 6)),
)


SEGONA_FASE: CalendarPhase = (
    ((8, 5), (6, 4), (7, 3), (1, 2)),
    ((2, 8), (3, 1), (4, 7), (5, 6)),
    ((8, 6), (7, 5), (1, 4), (2, 3)),
    ((3, 8), (4, 2), (5, 1), (6, 7)),
    ((8, 7), (1, 6), (2, 5), (3, 4)),
    ((8, 4), (5, 3), (6, 2), (7, 1)),
    ((1, 8), (2, 7), (3, 6), (4, 5)),
    ((5, 8), (4, 6), (3, 7), (2, 1)),
    ((8, 2), (1, 3), (7, 4), (6, 5)),
    ((6, 8), (5, 7), (4, 1), (3, 2)),
    ((8, 3), (2, 4), (1, 5), (7, 6)),
    ((7, 8), (6, 1), (5, 2), (4, 3)),
    ((4, 8), (3, 5), (2, 6), (1, 7)),
    ((8, 1), (7, 2), (6, 3), (5, 4)),
)


SEGONA_FASE_10: CalendarPhase = (
    ((10, 6), (7, 5), (8, 4), (9, 3), (1, 2)),
    ((2, 10), (3, 1), (4, 9), (5, 8), (6, 7)),
    ((10, 7), (8, 6), (9, 5), (1, 4), (2, 3)),
    ((3, 10), (4, 2), (5, 1), (6, 9), (7, 8)),
    ((10, 8), (9, 7), (1, 6), (2, 5), (3, 4)),
    ((4, 10), (5, 3), (6, 2), (7, 1), (8, 9)),
    ((10, 9), (1, 8), (2, 7), (3, 6), (4, 5)),
    ((10, 5), (6, 4), (7, 3), (8, 2), (9, 1)),
    ((1, 10), (2, 9), (3, 8), (4, 7), (5, 6)),
    ((6, 10), (5, 7), (4, 8), (3, 9), (2, 1)),
    ((10, 2), (1, 3), (9, 4), (8, 5), (7, 6)),
    ((7, 10), (6, 8), (5, 9), (4, 1), (3, 2)),
    ((10, 3), (2, 4), (1, 5), (9, 6), (8, 7)),
    ((8, 10), (7, 9), (6, 1), (5, 2), (4, 3)),
    ((10, 4), (3, 5), (2, 6), (1, 7), (9, 8)),
    ((9, 10), (8, 1), (7, 2), (6, 3), (5, 4)),
    ((5, 10), (4, 6), (3, 7), (2, 8), (1, 9)),
    ((10, 1), (9, 2), (8, 3), (7, 4), (6, 5)),
)


@dataclass(frozen=True)
class PhaseConfig:
    name: str
    calendar: CalendarPhase
    slots_per_group: int = 8

    @property
    def rounds(self) -> int:
        return len(self.calendar)


FIRST_PHASE = PhaseConfig(name="primera_fase", calendar=PRIMERA_FASE)
SECOND_PHASE = PhaseConfig(name="segona_fase", calendar=SEGONA_FASE)


_PHASE_CALENDARS: dict[tuple[str, int], CalendarPhase] = {
    ("primera_fase", 8): PRIMERA_FASE,
    ("primera_fase", 10): PRIMERA_FASE_10,
    ("segona_fase", 8): SEGONA_FASE,
    ("segona_fase", 10): SEGONA_FASE_10,
}


def phase_calendar(phase_name: str, slot_count: int = 8) -> CalendarPhase:
    """Return the official calendar for a phase and slot count."""

    normalized_phase = _normalize_phase_name(phase_name)
    normalized_slots = _normalize_slot_count(slot_count)
    return _PHASE_CALENDARS[(normalized_phase, normalized_slots)]


def slot_count_for_numbers(numbers: Sequence[int]) -> int:
    """Return the supported calendar size implied by draw numbers."""

    if not numbers:
        return 8
    highest_number = max(int(number) for number in numbers)
    if highest_number <= 8 and len(numbers) <= 8:
        return 8
    if highest_number <= 10 and len(numbers) <= 10:
        return 10
    raise ValueError(f"Unsupported draw numbers for phase calendar: {tuple(numbers)!r}")


def _normalize_phase_name(phase_name: str) -> str:
    normalized = str(phase_name or "primera_fase").strip().casefold()
    if normalized in {"primera_fase", "primera", "first"}:
        return "primera_fase"
    if normalized in {"segona_fase", "segona", "second"}:
        return "segona_fase"
    raise ValueError(f"Unsupported phase name: {phase_name!r}")


def _normalize_slot_count(slot_count: int) -> int:
    value = int(slot_count)
    if value not in {8, 10}:
        raise ValueError(f"Unsupported phase slot count: {slot_count!r}")
    return value


def build_disposicions(
    fase: Sequence[Sequence[Match]],
    slot_count: int | None = None,
) -> list[list[str]]:
    if slot_count is None:
        slot_count = max((max(match) for jornada in fase for match in jornada), default=8)
    slot_count = _normalize_slot_count(slot_count)
    disposicions: list[list[str]] = [[] for _ in range(slot_count)]

    for jornada in fase:
        for casa, fora in jornada:
            if 1 <= casa <= slot_count:
                disposicions[casa - 1].append("casa")
            if 1 <= fora <= slot_count:
                disposicions[fora - 1].append("fora")

    return disposicions
