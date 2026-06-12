from copy import deepcopy
from datetime import date

from django.test import TestCase

from ..base import _BaseTrampoliDataMixin
from ...forms import PhaseSourceCutForm
from ...models.classificacions import ClassificacioConfig
from ...models.competicio import CompeticioAparellFase, FasePartitionState, ProgramUnit, ProgramUnitSlot, QualificationRun
from ...models.scoring import ScoreEntry
from ...services.classificacions.compute import DEFAULT_SCHEMA
from ...services.fases import (
    CIRCULAR_SOURCE_PHASE_MESSAGE,
    QualificationError,
    SlotSubject,
    apply_group_plan,
    apply_qualification,
    confirm_qualification_partition,
    create_program_unit_from_subjects,
    preview_group_plan,
    preview_qualification,
    qualification_is_stale,
    record_qualification_preview,
)
from ...services.fases.planner import configure_phase_source_cut


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

    def _source_cut_config(self, cfg, *, tie_policy="classification_order"):
        return {
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
        }

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

    def test_preview_rejects_classification_scoped_to_same_phase(self):
        dest = CompeticioAparellFase.objects.create(
            competicio=self.competicio,
            comp_aparell=self.comp_aparell,
            nom="Semifinal",
            codi="SEMI",
            ordre=1,
        )
        cfg = self._source_cfg(phase=dest)
        dest.config = self._source_cut_config(cfg)
        dest.save(update_fields=["config", "updated_at"])
        create_program_unit_from_subjects(
            fase=dest,
            nom="Semifinal",
            subjects=[SlotSubject("inscripcio", self.ins_1.id), SlotSubject("inscripcio", self.ins_2.id)],
        )

        with self.assertRaisesMessage(QualificationError, CIRCULAR_SOURCE_PHASE_MESSAGE):
            preview_qualification(dest)

    def test_group_plan_rejects_classification_scoped_to_same_phase(self):
        dest = CompeticioAparellFase.objects.create(
            competicio=self.competicio,
            comp_aparell=self.comp_aparell,
            nom="Semifinal",
            codi="SEMI",
            ordre=1,
        )
        cfg = self._source_cfg(phase=dest)
        dest.config = self._source_cut_config(cfg)
        dest.save(update_fields=["config", "updated_at"])

        with self.assertRaisesMessage(QualificationError, CIRCULAR_SOURCE_PHASE_MESSAGE):
            preview_group_plan(dest)

    def test_configure_source_cut_rejects_classification_scoped_to_same_phase(self):
        dest = CompeticioAparellFase.objects.create(
            competicio=self.competicio,
            comp_aparell=self.comp_aparell,
            nom="Semifinal",
            codi="SEMI",
            ordre=1,
        )
        cfg = self._source_cfg(phase=dest)
        form = PhaseSourceCutForm(
            {
                "classificacio": str(cfg.id),
                "cut_mode": PhaseSourceCutForm.CUT_MODE_TOP_N,
                "qualifiers_count": "2",
                "reserve_count": "0",
                "partition_mode": PhaseSourceCutForm.PARTITION_GLOBAL,
                "tie_policy": PhaseSourceCutForm.TIE_CLASSIFICATION_ORDER,
                "unit_capacity": "2",
                "unit_name_template": "{fase} - {particio}",
            },
            competicio=self.competicio,
        )
        self.assertTrue(form.is_valid(), form.errors)

        with self.assertRaisesMessage(QualificationError, CIRCULAR_SOURCE_PHASE_MESSAGE):
            configure_phase_source_cut(dest, form)

    def test_preview_and_apply_freezes_classification_cut_into_slots(self):
        self._score(self.ins_1, 9.0)
        self._score(self.ins_2, 8.0)
        self._score(self.ins_3, 7.0)
        cfg = self._source_cfg()
        dest = self._dest_phase(cfg)

        group_plan = preview_group_plan(dest)
        self.assertEqual(group_plan.summary()["units"], 1)
        self.assertEqual(group_plan.summary()["slots"], 2)
        apply_group_plan(dest)
        preview = preview_qualification(dest)

        self.assertEqual(preview.summary()["candidates"], 3)
        self.assertEqual(preview.summary()["reserves"], 1)
        self.assertEqual(preview.summary()["units"], 1)
        self.assertEqual(preview.summary()["slots"], 2)

        applied = apply_qualification(dest)
        dest.refresh_from_db()

        self.assertEqual(applied.snapshot_hash, preview.snapshot_hash)
        self.assertEqual(dest.estat, CompeticioAparellFase.Estat.GENERATED)
        self.assertEqual(dest.program_units.count(), 1)
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
            ],
        )
        self.assertTrue(all(slot.source_classificacio_id == cfg.id for slot in slots))
        self.assertIn("qualification", dest.config)
        run = QualificationRun.objects.get(fase=dest, status=QualificationRun.Status.APPLIED)
        self.assertIn("global", run.payload["reserves"])
        self.assertEqual(run.payload["reserves"]["global"][0]["subject_id"], self.ins_3.id)
        state = FasePartitionState.objects.get(fase=dest, partition_key="global")
        self.assertEqual(state.status, FasePartitionState.Status.GENERATED)
        self.assertEqual(state.qualification_run.source_classificacio_id, cfg.id)

        confirmed = confirm_qualification_partition(dest, "global")
        dest.refresh_from_db()
        self.assertEqual(confirmed.status, FasePartitionState.Status.CONFIRMED)
        self.assertEqual(dest.estat, CompeticioAparellFase.Estat.CONFIRMED)

    def test_group_plan_creates_empty_units_and_record_preview_does_not_fill_slots(self):
        self._score(self.ins_1, 9.0)
        self._score(self.ins_2, 8.0)
        cfg = self._source_cfg()
        dest = self._dest_phase(cfg)

        group_plan = apply_group_plan(dest)
        self.assertEqual(group_plan.summary()["units"], 1)
        self.assertEqual(dest.program_units.count(), 1)
        self.assertEqual(
            ProgramUnitSlot.objects.filter(unit__fase=dest, status=ProgramUnitSlot.Status.EMPTY).count(),
            2,
        )
        preview = record_qualification_preview(dest)

        self.assertEqual(preview.summary()["candidates"], 3)
        self.assertFalse(
            ProgramUnitSlot.objects.filter(unit__fase=dest).exclude(status=ProgramUnitSlot.Status.EMPTY).exists()
        )
        run = QualificationRun.objects.get(fase=dest)
        self.assertEqual(run.status, QualificationRun.Status.PREVIEWED)
        self.assertEqual(run.snapshot_hash, preview.snapshot_hash)

    def test_apply_qualification_requires_existing_group_units(self):
        self._score(self.ins_1, 9.0)
        self._score(self.ins_2, 8.0)
        cfg = self._source_cfg()
        dest = self._dest_phase(cfg)

        with self.assertRaisesMessage(QualificationError, "Grups"):
            apply_qualification(dest)

    def test_group_plan_by_count_excludes_reserves_from_unit_slots(self):
        self._score(self.ins_1, 9.0)
        self._score(self.ins_2, 8.0)
        self._score(self.ins_3, 7.0)
        cfg = self._source_cfg()
        dest = self._dest_phase(cfg)
        dest.config["cut"]["qualifiers_count"] = 2
        dest.config["cut"]["reserve_count"] = 1
        dest.config["group_plan_settings"] = {
            "split_mode": "by_count",
            "units_per_partition": 2,
            "unit_capacity": 8,
            "formation_strategy": "classification_order",
            "unit_name_template": "{fase} - {particio}",
        }
        dest.save(update_fields=["config", "updated_at"])

        preview = apply_group_plan(dest)

        self.assertEqual(preview.summary()["units"], 2)
        self.assertEqual(preview.summary()["slots"], 2)
        self.assertEqual(
            list(dest.program_units.order_by("ordre").values_list("capacity", flat=True)),
            [1, 1],
        )

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
        apply_group_plan(dest)

        preview = preview_qualification(dest)
        self.assertTrue(any("Cal confirmar-la o tancar-la" in warning for warning in preview.warnings))
        with self.assertRaises(QualificationError):
            apply_qualification(dest)

        source_phase.estat = CompeticioAparellFase.Estat.CLOSED
        source_phase.save(update_fields=["estat", "updated_at"])

        apply_qualification(dest)
        self.assertEqual(dest.program_units.count(), 1)

    def test_source_changes_mark_generated_phase_as_stale_without_rewriting_slots(self):
        score_1 = self._score(self.ins_1, 9.0)
        self._score(self.ins_2, 8.0)
        self._score(self.ins_3, 7.0)
        cfg = self._source_cfg()
        dest = self._dest_phase(cfg)
        apply_group_plan(dest)
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
        apply_group_plan(dest)

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
        apply_group_plan(dest)

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
        apply_group_plan(dest)
        apply_qualification(dest)
        slot = ProgramUnitSlot.objects.filter(unit__fase=dest).order_by("id").first()
        slot.locked = True
        slot.save(update_fields=["locked", "updated_at"])

        with self.assertRaises(QualificationError):
            apply_qualification(dest, replace_existing=True)

        apply_qualification(dest, replace_existing=True, allow_replace_protected=True)
        self.assertEqual(QualificationRun.objects.filter(fase=dest, status=QualificationRun.Status.APPLIED).count(), 2)

    def test_source_partitions_fill_matching_partition_units(self):
        self.ins_1.data_naixement = date(2009, 1, 1)
        self.ins_2.data_naixement = date(2010, 1, 1)
        self.ins_3.data_naixement = date(2009, 6, 1)
        self.ins_1.save(update_fields=["data_naixement"])
        self.ins_2.save(update_fields=["data_naixement"])
        self.ins_3.save(update_fields=["data_naixement"])
        self._score(self.ins_1, 9.0)
        self._score(self.ins_2, 8.0)
        self._score(self.ins_3, 7.0)

        schema = self._schema_for_app()
        schema["particions"] = ["any_naixement_forquilla"]
        schema["particions_v2"] = [
            {"code": "any_naixement_forquilla", "apply_mode": "all", "parent_values": []},
        ]
        schema["particions_config"] = {
            "any_naixement_forquilla": {
                "ranges": [
                    {"label": "2007-2009", "from_year": 2007, "to_year": 2009},
                    {"label": "2010-2012", "from_year": 2010, "to_year": 2012},
                ],
                "sense_data_label": "Sense data",
                "fora_rang_label": "Fora de forquilla",
            }
        }
        cfg = ClassificacioConfig.objects.create(
            competicio=self.competicio,
            nom="Classificacio per edat",
            activa=True,
            ordre=1,
            tipus="individual",
            schema=schema,
        )
        dest = self._dest_phase(cfg)
        dest.config["cut"]["partition_mode"] = "source_partitions"
        dest.config["cut"]["qualifiers_count"] = 1
        dest.config["cut"]["reserve_count"] = 0
        dest.config["cut"]["unit_capacity"] = 1
        dest.save(update_fields=["config", "updated_at"])

        apply_group_plan(dest)
        self.assertEqual(
            set(ProgramUnit.objects.filter(fase=dest).values_list("partition_key", flat=True)),
            {"any_naixement_forquilla:2007-2009", "any_naixement_forquilla:2010-2012"},
        )

        apply_qualification(dest)

        filled = list(
            ProgramUnitSlot.objects
            .filter(unit__fase=dest, status=ProgramUnitSlot.Status.FILLED)
            .order_by("unit__partition_key")
            .values_list("unit__partition_key", "source_particio_key", "subject_id")
        )
        self.assertEqual(
            filled,
            [
                ("any_naixement_forquilla:2007-2009", "any_naixement_forquilla:2007-2009", self.ins_1.id),
                ("any_naixement_forquilla:2010-2012", "any_naixement_forquilla:2010-2012", self.ins_2.id),
            ],
        )
