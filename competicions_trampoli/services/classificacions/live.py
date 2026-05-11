from django.utils import timezone

from ...models.classificacions import ClassificacioConfig
from .compute import compute_classificacio
from .display import get_display_columns
from .runtime import execute_classificacio_runtime


def active_cfg_values(competicio, *, only_public=False):
    cfgs = (
        ClassificacioConfig.objects
        .filter(competicio=competicio, activa=True)
        .order_by("ordre", "id")
    )
    if only_public:
        cfgs = cfgs.filter(publicada=True)
    return list(cfgs.values("id", "nom", "tipus", "ordre", "publicada"))


def default_live_columns():
    return [
        {"type": "builtin", "key": "posicio", "label": "Pos.", "align": "left"},
        {"type": "builtin", "key": "participant", "label": "Nom", "align": "left"},
        {"type": "builtin", "key": "punts", "label": "Punts", "align": "right", "decimals": 3},
    ]


def format_partition_title(raw):
    source = "global" if raw in (None, "") else str(raw)
    tokens = []
    for part in source.split("|"):
        token = str(part or "").strip()
        if not token:
            continue
        idx = token.find(":")
        tokens.append(token[idx + 1 :].strip() if idx >= 0 else token)
    return " / ".join([value for value in tokens if value]) or "global"


def fallback_export_value(row: dict, key: str):
    if key in ("participant", "nom"):
        return row.get("participant") or row.get("nom") or row.get("entitat_nom") or ""
    if key == "punts":
        return row.get("punts")
    if key == "posicio":
        return row.get("posicio")
    if key == "entitat_nom":
        return row.get("entitat_nom") or ""
    if key == "participants":
        return row.get("participants") if row.get("participants") is not None else ""
    return row.get(key)


def extract_export_value(row: dict, col: dict):
    key = str((col or {}).get("key") or "")
    cells = row.get("cells") or row.get("display") or {}
    if isinstance(cells, dict) and key in cells:
        return cells.get(key)
    return fallback_export_value(row, key)


def build_live_cfg_payload_row(competicio, cfg, *, compute_fn=compute_classificacio):
    runtime = execute_classificacio_runtime(
        competicio,
        schema_local=cfg.schema or {},
        tipus=cfg.tipus,
        compute_fn=compute_fn,
        invalid_message="Configuracio de classificacio invalida.",
        runtime_message="No s'ha pogut renderitzar la classificacio.",
    )
    return {
        "id": cfg.id,
        "nom": cfg.nom,
        "tipus": cfg.tipus,
        "publicada": bool(getattr(cfg, "publicada", True)),
        "columns": runtime["columns"] or get_display_columns(cfg.schema or {}),
        "parts": runtime["parts"],
        **({"error": runtime["error"]} if runtime["error"] else {}),
    }


def live_data_payload(competicio, since_raw=None, *, build_row_fn=build_live_cfg_payload_row):
    del since_raw
    cfgs = (
        ClassificacioConfig.objects
        .filter(competicio=competicio, activa=True)
        .order_by("ordre", "id")
    )
    payload_cfgs = [build_row_fn(competicio, cfg) for cfg in cfgs]
    stamp = timezone.now().isoformat()
    return {
        "ok": True,
        "changed": True,
        "stamp": stamp,
        "competicio": {"id": competicio.id, "nom": competicio.nom},
        "cfgs": payload_cfgs,
    }


def public_live_payload(payload):
    response = dict(payload or {})
    if response.get("changed") is False:
        return response
    cfgs = response.get("cfgs")
    if isinstance(cfgs, list):
        response["cfgs"] = [
            cfg for cfg in cfgs
            if not isinstance(cfg, dict) or bool(cfg.get("publicada", True))
        ]
    return response


__all__ = [
    "active_cfg_values",
    "build_live_cfg_payload_row",
    "default_live_columns",
    "extract_export_value",
    "format_partition_title",
    "live_data_payload",
    "public_live_payload",
]
