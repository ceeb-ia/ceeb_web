from django.test import TestCase
from django.urls import reverse

from ...models import CompeticioMembership
from ...models.competicio import CompeticioAparellFase, ProgramUnit, ProgramUnitSlot
from ...models.inscripcions import GrupCompeticio, Inscripcio
from ...models.scoring import ScoreEntry, TeamScoreEntry
from ...services.fases import create_program_unit_with_empty_slots, ensure_default_phase_for_comp_aparell
from ..base import _BaseTrampoliDataMixin


class FasesBasicPlannerTests(_BaseTrampoliDataMixin, TestCase):
    def setUp(self):
        self.competicio = self._create_competicio("Comp fases planner")
        self.user = self._login_competicio_user(
            self.competicio,
            role=CompeticioMembership.Role.OWNER,
            username_prefix="fases_planner_owner",
        )
        self.aparell = self._create_aparell("TRA_PLAN", "Trampoli", owner=self.user)
        self.comp_aparell = self._create_comp_aparell(self.competicio, self.aparell)
        self.fase = ensure_default_phase_for_comp_aparell(self.comp_aparell)

    def _planner_url(self):
        return reverse(
            "trampoli_aparell_fases",
            kwargs={"pk": self.competicio.id, "app_id": self.comp_aparell.id},
        )

    def test_planner_lists_default_phase_and_program_units_without_score_payloads(self):
        create_program_unit_with_empty_slots(
            fase=self.fase,
            nom="Bloc inicial",
            capacity=2,
            tipus=ProgramUnit.Tipus.BLOCK,
        )
        inscripcio = self._create_inscripcio(self.competicio, "Participant A")
        ScoreEntry.objects.create(
            competicio=self.competicio,
            inscripcio=inscripcio,
            comp_aparell=self.comp_aparell,
            exercici=1,
            inputs={"contract_marker": "score-inputs-must-not-leak"},
            outputs={"total": 9},
            total=9,
        )

        response = self.client.get(self._planner_url())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["competicio"], self.competicio)
        self.assertEqual(response.context["comp_aparell"], self.comp_aparell)
        self.assertIn(self.fase, list(response.context["phases"]))
        body = response.content.decode("utf-8")
        self.assertIn("Fase unica", body)
        self.assertIn("Bloc inicial", body)
        self.assertNotIn("score-inputs-must-not-leak", body)
        self.assertNotIn("scores", response.context)
        self.assertNotIn("team_scores", response.context)

    def test_aparell_list_links_to_phase_planner(self):
        response = self.client.get(reverse("trampoli_aparells_list", kwargs={"pk": self.competicio.id}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self._planner_url())
        self.assertContains(response, "Fases")

    def test_post_create_phase_creates_child_phase(self):
        response = self.client.post(
            self._planner_url(),
            data={
                "action": "create_phase",
                "parent": self.fase.id,
                "nom": "Final",
                "codi": "final",
                "ordre": 2,
                "estat": CompeticioAparellFase.Estat.PLANNED,
            },
        )

        self.assertEqual(response.status_code, 302)
        child = CompeticioAparellFase.objects.get(comp_aparell=self.comp_aparell, codi="FINAL")
        self.assertEqual(child.parent_id, self.fase.id)
        self.assertEqual(child.nom, "Final")

    def test_post_create_manual_unit_creates_empty_slots(self):
        response = self.client.post(
            self._planner_url(),
            data={
                "action": "create_manual_unit",
                "fase_id": self.fase.id,
                "nom": "Final Infantil F",
                "capacity": 3,
                "tipus": ProgramUnit.Tipus.CUSTOM,
                "partition_key": "categoria=Infantil|subcategoria=F",
            },
        )

        self.assertEqual(response.status_code, 302)
        unit = ProgramUnit.objects.get(fase=self.fase, nom="Final Infantil F")
        self.assertEqual(unit.capacity, 3)
        self.assertEqual(unit.slots.count(), 3)
        self.assertEqual(unit.slots.filter(status=ProgramUnitSlot.Status.EMPTY).count(), 3)

    def test_post_partition_unit_creates_partition_slots(self):
        response = self.client.post(
            self._planner_url(),
            data={
                "action": "create_partition_unit",
                "fase_id": self.fase.id,
                "label": "Infantil F",
                "key": "categoria=Infantil|subcategoria=F",
                "capacity": 4,
            },
        )

        self.assertEqual(response.status_code, 302)
        unit = ProgramUnit.objects.get(fase=self.fase, nom="Infantil F")
        self.assertEqual(unit.partition_key, "categoria=Infantil|subcategoria=F")
        self.assertEqual(unit.capacity, 4)
        self.assertEqual(unit.slots.count(), 4)

    def test_generate_from_base_groups_fills_slots_and_does_not_touch_scores(self):
        group = GrupCompeticio.objects.create(
            competicio=self.competicio,
            display_num=1,
            legacy_num=1,
            nom="Grup A",
        )
        first = Inscripcio.objects.create(
            competicio=self.competicio,
            nom_i_cognoms="Participant A",
            grup=1,
            grup_competicio=group,
            ordre_sortida=1,
        )
        second = Inscripcio.objects.create(
            competicio=self.competicio,
            nom_i_cognoms="Participant B",
            grup=1,
            grup_competicio=group,
            ordre_sortida=2,
        )
        score = ScoreEntry.objects.create(
            competicio=self.competicio,
            inscripcio=first,
            comp_aparell=self.comp_aparell,
            exercici=1,
            inputs={"individual_contract_marker": "keep"},
            outputs={"total": 9},
            total=9,
        )

        response = self.client.post(
            self._planner_url(),
            data={"action": "generate_from_base_groups", "fase_id": self.fase.id},
        )

        self.assertEqual(response.status_code, 302)
        unit = ProgramUnit.objects.get(fase=self.fase, nom="Grup A")
        self.assertEqual(
            list(unit.slots.order_by("slot_index").values_list("subject_kind", "subject_id", "status")),
            [
                ("inscripcio", first.id, ProgramUnitSlot.Status.FILLED),
                ("inscripcio", second.id, ProgramUnitSlot.Status.FILLED),
            ],
        )
        self.assertEqual(ScoreEntry.objects.count(), 1)
        self.assertEqual(TeamScoreEntry.objects.count(), 0)
        score.refresh_from_db()
        self.assertEqual(score.inputs, {"individual_contract_marker": "keep"})
