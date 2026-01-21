import asyncio
import pandas as pd
import os
import unicodedata, hashlib
from pandas.api.types import CategoricalDtype
from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from .services.modalitat_map import load_modalitat_map_df
from .consulta_resultats import fetch_ceeb_async, parse_ceeb_xml, xml_to_dataframe
from .geolocate import clusteritza_i_plota, geocodificar
import numpy as np
import folium
from folium.plugins import MarkerCluster
from folium.features import DivIcon
from scipy.optimize import linear_sum_assignment
import sys
from datetime import datetime, timedelta
from logs import _write_job, _read_job, push_log
from asgiref.sync import async_to_sync
from django.db import transaction
from django.utils.dateparse import parse_date




RESULTS_DIR = os.getenv('MEDIA_ROOT', '/data/media/')
MEDIA_URL = os.getenv('MEDIA_URL', '/media/')
MEDIA_ROOT = os.getenv('MEDIA_ROOT', '/data/media/')
os.makedirs(RESULTS_DIR, exist_ok=True)
file_path_dispo =  MEDIA_ROOT + 'designacions/' + 'dispos_tutors_23_01.xlsx'
file_path_partits = MEDIA_ROOT + 'designacions/' + 'partits_23_01.xlsx'

def _parse_times(s):
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            parsed = pd.to_datetime(s, format=fmt, errors="coerce")
            if not parsed.isna().all():
                return parsed.dt.time
        except Exception:
            pass
    # fallback: infer per element (pandas infers mixed formats)
    return pd.to_datetime(s, errors="coerce").dt.time


def _color_per_tutor(tutor_codi) -> str:
    if pd.isna(tutor_codi) or str(tutor_codi).strip() == "":
        return "#808080"  # gris (sense assignar)
    h = hashlib.md5(str(tutor_codi).encode("utf-8")).hexdigest()
    return "#" + h[:6]

def _color_estat_seu(n_assigned: int, n_unassigned: int) -> str:
    if n_unassigned > 0 and n_assigned == 0:
        return "#d62728"  # vermell
    if n_unassigned > 0:
        return "#ff7f0e"  # taronja
    return "#2ca02c"      # verd

def mapa_assignacions_interactiu(
    df_partits_geo: pd.DataFrame,
    df_assignacions: pd.DataFrame,
    lat_col="lat",
    lon_col="lon",
    seu_col="adreca",          # domicili + municipi
    codi_partit_col="Codi",    # codi del partit al df_partits
    codi_assign_col="Codi Partit",  # codi del partit al df_assignacions
    tutor_codi_col="Tutor Codi",
    tutor_nom_col="Tutor",
    hora_col="Partit Hora",
    data_col="Data Partit",    # opcional
    out_html="mapa_assignacions.html",
    zoom_start=12,
    jitter_m=12,
    mostra_totes_les_seus=False  # si False, al resum només es veuen seus amb no assignats
):
    # --- Merge partits + assignació ---
    dfP = df_partits_geo.copy()
    dfA = df_assignacions.copy()

    # Normalitza per poder fer merge
    if codi_assign_col in dfA.columns and codi_partit_col in dfP.columns:
        dfA = dfA.rename(columns={codi_assign_col: codi_partit_col})

    merged = dfP.merge(dfA, on=codi_partit_col, how="left", suffixes=("", "_asgn"))

    # Columnes unificades per data/hora: així els partits SENSE ASSIGNAR també conserven Hora/Data del df_partits
    if hora_col in merged.columns and "Hora" in merged.columns:
        merged["__hora_mapa"] = merged[hora_col].where(merged[hora_col].notna(), merged["Hora"])
    elif hora_col in merged.columns:
        merged["__hora_mapa"] = merged[hora_col]
    elif "Hora" in merged.columns:
        merged["__hora_mapa"] = merged["Hora"]
    else:
        merged["__hora_mapa"] = np.nan

    if data_col in merged.columns and "Data" in merged.columns:
        merged["__data_mapa"] = merged[data_col].where(merged[data_col].notna(), merged["Data"])
    elif data_col in merged.columns:
        merged["__data_mapa"] = merged[data_col]
    elif "Data" in merged.columns:
        merged["__data_mapa"] = merged["Data"]
    else:
        merged["__data_mapa"] = np.nan

    # Estat assignació
    merged["assignat"] = merged[tutor_codi_col].notna() & (merged[tutor_codi_col].astype(str).str.strip() != "")

    # Validació coords
    d_ok = merged.dropna(subset=[lat_col, lon_col]).copy()
    if d_ok.empty:
        raise ValueError("No hi ha partits amb coordenades (lat/lon) per dibuixar el mapa.")

    center = [d_ok[lat_col].astype(float).mean(), d_ok[lon_col].astype(float).mean()]
    m = folium.Map(location=center, zoom_start=zoom_start, control_scale=True)

    # Apply _parse_times to the time column (returns a Series) instead of
    # applying row-wise which returned a Series per row and caused the
    # 'multiple columns to single column' ValueError.
    d_ok["_slot"] = _parse_times(d_ok["__hora_mapa"])

    # agrupa per seu
    resum = (
        d_ok.groupby(seu_col, as_index=False)
        .agg(
            lat=(lat_col, "first"),
            lon=(lon_col, "first"),
            n_partits=(codi_partit_col, "count"),
            n_assignats=("assignat", "sum"),
        )
    )
    resum["n_no_assignats"] = resum["n_partits"] - resum["n_assignats"]

    # llista d’hores (o data+hora) només dels no assignats (utilitzem _parse_times per formatar correctament)
    no_asg = d_ok[~d_ok["assignat"]].copy()
    
    hores_no_asg = (
        no_asg.groupby(seu_col)["_slot"]
        .apply(lambda s: sorted([x for x in s.dropna().tolist() if str(x).strip() != ""]))
        .to_dict()
    )

    # --- CAPA 1: RESUM PER SEU (ALERTES) + HORES NO ASSIGNATS ---
    # mostra només seus amb incidències (o totes)
    fg_seus_incidencies = folium.FeatureGroup(
        name="Seus amb incidències (no assignats)",
        show=True
    )

    fg_seus_assignades = folium.FeatureGroup(
        name="Seus completament assignades",
        show=False
    )

    for _, r in resum.iterrows():
        nA = int(r["n_assignats"])
        nN = int(r["n_no_assignats"])
        color = _color_estat_seu(nA, nN)

        hores = hores_no_asg.get(r[seu_col], [])
        hores_txt = "<br>".join([f"• {h}" for h in hores]) if hores else "—"

        tooltip_html = (
            f"<b>{r[seu_col]}</b><br>"
            f"Assignats: {nA} / {int(r['n_partits'])}<br>"
            f"<b>No assignats: {nN}</b>"
        )

        popup_html = (
            f"<b>{r[seu_col]}</b><br>"
            f"Assignats: {nA} / {int(r['n_partits'])}<br>"
            f"<b>No assignats: {nN}</b><br><br>"
            f"<b>Hores no assignades:</b><br>{hores_txt}"
        )

        marker = folium.CircleMarker(
            location=[float(r["lat"]), float(r["lon"])],
            radius=10 if nN > 0 else 7,
            color=color,
            fill=True,
            fill_color=color,
            fill_opacity=0.85,
            tooltip=folium.Tooltip(tooltip_html, sticky=True),
            popup=folium.Popup(popup_html, max_width=500),
        )

        if nN > 0:
            marker.add_to(fg_seus_incidencies)
        else:
            marker.add_to(fg_seus_assignades)

        

    # --- CAPA 2: DETALL PER PARTIT (colors per tutor + grisos) ---
    fg_assigned = folium.FeatureGroup(name="Detall: Assignats (per tutor)", show=False)
    fg_unassigned = folium.FeatureGroup(name="Detall: Sense assignar", show=False)

    lat0 = np.radians(center[0])
    m_per_deg_lat = 111_320.0
    m_per_deg_lon = 111_320.0 * np.cos(lat0)
    rng = np.random.default_rng(42)

    for _, rr in d_ok.iterrows():
        lat = float(rr[lat_col])
        lon = float(rr[lon_col])

        dx = rng.uniform(-jitter_m, jitter_m)
        dy = rng.uniform(-jitter_m, jitter_m)
        lat_j = lat + (dy / m_per_deg_lat)
        lon_j = lon + (dx / m_per_deg_lon)

        assignat = bool(rr["assignat"])
        tutor = rr.get(tutor_codi_col, None)
        color = _color_per_tutor(tutor) if assignat else "#808080"

        # Info per tooltip/popup
        txt = []
        if "__data_mapa" in rr and pd.notna(rr["__data_mapa"]): txt.append(f"Data: {rr['__data_mapa']}")
        if "__hora_mapa" in rr and pd.notna(rr["__hora_mapa"]): txt.append(f"Hora: {rr['__hora_mapa']}")
        if "Pista" in rr and pd.notna(rr["Pista"]): txt.append(f"Pista: {rr['Pista']}")
        if "Club Local" in rr and pd.notna(rr["Club Local"]): txt.append(f"Local: {rr['Club Local']}")
        if "Club Visitant" in rr and pd.notna(rr["Club Visitant"]): txt.append(f"Visitant: {rr['Club Visitant']}")
        if "Categoria" in rr and pd.notna(rr["Categoria"]): txt.append(f"Categoria: {rr['Categoria']}")
        if "Modalitat" in rr and pd.notna(rr["Modalitat"]): txt.append(f"Modalitat: {rr['Modalitat']}")
        if assignat:
            txt.append(f"Tutor: {rr.get(tutor_codi_col,'')} - {rr.get(tutor_nom_col,'')}")
        else:
            txt.append("Tutor: SENSE ASSIGNAR")

        if len(txt) == 0:
                        txt.append("(sense informació)")

        tooltip = folium.Tooltip("<br>".join(txt), sticky=True)
        popup = folium.Popup("<br>".join(txt), max_width=450)

        marker = folium.CircleMarker(
            location=[lat_j, lon_j],
            radius=5 if assignat else 6,
            color=color,
            fill=True,
            fill_color=color,
            fill_opacity=0.9 if assignat else 0.6,
            tooltip=tooltip,
            popup=popup
        )

        if assignat:
            marker.add_to(fg_assigned)
        else:
            marker.add_to(fg_unassigned)

    fg_assigned.add_to(m)
    fg_unassigned.add_to(m)
    fg_seus_incidencies.add_to(m)
    fg_seus_assignades.add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)
    m.save(out_html)
    return out_html


def _normalize_entity_name(name: str) -> str:
    # treu variacions d’accents/espais/majús-minus
    s = unicodedata.normalize('NFKC', str(name)).casefold().strip()
    s = " ".join(s.split())  # col·lapsa espais múltiples
    return s



def read_excel_file(path):
    """Read an Excel file using an engine inferred from the extension.

    - `.xls` -> `xlrd` (requires `xlrd==1.2.0`)
    - others (xlsx, xlsm, etc.) -> `openpyxl`
    """
    _, ext = os.path.splitext(path)
    ext = ext.lower()
    if ext == ".xlsx":
        return pd.read_excel(path, engine="openpyxl")
    else:
        raise ValueError(f"Unsupported file extension '{ext}' for file '{path}'.")


def persist_assignacions_to_db(
    *,
    run_id: int,
    df_partits: pd.DataFrame,
    df_dispos: pd.DataFrame,
    df_assignacions: pd.DataFrame,
):
    """
    Desa a BD:
    - Referee (si no existeix)
    - Match (si no existeix) per aquest run
    - Assignment (upsert) per Match

    IMPORTANT:
    - No toca assignacions locked=True.
    - Manté referee=None si el partit queda sense assignar.
    """
    from .models import DesignationRun, Referee, Match, Assignment

    run = DesignationRun.objects.get(id=run_id)

    # Mapa ràpid: referee_code -> (nom complet)
    # df_dispos té 'Codi Tutor de Joc', 'Nom', 'Cognoms'
    dispo_name = {}
    for _, r in df_dispos.iterrows():
        c = str(r.get("Codi Tutor de Joc", "")).strip()
        if not c:
            continue
        n = str(r.get("Nom", "")).strip()
        cg = str(r.get("Cognoms", "")).strip()
        full = (n + " " + cg).strip() or c
        dispo_name[c] = full

    # Mapa assignacions: codi_partit -> referee_code
    # df_assignacions té 'Codi Partit' i 'Tutor Codi'
    assigned_map = {}
    if df_assignacions is not None and not df_assignacions.empty:
        for _, r in df_assignacions.iterrows():
            codi_partit = str(r.get("Codi Partit", "")).strip()
            tutor_codi = str(r.get("Tutor Codi", "")).strip()
            if codi_partit:
                assigned_map[codi_partit] = tutor_codi or None

    # Upsert matches + assignments dins transacció
    with transaction.atomic():
        # 1) Assegura que tots els partits existeixen com Match per aquest run
        for _, p in df_partits.iterrows():
            codi = str(p.get("Codi", "")).strip()
            if not codi:
                continue

            # engine_id (hash) si el tens a df_partits['ID']
            engine_id = str(p.get("ID", "")).strip() or None

            # Data pot venir com datetime o string; Match.date és DateField
            d = p.get("Data", None)
            date_val = None
            try:
                if pd.notna(d):
                    if hasattr(d, "date"):
                        date_val = d.date()
                    else:
                        date_val = parse_date(str(d))
            except Exception:
                date_val = None

            Match.objects.update_or_create(
                run=run,
                code=codi,
                defaults={
                    "engine_id": engine_id,
                    "club_local": p.get("Club Local"),
                    "equip_local": p.get("Equip local"),
                    "equip_visitant": p.get("Equip visitant"),
                    "lliga": p.get("Lliga"),
                    "group": p.get("Grup"),
                    "jornada": p.get("Jornada"),
                    "modality": p.get("Modalitat"),
                    "category": p.get("Categoria"),
                    "subcategory": p.get("Subcategoria"),
                    "date": date_val,
                    "hour_raw": str(p.get("Hora", "")).strip() or None,
                    "domicile": p.get("Domicili"),
                    "municipality": p.get("Municipi"),
                    "venue": p.get("Pista joc"),
                    "sub_venue": p.get("SubPista joc"),
                },
            )

        # 2) Upsert assignments (respectant locked)
        matches = {m.code: m for m in Match.objects.filter(run=run)}

        for match_code, match in matches.items():
            tutor_code = assigned_map.get(match_code, None)

            # si no hi ha assignació, deixem referee=None (sense tocar locked)
            asg, _ = Assignment.objects.get_or_create(run=run, match=match)

            if asg.locked:
                continue

            if not tutor_code:
                if asg.referee_id is not None:
                    asg.referee = None
                    asg.save(update_fields=["referee", "updated_at"])
                continue

            ref_name = dispo_name.get(tutor_code, tutor_code)
            ref, _ = Referee.objects.update_or_create(
                code=tutor_code,
                defaults={"name": ref_name, "active": True},
            )

            if asg.referee_id != ref.id:
                asg.referee = ref
                asg.save(update_fields=["referee", "updated_at"])


def main(path_disposicions: str, path_dades: str, task_id: str | None = None, run_id: int | None = None) -> dict:
    """
    Motor d'assignació.

    Canvis vs la versió antiga:
    - map_modalitat_nom surt de BD (DataFrame) i NO d'un CSV
    - geocodificació surt de BD (Address) i NO d'un CSV
    - clusterització es guarda a BD per RUN (AddressCluster)
    """

    # --- Mapping modalitat/categoria (BD) ---
    # IMPORTANT: ha de retornar un DataFrame tipus map_modalitat_nom.csv amb columnes:
    #   "Modalitat", "Nom", "Id Categoria" (mínim)
    map_modalitat_nom = load_modalitat_map_df()

    # ------------ Get paths ------------
    file_abspath_dispo = os.path.abspath(path_disposicions)
    file_abspath_partits = os.path.abspath(path_dades)
    results_abspath = os.path.abspath(RESULTS_DIR)

    df_dispos = read_excel_file(file_abspath_dispo)
    df_partits = read_excel_file(file_abspath_partits)

    # Fem shuffle per evitar biaixos en assignacions
    df_dispos = df_dispos.sample(frac=1, random_state=42).reset_index(drop=True)
    df_partits = df_partits.sample(frac=1, random_state=42).reset_index(drop=True)

    print("\nColumnes partits:", df_partits.columns)
    print("\nColumnes disponibilitats tutors:", df_dispos.columns)
    if task_id:
        async_to_sync(push_log)(task_id, "Llegint els fitxers.", 30)

    def _mk_id(row, tutor: bool = True) -> str:
        if tutor:
            nom = _normalize_entity_name(row.get('Codi Tutor de Joc', ''))
            lliga = _normalize_entity_name(row.get('Nom', ''))
            cat = _normalize_entity_name(row.get('Nivell', ''))
            mod = _normalize_entity_name(row.get('Modalitat', ''))
        else:
            nom = _normalize_entity_name(row.get('Codi', ''))
            lliga = _normalize_entity_name(row.get('Codi Extern Local', ''))
            cat = _normalize_entity_name(row.get('Lliga', ''))
            mod = _normalize_entity_name(row.get('Categoria', ''))

        key = f"{nom}|{lliga}|{cat}|{mod}"
        return hashlib.sha1(key.encode('utf-8')).hexdigest()[:10].upper()

    # Ens quedem només amb llicència tutor
    df_dispos = df_dispos[df_dispos['Categoria'] == "TUTOR/TUTORA DE JOC"].copy()

    categories_dispos = df_dispos['Categoria'].unique()
    if len(categories_dispos) > 1:
        if task_id:
            async_to_sync(push_log)(task_id, f"S'hi han trobat múltiples llicències: {categories_dispos}. Introdueix només la del tutor.", 0)
        raise ValueError(f"S'hi han trobat múltiples llicències a dispos: {categories_dispos}")

    # IDs
    df_dispos['ID'] = df_dispos.apply(_mk_id, axis=1, tutor=True)
    df_dispos.drop_duplicates(subset=['ID'], keep='first', inplace=True)

    df_partits['ID'] = df_partits.apply(_mk_id, axis=1, tutor=False)

    def _report_duplicates(df, name: str):
        dup_mask = df['ID'].duplicated(keep=False)
        if not dup_mask.any():
            print(f"No hi ha IDs duplicats a {name}\n")
            return
        dup_ids = df.loc[dup_mask, 'ID'].unique().tolist()
        if task_id:
            async_to_sync(push_log)(task_id, f"IDs duplicats trobats a {name}: {dup_ids}", 0)
        raise ValueError(f"IDs duplicats trobats a {name} - {dup_ids}")

    _report_duplicates(df_dispos, 'tutors')
    _report_duplicates(df_partits, 'partits')

    # ------------ Filtrat tutors / partits ------------
    codis_a_eliminar = ['TJ PROPI', 'TJ LEXIA', 'CEBLL', 'CEVOSABADELL', 'CELH', 'CEBN']
    df_dispos = df_dispos[~df_dispos['Codi Tutor de Joc'].isin(codis_a_eliminar)].copy()

    grups_a_eliminar = ['FUTBOL 5 SENSE BARRERES JUVENIL MIXT GRUP 06 1a FASE CEEB', 'AMISTÓS FUTBOL 5']
    df_partits = df_partits[~df_partits['Grup'].isin(grups_a_eliminar)].copy()

    if task_id:
        async_to_sync(push_log)(task_id, f"Eliminant codis tutor no vàlids: {codis_a_eliminar}", 40)
        async_to_sync(push_log)(task_id, f"Eliminant grups partit no vàlids: {grups_a_eliminar}", 40)

    # Tutors sense nivell
    if df_dispos['Nivell'].isna().any():
        if task_id:
            async_to_sync(push_log)(task_id, "S'han trobat tutors sense nivell (s'exclouran i es guardaran a revisió).", 0)
        df_revisio_sense_nivell = df_dispos[df_dispos['Nivell'].isna()].copy()
        df_dispos = df_dispos[~df_dispos['Nivell'].isna()].copy()
    else:
        df_revisio_sense_nivell = pd.DataFrame()

    tutor_nivel_order = ['NIVELLA1', 'NIVELLB1', 'NIVELLC1', 'NIVELLD1', 'D']
    nivel_dtype = CategoricalDtype(categories=tutor_nivel_order, ordered=True)
    df_dispos['Nivell'] = df_dispos['Nivell'].astype(nivel_dtype)
    df_dispos = df_dispos.sort_values('Nivell').reset_index(drop=True)

    # ------------ Adreces (geocodificació BD) + clusterització ------------
    df_partits['adreca'] = df_partits['Domicili'].astype(str) + ', ' + df_partits['Municipi'].astype(str)

    from .services.geocoding_db import geocodifica_adreces, addresses_to_df
    from .models import Address, AddressCluster

    adreces_uniques = df_partits["adreca"].unique().tolist()
    addr_objs = geocodifica_adreces(adreces_uniques)  # respecte Nominatim intern
    df_geocodificats = addresses_to_df(addr_objs)

    domicilis_clusteritzats, _, _, _ = clusteritza_i_plota(
        df_geocodificats,
        lat_col="lat",
        lon_col="lon"
    )

    # Guardem clusters per RUN (si run_id ve informat)
    if run_id is not None:
        for _, r in domicilis_clusteritzats.iterrows():
            adreca_txt = str(r.get("adreca", "")).strip()
            if not adreca_txt:
                continue
            addr = Address.objects.filter(text=adreca_txt).first()
            if not addr:
                continue
            cluster_val = r.get("cluster", None)
            cluster_id = None if pd.isna(cluster_val) else int(cluster_val)
            AddressCluster.objects.update_or_create(
                run_id=run_id,
                address=addr,
                defaults={"cluster_id": cluster_id},
            )

    # Enllacem cluster al df_partits
    df_localitzats = pd.merge(df_partits, domicilis_clusteritzats, on='adreca', how='inner')
    df_partits = pd.merge(df_partits, df_localitzats[['ID', 'cluster']], on='ID', how='left')

    # Validació: una adreça no pot tenir múltiples clusters
    discrepancies = []
    for adreca, group in df_partits.groupby('adreca'):
        unique_clusters = group['cluster'].dropna().unique()
        if len(unique_clusters) > 1:
            discrepancies.append((adreca, unique_clusters.tolist()))
    if discrepancies:
        if task_id:
            async_to_sync(push_log)(task_id, "S'han trobat discrepàncies de cluster per adreça (revisa log).", 0)
        raise ValueError(f"Discrepàncies de cluster per adreça: {discrepancies[:5]} ...")

    # ------------ Nivells partits ------------
    partits_nivel_order = ["SÈNIOR", "JÚNIOR", 'JUVENIL', "CADET", "INFANTIL", "PREINFANTIL",
                           "ALEVÍ", "PREALEVÍ", "BENJAMÍ", "PREBENJAMÍ", "MENUDETS", "MENUTS"]
    nivel_dtype_partits = CategoricalDtype(categories=partits_nivel_order, ordered=True)
    df_partits['Categoria'] = df_partits['Categoria'].astype(nivel_dtype_partits)
    df_partits = df_partits.sort_values('Categoria').reset_index(drop=True)

    # ------------ Assignació per modalitats ------------
    modalitats = df_partits['Modalitat'].unique()

    assigned_tutors = []
    assigned_partit_ids = set()
    assigned_tutor_ids = set()

    for modalitat in modalitats:
        print(f"\nProcessant modalitat: {modalitat}")
        if task_id:
            async_to_sync(push_log)(task_id, f"Processant modalitat: {modalitat}", 50)

        # mapping DataFrame per modalitat
        map_modalitat = map_modalitat_nom.loc[map_modalitat_nom['Modalitat'] == modalitat].copy()

        df_partits_modalitat = df_partits[df_partits['Modalitat'] == modalitat].copy()
        df_dispos_modalitat = df_dispos[df_dispos['Modalitat'] == modalitat].copy()

        df_dispos_modalitat.reset_index(drop=True, inplace=True)
        df_partits_modalitat.reset_index(drop=True, inplace=True)

        grups = df_partits_modalitat['Grup'].unique()

        # --- classificacions (actualment desactivades al teu codi original) ---
        for grup in grups:
            if task_id:
                async_to_sync(push_log)(task_id, f"Consultant classificacions per grup: {grup}", 60)

            df_partits_grup = df_partits_modalitat[df_partits_modalitat['Grup'] == grup].copy()
            if len(df_partits_grup['Grup'].unique()) != 1:
                raise ValueError(f"Múltiples grups detectats dins {grup}")

            genere = df_partits_grup["Subcategoria"].iloc[0]
            if genere == "MIXT":
                p5 = "SXMIX"
            elif genere == "FEMENÍ":
                p5 = "SXFEM"
            else:
                raise ValueError(f"Subcategoria desconeguda: {genere}")

            categoria = df_partits_grup["Categoria"].iloc[0]

            # Aquí necessites Id Categoria (p2) per cridar el servei de classificacions
            p2 = map_modalitat[map_modalitat["Nom"] == categoria]
            if p2.empty:
                # si no hi ha mapping, seguim sense posicions
                continue

            # root = asyncio.run(fetch_ceeb_async(str(p2["Id Categoria"].values[0]), p5))
            root = None  # mantenim com al teu codi actual
            if root is None:
                continue

            # parsed = parse_ceeb_xml(root)
            # df_classificacions = xml_to_dataframe(parsed, grup=grup)
            # ...
            # pos_local / pos_visitant actualment desactivat al teu codi

            for _, partit in df_partits_grup.iterrows():
                df_partits_modalitat.loc[df_partits_modalitat['ID'] == partit['ID'], 'Posició Equip Local'] = -1
                df_partits_modalitat.loc[df_partits_modalitat['ID'] == partit['ID'], 'Posició Equip Visitant'] = -1

        # --- agrupació per pista / horari ---
        df_partits_grouped = df_partits_modalitat.groupby(['Pista joc'])

        df_partits_modalitat['Hora'] = _parse_times(df_partits_modalitat['Hora'])
        df_dispos_modalitat['Hora Inici'] = _parse_times(df_dispos_modalitat['Hora Inici'])
        df_dispos_modalitat['Hora Fi'] = _parse_times(df_dispos_modalitat['Hora Fi'])

        final_subgrups = []
        for pista, group in df_partits_grouped:
            group_ordenado = group.sort_values(['Hora'], na_position='last').reset_index(drop=True)
            subgrups = []
            used_rows = set()

            def _crear_subgrups(group_sorted: pd.DataFrame, used_rows: set):
                current_subgroup = []
                previous_time = None
                prev_pista_joc = None
                for idx, row in group_sorted.iterrows():
                    if idx in used_rows:
                        continue
                    current_time = row['Hora']
                    pista_joc = row['Pista joc']
                    if previous_time is None:
                        current_subgroup.append(row)
                        used_rows.add(idx)
                    else:
                        time_diff = (
                            pd.Timestamp.combine(pd.Timestamp.today(), current_time) -
                            pd.Timestamp.combine(pd.Timestamp.today(), previous_time)
                        ).total_seconds() / 60.0

                        if pista_joc != prev_pista_joc:
                            if time_diff >= 75:
                                current_subgroup.append(row)
                                used_rows.add(idx)
                        else:
                            if time_diff >= 60:
                                current_subgroup.append(row)
                                used_rows.add(idx)

                    previous_time = current_time
                    prev_pista_joc = pista_joc

                return current_subgroup

            while len(used_rows) < len(group_ordenado):
                sg = _crear_subgrups(group_ordenado, used_rows)
                if sg:
                    subgrups.append(sg)

            final_subgrups.extend(subgrups)

        # --- fusió subgrups petits (igual que el teu codi) ---
        MAX_PARTITS_SUBGRUP = 3

        def _fusionar_subgrups(subgrups: list) -> list:
            subgrups = sorted(subgrups, key=lambda sg: min(row['Hora'] for row in sg))
            fused = []
            used = set()
            skip_next = False

            for i in range(len(subgrups)):
                if skip_next:
                    skip_next = False
                    fused.append(subgrups[i])
                    used.add(i)
                    continue

                current_sg = subgrups[i]
                if len(current_sg) < MAX_PARTITS_SUBGRUP and i + 1 < len(subgrups):
                    for j in range(i + 1, len(subgrups)):
                        next_sg = subgrups[j]
                        if len(next_sg) + len(current_sg) > MAX_PARTITS_SUBGRUP:
                            continue

                        pista_actual = current_sg[0]['Pista joc']
                        pista_seguent = next_sg[0]['Pista joc']
                        cluster_actual = current_sg[0]['cluster']
                        cluster_seguent = next_sg[0]['cluster']

                        if pd.isna(cluster_actual) or pd.isna(cluster_seguent) or cluster_actual == -1 or cluster_seguent == -1:
                            continue

                        if pista_actual != pista_seguent and cluster_actual == cluster_seguent and j not in used:
                            hora_darrer = max(row['Hora'] for row in current_sg)
                            hora_primer = min(row['Hora'] for row in next_sg)
                            time_diff = (
                                pd.Timestamp.combine(pd.Timestamp.today(), hora_primer) -
                                pd.Timestamp.combine(pd.Timestamp.today(), hora_darrer)
                            ).total_seconds() / 60.0
                            if time_diff >= 75:
                                current_sg.extend(next_sg)
                                used.add(j)
                                skip_next = True
                                break

                    fused.append(current_sg)
                else:
                    fused.append(current_sg)

            return fused

        final_subgrups = _fusionar_subgrups(final_subgrups)

        # --- nivell subgrup ---
        def _subgrup_nivel(subgrup):
            niveles = []
            posicions = []
            for row in subgrup:
                categoria = row['Categoria']
                if pd.isna(categoria):
                    continue
                niveles.append(categoria)
                pos_local = row.get('Posició Equip Local', None)
                pos_visitant = row.get('Posició Equip Visitant', None)
                if pos_local is not None and not pd.isna(pos_local) and pos_visitant is not None and not pd.isna(pos_visitant):
                    posicions.append((pos_local, pos_visitant))

            if not niveles:
                raise ValueError(f"No hi ha categories vàlides al subgrup.")

            suma_posicions_prev = 19
            if posicions:
                suma_posicions_prev = min(p[0] + p[1] for p in posicions)

            pistes_joc = set(r['Pista joc'] for r in subgrup)
            clusters_pistes = set(r['cluster'] for r in subgrup)
            multiple_pistes = len(pistes_joc) > 1

            niveles = pd.Series(niveles, dtype=nivel_dtype_partits)
            return niveles.min(), suma_posicions_prev, multiple_pistes, clusters_pistes

        # --- matriu costos ---
        C = np.zeros((len(df_dispos_modalitat), len(final_subgrups)))

        if task_id:
            async_to_sync(push_log)(task_id, "Assignant tutors...", 80)

        for i, (_, row) in enumerate(df_dispos_modalitat.iterrows()):
            tutor_codi = row['Codi Tutor de Joc']
            tutor_nivel = row['Nivell']
            tutor_modalitat = row['Modalitat']

            for j, subgrup in enumerate(final_subgrups):
                cost = 0
                subgrup_modalitat = subgrup[0]['Modalitat']
                if tutor_modalitat != subgrup_modalitat:
                    raise ValueError(f"Modalitat tutor ({tutor_modalitat}) != modalitat subgrup ({subgrup_modalitat})")

                subgrup_nivel, suma_posicions, multiple_pistes, clusters_pistes = _subgrup_nivel(subgrup)

                try:
                    tutor_idx = tutor_nivel_order.index(tutor_nivel)
                    part_idx = partits_nivel_order.index(subgrup_nivel)

                    n_t = len(tutor_nivel_order)
                    m_p = len(partits_nivel_order)

                    map_tutor = tutor_idx / (n_t - 1) if n_t > 1 else 0
                    map_partit = part_idx / (m_p - 1) if m_p > 1 else 0
                    map_posicions = (suma_posicions - 3) / (19 - 3)

                    nombre_partits_subgrup = len(subgrup)

                    mitja_transport = row.get('Mitjà de Transport', '')
                    if pd.isna(mitja_transport):
                        mitja_transport = ''
                    if any(x in mitja_transport.lower() for x in ['moto', 'cotxe', 'patinet elèctric', 'bicicleta']):
                        scale_vehicle = 0
                    else:
                        scale_vehicle = 1000

                    dist = abs(map_tutor - map_partit)
                    dist_classif = abs(map_posicions - map_tutor)

                    cost = dist * 1000 + dist_classif * 500 + (1 / max(nombre_partits_subgrup, 1)) * 100
                    if multiple_pistes:
                        cost += scale_vehicle

                    # preferències hardcoded del teu codi
                    if "5413" in str(tutor_codi):
                        favorits = {"12", "13", "9", "6", "10", "15"}
                        if any(str(c) in favorits for c in clusters_pistes):
                            cost *= 0.2

                except ValueError:
                    raise ValueError(f"Nivell tutor ({tutor_nivel}) o subgrup ({subgrup_nivel}) no reconegut.")

                # disponibilitat
                dispo_inici = row['Hora Inici']
                dispo_final = row['Hora Fi']
                sub_inici = min(r['Hora'] for r in subgrup)
                sub_final = max(r['Hora'] for r in subgrup)

                dispo_final_adj = (datetime.combine(datetime.today(), dispo_final) - timedelta(hours=1)).time()
                if dispo_inici > sub_inici or dispo_final_adj < sub_final:
                    cost += 1e6

                C[i, j] = cost

        row_ind, col_ind = linear_sum_assignment(C)

        if task_id:
            async_to_sync(push_log)(task_id, "Tutors assignats.", 85)

        # df_partits_geo per mapa
        df_partits_geo = df_partits.merge(
            domicilis_clusteritzats[["adreca", "lat", "lon"]],
            on="adreca",
            how="left"
        )

        # construir assignacions
        for tutor_idx, subgrup_idx in zip(row_ind, col_ind):
            tutor_row = df_dispos_modalitat.iloc[tutor_idx]
            tutor_id = tutor_row['ID']
            tutor_codi = tutor_row['Codi Tutor de Joc']
            tutor_nom = tutor_row.get('Nom', '')
            tutor_cognoms = tutor_row.get('Cognoms', '')
            tutor_nivell = tutor_row.get('Nivell', '')
            tutor_hora_inici = tutor_row.get('Hora Inici', '')
            tutor_hora_fi = tutor_row.get('Hora Fi', '')
            observacions = tutor_row.get('Observacions', '')

            subgrup = final_subgrups[subgrup_idx]
            assigned_tutor_ids.add(tutor_id)

            for partit in subgrup:
                if C[tutor_idx, subgrup_idx] >= 1e5:
                    continue

                assigned_partit_ids.add(partit['ID'])
                assigned_tutors.append({
                    'ID': partit.get('ID', ''),
                    'Data Partit': partit.get('Data', ''),
                    'Partit Hora': partit.get('Hora', ''),
                    'Codi Partit': partit.get('Codi', ''),
                    'Pista': partit.get('Pista joc', ''),
                    'Club Visitant': partit.get('Equip visitant', ''),
                    'Categoria': partit.get('Categoria', ''),
                    'Modalitat': partit.get('Modalitat', ''),
                    'Club Local': partit.get('Club Local', ''),
                    'Classificació Equips': f"Pos Local: {int(partit.get('Posició Equip Local', -1))}, Pos Visitant: {int(partit.get('Posició Equip Visitant', -1))}",
                    'Tutor Codi': tutor_codi,
                    'Tutor Nom': tutor_nom,
                    'Tutor Cognoms': tutor_cognoms,
                    'Tutor Nivell': tutor_nivell,
                    'Tutor Hora Inici': tutor_hora_inici,
                    'Tutor Hora Fi': tutor_hora_fi,
                    'Observacions': observacions
                })

    df_assignacions = pd.DataFrame(assigned_tutors)
    if not df_assignacions.empty:
        df_assignacions['Tutor'] = (df_assignacions.get('Tutor Nom', '').fillna('') + ' ' +
                                    df_assignacions.get('Tutor Cognoms', '').fillna('')).str.strip()
        df_assignacions = df_assignacions.sort_values(['Tutor Codi', 'Data Partit', 'Partit Hora']).reset_index(drop=True)

        # --- Persistència a BD (Assignment/Match/Referee) ---
    if run_id is not None:
        persist_assignacions_to_db(
            run_id=run_id,
            df_partits=df_partits,
            df_dispos=df_dispos,
            df_assignacions=df_assignacions,
        )

    # --- Mapa: desa dins MEDIA_ROOT/designacions/maps/ ---
    map_rel_path = None
    out_map_abs = None
    if run_id is not None:
        maps_dir = os.path.join(MEDIA_ROOT, "designacions", "maps")
        os.makedirs(maps_dir, exist_ok=True)
        out_map_abs = os.path.join(maps_dir, f"run_{run_id}.html")
        map_rel_path = os.path.join("designacions", "maps", f"run_{run_id}.html")

    if task_id:
        async_to_sync(push_log)(task_id, "Generant mapa d'assignacions.", 92)

    out_map = mapa_assignacions_interactiu(
        df_partits_geo=df_partits_geo,
        df_assignacions=df_assignacions if not df_assignacions.empty else pd.DataFrame(columns=["Codi Partit"]),
        out_html=out_map_abs or "mapa_assignacions.html",
        mostra_totes_les_seus=True
    )

    if task_id:
        async_to_sync(push_log)(task_id, "Mapa generat.", 94)

    # --- No assignats (per resum) ---
    all_partit_ids = set(df_partits['ID'])
    unassigned_partit_ids = all_partit_ids - assigned_partit_ids
    df_unassigned = df_partits[df_partits['ID'].isin(unassigned_partit_ids)] if unassigned_partit_ids else pd.DataFrame()

    all_tutor_ids = set(df_dispos['ID'])
    unassigned_tutor_ids = all_tutor_ids - assigned_tutor_ids
    df_unassigned_tutors = df_dispos[df_dispos['ID'].isin(unassigned_tutor_ids)] if unassigned_tutor_ids else pd.DataFrame()

    if task_id:
        async_to_sync(push_log)(task_id, "Procés del motor finalitzat.", 96)

    # Retornem un resum (no Excel)
    return {
        "assigned": int(len(df_assignacions)) if df_assignacions is not None else 0,
        "unassigned_matches": int(len(df_unassigned)) if df_unassigned is not None else 0,
        "unassigned_referees": int(len(df_unassigned_tutors)) if df_unassigned_tutors is not None else 0,
        "needs_review_referees": int(len(df_revisio_sense_nivell)) if df_revisio_sense_nivell is not None else 0,
        "map_path": map_rel_path,   # relatiu a MEDIA_ROOT
    }


if __name__ == "__main__":

    main(file_path_dispo, file_path_partits)