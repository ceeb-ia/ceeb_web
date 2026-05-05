import tempfile
import unittest
from pathlib import Path

from calendaritzacions.application.storage import finalize_result_path


class StorageTests(unittest.TestCase):
    def test_finalize_result_path_moves_file_into_media_root(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            source = tmp / "result.xlsx"
            media = tmp / "media"
            source.write_text("data", encoding="utf-8")
            logs = []

            final_path = finalize_result_path(source, logs, media_root=str(media))

            final = Path(final_path)
            self.assertEqual(final.parent, media)
            self.assertEqual(final.name, "result.xlsx")
            self.assertTrue(final.exists())
            self.assertFalse(source.exists())
            self.assertTrue(any("mogut a MEDIA_ROOT" in item for item in logs))


if __name__ == "__main__":
    unittest.main()
