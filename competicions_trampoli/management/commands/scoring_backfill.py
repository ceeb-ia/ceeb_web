# management/commands/scoring_backfill.py
from django.core.management.base import BaseCommand
from django.db import transaction

from ...models_trampoli import CompeticioAparell, TrampoliConfiguracio
from ...models_scoring import ScoringSchema


def build_default_schema_for_comp_aparell(comp_aparell: CompeticioAparell, cfg: TrampoliConfiguracio | None) -> dict:
    # Defaults “trampolí-like” basats en el que tens ara
    n_judges = int(getattr(cfg, "nombre_jutges_execucio", 3) or 3) if cfg else 3
    n_valid = int(getattr(cfg, "nombre_notes_valides_execucio", n_judges) or n_judges) if cfg else n_judges
    criteri = str(getattr(cfg, "criteri_execucio", "totes") or "totes") if cfg else "totes"

    n_elements = int(getattr(comp_aparell, "nombre_elements", 11) or 11)

    # Si l’aparell està en mode manual, fem un field list per jutge; si no, fem matrix.
    mode = getattr(comp_aparell, "mode_execucio", "salts") or "salts"

    fields = []
    computed = []

    if getattr(comp_aparell, "te_execucio", True):
        if mode == "manual":
            fields.append({
                "code": "E_manual",
                "label": "Execució (manual)",
                "type": "list",
                "shape": "judge",
                "decimals": 3,
                "min": 0
            })
            computed.append({
                "code": "E_total",
                "label": "Execució total",
                "type": "number",
                "formula": "select_sum(E_manual, params['n_valid'], params['criteria'])"
            })
        else:
            fields.append({
                "code": "E",
                "label": "Execució",
                "type": "matrix",
                "shape": "judge_x_element",
                "decimals": 0,
                "min": 0,
                "max": 10,
                "with_crash": True
            })
            # crash es normalitza automàticament si with_crash=True
            computed.append({
                "code": "E_j",
                "label": "Execució per jutge",
                "type": "list",
                "formula": "exec_by_judge(E, crash, params)"
            })
            computed.append({
                "code": "E_total",
                "label": "Execució total",
                "type": "number",
                "formula": "select_sum(E_j, params['n_valid'], params['criteria'])"
            })

    if getattr(comp_aparell, "te_dificultat", True):
        fields.append({"code": "DD", "label": "Dificultat", "type": "number", "decimals": 3})
    if getattr(comp_aparell, "te_tof", True):
        fields.append({"code": "TOF", "label": "TOF", "type": "number", "decimals": 3})
    if getattr(comp_aparell, "te_hd", True):
        fields.append({"code": "HD", "label": "HD", "type": "number", "decimals": 3})
    if getattr(comp_aparell, "te_penalitzacio", True):
        fields.append({"code": "P", "label": "Penalització", "type": "number", "decimals": 3})

    # total
    # fórmula tolerant: només suma el que existeix
    parts = []
    if any(c.get("code") == "E_total" for c in computed):
        parts.append("E_total")
    if any(f.get("code") == "DD" for f in fields):
        parts.append("DD")
    if any(f.get("code") == "TOF" for f in fields):
        parts.append("TOF")
    if any(f.get("code") == "HD" for f in fields):
        parts.append("HD")

    subtract = "P" if any(f.get("code") == "P" for f in fields) else None
    formula_total = " + ".join(parts) if parts else "0"
    if subtract:
        formula_total = f"({formula_total}) - {subtract}"

    computed.append({"code": "TOTAL", "label": "Total", "type": "number", "formula": formula_total})

    columns = []
    # ordre suggerit
    if mode == "salts" and any(f.get("code") == "E" for f in fields):
        columns += ["E", "E_total"]
    elif mode == "manual" and any(f.get("code") == "E_manual" for f in fields):
        columns += ["E_manual", "E_total"]
    if any(f.get("code") == "DD" for f in fields): columns.append("DD")
    if any(f.get("code") == "TOF" for f in fields): columns.append("TOF")
    if any(f.get("code") == "HD" for f in fields): columns.append("HD")
    if any(f.get("code") == "P" for f in fields): columns.append("P")
    columns.append("TOTAL")

    schema = {
        "params": {
            "n_judges": n_judges,
            "n_valid": min(n_valid, n_judges),
            "criteria": criteri,
            "n_elements": n_elements,
        },
        "fields": fields,
        "computed": computed,
        "ui": {"columns": columns}
    }
    return schema


class Command(BaseCommand):
    help = "Crea/actualitza ScoringSchema per a tots els CompeticioAparell existents."

    def add_arguments(self, parser):
        parser.add_argument("--overwrite", action="store_true", help="Sobreescriu schemas existents.")

    @transaction.atomic
    def handle(self, *args, **opts):
        overwrite = opts["overwrite"]

        q = CompeticioAparell.objects.select_related("competicio", "aparell").all()
        total = q.count()
        done = 0

        for ca in q:
            cfg = getattr(ca.competicio, "cfg_trampoli", None)
            schema = build_default_schema_for_comp_aparell(ca, cfg)

            obj, created = ScoringSchema.objects.get_or_create(comp_aparell=ca, defaults={"schema": schema})
            if (not created) and overwrite:
                obj.schema = schema
                obj.save()
            done += 1

        self.stdout.write(self.style.SUCCESS(f"OK: {done}/{total} schemas creats/actualitzats."))
