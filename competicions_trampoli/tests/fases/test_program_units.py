from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase

from ..base import _BaseTrampoliDataMixin
from ...models.competicio import CompeticioAparellFase, ProgramUnit, ProgramUnitSlot
from ...models.scoring import ScoreEntry, TeamScoreEntry
from ...services.fases import (
    SlotSubject,
    create_program_unit_from_subjects,
    create_program_unit_with_empty_slots,
    create_units_one_per_partition,
    create_units_split_by_capacity,
)


class ProgramUnitModelTests(_BaseTrampoliDataMixin, TestCase):
    def setUp(self):
        self.competicio = self._create_competicio("Comp program units")
        self.aparell = self._create_aparell("TRA", "Trampoli")
        self.comp_aparell = self._create_comp_aparell(self.competicio, self.aparell)
        self.fase = CompeticioAparellFase.objects.create(
            competicio=self.competicio,
            comp_aparell=self.comp_aparell,
            nom="Semifinal",
            codi="SEMI",
            ordre=2,
        )

    def test_can_create_program_unit_with_empty_slots(self):
        unit = create_program_unit_with_empty_slots(
            fase=self.fase,
            nom="Semifinal Infantil F",
            capacity=3,
            tipus=ProgramUnit.Tipus.BLOCK,
            partition_key="categoria=Infantil|subcategoria=F",
            partition_values={"categoria": "Infantil", "subcategoria": "F"},
        )

        self.assertEqual(unit.fase_id, self.fase.id)
        self.assertEqual(unit.capacity, 3)
        self.assertEqual(unit.slots.count(), 3)
        self.assertEqual(
            list(unit.slots.order_by("slot_index").values_list("slot_index", "status")),
            [
                (1, ProgramUnitSlot.Status.EMPTY),
                (2, ProgramUnitSlot.Status.EMPTY),
                (3, ProgramUnitSlot.Status.EMPTY),
            ],
        )

    def test_slot_requires_subject_when_filled_or_reserve(self):
        unit = create_program_unit_with_empty_slots(fase=self.fase, nom="Final", capacity=1)
        slot = unit.slots.first()
        slot.status = ProgramUnitSlot.Status.FILLED

        with self.assertRaises(ValidationError) as ctx:
            slot.full_clean()
        self.assertIn("subject_id", ctx.exception.message_dict)

    def test_empty_slot_rejects_subject(self):
        unit = create_program_unit_with_empty_slots(fase=self.fase, nom="Final", capacity=1)
        slot = unit.slots.first()
        slot.subject_kind = "inscripcio"
        slot.subject_id = 123

        with self.assertRaises(ValidationError) as ctx:
            slot.full_clean()
        self.assertIn("status", ctx.exception.message_dict)

    def test_unit_order_is_unique_inside_phase(self):
        create_program_unit_with_empty_slots(fase=self.fase, nom="Bloc 1", capacity=1, ordre=1)

        with self.assertRaises(IntegrityError):
            create_program_unit_with_empty_slots(fase=self.fase, nom="Bloc 2", capacity=1, ordre=1)

    def test_same_subject_can_exist_in_slots_of_different_phases(self):
        inscripcio = self._create_inscripcio(self.competicio, "Participant A")
        semifinal = self.fase
        final = CompeticioAparellFase.objects.create(
            competicio=self.competicio,
            comp_aparell=self.comp_aparell,
            parent=semifinal,
            nom="Final",
            codi="FINAL",
            ordre=3,
        )

        semifinal_unit = create_program_unit_from_subjects(
            fase=semifinal,
            nom="Semifinal",
            subjects=[SlotSubject("inscripcio", inscripcio.id)],
        )
        final_unit = create_program_unit_from_subjects(
            fase=final,
            nom="Final",
            subjects=[SlotSubject("inscripcio", inscripcio.id)],
        )

        self.assertNotEqual(semifinal_unit.id, final_unit.id)
        self.assertEqual(semifinal_unit.slots.get().subject_id, inscripcio.id)
        self.assertEqual(final_unit.slots.get().subject_id, inscripcio.id)

    def test_score_entry_contract_has_phase_but_no_program_unit(self):
        score_fields = {field.name for field in ScoreEntry._meta.get_fields()}
        team_score_fields = {field.name for field in TeamScoreEntry._meta.get_fields()}

        self.assertIn("fase", score_fields)
        self.assertNotIn("program_unit", score_fields)
        self.assertIn("fase", team_score_fields)
        self.assertNotIn("program_unit", team_score_fields)

    def test_same_inscripcio_can_have_legacy_and_phase_scores_for_same_exercise(self):
        inscripcio = self._create_inscripcio(self.competicio, "Participant A")

        legacy = ScoreEntry.objects.create(
            competicio=self.competicio,
            inscripcio=inscripcio,
            exercici=1,
            comp_aparell=self.comp_aparell,
            total=7.5,
        )
        phase_score = ScoreEntry.objects.create(
            competicio=self.competicio,
            inscripcio=inscripcio,
            exercici=1,
            comp_aparell=self.comp_aparell,
            fase=self.fase,
            total=8.5,
        )

        self.assertIsNone(legacy.fase_id)
        self.assertEqual(phase_score.fase_id, self.fase.id)


class ProgramUnitGenerationTests(_BaseTrampoliDataMixin, TestCase):
    def setUp(self):
        self.competicio = self._create_competicio("Comp generators")
        self.aparell = self._create_aparell("TRA", "Trampoli")
        self.comp_aparell = self._create_comp_aparell(self.competicio, self.aparell)
        self.fase = CompeticioAparellFase.objects.create(
            competicio=self.competicio,
            comp_aparell=self.comp_aparell,
            nom="Semifinal",
            codi="SEMI",
            ordre=2,
        )

    def test_create_units_one_per_partition(self):
        units = create_units_one_per_partition(
            fase=self.fase,
            default_capacity=4,
            partitions=[
                {"key": "cat=Infantil", "label": "Infantil", "values": {"categoria": "Infantil"}},
                {"key": "cat=Junior", "label": "Junior", "capacity": 2, "values": {"categoria": "Junior"}},
            ],
        )

        self.assertEqual(len(units), 2)
        self.assertEqual(units[0].capacity, 4)
        self.assertEqual(units[1].capacity, 2)
        self.assertEqual(units[0].slots.count(), 4)
        self.assertEqual(units[1].partition_values, {"categoria": "Junior"})

    def test_create_units_split_by_capacity(self):
        subjects = [
            SlotSubject("inscripcio", 101),
            SlotSubject("inscripcio", 102),
            SlotSubject("inscripcio", 103),
        ]

        units = create_units_split_by_capacity(
            fase=self.fase,
            label="Semifinal",
            subjects=subjects,
            max_capacity=2,
        )

        self.assertEqual(len(units), 2)
        self.assertEqual(units[0].slots.filter(status=ProgramUnitSlot.Status.FILLED).count(), 2)
        self.assertEqual(units[1].slots.filter(status=ProgramUnitSlot.Status.FILLED).count(), 1)
