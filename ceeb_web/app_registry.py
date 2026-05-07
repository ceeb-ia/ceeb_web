from django.conf import settings


def _has_active_competicio_membership(user) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    if "competicions_trampoli" not in settings.INSTALLED_APPS:
        return False

    from competicions_trampoli.models import CompeticioMembership

    return CompeticioMembership.objects.filter(user=user, is_active=True).exists()


INTERNAL_APPS = {
    "calendar": {
        "label": "Calendari",
        "url_name": "calendar_home",
        "active_url_names": ("home", "calendar_home", "calendar_events_json", "calendar_event_create", "calendar_event_update", "calendar_event_delete"),
        "app_label": "ceeb_web",
        "groups": ("calendar_manager",),
        "image": "images/calendaritzacions.jpg",
        "description": "Gestiona el calendari intern.",
    },
    "competicions": {
        "label": "Competicions",
        "url_name": "competicions_home",
        "active_url_names": ("competicions_home", "created", "create"),
        "app_label": "competicions_trampoli",
        "groups": ("competicions_manager",),
        "extra_check": _has_active_competicio_membership,
        "image": "images/competicio_trampoli_ia.webp",
        "description": "Gestiona competicions, inscripcions i resultats.",
    },
    "designacions": {
        "label": "Designacions",
        "url_name": "designacions_runs_list",
        "active_url_names": ("designacions_upload", "designacions_run_detail", "designacions_assignments", "designacions_geocoding_pending", "designacions_runs_list"),
        "app_label": "designacions",
        "groups": ("designacions_manager",),
        "image": "images/designacions.jpg",
        "description": "Realitza les designacions arbitrals.",
    },
    "certificats": {
        "label": "Certificats",
        "url_name": "certificats",
        "active_url_names": ("certificats", "processar_pdfs"),
        "app_label": "certificats",
        "groups": ("certificats_manager",),
        "image": "images/certificats.jpg",
        "description": "Reanomena certificats de formacio.",
    },
    "informes": {
        "label": "Informes",
        "url_name": "annual_report_list",
        "active_url_names": ("annual_report_list", "annual_report_create", "annual_report_update", "annual_report_detail"),
        "app_label": "marbella_informes",
        "groups": ("informes_manager",),
        "image": "images/bar-chart.png",
        "description": "Consulta i prepara informes interns.",
    },
}


def get_internal_app_config(app_key: str):
    return INTERNAL_APPS.get(app_key)


def is_internal_app_installed(app_key: str) -> bool:
    config = get_internal_app_config(app_key)
    if not config:
        return False
    return config["app_label"] in settings.INSTALLED_APPS
