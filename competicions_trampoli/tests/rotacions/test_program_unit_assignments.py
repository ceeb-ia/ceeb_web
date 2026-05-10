import json

from django.test import TestCase
from django.urls import reverse

from ..base import _BaseTrampoliDataMixin
from ...models.competicio import Aparell, CompeticioAparellFase, ProgramUnit
from ...models.rotacions import (
    RotacioAssignacio,
    RotacioAssignacioGrup,
    RotacioAssignacioProgramUnit,
    RotacioAssignacioSerieEquip,
    RotacioEstacio,
    RotacioFranja,
)
from ...models.scoring import SerieEquip


class RotacionsProgramUnitAssignmentTests(_BaseTrampoliDataMixin, TestCase):
    def setUp(self):
        self.competicio = self._create_competicio("Comp rotacions unitats")
        self.user = self._login_competicio_user(
            self.competicio,
            username_prefix="rotacions_program_units",
        )
        self.aparell = self._create_aparell("TRA_PU", "Trampoli")
        self.comp_aparell = self._create_comp_aparell(self.competicio, self.aparell)
        self.fase = CompeticioAparellFase.objects.create(
            competicio=self.competicio,
            comp_aparell=self.comp_aparell,
            nom="Semifinal",
            codi="SEMI",
            ordre=2,
        )
        self.unit = ProgramUnit.objects.create(
            fase=self.fase,
            nom="Semifinal Grup A",
            tipus=ProgramUnit.Tipus.BLOCK,
            ordre=1,
            capacity=6,
        )
        self.franja = RotacioFranja.objects.create(
            competicio=self.competicio,
            hora_inici="09:00",
            hora_fi="10:00",
            ordre=1,
            ordre_visual=1,
            titol="Franja 1",
        )
        self.estacio = RotacioEstacio.objects.create(
            competicio=self.competicio,
            tipus="aparell",
            comp_aparell=self.comp_aparell,
            ordre=1,
        )

    def _post_json(self, url_name, payload):
        return self.client.post(
            reverse(url_name, kwargs={"pk": self.competicio.id}),
            data=json.dumps(payload),
            content_type="application/json",
        )

    def test_planner_sidebar_includes_program_units_with_pu_keys(self):
        response = self.client.get(reverse("rotacions_planner", kwargs={"pk": self.competicio.id}))

        self.assertEqual(response.status_code, 200)
        sidebar = json.loads(response.context["group_sidebar_json"])
        item = next((entry for entry in sidebar if entry["key"] == f"pu:{self.unit.id}"), None)
        self.assertIsNotNone(item)
        self.assertEqual(item["kind"], "program_unit")
        self.assertEqual(item["id"], self.unit.id)
        self.assertEqual(item["app_id"], self.comp_aparell.id)
        self.assertIn("Semifinal Grup A", item["label"])

    def test_save_persists_program_unit_link(self):
        response = self._post_json(
            "rotacions_save",
            {
                "cells": [
                    {
                        "franja": self.franja.id,
                        "estacio": self.estacio.id,
                        "items": [f"pu:{self.unit.id}"],
                    }
                ],
            },
        )

        self.assertEqual(response.status_code, 200)
        assignacio = RotacioAssignacio.objects.get(
            competicio=self.competicio,
            franja=self.franja,
            estacio=self.estacio,
        )
        self.assertEqual(
            list(assignacio.program_unit_links.values_list("program_unit_id", "ordre")),
            [(self.unit.id, 1)],
        )
        self.assertFalse(RotacioAssignacioGrup.objects.filter(assignacio=assignacio).exists())
        self.assertFalse(RotacioAssignacioSerieEquip.objects.filter(assignacio=assignacio).exists())

    def test_planner_grid_returns_program_unit_keys(self):
        assignacio = RotacioAssignacio.objects.create(
            competicio=self.competicio,
            franja=self.franja,
            estacio=self.estacio,
        )
        RotacioAssignacioProgramUnit.objects.create(
            assignacio=assignacio,
            program_unit=self.unit,
            ordre=1,
        )

        response = self.client.get(reverse("rotacions_planner", kwargs={"pk": self.competicio.id}))

        self.assertEqual(response.status_code, 200)
        grid = json.loads(response.context["grid_json"])
        self.assertEqual(grid[str(self.franja.id)][str(self.estacio.id)], [f"pu:{self.unit.id}"])

    def test_program_unit_support_does_not_change_legacy_group_or_series_assignments(self):
        inscripcio = self._create_inscripcio(self.competicio, "Participant 1", grup=1)
        group_id = inscripcio.grup_competicio_id
        team_app = self._create_aparell("TEAM_PU", "Equip")
        team_app.competition_unit = Aparell.CompetitionUnit.TEAM
        team_app.save(update_fields=["competition_unit"])
        team_comp_aparell = self._create_comp_aparell(self.competicio, team_app, ordre=2)
        team_estacio = RotacioEstacio.objects.create(
            competicio=self.competicio,
            tipus="aparell",
            comp_aparell=team_comp_aparell,
            ordre=2,
        )
        serie = SerieEquip.objects.create(
            competicio=self.competicio,
            comp_aparell=team_comp_aparell,
            display_num=1,
            nom="Serie 1",
        )

        response = self._post_json(
            "rotacions_save",
            {
                "cells": [
                    {"franja": self.franja.id, "estacio": self.estacio.id, "items": [f"g:{group_id}"]},
                    {"franja": self.franja.id, "estacio": team_estacio.id, "items": [f"s:{serie.id}"]},
                ],
            },
        )

        self.assertEqual(response.status_code, 200)
        individual_assignacio = RotacioAssignacio.objects.get(
            competicio=self.competicio,
            franja=self.franja,
            estacio=self.estacio,
        )
        team_assignacio = RotacioAssignacio.objects.get(
            competicio=self.competicio,
            franja=self.franja,
            estacio=team_estacio,
        )
        self.assertEqual(list(individual_assignacio.grup_links.values_list("grup_id", flat=True)), [group_id])
        self.assertEqual(list(team_assignacio.serie_links.values_list("serie_id", flat=True)), [serie.id])
        self.assertFalse(individual_assignacio.program_unit_links.exists())
        self.assertFalse(team_assignacio.program_unit_links.exists())
