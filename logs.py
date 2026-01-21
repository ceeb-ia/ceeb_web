# logs.py
import os, json, time
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

async def _write_job(task_id: str, data: dict):
    r = _redis_async()
    payload = dict(data or {})
    payload.setdefault("task_id", task_id)
    payload.setdefault("updated_at", time.time())
    # Convert all values to JSON-safe
    for k, v in payload.items():
        if isinstance(v, (pd.Timestamp,)):
            payload[k] = v.isoformat()
    await r.set(_job_key(task_id), json.dumps(payload, ensure_ascii=False, default=_json_safe))
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

async def push_log(task_id: str, message: str, progress: int | None = None):
    r = _redis_async()
    event = {"message": message, "progress": progress, "ts": time.time()}
    # Convert all values to JSON-safe
    for k, v in event.items():
        if isinstance(v, (pd.Timestamp,)):
            event[k] = v.isoformat()
    await r.rpush(_logs_key(task_id), json.dumps(event, ensure_ascii=False, default=_json_safe))
    await r.publish(_channel(task_id), json.dumps(event, ensure_ascii=False, default=_json_safe))
    await r.aclose()
