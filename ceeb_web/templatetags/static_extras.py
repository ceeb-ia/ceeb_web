from django import template
from django.contrib.staticfiles.storage import staticfiles_storage
from django.contrib.staticfiles import finders
from django.apps import apps
from django.utils.encoding import iri_to_uri
import os

register = template.Library()

@register.simple_tag
def staticv(path: str):
    """
    Torna la URL de l'estàtic amb ?v=<mtime> si el fitxer existeix.
    Exemple: {% staticv 'css/style.css' %}
    """
    url = staticfiles_storage.url(path)
    # Intenta trobar el path físic
    absolute = finders.find(path)
    if absolute and os.path.exists(absolute):
        mtime = int(os.path.getmtime(absolute))
        sep = '&' if '?' in url else '?'
        return iri_to_uri(f"{url}{sep}v={mtime}")
    return iri_to_uri(url)


@register.simple_tag(takes_context=True)
def page_background_url(context):
    if apps.is_installed("competicions_trampoli"):
        try:
            from competicions_trampoli.templatetags.competicio_extras import (
                get_competicio_background_url_from_request,
            )

            request = context.get("request") if hasattr(context, "get") else None
            return get_competicio_background_url_from_request(request)
        except Exception:
            pass
    return staticfiles_storage.url("images/fondo.jpg")
