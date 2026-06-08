import re

from django.conf import settings
from django.contrib.staticfiles import finders
from django.urls import NoReverseMatch, reverse

from .access import get_internal_nav_apps


_FONT_FOLDER_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_FONT_FAMILY_RE = re.compile(r"^[A-Za-z0-9 _-]+$")
_FONT_FILE_RE = re.compile(r"^[A-Za-z0-9_. -]+\.(?:otf|ttf|woff|woff2)$", re.IGNORECASE)
_DEFAULT_COMPETICIONS_FONT_FAMILY = "Inter"
_COMPETICIONS_FONT_FALLBACKS = ('"Poppins"', '"Segoe UI"', "Arial", "sans-serif")
_DEFAULT_FONT_FILES_BY_SUFFIX = (
    (200, "ExtraLight"),
    (300, "Light"),
    (400, "Regular"),
    (500, "Medium"),
    (600, "SemiBold"),
    (700, "Bold"),
    (800, "ExtraBold"),
)


def _is_competicions_app(request):
    resolver_match = getattr(request, "resolver_match", None)
    path = str(getattr(request, "path", "") or "")
    if path.startswith((
        "/competicions/",
        "/competicio/",
        "/trampoli/",
        "/scoring/",
        "/judge/",
        "/public/live/",
    )):
        return True
    if not resolver_match:
        return False
    func = getattr(resolver_match, "func", None)
    view_class = getattr(func, "view_class", None)
    module = getattr(view_class or func, "__module__", "")
    return str(module).startswith("competicions_trampoli.")


def _active_competicio_id(request):
    resolver_match = getattr(request, "resolver_match", None)
    kwargs = getattr(resolver_match, "kwargs", None) or {}
    for key in ("pk", "competicio_id"):
        try:
            return int(kwargs.get(key))
        except (TypeError, ValueError):
            continue
    return None


def _safe_reverse(name, *args, **kwargs):
    try:
        return reverse(name, args=args, kwargs=kwargs)
    except NoReverseMatch:
        return ""


def _active_dock_section(url_name):
    url_name = str(url_name or "")
    if url_name in {"competicions_home", "created"}:
        return "home"
    if url_name in {
        "qr_admin_home",
        "qr_admin_detail",
        "judges_qr_home",
        "judges_qr_print",
        "public_live_qr_home",
        "public_live_qr_print",
    }:
        return "notes"
    if "inscripcio" in url_name or "inscripcions" in url_name or url_name == "import":
        return "inscripcions"
    if "rotacions" in url_name:
        return "rotacions"
    if "classificacio" in url_name or "classificacions" in url_name or "public_live" in url_name:
        return "classificacions"
    if (
        "notes" in url_name
        or "scoring" in url_name
        or "judge" in url_name
        or "token" in url_name
        or url_name == "trampoli_save"
    ):
        return "notes"
    if "aparell" in url_name or "fases" in url_name:
        return "fases"
    if url_name == "trampoli_config":
        return "config"
    return ""


def _dock_icon_path(section):
    icon_names = {
        "home": "home",
        "inscripcions": "inscripcions",
        "fases": "fases",
        "rotacions": "rotacions",
        "classificacions": "classificacions",
        "notes": "notes",
        "config": "configuracio",
    }
    return "dock/{}.png".format(icon_names.get(section, "home"))


def _clean_font_folder(value):
    folder = str(value or "").strip().strip("/\\")
    return folder if folder and _FONT_FOLDER_RE.fullmatch(folder) else ""


def _clean_font_family(value):
    family = " ".join(str(value or "").strip().split())
    return family if family and _FONT_FAMILY_RE.fullmatch(family) else ""


def _font_format(filename):
    lowered = str(filename or "").lower()
    if lowered.endswith(".woff2"):
        return "woff2"
    if lowered.endswith(".woff"):
        return "woff"
    if lowered.endswith(".ttf"):
        return "truetype"
    return "opentype"


def _configured_font_files(family):
    configured = getattr(settings, "COMPETICIONS_APP_FONT_FILES", None)
    if isinstance(configured, dict):
        faces = []
        for raw_weight, raw_filename in configured.items():
            try:
                weight = int(raw_weight)
            except (TypeError, ValueError):
                continue
            filename = str(raw_filename or "").strip()
            if _FONT_FILE_RE.fullmatch(filename):
                faces.append((weight, filename))
        return sorted(faces)

    compact_family = str(family or "").replace(" ", "")
    return [
        (weight, "{}-{}.otf".format(compact_family, suffix))
        for weight, suffix in _DEFAULT_FONT_FILES_BY_SUFFIX
    ]


def _build_competicions_font_config(is_competicions_app):
    configured_folder = _clean_font_folder(getattr(settings, "COMPETICIONS_APP_FONT_FOLDER", ""))
    configured_family = _clean_font_family(getattr(settings, "COMPETICIONS_APP_FONT_FAMILY", ""))
    family = configured_family or (configured_folder.replace("_", " ").replace("-", " ").title().replace(" ", "") if configured_folder else _DEFAULT_COMPETICIONS_FONT_FAMILY)
    family_css = ", ".join(['"{}"'.format(family), *_COMPETICIONS_FONT_FALLBACKS])

    faces = []
    if is_competicions_app and configured_folder:
        for weight, filename in _configured_font_files(family):
            path = "fonts/{}/{}".format(configured_folder, filename)
            if not finders.find(path):
                continue
            faces.append({
                "family": family,
                "path": path,
                "weight": weight,
                "format": _font_format(filename),
            })

    return {
        "competicio_font_family": family,
        "competicio_font_family_css": family_css,
        "competicio_font_folder": configured_folder,
        "competicio_font_faces": faces,
    }


def _build_competition_dock(request, is_competicions_app):
    if not is_competicions_app:
        return []
    if "competicions_trampoli" not in getattr(settings, "INSTALLED_APPS", ()):
        return []

    from ceeb_web.access import user_has_any_global_group

    from competicions_trampoli.access import (
        GLOBAL_COMPETICIONS_GROUPS,
        user_has_competicio_capability,
    )
    from competicions_trampoli.models import Competicio

    resolver_match = getattr(request, "resolver_match", None)
    url_name = getattr(resolver_match, "url_name", "") or ""
    active_section = _active_dock_section(url_name)
    competicio_id = _active_competicio_id(request)

    items = [
        {
            "label": "Competicions",
            "section": "home",
            "url": _safe_reverse("created"),
        }
    ]

    if competicio_id is None:
        can_manage_global_competicions = user_has_any_global_group(
            getattr(request, "user", None),
            GLOBAL_COMPETICIONS_GROUPS,
        )
        items.extend(
            [
                {
                    "label": "Aparells globals",
                    "section": "fases",
                    "url": _safe_reverse("aparells_list") if can_manage_global_competicions else "",
                },
                {
                    "label": "Plantilles",
                    "section": "classificacions",
                    "url": _safe_reverse("classificacio_template_global_list") if can_manage_global_competicions else "",
                },
            ]
        )
    else:
        competicio = (
            Competicio.objects
            .filter(pk=competicio_id)
            .only("id")
            .first()
        )
        if competicio:
            user = getattr(request, "user", None)
            te_notes_attr = getattr(competicio, "te_notes", False)
            has_notes = bool(te_notes_attr() if callable(te_notes_attr) else te_notes_attr)
            can_inscripcions = user_has_competicio_capability(user, competicio, "inscripcions.view")
            can_fases = user_has_competicio_capability(user, competicio, "scoring.edit")
            can_rotacions = user_has_competicio_capability(user, competicio, "rotacions.view")
            can_classificacions = user_has_competicio_capability(user, competicio, "classificacions.view")
            can_notes = has_notes and user_has_competicio_capability(user, competicio, "scoring.view")
            can_config = has_notes and user_has_competicio_capability(user, competicio, "scoring.edit")
            pk = competicio.id
            candidate_items = [
                (
                    can_inscripcions,
                    {
                        "label": "Inscripcions",
                        "section": "inscripcions",
                        "url": _safe_reverse("inscripcions_list", pk),
                    },
                ),
                (
                    can_fases,
                    {
                        "label": "Aparells i Fases",
                        "section": "fases",
                        "url": _safe_reverse("trampoli_fases", pk),
                    },
                ),
                (
                    can_rotacions,
                    {
                        "label": "Rotacions",
                        "section": "rotacions",
                        "url": _safe_reverse("rotacions_planner", pk),
                    },
                ),
                (
                    can_classificacions,
                    {
                        "label": "Classificacions",
                        "section": "classificacions",
                        "url": _safe_reverse("classificacions_home", pk),
                    },
                ),
                (
                    can_notes,
                    {
                        "label": "Notes i QRs",
                        "section": "notes",
                        "url": _safe_reverse("scoring_notes_home", pk),
                    },
                ),
                (
                    can_config,
                    {
                        "label": "Configuració",
                        "section": "config",
                        "url": _safe_reverse("trampoli_config", pk),
                    },
                ),
            ]
            items.extend(item for allowed, item in candidate_items if allowed)

    return [
        {
            **item,
            "active": item["section"] == active_section,
            "icon_path": _dock_icon_path(item["section"]),
        }
        for item in items
        if item.get("url")
    ]


def _competition_dock_avatar_messages(show_help):
    if not show_help:
        return {}
    if "competicions_trampoli" not in getattr(settings, "INSTALLED_APPS", ()):
        return {}

    from competicions_trampoli.services.avatar.competition.overview import AVATAR_MESSAGES

    return AVATAR_MESSAGES


def app_env(request):
    app_env = getattr(settings, "APP_ENV", "dev")
    internal_nav_apps = (
        get_internal_nav_apps(getattr(request, "user", None), request=request)
        if app_env == "intern"
        else []
    )
    is_competicions_app = _is_competicions_app(request)
    resolver_match = getattr(request, "resolver_match", None)
    url_name = getattr(resolver_match, "url_name", "") or ""
    competition_active_section = _active_dock_section(url_name) if is_competicions_app else ""
    if competition_active_section in {"", "home", "config"}:
        competition_active_section = "general" if is_competicions_app else ""
    competition_dock_items = _build_competition_dock(request, is_competicions_app)
    competition_dock_help_topic = (
        "competition_intro"
        if competition_dock_items and _active_competicio_id(request) is not None
        else ""
    )
    competicions_font_config = _build_competicions_font_config(is_competicions_app)
    return {
        "APP_ENV": app_env,
        "IS_DEV": app_env == "dev",
        "IS_PROD": app_env == "prod",
        "is_internal_env": app_env == "intern",
        "internal_nav_apps": internal_nav_apps,
        "has_active_internal_nav_app": any(app["active"] for app in internal_nav_apps),
        "has_any_internal_app_access": bool(internal_nav_apps),
        "is_competicions_app": is_competicions_app,
        "competition_active_section": competition_active_section,
        "competition_dock_items": competition_dock_items,
        "has_competition_dock": bool(competition_dock_items),
        "competition_dock_help_topic": competition_dock_help_topic,
        "competition_dock_avatar_messages": _competition_dock_avatar_messages(bool(competition_dock_help_topic)),
        "competition_dock_avatar_initial_topic": competition_dock_help_topic,
        **competicions_font_config,
    }
