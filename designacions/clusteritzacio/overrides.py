from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path

import pandas as pd
from django.conf import settings

from .contracts import PreviewClusterOverride


PREVIEW_OVERRIDE_REL_DIR = os.path.join("designacions", "preview_overrides")


def _preview_override_abs_path(preview_id: str) -> str:
    return str(Path(settings.MEDIA_ROOT) / PREVIEW_OVERRIDE_REL_DIR / f"{preview_id}.json")


def _normalize_override(raw_override) -> dict | None:
    if not isinstance(raw_override, dict):
        return None

    kind_aliases = {
        "merge": "merge_with_address",
        "merge_with_address": "merge_with_address",
        "isolate": "isolate_address",
        "isolate_address": "isolate_address",
    }
    raw_kind = str(raw_override.get("kind") or raw_override.get("action") or "").strip().lower()
    kind = kind_aliases.get(raw_kind)
    if not kind:
        return None

    try:
        source_address_id = int(raw_override.get("source_address_id") or raw_override.get("address_id"))
    except (TypeError, ValueError):
        return None

    normalized = {
        "override_id": str(raw_override.get("override_id") or uuid.uuid4().hex),
        "kind": kind,
        "source_address_id": source_address_id,
        "created_at": str(raw_override.get("created_at") or int(time.time())),
    }
    if kind == "merge_with_address":
        try:
            target_address_id = int(raw_override.get("target_address_id"))
        except (TypeError, ValueError):
            return None
        if target_address_id == source_address_id:
            return None
        normalized["target_address_id"] = target_address_id
    return normalized


def _normalize_override_list(raw_overrides) -> list[dict]:
    normalized_by_source: dict[int, dict] = {}
    items = raw_overrides.values() if isinstance(raw_overrides, dict) else (raw_overrides or [])
    for raw_override in items:
        normalized = _normalize_override(raw_override)
        if not normalized:
            continue
        normalized_by_source[int(normalized["source_address_id"])] = normalized
    return [normalized_by_source[address_id] for address_id in sorted(normalized_by_source)]


def load_preview_overrides(preview_id: str) -> list[dict]:
    abs_path = _preview_override_abs_path(preview_id)
    if not os.path.exists(abs_path):
        return []
    with open(abs_path, "r", encoding="utf-8") as handle:
        try:
            payload = json.load(handle)
        except json.JSONDecodeError:
            return []
    return _normalize_override_list(payload)


def save_preview_overrides(preview_id: str, overrides) -> list[dict]:
    normalized = _normalize_override_list(overrides)
    abs_path = _preview_override_abs_path(preview_id)
    Path(abs_path).parent.mkdir(parents=True, exist_ok=True)
    with open(abs_path, "w", encoding="utf-8") as handle:
        json.dump(normalized, handle, ensure_ascii=False, indent=2)
    return normalized


def clear_preview_overrides(preview_id: str):
    abs_path = _preview_override_abs_path(preview_id)
    if os.path.exists(abs_path):
        os.remove(abs_path)


def add_preview_override(preview_id: str, override_payload: dict) -> list[dict]:
    overrides = load_preview_overrides(preview_id)
    normalized = _normalize_override(override_payload)
    if normalized is None:
        return overrides
    by_source = {int(item["source_address_id"]): item for item in overrides}
    by_source[int(normalized["source_address_id"])] = normalized
    return save_preview_overrides(preview_id, by_source.values())


def remove_preview_override(preview_id: str, *, source_address_id: int) -> list[dict]:
    overrides = load_preview_overrides(preview_id)
    filtered = [item for item in overrides if int(item["source_address_id"]) != int(source_address_id)]
    return save_preview_overrides(preview_id, filtered)


def resolve_preview_overrides(*, preview_id: str | None = None, inline_overrides=None) -> list[dict]:
    if preview_id:
        persisted = load_preview_overrides(preview_id)
        if persisted:
            return persisted
    return _normalize_override_list(inline_overrides)


def enrich_preview_overrides(points_df: pd.DataFrame, overrides) -> list[PreviewClusterOverride]:
    normalized = _normalize_override_list(overrides)
    if not normalized:
        return []

    address_labels: dict[int, str] = {}
    if not points_df.empty and "address_id" in points_df.columns:
        for _, row in points_df.iterrows():
            address_id = row.get("address_id")
            if pd.isna(address_id):
                continue
            address_labels[int(address_id)] = str(row.get("adreca") or "")

    payload = []
    for override in normalized:
        target_address_id = override.get("target_address_id")
        payload.append(
            PreviewClusterOverride(
                override_id=str(override["override_id"]),
                kind=str(override["kind"]),
                source_address_id=int(override["source_address_id"]),
                target_address_id=int(target_address_id) if target_address_id is not None else None,
                source_adreca=address_labels.get(int(override["source_address_id"]), ""),
                target_adreca=address_labels.get(int(target_address_id), "") if target_address_id is not None else "",
                created_at=str(override.get("created_at") or ""),
            )
        )
    return payload


def apply_preview_overrides(points_df: pd.DataFrame, overrides) -> tuple[pd.DataFrame, list[dict], dict]:
    out = points_df.copy()
    normalized = _normalize_override_list(overrides)

    out["auto_cluster"] = out.get("cluster")
    out["auto_cluster_status"] = out.get("cluster_status", "pending")
    out["is_manual"] = False
    out["manual_role"] = None
    out["cluster_origin"] = "automatic"
    out["manual_override_ids"] = [[] for _ in range(len(out))]
    out["manual_override_kinds"] = [[] for _ in range(len(out))]

    if out.empty or not normalized:
        return out, [], {"applied_override_count": 0, "manual_point_count": 0, "manual_cluster_count": 0}

    index_by_address_id = {}
    for idx, row in out.iterrows():
        address_id = row.get("address_id")
        if pd.isna(address_id):
            continue
        index_by_address_id[int(address_id)] = idx

    valid_clusters = []
    for raw_value in out.get("cluster", pd.Series(dtype="object")).dropna().tolist():
        try:
            cluster_value = int(raw_value)
        except (TypeError, ValueError):
            continue
        if cluster_value != -1:
            valid_clusters.append(cluster_value)
    next_cluster_id = (max(valid_clusters) + 1) if valid_clusters else 0

    effects = []
    applied_override_count = 0

    for override in normalized:
        override_id = str(override["override_id"])
        kind = str(override["kind"])
        source_address_id = int(override["source_address_id"])
        source_idx = index_by_address_id.get(source_address_id)
        if source_idx is None:
            effects.append(
                {
                    "override_id": override_id,
                    "kind": kind,
                    "status": "skipped_missing_source",
                    "label": "Override ignorat",
                    "description": f"No s'ha trobat la seu {source_address_id} en aquest preview.",
                }
            )
            continue

        source_adreca = str(out.at[source_idx, "adreca"] or "")

        if kind == "isolate_address":
            cluster_id = next_cluster_id
            next_cluster_id += 1
            out.at[source_idx, "cluster"] = cluster_id
            out.at[source_idx, "cluster_status"] = "clustered"
            out.at[source_idx, "is_manual"] = True
            out.at[source_idx, "manual_role"] = "isolated"
            out.at[source_idx, "cluster_origin"] = "manual"
            out.at[source_idx, "manual_override_ids"] = [override_id]
            out.at[source_idx, "manual_override_kinds"] = [kind]
            applied_override_count += 1
            effects.append(
                {
                    "override_id": override_id,
                    "kind": kind,
                    "status": "applied",
                    "label": "Seu aillada manualment",
                    "description": f"{source_adreca} passa a tenir un cluster manual independent.",
                    "source_name": source_adreca,
                }
            )
            continue

        if kind != "merge_with_address":
            effects.append(
                {
                    "override_id": override_id,
                    "kind": kind,
                    "status": "skipped_unknown_kind",
                    "label": "Override ignorat",
                    "description": f"No s'entén l'accio {kind}.",
                }
            )
            continue

        target_address_id = override.get("target_address_id")
        target_idx = index_by_address_id.get(int(target_address_id)) if target_address_id is not None else None
        if target_idx is None:
            effects.append(
                {
                    "override_id": override_id,
                    "kind": kind,
                    "status": "skipped_missing_target",
                    "label": "Override ignorat",
                    "description": f"No s'ha trobat la seu desti {target_address_id}.",
                    "source_name": source_adreca,
                }
            )
            continue

        source_cluster = out.at[source_idx, "cluster"]
        target_cluster = out.at[target_idx, "cluster"]
        cluster_id = None
        for raw_cluster in (target_cluster, source_cluster):
            if pd.isna(raw_cluster):
                continue
            try:
                cluster_value = int(raw_cluster)
            except (TypeError, ValueError):
                continue
            if cluster_value != -1:
                cluster_id = cluster_value
                break
        if cluster_id is None:
            cluster_id = next_cluster_id
            next_cluster_id += 1

        target_adreca = str(out.at[target_idx, "adreca"] or "")
        out.at[source_idx, "cluster"] = cluster_id
        out.at[source_idx, "cluster_status"] = "clustered"
        out.at[source_idx, "is_manual"] = True
        out.at[source_idx, "manual_role"] = "merged"
        out.at[source_idx, "cluster_origin"] = "manual"
        out.at[source_idx, "manual_override_ids"] = [override_id]
        out.at[source_idx, "manual_override_kinds"] = [kind]

        out.at[target_idx, "cluster"] = cluster_id
        out.at[target_idx, "cluster_status"] = "clustered"
        out.at[target_idx, "is_manual"] = True
        if not out.at[target_idx, "manual_role"]:
            out.at[target_idx, "manual_role"] = "merge_target"
        existing_ids = list(out.at[target_idx, "manual_override_ids"] or [])
        existing_kinds = list(out.at[target_idx, "manual_override_kinds"] or [])
        if override_id not in existing_ids:
            existing_ids.append(override_id)
        if kind not in existing_kinds:
            existing_kinds.append(kind)
        out.at[target_idx, "manual_override_ids"] = existing_ids
        out.at[target_idx, "manual_override_kinds"] = existing_kinds

        applied_override_count += 1
        effects.append(
            {
                "override_id": override_id,
                "kind": kind,
                "status": "applied",
                "label": "Fusio manual de seus",
                "description": f"{source_adreca} s'assigna al cluster de {target_adreca}.",
                "source_name": source_adreca,
                "target_name": target_adreca,
            }
        )

    if "cluster" in out.columns:
        out["cluster"] = pd.to_numeric(out["cluster"], errors="coerce").astype("Int64")
    if "auto_cluster" in out.columns:
        out["auto_cluster"] = pd.to_numeric(out["auto_cluster"], errors="coerce").astype("Int64")

    manual_point_count = int(out["is_manual"].fillna(False).sum()) if "is_manual" in out.columns else 0
    manual_cluster_values = set()
    for _, row in out.iterrows():
        if not bool(row.get("is_manual", False)):
            continue
        raw_cluster = row.get("cluster")
        if pd.isna(raw_cluster):
            continue
        try:
            cluster_value = int(raw_cluster)
        except (TypeError, ValueError):
            continue
        if cluster_value != -1:
            manual_cluster_values.add(cluster_value)

    return out, effects, {
        "applied_override_count": applied_override_count,
        "manual_point_count": manual_point_count,
        "manual_cluster_count": len(manual_cluster_values),
    }
