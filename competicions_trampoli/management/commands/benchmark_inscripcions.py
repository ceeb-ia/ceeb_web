import json

from django.core.management.base import BaseCommand, CommandError

from ...services.inscripcions.baseline import (
    build_benchmark_metadata,
    build_markdown_snippet,
    build_output_file_path,
    build_results_payload,
    ensure_benchmark_user,
    format_summary_table,
    get_benchmark_competicio,
    get_dataset_names,
    get_scenario_names,
    run_benchmark_scenario,
    aggregate_benchmark_results,
)


class Command(BaseCommand):
    help = "Executa benchmarks locals backend del modul d'inscripcions."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dataset",
            default="all",
            choices=["small", "medium", "large", "all"],
            help="Dataset o conjunt de datasets a mesurar.",
        )
        parser.add_argument(
            "--scenario",
            default="all",
            choices=[
                "get_list",
                "filter_values",
                "sort_apply",
                "groups_preview",
                "groups_workspace",
                "equips_workspace",
                "media_match_preview",
                "all",
            ],
            help="Escenari o conjunt d'escenaris a mesurar.",
        )
        parser.add_argument("--warmup", type=int, default=1, help="Nombre de passades de warmup per escenari.")
        parser.add_argument("--repeats", type=int, default=5, help="Nombre de passades mesurades per escenari.")
        parser.add_argument(
            "--output-dir",
            default="var/benchmarks/inscripcions",
            help="Directori on guardar l'artefacte JSON.",
        )
        parser.add_argument(
            "--format",
            default="both",
            choices=["table", "json", "both"],
            help="Format de sortida principal per consola.",
        )
        parser.add_argument(
            "--emit-doc-snippet",
            action="store_true",
            help="Imprimeix un snippet Markdown preparat per enganxar al document baseline.",
        )

    def handle(self, *args, **options):
        dataset_names = get_dataset_names(options["dataset"])
        scenario_names = get_scenario_names(options["scenario"])
        warmup = max(0, int(options["warmup"] or 0))
        repeats = max(1, int(options["repeats"] or 1))
        output_dir = options["output_dir"]
        output_format = str(options["format"] or "both").strip().lower()
        emit_doc_snippet = bool(options["emit_doc_snippet"])

        missing = [dataset for dataset in dataset_names if get_benchmark_competicio(dataset) is None]
        if missing:
            raise CommandError(
                "Falten datasets benchmark: {}. Executa primer generate_inscripcions_benchmark_data.".format(
                    ", ".join(missing)
                )
            )

        benchmark_user = ensure_benchmark_user()
        metadata = build_benchmark_metadata(
            datasets=dataset_names,
            scenarios=scenario_names,
            warmup=warmup,
            repeats=repeats,
        )

        raw_results = []
        for dataset in dataset_names:
            for scenario in scenario_names:
                total_runs = warmup + repeats
                for run_index in range(total_runs):
                    is_warmup = run_index < warmup
                    measured = run_benchmark_scenario(
                        dataset=dataset,
                        scenario=scenario,
                        run_index=run_index + 1,
                        is_warmup=is_warmup,
                        benchmark_user=benchmark_user,
                    )
                    raw_results.append(measured)
                    phase = "warmup" if is_warmup else "measured"
                    self.stdout.write(
                        f"[{dataset}:{scenario}] run={run_index + 1}/{total_runs} phase={phase} "
                        f"status={measured['status_code']} elapsed_ms={measured['elapsed_ms']}"
                    )

        summary_rows = aggregate_benchmark_results(raw_results)
        results_payload = build_results_payload(metadata, raw_results, summary_rows)
        output_path = build_output_file_path(output_dir, extension="json")
        output_path.write_text(json.dumps(results_payload, indent=2, ensure_ascii=False), encoding="utf-8")

        if output_format in {"table", "both"}:
            self.stdout.write("")
            self.stdout.write("Summary table")
            self.stdout.write(format_summary_table(summary_rows))
        if output_format in {"json", "both"}:
            self.stdout.write("")
            self.stdout.write(f"json_artifact: {output_path}")

        if emit_doc_snippet:
            self.stdout.write("")
            self.stdout.write(build_markdown_snippet(metadata, summary_rows))
