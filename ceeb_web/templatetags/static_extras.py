from django import template
from django.contrib.staticfiles.storage import staticfiles_storage
from django.contrib.staticfiles import finders
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
