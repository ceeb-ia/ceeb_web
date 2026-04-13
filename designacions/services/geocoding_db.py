from __future__ import annotations

from time import sleep
from typing import Iterable

import pandas as pd
from asgiref.sync import async_to_sync
from geopy.geocoders import Nominatim

from designacions.geolocate import extreu_municipi, geocode_address_amb_fallback
from designacions.models import Address
from logs import push_log

from .addressing import build_address_payload, resolve_address


_geolocator = Nominatim(user_agent="designacions_ceeb")


def geocodifica_adreces(adreces: Iterable[str], *, sleep_seconds: float = 2.0, task_id=None) -> list[Address]:
    """
    Geocodifica una llista d'adreces utilitzant Address (BD) com a master.

    - Si l'adreca ja existeix amb lat/lon -> la reutilitza i normalitza l'estat.
    - Si no existeix o no te coords -> geocodifica i guarda lat/lon + geocode_status.
    - Retorna la llista d'Address en el mateix ordre d'entrada deduplicat.
    """
    seen = set()
    ordered_addresses = []
    for raw_address in adreces:
        payload = build_address_payload(text=raw_address, municipality=extreu_municipi(raw_address))
        if not payload["text"] or payload["normalized_text"] in seen:
            continue
        seen.add(payload["normalized_text"])
        ordered_addresses.append(payload)

    resolved = []
    total = len(ordered_addresses)
    for counter, payload in enumerate(ordered_addresses):
        percentage = 45 + int((counter + 1) / max(total, 1) * (55 - 45))
        address = resolve_address(text=payload["text"], municipality=payload["municipality"])
        if address is None:
            continue

        if address.lat is not None and address.lon is not None:
            if address.geocode_status not in {"ok", "manual"} or address.last_error:
                address.geocode_status = "ok" if address.geocode_status != "manual" else "manual"
                address.last_error = None
                address.save(update_fields=["geocode_status", "last_error", "updated_at"])
            resolved.append(address)
            continue

        if task_id:
            async_to_sync(push_log)(task_id, f"Geocodificant adreca: {payload['text']}", percentage)
        lat, lon, query_used = geocode_address_amb_fallback(_geolocator, payload["text"])

        if lat is not None and lon is not None:
            address.lat = float(lat)
            address.lon = float(lon)
            if payload["municipality"] and not address.municipality:
                address.municipality = payload["municipality"]
            address.geocode_status = "ok"
            address.provider = "nominatim"
            address.last_error = None
            address.save(
                update_fields=["lat", "lon", "municipality", "geocode_status", "provider", "last_error", "updated_at"]
            )
        else:
            address.geocode_status = "not_found"
            address.provider = "nominatim"
            address.last_error = f"Sense resultat per a '{query_used or payload['text']}'"
            address.save(update_fields=["geocode_status", "provider", "last_error", "updated_at"])

        resolved.append(address)

        if sleep_seconds:
            sleep(sleep_seconds)

    return resolved


def addresses_to_df(addresses: Iterable[Address]) -> pd.DataFrame:
    """
    Converteix Address a un DataFrame compatible amb clusteritza_i_plota().
    """
    rows = []
    for address in addresses:
        rows.append(
            {
                "address_id": address.id,
                "adreca": address.text,
                "lat": address.lat,
                "lon": address.lon,
            }
        )
    return pd.DataFrame(rows)
