"""Prepare reruns for persistent resource-solver components."""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from calendaritzacions.django.services.component_recovery import (
    ComponentRecoveryUnavailable,
    prepare_component_rerun,
    select_components_for_rerun,
)


class Command(BaseCommand):
    help = "Create a new active attempt for one or more resource-solver components."

    def add_arguments(self, parser):
        parser.add_argument("run_id", type=int)
        parser.add_argument("component_id", nargs="?")
        parser.add_argument("--failed", action="store_true", help="Rerun active components currently in error.")
        parser.add_argument("--stale", action="store_true", help="Rerun active components currently stale.")
        parser.add_argument("--all", action="store_true", dest="all_components", help="Rerun all active components.")
        parser.add_argument(
            "--enqueue",
            action="store_true",
            help="Call the injectable enqueue hook when available. No Celery task is wired by default.",
        )

    def handle(self, *args, **options):
        run_id = options["run_id"]
        component_id = options["component_id"]
        bulk = options["failed"] or options["stale"] or options["all_components"]
        if component_id and bulk:
            raise CommandError("Use either component_id or --failed/--stale/--all, not both.")
        if not component_id and not bulk:
            raise CommandError("Pass component_id or one of --failed, --stale, --all.")

        enqueue_component = _load_enqueue_hook() if options["enqueue"] else None
        try:
            if component_id:
                components = [
                    prepare_component_rerun(
                        run_id=run_id,
                        component_id=component_id,
                        enqueue_component=enqueue_component,
                    )
                ]
            else:
                selected = select_components_for_rerun(
                    run_id=run_id,
                    failed=options["failed"],
                    stale=options["stale"],
                    all_components=options["all_components"],
                )
                components = [
                    prepare_component_rerun(
                        run_id=run_id,
                        component_id=component.component_id,
                        enqueue_component=enqueue_component,
                    )
                    for component in selected
                ]
        except ComponentRecoveryUnavailable as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(self.style.SUCCESS(f"prepared reruns: {len(components)}"))
        for component in components:
            self.stdout.write(
                f"{component.component_id} attempt={component.attempt} status={component.status}"
            )


def _load_enqueue_hook():
    try:
        from calendaritzacions.django.services.component_tasks import enqueue_component
    except ImportError:
        return None
    return enqueue_component
