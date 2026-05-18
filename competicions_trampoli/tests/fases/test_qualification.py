from copy import deepcopy

from django.test import TestCase

from ..base import _BaseTrampoliDataMixin
from ...models.classificacions import ClassificacioConfig
from ...models.competicio import CompeticioAparellFase, FasePartitionState, ProgramUnitSlot, QualificationRun
from ...models.scoring import ScoreEntry
from ...services.classificacions.compute import DEFAULT_SCHEMA
from ...services.fases import (
    QualificationError,
    SlotSubject,
    apply_qualification,
    confirm_qualification_partition,
    create_program_unit_from_subjects,
    preview_qualification,
    qualification_is_stale,
    record_qualification_preview,
)


class QualificationServiceTests(_BaseTrampoliDataMixin, TestCase):
    def setUp(self):
        self.competicio = self._create_competicio("Comp qualificacio")
        self.aparell = self._create_aparell("TRA_Q", "Trampoli")
        self.comp_aparell = self._create_comp_aparell(self.competicio, self.aparell)
        self.ins_1 = self._create_inscripcio(self.competicio, "Participant 1", ordre=1)
        self.ins_2 = self._create_inscripcio(self.competicio, "Participant 2", ordre=2)
        self.ins_3 = self._create_inscripcio(self.competicio, "Participant 3", ordre=3)

    def _schema_for_app(self, *, phase=None):
        schema = deepcopy(DEFAULT_SCHEMA)
        schema["particions"] = []
        schema["particions_v2"] = []
        schema["puntuacio"]["aparells"] = {"mode": "seleccionar", "ids": [self.comp_aparell.id]}
        schema["puntuacio"]["camps_per_aparell"] = {str(self.comp_aparell.id): ["total"]}
        schema["puntuacio"]["agregacio_camps"] = "sum"
        schema["puntuacio"]["exercicis"] = {"mode": "tots", "best_n": 1, "index": 1, "ids": []}
        schema["puntuacio"]["agregacio_exercicis"] = "sum"
        schema["puntuacio"]["agregacio_aparells"] = "sum"
        schema["puntuacio"]["ordre"] = "desc"
        if phase is not None:
            schema["scope"] = {"mode": "phase", "fase_id": phase.id}
        return schema

    def _source_cfg(self, *, phase=None):
        return ClassificacioConfig.objects.create(
            competicio=self.competicio,
            nom="Classificacio origen",
            activa=True,
            ordre=1,
            tipus="individual",
            schema=self._schema_for_app(phase=phase),
        )

    def _dest_phase(self, cfg, *, name="Final", tie_policy="classification_order"):
        return CompeticioAparellFase.objects.create(
            competicio=self.competicio,
            comp_aparell=self.comp_aparell,
            nom=name,
            codi=name.upper(),
            ordre=2,
            config={
                "source": {
                    "classificacio_id": cfg.id,
                    "classificacio_nom": cfg.nom,
                    "tipus": cfg.tipus,
                },
                "cut": {
                    "mode": "top_n",
                    "qualifiers_count": 2,
                    "reserve_count": 1,
                    "partition_mode": "global",
                    "tie_policy": tie_policy,
                    "unit_capacity": 2,
                    "unit_name_template": "{fase} - {particio}",
                },
            },
        )

    def _score(self, inscripcio, total, *, phase=None):
        return ScoreEntry.objects.create(
            competicio=self.competicio,
            inscripcio=inscripcio,
            exercici=1,
            comp_aparell=self.comp_aparell,
            fase=phase,
            total=total,
            inputs={"total": total},
            outputs={"total": total},
        )

    def test_preview_and_apply_freezes_classification_cut_into_slots(self):
        self._score(self.ins_1, 9.0)
        self._score(self.ins_2, 8.0)
        self._score(self.ins_3, 7.0)
        cfg = self._source_cfg()
        dest = self._dest_phase(cfg)

        preview = preview_qualification(dest)

        self.assertEqual(preview.summary()["candidates"], 3)
        self.assertEqual(preview.summary()["reserves"], 1)
        self.assertEqual(preview.summary()["units"], 2)

        applied = apply_qualification(dest)
        dest.refresh_from_db()

        self.assertEqual(applied.snapshot_hash, preview.snapshot_hash)
        self.assertEqual(dest.estat, CompeticioAparellFase.Estat.GENERATED)
        self.assertEqual(dest.program_units.count(), 2)
        slots = list(
            ProgramUnitSlot.objects
            .filter(unit__fase=dest)
            .order_by("unit__ordre", "slot_index")
        )
        self.assertEqual(
            [(slot.subject_kind, slot.subject_id, slot.status, slot.source_position) for slot in slots],
            [
                ("inscripcio", self.ins_1.id, ProgramUnitSlot.Status.FILLED, 1),
                ("inscripcio", self.ins_2.id, ProgramUnitSlot.Status.FILLED, 2),
                ("inscripcio", self.ins_3.id, ProgramUnitSlot.Status.RESERVE, 3),
            ],
        )
        self.assertTrue(all(slot.source_classificacio_id == cfg.id for slot in slots))
        self.assertIn("qualification", dest.config)
        self.assertEqual(QualificationRun.objects.filter(fase=dest, status=QualificationRun.Status.APPLIED).count(), 1)
        state = FasePartitionState.objects.get(fase=dest, partition_key="global")
        self.assertEqual(state.status, FasePartitionState.Status.GENERATED)
        self.assertEqual(state.qualification_run.source_classificacio_id, cfg.id)

        confirmed = confirm_qualification_partition(dest, "global")
        dest.refresh_from_db()
        self.assertEqual(confirmed.status, FasePartitionState.Status.CONFIRMED)
        self.assertEqual(dest.estat, CompeticioAparellFase.Estat.CONFIRMED)

    def test_record_preview_persists_previewed_run_without_generating_slots(self):
        self._score(self.ins_1, 9.0)
        self._score(self.ins_2, 8.0)
        cfg = self._source_cfg()
        dest = self._dest_phase(cfg)

        preview = record_qualification_preview(dest)

        self.assertEqual(preview.summary()["candidates"], 3)
        self.assertEqual(dest.program_units.count(), 0)
        run = QualificationRun.objects.get(fase=dest)
        self.assertEqual(run.status, QualificationRun.Status.PREVIEWED)
        self.assertEqual(run.snapshot_hash, preview.snapshot_hash)

    def test_apply_requires_persistent_source_phase_to_be_closed_or_confirmed(self):
        source_phase = CompeticioAparellFase.objects.create(
            competicio=self.competicio,
            comp_aparell=self.comp_aparell,
            nom="Semifinal",
            codi="SEMI",
            ordre=1,
        )
        create_program_unit_from_subjects(
            fase=source_phase,
            nom="Semifinal",
            subjects=[SlotSubject("inscripcio", self.ins_1.id), SlotSubject("inscripcio", self.ins_2.id)],
        )
        self._score(self.ins_1, 9.0, phase=source_phase)
        self._score(self.ins_2, 8.0, phase=source_phase)
        cfg = self._source_cfg(phase=source_phase)
        dest = self._dest_phase(cfg)

        preview = preview_qualification(dest)
        self.assertTrue(any("Cal confirmar-la o tancar-la" in warning for warning in preview.warnings))
        with self.assertRaises(QualificationError):
            apply_qualification(dest)

        source_phase.estat = CompeticioAparellFase.Estat.CLOSED
        source_phase.save(update_fields=["estat", "updated_at"])

        apply_qualification(dest)
        self.assertEqual(dest.program_units.count(), 2)

    def test_source_changes_mark_generated_phase_as_stale_without_rewriting_slots(self):
        score_1 = self._score(self.ins_1, 9.0)
        self._score(self.ins_2, 8.0)
        self._score(self.ins_3, 7.0)
        cfg = self._source_cfg()
        dest = self._dest_phase(cfg)
        apply_qualification(dest)
        original_slots = list(
            ProgramUnitSlot.objects
            .filter(unit__fase=dest)
            .order_by("unit__ordre", "slot_index")
            .values_list("subject_id", "status")
        )

        self.assertFalse(qualification_is_stale(dest))
        score_1.total = 1.0
        score_1.save(update_fields=["total", "updated_at"])

        self.assertTrue(qualification_is_stale(dest))
        self.assertEqual(
            list(
                ProgramUnitSlot.objects
                .filter(unit__fase=dest)
                .order_by("unit__ordre", "slot_index")
                .values_list("subject_id", "status")
            ),
            original_slots,
        )

    def test_manual_decision_marks_tied_cut_as_pending_decision(self):
        self._score(self.ins_1, 9.0)
        self._score(self.ins_2, 8.0)
        self._score(self.ins_3, 8.0)
        cfg = self._source_cfg()
        dest = self._dest_phase(cfg, tie_policy="manual_decision")
        dest.config["cut"]["reserve_count"] = 0
        dest.save(update_fields=["config", "updated_at"])

        preview = preview_qualification(dest)

        self.assertEqual(preview.summary()["pending_decision"], 2)
        applied = apply_qualification(dest)
        self.assertEqual(applied.summary()["pending_decision"], 2)
        statuses = list(
            ProgramUnitSlot.objects
            .filter(unit__fase=dest)
            .order_by("unit__ordre", "slot_index")
            .values_list("subject_id", "status")
        )
        self.assertEqual(statuses[0], (self.ins_1.id, ProgramUnitSlot.Status.FILLED))
        self.assertIn((self.ins_2.id, ProgramUnitSlot.Status.PENDING_DECISION), statuses)
        self.assertIn((self.ins_3.id, ProgramUnitSlot.Status.PENDING_DECISION), statuses)

    def test_include_all_at_cut_keeps_all_tied_cut_rows_filled(self):
        self._score(self.ins_1, 9.0)
        self._score(self.ins_2, 8.0)
        self._score(self.ins_3, 8.0)
        cfg = self._source_cfg()
        dest = self._dest_phase(cfg, tie_policy="include_all_at_cut")
        dest.config["cut"]["reserve_count"] = 0
        dest.save(update_fields=["config", "updated_at"])

        apply_qualification(dest)

        statuses = list(
            ProgramUnitSlot.objects
            .filter(unit__fase=dest)
            .exclude(status=ProgramUnitSlot.Status.EMPTY)
            .order_by("unit__ordre", "slot_index")
            .values_list("subject_id", "status")
        )
        self.assertEqual(len(statuses), 3)
        self.assertTrue(all(status == ProgramUnitSlot.Status.FILLED for _subject_id, status in statuses))

    def test_regeneration_requires_confirmation_for_manual_or_locked_slots(self):
        self._score(self.ins_1, 9.0)
        self._score(self.ins_2, 8.0)
        self._score(self.ins_3, 7.0)
        cfg = self._source_cfg()
        dest = self._dest_phase(cfg)
        apply_qualification(dest)
        slot = ProgramUnitSlot.objects.filter(unit__fase=dest).order_by("id").first()
        slot.locked = True
        slot.save(update_fields=["locked", "updated_at"])

        with self.assertRaises(QualificationError):
            apply_qualification(dest, replace_existing=True)

        apply_qualification(dest, replace_existing=True, allow_replace_protected=True)
        self.assertEqual(QualificationRun.objects.filter(fase=dest, status=QualificationRun.Status.APPLIED).count(), 2)
