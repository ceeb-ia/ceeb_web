from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.cluster import DBSCAN


EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1, lon1, lat2, lon2):
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    c = 2 * np.arcsin(np.sqrt(a))
    return EARTH_RADIUS_KM * c


def _cluster_status_from_values(cluster_value, lat_value, lon_value) -> str:
    lat_missing = lat_value is None or pd.isna(lat_value)
    lon_missing = lon_value is None or pd.isna(lon_value)
    if lat_missing or lon_missing:
        return "missing_geocode"
    if cluster_value is None or pd.isna(cluster_value):
        return "outlier"
    try:
        if int(cluster_value) == -1:
            return "outlier"
    except (TypeError, ValueError):
        pass
    return "clustered"


def _apply_subcluster_limit(
    df: pd.DataFrame,
    *,
    lat_col: str,
    lon_col: str,
    cluster_col: str,
    max_points_per_subcluster: int,
) -> pd.DataFrame:
    if max_points_per_subcluster <= 0:
        return df

    out = df.copy()
    valid_cluster_values = []
    for raw_value in out[cluster_col].dropna().tolist():
        try:
            valid_cluster_values.append(int(raw_value))
        except (TypeError, ValueError):
            continue
    next_cluster_id = (max(valid_cluster_values) + 1) if valid_cluster_values else 0

    for cluster_id in out[cluster_col].dropna().unique():
        try:
            cluster_id_int = int(cluster_id)
        except (TypeError, ValueError):
            continue
        if cluster_id_int == -1:
            continue

        subdf = out[out[cluster_col] == cluster_id].copy()
        if len(subdf) <= max_points_per_subcluster:
            continue

        lat = np.radians(subdf[lat_col].astype(float).to_numpy())
        lon = np.radians(subdf[lon_col].astype(float).to_numpy())
        dist = haversine_km(lat[:, None], lon[:, None], lat[None, :], lon[None, :])
        np.fill_diagonal(dist, np.inf)

        n = len(subdf)
        assigned_pos = set()
        pos_to_idx = list(subdf.index)
        while len(assigned_pos) < n:
            remaining = [position for position in range(n) if position not in assigned_pos]
            seed = remaining[0]
            neighbours = [candidate for candidate in sorted(remaining, key=lambda candidate: dist[seed, candidate]) if candidate != seed]
            take = [seed] + neighbours[: min(max_points_per_subcluster - 1, len(neighbours))]
            for position in take:
                original_index = pos_to_idx[position]
                out.at[original_index, cluster_col] = next_cluster_id
                assigned_pos.add(position)
            next_cluster_id += 1

    out[cluster_col] = pd.to_numeric(out[cluster_col], errors="coerce").astype("Int64")
    return out


def cluster_points_dataframe(
    df: pd.DataFrame,
    *,
    lat_col: str = "lat",
    lon_col: str = "lon",
    eps_m: float = 500,
    min_samples: int = 2,
    cluster_col: str = "cluster",
    max_points_per_subcluster: int = 0,
) -> pd.DataFrame:
    out = df.copy()
    out[cluster_col] = pd.Series([pd.NA] * len(out), dtype="Int64")

    if lat_col not in out.columns or lon_col not in out.columns:
        raise ValueError(f"El DataFrame ha de contenir '{lat_col}' i '{lon_col}'.")

    coords = out[[lat_col, lon_col]].astype(float)
    coords = coords.dropna()
    if not coords.empty:
        coords_rad = np.radians(coords.to_numpy())
        eps = (float(eps_m) / 1000.0) / EARTH_RADIUS_KM
        model = DBSCAN(eps=eps, min_samples=int(min_samples), metric="haversine")
        labels = model.fit_predict(coords_rad)
        out.loc[coords.index, cluster_col] = pd.Series(labels, index=coords.index, dtype="Int64")

    if max_points_per_subcluster and max_points_per_subcluster > 0:
        out = _apply_subcluster_limit(
            out,
            lat_col=lat_col,
            lon_col=lon_col,
            cluster_col=cluster_col,
            max_points_per_subcluster=int(max_points_per_subcluster),
        )

    out["cluster_status"] = out.apply(
        lambda row: _cluster_status_from_values(row.get(cluster_col), row.get(lat_col), row.get(lon_col)),
        axis=1,
    )
    return out
