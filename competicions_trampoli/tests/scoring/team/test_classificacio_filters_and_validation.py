from ._shared import *  # noqa: F401,F403


class TeamContextClassificacioFiltersAndValidationTests(TeamContextScoringFlowTestBase):
    def test_compute_classificacio_native_team_filters_require_all_members_to_match(self):
        self.ins1.categoria = "Base"
        self.ins2.categoria = "Promo"
        self.ins1.save(update_fields=["categoria"])
        self.ins2.save(update_fields=["categoria"])

        team_subject, _subject_meta = self._team_subject()
        TeamScoreEntry.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            team_subject=team_subject,
            exercici=1,
            inputs={},
            outputs={},
            total=31,
        )
        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Team filtered all members",
            activa=True,
            ordre=1,
            tipus="equips",
            schema={
                "filtres": {"categories_in": ["Base"]},
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
        self.assertEqual(rows, [])

    def test_compute_classificacio_native_team_group_filters_prefer_normalized_group_and_fallback_to_legacy(self):
        equip_2, members_2 = self._create_team_with_members("Parella 2", ["Nora", "Marta"], start_order=20)
        normalized_group = GrupCompeticio.objects.create(
            competicio=self.comp,
            display_num=2,
            nom="Grup 2",
        )
        self.ins1.grup_competicio = normalized_group
        self.ins2.grup_competicio = normalized_group
        self.ins1.save(update_fields=["grup_competicio"])
        self.ins2.save(update_fields=["grup_competicio"])
        for member in members_2:
            member.grup = 3
            member.save(update_fields=["grup"])

        team_subject_1, _subject_meta_1 = self._team_subject()
        team_subject_2, _subject_meta_2 = self._team_subject(equip_2)
        TeamScoreEntry.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            team_subject=team_subject_1,
            exercici=1,
            inputs={},
            outputs={},
            total=31,
        )
        TeamScoreEntry.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            team_subject=team_subject_2,
            exercici=1,
            inputs={},
            outputs={},
            total=28,
        )

        cfg_normalized = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Team normalized group filter",
            activa=True,
            ordre=1,
            tipus="equips",
            schema={
                "filtres": {"grups_in": ["2"]},
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
        cfg_legacy = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Team legacy group filter",
            activa=True,
            ordre=2,
            tipus="equips",
            schema={
                "filtres": {"grups_in": [3]},
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

        normalized_rows = compute_classificacio(self.comp, cfg_normalized).get("global", [])
        legacy_rows = compute_classificacio(self.comp, cfg_legacy).get("global", [])

        self.assertEqual([row["participant"] for row in normalized_rows], ["Parella 1"])
        self.assertEqual([row["participant"] for row in legacy_rows], ["Parella 2"])

    def test_compute_classificacio_derived_team_uses_only_filtered_members(self):
        ind_app = self._create_aparell("TR", "Tramp")
        comp_ind_app = self._create_comp_aparell(self.comp, ind_app, ordre=2)

        self.ins1.categoria = "Base"
        self.ins2.categoria = "Promo"
        self.ins1.save(update_fields=["categoria"])
        self.ins2.save(update_fields=["categoria"])

        ScoreEntry.objects.create(
            competicio=self.comp,
            comp_aparell=comp_ind_app,
            inscripcio=self.ins1,
            exercici=1,
            inputs={},
            outputs={},
            total=10,
        )
        ScoreEntry.objects.create(
            competicio=self.comp,
            comp_aparell=comp_ind_app,
            inscripcio=self.ins2,
            exercici=1,
            inputs={},
            outputs={},
            total=25,
        )

        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Derived team filtered members",
            activa=True,
            ordre=1,
            tipus="equips",
            schema={
                "filtres": {"categories_in": ["Base"]},
                "puntuacio": {
                    "aparells": {"mode": "seleccionar", "ids": [comp_ind_app.id]},
                    "camps_per_aparell": {str(comp_ind_app.id): ["total"]},
                    "agregacio_camps": "sum",
                    "exercicis": {"mode": "tots"},
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
        self.assertEqual([row["participant"] for row in rows], ["Parella 1"])
        self.assertEqual(rows[0]["score"], 10.0)

    def test_classificacio_save_persists_default_exercise_selection_scope_for_derived_team(self):
        ind_app = self._create_aparell("TR", "Tramp")
        comp_ind_app = self._create_comp_aparell(self.comp, ind_app, ordre=2)

        response = self._post_json(
            "classificacio_save",
            self._classificacio_payload(
                tipus="equips",
                app_ids=[comp_ind_app.id],
                context_code="parelles",
                team_mode="derived_from_individual",
            ),
        )

        self.assertEqual(response.status_code, 200)
        cfg = ClassificacioConfig.objects.get(pk=response.json()["id"])
        self.assertEqual(
            (cfg.schema.get("puntuacio") or {}).get("exercise_selection_scope"),
            "per_member",
        )

    def test_classificacio_save_sanitizes_filter_lists(self):
        payload = self._classificacio_payload(
            tipus="equips",
            app_ids=[self.comp_app.id],
            context_code="parelles",
            team_mode="native_team",
        )
        payload["schema"]["filtres"] = {
            "categories_in": ["Base", "Base", "", None],
            "grups_in": [1, "1", "", None],
        }

        response = self._post_json("classificacio_save", payload)

        self.assertEqual(response.status_code, 200)
        cfg = ClassificacioConfig.objects.get(pk=response.json()["id"])
        self.assertEqual(
            cfg.schema.get("filtres"),
            {"categories_in": ["Base"], "grups_in": ["1"]},
        )

    def test_classificacio_save_rejects_unknown_filter_key(self):
        payload = self._classificacio_payload(
            tipus="equips",
            app_ids=[self.comp_app.id],
            context_code="parelles",
            team_mode="native_team",
        )
        payload["schema"]["filtres"] = {"unknown_filter": ["X"]}

        response = self._post_json("classificacio_save", payload)

        self.assertEqual(response.status_code, 400)
        self.assertTrue(any("clau no admesa" in err for err in response.json().get("errors", [])))

    def test_classificacio_save_rejects_exercise_selection_scope_for_native_team(self):
        payload = self._classificacio_payload(
            tipus="equips",
            app_ids=[self.comp_app.id],
            context_code="parelles",
            team_mode="native_team",
        )
        payload["schema"]["puntuacio"]["exercise_selection_scope"] = "team_pool"
        payload["schema"]["desempat"] = [
            {
                "camps": ["TOTAL"],
                "scope": {"aparells": {"mode": "seleccionar", "ids": [self.comp_app.id]}},
                "exercise_selection_scope": "team_pool",
            }
        ]

        response = self._post_json("classificacio_save", payload)

        self.assertEqual(response.status_code, 400)
        errors = response.json().get("errors", [])
        self.assertTrue(any("puntuacio.exercise_selection_scope" in err for err in errors))
        self.assertTrue(any("desempat[0].exercise_selection_scope" in err for err in errors))

    def test_classificacio_save_accepts_team_aggregate_for_native_team(self):
        payload = self._classificacio_payload(
            tipus="equips",
            app_ids=[self.comp_app.id],
            context_code="parelles",
            team_mode="native_team",
        )
        payload["schema"]["puntuacio"]["candidate_source_mode"] = "team_aggregate"
        payload["schema"]["puntuacio"]["candidate_source_cfg"] = {
            "mode": "millor_n",
            "best_n": 1,
            "index": 1,
            "ids": [],
            "agregacio_exercicis": "sum",
        }
        payload["schema"]["puntuacio"]["candidate_source_per_aparell"] = {
            str(self.comp_app.id): {
                "mode": "team_aggregate",
                "cfg": {
                    "mode": "index",
                    "best_n": 1,
                    "index": 1,
                    "ids": [],
                    "agregacio_exercicis": "max",
                },
            },
        }

        response = self._post_json("classificacio_save", payload)

        self.assertEqual(response.status_code, 200)
        cfg = ClassificacioConfig.objects.get(pk=response.json()["id"])
        punt = cfg.schema.get("puntuacio") or {}
        self.assertEqual(punt.get("candidate_source_mode"), "team_aggregate")
        self.assertEqual((punt.get("candidate_source_cfg") or {}).get("mode"), "index")
        self.assertEqual((((punt.get("candidate_source_per_aparell") or {}).get(str(self.comp_app.id)) or {}).get("mode")), "team_aggregate")

    def test_classificacio_save_rejects_participant_aggregate_for_native_team(self):
        payload = self._classificacio_payload(
            tipus="equips",
            app_ids=[self.comp_app.id],
            context_code="parelles",
            team_mode="native_team",
        )
        payload["schema"]["puntuacio"]["candidate_source_mode"] = "participant_aggregate"
        payload["schema"]["puntuacio"]["candidate_source_cfg"] = {
            "mode": "millor_n",
            "best_n": 1,
            "index": 1,
            "ids": [],
            "agregacio_exercicis": "sum",
        }

        response = self._post_json("classificacio_save", payload)

        self.assertEqual(response.status_code, 400)
        self.assertTrue(any("candidate_source_mode" in err for err in response.json().get("errors", [])))

    def test_classificacio_save_rejects_team_aggregate_for_derived_team(self):
        _ind_app, comp_ind_app = self._create_individual_comp_aparell("TR_DER", "Derived candidate source")
        payload = self._classificacio_payload(
            tipus="equips",
            app_ids=[comp_ind_app.id],
            context_code="parelles",
            team_mode="derived_from_individual",
        )
        payload["schema"]["puntuacio"]["candidate_source_mode"] = "team_aggregate"
        payload["schema"]["puntuacio"]["candidate_source_cfg"] = {
            "mode": "millor_n",
            "best_n": 1,
            "index": 1,
            "ids": [],
            "agregacio_exercicis": "sum",
        }

        response = self._post_json("classificacio_save", payload)

        self.assertEqual(response.status_code, 400)
        self.assertTrue(any("candidate_source_mode" in err for err in response.json().get("errors", [])))

    def test_classificacio_validation_rejects_context_mismatch_for_team_context_app(self):
        schema, errors = _validate_schema_for_competicio(
            self.comp,
            {
                "puntuacio": {
                    "aparells": {"mode": "seleccionar", "ids": [self.comp_app.id]},
                    "camps_per_aparell": {str(self.comp_app.id): ["total"]},
                },
                "equips": {
                    "assignment_source": {"mode": "context", "context_code": "altre", "fallback": "native"},
                },
            },
            tipus="equips",
        )

        self.assertEqual(schema["equips"]["assignment_source"]["context_code"], "altre")
        self.assertTrue(any("requereix context parelles" in err for err in errors))

    def test_classificacio_validation_rejects_native_team_mode_with_individual_app(self):
        ind_app = self._create_aparell("TR", "Tramp")
        comp_ind_app = self._create_comp_aparell(self.comp, ind_app, ordre=2)

        _schema, errors = _validate_schema_for_competicio(
            self.comp,
            {
                "puntuacio": {
                    "aparells": {"mode": "seleccionar", "ids": [comp_ind_app.id]},
                    "camps_per_aparell": {str(comp_ind_app.id): ["total"]},
                },
                "equips": {
                    "context_code": "parelles",
                    "team_mode": "native_team",
                },
            },
            tipus="equips",
        )

        self.assertTrue(any("team_mode=native_team" in err for err in errors))

    def test_classificacio_validation_rejects_native_team_raw_column_on_individual_app(self):
        ind_app = self._create_aparell("TR_RAW_VAL", "Tramp raw validation")
        comp_ind_app = self._create_comp_aparell(self.comp, ind_app, ordre=2)

        _schema, errors = _validate_schema_for_competicio(
            self.comp,
            {
                **self._native_team_schema_with_tie({"camps": ["TOTAL"], "ordre": "desc"}),
                "presentacio": {
                    "columnes": [
                        {"type": "builtin", "key": "participant", "label": "Nom", "align": "left"},
                        {
                            "type": "raw",
                            "key": "raw_total",
                            "label": "Raw total",
                            "align": "right",
                            "decimals": 3,
                            "source": {"aparell_id": comp_ind_app.id, "exercici": 1, "camp": "total", "jutges": {"ids": []}},
                        },
                    ]
                },
            },
            tipus="equips",
        )

        self.assertTrue(any("nomes es poden mostrar aparells d'equip" in err for err in errors))

    def test_classificacio_validation_rejects_invalid_detail_builtin_for_derived_team(self):
        ind_app = self._create_aparell("TR_DETAIL_VAL", "Tramp detail validation")
        comp_ind_app = self._create_comp_aparell(self.comp, ind_app, ordre=2)

        _schema, errors = _validate_schema_for_competicio(
            self.comp,
            {
                "puntuacio": {
                    "aparells": {"mode": "seleccionar", "ids": [comp_ind_app.id]},
                    "camps_per_aparell": {str(comp_ind_app.id): ["total"]},
                },
                "presentacio": {
                    "detall": {
                        "enabled": True,
                        "columnes": [
                            {"type": "builtin", "key": "punts", "label": "Punts", "align": "right"},
                        ],
                    },
                },
                "equips": {
                    "context_code": "parelles",
                    "team_mode": "derived_from_individual",
                },
            },
            tipus="equips",
        )

        self.assertTrue(
            any("presentacio.detall.columnes[0] builtin: clau no permesa" in err for err in errors)
        )

    def test_classificacio_validation_rejects_detail_enabled_without_sections(self):
        ind_app = self._create_aparell("TR_DETAIL_REQ", "Tramp detail required")
        comp_ind_app = self._create_comp_aparell(self.comp, ind_app, ordre=2)

        _schema, errors = _validate_schema_for_competicio(
            self.comp,
            {
                "puntuacio": {
                    "aparells": {"mode": "seleccionar", "ids": [comp_ind_app.id]},
                    "camps_per_aparell": {str(comp_ind_app.id): ["total"]},
                },
                "presentacio": {
                    "detall": {
                        "enabled": True,
                        "sections": [],
                    },
                },
            },
            tipus="individual",
        )

        self.assertTrue(
            any("presentacio.detall.enabled requereix sections o columnes legacy compatibles" in err for err in errors)
        )

    def test_classificacio_validation_rejects_legacy_detail_columns_for_individual(self):
        ind_app = self._create_aparell("TR_DETAIL_F1_IND", "Tramp detail legacy individual")
        comp_ind_app = self._create_comp_aparell(self.comp, ind_app, ordre=2)

        _schema, errors = _validate_schema_for_competicio(
            self.comp,
            {
                "puntuacio": {
                    "aparells": {"mode": "seleccionar", "ids": [comp_ind_app.id]},
                    "camps_per_aparell": {str(comp_ind_app.id): ["total"]},
                },
                "presentacio": {
                    "detall": {
                        "enabled": True,
                        "columnes": [
                            {"type": "builtin", "key": "participant", "label": "Participant", "align": "left"},
                        ],
                    },
                },
            },
            tipus="individual",
        )

        self.assertTrue(
            any("presentacio.detall.columnes nomes es compatible" in err for err in errors)
        )

    def test_classificacio_validation_rejects_legacy_detail_columns_for_native_team(self):
        _schema, errors = _validate_schema_for_competicio(
            self.comp,
            {
                **self._native_team_schema_with_tie({"camps": ["TOTAL"], "ordre": "desc"}),
                "presentacio": {
                    "detall": {
                        "enabled": True,
                        "columnes": [
                            {"type": "builtin", "key": "participant", "label": "Participant", "align": "left"},
                        ],
                    },
                },
            },
            tipus="equips",
        )

        self.assertTrue(
            any("presentacio.detall.columnes nomes es compatible" in err for err in errors)
        )

    def test_normalize_schema_does_not_inject_legacy_detail_columns_when_absent(self):
        schema, _info = normalize_schema_legacy_team_birth_partition(
            self.comp,
            {
                **self._native_team_schema_with_tie({"camps": ["TOTAL"], "ordre": "desc"}),
                "presentacio": {
                    "columnes": [
                        {"type": "builtin", "key": "participant", "label": "Nom", "align": "left"},
                        {"type": "builtin", "key": "punts", "label": "Punts", "align": "right", "decimals": 3},
                    ],
                    "detall": {
                        "enabled": False,
                        "default_open": False,
                        "sections": [],
                    },
                },
            },
            tipus="equips",
            persist=False,
        )

        self.assertNotIn("columnes", (schema.get("presentacio") or {}).get("detall") or {})

    def test_normalize_schema_preserves_explicit_legacy_detail_columns(self):
        schema, _info = normalize_schema_legacy_team_birth_partition(
            self.comp,
            {
                **self._native_team_schema_with_tie({"camps": ["TOTAL"], "ordre": "desc"}),
                "presentacio": {
                    "detall": {
                        "enabled": True,
                        "columnes": [
                            {"type": "builtin", "key": "participant", "label": "Participant", "align": "left"},
                        ],
                    },
                },
            },
            tipus="equips",
            persist=False,
        )

        self.assertEqual(
            (((schema.get("presentacio") or {}).get("detall") or {}).get("columnes")) or [],
            [{"type": "builtin", "key": "participant", "label": "Participant", "align": "left"}],
        )

    def test_classificacio_validation_accepts_empty_legacy_detail_columns_for_native_team_sections(self):
        _schema, errors = _validate_schema_for_competicio(
            self.comp,
            {
                **self._native_team_schema_with_tie({"camps": ["TOTAL"], "ordre": "desc"}),
                "presentacio": {
                    "columnes": [
                        {"type": "builtin", "key": "participant", "label": "Nom", "align": "left"},
                        {"type": "builtin", "key": "punts", "label": "Punts", "align": "right", "decimals": 3},
                    ],
                    "detall": {
                        "enabled": True,
                        "default_open": False,
                        "sections": [
                            {"type": "members_list", "label": "Participants"},
                            {
                                "type": "team_metrics",
                                "label": "Notes equip",
                                "aparell_id": self.comp_app.id,
                                "columns": [
                                    {
                                        "type": "raw",
                                        "key": "team_total",
                                        "label": "Total",
                                        "align": "right",
                                        "decimals": 3,
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
                        "columnes": [],
                    },
                },
            },
            tipus="equips",
        )

        self.assertEqual(errors, [])

    def test_classificacio_validation_rejects_multi_app_detail_section(self):
        app_b = self._create_aparell("TR_DETAIL_MULTI", "Tramp detail multi")
        comp_app_b = self._create_comp_aparell(self.comp, app_b, ordre=3)

        _schema, errors = _validate_schema_for_competicio(
            self.comp,
            {
                "puntuacio": {
                    "aparells": {"mode": "seleccionar", "ids": [self.comp_app.id, comp_app_b.id]},
                    "camps_per_aparell": {
                        str(self.comp_app.id): ["total"],
                        str(comp_app_b.id): ["total"],
                    },
                },
                "presentacio": {
                    "detall": {
                        "enabled": True,
                        "sections": [
                            {
                                "type": "members_table",
                                "label": "Detall",
                                "columns": [
                                    {"type": "builtin", "key": "participant", "label": "Participant", "align": "left"},
                                    {
                                        "type": "raw",
                                        "key": "detail_total_a",
                                        "label": "Total A",
                                        "align": "right",
                                        "decimals": 3,
                                        "source": {"aparell_id": self.comp_app.id, "exercici": 1, "camp": "total", "jutges": {"ids": []}},
                                    },
                                    {
                                        "type": "raw",
                                        "key": "detail_total_b",
                                        "label": "Total B",
                                        "align": "right",
                                        "decimals": 3,
                                        "source": {"aparell_id": comp_app_b.id, "exercici": 1, "camp": "total", "jutges": {"ids": []}},
                                    },
                                ],
                            }
                        ],
                    },
                },
                "equips": {
                    "context_code": "parelles",
                    "team_mode": "derived_from_individual",
                },
            },
            tipus="equips",
        )

        self.assertTrue(
            any("presentacio.detall.sections[0] barreja aparells multiples" in err for err in errors)
        )

    def test_classificacio_save_returns_error_details_for_invalid_detail_section_field(self):
        ind_app = self._create_aparell("TR_DETAIL_BAD", "Tramp detail bad")
        comp_ind_app = self._create_comp_aparell(self.comp, ind_app, ordre=2)
        payload = self._classificacio_payload(tipus="individual", app_ids=[comp_ind_app.id])
        payload["schema"]["presentacio"] = {
            "top_n": 0,
            "mostrar_empats": True,
            "columnes": [
                {"type": "builtin", "key": "participant", "label": "Nom", "align": "left"},
            ],
            "detall": {
                "enabled": True,
                "sections": [
                    {
                        "type": "exercise_table",
                        "label": "Exercicis",
                        "aparell_id": comp_ind_app.id,
                        "columns": [
                            {"type": "builtin", "key": "exercise_index", "label": "Ex.", "align": "left"},
                            {
                                "type": "raw",
                                "key": "detail_bad",
                                "label": "Camp invalid",
                                "align": "right",
                                "decimals": 3,
                                "source": {"aparell_id": comp_ind_app.id, "exercici": 1, "camp": "NO_EXISTEIX", "jutges": {"ids": []}},
                            },
                        ],
                    }
                ],
            },
        }

        response = self._post_json("classificacio_save", payload)
        self.assertEqual(response.status_code, 400)
        body = response.json()
        details = body.get("error_details") or []
        self.assertTrue(any(item.get("path") == "presentacio.detall.sections[0].columns[1].source.camp" for item in details))

    def test_classificacio_save_rejects_detail_exercici_out_of_range_with_precise_path(self):
        ind_app = self._create_aparell("TR_DETAIL_RANGE", "Tramp detail range")
        comp_ind_app = self._create_comp_aparell(self.comp, ind_app, ordre=2)
        payload = self._classificacio_payload(tipus="individual", app_ids=[comp_ind_app.id])
        payload["schema"]["presentacio"] = {
            "top_n": 0,
            "mostrar_empats": True,
            "columnes": [
                {"type": "builtin", "key": "participant", "label": "Nom", "align": "left"},
            ],
            "detall": {
                "enabled": True,
                "sections": [
                    {
                        "type": "exercise_table",
                        "label": "Exercicis",
                        "aparell_id": comp_ind_app.id,
                        "columns": [
                            {"type": "builtin", "key": "exercise_index", "label": "Ex.", "align": "left"},
                            {
                                "type": "raw",
                                "key": "detail_total",
                                "label": "Total",
                                "align": "right",
                                "decimals": 3,
                                "source": {"aparell_id": comp_ind_app.id, "exercici": 99, "camp": "total", "jutges": {"ids": []}},
                            },
                        ],
                    }
                ],
            },
        }

        response = self._post_json("classificacio_save", payload)
        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertTrue(any("fora de rang" in err for err in (body.get("errors") or [])))
        details = body.get("error_details") or []
        self.assertTrue(any(item.get("path") == "presentacio.detall.sections[0].columns[1].source.exercici" for item in details))

    def test_classificacio_validation_rejects_members_list_columns(self):
        _schema, errors = _validate_schema_for_competicio(
            self.comp,
            {
                "puntuacio": {
                    "aparells": {"mode": "seleccionar", "ids": [self.comp_app.id]},
                    "camps_per_aparell": {str(self.comp_app.id): ["total"]},
                },
                "equips": {
                    "context_code": "parelles",
                    "team_mode": "derived_from_individual",
                },
                "presentacio": {
                    "detall": {
                        "enabled": True,
                        "sections": [
                            {
                                "type": "members_list",
                                "label": "Membres",
                                "columns": [
                                    {"type": "builtin", "key": "participant", "label": "Participant", "align": "left"},
                                ],
                            }
                        ],
                    },
                },
            },
            tipus="equips",
        )

        self.assertTrue(any("presentacio.detall.sections[0].columns no es compatible amb members_list" in err for err in errors))

    def test_classificacio_validation_accepts_native_team_team_members_table_member_field(self):
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

        _schema, errors = _validate_schema_for_competicio(
            self.comp,
            {
                **self._native_team_schema_with_tie({"camps": ["TOTAL"], "ordre": "desc"}),
                "presentacio": {
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
                                        "decimals": 3,
                                        "source": {"aparell_id": self.comp_app.id, "exercici": 1, "camp": "E", "jutges": {"ids": []}},
                                    },
                                ],
                            },
                        ],
                    },
                },
            },
            tipus="equips",
        )

        self.assertEqual(errors, [])

    def test_classificacio_validation_accepts_native_team_team_members_table_fixed_exercise_mode(self):
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

        _schema, errors = _validate_schema_for_competicio(
            self.comp,
            {
                **self._native_team_schema_with_tie({"camps": ["TOTAL"], "ordre": "desc"}),
                "presentacio": {
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
                                        "decimals": 3,
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
            },
            tipus="equips",
        )

        self.assertEqual(errors, [])

    def test_classificacio_validation_legacy_team_members_table_ignores_exercici_when_mode_missing(self):
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

        _schema, errors = _validate_schema_for_competicio(
            self.comp,
            {
                **self._native_team_schema_with_tie({"camps": ["TOTAL"], "ordre": "desc"}),
                "presentacio": {
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
                                        "decimals": 3,
                                        "source": {
                                            "aparell_id": self.comp_app.id,
                                            "exercici": 99,
                                            "camp": "E",
                                            "jutges": {"ids": []},
                                        },
                                    },
                                ],
                            },
                        ],
                    },
                },
            },
            tipus="equips",
        )

        self.assertEqual(errors, [])

    def test_classificacio_validation_rejects_native_team_team_members_table_invalid_exercise_mode(self):
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

        _schema, errors = _validate_schema_for_competicio(
            self.comp,
            {
                **self._native_team_schema_with_tie({"camps": ["TOTAL"], "ordre": "desc"}),
                "presentacio": {
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
                                        "decimals": 3,
                                        "source": {
                                            "aparell_id": self.comp_app.id,
                                            "exercise_mode": "broken",
                                            "camp": "E",
                                            "jutges": {"ids": []},
                                        },
                                    },
                                ],
                            },
                        ],
                    },
                },
            },
            tipus="equips",
        )

        self.assertTrue(any("exercise_mode invalid" in err for err in errors))

    def test_prepare_schema_for_persistence_preserves_team_members_table_exercise_mode(self):
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
        schema = {
            **self._native_team_schema_with_tie({"camps": ["TOTAL"], "ordre": "desc"}),
            "presentacio": {
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
                                    "decimals": 3,
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
                "assignment_source": {"mode": "context", "context_code": "parelles", "fallback": "native"},
                "team_mode": "native_team",
                "incloure_sense_equip": False,
            },
        }

        prepared = prepare_schema_for_persistence(self.comp, schema, tipus="equips")

        self.assertEqual(prepared["errors"], [])
        col_source = (((((prepared["schema"] or {}).get("presentacio") or {}).get("detall") or {}).get("sections") or [])[0]["columns"][0]["source"])
        self.assertEqual(col_source.get("exercise_mode"), "fixed")
        self.assertNotIn("has_explicit_exercici", col_source)

    def test_competition_template_roundtrip_preserves_team_members_table_exercise_mode(self):
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
        schema = {
            **self._native_team_schema_with_tie({"camps": ["TOTAL"], "ordre": "desc"}),
            "presentacio": {
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
                                    "decimals": 3,
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
                "assignment_source": {"mode": "context", "context_code": "parelles", "fallback": "native"},
                "team_mode": "native_team",
                "incloure_sense_equip": False,
            },
        }

        schema_tpl, warnings = _schema_to_template_schema(self.comp, schema)
        self.assertEqual(warnings, [])
        tpl_source = (((schema_tpl.get("presentacio") or {}).get("detall") or {}).get("sections") or [])[0]["columns"][0]["source"]
        self.assertEqual(tpl_source.get("exercise_mode"), "fixed")
        self.assertNotIn("has_explicit_exercici", tpl_source)

        schema_roundtrip, compat_warnings, mapping, compat_meta = _template_schema_to_competicio_schema_service(
            self.comp,
            schema_tpl,
        )
        self.assertEqual(mapping.get(self.app.codi), self.comp_app.id)
        self.assertEqual(compat_warnings, [])
        self.assertFalse(compat_meta.get("adaptable"))
        roundtrip_source = (((schema_roundtrip.get("presentacio") or {}).get("detall") or {}).get("sections") or [])[0]["columns"][0]["source"]
        self.assertEqual(roundtrip_source.get("exercise_mode"), "fixed")
        self.assertNotIn("has_explicit_exercici", roundtrip_source)

    def test_classificacio_validation_accepts_native_team_team_members_table_display_only_member_field(self):
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
                        "judges": {"count": 3},
                        "items": {"count": 5},
                    },
                    {"code": "SYNC", "label": "Sync", "type": "number", "scope": "shared"},
                ],
                "computed": [],
            },
        )

        _schema, errors = _validate_schema_for_competicio(
            self.comp,
            {
                **self._native_team_schema_with_tie({"camps": ["TOTAL"], "ordre": "desc"}),
                "presentacio": {
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
                                        "decimals": 3,
                                        "source": {"aparell_id": self.comp_app.id, "exercici": 1, "camp": "E", "jutges": {"ids": []}},
                                    },
                                ],
                            },
                        ],
                    },
                },
            },
            tipus="equips",
        )

        self.assertEqual(errors, [])

    def test_classificacio_validation_infers_team_members_table_section_app_from_single_raw_app(self):
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

        _schema, errors = _validate_schema_for_competicio(
            self.comp,
            {
                **self._native_team_schema_with_tie({"camps": ["TOTAL"], "ordre": "desc"}),
                "presentacio": {
                    "detall": {
                        "enabled": True,
                        "sections": [
                            {
                                "type": "team_members_table",
                                "label": "Notes per membre",
                                "columns": [
                                    {
                                        "type": "raw",
                                        "key": "member_exec",
                                        "label": "Exec",
                                        "align": "right",
                                        "decimals": 3,
                                        "source": {"aparell_id": self.comp_app.id, "exercici": 1, "camp": "E", "jutges": {"ids": []}},
                                    },
                                ],
                            },
                        ],
                    },
                },
            },
            tipus="equips",
        )

        self.assertEqual(errors, [])

    def test_classificacio_validation_rejects_native_team_team_members_table_shared_field(self):
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

        _schema, errors = _validate_schema_for_competicio(
            self.comp,
            {
                **self._native_team_schema_with_tie({"camps": ["TOTAL"], "ordre": "desc"}),
                "presentacio": {
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
                                        "key": "team_sync",
                                        "label": "Sync",
                                        "align": "right",
                                        "decimals": 3,
                                        "source": {"aparell_id": self.comp_app.id, "exercici": 1, "camp": "SYNC", "jutges": {"ids": []}},
                                    },
                                ],
                            },
                        ],
                    },
                },
            },
            tipus="equips",
        )

        self.assertTrue(any("team_members_table" in err for err in errors))

    def test_classificacio_validation_rejects_native_team_main_column_member_field(self):
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

        _schema, errors = _validate_schema_for_competicio(
            self.comp,
            {
                **self._native_team_schema_with_tie({"camps": ["TOTAL"], "ordre": "desc"}),
                "presentacio": {
                    "columnes": [
                        {"type": "builtin", "key": "participant", "label": "Nom", "align": "left"},
                        {
                            "type": "raw",
                            "key": "member_exec",
                            "label": "Exec",
                            "align": "right",
                            "decimals": 3,
                            "source": {"aparell_id": self.comp_app.id, "exercici": 1, "camp": "E", "jutges": {"ids": []}},
                        },
                    ],
                },
            },
            tipus="equips",
        )

        self.assertTrue(any("camps individuals per membre" in err for err in errors))

    def test_classificacio_validation_rejects_native_team_team_metrics_member_field(self):
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

        _schema, errors = _validate_schema_for_competicio(
            self.comp,
            {
                **self._native_team_schema_with_tie({"camps": ["TOTAL"], "ordre": "desc"}),
                "presentacio": {
                    "detall": {
                        "enabled": True,
                        "sections": [
                            {
                                "type": "team_metrics",
                                "label": "Notes equip",
                                "aparell_id": self.comp_app.id,
                                "columns": [
                                    {
                                        "type": "raw",
                                        "key": "member_exec",
                                        "label": "Exec",
                                        "align": "right",
                                        "decimals": 3,
                                        "source": {"aparell_id": self.comp_app.id, "exercici": 1, "camp": "E", "jutges": {"ids": []}},
                                    },
                                ],
                            },
                        ],
                    },
                },
            },
            tipus="equips",
        )

        self.assertTrue(any("team_metrics" in err for err in errors))

    def test_classificacio_validation_rejects_native_team_tie_with_participant_scope(self):
        _schema, errors = _validate_schema_for_competicio(
            self.comp,
            self._native_team_schema_with_tie(
                {
                    "camps": ["TOTAL"],
                    "scope": {"participants": {"mode": "millor_n", "n": 1}},
                }
            ),
            tipus="equips",
        )

        self.assertTrue(any("scope.participants" in err for err in errors))

    def test_classificacio_validation_rejects_native_team_pipeline_with_participants(self):
        _schema, errors = _validate_schema_for_competicio(
            self.comp,
            self._native_team_schema_with_tie(
                {
                    "id": "tie_native_pipeline",
                    "ordre": "desc",
                    "pipeline_version": 1,
                    "pipeline": {
                        "aparells": {"mode": "seleccionar", "ids": [self.comp_app.id]},
                        "camps_per_aparell": {str(self.comp_app.id): ["TOTAL"]},
                        "agregacio_camps_per_aparell": {str(self.comp_app.id): "sum"},
                        "agregacio_camps": "sum",
                        "candidate_source_mode": "team_aggregate",
                        "candidate_source_cfg": {
                            "mode": "tots",
                            "best_n": 1,
                            "index": 1,
                            "ids": [],
                            "agregacio_exercicis": "sum",
                        },
                        "candidate_source_per_aparell": {str(self.comp_app.id): {"mode": "team_aggregate"}},
                        "exercicis": {"mode": "tots"},
                        "exercise_selection_scope": "per_member",
                        "mode_seleccio_exercicis": "per_aparell_global",
                        "agregacio_exercicis": "sum",
                        "agregacio_aparells": "sum",
                        "mode_resultat_aparells": "score",
                        "participants": {"mode": "millor_n", "n": 1},
                        "agregacio_participants": "sum",
                    },
                }
            ),
            tipus="equips",
        )
        self.assertTrue(any("desempat[0].pipeline.participants" in err for err in errors))

    def test_classificacio_validation_rejects_native_team_tie_with_participant_aggregation(self):
        _schema, errors = _validate_schema_for_competicio(
            self.comp,
            self._native_team_schema_with_tie(
                {
                    "camps": ["TOTAL"],
                    "agregacio_participants": "sum",
                }
            ),
            tipus="equips",
        )

        self.assertTrue(any("agregacio_participants" in err for err in errors))

    def test_classificacio_validation_rejects_native_team_tie_with_non_scalar_member_field(self):
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

        _schema, errors = _validate_schema_for_competicio(
            self.comp,
            self._native_team_schema_with_tie({"camps": ["E"]}),
            tipus="equips",
        )

        self.assertTrue(errors)

    def test_classificacio_validation_accepts_native_team_tie_with_shared_computed_scalar(self):
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

        _schema, errors = _validate_schema_for_competicio(
            self.comp,
            self._native_team_schema_with_tie({"camps": ["TEAM_SYNC"]}),
            tipus="equips",
        )

        self.assertEqual(errors, [])

    def test_classificacio_validation_accepts_native_team_tie_with_member_derived_scalar_computed(self):
        ScoringSchema.objects.create(
            aparell=self.app,
            schema={
                "meta": {"subject_mode": "team_context", "expected_team_size": 2},
                "fields": [
                    {"code": "SYNC", "label": "Sync", "type": "number", "scope": "shared"},
                    {"code": "E", "label": "Exec", "type": "number", "scope": "member"},
                ],
                "computed": [
                    {"code": "TEAM_E", "label": "Team exec", "formula": "members_sum(E)"},
                ],
            },
        )

        _schema, errors = _validate_schema_for_competicio(
            self.comp,
            self._native_team_schema_with_tie({"camps": ["TEAM_E"]}),
            tipus="equips",
        )

        self.assertEqual(errors, [])

    def test_classificacio_save_rejects_team_app_for_individual_tipus(self):
        response = self._post_json(
            "classificacio_save",
            self._classificacio_payload(tipus="individual", app_ids=[self.comp_app.id]),
        )

        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertTrue(any("tipus='individual'" in err for err in body.get("errors", [])))

    def test_classificacio_save_forces_derived_team_mode_when_context_has_no_team_apps(self):
        ind_app = self._create_aparell("DMT", "Doble mini")
        comp_ind_app = self._create_comp_aparell(self.comp, ind_app, ordre=2)

        response = self._post_json(
            "classificacio_save",
            self._classificacio_payload(
                tipus="equips",
                app_ids=[comp_ind_app.id],
                context_code="altre",
                team_mode=None,
            ),
        )

        self.assertEqual(response.status_code, 200)
        cfg = ClassificacioConfig.objects.get(pk=response.json()["id"])
        equips_cfg = cfg.schema.get("equips") or {}
        self.assertEqual(equips_cfg.get("context_code"), "altre")
        self.assertEqual(equips_cfg.get("team_mode"), "derived_from_individual")
        self.assertEqual((equips_cfg.get("mode_resolution") or {}).get("eligible_team_app_ids_at_save"), [])
        self.assertTrue((equips_cfg.get("mode_resolution") or {}).get("resolved_at"))

    def test_classificacio_preview_rejects_stale_native_team_context(self):
        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Team preview stale",
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
                    "mode_resolution": {
                        "resolved_at": "2026-03-29T10:00:00Z",
                        "eligible_team_app_ids_at_save": [self.comp_app.id],
                    },
                },
            },
        )
        CompeticioAparellEquipContextSource.objects.filter(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            context=self.ctx,
        ).delete()

        response = self.client.post(reverse("classificacio_preview", kwargs={"pk": self.comp.id, "cid": cfg.id}))

        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertFalse(body.get("ok"))
        self.assertTrue(any("no admet el context" in err for err in body.get("errors", [])))

    def test_classificacions_home_exposes_team_context_capabilities_and_cfg_statuses(self):
        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Cfg status v1",
            activa=True,
            ordre=1,
            tipus="equips",
            schema={
                "puntuacio": {
                    "aparells": {"mode": "seleccionar", "ids": [self.comp_app.id]},
                    "camps_per_aparell": {str(self.comp_app.id): ["total"]},
                },
                "equips": {
                    "context_code": "parelles",
                    "team_mode": "native_team",
                    "mode_resolution": {
                        "resolved_at": "2026-03-29T10:00:00Z",
                        "eligible_team_app_ids_at_save": [self.comp_app.id],
                    },
                },
            },
        )

        response = self.client.get(reverse("classificacions_home", kwargs={"pk": self.comp.id}))

        self.assertEqual(response.status_code, 200)
        self.assertIn("cfg_statuses", response.context)
        self.assertIn(str(cfg.id), response.context["cfg_statuses"])
        self.assertIn("resolved_at", response.context["cfg_statuses"][str(cfg.id)])
        self.assertEqual(
            response.context["cfg_statuses"][str(cfg.id)]["resolved_at"],
            "2026-03-29T10:00:00Z",
        )
        self.assertTrue(
            any(item.get("context_code") == "parelles" for item in response.context.get("team_context_capabilities", []))
        )

    def test_classificacio_save_persists_derived_exercise_selection_scope_default(self):
        individual_app = self._create_aparell("TRS", "Tramp save")
        individual_comp_app = self._create_comp_aparell(self.comp, individual_app, ordre=2)
        payload = self._classificacio_payload(
            tipus="equips",
            app_ids=[individual_comp_app.id],
            team_mode="derived_from_individual",
        )

        response = self._post_json("classificacio_save", payload)

        self.assertEqual(response.status_code, 200)
        cfg = ClassificacioConfig.objects.get(pk=response.json()["id"])
        self.assertEqual(
            (cfg.schema.get("puntuacio") or {}).get("exercise_selection_scope"),
            "per_member",
        )

    def test_classificacio_validation_rejects_exercise_selection_scope_for_native_team(self):
        schema = self._native_team_schema_with_tie(
            {
                "camps": ["TOTAL"],
                "ordre": "desc",
                "exercise_selection_scope": "team_pool",
            }
        )
        schema["puntuacio"]["exercise_selection_scope"] = "team_pool"

        _schema, errors = _validate_schema_for_competicio(
            self.comp,
            schema,
            tipus="equips",
        )

        self.assertTrue(any("puntuacio.exercise_selection_scope" in err for err in errors))
        self.assertTrue(any("desempat[0].exercise_selection_scope" in err for err in errors))

    def test_classificacio_validation_rejects_team_pool_tie_reselection_fields(self):
        individual_app = self._create_aparell("TRV", "Tramp validation")
        individual_comp_app = self._create_comp_aparell(self.comp, individual_app, ordre=2)
        schema = {
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
                    "camps": ["total"],
                    "ordre": "desc",
                    "exercise_selection_scope": "team_pool",
                    "mode_seleccio_exercicis": "global_pool",
                    "exercicis_per_aparell": {
                        str(individual_comp_app.id): {"mode": "millor_n", "best_n": 1}
                    },
                    "scope": {
                        "aparells": {"mode": "seleccionar", "ids": [individual_comp_app.id]},
                        "exercicis": {"mode": "millor_n", "best_n": 1},
                        "participants": {"mode": "millor_1"},
                    },
                    "agregacio_participants": "sum",
                }
            ],
            "equips": {
                "context_code": "parelles",
                "team_mode": "derived_from_individual",
                "incloure_sense_equip": False,
            },
        }

        _schema, errors = _validate_schema_for_competicio(
            self.comp,
            schema,
            tipus="equips",
        )

        self.assertTrue(any("desempat[0].scope.exercicis" in err for err in errors))
        self.assertTrue(any("desempat[0].mode_seleccio_exercicis" in err for err in errors))
        self.assertTrue(any("desempat[0].exercicis_per_aparell" in err for err in errors))
        self.assertTrue(any("desempat[0].scope.participants" in err for err in errors))
        self.assertTrue(any("desempat[0].agregacio_participants" in err for err in errors))

