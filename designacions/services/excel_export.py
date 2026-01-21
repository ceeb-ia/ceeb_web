# designacions_app/services/excel_export.py
import pandas as pd

def export_run_to_excel(run, output_path: str):
    rows = []
    qs = run.assignments.select_related("match", "referee").all().order_by("match__code")

    for a in qs:
        m = a.match
        r = a.referee
        rows.append({
            "Codi": m.code,
            "Club Local": m.club_local or "",
            "Equip local": m.equip_local or "",
            "Equip visitant": m.equip_visitant or "",
            "Lliga": m.lliga or "",
            "Grup": m.group or "",
            "Jornada": m.jornada or "",
            "Modalitat": m.modality or "",
            "Categoria": m.category or "",
            "Subcategoria": m.subcategory or "",
            "Data": m.date,
            "Hora": m.hour_raw or "",
            "Domicili": m.domicile or "",
            "Municipi": m.municipality or "",
            "Pista joc": m.venue or "",
            "SubPista joc": m.sub_venue or "",

            "Codi Tutor de Joc": r.code if r else "",
            "Tutor": r.name if r else "",
            "Nivell Tutor": r.level if r else "",
            "Bloquejat": "Sí" if a.locked else "No",
            "Nota": a.note or "",
        })

    df = pd.DataFrame(rows)
    df.to_excel(output_path, index=False, engine="openpyxl")
    return output_path
