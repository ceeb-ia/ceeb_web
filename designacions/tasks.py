# designacions_app/tasks.py
from celery import shared_task
from django.utils import timezone
from asgiref.sync import async_to_sync

from logs import push_log, _write_job
from .main_fixed import main as engine_main
from .models import DesignationRun
from .services.excel_import import import_excels_to_db

@shared_task(bind=True, queue="heavy_queue")
def process_designacions_run(self, run_id: int, task_id: str, path_disponibilitats: str, path_partits: str):
    run = DesignationRun.objects.get(id=run_id)

    try:
        run.status = "processing"
        run.started_at = timezone.now()
        run.save(update_fields=["status", "started_at"])

        async_to_sync(push_log)(task_id, "Important Excels a la base de dades.", 10)
        info = import_excels_to_db(run, path_disponibilitats, path_partits)
        async_to_sync(push_log)(task_id, f"Import OK: {info}", 25)

        async_to_sync(push_log)(task_id, "Executant motor d'optimització.", 35)

        # Ara el motor retorna dict, no un path a excel
        result = engine_main(path_disponibilitats, path_partits, task_id, run_id=run.id)

        # Desa resum + map_path al run
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
