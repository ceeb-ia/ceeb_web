from __future__ import annotations

import os
from collections import defaultdict
from pathlib import Path

import pandas as pd
from asgiref.sync import async_to_sync
from django.conf import settings

from logs import push_log

from ..geolocate import extreu_municipi
from ..models import Address
from ..services.addressing import build_address_payload
from ..services.geocoding_db import geocodifica_adreces
from ..services.run_scope import filter_run_dataframes, load_scoped_run_data
from .contracts import PreviewAddressPoint, PreviewResult, PreviewScenario
from .engine import cluster_points_dataframe
from .maps import render_preview_map
from .metrics import build_preview_metrics
from .overrides import apply_preview_overrides, enrich_preview_overrides, resolve_preview_overrides
from .selectors import build_eps_options, pick_recommended_scenario


def _log(task_id: str | None, message: str, progress: int | None = None):
    if task_id:
        async_to_sync(push_log)(task_id, message, progress)


def _build_partits_with_addresses(df_partits: pd.DataFrame) -> pd.DataFrame:
    out = df_partits.copy()
    address_payloads = out.apply(
        lambda row: build_address_payload(domicile=row.get("Domicili"), municipality=row.get("Municipi")),
        axis=1,
    )
    out["adreca"] = address_payloads.map(lambda payload: payload["text"])
    out["normalized_adreca"] = address_payloads.map(lambda payload: payload["normalized_text"])
    return out


def _resolve_existing_address_state(address_texts: list[str]) -> dict[str, bool]:
    payloads = [build_address_payload(text=text, municipality=extreu_municipi(text)) for text in address_texts]
    normalized_values = [payload["normalized_text"] for payload in payloads if payload["normalized_text"]]
    existing = {
        address.normalized_text: bool(address.lat is not None and address.lon is not None)
        for address in Address.objects.filter(normalized_text__in=normalized_values)
    }
    return existing


def _build_points_dataframe(df_partits: pd.DataFrame, addresses: list[Address], fresh_geocode_by_norm: dict[str, bool]) -> pd.DataFrame:
    address_by_norm = {address.normalized_text: address for address in addresses if address.normalized_text}
    matches_by_address = defaultdict(list)
    for _, row in df_partits.iterrows():
        normalized = row.get("normalized_adreca")
        if not normalized:
            continue
        address = address_by_norm.get(normalized)
        if not address:
            continue
        matches_by_address[address.id].append(row)

    point_rows = []
    for address in addresses:
        related_matches = matches_by_address.get(address.id, [])
        venue_count = len(
            {
                str(match.get("Pista joc", "")).strip()
                for match in related_matches
                if str(match.get("Pista joc", "")).strip()
            }
        )
        modalities = sorted(
            {
                str(match.get("Modalitat", "")).strip()
                for match in related_matches
                if str(match.get("Modalitat", "")).strip()
            }
        )
        point_rows.append(
            {
                "address_id": address.id,
                "adreca": address.text,
                "municipality": address.municipality or "",
                "lat": address.lat,
                "lon": address.lon,
                "geocode_status": address.geocode_status or "pending",
                "provider": address.provider or "",
                "is_fresh_geocode": bool(fresh_geocode_by_norm.get(address.normalized_text or "", False)),
                "match_count": len(related_matches),
                "venue_count": venue_count,
                "modalities": modalities,
            }
        )

    return pd.DataFrame(point_rows)


def _attach_clusters_to_matches(df_partits: pd.DataFrame, scenario_points_df: pd.DataFrame) -> pd.DataFrame:
    cluster_info = scenario_points_df[["address_id", "cluster", "cluster_status"]].copy()
    return df_partits.merge(cluster_info, on="address_id", how="left")


def _build_preview_counts(points_df: pd.DataFrame, df_partits: pd.DataFrame) -> dict:
    return {
        "total_matches": int(len(df_partits)),
        "total_unique_addresses": int(len(points_df)),
        "total_geocoded_addresses": int(points_df[["lat", "lon"]].dropna().shape[0]) if not points_df.empty else 0,
        "total_missing_geocode_addresses": int(points_df["lat"].isna().sum()) if not points_df.empty else 0,
        "total_unique_venues": int(df_partits["Pista joc"].dropna().nunique()) if not df_partits.empty and "Pista joc" in df_partits.columns else 0,
    }


def _build_availability_counts(df_dispos: pd.DataFrame) -> dict:
    if df_dispos.empty:
        return {
            "total_availability_rows": 0,
            "total_unique_referees": 0,
            "total_modalities_with_referees": 0,
        }

    working = df_dispos.copy()
    unique_referees = (
        working["Codi Tutor de Joc"].dropna().astype(str).str.strip().replace("", pd.NA).dropna().nunique()
        if "Codi Tutor de Joc" in working.columns
        else 0
    )
    modalities_with_referees = (
        working["Modalitat"].dropna().astype(str).str.strip().replace("", pd.NA).dropna().nunique()
        if "Modalitat" in working.columns
        else 0
    )
    return {
        "total_availability_rows": int(len(working)),
        "total_unique_referees": int(unique_referees),
        "total_modalities_with_referees": int(modalities_with_referees),
    }


def _build_modality_breakdown(
    df_dispos: pd.DataFrame,
    scenario_matches_df: pd.DataFrame,
    *,
    gap_same_pitch_min: int,
    gap_diff_pitch_min: int,
    max_partits_subgrup: int,
) -> list[dict]:
    if df_dispos.empty and scenario_matches_df.empty:
        return []

    from ..main_fixed import _build_daily_subgroups_with_stats

    modality_values = set()
    if "Modalitat" in df_dispos.columns:
        modality_values.update(
            value
            for value in df_dispos["Modalitat"].dropna().astype(str).str.strip().tolist()
            if value
        )
    if "Modalitat" in scenario_matches_df.columns:
        modality_values.update(
            value
            for value in scenario_matches_df["Modalitat"].dropna().astype(str).str.strip().tolist()
            if value
        )

    rows = []
    for modality in sorted(modality_values):
        matches_group = (
            scenario_matches_df[scenario_matches_df["Modalitat"] == modality].copy()
            if "Modalitat" in scenario_matches_df.columns
            else pd.DataFrame()
        )
        dispos_group = (
            df_dispos[df_dispos["Modalitat"] == modality].copy()
            if "Modalitat" in df_dispos.columns
            else pd.DataFrame()
        )

        subgroup_stats = {"base_subgroups": 0, "fused_subgroups": 0}
        if not matches_group.empty:
            subgroup_stats = _build_daily_subgroups_with_stats(
                matches_group,
                gap_same_pitch_min=gap_same_pitch_min,
                gap_diff_pitch_min=gap_diff_pitch_min,
                max_partits_subgrup=max_partits_subgrup,
            )

        unique_referees = (
            dispos_group["Codi Tutor de Joc"].dropna().astype(str).str.strip().replace("", pd.NA).dropna().nunique()
            if not dispos_group.empty and "Codi Tutor de Joc" in dispos_group.columns
            else 0
        )
        matches_count = int(len(matches_group))
        fused_subgroups = int(subgroup_stats["fused_subgroups"])
        rows.append(
            {
                "modality": modality,
                "matches": matches_count,
                "availability_rows": int(len(dispos_group)),
                "unique_referees": int(unique_referees),
                "estimated_base_subgroups": int(subgroup_stats["base_subgroups"]),
                "estimated_fused_subgroups": fused_subgroups,
                "matches_per_referee": round(matches_count / unique_referees, 2) if unique_referees else None,
                "subgroups_per_referee": round(fused_subgroups / unique_referees, 2) if unique_referees else None,
            }
        )
    return rows


def _build_geocoding_issues(points_df: pd.DataFrame) -> list[dict]:
    if points_df.empty:
        return []
    issues = []
    missing_df = points_df[points_df["lat"].isna() | points_df["lon"].isna()]
    for _, row in missing_df.iterrows():
        issues.append(
            {
                "address_id": row.get("address_id"),
                "adreca": row.get("adreca"),
                "municipality": row.get("municipality") or "",
                "geocode_status": row.get("geocode_status") or "pending",
                "match_count": int(row.get("match_count") or 0),
            }
        )
    return issues


def _scenario_map_abs_path(base_out_map_abs: str, eps_m: int) -> str:
    base_path = Path(base_out_map_abs)
    return str(base_path.with_name(f"{base_path.stem}__eps_{eps_m}{base_path.suffix}"))


def build_cluster_preview(
    *,
    preview_id: str | None = None,
    path_disponibilitats: str | None = None,
    path_partits: str | None = None,
    params: dict | None = None,
    task_id: str | None = None,
    out_map_abs: str | None = None,
    df_dispos: pd.DataFrame | None = None,
    df_partits: pd.DataFrame | None = None,
) -> PreviewResult:
    params = dict(params or {})
    if df_dispos is None or df_partits is None:
        if not path_disponibilitats or not path_partits:
            raise ValueError("Cal indicar fitxers o DataFrames per construir el preview.")
        df_dispos, df_partits = load_scoped_run_data(path_disponibilitats, path_partits, params=params)
    else:
        df_dispos, df_partits = filter_run_dataframes(df_dispos, df_partits, params=params)

    cluster_eps_m = int(float(params.get("cluster_eps_m", 500)))
    cluster_min_samples = int(params.get("cluster_min_samples", 2))
    max_partits_subgrup = int(params.get("max_partits_subgrup", 3))
    gap_same_pitch_min = int(params.get("gap_same_pitch_min", 60))
    gap_diff_pitch_min = int(params.get("gap_diff_pitch_min", 75))
    eps_options = build_eps_options(cluster_eps_m, params.get("preview_cluster_eps_options"))

    _log(task_id, "Preparant dades del preview de geolocalitzacio.", 8)
    df_partits_preview = _build_partits_with_addresses(df_partits)
    adreces_uniques = [
        value
        for value in df_partits_preview["adreca"].dropna().drop_duplicates().tolist()
        if str(value).strip()
    ]

    _log(task_id, "Verificant adreces existents i punts pendents.", 18)
    before_geocode = _resolve_existing_address_state(adreces_uniques)

    _log(task_id, "Geocodificant escoles i seus necessaries per al preview.", 28)
    addresses = geocodifica_adreces(adreces_uniques, task_id=task_id)
    address_by_norm = {address.normalized_text: address for address in addresses if address.normalized_text}
    fresh_geocode_by_norm = {
        normalized: (not before_geocode.get(normalized, False) and bool(address.lat is not None and address.lon is not None))
        for normalized, address in address_by_norm.items()
    }

    df_partits_preview["address_id"] = df_partits_preview["normalized_adreca"].map(
        lambda normalized: getattr(address_by_norm.get(normalized), "id", None)
    )

    _log(task_id, "Construint punts agregats per seu.", 46)
    points_df = _build_points_dataframe(df_partits_preview, addresses, fresh_geocode_by_norm)
    preview_counts = _build_preview_counts(points_df, df_partits_preview)
    availability_counts = _build_availability_counts(df_dispos)
    geocoding_issues = _build_geocoding_issues(points_df)
    raw_overrides = params.get("cluster_overrides") or params.get("preview_cluster_overrides") or []
    effective_overrides = resolve_preview_overrides(
        preview_id=preview_id,
        inline_overrides=raw_overrides if isinstance(raw_overrides, list) else [],
    )
    override_payload = enrich_preview_overrides(points_df, effective_overrides)

    _log(task_id, "Calculant escenaris de clusteritzacio.", 58)
    if out_map_abs:
        _log(task_id, "Renderitzant mapes de preview per radi.", 82)
    scenarios = []
    for eps_m in eps_options:
        scenario_points_df = cluster_points_dataframe(
            points_df,
            eps_m=eps_m,
            min_samples=cluster_min_samples,
            max_points_per_subcluster=max_partits_subgrup,
        )
        scenario_points_df, scenario_override_effects, scenario_override_summary = apply_preview_overrides(
            scenario_points_df,
            effective_overrides,
        )
        scenario_matches_df = _attach_clusters_to_matches(df_partits_preview, scenario_points_df)
        metrics = build_preview_metrics(
            scenario_points_df,
            scenario_matches_df,
            max_points_per_subcluster=max_partits_subgrup,
            gap_same_pitch_min=gap_same_pitch_min,
            gap_diff_pitch_min=gap_diff_pitch_min,
            max_partits_subgrup=max_partits_subgrup,
        )
        point_objects = [
            PreviewAddressPoint(
                address_id=int(row["address_id"]) if pd.notna(row["address_id"]) else None,
                adreca=str(row.get("adreca", "") or ""),
                municipality=str(row.get("municipality", "") or ""),
                lat=float(row["lat"]) if pd.notna(row.get("lat")) else None,
                lon=float(row["lon"]) if pd.notna(row.get("lon")) else None,
                geocode_status=str(row.get("geocode_status", "") or "pending"),
                provider=str(row.get("provider", "") or ""),
                is_fresh_geocode=bool(row.get("is_fresh_geocode", False)),
                match_count=int(row.get("match_count") or 0),
                venue_count=int(row.get("venue_count") or 0),
                modalities=list(row.get("modalities") or []),
                cluster=int(row["cluster"]) if pd.notna(row.get("cluster")) and int(row.get("cluster")) != -1 else None,
                cluster_status=str(row.get("cluster_status", "") or "pending"),
                auto_cluster=int(row["auto_cluster"]) if pd.notna(row.get("auto_cluster")) and int(row.get("auto_cluster")) != -1 else None,
                auto_cluster_status=str(row.get("auto_cluster_status", "") or "pending"),
                is_manual=bool(row.get("is_manual", False)),
                manual_role=str(row.get("manual_role")) if row.get("manual_role") else None,
                cluster_origin=str(row.get("cluster_origin", "") or "automatic"),
                manual_override_ids=list(row.get("manual_override_ids") or []),
                manual_override_kinds=list(row.get("manual_override_kinds") or []),
            )
            for _, row in scenario_points_df.iterrows()
        ]
        scenario = PreviewScenario(
            eps_m=int(eps_m),
            min_samples=cluster_min_samples,
            max_points_per_subcluster=max_partits_subgrup,
            points=point_objects,
            metrics=metrics,
            modality_breakdown=_build_modality_breakdown(
                df_dispos,
                scenario_matches_df,
                gap_same_pitch_min=gap_same_pitch_min,
                gap_diff_pitch_min=gap_diff_pitch_min,
                max_partits_subgrup=max_partits_subgrup,
            ),
            active_overrides=scenario_override_effects,
            manual_point_count=int(scenario_override_summary.get("manual_point_count") or 0),
            manual_cluster_count=int(scenario_override_summary.get("manual_cluster_count") or 0),
            override_summary=scenario_override_summary,
        )
        if out_map_abs:
            saved_abs_path = render_preview_map(scenario, _scenario_map_abs_path(out_map_abs, int(eps_m)))
            if saved_abs_path:
                try:
                    scenario.map_path = os.path.relpath(saved_abs_path, settings.MEDIA_ROOT).replace("\\", "/")
                except Exception:
                    scenario.map_path = saved_abs_path
        scenarios.append(scenario)

    recommended = pick_recommended_scenario(scenarios)
    recommended_eps_m = recommended.eps_m if recommended else None
    selected_eps_m = cluster_eps_m if any(scenario.eps_m == cluster_eps_m for scenario in scenarios) else (recommended_eps_m or (scenarios[0].eps_m if scenarios else cluster_eps_m))
    selected_scenario = None
    for scenario in scenarios:
        scenario.recommended = bool(recommended and scenario.eps_m == recommended.eps_m)
        scenario.selected = scenario.eps_m == selected_eps_m
        if scenario.selected:
            selected_scenario = scenario

    map_path = None
    if out_map_abs and selected_scenario:
        map_path = selected_scenario.map_path

    summary = {
        "selected_eps_m": selected_eps_m,
        "recommended_eps_m": recommended_eps_m,
        "scenario_count": len(scenarios),
        "fresh_geocoded_points": int(sum(1 for scenario in scenarios[:1] for point in scenario.points if point.is_fresh_geocode)),
        "missing_geocode_points": int(len(geocoding_issues)),
        "active_override_count": len(override_payload),
        "manual_point_count": int(selected_scenario.manual_point_count) if selected_scenario else 0,
    }

    _log(task_id, "Preview de clusters preparat.", 92)
    return PreviewResult(
        params=params,
        selected_eps_m=selected_eps_m,
        recommended_eps_m=recommended_eps_m,
        scenarios=scenarios,
        summary=summary,
        map_path=map_path,
        geocoding_issues=geocoding_issues,
        preview_counts=preview_counts,
        availability_counts=availability_counts,
        cluster_overrides=override_payload,
        override_summary={
            "active_override_count": len(override_payload),
            "override_kinds": sorted({override.kind for override in override_payload}),
            "manual_point_count": int(selected_scenario.manual_point_count) if selected_scenario else 0,
            "manual_cluster_count": int(selected_scenario.manual_cluster_count) if selected_scenario else 0,
        },
    )
