from django.core.management.base import BaseCommand

from ...services.inscripcions.baseline import (
    DEFAULT_BENCHMARK_SEED,
    BENCHMARK_DATASET_SPECS,
    BENCHMARK_USER_USERNAME,
    ensure_benchmark_user,
    ensure_benchmark_datasets,
    get_dataset_names,
)


class Command(BaseCommand):
    help = "Genera datasets sintetics per la baseline local d'inscripcions."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dataset",
            default="all",
            choices=["small", "medium", "large", "all"],
            help="Dataset o conjunt de datasets a generar.",
        )
        parser.add_argument(
            "--replace",
            action="store_true",
            help="Recrea els datasets benchmark si ja existeixen.",
        )
        parser.add_argument(
            "--seed",
            type=int,
            default=DEFAULT_BENCHMARK_SEED,
            help="Seed deterministic per a la generacio.",
        )

    def handle(self, *args, **options):
        dataset_names = get_dataset_names(options["dataset"])
        replace = bool(options["replace"])
        seed = int(options["seed"] or DEFAULT_BENCHMARK_SEED)

        benchmark_user = ensure_benchmark_user()
        competicions = ensure_benchmark_datasets(dataset_names, replace=replace, seed=seed)

        self.stdout.write("Benchmark datasets generated")
        self.stdout.write(f"user: {BENCHMARK_USER_USERNAME}")
        self.stdout.write(f"seed: {seed}")
        for competicio in competicions:
            dataset_name = str(competicio.nom).replace("__bench_inscripcions_", "").replace("__", "")
            size = BENCHMARK_DATASET_SPECS.get(dataset_name, {}).get("size")
            self.stdout.write(
                f"- {competicio.nom}: size={size} user={benchmark_user.username}"
            )
