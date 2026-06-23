"""Decomposition plot generation for resource-solver runs."""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


TOP_COMPONENTS = 20
TOP_HEATMAP_ITEMS = 15
MAX_HUB_CUT_COMPONENTS = 6
MAX_HUB_CUT_NETWORK_NODES = 120
MAX_HUB_CUT_LABELS = 38
MAX_HUB_CUT_MATRIX_NODES = 18
MAX_BETWEENNESS_EXACT_NODES = 260
MAX_BETWEENNESS_SAMPLE_NODES = 90
MAX_COMPONENT_NETWORKS = 12
MAX_FULL_NETWORK_NODES = 120
MAX_FULL_NETWORK_LABELS = 45
MAX_INTERACTIVE_COMPONENTS = 12
MAX_INTERACTIVE_GRAPH_NODES = 700
INTERACTIVE_TEAM_NODE_SHARE = 0.35


def write_resource_solver_decomposition_plots(
    output_dir: str | Path,
    *,
    summary: Any,
    context: Any | None = None,
    stem: str = "resource_solver_decomposition",
    fmt: str = "png",
    dpi: int = 160,
) -> dict[str, str]:
    """Write decomposition plots and return a plot-id to path mapping."""

    import matplotlib

    matplotlib.use("Agg")

    import matplotlib.pyplot as plt
    plt.rcParams["figure.max_open_warning"] = 0

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    components = _normalise_components(summary)
    plots: dict[str, str] = {}
    plot_specs = [
        ("component_team_count_histogram", _plot_component_team_count_histogram(components)),
        ("top_components_by_teams", _plot_top_components_by_teams(components)),
        ("components_resources_vs_competitions", _plot_components_resources_vs_competitions(components)),
        ("candidate_pareto_by_component", _plot_candidate_pareto_by_component(components)),
    ]

    largest = _largest_component(components)
    if context is not None and largest is not None:
        plot_specs.append(("initial_hub_concentration_heatmap", _plot_initial_hub_concentration_heatmap(components, context)))
        hub_cut_diagnostics = _build_hub_cut_diagnostics(components, context)
        plot_specs.extend(_hub_cut_plot_specs(hub_cut_diagnostics))
        plot_specs.append(
            (
                "top_component_competition_resource_heatmap",
                _plot_top_component_competition_resource_heatmap(largest, context),
            )
        )
        plot_specs.append(("top_component_network", _plot_top_component_network(largest, context)))
        plot_specs.extend(_component_network_plot_specs(components, context))

    for plot_id, fig in plot_specs:
        if fig is None:
            continue
        suffix = ""
        if plot_id.startswith("top_component_") and largest is not None:
            suffix = f"_{_safe_component_id(largest['component_id'])}"
        file_path = output_path / f"{stem}_{plot_id}{suffix}.{fmt}"
        fig.savefig(file_path, dpi=dpi, bbox_inches="tight")
        plt.close(fig)
        plots[plot_id] = str(file_path)

    if context is not None:
        interactive_path = _write_interactive_dependency_graph(
            output_path / f"{stem}_component_graph_3d.html",
            components,
            context,
        )
        if interactive_path is not None:
            plots["component_graph_3d"] = str(interactive_path)

    manifest_path = output_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "artifact_type": "resource_solver_decomposition_plots",
                "hub_cut_diagnostics": _write_hub_cut_diagnostics(output_path, stem, hub_cut_diagnostics)
                if context is not None and largest is not None
                else "",
                "plots": plots,
                "plot_descriptions": _plot_descriptions(plots),
                "notes": [
                    "Els plots component_network_* mostren nodes tipats i arestes de dependencia.",
                    "Els plots hub_cut_* mostren punts d'acoblament interns dels components inicials grans.",
                    "El plot component_graph_3d es un HTML interactiu amb rotacio, zoom i seleccio de nodes.",
                    "Els components molt grans es resumeixen per evitar imatges illegibles.",
                ],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    plots["manifest"] = str(manifest_path)
    return plots


def _plot_component_team_count_histogram(components: list[dict[str, Any]]) -> Any | None:
    if not components:
        return None
    import matplotlib.pyplot as plt

    team_counts = [max(0, int(component["team_count"])) for component in components]
    upper = max(team_counts) if team_counts else 0
    if upper <= 10:
        bins = range(0, upper + 2)
    else:
        bin_count = min(12, max(4, math.ceil(math.sqrt(len(team_counts)))))
        bins = [round(value) for value in _linspace(0, upper, bin_count + 1)]

    fig, ax = plt.subplots(figsize=(8.5, 4.8))
    ax.hist(team_counts, bins=list(bins), color="#4E79A7", edgecolor="#ffffff")
    ax.set_title("Distribucio de mida dels components")
    ax.set_xlabel("Equips per component")
    ax.set_ylabel("Components")
    ax.grid(axis="y", alpha=0.25)
    return fig


def _plot_top_components_by_teams(components: list[dict[str, Any]]) -> Any | None:
    rows = sorted(components, key=lambda item: (item["team_count"], item["candidate_count"]), reverse=True)[:TOP_COMPONENTS]
    if not rows:
        return None
    import matplotlib.pyplot as plt

    labels = [_short_label(component["component_id"]) for component in rows]
    metrics = [
        ("Equips", "team_count", "#4E79A7"),
        ("Competicions", "competition_count", "#59A14F"),
        ("Recursos", "resource_count", "#F28E2B"),
        ("Linkages", "linkage_count", "#B07AA1"),
        ("Candidats", "candidate_count", "#E15759"),
    ]
    y_pos = list(range(len(rows)))
    left = [0] * len(rows)

    fig, ax = plt.subplots(figsize=(11, max(5, 0.36 * len(rows))))
    for label, field, color in metrics:
        values = [int(component[field]) for component in rows]
        if not any(values):
            continue
        ax.barh(y_pos, values, left=left, label=label, color=color)
        left = [current + value for current, value in zip(left, values)]
    ax.set_yticks(y_pos, labels)
    ax.invert_yaxis()
    ax.set_title("Components principals per volum")
    ax.set_xlabel("Comptadors")
    ax.legend(loc="lower right")
    ax.grid(axis="x", alpha=0.2)
    return fig


def _plot_components_resources_vs_competitions(components: list[dict[str, Any]]) -> Any | None:
    if not components:
        return None
    import matplotlib.pyplot as plt

    x_values = [int(component["resource_count"]) for component in components]
    y_values = [int(component["competition_count"]) for component in components]
    sizes = [max(35, int(component["team_count"]) * 18) for component in components]
    colors = [int(component["candidate_count"]) for component in components]

    fig, ax = plt.subplots(figsize=(8.5, 5.2))
    scatter = ax.scatter(x_values, y_values, s=sizes, c=colors, cmap="viridis", alpha=0.72, edgecolors="#222222", linewidths=0.4)
    ax.set_title("Recursos vs competicions per component")
    ax.set_xlabel("Recursos")
    ax.set_ylabel("Competicions")
    ax.grid(alpha=0.25)
    colorbar = fig.colorbar(scatter, ax=ax)
    colorbar.set_label("Candidats")
    for component, x_value, y_value in zip(components, x_values, y_values):
        if int(component["team_count"]) == max(int(item["team_count"]) for item in components):
            ax.annotate(_short_label(component["component_id"]), (x_value, y_value), xytext=(5, 5), textcoords="offset points", fontsize=8)
    return fig


def _plot_candidate_pareto_by_component(components: list[dict[str, Any]]) -> Any | None:
    rows = sorted(components, key=lambda item: item["candidate_count"], reverse=True)
    if not rows or not any(int(component["candidate_count"]) for component in rows):
        return None
    import matplotlib.pyplot as plt

    rows = rows[:TOP_COMPONENTS]
    labels = [_short_label(component["component_id"]) for component in rows]
    values = [int(component["candidate_count"]) for component in rows]
    total = sum(int(component["candidate_count"]) for component in components)
    cumulative = []
    running = 0
    for value in values:
        running += value
        cumulative.append((running / total) * 100 if total else 0)

    fig, ax = plt.subplots(figsize=(max(9, 0.45 * len(rows)), 5))
    ax.bar(labels, values, color="#4E79A7")
    ax.set_title("Pareto de candidats per component")
    ax.set_xlabel("Component")
    ax.set_ylabel("Candidats")
    ax.tick_params(axis="x", rotation=45)
    ax.grid(axis="y", alpha=0.25)

    line_ax = ax.twinx()
    line_ax.plot(labels, cumulative, color="#E15759", marker="o", linewidth=2)
    line_ax.axhline(80, color="#777777", linestyle="--", linewidth=1)
    line_ax.set_ylabel("Candidats acumulats (%)")
    line_ax.set_ylim(0, 105)
    return fig


def _plot_initial_hub_concentration_heatmap(components: list[dict[str, Any]], context: Any) -> Any | None:
    rows, attractors, matrix = _initial_hub_concentration_matrix(components, context)
    if not rows or not attractors:
        return None
    import matplotlib.pyplot as plt

    values = [[matrix.get((component["component_id"], attractor["node_id"]), 0) for attractor in attractors] for component in rows]
    fig, ax = plt.subplots(figsize=(max(10, 0.48 * len(attractors)), max(5.5, 0.36 * len(rows))))
    image = ax.imshow(values, aspect="auto", cmap="YlOrRd")
    ax.set_title("Concentracio inicial de hubs del graf")
    ax.set_xlabel("Node atractor")
    ax.set_ylabel("Component inicial")
    ax.set_xticks(
        range(len(attractors)),
        [
            f"{_node_kind_short_label(attractor['kind'])}: {_short_label(attractor['label'], max_len=24)}"
            for attractor in attractors
        ],
        rotation=45,
        ha="right",
    )
    ax.set_yticks(
        range(len(rows)),
        [
            f"{_short_label(component['component_id'], max_len=10)} ({int(component['team_count'])} eq.)"
            for component in rows
        ],
    )
    colorbar = fig.colorbar(image, ax=ax)
    colorbar.set_label("Connexions equip-node")

    for row_index, row_values in enumerate(values):
        for column_index, value in enumerate(row_values):
            if value <= 0:
                continue
            ax.text(
                column_index,
                row_index,
                str(value),
                ha="center",
                va="center",
                fontsize=7,
                color="#111111" if value < max(max(items) for items in values) * 0.55 else "#ffffff",
            )
    return fig


def _hub_cut_plot_specs(diagnostics: dict[str, Any]) -> list[tuple[str, Any | None]]:
    specs: list[tuple[str, Any | None]] = []
    for hub in diagnostics.get("hubs", ())[:MAX_HUB_CUT_COMPONENTS]:
        component_id = _safe_component_id(hub.get("component_id", "hub"))
        specs.append((f"hub_cut_network_{component_id}", _plot_hub_cut_network(hub)))
        specs.append((f"hub_cut_ranking_{component_id}", _plot_hub_cut_ranking(hub)))
        specs.append((f"hub_cut_matrix_{component_id}", _plot_hub_cut_matrix(hub)))
    return specs


def _plot_hub_cut_network(hub: dict[str, Any]) -> Any | None:
    graph = hub.get("graph") or {}
    nodes = graph.get("nodes") or {}
    edges = graph.get("edges") or []
    if not nodes or not edges:
        return None
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    selected = set(_selected_hub_cut_network_nodes(hub))
    if not selected:
        return None
    selected_edges = [
        edge
        for edge in edges
        if edge.get("source") in selected and edge.get("target") in selected
    ]
    if not selected_edges:
        return None

    selected_nodes = {node_id: nodes[node_id] for node_id in selected if node_id in nodes}
    layout_edges = [(edge["source"], edge["target"], edge.get("kind", "")) for edge in selected_edges]
    positions = _dependency_network_layout(selected_nodes, layout_edges)
    metrics = {row["node_id"]: row for row in hub.get("node_metrics", ())}
    max_weight = max(float(edge.get("weight", 1) or 1) for edge in selected_edges)
    max_betweenness = max((float(row.get("betweenness", 0) or 0) for row in metrics.values()), default=0.0)

    fig, ax = plt.subplots(figsize=(12, 8.2))
    for edge in selected_edges:
        source = edge["source"]
        target = edge["target"]
        if source not in positions or target not in positions:
            continue
        x1, y1 = positions[source]
        x2, y2 = positions[target]
        weight = float(edge.get("weight", 1) or 1)
        ax.plot(
            [x1, x2],
            [y1, y2],
            color=_edge_color(str(edge.get("kind") or "")),
            linewidth=0.45 + 2.8 * (weight / max_weight),
            alpha=0.22 + 0.26 * (weight / max_weight),
            zorder=1,
        )

    for kind in ("competition", "resource", "linkage", "level", "team"):
        node_ids = [node_id for node_id, node in selected_nodes.items() if node.get("kind") == kind]
        if not node_ids:
            continue
        xs = [positions[node_id][0] for node_id in node_ids]
        ys = [positions[node_id][1] for node_id in node_ids]
        sizes = []
        edge_colors = []
        widths = []
        for node_id in node_ids:
            row = metrics.get(node_id, {})
            sizes.append(70 + min(780, float(row.get("weighted_degree", 0) or 0) * 18))
            is_cut = bool(row.get("is_articulation"))
            betweenness = float(row.get("betweenness", 0) or 0)
            edge_colors.append("#D62728" if is_cut or (max_betweenness and betweenness >= max_betweenness * 0.5) else "#ffffff")
            widths.append(1.8 if is_cut else 0.8)
        ax.scatter(
            xs,
            ys,
            s=sizes,
            color=_node_color(kind),
            edgecolors=edge_colors,
            linewidths=widths,
            alpha=0.92,
            label=_node_kind_label(kind),
            zorder=3,
        )

    label_nodes = _label_hub_cut_nodes(selected_nodes, metrics)
    for node_id in label_nodes:
        if node_id not in positions:
            continue
        x_pos, y_pos = positions[node_id]
        node = selected_nodes[node_id]
        row = metrics.get(node_id, {})
        prefix = "*" if row.get("is_articulation") else ""
        ax.text(
            x_pos,
            y_pos + 0.026,
            prefix + _short_label(node.get("label", node_id), max_len=24 if node.get("kind") != "team" else 13),
            ha="center",
            va="bottom",
            fontsize=7,
            color="#222222",
            zorder=4,
        )

    legend_items = [
        Line2D([0], [0], marker="o", color="w", label=_node_kind_label(kind), markerfacecolor=_node_color(kind), markersize=8)
        for kind in ("competition", "resource", "linkage", "level", "team")
        if any(node.get("kind") == kind for node in selected_nodes.values())
    ]
    if legend_items:
        ax.legend(handles=legend_items, loc="lower center", ncol=min(5, len(legend_items)), frameon=False)
    ax.set_title(
        f"Entramat intra-hub {hub.get('component_id')} - "
        f"{hub.get('team_count', 0)} equips, "
        f"{len(nodes)} nodes, {len(edges)} arestes"
    )
    ax.set_xlim(-1.08, 1.08)
    ax.set_ylim(-1.08, 1.08)
    ax.axis("off")
    return fig


def _plot_hub_cut_ranking(hub: dict[str, Any]) -> Any | None:
    rows = [
        row
        for row in hub.get("node_metrics", ())
        if row.get("kind") != "team"
    ][:TOP_COMPONENTS]
    if not rows:
        return None
    import matplotlib.pyplot as plt

    labels = [
        f"{_node_kind_short_label(row.get('kind', ''))}: {_short_label(row.get('label', row.get('node_id')), max_len=34)}"
        for row in rows
    ]
    values = [float(row.get("cut_score", 0) or 0) for row in rows]
    colors = [_node_color(str(row.get("kind") or "")) for row in rows]
    y_pos = list(range(len(rows)))

    fig, ax = plt.subplots(figsize=(11.5, max(5, 0.36 * len(rows))))
    ax.barh(y_pos, values, color=colors)
    ax.set_yticks(y_pos, labels)
    ax.invert_yaxis()
    ax.set_title(f"Ranking de punts febles intra-hub {hub.get('component_id')}")
    ax.set_xlabel("Cut score = betweenness + cut_gain + grau ponderat normalitzat")
    ax.grid(axis="x", alpha=0.22)
    for index, row in enumerate(rows):
        text = (
            f"b={float(row.get('betweenness', 0) or 0):.2f} "
            f"wd={float(row.get('weighted_degree', 0) or 0):.0f} "
            f"gain={int(row.get('cut_gain', 0) or 0)} "
            f"eq={int(row.get('affected_team_count', 0) or 0)}"
        )
        ax.text(values[index] + max(values or [1]) * 0.01, index, text, va="center", fontsize=7)
    return fig


def _plot_hub_cut_matrix(hub: dict[str, Any]) -> Any | None:
    matrix_payload = hub.get("cooccurrence_matrix") or {}
    nodes = matrix_payload.get("nodes") or []
    values = matrix_payload.get("values") or []
    if not nodes or not values:
        return None
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(max(8, 0.42 * len(nodes)), max(6, 0.38 * len(nodes))))
    image = ax.imshow(values, aspect="auto", cmap="PuBuGn")
    labels = [
        f"{_node_kind_short_label(node.get('kind', ''))}: {_short_label(node.get('label', node.get('node_id')), max_len=22)}"
        for node in nodes
    ]
    ax.set_title(f"Coocurrencia de nodes atractors {hub.get('component_id')}")
    ax.set_xticks(range(len(nodes)), labels, rotation=45, ha="right")
    ax.set_yticks(range(len(nodes)), labels)
    colorbar = fig.colorbar(image, ax=ax)
    colorbar.set_label("Equips connectats als dos nodes")
    return fig


def _plot_top_component_competition_resource_heatmap(component: dict[str, Any], context: Any) -> Any | None:
    matrix = _component_competition_resource_counts(component, context)
    if not matrix:
        return None
    import matplotlib.pyplot as plt

    competition_totals = Counter()
    resource_totals = Counter()
    for (competition, resource), count in matrix.items():
        competition_totals[competition] += count
        resource_totals[resource] += count
    competitions = [label for label, _count in competition_totals.most_common(TOP_HEATMAP_ITEMS)]
    resources = [label for label, _count in resource_totals.most_common(TOP_HEATMAP_ITEMS)]
    if not competitions or not resources:
        return None

    values = [[matrix.get((competition, resource), 0) for resource in resources] for competition in competitions]
    fig, ax = plt.subplots(figsize=(max(8, 0.45 * len(resources)), max(5, 0.35 * len(competitions))))
    image = ax.imshow(values, aspect="auto", cmap="YlGnBu")
    ax.set_title(f"Competicio-recurs del component {_short_label(component['component_id'])}")
    ax.set_xlabel("Recurs")
    ax.set_ylabel("Competicio")
    ax.set_xticks(range(len(resources)), [_short_label(resource, max_len=24) for resource in resources], rotation=45, ha="right")
    ax.set_yticks(range(len(competitions)), [_short_label(competition, max_len=32) for competition in competitions])
    colorbar = fig.colorbar(image, ax=ax)
    colorbar.set_label("Equips")
    return fig


def _plot_top_component_network(component: dict[str, Any], context: Any) -> Any | None:
    edges = _component_competition_resource_counts(component, context)
    if not edges:
        return None
    competition_totals = Counter()
    resource_totals = Counter()
    for (competition, resource), count in edges.items():
        competition_totals[competition] += count
        resource_totals[resource] += count
    competitions = [label for label, _count in competition_totals.most_common(8)]
    resources = [label for label, _count in resource_totals.most_common(8)]
    visible_edges = {
        (competition, resource): count
        for (competition, resource), count in edges.items()
        if competition in competitions and resource in resources
    }
    if not visible_edges or len(competitions) + len(resources) > 16:
        return None
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(10, max(5, 0.45 * max(len(competitions), len(resources)))))
    comp_y = _spread_positions(len(competitions))
    res_y = _spread_positions(len(resources))
    comp_pos = {competition: (0.05, y) for competition, y in zip(competitions, comp_y)}
    res_pos = {resource: (0.95, y) for resource, y in zip(resources, res_y)}
    max_count = max(visible_edges.values())

    for (competition, resource), count in visible_edges.items():
        ax.plot(
            [comp_pos[competition][0], res_pos[resource][0]],
            [comp_pos[competition][1], res_pos[resource][1]],
            color="#9E9E9E",
            linewidth=0.7 + 3.0 * (count / max_count),
            alpha=0.55,
        )
    for competition, (x_pos, y_pos) in comp_pos.items():
        ax.scatter([x_pos], [y_pos], s=180, color="#4E79A7", zorder=3)
        ax.text(x_pos + 0.025, y_pos, _short_label(competition, max_len=28), va="center", ha="left", fontsize=8)
    for resource, (x_pos, y_pos) in res_pos.items():
        ax.scatter([x_pos], [y_pos], s=180, color="#F28E2B", zorder=3)
        ax.text(x_pos - 0.025, y_pos, _short_label(resource, max_len=28), va="center", ha="right", fontsize=8)
    ax.set_title(f"Xarxa reduida del component {_short_label(component['component_id'])}")
    ax.set_xlim(0, 1)
    ax.set_ylim(-0.08, 1.08)
    ax.axis("off")
    return fig


def _component_network_plot_specs(
    components: list[dict[str, Any]],
    context: Any,
) -> list[tuple[str, Any | None]]:
    specs: list[tuple[str, Any | None]] = []
    for component in components[:MAX_COMPONENT_NETWORKS]:
        component_id = _safe_component_id(component["component_id"])
        graph = _component_dependency_graph(component, context)
        if not graph["nodes"]:
            continue
        if len(graph["nodes"]) <= MAX_FULL_NETWORK_NODES:
            specs.append((f"component_network_{component_id}", _plot_component_dependency_network(component, graph)))
        else:
            specs.append((f"component_bridge_network_{component_id}", _plot_component_bridge_network(component, context)))
    return specs


def _plot_component_dependency_network(component: dict[str, Any], graph: dict[str, Any]) -> Any | None:
    nodes = graph["nodes"]
    edges = graph["edges"]
    if not nodes or not edges:
        return None
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    positions = _dependency_network_layout(nodes, edges)
    degrees = Counter()
    for left, right, _kind in edges:
        degrees[left] += 1
        degrees[right] += 1

    fig_width = 11 if len(nodes) < 70 else 13
    fig_height = max(6, min(12, 0.1 * len(nodes) + 4.5))
    fig, ax = plt.subplots(figsize=(fig_width, fig_height))

    for left, right, kind in edges:
        x1, y1 = positions[left]
        x2, y2 = positions[right]
        ax.plot(
            [x1, x2],
            [y1, y2],
            color=_edge_color(kind),
            linewidth=0.7,
            alpha=0.34,
            zorder=1,
        )

    for kind in ("competition", "resource", "linkage", "team"):
        kind_nodes = [node_id for node_id, node in nodes.items() if node["kind"] == kind]
        if not kind_nodes:
            continue
        xs = [positions[node_id][0] for node_id in kind_nodes]
        ys = [positions[node_id][1] for node_id in kind_nodes]
        sizes = [_node_size(kind, degrees[node_id]) for node_id in kind_nodes]
        ax.scatter(
            xs,
            ys,
            s=sizes,
            color=_node_color(kind),
            edgecolors="#ffffff",
            linewidths=0.7,
            alpha=0.92,
            label=_node_kind_label(kind),
            zorder=3,
        )

    label_nodes = _label_nodes_for_network(nodes, degrees)
    for node_id in label_nodes:
        x_pos, y_pos = positions[node_id]
        node = nodes[node_id]
        ax.text(
            x_pos,
            y_pos + 0.025,
            _short_label(node["label"], max_len=28 if node["kind"] != "team" else 14),
            ha="center",
            va="bottom",
            fontsize=7 if len(label_nodes) > 25 else 8,
            color="#222222",
            zorder=4,
        )

    legend_items = [
        Line2D([0], [0], marker="o", color="w", label=_node_kind_label(kind), markerfacecolor=_node_color(kind), markersize=8)
        for kind in ("competition", "resource", "linkage", "team")
        if any(node["kind"] == kind for node in nodes.values())
    ]
    ax.legend(handles=legend_items, loc="lower center", ncol=min(4, len(legend_items)), frameon=False)
    ax.set_title(
        "Xarxa de dependencies "
        f"{component['component_id']} - {component['team_count']} equips, "
        f"{component['competition_count']} competicions, {component['resource_count']} recursos"
    )
    ax.set_xlim(-1.08, 1.08)
    ax.set_ylim(-1.08, 1.08)
    ax.axis("off")
    return fig


def _plot_component_bridge_network(component: dict[str, Any], context: Any) -> Any | None:
    fig = _plot_top_component_network(component, context)
    if fig is None:
        return None
    return fig


def _write_interactive_dependency_graph(
    file_path: Path,
    components: list[dict[str, Any]],
    context: Any,
) -> Path | None:
    payload = _interactive_dependency_graph_payload(components, context)
    if not payload["components"]:
        return None
    file_path.write_text(_interactive_dependency_graph_html(payload), encoding="utf-8")
    return file_path


def _interactive_dependency_graph_payload(
    components: list[dict[str, Any]],
    context: Any,
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for component in components[:MAX_INTERACTIVE_COMPONENTS]:
        graph = _component_dependency_graph(component, context)
        if not graph["nodes"] or not graph["edges"]:
            continue
        limited_graph, omitted = _limit_interactive_graph(graph, MAX_INTERACTIVE_GRAPH_NODES)
        items.append(
            {
                "id": component["component_id"],
                "label": _short_label(component["component_id"], max_len=32),
                "team_count": int(component["team_count"]),
                "competition_count": int(component["competition_count"]),
                "resource_count": int(component["resource_count"]),
                "linkage_count": int(component["linkage_count"]),
                "candidate_count": int(component["candidate_count"]),
                "omitted_nodes": omitted,
                "nodes": _interactive_nodes_payload(limited_graph["nodes"], limited_graph["edges"]),
                "links": [
                    {"source": left, "target": right, "kind": kind}
                    for left, right, kind in limited_graph["edges"]
                    if left in limited_graph["nodes"] and right in limited_graph["nodes"]
                ],
            }
        )
    return {
        "artifact_type": "resource_solver_dependency_graph_3d",
        "components": items,
        "legend": {
            "competition": _node_kind_label("competition"),
            "resource": _node_kind_label("resource"),
            "linkage": _node_kind_label("linkage"),
            "team": _node_kind_label("team"),
        },
    }


def _limit_interactive_graph(graph: dict[str, Any], max_nodes: int) -> tuple[dict[str, Any], int]:
    nodes = graph["nodes"]
    edges = graph["edges"]
    if len(nodes) <= max_nodes:
        return graph, 0

    degrees = Counter()
    for left, right, _kind in edges:
        degrees[left] += 1
        degrees[right] += 1

    selected = _balanced_interactive_node_sample(nodes, degrees, max_nodes)
    return (
        {
            "nodes": {node_id: nodes[node_id] for node_id in sorted(selected)},
            "edges": [
                (left, right, kind)
                for left, right, kind in edges
                if left in selected and right in selected
            ],
        },
        len(nodes) - len(selected),
    )


def _balanced_interactive_node_sample(
    nodes: dict[str, dict[str, str]],
    degrees: Counter[str],
    max_nodes: int,
) -> set[str]:
    by_kind: dict[str, list[str]] = defaultdict(list)
    for node_id, node in nodes.items():
        by_kind[str(node.get("kind") or "")].append(node_id)

    def ordered(node_ids: list[str]) -> list[str]:
        return sorted(
            node_ids,
            key=lambda node_id: (
                -degrees[node_id],
                str(nodes[node_id].get("label") or ""),
                node_id,
            ),
        )

    selected: set[str] = set()
    team_quota = min(len(by_kind.get("team", ())), max(1, int(max_nodes * INTERACTIVE_TEAM_NODE_SHARE)))
    for node_id in ordered(by_kind.get("team", []))[:team_quota]:
        selected.add(node_id)

    other_kinds = ["competition", "resource", "linkage"]
    remaining = max_nodes - len(selected)
    non_empty_kinds = [kind for kind in other_kinds if by_kind.get(kind)]
    if non_empty_kinds and remaining > 0:
        base_quota = max(1, remaining // len(non_empty_kinds))
        for kind in non_empty_kinds:
            for node_id in ordered(by_kind[kind])[:base_quota]:
                if len(selected) >= max_nodes:
                    break
                selected.add(node_id)

    remaining_nodes = [
        node_id
        for node_id in nodes
        if node_id not in selected
    ]
    for node_id in sorted(
        remaining_nodes,
        key=lambda item: (
            -degrees[item],
            str(nodes[item].get("kind") or ""),
            str(nodes[item].get("label") or ""),
            item,
        ),
    ):
        if len(selected) >= max_nodes:
            break
        selected.add(node_id)

    return selected


def _interactive_nodes_payload(
    nodes: dict[str, dict[str, str]],
    edges: list[tuple[str, str, str]],
) -> list[dict[str, Any]]:
    degrees = Counter()
    for left, right, _kind in edges:
        degrees[left] += 1
        degrees[right] += 1
    return [
        {
            "id": node_id,
            "kind": node["kind"],
            "key": node["key"],
            "label": node["label"],
            "degree": degrees[node_id],
        }
        for node_id, node in sorted(nodes.items(), key=lambda item: (item[1]["kind"], item[1]["label"], item[0]))
    ]


def _interactive_dependency_graph_html(payload: dict[str, Any]) -> str:
    payload_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return f"""<!doctype html>
<html lang="ca">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Graf 3D de dependencies</title>
  <style>
    html, body {{ height: 100%; margin: 0; }}
    body {{ background: #f6f8fb; color: #1f2937; font-family: Arial, sans-serif; overflow: hidden; }}
    .shell {{ display: grid; grid-template-columns: 280px 1fr 320px; height: 100%; }}
    .panel {{ background: #fff; border-right: 1px solid #d9e0e8; box-sizing: border-box; padding: 14px; overflow: auto; }}
    .detail {{ border-left: 1px solid #d9e0e8; border-right: 0; }}
    h1 {{ font-size: 18px; line-height: 1.2; margin: 0 0 12px; }}
    h2 {{ font-size: 13px; margin: 16px 0 8px; text-transform: uppercase; color: #596579; }}
    label {{ display: block; font-size: 12px; font-weight: 700; margin: 12px 0 5px; }}
    select, input {{ box-sizing: border-box; width: 100%; border: 1px solid #cdd5df; border-radius: 6px; padding: 7px 8px; }}
    .checks label {{ align-items: center; display: flex; gap: 6px; font-weight: 400; margin: 7px 0; }}
    .checks input {{ width: auto; }}
    .stats {{ display: grid; gap: 6px; grid-template-columns: 1fr 1fr; }}
    .stat {{ background: #f8fafc; border: 1px solid #e3e8ef; border-radius: 6px; padding: 8px; }}
    .stat b {{ display: block; font-size: 16px; }}
    .stat span {{ color: #697586; font-size: 11px; }}
    .canvas-wrap {{ position: relative; min-width: 0; }}
    canvas {{ display: block; height: 100%; width: 100%; }}
    .hud {{ background: rgba(255,255,255,.9); border: 1px solid #d9e0e8; border-radius: 8px; left: 14px; padding: 8px 10px; position: absolute; top: 14px; }}
    .hud div {{ font-size: 12px; line-height: 1.45; }}
    .legend {{ display: grid; gap: 6px; }}
    .legend-row {{ align-items: center; display: flex; gap: 8px; font-size: 13px; }}
    .dot {{ border-radius: 999px; display: inline-block; height: 12px; width: 12px; }}
    .muted {{ color: #697586; font-size: 12px; line-height: 1.4; }}
    .detail-card {{ background: #f8fafc; border: 1px solid #e3e8ef; border-radius: 8px; padding: 10px; }}
    .detail-card div {{ overflow-wrap: anywhere; }}
    .btn-row {{ display: flex; gap: 8px; margin-top: 12px; }}
    button {{ background: #fff; border: 1px solid #cdd5df; border-radius: 6px; cursor: pointer; padding: 7px 9px; }}
    button.primary {{ background: #2f6f9f; border-color: #2f6f9f; color: #fff; }}
    @media (max-width: 900px) {{ .shell {{ grid-template-columns: 1fr; grid-template-rows: auto 1fr auto; }} .panel {{ max-height: 28vh; }} .detail {{ border-left: 0; border-top: 1px solid #d9e0e8; }} }}
  </style>
</head>
<body>
  <div class="shell">
    <aside class="panel">
      <h1>Graf 3D de dependencies</h1>
      <label for="componentSelect">Component</label>
      <select id="componentSelect"></select>
      <label for="searchBox">Cerca</label>
      <input id="searchBox" placeholder="Equip, competicio, recurs...">
      <h2>Tipus de node</h2>
      <div class="checks" id="kindChecks"></div>
      <div class="btn-row">
        <button class="primary" id="resetView" type="button">Recentrar</button>
        <button id="pauseLayout" type="button">Pausar</button>
      </div>
      <h2>Component</h2>
      <div class="stats" id="stats"></div>
      <p class="muted" id="truncatedNote"></p>
    </aside>
    <main class="canvas-wrap">
      <canvas id="graphCanvas"></canvas>
      <div class="hud">
        <div>Arrossega: mou</div>
        <div>Maj + arrossega: rota</div>
        <div>Roda: zoom</div>
        <div>Click: selecciona node</div>
      </div>
    </main>
    <aside class="panel detail">
      <h2>Seleccio</h2>
      <div class="detail-card" id="detail">Clica un node per veure'n el detall.</div>
      <h2>Llegenda</h2>
      <div class="legend" id="legend"></div>
    </aside>
  </div>
  <script id="graph-data" type="application/json">{payload_json}</script>
  <script>
  (function(){{
    var payload = JSON.parse(document.getElementById('graph-data').textContent);
    var colors = {{ competition:'#4E79A7', resource:'#F28E2B', linkage:'#B07AA1', team:'#7b8794' }};
    var componentSelect = document.getElementById('componentSelect');
    var kindChecks = document.getElementById('kindChecks');
    var searchBox = document.getElementById('searchBox');
    var stats = document.getElementById('stats');
    var detail = document.getElementById('detail');
    var truncatedNote = document.getElementById('truncatedNote');
    var canvas = document.getElementById('graphCanvas');
    var ctx = canvas.getContext('2d');
    var component = null, nodes = [], links = [], visibleNodes = [], visibleLinks = [];
    var selected = null, hovered = null, paused = false;
    var zoom = 0.62, panX = 0, panY = 0, rotX = -0.35, rotY = 0.65, dragging = false, rotating = false, lastX = 0, lastY = 0;
    var kinds = {{ competition:true, resource:true, linkage:true, team:true }};

    payload.components.forEach(function(item, index){{
      var option = document.createElement('option');
      option.value = index;
      option.textContent = item.id + ' - ' + item.team_count + ' equips';
      componentSelect.appendChild(option);
    }});
    Object.keys(payload.legend).forEach(function(kind){{
      var label = document.createElement('label');
      label.innerHTML = '<input type="checkbox" data-kind="' + kind + '" checked> ' + payload.legend[kind];
      kindChecks.appendChild(label);
    }});
    Object.keys(payload.legend).forEach(function(kind){{
      var row = document.createElement('div');
      row.className = 'legend-row';
      row.innerHTML = '<span class="dot" style="background:' + colors[kind] + '"></span>' + payload.legend[kind];
      document.getElementById('legend').appendChild(row);
    }});

    function loadComponent(index){{
      component = payload.components[index];
      nodes = component.nodes.map(function(node, idx){{
        var phi = Math.acos(1 - 2 * ((idx + .5) / Math.max(1, component.nodes.length)));
        var theta = Math.PI * (1 + Math.sqrt(5)) * idx;
        return Object.assign({{
          x: Math.cos(theta) * Math.sin(phi),
          y: Math.sin(theta) * Math.sin(phi),
          z: Math.cos(phi),
          vx: 0, vy: 0, vz: 0
        }}, node);
      }});
      var byId = Object.fromEntries(nodes.map(function(node){{ return [node.id, node]; }}));
      links = component.links.map(function(link){{ return Object.assign({{ sourceNode: byId[link.source], targetNode: byId[link.target] }}, link); }}).filter(function(link){{ return link.sourceNode && link.targetNode; }});
      selected = null;
      updateStats();
      applyFilters();
      resetView();
    }}

    function updateStats(){{
      stats.innerHTML = [
        ['Equips', component.team_count],
        ['Competicions', component.competition_count],
        ['Recursos', component.resource_count],
        ['Linkages', component.linkage_count],
        ['Candidats', component.candidate_count],
        ['Nodes visibles', component.nodes.length]
      ].map(function(item){{ return '<div class="stat"><b>' + item[1] + '</b><span>' + item[0] + '</span></div>'; }}).join('');
      truncatedNote.textContent = component.omitted_nodes ? ('Mostra parcial: ' + component.omitted_nodes + ' nodes omesos per mantenir la vista fluida.') : '';
      detail.textContent = 'Clica un node per veure\\'n el detall.';
    }}

    function applyFilters(){{
      var query = searchBox.value.trim().toLowerCase();
      visibleNodes = nodes.filter(function(node){{
        return kinds[node.kind] && (!query || (node.label + ' ' + node.key).toLowerCase().indexOf(query) !== -1);
      }});
      var visibleIds = new Set(visibleNodes.map(function(node){{ return node.id; }}));
      visibleLinks = links.filter(function(link){{ return visibleIds.has(link.source) && visibleIds.has(link.target); }});
    }}

    function layoutStep(){{
      if (paused) return;
      var active = visibleNodes;
      var linkSet = visibleLinks;
      for (var i = 0; i < active.length; i++) {{
        var a = active[i];
        a.vx += -a.x * 0.002; a.vy += -a.y * 0.002; a.vz += -a.z * 0.002;
        for (var j = i + 1; j < active.length; j++) {{
          var b = active[j], dx = a.x - b.x, dy = a.y - b.y, dz = a.z - b.z;
          var d2 = Math.max(dx*dx + dy*dy + dz*dz, 0.01);
          var f = Math.min(0.018 / d2, 0.06);
          a.vx += dx*f; a.vy += dy*f; a.vz += dz*f;
          b.vx -= dx*f; b.vy -= dy*f; b.vz -= dz*f;
        }}
      }}
      linkSet.forEach(function(link){{
        var a = link.sourceNode, b = link.targetNode;
        var dx = b.x - a.x, dy = b.y - a.y, dz = b.z - a.z;
        var f = 0.006;
        a.vx += dx*f; a.vy += dy*f; a.vz += dz*f;
        b.vx -= dx*f; b.vy -= dy*f; b.vz -= dz*f;
      }});
      active.forEach(function(n){{
        n.x += n.vx; n.y += n.vy; n.z += n.vz;
        n.vx *= .86; n.vy *= .86; n.vz *= .86;
      }});
    }}

    function graphFrame(){{
      if (!visibleNodes.length) return {{ cx: 0, cy: 0, cz: 0, radius: 1 }};
      var cx = 0, cy = 0, cz = 0;
      visibleNodes.forEach(function(node){{ cx += node.x; cy += node.y; cz += node.z; }});
      cx /= visibleNodes.length; cy /= visibleNodes.length; cz /= visibleNodes.length;
      var radius = 0;
      visibleNodes.forEach(function(node){{
        radius = Math.max(radius, Math.hypot(node.x - cx, node.y - cy, node.z - cz));
      }});
      return {{ cx: cx, cy: cy, cz: cz, radius: Math.max(radius, 0.001) }};
    }}

    function project(node, frame){{
      frame = frame || graphFrame();
      var nx = (node.x - frame.cx) / frame.radius;
      var ny = (node.y - frame.cy) / frame.radius;
      var nz = (node.z - frame.cz) / frame.radius;
      var cx = Math.cos(rotX), sx = Math.sin(rotX), cy = Math.cos(rotY), sy = Math.sin(rotY);
      var x = nx * cy + nz * sy;
      var z = -nx * sy + nz * cy;
      var y = ny * cx - z * sx;
      z = ny * sx + z * cx;
      var scale = Math.min(canvas.width, canvas.height) * 0.22 * zoom;
      var cameraDistance = 5.0;
      var p = cameraDistance / Math.max(0.8, cameraDistance + z);
      return {{ x: canvas.width/2 + panX + x*scale*p, y: canvas.height/2 + panY + y*scale*p, z:z, p:p }};
    }}

    function draw(){{
      resize();
      layoutStep();
      ctx.clearRect(0,0,canvas.width,canvas.height);
      var frame = graphFrame();
      var projected = new Map();
      visibleNodes.forEach(function(node){{ projected.set(node.id, project(node, frame)); }});
      visibleLinks.forEach(function(link){{
        var a = projected.get(link.source), b = projected.get(link.target);
        if (!a || !b) return;
        ctx.strokeStyle = selected && (link.source === selected.id || link.target === selected.id) ? '#20242a' : '#aab4c0';
        ctx.globalAlpha = selected && (link.source !== selected.id && link.target !== selected.id) ? .12 : .45;
        ctx.lineWidth = selected && (link.source === selected.id || link.target === selected.id) ? 1.8 : .8;
        ctx.beginPath(); ctx.moveTo(a.x,a.y); ctx.lineTo(b.x,b.y); ctx.stroke();
      }});
      ctx.globalAlpha = 1;
      visibleNodes.slice().sort(function(a,b){{ return projected.get(a.id).z - projected.get(b.id).z; }}).forEach(function(node){{
        var p = projected.get(node.id);
        var active = selected && (selected.id === node.id || visibleLinks.some(function(link){{ return (link.source === selected.id && link.target === node.id) || (link.target === selected.id && link.source === node.id); }}));
        var dim = selected && !active;
        var radius = Math.max(4, Math.min(13, 4 + Math.sqrt(node.degree + 1) * 2)) * p.p;
        ctx.globalAlpha = dim ? .25 : 1;
        ctx.fillStyle = colors[node.kind] || '#777';
        ctx.beginPath(); ctx.arc(p.x, p.y, radius, 0, Math.PI*2); ctx.fill();
        ctx.strokeStyle = node === selected ? '#111827' : '#fff';
        ctx.lineWidth = node === selected ? 3 : 1.2;
        ctx.stroke();
        if (node === selected || node === hovered || (active && node.kind !== 'team')) {{
          ctx.fillStyle = '#1f2937'; ctx.font = '12px Arial'; ctx.globalAlpha = 1;
          ctx.fillText(shortLabel(node.label, 28), p.x + radius + 4, p.y - radius);
        }}
      }});
      ctx.globalAlpha = 1;
      requestAnimationFrame(draw);
    }}

    function shortLabel(text, max){{ text = String(text || ''); return text.length <= max ? text : text.slice(0, max - 1) + '...'; }}
    function resize(){{
      var rect = canvas.getBoundingClientRect(), ratio = window.devicePixelRatio || 1;
      var w = Math.max(300, Math.floor(rect.width * ratio)), h = Math.max(300, Math.floor(rect.height * ratio));
      if (canvas.width !== w || canvas.height !== h) {{ canvas.width = w; canvas.height = h; }}
    }}
    function nodeAt(event){{
      var rect = canvas.getBoundingClientRect(), ratio = window.devicePixelRatio || 1;
      var x = (event.clientX - rect.left) * ratio, y = (event.clientY - rect.top) * ratio;
      var best = null, bestDist = 9999;
      var frame = graphFrame();
      visibleNodes.forEach(function(node){{
        var p = project(node, frame), r = Math.max(7, Math.min(15, 5 + Math.sqrt(node.degree + 1) * 2)) * p.p;
        var d = Math.hypot(p.x - x, p.y - y);
        if (d < r && d < bestDist) {{ best = node; bestDist = d; }}
      }});
      return best;
    }}
    function showDetail(node){{
      if (!node) return;
      detail.innerHTML = '<div><b>' + escapeHtml(node.label) + '</b></div>' +
        '<div class="muted">' + escapeHtml(payload.legend[node.kind] || node.kind) + '</div>' +
        '<hr><div><b>Clau</b></div><div>' + escapeHtml(node.key) + '</div>' +
        '<div style="margin-top:8px"><b>Grau</b>: ' + node.degree + '</div>';
    }}
    function escapeHtml(text){{ return String(text).replace(/[&<>"']/g, function(ch){{ return ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}})[ch]; }}); }}
    function resetView(){{ zoom = 0.62; panX = 0; panY = 0; rotX = -0.35; rotY = 0.65; }}

    componentSelect.addEventListener('change', function(){{ loadComponent(parseInt(componentSelect.value, 10)); }});
    searchBox.addEventListener('input', applyFilters);
    kindChecks.addEventListener('change', function(event){{
      var kind = event.target.getAttribute('data-kind');
      if (kind) {{ kinds[kind] = event.target.checked; applyFilters(); }}
    }});
    document.getElementById('resetView').addEventListener('click', resetView);
    document.getElementById('pauseLayout').addEventListener('click', function(event){{
      paused = !paused; event.target.textContent = paused ? 'Reprendre' : 'Pausar';
    }});
    canvas.addEventListener('mousedown', function(event){{ dragging = true; rotating = event.shiftKey || event.button === 1; lastX = event.clientX; lastY = event.clientY; }});
    window.addEventListener('mouseup', function(){{ dragging = false; rotating = false; }});
    canvas.addEventListener('mousemove', function(event){{
      hovered = nodeAt(event);
      if (!dragging) return;
      if (rotating || event.shiftKey) {{
        rotY += (event.clientX - lastX) * 0.008;
        rotX += (event.clientY - lastY) * 0.008;
      }} else {{
        var ratio = window.devicePixelRatio || 1;
        panX += (event.clientX - lastX) * ratio;
        panY += (event.clientY - lastY) * ratio;
      }}
      lastX = event.clientX; lastY = event.clientY;
    }});
    canvas.addEventListener('wheel', function(event){{ event.preventDefault(); zoom *= event.deltaY > 0 ? .9 : 1.1; zoom = Math.max(.001, Math.min(12, zoom)); }}, {{ passive:false }});
    canvas.addEventListener('click', function(event){{ selected = nodeAt(event); showDetail(selected); }});
    window.addEventListener('resize', resize);

    loadComponent(0);
    draw();
  }})();
  </script>
</body>
</html>
"""


def _component_dependency_graph(component: dict[str, Any], context: Any) -> dict[str, Any]:
    team_ids = set(component.get("team_ids") or ())
    if not team_ids:
        return {"nodes": {}, "edges": []}

    teams = [team for team in _sequence(_get(context, "teams")) if str(_get(team, "team_id", "")) in team_ids]
    nodes: dict[str, dict[str, str]] = {}
    edges: list[tuple[str, str, str]] = []

    def add_node(kind: str, key: str, label: str) -> str:
        node_id = f"{kind}:{key}"
        nodes.setdefault(node_id, {"kind": kind, "key": key, "label": label})
        return node_id

    for team in teams:
        team_id = str(_get(team, "team_id"))
        team_node = add_node("team", team_id, str(_get(team, "name", team_id) or team_id))

        competition_key = _competition_key_for_team(team)
        competition_node = add_node("competition", competition_key, _competition_label(team))
        edges.append((team_node, competition_node, "competition"))

        resource_key = _resource_key_for_team(team)
        resource_node = add_node("resource", resource_key, _resource_label_for_team(team, resource_key))
        edges.append((team_node, resource_node, "resource"))

    for linkage_key, linkage_team_ids in _component_linkage_groups(teams).items():
        linkage_node = add_node("linkage", linkage_key, _short_linkage_label(linkage_key))
        for team_id in linkage_team_ids:
            team_node = f"team:{team_id}"
            if team_node in nodes:
                edges.append((team_node, linkage_node, "linkage"))

    return {"nodes": nodes, "edges": sorted(set(edges))}


def _initial_hub_concentration_matrix(
    components: list[dict[str, Any]],
    context: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], Counter[tuple[str, str]]]:
    rows = sorted(
        components,
        key=lambda item: (int(item["team_count"]), int(item["candidate_count"]), item["component_id"]),
        reverse=True,
    )[:TOP_COMPONENTS]
    if not rows:
        return [], [], Counter()

    matrix: Counter[tuple[str, str]] = Counter()
    totals: Counter[str] = Counter()
    component_counts: Counter[str] = Counter()
    metadata: dict[str, dict[str, str]] = {}
    for component in rows:
        component_id = str(component["component_id"])
        graph = _component_dependency_graph(component, context)
        nodes = graph["nodes"]
        if not nodes:
            continue
        component_seen: set[str] = set()
        for left, right, _kind in graph["edges"]:
            for node_id in (left, right):
                node = nodes.get(node_id)
                if not node or node.get("kind") == "team":
                    continue
                metadata[node_id] = {
                    "node_id": node_id,
                    "kind": str(node.get("kind") or ""),
                    "label": str(node.get("label") or node.get("key") or node_id),
                }
                matrix[(component_id, node_id)] += 1
                totals[node_id] += 1
                component_seen.add(node_id)
        for node_id in component_seen:
            component_counts[node_id] += 1

    attractor_ids = sorted(
        totals,
        key=lambda node_id: (
            -component_counts[node_id],
            -totals[node_id],
            metadata.get(node_id, {}).get("kind", ""),
            metadata.get(node_id, {}).get("label", node_id),
        ),
    )[:TOP_HEATMAP_ITEMS]
    attractors = [metadata[node_id] for node_id in attractor_ids if node_id in metadata]
    active_rows = [
        component
        for component in rows
        if any(matrix.get((str(component["component_id"]), attractor["node_id"]), 0) for attractor in attractors)
    ]
    return active_rows, attractors, matrix


def _build_hub_cut_diagnostics(components: list[dict[str, Any]], context: Any) -> dict[str, Any]:
    hubs: list[dict[str, Any]] = []
    rows = sorted(
        components,
        key=lambda item: (int(item["team_count"]), int(item["candidate_count"]), item["component_id"]),
        reverse=True,
    )[:MAX_HUB_CUT_COMPONENTS]
    for component in rows:
        graph = _hub_cut_graph(component, context)
        if not graph["nodes"] or not graph["edges"]:
            continue
        metrics = _hub_cut_node_metrics(graph)
        cooccurrence = _hub_cut_cooccurrence_matrix(graph, metrics)
        hubs.append(
            {
                "component_id": component["component_id"],
                "team_count": int(component["team_count"]),
                "candidate_count": int(component["candidate_count"]),
                "node_count": len(graph["nodes"]),
                "edge_count": len(graph["edges"]),
                "betweenness_approximate": bool(metrics.get("_approximate")),
                "best_cut_nodes": [row for row in metrics["rows"] if row.get("kind") != "team"][:10],
                "node_metrics": metrics["rows"],
                "cooccurrence_matrix": cooccurrence,
                "graph": graph,
            }
        )
    return {
        "artifact_type": "resource_solver_hub_cut_diagnostics",
        "hub_count": len(hubs),
        "hubs": hubs,
        "notes": [
            "Betweenness exacta fins al llindar configurat; per grafs grans s'usa mostra determinista.",
            "cut_gain estima quants components addicionals apareixen si es retira aquell node.",
            "weighted_degree suma el pes de les arestes: recursos candidats poden pesar mes d'una vegada.",
        ],
    }


def _write_hub_cut_diagnostics(output_path: Path, stem: str, diagnostics: dict[str, Any]) -> str:
    if not diagnostics.get("hubs"):
        return ""
    path = output_path / f"{stem}_hub_cut_diagnostics.json"
    payload = {**diagnostics, "hubs": [_hub_without_plot_graph(hub) for hub in diagnostics.get("hubs", ())]}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return str(path)


def _hub_without_plot_graph(hub: dict[str, Any]) -> dict[str, Any]:
    graph = hub.get("graph") or {}
    graph_payload = {
        "nodes": list((graph.get("nodes") or {}).values()),
        "edges": graph.get("edges") or [],
    }
    return {**hub, "graph": graph_payload}


def _hub_cut_graph(component: dict[str, Any], context: Any) -> dict[str, Any]:
    team_ids = set(component.get("team_ids") or ())
    if not team_ids:
        return {"nodes": {}, "edges": []}

    teams = [team for team in _sequence(_get(context, "teams")) if str(_get(team, "team_id", "")) in team_ids]
    candidates = [candidate for candidate in _sequence(_get(context, "candidates")) if str(_get(candidate, "team_id", "")) in team_ids]
    nodes: dict[str, dict[str, str]] = {}
    edge_weights: Counter[tuple[str, str, str]] = Counter()

    def add_node(kind: str, key: str, label: str) -> str:
        node_id = f"{kind}:{key}"
        nodes.setdefault(node_id, {"node_id": node_id, "kind": kind, "key": key, "label": label})
        return node_id

    def add_edge(left: str, right: str, kind: str, weight: int = 1) -> None:
        if not left or not right or left == right:
            return
        source, target = sorted((left, right))
        edge_weights[(source, target, kind)] += max(1, int(weight or 1))

    team_node_by_id: dict[str, str] = {}
    for team in teams:
        team_id = str(_get(team, "team_id"))
        team_node = add_node("team", team_id, str(_get(team, "name", _get(team, "team_name", team_id)) or team_id))
        team_node_by_id[team_id] = team_node

        competition_key = _competition_key_for_team(team)
        competition_node = add_node("competition", competition_key, _competition_label(team))
        add_edge(team_node, competition_node, "competition")

        level_label = _level_family_label(_get(team, "level", ""))
        level_node = add_node("level", level_label, level_label)
        add_edge(team_node, level_node, "level")

    for linkage_key, linkage_team_ids in _component_linkage_groups(teams).items():
        linkage_node = add_node("linkage", linkage_key, _short_linkage_label(linkage_key))
        for team_id in linkage_team_ids:
            team_node = team_node_by_id.get(team_id)
            if team_node:
                add_edge(team_node, linkage_node, "linkage")

    for candidate in candidates:
        team_id = str(_get(candidate, "team_id", ""))
        team_node = team_node_by_id.get(team_id)
        if not team_node:
            continue
        for resource_id in _sequence(_get(candidate, "potential_resources")):
            resource_key = _base_resource_id(resource_id)
            resource_node = add_node("resource", resource_key, resource_key)
            add_edge(team_node, resource_node, "resource")

    edges = [
        {"source": source, "target": target, "kind": kind, "weight": weight}
        for (source, target, kind), weight in sorted(edge_weights.items())
    ]
    return {"nodes": nodes, "edges": edges}


def _hub_cut_node_metrics(graph: dict[str, Any]) -> dict[str, Any]:
    nodes = graph["nodes"]
    edges = graph["edges"]
    neighbours: dict[str, set[str]] = defaultdict(set)
    weighted_degree: Counter[str] = Counter()
    degree: Counter[str] = Counter()
    for edge in edges:
        source = str(edge["source"])
        target = str(edge["target"])
        weight = float(edge.get("weight", 1) or 1)
        neighbours[source].add(target)
        neighbours[target].add(source)
        degree[source] += 1
        degree[target] += 1
        weighted_degree[source] += weight
        weighted_degree[target] += weight

    betweenness, approximate = _betweenness_centrality(neighbours)
    articulation_points = _articulation_points(neighbours)
    baseline_components = _component_count_without_node(neighbours, "")
    max_weighted_degree = max((float(value) for value in weighted_degree.values()), default=1.0)
    max_betweenness = max((float(value) for value in betweenness.values()), default=1.0)

    rows: list[dict[str, Any]] = []
    for node_id, node in nodes.items():
        cut_components = _component_count_without_node(neighbours, node_id)
        cut_gain = max(0, cut_components - baseline_components)
        affected_teams = _affected_team_count(node_id, nodes, neighbours)
        b_value = float(betweenness.get(node_id, 0.0) or 0.0)
        wd_value = float(weighted_degree.get(node_id, 0.0) or 0.0)
        cut_score = (
            (b_value / max_betweenness if max_betweenness else 0.0) * 6.0
            + cut_gain * 2.0
            + (wd_value / max_weighted_degree if max_weighted_degree else 0.0)
        )
        rows.append(
            {
                "node_id": node_id,
                "kind": node.get("kind", ""),
                "key": node.get("key", ""),
                "label": node.get("label", node_id),
                "degree": int(degree.get(node_id, 0)),
                "weighted_degree": round(wd_value, 4),
                "betweenness": round(b_value, 6),
                "is_articulation": node_id in articulation_points,
                "cut_gain": cut_gain,
                "affected_team_count": affected_teams,
                "cut_score": round(cut_score, 6),
            }
        )
    rows.sort(
        key=lambda row: (
            -float(row["cut_score"]),
            row["kind"] == "team",
            -float(row["betweenness"]),
            -float(row["weighted_degree"]),
            str(row["label"]),
        )
    )
    return {"rows": rows, "_approximate": approximate}


def _hub_cut_cooccurrence_matrix(graph: dict[str, Any], metrics: dict[str, Any]) -> dict[str, Any]:
    nodes = graph["nodes"]
    neighbours: dict[str, set[str]] = defaultdict(set)
    for edge in graph["edges"]:
        source = str(edge["source"])
        target = str(edge["target"])
        neighbours[source].add(target)
        neighbours[target].add(source)

    ranked = [
        row
        for row in metrics["rows"]
        if row.get("kind") != "team"
    ][:MAX_HUB_CUT_MATRIX_NODES]
    if not ranked:
        return {"nodes": [], "values": []}
    node_ids = [row["node_id"] for row in ranked]

    team_neighbours: dict[str, set[str]] = {}
    for node_id in node_ids:
        team_neighbours[node_id] = {
            neighbour
            for neighbour in neighbours.get(node_id, set())
            if (nodes.get(neighbour) or {}).get("kind") == "team"
        }
    values = [
        [
            len(team_neighbours[left].intersection(team_neighbours[right]))
            for right in node_ids
        ]
        for left in node_ids
    ]
    return {
        "nodes": [
            {
                "node_id": row["node_id"],
                "kind": row["kind"],
                "label": row["label"],
            }
            for row in ranked
        ],
        "values": values,
    }


def _betweenness_centrality(neighbours: dict[str, set[str]]) -> tuple[dict[str, float], bool]:
    node_ids = sorted(neighbours)
    if not node_ids:
        return {}, False
    approximate = len(node_ids) > MAX_BETWEENNESS_EXACT_NODES
    sources = node_ids
    if approximate:
        ordered = sorted(node_ids, key=lambda node_id: (-len(neighbours.get(node_id, ())), node_id))
        head = ordered[: MAX_BETWEENNESS_SAMPLE_NODES // 2]
        stride = max(1, len(ordered) // max(1, MAX_BETWEENNESS_SAMPLE_NODES - len(head)))
        sampled = ordered[::stride][: max(0, MAX_BETWEENNESS_SAMPLE_NODES - len(head))]
        sources = sorted(set(head + sampled))

    centrality = {node_id: 0.0 for node_id in node_ids}
    for source in sources:
        stack: list[str] = []
        predecessors: dict[str, list[str]] = {node_id: [] for node_id in node_ids}
        sigma = dict.fromkeys(node_ids, 0.0)
        sigma[source] = 1.0
        distance = dict.fromkeys(node_ids, -1)
        distance[source] = 0
        queue = [source]
        for current in queue:
            stack.append(current)
            for neighbor in sorted(neighbours.get(current, ())):
                if distance[neighbor] < 0:
                    queue.append(neighbor)
                    distance[neighbor] = distance[current] + 1
                if distance[neighbor] == distance[current] + 1:
                    sigma[neighbor] += sigma[current]
                    predecessors[neighbor].append(current)
        dependency = dict.fromkeys(node_ids, 0.0)
        while stack:
            node_id = stack.pop()
            for predecessor in predecessors[node_id]:
                if sigma[node_id]:
                    dependency[predecessor] += (sigma[predecessor] / sigma[node_id]) * (1.0 + dependency[node_id])
            if node_id != source:
                centrality[node_id] += dependency[node_id]

    scale = 1.0
    node_count = len(node_ids)
    if approximate and sources:
        scale *= node_count / len(sources)
    if node_count > 2:
        scale *= 1.0 / ((node_count - 1) * (node_count - 2))
    for node_id in centrality:
        centrality[node_id] *= scale
    return centrality, approximate


def _articulation_points(neighbours: dict[str, set[str]]) -> set[str]:
    visited: set[str] = set()
    discovery: dict[str, int] = {}
    low: dict[str, int] = {}
    parent: dict[str, str | None] = {}
    points: set[str] = set()
    time = 0

    def visit(node_id: str) -> None:
        nonlocal time
        visited.add(node_id)
        discovery[node_id] = time
        low[node_id] = time
        time += 1
        child_count = 0
        for neighbor in sorted(neighbours.get(node_id, ())):
            if neighbor not in visited:
                parent[neighbor] = node_id
                child_count += 1
                visit(neighbor)
                low[node_id] = min(low[node_id], low[neighbor])
                if parent.get(node_id) is None and child_count > 1:
                    points.add(node_id)
                if parent.get(node_id) is not None and low[neighbor] >= discovery[node_id]:
                    points.add(node_id)
            elif neighbor != parent.get(node_id):
                low[node_id] = min(low[node_id], discovery[neighbor])

    for node_id in sorted(neighbours):
        if node_id in visited:
            continue
        parent[node_id] = None
        visit(node_id)
    return points


def _component_count_without_node(neighbours: dict[str, set[str]], removed: str) -> int:
    nodes = {node_id for node_id in neighbours if node_id != removed}
    if not nodes:
        return 0
    seen: set[str] = set()
    count = 0
    for start in sorted(nodes):
        if start in seen:
            continue
        count += 1
        queue = [start]
        seen.add(start)
        for current in queue:
            for neighbor in neighbours.get(current, ()):
                if neighbor == removed or neighbor in seen:
                    continue
                seen.add(neighbor)
                queue.append(neighbor)
    return count


def _affected_team_count(node_id: str, nodes: dict[str, dict[str, str]], neighbours: dict[str, set[str]]) -> int:
    if (nodes.get(node_id) or {}).get("kind") == "team":
        return 1
    return sum(1 for neighbor in neighbours.get(node_id, ()) if (nodes.get(neighbor) or {}).get("kind") == "team")


def _selected_hub_cut_network_nodes(hub: dict[str, Any]) -> list[str]:
    graph = hub.get("graph") or {}
    nodes = graph.get("nodes") or {}
    metrics = {row["node_id"]: row for row in hub.get("node_metrics", ())}
    non_team = [
        row["node_id"]
        for row in hub.get("node_metrics", ())
        if row.get("kind") != "team"
    ][:35]
    selected = set(non_team)
    neighbours: dict[str, set[str]] = defaultdict(set)
    for edge in graph.get("edges") or []:
        source = edge.get("source")
        target = edge.get("target")
        if source and target:
            neighbours[str(source)].add(str(target))
            neighbours[str(target)].add(str(source))
    team_candidates: set[str] = set()
    for node_id in selected:
        team_candidates.update(
            neighbor
            for neighbor in neighbours.get(node_id, ())
            if (nodes.get(neighbor) or {}).get("kind") == "team"
        )
    teams = sorted(
        team_candidates,
        key=lambda node_id: (
            -float(metrics.get(node_id, {}).get("weighted_degree", 0) or 0),
            node_id,
        ),
    )
    remaining = max(0, MAX_HUB_CUT_NETWORK_NODES - len(selected))
    selected.update(teams[:remaining])
    return sorted(selected)


def _label_hub_cut_nodes(nodes: dict[str, dict[str, str]], metrics: dict[str, dict[str, Any]]) -> list[str]:
    rows = sorted(
        (
            row
            for node_id, row in metrics.items()
            if node_id in nodes
        ),
        key=lambda row: (
            row.get("kind") == "team",
            not row.get("is_articulation"),
            -float(row.get("cut_score", 0) or 0),
            str(row.get("label", "")),
        ),
    )
    return [row["node_id"] for row in rows[:MAX_HUB_CUT_LABELS]]


def _dependency_network_layout(
    nodes: dict[str, dict[str, str]],
    edges: list[tuple[str, str, str]],
) -> dict[str, tuple[float, float]]:
    positions: dict[str, tuple[float, float]] = {}
    by_kind: dict[str, list[str]] = defaultdict(list)
    for node_id, node in sorted(nodes.items()):
        by_kind[node["kind"]].append(node_id)

    anchors = {
        "competition": (-0.82, 0.25),
        "resource": (0.82, 0.25),
        "linkage": (0.0, -0.82),
        "level": (-0.42, -0.58),
        "team": (0.0, 0.0),
    }
    for kind, node_ids in by_kind.items():
        cx, cy = anchors.get(kind, (0.0, 0.0))
        radius = 0.14 if len(node_ids) <= 1 else min(0.42, 0.08 + 0.018 * len(node_ids))
        for index, node_id in enumerate(node_ids):
            angle = (2 * math.pi * index / max(1, len(node_ids))) + _kind_angle_offset(kind)
            positions[node_id] = (
                cx + radius * math.cos(angle),
                cy + radius * math.sin(angle),
            )

    neighbours: dict[str, set[str]] = defaultdict(set)
    for left, right, _kind in edges:
        neighbours[left].add(right)
        neighbours[right].add(left)

    node_ids = list(nodes)
    for _iteration in range(70):
        updated = dict(positions)
        for node_id in node_ids:
            x_pos, y_pos = positions[node_id]
            kind = nodes[node_id]["kind"]
            anchor_x, anchor_y = anchors.get(kind, (0.0, 0.0))
            force_x = (anchor_x - x_pos) * 0.035
            force_y = (anchor_y - y_pos) * 0.035

            for other_id in node_ids:
                if other_id == node_id:
                    continue
                other_x, other_y = positions[other_id]
                dx = x_pos - other_x
                dy = y_pos - other_y
                dist_sq = max(dx * dx + dy * dy, 0.002)
                strength = 0.0018 / dist_sq
                force_x += dx * strength
                force_y += dy * strength

            for other_id in neighbours.get(node_id, ()):
                other_x, other_y = positions[other_id]
                force_x += (other_x - x_pos) * 0.012
                force_y += (other_y - y_pos) * 0.012

            updated[node_id] = (
                max(-0.98, min(0.98, x_pos + force_x)),
                max(-0.98, min(0.98, y_pos + force_y)),
            )
        positions = updated
    return positions


def _label_nodes_for_network(nodes: dict[str, dict[str, str]], degrees: Counter[str]) -> list[str]:
    important = [
        node_id
        for node_id, node in nodes.items()
        if node["kind"] in {"competition", "resource", "linkage"}
    ]
    remaining = [
        node_id
        for node_id, node in sorted(nodes.items(), key=lambda item: (-degrees[item[0]], item[0]))
        if node["kind"] == "team"
    ]
    return (important + remaining)[:MAX_FULL_NETWORK_LABELS]


def _component_linkage_groups(teams: list[Any]) -> dict[str, tuple[str, ...]]:
    buckets: dict[tuple[str, str], list[str]] = defaultdict(list)
    for team in teams:
        group = _normalize_linkage_group(_get(team, "linkage_group", ""))
        if not group or _is_indifferent_side(_get(team, "linkage_side", "")):
            continue
        venue = _normalize_text(_get(team, "venue", ""))
        buckets[(venue, group)].append(str(_get(team, "team_id")))
    return {
        f"venue|{venue}|linkage|{group}": tuple(sorted(team_ids))
        for (venue, group), team_ids in sorted(buckets.items())
        if len(team_ids) > 1
    }


def _normalise_components(summary: Any) -> list[dict[str, Any]]:
    raw_components = _extract_components(summary)
    components = [_normalise_component(component, index) for index, component in enumerate(raw_components, start=1)]
    return sorted(components, key=lambda item: (item["team_count"], item["candidate_count"], item["component_id"]), reverse=True)


def _extract_components(summary: Any) -> list[Any]:
    components = _get(summary, "components")
    if components is not None:
        return list(components.values()) if isinstance(components, dict) else list(components)

    by_size = _get(summary, "components_by_size")
    if by_size is None:
        return []
    if isinstance(by_size, list):
        return by_size
    if not isinstance(by_size, dict):
        return []

    extracted: list[Any] = []
    for size_key, value in by_size.items():
        if isinstance(value, int):
            for index in range(value):
                extracted.append({"component_id": f"size_{size_key}_{index + 1}", "team_count": _int_or_zero(size_key)})
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    item = {**item}
                    item.setdefault("team_count", _int_or_zero(size_key))
                extracted.append(item)
        elif isinstance(value, dict):
            item = {**value}
            item.setdefault("team_count", _int_or_zero(size_key))
            extracted.append(item)
    return extracted


def _normalise_component(component: Any, index: int) -> dict[str, Any]:
    team_ids = tuple(str(item) for item in _sequence(_get(component, "team_ids")))
    competition_keys = tuple(str(item) for item in _sequence(_get(component, "competition_keys", _get(component, "competitions"))))
    resource_ids = tuple(str(item) for item in _sequence(_get(component, "resource_ids", _get(component, "resources"))))
    linkage_keys = tuple(str(item) for item in _sequence(_get(component, "linkage_keys", _get(component, "linkages"))))
    candidates = _sequence(_get(component, "candidates"))
    candidate_ids = _sequence(_get(component, "candidate_ids"))
    return {
        "component_id": str(_get(component, "component_id", _get(component, "id", f"C{index:03d}"))),
        "team_count": _count_or_len(component, "team_count", team_ids),
        "competition_count": _count_or_len(component, "competition_count", competition_keys),
        "resource_count": _count_or_len(component, "resource_count", resource_ids),
        "linkage_count": _count_or_len(component, "linkage_count", linkage_keys),
        "candidate_count": _count_or_len(component, "candidate_count", candidate_ids or candidates),
        "team_ids": team_ids,
        "competition_keys": competition_keys,
        "resource_ids": resource_ids,
        "linkage_keys": linkage_keys,
    }


def _component_competition_resource_counts(component: dict[str, Any], context: Any) -> Counter[tuple[str, str]]:
    team_ids = set(component.get("team_ids") or ())
    allowed_resources = set(component.get("resource_ids") or ())
    if not team_ids and not allowed_resources:
        return Counter()

    teams = list(_sequence(_get(context, "teams")))
    candidates = list(_sequence(_get(context, "candidates")))
    competition_by_team = {str(_get(team, "team_id")): _competition_label(team) for team in teams}
    candidate_resources_by_team: dict[str, set[str]] = defaultdict(set)
    for candidate in candidates:
        team_id = str(_get(candidate, "team_id", ""))
        if team_ids and team_id not in team_ids:
            continue
        for resource_id in _sequence(_get(candidate, "potential_resources")):
            resource = str(resource_id)
            base_resource = _base_resource_id(resource)
            if allowed_resources and resource not in allowed_resources and base_resource not in allowed_resources:
                continue
            candidate_resources_by_team[team_id].add(base_resource)

    counts: Counter[tuple[str, str]] = Counter()
    for team_id, resources in candidate_resources_by_team.items():
        competition = competition_by_team.get(team_id)
        if not competition:
            continue
        for resource in resources:
            counts[(competition, resource)] += 1
    return counts


def _competition_label(team: Any) -> str:
    fields = [
        _get(team, "league_name"),
        _get(team, "modality"),
        _get(team, "category"),
        _get(team, "subcategory"),
    ]
    parts = [str(value).strip() for value in fields if str(value or "").strip()]
    return " / ".join(parts) if parts else str(_get(team, "team_id", "Sense competicio"))


def _largest_component(components: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not components:
        return None
    return max(components, key=lambda item: (int(item["team_count"]), int(item["candidate_count"])))


def _count_or_len(component: Any, field: str, sequence: Any) -> int:
    value = _get(component, field)
    if value is not None:
        return _int_or_zero(value)
    return len(sequence)


def _get(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def _sequence(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, dict):
        return tuple(value.values())
    try:
        return tuple(value)
    except TypeError:
        return (value,)


def _int_or_zero(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _short_label(value: Any, *, max_len: int = 18) -> str:
    text = str(value).replace("|", " / ")
    return text if len(text) <= max_len else f"{text[: max_len - 1]}..."


def _safe_component_id(value: Any) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in str(value)) or "component"


def _base_resource_id(value: Any) -> str:
    text = str(value)
    if "|J" in text:
        return text.rsplit("|J", 1)[0]
    return text


def _plot_descriptions(plots: dict[str, str]) -> dict[str, str]:
    descriptions: dict[str, str] = {}
    for plot_id in plots:
        if plot_id == "component_team_count_histogram":
            descriptions[plot_id] = "Distribucio del nombre d'equips per component."
        elif plot_id == "top_components_by_teams":
            descriptions[plot_id] = "Ranking dels components amb mes equips i volum de model."
        elif plot_id == "components_resources_vs_competitions":
            descriptions[plot_id] = "Relacio entre recursos i competicions que fan crecer cada component."
        elif plot_id == "candidate_pareto_by_component":
            descriptions[plot_id] = "Concentracio de variables candidates per component."
        elif plot_id == "initial_hub_concentration_heatmap":
            descriptions[plot_id] = "Heatmap component-node que mostra quins recursos, competicions i linkages concentren mes connexions inicials."
        elif plot_id.startswith("hub_cut_network_"):
            descriptions[plot_id] = "Graf intra-hub amb mida per grau ponderat i vora vermella per punts de tall o alta betweenness."
        elif plot_id.startswith("hub_cut_ranking_"):
            descriptions[plot_id] = "Ranking de nodes interns del hub ordenats per cut score, betweenness, cut gain i grau ponderat."
        elif plot_id.startswith("hub_cut_matrix_"):
            descriptions[plot_id] = "Heatmap de coocurrencia entre nodes atractors dins el hub."
        elif plot_id.startswith("component_network_"):
            descriptions[plot_id] = "Xarxa completa de dependencies del component, amb nodes team/competition/resource/linkage."
        elif plot_id.startswith("component_bridge_network_") or plot_id == "top_component_network":
            descriptions[plot_id] = "Xarxa agregada de ponts entre competicions i recursos per components grans."
        elif plot_id == "top_component_competition_resource_heatmap":
            descriptions[plot_id] = "Matriu d'equips que connecten competicions amb recursos dins el component principal."
        elif plot_id == "component_graph_3d":
            descriptions[plot_id] = "Graf HTML interactiu amb nodes team/competition/resource/linkage, zoom, rotacio i seleccio."
    return descriptions


def _node_color(kind: str) -> str:
    return {
        "competition": "#4E79A7",
        "resource": "#F28E2B",
        "linkage": "#B07AA1",
        "level": "#59A14F",
        "team": "#BAB0AC",
    }.get(kind, "#777777")


def _edge_color(kind: str) -> str:
    return {
        "competition": "#4E79A7",
        "resource": "#F28E2B",
        "linkage": "#B07AA1",
        "level": "#59A14F",
    }.get(kind, "#9E9E9E")


def _node_size(kind: str, degree: int) -> float:
    base = 170 if kind == "team" else 310
    return base + min(360, max(0, degree - 1) * 45)


def _node_kind_label(kind: str) -> str:
    return {
        "competition": "Competicio",
        "resource": "Recurs",
        "linkage": "Linkage",
        "level": "Nivell",
        "team": "Equip",
    }.get(kind, kind)


def _node_kind_short_label(kind: str) -> str:
    return {
        "competition": "Comp",
        "resource": "Rec",
        "linkage": "Link",
        "level": "Niv",
        "team": "Eq",
    }.get(kind, kind)


def _kind_angle_offset(kind: str) -> float:
    return {
        "competition": 0.15,
        "resource": 1.25,
        "linkage": 2.35,
        "level": 1.8,
        "team": 0.75,
    }.get(kind, 0.0)


def _competition_key_for_team(team: Any) -> str:
    parts = [
        str(_get(team, "modality", "") or "").strip(),
        str(_get(team, "category", "") or "").strip(),
        str(_get(team, "subcategory", "") or "").strip(),
    ]
    if all(parts):
        return "|".join(("fields", *parts))
    league = str(_get(team, "league_name", "") or "").strip() or "Sense lliga"
    return f"league|{league}"


def _resource_key_for_team(team: Any) -> str:
    return "|".join(
        _slug_part(str(value or "missing"))
        for value in (
            _get(team, "venue", ""),
            _get(team, "day", ""),
            _get(team, "time", ""),
        )
    )


def _resource_label_for_team(team: Any, fallback: str) -> str:
    parts = [
        str(_get(team, "venue", "") or "").strip(),
        str(_get(team, "day", "") or "").strip(),
        str(_get(team, "time", "") or "").strip(),
    ]
    clean = [part for part in parts if part]
    return " / ".join(clean) if clean else fallback


def _short_linkage_label(linkage_key: str) -> str:
    parts = str(linkage_key).split("|")
    if len(parts) >= 4:
        return f"{parts[1]} / {parts[-1]}"
    return linkage_key


def _level_family_label(value: Any) -> str:
    text = str(value or "").strip().casefold()
    if not text:
        return "Nivell desconegut"
    if "nivell a" in text or text in {"a", "level a"}:
        return "Nivell A"
    if "nivell b" in text or text in {"b", "level b"}:
        return "Nivell B"
    if "nivell c" in text or text in {"c", "level c"}:
        return "Nivell C"
    return str(value or "Nivell desconegut").strip() or "Nivell desconegut"


def _normalize_linkage_group(value: Any) -> str:
    return _normalize_text(value)


def _is_indifferent_side(value: Any) -> bool:
    return _normalize_text(value) in {"", "indiferent", "indifferent", "none", "neutral", "neutre"}


def _normalize_text(value: Any) -> str:
    return str(value or "").strip().casefold()


def _slug_part(value: str) -> str:
    text = _normalize_text(value)
    chars = [char if char.isalnum() else "-" for char in text]
    return "-".join("".join(chars).split("-")).strip("-") or "missing"


def _linspace(start: float, stop: float, count: int) -> list[float]:
    if count <= 1:
        return [start]
    step = (stop - start) / (count - 1)
    return [start + step * index for index in range(count)]


def _spread_positions(count: int) -> list[float]:
    if count <= 1:
        return [0.5]
    return [index / (count - 1) for index in range(count)]


__all__ = ["write_resource_solver_decomposition_plots"]
