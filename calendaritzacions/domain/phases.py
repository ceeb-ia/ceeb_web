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


def build_disposicions(fase: Sequence[Sequence[Match]]) -> list[list[str]]:
    disposicions: list[list[str]] = [[] for _ in range(8)]

    for jornada in fase:
        for casa, fora in jornada:
            if 1 <= casa <= 8:
                disposicions[casa - 1].append("casa")
            if 1 <= fora <= 8:
                disposicions[fora - 1].append("fora")

    return disposicions

