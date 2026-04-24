# designacions_app/tasks.py
import inspect
import os
from dataclasses import asdict, is_dataclass
from importlib import import_module

from asgiref.sync import async_to_sync
from celery import shared_task
from django.conf import settings
from django.utils import timezone

from logs import _write_job, push_log

from .main_fixed import main as engine_main
from .models import DesignationRun
from .services.excel_import import import_excels_to_db
from .services.jobstore import preview_map_rel_path, write_preview_map_html_sync
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


def _serialize_preview_value(value):
    if is_dataclass(value):
        return _serialize_preview_value(asdict(value))
    if hasattr(value, "model_dump") and callable(value.model_dump):
        return _serialize_preview_value(value.model_dump())
    if isinstance(value, dict):
        return {str(key): _serialize_preview_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_serialize_preview_value(item) for item in value]
    if hasattr(value, "isoformat") and callable(value.isoformat):
        try:
            return value.isoformat()
        except Exception:
            pass
    if hasattr(value, "__dict__") and not isinstance(value, type):
        return _serialize_preview_value(vars(value))
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _resolve_cluster_preview_builder():
    try:
        module = import_module("designacions.clusteritzacio.preview_service")
    except ModuleNotFoundError as exc:
        raise RuntimeError("El servei de cluster preview encara no esta disponible.") from exc

    function_candidates = (
        "build_cluster_preview",
        "run_cluster_preview",
        "generate_cluster_preview",
        "create_cluster_preview",
        "build_preview",
    )
    for name in function_candidates:
        candidate = getattr(module, name, None)
        if callable(candidate):
            return candidate

    service_cls = getattr(module, "ClusterPreviewService", None)
    if service_cls is not None:
        service = service_cls()
        for name in function_candidates:
            candidate = getattr(service, name, None)
            if callable(candidate):
                return candidate

    raise RuntimeError("No s'ha trobat cap builder compatible a designacions.clusteritzacio.preview_service.")


def _invoke_cluster_preview_builder(builder, *, task_id: str, path_disponibilitats: str, path_partits: str, params: dict):
    out_map_abs = os.path.join(settings.MEDIA_ROOT, preview_map_rel_path(task_id))
    signature = inspect.signature(builder)
    accepts_kwargs = any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )
    candidate_kwargs = {
        "task_id": task_id,
        "preview_id": task_id,
        "job_id": task_id,
        "path_disponibilitats": path_disponibilitats,
        "disponibilitats_path": path_disponibilitats,
        "path_disp": path_disponibilitats,
        "file_path_dispo": path_disponibilitats,
        "path_partits": path_partits,
        "partits_path": path_partits,
        "matches_path": path_partits,
        "file_path_partits": path_partits,
        "out_map_abs": out_map_abs,
        "map_output_path": out_map_abs,
        "map_path": out_map_abs,
        "params": params,
        "config": params,
        "options": params,
    }
    if accepts_kwargs:
        return builder(**candidate_kwargs)

    kwargs = {
        name: value
        for name, value in candidate_kwargs.items()
        if name in signature.parameters
    }
    return builder(**kwargs)


def _extract_preview_map_html(payload: dict) -> str | None:
    if not isinstance(payload, dict):
        return None

    for key in ("map_html", "html"):
        html = payload.pop(key, None)
        if isinstance(html, str) and html.strip():
            return html

    map_payload = payload.get("map")
    if isinstance(map_payload, dict):
        for key in ("map_html", "html"):
            html = map_payload.pop(key, None)
            if isinstance(html, str) and html.strip():
                return html

    selected_scenario = payload.get("selected_scenario")
    if isinstance(selected_scenario, dict):
        for key in ("map_html", "html"):
            html = selected_scenario.pop(key, None)
            if isinstance(html, str) and html.strip():
                return html

    return None


@shared_task(bind=True, queue="heavy_queue")
def build_cluster_preview_task(
    self,
    task_id: str,
    path_disponibilitats: str,
    path_partits: str,
    params: dict | None = None,
):
    params = params or {}

    try:
        async_to_sync(_write_job)(
            task_id,
            {
                "status": "processing",
                "task_id": task_id,
                "preview_id": task_id,
                "params": params,
            },
        )
        log_and_store(task_id, "Preparant previsualitzacio de geolocalitzacio i clusters.", 5, "processing")
        builder = _resolve_cluster_preview_builder()
        log_and_store(task_id, "Executant calcul de preview.", 15, "processing")

        result = _invoke_cluster_preview_builder(
            builder,
            task_id=task_id,
            path_disponibilitats=path_disponibilitats,
            path_partits=path_partits,
            params=params,
        )
        payload = _serialize_preview_value(result or {})
        if not isinstance(payload, dict):
            payload = {"result": payload}

        map_html = _extract_preview_map_html(payload)
        map_path = payload.get("map_path")
        if isinstance(map_path, str) and not map_path.strip():
            map_path = None

        if map_html is not None:
            map_path = write_preview_map_html_sync(task_id, map_html)

        async_to_sync(_write_job)(
            task_id,
            {
                "status": "done",
                "task_id": task_id,
                "preview_id": task_id,
                "params": params,
                "result": payload,
                "map_path": map_path,
            },
        )
        async_to_sync(push_log)(task_id, "Previsualitzacio completada.", 100, status="done")
        return {"preview_id": task_id, "map_path": map_path, "result": payload}

    except Exception as exc:
        async_to_sync(_write_job)(
            task_id,
            {
                "status": "failed",
                "task_id": task_id,
                "preview_id": task_id,
                "params": params,
                "error": str(exc),
            },
        )
        async_to_sync(push_log)(task_id, f"ERROR: {exc}", status="failed")
        raise


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
