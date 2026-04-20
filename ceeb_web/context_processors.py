from django.conf import settings

from .access import get_internal_nav_apps


def app_env(request):
    app_env = getattr(settings, "APP_ENV", "dev")
    internal_nav_apps = (
        get_internal_nav_apps(getattr(request, "user", None), request=request)
        if app_env == "intern"
        else []
    )
    return {
        "APP_ENV": app_env,
        "IS_DEV": app_env == "dev",
        "IS_PROD": app_env == "prod",
        "is_internal_env": app_env == "intern",
        "internal_nav_apps": internal_nav_apps,
        "has_active_internal_nav_app": any(app["active"] for app in internal_nav_apps),
        "has_any_internal_app_access": bool(internal_nav_apps),
    }
