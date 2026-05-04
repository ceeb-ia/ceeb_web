from __future__ import annotations

from typing import Any

from django.template.loader import render_to_string
from django.utils import timezone
from weasyprint import HTML

from designacions.models import DesignationRun


def render_run_analytics_pdf(run: DesignationRun, analytics: dict[str, Any], base_url: str | None = None) -> bytes:
    html = render_to_string(
        "run_analytics_pdf.html",
        {
            "run": run,
            "analytics": analytics,
            "generated_at": timezone.localtime(),
        },
    )
    return HTML(string=html, base_url=base_url).write_pdf()
