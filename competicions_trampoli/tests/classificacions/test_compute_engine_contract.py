from datetime import date
from types import SimpleNamespace

from django.test import TestCase

from ...models import EquipContext, InscripcioEquipAssignacio
from ...models.competicio import Aparell, CompeticioAparellEquipContextSource
from ...models.scoring import ScoreEntry, TeamCompetitiveSubject, TeamScoreEntry
from ...services.classificacions.compute import compute_classificacio as engine_compute_classificacio

from ..base import _BaseTrampoliDataMixin


class ComputeEngineContractTests(_BaseTrampoliDataMixin, TestCase):
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

    def _tie_pipeline_for_apps(self, *app_ids, candidate_source_mode="raw_exercise"):
        selected_ids = list(app_ids)
        return {
            "aparells": {"mode": "seleccionar", "ids": selected_ids},
            "camps_per_aparell": {str(app_id): ["total"] for app_id in selected_ids},
            "agregacio_camps_per_aparell": {str(app_id): "sum" for app_id in selected_ids},
            "agregacio_camps": "sum",
            "candidate_source_mode": candidate_source_mode,
            "candidate_source_cfg": {
                "mode": "tots",
                "best_n": 1,
                "index": 1,
                "ids": [],
                "agregacio_exercicis": "sum",
            },
            "candidate_source_per_aparell": {
                str(app_id): {"mode": candidate_source_mode} for app_id in selected_ids
            },
            "exercicis": {"mode": "tots", "index": 1, "ids": [], "max_per_participant": 0},
            "exercise_selection_scope": "per_member",
            "mode_seleccio_exercicis": "per_aparell_global",
            "agregacio_exercicis": "sum",
            "agregacio_aparells": "sum",
            "mode_resultat_aparells": "score",
            "ordre": "desc",
        }

    def _compute_engine(self, *, tipus, schema):
        cfg = SimpleNamespace(schema=schema, tipus=tipus)
        engine = engine_compute_classificacio(self.comp, cfg)
        return self._normalize_result(engine)

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
            "row_id",
            "tie",
            "by_app",
            "by_app_base",
            "cells",
            "display",
            "detail",
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

    def test_compute_individual_simple(self):
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

        engine = self._compute_engine(tipus="individual", schema=self._base_schema(comp_app.id))
        rows_by_participant = {row["participant"]: row for row in engine["global"]}
        self.assertEqual(sorted(rows_by_participant.keys()), ["Participant A", "Participant B"])
        self.assertEqual(rows_by_participant["Participant A"]["score"], 10.0)
        self.assertEqual(rows_by_participant["Participant A"]["posicio"], 2)
        self.assertEqual(rows_by_participant["Participant B"]["score"], 20.0)
        self.assertEqual(rows_by_participant["Participant B"]["posicio"], 1)

    def test_compute_individual_filters_by_group_and_category(self):
        app = self._create_aparell("TRFILT", "Tramp Filtres")
        comp_app = self._create_comp_aparell(self.comp, app, ordre=1, actiu=True)

        rows = (
            ("Participant A", 1, "BASE", 12.0),
            ("Participant B", 2, "BASE", 11.0),
            ("Participant C", 1, "PROMO", 10.0),
            ("Participant D", 2, "PROMO", 9.0),
        )
        for ordre, (name, grup, categoria, total) in enumerate(rows, start=1):
            ins = self._create_inscripcio(self.comp, name, ordre=ordre, grup=grup)
            ins.categoria = categoria
            ins.save(update_fields=["categoria"])
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
        schema["filtres"] = {
            "categories_in": ["base"],
            "grups_in": [1],
        }

        engine = self._compute_engine(tipus="individual", schema=schema)
        self.assertEqual([row["participant"] for row in engine["global"]], ["Participant A"])
        self.assertEqual(engine["global"][0]["score"], 12.0)

    def test_compute_individual_birth_year_partition_ranges(self):
        app = self._create_aparell("TRBIRTH", "Tramp Naixement")
        comp_app = self._create_comp_aparell(self.comp, app, ordre=1, actiu=True)

        ins_a = self._create_inscripcio(self.comp, "Participant A", ordre=1)
        ins_b = self._create_inscripcio(self.comp, "Participant B", ordre=2)
        ins_a.data_naixement = date(2009, 1, 1)
        ins_b.data_naixement = date(2010, 12, 31)
        ins_a.save(update_fields=["data_naixement"])
        ins_b.save(update_fields=["data_naixement"])

        ScoreEntry.objects.create(
            competicio=self.comp,
            comp_aparell=comp_app,
            inscripcio=ins_a,
            exercici=1,
            inputs={},
            outputs={},
            total=9.0,
        )
        ScoreEntry.objects.create(
            competicio=self.comp,
            comp_aparell=comp_app,
            inscripcio=ins_b,
            exercici=1,
            inputs={},
            outputs={},
            total=8.0,
        )

        schema = self._base_schema(comp_app.id)
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

        engine = self._compute_engine(tipus="individual", schema=schema)
        self.assertEqual(set(engine.keys()), {"any_naixement_forquilla:2007-2009", "any_naixement_forquilla:2010-2012"})
        self.assertEqual(engine["any_naixement_forquilla:2007-2009"][0]["participant"], "Participant A")
        self.assertEqual(engine["any_naixement_forquilla:2010-2012"][0]["participant"], "Participant B")

    def test_compute_derived_team_team_pool_scope(self):
        app = self._create_aparell("TRPOOL", "Tramp Team Pool")
        comp_app = self._create_comp_aparell(self.comp, app, ordre=1, actiu=True)
        comp_app.nombre_exercicis = 2
        comp_app.save(update_fields=["nombre_exercicis"])

        native_ctx = self._ensure_native_equip_context(self.comp)
        context = EquipContext.objects.create(competicio=self.comp, code="parelles", nom="Parelles")
        CompeticioAparellEquipContextSource.objects.create(
            competicio=self.comp,
            comp_aparell=comp_app,
            context=context,
        )

        team_a = self._create_equip(self.comp, "Parella A", context=context)
        team_b = self._create_equip(self.comp, "Parella B", context=context)
        for idx, (team, name, scores) in enumerate(
            (
                (team_a, "Anna", (10.0, 2.0)),
                (team_a, "Berta", (7.0, 1.0)),
                (team_b, "Carla", (9.0, 3.0)),
                (team_b, "Diana", (6.0, 4.0)),
            ),
            start=1,
        ):
            ins = self._create_inscripcio(self.comp, name, ordre=idx)
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
            for exercici, total in enumerate(scores, start=1):
                ScoreEntry.objects.create(
                    competicio=self.comp,
                    comp_aparell=comp_app,
                    inscripcio=ins,
                    exercici=exercici,
                    inputs={},
                    outputs={},
                    total=total,
                )

        schema = self._base_schema(comp_app.id)
        schema["puntuacio"]["exercicis"] = {"mode": "millor_n", "best_n": 1, "index": 1, "ids": [], "max_per_participant": 0}
        schema["puntuacio"]["exercise_selection_scope"] = "team_pool"
        schema["equips"] = {
            "context_code": "parelles",
            "team_mode": "derived_from_individual",
            "incloure_sense_equip": False,
        }

        engine = self._compute_engine(tipus="equips", schema=schema)
        rows_by_participant = {row["participant"]: row for row in engine["global"]}
        self.assertEqual(sorted(rows_by_participant.keys()), ["Parella A", "Parella B"])
        self.assertEqual(rows_by_participant["Parella A"]["score"], 10.0)
        self.assertEqual(rows_by_participant["Parella A"]["posicio"], 1)
        self.assertEqual(rows_by_participant["Parella B"]["score"], 9.0)
        self.assertEqual(rows_by_participant["Parella B"]["posicio"], 2)

    def test_compute_derived_team_team_pool_per_exercise_preaggregation(self):
        app = self._create_aparell("TRPOOLX", "Tramp Team Pool Per Exercici")
        comp_app = self._create_comp_aparell(self.comp, app, ordre=1, actiu=True)
        comp_app.nombre_exercicis = 2
        comp_app.save(update_fields=["nombre_exercicis"])

        native_ctx = self._ensure_native_equip_context(self.comp)
        context = EquipContext.objects.create(competicio=self.comp, code="trios", nom="Trios")
        CompeticioAparellEquipContextSource.objects.create(
            competicio=self.comp,
            comp_aparell=comp_app,
            context=context,
        )

        team_a = self._create_equip(self.comp, "Equip A", context=context)
        team_b = self._create_equip(self.comp, "Equip B", context=context)
        rows = (
            (team_a, "A1", (10.0, 7.0)),
            (team_a, "A2", (9.0, 1.0)),
            (team_a, "A3", (8.0, 1.0)),
            (team_b, "B1", (6.0, 5.0)),
            (team_b, "B2", (6.0, 5.0)),
            (team_b, "B3", (6.0, 5.0)),
        )
        for ordre, (team, name, scores) in enumerate(rows, start=1):
            ins = self._create_inscripcio(self.comp, name, ordre=ordre)
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
            for exercici, total in enumerate(scores, start=1):
                ScoreEntry.objects.create(
                    competicio=self.comp,
                    comp_aparell=comp_app,
                    inscripcio=ins,
                    exercici=exercici,
                    inputs={},
                    outputs={},
                    total=total,
                )

        schema = self._base_schema(comp_app.id)
        schema["puntuacio"]["exercise_selection_scope"] = "team_pool"
        schema["puntuacio"]["team_pool_mode_per_aparell"] = {str(comp_app.id): "per_exercici"}
        schema["puntuacio"]["team_pool_participants_per_exercici_per_aparell"] = {
            str(comp_app.id): {
                "1": {"mode": "millor_n", "n": 2},
                "2": {"mode": "millor_1"},
            }
        }
        schema["puntuacio"]["team_pool_agregacio_participants_per_exercici_per_aparell"] = {
            str(comp_app.id): {
                "1": "sum",
                "2": "sum",
            }
        }
        schema["puntuacio"]["exercicis"] = {"mode": "tots"}
        schema["puntuacio"]["agregacio_exercicis"] = "sum"
        schema["equips"] = {
            "context_code": "trios",
            "team_mode": "derived_from_individual",
            "incloure_sense_equip": False,
        }

        engine = self._compute_engine(tipus="equips", schema=schema)
        rows_by_participant = {row["participant"]: row for row in engine["global"]}
        self.assertEqual(sorted(rows_by_participant.keys()), ["Equip A", "Equip B"])
        self.assertEqual(rows_by_participant["Equip A"]["score"], 26.0)
        self.assertEqual(rows_by_participant["Equip A"]["posicio"], 1)
        self.assertEqual(rows_by_participant["Equip B"]["score"], 17.0)
        self.assertEqual(rows_by_participant["Equip B"]["posicio"], 2)

    def test_compute_derived_team_simple(self):
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

        engine = self._compute_engine(tipus="equips", schema=schema)
        rows_by_participant = {row["participant"]: row for row in engine["global"]}
        self.assertEqual(sorted(rows_by_participant.keys()), ["Parella A", "Parella B"])
        self.assertEqual(rows_by_participant["Parella A"]["score"], 17.0)
        self.assertEqual(rows_by_participant["Parella A"]["posicio"], 1)
        self.assertEqual(rows_by_participant["Parella A"]["participants"], 2)
        self.assertEqual(rows_by_participant["Parella B"]["score"], 15.0)
        self.assertEqual(rows_by_participant["Parella B"]["posicio"], 2)
        self.assertEqual(rows_by_participant["Parella B"]["participants"], 2)

    def test_compute_entitat_simple(self):
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

        engine = self._compute_engine(tipus="entitat", schema=self._base_schema(comp_app.id))
        rows_by_entitat = {row["entitat_nom"]: row for row in engine["global"]}
        self.assertEqual(sorted(rows_by_entitat.keys()), ["Club A", "Club B"])
        self.assertEqual(rows_by_entitat["Club A"]["score"], 20.0)
        self.assertEqual(rows_by_entitat["Club A"]["posicio"], 1)
        self.assertEqual(rows_by_entitat["Club B"]["score"], 15.0)
        self.assertEqual(rows_by_entitat["Club B"]["posicio"], 2)

    def test_compute_individual_victories_simple(self):
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

        engine = self._compute_engine(tipus="individual", schema=schema)
        rows_by_participant = {row["participant"]: row for row in engine["global"]}
        self.assertEqual(rows_by_participant["Participant A"]["score"], 1.0)
        self.assertEqual(rows_by_participant["Participant A"]["posicio"], 1)
        self.assertEqual(rows_by_participant["Participant B"]["score"], 0.0)
        self.assertEqual(rows_by_participant["Participant B"]["posicio"], 2)

    def test_compute_individual_raw_columns(self):
        app = self._create_aparell("TRRAW", "Tramp Raw Columns")
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
            total=20.0,
        )

        schema = self._base_schema(comp_app.id)
        schema["presentacio"] = {
            "top_n": 0,
            "mostrar_empats": True,
            "columnes": [
                {"type": "builtin", "key": "posicio", "label": "#", "align": "left"},
                {"type": "builtin", "key": "participant", "label": "Nom", "align": "left"},
                {
                    "type": "raw",
                    "key": "raw_total",
                    "label": "Total raw",
                    "align": "right",
                    "decimals": 2,
                    "source": {
                        "aparell_id": comp_app.id,
                        "exercici": 1,
                        "camp": "total",
                        "jutges": {"ids": []},
                    },
                },
            ],
            "detall": {"enabled": False, "default_open": False, "sections": []},
        }

        engine = self._compute_engine(tipus="individual", schema=schema)
        rows_by_participant = {row["participant"]: row for row in engine["global"]}
        self.assertEqual(rows_by_participant["Participant A"]["score"], 10.0)
        self.assertEqual(rows_by_participant["Participant A"]["posicio"], 2)
        self.assertEqual(rows_by_participant["Participant A"]["cells"]["raw_total"], 10.0)
        self.assertEqual(rows_by_participant["Participant B"]["score"], 20.0)
        self.assertEqual(rows_by_participant["Participant B"]["posicio"], 1)
        self.assertEqual(rows_by_participant["Participant B"]["cells"]["raw_total"], 20.0)

    def test_compute_equips_detail_sections(self):
        app = self._create_aparell("TRDET", "Tramp Detall")
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
        for idx, (team, name, total) in enumerate(
            (
                (team_a, "Anna", 10.0),
                (team_b, "Berta", 8.0),
            ),
            start=1,
        ):
            ins = self._create_inscripcio(self.comp, name, ordre=idx)
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
        schema["presentacio"] = {
            "top_n": 0,
            "mostrar_empats": True,
            "detall": {
                "enabled": True,
                "default_open": True,
                "sections": [
                    {
                        "type": "members_table",
                        "label": "Membres",
                        "columns": [
                            {"type": "builtin", "key": "participant", "label": "Participant"},
                            {"type": "builtin", "key": "entitat_nom", "label": "Club"},
                        ],
                    }
                ],
            },
        }

        engine = self._compute_engine(tipus="equips", schema=schema)
        rows_by_participant = {row["participant"]: row for row in engine["global"]}
        self.assertEqual(sorted(rows_by_participant.keys()), ["Parella A", "Parella B"])
        self.assertEqual(rows_by_participant["Parella A"]["score"], 10.0)
        self.assertEqual(rows_by_participant["Parella A"]["posicio"], 1)
        self.assertEqual(rows_by_participant["Parella A"]["detail"]["sections"][0]["type"], "members_table")
        self.assertEqual(rows_by_participant["Parella A"]["detail"]["sections"][0]["rows"][0]["participant"], "Anna")
        self.assertEqual(rows_by_participant["Parella B"]["score"], 8.0)
        self.assertEqual(rows_by_participant["Parella B"]["posicio"], 2)

    def test_compute_entitat_simple_tie(self):
        app_main = self._create_aparell("TRENT1", "Tramp Entitats Main")
        comp_app_main = self._create_comp_aparell(self.comp, app_main, ordre=1, actiu=True)
        app_tie = self._create_aparell("TRENT2", "Tramp Entitats Tie")
        comp_app_tie = self._create_comp_aparell(self.comp, app_tie, ordre=2, actiu=True)

        rows = (
            ("Participant A", "Club A", 5.0, 1.0),
            ("Participant B", "Club B", 4.0, 2.0),
        )
        for ordre, (name, entitat, main_total, tie_total) in enumerate(rows, start=1):
            ins = self._create_inscripcio(self.comp, name, ordre=ordre)
            ins.entitat = entitat
            ins.save(update_fields=["entitat"])
            ScoreEntry.objects.create(
                competicio=self.comp,
                comp_aparell=comp_app_main,
                inscripcio=ins,
                exercici=1,
                inputs={},
                outputs={},
                total=main_total,
            )
            ScoreEntry.objects.create(
                competicio=self.comp,
                comp_aparell=comp_app_tie,
                inscripcio=ins,
                exercici=1,
                inputs={},
                outputs={},
                total=tie_total,
            )

        schema = self._base_schema(comp_app_main.id, comp_app_tie.id)
        schema["desempat"] = [
            {
                "id": "tie_entitat_app_tie",
                "ordre": "desc",
                "pipeline_version": 1,
                "pipeline": self._tie_pipeline_for_apps(comp_app_tie.id),
            }
        ]

        engine = self._compute_engine(tipus="entitat", schema=schema)
        rows_by_entitat = {row["entitat_nom"]: row for row in engine["global"]}
        self.assertEqual(sorted(rows_by_entitat.keys()), ["Club A", "Club B"])
        self.assertEqual(rows_by_entitat["Club A"]["score"], 6.0)
        self.assertEqual(rows_by_entitat["Club A"]["tie"]["tie_entitat_app_tie"], 1.0)
        self.assertEqual(rows_by_entitat["Club A"]["posicio"], 2)
        self.assertEqual(rows_by_entitat["Club B"]["score"], 6.0)
        self.assertEqual(rows_by_entitat["Club B"]["tie"]["tie_entitat_app_tie"], 2.0)
        self.assertEqual(rows_by_entitat["Club B"]["posicio"], 1)

    def test_compute_native_team_simple_tie(self):
        app_main = self._create_aparell("TRNAT", "Tramp Native Team Main")
        app_main.competition_unit = Aparell.CompetitionUnit.TEAM
        app_main.save(update_fields=["competition_unit"])
        comp_app_main = self._create_comp_aparell(self.comp, app_main, ordre=1, actiu=True)
        app_tie = self._create_aparell("TRNAT2", "Tramp Native Team Tie")
        app_tie.competition_unit = Aparell.CompetitionUnit.TEAM
        app_tie.save(update_fields=["competition_unit"])
        comp_app_tie = self._create_comp_aparell(self.comp, app_tie, ordre=2, actiu=True)

        context = EquipContext.objects.create(competicio=self.comp, code="parelles", nom="Parelles")
        CompeticioAparellEquipContextSource.objects.create(
            competicio=self.comp,
            comp_aparell=comp_app_main,
            context=context,
        )
        CompeticioAparellEquipContextSource.objects.create(
            competicio=self.comp,
            comp_aparell=comp_app_tie,
            context=context,
        )
        team_a = self._create_equip(self.comp, "Parella A", context=context)
        team_b = self._create_equip(self.comp, "Parella B", context=context)
        for ordre, (team, name, main_total, tie_total) in enumerate(
            (
                (team_a, "Anna", 5.0, 1.0),
                (team_b, "Berta", 4.0, 2.0),
            ),
            start=1,
        ):
            member = self._create_inscripcio(self.comp, name, ordre=ordre)
            InscripcioEquipAssignacio.objects.create(
                competicio=self.comp,
                context=context,
                inscripcio=member,
                equip=team,
            )
            team_subject_main = TeamCompetitiveSubject.objects.create(
                competicio=self.comp,
                comp_aparell=comp_app_main,
                context=context,
                equip=team,
                member_ids=[member.id],
            )
            team_subject_tie = TeamCompetitiveSubject.objects.create(
                competicio=self.comp,
                comp_aparell=comp_app_tie,
                context=context,
                equip=team,
                member_ids=[member.id],
            )
            TeamScoreEntry.objects.create(
                competicio=self.comp,
                team_subject=team_subject_main,
                comp_aparell=comp_app_main,
                exercici=1,
                inputs={},
                outputs={},
                total=main_total,
            )
            TeamScoreEntry.objects.create(
                competicio=self.comp,
                team_subject=team_subject_tie,
                comp_aparell=comp_app_tie,
                exercici=1,
                inputs={},
                outputs={},
                total=tie_total,
            )

        schema = self._base_schema(comp_app_main.id, comp_app_tie.id)
        schema["equips"] = {
            "context_code": "parelles",
            "team_mode": "native_team",
            "incloure_sense_equip": False,
        }
        schema["desempat"] = [
            {
                "id": "tie_native_team_app_tie",
                "ordre": "desc",
                "pipeline_version": 1,
                "pipeline": self._tie_pipeline_for_apps(
                    comp_app_tie.id,
                    candidate_source_mode="team_aggregate",
                ),
            }
        ]

        engine = self._compute_engine(tipus="equips", schema=schema)
        rows_by_participant = {row["participant"]: row for row in engine["global"]}
        self.assertEqual(sorted(rows_by_participant.keys()), ["Parella A", "Parella B"])
        self.assertEqual(rows_by_participant["Parella A"]["score"], 6.0)
        self.assertEqual(rows_by_participant["Parella A"]["participants"], 1)
        self.assertEqual(rows_by_participant["Parella A"]["tie"]["tie_native_team_app_tie"], 1.0)
        self.assertEqual(rows_by_participant["Parella A"]["posicio"], 2)
        self.assertEqual(rows_by_participant["Parella B"]["score"], 6.0)
        self.assertEqual(rows_by_participant["Parella B"]["participants"], 1)
        self.assertEqual(rows_by_participant["Parella B"]["tie"]["tie_native_team_app_tie"], 2.0)
        self.assertEqual(rows_by_participant["Parella B"]["posicio"], 1)


