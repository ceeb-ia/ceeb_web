from copy import deepcopy

from django.test import TestCase

from ..base import _BaseTrampoliDataMixin
from ...models.classificacions import ClassificacioConfig
from ...models.competicio import CompeticioAparellFase
from ...models.scoring import ScoreEntry
from ...services.classificacions.compute import DEFAULT_SCHEMA, compute_classificacio
from ...services.classificacions.runtime import prepare_schema_for_persistence
from ...services.classificacions.validation import validate_schema_for_competicio
from ...services.fases import SlotSubject, create_program_unit_from_subjects


class ClassificacioPhaseScopeTests(_BaseTrampoliDataMixin, TestCase):
    def setUp(self):
        self.competicio = self._create_competicio("Comp classificacio fase")
        self.aparell_a = self._create_aparell("TRA", "Trampoli")
        self.aparell_b = self._create_aparell("DMT", "Doble minitramp")
        self.comp_app_a = self._create_comp_aparell(self.competicio, self.aparell_a, ordre=1)
        self.comp_app_b = self._create_comp_aparell(self.competicio, self.aparell_b, ordre=2)
        self.fase_a = CompeticioAparellFase.objects.create(
            competicio=self.competicio,
            comp_aparell=self.comp_app_a,
            nom="Semifinal",
            codi="SEMI",
            ordre=2,
        )
        self.fase_b = CompeticioAparellFase.objects.create(
            competicio=self.competicio,
            comp_aparell=self.comp_app_b,
            nom="Final DMT",
            codi="FINAL",
            ordre=3,
        )
        self.ins_a = self._create_inscripcio(self.competicio, "Participant A", ordre=1)
        self.ins_b = self._create_inscripcio(self.competicio, "Participant B", ordre=2)

    def _schema_for_apps(self, comp_apps, *, scope=None):
        comp_apps = list(comp_apps)
        schema = deepcopy(DEFAULT_SCHEMA)
        schema["particions"] = []
        schema["particions_v2"] = []
        schema["puntuacio"]["aparells"] = {"mode": "seleccionar", "ids": [comp_app.id for comp_app in comp_apps]}
        schema["puntuacio"]["camps_per_aparell"] = {str(comp_app.id): ["total"] for comp_app in comp_apps}
        schema["puntuacio"]["agregacio_camps"] = "sum"
        schema["puntuacio"]["exercicis"] = {"mode": "tots", "best_n": 1, "index": 1, "ids": []}
        schema["puntuacio"]["agregacio_exercicis"] = "sum"
        schema["puntuacio"]["agregacio_aparells"] = "sum"
        schema["puntuacio"]["ordre"] = "desc"
        if scope is not None:
            schema["scope"] = scope
        return schema

    def _schema_for_app(self, comp_app, *, phase=None):
        schema = self._schema_for_apps([comp_app])
        if phase is not None:
            schema["scope"] = {"mode": "phase", "fase_id": phase.id}
        return schema

    def test_compute_classificacio_scoped_to_phase_slots_only_sees_phase_participants(self):
        create_program_unit_from_subjects(
            fase=self.fase_a,
            nom="Semifinal",
            subjects=[SlotSubject("inscripcio", self.ins_a.id)],
        )
        ScoreEntry.objects.create(
            competicio=self.competicio,
            inscripcio=self.ins_a,
            exercici=1,
            comp_aparell=self.comp_app_a,
            fase=self.fase_a,
            total=8.4,
        )
        ScoreEntry.objects.create(
            competicio=self.competicio,
            inscripcio=self.ins_a,
            exercici=1,
            comp_aparell=self.comp_app_a,
            total=2.0,
        )

        cfg = ClassificacioConfig.objects.create(
            competicio=self.competicio,
            nom="Semifinal",
            activa=True,
            ordre=1,
            tipus="individual",
            schema=self._schema_for_app(self.comp_app_a, phase=self.fase_a),
        )

        rows = compute_classificacio(self.competicio, cfg).get("global", [])

        self.assertEqual([row["inscripcio_id"] for row in rows], [self.ins_a.id])
        self.assertEqual(rows[0]["punts"], 8.4)

    def test_phase_scope_is_validated_against_selected_competition_app(self):
        schema = self._schema_for_app(self.comp_app_a, phase=self.fase_b)

        _normalized, errors = validate_schema_for_competicio(self.competicio, schema, tipus="individual")

        self.assertTrue(any("scope.fase_id" in error for error in errors))

    def test_prepare_schema_for_persistence_keeps_valid_phase_scope(self):
        schema = self._schema_for_app(self.comp_app_a, phase=self.fase_a)

        result = prepare_schema_for_persistence(self.competicio, schema, tipus="individual")

        self.assertEqual(result["errors"], [])
        self.assertEqual(result["schema"]["scope"], {"mode": "phase", "fase_id": self.fase_a.id})

    def test_compute_classificacio_per_app_phase_scope_filters_each_app_independently(self):
        create_program_unit_from_subjects(
            fase=self.fase_a,
            nom="Semifinal TRA",
            subjects=[SlotSubject("inscripcio", self.ins_a.id)],
        )
        create_program_unit_from_subjects(
            fase=self.fase_b,
            nom="Final DMT",
            subjects=[SlotSubject("inscripcio", self.ins_b.id)],
        )
        for inscripcio, app, phase, total in (
            (self.ins_a, self.comp_app_a, self.fase_a, 8.0),
            (self.ins_a, self.comp_app_b, None, 80.0),
            (self.ins_b, self.comp_app_a, None, 90.0),
            (self.ins_b, self.comp_app_b, self.fase_b, 9.0),
        ):
            ScoreEntry.objects.create(
                competicio=self.competicio,
                inscripcio=inscripcio,
                exercici=1,
                comp_aparell=app,
                fase=phase,
                total=total,
            )
        schema = self._schema_for_apps(
            [self.comp_app_a, self.comp_app_b],
            scope={
                "mode": "per_app",
                "apps": {
                    str(self.comp_app_a.id): {"mode": "phase", "fase_id": self.fase_a.id},
                    str(self.comp_app_b.id): {"mode": "phase", "fase_id": self.fase_b.id},
                },
            },
        )
        cfg = ClassificacioConfig.objects.create(
            competicio=self.competicio,
            nom="Multi fase",
            activa=True,
            ordre=1,
            tipus="individual",
            schema=schema,
        )

        rows = compute_classificacio(self.competicio, cfg).get("global", [])
        points_by_id = {row["inscripcio_id"]: row["punts"] for row in rows}

        self.assertEqual(points_by_id, {self.ins_b.id: 9.0, self.ins_a.id: 8.0})

    def test_per_app_phase_scope_rejects_phase_from_another_app(self):
        schema = self._schema_for_apps(
            [self.comp_app_a, self.comp_app_b],
            scope={
                "mode": "per_app",
                "apps": {
                    str(self.comp_app_a.id): {"mode": "phase", "fase_id": self.fase_b.id},
                    str(self.comp_app_b.id): {"mode": "implicit", "fase_id": None},
                },
            },
        )

        _normalized, errors = validate_schema_for_competicio(self.competicio, schema, tipus="individual")

        self.assertTrue(any(f"scope.apps[{self.comp_app_a.id}].fase_id" in error for error in errors))
