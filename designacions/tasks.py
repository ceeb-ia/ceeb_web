# designacions_app/tasks.py
from asgiref.sync import async_to_sync
from celery import shared_task
from django.utils import timezone

from logs import _write_job, push_log

from .main_fixed import main as engine_main
from .models import DesignationRun
from .services.excel_import import import_excels_to_db
from .services.map_rebuild import rebuild_run_map
from .services.run_scope import load_scoped_run_data


@shared_task(bind=True, queue="heavy_queue")
def process_designacions_run(
    self,
    run_id: int,
    task_id: str,
    path_disponibilitats: str,
    path_partits: str,
    params: dict | None = None,
):
    run = DesignationRun.objects.get(id=run_id)
    params = params or {}

    try:
        run.status = "processing"
        run.map_status = "processing"
        run.started_at = timezone.now()
        run.params = params
        run.save(update_fields=["status", "map_status", "started_at", "params"])

        log_and_store(task_id, "Aplicant filtres de modalitat i dates.", 8, "processing")
        df_disp, df_partits = load_scoped_run_data(path_disponibilitats, path_partits, params=params)

        log_and_store(task_id, "Important Excels a la base de dades.", 10, "processing")
        info = import_excels_to_db(run, df_disp=df_disp, df_partits=df_partits)
        log_and_store(task_id, f"Import OK: {info}", 15)

        log_and_store(task_id, "Executant motor d'optimitzacio.", 20, "processing")
        result = engine_main(
            path_disponibilitats,
            path_partits,
            task_id,
            run_id=run.id,
            config=params,
            df_dispos=df_disp,
            df_partits=df_partits,
        )

        run.result_summary = result or {}
        run.map_path = (result or {}).get("map_path")
        run.map_status = "ready"
        run.status = "done"
        run.finished_at = timezone.now()
        run.save(update_fields=["result_summary", "map_path", "map_status", "status", "finished_at"])

        async_to_sync(_write_job)(
            task_id,
            {
                "status": "done",
                "task_id": task_id,
                "summary": run.result_summary,
                "run_id": run.id,
                "map_path": run.map_path,
            },
        )

        async_to_sync(push_log)(task_id, "Proces finalitzat.", 100, status="done")
        return {"run_id": run.id, **(result or {})}

    except Exception as exc:
        run.status = "failed"
        run.map_status = "failed"
        run.error = str(exc)
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "map_status", "error", "finished_at"])

        async_to_sync(_write_job)(task_id, {"status": "failed", "error": str(exc), "task_id": task_id})
        async_to_sync(push_log)(task_id, f"ERROR: {exc}", status="failed")
        raise


def log_and_store(task_id: str, message: str, progress: int | None = None, status: str | None = None):
    async_to_sync(push_log)(task_id, message, progress, status=status)


@shared_task(bind=True, queue="heavy_queue")
def rebuild_run_map_task(self, run_id: int):
    run = DesignationRun.objects.get(id=run_id)

    try:
        run.map_status = "processing"
        run.save(update_fields=["map_status"])
        rebuild_run_map(run)
        run.refresh_from_db(fields=["map_path"])
        run.map_status = "ready"
        run.save(update_fields=["map_status"])
        return {"run_id": run.id, "map_path": run.map_path}
    except Exception:
        run.map_status = "failed"
        run.save(update_fields=["map_status"])
        raise
