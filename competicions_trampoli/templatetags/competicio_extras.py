from django import template
from django.contrib.staticfiles import finders
from django.templatetags.static import static

from competicions_trampoli.models import Competicio

register = template.Library()

DEFAULT_COMPETITION_BACKGROUND = "images/fondo.jpg"
COMPETITION_BACKGROUND_BY_TYPE = {
    Competicio.Tipus.NATACIO: "images/natacio.jpg",
    Competicio.Tipus.TRAMPOLI: "images/competicio_trampoli_ia.webp",
    Competicio.Tipus.PATINATGE: "images/patinatge.jpg",
    Competicio.Tipus.ARTISTICA: "images/artistica.jpg",
}


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


@register.simple_tag(takes_context=True)
def competicio_background_url(context):
    request = context.get("request") if hasattr(context, "get") else None
    return get_competicio_background_url_from_request(request)
