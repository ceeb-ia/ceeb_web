from __future__ import annotations

import hashlib
from pathlib import Path

import folium

from .contracts import PreviewScenario


def _color_for_cluster(cluster_id) -> str:
    if cluster_id in (None, -1):
        return "#808080"
    digest = hashlib.md5(str(int(cluster_id)).encode("utf-8")).hexdigest()
    return "#" + digest[:6]


def render_preview_map(scenario: PreviewScenario, out_html: str) -> str | None:
    points = [point for point in scenario.points if point.lat is not None and point.lon is not None]
    if not points:
        return None

    center_lat = sum(point.lat for point in points if point.lat is not None) / len(points)
    center_lon = sum(point.lon for point in points if point.lon is not None) / len(points)

    fmap = folium.Map(location=[center_lat, center_lon], zoom_start=11, control_scale=True)
    fg_clustered = folium.FeatureGroup(name="Clusters", show=True)
    fg_outliers = folium.FeatureGroup(name="Outliers", show=True)
    fg_missing = folium.FeatureGroup(name="Sense geocodificar", show=True)
    fg_fresh = folium.FeatureGroup(name="Geocodificades ara", show=True)

    for point in scenario.points:
        label_lines = [
            f"<strong>{point.adreca}</strong>",
            f"Municipi: {point.municipality or '-'}",
            f"Partits: {point.match_count}",
            f"Pistes: {point.venue_count}",
            f"Modalitats: {', '.join(point.modalities) if point.modalities else '-'}",
            f"Estat: {point.cluster_status}",
        ]
        if point.cluster is not None:
            label_lines.append(f"Cluster: {point.cluster}")

        if point.lat is None or point.lon is None:
            folium.Marker(
                location=[center_lat, center_lon],
                icon=folium.DivIcon(html="<div style='font-size:10px;color:#666;'>sense coords</div>"),
                popup=folium.Popup("<br>".join(label_lines), max_width=420),
            ).add_to(fg_missing)
            continue

        color = _color_for_cluster(point.cluster)
        marker = folium.CircleMarker(
            location=[point.lat, point.lon],
            radius=6 if point.cluster_status == "outlier" else 5,
            color=color,
            fill=True,
            fill_color=color,
            fill_opacity=0.85,
            tooltip=folium.Tooltip(point.adreca, sticky=True),
            popup=folium.Popup("<br>".join(label_lines), max_width=420),
        )

        if point.cluster_status == "outlier":
            marker.add_to(fg_outliers)
        else:
            marker.add_to(fg_clustered)
        if point.is_fresh_geocode:
            folium.CircleMarker(
                location=[point.lat, point.lon],
                radius=10,
                color="#111111",
                weight=1,
                fill=False,
                tooltip=folium.Tooltip(f"Geocodificada ara: {point.adreca}", sticky=True),
            ).add_to(fg_fresh)

    fg_clustered.add_to(fmap)
    fg_outliers.add_to(fmap)
    fg_missing.add_to(fmap)
    fg_fresh.add_to(fmap)
    folium.LayerControl(collapsed=False).add_to(fmap)

    out_path = Path(out_html)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fmap.save(str(out_path))
    return str(out_path)
