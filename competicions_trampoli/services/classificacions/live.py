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


def partition_presentation_config(schema):
    presentacio = (schema or {}).get("presentacio") if isinstance(schema, dict) else {}
    raw_cfg = (presentacio or {}).get("particions") if isinstance(presentacio, dict) else {}
    raw_cfg = raw_cfg if isinstance(raw_cfg, dict) else {}
    order = []
    seen = set()
    for item in raw_cfg.get("ordre") or []:
        key = str(item or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        order.append(key)
    styles = {}
    raw_styles = raw_cfg.get("estils") if isinstance(raw_cfg.get("estils"), dict) else {}
    allowed_colors = {"auto", "blue", "green", "amber", "red", "cyan", "violet", "slate"}
    for raw_key, raw_style in raw_styles.items():
        key = str(raw_key or "").strip()
        if not key:
            continue
        style = raw_style if isinstance(raw_style, dict) else {}
        color = str(style.get("color") or "auto").strip().lower()
        styles[key] = {
            "color": color if color in allowed_colors else "auto",
            "label": str(style.get("label") or "").strip(),
        }
    return {"ordre": order, "estils": styles}


def row_presentation_config(schema):
    presentacio = (schema or {}).get("presentacio") if isinstance(schema, dict) else {}
    raw_cfg = (presentacio or {}).get("files") if isinstance(presentacio, dict) else {}
    raw_cfg = raw_cfg if isinstance(raw_cfg, dict) else {}
    raw_positions = raw_cfg.get("posicions") if isinstance(raw_cfg.get("posicions"), dict) else {}
    allowed_colors = {"gold", "silver", "bronze", "blue", "green", "amber", "red", "violet", "slate"}
    positions = {}
    for raw_pos, raw_style in raw_positions.items():
        try:
            pos = int(raw_pos)
        except (TypeError, ValueError):
            continue
        if pos < 1:
            continue
        style = raw_style if isinstance(raw_style, dict) else {}
        color = str(style.get("color") or "").strip().lower()
        if color not in allowed_colors:
            continue
        positions[str(pos)] = {"color": color}
    return {"posicions": positions}


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
        "partition_presentation": partition_presentation_config(cfg.schema or {}),
        "row_presentation": row_presentation_config(cfg.schema or {}),
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
    "partition_presentation_config",
    "public_live_payload",
    "row_presentation_config",
]
