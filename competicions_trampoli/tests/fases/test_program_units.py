from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase

from ..base import _BaseTrampoliDataMixin
from ...models.inscripcions import GrupCompeticio, Inscripcio
from ...models.competicio import CompeticioAparellFase, ProgramUnit, ProgramUnitSlot
from ...models.scoring import ScoreEntry, TeamScoreEntry
from ...services.fases import (
    SlotSubject,
    create_program_unit_from_subjects,
    create_program_unit_with_empty_slots,
    create_units_from_base_groups,
    create_units_one_per_partition,
    create_units_split_by_capacity,
    ensure_default_phase_for_comp_aparell,
)


class ProgramUnitModelTests(_BaseTrampoliDataMixin, TestCase):
    def setUp(self):
        self.competicio = self._create_competicio("Comp program units")
        self.aparell = self._create_aparell("TRA", "Trampoli")
        self.comp_aparell = self._create_comp_aparell(self.competicio, self.aparell)
        self.fase = ensure_default_phase_for_comp_aparell(self.comp_aparell)

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
        prelim = self.fase
        final = CompeticioAparellFase.objects.create(
            competicio=self.competicio,
            comp_aparell=self.comp_aparell,
            parent=prelim,
            nom="Final",
            codi="FINAL",
            ordre=2,
        )

        prelim_unit = create_program_unit_from_subjects(
            fase=prelim,
            nom="Preliminar",
            subjects=[SlotSubject("inscripcio", inscripcio.id)],
        )
        final_unit = create_program_unit_from_subjects(
            fase=final,
            nom="Final",
            subjects=[SlotSubject("inscripcio", inscripcio.id)],
        )

        self.assertNotEqual(prelim_unit.id, final_unit.id)
        self.assertEqual(prelim_unit.slots.get().subject_id, inscripcio.id)
        self.assertEqual(final_unit.slots.get().subject_id, inscripcio.id)

    def test_score_entry_contract_still_has_no_phase_or_program_unit(self):
        score_fields = {field.name for field in ScoreEntry._meta.get_fields()}
        team_score_fields = {field.name for field in TeamScoreEntry._meta.get_fields()}

        self.assertNotIn("fase", score_fields)
        self.assertNotIn("program_unit", score_fields)
        self.assertNotIn("fase", team_score_fields)
        self.assertNotIn("program_unit", team_score_fields)


class ProgramUnitGenerationTests(_BaseTrampoliDataMixin, TestCase):
    def setUp(self):
        self.competicio = self._create_competicio("Comp generators")
        self.aparell = self._create_aparell("TRA", "Trampoli")
        self.comp_aparell = self._create_comp_aparell(self.competicio, self.aparell)
        self.fase = ensure_default_phase_for_comp_aparell(self.comp_aparell)

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

    def test_create_units_from_base_groups_fills_inscripcio_slots(self):
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

        units = create_units_from_base_groups(self.fase)

        self.assertEqual(len(units), 1)
        unit = units[0]
        self.assertEqual(unit.nom, "Grup A")
        self.assertEqual(unit.tipus, ProgramUnit.Tipus.GROUP)
        self.assertEqual(unit.capacity, 2)
        self.assertEqual(
            list(unit.slots.order_by("slot_index").values_list("subject_kind", "subject_id", "status")),
            [
                ("inscripcio", first.id, ProgramUnitSlot.Status.FILLED),
                ("inscripcio", second.id, ProgramUnitSlot.Status.FILLED),
            ],
        )
