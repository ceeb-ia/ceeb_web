"""Final plot generation for resource-solver runs."""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any
import unicodedata

from calendaritzacions.engine.variants.resource_solver.audit import build_linkage_audit
from calendaritzacions.engine.variants.resource_solver.types import (
    ResourceSolverResult,
    SolverContext,
)


LEVEL_ORDER = ["A", "B", "B-C", "C", "Sense nivell"]


def write_resource_solver_final_plots(
    output_dir: str | Path,
    *,
    result: ResourceSolverResult,
    context: SolverContext,
    stem: str = "resource_solver",
    fmt: str = "png",
    dpi: int = 160,
) -> dict[str, str]:
    """Write final resource-solver plots and return plot-id to path mapping."""

    import matplotlib

    matplotlib.use("Agg")

    import matplotlib.pyplot as plt

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    plots: dict[str, str] = {}
    plot_specs = [
        ("group_sizes", _plot_group_sizes(result)),
        ("resource_excess", _plot_resource_excess(result)),
        ("entity_conflicts", _plot_entity_conflicts(result)),
        ("assigned_numbers_by_modality", _plot_assigned_numbers_by_modality(result, context)),
        ("level_dispersion_by_modality", _plot_level_dispersion_by_modality(result, context)),
        ("linkage_compliance", _plot_linkage_compliance(result, context)),
        ("status_summary", _plot_status_summary(result, context)),
    ]

    for plot_id, fig in plot_specs:
        if fig is None:
            continue
        file_path = output_path / f"{stem}_{plot_id}.{fmt}"
        fig.savefig(file_path, dpi=dpi, bbox_inches="tight")
        plt.close(fig)
        plots[plot_id] = str(file_path)

    manifest_path = output_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "artifact_type": "resource_solver_final_plots",
                "plots": plots,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    plots["manifest"] = str(manifest_path)
    return plots


def _plot_group_sizes(result: ResourceSolverResult) -> Any | None:
    if not result.group_summary:
        return None
    import matplotlib.pyplot as plt

    labels = [_display_group_id(summary.group_id) for summary in result.group_summary]
    sizes = [len(summary.assigned_numbers) for summary in result.group_summary]
    empty = [len(summary.empty_numbers) for summary in result.group_summary]

    fig, ax = plt.subplots(figsize=(max(7, 0.45 * len(labels)), 4.8))
    ax.bar(labels, sizes, label="Equips", color="#4E79A7")
    ax.bar(labels, empty, bottom=sizes, label="Descansos", color="#BAB0AC")
    ax.set_title("Mida dels grups")
    ax.set_xlabel("Grup")
    ax.set_ylabel("Slots")
    ax.set_ylim(0, 8)
    ax.legend(loc="upper right")
    ax.tick_params(axis="x", rotation=45)
    return fig


def _plot_resource_excess(result: ResourceSolverResult) -> Any | None:
    rows = [usage for usage in result.resource_usage if usage.locals_count or usage.excess]
    if not rows:
        return None
    import matplotlib.pyplot as plt

    rows = sorted(rows, key=lambda usage: (usage.excess, usage.locals_count), reverse=True)[:30]
    labels = [_short_resource_id(usage.resource_id) for usage in rows]
    locals_count = [usage.locals_count for usage in rows]
    capacity = [usage.capacity for usage in rows]

    fig, ax = plt.subplots(figsize=(11, max(5, 0.35 * len(rows))))
    y_pos = range(len(rows))
    ax.barh(y_pos, locals_count, color="#E15759", label="Locals assignats")
    ax.scatter(capacity, y_pos, color="#222222", marker="|", s=130, label="Capacitat")
    ax.set_yticks(list(y_pos), labels)
    ax.invert_yaxis()
    ax.set_title("Pressio final de recursos")
    ax.set_xlabel("Partits locals")
    ax.legend(loc="lower right")
    return fig


def _plot_entity_conflicts(result: ResourceSolverResult) -> Any | None:
    if not result.entity_excess:
        return None
    import matplotlib.pyplot as plt

    totals = Counter()
    for (entity, _group_id), excess in result.entity_excess.items():
        totals[str(entity)] += int(excess)
    rows = totals.most_common(25)
    if not rows:
        return None

    labels = [entity for entity, _value in rows]
    values = [value for _entity, value in rows]

    fig, ax = plt.subplots(figsize=(10, max(5, 0.35 * len(rows))))
    y_pos = range(len(rows))
    ax.barh(y_pos, values, color="#F28E2B")
    ax.set_yticks(list(y_pos), labels)
    ax.invert_yaxis()
    ax.set_title("Conflictes d'entitat finals")
    ax.set_xlabel("Exces d'equips compartint grup")
    return fig


def _plot_status_summary(result: ResourceSolverResult, context: SolverContext) -> Any | None:
    import matplotlib.pyplot as plt

    linkage_summary = build_linkage_audit(result, context).get("summary", {})
    metrics = {
        "Equips": len(context.teams),
        "Assignats": len(result.assignments),
        "Grups": len(context.groups),
        "Partits": len(result.real_matches),
        "Exces recursos": sum(int(usage.excess) for usage in result.resource_usage),
        "Exces entitats": sum(int(value) for value in result.entity_excess.values()),
    }
    if int(linkage_summary.get("groups", 0) or 0):
        metrics["Linkage violations"] = int(linkage_summary.get("violations", 0) or 0)
    fig, ax = plt.subplots(figsize=(9, 4.8))
    colors = ["#4E79A7", "#59A14F", "#76B7B2", "#EDC948", "#E15759", "#F28E2B", "#B07AA1"]
    ax.bar(metrics.keys(), metrics.values(), color=colors[: len(metrics)])
    ax.set_title(f"Resum final solver: {result.status}")
    ax.set_ylabel("Valor")
    ax.tick_params(axis="x", rotation=30)
    return fig


def _plot_linkage_compliance(result: ResourceSolverResult, context: SolverContext) -> Any | None:
    linkage = build_linkage_audit(result, context)
    summary = linkage.get("summary", {})
    if not int(summary.get("groups", 0) or 0):
        return None
    import matplotlib.pyplot as plt

    ok_pairs = int(summary.get("ok_pairs", 0) or 0)
    violations = int(summary.get("violations", 0) or 0)
    unchecked = sum(
        1
        for group in linkage.get("groups", [])
        if isinstance(group, dict) and int(group.get("checked_pairs", 0) or 0) == 0
    )
    labels = ["OK pairs", "Violations"]
    values = [ok_pairs, violations]
    colors = ["#59A14F", "#E15759"]
    if unchecked:
        labels.append("Unchecked groups")
        values.append(unchecked)
        colors.append("#BAB0AC")

    fig, ax = plt.subplots(figsize=(7.5, 4.8))
    ax.bar(labels, values, color=colors)
    ax.set_title("Linkage compliance")
    ax.set_ylabel("Count")
    ax.grid(axis="y", alpha=0.25)
    return fig


def _plot_assigned_numbers_by_modality(result: ResourceSolverResult, context: SolverContext) -> Any | None:
    if not result.assignments:
        return None
    import matplotlib.pyplot as plt

    modality_by_team = {
        team.team_id: (team.modality.strip() or "Sense modalitat")
        for team in context.teams
    }
    counts: Counter[tuple[str, int]] = Counter()
    totals: Counter[str] = Counter()
    for assignment in result.assignments:
        modality = modality_by_team.get(assignment.team_id, "Sense modalitat")
        counts[(modality, int(assignment.number))] += 1
        totals[modality] += 1

    modalities = [modality for modality, _total in totals.most_common(12)]
    if not modalities:
        return None

    cols = min(3, len(modalities))
    rows = math.ceil(len(modalities) / cols)
    fig, axes = plt.subplots(rows, cols, figsize=(4.6 * cols, 3.8 * rows))
    try:
        axes = axes.flatten()
    except AttributeError:
        axes = [axes]

    palette = ["#4E79A7", "#F28E2B", "#E15759", "#76B7B2", "#59A14F", "#EDC948", "#B07AA1", "#FF9DA7"]
    for ax, modality in zip(axes, modalities):
        labels = []
        values = []
        for number in range(1, 9):
            count = counts.get((modality, number), 0)
            if count:
                labels.append(str(number))
                values.append(count)
        if not values:
            ax.axis("off")
            continue
        ax.pie(values, labels=labels, autopct="%1.0f%%", startangle=90, colors=palette[: len(values)], textprops={"fontsize": 8})
        ax.set_title(str(modality), fontsize=10)
    for ax in axes[len(modalities):]:
        ax.axis("off")
    fig.suptitle("Assignacio final de numeros per modalitat", fontsize=13)
    fig.tight_layout()
    return fig


def _plot_level_dispersion_by_modality(result: ResourceSolverResult, context: SolverContext) -> Any | None:
    if not result.assignments or not context.teams:
        return None
    import matplotlib.pyplot as plt

    team_by_id = {team.team_id: team for team in context.teams}
    counts: Counter[tuple[str, str, str]] = Counter()
    totals: Counter[str] = Counter()
    group_totals: Counter[tuple[str, str]] = Counter()
    for assignment in result.assignments:
        team = team_by_id.get(assignment.team_id)
        if team is None:
            continue
        modality = team.modality.strip() or "Sense modalitat"
        group_id = _display_group_id(assignment.group_id)
        level = _normalize_level_label(team.level)
        counts[(modality, group_id, level)] += 1
        totals[modality] += 1
        group_totals[(modality, group_id)] += 1

    modalities = [modality for modality, _total in totals.most_common(12)]
    if not modalities:
        return None

    cols = min(2, len(modalities))
    rows = math.ceil(len(modalities) / cols)
    fig, axes = plt.subplots(rows, cols, figsize=(6.2 * cols, 4.2 * rows))
    try:
        axes = axes.flatten()
    except AttributeError:
        axes = [axes]

    colors = {"A": "#4E79A7", "B": "#59A14F", "B-C": "#EDC948", "C": "#E15759", "Sense nivell": "#BAB0AC"}
    for ax, modality in zip(axes, modalities):
        groups = sorted(
            {group for item_modality, group in group_totals if item_modality == modality},
            key=_group_sort_key,
        )
        if not groups:
            ax.axis("off")
            continue
        left = [0] * len(groups)
        for level in LEVEL_ORDER:
            values = [counts.get((modality, group, level), 0) for group in groups]
            if not any(values):
                continue
            ax.barh(groups, values, left=left, label=level, color=colors.get(level, "#76B7B2"))
            left = [current + value for current, value in zip(left, values)]
        ax.set_title(str(modality), fontsize=10)
        ax.set_xlabel("Equips assignats")
        ax.grid(axis="x", alpha=0.25)
        ax.invert_yaxis()
    for ax in axes[len(modalities):]:
        ax.axis("off")

    handles, labels = axes[0].get_legend_handles_labels()
    if handles:
        fig.legend(handles, labels, loc="lower center", ncol=min(len(labels), len(LEVEL_ORDER)))
    fig.suptitle("Dispersio final de nivells normalitzats per modalitat", fontsize=13)
    fig.tight_layout(rect=(0, 0.08, 1, 0.96))
    return fig


def _normalize_level_label(value: Any) -> str:
    if value is None:
        return "Sense nivell"
    text = str(value).strip()
    if not text:
        return "Sense nivell"
    key = unicodedata.normalize("NFKD", text.casefold())
    key = "".join(char for char in key if not unicodedata.combining(char)).upper()
    if re.search(r"\bB\s*[-/]\s*C\b", key):
        return "B-C"
    match = re.search(r"\b([A-E])\b", key)
    if not match:
        match = re.search(r"(?:NIVELL\s*)?([A-E])\s*$", key)
    if not match:
        return "Sense nivell"
    return {"A": "A", "B": "B", "C": "B-C", "D": "B-C", "E": "C"}[match.group(1)]


def _group_sort_key(value: Any) -> tuple[int, str]:
    text = str(value)
    match = re.search(r"(\d+)$", text)
    return (int(match.group(1)) if match else 999_999, text)


def _display_group_id(group_id: str) -> str:
    text = str(group_id)
    if "_G" in text:
        return "G" + text.rsplit("_G", 1)[1]
    return text


def _short_resource_id(resource_id: str) -> str:
    return str(resource_id).replace("|", " · ")


__all__ = ["write_resource_solver_final_plots"]
