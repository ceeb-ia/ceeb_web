from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

import pandas as pd

from calendaritzacions.second_phase.ceeb_client import parse_ceeb_xml, xml_to_dataframe


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


class CeebClientTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
