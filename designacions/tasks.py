# designacions_app/tasks.py
from celery import shared_task
from django.utils import timezone
from asgiref.sync import async_to_sync

from logs import push_log, _write_job
from .main_fixed import main as engine_main
from .models import DesignationRun
from .services.excel_import import import_excels_to_db

@shared_task(bind=True, queue="heavy_queue")
def process_designacions_run(self, run_id: int, task_id: str, path_disponibilitats: str, path_partits: str, params: dict | None = None):
    run = DesignationRun.objects.get(id=run_id)
    params = params or {}

    try:
        run.status = "processing"
        run.started_at = timezone.now()
        # guarda params definitivament (per si vénen buits)
        run.params = params
        run.save(update_fields=["status", "started_at", "params"])

        log_and_store(task_id, "Important Excels a la base de dades.", 10, "processing")
        info = import_excels_to_db(run, path_disponibilitats, path_partits)
        log_and_store(task_id, f"Import OK: {info}", 15)

        log_and_store(task_id, "Executant motor d'optimització.", 20, "processing")
        result = engine_main(path_disponibilitats, path_partits, task_id, run_id=run.id, config=params)

        run.result_summary = result or {}
        run.map_path = (result or {}).get("map_path")
        run.status = "done"
        run.finished_at = timezone.now()
        run.save(update_fields=["result_summary", "map_path", "status", "finished_at"])

        async_to_sync(_write_job)(task_id, {
            "status": "done",
            "task_id": task_id,
            "summary": run.result_summary,
            "run_id": run.id,
            "map_path": run.map_path,
        })

        async_to_sync(push_log)(task_id, "Procés finalitzat.", 100)
        return {"run_id": run.id, **(result or {})}

    except Exception as exc:
        run.status = "failed"
        run.error = str(exc)
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "error", "finished_at"])

        async_to_sync(push_log)(task_id, f"ERROR: {exc}", 0)
        async_to_sync(_write_job)(task_id, {"status": "failed", "error": str(exc), "task_id": task_id})
        raise


def log_and_store(task_id: str, message: str, progress: int | None = None, status: str | None = None):
    async_to_sync(push_log)(task_id, message, progress)

    data = {"task_id": task_id, "message": message}
    if progress is not None:
        data["progress"] = int(progress)
    if status:
        data["status"] = status

    async_to_sync(_write_job)(task_id, data)
