import argparse
import httpx
import asyncio
import sys
import pandas as pd
#from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET

# ---------------------------------------------------------------------------
#  UTILITATS GENERALS
# ---------------------------------------------------------------------------

def fetch_async(url, params=None, headers=None, timeout=10.0):
    async def _run():
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url, params=params, headers=headers)
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "").lower()

            # JSON
            if "json" in content_type:
                try:
                    return resp.json()
                except ValueError:
                    return resp.text

            # Altres formats (HTML / XML / text)
            return resp.text

    return asyncio.run(_run())


# ---------------------------------------------------------------------------
#  PARSING HTML DE JEEB (si es necessita)
# ---------------------------------------------------------------------------

def parse_matches_from_html(html):
    soup = BeautifulSoup(html, "lxml")
    rows = []

    for node in soup.select(".fixture, .match-row, .partit, article"):
        date = node.select_one(".date, .dia, .data")
        time = node.select_one(".time, .hora")
        home = node.select_one(".home, .equip-local, .equip")
        away = node.select_one(".away, .equip-visitant")
        place = node.select_one(".place, .pista, .camp")
        rows.append({
            "date": date.get_text(strip=True) if date else None,
            "time": time.get_text(strip=True) if time else None,
            "home": home.get_text(strip=True) if home else None,
            "away": away.get_text(strip=True) if away else None,
            "place": place.get_text(strip=True) if place else None,
        })

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
#  FETCH + PARSING XML CEEB
# ---------------------------------------------------------------------------

CEEB_AUTH_USER = "competi"
CEEB_AUTH_PASS = "a252c08e6ca437ee4e6d9eabe79d49b3"


async def fetch_ceeb_async(p2: str, p5: str, timeout: float = 15.0, verify: bool = False):
    url = f"https://ceeb.playoffinformatica.com/serveisLliga.php?p1=lliga&type=xml&p2={p2}&p3=24&p4=FS1&p5={p5}"

    async with httpx.AsyncClient(timeout=timeout, verify=verify, auth=(CEEB_AUTH_USER, CEEB_AUTH_PASS)) as client:
        try:
            resp = await client.get(url)
        except Exception as exc:
            print(f"Error de connexió: {exc}")
            return None

        if resp.status_code != 200:
            print(f"Error HTTP {resp.status_code}")
            return None

        try:
            root = ET.fromstring(resp.content)
            return root
        except ET.ParseError as exc:
            print(f"Error parsejant XML: {exc}")
            return None


# ---------------------------------------------------------------------------
#  ESTRUCTURACIÓ DEL XML EN DICCIONARIS
# ---------------------------------------------------------------------------

def parse_team(equip_node):
    return {child.tag: child.text for child in equip_node}


def parse_ceeb_xml(root):
    data = {"grups": []}

    for grup in root.findall(".//grup_classificacions"):
        grup_data = {}

        # Info del grup
        info = grup.find("info_lliga")
        if info is not None:
            grup_data["info"] = {c.tag: c.text for c in info}

        # Equips classificació general
        all_block = grup.find("prt_class_all")
        if all_block is not None:
            grup_data["equips_all"] = [parse_team(eq) for eq in all_block.findall("equip")]

        # Equips sense classificació
        sense_block = grup.find("prt_class_senseForaclass")
        if sense_block is not None:
            grup_data["equips_sense_fora"] = [parse_team(eq) for eq in sense_block.findall("equip")]

        # Ordre de classificació
        ordre_block = grup.find("prt_class_ordre")
        if ordre_block is not None:
            order = []
            i = 0
            while True:
                pos = ordre_block.find(f"pos_{i}")
                if pos is None:
                    break
                order.append(pos.text)
                i += 1
            grup_data["ordre"] = order

        data["grups"].append(grup_data)

    return data


# ---------------------------------------------------------------------------
#  EXPORTACIÓ A DATAFRAME (opcional)
# ---------------------------------------------------------------------------

def xml_to_dataframe(parsed, grup=None) -> pd.DataFrame:
    if grup is not None:
        # Ens quedem amb el grup indicat
        for g in parsed.get("grups", []):
            #print("Revisant grup:", g.get("info", {}).get("nomGrup"))
            if g.get("info", {}).get("nomGrup") == grup:
                nou_parsed = {"grups": [g]}
                #print("Grup seleccionat:", grup)
    
    if not nou_parsed.get("grups", []):
        raise ValueError("No s'ha trobat el grup especificat.")
    frames = []

    for grup in nou_parsed.get("grups", []):
        equips = grup.get("equips_all", [])
        if equips:
            df = pd.DataFrame(equips)
            df["nomGrup"] = grup.get("info", {}).get("nomGrup", None)
            frames.append(df)

    if frames:
        return pd.concat(frames, ignore_index=True)

    return pd.DataFrame()


# ---------------------------------------------------------------------------
#  MAIN SCRIPT
# ---------------------------------------------------------------------------
# p2=idModalitat, p3=numJornada, p4=fase
def main(action = "ceeb", p2=None, p5=None, url=None):
    # MODE JEED --------------------------------------------------------------
    if action == "jeeb":
        html = fetch_async(url)
        df = parse_matches_from_html(html)
        print(df)
        sys.exit(0)

    # MODE CEEB --------------------------------------------------------------
    if action == "ceeb":
        root = asyncio.run(fetch_ceeb_async(p2, p5))
        if root is None:
            sys.exit(1)

        parsed = parse_ceeb_xml(root)
        df = xml_to_dataframe(parsed)
        print("\nDADES ESTRUCTURADES:\n", parsed)
        print("\nDATAFRAME RESULTANT:\n", df)

        # Fem df dels diferents grups
        for i, grup in enumerate(parsed.get("grups", [])):
            equips = grup.get("equips_all", [])
            if equips:
                df_grup = pd.DataFrame(equips)
                print("Camps:", df_grup.columns.tolist())
                print(f"\nDATAFRAME GRUP {i}:\n", df_grup)

        # El passem a Excel (opcional)
        with pd.ExcelWriter("ceeb_output.xlsx") as writer:
            df.to_excel(writer, sheet_name="TotsEquips", index=False)
            for i, grup in enumerate(parsed.get("grups", [])):
                equips = grup.get("equips_all", [])
                if equips:
                    df_grup = pd.DataFrame(equips)
                    df_grup.to_excel(writer, sheet_name=f"Grup_{i}", index=False)





if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Consulta i estructura dades de JEED/CEEB")
    sub = parser.add_subparsers(dest="action")
    # CEEB
    p_ceeb = sub.add_parser("ceeb", help="Consulta i processa XML del CEEB")
    p_ceeb.add_argument("--p2", default=6, help="idCategoria")
    p_ceeb.add_argument("--p5", default="SMIX", help="sexe/subcategoria")
    args = parser.parse_args()

    main(args.action, args.p2, args.p5)