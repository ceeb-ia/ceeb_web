from types import SimpleNamespace

from django.test import TestCase

from ...models import EquipContext, InscripcioEquipAssignacio
from ...models.competicio import Aparell, CompeticioAparellEquipContextSource
from ...models.scoring import ScoreEntry, TeamCompetitiveSubject, TeamScoreEntry
from ...services.classificacions.compute import compute_classificacio as engine_compute_classificacio
from ...services.legacy.services_classificacions_2 import compute_classificacio as legacy_compute_classificacio

from ..base import _BaseTrampoliDataMixin


class ComputeEngineParityTests(_BaseTrampoliDataMixin, TestCase):
    def setUp(self):
        self.comp = self._create_competicio("Comp Compute Parity")

    def _base_schema(self, *app_ids):
        selected_ids = list(app_ids)
        return {
            "particions": [],
            "filtres": {},
            "puntuacio": {
                "aparells": {"mode": "seleccionar", "ids": selected_ids},
                "camps_per_aparell": {str(app_id): ["total"] for app_id in selected_ids},
                "agregacio_camps": "sum",
                "exercicis": {"mode": "tots"},
                "agregacio_exercicis": "sum",
                "agregacio_aparells": "sum",
                "ordre": "desc",
            },
            "desempat": [],
            "presentacio": {"top_n": 0, "mostrar_empats": True},
        }

    def _compute_pair(self, *, tipus, schema):
        cfg = SimpleNamespace(schema=schema, tipus=tipus)
        legacy = legacy_compute_classificacio(self.comp, cfg)
        engine = engine_compute_classificacio(self.comp, cfg)
        return self._normalize_result(legacy), self._normalize_result(engine)

    def _normalize_result(self, result):
        normalized = {}
        for partition_key in sorted(result.keys()):
            rows = [self._normalize_row(row) for row in result.get(partition_key) or []]
            normalized[partition_key] = sorted(rows, key=self._row_sort_key)
        return normalized

    def _normalize_row(self, row):
        normalized = {}
        for key in (
            "posicio",
            "participant",
            "nom",
            "entitat_nom",
            "participants",
            "score",
            "punts",
            "inscripcio_id",
            "equip_id",
            "team_id",
            "_team_mode",
        ):
            if key in row:
                normalized[key] = self._normalize_value(row.get(key))
        member_ids = row.get("_member_ids")
        if member_ids is not None:
            normalized["_member_ids"] = sorted(int(item) for item in member_ids)
        return normalized

    def _normalize_value(self, value):
        if isinstance(value, float):
            return round(value, 6)
        if isinstance(value, list):
            return [self._normalize_value(item) for item in value]
        if isinstance(value, tuple):
            return tuple(self._normalize_value(item) for item in value)
        if isinstance(value, dict):
            return {str(key): self._normalize_value(val) for key, val in sorted(value.items(), key=lambda item: str(item[0]))}
        return value

    def _row_sort_key(self, row):
        return (
            str(row.get("participant") or row.get("nom") or row.get("entitat_nom") or ""),
            int(row.get("inscripcio_id") or 0),
            int(row.get("equip_id") or row.get("team_id") or 0),
            tuple(row.get("_member_ids") or []),
        )

    def test_compute_parity_individual_simple(self):
        app = self._create_aparell("TRIND", "Tramp Individual")
        comp_app = self._create_comp_aparell(self.comp, app, ordre=1, actiu=True)
        ins_a = self._create_inscripcio(self.comp, "Participant A", ordre=1)
        ins_b = self._create_inscripcio(self.comp, "Participant B", ordre=2)
        ins_a.entitat = "Club A"
        ins_b.entitat = "Club B"
        ins_a.save(update_fields=["entitat"])
        ins_b.save(update_fields=["entitat"])

        ScoreEntry.objects.create(
            competicio=self.comp,
            comp_aparell=comp_app,
            inscripcio=ins_a,
            exercici=1,
            inputs={},
            outputs={},
            total=10.0,
        )
        ScoreEntry.objects.create(
            competicio=self.comp,
            comp_aparell=comp_app,
            inscripcio=ins_b,
            exercici=1,
            inputs={},
            outputs={},
            total=20.0,
        )

        legacy, engine = self._compute_pair(tipus="individual", schema=self._base_schema(comp_app.id))

        self.assertEqual(legacy, engine)
        rows_by_participant = {row["participant"]: row for row in engine["global"]}
        self.assertEqual(sorted(rows_by_participant.keys()), ["Participant A", "Participant B"])
        self.assertEqual(rows_by_participant["Participant A"]["score"], 10.0)
        self.assertEqual(rows_by_participant["Participant A"]["posicio"], 2)
        self.assertEqual(rows_by_participant["Participant B"]["score"], 20.0)
        self.assertEqual(rows_by_participant["Participant B"]["posicio"], 1)

    def test_compute_parity_derived_team_simple(self):
        app = self._create_aparell("TRTEAM", "Tramp Equips")
        comp_app = self._create_comp_aparell(self.comp, app, ordre=1, actiu=True)

        native_ctx = self._ensure_native_equip_context(self.comp)
        context = EquipContext.objects.create(competicio=self.comp, code="parelles", nom="Parelles")
        CompeticioAparellEquipContextSource.objects.create(
            competicio=self.comp,
            comp_aparell=comp_app,
            context=context,
        )

        team_a = self._create_equip(self.comp, "Parella A", context=context)
        team_b = self._create_equip(self.comp, "Parella B", context=context)
        members = []
        for idx, (team, name, total) in enumerate(
            (
                (team_a, "Anna", 10.0),
                (team_a, "Berta", 7.0),
                (team_b, "Carla", 9.0),
                (team_b, "Diana", 6.0),
            ),
            start=1,
        ):
            ins = self._create_inscripcio(self.comp, name, ordre=idx)
            members.append(ins)
            InscripcioEquipAssignacio.objects.create(
                competicio=self.comp,
                context=native_ctx,
                inscripcio=ins,
                equip=self._create_equip(self.comp, f"Native {name}", context=native_ctx),
            )
            InscripcioEquipAssignacio.objects.create(
                competicio=self.comp,
                context=context,
                inscripcio=ins,
                equip=team,
            )
            ScoreEntry.objects.create(
                competicio=self.comp,
                comp_aparell=comp_app,
                inscripcio=ins,
                exercici=1,
                inputs={},
                outputs={},
                total=total,
            )

        schema = self._base_schema(comp_app.id)
        schema["equips"] = {
            "context_code": "parelles",
            "team_mode": "derived_from_individual",
            "incloure_sense_equip": False,
        }

        legacy, engine = self._compute_pair(tipus="equips", schema=schema)

        self.assertEqual(legacy, engine)
        rows_by_participant = {row["participant"]: row for row in engine["global"]}
        self.assertEqual(sorted(rows_by_participant.keys()), ["Parella A", "Parella B"])
        self.assertEqual(rows_by_participant["Parella A"]["score"], 17.0)
        self.assertEqual(rows_by_participant["Parella A"]["posicio"], 1)
        self.assertEqual(rows_by_participant["Parella A"]["participants"], 2)
        self.assertEqual(rows_by_participant["Parella B"]["score"], 15.0)
        self.assertEqual(rows_by_participant["Parella B"]["posicio"], 2)
        self.assertEqual(rows_by_participant["Parella B"]["participants"], 2)

    def test_compute_parity_entitat_simple(self):
        app = self._create_aparell("TRENT", "Tramp Entitats")
        comp_app = self._create_comp_aparell(self.comp, app, ordre=1, actiu=True)

        rows = (
            ("Participant A", "Club A", 12.0),
            ("Participant B", "Club A", 8.0),
            ("Participant C", "Club B", 15.0),
        )
        for ordre, (name, entitat, total) in enumerate(rows, start=1):
            ins = self._create_inscripcio(self.comp, name, ordre=ordre)
            ins.entitat = entitat
            ins.save(update_fields=["entitat"])
            ScoreEntry.objects.create(
                competicio=self.comp,
                comp_aparell=comp_app,
                inscripcio=ins,
                exercici=1,
                inputs={},
                outputs={},
                total=total,
            )

        legacy, engine = self._compute_pair(tipus="entitat", schema=self._base_schema(comp_app.id))

        self.assertEqual(legacy, engine)
        rows_by_entitat = {row["entitat_nom"]: row for row in engine["global"]}
        self.assertEqual(sorted(rows_by_entitat.keys()), ["Club A", "Club B"])
        self.assertEqual(rows_by_entitat["Club A"]["score"], 20.0)
        self.assertEqual(rows_by_entitat["Club A"]["posicio"], 1)
        self.assertEqual(rows_by_entitat["Club B"]["score"], 15.0)
        self.assertEqual(rows_by_entitat["Club B"]["posicio"], 2)

    def test_compute_parity_individual_victories_simple(self):
        app = self._create_aparell("TRVICT", "Tramp Victories")
        comp_app = self._create_comp_aparell(self.comp, app, ordre=1, actiu=True)
        ins_a = self._create_inscripcio(self.comp, "Participant A", ordre=1)
        ins_b = self._create_inscripcio(self.comp, "Participant B", ordre=2)

        ScoreEntry.objects.create(
            competicio=self.comp,
            comp_aparell=comp_app,
            inscripcio=ins_a,
            exercici=1,
            inputs={},
            outputs={},
            total=10.0,
        )
        ScoreEntry.objects.create(
            competicio=self.comp,
            comp_aparell=comp_app,
            inscripcio=ins_b,
            exercici=1,
            inputs={},
            outputs={},
            total=7.0,
        )

        schema = self._base_schema(comp_app.id)
        schema["puntuacio"]["mode_resultat_aparells"] = "victories"
        schema["puntuacio"]["victories"] = {
            "punts_victoria": 1,
            "punts_empat": 0.5,
            "sense_nota_mode": "skip",
            "mode_camps": "agregat",
            "mode_exercicis": "agregat",
            "mode_seleccio_exercicis_camps_separats": "per_camp",
            "agregacio_victories_camps": "sum",
            "agregacio_victories_exercicis": "sum",
            "desempat_comparacio": [],
        }

        legacy, engine = self._compute_pair(tipus="individual", schema=schema)

        self.assertEqual(legacy, engine)
        rows_by_participant = {row["participant"]: row for row in engine["global"]}
        self.assertEqual(rows_by_participant["Participant A"]["score"], 1.0)
        self.assertEqual(rows_by_participant["Participant A"]["posicio"], 1)
        self.assertEqual(rows_by_participant["Participant B"]["score"], 0.0)
        self.assertEqual(rows_by_participant["Participant B"]["posicio"], 2)

    def test_compute_parity_native_team_simple(self):
        app = self._create_aparell("TRNAT", "Tramp Native Team")
        app.competition_unit = Aparell.CompetitionUnit.TEAM
        app.save(update_fields=["competition_unit"])
        comp_app = self._create_comp_aparell(self.comp, app, ordre=1, actiu=True)

        context = EquipContext.objects.create(competicio=self.comp, code="parelles", nom="Parelles")
        CompeticioAparellEquipContextSource.objects.create(
            competicio=self.comp,
            comp_aparell=comp_app,
            context=context,
        )
        equip = self._create_equip(self.comp, "Parella 1", context=context)
        members = [
            self._create_inscripcio(self.comp, "Anna", ordre=1),
            self._create_inscripcio(self.comp, "Berta", ordre=2),
        ]
        for member in members:
            InscripcioEquipAssignacio.objects.create(
                competicio=self.comp,
                context=context,
                inscripcio=member,
                equip=equip,
            )
        team_subject = TeamCompetitiveSubject.objects.create(
            competicio=self.comp,
            comp_aparell=comp_app,
            context=context,
            equip=equip,
            member_ids=[member.id for member in members],
        )
        TeamScoreEntry.objects.create(
            competicio=self.comp,
            team_subject=team_subject,
            comp_aparell=comp_app,
            exercici=1,
            inputs={},
            outputs={},
            total=30.0,
        )

        schema = self._base_schema(comp_app.id)
        schema["equips"] = {
            "context_code": "parelles",
            "team_mode": "native_team",
            "incloure_sense_equip": False,
        }

        legacy, engine = self._compute_pair(tipus="equips", schema=schema)

        self.assertEqual(legacy, engine)
        rows_by_participant = {row["participant"]: row for row in engine["global"]}
        self.assertEqual(rows_by_participant["Parella 1"]["score"], 30.0)
        self.assertEqual(rows_by_participant["Parella 1"]["participants"], 2)
        self.assertEqual(rows_by_participant["Parella 1"]["posicio"], 1)
