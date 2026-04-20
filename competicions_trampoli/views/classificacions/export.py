from io import BytesIO

from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404
from openpyxl import Workbook

from ...models import Competicio
from ...models.classificacions import ClassificacioConfig
from ...services.classificacions.compute import compute_classificacio
from ...services.classificacions.export import (
    build_excel_sheet_name,
    sanitize_filename_component,
    write_cfg_excel_sheet,
)
from ...services.classificacions.live import default_live_columns
from ...services.classificacions.runtime import execute_classificacio_runtime


def classificacions_live_export_excel(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    cfg_qs = (
        ClassificacioConfig.objects
        .filter(competicio=competicio, activa=True)
        .order_by("ordre", "id")
    )

    cfg_id_raw = (request.GET.get("cfg_id") or "").strip()
    selected_cfg_id = None
    if cfg_id_raw:
        try:
            selected_cfg_id = int(cfg_id_raw)
        except Exception:
            return HttpResponseBadRequest("cfg_id invalid")
        cfg_qs = cfg_qs.filter(id=selected_cfg_id)

    cfgs = list(cfg_qs)
    if not cfgs:
        return HttpResponseBadRequest("No hi ha classificacions actives per exportar.")

    wb = Workbook()
    used_sheet_names = set()
    for idx, cfg in enumerate(cfgs):
        ws = wb.active if idx == 0 else wb.create_sheet()
        ws.title = build_excel_sheet_name(cfg.nom or f"Classificacio {idx + 1}", used_sheet_names)

        runtime = execute_classificacio_runtime(
            competicio,
            schema_local=cfg.schema or {},
            tipus=cfg.tipus,
            compute_fn=compute_classificacio,
            invalid_message="Configuracio de classificacio invalida.",
            runtime_message="No s'ha pogut renderitzar la classificacio.",
        )
        if runtime["error"]:
            reasons = " | ".join(runtime["error"]["errors"])
            return HttpResponseBadRequest(
                f"La classificacio '{cfg.nom}' no es pot exportar: {runtime['error']['message']} | {reasons}"
            )
        parts = runtime["parts"]
        columns = runtime["columns"] or default_live_columns()
        write_cfg_excel_sheet(
            ws,
            competicio,
            cfg.nom or f"Classificacio {idx + 1}",
            columns,
            parts,
            tipus=cfg.tipus,
            schema=runtime["schema"],
        )

    content = BytesIO()
    wb.save(content)
    response = HttpResponse(
        content.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    suffix = f"_cfg_{selected_cfg_id}" if selected_cfg_id else ""
    filename = f"classificacions_{sanitize_filename_component(competicio.nom)}{suffix}.xlsx"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


__all__ = ["classificacions_live_export_excel"]
