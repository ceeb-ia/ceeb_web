"""Finalize a componentized resource-solver run when all components are solved."""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from calendaritzacions.django.services.component_tasks import _finalize_run_if_components_complete


class Command(BaseCommand):
    help = "Merge successful resource-solver component attempts and write the final Excel."

    def add_arguments(self, parser):
        parser.add_argument("run_id", type=int)

    def handle(self, *args, **options):
        run_id = int(options["run_id"])
        if not _finalize_run_if_components_complete(run_id):
            raise CommandError("Run is not ready to merge, or merge failed. Check component statuses and run logs.")
        self.stdout.write(self.style.SUCCESS(f"merged resource components for run {run_id}"))
