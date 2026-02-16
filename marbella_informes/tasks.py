from __future__ import annotations
from datetime import timezone

from celery import shared_task
from django.db import transaction
from .models import AnnualReport
from .services.analysis import run_analysis  
from .services.reporting import generate_report  

# --------------------- ANALYSIS TASK ---------------------

@shared_task(bind=True, queue="heavy_queue")
def run_analysis_task(self, report_id: int):
    # estat inicial
    AnnualReport.objects.filter(pk=report_id).update(
        status="processing",
        progress=0,
        analysis_error="",
    )

    # per evitar massa writes a BD
    last = {"pct": -1, "status": ""}

    def progress_cb(pct: int, status: str):
        # actualitza només si ha canviat prou (o status nou)
        print("[task] progress_cb", pct, status)
        if pct == last["pct"] and status == last["status"]:
            return
        if last["pct"] != -1 and abs(pct - last["pct"]) < 1 and status == last["status"]:
            return

        AnnualReport.objects.filter(pk=report_id).update(
            progress=int(pct),
            status=status,
            analysis_error="",
        )
        last["pct"] = int(pct)
        last["status"] = status

    try:
        print("[task] calling run_analysis")

        run_analysis(report_id, persist=True, verbose=False, progress_cb=progress_cb)
        AnnualReport.objects.filter(pk=report_id).update(status="done", progress=100)
    except Exception as e:
        AnnualReport.objects.filter(pk=report_id).update(status="error", analysis_error=str(e))
        raise




# --------------------- REPORT TASK ---------------------
@shared_task(bind=True, queue="heavy_queue")
def generate_report_task(self, report_id: int):
    AnnualReport.objects.filter(pk=report_id).update(
        report_status="report_processing",
        report_progress=0,
        report_error="",
    )

    last = {"pct": -1, "status": ""}

    def progress_cb(pct: int, status: str):
        if pct == last["pct"] and status == last["status"]:
            return
        AnnualReport.objects.filter(pk=report_id).update(
            report_progress=int(pct),
            report_status=status,
            report_error="",
        )
        last["pct"] = int(pct)
        last["status"] = status

    try:
        generate_report(report_id=report_id, progress_cb=progress_cb)
        AnnualReport.objects.filter(pk=report_id).update(
            report_status="report_done",
            report_progress=100,
            report_generated_at=timezone.now(),
        )
    except Exception as e:
        AnnualReport.objects.filter(pk=report_id).update(
            report_status="report_error",
            report_error=str(e),
        )
        raise