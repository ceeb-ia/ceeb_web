from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.generic import TemplateView

from ...live_cache import get_live_payload_cached
from ...models import Competicio
from ...models.judging import PublicLiveToken
from ...services.classificacions.compute import compute_classificacio
from ...services.classificacions.live import (
    active_cfg_values,
    build_live_cfg_payload_row as service_build_live_cfg_payload_row,
    live_data_payload as service_live_data_payload,
    public_live_payload,
)


def build_live_cfg_payload_row(competicio, cfg):
    return service_build_live_cfg_payload_row(
        competicio,
        cfg,
        compute_fn=compute_classificacio,
    )


def live_data_payload(competicio, since_raw=None):
    return service_live_data_payload(
        competicio,
        since_raw=since_raw,
        build_row_fn=build_live_cfg_payload_row,
    )


class ClassificacionsLive(TemplateView):
    template_name = "classificacions/classificacions_live.html"

    def dispatch(self, request, *args, **kwargs):
        self.competicio = get_object_or_404(Competicio, pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        public_raw = (self.request.GET.get("public") or "").strip().lower()
        is_public = public_raw in {"1", "true", "yes", "on"}
        data_url = ""
        if is_public:
            data_url = f"{reverse('classificacions_live_data', kwargs={'pk': self.competicio.id})}?public=1"
        ctx.update(
            {
                "competicio": self.competicio,
                "cfgs": active_cfg_values(self.competicio, only_public=is_public),
                "is_public": is_public,
                "hide_base_chrome": is_public,
                "poll_ms": 4000,
                "data_url": data_url,
            }
        )
        return ctx


class ClassificacionsLoopLive(TemplateView):
    template_name = "classificacions/classificacions_loop_live.html"

    @staticmethod
    def _parse_int_param(raw, default: int, min_value: int, max_value: int) -> int:
        try:
            value = int(raw)
        except Exception:
            value = default
        return max(min_value, min(max_value, value))

    def dispatch(self, request, *args, **kwargs):
        self.competicio = get_object_or_404(Competicio, pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        public_raw = (self.request.GET.get("public") or "").strip().lower()
        is_public = public_raw in {"1", "true", "yes", "on"}
        data_url = ""
        if is_public:
            data_url = f"{reverse('classificacions_live_data', kwargs={'pk': self.competicio.id})}?public=1"
        poll_ms = self._parse_int_param(self.request.GET.get("poll_ms"), 4000, 1000, 60000)
        slide_ms = self._parse_int_param(self.request.GET.get("slide_ms"), 8000, 2000, 120000)
        rows_per_page = self._parse_int_param(self.request.GET.get("rows"), 12, 3, 60)
        transition = (self.request.GET.get("transition") or "fade").strip().lower()
        if transition not in {"fade", "none"}:
            transition = "fade"
        ctx.update(
            {
                "competicio": self.competicio,
                "cfgs": active_cfg_values(self.competicio, only_public=is_public),
                "is_public": is_public,
                "hide_base_chrome": is_public,
                "poll_ms": poll_ms,
                "slide_ms": slide_ms,
                "rows_per_page": rows_per_page,
                "transition": transition,
                "data_url": data_url,
            }
        )
        return ctx


class PublicClassificacionsLive(TemplateView):
    template_name = "classificacions/classificacions_live.html"

    def dispatch(self, request, *args, **kwargs):
        self.token_obj = get_object_or_404(PublicLiveToken, pk=kwargs["token"])
        if not self.token_obj.is_valid():
            return JsonResponse({"ok": False, "error": "Token invalid o revocat"}, status=403)
        self.token_obj.touch()
        self.competicio = self.token_obj.competicio
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(
            {
                "competicio": self.competicio,
                "cfgs": active_cfg_values(self.competicio, only_public=True),
                "is_public": True,
                "hide_base_chrome": True,
                "poll_ms": 4000,
                "public_token_can_view_media": bool(self.token_obj.can_view_media),
                "data_url": self.request.build_absolute_uri(
                    reverse("public_live_classificacions_data", kwargs={"token": self.token_obj.id})
                ),
            }
        )
        return ctx


class PublicClassificacionsLoopLive(TemplateView):
    template_name = "classificacions/classificacions_loop_live.html"

    @staticmethod
    def _parse_int_param(raw, default: int, min_value: int, max_value: int) -> int:
        try:
            value = int(raw)
        except Exception:
            value = default
        return max(min_value, min(max_value, value))

    def dispatch(self, request, *args, **kwargs):
        self.token_obj = get_object_or_404(PublicLiveToken, pk=kwargs["token"])
        if not self.token_obj.is_valid():
            return JsonResponse({"ok": False, "error": "Token invalid o revocat"}, status=403)
        self.token_obj.touch()
        self.competicio = self.token_obj.competicio
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        poll_ms = self._parse_int_param(self.request.GET.get("poll_ms"), 4000, 1000, 60000)
        slide_ms = self._parse_int_param(self.request.GET.get("slide_ms"), 8000, 2000, 120000)
        rows_per_page = self._parse_int_param(self.request.GET.get("rows"), 12, 3, 60)
        transition = (self.request.GET.get("transition") or "fade").strip().lower()
        if transition not in {"fade", "none"}:
            transition = "fade"
        ctx.update(
            {
                "competicio": self.competicio,
                "cfgs": active_cfg_values(self.competicio, only_public=True),
                "is_public": True,
                "hide_base_chrome": True,
                "poll_ms": poll_ms,
                "slide_ms": slide_ms,
                "rows_per_page": rows_per_page,
                "transition": transition,
                "public_token_can_view_media": bool(self.token_obj.can_view_media),
                "data_url": self.request.build_absolute_uri(
                    reverse("public_live_classificacions_data", kwargs={"token": self.token_obj.id})
                ),
            }
        )
        return ctx


def classificacions_live_data(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    payload, source = get_live_payload_cached(
        competicio,
        compute_payload=live_data_payload,
        since_raw=request.GET.get("since"),
    )
    public_raw = (request.GET.get("public") or "").strip().lower()
    if public_raw in {"1", "true", "yes", "on"}:
        payload = public_live_payload(payload)
    response = JsonResponse(payload)
    response["X-Live-Cache"] = source
    return response


def public_classificacions_live_data(request, token):
    token_obj = get_object_or_404(PublicLiveToken, pk=token)
    if not token_obj.is_valid():
        return JsonResponse({"ok": False, "error": "Token invalid o revocat"}, status=403)

    competicio = token_obj.competicio
    payload, source = get_live_payload_cached(
        competicio,
        compute_payload=live_data_payload,
        since_raw=request.GET.get("since"),
    )
    payload = public_live_payload(payload)
    payload["permissions"] = {"can_view_media": bool(token_obj.can_view_media)}
    response = JsonResponse(payload)
    response["X-Live-Cache"] = source
    return response


__all__ = [
    "ClassificacionsLive",
    "ClassificacionsLoopLive",
    "PublicClassificacionsLive",
    "PublicClassificacionsLoopLive",
    "build_live_cfg_payload_row",
    "classificacions_live_data",
    "compute_classificacio",
    "live_data_payload",
    "public_classificacions_live_data",
]
