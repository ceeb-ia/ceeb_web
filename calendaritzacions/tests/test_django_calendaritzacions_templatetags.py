import importlib.util
import unittest


HAS_DJANGO = importlib.util.find_spec("django") is not None


@unittest.skipUnless(HAS_DJANGO, "django not installed")
class DjangoCalendarizationTemplateTagTests(unittest.TestCase):
    def test_json_pretty_and_dict_get_and_basename(self):
        from calendaritzacions.django.templatetags.calendaritzacions_json import audit_cell, basename, dict_get, json_pretty

        self.assertIn('"a": 1', json_pretty({"a": 1}))
        self.assertEqual(dict_get({"x": 2}, "x"), 2)
        self.assertEqual(dict_get({}, "missing"), None)
        self.assertEqual(audit_cell(["Equip A", "Equip B"]), "Equip A · Equip B")
        self.assertEqual(basename("/tmp/output.xlsx"), "output.xlsx")


if __name__ == "__main__":
    unittest.main()
