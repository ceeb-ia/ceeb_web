# logs.py
import json
import os
import time

import pandas as pd
from redis import Redis
from redis.asyncio import Redis as AsyncRedis

REDIS_URL = os.getenv("REDIS_URL") or os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0")



def _json_safe(obj):
    if isinstance(obj, (pd.Timestamp,)):
        return obj.isoformat()
    return str(obj) if not isinstance(obj, (str, int, float, bool, type(None), list, dict)) else obj

def _redis_sync() -> Redis:
    return Redis.from_url(REDIS_URL, decode_responses=True)

def _redis_async() -> AsyncRedis:
    return AsyncRedis.from_url(REDIS_URL, decode_responses=True)

def _job_key(task_id: str) -> str:
    return f"job:{task_id}"

def _logs_key(task_id: str) -> str:
    return f"job:{task_id}:logs"

def _channel(task_id: str) -> str:
    return f"job:{task_id}:channel"

def _coerce_progress(value):
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

def _merge_job_payload(task_id: str, current: dict | None, incoming: dict | None) -> dict:
    merged = dict(current or {})
    payload = dict(incoming or {})

    merged["task_id"] = task_id

    incoming_progress = _coerce_progress(payload.get("progress"))
    current_progress = _coerce_progress(merged.get("progress"))
    if incoming_progress is not None:
        merged["progress"] = max(incoming_progress, current_progress or 0)
    elif current_progress is not None:
        merged["progress"] = current_progress

    for key, value in payload.items():
        if key == "progress":
            continue
        if value is None:
            continue
        merged[key] = value

    merged["updated_at"] = time.time()
    return merged

async def _write_job(task_id: str, data: dict):
    r = _redis_async()
    try:
        raw = await r.get(_job_key(task_id))
        current = None
        if raw:
            try:
                current = json.loads(raw)
            except Exception:
                current = None

        payload = _merge_job_payload(task_id, current, data)
        for k, v in payload.items():
            if isinstance(v, (pd.Timestamp,)):
                payload[k] = v.isoformat()
        await r.set(_job_key(task_id), json.dumps(payload, ensure_ascii=False, default=_json_safe))
    finally:
        await r.aclose()

async def _read_job(task_id: str) -> dict | None:
    r = _redis_async()
    raw = await r.get(_job_key(task_id))
    await r.aclose()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def read_logs_sync(task_id: str, limit: int = 200) -> list[dict]:
    r = _redis_sync()
    try:
        start = -abs(int(limit or 0)) if limit else 0
        raw_items = r.lrange(_logs_key(task_id), start, -1)
    finally:
        r.close()

    items: list[dict] = []
    for raw in raw_items:
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = {"message": str(raw)}
        if isinstance(parsed, dict):
            items.append(parsed)
    return items

async def push_log(task_id: str, message: str, progress: int | None = None, status: str | None = None):
    r = _redis_async()
    try:
        event = {"message": message, "progress": progress, "ts": time.time()}
        if status is not None:
            event["status"] = status
        for k, v in event.items():
            if isinstance(v, (pd.Timestamp,)):
                event[k] = v.isoformat()

        await r.rpush(_logs_key(task_id), json.dumps(event, ensure_ascii=False, default=_json_safe))
        await r.publish(_channel(task_id), json.dumps(event, ensure_ascii=False, default=_json_safe))

        job_payload = {"message": message}
        if progress is not None:
            job_payload["progress"] = progress
        if status is not None:
            job_payload["status"] = status
        await _write_job(task_id, job_payload)
    finally:
        await r.aclose()
