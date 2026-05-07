import tempfile
import unittest
import zipfile
from pathlib import Path

from certificats.services.archive import create_certificats_zip


class CreateCertificatsZipTests(unittest.TestCase):
    def test_zip_contains_result_dir_contents_without_temp_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            result_dir = base_dir / "Certificats_generats"
            nested_dir = result_dir / "PA"
            nested_dir.mkdir(parents=True)
            (result_dir / "root.txt").write_text("root", encoding="utf-8")
            (nested_dir / "nested.txt").write_text("nested", encoding="utf-8")

            destination_dir = base_dir / "media" / "certificats"

            zip_path = create_certificats_zip(result_dir, destination_dir)

            self.assertEqual(Path(zip_path).suffix, ".zip")
            self.assertTrue(Path(zip_path).is_file())
            self.assertEqual(Path(zip_path).parent, destination_dir)

            with zipfile.ZipFile(zip_path) as created_zip:
                names = {name.replace("\\", "/") for name in created_zip.namelist()}

            self.assertEqual(names, {"root.txt", "PA/nested.txt"})

    def test_zip_names_do_not_collide_between_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            result_dir = base_dir / "Certificats_generats"
            result_dir.mkdir()
            (result_dir / "certificate.txt").write_text("safe fixture", encoding="utf-8")

            destination_dir = base_dir / "media" / "certificats"

            first_zip = Path(create_certificats_zip(result_dir, destination_dir))
            second_zip = Path(create_certificats_zip(result_dir, destination_dir))

            self.assertTrue(first_zip.exists())
            self.assertTrue(second_zip.exists())
            self.assertNotEqual(first_zip.name, second_zip.name)


if __name__ == "__main__":
    unittest.main()
