# designacions_app/services/map_rebuild.py
import os
import pandas as pd
from django.conf import settings

from ..main_fixed import mapa_assignacions_interactiu
from ..models import Address


def rebuild_run_map(run) -> str | None:
    """
    Regenera el mapa folium del run a partir de BD (Match + Assignment + Address).
    Retorna map_path (relatiu a MEDIA_ROOT) o None si no es pot construir.
    """

    matches = list(run.matches.all().select_related())
    if not matches:
        run.map_path = None
        run.save(update_fields=["map_path"])
        return None

    # df_partits_geo: el mapa espera lat/lon + adreca + Codi + altres camps opcionals
    rows_p = []
    for m in matches:
        adreca = f"{(m.domicile or '').strip()}, {(m.municipality or '').strip()}".strip().strip(",")
        addr = Address.objects.filter(text=adreca).first() if adreca else None

        rows_p.append({
            "Codi": m.code,
            "adreca": adreca or None,
            "lat": getattr(addr, "lat", None),
            "lon": getattr(addr, "lon", None),
            "Hora": m.hour_raw,
            "Data": m.date,
            "Pista": m.venue,
            "Club Local": m.club_local,
            "Club Visitant": m.equip_visitant,  # si tens camp específic, canvia-ho
            "Categoria": m.category,
            "Modalitat": m.modality,
        })

    df_partits_geo = pd.DataFrame(rows_p)
    # Necessitem coords per dibuixar
    if df_partits_geo[["lat", "lon"]].dropna().empty:
        run.map_path = None
        run.save(update_fields=["map_path"])
        return None

    # df_assignacions: només assignats (si està buit, mapa surt però tot gris “sense assignar”)
    asgs = list(run.assignments.select_related("match", "referee").all())
    rows_a = []
    for a in asgs:
        if not a.referee:
            continue
        rows_a.append({
            "Codi Partit": a.match.code,
            "Tutor Codi": a.referee.code,
            "Tutor": a.referee.name,
            "Partit Hora": a.match.hour_raw,
            "Data Partit": a.match.date,
        })
    df_assignacions = pd.DataFrame(rows_a)

    rel_dir = os.path.join("designacions", "maps")
    abs_dir = os.path.join(settings.MEDIA_ROOT, rel_dir)
    os.makedirs(abs_dir, exist_ok=True)

    rel_path = os.path.join(rel_dir, f"run_{run.id}.html")
    abs_path = os.path.join(settings.MEDIA_ROOT, rel_path)

    # Genera i guarda HTML
    mapa_assignacions_interactiu(
        df_partits_geo=df_partits_geo,
        df_assignacions=df_assignacions if not df_assignacions.empty else pd.DataFrame(columns=["Codi Partit"]),
        lat_col="lat",
        lon_col="lon",
        seu_col="adreca",
        codi_partit_col="Codi",
        codi_assign_col="Codi Partit",
        tutor_codi_col="Tutor Codi",
        tutor_nom_col="Tutor",
        hora_col="Partit Hora",
        data_col="Data Partit",
        out_html=abs_path,
        mostra_totes_les_seus=True,
    )

    run.map_path = rel_path
    run.save(update_fields=["map_path"])
    return rel_path
