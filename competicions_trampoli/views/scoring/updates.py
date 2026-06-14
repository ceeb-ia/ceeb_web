from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET

from ...models import Competicio
from ...models.competicio import CompeticioAparell
from ...models.scoring import ScoreEntry, TeamScoreEntry
from ...services.shared.incremental_feeds import FeedCursor, parse_feed_cursor
from ...services.scoring.schema_resolution import resolve_scoring_schema_for_comp_aparell
from ...services.inscripcions.admission import filter_score_entries_admeses
from ...services.scoring.team_scoring import is_team_context_app
from ...services.scoring.team_subject_contract import build_team_subject_registry, filter_team_subject_ids_for_serie
from .helpers import (
    _allowed_input_codes_for_schema,
    _logical_team_input_codes,
    _serialize_individual_scoring_update,
    _serialize_team_scoring_update,
)


SCORING_UPDATES_LIMIT = 500
SCORING_FEED_SOURCE_SCORE = "score"
SCORING_FEED_SOURCE_TEAM = "team"


def _combined_source_rank(source: str) -> int:
    return 0 if source == SCORING_FEED_SOURCE_SCORE else 1


def _parse_combined_after_id(raw_after_id: str) -> tuple[str, int | None]:
    text = str(raw_after_id or "").strip()
    if ":" not in text:
        return "", None
    source, raw_id = text.split(":", 1)
    try:
        parsed_id = int(raw_id)
    except Exception:
        return "", None
    return str(source or "").strip(), parsed_id


def _apply_combined_cursor(qs, cursor: FeedCursor, *, source: str):
    if cursor.dt is None:
        return qs

    after_source, after_id = _parse_combined_after_id(cursor.after_id)
    if after_source == source and after_id is not None:
        return qs.filter(
            Q(updated_at__gt=cursor.dt)
            | Q(updated_at=cursor.dt, id__gt=after_id)
        )
    if after_source == SCORING_FEED_SOURCE_SCORE and source == SCORING_FEED_SOURCE_TEAM:
        return qs.filter(
            Q(updated_at__gt=cursor.dt)
            | Q(updated_at=cursor.dt)
        )
    return qs.filter(updated_at__gt=cursor.dt)


def _combined_feed_meta(rows: list[dict], *, limit: int, cursor: FeedCursor) -> dict:
    page = rows[:limit]
    has_more = len(rows) > limit
    if page:
        last_row = page[-1]
        next_since = last_row["sort_updated_at"].isoformat() if last_row.get("sort_updated_at") else None
        next_after_id = f"{last_row.get('sort_source')}:{last_row.get('sort_id')}"
    else:
        next_since = cursor.dt.isoformat() if cursor.dt else None
        next_after_id = cursor.after_id
    return {
        "page": page,
        "has_more": has_more,
        "next_since": next_since,
        "next_after_id": str(next_after_id or ""),
    }


def _collect_team_scoring_updates(competicio, cursor: FeedCursor, *, comp_aparell_id=None, exercici=None, serie_id=None) -> list[dict]:
    team_apps_qs = (
        CompeticioAparell.objects
        .filter(competicio=competicio, actiu=True)
        .select_related("aparell")
    )
    if comp_aparell_id:
        team_apps_qs = team_apps_qs.filter(pk=comp_aparell_id)
    team_apps = [app for app in team_apps_qs if is_team_context_app(app)]
    if not team_apps:
        return []

    team_app_ids = [int(app.id) for app in team_apps]
    allowed_inputs_by_app = {}
    subject_meta_by_app = {}
    allowed_team_ids_by_app = {}
    for app in team_apps:
        registry = build_team_subject_registry(competicio, app)
        subject_meta_by_app[int(app.id)] = registry["all_by_id"]
        if comp_aparell_id and str(app.id) == str(comp_aparell_id):
            allowed_team_ids_by_app[int(app.id)] = set(
                filter_team_subject_ids_for_serie(registry["all_by_id"], serie_id)
            )
        else:
            allowed_team_ids_by_app[int(app.id)] = set(registry["all_by_id"].keys())
        _schema_obj, schema = resolve_scoring_schema_for_comp_aparell(app)
        allowed_inputs_by_app[int(app.id)] = _logical_team_input_codes(schema or {})

    qs = (
        TeamScoreEntry.objects
        .filter(
            competicio=competicio,
            comp_aparell_id__in=team_app_ids,
            fase__isnull=True,
        )
        .select_related("team_subject")
        .order_by("updated_at", "id")
    )
    qs = _apply_combined_cursor(qs, cursor, source=SCORING_FEED_SOURCE_TEAM)
    if exercici:
        try:
            qs = qs.filter(exercici=int(exercici))
        except Exception:
            pass

    updates = []
    for entry in qs[: SCORING_UPDATES_LIMIT + 1]:
        app_id = int(entry.comp_aparell_id)
        if int(entry.team_subject_id) not in allowed_team_ids_by_app.get(app_id, set()):
            continue
        updates.append(
            {
                "payload": _serialize_team_scoring_update(
                    entry,
                    allowed_inputs=allowed_inputs_by_app.get(app_id, set()),
                    subject_meta=(subject_meta_by_app.get(app_id, {}) or {}).get(int(entry.team_subject_id), {}),
                ),
                "sort_updated_at": entry.updated_at,
                "sort_id": int(entry.id),
                "sort_source": SCORING_FEED_SOURCE_TEAM,
            }
        )
    return updates


@require_GET
def scoring_updates(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)

    cursor = parse_feed_cursor(request)
    comp_aparell_id = request.GET.get("comp_aparell_id")
    exercici = request.GET.get("exercici")
    group = request.GET.get("group")
    serie_id = request.GET.get("serie_id")

    if cursor.dt is None:
        return JsonResponse(
            {
                "ok": True,
                "now": None,
                "updates": [],
                "next_since": None,
                "next_after_id": "",
                "has_more": False,
            }
        )

    rows = []
    allowed_inputs_by_app = {}
    qs = filter_score_entries_admeses(ScoreEntry.objects.filter(competicio=competicio, fase__isnull=True))

    if comp_aparell_id:
        qs = qs.filter(comp_aparell_id=comp_aparell_id)
    if exercici:
        try:
            qs = qs.filter(exercici=int(exercici))
        except Exception:
            pass
    if group is not None:
        try:
            qs = qs.filter(inscripcio__grup_competicio_id=int(group))
        except Exception:
            pass

    qs = _apply_combined_cursor(qs.order_by("updated_at", "id"), cursor, source=SCORING_FEED_SOURCE_SCORE)

    for score_entry in qs.select_related("inscripcio")[: SCORING_UPDATES_LIMIT + 1]:
        if int(score_entry.comp_aparell_id) not in allowed_inputs_by_app:
            comp_aparell = CompeticioAparell.objects.filter(pk=score_entry.comp_aparell_id, competicio=competicio).first()
            _schema_obj, schema = resolve_scoring_schema_for_comp_aparell(comp_aparell) if comp_aparell else (None, {})
            allowed_inputs_by_app[int(score_entry.comp_aparell_id)] = _allowed_input_codes_for_schema(
                schema or {},
                comp_aparell,
            )
        rows.append(
            {
                "payload": _serialize_individual_scoring_update(
                    score_entry,
                    allowed_inputs=allowed_inputs_by_app.get(int(score_entry.comp_aparell_id), set()),
                ),
                "sort_updated_at": score_entry.updated_at,
                "sort_id": int(score_entry.id),
                "sort_source": SCORING_FEED_SOURCE_SCORE,
            }
        )

    rows.extend(
        _collect_team_scoring_updates(
            competicio,
            cursor,
            comp_aparell_id=comp_aparell_id,
            exercici=exercici,
            serie_id=serie_id if comp_aparell_id else None,
        )
    )

    rows.sort(key=lambda row: (row["sort_updated_at"], _combined_source_rank(row["sort_source"]), row["sort_id"]))
    feed_meta = _combined_feed_meta(rows, limit=SCORING_UPDATES_LIMIT, cursor=cursor)
    return JsonResponse(
        {
            "ok": True,
            "now": feed_meta["next_since"],
            "updates": [row["payload"] for row in feed_meta["page"]],
            "next_since": feed_meta["next_since"],
            "next_after_id": feed_meta["next_after_id"],
            "has_more": feed_meta["has_more"],
        }
    )
