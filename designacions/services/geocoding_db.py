# designacions/services/geocoding_db.py
from __future__ import annotations

from dataclasses import dataclass
from time import sleep
from typing import Iterable

import pandas as pd
from geopy.geocoders import Nominatim
from asgiref.sync import async_to_sync
from designacions.models import Address
from designacions.geolocate import geocode_address_amb_fallback, extreu_municipi
from logs import push_log


_geolocator = Nominatim(user_agent="designacions_ceeb")


def geocodifica_adreces(adreces: Iterable[str], *, sleep_seconds: float = 2.0, task_id=None) -> list[Address]:
    """
    Geocodifica una llista d'adreces utilitzant Address (BD) com a master.

    - Si l'adreça ja existeix amb lat/lon -> la reutilitza.
    - Si no existeix o no té coords -> geocodifica (Nominatim) i guarda a BD.
    - Retorna la llista d'Address (en el mateix ordre d'entrada, deduplicat).
    """
    # dedup estable
    seen = set()
    norm = []
    for a in adreces:
        a = (a or "").strip()
        if not a or a in seen:
            continue
        seen.add(a)
        norm.append(a)

    out: list[Address] = []

    for counter, adreca in enumerate(norm):
        percentage = 45 + int((counter + 1) / len(norm) * (55 - 45))
        municipi = extreu_municipi(adreca)

        addr, _ = Address.objects.get_or_create(
            text=adreca,
            defaults={"municipality": municipi},
        )

        # Si ja té coords, OK
        if addr.lat is not None and addr.lon is not None:
            out.append(addr)
            continue

        # Geocodifica
        if task_id:
            async_to_sync(push_log)(task_id, f"Geocodificant adreça: {adreca}", percentage)
        lat, lon, _query_used = geocode_address_amb_fallback(_geolocator, adreca)

        if lat is not None and lon is not None:
            addr.lat = float(lat)
            addr.lon = float(lon)
            if not addr.municipality and municipi:
                addr.municipality = municipi
            addr.save(update_fields=["lat", "lon", "municipality"])
        # si no troba coords, queda a BD amb lat/lon null i després ho arreglaràs via la vista manual

        out.append(addr)

        # respecta rate limit Nominatim
        if sleep_seconds:
            sleep(sleep_seconds)

    return out


def addresses_to_df(addresses: Iterable[Address]) -> pd.DataFrame:
    """
    Converteix Addresses a un DataFrame compatible amb clusteritza_i_plota()
    (columnes: adreca, lat, lon).
    """
    rows = []
    for a in addresses:
        rows.append({
            "adreca": a.text,
            "lat": a.lat,
            "lon": a.lon,
        })
    return pd.DataFrame(rows)
