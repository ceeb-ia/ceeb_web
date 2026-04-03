from django.core.management.base import BaseCommand

from ...models import Competicio, EquipContext, Inscripcio, InscripcioEquipAssignacio
from ...services.equip_contexts import NATIVE_EQUIP_CONTEXT_CODE


class Command(BaseCommand):
    help = (
        "Audita l'estat legacy del context base d'equips. "
        "Reporta inscripcions amb Inscripcio.equip sense assignacio native, divergencies i competicions sense context native."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--competicio-id",
            type=int,
            dest="competicio_id",
            default=None,
            help="Limita l'auditoria a una competicio concreta.",
        )
        parser.add_argument(
            "--sample-limit",
            type=int,
            dest="sample_limit",
            default=10,
            help="Maxim d'exemples per categoria al report.",
        )

    def handle(self, *args, **options):
        # This command intentionally stays side-effect free. The runtime repairs
        # the native context in functional flows; the audit reads persisted
        # state as-is.
        competicio_id = options.get("competicio_id")
        sample_limit = max(1, int(options.get("sample_limit") or 10))

        competicions_qs = Competicio.objects.order_by("id")
        if competicio_id:
            competicions_qs = competicions_qs.filter(id=competicio_id)
        competicions = list(competicions_qs.only("id", "nom"))

        native_ctx_by_comp = {
            row.competicio_id: row
            for row in EquipContext.objects
            .filter(competicio__in=competicions, code=NATIVE_EQUIP_CONTEXT_CODE)
            .only("id", "competicio_id", "code")
        }
        legacy_rows_by_comp = {}
        for row in (
            Inscripcio.objects
            .filter(competicio__in=competicions)
            .exclude(equip_id__isnull=True)
            .order_by("competicio_id", "id")
            .values("id", "competicio_id", "nom_i_cognoms", "equip_id")
        ):
            legacy_rows_by_comp.setdefault(int(row["competicio_id"]), []).append(row)

        native_assign_rows_by_comp = {}
        native_ctx_ids = [int(ctx.id) for ctx in native_ctx_by_comp.values()]
        if native_ctx_ids:
            for row in (
                InscripcioEquipAssignacio.objects
                .filter(context_id__in=native_ctx_ids)
                .order_by("competicio_id", "inscripcio_id")
                .values("competicio_id", "inscripcio_id", "equip_id")
            ):
                native_assign_rows_by_comp.setdefault(int(row["competicio_id"]), {})[int(row["inscripcio_id"])] = int(row["equip_id"])

        missing_native_contexts = []
        orphan_legacy_rows = []
        divergent_rows = []

        for competicio in competicions:
            comp_id = int(competicio.id)
            native_ctx = native_ctx_by_comp.get(comp_id)
            if native_ctx is None:
                missing_native_contexts.append(
                    {
                        "competicio_id": comp_id,
                        "competicio_nom": str(competicio.nom or "").strip(),
                    }
                )

            native_assign_map = native_assign_rows_by_comp.get(comp_id, {})
            for row in legacy_rows_by_comp.get(comp_id, []):
                ins_id = int(row["id"])
                legacy_equip_id = int(row["equip_id"])
                native_equip_id = native_assign_map.get(ins_id)
                example = {
                    "competicio_id": comp_id,
                    "competicio_nom": str(competicio.nom or "").strip(),
                    "inscripcio_id": ins_id,
                    "inscripcio_nom": str(row.get("nom_i_cognoms") or "").strip(),
                    "legacy_equip_id": legacy_equip_id,
                }
                if native_equip_id is None:
                    orphan_legacy_rows.append(example)
                    continue
                if native_equip_id != legacy_equip_id:
                    divergent_rows.append(
                        {
                            **example,
                            "native_equip_id": native_equip_id,
                        }
                    )

        self.stdout.write("Base team context audit")
        self.stdout.write(f"competitions_scanned: {len(competicions)}")
        self.stdout.write(f"competitions_without_native_context: {len(missing_native_contexts)}")
        self.stdout.write(f"legacy_team_without_native_assignment: {len(orphan_legacy_rows)}")
        self.stdout.write(f"legacy_native_divergences: {len(divergent_rows)}")

        self._write_examples(
            "Competitions without native context",
            missing_native_contexts,
            sample_limit,
            ("competicio_id", "competicio_nom"),
        )
        self._write_examples(
            "Legacy team without native assignment",
            orphan_legacy_rows,
            sample_limit,
            ("competicio_id", "competicio_nom", "inscripcio_id", "inscripcio_nom", "legacy_equip_id"),
        )
        self._write_examples(
            "Legacy/native divergences",
            divergent_rows,
            sample_limit,
            ("competicio_id", "competicio_nom", "inscripcio_id", "inscripcio_nom", "legacy_equip_id", "native_equip_id"),
        )

    def _write_examples(self, title, rows, limit, keys):
        self.stdout.write("")
        self.stdout.write(f"{title}: {len(rows)}")
        if not rows:
            return
        for row in rows[:limit]:
            parts = [f"{key}={row.get(key)}" for key in keys]
            self.stdout.write(f"  - {' | '.join(parts)}")
