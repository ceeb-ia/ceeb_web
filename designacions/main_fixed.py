import asyncio
import pandas as pd
import os
import unicodedata, hashlib
from pandas.api.types import CategoricalDtype
from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from .services.modalitat_map import load_modalitat_map_df
from .services.run_scope import EXCLUDED_MATCH_GROUPS, EXCLUDED_REFEREE_CODES, load_scoped_run_data
from .consulta_resultats import fetch_ceeb_async, parse_ceeb_xml, xml_to_dataframe
from .geolocate import clusteritza_i_plota, geocodificar
import numpy as np
import folium
from folium.plugins import MarkerCluster
from folium.features import DivIcon
from scipy.optimize import linear_sum_assignment
import sys
from datetime import datetime, timedelta, time as dt_time
from logs import _write_job, _read_job, push_log
from asgiref.sync import async_to_sync
from django.db import transaction
from django.utils.dateparse import parse_date
from .services.geocoding_db import geocodifica_adreces, addresses_to_df
from .models import Address, AddressCluster





RESULTS_DIR = os.getenv('MEDIA_ROOT', '/data/media/')
MEDIA_URL = os.getenv('MEDIA_URL', '/media/')
MEDIA_ROOT = os.getenv('MEDIA_ROOT', '/data/media/')
os.makedirs(RESULTS_DIR, exist_ok=True)
file_path_dispo =  MEDIA_ROOT + 'designacions/' + 'dispos_tutors_23_01.xlsx'
file_path_partits = MEDIA_ROOT + 'designacions/' + 'partits_23_01.xlsx'

def _parse_times(s):
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            parsed = pd.to_datetime(s, format=fmt, errors="coerce")
            if not parsed.isna().all():
                return parsed.dt.time
        except Exception:
            pass
    # fallback: infer per element (pandas infers mixed formats)
    return pd.to_datetime(s, errors="coerce").dt.time


def _normalize_date_value(value):
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return pd.NaT
    return pd.Timestamp(parsed).normalize()


def _normalize_date_series(series):
    return pd.to_datetime(series, errors="coerce").dt.normalize()


def _date_token(value) -> str:
    normalized = _normalize_date_value(value)
    if pd.isna(normalized):
        return ""
    return normalized.strftime("%Y-%m-%d")


def _combine_date_time(date_value, time_value):
    normalized_date = _normalize_date_value(date_value)
    if pd.isna(normalized_date):
        return pd.NaT
    if time_value in (None, "") or pd.isna(time_value):
        return pd.NaT
    if isinstance(time_value, pd.Timestamp):
        parsed_time = time_value.time()
    elif isinstance(time_value, datetime):
        parsed_time = time_value.time()
    elif isinstance(time_value, dt_time):
        parsed_time = time_value
    else:
        parsed = pd.to_datetime(time_value, format="%H:%M:%S", errors="coerce")
        if pd.isna(parsed):
            parsed = pd.to_datetime(time_value, format="%H:%M", errors="coerce")
        if pd.isna(parsed):
            parsed = pd.to_datetime(time_value, errors="coerce")
        if pd.isna(parsed):
            return pd.NaT
        parsed_time = parsed.time()
    return pd.Timestamp(datetime.combine(normalized_date.date(), parsed_time))


def _safe_position_int(value, default: int = -1) -> int:
    try:
        if pd.isna(value):
            return default
    except Exception:
        pass
    if value in (None, ""):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _build_tutor_working_id(row) -> str:
    key = "|".join(
        [
            _normalize_entity_name(row.get("Codi Tutor de Joc", "")),
            _normalize_entity_name(row.get("Modalitat", "")),
            _normalize_entity_name(row.get("Nivell", "")),
            _date_token(row.get("Data")),
        ]
    )
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:10].upper()


def _subgroup_date_key(subgrup):
    for row in subgrup:
        normalized = _normalize_date_value(row.get("Data"))
        if not pd.isna(normalized):
            return normalized
    return pd.NaT


def _subgroup_first_datetime(subgrup):
    datetimes = [row.get("__match_datetime") for row in subgrup if not pd.isna(row.get("__match_datetime"))]
    if not datetimes:
        return pd.NaT
    return min(datetimes)


def _subgroup_last_datetime(subgrup):
    datetimes = [row.get("__match_datetime") for row in subgrup if not pd.isna(row.get("__match_datetime"))]
    if not datetimes:
        return pd.NaT
    return max(datetimes)


def _build_daily_subgroups(df_partits_modalitat: pd.DataFrame, gap_same_pitch_min: int, gap_diff_pitch_min: int, max_partits_subgrup: int) -> list:
    if df_partits_modalitat.empty:
        return []

    working = df_partits_modalitat.copy()
    if "Data" in working.columns:
        working["Data"] = _normalize_date_series(working["Data"])
    working["__match_datetime"] = working.apply(
        lambda row: _combine_date_time(row.get("Data"), row.get("Hora")),
        axis=1,
    )
    working["__day_key"] = working["Data"]

    final_subgrups = []
    for _, group in working.groupby("__day_key", dropna=False):
        group_ordered = group.sort_values(["__match_datetime", "Pista joc"], na_position="last").reset_index(drop=True)
        valid_rows = group_ordered[group_ordered["__match_datetime"].notna()].reset_index(drop=True)
        invalid_rows = group_ordered[group_ordered["__match_datetime"].isna()]

        subgrups = []
        used_rows = set()

        while len(used_rows) < len(valid_rows):
            current_subgroup = []
            previous_dt = None
            prev_pista_joc = None
            for idx, row in valid_rows.iterrows():
                if idx in used_rows:
                    continue
                current_dt = row["__match_datetime"]
                pista_joc = row["Pista joc"]
                if previous_dt is None:
                    current_subgroup.append(row)
                    used_rows.add(idx)
                else:
                    time_diff = (current_dt - previous_dt).total_seconds() / 60.0
                    required_gap = gap_diff_pitch_min if pista_joc != prev_pista_joc else gap_same_pitch_min
                    if time_diff >= required_gap:
                        current_subgroup.append(row)
                        used_rows.add(idx)

                previous_dt = current_dt
                prev_pista_joc = pista_joc

            if current_subgroup:
                subgrups.append(current_subgroup)

        for _, row in invalid_rows.iterrows():
            subgrups.append([row])

        ordered_subgrups = sorted(
            subgrups,
            key=lambda sg: _subgroup_first_datetime(sg) if not pd.isna(_subgroup_first_datetime(sg)) else pd.Timestamp.max,
        )
        fused = []
        used = set()
        for i, current_sg in enumerate(ordered_subgrups):
            if i in used:
                continue
            merged_sg = list(current_sg)
            if len(merged_sg) < max_partits_subgrup:
                for j in range(i + 1, len(ordered_subgrups)):
                    if j in used:
                        continue
                    next_sg = ordered_subgrups[j]
                    if len(merged_sg) + len(next_sg) > max_partits_subgrup:
                        continue

                    pista_actual = merged_sg[0].get("Pista joc")
                    pista_seguent = next_sg[0].get("Pista joc")
                    cluster_actual = merged_sg[0].get("cluster")
                    cluster_seguent = next_sg[0].get("cluster")
                    if (
                        pista_actual == pista_seguent
                        or pd.isna(cluster_actual)
                        or pd.isna(cluster_seguent)
                        or cluster_actual == -1
                        or cluster_seguent == -1
                        or cluster_actual != cluster_seguent
                    ):
                        continue

                    hora_darrer = _subgroup_last_datetime(merged_sg)
                    hora_primer = _subgroup_first_datetime(next_sg)
                    if pd.isna(hora_darrer) or pd.isna(hora_primer):
                        continue

                    time_diff = (hora_primer - hora_darrer).total_seconds() / 60.0
                    if time_diff >= gap_diff_pitch_min:
                        merged_sg.extend(next_sg)
                        used.add(j)
                        break

            fused.append(
                sorted(
                    merged_sg,
                    key=lambda row: row.get("__match_datetime") if not pd.isna(row.get("__match_datetime")) else pd.Timestamp.max,
                )
            )

        final_subgrups.extend(fused)

    return final_subgrups


def _availability_penalty_for_subgroup(tutor_row, subgrup, availability_end_buffer_min: int = 60, penalty: float = 1e6) -> float:
    dispo_date = _normalize_date_value(tutor_row.get("Data"))
    subgrup_date = _subgroup_date_key(subgrup)
    if pd.isna(dispo_date) or pd.isna(subgrup_date) or dispo_date != subgrup_date:
        return penalty

    sub_inici_dt = _subgroup_first_datetime(subgrup)
    sub_final_dt = _subgroup_last_datetime(subgrup)
    dispo_inici_dt = _combine_date_time(dispo_date, tutor_row.get("Hora Inici"))
    dispo_final_dt = _combine_date_time(dispo_date, tutor_row.get("Hora Fi"))

    if pd.isna(sub_inici_dt) or pd.isna(sub_final_dt) or pd.isna(dispo_inici_dt) or pd.isna(dispo_final_dt):
        return penalty

    dispo_final_adj = dispo_final_dt - timedelta(minutes=availability_end_buffer_min)
    if dispo_inici_dt > sub_inici_dt or dispo_final_adj < sub_final_dt:
        return penalty
    return 0.0


def _subgrup_profile(subgrup, nivel_dtype_partits):
    niveles = []
    posicions = []
    for row in subgrup:
        categoria = row["Categoria"]
        if pd.isna(categoria):
            continue
        niveles.append(categoria)
        pos_local = row.get("Posició Equip Local", None)
        pos_visitant = row.get("Posició Equip Visitant", None)
        if pos_local is not None and not pd.isna(pos_local) and pos_visitant is not None and not pd.isna(pos_visitant):
            posicions.append((pos_local, pos_visitant))

    if not niveles:
        raise ValueError("No hi ha categories vàlides al subgrup.")

    suma_posicions_prev = 19
    if posicions:
        suma_posicions_prev = min(p[0] + p[1] for p in posicions)

    pistes_joc = set(r["Pista joc"] for r in subgrup)
    clusters_pistes = set(r["cluster"] for r in subgrup)
    multiple_pistes = len(pistes_joc) > 1

    niveles = pd.Series(niveles, dtype=nivel_dtype_partits)
    return niveles.min(), suma_posicions_prev, multiple_pistes, clusters_pistes


def _compute_subgroup_cost(
    tutor_row,
    subgrup,
    *,
    tutor_nivel_order,
    partits_nivel_order,
    nivel_dtype_partits,
    availability_end_buffer_min,
):
    tutor_codi = tutor_row["Codi Tutor de Joc"]
    tutor_nivel = tutor_row["Nivell"]
    tutor_modalitat = tutor_row["Modalitat"]
    subgrup_modalitat = subgrup[0]["Modalitat"]
    if tutor_modalitat != subgrup_modalitat:
        raise ValueError(f"Modalitat tutor ({tutor_modalitat}) != modalitat subgrup ({subgrup_modalitat})")

    subgrup_nivel, suma_posicions, multiple_pistes, clusters_pistes = _subgrup_profile(subgrup, nivel_dtype_partits)

    try:
        tutor_idx = tutor_nivel_order.index(tutor_nivel)
        part_idx = partits_nivel_order.index(subgrup_nivel)

        n_t = len(tutor_nivel_order)
        m_p = len(partits_nivel_order)

        map_tutor = tutor_idx / (n_t - 1) if n_t > 1 else 0
        map_partit = part_idx / (m_p - 1) if m_p > 1 else 0
        map_posicions = (suma_posicions - 3) / (19 - 3)

        nombre_partits_subgrup = len(subgrup)

        mitja_transport = tutor_row.get("Mitjà de Transport", "")
        if pd.isna(mitja_transport):
            mitja_transport = ""
        if any(x in mitja_transport.lower() for x in ["moto", "cotxe", "patinet elèctric", "bicicleta"]):
            scale_vehicle = 0
        else:
            scale_vehicle = 1000

        dist = abs(map_tutor - map_partit)
        dist_classif = abs(map_posicions - map_tutor)

        cost = dist * 1000 + dist_classif * 500 + (1 / max(nombre_partits_subgrup, 1)) * 100
        if multiple_pistes:
            cost += scale_vehicle

        if "5413" in str(tutor_codi):
            favorits = {"12", "13", "9", "6", "10", "15"}
            if any(str(c) in favorits for c in clusters_pistes):
                cost *= 0.2

    except ValueError:
        raise ValueError(f"Nivell tutor ({tutor_nivel}) o subgrup ({subgrup_nivel}) no reconegut.")

    cost += _availability_penalty_for_subgroup(
        tutor_row,
        subgrup,
        availability_end_buffer_min=availability_end_buffer_min,
        penalty=1e6,
    )
    return cost


def _build_subgroup_cost_matrix(
    referee_rows,
    subgroups,
    subgroup_cost_fn,
):
    if len(referee_rows) == 0 or len(subgroups) == 0:
        return np.zeros((len(referee_rows), len(subgroups)))

    cost_matrix = np.zeros((len(referee_rows), len(subgroups)))
    for i, (_, row) in enumerate(referee_rows.iterrows()):
        for j, subgrup in enumerate(subgroups):
            cost_matrix[i, j] = subgroup_cost_fn(row, subgrup)
    return cost_matrix


def _solve_assignment_pairs(cost_matrix, *, threshold: float = 1e5):
    if cost_matrix.size == 0 or 0 in cost_matrix.shape:
        return []

    row_ind, col_ind = linear_sum_assignment(cost_matrix)
    return [
        (row_idx, col_idx)
        for row_idx, col_idx in zip(row_ind, col_ind)
        if cost_matrix[row_idx, col_idx] < threshold
    ]


def _segment_failed_subgroup(
    subgrup,
    candidate_referees,
    subgroup_cost_fn,
    *,
    threshold: float = 1e5,
):
    ordered = sorted(
        list(subgrup),
        key=lambda row: row.get("__match_datetime") if not pd.isna(row.get("__match_datetime")) else pd.Timestamp.max,
    )
    if len(ordered) <= 1:
        return [ordered]
    if candidate_referees.empty:
        return [[row] for row in ordered]

    n = len(ordered)
    split_points = []
    for split_idx in (n - 1, 1):
        if 0 < split_idx < n and split_idx not in split_points:
            split_points.append(split_idx)

    fallback_candidates = []
    for split_idx in split_points:
        direct_segments = [ordered[:split_idx], ordered[split_idx:]]
        direct_cost_matrix = _build_subgroup_cost_matrix(candidate_referees, direct_segments, subgroup_cost_fn)
        if len(_solve_assignment_pairs(direct_cost_matrix, threshold=threshold)) == len(direct_segments):
            return direct_segments

        recursive_segments = []
        for segment in direct_segments:
            recursive_segments.extend(
                _segment_failed_subgroup(segment, candidate_referees, subgroup_cost_fn, threshold=threshold)
            )
        recursive_cost_matrix = _build_subgroup_cost_matrix(candidate_referees, recursive_segments, subgroup_cost_fn)
        if len(_solve_assignment_pairs(recursive_cost_matrix, threshold=threshold)) == len(recursive_segments):
            return recursive_segments
        fallback_candidates.append(recursive_segments)

    return min(fallback_candidates, key=len) if fallback_candidates else [[row] for row in ordered]


def _run_rescue_assignment(candidate_referees, failed_subgroups, subgroup_cost_fn, *, threshold: float = 1e5):
    rescue_segments = []
    for subgrup in failed_subgroups:
        rescue_segments.extend(
            _segment_failed_subgroup(subgrup, candidate_referees, subgroup_cost_fn, threshold=threshold)
        )

    rescue_cost_matrix = _build_subgroup_cost_matrix(candidate_referees, rescue_segments, subgroup_cost_fn)
    assignment_pairs = _solve_assignment_pairs(rescue_cost_matrix, threshold=threshold)
    return {
        "segments": rescue_segments,
        "cost_matrix": rescue_cost_matrix,
        "pairs": assignment_pairs,
    }


def _color_per_tutor(tutor_codi) -> str:
    if pd.isna(tutor_codi) or str(tutor_codi).strip() == "":
        return "#808080"  # gris (sense assignar)
    h = hashlib.md5(str(tutor_codi).encode("utf-8")).hexdigest()
    return "#" + h[:6]

def _color_estat_seu(n_assigned: int, n_unassigned: int) -> str:
    if n_unassigned > 0 and n_assigned == 0:
        return "#d62728"  # vermell
    if n_unassigned > 0:
        return "#ff7f0e"  # taronja
    return "#2ca02c"      # verd

def mapa_assignacions_interactiu(
    df_partits_geo: pd.DataFrame,
    df_assignacions: pd.DataFrame,
    lat_col="lat",
    lon_col="lon",
    seu_col="adreca",          # domicili + municipi
    codi_partit_col="Codi",    # codi del partit al df_partits
    codi_assign_col="Codi Partit",  # codi del partit al df_assignacions
    tutor_codi_col="Tutor Codi",
    tutor_nom_col="Tutor",
    hora_col="Partit Hora",
    data_col="Data Partit",    # opcional
    out_html="mapa_assignacions.html",
    zoom_start=12,
    jitter_m=12,
    mostra_totes_les_seus=False  # si False, al resum només es veuen seus amb no assignats
):
    # --- Merge partits + assignació ---
    dfP = df_partits_geo.copy()
    dfA = df_assignacions.copy()

    # Normalitza per poder fer merge
    if codi_assign_col in dfA.columns and codi_partit_col in dfP.columns:
        dfA = dfA.rename(columns={codi_assign_col: codi_partit_col})

    merged = dfP.merge(dfA, on=codi_partit_col, how="left", suffixes=("", "_asgn"))

    # Columnes unificades per data/hora: així els partits SENSE ASSIGNAR també conserven Hora/Data del df_partits
    if hora_col in merged.columns and "Hora" in merged.columns:
        merged["__hora_mapa"] = merged[hora_col].where(merged[hora_col].notna(), merged["Hora"])
    elif hora_col in merged.columns:
        merged["__hora_mapa"] = merged[hora_col]
    elif "Hora" in merged.columns:
        merged["__hora_mapa"] = merged["Hora"]
    else:
        merged["__hora_mapa"] = np.nan

    if data_col in merged.columns and "Data" in merged.columns:
        merged["__data_mapa"] = merged[data_col].where(merged[data_col].notna(), merged["Data"])
    elif data_col in merged.columns:
        merged["__data_mapa"] = merged[data_col]
    elif "Data" in merged.columns:
        merged["__data_mapa"] = merged["Data"]
    else:
        merged["__data_mapa"] = np.nan

    # Estat assignació
    merged["assignat"] = merged[tutor_codi_col].notna() & (merged[tutor_codi_col].astype(str).str.strip() != "")

    # Validació coords
    d_ok = merged.dropna(subset=[lat_col, lon_col]).copy()
    if d_ok.empty:
        raise ValueError("No hi ha partits amb coordenades (lat/lon) per dibuixar el mapa.")

    center = [d_ok[lat_col].astype(float).mean(), d_ok[lon_col].astype(float).mean()]
    m = folium.Map(location=center, zoom_start=zoom_start, control_scale=True)

    # Apply _parse_times to the time column (returns a Series) instead of
    # applying row-wise which returned a Series per row and caused the
    # 'multiple columns to single column' ValueError.
    d_ok["_slot"] = _parse_times(d_ok["__hora_mapa"])

    # agrupa per seu
    resum = (
        d_ok.groupby(seu_col, as_index=False)
        .agg(
            lat=(lat_col, "first"),
            lon=(lon_col, "first"),
            n_partits=(codi_partit_col, "count"),
            n_assignats=("assignat", "sum"),
        )
    )
    resum["n_no_assignats"] = resum["n_partits"] - resum["n_assignats"]

    # llista d’hores (o data+hora) només dels no assignats (utilitzem _parse_times per formatar correctament)
    no_asg = d_ok[~d_ok["assignat"]].copy()
    
    hores_no_asg = (
        no_asg.groupby(seu_col)["_slot"]
        .apply(lambda s: sorted([x for x in s.dropna().tolist() if str(x).strip() != ""]))
        .to_dict()
    )

    # --- CAPA 1: RESUM PER SEU (ALERTES) + HORES NO ASSIGNATS ---
    # mostra només seus amb incidències (o totes)
    fg_seus_incidencies = folium.FeatureGroup(
        name="Seus amb incidències (no assignats)",
        show=True
    )

    fg_seus_assignades = folium.FeatureGroup(
        name="Seus completament assignades",
        show=False
    )

    for _, r in resum.iterrows():
        nA = int(r["n_assignats"])
        nN = int(r["n_no_assignats"])
        color = _color_estat_seu(nA, nN)

        hores = hores_no_asg.get(r[seu_col], [])
        hores_txt = "<br>".join([f"• {h}" for h in hores]) if hores else "—"

        tooltip_html = (
            f"<b>{r[seu_col]}</b><br>"
            f"Assignats: {nA} / {int(r['n_partits'])}<br>"
            f"<b>No assignats: {nN}</b>"
        )

        popup_html = (
            f"<b>{r[seu_col]}</b><br>"
            f"Assignats: {nA} / {int(r['n_partits'])}<br>"
            f"<b>No assignats: {nN}</b><br><br>"
            f"<b>Hores no assignades:</b><br>{hores_txt}"
        )

        marker = folium.CircleMarker(
            location=[float(r["lat"]), float(r["lon"])],
            radius=10 if nN > 0 else 7,
            color=color,
            fill=True,
            fill_color=color,
            fill_opacity=0.85,
            tooltip=folium.Tooltip(tooltip_html, sticky=True),
            popup=folium.Popup(popup_html, max_width=500),
        )

        if nN > 0:
            marker.add_to(fg_seus_incidencies)
        else:
            marker.add_to(fg_seus_assignades)

        

    # --- CAPA 2: DETALL PER PARTIT (colors per tutor + grisos) ---
    fg_assigned = folium.FeatureGroup(name="Detall: Assignats (per tutor)", show=False)
    fg_unassigned = folium.FeatureGroup(name="Detall: Sense assignar", show=False)

    lat0 = np.radians(center[0])
    m_per_deg_lat = 111_320.0
    m_per_deg_lon = 111_320.0 * np.cos(lat0)
    rng = np.random.default_rng(42)

    for _, rr in d_ok.iterrows():
        lat = float(rr[lat_col])
        lon = float(rr[lon_col])

        dx = rng.uniform(-jitter_m, jitter_m)
        dy = rng.uniform(-jitter_m, jitter_m)
        lat_j = lat + (dy / m_per_deg_lat)
        lon_j = lon + (dx / m_per_deg_lon)

        assignat = bool(rr["assignat"])
        tutor = rr.get(tutor_codi_col, None)
        color = _color_per_tutor(tutor) if assignat else "#808080"

        # Info per tooltip/popup
        txt = []
        if "__data_mapa" in rr and pd.notna(rr["__data_mapa"]): txt.append(f"Data: {rr['__data_mapa']}")
        if "__hora_mapa" in rr and pd.notna(rr["__hora_mapa"]): txt.append(f"Hora: {rr['__hora_mapa']}")
        if "Pista" in rr and pd.notna(rr["Pista"]): txt.append(f"Pista: {rr['Pista']}")
        if "Club Local" in rr and pd.notna(rr["Club Local"]): txt.append(f"Local: {rr['Club Local']}")
        if "Club Visitant" in rr and pd.notna(rr["Club Visitant"]): txt.append(f"Visitant: {rr['Club Visitant']}")
        if "Categoria" in rr and pd.notna(rr["Categoria"]): txt.append(f"Categoria: {rr['Categoria']}")
        if "Modalitat" in rr and pd.notna(rr["Modalitat"]): txt.append(f"Modalitat: {rr['Modalitat']}")
        if assignat:
            txt.append(f"Tutor: {rr.get(tutor_codi_col,'')} - {rr.get(tutor_nom_col,'')}")
        else:
            txt.append("Tutor: SENSE ASSIGNAR")

        if len(txt) == 0:
                        txt.append("(sense informació)")

        tooltip = folium.Tooltip("<br>".join(txt), sticky=True)
        popup = folium.Popup("<br>".join(txt), max_width=450)

        marker = folium.CircleMarker(
            location=[lat_j, lon_j],
            radius=5 if assignat else 6,
            color=color,
            fill=True,
            fill_color=color,
            fill_opacity=0.9 if assignat else 0.6,
            tooltip=tooltip,
            popup=popup
        )

        if assignat:
            marker.add_to(fg_assigned)
        else:
            marker.add_to(fg_unassigned)

    fg_assigned.add_to(m)
    fg_unassigned.add_to(m)
    fg_seus_incidencies.add_to(m)
    fg_seus_assignades.add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)
    m.save(out_html)
    return out_html


def _normalize_entity_name(name: str) -> str:
    # treu variacions d’accents/espais/majús-minus
    s = unicodedata.normalize('NFKC', str(name)).casefold().strip()
    s = " ".join(s.split())  # col·lapsa espais múltiples
    return s



def read_excel_file(path):
    """Read an Excel file using an engine inferred from the extension.

    - `.xls` -> `xlrd` (requires `xlrd==1.2.0`)
    - others (xlsx, xlsm, etc.) -> `openpyxl`
    """
    _, ext = os.path.splitext(path)
    ext = ext.lower()
    if ext == ".xlsx":
        return pd.read_excel(path, engine="openpyxl")
    else:
        raise ValueError(f"Unsupported file extension '{ext}' for file '{path}'.")


def persist_assignacions_to_db(
    *,
    run_id: int,
    df_partits: pd.DataFrame,
    df_dispos: pd.DataFrame,
    df_assignacions: pd.DataFrame,
):
    """
    Desa a BD:
    - Referee (si no existeix)
    - Match (si no existeix) per aquest run
    - Assignment (upsert) per Match

    IMPORTANT:
    - No toca assignacions locked=True.
    - Manté referee=None si el partit queda sense assignar.
    """
    from .models import DesignationRun, Referee, Match, Assignment

    run = DesignationRun.objects.get(id=run_id)

    # Mapa ràpid: referee_code -> (nom complet)
    # df_dispos té 'Codi Tutor de Joc', 'Nom', 'Cognoms'
    dispo_name = {}
    for _, r in df_dispos.iterrows():
        c = str(r.get("Codi Tutor de Joc", "")).strip()
        if not c:
            continue
        n = str(r.get("Nom", "")).strip()
        cg = str(r.get("Cognoms", "")).strip()
        full = (n + " " + cg).strip() or c
        dispo_name[c] = full

    # Mapa assignacions: codi_partit -> referee_code
    # df_assignacions té 'Codi Partit' i 'Tutor Codi'
    assigned_map = {}
    if df_assignacions is not None and not df_assignacions.empty:
        for _, r in df_assignacions.iterrows():
            codi_partit = str(r.get("Codi Partit", "")).strip()
            tutor_codi = str(r.get("Tutor Codi", "")).strip()
            if codi_partit:
                assigned_map[codi_partit] = tutor_codi or None

    # Upsert matches + assignments dins transacció
    with transaction.atomic():
        # 1) Assegura que tots els partits existeixen com Match per aquest run
        for _, p in df_partits.iterrows():
            codi = str(p.get("Codi", "")).strip()
            if not codi:
                continue

            # engine_id (hash) si el tens a df_partits['ID']
            engine_id = str(p.get("ID", "")).strip() or None

            # Data pot venir com datetime o string; Match.date és DateField
            d = p.get("Data", None)
            date_val = None
            try:
                if pd.notna(d):
                    if hasattr(d, "date"):
                        date_val = d.date()
                    else:
                        date_val = parse_date(str(d))
            except Exception:
                date_val = None

            Match.objects.update_or_create(
                run=run,
                code=codi,
                defaults={
                    "engine_id": engine_id,
                    "club_local": p.get("Club Local"),
                    "equip_local": p.get("Equip local"),
                    "equip_visitant": p.get("Equip visitant"),
                    "lliga": p.get("Lliga"),
                    "group": p.get("Grup"),
                    "jornada": p.get("Jornada"),
                    "modality": p.get("Modalitat"),
                    "category": p.get("Categoria"),
                    "subcategory": p.get("Subcategoria"),
                    "date": date_val,
                    "hour_raw": str(p.get("Hora", "")).strip() or None,
                    "domicile": p.get("Domicili"),
                    "municipality": p.get("Municipi"),
                    "venue": p.get("Pista joc"),
                    "sub_venue": p.get("SubPista joc"),
                },
            )

        # 2) Upsert assignments (respectant locked)
        matches = {m.code: m for m in Match.objects.filter(run=run)}

        for match_code, match in matches.items():
            tutor_code = assigned_map.get(match_code, None)

            # si no hi ha assignació, deixem referee=None (sense tocar locked)
            asg, _ = Assignment.objects.get_or_create(run=run, match=match)

            if asg.locked:
                continue

            if not tutor_code:
                if asg.referee_id is not None:
                    asg.referee = None
                    asg.save(update_fields=["referee", "updated_at"])
                continue

            ref_name = dispo_name.get(tutor_code, tutor_code)
            ref, _ = Referee.objects.update_or_create(
                code=tutor_code,
                defaults={"name": ref_name, "active": True},
            )

            if asg.referee_id != ref.id:
                asg.referee = ref
                asg.save(update_fields=["referee", "updated_at"])


def main(
    path_disposicions: str,
    path_dades: str,
    task_id: str | None = None,
    run_id: int | None = None,
    config: dict | None = None,
    *,
    df_dispos: pd.DataFrame | None = None,
    df_partits: pd.DataFrame | None = None,
) -> dict:
    config = config or {}

    cluster_eps_m = float(config.get("cluster_eps_m", 500))
    cluster_min_samples = int(config.get("cluster_min_samples", 2))
    max_partits_subgrup = int(config.get("max_partits_subgrup", 3))
    gap_same_pitch_min = int(config.get("gap_same_pitch_min", 60))
    gap_diff_pitch_min = int(config.get("gap_diff_pitch_min", 75))
    availability_end_buffer_min = int(config.get("availability_end_buffer_min", 60))
    modalitats_filter = config.get("modalitats") or []
    date_from = config.get("date_from") or None
    date_to = config.get("date_to") or None
    fase = str(config.get("fase", "FS1") or "FS1").strip().upper()
    if fase not in {"FS1", "FS2"}:
        fase = "FS1"

    # --- Mapping modalitat/categoria (BD) ---
    # IMPORTANT: ha de retornar un DataFrame tipus map_modalitat_nom.csv amb columnes:
    #   "Modalitat", "Nom", "Id Categoria" (mínim)
    map_modalitat_nom = load_modalitat_map_df()

    # ------------ Get paths ------------
    file_abspath_dispo = os.path.abspath(path_disposicions)
    file_abspath_partits = os.path.abspath(path_dades)
    results_abspath = os.path.abspath(RESULTS_DIR)

    if df_dispos is None or df_partits is None:
        df_dispos, df_partits = load_scoped_run_data(file_abspath_dispo, file_abspath_partits, config)
    else:
        df_dispos = df_dispos.copy()
        df_partits = df_partits.copy()

    # Fem shuffle per evitar biaixos en assignacions
    df_dispos = df_dispos.sample(frac=1, random_state=42).reset_index(drop=True)
    df_partits = df_partits.sample(frac=1, random_state=42).reset_index(drop=True)
    if "Data" in df_dispos.columns:
        df_dispos["Data"] = _normalize_date_series(df_dispos["Data"])
    if "Data" in df_partits.columns:
        df_partits["Data"] = _normalize_date_series(df_partits["Data"])

    print("\nColumnes partits:", df_partits.columns)
    print("\nColumnes disponibilitats tutors:", df_dispos.columns)
    if task_id:
        async_to_sync(push_log)(task_id, "Llegint els fitxers.", 30)

    def _mk_id(row, tutor: bool = True) -> str:
        if tutor:
            nom = _normalize_entity_name(row.get('Codi Tutor de Joc', ''))
            lliga = _normalize_entity_name(row.get('Nom', ''))
            cat = _normalize_entity_name(row.get('Nivell', ''))
            mod = _normalize_entity_name(row.get('Modalitat', ''))
            day = _date_token(row.get("Data"))
        else:
            nom = _normalize_entity_name(row.get('Codi', ''))
            lliga = _normalize_entity_name(row.get('Codi Extern Local', ''))
            cat = _normalize_entity_name(row.get('Lliga', ''))
            mod = _normalize_entity_name(row.get('Categoria', ''))
            day = ""

        key = f"{nom}|{lliga}|{cat}|{mod}|{day}"
        return hashlib.sha1(key.encode('utf-8')).hexdigest()[:10].upper()

    categories_dispos = df_dispos['Categoria'].unique()
    if len(categories_dispos) > 1:
        if task_id:
            async_to_sync(push_log)(task_id, f"S'hi han trobat múltiples llicències: {categories_dispos}. Introdueix només la del tutor.", 100)
        raise ValueError(f"S'hi han trobat múltiples llicències a dispos: {categories_dispos}")

    # IDs
    df_dispos['ID'] = df_dispos.apply(_mk_id, axis=1, tutor=True)
    df_dispos.drop_duplicates(subset=['ID'], keep='first', inplace=True)

    df_partits['ID'] = df_partits.apply(_mk_id, axis=1, tutor=False)

    def _report_duplicates(df, name: str):
        dup_mask = df['ID'].duplicated(keep=False)
        if not dup_mask.any():
            print(f"No hi ha IDs duplicats a {name}\n")
            return
        dup_ids = df.loc[dup_mask, 'ID'].unique().tolist()
        if task_id:
            async_to_sync(push_log)(task_id, f"IDs duplicats trobats a {name}: {dup_ids}", 100)
        raise ValueError(f"IDs duplicats trobats a {name} - {dup_ids}")

    _report_duplicates(df_dispos, 'tutors')
    _report_duplicates(df_partits, 'partits')

    if task_id:
        async_to_sync(push_log)(task_id, f"Eliminant codis tutor no vàlids: {EXCLUDED_REFEREE_CODES}", 40)
        async_to_sync(push_log)(task_id, f"Eliminant grups partit no vàlids: {EXCLUDED_MATCH_GROUPS}", 40)

    # Tutors sense nivell
    if df_dispos['Nivell'].isna().any():
        if task_id:
            async_to_sync(push_log)(task_id, "S'han trobat tutors sense nivell (s'exclouran i es guardaran a revisió).", 42)
        df_revisio_sense_nivell = df_dispos[df_dispos['Nivell'].isna()].copy()
        df_dispos = df_dispos[~df_dispos['Nivell'].isna()].copy()
    else:
        df_revisio_sense_nivell = pd.DataFrame()

    if df_partits.empty:
        if task_id:
            async_to_sync(push_log)(task_id, "No hi ha partits dins del filtre seleccionat.", 96)
        return {
            "assigned": 0,
            "unassigned_matches": 0,
            "unassigned_referees": 0,
            "needs_review_referees": int(
                df_revisio_sense_nivell["Codi Tutor de Joc"].astype(str).str.strip().replace("", pd.NA).dropna().nunique()
            ) if not df_revisio_sense_nivell.empty else 0,
            "rescue_failed_subgroups": 0,
            "rescue_segments_generated": 0,
            "rescue_matches_recovered": 0,
            "map_path": None,
        }

    tutor_nivel_order = ['NIVELLA1', 'NIVELLB1', 'NIVELLC1', 'NIVELLD1', 'D']
    nivel_dtype = CategoricalDtype(categories=tutor_nivel_order, ordered=True)
    df_dispos['Nivell'] = df_dispos['Nivell'].astype(nivel_dtype)
    df_dispos = df_dispos.sort_values('Nivell').reset_index(drop=True)

    # ------------ Adreces (geocodificació BD) + clusterització ------------
    df_partits['adreca'] = df_partits['Domicili'].astype(str) + ', ' + df_partits['Municipi'].astype(str)

    if task_id:
        async_to_sync(push_log)(task_id, "Iniciant geocodificació d'adreces.", 45)

    adreces_uniques = df_partits["adreca"].unique().tolist()
    addr_objs = geocodifica_adreces(adreces_uniques, task_id=task_id)  # respecte Nominatim intern
    df_geocodificats = addresses_to_df(addr_objs)

    if task_id:
        async_to_sync(push_log)(task_id, "Geocodificació completada.", 57)
        async_to_sync(push_log)(task_id, "Iniciant agrupació geogràfica d'adreces.", 58)


    domicilis_clusteritzats, _, _, _ = clusteritza_i_plota(
        df_geocodificats,
        lat_col="lat",
        lon_col="lon",
        eps_metres=cluster_eps_m,
        min_samples=cluster_min_samples,
        max_punts_per_subcluster=max_partits_subgrup,  
    )

    # Guardem clusters per RUN (si run_id ve informat)
    if run_id is not None:
        for _, r in domicilis_clusteritzats.iterrows():
            adreca_txt = str(r.get("adreca", "")).strip()
            if not adreca_txt:
                continue
            addr = Address.objects.filter(text=adreca_txt).first()
            if not addr:
                continue
            cluster_val = r.get("cluster", None)
            cluster_id = None if pd.isna(cluster_val) else int(cluster_val)
            AddressCluster.objects.update_or_create(
                run_id=run_id,
                address=addr,
                defaults={"cluster_id": cluster_id},
            )

    # Enllacem cluster al df_partits
    df_localitzats = pd.merge(df_partits, domicilis_clusteritzats, on='adreca', how='inner')
    df_partits = pd.merge(df_partits, df_localitzats[['ID', 'cluster']], on='ID', how='left')
    df_partits_geo = df_partits.merge(
        domicilis_clusteritzats[["adreca", "lat", "lon"]],
        on="adreca",
        how="left"
    )

    # Validació: una adreça no pot tenir múltiples clusters
    discrepancies = []
    for adreca, group in df_partits.groupby('adreca'):
        unique_clusters = group['cluster'].dropna().unique()
        if len(unique_clusters) > 1:
            discrepancies.append((adreca, unique_clusters.tolist()))
    if discrepancies:
        if task_id:
            async_to_sync(push_log)(task_id, "S'han trobat discrepàncies de cluster per adreça (revisa log).", 100)
        raise ValueError(f"Discrepàncies de cluster per adreça: {discrepancies[:5]} ...")

    # ------------ Nivells partits ------------
    partits_nivel_order = ["SÈNIOR", "JÚNIOR", 'JUVENIL', "CADET", "INFANTIL", "PREINFANTIL",
                           "ALEVÍ", "PREALEVÍ", "BENJAMÍ", "PREBENJAMÍ", "MENUDETS", "MENUTS"]
    nivel_dtype_partits = CategoricalDtype(categories=partits_nivel_order, ordered=True)
    df_partits['Categoria'] = df_partits['Categoria'].astype(nivel_dtype_partits)
    df_partits = df_partits.sort_values('Categoria').reset_index(drop=True)

    # ------------ Assignació per modalitats ------------
    modalitats = df_partits["Modalitat"].dropna().unique().tolist()

    assigned_tutors = []
    assigned_partit_ids = set()
    assigned_tutor_ids = set()
    rescue_failed_subgroups_count = 0
    rescue_segments_generated_count = 0
    rescue_matches_recovered_count = 0

    def _get_team_position(equip: str, df_classificacions: pd.DataFrame, task_id) -> int:
        equip_norm = _normalize_entity_name(equip)
        for idx, row in df_classificacions.iterrows():
            nom_equip = _normalize_entity_name(row.get('NomEquipMostrar', ''))
            #print(f"Comparant equip '{equip_norm}' amb '{nom_equip}'")
            if nom_equip == equip_norm:
                return idx + 1  # posició 1-based
            
        print(f"Equip '{equip}' no trobat a la classificació.", df_classificacions)
        if task_id:
            async_to_sync(push_log)(task_id, f"Equip '{equip}' no trobat a la classificació, revisa que a JEEB no aparegui amb un nom diferent", 99)
        return -1  # no trobat


    for modalitat in modalitats:
        print(f"\nProcessant modalitat: {modalitat}")
        if task_id:
            async_to_sync(push_log)(task_id, f"Processant modalitat: {modalitat}", 60)

        # mapping DataFrame per modalitat
        map_modalitat = map_modalitat_nom.loc[map_modalitat_nom['Modalitat'] == modalitat].copy()

        df_partits_modalitat = df_partits[df_partits['Modalitat'] == modalitat].copy()
        df_dispos_modalitat = df_dispos[df_dispos['Modalitat'] == modalitat].copy()

        df_dispos_modalitat.reset_index(drop=True, inplace=True)
        df_partits_modalitat.reset_index(drop=True, inplace=True)

        grups = df_partits_modalitat['Grup'].unique()

        # --- classificacions (actualment desactivades al teu codi original) ---
        for grup in grups:
            percentatge = 60 +int((list(grups).index(grup) + 1) / len(grups) * (70-60))
            if task_id:
                async_to_sync(push_log)(task_id, f"Consultant classificacions per grup: {grup}", percentatge)

            df_partits_grup = df_partits_modalitat[df_partits_modalitat['Grup'] == grup].copy()
            if len(df_partits_grup['Grup'].unique()) != 1:
                raise ValueError(f"Múltiples grups detectats dins {grup}")

            genere = df_partits_grup["Subcategoria"].iloc[0]
            if genere == "MIXT":
                p5 = "SXMIX"
            elif genere == "FEMENÍ":
                p5 = "SXFEM"
            else:
                raise ValueError(f"Subcategoria desconeguda: {genere}")

            categoria = df_partits_grup["Categoria"].iloc[0]

            # Aquí necessites Id Categoria (p2) per cridar el servei de classificacions
            p2 = map_modalitat[map_modalitat["Nom"] == categoria]
            if p2.empty:
                # si no hi ha mapping, seguim sense posicions
                continue

            root = None  # mantenim com al teu codi actual
            root = asyncio.run(fetch_ceeb_async(str(p2["Id Categoria"].values[0]), p5, fase=fase))
            if root is None:
                continue

            parsed = parse_ceeb_xml(root)
            df_classificacions = xml_to_dataframe(parsed, grup=grup)
            OUTPUT_COLUMNS = ['NomEquipMostrar', 'isBaixa', 'PJ', 'PG', 'PE', 'PP', 'PUNTS', 'PUNTSBASE', 'PUNTSTOTALSAMBVALORS', 'PUNTSVALORS', 'PUNTSVALORSESPORTISTA', 'PUNTSVALORSTECNIC', 'PUNTSVALORSFAMILIAR', 'AVG', 'PF', 'PC', 'SANC', 'BONIF', 'NOPRESENTAT']
            df_classificacions = df_classificacions[OUTPUT_COLUMNS] if not df_classificacions.empty else df_classificacions
            # Ara, mirem els partits d'aquest grup i afegim la posició de cada equip segons la classificació
            for idx, partit in df_partits_grup.iterrows():
                #print(partit)
                #print(f"\nProcessant partit ID {partit.get('ID', '')} del grup {grup}")
                # Obtenim la posició de l'equip local
                pos_local = _get_team_position(partit.get('Equip local', ''), df_classificacions, task_id)
                pos_visitant = _get_team_position(partit.get('Equip visitant', ''), df_classificacions, task_id)
                #print(f"Posició equip local '{partit.get('Equip local', '')}': {pos_local}, equip visitant '{partit.get('Equip visitant', '')}': {pos_visitant}")

                # Afegim al df dues columnes que indiquin la posicio
                df_partits_modalitat.loc[df_partits_modalitat['ID'] == partit['ID'], 'Posició Equip Local'] = pos_local
                df_partits_modalitat.loc[df_partits_modalitat['ID'] == partit['ID'], 'Posició Equip Visitant'] = pos_visitant
        df_partits_modalitat['Hora'] = _parse_times(df_partits_modalitat['Hora'])
        df_dispos_modalitat['Hora Inici'] = _parse_times(df_dispos_modalitat['Hora Inici'])
        df_dispos_modalitat['Hora Fi'] = _parse_times(df_dispos_modalitat['Hora Fi'])
        df_partits_modalitat["Data"] = _normalize_date_series(df_partits_modalitat["Data"])
        df_dispos_modalitat["Data"] = _normalize_date_series(df_dispos_modalitat["Data"])
        df_partits_modalitat["__match_datetime"] = df_partits_modalitat.apply(
            lambda row: _combine_date_time(row.get("Data"), row.get("Hora")),
            axis=1,
        )

        if task_id:
            async_to_sync(push_log)(task_id, "Creant subgrups de partits...", 75)
        final_subgrups = _build_daily_subgroups(
            df_partits_modalitat,
            gap_same_pitch_min=gap_same_pitch_min,
            gap_diff_pitch_min=gap_diff_pitch_min,
            max_partits_subgrup=max_partits_subgrup,
        )

        # --- matriu costos ---
        subgroup_cost_fn = lambda tutor_row, subgrup: _compute_subgroup_cost(
            tutor_row,
            subgrup,
            tutor_nivel_order=tutor_nivel_order,
            partits_nivel_order=partits_nivel_order,
            nivel_dtype_partits=nivel_dtype_partits,
            availability_end_buffer_min=availability_end_buffer_min,
        )
        C = _build_subgroup_cost_matrix(df_dispos_modalitat, final_subgrups, subgroup_cost_fn)

        if task_id:
            async_to_sync(push_log)(task_id, "Assignant tutors...", 80)

        assigned_pairs = _solve_assignment_pairs(C)
        row_ind = np.array([pair[0] for pair in assigned_pairs], dtype=int)
        col_ind = np.array([pair[1] for pair in assigned_pairs], dtype=int)

        if task_id:
            async_to_sync(push_log)(task_id, "Tutors assignats.", 85)

        # construir assignacions
        for tutor_idx, subgrup_idx in zip(row_ind, col_ind):
            tutor_row = df_dispos_modalitat.iloc[tutor_idx]
            tutor_id = tutor_row['ID']
            tutor_codi = tutor_row['Codi Tutor de Joc']
            tutor_nom = tutor_row.get('Nom', '')
            tutor_cognoms = tutor_row.get('Cognoms', '')
            tutor_nivell = tutor_row.get('Nivell', '')
            tutor_hora_inici = tutor_row.get('Hora Inici', '')
            tutor_hora_fi = tutor_row.get('Hora Fi', '')
            observacions = tutor_row.get('Observacions', '')

            subgrup = final_subgrups[subgrup_idx]
            tutor_was_assigned = False
            for partit in subgrup:
                if C[tutor_idx, subgrup_idx] >= 1e5:
                    continue

                assigned_partit_ids.add(partit['ID'])
                tutor_was_assigned = True
                assigned_tutors.append({
                    'ID': partit.get('ID', ''),
                    'Data Partit': partit.get('Data', ''),
                    'Partit Hora': partit.get('Hora', ''),
                    'Codi Partit': partit.get('Codi', ''),
                    'Pista': partit.get('Pista joc', ''),
                    'Club Visitant': partit.get('Equip visitant', ''),
                    'Categoria': partit.get('Categoria', ''),
                    'Modalitat': partit.get('Modalitat', ''),
                    'Club Local': partit.get('Club Local', ''),
                    'Classificació Equips': (
                        f"Pos Local: {_safe_position_int(partit.get('Posició Equip Local', -1))}, "
                        f"Pos Visitant: {_safe_position_int(partit.get('Posició Equip Visitant', -1))}"
                    ),
                    'Tutor Codi': tutor_codi,
                    'Tutor Nom': tutor_nom,
                    'Tutor Cognoms': tutor_cognoms,
                    'Tutor Nivell': tutor_nivell,
                    'Tutor Hora Inici': tutor_hora_inici,
                    'Tutor Hora Fi': tutor_hora_fi,
                    'Observacions': observacions
                })
            if tutor_was_assigned:
                assigned_tutor_ids.add(tutor_id)

        covered_subgroup_indexes = set(col_ind.tolist())
        failed_subgroups = [
            final_subgrups[idx]
            for idx in range(len(final_subgrups))
            if idx not in covered_subgroup_indexes
        ]
        rescue_failed_subgroups_count += len(failed_subgroups)

        idle_referees = (
            df_dispos_modalitat[~df_dispos_modalitat["ID"].isin(assigned_tutor_ids)]
            .copy()
            .reset_index(drop=True)
        )
        rescue_result = _run_rescue_assignment(idle_referees, failed_subgroups, subgroup_cost_fn)
        rescue_segments = rescue_result["segments"]
        rescue_segments_generated_count += len(rescue_segments)

        for tutor_idx, segment_idx in rescue_result["pairs"]:
            tutor_row = idle_referees.iloc[tutor_idx]
            tutor_id = tutor_row["ID"]
            tutor_codi = tutor_row["Codi Tutor de Joc"]
            tutor_nom = tutor_row.get("Nom", "")
            tutor_cognoms = tutor_row.get("Cognoms", "")
            tutor_nivell = tutor_row.get("Nivell", "")
            tutor_hora_inici = tutor_row.get("Hora Inici", "")
            tutor_hora_fi = tutor_row.get("Hora Fi", "")
            observacions = tutor_row.get("Observacions", "")

            segment = rescue_segments[segment_idx]
            tutor_was_assigned = False
            for partit in segment:
                assigned_partit_ids.add(partit["ID"])
                tutor_was_assigned = True
                assigned_tutors.append({
                    "ID": partit.get("ID", ""),
                    "Data Partit": partit.get("Data", ""),
                    "Partit Hora": partit.get("Hora", ""),
                    "Codi Partit": partit.get("Codi", ""),
                    "Pista": partit.get("Pista joc", ""),
                    "Club Visitant": partit.get("Equip visitant", ""),
                    "Categoria": partit.get("Categoria", ""),
                    "Modalitat": partit.get("Modalitat", ""),
                    "Club Local": partit.get("Club Local", ""),
                    "Classificació Equips": (
                        f"Pos Local: {_safe_position_int(partit.get('Posició Equip Local', -1))}, "
                        f"Pos Visitant: {_safe_position_int(partit.get('Posició Equip Visitant', -1))}"
                    ),
                    "Tutor Codi": tutor_codi,
                    "Tutor Nom": tutor_nom,
                    "Tutor Cognoms": tutor_cognoms,
                    "Tutor Nivell": tutor_nivell,
                    "Tutor Hora Inici": tutor_hora_inici,
                    "Tutor Hora Fi": tutor_hora_fi,
                    "Observacions": observacions
                })
            if tutor_was_assigned:
                assigned_tutor_ids.add(tutor_id)
                rescue_matches_recovered_count += len(segment)

    df_assignacions = pd.DataFrame(assigned_tutors)
    if not df_assignacions.empty:
        df_assignacions['Tutor'] = (df_assignacions.get('Tutor Nom', '').fillna('') + ' ' +
                                    df_assignacions.get('Tutor Cognoms', '').fillna('')).str.strip()
        df_assignacions = df_assignacions.sort_values(['Tutor Codi', 'Data Partit', 'Partit Hora']).reset_index(drop=True)

        # --- Persistència a BD (Assignment/Match/Referee) ---
    if run_id is not None:
        persist_assignacions_to_db(
            run_id=run_id,
            df_partits=df_partits,
            df_dispos=df_dispos,
            df_assignacions=df_assignacions,
        )

    # --- Mapa: desa dins MEDIA_ROOT/designacions/maps/ ---
    map_rel_path = None
    out_map_abs = None
    if run_id is not None:
        maps_dir = os.path.join(MEDIA_ROOT, "designacions", "maps")
        os.makedirs(maps_dir, exist_ok=True)
        out_map_abs = os.path.join(maps_dir, f"run_{run_id}.html")
        map_rel_path = os.path.join("designacions", "maps", f"run_{run_id}.html")

    if task_id:
        async_to_sync(push_log)(task_id, "Generant mapa d'assignacions.", 92)

    if not out_map_abs:
        raise RuntimeError("No s'ha pogut determinar el path del mapa (run_id absent).")


    out_map = mapa_assignacions_interactiu(
        df_partits_geo=df_partits_geo,
        df_assignacions=df_assignacions if not df_assignacions.empty else pd.DataFrame(columns=["Codi Partit"]),
        out_html=out_map_abs or "mapa_assignacions.html",
        mostra_totes_les_seus=True
    )

    if task_id:
        async_to_sync(push_log)(task_id, "Mapa generat.", 94)

    # --- No assignats (per resum) ---
    all_partit_ids = set(df_partits['ID'])
    unassigned_partit_ids = all_partit_ids - assigned_partit_ids
    df_unassigned = df_partits[df_partits['ID'].isin(unassigned_partit_ids)] if unassigned_partit_ids else pd.DataFrame()

    all_tutor_ids = set(df_dispos['ID'])
    unassigned_tutor_ids = all_tutor_ids - assigned_tutor_ids
    df_unassigned_tutors = df_dispos[df_dispos['ID'].isin(unassigned_tutor_ids)] if unassigned_tutor_ids else pd.DataFrame()
    unassigned_tutor_codes = (
        df_unassigned_tutors["Codi Tutor de Joc"].astype(str).str.strip().replace("", pd.NA).dropna().unique().tolist()
        if not df_unassigned_tutors.empty and "Codi Tutor de Joc" in df_unassigned_tutors.columns
        else []
    )

    if task_id:
        async_to_sync(push_log)(task_id, "Procés del motor finalitzat.", 96)

    # Retornem un resum (no Excel)
    return {
        "assigned": int(len(df_assignacions)) if df_assignacions is not None else 0,
        "unassigned_matches": int(len(df_unassigned)) if df_unassigned is not None else 0,
        "unassigned_referees": int(len(unassigned_tutor_codes)),
        "needs_review_referees": int(
            df_revisio_sense_nivell["Codi Tutor de Joc"].astype(str).str.strip().replace("", pd.NA).dropna().nunique()
        ) if df_revisio_sense_nivell is not None and not df_revisio_sense_nivell.empty else 0,
        "rescue_failed_subgroups": int(rescue_failed_subgroups_count),
        "rescue_segments_generated": int(rescue_segments_generated_count),
        "rescue_matches_recovered": int(rescue_matches_recovered_count),
        "map_path": map_rel_path,   # relatiu a MEDIA_ROOT
    }


if __name__ == "__main__":

    main(file_path_dispo, file_path_partits)
