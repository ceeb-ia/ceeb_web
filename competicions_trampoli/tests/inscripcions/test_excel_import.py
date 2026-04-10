import importlib
import json
from pathlib import Path
from datetime import date, datetime
from io import BytesIO

from django.test import TestCase
from django.urls import resolve, reverse
from openpyxl import Workbook

from ...models import Competicio, CompeticioMembership, Inscripcio, InscripcioMedia
from ...services.inscripcions.import_excel import importar_inscripcions_excel
from ...views.inscripcions.listing import _serialize_listing_media_item
from ..base import _BaseTrampoliDataMixin



class InscripcionsExcelImportServiceTests(_BaseTrampoliDataMixin, TestCase):
    def _build_workbook_file(self, headers, row):
        wb = Workbook()
        ws = wb.active
        ws.append(headers)
        ws.append(row)
        content = BytesIO()
        wb.save(content)
        content.seek(0)
        return content

    def test_import_accepts_datetime_values_in_extra_columns_and_real_headers(self):
        comp = self._create_competicio("Comp Import Excel")
        fitxer = self._build_workbook_file(
            [
                "Id Adjunt",
                "Id InscripciÃ³",
                "Lliga",
                "Grup",
                "Club",
                "Nom",
                "Cognoms",
                "Data Naixement",
                "CompeticiÃ³",
                "Estat inscripciÃ³",
                "Data IntroducciÃ³",
                "Modalitat",
                "Categoria",
                "SubCategoria",
                "Link Adjunt",
            ],
            [
                991,
                225,
                "CEEB",
                "A",
                "Club Example",
                "Laia",
                "Garcia",
                date(2014, 5, 3),
                "CompeticiÃ³ prova",
                "Pendent",
                datetime(2026, 4, 5, 10, 30, 15),
                "Individual",
                "BenjamÃ­",
                "Nivell 1",
                "https://example.invalid/file",
            ],
        )

        result = importar_inscripcions_excel(fitxer, comp)

        self.assertEqual(result["errors"], 0)
        self.assertEqual(result["creats"], 1)

        inscripcio = Inscripcio.objects.get(competicio=comp)
        self.assertEqual(inscripcio.nom_i_cognoms, "Laia Garcia")
        self.assertEqual(inscripcio.entitat, "Club Example")
        self.assertEqual(inscripcio.categoria, "BenjamÃ­")
        self.assertEqual(inscripcio.subcategoria, "Nivell 1")
        self.assertEqual(inscripcio.data_naixement, date(2014, 5, 3))
        self.assertEqual(inscripcio.extra["data_introduccio"], "2026-04-05T10:30:15")
        self.assertEqual(inscripcio.extra["modalitat"], "Individual")
        self.assertEqual(inscripcio.extra["excel__grup"], "A")


