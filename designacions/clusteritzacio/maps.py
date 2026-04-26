from __future__ import annotations

import hashlib
import json
from pathlib import Path

import folium
from html import escape

from .contracts import PreviewScenario


def _color_for_cluster(cluster_id) -> str:
    if cluster_id in (None, -1):
        return "#808080"
    digest = hashlib.md5(str(int(cluster_id)).encode("utf-8")).hexdigest()
    return "#" + digest[:6]


def _add_base_tile_layers(fmap: folium.Map):
    folium.TileLayer(
        tiles="CartoDB positron",
        name="Base · Minimal",
        control=True,
        overlay=False,
        show=True,
    ).add_to(fmap)
    folium.TileLayer(
        tiles="OpenStreetMap",
        name="Base · Carrer",
        control=True,
        overlay=False,
        show=False,
    ).add_to(fmap)
    folium.TileLayer(
        tiles="CartoDB Voyager",
        name="Base · Detallat",
        control=True,
        overlay=False,
        show=False,
    ).add_to(fmap)
    folium.TileLayer(
        tiles="OpenTopoMap",
        name="Base · Topografic",
        attr="Map data: OpenStreetMap contributors, SRTM | Map style: OpenTopoMap",
        control=True,
        overlay=False,
        show=False,
    ).add_to(fmap)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        name="Base · Satellit",
        attr="Tiles © Esri",
        control=True,
        overlay=False,
        show=False,
    ).add_to(fmap)


def _build_popup_actions(scenario: PreviewScenario, point) -> str:
    if point.address_id is None:
        return ""
    onclick = (
        "window.parent.postMessage({"
        f"type:'cluster_preview_select_address',addressId:{int(point.address_id)},epsM:{int(scenario.eps_m)}"
        "}, '*')"
    )
    return (
        "<div style='margin-top:8px;'>"
        f"<button type='button' onclick=\"{escape(onclick, quote=True)}\" "
        "style='border:1px solid #0d6efd;background:#0d6efd;color:#fff;padding:4px 8px;border-radius:6px;cursor:pointer;'>"
        "Seleccionar aquesta seu"
        "</button>"
        "</div>"
    )


def _build_selection_sync_script(
    *,
    map_name: str,
    eps_m: int,
    marker_names_by_address_id: dict[str, str],
    coordinates_by_address_id: dict[str, dict[str, float]],
) -> str:
    return f"""
    <script>
    (function() {{
      const mapVariableName = {json.dumps(map_name)};
      const markerNamesByAddressId = {json.dumps(marker_names_by_address_id)};
      const coordinatesByAddressId = {json.dumps(coordinates_by_address_id)};
      const selectedEpsM = {json.dumps(str(eps_m))};
      let selectedMarkerName = null;
      let selectedMarkerSnapshot = null;
      let selectionRing = null;

      function getMapInstance() {{
        return window[mapVariableName] || null;
      }}

      function getMarkerName(addressId) {{
        return markerNamesByAddressId[String(addressId)] || null;
      }}

      function getMarker(addressId) {{
        const markerName = getMarkerName(addressId);
        if (!markerName) {{
          return null;
        }}
        return window[markerName] || null;
      }}

      function getCoordinates(addressId) {{
        return coordinatesByAddressId[String(addressId)] || null;
      }}

      function captureMarkerSnapshot(marker) {{
        const options = marker && marker.options ? marker.options : {{}};
        return {{
          radius: typeof options.radius === 'number' ? options.radius : null,
          style: {{
            color: options.color,
            fillColor: options.fillColor,
            fillOpacity: options.fillOpacity,
            opacity: typeof options.opacity === 'number' ? options.opacity : 1,
            weight: typeof options.weight === 'number' ? options.weight : 3,
          }},
        }};
      }}

      function restoreSelectedMarker() {{
        if (!selectedMarkerName || !selectedMarkerSnapshot) {{
          return;
        }}
        const marker = window[selectedMarkerName];
        if (marker && typeof marker.setStyle === 'function') {{
          marker.setStyle(selectedMarkerSnapshot.style);
          if (typeof selectedMarkerSnapshot.radius === 'number' && typeof marker.setRadius === 'function') {{
            marker.setRadius(selectedMarkerSnapshot.radius);
          }}
        }}
        selectedMarkerName = null;
        selectedMarkerSnapshot = null;
      }}

      function clearSelectionRing() {{
        const mapInstance = getMapInstance();
        if (selectionRing && mapInstance && typeof mapInstance.removeLayer === 'function') {{
          mapInstance.removeLayer(selectionRing);
        }}
        selectionRing = null;
      }}

      function clearSelection() {{
        restoreSelectedMarker();
        clearSelectionRing();
      }}

      function renderSelectionRing(addressId) {{
        const coordinates = getCoordinates(addressId);
        const mapInstance = getMapInstance();
        if (!coordinates || !mapInstance || !window.L) {{
          return null;
        }}
        if (selectionRing && typeof mapInstance.removeLayer === 'function') {{
          mapInstance.removeLayer(selectionRing);
          selectionRing = null;
        }}
        selectionRing = window.L.circleMarker([coordinates.lat, coordinates.lon], {{
          radius: 14,
          color: '#dc3545',
          weight: 3,
          fill: false,
          opacity: 0.95,
          interactive: false,
        }});
        if (typeof selectionRing.addTo === 'function') {{
          selectionRing.addTo(mapInstance);
        }}
        return coordinates;
      }}

      function highlightAddress(addressId) {{
        const markerName = getMarkerName(addressId);
        const marker = getMarker(addressId);
        const coordinates = renderSelectionRing(addressId);

        if (selectedMarkerName && selectedMarkerName !== markerName) {{
          restoreSelectedMarker();
        }}
        if (markerName && marker && (!selectedMarkerSnapshot || selectedMarkerName !== markerName)) {{
          selectedMarkerSnapshot = captureMarkerSnapshot(marker);
        }}

        if (marker && typeof marker.setStyle === 'function') {{
          marker.setStyle({{
            color: '#dc3545',
            fillColor: '#dc3545',
            fillOpacity: 1,
            opacity: 1,
            weight: 4,
          }});
          if (typeof marker.setRadius === 'function') {{
            const baseRadius = marker.options && typeof marker.options.radius === 'number' ? marker.options.radius : 6;
            marker.setRadius(Math.max(baseRadius, 9));
          }}
          if (typeof marker.openPopup === 'function') {{
            marker.openPopup();
          }}
        }}

        const mapInstance = getMapInstance();
        const latLng = marker && typeof marker.getLatLng === 'function'
          ? marker.getLatLng()
          : (coordinates && window.L ? window.L.latLng(coordinates.lat, coordinates.lon) : null);
        if (mapInstance && latLng && typeof mapInstance.panTo === 'function') {{
          mapInstance.panTo(latLng);
        }}

        selectedMarkerName = markerName || null;
      }}

      window.addEventListener('message', function(event) {{
        const data = event && event.data ? event.data : null;
        if (!data || (data.type !== 'cluster_preview_highlight_address' && data.type !== 'cluster_preview_clear_selection')) {{
          return;
        }}
        if (data.epsM && String(data.epsM) !== selectedEpsM) {{
          return;
        }}
        if (data.type === 'cluster_preview_clear_selection') {{
          window.setTimeout(function() {{
            clearSelection();
          }}, 0);
          return;
        }}
        window.setTimeout(function() {{
          highlightAddress(data.addressId);
        }}, 0);
      }});
    }})();
    </script>
    """


def render_preview_map(scenario: PreviewScenario, out_html: str) -> str | None:
    points = [point for point in scenario.points if point.lat is not None and point.lon is not None]
    if not points:
        return None

    center_lat = sum(point.lat for point in points if point.lat is not None) / len(points)
    center_lon = sum(point.lon for point in points if point.lon is not None) / len(points)

    fmap = folium.Map(location=[center_lat, center_lon], zoom_start=11, control_scale=True, tiles=None)
    _add_base_tile_layers(fmap)
    fg_clustered = folium.FeatureGroup(name="Clusters", show=True)
    fg_outliers = folium.FeatureGroup(name="Outliers", show=True)
    fg_missing = folium.FeatureGroup(name="Sense geocodificar", show=False)
    fg_fresh = folium.FeatureGroup(name="Geocodificades ara", show=False)
    fg_manual = folium.FeatureGroup(name="Overrides manuals", show=False)
    marker_names_by_address_id: dict[str, str] = {}
    coordinates_by_address_id: dict[str, dict[str, float]] = {}

    for point in scenario.points:
        label_lines = [
            f"<strong>{point.adreca}</strong>",
            f"Municipi: {point.municipality or '-'}",
            f"Partits: {point.match_count}",
            f"Pistes: {point.venue_count}",
            f"Modalitats: {', '.join(point.modalities) if point.modalities else '-'}",
            f"Estat: {point.cluster_status}",
            f"Cluster origen: {point.cluster_origin}",
        ]
        if point.cluster is not None:
            label_lines.append(f"Cluster: {point.cluster}")
        if point.auto_cluster is not None:
            label_lines.append(f"Cluster automatic: {point.auto_cluster}")
        if point.is_manual:
            label_lines.append(f"Override manual: {point.manual_role or 'actiu'}")
            if point.manual_override_ids:
                label_lines.append(f"Overrides: {', '.join(point.manual_override_ids)}")
        popup_html = "<br>".join(label_lines) + _build_popup_actions(scenario, point)

        if point.lat is None or point.lon is None:
            folium.Marker(
                location=[center_lat, center_lon],
                icon=folium.DivIcon(html="<div style='font-size:10px;color:#666;'>sense coords</div>"),
                popup=folium.Popup(popup_html, max_width=420),
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
            popup=folium.Popup(popup_html, max_width=420),
        )

        if point.cluster_status == "outlier":
            marker.add_to(fg_outliers)
        else:
            marker.add_to(fg_clustered)
        if point.address_id is not None:
            address_id_key = str(int(point.address_id))
            marker_names_by_address_id[address_id_key] = marker.get_name()
            coordinates_by_address_id[address_id_key] = {
                "lat": float(point.lat),
                "lon": float(point.lon),
            }
        if point.is_manual:
            folium.CircleMarker(
                location=[point.lat, point.lon],
                radius=11,
                color="#000000",
                weight=2,
                fill=False,
                tooltip=folium.Tooltip(f"Override manual: {point.adreca}", sticky=True),
            ).add_to(fg_manual)
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
    fg_manual.add_to(fmap)
    folium.LayerControl(collapsed=False).add_to(fmap)
    if coordinates_by_address_id:
        fmap.get_root().html.add_child(
            folium.Element(
                _build_selection_sync_script(
                    map_name=fmap.get_name(),
                    eps_m=int(scenario.eps_m),
                    marker_names_by_address_id=marker_names_by_address_id,
                    coordinates_by_address_id=coordinates_by_address_id,
                )
            )
        )

    out_path = Path(out_html)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fmap.save(str(out_path))
    return str(out_path)
