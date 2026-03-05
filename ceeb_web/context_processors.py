from django.conf import settings


def app_env(request):
    app_env = getattr(settings, "APP_ENV", "dev")
    return {
        "APP_ENV": app_env,
        "IS_PROD": app_env == "prod",
    }

