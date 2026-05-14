"""Watchdog command for persistent resource-solver components."""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from calendaritzacions.django.services.component_recovery import (
    ComponentRecoveryUnavailable,
    reconcile_component_runs,
)


class Command(BaseCommand):
    help = "Detect stale resource-solver component runs and optionally requeue them."

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--run", type=int, dest="run_id", help="CalendarizationRun id to reconcile.")
        group.add_argument("--all-running", action="store_true", help="Reconcile all running component runs.")
        parser.add_argument("--stale-after-minutes", type=int, default=30)
        parser.add_argument("--max-attempts", type=int, default=3)
        parser.add_argument(
            "--enqueue",
            action="store_true",
            help="Call the injectable enqueue hook when available. No Celery task is wired by default.",
        )

    def handle(self, *args, **options):
        enqueue_component = _load_enqueue_hook() if options["enqueue"] else None
        try:
            result = reconcile_component_runs(
                run_id=options["run_id"],
                all_running=options["all_running"],
                stale_after_minutes=options["stale_after_minutes"],
                max_attempts=options["max_attempts"],
                enqueue_component=enqueue_component,
            )
        except ComponentRecoveryUnavailable as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                "reconcile complete: "
                f"stale={len(result.stale_marked)} "
                f"requeued={len(result.requeued)} "
                f"errors={len(result.marked_error)}"
            )
        )
        if result.manifest_path:
            self.stdout.write(f"manifest: {result.manifest_path}")


def _load_enqueue_hook():
    try:
        from calendaritzacions.django.services.component_tasks import enqueue_component
    except ImportError:
        return None
    return enqueue_component
