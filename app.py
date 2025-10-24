from fastapi import FastAPI, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse
from fastapi.responses import StreamingResponse

import tempfile, os
import io
from main import process_excel  # la funció que acabem de crear

app = FastAPI()

@app.get("/health")
def health():
    return {"status": "ok"}

from fastapi import FastAPI, UploadFile, File, BackgroundTasks
from fastapi.responses import FileResponse, JSONResponse
import tempfile, os, uuid
from main import process_excel

app = FastAPI()
JOBS = {}  # {job_id: {"status": "queued|running|done|error", "logs": [], "result": "/tmp/out.zip"}}

def _run_job(job_id: str, in_path: str):
    JOBS[job_id]["status"] = "running"
    logs = []
    try:
        out_path, partial_logs = process_excel(in_path, return_logs=True)
        logs.extend(partial_logs)
        JOBS[job_id].update(status="done", logs=logs, result=out_path)
    except Exception as e:
        logs.append(f"ERROR: {e}")
        JOBS[job_id].update(status="error", logs=logs)

@app.post("/process_async")
async def process_async(file: UploadFile = File(...), bg: BackgroundTasks = None):
    suffix = os.path.splitext(file.filename)[1] or ".xlsx"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        in_path = tmp.name
    job_id = str(uuid.uuid4())
    JOBS[job_id] = {"status":"queued","logs":[], "result": None}
    bg.add_task(_run_job, job_id, in_path)
    return {"job_id": job_id}

@app.get("/status/{job_id}")
def status(job_id: str):
    return JOBS.get(job_id, {"status":"unknown", "logs": []})

@app.get("/download/{job_id}")
def download(job_id: str):
    job = JOBS.get(job_id)
    if not job or job["status"] != "done" or not job["result"]:
        return JSONResponse(status_code=404, content={"error": "Encara no llest"})
    
    # Si el resultat és un objecte BytesIO, retornem-lo directament
    if isinstance(job["result"], io.BytesIO):
        job["result"].seek(0)  # Tornem al principi del buffer
        return StreamingResponse(
            job["result"],
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=resultat.xlsx"}
        )
    
    # Si el resultat és un camí de fitxer (per compatibilitat amb altres casos)
    if isinstance(job["result"], str):
        media = "application/zip" if job["result"].endswith(".zip") else \
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        filename = os.path.basename(job["result"])
        return FileResponse(job["result"], media_type=media, filename=filename)
    
    # Si no és cap dels casos anteriors, retornem un error
    return JSONResponse(status_code=500, content={"error": "Tipus de resultat desconegut"})