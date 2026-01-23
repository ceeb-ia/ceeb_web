# designacions_app/templatetags/dict_extras.py
from django import template
from datetime import datetime, time

register = template.Library()

@register.filter
def get_item(d, key):
    if not d:
        return None
    return d.get(key)

def _parse_date(s):
    if not s:
        return None
    # ve com "2026-01-23T00:00:00"
    try:
        return datetime.fromisoformat(s).date()
    except Exception:
        return None

def _parse_time(s):
    if not s:
        return None
    # ve com "09:00:00"
    try:
        return time.fromisoformat(s)
    except Exception:
        # si vingués "09:00"
        try:
            return datetime.strptime(s, "%H:%M").time()
        except Exception:
            return None

@register.filter
def availability_summary(raw):
    """
    Retorna un resum curt i llegible de l'Availability.raw.
    """
    if not raw or not isinstance(raw, dict):
        return ""

    d = _parse_date(raw.get("Data"))
    h0 = raw.get("Hora Inici")
    h1 = raw.get("Hora Fi")
    transport = raw.get("Mitjà de Transport")

    parts = []
    if d:
        parts.append(d.strftime("%d/%m/%Y"))
    if h0 and h1:
        parts.append(f"{h0[:5]}–{h1[:5]}")
    elif h0:
        parts.append(f"des de {h0[:5]}")
    elif h1:
        parts.append(f"fins {h1[:5]}")

    if transport:
        parts.append(f"🚗 {transport}")

    return " · ".join(parts)

@register.simple_tag
def availability_fits_match(raw, match_date, match_hour_raw):
    """
    Retorna True/False si l'hora del partit cau dins Hora Inici - Hora Fi
    (si la data coincideix). Si no es pot calcular, retorna None.
    """
    if not raw or not isinstance(raw, dict) or not match_date or not match_hour_raw:
        return None

    d = _parse_date(raw.get("Data"))
    if not d or d != match_date:
        return None  # no podem validar o no és el mateix dia

    start = _parse_time(raw.get("Hora Inici"))
    end = _parse_time(raw.get("Hora Fi"))
    if not start or not end:
        return None

    # match_hour_raw pot ser "10:00" o "10:00:00"
    mh = _parse_time(match_hour_raw)
    if not mh:
        return None

    return start <= mh <= end
