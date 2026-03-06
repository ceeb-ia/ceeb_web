import json

from django.db import transaction
from django.db.models import Case, IntegerField, Value, When
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_http_methods, require_POST

from .models import Competicio
from .models_judging import (
    JudgeConversation,
    JudgeConversationMessage,
    JudgeDeviceToken,
)


JUDGE_MESSAGE_MAX_LENGTH = 500
JUDGE_SUPPORT_COOLDOWN_SECONDS = 30
JUDGE_MESSAGES_SNAPSHOT_LIMIT = 120
JUDGE_MESSAGES_DELTA_LIMIT = 200
ORG_CONVERSATIONS_LIMIT = 300


def _json_body(request):
    raw = (request.body or b"").decode("utf-8").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _normalize_text(value):
    text = str(value or "").strip()
    if len(text) > JUDGE_MESSAGE_MAX_LENGTH:
        return text[:JUDGE_MESSAGE_MAX_LENGTH]
    return text


def _conversation_ordering_queryset(qs):
    priority_order = Case(
        When(status=JudgeConversation.Status.REQUESTED, then=Value(0)),
        When(status=JudgeConversation.Status.ACK, then=Value(1)),
        When(status=JudgeConversation.Status.IDLE, then=Value(2)),
        default=Value(3),
        output_field=IntegerField(),
    )
    return qs.order_by(priority_order, "-unread_for_org", "-last_message_at", "-updated_at")


def _sender_label(message):
    if message.sender_type == JudgeConversationMessage.SenderType.JUDGE:
        label = (getattr(message.judge_token, "label", "") or "").strip()
        return label or "Jurat"
    if message.sender_type == JudgeConversationMessage.SenderType.ORGANIZATION:
        user = message.sender_user
        if not user:
            return "Organitzacio"
        full = (user.get_full_name() or "").strip()
        return full or user.get_username() or "Organitzacio"
    return "Sistema"


def _preview_for_message(message_type, text):
    if text:
        return text[:180]
    if message_type == JudgeConversationMessage.MessageType.SUPPORT_REQUEST_QUICK:
        return "Jutge demana assistencia immediata."
    if message_type == JudgeConversationMessage.MessageType.SUPPORT_REQUEST:
        return "Jutge demana assistencia."
    if message_type == JudgeConversationMessage.MessageType.INSTRUCTION:
        return "Nova instruccio d'organitzacio."
    if message_type == JudgeConversationMessage.MessageType.SYSTEM:
        return "Actualitzacio de l'estat de suport."
    return "Nou missatge"


def _conversation_payload(conv):
    return {
        "id": str(conv.id),
        "status": conv.status,
        "priority": conv.priority,
        "unread_for_org": int(conv.unread_for_org or 0),
        "unread_for_judge": int(conv.unread_for_judge or 0),
        "last_message_at": conv.last_message_at.isoformat() if conv.last_message_at else None,
        "last_message_preview": conv.last_message_preview or "",
        "requested_at": conv.requested_at.isoformat() if conv.requested_at else None,
        "acked_at": conv.acked_at.isoformat() if conv.acked_at else None,
        "resolved_at": conv.resolved_at.isoformat() if conv.resolved_at else None,
        "token_id": str(conv.judge_token_id),
        "token_label": conv.judge_token.label or "",
        "comp_aparell_id": conv.comp_aparell_id,
        "comp_aparell_label": getattr(conv.comp_aparell.aparell, "nom", "") or "",
    }


def _message_payload(message):
    return {
        "id": message.id,
        "conversation_id": str(message.conversation_id),
        "sender_type": message.sender_type,
        "sender_label": _sender_label(message),
        "message_type": message.message_type,
        "text": message.text or "",
        "payload": message.payload or {},
        "created_at": message.created_at.isoformat() if message.created_at else None,
    }


def _get_or_create_conversation_for_token(token_obj):
    defaults = {
        "competicio": token_obj.competicio,
        "comp_aparell": token_obj.comp_aparell,
    }
    conv, _created = JudgeConversation.objects.get_or_create(
        judge_token=token_obj,
        defaults=defaults,
    )
    dirty_fields = []
    if conv.competicio_id != token_obj.competicio_id:
        conv.competicio = token_obj.competicio
        dirty_fields.append("competicio")
    if conv.comp_aparell_id != token_obj.comp_aparell_id:
        conv.comp_aparell = token_obj.comp_aparell
        dirty_fields.append("comp_aparell")
    if dirty_fields:
        dirty_fields.append("updated_at")
        conv.save(update_fields=dirty_fields)
    return conv


def _support_cooldown_remaining(conversation, now_dt):
    last_request = (
        JudgeConversationMessage.objects
        .filter(
            conversation=conversation,
            sender_type=JudgeConversationMessage.SenderType.JUDGE,
            message_type__in=(
                JudgeConversationMessage.MessageType.SUPPORT_REQUEST,
                JudgeConversationMessage.MessageType.SUPPORT_REQUEST_QUICK,
            ),
        )
        .order_by("-created_at")
        .first()
    )
    if not last_request or not last_request.created_at:
        return 0
    elapsed = (now_dt - last_request.created_at).total_seconds()
    remain = int(JUDGE_SUPPORT_COOLDOWN_SECONDS - elapsed)
    return max(0, remain)


def _append_message_locked(
    *,
    conversation,
    sender_type,
    message_type,
    text,
    sender_user=None,
    payload=None,
):
    now_dt = timezone.now()
    msg = JudgeConversationMessage.objects.create(
        conversation=conversation,
        competicio=conversation.competicio,
        comp_aparell=conversation.comp_aparell,
        judge_token=conversation.judge_token,
        sender_type=sender_type,
        sender_user=sender_user,
        message_type=message_type,
        text=text,
        payload=payload or {},
    )

    conversation.last_message_at = msg.created_at or now_dt
    conversation.last_message_preview = _preview_for_message(message_type, text)
    if sender_type == JudgeConversationMessage.SenderType.JUDGE:
        conversation.unread_for_org = int(conversation.unread_for_org or 0) + 1
        if message_type in (
            JudgeConversationMessage.MessageType.SUPPORT_REQUEST,
            JudgeConversationMessage.MessageType.SUPPORT_REQUEST_QUICK,
        ) or conversation.status in (
            JudgeConversation.Status.IDLE,
            JudgeConversation.Status.RESOLVED,
        ):
            conversation.status = JudgeConversation.Status.REQUESTED
            conversation.priority = JudgeConversation.Priority.HIGH
            conversation.requested_at = now_dt
            conversation.resolved_at = None
    else:
        conversation.unread_for_judge = int(conversation.unread_for_judge or 0) + 1
        if sender_type == JudgeConversationMessage.SenderType.ORGANIZATION and conversation.status in (
            JudgeConversation.Status.IDLE,
            JudgeConversation.Status.REQUESTED,
        ):
            conversation.status = JudgeConversation.Status.ACK
            conversation.acked_at = now_dt
            conversation.resolved_at = None

    conversation.save(
        update_fields=[
            "last_message_at",
            "last_message_preview",
            "unread_for_org",
            "unread_for_judge",
            "status",
            "priority",
            "requested_at",
            "acked_at",
            "resolved_at",
            "updated_at",
        ]
    )
    return msg


def _list_messages_for_conversation(conversation, since_dt=None):
    qs = JudgeConversationMessage.objects.filter(conversation=conversation).select_related("sender_user", "judge_token")
    if since_dt:
        qs = qs.filter(created_at__gt=since_dt)
        limit = JUDGE_MESSAGES_DELTA_LIMIT
    else:
        limit = JUDGE_MESSAGES_SNAPSHOT_LIMIT
    rows = list(qs.order_by("-created_at")[:limit])
    rows.reverse()
    return rows


@require_POST
def judge_request_support(request, token):
    token_obj = get_object_or_404(JudgeDeviceToken, pk=token)
    if not token_obj.is_valid():
        return JsonResponse({"ok": False, "error": "Token invalid o revocat"}, status=403)
    token_obj.touch()

    payload = _json_body(request)
    if payload is None:
        return JsonResponse({"ok": False, "error": "JSON invalid"}, status=400)

    text = _normalize_text((payload or {}).get("text"))
    quick = str((payload or {}).get("quick", "1")).strip().lower() not in {"0", "false", "no"}
    message_type = (
        JudgeConversationMessage.MessageType.SUPPORT_REQUEST_QUICK
        if quick and not text
        else JudgeConversationMessage.MessageType.SUPPORT_REQUEST
    )
    if not text and message_type == JudgeConversationMessage.MessageType.SUPPORT_REQUEST_QUICK:
        text = "Jutge demana assistencia immediata."
    elif not text:
        text = "Jutge demana assistencia."

    now_dt = timezone.now()
    with transaction.atomic():
        conversation = _get_or_create_conversation_for_token(token_obj)
        conversation = (
            JudgeConversation.objects
            .select_for_update()
            .select_related("judge_token", "comp_aparell__aparell")
            .get(pk=conversation.pk)
        )
        remain = _support_cooldown_remaining(conversation, now_dt)
        if remain > 0:
            return JsonResponse(
                {
                    "ok": False,
                    "error": f"Espera {remain}s abans de tornar a sol.licitar assistencia.",
                    "reason": "cooldown",
                    "retry_after_seconds": remain,
                },
                status=429,
            )

        message = _append_message_locked(
            conversation=conversation,
            sender_type=JudgeConversationMessage.SenderType.JUDGE,
            message_type=message_type,
            text=text,
            payload={"quick": message_type == JudgeConversationMessage.MessageType.SUPPORT_REQUEST_QUICK},
        )

    return JsonResponse(
        {
            "ok": True,
            "quick": message_type == JudgeConversationMessage.MessageType.SUPPORT_REQUEST_QUICK,
            "conversation": _conversation_payload(conversation),
            "message": _message_payload(message),
            "retry_after_seconds": JUDGE_SUPPORT_COOLDOWN_SECONDS,
        }
    )


@require_POST
def judge_send_message(request, token):
    token_obj = get_object_or_404(JudgeDeviceToken, pk=token)
    if not token_obj.is_valid():
        return JsonResponse({"ok": False, "error": "Token invalid o revocat"}, status=403)
    token_obj.touch()

    payload = _json_body(request)
    if payload is None:
        return JsonResponse({"ok": False, "error": "JSON invalid"}, status=400)

    text = _normalize_text((payload or {}).get("text"))
    if not text:
        return JsonResponse({"ok": False, "error": "Cal informar un missatge."}, status=400)

    with transaction.atomic():
        conversation = _get_or_create_conversation_for_token(token_obj)
        conversation = (
            JudgeConversation.objects
            .select_for_update()
            .select_related("judge_token", "comp_aparell__aparell")
            .get(pk=conversation.pk)
        )
        message = _append_message_locked(
            conversation=conversation,
            sender_type=JudgeConversationMessage.SenderType.JUDGE,
            message_type=JudgeConversationMessage.MessageType.REPLY,
            text=text,
        )

    return JsonResponse(
        {
            "ok": True,
            "conversation": _conversation_payload(conversation),
            "message": _message_payload(message),
        }
    )


@require_http_methods(["GET"])
def judge_messages_updates(request, token):
    token_obj = get_object_or_404(JudgeDeviceToken, pk=token)
    if not token_obj.is_valid():
        return JsonResponse({"ok": False, "error": "Token invalid o revocat"}, status=403)
    token_obj.touch()

    since_raw = (request.GET.get("since") or "").strip()
    since_dt = parse_datetime(since_raw) if since_raw else None
    conversation = _get_or_create_conversation_for_token(token_obj)
    conversation = (
        JudgeConversation.objects
        .select_related("judge_token", "comp_aparell__aparell")
        .get(pk=conversation.pk)
    )

    messages = _list_messages_for_conversation(conversation, since_dt=since_dt)
    now_dt = timezone.now()
    JudgeConversation.objects.filter(pk=conversation.pk).update(
        unread_for_judge=0,
        judge_last_read_at=now_dt,
    )
    conversation.unread_for_judge = 0
    conversation.judge_last_read_at = now_dt
    cooldown_remaining = _support_cooldown_remaining(conversation, now_dt)

    return JsonResponse(
        {
            "ok": True,
            "now": now_dt.isoformat(),
            "conversation": _conversation_payload(conversation),
            "cooldown_remaining": cooldown_remaining,
            "messages": [_message_payload(m) for m in messages],
        }
    )


@require_http_methods(["GET"])
def judge_messages_hub(request, competicio_id):
    competicio = get_object_or_404(Competicio, pk=competicio_id)
    token_rows = (
        JudgeDeviceToken.objects
        .filter(competicio=competicio, is_active=True, revoked_at__isnull=True)
        .select_related("comp_aparell__aparell")
        .order_by("comp_aparell__ordre", "label", "created_at")
    )
    tokens = [
        {
            "id": str(t.id),
            "label": t.label or "",
            "comp_aparell": {
                "id": t.comp_aparell_id,
                "aparell": {
                    "nom": getattr(t.comp_aparell.aparell, "nom", "") or "",
                },
            },
        }
        for t in token_rows
    ]
    return render(
        request,
        "competicio/judge_messages_hub.html",
        {
            "competicio": competicio,
            "tokens": tokens,
            "updates_cursor_init": timezone.now().isoformat(),
        },
    )


@require_http_methods(["GET"])
def judge_messages_updates_org(request, competicio_id):
    competicio = get_object_or_404(Competicio, pk=competicio_id)
    since_raw = (request.GET.get("since") or "").strip()
    since_dt = parse_datetime(since_raw) if since_raw else None
    conversation_id = (request.GET.get("conversation_id") or "").strip()

    conv_qs = (
        JudgeConversation.objects
        .filter(competicio=competicio)
        .select_related("judge_token", "comp_aparell__aparell")
    )
    if since_dt:
        conv_qs = conv_qs.filter(updated_at__gt=since_dt)
    conv_qs = _conversation_ordering_queryset(conv_qs)[:ORG_CONVERSATIONS_LIMIT]
    conversations = list(conv_qs)

    messages = []
    selected_conversation = None
    if conversation_id:
        selected_conversation = get_object_or_404(
            JudgeConversation.objects.select_related("judge_token", "comp_aparell__aparell"),
            pk=conversation_id,
            competicio=competicio,
        )
        messages = _list_messages_for_conversation(selected_conversation, since_dt=since_dt)
        now_dt = timezone.now()
        JudgeConversation.objects.filter(pk=selected_conversation.pk).update(
            unread_for_org=0,
            org_last_read_at=now_dt,
        )
        selected_conversation.unread_for_org = 0
        selected_conversation.org_last_read_at = now_dt
        if selected_conversation.pk not in {c.pk for c in conversations}:
            conversations.insert(0, selected_conversation)

    now_iso = timezone.now().isoformat()
    return JsonResponse(
        {
            "ok": True,
            "now": now_iso,
            "selected_conversation_id": str(selected_conversation.id) if selected_conversation else "",
            "conversations": [_conversation_payload(c) for c in conversations],
            "messages": [_message_payload(m) for m in messages],
        }
    )


@require_POST
def judge_messages_send_org(request, competicio_id):
    competicio = get_object_or_404(Competicio, pk=competicio_id)
    payload = _json_body(request)
    if payload is None:
        return JsonResponse({"ok": False, "error": "JSON invalid"}, status=400)

    text = _normalize_text((payload or {}).get("text"))
    if not text:
        return JsonResponse({"ok": False, "error": "Cal informar un missatge."}, status=400)

    conversation_id = str((payload or {}).get("conversation_id") or "").strip()
    judge_token_id = str((payload or {}).get("judge_token_id") or "").strip()
    message_type_raw = str((payload or {}).get("message_type") or "instruction").strip().lower()
    allowed_types = {
        JudgeConversationMessage.MessageType.REPLY,
        JudgeConversationMessage.MessageType.INSTRUCTION,
    }
    message_type = (
        message_type_raw
        if message_type_raw in allowed_types
        else JudgeConversationMessage.MessageType.INSTRUCTION
    )

    if not conversation_id and not judge_token_id:
        return JsonResponse({"ok": False, "error": "Cal informar conversation_id o judge_token_id."}, status=400)

    with transaction.atomic():
        if conversation_id:
            conversation = get_object_or_404(
                JudgeConversation.objects.select_for_update().select_related("judge_token", "comp_aparell__aparell"),
                pk=conversation_id,
                competicio=competicio,
            )
        else:
            token_obj = get_object_or_404(
                JudgeDeviceToken,
                pk=judge_token_id,
                competicio=competicio,
            )
            if not token_obj.is_valid():
                return JsonResponse({"ok": False, "error": "El token de desti no esta actiu."}, status=400)
            conversation = _get_or_create_conversation_for_token(token_obj)
            conversation = (
                JudgeConversation.objects
                .select_for_update()
                .select_related("judge_token", "comp_aparell__aparell")
                .get(pk=conversation.pk)
            )

        message = _append_message_locked(
            conversation=conversation,
            sender_type=JudgeConversationMessage.SenderType.ORGANIZATION,
            sender_user=request.user,
            message_type=message_type,
            text=text,
        )

    return JsonResponse(
        {
            "ok": True,
            "conversation": _conversation_payload(conversation),
            "message": _message_payload(message),
        }
    )


@require_POST
def judge_messages_set_status_org(request, competicio_id):
    competicio = get_object_or_404(Competicio, pk=competicio_id)
    payload = _json_body(request)
    if payload is None:
        return JsonResponse({"ok": False, "error": "JSON invalid"}, status=400)

    conversation_id = str((payload or {}).get("conversation_id") or "").strip()
    next_status = str((payload or {}).get("status") or "").strip().lower()
    if not conversation_id:
        return JsonResponse({"ok": False, "error": "Falta conversation_id."}, status=400)
    allowed = {
        JudgeConversation.Status.IDLE,
        JudgeConversation.Status.ACK,
        JudgeConversation.Status.RESOLVED,
        JudgeConversation.Status.REQUESTED,
    }
    if next_status not in allowed:
        return JsonResponse({"ok": False, "error": "Estat no valid."}, status=400)

    now_dt = timezone.now()
    with transaction.atomic():
        conversation = get_object_or_404(
            JudgeConversation.objects.select_for_update().select_related("judge_token", "comp_aparell__aparell"),
            pk=conversation_id,
            competicio=competicio,
        )
        conversation.status = next_status
        if next_status == JudgeConversation.Status.REQUESTED:
            conversation.requested_at = now_dt
            conversation.resolved_at = None
        elif next_status == JudgeConversation.Status.ACK:
            conversation.acked_at = now_dt
            conversation.resolved_at = None
        elif next_status == JudgeConversation.Status.RESOLVED:
            conversation.resolved_at = now_dt
        elif next_status == JudgeConversation.Status.IDLE:
            conversation.priority = JudgeConversation.Priority.NORMAL
            conversation.resolved_at = now_dt

        message = _append_message_locked(
            conversation=conversation,
            sender_type=JudgeConversationMessage.SenderType.SYSTEM,
            sender_user=request.user,
            message_type=JudgeConversationMessage.MessageType.SYSTEM,
            text=f"Organitzacio ha marcat l'estat com: {next_status}.",
            payload={"status": next_status},
        )

    return JsonResponse(
        {
            "ok": True,
            "conversation": _conversation_payload(conversation),
            "message": _message_payload(message),
        }
    )
