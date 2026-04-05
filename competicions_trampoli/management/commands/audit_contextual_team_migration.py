from django.core.management.base import BaseCommand

from ...models import Competicio, Equip, EquipContext, InscripcioEquipAssignacio
from ...models.classificacions import ClassificacioConfig
from ...models.scoring import TeamCompetitiveSubject
from ...services.teams.equip_contexts import NATIVE_EQUIP_CONTEXT_CODE


class Command(BaseCommand):
    help = (
        "Audita la migracio cap a equips contextuals. "
        "Reporta equips compartits entre contexts, equips sense context inferible i configuracions de classificacio que els referencien."
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
        competicio_id = options.get("competicio_id")
        sample_limit = max(1, int(options.get("sample_limit") or 10))

        competicions_qs = Competicio.objects.order_by("id")
        if competicio_id:
            competicions_qs = competicions_qs.filter(id=competicio_id)
        competicions = list(competicions_qs.only("id", "nom"))
        competition_ids = [int(c.id) for c in competicions]

        contexts_by_comp = {}
        for ctx in EquipContext.objects.filter(competicio_id__in=competition_ids).only("id", "competicio_id", "code"):
            contexts_by_comp.setdefault(int(ctx.competicio_id), {})[int(ctx.id)] = str(ctx.code or "").strip()

        classificacio_usage = {}
        for cfg in ClassificacioConfig.objects.filter(competicio_id__in=competition_ids).only("id", "competicio_id", "schema"):
            schema = cfg.schema if isinstance(cfg.schema, dict) else {}
            equips_cfg = schema.get("equips") or {}
            manual_rows = equips_cfg.get("particions_manuals") or []
            if not isinstance(manual_rows, list):
                continue
            raw_source = equips_cfg.get("assignment_source") or {}
            mode = str(raw_source.get("mode") or "native").strip().lower()
            context_code = str(raw_source.get("context_code") or "").strip() or NATIVE_EQUIP_CONTEXT_CODE
            if mode == "native":
                context_code = NATIVE_EQUIP_CONTEXT_CODE
            target_context_id = None
            for ctx_id, code in contexts_by_comp.get(int(cfg.competicio_id), {}).items():
                if code == context_code:
                    target_context_id = int(ctx_id)
                    break
            if not target_context_id:
                continue
            for row in manual_rows:
                if not isinstance(row, dict):
                    continue
                for raw_equip_id in (row.get("equip_ids") or []):
                    try:
                        equip_id = int(raw_equip_id)
                    except Exception:
                        continue
                    classificacio_usage.setdefault(equip_id, set()).add(target_context_id)

        shared_equips = []
        contextless_equips = []
        for equip in Equip.objects.filter(competicio_id__in=competition_ids).only("id", "competicio_id", "nom"):
            context_ids = set(
                int(ctx_id)
                for ctx_id in InscripcioEquipAssignacio.objects
                .filter(equip_id=equip.id)
                .values_list("context_id", flat=True)
            )
            context_ids.update(
                int(ctx_id)
                for ctx_id in TeamCompetitiveSubject.objects
                .filter(equip_id=equip.id)
                .values_list("context_id", flat=True)
            )
            context_ids.update(int(ctx_id) for ctx_id in classificacio_usage.get(int(equip.id), set()))
            context_codes = sorted(
                {
                    contexts_by_comp.get(int(equip.competicio_id), {}).get(int(ctx_id), f"id:{ctx_id}")
                    for ctx_id in context_ids
                }
            )
            example = {
                "competicio_id": int(equip.competicio_id),
                "equip_id": int(equip.id),
                "equip_nom": str(equip.nom or "").strip(),
                "contexts": ", ".join(context_codes),
            }
            if not context_ids:
                contextless_equips.append(example)
            elif len(context_ids) > 1:
                shared_equips.append(example)

        missing_native = []
        for competicio in competicions:
            codes = set(contexts_by_comp.get(int(competicio.id), {}).values())
            if NATIVE_EQUIP_CONTEXT_CODE not in codes:
                missing_native.append(
                    {
                        "competicio_id": int(competicio.id),
                        "competicio_nom": str(competicio.nom or "").strip(),
                    }
                )

        self.stdout.write("Contextual team migration audit")
        self.stdout.write(f"competitions_scanned: {len(competicions)}")
        self.stdout.write(f"competitions_without_native_context: {len(missing_native)}")
        self.stdout.write(f"teams_shared_across_contexts: {len(shared_equips)}")
        self.stdout.write(f"teams_without_inferable_context: {len(contextless_equips)}")

        self._write_examples(
            "Competitions without native context",
            missing_native,
            sample_limit,
            ("competicio_id", "competicio_nom"),
        )
        self._write_examples(
            "Teams shared across contexts",
            shared_equips,
            sample_limit,
            ("competicio_id", "equip_id", "equip_nom", "contexts"),
        )
        self._write_examples(
            "Teams without inferable context",
            contextless_equips,
            sample_limit,
            ("competicio_id", "equip_id", "equip_nom"),
        )

    def _write_examples(self, title, rows, limit, keys):
        self.stdout.write("")
        self.stdout.write(f"{title}: {len(rows)}")
        if not rows:
            return
        for row in rows[:limit]:
            self.stdout.write("  - " + " | ".join(f"{key}={row.get(key)}" for key in keys))
