import os
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from ...models_scoring import ScoreEntryVideo, ScoreEntryVideoEvent


class Command(BaseCommand):
    help = "Delete old judge videos according to retention policy."

    def add_arguments(self, parser):
        parser.add_argument(
            "--older-than-days",
            type=int,
            default=int(os.getenv("JUDGE_VIDEO_RETENTION_DAYS", "60")),
            help="Delete rows older than this number of days (0 disables cleanup).",
        )
        parser.add_argument(
            "--status",
            choices=["all", "ready", "failed", "pending"],
            default="all",
            help="Optional status filter before deletion.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show candidates without deleting files/rows.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=200,
            help="Chunk size for queryset iteration.",
        )

    def handle(self, *args, **options):
        older_than_days = int(options["older_than_days"])
        status_filter = options["status"]
        dry_run = bool(options["dry_run"])
        batch_size = max(1, int(options["batch_size"]))

        if older_than_days <= 0:
            self.stdout.write(self.style.WARNING("Cleanup disabled: older-than-days <= 0"))
            return

        cutoff = timezone.now() - timedelta(days=older_than_days)
        qs = ScoreEntryVideo.objects.filter(created_at__lt=cutoff).select_related(
            "score_entry",
            "score_entry__competicio",
            "score_entry__inscripcio",
            "score_entry__comp_aparell",
            "judge_token",
        )
        if status_filter != "all":
            qs = qs.filter(status=status_filter)

        total = qs.count()
        self.stdout.write(f"Candidates: {total} (cutoff={cutoff.isoformat()}, status={status_filter})")
        if total == 0:
            return

        deleted = 0
        for video in qs.iterator(chunk_size=batch_size):
            if dry_run:
                self.stdout.write(
                    f"[DRY] id={video.id} score={video.score_entry_id} status={video.status} file={video.video_file.name if video.video_file else ''}"
                )
                continue

            with transaction.atomic():
                file_name = video.video_file.name if video.video_file else ""
                score_entry = video.score_entry
                competicio = score_entry.competicio if score_entry else None
                inscripcio = score_entry.inscripcio if score_entry else None
                comp_aparell = score_entry.comp_aparell if score_entry else None

                if score_entry and competicio and inscripcio and comp_aparell:
                    ScoreEntryVideoEvent.objects.create(
                        action=ScoreEntryVideoEvent.Action.DELETE,
                        ok=True,
                        http_status=200,
                        detail="retention_cleanup",
                        payload={"cleanup": True, "deleted_path": file_name},
                        competicio=competicio,
                        inscripcio=inscripcio,
                        comp_aparell=comp_aparell,
                        score_entry=score_entry,
                        video=video,
                        judge_token=video.judge_token,
                    )

                if video.video_file:
                    video.video_file.delete(save=False)
                video.delete()
                deleted += 1

        if dry_run:
            self.stdout.write(self.style.SUCCESS("Dry-run finished. No rows deleted."))
        else:
            self.stdout.write(self.style.SUCCESS(f"Deleted videos: {deleted}/{total}"))
