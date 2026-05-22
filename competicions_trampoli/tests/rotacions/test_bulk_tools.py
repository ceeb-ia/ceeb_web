import json

from django.test import TestCase
from django.urls import reverse

from ..base import _BaseTrampoliDataMixin
from ...models import GrupCompeticio, Inscripcio
from ...models.competicio import Aparell
from ...models.rotacions import (
    RotacioAssignacio,
    RotacioAssignacioGrup,
    RotacioEstacio,
    RotacioFranja,
)


class RotacionsBulkToolsTests(_BaseTrampoliDataMixin, TestCase):
    def setUp(self):
        self.competicio = self._create_competicio("Bulk rotacions")
        self._login_competicio_user(self.competicio, username_prefix="bulk_rotacions")
        self.aparell = self._create_aparell("TRA_BULK", "Trampoli")
        self.comp_aparell = self._create_comp_aparell(self.competicio, self.aparell)
        self.estacio = RotacioEstacio.objects.create(
            competicio=self.competicio,
            tipus="aparell",
            comp_aparell=self.comp_aparell,
            ordre=1,
        )
        self.f1 = RotacioFranja.objects.create(
            competicio=self.competicio,
            hora_inici="09:00",
            hora_fi="09:20",
            ordre=1,
            ordre_visual=1,
            titol="F1",
        )
        self.f2 = RotacioFranja.objects.create(
            competicio=self.competicio,
            hora_inici="09:20",
            hora_fi="09:40",
            ordre=2,
            ordre_visual=2,
            titol="F2",
        )
        self.group = GrupCompeticio.objects.create(
            competicio=self.competicio,
            display_num=1,
            nom="Grup 1",
        )
        Inscripcio.objects.create(
            competicio=self.competicio,
            nom_i_cognoms="Participant 1",
            grup_competicio=self.group,
            grup=1,
        )
        self.assignacio = RotacioAssignacio.objects.create(
            competicio=self.competicio,
            franja=self.f1,
            estacio=self.estacio,
        )
        RotacioAssignacioGrup.objects.create(assignacio=self.assignacio, grup=self.group, ordre=1)

    def _post_json(self, route_name, payload):
        return self.client.post(
            reverse(route_name, kwargs={"pk": self.competicio.id}),
            data=json.dumps(payload),
            content_type="application/json",
        )

    def test_bulk_clear_removes_assignments_not_franges(self):
        response = self._post_json("rotacions_franges_bulk_clear", {"franja_ids": [self.f1.id]})

        self.assertEqual(response.status_code, 200)
        self.assertFalse(RotacioAssignacio.objects.filter(franja=self.f1).exists())
        self.assertTrue(RotacioFranja.objects.filter(pk=self.f1.id).exists())

    def test_bulk_update_color_and_type(self):
        response = self._post_json(
            "rotacions_franges_bulk_update",
            {"franja_ids": [self.f2.id], "color_fons": "#dbeafe", "tipus": RotacioFranja.TIPUS_BREAK},
        )

        self.assertEqual(response.status_code, 200)
        self.f2.refresh_from_db()
        self.assertEqual(self.f2.color_fons, "#DBEAFE")
        self.assertEqual(self.f2.tipus, RotacioFranja.TIPUS_BREAK)

    def test_bulk_update_blocks_non_competitive_type_when_assigned(self):
        response = self._post_json(
            "rotacions_franges_bulk_update",
            {"franja_ids": [self.f1.id], "tipus": RotacioFranja.TIPUS_BREAK},
        )

        self.assertEqual(response.status_code, 400)
        self.f1.refresh_from_db()
        self.assertEqual(self.f1.tipus, RotacioFranja.TIPUS_COMPETITION)

    def test_bulk_shift_preserves_duration(self):
        response = self._post_json(
            "rotacions_franges_bulk_shift",
            {"franja_ids": [self.f2.id], "minutes": 10, "confirm_reorder": True},
        )

        self.assertEqual(response.status_code, 200)
        self.f2.refresh_from_db()
        self.assertEqual(str(self.f2.hora_inici), "09:30:00")
        self.assertEqual(str(self.f2.hora_fi), "09:50:00")

    def test_bulk_shift_pushes_following_competitive_franges(self):
        preview = self._post_json(
            "rotacions_franges_bulk_shift",
            {"franja_ids": [self.f1.id], "minutes": 10, "preview_only": True},
        )
        self.assertEqual(preview.status_code, 200)
        self.assertTrue(preview.json()["requires_confirmation"])
        self.assertEqual(
            [(item["franja_id"], item["new_start"], item["new_end"]) for item in preview.json()["affected"]],
            [
                (self.f1.id, "09:10", "09:30"),
                (self.f2.id, "09:30", "09:50"),
            ],
        )

        response = self._post_json(
            "rotacions_franges_bulk_shift",
            {"franja_ids": [self.f1.id], "minutes": 10, "confirm_reorder": True},
        )

        self.assertEqual(response.status_code, 200)
        self.f1.refresh_from_db()
        self.f2.refresh_from_db()
        self.assertEqual(str(self.f1.hora_inici), "09:10:00")
        self.assertEqual(str(self.f1.hora_fi), "09:30:00")
        self.assertEqual(str(self.f2.hora_inici), "09:30:00")
        self.assertEqual(str(self.f2.hora_fi), "09:50:00")

    def test_bulk_duration_pushes_following_competitive_franges(self):
        preview = self._post_json(
            "rotacions_franges_bulk_duration",
            {"franja_ids": [self.f1.id], "minutes": 10, "preview_only": True},
        )

        self.assertEqual(preview.status_code, 200)
        self.assertTrue(preview.json()["requires_confirmation"])
        self.assertEqual(
            [(item["franja_id"], item["new_start"], item["new_end"]) for item in preview.json()["affected"]],
            [
                (self.f1.id, "09:00", "09:30"),
                (self.f2.id, "09:30", "09:50"),
            ],
        )

        response = self._post_json(
            "rotacions_franges_bulk_duration",
            {"franja_ids": [self.f1.id], "minutes": 10, "confirm_reorder": True},
        )

        self.assertEqual(response.status_code, 200)
        self.f1.refresh_from_db()
        self.f2.refresh_from_db()
        self.assertEqual(str(self.f1.hora_inici), "09:00:00")
        self.assertEqual(str(self.f1.hora_fi), "09:30:00")
        self.assertEqual(str(self.f2.hora_inici), "09:30:00")
        self.assertEqual(str(self.f2.hora_fi), "09:50:00")

    def test_bulk_duration_reflows_selected_adjacent_franges(self):
        response = self._post_json(
            "rotacions_franges_bulk_duration",
            {"franja_ids": [self.f1.id, self.f2.id], "minutes": 10, "confirm_reorder": True},
        )

        self.assertEqual(response.status_code, 200)
        self.f1.refresh_from_db()
        self.f2.refresh_from_db()
        self.assertEqual(str(self.f1.hora_inici), "09:00:00")
        self.assertEqual(str(self.f1.hora_fi), "09:30:00")
        self.assertEqual(str(self.f2.hora_inici), "09:30:00")
        self.assertEqual(str(self.f2.hora_fi), "10:00:00")

    def test_bulk_duration_rejects_non_positive_duration(self):
        response = self._post_json(
            "rotacions_franges_bulk_duration",
            {"franja_ids": [self.f1.id], "minutes": -20, "confirm_reorder": True},
        )

        self.assertEqual(response.status_code, 400)
        self.f1.refresh_from_db()
        self.assertEqual(str(self.f1.hora_inici), "09:00:00")
        self.assertEqual(str(self.f1.hora_fi), "09:20:00")

    def test_bulk_duplicate_pushes_following_competitive_franges(self):
        preview = self._post_json(
            "rotacions_franges_bulk_duplicate",
            {"franja_ids": [self.f1.id], "offset_minutes": 0, "preview_only": True},
        )
        self.assertEqual(preview.status_code, 200)
        self.assertTrue(preview.json()["requires_confirmation"])
        self.assertEqual(preview.json()["affected"][0]["franja_id"], None)
        self.assertEqual(preview.json()["affected"][0]["new_start"], "09:20")
        self.assertEqual(preview.json()["affected"][1]["franja_id"], self.f2.id)
        self.assertEqual(preview.json()["affected"][1]["new_start"], "09:40")

        response = self._post_json(
            "rotacions_franges_bulk_duplicate",
            {"franja_ids": [self.f1.id], "offset_minutes": 0, "confirm_reorder": True},
        )

        self.assertEqual(response.status_code, 200)
        self.f2.refresh_from_db()
        clone = RotacioFranja.objects.exclude(pk__in=[self.f1.id, self.f2.id]).get(competicio=self.competicio)
        self.assertEqual(str(clone.hora_inici), "09:20:00")
        self.assertEqual(str(clone.hora_fi), "09:40:00")
        self.assertEqual(str(self.f2.hora_inici), "09:40:00")
        self.assertEqual(str(self.f2.hora_fi), "10:00:00")

    def test_bulk_duplicate_compacts_non_contiguous_selection_before_pushing_following_franges(self):
        f3 = RotacioFranja.objects.create(
            competicio=self.competicio,
            hora_inici="09:40",
            hora_fi="10:00",
            ordre=3,
            ordre_visual=3,
            titol="F3",
        )
        f4 = RotacioFranja.objects.create(
            competicio=self.competicio,
            hora_inici="10:00",
            hora_fi="10:20",
            ordre=4,
            ordre_visual=4,
            titol="F4",
        )

        preview = self._post_json(
            "rotacions_franges_bulk_duplicate",
            {"franja_ids": [self.f1.id, f3.id], "offset_minutes": 0, "preview_only": True},
        )

        self.assertEqual(preview.status_code, 200)
        self.assertEqual(
            [(item["franja_id"], item["new_start"], item["new_end"]) for item in preview.json()["affected"]],
            [
                (None, "10:00", "10:20"),
                (None, "10:20", "10:40"),
                (f4.id, "10:40", "11:00"),
            ],
        )

        response = self._post_json(
            "rotacions_franges_bulk_duplicate",
            {"franja_ids": [self.f1.id, f3.id], "offset_minutes": 0, "confirm_reorder": True},
        )

        self.assertEqual(response.status_code, 200)
        f4.refresh_from_db()
        clones = list(
            RotacioFranja.objects
            .filter(competicio=self.competicio, titol__endswith="copia")
            .order_by("hora_inici", "id")
        )
        self.assertEqual([(str(fr.hora_inici), str(fr.hora_fi)) for fr in clones], [
            ("10:00:00", "10:20:00"),
            ("10:20:00", "10:40:00"),
        ])
        self.assertEqual(str(f4.hora_inici), "10:40:00")
        self.assertEqual(str(f4.hora_fi), "11:00:00")

    def test_note_save_and_validation_endpoint(self):
        note_response = self._post_json(
            "rotacions_franja_note_save",
            {"franja_id": self.f1.id, "nota_interna": "Preparar entrada"},
        )
        validation_response = self._post_json("rotacions_validate_program", {})

        self.assertEqual(note_response.status_code, 200)
        self.f1.refresh_from_db()
        self.assertEqual(self.f1.nota_interna, "Preparar entrada")
        self.assertEqual(validation_response.status_code, 200)
        self.assertIn("warnings", validation_response.json())

    def test_bulk_duplicate_can_copy_assignments(self):
        response = self._post_json(
            "rotacions_franges_bulk_duplicate",
            {
                "franja_ids": [self.f1.id],
                "offset_minutes": 30,
                "copy_assignments": True,
                "confirm_reorder": True,
            },
        )

        self.assertEqual(response.status_code, 200)
        new_franja = RotacioFranja.objects.exclude(pk__in=[self.f1.id, self.f2.id]).get(competicio=self.competicio)
        copied = RotacioAssignacio.objects.get(competicio=self.competicio, franja=new_franja, estacio=self.estacio)
        self.assertEqual(list(copied.grup_links.values_list("grup_id", flat=True)), [self.group.id])
