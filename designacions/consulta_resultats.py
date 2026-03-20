import argparse
import asyncio
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass

import httpx
import pandas as pd
from bs4 import BeautifulSoup


def fetch_async(url, params=None, headers=None, timeout=10.0):
    async def _run():
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url, params=params, headers=headers)
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "").lower()

            if "json" in content_type:
                try:
                    return resp.json()
                except ValueError:
                    return resp.text

            return resp.text

    return asyncio.run(_run())


def parse_matches_from_html(html):
    soup = BeautifulSoup(html, "lxml")
    rows = []

    for node in soup.select(".fixture, .match-row, .partit, article"):
        date = node.select_one(".date, .dia, .data")
        time = node.select_one(".time, .hora")
        home = node.select_one(".home, .equip-local, .equip")
        away = node.select_one(".away, .equip-visitant")
        place = node.select_one(".place, .pista, .camp")
        rows.append(
            {
                "date": date.get_text(strip=True) if date else None,
                "time": time.get_text(strip=True) if time else None,
                "home": home.get_text(strip=True) if home else None,
                "away": away.get_text(strip=True) if away else None,
                "place": place.get_text(strip=True) if place else None,
            }
        )

    return pd.DataFrame(rows)


CEEB_AUTH_USER = "competi"
CEEB_AUTH_PASS = "a252c08e6ca437ee4e6d9eabe79d49b3"
DEFAULT_CEEB_TIMEOUT = 15.0
DEFAULT_CEEB_RETRIES = 3
DEFAULT_CEEB_BACKOFF_SECONDS = 1.0


@dataclass
class CEEBFetchResult:
    root: ET.Element | None
    from_cache: bool = False
    attempts: int = 0
    error: str | None = None


def _ceeb_cache_key(p2: str, p5: str, fase: str) -> tuple[str, str, str]:
    return (str(p2), str(p5), str(fase).upper())


def _build_ceeb_url(p2: str, p5: str, fase: str) -> str:
    return f"https://ceeb.playoffinformatica.com/serveisLliga.php?p1=lliga&type=xml&p2={p2}&p3=24&p4={fase}&p5={p5}"


async def _fetch_ceeb_once(client: httpx.AsyncClient, url: str) -> ET.Element:
    resp = await client.get(url)
    resp.raise_for_status()
    return ET.fromstring(resp.content)


async def fetch_ceeb_classification_async(
    p2: str,
    p5: str,
    *,
    timeout: float = DEFAULT_CEEB_TIMEOUT,
    verify: bool = False,
    fase: str = "FS1",
    cache: dict | None = None,
    max_retries: int = DEFAULT_CEEB_RETRIES,
    backoff_seconds: float = DEFAULT_CEEB_BACKOFF_SECONDS,
) -> CEEBFetchResult:
    fase = str(fase or "FS1").strip().upper()
    if fase not in {"FS1", "FS2"}:
        return CEEBFetchResult(root=None, error=f"Fase no valida: {fase}. Ha de ser FS1 o FS2.")

    cache_key = _ceeb_cache_key(p2, p5, fase)
    if cache is not None and cache_key in cache:
        cached = cache[cache_key]
        return CEEBFetchResult(
            root=cached.get("root"),
            from_cache=True,
            attempts=0,
            error=cached.get("error"),
        )

    url = _build_ceeb_url(p2, p5, fase)
    attempts = 0
    last_error = None

    async with httpx.AsyncClient(timeout=timeout, verify=verify, auth=(CEEB_AUTH_USER, CEEB_AUTH_PASS)) as client:
        for attempt in range(1, max_retries + 1):
            attempts = attempt
            try:
                root = await _fetch_ceeb_once(client, url)
                result = CEEBFetchResult(root=root, attempts=attempts)
                if cache is not None:
                    cache[cache_key] = {"root": root, "error": None}
                return result
            except httpx.TimeoutException as exc:
                last_error = f"Timeout de connexio: {exc}"
            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code if exc.response is not None else "?"
                last_error = f"Error HTTP {status_code}"
            except httpx.HTTPError as exc:
                last_error = f"Error de connexio: {exc}"
            except ET.ParseError as exc:
                last_error = f"Error parsejant XML: {exc}"

            if attempt < max_retries:
                await asyncio.sleep(backoff_seconds * attempt)

    result = CEEBFetchResult(root=None, attempts=attempts, error=last_error)
    if cache is not None:
        cache[cache_key] = {"root": None, "error": last_error}
    return result


async def fetch_ceeb_async(
    p2: str,
    p5: str,
    timeout: float = DEFAULT_CEEB_TIMEOUT,
    verify: bool = False,
    fase: str = "FS1",
) -> ET.Element | None:
    result = await fetch_ceeb_classification_async(
        p2,
        p5,
        timeout=timeout,
        verify=verify,
        fase=fase,
    )
    if result.error:
        print(result.error)
    return result.root


def parse_team(equip_node):
    return {child.tag: child.text for child in equip_node}


def parse_ceeb_xml(root):
    data = {"grups": []}

    for grup in root.findall(".//grup_classificacions"):
        grup_data = {}

        info = grup.find("info_lliga")
        if info is not None:
            grup_data["info"] = {c.tag: c.text for c in info}

        all_block = grup.find("prt_class_all")
        if all_block is not None:
            grup_data["equips_all"] = [parse_team(eq) for eq in all_block.findall("equip")]

        sense_block = grup.find("prt_class_senseForaclass")
        if sense_block is not None:
            grup_data["equips_sense_fora"] = [parse_team(eq) for eq in sense_block.findall("equip")]

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


def xml_to_dataframe(parsed, grup=None) -> pd.DataFrame:
    nou_parsed = parsed
    if grup is not None:
        nou_parsed = {"grups": []}
        for g in parsed.get("grups", []):
            if g.get("info", {}).get("nomGrup") == grup:
                nou_parsed = {"grups": [g]}

    if not nou_parsed.get("grups", []):
        return pd.DataFrame()
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


def main(action="ceeb", p2=None, p5=None, url=None):
    if action == "jeeb":
        html = fetch_async(url)
        df = parse_matches_from_html(html)
        print(df)
        sys.exit(0)

    if action == "ceeb":
        root = asyncio.run(fetch_ceeb_async(p2, p5))
        if root is None:
            sys.exit(1)

        parsed = parse_ceeb_xml(root)
        df = xml_to_dataframe(parsed)
        print("\nDADES ESTRUCTURADES:\n", parsed)
        print("\nDATAFRAME RESULTANT:\n", df)

        for i, grup in enumerate(parsed.get("grups", [])):
            equips = grup.get("equips_all", [])
            if equips:
                df_grup = pd.DataFrame(equips)
                print("Camps:", df_grup.columns.tolist())
                print(f"\nDATAFRAME GRUP {i}:\n", df_grup)

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
    p_ceeb = sub.add_parser("ceeb", help="Consulta i processa XML del CEEB")
    p_ceeb.add_argument("--p2", default=6, help="idCategoria")
    p_ceeb.add_argument("--p5", default="SMIX", help="sexe/subcategoria")
    args = parser.parse_args()

    main(args.action, args.p2, args.p5)
