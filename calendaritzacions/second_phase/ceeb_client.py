"""CEEB classification client boundary for second-phase enrichment."""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET

import httpx
import pandas as pd


CEEB_AUTH_USER_ENV = "CEEB_AUTH_USER"
CEEB_AUTH_PASS_ENV = "CEEB_AUTH_PASS"


def _resolve_ceeb_auth(user: str | None = None, password: str | None = None):
    resolved_user = user if user is not None else os.getenv(CEEB_AUTH_USER_ENV)
    resolved_password = password if password is not None else os.getenv(CEEB_AUTH_PASS_ENV)
    if not resolved_user or not resolved_password:
        return None
    return (resolved_user, resolved_password)


async def fetch_ceeb_async(
    p2: str,
    p5: str,
    timeout: float = 15.0,
    verify: bool = False,
    user: str | None = None,
    password: str | None = None,
):
    """Fetch CEEB XML classification data."""
    auth = _resolve_ceeb_auth(user=user, password=password)
    if auth is None:
        print(f"Falten credencials CEEB: configura {CEEB_AUTH_USER_ENV} i {CEEB_AUTH_PASS_ENV}")
        return None

    url = f"https://ceeb.playoffinformatica.com/serveisLliga.php?p1=lliga&type=xml&p2={p2}&p3=24&p4=FS1&p5={p5}"

    async with httpx.AsyncClient(timeout=timeout, verify=verify, auth=auth) as client:
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


def parse_team(equip_node):
    return {child.tag: child.text for child in equip_node}


def parse_ceeb_xml(root):
    """Parse a CEEB XML root into the legacy classification structure."""
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


def xml_to_dataframe(parsed, grup=None):
    """Convert parsed CEEB classification data into the legacy frame/list shape."""
    nou_parsed = None
    if grup is not None:
        for g in parsed.get("grups", []):
            if g.get("info", {}).get("nomGrup") == grup:
                nou_parsed = {"grups": [g]}
    else:
        nou_parsed = parsed

    frames = []
    if not nou_parsed.get("grups", []):
        return frames

    for grup in nou_parsed.get("grups", []):
        equips = grup.get("equips_all", [])
        if equips:
            df = pd.DataFrame(equips)
            df["nomGrup"] = grup.get("info", {}).get("nomGrup", None)
            frames.append(df)

    if frames:
        print("frames", frames)
        return frames

    return pd.DataFrame()
