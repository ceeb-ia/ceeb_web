from ._shared import *  # noqa: F401,F403


class TeamContextClassificacioDetailSectionsTests(TeamContextScoringFlowTestBase):
    def test_compute_classificacio_derived_team_raw_column_returns_team_detail_payload(self):
        ind_app = self._create_aparell("TR_RAW", "Tramp raw")
        comp_ind_app = self._create_comp_aparell(self.comp, ind_app, ordre=2)

        ScoreEntry.objects.create(
            competicio=self.comp,
            comp_aparell=comp_ind_app,
            inscripcio=self.ins1,
            exercici=1,
            inputs={},
            outputs={},
            total=12.5,
        )
        ScoreEntry.objects.create(
            competicio=self.comp,
            comp_aparell=comp_ind_app,
            inscripcio=self.ins2,
            exercici=1,
            inputs={},
            outputs={},
            total=11.25,
        )

        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Derived raw detail",
            activa=True,
            ordre=1,
            tipus="equips",
            schema={
                "puntuacio": {
                    "aparells": {"mode": "seleccionar", "ids": [comp_ind_app.id]},
                    "camps_per_aparell": {str(comp_ind_app.id): ["total"]},
                    "agregacio_camps": "sum",
                    "exercicis": {"mode": "tots"},
                    "agregacio_exercicis": "sum",
                    "agregacio_aparells": "sum",
                    "ordre": "desc",
                },
                "presentacio": {
                    "columnes": [
                        {"type": "builtin", "key": "participant", "label": "Nom", "align": "left"},
                        {
                            "type": "raw",
                            "key": "raw_total",
                            "label": "Raw total",
                            "align": "right",
                            "decimals": 2,
                            "source": {"aparell_id": comp_ind_app.id, "exercici": 1, "camp": "total", "jutges": {"ids": []}},
                        },
                    ]
                },
                "equips": {
                    "context_code": "parelles",
                    "team_mode": "derived_from_individual",
                    "incloure_sense_equip": False,
                },
            },
        )

        rows = compute_classificacio(self.comp, cfg).get("global", [])

        payload = rows[0]["cells"]["raw_total"]
        self.assertEqual(payload["_kind"], "team_raw_detail")
        self.assertEqual(payload["summary"], 23.75)
        self.assertEqual([item["label"] for item in payload["rows"]], ["Maria", "Laia"])
        self.assertEqual([item["value"] for item in payload["rows"]], [12.5, 11.25])

    def test_compute_classificacio_derived_team_raw_multijudge_keeps_member_judge_rows(self):
        ind_app = self._create_aparell("TR_J", "Tramp judges")
        comp_ind_app = self._create_comp_aparell(self.comp, ind_app, ordre=2)

        ScoreEntry.objects.create(
            competicio=self.comp,
            comp_aparell=comp_ind_app,
            inscripcio=self.ins1,
            exercici=1,
            inputs={"E": [8.1, 8.2]},
            outputs={},
            total=12.0,
        )
        ScoreEntry.objects.create(
            competicio=self.comp,
            comp_aparell=comp_ind_app,
            inscripcio=self.ins2,
            exercici=1,
            inputs={"E": [7.4, 7.6]},
            outputs={},
            total=11.0,
        )

        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Derived raw judges",
            activa=True,
            ordre=1,
            tipus="equips",
            schema={
                "puntuacio": {
                    "aparells": {"mode": "seleccionar", "ids": [comp_ind_app.id]},
                    "camps_per_aparell": {str(comp_ind_app.id): ["total"]},
                    "agregacio_camps": "sum",
                    "exercicis": {"mode": "tots"},
                    "agregacio_exercicis": "sum",
                    "agregacio_aparells": "sum",
                    "ordre": "desc",
                },
                "presentacio": {
                    "columnes": [
                        {"type": "builtin", "key": "participant", "label": "Nom", "align": "left"},
                        {
                            "type": "raw",
                            "key": "raw_exec",
                            "label": "Exec",
                            "align": "right",
                            "decimals": 2,
                            "source": {"aparell_id": comp_ind_app.id, "exercici": 1, "camp": "E", "jutges": {"ids": []}},
                        },
                    ]
                },
                "equips": {
                    "context_code": "parelles",
                    "team_mode": "derived_from_individual",
                    "incloure_sense_equip": False,
                },
            },
        )

        rows = compute_classificacio(self.comp, cfg).get("global", [])

        payload = rows[0]["cells"]["raw_exec"]
        self.assertEqual(payload["_kind"], "team_raw_detail")
        self.assertEqual(payload["summary"], "")
        self.assertEqual(payload["rows"][0]["judge_rows"]["_kind"], "judge_rows")
        self.assertEqual(payload["rows"][1]["judge_rows"]["_kind"], "judge_rows")

    def test_compute_classificacio_derived_team_raw_column_uses_per_member_selected_exercises(self):
        ind_app = self._create_aparell("TR_PM", "Tramp per member")
        comp_ind_app = self._create_comp_aparell(self.comp, ind_app, ordre=2)
        comp_ind_app.nombre_exercicis = 2
        comp_ind_app.save(update_fields=["nombre_exercicis"])

        for inscripcio, exercici, total in (
            (self.ins1, 1, 1.0),
            (self.ins1, 2, 10.0),
            (self.ins2, 1, 2.0),
            (self.ins2, 2, 9.0),
        ):
            ScoreEntry.objects.create(
                competicio=self.comp,
                comp_aparell=comp_ind_app,
                inscripcio=inscripcio,
                exercici=exercici,
                inputs={},
                outputs={},
                total=total,
            )

        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Derived raw per member",
            activa=True,
            ordre=1,
            tipus="equips",
            schema={
                "puntuacio": {
                    "aparells": {"mode": "seleccionar", "ids": [comp_ind_app.id]},
                    "camps_per_aparell": {str(comp_ind_app.id): ["total"]},
                    "agregacio_camps": "sum",
                    "exercicis": {"mode": "millor_n", "best_n": 1},
                    "exercise_selection_scope": "per_member",
                    "agregacio_exercicis": "sum",
                    "agregacio_aparells": "sum",
                    "ordre": "desc",
                },
                "presentacio": {
                    "columnes": [
                        {"type": "builtin", "key": "participant", "label": "Nom", "align": "left"},
                        {
                            "type": "raw",
                            "key": "raw_total",
                            "label": "Raw total",
                            "align": "right",
                            "decimals": 2,
                            "source": {"aparell_id": comp_ind_app.id, "exercici": 1, "camp": "total", "jutges": {"ids": []}},
                        },
                    ]
                },
                "equips": {
                    "context_code": "parelles",
                    "team_mode": "derived_from_individual",
                    "incloure_sense_equip": False,
                },
            },
        )

        rows = compute_classificacio(self.comp, cfg).get("global", [])

        payload = rows[0]["cells"]["raw_total"]
        self.assertEqual(payload["_kind"], "team_raw_detail")
        self.assertEqual(payload["summary"], 19.0)
        self.assertEqual([item["value"] for item in payload["rows"]], [10.0, 9.0])

    def test_compute_classificacio_derived_team_raw_column_uses_team_pool_selected_exercises(self):
        ind_app = self._create_aparell("TR_TP", "Tramp team pool")
        comp_ind_app = self._create_comp_aparell(self.comp, ind_app, ordre=2)
        comp_ind_app.nombre_exercicis = 2
        comp_ind_app.save(update_fields=["nombre_exercicis"])

        for inscripcio, exercici, total in (
            (self.ins1, 1, 1.0),
            (self.ins1, 2, 10.0),
            (self.ins2, 1, 2.0),
            (self.ins2, 2, 9.0),
        ):
            ScoreEntry.objects.create(
                competicio=self.comp,
                comp_aparell=comp_ind_app,
                inscripcio=inscripcio,
                exercici=exercici,
                inputs={},
                outputs={},
                total=total,
            )

        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Derived raw team pool",
            activa=True,
            ordre=1,
            tipus="equips",
            schema={
                "puntuacio": {
                    "aparells": {"mode": "seleccionar", "ids": [comp_ind_app.id]},
                    "camps_per_aparell": {str(comp_ind_app.id): ["total"]},
                    "agregacio_camps": "sum",
                    "candidate_source_mode": "participant_aggregate",
                    "candidate_source_cfg": {
                        "mode": "millor_n",
                        "best_n": 1,
                        "index": 1,
                        "ids": [],
                        "agregacio_exercicis": "sum",
                    },
                    "exercicis": {"mode": "millor_n", "best_n": 2, "max_per_participant": 1},
                    "exercise_selection_scope": "team_pool",
                    "agregacio_exercicis": "sum",
                    "agregacio_aparells": "sum",
                    "ordre": "desc",
                },
                "presentacio": {
                    "columnes": [
                        {"type": "builtin", "key": "participant", "label": "Nom", "align": "left"},
                        {
                            "type": "raw",
                            "key": "raw_total",
                            "label": "Raw total",
                            "align": "right",
                            "decimals": 2,
                            "source": {"aparell_id": comp_ind_app.id, "exercici": 1, "camp": "total", "jutges": {"ids": []}},
                        },
                    ]
                },
                "equips": {
                    "context_code": "parelles",
                    "team_mode": "derived_from_individual",
                    "incloure_sense_equip": False,
                },
            },
        )

        rows = compute_classificacio(self.comp, cfg).get("global", [])

        payload = rows[0]["cells"]["raw_total"]
        self.assertEqual(payload["_kind"], "team_raw_detail")
        self.assertEqual(payload["summary"], 19.0)
        self.assertEqual([item["value"] for item in payload["rows"]], [10.0, 9.0])

    def test_compute_classificacio_derived_team_raw_column_respects_global_pool_per_app(self):
        app_a = self._create_aparell("TRA_RAW", "Tramp A raw")
        app_b = self._create_aparell("TRB_RAW", "Tramp B raw")
        comp_app_a = self._create_comp_aparell(self.comp, app_a, ordre=2)
        comp_app_b = self._create_comp_aparell(self.comp, app_b, ordre=3)

        for comp_aparell, inscripcio, total in (
            (comp_app_a, self.ins1, 1.0),
            (comp_app_b, self.ins1, 10.0),
            (comp_app_a, self.ins2, 2.0),
            (comp_app_b, self.ins2, 9.0),
        ):
            ScoreEntry.objects.create(
                competicio=self.comp,
                comp_aparell=comp_aparell,
                inscripcio=inscripcio,
                exercici=1,
                inputs={},
                outputs={},
                total=total,
            )

        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Derived raw global pool",
            activa=True,
            ordre=1,
            tipus="equips",
            schema={
                "puntuacio": {
                    "aparells": {"mode": "seleccionar", "ids": [comp_app_a.id, comp_app_b.id]},
                    "camps_per_aparell": {
                        str(comp_app_a.id): ["total"],
                        str(comp_app_b.id): ["total"],
                    },
                    "agregacio_camps": "sum",
                    "candidate_source_mode": "raw_exercise",
                    "candidate_source_cfg": {
                        "mode": "tots",
                        "best_n": 1,
                        "index": 1,
                        "ids": [],
                        "agregacio_exercicis": "sum",
                    },
                    "exercicis": {"mode": "millor_n", "best_n": 2, "max_per_participant": 1},
                    "exercise_selection_scope": "team_pool",
                    "mode_seleccio_exercicis": "global_pool",
                    "agregacio_exercicis": "sum",
                    "agregacio_aparells": "sum",
                    "ordre": "desc",
                },
                "presentacio": {
                    "columnes": [
                        {"type": "builtin", "key": "participant", "label": "Nom", "align": "left"},
                        {
                            "type": "raw",
                            "key": "raw_a",
                            "label": "Raw A",
                            "align": "right",
                            "decimals": 2,
                            "source": {"aparell_id": comp_app_a.id, "exercici": 1, "camp": "total", "jutges": {"ids": []}},
                        },
                        {
                            "type": "raw",
                            "key": "raw_b",
                            "label": "Raw B",
                            "align": "right",
                            "decimals": 2,
                            "source": {"aparell_id": comp_app_b.id, "exercici": 1, "camp": "total", "jutges": {"ids": []}},
                        },
                    ]
                },
                "equips": {
                    "context_code": "parelles",
                    "team_mode": "derived_from_individual",
                    "incloure_sense_equip": False,
                },
            },
        )

        rows = compute_classificacio(self.comp, cfg).get("global", [])

        self.assertEqual(rows[0]["cells"]["raw_a"], "")
        payload = rows[0]["cells"]["raw_b"]
        self.assertEqual(payload["_kind"], "team_raw_detail")
        self.assertEqual(payload["summary"], 19.0)
        self.assertEqual([item["value"] for item in payload["rows"]], [10.0, 9.0])

    def test_compute_classificacio_native_team_raw_column_returns_team_detail_payload(self):
        team_subject, _subject_meta = self._team_subject()
        TeamScoreEntry.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            team_subject=team_subject,
            exercici=1,
            inputs={"SYNC": 7.5},
            outputs={},
            total=31,
        )
        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Native raw detail",
            activa=True,
            ordre=1,
            tipus="equips",
            schema={
                "puntuacio": {
                    "aparells": {"mode": "seleccionar", "ids": [self.comp_app.id]},
                    "camps_per_aparell": {str(self.comp_app.id): ["total"]},
                    "agregacio_camps": "sum",
                    "exercicis": {"mode": "tots"},
                    "agregacio_exercicis": "sum",
                    "agregacio_aparells": "sum",
                    "ordre": "desc",
                },
                "presentacio": {
                    "columnes": [
                        {"type": "builtin", "key": "participant", "label": "Nom", "align": "left"},
                        {
                            "type": "raw",
                            "key": "raw_sync",
                            "label": "Sync",
                            "align": "right",
                            "decimals": 2,
                            "source": {"aparell_id": self.comp_app.id, "exercici": 1, "camp": "SYNC", "jutges": {"ids": []}},
                        },
                    ]
                },
                "equips": {
                    "context_code": "parelles",
                    "team_mode": "native_team",
                    "incloure_sense_equip": False,
                },
            },
        )

        rows = compute_classificacio(self.comp, cfg).get("global", [])

        payload = rows[0]["cells"]["raw_sync"]
        self.assertEqual(payload["_kind"], "team_raw_detail")
        self.assertEqual(payload["summary"], 7.5)
        self.assertEqual(payload["rows"], [{"label": "Parella 1", "value": 7.5}])

    def test_compute_classificacio_native_team_raw_column_uses_selected_team_exercises(self):
        self.comp_app.nombre_exercicis = 2
        self.comp_app.save(update_fields=["nombre_exercicis"])
        team_subject, _subject_meta = self._team_subject()
        TeamScoreEntry.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            team_subject=team_subject,
            exercici=1,
            inputs={"SYNC": 1.0},
            outputs={},
            total=10.0,
        )
        TeamScoreEntry.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            team_subject=team_subject,
            exercici=2,
            inputs={"SYNC": 7.5},
            outputs={},
            total=30.0,
        )

        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Native raw selected exercises",
            activa=True,
            ordre=1,
            tipus="equips",
            schema={
                "puntuacio": {
                    "aparells": {"mode": "seleccionar", "ids": [self.comp_app.id]},
                    "camps_per_aparell": {str(self.comp_app.id): ["total"]},
                    "agregacio_camps": "sum",
                    "exercicis": {"mode": "millor_n", "best_n": 1},
                    "agregacio_exercicis": "sum",
                    "agregacio_aparells": "sum",
                    "ordre": "desc",
                },
                "presentacio": {
                    "columnes": [
                        {"type": "builtin", "key": "participant", "label": "Nom", "align": "left"},
                        {
                            "type": "raw",
                            "key": "raw_sync",
                            "label": "Sync",
                            "align": "right",
                            "decimals": 2,
                            "source": {"aparell_id": self.comp_app.id, "exercici": 1, "camp": "SYNC", "jutges": {"ids": []}},
                        },
                    ]
                },
                "equips": {
                    "context_code": "parelles",
                    "team_mode": "native_team",
                    "incloure_sense_equip": False,
                },
            },
        )

        rows = compute_classificacio(self.comp, cfg).get("global", [])

        payload = rows[0]["cells"]["raw_sync"]
        self.assertEqual(payload["_kind"], "team_raw_detail")
        self.assertEqual(payload["summary"], 7.5)
        self.assertEqual(payload["rows"], [{"label": "Parella 1", "value": 7.5}])

    def test_compute_classificacio_derived_team_detail_payload_exposes_member_rows(self):
        ind_app = self._create_aparell("TR_DETAIL", "Tramp detail")
        comp_ind_app = self._create_comp_aparell(self.comp, ind_app, ordre=2)

        ScoreEntry.objects.create(
            competicio=self.comp,
            comp_aparell=comp_ind_app,
            inscripcio=self.ins1,
            exercici=1,
            inputs={},
            outputs={},
            total=12.5,
        )
        ScoreEntry.objects.create(
            competicio=self.comp,
            comp_aparell=comp_ind_app,
            inscripcio=self.ins2,
            exercici=1,
            inputs={},
            outputs={},
            total=11.25,
        )

        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Derived member detail",
            activa=True,
            ordre=1,
            tipus="equips",
            schema={
                "puntuacio": {
                    "aparells": {"mode": "seleccionar", "ids": [comp_ind_app.id]},
                    "camps_per_aparell": {str(comp_ind_app.id): ["total"]},
                    "agregacio_camps": "sum",
                    "exercicis": {"mode": "tots"},
                    "agregacio_exercicis": "sum",
                    "agregacio_aparells": "sum",
                    "ordre": "desc",
                },
                "presentacio": {
                    "columnes": [
                        {"type": "builtin", "key": "participant", "label": "Nom", "align": "left"},
                    ],
                    "detall": {
                        "enabled": True,
                        "default_open": True,
                        "columnes": [
                            {"type": "builtin", "key": "participant", "label": "Participant", "align": "left"},
                            {
                                "type": "raw",
                                "key": "detail_total",
                                "label": "Total",
                                "align": "right",
                                "decimals": 2,
                                "source": {
                                    "aparell_id": comp_ind_app.id,
                                    "exercici": 1,
                                    "camp": "total",
                                    "jutges": {"ids": []},
                                },
                            },
                        ],
                    },
                },
                "equips": {
                    "context_code": "parelles",
                    "team_mode": "derived_from_individual",
                    "incloure_sense_equip": False,
                },
            },
        )

        rows = compute_classificacio(self.comp, cfg).get("global", [])

        self.assertTrue(rows[0]["row_id"].startswith("team:"))
        detail = rows[0]["detail"]
        self.assertTrue(detail["default_open"])
        self.assertEqual([section["type"] for section in detail["sections"]], ["members_table"])
        members_table = detail["sections"][0]
        self.assertEqual([col["key"] for col in members_table["columns"]], ["participant", "detail_total"])
        self.assertEqual([item["participant"] for item in members_table["rows"]], ["Maria", "Laia"])
        self.assertEqual([item["cells"]["detail_total"] for item in members_table["rows"]], [12.5, 11.25])

    def test_compute_classificacio_derived_team_detail_defaults_to_participant_column(self):
        ind_app = self._create_aparell("TR_DETAIL_DEF", "Tramp detail default")
        comp_ind_app = self._create_comp_aparell(self.comp, ind_app, ordre=2)

        ScoreEntry.objects.create(
            competicio=self.comp,
            comp_aparell=comp_ind_app,
            inscripcio=self.ins1,
            exercici=1,
            inputs={},
            outputs={},
            total=12.5,
        )
        ScoreEntry.objects.create(
            competicio=self.comp,
            comp_aparell=comp_ind_app,
            inscripcio=self.ins2,
            exercici=1,
            inputs={},
            outputs={},
            total=11.25,
        )

        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Derived member detail default",
            activa=True,
            ordre=1,
            tipus="equips",
            schema={
                "puntuacio": {
                    "aparells": {"mode": "seleccionar", "ids": [comp_ind_app.id]},
                    "camps_per_aparell": {str(comp_ind_app.id): ["total"]},
                    "agregacio_camps": "sum",
                    "exercicis": {"mode": "tots"},
                    "agregacio_exercicis": "sum",
                    "agregacio_aparells": "sum",
                    "ordre": "desc",
                },
                "presentacio": {
                    "columnes": [
                        {"type": "builtin", "key": "participant", "label": "Nom", "align": "left"},
                    ],
                    "detall": {
                        "enabled": True,
                        "columnes": [],
                    },
                },
                "equips": {
                    "context_code": "parelles",
                    "team_mode": "derived_from_individual",
                    "incloure_sense_equip": False,
                },
            },
        )

        rows = compute_classificacio(self.comp, cfg).get("global", [])

        detail = rows[0]["detail"]
        self.assertEqual([section["type"] for section in detail["sections"]], ["members_table"])
        members_table = detail["sections"][0]
        self.assertEqual([col["key"] for col in members_table["columns"]], ["participant"])
        self.assertEqual([item["cells"]["participant"] for item in members_table["rows"]], ["Maria", "Laia"])

    def test_compute_classificacio_detail_enabled_without_sections_does_not_invent_defaults(self):
        ind_app = self._create_aparell("TR_DETAIL_NONE", "Tramp detail none")
        comp_ind_app = self._create_comp_aparell(self.comp, ind_app, ordre=2)

        ScoreEntry.objects.create(
            competicio=self.comp,
            comp_aparell=comp_ind_app,
            inscripcio=self.ins1,
            exercici=1,
            inputs={},
            outputs={},
            total=12.5,
        )
        ScoreEntry.objects.create(
            competicio=self.comp,
            comp_aparell=comp_ind_app,
            inscripcio=self.ins2,
            exercici=1,
            inputs={},
            outputs={},
            total=11.25,
        )

        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Derived detail no defaults",
            activa=True,
            ordre=1,
            tipus="equips",
            schema={
                "puntuacio": {
                    "aparells": {"mode": "seleccionar", "ids": [comp_ind_app.id]},
                    "camps_per_aparell": {str(comp_ind_app.id): ["total"]},
                    "agregacio_camps": "sum",
                    "exercicis": {"mode": "tots"},
                    "agregacio_exercicis": "sum",
                    "agregacio_aparells": "sum",
                    "ordre": "desc",
                },
                "presentacio": {
                    "columnes": [
                        {"type": "builtin", "key": "participant", "label": "Nom", "align": "left"},
                    ],
                    "detall": {
                        "enabled": True,
                    },
                },
                "equips": {
                    "context_code": "parelles",
                    "team_mode": "derived_from_individual",
                    "incloure_sense_equip": False,
                },
            },
        )

        rows = compute_classificacio(self.comp, cfg).get("global", [])

        self.assertNotIn("detail", rows[0])

    def test_compute_classificacio_native_team_legacy_member_table_detail_is_ignored(self):
        team_subject, _subject_meta = self._team_subject()
        TeamScoreEntry.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            team_subject=team_subject,
            exercici=1,
            inputs={"SYNC": 7.5},
            outputs={},
            total=31,
        )
        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Native detail disabled by mode",
            activa=True,
            ordre=1,
            tipus="equips",
            schema={
                "puntuacio": {
                    "aparells": {"mode": "seleccionar", "ids": [self.comp_app.id]},
                    "camps_per_aparell": {str(self.comp_app.id): ["total"]},
                    "agregacio_camps": "sum",
                    "exercicis": {"mode": "tots"},
                    "agregacio_exercicis": "sum",
                    "agregacio_aparells": "sum",
                    "ordre": "desc",
                },
                "presentacio": {
                    "columnes": [
                        {"type": "builtin", "key": "participant", "label": "Nom", "align": "left"},
                    ],
                    "detall": {
                        "enabled": True,
                        "default_open": True,
                        "columnes": [
                            {"type": "builtin", "key": "participant", "label": "Participant", "align": "left"},
                        ],
                    },
                },
                "equips": {
                    "context_code": "parelles",
                    "team_mode": "native_team",
                    "incloure_sense_equip": False,
                },
            },
        )

        rows = compute_classificacio(self.comp, cfg).get("global", [])

        self.assertTrue(rows[0]["row_id"].startswith("team:"))
        self.assertNotIn("detail", rows[0])

    def test_compute_classificacio_native_team_detail_sections_include_members_and_metrics(self):
        team_subject, _subject_meta = self._team_subject()
        TeamScoreEntry.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            team_subject=team_subject,
            exercici=1,
            inputs={"SYNC": 7.5},
            outputs={},
            total=31,
        )
        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Native detail sections",
            activa=True,
            ordre=1,
            tipus="equips",
            schema={
                "puntuacio": {
                    "aparells": {"mode": "seleccionar", "ids": [self.comp_app.id]},
                    "camps_per_aparell": {str(self.comp_app.id): ["total"]},
                    "agregacio_camps": "sum",
                    "exercicis": {"mode": "tots"},
                    "agregacio_exercicis": "sum",
                    "agregacio_aparells": "sum",
                    "ordre": "desc",
                },
                "presentacio": {
                    "columnes": [
                        {"type": "builtin", "key": "participant", "label": "Nom", "align": "left"},
                    ],
                    "detall": {
                        "enabled": True,
                        "default_open": True,
                        "sections": [
                            {"type": "members_list", "label": "Participants"},
                            {
                                "type": "team_metrics",
                                "label": "Notes equip",
                                "columns": [
                                    {
                                        "type": "raw",
                                        "key": "team_total",
                                        "label": "Total",
                                        "align": "right",
                                        "decimals": 2,
                                        "source": {
                                            "aparell_id": self.comp_app.id,
                                            "exercici": 1,
                                            "camp": "total",
                                            "jutges": {"ids": []},
                                        },
                                    },
                                ],
                            },
                        ],
                    },
                },
                "equips": {
                    "context_code": "parelles",
                    "team_mode": "native_team",
                    "incloure_sense_equip": False,
                },
            },
        )

        rows = compute_classificacio(self.comp, cfg).get("global", [])

        detail = rows[0]["detail"]
        self.assertEqual([section["type"] for section in detail["sections"]], ["members_list", "team_metrics"])
        self.assertEqual([item["participant"] for item in detail["sections"][0]["items"]], ["Maria", "Laia"])
        metrics_section = detail["sections"][1]
        self.assertEqual(metrics_section["aparell_id"], self.comp_app.id)
        self.assertEqual([col["key"] for col in metrics_section["columns"]], ["team_total"])
        metric_cell = metrics_section["rows"][0]["cells"]["team_total"]
        self.assertEqual(metric_cell["_kind"], "team_raw_detail")
        self.assertEqual(metric_cell["summary"], 31.0)

    def test_compute_classificacio_native_team_team_metrics_honors_fixed_exercise_per_section(self):
        self.comp_app.nombre_exercicis = 2
        self.comp_app.save(update_fields=["nombre_exercicis"])
        team_subject, _subject_meta = self._team_subject()
        TeamScoreEntry.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            team_subject=team_subject,
            exercici=1,
            inputs={"SYNC": 6.5},
            outputs={},
            total=20,
        )
        TeamScoreEntry.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            team_subject=team_subject,
            exercici=2,
            inputs={"SYNC": 7.4},
            outputs={},
            total=30,
        )
        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Native metrics fixed exercises",
            activa=True,
            ordre=1,
            tipus="equips",
            schema={
                "puntuacio": {
                    "aparells": {"mode": "seleccionar", "ids": [self.comp_app.id]},
                    "camps_per_aparell": {str(self.comp_app.id): ["total"]},
                    "agregacio_camps": "sum",
                    "exercicis": {"mode": "millor_n", "best_n": 1},
                    "agregacio_exercicis": "sum",
                    "agregacio_aparells": "sum",
                    "ordre": "desc",
                },
                "presentacio": {
                    "columnes": [
                        {"type": "builtin", "key": "participant", "label": "Nom", "align": "left"},
                    ],
                    "detall": {
                        "enabled": True,
                        "sections": [
                            {
                                "type": "team_metrics",
                                "label": "Exercici 1",
                                "aparell_id": self.comp_app.id,
                                "columns": [
                                    {
                                        "type": "raw",
                                        "key": "team_sync_ex1",
                                        "label": "Sync",
                                        "align": "right",
                                        "decimals": 2,
                                        "source": {
                                            "aparell_id": self.comp_app.id,
                                            "exercici": 1,
                                            "camp": "SYNC",
                                            "jutges": {"ids": []},
                                        },
                                    },
                                ],
                            },
                            {
                                "type": "team_metrics",
                                "label": "Exercici 2",
                                "aparell_id": self.comp_app.id,
                                "columns": [
                                    {
                                        "type": "raw",
                                        "key": "team_sync_ex2",
                                        "label": "Sync",
                                        "align": "right",
                                        "decimals": 2,
                                        "source": {
                                            "aparell_id": self.comp_app.id,
                                            "exercici": 2,
                                            "camp": "SYNC",
                                            "jutges": {"ids": []},
                                        },
                                    },
                                ],
                            },
                        ],
                    },
                },
                "equips": {
                    "context_code": "parelles",
                    "team_mode": "native_team",
                    "incloure_sense_equip": False,
                },
            },
        )

        rows = compute_classificacio(self.comp, cfg).get("global", [])

        detail = rows[0]["detail"]
        ex1_cell = detail["sections"][0]["rows"][0]["cells"]["team_sync_ex1"]
        ex2_cell = detail["sections"][1]["rows"][0]["cells"]["team_sync_ex2"]
        self.assertEqual(ex1_cell["_kind"], "team_raw_detail")
        self.assertEqual(ex2_cell["_kind"], "team_raw_detail")
        self.assertEqual(ex1_cell["summary"], 6.5)
        self.assertEqual(ex2_cell["summary"], 7.4)

    def test_compute_classificacio_native_team_team_members_table_uses_fixed_exercise_when_configured(self):
        self.comp_app.nombre_exercicis = 2
        self.comp_app.save(update_fields=["nombre_exercicis"])
        ScoringSchema.objects.create(
            aparell=self.app,
            schema={
                "meta": {"subject_mode": "team_context", "expected_team_size": 2},
                "fields": [
                    {"code": "SYNC", "label": "Sync", "type": "number", "scope": "shared"},
                    {"code": "E", "label": "Exec", "type": "number", "scope": "member"},
                ],
                "computed": [],
            },
        )
        team_subject, _subject_meta = self._team_subject()
        TeamScoreEntry.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            team_subject=team_subject,
            exercici=1,
            inputs={"SYNC": 6.5, "E": {str(self.ins1.id): 7.1, str(self.ins2.id): 7.0}},
            outputs={},
            total=20,
        )
        TeamScoreEntry.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            team_subject=team_subject,
            exercici=2,
            inputs={"SYNC": 7.4, "E": {str(self.ins1.id): 8.3, str(self.ins2.id): 8.1}},
            outputs={},
            total=30,
        )
        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Native member detail",
            activa=True,
            ordre=1,
            tipus="equips",
            schema={
                "puntuacio": {
                    "aparells": {"mode": "seleccionar", "ids": [self.comp_app.id]},
                    "camps_per_aparell": {str(self.comp_app.id): ["total"]},
                    "agregacio_camps": "sum",
                    "exercicis": {"mode": "millor_n", "best_n": 1},
                    "agregacio_exercicis": "sum",
                    "agregacio_aparells": "sum",
                    "ordre": "desc",
                },
                "presentacio": {
                    "columnes": [
                        {"type": "builtin", "key": "participant", "label": "Nom", "align": "left"},
                    ],
                    "detall": {
                        "enabled": True,
                        "sections": [
                            {
                                "type": "team_members_table",
                                "label": "Notes per membre",
                                "aparell_id": self.comp_app.id,
                                "columns": [
                                    {"type": "builtin", "key": "participant", "label": "Participant", "align": "left"},
                                    {
                                        "type": "raw",
                                        "key": "member_exec",
                                        "label": "Exec",
                                        "align": "right",
                                        "decimals": 2,
                                        "source": {
                                            "aparell_id": self.comp_app.id,
                                            "exercise_mode": "fixed",
                                            "exercici": 1,
                                            "camp": "E",
                                            "jutges": {"ids": []},
                                        },
                                    },
                                ],
                            },
                        ],
                    },
                },
                "equips": {
                    "context_code": "parelles",
                    "team_mode": "native_team",
                    "incloure_sense_equip": False,
                },
            },
        )

        rows = compute_classificacio(self.comp, cfg).get("global", [])

        detail = rows[0]["detail"]
        self.assertEqual([section["type"] for section in detail["sections"]], ["team_members_table"])
        members_table = detail["sections"][0]
        self.assertEqual([item["participant"] for item in members_table["rows"]], ["Maria", "Laia"])
        self.assertEqual([item["cells"]["member_exec"] for item in members_table["rows"]], [7.1, 7.0])

    def test_compute_classificacio_native_team_team_members_table_uses_selected_exercises_for_legacy_schema_without_exercise_mode(self):
        self.comp_app.nombre_exercicis = 2
        self.comp_app.save(update_fields=["nombre_exercicis"])
        ScoringSchema.objects.create(
            aparell=self.app,
            schema={
                "meta": {"subject_mode": "team_context", "expected_team_size": 2},
                "fields": [
                    {"code": "SYNC", "label": "Sync", "type": "number", "scope": "shared"},
                    {"code": "E", "label": "Exec", "type": "number", "scope": "member"},
                ],
                "computed": [],
            },
        )
        team_subject, _subject_meta = self._team_subject()
        TeamScoreEntry.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            team_subject=team_subject,
            exercici=1,
            inputs={"SYNC": 6.5, "E": {str(self.ins1.id): 7.1, str(self.ins2.id): 7.0}},
            outputs={},
            total=20,
        )
        TeamScoreEntry.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            team_subject=team_subject,
            exercici=2,
            inputs={"SYNC": 7.4, "E": {str(self.ins1.id): 8.3, str(self.ins2.id): 8.1}},
            outputs={},
            total=30,
        )
        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Native member detail selected",
            activa=True,
            ordre=1,
            tipus="equips",
            schema={
                "puntuacio": {
                    "aparells": {"mode": "seleccionar", "ids": [self.comp_app.id]},
                    "camps_per_aparell": {str(self.comp_app.id): ["total"]},
                    "agregacio_camps": "sum",
                    "exercicis": {"mode": "millor_n", "best_n": 1},
                    "agregacio_exercicis": "sum",
                    "agregacio_aparells": "sum",
                    "ordre": "desc",
                },
                "presentacio": {
                    "columnes": [
                        {"type": "builtin", "key": "participant", "label": "Nom", "align": "left"},
                    ],
                    "detall": {
                        "enabled": True,
                        "sections": [
                            {
                                "type": "team_members_table",
                                "label": "Notes per membre",
                                "aparell_id": self.comp_app.id,
                                "columns": [
                                    {
                                        "type": "raw",
                                        "key": "member_exec",
                                        "label": "Exec",
                                        "align": "right",
                                        "decimals": 2,
                                        "source": {
                                            "aparell_id": self.comp_app.id,
                                            "exercici": 1,
                                            "camp": "E",
                                            "jutges": {"ids": []},
                                        },
                                    },
                                ],
                            },
                        ],
                    },
                },
                "equips": {
                    "context_code": "parelles",
                    "team_mode": "native_team",
                    "incloure_sense_equip": False,
                },
            },
        )

        rows = compute_classificacio(self.comp, cfg).get("global", [])

        members_table = rows[0]["detail"]["sections"][0]
        self.assertEqual([item["cells"]["member_exec"] for item in members_table["rows"]], [8.3, 8.1])

    def test_compute_classificacio_native_team_team_members_table_keeps_member_judge_rows(self):
        ScoringSchema.objects.create(
            aparell=self.app,
            schema={
                "meta": {"subject_mode": "team_context", "expected_team_size": 2},
                "fields": [
                    {
                        "code": "E",
                        "label": "Exec",
                        "type": "matrix",
                        "shape": "judge_x_item",
                        "scope": "member",
                        "judges": {"count": 2},
                        "items": {"count": 2},
                    },
                ],
                "computed": [],
            },
        )
        team_subject, _subject_meta = self._team_subject()
        TeamScoreEntry.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            team_subject=team_subject,
            exercici=1,
            inputs={
                "E": {
                    str(self.ins1.id): [[8.1, 8.2], [8.0, 8.3]],
                    str(self.ins2.id): [[7.4, 7.6], [7.5, 7.7]],
                }
            },
            outputs={},
            total=30,
        )
        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Native member judge detail",
            activa=True,
            ordre=1,
            tipus="equips",
            schema={
                "puntuacio": {
                    "aparells": {"mode": "seleccionar", "ids": [self.comp_app.id]},
                    "camps_per_aparell": {str(self.comp_app.id): ["total"]},
                    "agregacio_camps": "sum",
                    "exercicis": {"mode": "tots"},
                    "agregacio_exercicis": "sum",
                    "agregacio_aparells": "sum",
                    "ordre": "desc",
                },
                "presentacio": {
                    "columnes": [
                        {"type": "builtin", "key": "participant", "label": "Nom", "align": "left"},
                    ],
                    "detall": {
                        "enabled": True,
                        "sections": [
                            {
                                "type": "team_members_table",
                                "label": "Notes per membre",
                                "aparell_id": self.comp_app.id,
                                "columns": [
                                    {
                                        "type": "raw",
                                        "key": "member_exec",
                                        "label": "Exec",
                                        "align": "right",
                                        "decimals": 2,
                                        "source": {
                                            "aparell_id": self.comp_app.id,
                                            "exercici": 1,
                                            "camp": "E",
                                            "jutges": {"ids": []},
                                        },
                                    },
                                ],
                            },
                        ],
                    },
                },
                "equips": {
                    "context_code": "parelles",
                    "team_mode": "native_team",
                    "incloure_sense_equip": False,
                },
            },
        )

        rows = compute_classificacio(self.comp, cfg).get("global", [])

        members_table = rows[0]["detail"]["sections"][0]
        self.assertEqual(members_table["rows"][0]["cells"]["member_exec"]["_kind"], "judge_rows")
        self.assertEqual(members_table["rows"][1]["cells"]["member_exec"]["_kind"], "judge_rows")
        self.assertEqual(
            members_table["rows"][0]["cells"]["member_exec"]["rows"],
            [
                {"judge": 1, "items": [8.1, 8.2]},
                {"judge": 2, "items": [8.0, 8.3]},
            ],
        )

    def test_compute_classificacio_native_team_team_members_table_resolves_member_computed_outputs_by_subject_slot(self):
        ScoringSchema.objects.create(
            aparell=self.app,
            schema={
                "meta": {"subject_mode": "team_context", "expected_team_size": 2},
                "fields": [
                    {"code": "E", "label": "Exec", "type": "number", "scope": "member"},
                ],
                "computed": [
                    {"code": "E_mem", "label": "Exec neta", "formula": "E__m1 if 1 else E__m2"},
                ],
            },
        )
        team_subject, _subject_meta = self._team_subject()
        team_subject.member_ids = [self.ins2.id, self.ins1.id]
        team_subject.save(update_fields=["member_ids"])
        TeamScoreEntry.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            team_subject=team_subject,
            exercici=1,
            inputs={"E": {str(self.ins1.id): 8.2, str(self.ins2.id): 8.1}},
            outputs={"E_mem__m1": 5.4, "E_mem__m2": 9.7},
            total=30,
        )
        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Native member computed detail",
            activa=True,
            ordre=1,
            tipus="equips",
            schema={
                "puntuacio": {
                    "aparells": {"mode": "seleccionar", "ids": [self.comp_app.id]},
                    "camps_per_aparell": {str(self.comp_app.id): ["total"]},
                    "agregacio_camps": "sum",
                    "exercicis": {"mode": "tots"},
                    "agregacio_exercicis": "sum",
                    "agregacio_aparells": "sum",
                    "ordre": "desc",
                },
                "presentacio": {
                    "columnes": [
                        {"type": "builtin", "key": "participant", "label": "Nom", "align": "left"},
                    ],
                    "detall": {
                        "enabled": True,
                        "sections": [
                            {
                                "type": "team_members_table",
                                "label": "Notes per membre",
                                "aparell_id": self.comp_app.id,
                                "columns": [
                                    {
                                        "type": "raw",
                                        "key": "member_exec_net",
                                        "label": "Exec neta",
                                        "align": "right",
                                        "decimals": 2,
                                        "source": {
                                            "aparell_id": self.comp_app.id,
                                            "exercise_mode": "fixed",
                                            "exercici": 1,
                                            "camp": "E_mem",
                                            "jutges": {"ids": []},
                                        },
                                    },
                                ],
                            },
                        ],
                    },
                },
                "equips": {
                    "context_code": "parelles",
                    "team_mode": "native_team",
                    "incloure_sense_equip": False,
                },
            },
        )

        rows = compute_classificacio(self.comp, cfg).get("global", [])

        members_table = rows[0]["detail"]["sections"][0]
        self.assertEqual([item["participant"] for item in members_table["rows"]], ["Maria", "Laia"])
        self.assertEqual([item["cells"]["member_exec_net"] for item in members_table["rows"]], [9.7, 5.4])

    def test_compute_classificacio_native_team_team_members_table_falls_back_to_row_order_for_inconsistent_subject_slots(self):
        ScoringSchema.objects.create(
            aparell=self.app,
            schema={
                "meta": {"subject_mode": "team_context", "expected_team_size": 2},
                "fields": [
                    {"code": "E", "label": "Exec", "type": "number", "scope": "member"},
                ],
                "computed": [],
            },
        )
        team_subject, _subject_meta = self._team_subject()
        team_subject.member_ids = [self.ins1.id, self.ins2.id, self.ins2.id]
        team_subject.save(update_fields=["member_ids"])
        TeamScoreEntry.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            team_subject=team_subject,
            exercici=1,
            inputs={},
            outputs={"E__m1": 6.2, "E__m2": 6.4},
            total=30,
        )
        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Native member fallback order detail",
            activa=True,
            ordre=1,
            tipus="equips",
            schema={
                "puntuacio": {
                    "aparells": {"mode": "seleccionar", "ids": [self.comp_app.id]},
                    "camps_per_aparell": {str(self.comp_app.id): ["total"]},
                    "agregacio_camps": "sum",
                    "exercicis": {"mode": "tots"},
                    "agregacio_exercicis": "sum",
                    "agregacio_aparells": "sum",
                    "ordre": "desc",
                },
                "presentacio": {
                    "columnes": [
                        {"type": "builtin", "key": "participant", "label": "Nom", "align": "left"},
                    ],
                    "detall": {
                        "enabled": True,
                        "sections": [
                            {
                                "type": "team_members_table",
                                "label": "Notes per membre",
                                "aparell_id": self.comp_app.id,
                                "columns": [
                                    {
                                        "type": "raw",
                                        "key": "member_exec",
                                        "label": "Exec",
                                        "align": "right",
                                        "decimals": 2,
                                        "source": {
                                            "aparell_id": self.comp_app.id,
                                            "exercise_mode": "fixed",
                                            "exercici": 1,
                                            "camp": "E",
                                            "jutges": {"ids": []},
                                        },
                                    },
                                ],
                            },
                        ],
                    },
                },
                "equips": {
                    "context_code": "parelles",
                    "team_mode": "native_team",
                    "incloure_sense_equip": False,
                },
            },
        )

        rows = compute_classificacio(self.comp, cfg).get("global", [])

        members_table = rows[0]["detail"]["sections"][0]
        self.assertEqual([item["cells"]["member_exec"] for item in members_table["rows"]], [6.2, 6.4])

    def test_compute_classificacio_native_team_team_members_table_keeps_blank_when_member_value_missing(self):
        ScoringSchema.objects.create(
            aparell=self.app,
            schema={
                "meta": {"subject_mode": "team_context", "expected_team_size": 2},
                "fields": [
                    {"code": "E", "label": "Exec", "type": "number", "scope": "member"},
                ],
                "computed": [],
            },
        )
        team_subject, _subject_meta = self._team_subject()
        TeamScoreEntry.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            team_subject=team_subject,
            exercici=1,
            inputs={"E": {str(self.ins1.id): 6.2}},
            outputs={},
            total=30,
        )
        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Native member missing detail",
            activa=True,
            ordre=1,
            tipus="equips",
            schema={
                "puntuacio": {
                    "aparells": {"mode": "seleccionar", "ids": [self.comp_app.id]},
                    "camps_per_aparell": {str(self.comp_app.id): ["total"]},
                    "agregacio_camps": "sum",
                    "exercicis": {"mode": "tots"},
                    "agregacio_exercicis": "sum",
                    "agregacio_aparells": "sum",
                    "ordre": "desc",
                },
                "presentacio": {
                    "columnes": [
                        {"type": "builtin", "key": "participant", "label": "Nom", "align": "left"},
                    ],
                    "detall": {
                        "enabled": True,
                        "sections": [
                            {
                                "type": "team_members_table",
                                "label": "Notes per membre",
                                "aparell_id": self.comp_app.id,
                                "columns": [
                                    {
                                        "type": "raw",
                                        "key": "member_exec",
                                        "label": "Exec",
                                        "align": "right",
                                        "decimals": 2,
                                        "source": {
                                            "aparell_id": self.comp_app.id,
                                            "exercise_mode": "fixed",
                                            "exercici": 1,
                                            "camp": "E",
                                            "jutges": {"ids": []},
                                        },
                                    },
                                ],
                            },
                        ],
                    },
                },
                "equips": {
                    "context_code": "parelles",
                    "team_mode": "native_team",
                    "incloure_sense_equip": False,
                },
            },
        )

        rows = compute_classificacio(self.comp, cfg).get("global", [])

        members_table = rows[0]["detail"]["sections"][0]
        self.assertEqual([item["cells"]["member_exec"] for item in members_table["rows"]], [6.2, ""])

    def test_compute_classificacio_individual_detail_sections_include_exercise_table(self):
        ind_app = self._create_aparell("TR_DETAIL_EX", "Tramp detail exercises")
        comp_ind_app = self._create_comp_aparell(self.comp, ind_app, ordre=2)
        comp_ind_app.nombre_exercicis = 2
        comp_ind_app.save(update_fields=["nombre_exercicis"])

        ScoreEntry.objects.create(
            competicio=self.comp,
            comp_aparell=comp_ind_app,
            inscripcio=self.ins1,
            exercici=1,
            inputs={},
            outputs={},
            total=10.5,
        )
        ScoreEntry.objects.create(
            competicio=self.comp,
            comp_aparell=comp_ind_app,
            inscripcio=self.ins1,
            exercici=2,
            inputs={},
            outputs={},
            total=11.25,
        )

        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Individual detail sections",
            activa=True,
            ordre=1,
            tipus="individual",
            schema={
                "puntuacio": {
                    "aparells": {"mode": "seleccionar", "ids": [comp_ind_app.id]},
                    "camps_per_aparell": {str(comp_ind_app.id): ["total"]},
                    "agregacio_camps": "sum",
                    "exercicis": {"mode": "tots"},
                    "agregacio_exercicis": "sum",
                    "agregacio_aparells": "sum",
                    "ordre": "desc",
                },
                "presentacio": {
                    "columnes": [
                        {"type": "builtin", "key": "participant", "label": "Nom", "align": "left"},
                    ],
                    "detall": {
                        "enabled": True,
                        "sections": [
                            {
                                "type": "exercise_table",
                                "label": "Exercicis",
                                "columns": [
                                    {"type": "builtin", "key": "aparell_nom", "label": "Aparell", "align": "left"},
                                    {"type": "builtin", "key": "exercise_index", "label": "Ex.", "align": "left"},
                                    {
                                        "type": "raw",
                                        "key": "total_ex1",
                                        "label": "Total 1",
                                        "align": "right",
                                        "decimals": 2,
                                        "source": {
                                            "aparell_id": comp_ind_app.id,
                                            "exercici": 1,
                                            "camp": "total",
                                            "jutges": {"ids": []},
                                        },
                                    },
                                    {
                                        "type": "raw",
                                        "key": "total_ex2",
                                        "label": "Total 2",
                                        "align": "right",
                                        "decimals": 2,
                                        "source": {
                                            "aparell_id": comp_ind_app.id,
                                            "exercici": 2,
                                            "camp": "total",
                                            "jutges": {"ids": []},
                                        },
                                    },
                                ],
                            },
                        ],
                    },
                },
            },
        )

        rows = compute_classificacio(self.comp, cfg).get("global", [])

        detail = rows[0]["detail"]
        self.assertEqual([section["type"] for section in detail["sections"]], ["exercise_table"])
        self.assertEqual(detail["sections"][0]["aparell_id"], comp_ind_app.id)
        exercise_rows = detail["sections"][0]["rows"]
        self.assertEqual([item["exercise_index"] for item in exercise_rows], [1, 2])
        self.assertEqual(exercise_rows[0]["cells"]["total_ex1"], 10.5)
        self.assertEqual(exercise_rows[0]["cells"]["total_ex2"], "")
        self.assertEqual(exercise_rows[1]["cells"]["total_ex1"], "")
        self.assertEqual(exercise_rows[1]["cells"]["total_ex2"], 11.25)

    def test_compute_classificacio_entitat_detail_sections_include_member_table(self):
        ind_app = self._create_aparell("TR_DETAIL_ENT", "Tramp detail entitat")
        comp_ind_app = self._create_comp_aparell(self.comp, ind_app, ordre=2)

        ScoreEntry.objects.create(
            competicio=self.comp,
            comp_aparell=comp_ind_app,
            inscripcio=self.ins1,
            exercici=1,
            inputs={},
            outputs={},
            total=12.5,
        )
        ScoreEntry.objects.create(
            competicio=self.comp,
            comp_aparell=comp_ind_app,
            inscripcio=self.ins2,
            exercici=1,
            inputs={},
            outputs={},
            total=11.0,
        )

        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Entity detail sections",
            activa=True,
            ordre=1,
            tipus="entitat",
            schema={
                "puntuacio": {
                    "aparells": {"mode": "seleccionar", "ids": [comp_ind_app.id]},
                    "camps_per_aparell": {str(comp_ind_app.id): ["total"]},
                    "agregacio_camps": "sum",
                    "exercicis": {"mode": "tots"},
                    "agregacio_exercicis": "sum",
                    "agregacio_aparells": "sum",
                    "ordre": "desc",
                },
                "presentacio": {
                    "columnes": [
                        {"type": "builtin", "key": "participant", "label": "Entitat", "align": "left"},
                    ],
                    "detall": {
                        "enabled": True,
                        "sections": [
                            {
                                "type": "entity_members_table",
                                "label": "Participants",
                                "columns": [
                                    {"type": "builtin", "key": "participant", "label": "Participant", "align": "left"},
                                    {
                                        "type": "raw",
                                        "key": "detail_total",
                                        "label": "Total",
                                        "align": "right",
                                        "decimals": 2,
                                        "source": {
                                            "aparell_id": comp_ind_app.id,
                                            "exercici": 1,
                                            "camp": "total",
                                            "jutges": {"ids": []},
                                        },
                                    },
                                ],
                            },
                        ],
                    },
                },
            },
        )

        rows = compute_classificacio(self.comp, cfg).get("global", [])

        self.assertTrue(rows[0]["row_id"].startswith("entity:"))
        detail = rows[0]["detail"]
        self.assertEqual([section["type"] for section in detail["sections"]], ["entity_members_table"])
        members_table = detail["sections"][0]
        self.assertEqual([item["participant"] for item in members_table["rows"]], ["Maria", "Laia"])
        self.assertEqual([item["cells"]["detail_total"] for item in members_table["rows"]], [12.5, 11.0])

    def test_compute_classificacio_native_team_raw_column_on_individual_app_returns_blank_for_stale_schema(self):
        ind_app = self._create_aparell("TR_STALE", "Tramp stale")
        comp_ind_app = self._create_comp_aparell(self.comp, ind_app, ordre=2)
        team_subject, _subject_meta = self._team_subject()
        TeamScoreEntry.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            team_subject=team_subject,
            exercici=1,
            inputs={"SYNC": 6.0},
            outputs={},
            total=31.0,
        )

        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Native raw stale individual app",
            activa=True,
            ordre=1,
            tipus="equips",
            schema={
                "puntuacio": {
                    "aparells": {"mode": "seleccionar", "ids": [self.comp_app.id, comp_ind_app.id]},
                    "camps_per_aparell": {
                        str(self.comp_app.id): ["total"],
                        str(comp_ind_app.id): ["total"],
                    },
                    "agregacio_camps": "sum",
                    "exercicis": {"mode": "tots"},
                    "agregacio_exercicis": "sum",
                    "agregacio_aparells": "sum",
                    "ordre": "desc",
                },
                "presentacio": {
                    "columnes": [
                        {"type": "builtin", "key": "participant", "label": "Nom", "align": "left"},
                        {
                            "type": "raw",
                            "key": "raw_invalid",
                            "label": "Raw invalid",
                            "align": "right",
                            "decimals": 2,
                            "source": {"aparell_id": comp_ind_app.id, "exercici": 1, "camp": "total", "jutges": {"ids": []}},
                        },
                    ]
                },
                "equips": {
                    "context_code": "parelles",
                    "team_mode": "native_team",
                    "incloure_sense_equip": False,
                },
            },
        )

        rows = compute_classificacio(self.comp, cfg).get("global", [])

        self.assertEqual(rows[0]["cells"]["raw_invalid"], "")

    def test_normalize_excel_cell_supports_team_raw_detail(self):
        value, _fmt, wrap = _normalize_excel_cell(
            {
                "_kind": "team_raw_detail",
                "summary": 23.75,
                "rows": [
                    {"label": "Maria", "value": 12.5},
                    {
                        "label": "Laia",
                        "judge_rows": {
                            "_kind": "judge_rows",
                            "rows": [{"judge": 1, "items": [7.4, 7.6]}],
                        },
                    },
                ],
            },
            {"decimals": 2},
        )

        self.assertEqual(value, "23.75\nMaria: 12.50\nLaia:\n  J1: 7.40 | 7.60")
        self.assertTrue(wrap)


