"""Second-phase classification enrichment for the legacy pipeline."""

from __future__ import annotations

import asyncio

import pandas as pd
from asgiref.sync import async_to_sync

from logs import push_log
from calendaritzacions.second_phase.ceeb_client import fetch_ceeb_async, parse_ceeb_xml, xml_to_dataframe
from calendaritzacions.second_phase.matching import _get_team_position, _normalize_team_key


def enrich_second_phase_classifications(
    df: pd.DataFrame,
    map_modalitat_nom: pd.DataFrame,
    task_id=None,
) -> tuple[pd.DataFrame, list[dict], list[dict]]:
    """Apply legacy second-phase classification lookups to ``df``."""
    print("Segona fase: processant classificacions prèvies...")
    if task_id:
        async_to_sync(push_log)(task_id, "Consultant classificacions per equips... (això pot portar uns minuts)", 60)

    missing_classifications = []
    unused_classification_teams = []

    df_grouped_modalitat = df.groupby(["Modalitat", "Categoria", "Subcategoria"])
    for (modalitat, categoria, subcategoria), df_modalitat in df_grouped_modalitat:
        print(f"Processant modalitat '{modalitat}, {categoria}, {subcategoria}' amb {len(df_modalitat)} equips...")
        map_modalitat = map_modalitat_nom.loc[map_modalitat_nom["Modalitat"] == modalitat]
        p2 = map_modalitat[map_modalitat["Nom"] == categoria]
        if subcategoria == "MIXT":
            p5 = "SXMIX"
        elif subcategoria == "FEMENÍ" or subcategoria == "FEMENI" or subcategoria == "FEM" or subcategoria == "F":
            p5 = "SXFEM"
        else:
            raise ValueError(f"Subcategoria desconeguda: {subcategoria}")

        root = asyncio.run(fetch_ceeb_async(str(p2["Id Categoria"].values[0]), p5))
        if root is None:
            print(f"Error fetching classifications for modalitat: {modalitat}")
            continue
        parsed = parse_ceeb_xml(root)
        classificacions_list = xml_to_dataframe(parsed)

        print(f"Classificació obtinguda per modalitat '{modalitat}, {categoria}, {subcategoria}':")
        print(classificacions_list)

        used_teams = set()
        total_teams = set()
        for idx, row in df_modalitat.iterrows():
            posicio = -1
            equip_id = row["Id"]
            equip_nom = row["Nom"]
            ctx = f"{modalitat}||{categoria}||{subcategoria}"

            for idx2, df_grup in enumerate(classificacions_list):
                posicio, category_teams_raw = _get_team_position(equip_nom, df_grup, task_id)
                grup_id = f"G{idx2}"
                group_team_tags = {
                    f"{_normalize_team_key(t)}||{ctx}||{grup_id}"
                    for t in category_teams_raw
                }
                total_teams.update(group_team_tags)

                if posicio != -1:
                    found_tag = f"{_normalize_team_key(equip_nom)}||{ctx}||{grup_id}"
                    used_teams.add(found_tag)
                    break

            if posicio == -1:
                print(f"    → NO TROBAT a cap grup per la modalitat '{modalitat}, {categoria}, {subcategoria}'")
                missing_classifications.append(
                    {
                        "Modalitat": modalitat,
                        "Categoria": categoria,
                        "Subcategoria": subcategoria,
                        "Nom Lliga": row.get("Nom Lliga", ""),
                        "Id": equip_id,
                        "Nom": equip_nom,
                        "Motiu": "No trobat a la classificació",
                    }
                )
                posicio = 10
            top = posicio <= 4 and posicio >= 0
            print(f"    → Posició final assignada: {posicio} (Top3: {top})")
            df.loc[df["Id"] == equip_id, "Posició Classificació Num"] = posicio
            df.loc[df["Id"] == equip_id, "Posició Classificació"] = bool(top)

        unused_teams_modalitat = total_teams - used_teams
        print(
            f"Total equips a la classificació: {len(total_teams)} modalitat {modalitat}, "
            f"equips utilitzats: {len(used_teams)}, no utilitzats: {len(unused_teams_modalitat)}"
        )

        if unused_teams_modalitat:
            print(f"Equips no utilitzats a la classificació (modalitat {modalitat}): {unused_teams_modalitat}")
            for entry in sorted(unused_teams_modalitat):
                try:
                    parts = entry.split("||")
                    team_name = parts[0] if len(parts) > 0 else entry
                    modalitat_name = parts[1] if len(parts) > 1 else ""
                    categoria_name = parts[2] if len(parts) > 2 else ""
                    subcat_name = parts[3] if len(parts) > 3 else ""
                    grup_name = parts[4] if len(parts) > 4 else ""
                except Exception:
                    team_name = entry
                    modalitat_name = ""
                    categoria_name = ""
                    subcat_name = ""
                    grup_name = ""

                unused_classification_teams.append(
                    {
                        "Modalitat": modalitat_name or modalitat,
                        "Categoria": categoria_name or categoria,
                        "Subcategoria": subcat_name or subcategoria,
                        "Nom Lliga": f"{modalitat_name} {categoria_name} {subcat_name}".strip(),
                        "Nom": team_name,
                        "Grup": grup_name,
                        "Motiu": "Present a la classificació però no trobat a l'input",
                    }
                )

    print(f"Equips no utilitzats a la classificació (TOTAL): {len(unused_classification_teams)}")
    if len(unused_classification_teams) > 0:
        df_unused = pd.DataFrame(unused_classification_teams)
        print(df_unused)

    for idx, row in df.iterrows():
        if "Posició Classificació Num" not in df.columns or pd.isna(row["Posició Classificació Num"]):
            df.at[idx, "Posició Classificació Num"] = 10
        if "Posició Classificació" not in df.columns or pd.isna(row["Posició Classificació"]):
            df.at[idx, "Posició Classificació"] = False

    print("DataFrame amb posicions de classificació assignades:")
    print(df[["Nom", "Nom Lliga", "Modalitat", "Categoria", "Subcategoria", "Posició Classificació Num"]])

    return df, missing_classifications, unused_classification_teams
