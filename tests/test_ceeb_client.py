import asyncio
import os
from pathlib import Path
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

import pandas as pd

from calendaritzacions.second_phase.ceeb_client import fetch_ceeb_async, parse_ceeb_xml, xml_to_dataframe


ROOT = Path(__file__).resolve().parents[1]


TINY_CEEB_XML = """
<root>
  <grup_classificacions>
    <info_lliga>
      <nomGrup>Grup A</nomGrup>
      <nomLliga>Lliga 1</nomLliga>
    </info_lliga>
    <prt_class_all>
      <equip>
        <nom>Equip A</nom>
        <posicio>1</posicio>
        <punts>12</punts>
      </equip>
      <equip>
        <nom>Equip B</nom>
        <posicio>2</posicio>
        <punts>9</punts>
      </equip>
    </prt_class_all>
    <prt_class_senseForaclass>
      <equip>
        <nom>Equip Fora</nom>
      </equip>
    </prt_class_senseForaclass>
    <prt_class_ordre>
      <pos_0>punts</pos_0>
      <pos_1>average</pos_1>
    </prt_class_ordre>
  </grup_classificacions>
  <grup_classificacions>
    <info_lliga>
      <nomGrup>Grup B</nomGrup>
    </info_lliga>
    <prt_class_all>
      <equip>
        <nom>Equip C</nom>
        <posicio>1</posicio>
      </equip>
    </prt_class_all>
  </grup_classificacions>
</root>
"""


class FakeAsyncClient:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.requested_urls = []
        self.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def get(self, url):
        self.requested_urls.append(url)
        return FakeResponse()


class FakeResponse:
    status_code = 200
    content = b"<root />"


class CeebClientTests(unittest.TestCase):
    def setUp(self):
        FakeAsyncClient.instances.clear()

    def test_parse_ceeb_xml_preserves_legacy_shape(self):
        root = ET.fromstring(TINY_CEEB_XML)

        parsed = parse_ceeb_xml(root)

        self.assertEqual(len(parsed["grups"]), 2)
        self.assertEqual(parsed["grups"][0]["info"], {"nomGrup": "Grup A", "nomLliga": "Lliga 1"})
        self.assertEqual(
            parsed["grups"][0]["equips_all"],
            [
                {"nom": "Equip A", "posicio": "1", "punts": "12"},
                {"nom": "Equip B", "posicio": "2", "punts": "9"},
            ],
        )
        self.assertEqual(parsed["grups"][0]["equips_sense_fora"], [{"nom": "Equip Fora"}])
        self.assertEqual(parsed["grups"][0]["ordre"], ["punts", "average"])

    def test_xml_to_dataframe_returns_one_frame_per_group(self):
        parsed = parse_ceeb_xml(ET.fromstring(TINY_CEEB_XML))

        frames = xml_to_dataframe(parsed)

        self.assertEqual(len(frames), 2)
        self.assertEqual(frames[0]["nom"].tolist(), ["Equip A", "Equip B"])
        self.assertEqual(frames[0]["nomGrup"].tolist(), ["Grup A", "Grup A"])
        self.assertEqual(frames[1]["nom"].tolist(), ["Equip C"])
        self.assertEqual(frames[1]["nomGrup"].tolist(), ["Grup B"])

    def test_xml_to_dataframe_can_filter_by_group(self):
        parsed = parse_ceeb_xml(ET.fromstring(TINY_CEEB_XML))

        frames = xml_to_dataframe(parsed, grup="Grup B")

        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0]["nom"].tolist(), ["Equip C"])
        self.assertEqual(frames[0]["nomGrup"].tolist(), ["Grup B"])

    def test_xml_to_dataframe_returns_empty_frame_when_no_equips(self):
        parsed = {"grups": [{"info": {"nomGrup": "Buit"}}]}

        result = xml_to_dataframe(parsed)

        self.assertIsInstance(result, pd.DataFrame)
        self.assertTrue(result.empty)

    def test_ceeb_client_does_not_import_consulta_resultats(self):
        text = (ROOT / "calendaritzacions" / "second_phase" / "ceeb_client.py").read_text(encoding="utf-8")

        self.assertNotIn("consulta_resultats", text)

    def test_fetch_ceeb_async_uses_env_credentials(self):
        with patch.dict(os.environ, {"CEEB_AUTH_USER": "env-user", "CEEB_AUTH_PASS": "env-pass"}, clear=True):
            with patch("calendaritzacions.second_phase.ceeb_client.httpx.AsyncClient", FakeAsyncClient):
                root = asyncio.run(fetch_ceeb_async("phase", "group", timeout=1.5, verify=True))

        self.assertEqual(root.tag, "root")
        self.assertEqual(FakeAsyncClient.instances[0].kwargs["auth"], ("env-user", "env-pass"))
        self.assertEqual(FakeAsyncClient.instances[0].kwargs["timeout"], 1.5)
        self.assertTrue(FakeAsyncClient.instances[0].kwargs["verify"])
        self.assertIn("p2=phase", FakeAsyncClient.instances[0].requested_urls[0])
        self.assertIn("p5=group", FakeAsyncClient.instances[0].requested_urls[0])

    def test_fetch_ceeb_async_arguments_override_env_credentials(self):
        with patch.dict(os.environ, {"CEEB_AUTH_USER": "env-user", "CEEB_AUTH_PASS": "env-pass"}, clear=True):
            with patch("calendaritzacions.second_phase.ceeb_client.httpx.AsyncClient", FakeAsyncClient):
                root = asyncio.run(fetch_ceeb_async("phase", "group", user="arg-user", password="arg-pass"))

        self.assertEqual(root.tag, "root")
        self.assertEqual(FakeAsyncClient.instances[0].kwargs["auth"], ("arg-user", "arg-pass"))

    def test_fetch_ceeb_async_skips_request_without_credentials(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch("calendaritzacions.second_phase.ceeb_client.httpx.AsyncClient", FakeAsyncClient):
                root = asyncio.run(fetch_ceeb_async("phase", "group"))

        self.assertIsNone(root)
        self.assertEqual(FakeAsyncClient.instances, [])


if __name__ == "__main__":
    unittest.main()
