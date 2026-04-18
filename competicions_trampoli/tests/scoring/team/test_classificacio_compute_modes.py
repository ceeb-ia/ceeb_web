from ._shared import *  # noqa: F401,F403


class TeamContextClassificacioComputeModesTests(TeamContextScoringFlowTestBase):
    def test_compute_classificacio_uses_team_score_entry_for_team_context_app(self):
        ScoringSchema.objects.create(
            aparell=self.app,
            schema={
                "meta": {"subject_mode": "team_context", "expected_team_size": 2},
                "fields": [{"code": "TOTAL", "label": "Total", "type": "number", "scope": "shared"}],
                "computed": [],
            },
        )
        team_subject, _subject_meta = self._team_subject()
        TeamScoreEntry.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            team_subject=team_subject,
            exercici=1,
            inputs={"TOTAL": 30},
            outputs={},
            total=30,
        )
        ScoreEntry.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            inscripcio=self.ins1,
            exercici=1,
            inputs={},
            outputs={},
            total=2,
        )
        ScoreEntry.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            inscripcio=self.ins2,
            exercici=1,
            inputs={},
            outputs={},
            total=3,
        )
        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Team direct",
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
                "equips": {
                    "assignment_source": {"mode": "context", "context_code": "parelles", "fallback": "native"},
                    "incloure_sense_equip": False,
                },
            },
        )

        rows = compute_classificacio(self.comp, cfg).get("global", [])
        self.assertEqual(rows[0]["participant"], "Parella 1")
        self.assertEqual(rows[0]["score"], 30.0)

    def test_compute_classificacio_supports_new_team_mode_contract(self):
        ScoringSchema.objects.create(
            aparell=self.app,
            schema={
                "meta": {"subject_mode": "team_context", "expected_team_size": 2},
                "fields": [{"code": "TOTAL", "label": "Total", "type": "number", "scope": "shared"}],
                "computed": [],
            },
        )
        team_subject, _subject_meta = self._team_subject()
        TeamScoreEntry.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            team_subject=team_subject,
            exercici=1,
            inputs={"TOTAL": 31},
            outputs={},
            total=31,
        )
        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Team direct v1",
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
                "equips": {
                    "context_code": "parelles",
                    "team_mode": "native_team",
                    "incloure_sense_equip": False,
                },
            },
        )

        rows = compute_classificacio(self.comp, cfg).get("global", [])
        self.assertEqual(rows[0]["participant"], "Parella 1")
        self.assertEqual(rows[0]["score"], 31.0)

    def test_compute_classificacio_native_team_team_aggregate_preselects_inside_each_team(self):
        self.comp_app.nombre_exercicis = 2
        self.comp_app.save(update_fields=["nombre_exercicis"])
        team_subject_1, _subject_meta = self._team_subject()
        equip_2, _members_2 = self._create_team_with_members("Parella 2", ["Nora", "Marta"], start_order=20)
        team_subject_2, _subject_meta_2 = self._team_subject(equip_2)

        for team_subject, exercici, total in (
            (team_subject_1, 1, 10.0),
            (team_subject_1, 2, 30.0),
            (team_subject_2, 1, 15.0),
            (team_subject_2, 2, 20.0),
        ):
            TeamScoreEntry.objects.create(
                competicio=self.comp,
                comp_aparell=self.comp_app,
                team_subject=team_subject,
                exercici=exercici,
                inputs={"TOTAL": total},
                outputs={},
                total=total,
            )

        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Native team aggregate",
            activa=True,
            ordre=1,
            tipus="equips",
            schema={
                "puntuacio": {
                    "aparells": {"mode": "seleccionar", "ids": [self.comp_app.id]},
                    "camps_per_aparell": {str(self.comp_app.id): ["total"]},
                    "agregacio_camps": "sum",
                    "candidate_source_mode": "team_aggregate",
                    "candidate_source_cfg": {
                        "mode": "millor_n",
                        "best_n": 1,
                        "index": 1,
                        "ids": [],
                        "agregacio_exercicis": "sum",
                    },
                    "exercicis": {"mode": "tots"},
                    "agregacio_exercicis": "sum",
                    "agregacio_aparells": "sum",
                    "ordre": "desc",
                },
                "equips": {
                    "context_code": "parelles",
                    "team_mode": "native_team",
                    "incloure_sense_equip": False,
                },
            },
        )

        rows = compute_classificacio(self.comp, cfg).get("global", [])
        scores = {row["participant"]: row["score"] for row in rows}

        self.assertEqual(rows[0]["participant"], "Parella 1")
        self.assertEqual(scores["Parella 1"], 30.0)
        self.assertEqual(scores["Parella 2"], 20.0)

    def test_compute_classificacio_native_team_global_pool_applies_team_aggregate_per_app(self):
        app_b = self._create_aparell("SYNC_B", "Sincronitzat B")
        app_b.competition_unit = Aparell.CompetitionUnit.TEAM
        app_b.save(update_fields=["competition_unit"])
        comp_app_b = self._create_comp_aparell(self.comp, app_b, ordre=2)
        comp_app_b.nombre_exercicis = 2
        comp_app_b.save(update_fields=["nombre_exercicis"])
        CompeticioAparellEquipContextSource.objects.create(
            competicio=self.comp,
            comp_aparell=comp_app_b,
            context=self.ctx,
        )

        def team_subject_for(comp_aparell, equip):
            subjects, _issues = build_team_subjects_for_comp_aparell(self.comp, comp_aparell)
            subject_id = next(
                int(subject["subject_id"])
                for subject in subjects
                if int(subject.get("equip_id") or 0) == int(equip.id)
            )
            return TeamCompetitiveSubject.objects.get(pk=subject_id)

        equip_1 = self.equip
        equip_2, _members_2 = self._create_team_with_members("Parella 2", ["Nora", "Marta"], start_order=20)
        team_subject_a_1 = team_subject_for(self.comp_app, equip_1)
        team_subject_a_2 = team_subject_for(self.comp_app, equip_2)
        team_subject_b_1 = team_subject_for(comp_app_b, equip_1)
        team_subject_b_2 = team_subject_for(comp_app_b, equip_2)

        for comp_aparell, team_subject, exercici, total in (
            (self.comp_app, team_subject_a_1, 1, 25.0),
            (self.comp_app, team_subject_a_2, 1, 24.0),
            (comp_app_b, team_subject_b_1, 1, 5.0),
            (comp_app_b, team_subject_b_1, 2, 20.0),
            (comp_app_b, team_subject_b_2, 1, 18.0),
            (comp_app_b, team_subject_b_2, 2, 17.0),
        ):
            TeamScoreEntry.objects.create(
                competicio=self.comp,
                comp_aparell=comp_aparell,
                team_subject=team_subject,
                exercici=exercici,
                inputs={"TOTAL": total},
                outputs={},
                total=total,
            )

        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Native team global pool per app source",
            activa=True,
            ordre=1,
            tipus="equips",
            schema={
                "puntuacio": {
                    "aparells": {"mode": "seleccionar", "ids": [self.comp_app.id, comp_app_b.id]},
                    "camps_per_aparell": {
                        str(self.comp_app.id): ["total"],
                        str(comp_app_b.id): ["total"],
                    },
                    "candidate_source_mode": "raw_exercise",
                    "candidate_source_cfg": {
                        "mode": "tots",
                        "best_n": 1,
                        "index": 1,
                        "ids": [],
                        "agregacio_exercicis": "sum",
                    },
                    "candidate_source_per_aparell": {
                        str(self.comp_app.id): {"mode": "raw_exercise"},
                        str(comp_app_b.id): {
                            "mode": "team_aggregate",
                            "cfg": {
                                "mode": "millor_n",
                                "best_n": 1,
                                "index": 1,
                                "ids": [],
                                "agregacio_exercicis": "sum",
                            },
                        },
                    },
                    "exercicis": {"mode": "millor_n", "best_n": 2},
                    "mode_seleccio_exercicis": "global_pool",
                    "agregacio_camps": "sum",
                    "agregacio_exercicis": "sum",
                    "agregacio_aparells": "sum",
                    "ordre": "desc",
                },
                "equips": {
                    "context_code": "parelles",
                    "team_mode": "native_team",
                    "incloure_sense_equip": False,
                },
            },
        )

        rows = compute_classificacio(self.comp, cfg).get("global", [])
        scores = {row["participant"]: row["score"] for row in rows}

        self.assertEqual(rows[0]["participant"], "Parella 1")
        self.assertEqual(scores["Parella 1"], 45.0)
        self.assertEqual(scores["Parella 2"], 42.0)

    def test_compute_classificacio_derived_team_pool_selects_best_n_with_member_cap(self):
        ind_app = self._create_aparell("TR", "Tramp")
        comp_ind_app = self._create_comp_aparell(self.comp, ind_app, ordre=2)
        comp_ind_app.nombre_exercicis = 2
        comp_ind_app.save(update_fields=["nombre_exercicis"])
        equip_2, members_2 = self._create_team_with_members("Parella 2", ["Nora", "Marta"], start_order=20)

        for ins, exercici, total in (
            (self.ins1, 1, 9.0),
            (self.ins1, 2, 8.0),
            (self.ins2, 1, 7.0),
            (self.ins2, 2, 6.0),
            (members_2[0], 1, 9.0),
            (members_2[0], 2, 5.0),
            (members_2[1], 1, 8.0),
            (members_2[1], 2, 7.0),
        ):
            ScoreEntry.objects.create(
                competicio=self.comp,
                comp_aparell=comp_ind_app,
                inscripcio=ins,
                exercici=exercici,
                inputs={},
                outputs={},
                total=total,
            )

        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Derived team pool",
            activa=True,
            ordre=1,
            tipus="equips",
            schema={
                "puntuacio": {
                    "aparells": {"mode": "seleccionar", "ids": [comp_ind_app.id]},
                    "camps_per_aparell": {str(comp_ind_app.id): ["total"]},
                    "agregacio_camps": "sum",
                    "exercicis": {
                        "mode": "millor_n",
                        "best_n": 2,
                        "max_per_participant": 1,
                    },
                    "exercise_selection_scope": "team_pool",
                    "agregacio_exercicis": "sum",
                    "agregacio_aparells": "sum",
                    "ordre": "desc",
                },
                "equips": {
                    "context_code": "parelles",
                    "team_mode": "derived_from_individual",
                    "incloure_sense_equip": False,
                },
            },
        )

        rows = compute_classificacio(self.comp, cfg).get("global", [])
        self.assertEqual([row["participant"] for row in rows[:2]], ["Parella 2", "Parella 1"])
        self.assertEqual(rows[0]["punts"], 17.0)
        self.assertEqual(rows[1]["punts"], 16.0)

    def test_compute_classificacio_derived_team_pool_tie_break_uses_team_pool(self):
        ind_app = self._create_aparell("DMT", "Double Mini")
        comp_ind_app = self._create_comp_aparell(self.comp, ind_app, ordre=2)
        comp_ind_app.nombre_exercicis = 2
        comp_ind_app.save(update_fields=["nombre_exercicis"])
        equip_2, members_2 = self._create_team_with_members("Parella 2", ["Nora", "Marta"], start_order=20)

        for ins, exercici, total, d_value in (
            (self.ins1, 1, 10.0, 100.0),
            (self.ins1, 2, 1.0, 0.0),
            (self.ins2, 1, 7.0, 0.0),
            (self.ins2, 2, 0.0, 0.0),
            (members_2[0], 1, 9.0, 50.0),
            (members_2[0], 2, 2.0, 0.0),
            (members_2[1], 1, 8.0, 60.0),
            (members_2[1], 2, 1.0, 0.0),
        ):
            ScoreEntry.objects.create(
                competicio=self.comp,
                comp_aparell=comp_ind_app,
                inscripcio=ins,
                exercici=exercici,
                inputs={"D": d_value},
                outputs={},
                total=total,
            )

        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Derived team pool tie",
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
                "desempat": [
                    {
                        "camps": ["D"],
                        "ordre": "desc",
                        "exercise_selection_scope": "team_pool",
                        "scope": {
                            "aparells": {"mode": "seleccionar", "ids": [comp_ind_app.id]},
                        },
                        "agregacio_camps": "sum",
                        "agregacio_exercicis": "sum",
                        "agregacio_aparells": "sum",
                    }
                ],
                "equips": {
                    "context_code": "parelles",
                    "team_mode": "derived_from_individual",
                    "incloure_sense_equip": False,
                },
            },
        )

        rows = compute_classificacio(self.comp, cfg).get("global", [])
        self.assertEqual([row["participant"] for row in rows[:2]], ["Parella 2", "Parella 1"])

    def test_compute_classificacio_derived_team_per_exercise_fields_affect_member_scores(self):
        ind_app = self._create_aparell("TR_PER_EX", "Tramp Per Exercici")
        comp_ind_app = self._create_comp_aparell(self.comp, ind_app, ordre=2)
        comp_ind_app.nombre_exercicis = 2
        comp_ind_app.save(update_fields=["nombre_exercicis"])
        equip_2, members_2 = self._create_team_with_members("Parella 2", ["Nora", "Marta"], start_order=20)
        ScoringSchema.objects.create(
            aparell=ind_app,
            schema={
                "fields": [
                    {"code": "A", "label": "Camp A", "type": "number"},
                    {"code": "B", "label": "Camp B", "type": "number"},
                ],
                "computed": [],
            },
        )

        for ins, exercici, a_value, b_value in (
            (self.ins1, 1, 4.0, 40.0),
            (self.ins1, 2, 1.0, 6.0),
            (self.ins2, 1, 5.0, 50.0),
            (self.ins2, 2, 1.0, 7.0),
            (members_2[0], 1, 3.0, 30.0),
            (members_2[0], 2, 1.0, 4.0),
            (members_2[1], 1, 2.0, 20.0),
            (members_2[1], 2, 1.0, 3.0),
        ):
            ScoreEntry.objects.create(
                competicio=self.comp,
                comp_aparell=comp_ind_app,
                inscripcio=ins,
                exercici=exercici,
                inputs={"A": a_value, "B": b_value},
                outputs={},
                total=0,
            )

        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Derived per exercise fields",
            activa=True,
            ordre=1,
            tipus="equips",
            schema={
                "puntuacio": {
                    "aparells": {"mode": "seleccionar", "ids": [comp_ind_app.id]},
                    "camps_per_aparell": {str(comp_ind_app.id): ["A"]},
                    "agregacio_camps_per_aparell": {str(comp_ind_app.id): "sum"},
                    "camps_mode_per_aparell": {str(comp_ind_app.id): "per_exercici"},
                    "camps_per_exercici_per_aparell": {
                        str(comp_ind_app.id): {
                            "1": ["A"],
                            "2": ["B"],
                        }
                    },
                    "agregacio_camps_per_exercici_per_aparell": {
                        str(comp_ind_app.id): {
                            "1": "sum",
                            "2": "sum",
                        }
                    },
                    "agregacio_camps": "sum",
                    "exercicis": {"mode": "tots"},
                    "exercise_selection_scope": "per_member",
                    "agregacio_exercicis": "sum",
                    "agregacio_aparells": "sum",
                    "ordre": "desc",
                },
                "equips": {
                    "context_code": "parelles",
                    "team_mode": "derived_from_individual",
                    "incloure_sense_equip": False,
                },
            },
        )

        rows = compute_classificacio(self.comp, cfg).get("global", [])
        scores = {row["participant"]: row["score"] for row in rows}

        self.assertEqual(rows[0]["participant"], "Parella 1")
        self.assertEqual(scores["Parella 1"], 22.0)
        self.assertEqual(scores["Parella 2"], 12.0)

    def test_compute_classificacio_native_team_per_exercise_fields_affect_team_scores(self):
        self.comp_app.nombre_exercicis = 2
        self.comp_app.save(update_fields=["nombre_exercicis"])
        equip_2, _members_2 = self._create_team_with_members("Parella 2", ["Nora", "Marta"], start_order=20)
        ScoringSchema.objects.create(
            aparell=self.app,
            schema={
                "meta": {"subject_mode": "team_context", "expected_team_size": 2},
                "fields": [
                    {"code": "A", "label": "Camp A", "type": "number", "scope": "shared"},
                    {"code": "B", "label": "Camp B", "type": "number", "scope": "shared"},
                ],
                "computed": [],
            },
        )
        team_subject_1, _subject_meta_1 = self._team_subject()
        team_subject_2, _subject_meta_2 = self._team_subject(equip_2)

        for team_subject, exercici, a_value, b_value in (
            (team_subject_1, 1, 10.0, 1.0),
            (team_subject_1, 2, 2.0, 20.0),
            (team_subject_2, 1, 9.0, 50.0),
            (team_subject_2, 2, 3.0, 5.0),
        ):
            TeamScoreEntry.objects.create(
                competicio=self.comp,
                comp_aparell=self.comp_app,
                team_subject=team_subject,
                exercici=exercici,
                inputs={"A": a_value, "B": b_value},
                outputs={},
                total=0,
            )

        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Native team per exercise fields",
            activa=True,
            ordre=1,
            tipus="equips",
            schema={
                "puntuacio": {
                    "aparells": {"mode": "seleccionar", "ids": [self.comp_app.id]},
                    "camps_per_aparell": {str(self.comp_app.id): ["A"]},
                    "agregacio_camps_per_aparell": {str(self.comp_app.id): "sum"},
                    "camps_mode_per_aparell": {str(self.comp_app.id): "per_exercici"},
                    "camps_per_exercici_per_aparell": {
                        str(self.comp_app.id): {
                            "1": ["A"],
                            "2": ["B"],
                        }
                    },
                    "agregacio_camps_per_exercici_per_aparell": {
                        str(self.comp_app.id): {
                            "1": "sum",
                            "2": "sum",
                        }
                    },
                    "agregacio_camps": "sum",
                    "exercicis": {"mode": "tots"},
                    "agregacio_exercicis": "sum",
                    "agregacio_aparells": "sum",
                    "ordre": "desc",
                },
                "equips": {
                    "context_code": "parelles",
                    "team_mode": "native_team",
                    "incloure_sense_equip": False,
                },
            },
        )

        rows = compute_classificacio(self.comp, cfg).get("global", [])
        scores = {row["participant"]: row["score"] for row in rows}

        self.assertEqual(rows[0]["participant"], "Parella 1")
        self.assertEqual(scores["Parella 1"], 30.0)
        self.assertEqual(scores["Parella 2"], 14.0)

    def test_compute_classificacio_derived_team_per_member_selects_participants_per_app_before_aggregating_apps(self):
        _app_a, comp_app_a = self._create_individual_comp_aparell("TR_PM_A", "Tramp per member A", ordre=2)
        _app_b, comp_app_b = self._create_individual_comp_aparell("TR_PM_B", "Tramp per member B", ordre=3)

        for inscripcio, total_a, total_b in (
            (self.ins1, 100.0, 1.0),
            (self.ins2, 90.0, 90.0),
        ):
            ScoreEntry.objects.create(
                competicio=self.comp,
                comp_aparell=comp_app_a,
                inscripcio=inscripcio,
                exercici=1,
                inputs={},
                outputs={},
                total=total_a,
            )
            ScoreEntry.objects.create(
                competicio=self.comp,
                comp_aparell=comp_app_b,
                inscripcio=inscripcio,
                exercici=1,
                inputs={},
                outputs={},
                total=total_b,
            )

        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Derived per member ordering",
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
                    "exercicis": {"mode": "tots"},
                    "exercise_selection_scope": "per_member",
                    "participants_per_aparell": {
                        str(comp_app_a.id): {"mode": "millor_1"},
                        str(comp_app_b.id): {"mode": "millor_1"},
                    },
                    "agregacio_participants_per_aparell": {
                        str(comp_app_a.id): "sum",
                        str(comp_app_b.id): "sum",
                    },
                    "agregacio_exercicis": "sum",
                    "agregacio_aparells": "sum",
                    "ordre": "desc",
                },
                "equips": {
                    "context_code": "parelles",
                    "team_mode": "derived_from_individual",
                    "incloure_sense_equip": False,
                },
            },
        )

        rows = compute_classificacio(self.comp, cfg).get("global", [])

        self.assertEqual(rows[0]["participant"], "Parella 1")
        self.assertEqual(rows[0]["score"], 190.0)

    def test_compute_classificacio_derived_team_per_member_falls_back_to_default_participant_selection_per_app(self):
        _app_a, comp_app_a = self._create_individual_comp_aparell("TR_PM_FA", "Tramp per member fallback A", ordre=2)
        _app_b, comp_app_b = self._create_individual_comp_aparell("TR_PM_FB", "Tramp per member fallback B", ordre=3)

        for inscripcio, total_a, total_b in (
            (self.ins1, 100.0, 1.0),
            (self.ins2, 90.0, 90.0),
        ):
            ScoreEntry.objects.create(
                competicio=self.comp,
                comp_aparell=comp_app_a,
                inscripcio=inscripcio,
                exercici=1,
                inputs={},
                outputs={},
                total=total_a,
            )
            ScoreEntry.objects.create(
                competicio=self.comp,
                comp_aparell=comp_app_b,
                inscripcio=inscripcio,
                exercici=1,
                inputs={},
                outputs={},
                total=total_b,
            )

        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Derived per member fallback",
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
                    "exercicis": {"mode": "tots"},
                    "exercise_selection_scope": "per_member",
                    "participants_per_aparell": {
                        str(comp_app_a.id): {"mode": "millor_1"},
                    },
                    "agregacio_participants_per_aparell": {
                        str(comp_app_a.id): "sum",
                    },
                    "agregacio_exercicis": "sum",
                    "agregacio_aparells": "sum",
                    "ordre": "desc",
                },
                "equips": {
                    "context_code": "parelles",
                    "team_mode": "derived_from_individual",
                    "incloure_sense_equip": False,
                },
            },
        )

        rows = compute_classificacio(self.comp, cfg).get("global", [])

        self.assertEqual(rows[0]["participant"], "Parella 1")
        self.assertEqual(rows[0]["score"], 191.0)

    def test_compute_classificacio_native_team_tie_uses_team_scores_only(self):
        equip_2, _members = self._create_team_with_members("Parella 2", ["Nora", "Marta"], start_order=20)
        ScoringSchema.objects.create(
            aparell=self.app,
            schema={
                "meta": {"subject_mode": "team_context", "expected_team_size": 2},
                "fields": [
                    {"code": "SYNC", "label": "Sync", "type": "number", "scope": "shared"},
                    {"code": "E", "label": "Exec", "type": "number", "scope": "member"},
                ],
                "computed": [
                    {"code": "TEAM_SYNC", "label": "Team sync", "formula": "SYNC"},
                ],
            },
        )
        team_subject_1, _subject_meta_1 = self._team_subject(self.equip)
        team_subject_2, _subject_meta_2 = self._team_subject(equip_2)
        TeamScoreEntry.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            team_subject=team_subject_1,
            exercici=1,
            inputs={"SYNC": 9},
            outputs={"TEAM_SYNC": 9},
            total=30,
        )
        TeamScoreEntry.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            team_subject=team_subject_2,
            exercici=1,
            inputs={"SYNC": 7},
            outputs={"TEAM_SYNC": 7},
            total=30,
        )
        ScoreEntry.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            inscripcio=self.ins1,
            exercici=1,
            inputs={"TOTAL": 999},
            outputs={},
            total=999,
        )
        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Team tie strict",
            activa=True,
            ordre=1,
            tipus="equips",
            schema={
                **self._native_team_schema_with_tie({"camps": ["TEAM_SYNC"], "ordre": "desc"}),
            },
        )

        rows = compute_classificacio(self.comp, cfg).get("global", [])

        self.assertEqual([row["participant"] for row in rows], ["Parella 1", "Parella 2"])

    def test_compute_classificacio_team_tie_break_uses_team_score_entries(self):
        equip2, members2 = self._create_team_with_members("Parella 2", ["Nora", "Marta"], start_order=30)
        team_subject, _subject_meta = self._team_subject()
        team_subject_2, _subject_meta_2 = self._team_subject(equip2)
        TeamScoreEntry.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            team_subject=team_subject,
            exercici=1,
            inputs={"TOTAL": 30},
            outputs={"SYNC": 9},
            total=30,
        )
        TeamScoreEntry.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            team_subject=team_subject_2,
            exercici=1,
            inputs={"TOTAL": 30},
            outputs={"SYNC": 8},
            total=30,
        )
        for ins, raw_total in [(self.ins1, 1), (self.ins2, 1), (members2[0], 50), (members2[1], 50)]:
            ScoreEntry.objects.create(
                competicio=self.comp,
                comp_aparell=self.comp_app,
                inscripcio=ins,
                exercici=1,
                inputs={},
                outputs={"SYNC": raw_total},
                total=raw_total,
            )
        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Team tiebreak",
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
                "desempat": [
                    {
                        "camp": "SYNC",
                        "ordre": "desc",
                        "scope": {"aparells": {"mode": "seleccionar", "ids": [self.comp_app.id]}},
                    }
                ],
                "equips": {
                    "assignment_source": {"mode": "context", "context_code": "parelles", "fallback": "native"},
                    "incloure_sense_equip": False,
                },
            },
        )
        rows = compute_classificacio(self.comp, cfg).get("global", [])
        self.assertEqual([row["participant"] for row in rows[:2]], ["Parella 1", "Parella 2"])

    def test_compute_classificacio_derived_team_pool_selects_best_rows_per_team(self):
        individual_app = self._create_aparell("TR", "Tramp")
        individual_comp_app = self._create_comp_aparell(self.comp, individual_app, ordre=2)
        equip_2, members_2 = self._create_team_with_members("Parella 2", ["Nora", "Marta"], start_order=20)

        for inscripcio, exercici, total in (
            (self.ins1, 1, 9.0),
            (self.ins1, 2, 8.0),
            (self.ins2, 1, 7.0),
            (self.ins2, 2, 6.0),
            (members_2[0], 1, 8.5),
            (members_2[0], 2, 7.5),
            (members_2[1], 1, 8.0),
            (members_2[1], 2, 6.0),
        ):
            ScoreEntry.objects.create(
                competicio=self.comp,
                comp_aparell=individual_comp_app,
                inscripcio=inscripcio,
                exercici=exercici,
                inputs={},
                outputs={},
                total=total,
            )

        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Derived team pool main",
            activa=True,
            ordre=1,
            tipus="equips",
            schema={
                "puntuacio": {
                    "aparells": {"mode": "seleccionar", "ids": [individual_comp_app.id]},
                    "camps_per_aparell": {str(individual_comp_app.id): ["total"]},
                    "agregacio_camps": "sum",
                    "exercicis": {"mode": "millor_n", "best_n": 2, "max_per_participant": 1},
                    "exercise_selection_scope": "team_pool",
                    "agregacio_exercicis": "sum",
                    "agregacio_aparells": "sum",
                    "ordre": "desc",
                },
                "equips": {
                    "context_code": "parelles",
                    "team_mode": "derived_from_individual",
                    "incloure_sense_equip": False,
                },
            },
        )

        rows = compute_classificacio(self.comp, cfg).get("global", [])

        self.assertEqual([row["participant"] for row in rows[:2]], ["Parella 2", "Parella 1"])
        scores = {row["participant"]: row["score"] for row in rows}
        self.assertEqual(scores["Parella 1"], 16.0)
        self.assertEqual(scores["Parella 2"], 16.5)

    def test_compute_classificacio_derived_team_pool_global_pool_respects_member_cap(self):
        app_a = self._create_aparell("TRA", "Tramp A")
        app_b = self._create_aparell("TRB", "Tramp B")
        comp_app_a = self._create_comp_aparell(self.comp, app_a, ordre=2)
        comp_app_b = self._create_comp_aparell(self.comp, app_b, ordre=3)
        equip_2, members_2 = self._create_team_with_members("Parella 2", ["Nora", "Marta"], start_order=20)

        for comp_aparell, inscripcio, total in (
            (comp_app_a, self.ins1, 9.0),
            (comp_app_b, self.ins1, 8.0),
            (comp_app_a, self.ins2, 7.0),
            (comp_app_b, self.ins2, 6.0),
            (comp_app_a, members_2[0], 7.5),
            (comp_app_b, members_2[0], 7.0),
            (comp_app_a, members_2[1], 6.0),
            (comp_app_b, members_2[1], 5.5),
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
            nom="Derived team pool global",
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
                    "candidate_source_mode": "participant_aggregate",
                    "candidate_source_cfg": {
                        "mode": "millor_n",
                        "best_n": 2,
                        "index": 1,
                        "ids": [],
                        "agregacio_exercicis": "sum",
                    },
                    "exercicis": {"mode": "millor_n", "best_n": 3, "max_per_participant": 2},
                    "exercise_selection_scope": "team_pool",
                    "mode_seleccio_exercicis": "global_pool",
                    "agregacio_exercicis": "sum",
                    "agregacio_aparells": "sum",
                    "ordre": "desc",
                },
                "equips": {
                    "context_code": "parelles",
                    "team_mode": "derived_from_individual",
                    "incloure_sense_equip": False,
                },
            },
        )

        rows = compute_classificacio(self.comp, cfg).get("global", [])

        self.assertEqual([row["participant"] for row in rows[:2]], ["Parella 1", "Parella 2"])
        scores = {row["participant"]: row["score"] for row in rows}
        self.assertEqual(scores["Parella 1"], 24.0)
        self.assertEqual(scores["Parella 2"], 20.5)

    def test_compute_classificacio_derived_team_pool_tie_break_reuses_main_selected_rows(self):
        individual_app = self._create_aparell("TRT", "Tramp tie")
        individual_comp_app = self._create_comp_aparell(self.comp, individual_app, ordre=2)
        individual_comp_app.nombre_exercicis = 2
        individual_comp_app.save(update_fields=["nombre_exercicis"])
        equip_2, members_2 = self._create_team_with_members("Parella 2", ["Nora", "Marta"], start_order=20)

        for inscripcio, exercici, total, d_value in (
            (self.ins1, 1, 10.0, 1.0),
            (self.ins1, 2, 1.0, 100.0),
            (self.ins2, 1, 7.0, 7.0),
            (self.ins2, 2, 0.0, 0.0),
            (members_2[0], 1, 9.0, 5.0),
            (members_2[0], 2, 2.0, 6.0),
            (members_2[1], 1, 8.0, 4.0),
            (members_2[1], 2, 1.0, 5.0),
        ):
            ScoreEntry.objects.create(
                competicio=self.comp,
                comp_aparell=individual_comp_app,
                inscripcio=inscripcio,
                exercici=exercici,
                inputs={"D": d_value},
                outputs={},
                total=total,
            )

        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Derived team pool tie fixed rows",
            activa=True,
            ordre=1,
            tipus="equips",
            schema={
                "puntuacio": {
                    "aparells": {"mode": "seleccionar", "ids": [individual_comp_app.id]},
                    "camps_per_aparell": {str(individual_comp_app.id): ["total"]},
                    "agregacio_camps": "sum",
                    "exercicis": {"mode": "millor_n", "best_n": 2, "max_per_participant": 1},
                    "exercise_selection_scope": "team_pool",
                    "agregacio_exercicis": "sum",
                    "agregacio_aparells": "sum",
                    "ordre": "desc",
                },
                "desempat": [
                    {
                        "camps": ["D"],
                        "ordre": "desc",
                        "exercise_selection_scope": "team_pool",
                        "scope": {
                            "aparells": {"mode": "seleccionar", "ids": [individual_comp_app.id]},
                        },
                        "agregacio_camps": "sum",
                        "agregacio_exercicis": "sum",
                        "agregacio_aparells": "sum",
                    }
                ],
                "equips": {
                    "context_code": "parelles",
                    "team_mode": "derived_from_individual",
                    "incloure_sense_equip": False,
                },
            },
        )

        rows = compute_classificacio(self.comp, cfg).get("global", [])

        self.assertEqual([row["participant"] for row in rows[:2]], ["Parella 2", "Parella 1"])
        self.assertEqual(rows[0]["score"], 17.0)
        self.assertEqual(rows[1]["score"], 17.0)

    def test_compute_classificacio_derived_team_pool_pipeline_reuses_main_selected_rows(self):
        individual_app = self._create_aparell("TRP", "Tramp tie pipeline")
        individual_comp_app = self._create_comp_aparell(self.comp, individual_app, ordre=2)
        individual_comp_app.nombre_exercicis = 2
        individual_comp_app.save(update_fields=["nombre_exercicis"])
        _equip_2, members_2 = self._create_team_with_members("Parella 2", ["Nora", "Marta"], start_order=20)

        for inscripcio, exercici, total, d_value in (
            (self.ins1, 1, 10.0, 1.0),
            (self.ins1, 2, 1.0, 100.0),
            (self.ins2, 1, 7.0, 7.0),
            (self.ins2, 2, 0.0, 0.0),
            (members_2[0], 1, 9.0, 5.0),
            (members_2[0], 2, 2.0, 6.0),
            (members_2[1], 1, 8.0, 4.0),
            (members_2[1], 2, 1.0, 5.0),
        ):
            ScoreEntry.objects.create(
                competicio=self.comp,
                comp_aparell=individual_comp_app,
                inscripcio=inscripcio,
                exercici=exercici,
                inputs={"D": d_value},
                outputs={},
                total=total,
            )

        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Derived team pool tie pipeline",
            activa=True,
            ordre=1,
            tipus="equips",
            schema={
                "puntuacio": {
                    "aparells": {"mode": "seleccionar", "ids": [individual_comp_app.id]},
                    "camps_per_aparell": {str(individual_comp_app.id): ["total"]},
                    "agregacio_camps_per_aparell": {str(individual_comp_app.id): "sum"},
                    "candidate_source_per_aparell": {str(individual_comp_app.id): {"mode": "raw_exercise"}},
                    "agregacio_camps": "sum",
                    "exercicis": {"mode": "millor_n", "best_n": 2, "max_per_participant": 1},
                    "exercise_selection_scope": "team_pool",
                    "mode_seleccio_exercicis": "per_aparell_global",
                    "agregacio_exercicis": "sum",
                    "agregacio_aparells": "sum",
                    "ordre": "desc",
                },
                "desempat": [
                    {
                        "id": "tie_team_pool_pipeline",
                        "ordre": "desc",
                        "pipeline_version": 1,
                        "pipeline": {
                            "aparells": {"mode": "seleccionar", "ids": [individual_comp_app.id]},
                            "camps_per_aparell": {str(individual_comp_app.id): ["D"]},
                            "agregacio_camps_per_aparell": {str(individual_comp_app.id): "sum"},
                            "agregacio_camps": "sum",
                            "candidate_source_mode": "raw_exercise",
                            "candidate_source_cfg": {
                                "mode": "tots",
                                "best_n": 1,
                                "index": 1,
                                "ids": [],
                                "agregacio_exercicis": "sum",
                            },
                            "candidate_source_per_aparell": {str(individual_comp_app.id): {"mode": "raw_exercise"}},
                            "exercicis": {"mode": "tots"},
                            "exercise_selection_scope": "team_pool",
                            "mode_seleccio_exercicis": "per_aparell_global",
                            "agregacio_exercicis": "sum",
                            "agregacio_aparells": "sum",
                            "mode_resultat_aparells": "score",
                            "ordre": "desc",
                            "participants": {"mode": "tots"},
                            "agregacio_participants": "sum",
                        },
                    }
                ],
                "equips": {
                    "context_code": "parelles",
                    "team_mode": "derived_from_individual",
                    "incloure_sense_equip": False,
                },
            },
        )

        rows = compute_classificacio(self.comp, cfg).get("global", [])
        self.assertEqual([row["participant"] for row in rows[:2]], ["Parella 2", "Parella 1"])

    def test_compute_classificacio_derived_per_member_pipeline_can_use_main_selected_contributors(self):
        individual_app = self._create_aparell("TRPMC", "Tramp contributors")
        individual_comp_app = self._create_comp_aparell(self.comp, individual_app, ordre=2)
        individual_comp_app.nombre_exercicis = 2
        individual_comp_app.save(update_fields=["nombre_exercicis"])
        _equip_2, members_2 = self._create_team_with_members("Parella 2", ["Nora", "Marta"], start_order=20)

        for inscripcio, exercici, total, d_value in (
            (self.ins1, 1, 10.0, 1.0),
            (self.ins1, 2, 0.0, 100.0),
            (self.ins2, 1, 9.0, 9.0),
            (self.ins2, 2, 0.0, 0.0),
            (members_2[0], 1, 10.0, 5.0),
            (members_2[0], 2, 0.0, 50.0),
            (members_2[1], 1, 9.0, 8.0),
            (members_2[1], 2, 0.0, 0.0),
        ):
            ScoreEntry.objects.create(
                competicio=self.comp,
                comp_aparell=individual_comp_app,
                inscripcio=inscripcio,
                exercici=exercici,
                inputs={"D": d_value},
                outputs={},
                total=total,
            )

        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Derived contributors tie",
            activa=True,
            ordre=1,
            tipus="equips",
            schema={
                "puntuacio": {
                    "aparells": {"mode": "seleccionar", "ids": [individual_comp_app.id]},
                    "camps_per_aparell": {str(individual_comp_app.id): ["total"]},
                    "agregacio_camps_per_aparell": {str(individual_comp_app.id): "sum"},
                    "agregacio_camps": "sum",
                    "candidate_source_per_aparell": {str(individual_comp_app.id): {"mode": "raw_exercise"}},
                    "exercicis": {"mode": "millor_1"},
                    "exercise_selection_scope": "per_member",
                    "mode_seleccio_exercicis": "per_aparell_global",
                    "participants_per_aparell": {str(individual_comp_app.id): {"mode": "millor_1"}},
                    "agregacio_participants_per_aparell": {str(individual_comp_app.id): "sum"},
                    "agregacio_exercicis": "sum",
                    "agregacio_aparells": "sum",
                    "ordre": "desc",
                },
                "desempat": [
                    {
                        "id": "tie_contributors_derived",
                        "ordre": "desc",
                        "pipeline_version": 1,
                        "pipeline": {
                            "input_source": {"mode": "main_selected_contributors"},
                            "aparells": {"mode": "seleccionar", "ids": [individual_comp_app.id]},
                            "camps_per_aparell": {str(individual_comp_app.id): ["D"]},
                            "agregacio_camps_per_aparell": {str(individual_comp_app.id): "sum"},
                            "agregacio_camps": "sum",
                            "candidate_source_mode": "raw_exercise",
                            "candidate_source_per_aparell": {str(individual_comp_app.id): {"mode": "raw_exercise"}},
                            "exercicis": {"mode": "tots"},
                            "exercise_selection_scope": "per_member",
                            "mode_seleccio_exercicis": "per_aparell_global",
                            "participants_per_aparell": {str(individual_comp_app.id): {"mode": "millor_1"}},
                            "agregacio_participants_per_aparell": {str(individual_comp_app.id): "sum"},
                            "agregacio_exercicis": "sum",
                            "agregacio_aparells": "sum",
                            "mode_resultat_aparells": "score",
                            "ordre": "desc",
                        },
                    }
                ],
                "equips": {
                    "context_code": "parelles",
                    "team_mode": "derived_from_individual",
                    "incloure_sense_equip": False,
                },
            },
        )

        rows = compute_classificacio(self.comp, cfg).get("global", [])
        self.assertEqual([row["participant"] for row in rows[:2]], ["Parella 2", "Parella 1"])
        self.assertEqual(rows[0]["score"], 10.0)
        self.assertEqual(rows[1]["score"], 10.0)

    def test_compute_classificacio_native_team_pipeline_can_use_main_selected_contributors(self):
        self.comp_app.nombre_exercicis = 2
        self.comp_app.save(update_fields=["nombre_exercicis"])
        equip_2, _members_2 = self._create_team_with_members("Parella 2", ["Nora", "Marta"], start_order=20)

        ScoringSchema.objects.create(
            aparell=self.app,
            schema={
                "meta": {"subject_mode": "team_context", "expected_team_size": 2},
                "fields": [
                    {"code": "TOTAL", "label": "Total", "type": "number", "scope": "shared"},
                    {"code": "D", "label": "D", "type": "number", "scope": "shared"},
                ],
                "computed": [],
            },
        )
        team_subject_1, _subject_meta = self._team_subject(self.equip)
        team_subject_2, _subject_meta = self._team_subject(equip_2)

        for team_subject, exercici, total, d_value in (
            (team_subject_1, 1, 10.0, 1.0),
            (team_subject_1, 2, 0.0, 100.0),
            (team_subject_2, 1, 10.0, 5.0),
            (team_subject_2, 2, 0.0, 50.0),
        ):
            TeamScoreEntry.objects.create(
                competicio=self.comp,
                comp_aparell=self.comp_app,
                team_subject=team_subject,
                exercici=exercici,
                inputs={"D": d_value},
                outputs={},
                total=total,
            )

        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Native contributors tie",
            activa=True,
            ordre=1,
            tipus="equips",
            schema={
                "puntuacio": {
                    "aparells": {"mode": "seleccionar", "ids": [self.comp_app.id]},
                    "camps_per_aparell": {str(self.comp_app.id): ["total"]},
                    "agregacio_camps": "sum",
                    "exercicis": {"mode": "millor_1"},
                    "agregacio_exercicis": "sum",
                    "agregacio_aparells": "sum",
                    "ordre": "desc",
                },
                "desempat": [
                    {
                        "id": "tie_contributors_native",
                        "ordre": "desc",
                        "pipeline_version": 1,
                        "pipeline": {
                            "input_source": {"mode": "main_selected_contributors"},
                            "aparells": {"mode": "seleccionar", "ids": [self.comp_app.id]},
                            "camps_per_aparell": {str(self.comp_app.id): ["D"]},
                            "agregacio_camps_per_aparell": {str(self.comp_app.id): "sum"},
                            "agregacio_camps": "sum",
                            "candidate_source_mode": "raw_exercise",
                            "candidate_source_per_aparell": {str(self.comp_app.id): {"mode": "raw_exercise"}},
                            "exercicis": {"mode": "tots"},
                            "exercise_selection_scope": "per_member",
                            "mode_seleccio_exercicis": "per_aparell_global",
                            "agregacio_exercicis": "sum",
                            "agregacio_aparells": "sum",
                            "mode_resultat_aparells": "score",
                            "ordre": "desc",
                        },
                    }
                ],
                "equips": {
                    "context_code": "parelles",
                    "team_mode": "native_team",
                    "incloure_sense_equip": False,
                },
            },
        )

        rows = compute_classificacio(self.comp, cfg).get("global", [])
        self.assertEqual([row["participant"] for row in rows[:2]], ["Parella 2", "Parella 1"])
        self.assertEqual(rows[0]["score"], 10.0)
        self.assertEqual(rows[1]["score"], 10.0)


