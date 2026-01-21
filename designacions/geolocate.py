import pandas as pd
from geopy.geocoders import Nominatim
from time import sleep
import re
import time
from geopy.exc import GeocoderTimedOut, GeocoderUnavailable
import sys
from pathlib import Path
import hashlib
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import folium
from sklearn.cluster import DBSCAN


import numpy as np
import matplotlib.pyplot as plt

def haversine_km(lat1, lon1, lat2, lon2):
    # lat/lon en radians
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat/2)**2 + np.cos(lat1)*np.cos(lat2)*np.sin(dlon/2)**2
    c = 2*np.arcsin(np.sqrt(a))
    return 6371.0088 * c

def plot_clusters_amb_distanicies(
    df,
    lat_col="lat",
    lon_col="lon",
    cluster_col="cluster",
    label_col="adreca",
    top_k_pairs=1,
):
    d = df.dropna(subset=[lat_col, lon_col]).copy()

    # coordenades en radians
    lat = np.radians(d[lat_col].astype(float).to_numpy())
    lon = np.radians(d[lon_col].astype(float).to_numpy())
    n = len(d)

    # haversine vectoritzat
    def haversine_km(lat1, lon1, lat2, lon2):
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = np.sin(dlat/2)**2 + np.cos(lat1)*np.cos(lat2)*np.sin(dlon/2)**2
        c = 2*np.arcsin(np.sqrt(a))
        return 6371.0088 * c

    dist = haversine_km(lat[:, None], lon[:, None], lat[None, :], lon[None, :])
    np.fill_diagonal(dist, -1)

    iu = np.triu_indices(n, k=1)
    dist_u = dist[iu]
    idx_sort = np.argsort(dist_u)[::-1][:top_k_pairs]
    pairs = [(iu[0][i], iu[1][i], dist_u[i]) for i in idx_sort]

    # ---- PLOT BASE ----
    fig, ax = plt.subplots(figsize=(10, 8))

    sc = ax.scatter(
        d[lon_col],
        d[lat_col],
        c=d[cluster_col].astype(float),
        s=18,
        alpha=0.6,
    )

    ax.set_aspect("equal", adjustable="datalim")
    ax.set_xlabel("Longitud")
    ax.set_ylabel("Latitud")
    ax.set_title("Clústers i parells de domicilis més distants")
    plt.colorbar(sc, ax=ax, label="ID clúster")

    # ---- DIBUIXAR PARELLS + ETIQUETES ----
    for a, b, km in pairs:
        x = [d.iloc[a][lon_col], d.iloc[b][lon_col]]
        y = [d.iloc[a][lat_col], d.iloc[b][lat_col]]

        ax.plot(x, y, linewidth=2)
        ax.scatter(x, y, s=120)

        # text de distància al mig
        ax.text(
            np.mean(x),
            np.mean(y),
            f"{km:.2f} km",
            fontsize=10,
            weight="bold",
            ha="center",
        )

        # etiquetes dels dos domicilis
        for idx, dx, dy in [(a, 0.0003, 0.0003), (b, -0.0003, -0.0003)]:
            ax.annotate(
                d.iloc[idx][label_col],
                (d.iloc[idx][lon_col], d.iloc[idx][lat_col]),
                xytext=(d.iloc[idx][lon_col] + dx, d.iloc[idx][lat_col] + dy),
                arrowprops=dict(arrowstyle="->", linewidth=1),
                fontsize=9,
                bbox=dict(boxstyle="round,pad=0.2", alpha=0.7),
            )

    plt.show()
    return fig, ax, pairs


def clusteritza_i_plota(
    df: pd.DataFrame,
    lat_col: str = "lat",
    lon_col: str = "lon",
    eps_metres: float = 500,
    min_samples: int = 2,
    columna_sortida: str = "cluster",
):
    """
    Afegeix una columna de clúster al df i dibuixa un scatter (lon vs lat).

    - eps_metres: radi màxim (aprox) perquè punts siguin del mateix clúster
    - min_samples: mínim de punts per formar clúster
    - cluster = -1 indica 'outlier' (no assignat)
    """

    # Copia per no tocar l'original (si no ho vols, pots treure el .copy())
    out = df.copy()

    # Validacions bàsiques
    if lat_col not in out.columns or lon_col not in out.columns:
        raise ValueError(f"El df ha de tenir les columnes '{lat_col}' i '{lon_col}'.")

    coords = out[[lat_col, lon_col]].astype(float)
    coords = coords.dropna()
    if coords.empty:
        raise ValueError("No hi ha coordenades vàlides (lat/lon) per clusteritzar.")

    print(f"Clusteritzant {len(coords)} punts amb eps={eps_metres} metres i min_samples={min_samples}...")
    # DBSCAN amb haversine (cal passar radians)
    coords_rad = np.radians(coords.to_numpy())

    kms_per_radian = 6371.0088
    eps = (eps_metres / 1000.0) / kms_per_radian

    model = DBSCAN(eps=eps, min_samples=min_samples, metric="haversine")
    labels = model.fit_predict(coords_rad)

    # Assignar labels al df (respectant índexos després de dropna)
    out[columna_sortida] = np.nan
    out.loc[coords.index, columna_sortida] = labels

    # Ara trenquem els clúster ens subgrups més petits, de màxim 2 punts
    max_punts_per_subcluster = 3
    grups_actuals = out[columna_sortida].dropna().unique()
    nou_label = out[columna_sortida].max() + 1
    for g in grups_actuals:
        # Calculem la distancia total interclúster
        print("Revisant clúster:", g)
        if g == -1:
            print(" - És outlier, s'ignora.")
            continue
        subdf = out[out[columna_sortida] == g]
        if len(subdf) <= max_punts_per_subcluster:
            print(f" - Té {len(subdf)} punts, no es divideix.")
            continue
        print(f" - Té {len(subdf)} punts, es divideix en subclústers de màxim {max_punts_per_subcluster} punts.")
        # Matriu de distàncies
        lat = np.radians(subdf[lat_col].astype(float).to_numpy())
        lon = np.radians(subdf[lon_col].astype(float).to_numpy())
        dist = haversine_km(lat[:, None], lon[:, None], lat[None, :], lon[None, :])
        np.fill_diagonal(dist, np.inf)
        assigned = set()
        # assume dist (n x n) computed, subdf, nou_label defined
        k = max_punts_per_subcluster
        n = len(subdf)
        assigned_pos = set()
        pos_to_idx = list(subdf.index)  # pos -> original index

        while len(assigned_pos) < n:
            # punts disponibles (posicions 0..n-1)
            remaining = [p for p in range(n) if p not in assigned_pos]
            # escollim seed: primer de remaining (o el que vulguis)
            seed = remaining[0]
            # troba veïns no assignats ordenats per dist
            neigh = [j for j in sorted(remaining, key=lambda x: dist[seed, x]) if j != seed]
            take = [seed] + neigh[: min(k-1, len(neigh))]
            # assigna aquests punts al nou_label
            for p in take:
                orig_idx = pos_to_idx[p]
                out.at[orig_idx, columna_sortida] = nou_label
                assigned_pos.add(p)
            print(f"   - Assignant punts {[pos_to_idx[p] for p in take]} al subclúster {nou_label}")
            nou_label += 1
            out[columna_sortida] = out[columna_sortida].astype("Int64")  # permet NA

    # Plot
    fig, ax, pairs = plot_clusters_amb_distanicies(
        out,
        lat_col="lat",
        lon_col="lon",
        cluster_col="cluster",
        label_col="adreca",
        top_k_pairs=3
    )

    for a, b, km in pairs:
        print(
            f"{km:.2f} km entre:\n"
            f" - {out.iloc[a]['adreca']}\n"
            f" - {out.iloc[b]['adreca']}\n"
        )
    mapa = mapa_clusters_interactiu(out, out_html="mapa_clusters.html")
    print("Mapa guardat a:", mapa)

    return out, model, fig, ax


ABREVIATURES = [
    (r"\bC\.\s*", "Carrer "),
    (r"\bAv\.\s*", "Avinguda "),
    (r"\bPg\.\s*", "Passeig "),
    (r"\bPl\.\s*", "Plaça "),
    (r"\bSta\.\s*", "Santa "),
    (r"\bSt\.\s*", "Sant "),
]



def neteja_parentesis(adreca: str) -> str:
    s = re.sub(r"\s*\([^)]*\)\s*", " ", str(adreca))
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\s*,\s*", ", ", s)
    s = re.sub(r"(,\s*){2,}", ", ", s)
    s = re.sub(r",\s*$", "", s)
    return s

def expandeix_abreviatures(adreca: str) -> str:
    s = adreca
    for pattern, repl in ABREVIATURES:
        s = re.sub(pattern, repl, s, flags=re.IGNORECASE)
    return s

def afegeix_pais_si_cal(adreca: str) -> str:
    s = adreca.strip()
    if "espanya" not in s.lower() and "spain" not in s.lower():
        s = s + ", Espanya"
    return s

import unicodedata
import re

def _norm_txt(s: str) -> str:
    s = str(s or "").strip()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return s.casefold()

def extreu_municipi(adreca: str) -> str | None:
    """
    Extreu el municipi com el text després de l'última coma.
    Ex: "Camí de la Pava, 15, GAVA" -> "GAVA"
        "..., BARCELONA, Espanya"    -> "BARCELONA"
    """
    parts = [p.strip() for p in str(adreca).split(",") if p.strip()]
    if not parts:
        return None
    last = parts[-1]
    if _norm_txt(last) in ("espanya", "spain"):
        if len(parts) >= 2:
            return parts[-2]
        return None
    return last

def extreu_municipi_nominatim(loc) -> str | None:
    if not loc or not hasattr(loc, "raw"):
        return None
    addr = (loc.raw or {}).get("address", {}) or {}
    for k in ("city", "town", "village", "municipality", "hamlet", "suburb"):
        if addr.get(k):
            return addr.get(k)
    return None

def coincideix_municipi(loc, municipi_esperat: str) -> bool:
    if not municipi_esperat:
        return True  # si no sabem el municipi, no filtrem
    got = extreu_municipi_nominatim(loc)
    if not got:
        return False
    return _norm_txt(got) == _norm_txt(municipi_esperat)



def _color_per_cluster(cid) -> str:
    """Color estable per clúster (hex). Outliers en gris."""
    if cid == -1 or pd.isna(cid):
        return "#808080"  # gris
    # hash estable -> color
    h = hashlib.md5(str(int(cid)).encode("utf-8")).hexdigest()
    return "#" + h[:6]

def mapa_clusters_interactiu(
    df: pd.DataFrame,
    lat_col="lat",
    lon_col="lon",
    cluster_col="cluster",
    label_col="adreca",
    out_html="mapa_clusters.html",
    zoom_start=12,
    radius=5
):
    d = df.dropna(subset=[lat_col, lon_col]).copy()

    # centre del mapa
    center_lat = d[lat_col].astype(float).mean()
    center_lon = d[lon_col].astype(float).mean()

    m = folium.Map(location=[center_lat, center_lon], zoom_start=zoom_start, control_scale=True)

    # capes per clúster
    for cid, g in d.groupby(cluster_col, dropna=False):
        nom = "Outliers (-1)" if cid == -1 else f"Clúster {cid}"
        fg = folium.FeatureGroup(name=nom, show=True)

        color = _color_per_cluster(cid)

        for _, r in g.iterrows():
            label = str(r.get(label_col, ""))

            folium.CircleMarker(
                location=[float(r[lat_col]), float(r[lon_col])],
                radius=radius,
                color=color,
                fill=True,
                fill_color=color,
                fill_opacity=0.85,
                tooltip=folium.Tooltip(label, sticky=True),
                popup=folium.Popup(label, max_width=350),
            ).add_to(fg)

        fg.add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)
    m.save(out_html)
    return out_html



# Barcelona ciutat (aprox)
BCN_CITY_VIEWBOX = ((41.47, 2.07), (41.32, 2.23))  # (lat_max, lon_min), (lat_min, lon_max)

# Àrea Metropolitana / rodalia (aprox)
AMB_VIEWBOX = ((41.55, 1.90), (41.25, 2.45))

def geocode_amb_reintents_limitat(
    geolocator, query: str,
    viewbox,
    bounded: bool = True,
    intents: int = 3, timeout: int = 10, pausa: float = 1.5,
    country_codes: str = "es"
):
    for i in range(intents):
        try:
            loc = geolocator.geocode(
                query,
                timeout=timeout,
                country_codes=country_codes,
                viewbox=viewbox,
                bounded=bounded,
                addressdetails=True
            )
            if loc:
                return loc
            return None
        except (GeocoderTimedOut, GeocoderUnavailable):
            time.sleep(pausa * (i + 1))
    return None


def es_barcelona(adreca_original: str) -> bool:
    # detecta 'BARCELONA' com a paraula (evita falsos positius)
    return re.search(r"\bBARCELONA\b", str(adreca_original), flags=re.IGNORECASE) is not None



def normalitza_puntuacio(s: str) -> str:
    s = re.sub(r"\s+", " ", str(s)).strip()
    s = re.sub(r"\s*,\s*", ", ", s)
    s = re.sub(r"(,\s*){2,}", ", ", s)
    s = re.sub(r",\s*$", "", s)
    return s

def treu_text_extra_despres_numero(adreca: str) -> str:
    """
    Retalla informació descriptiva després d'un número de portal, si existeix.
    Ex:
      "C. Provençals, 9 ... Pavelló ..., BARCELONA"
    ->  "C. Provençals, 9, BARCELONA"
    """
    s = adreca

    # Patró: troba "..., <numero>," i es queda fins a la ciutat
    # Intent simple: si hi ha "BARCELONA" o "BADALONA", talla fins aquí.
    m_city = re.search(r"\b(BARCELONA|BADALONA)\b", s, flags=re.IGNORECASE)
    city = m_city.group(1) if m_city else None

    # Si hi ha ciutat, elimina el que hi ha entre el número i la ciutat
    if city:
        # Manté fins al número (o rang / s/n) i després posa ", CITY"
        m_num = re.search(r"(.*?\b(\d+\s*-\s*\d+|\d+|s\/n)\b)", s, flags=re.IGNORECASE)
        if m_num:
            base = m_num.group(1)
            return normalitza_puntuacio(f"{base}, {city}")

    return normalitza_puntuacio(s)

def treu_sn(adreca: str) -> str:
    """
    Elimina 's/n' si existeix i també neteja dobles comes.
    Ex: "C. Ordunya, s/n, BARCELONA" -> "C. Ordunya, BARCELONA"
    """
    s = re.sub(r"\bS\/N\b|\bs\/n\b", "", adreca)
    return normalitza_puntuacio(s)

def només_carrer_i_ciutat(adreca: str) -> str:
    """
    Redueix a "carrer..., ciutat" eliminant tot el que sembli extra.
    """
    s = adreca
    m_city = re.search(r"\b(BARCELONA|BADALONA)\b", s, flags=re.IGNORECASE)
    if not m_city:
        return normalitza_puntuacio(s)

    city = m_city.group(1)
    # Agafa tot abans de la ciutat i neteja
    before = s[:m_city.start()].strip(" ,")
    # Treu números / rangs / s/n del before per quedar només amb el nom del carrer
    before = re.sub(r"\b(\d+\s*-\s*\d+|\d+|s\/n)\b", "", before, flags=re.IGNORECASE)
    return normalitza_puntuacio(f"{before}, {city}")


def extreu_variants_rang(adreca: str) -> list[str]:
    """
    Si detecta un rang de portal (p.ex. '11-25'), retorna variants provant
    primer extrem inferior i superior.
    Si no hi ha rang, retorna [].
    """
    s = adreca

    # Rang simple: 11-25, 19-21, 1-25...
    m = re.search(r"\b(\d+)\s*-\s*(\d+)\b", s)
    if not m:
        return []

    a, b = m.group(1), m.group(2)

    # Substitueix només la primera ocurrència del rang
    v1 = re.sub(r"\b" + re.escape(m.group(0)) + r"\b", a, s, count=1)
    v2 = re.sub(r"\b" + re.escape(m.group(0)) + r"\b", b, s, count=1)

    # Opcional: si vols, també pots provar el punt mig
    # mid = str((int(a) + int(b)) // 2)
    # v3 = re.sub(r"\b" + re.escape(m.group(0)) + r"\b", mid, s, count=1)

    variants = []
    for v in (v1, v2):
        v = re.sub(r"\s+", " ", v).strip()
        if v and v != s:
            variants.append(v)
    return variants


def geocode_address_amb_fallback(geolocator, adreca: str):
    """
    Retorna (lat, lon, query_usada) o (None, None, None).

    Regla:
    - Sempre valida que el municipi del resultat coincideixi amb el municipi indicat a l'adreça (última coma).
    - Si el municipi esperat és BARCELONA -> primer BCN ciutat; si falla -> AMB.
    - Si no és BARCELONA -> directament AMB.
    """

    original = normalitza_puntuacio(adreca)
    municipi_esperat = extreu_municipi(original)

    # ---- candidats (igual que tens) ----
    base1 = original
    base2 = normalitza_puntuacio(neteja_parentesis(original))
    base3 = normalitza_puntuacio(expandeix_abreviatures(base2))

    candidats = [base1, base2, base3]

    for b in (base1, base2, base3):
        candidats.extend(extreu_variants_rang(b))

    candidats.append(treu_sn(base3))
    candidats.append(treu_sn(base2))

    candidats.append(treu_text_extra_despres_numero(base3))
    candidats.append(treu_text_extra_despres_numero(base2))

    candidats.append(només_carrer_i_ciutat(base3))
    candidats.append(només_carrer_i_ciutat(base2))

    candidats = [afegeix_pais_si_cal(c) for c in candidats if c]

    vistos, candidats_uni = set(), []
    for c in candidats:
        if c and c not in vistos:
            vistos.add(c)
            candidats_uni.append(c)

    # ---- cerca amb viewbox segons municipi ----
    es_bcn = municipi_esperat is not None and _norm_txt(municipi_esperat) == _norm_txt("Barcelona")

    for q in candidats_uni:
        if es_bcn:
            # 1) BCN ciutat
            loc = geocode_amb_reintents_limitat(geolocator, q, viewbox=BCN_CITY_VIEWBOX, bounded=True)
            if loc and not coincideix_municipi(loc, municipi_esperat):
                loc = None

            # 2) fallback AMB
            if not loc:
                loc = geocode_amb_reintents_limitat(geolocator, q, viewbox=AMB_VIEWBOX, bounded=True)
                if loc and not coincideix_municipi(loc, municipi_esperat):
                    loc = None
        else:
            # Directe AMB
            loc = geocode_amb_reintents_limitat(geolocator, q, viewbox=AMB_VIEWBOX, bounded=True)
            if loc and not coincideix_municipi(loc, municipi_esperat):
                loc = None

        if loc:
            return loc.latitude, loc.longitude, q

    return None, None, None

def geocodificar(document_csv, existing_adrecces="domicilis_geocodificats.csv"):

    # En cas que el document sigui una llista d'adreces
    if isinstance(document_csv, list):
        df_nou = pd.DataFrame({"adreca": document_csv})
        print(f"Geocodificant llista de {len(df_nou)} adreces proporcionades.")
        #print(df_nou)
    else:
        df_nou = pd.read_csv(document_csv)

    # Carrega l'antic si existeix, si no crea'l buit
    if Path(existing_adrecces).is_file():
        df_antic = pd.read_csv(existing_adrecces)
    else:
        df_antic = pd.DataFrame(columns=["adreca", "lat", "lon"])

    # Unió (antic + nou) i deduplicació per adreça
    df_master = pd.concat([df_antic, df_nou], ignore_index=True)

    # Normalitza mínim (evita espais finals)
    df_master["adreca"] = df_master["adreca"].astype(str).str.strip()

    # Si no existeixen lat/lon, crea-les
    if "lat" not in df_master.columns:
        df_master["lat"] = pd.NA
    if "lon" not in df_master.columns:
        df_master["lon"] = pd.NA

    # Prioritza files amb coordenades abans de deduplicar
    df_master["_te_coords"] = df_master["lat"].notna() & df_master["lon"].notna()

    # Ordenació estable + la fila amb coords primer
    df_master = df_master.sort_values(
        by=["adreca", "_te_coords"],
        ascending=[True, False],
        kind="mergesort"  # IMPORTANT: estable
    )

    # Ara deduplica quedant-te la "millor" fila (la que té coords si existeix)
    df_master = df_master.drop_duplicates(subset=["adreca"], keep="first").drop(columns=["_te_coords"])

    # Geocodificar només adreces sense lat/lon
    geolocator = Nominatim(user_agent="geocodificacio_ceeb")


    mask_falten = df_master["lat"].isna() | df_master["lon"].isna()
    pendents = df_master.loc[mask_falten, "adreca"].dropna().unique().tolist()

    print(f"Adreces totals al master: {len(df_master)}")
    print(f"Pendents de geocodificar: {len(pendents)}")

    new_adresses = []
    no_trobats = []
    for adreca in pendents:
        print(f"Geocodificant: {adreca}")
        lat, lon, adreca_usada = geocode_address_amb_fallback(geolocator, adreca)

        if lat is not None and lon is not None:
            if adreca_usada != adreca:
                print(f"  Trobat amb adreça netejada: {adreca_usada}")
            new_adresses.append({'adreca': adreca, 'lat_new': lat, 'lon_new': lon})
        else:
            print(f"  No s'ha obtingut coordenades per: {adreca}")
        if lat is not None and lon is not None:
            df_master.loc[df_master["adreca"] == adreca, "lat"] = lat
            df_master.loc[df_master["adreca"] == adreca, "lon"] = lon
            print(f"  OK lat={lat}, lon={lon}")
        else:
            print("  NO trobat")
            # Els guardem
            no_trobats.append(adreca)
        sleep(2)


    df_master.to_csv(existing_adrecces, index=False)
    if no_trobats:
        print(f"\nAdreces NO geocodificades ({len(no_trobats)}):")
        for a in no_trobats:
            print(" -", a)
        # Guardem en un fitxer separat
        with open("domicilis_no_trobats.txt", "w", encoding="utf-8") as f:
            for a in no_trobats:
                f.write(a + "\n")
    print(f"Master guardat/actualitzat a: {existing_adrecces}")

    return df_master



if __name__ == "__main__":


    # Obtenim domicilis de un fitxer i els geocodifiquem

    geocodificar("domicilis_partits.csv", existing_adrecces="domicilis_geocodificats.csv")

    # Fem clustering i plotejem
    df_domicilis = pd.read_csv("domicilis_geocodificats.csv")
    df_clusteritzat, model, fig, ax = clusteritza_i_plota(df_domicilis, lat_col='lat', lon_col='lon')

    # Mostrem els clusters trobats
    n_clusters = len(set(model.labels_)) - (1 if -1 in model.labels_ else 0)
    print(f"S'han trobat {n_clusters} clústers diferents.")
    for cluster_id in sorted(set(model.labels_)):
        if cluster_id == -1:
            print("Clúster -1: outliers (no assignats), nombre de punts:", sum(model.labels_ == cluster_id))
        else:
            num_punts = sum(model.labels_ == cluster_id)
            print(f"Clúster {cluster_id}: {num_punts} punts")
    
    # Guarda la figura
    try:
        fig.savefig("domicilis_clusteritzats.png")
        print("Figura guardada a 'domicilis_clusteritzats.png'")
    except Exception as exc:
        print(f"No s'ha pogut guardar la figura: {exc}", file=sys.stderr)

    # Guarda el df clusteritzat
    try:
        df_clusteritzat.to_csv("domicilis_clusteritzats.csv", index=False)
        print("Df clusteritzat guardat a 'domicilis_clusteritzats.csv'")
    except Exception as exc:
        print(f"No s'ha pogut escriure a 'domicilis_clusteritzats.csv': {exc}", file=sys.stderr)
