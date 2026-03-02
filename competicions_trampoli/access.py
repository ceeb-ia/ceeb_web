from functools import wraps

from django.contrib.auth.mixins import AccessMixin, LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404

from .models import Competicio, CompeticioMembership


GLOBAL_COMPETICIONS_GROUPS = ("platform_admin", "competicions_manager")

COMPETICIO_ROLE_CAPABILITIES = {
    CompeticioMembership.Role.OWNER: {"*"},
    CompeticioMembership.Role.EDITOR: {
        "competition.view",
        "competition.edit",
        "competition.delete",
        "inscripcions.view",
        "inscripcions.edit",
        "scoring.view",
        "scoring.edit",
        "rotacions.view",
        "rotacions.edit",
        "classificacions.view",
        "classificacions.edit",
        "judge_tokens.manage",
        "public_live.manage",
    },
    CompeticioMembership.Role.JUDGE_ADMIN: {
        "competition.view",
        "judge_tokens.manage",
        "public_live.manage",
    },
    CompeticioMembership.Role.SCORING: {
        "competition.view",
        "inscripcions.view",
        "scoring.view",
        "scoring.edit",
        "classificacions.view",
    },
    CompeticioMembership.Role.ROTACIONS: {
        "competition.view",
        "inscripcions.view",
        "rotacions.view",
        "rotacions.edit",
    },
    CompeticioMembership.Role.CLASSIFICACIONS: {
        "competition.view",
        "classificacions.view",
        "classificacions.edit",
        "public_live.manage",
    },
    CompeticioMembership.Role.READONLY: {
        "competition.view",
        "inscripcions.view",
        "scoring.view",
        "rotacions.view",
        "classificacions.view",
    },
}


def user_has_any_global_group(user, group_names) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True
    return user.groups.filter(name__in=tuple(group_names)).exists()


def user_has_global_competicions_access(user) -> bool:
    return user_has_any_global_group(user, GLOBAL_COMPETICIONS_GROUPS)


def get_active_competicio_membership(user, competicio):
    if not getattr(user, "is_authenticated", False):
        return None
    return (
        CompeticioMembership.objects
        .filter(user=user, competicio=competicio, is_active=True)
        .select_related("competicio", "user")
        .first()
    )


def user_has_competicio_capability(user, competicio, capability: str) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    if user_has_global_competicions_access(user):
        return True

    membership = get_active_competicio_membership(user, competicio)
    if not membership:
        return False

    allowed = COMPETICIO_ROLE_CAPABILITIES.get(membership.role, set())
    return "*" in allowed or capability in allowed


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


def require_competicio_capability(capability: str, competicio_kwarg: str = "pk"):
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            competicio = get_object_or_404(Competicio, pk=kwargs.get(competicio_kwarg))
            if not user_has_competicio_capability(request.user, competicio, capability):
                raise PermissionDenied("No tens permisos suficients per aquesta competicio.")
            return view_func(request, *args, **kwargs)

        return _wrapped

    return decorator


class GlobalGroupRequiredMixin(LoginRequiredMixin, AccessMixin):
    required_global_groups = ()

    def dispatch(self, request, *args, **kwargs):
        if not user_has_any_global_group(request.user, self.required_global_groups):
            raise PermissionDenied("No tens permisos per accedir a aquesta area.")
        return super().dispatch(request, *args, **kwargs)


class CompeticioCapabilityRequiredMixin(LoginRequiredMixin, AccessMixin):
    required_competicio_capability = ""
    competicio_kwarg = "pk"

    def dispatch(self, request, *args, **kwargs):
        competicio = get_object_or_404(Competicio, pk=kwargs.get(self.competicio_kwarg))
        self.competicio_access_object = competicio
        if not user_has_competicio_capability(
            request.user,
            competicio,
            self.required_competicio_capability,
        ):
            raise PermissionDenied("No tens permisos suficients per aquesta competicio.")
        return super().dispatch(request, *args, **kwargs)
