from django import template
from django.contrib.staticfiles import finders
from django.conf import settings
from django.templatetags.static import static

from competicions_trampoli.models import Competicio

register = template.Library()

DEFAULT_COMPETITION_BACKGROUND = "images/fondo.jpg"
DEFAULT_COMPETITION_WALLPAPER = "general/wallpapers/general.png"
COMPETITION_WALLPAPER_BY_SECTION = {
    "general": DEFAULT_COMPETITION_WALLPAPER,
    "home": DEFAULT_COMPETITION_WALLPAPER,
    "config": DEFAULT_COMPETITION_WALLPAPER,
    "inscripcions": "general/wallpapers/inscripcions.png",
    "fases": "general/wallpapers/fases.png",
    "rotacions": "general/wallpapers/rotacions.png",
    "classificacions": "general/wallpapers/classificacions.png",
    "notes": "general/wallpapers/notes.png",
}
COMPETITION_BACKGROUND_BY_TYPE = {
    Competicio.Tipus.NATACIO: "images/natacio.jpg",
    Competicio.Tipus.TRAMPOLI: "images/competicio_trampoli_ia.webp",
    Competicio.Tipus.PATINATGE: "images/patinatge.jpg",
    Competicio.Tipus.ARTISTICA: "images/artistica.jpg",
}
GENERAL_WALLPAPER_URL_NAMES = {
    "classificacions_live",
    "classificacions_loop_live",
    "public_live_portal",
    "public_live_loop",
    "public_live_classificacions_data",
    "classificacions_live_data",
    "classificacions_live_export_excel",
    "public_live_qr_png",
    "judge_messages_updates_org",
    "judge_messages_send_org",
    "judge_messages_set_status_org",
    "judge_manifest",
    "judge_service_worker",
    "judge_pwa_icon",
    "judge_portal",
    "judge_portal_assignment",
    "judge_qr_png",
    "judge_save_partial",
    "judge_updates",
    "judge_video_status",
    "judge_video_file",
    "judge_video_upload",
    "judge_video_delete",
    "judge_request_support",
    "judge_send_message",
    "judge_messages_updates",
}
NOTES_WALLPAPER_URL_NAMES = {
    "qr_admin_home",
    "qr_admin_detail",
    "judge_messages_hub",
    "judges_qr_home",
    "judges_qr_print",
    "public_live_qr_home",
    "public_live_qr_print",
}


def _active_competition_section_from_url_name(url_name):
    url_name = str(url_name or "")
    if url_name in GENERAL_WALLPAPER_URL_NAMES:
        return "general"
    if url_name in NOTES_WALLPAPER_URL_NAMES:
        return "notes"
    if url_name in {"competicions_home", "created"}:
        return "general"
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
        return "general"
    return "general"


def _is_competition_program_request(request):
    if request is None:
        return False
    path = str(getattr(request, "path", "") or "")
    return path.startswith((
        "/competicions/",
        "/competicio/",
        "/trampoli/",
        "/scoring/",
        "/judge/",
        "/public/live/",
    ))


def _resolve_competition_wallpaper_static_path(request):
    resolver_match = getattr(request, "resolver_match", None)
    url_name = getattr(resolver_match, "url_name", "") or ""
    section = _active_competition_section_from_url_name(url_name)
    candidate = COMPETITION_WALLPAPER_BY_SECTION.get(section, DEFAULT_COMPETITION_WALLPAPER)
    if not finders.find(candidate):
        return DEFAULT_COMPETITION_WALLPAPER
    return candidate


def _resolve_competicio_background_static_path(competicio_tipus):
    candidate = COMPETITION_BACKGROUND_BY_TYPE.get(
        str(competicio_tipus or "").strip(),
        DEFAULT_COMPETITION_BACKGROUND,
    )
    if candidate != DEFAULT_COMPETITION_BACKGROUND and not finders.find(candidate):
        return DEFAULT_COMPETITION_BACKGROUND
    return candidate


def _get_active_competicio_id_from_request(request):
    if request is None:
        return None
    path = str(getattr(request, "path", "") or "")
    if path and not path.startswith(("/competicio/", "/competicions/", "/scoring/")):
        return None
    resolver_match = getattr(request, "resolver_match", None)
    kwargs = getattr(resolver_match, "kwargs", None) or {}
    for key in ("pk", "competicio_id"):
        raw_value = kwargs.get(key)
        try:
            return int(raw_value)
        except (TypeError, ValueError):
            continue
    return None


def get_competicio_background_url_from_request(request):
    path = str(getattr(request, "path", "") or "")
    if getattr(settings, "APP_ENV", "dev") == "prod" and path.startswith("/accounts/"):
        return static(DEFAULT_COMPETITION_WALLPAPER)

    if _is_competition_program_request(request):
        return static(_resolve_competition_wallpaper_static_path(request))

    competicio_id = _get_active_competicio_id_from_request(request)
    if competicio_id is None:
        return static(DEFAULT_COMPETITION_BACKGROUND)

    tipus = (
        Competicio.objects.filter(pk=competicio_id)
        .values_list("tipus", flat=True)
        .first()
    )
    return static(_resolve_competicio_background_static_path(tipus))

@register.filter(name="attr")
def attr(obj, field_name):
    """Retorna l'atribut d'un objecte (o buit si no existeix)."""
    try:
        return getattr(obj, field_name)
    except Exception:
        return ""

@register.filter(name="attr_default")
def attr_default(obj, args):
    """
    Ús:
      - obj|attr_default:"camp,(Sense valor)"
      - obj|attr_default:"camp"
    """
    try:
        s = str(args).strip()

        # Si ve en format "camp,default"
        if "," in s:
            field_name, default = [x.strip() for x in s.split(",", 1)]
        else:
            field_name, default = s, None

        val = getattr(obj, field_name, None)

        # Normalitza buit / espais
        if val is None or (isinstance(val, str) and not val.strip()):
            return default if default is not None else ""
        return val
    except Exception:
        return ""


@register.filter
def get_item(d, key):
    if not d:
        return None
    return d.get(key)


@register.filter
def extra_item(d, key):
    if not isinstance(d, dict):
        return None
    if key in d:
        return d.get(key)
    if isinstance(key, str) and key.startswith("excel__"):
        legacy_key = key[len("excel__"):]
        return d.get(legacy_key)
    return None


@register.filter
def initials(value):
    words = [part for part in str(value or "").replace("-", " ").split() if part]
    if not words:
        return "?"
    if len(words) == 1:
        return words[0][:1].upper()
    return f"{words[0][:1]}{words[-1][:1]}".upper()


@register.simple_tag(takes_context=True)
def competicio_background_url(context):
    request = context.get("request") if hasattr(context, "get") else None
    return get_competicio_background_url_from_request(request)
