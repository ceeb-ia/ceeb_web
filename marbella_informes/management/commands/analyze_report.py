from __future__ import annotations

import os
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings

from ...services.analysis import run_analysis


class Command(BaseCommand):
    help = "Executa l'anàlisi d'un AnnualReport des de consola (ideal per fer proves)."

    def add_arguments(self, parser):
        parser.add_argument("--report-id", type=int, required=True, help="PK de l'AnnualReport")
        parser.add_argument("--dry-run", action="store_true", help="No persisteix resultats al model (per defecte).")
        parser.add_argument("--persist", action="store_true", help="Persisteix resultats al model (si està suportat).")
        parser.add_argument("--out-dir", type=str, default="", help="Directori ABSOLUT per escriure artefactes (opcional).")
        parser.add_argument("--quiet", action="store_true", help="No imprimeix informació.")

    def handle(self, *args, **options):
        report_id = options["report_id"]
        dry_run = options["dry_run"]
        persist = options["persist"]
        quiet = options["quiet"]
        out_dir = (options["out_dir"] or "").strip()

        if persist and dry_run:
            raise CommandError("No pots usar --persist i --dry-run a la vegada.")

        # per defecte: dry run
        if not persist and not dry_run:
            dry_run = True

        out_dir_abs = None
        if out_dir:
            # si passes out-dir, recomanat que sigui absolut
            if not os.path.isabs(out_dir):
                raise CommandError("--out-dir ha de ser un path ABSOLUT")
            out_dir_abs = out_dir

        try:
            result = run_analysis(
                report_id,
                persist=persist,
                out_dir=out_dir_abs,
                verbose=not quiet,
            )
        except Exception as e:
            raise CommandError(f"Error executant l'anàlisi: {e}")

        if not quiet:
            self.stdout.write(self.style.SUCCESS("Anàlisi executada."))
            self.stdout.write(f"Run dir (MEDIA rel): {result.artifacts.run_dir}")
            self.stdout.write(f"KPIs: {result.artifacts.kpis_path}")
            self.stdout.write(f"Warnings: {result.artifacts.warnings_path}")
            for p in result.artifacts.plots:
                self.stdout.write(f"Plot: {p}")

            if result.warnings:
                self.stdout.write(self.style.WARNING("Warnings:"))
                for w in result.warnings[:50]:
                    self.stdout.write(f" - {w}")
