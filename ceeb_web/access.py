from functools import wraps

from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import AccessMixin, LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.urls import NoReverseMatch, reverse

from .app_registry import get_internal_app_config, is_internal_app_installed


def user_has_any_global_group(user, group_names) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True
    return user.groups.filter(name__in=tuple(group_names)).exists()


def user_has_app_access(user, app_key: str) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False

    config = get_internal_app_config(app_key)
    if not config or not is_internal_app_installed(app_key):
        return False

    if user_has_any_global_group(user, ("platform_admin",)):
        return True

    required_groups = tuple(config.get("groups") or ())
    if required_groups and user_has_any_global_group(user, required_groups):
        return True

    extra_check = config.get("extra_check")
    if callable(extra_check):
        return bool(extra_check(user))

    return False


def get_internal_nav_apps(user, request=None):
    current_url_name = getattr(getattr(request, "resolver_match", None), "url_name", "")
    items = []

    for app_key in ("calendar", "competicions", "designacions", "calendaritzacions", "certificats", "informes"):
        if not user_has_app_access(user, app_key):
            continue

        config = get_internal_app_config(app_key)
        if not config:
            continue

        try:
            url = reverse(config["url_name"])
        except NoReverseMatch:
            continue

        active_url_names = tuple(config.get("active_url_names") or (config["url_name"],))
        items.append(
            {
                "key": app_key,
                "app_key": app_key,
                "label": config["label"],
                "url": url,
                "active": current_url_name in active_url_names,
                "image": config.get("image", ""),
                "description": config.get("description", ""),
            }
        )

    return items


def require_global_groups(*group_names):
    allowed_groups = tuple(group_names)

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if not user_has_any_global_group(request.user, allowed_groups):
                raise PermissionDenied("No tens permisos per accedir a aquesta area.")
            return view_func(request, *args, **kwargs)

        return _wrapped

    return decorator


def require_app_access(app_key: str):
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if not user_has_app_access(request.user, app_key):
                raise PermissionDenied("No tens permisos per accedir a aquesta aplicacio.")
            return view_func(request, *args, **kwargs)

        return _wrapped

    return decorator


def app_authenticated_view(view, app_key: str):
    return login_required(require_app_access(app_key)(view))


class GlobalGroupRequiredMixin(LoginRequiredMixin, AccessMixin):
    required_global_groups = ()

    def dispatch(self, request, *args, **kwargs):
        if not user_has_any_global_group(request.user, self.required_global_groups):
            raise PermissionDenied("No tens permisos per accedir a aquesta area.")
        return super().dispatch(request, *args, **kwargs)


class AppAccessRequiredMixin(LoginRequiredMixin, AccessMixin):
    required_app_access = ""

    def dispatch(self, request, *args, **kwargs):
        if not user_has_app_access(request.user, self.required_app_access):
            raise PermissionDenied("No tens permisos per accedir a aquesta aplicacio.")
        return super().dispatch(request, *args, **kwargs)
