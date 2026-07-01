from django.urls import path

from ..views import judge as views_judge
from ..views.judge import admin as views_judge_admin
from ..views.judge import messages as views_judge_messages
from ..views.judge import qr_admin as views_qr_admin
from .base import competition_view


urlpatterns = [
    path(
        "scoring/<int:competicio_id>/qr-admin/",
        competition_view(
            views_qr_admin.qr_admin_home,
            "judge_tokens.manage",
            competicio_kwarg="competicio_id",
        ),
        name="qr_admin_home",
    ),
    path(
        "scoring/<int:competicio_id>/qr-admin/<uuid:token_id>/",
        competition_view(
            views_qr_admin.qr_admin_home,
            "judge_tokens.manage",
            competicio_kwarg="competicio_id",
        ),
        name="qr_admin_detail",
    ),
    path(
        "scoring/<int:competicio_id>/judges-qr/",
        competition_view(
            views_judge_admin.judges_qr_home,
            "judge_tokens.manage",
            competicio_kwarg="competicio_id",
        ),
        name="judges_qr_home",
    ),
    path(
        "scoring/<int:competicio_id>/judges-qr/print/",
        competition_view(
            views_judge_admin.judges_qr_print,
            "judge_tokens.manage",
            competicio_kwarg="competicio_id",
        ),
        name="judges_qr_print",
    ),
    path(
        "scoring/<int:competicio_id>/public-live-qr/",
        competition_view(
            views_judge_admin.public_live_qr_home,
            "public_live.manage",
            competicio_kwarg="competicio_id",
        ),
        name="public_live_qr_home",
    ),
    path(
        "scoring/<int:competicio_id>/public-live-qr/print/",
        competition_view(
            views_judge_admin.public_live_qr_print,
            "public_live.manage",
            competicio_kwarg="competicio_id",
        ),
        name="public_live_qr_print",
    ),
    path(
        "scoring/<int:competicio_id>/judge-messages/",
        competition_view(
            views_judge_messages.judge_messages_hub,
            "judge_messages.manage",
            competicio_kwarg="competicio_id",
        ),
        name="judge_messages_hub",
    ),
    path(
        "scoring/<int:competicio_id>/api/judge-messages/updates/",
        competition_view(
            views_judge_messages.judge_messages_updates_org,
            "judge_messages.manage",
            competicio_kwarg="competicio_id",
        ),
        name="judge_messages_updates_org",
    ),
    path(
        "scoring/<int:competicio_id>/api/judge-messages/send/",
        competition_view(
            views_judge_messages.judge_messages_send_org,
            "judge_messages.manage",
            competicio_kwarg="competicio_id",
        ),
        name="judge_messages_send_org",
    ),
    path(
        "scoring/<int:competicio_id>/api/judge-messages/status/",
        competition_view(
            views_judge_messages.judge_messages_set_status_org,
            "judge_messages.manage",
            competicio_kwarg="competicio_id",
        ),
        name="judge_messages_set_status_org",
    ),
    path("judge/<uuid:token>/manifest.json", views_judge.judge_manifest, name="judge_manifest"),
    path("judge/<uuid:token>/sw.js", views_judge.judge_service_worker, name="judge_service_worker"),
    path("judge/pwa/<str:filename>", views_judge.judge_pwa_icon, name="judge_pwa_icon"),
    path("judge/<uuid:token>/assignment/<int:assignment_id>/", views_judge.judge_portal, name="judge_portal_assignment"),
    path("judge/<uuid:token>/", views_judge.judge_portal, name="judge_portal"),
    path("judge/<uuid:token>/qr.png", views_judge.judge_qr_png, name="judge_qr_png"),
    path("judge/<uuid:token>/api/save/", views_judge.judge_save_partial, name="judge_save_partial"),
    path("judge/<uuid:token>/api/updates/", views_judge.judge_updates, name="judge_updates"),
    path(
        "judge/<uuid:token>/api/supervision/pending/",
        views_judge.judge_supervision_pending,
        name="judge_supervision_pending",
    ),
    path(
        "judge/<uuid:token>/api/supervision/approve/",
        views_judge.judge_supervision_approve,
        name="judge_supervision_approve",
    ),
    path("judge/<uuid:token>/api/video/status/", views_judge.judge_video_status, name="judge_video_status"),
    path(
        "judge/<uuid:token>/api/video/file/<str:subject_kind>/<int:subject_id>/<int:exercici>/",
        views_judge.judge_video_file,
        name="judge_video_file",
    ),
    path("judge/<uuid:token>/api/video/upload/", views_judge.judge_video_upload, name="judge_video_upload"),
    path("judge/<uuid:token>/api/video/delete/", views_judge.judge_video_delete, name="judge_video_delete"),
    path(
        "judge/<uuid:token>/api/messages/request-support/",
        views_judge_messages.judge_request_support,
        name="judge_request_support",
    ),
    path(
        "judge/<uuid:token>/api/messages/send/",
        views_judge_messages.judge_send_message,
        name="judge_send_message",
    ),
    path(
        "judge/<uuid:token>/api/messages/updates/",
        views_judge_messages.judge_messages_updates,
        name="judge_messages_updates",
    ),
    path(
        "public/live/<uuid:token>/qr.png",
        views_judge.public_live_qr_png,
        name="public_live_qr_png",
    ),
]
