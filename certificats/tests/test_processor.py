import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from certificats.services import processor


class ProcessarCertificatsTests(unittest.TestCase):
    def test_missing_input_dir_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "output"
            missing_input_dir = Path(tmp) / "missing"

            result = processor.processar_certificats(missing_input_dir, output_dir)

            self.assertIsNone(result)

    def test_empty_input_dir_returns_none_without_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            input_dir = base_dir / "input"
            output_dir = base_dir / "output"
            input_dir.mkdir()

            result = processor.processar_certificats(input_dir, output_dir)

            self.assertIsNone(result)
            self.assertFalse((output_dir / "Certificats_generats").exists())

    def test_non_pdf_files_are_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            input_dir = base_dir / "input"
            output_dir = base_dir / "output"
            input_dir.mkdir()
            (input_dir / "notes.txt").write_text("not a pdf", encoding="utf-8")

            result = processor.processar_certificats(input_dir, output_dir)

            self.assertIsNone(result)

    def test_pdf_is_copied_to_specialty_folder_with_mocked_reader(self):
        sample_text = "\n".join(
            [
                "0",
                "1",
                "2",
                "3",
                "4",
                "5",
                "NOM PROVA",
                "7",
                "8",
                "Especialitat: JOC",
            ]
        )

        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            input_dir = base_dir / "input"
            output_dir = base_dir / "output"
            input_dir.mkdir()
            pdf_path = input_dir / "entrada.pdf"
            pdf_path.write_bytes(b"%PDF-test")

            with patch.object(processor, "llegir_pdf", return_value=sample_text):
                result = processor.processar_certificats(input_dir, output_dir)

            self.assertEqual(result, output_dir / "Certificats_generats")
            self.assertTrue(
                (output_dir / "Certificats_generats" / "JIE" / "Certificado_NOM_PROVA.pdf").is_file()
            )

    def test_extracts_pa_certificate_name_from_line_before_nif(self):
        sample_text = "\n".join(
            [
                "RR",
                "",
                "CERTIFICAT D'ASSISTENCIA",
                "",
                "AINA ANTONIJOAN CLARAMUNT",
                "",
                "Amb NIF numero 23844984X, ha superat la formacio que s'indica,",
                "organitzada per l'Escola Catalana de l'Esport,",
                "Curs de procediments, tecniques i recursos de primers auxilis",
            ]
        )

        nom, especialitat = processor.extreure_info(sample_text)

        self.assertEqual(nom, "AINA ANTONIJOAN CLARAMUNT")
        self.assertEqual(especialitat, "PA")

    def test_detects_course_type_before_defaulting_to_pa(self):
        sample_text = "\n".join(
            [
                "CERTIFICAT D'ASSISTENCIA",
                "NOM ALUMNE PROVA",
                "Amb NIF numero 12345678Z, ha superat la formacio que s'indica,",
                "Curs de gestio i organitzacio",
            ]
        )

        nom, especialitat = processor.extreure_info(sample_text)

        self.assertEqual(nom, "NOM ALUMNE PROVA")
        self.assertEqual(especialitat, "GIO")


if __name__ == "__main__":
    unittest.main()
