from __future__ import annotations

from typing import Any


def _to_position(value: Any) -> int | None:
    if value is None:
        return None
    try:
        if value != value:
            return None
    except Exception:
        pass
    try:
        parsed = int(float(str(value).strip().replace(",", ".")))
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def match_classification_importance(pos_local: Any, pos_visitant: Any) -> float:
    """Return a 0..1 importance signal from standings positions.

    High-table matches and close standings matches are more demanding. Missing
    or unresolved positions are neutral because classification data is external.
    """
    local = _to_position(pos_local)
    visitor = _to_position(pos_visitant)
    if local is None or visitor is None:
        return 0.0

    best = min(local, visitor)
    total = local + visitor
    gap = abs(local - visitor)

    table_score = max(0.0, 1.0 - ((total - 3.0) / 17.0))
    top_bonus = 0.25 if best <= 3 else 0.0
    closeness_bonus = 0.2 if gap <= 1 else 0.1 if gap <= 2 else 0.0
    return max(0.0, min(1.0, table_score + top_bonus + closeness_bonus))


def package_classification_importance(rows: list[Any], row_get) -> float:
    if not rows:
        return 0.0
    return max(
        match_classification_importance(
            row_get(row, "Posició Equip Local", row_get(row, "Posicio Equip Local")),
            row_get(row, "Posició Equip Visitant", row_get(row, "Posicio Equip Visitant")),
        )
        for row in rows
    )


def weighted_coverage(match_count: int, classification_importance: float, *, max_bonus: float = 0.4) -> float:
    return float(match_count) + max(0.0, min(1.0, float(classification_importance or 0.0))) * float(max_bonus)

