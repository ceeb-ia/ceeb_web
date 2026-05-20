from __future__ import annotations

from pathlib import Path


LOGO_ROOT = "fases/aparells"
FALLBACK_DISCIPLINE = "trampoli"
VALID_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".svg"}


def discipline_for_competicio(competicio) -> str:
    raw = str(getattr(competicio, "tipus", "") or "").strip().lower()
    if raw in {"artistica", "ritmica", "trampoli"}:
        return raw
    return FALLBACK_DISCIPLINE


def _static_logo_dir(discipline: str) -> Path:
    return Path(__file__).resolve().parents[2] / "static" / "fases" / "aparells" / discipline


def available_app_logos_for_competicio(competicio) -> list[dict]:
    discipline = discipline_for_competicio(competicio)
    logo_dir = _static_logo_dir(discipline)
    if not logo_dir.exists():
        discipline = FALLBACK_DISCIPLINE
        logo_dir = _static_logo_dir(discipline)

    choices = []
    for path in sorted(logo_dir.iterdir() if logo_dir.exists() else []):
        if not path.is_file() or path.suffix.lower() not in VALID_EXTENSIONS:
            continue
        stem = path.stem.replace("_", " ").replace("-", " ").strip()
        label = stem[:1].upper() + stem[1:] if stem else path.name
        choices.append({
            "path": f"{LOGO_ROOT}/{discipline}/{path.name}",
            "label": label,
            "filename": path.name,
        })
    if not choices:
        choices.append({
            "path": "fases/aparells.png",
            "label": "Aparells",
            "filename": "aparells.png",
        })
    return choices


def logo_choice_paths(competicio) -> set[str]:
    return {choice["path"] for choice in available_app_logos_for_competicio(competicio)}


def default_logo_path_for_app(comp_aparell, choices: list[dict] | None = None) -> str:
    available = choices or available_app_logos_for_competicio(comp_aparell.competicio)
    code = str(getattr(comp_aparell, "display_codi", "") or "").strip().lower()
    name = str(getattr(comp_aparell, "display_nom", "") or "").strip().lower()
    haystack = f"{code} {name}"
    for choice in available:
        key = Path(choice["filename"]).stem.lower()
        if key and key in haystack:
            return choice["path"]
    for choice in available:
        key = Path(choice["filename"]).stem.lower()
        if key and any(part and part in haystack for part in key.replace("-", "_").split("_")):
            return choice["path"]
    return available[0]["path"]


def selected_logo_path_for_app(comp_aparell, choices: list[dict] | None = None) -> str:
    config = comp_aparell.judge_ui_config if isinstance(comp_aparell.judge_ui_config, dict) else {}
    selected = str(config.get("phase_planner_logo") or "").strip()
    available = choices or available_app_logos_for_competicio(comp_aparell.competicio)
    paths = {choice["path"] for choice in available}
    if selected in paths:
        return selected
    return default_logo_path_for_app(comp_aparell, available)
