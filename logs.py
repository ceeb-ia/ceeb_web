import json
import os
from redis import asyncio as redis


REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

RESULTS_DIR = os.getenv('MEDIA_ROOT', '/data/media')
MEDIA_URL = os.getenv('MEDIA_URL', '/media/')
os.makedirs(RESULTS_DIR, exist_ok=True)


async def _get_client():
    """
    Crea un client Redis nou en el loop actual.
    És la clau per evitar errors de 'different loop'.
    """
    return redis.from_url(REDIS_URL, encoding="utf-8", decode_responses=True)


async def _write_job(job_id: str, data: dict):
    try:
        r = await _get_client()
        await r.set(f"job:{job_id}", json.dumps(data))
        await r.expire(f"job:{job_id}", 60 * 60 * 24 * 7)
    except Exception:
        pass


async def _read_job(job_id: str):
    try:
        r = await _get_client()
        raw = await r.get(f"job:{job_id}")
        if not raw:
            return None
        return json.loads(raw)
    except Exception:
        return None


async def push_log(task_id: str, msg: str, pct: int | None = None):
    if not task_id:
        return

    r = await _get_client()   # ← IMPORTANT: client creat dins el loop correcte

    data = {"message": msg}
    if pct is not None:
        data["progress"] = pct

    await r.publish(f"logs:{task_id}", json.dumps(data))


primera_fase = [
    [(8,5),(6,4), (7,3),(1,2)],
    [(2,8),(3,1), (4,7),(5,6)],
    [(8,6),(7,5), (1,4),(2,3)],
    [(3,8),(4,2), (5,1),(6,7)],
    [(8,7),(1,6), (2,5),(3,4)],
    [(8,4),(5,3), (6,2),(7,1)],
    [(1,8),(2,7), (3,6),(4,5)],
] 

segona_fase = [
    [(8,5),(6,4), (7,3),(1,2)],
    [(2,8),(3,1), (4,7),(5,6)],
    [(8,6),(7,5), (1,4),(2,3)],
    [(3,8),(4,2), (5,1),(6,7)],
    [(8,7),(1,6), (2,5),(3,4)],
    [(8,4),(5,3), (6,2),(7,1)],
    [(1,8),(2,7), (3,6),(4,5)], #primera
    [(5,8),(4,6), (3,7),(2,1)],
    [(8,2),(1,3), (7,4),(6,5)],
    [(6,8),(5,7), (4,1),(3,2)],
    [(8,3),(2,4), (1,5),(7,6)],
    [(7,8),(6,1), (5,2),(4,3)],
    [(4,8),(3,5), (2,6),(1,7)],
    [(8,1),(7,2), (6,3),(5,4)]
]
