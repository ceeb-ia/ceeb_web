from dataclasses import dataclass, field
from typing import Any, Mapping


PROVENANCE_STAGE_RAW = "raw"
PROVENANCE_STAGE_CANDIDATE_SOURCE = "candidate_source"
PROVENANCE_STAGE_EXERCISE_SELECTION = "exercise_selection"
PROVENANCE_STAGE_MEMBER_SELECTION = "member_selection"

ALLOWED_PROVENANCE_STAGES = (
    PROVENANCE_STAGE_RAW,
    PROVENANCE_STAGE_CANDIDATE_SOURCE,
    PROVENANCE_STAGE_EXERCISE_SELECTION,
    PROVENANCE_STAGE_MEMBER_SELECTION,
)


@dataclass(frozen=True)
class RawRow:
    row_id: str
    app_id: int | None
    exercici: int | None
    participant_kind: str
    participant_id: int | None
    value: float | None = None
    by_camp: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DerivedRow:
    row_id: str
    stage: str
    app_id: int | None
    exercici: int | None
    participant_kind: str
    participant_id: int | None
    value: float | None = None
    by_camp: Mapping[str, Any] = field(default_factory=dict)
    source_row_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class SelectionSnapshot:
    snapshot_id: str
    stage: str
    app_id: int | None
    subject_kind: str
    subject_id: str
    selected_row_ids: tuple[str, ...] = ()
