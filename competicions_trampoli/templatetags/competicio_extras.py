from django import template

register = template.Library()

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
