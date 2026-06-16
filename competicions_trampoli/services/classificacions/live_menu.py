LIVE_MENU_KEY = "live_menu"
MENU_TYPE_CLASSIFICACIO = "classificacio"
MENU_TYPE_HEADING = "heading"
MENU_TYPE_DIVIDER = "divider"
MENU_TYPES = {MENU_TYPE_CLASSIFICACIO, MENU_TYPE_HEADING, MENU_TYPE_DIVIDER}


def classificacions_view_config(competicio) -> dict:
    cfg = getattr(competicio, "classificacions_view", {}) or {}
    return cfg if isinstance(cfg, dict) else {}


def _next_item_id(prefix: str, idx: int) -> str:
    return f"{prefix}_{idx}"


def normalize_live_menu_items(raw_items, valid_cfg_ids=None):
    has_valid_filter = valid_cfg_ids is not None
    valid_ids = {int(x) for x in (valid_cfg_ids or []) if str(x).isdigit()}
    out = []
    seen_cfg_ids = set()
    auto_idx = 1

    for raw in raw_items if isinstance(raw_items, list) else []:
        if not isinstance(raw, dict):
            continue
        item_type = str(raw.get("type") or "").strip()
        if item_type not in MENU_TYPES:
            continue

        if item_type == MENU_TYPE_CLASSIFICACIO:
            try:
                cfg_id = int(raw.get("cfg_id"))
            except (TypeError, ValueError):
                continue
            if has_valid_filter and cfg_id not in valid_ids:
                continue
            if cfg_id in seen_cfg_ids:
                continue
            seen_cfg_ids.add(cfg_id)
            out.append({"type": MENU_TYPE_CLASSIFICACIO, "cfg_id": cfg_id})
            continue

        item_id = str(raw.get("id") or "").strip() or _next_item_id(item_type, auto_idx)
        auto_idx += 1
        if item_type == MENU_TYPE_HEADING:
            label = str(raw.get("label") or "").strip()
            if not label:
                continue
            out.append({"type": MENU_TYPE_HEADING, "id": item_id[:80], "label": label[:120]})
            continue

        out.append({"type": MENU_TYPE_DIVIDER, "id": item_id[:80]})

    return out


def live_menu_from_view_config(view_config: dict, cfgs):
    cfg_list = [dict(cfg) for cfg in (cfgs or [])]
    cfg_by_id = {int(cfg["id"]): cfg for cfg in cfg_list if cfg.get("id") is not None}
    menu = normalize_live_menu_items(
        (view_config or {}).get(LIVE_MENU_KEY),
        valid_cfg_ids=cfg_by_id.keys(),
    )
    seen_cfg_ids = {
        int(item["cfg_id"])
        for item in menu
        if item.get("type") == MENU_TYPE_CLASSIFICACIO and item.get("cfg_id") in cfg_by_id
    }
    for cfg in cfg_list:
        cfg_id = int(cfg["id"])
        if cfg_id in seen_cfg_ids:
            continue
        menu.append({"type": MENU_TYPE_CLASSIFICACIO, "cfg_id": cfg_id})
        seen_cfg_ids.add(cfg_id)

    return prune_empty_visual_items(menu, cfg_by_id)


def prune_empty_visual_items(menu, cfg_by_id):
    out = []
    pending_visual = []
    for item in menu:
        item_type = item.get("type")
        if item_type == MENU_TYPE_HEADING:
            if pending_visual and any(visual.get("type") == MENU_TYPE_HEADING for visual in pending_visual):
                pending_visual = [item]
            else:
                pending_visual.append(item)
            continue
        if item_type == MENU_TYPE_DIVIDER:
            if out and (not pending_visual or pending_visual[-1].get("type") != MENU_TYPE_DIVIDER):
                pending_visual.append(item)
            continue
        if item_type != MENU_TYPE_CLASSIFICACIO:
            continue
        cfg = cfg_by_id.get(int(item.get("cfg_id") or 0))
        if not cfg:
            continue
        out.extend(pending_visual)
        pending_visual = []
        out.append({**item, "cfg": cfg})
    return out


def first_menu_cfg_id(menu):
    for item in menu or []:
        if item.get("type") == MENU_TYPE_CLASSIFICACIO and item.get("cfg_id"):
            return int(item["cfg_id"])
    return None


def save_live_menu_to_competicio(competicio, raw_items, valid_cfg_ids):
    normalized = normalize_live_menu_items(raw_items, valid_cfg_ids=valid_cfg_ids)
    view_cfg = classificacions_view_config(competicio)
    view_cfg[LIVE_MENU_KEY] = normalized
    competicio.classificacions_view = view_cfg
    competicio.save(update_fields=["classificacions_view"])
    return view_cfg


__all__ = [
    "LIVE_MENU_KEY",
    "MENU_TYPE_CLASSIFICACIO",
    "MENU_TYPE_DIVIDER",
    "MENU_TYPE_HEADING",
    "classificacions_view_config",
    "first_menu_cfg_id",
    "live_menu_from_view_config",
    "normalize_live_menu_items",
    "prune_empty_visual_items",
    "save_live_menu_to_competicio",
]
