"""CASA/FORA textual request resolution copied from the legacy V1 flow.

This module is intentionally not wired into the current legacy execution path.
It exists so the behavior can be characterized and evolved independently.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import math
from typing import Any
import unicodedata

import pandas as pd

from calendaritzacions.domain.normalization import normalize_seed_value


SEED_COLUMN = "Núm. sorteig"
HOME_REQUEST = "casa"
AWAY_REQUEST = "fora"
TEXTUAL_REQUESTS = {HOME_REQUEST, AWAY_REQUEST}
VALID_HOME_NUMBERS = {8, 7, 6, 1}
VALID_AWAY_NUMBERS = {5, 4, 3, 2}


class HomeAwayResolutionError(ValueError):
    """Raised when CASA/FORA requests cannot be resolved consistently."""


@dataclass(frozen=True)
class HomeAwayResolution:
    equip_to_num_sorteig: dict[Any, int]
    entitats_assigned: dict[Any, int]
    duples_casa_fora: list[tuple[int, int]]
    traces: list[str]


def resolve_home_away_requests(df: pd.DataFrame) -> HomeAwayResolution:
    """Resolve textual CASA/FORA requests using the legacy V1 algorithm."""

    _validate_columns(df)

    df = df.copy()
    entity_key = _entity_assignment_key_column(df)
    duples_casa_fora = [(1, 5), (6, 2), (7, 3), (8, 4)]
    traces: list[str] = [f"entity_key={entity_key}"]

    _validate_no_mixed_textual_requests(df)

    entitats_links = _build_entitats_links(df, entity_key)
    traces.append(
        "entitats_links="
        + repr({entity: len(links) for entity, links in entitats_links.items()})
    )

    preferencies_entitat = _build_entity_preferences(
        df,
        entity_key,
        entitats_links,
        duples_casa_fora,
    )
    traces.extend(
        f"preferences[{entity}]={list(preferences.keys())}"
        for entity, preferences in preferencies_entitat.items()
    )

    mask_textual = _textual_request_mask(df)
    ids_textuals_per_entitat = (
        df.loc[mask_textual, [entity_key, "Id"]]
        .dropna(subset=[entity_key, "Id"])
        .groupby(entity_key)["Id"]
        .apply(lambda s: set(s.values))
        .to_dict()
    )

    ids_assigned_per_dupla = {idx: set() for idx in range(len(duples_casa_fora))}
    equip_to_num_sorteig: dict[Any, int] = {}
    entitats_assigned: dict[Any, int] = {}

    for entitat, preferencies in preferencies_entitat.items():
        equips_entitat = df[(df[entity_key] == entitat) & mask_textual].copy()
        links = set(entitats_links.get(entitat, set()))
        duples_ocupades = Counter(
            {
                idx: len(links & ids_assigned_per_dupla[idx])
                for idx in range(len(duples_casa_fora))
            }
        )

        tupla_preferida = _pick_preferred_dupla(preferencies, duples_ocupades)
        casa_num, fora_num = duples_casa_fora[tupla_preferida]

        for _, equip in equips_entitat.iterrows():
            req = _request_text(equip[SEED_COLUMN])
            if req == HOME_REQUEST:
                _assign_requested_number(
                    equip_to_num_sorteig,
                    equip["Id"],
                    casa_num,
                    VALID_HOME_NUMBERS,
                    HOME_REQUEST.upper(),
                )
            elif req == AWAY_REQUEST:
                _assign_requested_number(
                    equip_to_num_sorteig,
                    equip["Id"],
                    fora_num,
                    VALID_AWAY_NUMBERS,
                    AWAY_REQUEST.upper(),
                )
            else:
                raise HomeAwayResolutionError(
                    "Peticio de numero de sorteig no valida (ha de ser 'casa' o 'fora')"
                )

        entitats_assigned[entitat] = tupla_preferida
        ids_assigned_per_dupla[tupla_preferida] |= ids_textuals_per_entitat.get(
            entitat,
            set(),
        )
        traces.append(
            f"assigned[{entitat}]={tupla_preferida};conflicts="
            f"{duples_ocupades.get(tupla_preferida, 0)}"
        )

    counts = Counter(entitats_assigned.values())
    traces.append(f"dupla_counts={dict(counts)}")

    return HomeAwayResolution(
        equip_to_num_sorteig=equip_to_num_sorteig,
        entitats_assigned=entitats_assigned,
        duples_casa_fora=duples_casa_fora,
        traces=traces,
    )


def _validate_columns(df: pd.DataFrame) -> None:
    required = {"Id", "Nom Lliga", SEED_COLUMN}
    entity_column = _entity_assignment_key_column(df)
    if entity_column == "Entitat":
        required.add("Entitat")
    else:
        required.add("Pista joc")

    missing = required - set(df.columns)
    if missing:
        raise HomeAwayResolutionError(f"Falten columnes necessaries: {missing}")


def _entity_assignment_key_column(df: pd.DataFrame) -> str:
    return "Pista joc" if "Pista joc" in df.columns else "Entitat"


def _request_text(raw_value: Any) -> str:
    return str(raw_value).strip().lower()


def _textual_request_mask(df: pd.DataFrame) -> pd.Series:
    return df[SEED_COLUMN].astype(str).str.strip().str.lower().isin(TEXTUAL_REQUESTS)


def _validate_no_mixed_textual_requests(df: pd.DataFrame) -> None:
    df_req = df[_textual_request_mask(df)]
    if df_req.empty:
        return

    mix = df_req.groupby("Id")[SEED_COLUMN].apply(
        lambda values: set(_request_text(value) for value in values)
    )
    bad = mix[mix.apply(lambda values: len(values) > 1)]
    if bad.empty:
        return

    details = []
    for equip_id, values in bad.items():
        team_rows = df_req[df_req["Id"] == equip_id]
        team_name = (
            team_rows["Nom"].iloc[0]
            if "Nom" in team_rows.columns and not team_rows.empty
            else "(desconegut)"
        )
        details.append(f"- {team_name} [Id={equip_id}]: {', '.join(sorted(values))}")

    raise HomeAwayResolutionError(
        "ERROR: El mateix equip te peticions 'CASA' i 'FORA' en categories diferents. "
        "Un equip nomes pot demanar un tipus. Equips afectats:\n" + "\n".join(details)
    )


def _build_entitats_links(df: pd.DataFrame, entity_key: str) -> dict[Any, set[Any]]:
    entitats_links: dict[Any, set[Any]] = {}

    for _, row in df.iterrows():
        entitat = row[entity_key]
        peticio = _request_text(row[SEED_COLUMN])
        if peticio not in TEXTUAL_REQUESTS:
            continue
        if entitat in entitats_links:
            continue

        entitats_links[entitat] = set()
        equips_entitat_req = df[
            (df[entity_key] == entitat) & _textual_request_mask(df)
        ]
        categories_entitat = equips_entitat_req["Nom Lliga"].dropna().unique()

        for categoria in categories_entitat:
            equips_cat = df[df["Nom Lliga"] == categoria]
            for _, linked_row in equips_cat.iterrows():
                entitat2 = linked_row[entity_key]
                peticio2 = _request_text(linked_row[SEED_COLUMN])
                if entitat2 != entitat and peticio2 in TEXTUAL_REQUESTS:
                    entitats_links[entitat].add(linked_row["Id"])

    return {
        key: value
        for key, value in sorted(
            entitats_links.items(),
            key=lambda item: (-len(item[1]), str(item[0]).casefold()),
        )
    }


def _build_entity_preferences(
    df: pd.DataFrame,
    entity_key: str,
    entitats_links: dict[Any, set[Any]],
    duples_casa_fora: list[tuple[int, int]],
) -> dict[Any, dict[int, int]]:
    preferencies_entitat: dict[Any, dict[int, int]] = {}

    for entitat in list(entitats_links.keys()):
        entitat_count = {idx: 0 for idx in range(len(duples_casa_fora))}
        cats_req = (
            df.loc[
                (df[entity_key] == entitat) & _textual_request_mask(df),
                "Nom Lliga",
            ]
            .dropna()
            .unique()
        )

        for categoria in sorted(cats_req, key=lambda value: str(value).casefold()):
            equips_cat = df[df["Nom Lliga"] == categoria]
            for _, r_cat in equips_cat.iterrows():
                seed = normalize_seed_value(r_cat[SEED_COLUMN])
                if _is_nan(seed):
                    continue
                for idx, (casa, fora) in enumerate(duples_casa_fora):
                    if seed == casa or seed == fora:
                        entitat_count[idx] = entitat_count.get(idx, 0) + 1
                        break

        if sum(entitat_count.values()) == 0:
            fallback_idx = _stable_entity_hash(entitat) % len(duples_casa_fora)
            entitat_count = {fallback_idx: 0}

        preferencies_entitat[entitat] = dict(
            sorted(entitat_count.items(), key=lambda item: item[1])
        )

    return preferencies_entitat


def _pick_preferred_dupla(
    preferencies: dict[int, int],
    duples_ocupades: Counter,
) -> int:
    tupla_preferida = None
    min_conflictes = float("inf")

    for pref in preferencies.keys():
        conflicts = duples_ocupades.get(pref, 0)
        if conflicts < min_conflictes:
            min_conflictes = conflicts
            tupla_preferida = pref

    if tupla_preferida is None:
        tupla_preferida = next(iter(preferencies.keys()), None)

    if tupla_preferida is None:
        raise HomeAwayResolutionError("No s'ha pogut seleccionar cap dupla CASA/FORA")

    return tupla_preferida


def _assign_requested_number(
    equip_to_num_sorteig: dict[Any, int],
    equip_id: Any,
    number: int,
    valid_numbers: set[int],
    request_label: str,
) -> None:
    if number not in valid_numbers:
        raise HomeAwayResolutionError(
            f"Numero de sorteig assignat a '{request_label.lower()}' no valid"
        )

    previous = equip_to_num_sorteig.get(equip_id)
    if previous is not None and previous != number:
        raise HomeAwayResolutionError(
            f"ERROR: Conflicte de mapping per a l'equip '{equip_id}'. "
            f"Ja tenia assignat {previous} i s'esta intentant assignar {number} "
            f"({request_label})."
        )

    equip_to_num_sorteig[equip_id] = number


def _stable_entity_hash(entity: Any) -> int:
    return int(hashlib.sha1(_normalize_entity_name(entity).encode("utf-8")).hexdigest(), 16)


def _normalize_entity_name(name: Any) -> str:
    text = unicodedata.normalize("NFKC", str(name)).casefold().strip()
    return " ".join(text.split())


def _is_nan(value: Any) -> bool:
    try:
        return bool(math.isnan(value))
    except (TypeError, ValueError):
        return False
