# designacions_app/services/jobstore.py
from asgiref.sync import async_to_sync
from logs import _read_job, _write_job

def write_job_sync(task_id: str, data: dict):
    async_to_sync(_write_job)(task_id, data)

def read_job_sync(task_id: str):
    return async_to_sync(_read_job)(task_id)
