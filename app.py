import json
from fastapi import FastAPI, BackgroundTasks, Header, Body
from fastapi.responses import FileResponse, JSONResponse
import tempfile, os, uuid
import io
from calendaritzacions.application import process_calendarization
from redis import asyncio as redis
from anyio import to_thread
import asyncio
import shutil
import logging
import aiofiles
from logs import _write_job, _read_job, push_log


app = FastAPI()

@app.get("/health")
def health():
    return {"status": "ok"}


# We persist job metadata in Redis so restarts don't lose state
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
r = redis.from_url(REDIS_URL, encoding="utf-8", decode_responses=True)

# Directory to store final results (mount this to a volume in Docker)
RESULTS_DIR = os.getenv('MEDIA_ROOT', '/data/media')
MEDIA_URL = os.getenv('MEDIA_URL', '/media/')
os.makedirs(RESULTS_DIR, exist_ok=True)






async def _run_job(job_id: str, file_path: str, client_task_id: str | None = None):
    logs = []
    ch = client_task_id or job_id
    try:
        # mark running (store to Redis)
        job = await _read_job(job_id) or {}
        job.update({"status": "running", "task_id": client_task_id})
        await _write_job(job_id, job)
        await push_log(ch, "Començant procés", 0)

        out_path, partial_logs = await to_thread.run_sync(process_calendarization, file_path, True, ch, False)
        # Debug: report what process_excel returned so we can diagnose missing results
        try:
            await push_log(ch, "Excel generat", 95)
        except Exception:
            pass



        # If the task finished, move the result into the shared RESULTS_DIR
        # and save a relative path + public URL in the Redis job metadata so
        # the frontend can download it directly via MEDIA_URL.
        final_path = None
            
        if out_path and os.path.exists(out_path):
            filename = f"{job_id}_{os.path.basename(out_path)}"
            final_path = os.path.join(RESULTS_DIR, filename)
            shutil.move(out_path, final_path)
            # Store a relative path (filename) and a public URL
            result_rel = filename
            result_url = MEDIA_URL.rstrip('/') + '/' + result_rel.lstrip('/')
            await push_log(ch, "Preparant resultat", 99)
            job.update({"status": "done", "result": result_rel, "result_url": result_url, "logs": logs})
            await _write_job(job_id, job)

    except Exception as e:
        logs.append(f"Error: {str(e)}")
        job = await _read_job(job_id) or {}
        job.update({"status": "failed", "logs": logs, "result": None})
        await _write_job(job_id, job)
        await push_log(ch, f"failed: {str(e)}")
        return




@app.post("/process_async")
async def process_async(
    file_path: str = Body(..., embed=True),
    bg: BackgroundTasks = None,
    client_task_id: str | None = Header(None, alias="X-Task-ID"),
):

    # Basic validation: file_path must be a string, absolute, and located
    # under the shared RESULTS_DIR so we don't allow arbitrary file access.
    try:
        if not isinstance(file_path, str):
            return JSONResponse(status_code=400, content={"error": "file_path must be a string"})
        file_abspath = os.path.abspath(file_path)
        results_abspath = os.path.abspath(RESULTS_DIR)
        # Ensure the provided path is inside the shared results/media directory
        try:
            common = os.path.commonpath([results_abspath, file_abspath])
        except Exception:
            common = None
        if not os.path.isabs(file_abspath) or common != results_abspath:
            return JSONResponse(status_code=400, content={"error": "file_path must be an absolute path inside the shared media directory"})
        if not os.path.exists(file_abspath):
            return JSONResponse(status_code=404, content={"error": "file_path not found on server"})
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": f"Invalid file_path: {e}"})

    if client_task_id:
        job_id = client_task_id
        # register job in Redis so status/result can be queried later
        await _write_job(job_id, {"status": "queued", "logs": [], "result": None, "task_id": client_task_id})
        bg.add_task(_run_job, job_id, file_abspath, client_task_id)
        return JSONResponse(status_code=202, content={"job_id": job_id})

    else:
        # Reject requests without X-Task-ID header
        return JSONResponse(status_code=400, content={"error": "X-Task-ID header required"})


async def _run_job_segona_fase(job_id: str, file_path: str, client_task_id: str | None = None):
    logs = []
    ch = client_task_id or job_id
    try:
        # mark running (store to Redis)
        job = await _read_job(job_id) or {}
        job.update({"status": "running", "task_id": client_task_id})
        await _write_job(job_id, job)
        await push_log(ch, "Començant procés", 0)

        out_path, partial_logs = await to_thread.run_sync(process_calendarization, file_path, True, ch, True)
        # Debug: report what process_excel returned so we can diagnose missing results
        try:
            await push_log(ch, "Excel generat", 95)
        except Exception:
            pass



        # If the task finished, move the result into the shared RESULTS_DIR
        # and save a relative path + public URL in the Redis job metadata so
        # the frontend can download it directly via MEDIA_URL.
        final_path = None
            
        if out_path and os.path.exists(out_path):
            filename = f"{job_id}_{os.path.basename(out_path)}"
            final_path = os.path.join(RESULTS_DIR, filename)
            shutil.move(out_path, final_path)
            # Store a relative path (filename) and a public URL
            result_rel = filename
            result_url = MEDIA_URL.rstrip('/') + '/' + result_rel.lstrip('/')
            await push_log(ch, "Preparant resultat", 99)
            job.update({"status": "done", "result": result_rel, "result_url": result_url, "logs": logs})
            await _write_job(job_id, job)

    except Exception as e:
        logs.append(f"Error: {str(e)}")
        job = await _read_job(job_id) or {}
        job.update({"status": "failed", "logs": logs, "result": None})
        await _write_job(job_id, job)
        await push_log(ch, f"failed: {str(e)}")
        return




@app.post("/process_async_segona_fase")
async def process_async_segona_fase(
    file_path: str = Body(..., embed=True),
    bg: BackgroundTasks = None,
    client_task_id: str | None = Header(None, alias="X-Task-ID"),
):

    # Basic validation: file_path must be a string, absolute, and located
    # under the shared RESULTS_DIR so we don't allow arbitrary file access.
    try:
        if not isinstance(file_path, str):
            return JSONResponse(status_code=400, content={"error": "file_path must be a string"})
        file_abspath = os.path.abspath(file_path)
        results_abspath = os.path.abspath(RESULTS_DIR)
        # Ensure the provided path is inside the shared results/media directory
        try:
            common = os.path.commonpath([results_abspath, file_abspath])
        except Exception:
            common = None
        if not os.path.isabs(file_abspath) or common != results_abspath:
            return JSONResponse(status_code=400, content={"error": "file_path must be an absolute path inside the shared media directory"})
        if not os.path.exists(file_abspath):
            return JSONResponse(status_code=404, content={"error": "file_path not found on server"})
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": f"Invalid file_path: {e}"})

    if client_task_id:
        job_id = client_task_id
        # register job in Redis so status/result can be queried later
        await _write_job(job_id, {"status": "queued", "logs": [], "result": None, "task_id": client_task_id})
        bg.add_task(_run_job_segona_fase, job_id, file_abspath, client_task_id)
        return JSONResponse(status_code=202, content={"job_id": job_id})

    else:
        # Reject requests without X-Task-ID header
        return JSONResponse(status_code=400, content={"error": "X-Task-ID header required"})





@app.get("/status/{job_id}")
async def status(job_id: str):
    job = await _read_job(job_id)
    if not job:
        return {"status": "unknown", "logs": []}
    return job


@app.get("/download/{job_id}")
async def download(job_id: str):
    job = await _read_job(job_id)
    if not job:
        return JSONResponse(status_code=404, content={"error": "Job no trobat"})
    if job.get("status") != "done":
        return JSONResponse(status_code=404, content={"error": "Resultat encara no disponible"})
    result = job.get("result")
    if not result:
        return JSONResponse(status_code=500, content={"error": "Resultat sense path"})
    # Resolve result which may be a relative path stored in Redis (relative
    # to RESULTS_DIR) or an absolute filesystem path.
    candidate_path = None
    try:
        if isinstance(result, str) and os.path.isabs(result) and os.path.exists(result):
            candidate_path = result
        else:
            candidate_path = os.path.join(RESULTS_DIR, result)
            if not os.path.exists(candidate_path):
                candidate_path = None
    except Exception:
        candidate_path = None

    if candidate_path and os.path.exists(candidate_path):
        media = "application/zip" if candidate_path.endswith('.zip') else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        filename = os.path.basename(candidate_path)
        return FileResponse(candidate_path, media_type=media, filename=filename)

    return JSONResponse(status_code=500, content={"error": "Resultat no trobat al servidor"})

