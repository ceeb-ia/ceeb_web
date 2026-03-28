import json
import logging
import os
import time
import uuid

from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.timezone import is_aware

try:
    import redis
except ImportError:  # pragma: no cover - optional dependency in local/test envs
    redis = None


logger = logging.getLogger(__name__)
REDIS_URL = os.getenv("REDIS_URL") or os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0")
LIVE_CACHE_FRESH_TTL_SECONDS = 4
LIVE_CACHE_STALE_GRACE_SECONDS = 30
LIVE_CACHE_LOCK_TTL_SECONDS = 15
LIVE_CACHE_DIRTY_TTL_SECONDS = 300
LIVE_CACHE_WAIT_ATTEMPTS = 2
LIVE_CACHE_WAIT_DELAY_SECONDS = 0.2


def _live_redis_client():
    if redis is None:
        raise RuntimeError("redis package is not installed")
    return redis.from_url(REDIS_URL, encoding="utf-8", decode_responses=True)


def live_cache_key(competicio_id: int) -> str:
    return f"live:classificacions:{int(competicio_id)}"


def live_lock_key(competicio_id: int) -> str:
    return f"lock:live:classificacions:{int(competicio_id)}"


def live_dirty_key(competicio_id: int) -> str:
    return f"dirty:live:classificacions:{int(competicio_id)}"


def _coerce_live_datetime(raw):
    if not raw:
        return None
    dt = parse_datetime(str(raw))
    if dt and not is_aware(dt):
        dt = timezone.make_aware(dt, timezone.get_current_timezone())
    return dt


def _build_live_snapshot(payload: dict) -> dict:
    snapshot = dict(payload or {})
    snapshot["generated_at"] = timezone.now().isoformat()
    snapshot["ok"] = True
    snapshot["changed"] = True
    return snapshot


def _decode_live_snapshot(raw):
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except Exception:
        logger.warning("Invalid live snapshot JSON from Redis", exc_info=True)
        return None
    if not isinstance(data, dict) or not data.get("stamp"):
        return None
    return data


def load_live_snapshot(redis_client, competicio_id: int):
    return _decode_live_snapshot(redis_client.get(live_cache_key(competicio_id)))


def store_live_snapshot(redis_client, competicio_id: int, payload: dict) -> dict:
    snapshot = _build_live_snapshot(payload)
    ttl = LIVE_CACHE_FRESH_TTL_SECONDS + LIVE_CACHE_STALE_GRACE_SECONDS
    redis_client.set(
        live_cache_key(competicio_id),
        json.dumps(snapshot, ensure_ascii=False),
        ex=ttl,
    )
    return snapshot


def get_live_dirty_marker(redis_client, competicio_id: int):
    return redis_client.get(live_dirty_key(competicio_id))


def clear_live_dirty_if_match(redis_client, competicio_id: int, marker: str) -> bool:
    if not marker:
        return False
    try:
        key = live_dirty_key(competicio_id)
        if redis_client.get(key) != marker:
            return False
        redis_client.delete(key)
        return True
    except Exception:
        logger.warning("Failed to clear live dirty marker", exc_info=True)
        return False


def mark_live_dirty(competicio_id: int, marker=None):
    if not competicio_id:
        return None
    marker = str(marker or uuid.uuid4())
    try:
        redis_client = _live_redis_client()
        redis_client.set(
            live_dirty_key(competicio_id),
            marker,
            ex=LIVE_CACHE_DIRTY_TTL_SECONDS,
        )
    except Exception:
        logger.warning("Failed to mark live dirty", exc_info=True)
    return marker


def _live_snapshot_age_seconds(snapshot: dict, now=None):
    now = now or timezone.now()
    generated_at = _coerce_live_datetime(snapshot.get("generated_at"))
    if generated_at is None:
        return None
    return max(0.0, (now - generated_at).total_seconds())


def _live_snapshot_is_fresh(snapshot: dict, now=None) -> bool:
    age = _live_snapshot_age_seconds(snapshot, now=now)
    return age is not None and age <= LIVE_CACHE_FRESH_TTL_SECONDS


def _live_snapshot_is_usable(snapshot: dict, now=None) -> bool:
    age = _live_snapshot_age_seconds(snapshot, now=now)
    if age is None:
        return False
    return age <= (LIVE_CACHE_FRESH_TTL_SECONDS + LIVE_CACHE_STALE_GRACE_SECONDS)


def _try_acquire_live_lock(redis_client, competicio_id: int):
    token = str(uuid.uuid4())
    acquired = redis_client.set(
        live_lock_key(competicio_id),
        token,
        nx=True,
        ex=LIVE_CACHE_LOCK_TTL_SECONDS,
    )
    return token if acquired else None


def _release_live_lock(redis_client, competicio_id: int, token: str) -> None:
    if not token:
        return
    try:
        key = live_lock_key(competicio_id)
        if redis_client.get(key) == token:
            redis_client.delete(key)
    except Exception:
        logger.warning("Failed to release live cache lock", exc_info=True)


def _wait_for_live_snapshot(redis_client, competicio_id: int, attempts=None, delay=None):
    attempts = LIVE_CACHE_WAIT_ATTEMPTS if attempts is None else max(0, int(attempts))
    delay = LIVE_CACHE_WAIT_DELAY_SECONDS if delay is None else max(0.0, float(delay))
    for _ in range(attempts):
        if delay > 0:
            time.sleep(delay)
        snapshot = load_live_snapshot(redis_client, competicio_id)
        if snapshot:
            return snapshot
    return None


def _live_response_from_snapshot(snapshot: dict, since_raw=None) -> dict:
    stamp_raw = snapshot.get("stamp")
    stamp_dt = _coerce_live_datetime(stamp_raw)
    since_dt = _coerce_live_datetime(since_raw)
    if stamp_dt and since_dt and stamp_dt <= since_dt:
        return {"ok": True, "changed": False, "stamp": stamp_raw}

    response = {
        key: value
        for key, value in snapshot.items()
        if key != "generated_at"
    }
    response["ok"] = True
    response["changed"] = True
    return response


def get_live_payload_cached(competicio, compute_payload, since_raw=None):
    try:
        redis_client = _live_redis_client()
    except Exception:
        logger.warning("Live cache Redis unavailable while creating client", exc_info=True)
        return compute_payload(competicio, since_raw=since_raw), "fallback"

    try:
        snapshot = load_live_snapshot(redis_client, competicio.id)
        dirty_marker = get_live_dirty_marker(redis_client, competicio.id)
        now = timezone.now()

        if snapshot and _live_snapshot_is_fresh(snapshot, now=now) and not dirty_marker:
            return _live_response_from_snapshot(snapshot, since_raw=since_raw), "hit"

        if snapshot and _live_snapshot_is_usable(snapshot, now=now):
            lock_token = _try_acquire_live_lock(redis_client, competicio.id)
            if lock_token:
                try:
                    refresh_dirty_marker = dirty_marker or get_live_dirty_marker(redis_client, competicio.id)
                    payload = compute_payload(competicio, since_raw=None)
                    try:
                        snapshot = store_live_snapshot(redis_client, competicio.id, payload)
                    except Exception:
                        logger.warning("Failed to store refreshed live snapshot", exc_info=True)
                        snapshot = _build_live_snapshot(payload)
                    if refresh_dirty_marker:
                        clear_live_dirty_if_match(redis_client, competicio.id, refresh_dirty_marker)
                    return _live_response_from_snapshot(snapshot, since_raw=since_raw), "refresh"
                finally:
                    _release_live_lock(redis_client, competicio.id, lock_token)
            return _live_response_from_snapshot(snapshot, since_raw=since_raw), "stale"

        lock_token = _try_acquire_live_lock(redis_client, competicio.id)
        if lock_token:
            try:
                refresh_dirty_marker = dirty_marker or get_live_dirty_marker(redis_client, competicio.id)
                payload = compute_payload(competicio, since_raw=None)
                try:
                    snapshot = store_live_snapshot(redis_client, competicio.id, payload)
                except Exception:
                    logger.warning("Failed to store fresh live snapshot", exc_info=True)
                    snapshot = _build_live_snapshot(payload)
                if refresh_dirty_marker:
                    clear_live_dirty_if_match(redis_client, competicio.id, refresh_dirty_marker)
                return _live_response_from_snapshot(snapshot, since_raw=since_raw), "miss"
            finally:
                _release_live_lock(redis_client, competicio.id, lock_token)

        waited_snapshot = _wait_for_live_snapshot(redis_client, competicio.id)
        if waited_snapshot:
            return _live_response_from_snapshot(waited_snapshot, since_raw=since_raw), "wait-hit"
    except Exception:
        logger.warning("Live cache Redis flow failed, using direct fallback", exc_info=True)

    return compute_payload(competicio, since_raw=since_raw), "fallback"
