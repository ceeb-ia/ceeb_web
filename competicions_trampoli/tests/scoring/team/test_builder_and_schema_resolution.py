from ._shared import *  # noqa: F401,F403


class TeamContextScoringBuilderAndSchemaResolutionTests(TeamContextScoringFlowTestBase):
    def test_build_metric_meta_marks_native_team_displayable_fields(self):
        schema_obj = {
            "meta": {"subject_mode": "team"},
            "fields": [
                {
                    "code": "E",
                    "label": "Execucio",
                    "scope": "member",
                    "type": "matrix",
                    "shape": "judge_x_item",
                    "judges": {"count": 3},
                    "items": {"count": 5},
                },
                {
                    "code": "S",
                    "label": "Sync",
                    "scope": "shared",
                    "type": "number",
                },
            ],
            "computed": [
                {
                    "code": "E_mem",
                    "label": "Execucio membre",
                    "formula": "row_custom_compute('E', '1 - x')",
                },
                {
                    "code": "E_by_judge",
                    "label": "Execucio by judge",
                    "formula": "row_custom_compute('E', '1 - x', return_mode='by_judge')",
                },
            ],
        }

        meta = _build_metric_meta_for_comp_aparell(self.comp_app, schema_obj, strict_unknown=True)

        self.assertFalse(meta["E"]["scoreable"])
        self.assertTrue(meta["E"]["member_dependent"])
        self.assertTrue(meta["E"]["detail_displayable"])
        self.assertEqual(meta["E"]["detail_display_kind"], "judge_rows")
        self.assertTrue(meta["E_mem"]["detail_displayable"])
        self.assertEqual(meta["E_mem"]["detail_display_kind"], "scalar")
        self.assertTrue(meta["E_mem"]["member_dependent"])
        self.assertFalse(meta["E_by_judge"]["detail_displayable"])
        self.assertEqual(meta["E_by_judge"]["detail_display_kind"], "none")

    def test_builder_context_exposes_displayable_member_fields_for_native_team(self):
        ScoringSchema.objects.create(
            aparell=self.app,
            schema={
                "meta": {"subject_mode": "team"},
                "fields": [
                    {
                        "code": "E",
                        "label": "Execucio",
                        "scope": "member",
                        "type": "matrix",
                        "shape": "judge_x_item",
                        "judges": {"count": 3},
                        "items": {"count": 5},
                    },
                    {
                        "code": "S",
                        "label": "Sync",
                        "scope": "shared",
                        "type": "number",
                    },
                ],
                "computed": [
                    {
                        "code": "E_mem",
                        "label": "Execucio membre",
                        "formula": "row_custom_compute('E', '1 - x')",
                    },
                ],
            },
        )

        request = RequestFactory().get("/competicio/test/classificacions/")
        request.user = self.user
        view = ClassificacionsHome()
        view.request = request
        view.kwargs = {"pk": self.comp.id}
        view.competicio = self.comp

        ctx = view.get_context_data()
        options = ctx["aparell_field_options"][str(self.comp_app.id)]
        by_code = {item["code"]: item for item in options}

        self.assertIn("E", by_code)
        self.assertFalse(by_code["E"]["scoreable"])
        self.assertTrue(by_code["E"]["member_dependent"])
        self.assertTrue(by_code["E"]["detail_displayable"])
        self.assertEqual(by_code["E"]["detail_display_kind"], "judge_rows")
        self.assertTrue(by_code["E_mem"]["detail_displayable"])
        self.assertEqual(by_code["E_mem"]["detail_display_kind"], "scalar")

    def _native_team_schema_with_tie(self, tie):
        return {
            "puntuacio": {
                "aparells": {"mode": "seleccionar", "ids": [self.comp_app.id]},
                "camps_per_aparell": {str(self.comp_app.id): ["total"]},
                "agregacio_camps": "sum",
                "exercicis": {"mode": "tots"},
                "agregacio_exercicis": "sum",
                "agregacio_aparells": "sum",
                "ordre": "desc",
            },
            "desempat": [tie],
            "equips": {
                "context_code": "parelles",
                "team_mode": "native_team",
                "incloure_sense_equip": False,
            },
        }

    def _birth_range_partition_cfg(self, *, compliance_mode="strict", max_outside=0):
        return {
            "particions": ["any_naixement_forquilla"],
            "particions_v2": [
                {"code": "any_naixement_forquilla", "apply_mode": "all", "parent_values": []},
            ],
            "particions_config": {
                "any_naixement_forquilla": {
                    "ranges": [
                        {
                            "label": "U13",
                            "from_date": "2012-01-01",
                            "until_date": "2014-12-31",
                        },
                    ],
                    "sense_data_label": "Sense data",
                    "fora_rang_label": "Fora de forquilla",
                    "team_rules": {
                        "reference_mode": "oldest_member_birthdate",
                        "compliance_mode": compliance_mode,
                        "max_members_outside_range": max_outside,
                        "missing_birthdate_policy": "outside_range",
                    },
                }
            },
        }

    def test_team_builder_native_context_ignores_legacy_team_without_base_assignment(self):
        base_ctx = self._ensure_native_equip_context(self.comp)
        legacy_team = Equip.objects.create(competicio=self.comp, nom="Legacy Base")
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Legacy A",
            ordre_sortida=20,
            grup=1,
            equip=legacy_team,
        )
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Legacy B",
            ordre_sortida=21,
            grup=1,
            equip=legacy_team,
        )
        CompeticioAparellEquipContextSource.objects.filter(
            competicio=self.comp,
            comp_aparell=self.comp_app,
        ).delete()
        CompeticioAparellEquipContextSource.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            context=base_ctx,
        )

        subjects, issues = build_team_subjects_for_comp_aparell(self.comp, self.comp_app)

        self.assertEqual(subjects, [])
        self.assertTrue(any(item.get("context_code") == "native" for item in issues))

    def test_scoring_schema_full_clean_accepts_member_scope_for_team_context(self):
        schema = ScoringSchema(
            aparell=self.app,
            schema={
                "meta": {"subject_mode": "team_context", "expected_team_size": 2},
                "fields": [
                    {"code": "SYNC", "label": "Sincronisme", "type": "number", "scope": "shared"},
                    {"code": "E", "label": "Exec", "type": "number", "scope": "member"},
                ],
                "computed": [
                    {"code": "TOTAL", "label": "Total", "formula": "SYNC + E__m1 + E__m2"},
                ],
            },
        )
        schema.comp_aparell = self.comp_app
        schema.full_clean()

    def test_team_builder_shows_official_member_treatment_options(self):
        self.app.competition_unit = Aparell.CompetitionUnit.TEAM
        self.app.save(update_fields=["competition_unit"])

        response = self.client.get(
            reverse("scoring_schema_update", kwargs={"pk": self.comp.id, "ap_id": self.comp_app.id})
        )

        self.assertEqual(response.status_code, 200)
        body = response.content.decode("utf-8")
        self.assertIn("member_treatment(source, select='all', n=None, agg='sum')", body)
        self.assertIn('<option value="drop_extremes">', body)
        self.assertIn('<option value="drop_extremes_until_n">', body)
        self.assertIn('<option value="count">Comptar</option>', body)
        self.assertIn('<option value="med">Mediana</option>', body)

    def test_team_subject_label_is_truncated_to_model_limit(self):
        long_team_name = "Equip " + ("MoltLlarg" * 20)
        long_members = [
            "Participant " + ("Alpha" * 12),
            "Participant " + ("Beta" * 12),
            "Participant " + ("Gamma" * 12),
        ]
        equip, _members = self._create_team_with_members(long_team_name, long_members, start_order=50)

        subject_obj, subject = self._team_subject(equip)

        self.assertLessEqual(len(subject_obj.label), 255)
        self.assertEqual(subject_obj.label, subject_obj.label.strip())
        self.assertIn("Parelles", subject_obj.label)
        self.assertIn("Equip", subject_obj.label)

    def test_scoring_schema_builder_get_exposes_saved_bootstrap_and_draft_key(self):
        schema = ScoringSchema.objects.create(
            aparell=self.app,
            schema={
                "fields": [
                    {"code": "SYNC", "label": "Sincronisme", "type": "number"},
                ],
                "computed": [],
            },
        )

        response = self.client.get(
            reverse("scoring_schema_update", kwargs={"pk": self.comp.id, "ap_id": self.comp_app.id})
        )

        self.assertEqual(response.status_code, 200)
        bootstrap = response.context["schema_bootstrap"]
        self.assertEqual(bootstrap["schema_initial_source"], "saved")
        self.assertEqual(bootstrap["schema_initial"], schema.schema)
        self.assertIn(f"comp-aparell:{self.comp_app.id}", bootstrap["schema_draft_storage_key"])

    def test_scoring_schema_builder_rehydrates_last_posted_invalid_schema(self):
        existing = ScoringSchema.objects.create(
            aparell=self.app,
            schema={
                "fields": [
                    {"code": "OLD", "label": "Antic", "type": "number"},
                ],
                "computed": [],
            },
        )
        invalid_schema = {
            "fields": [
                {"code": "E", "label": "Exec", "type": "number"},
            ],
            "computed": [
                {"code": "E", "label": "Duplicat", "formula": "1"},
            ],
        }

        response = self.client.post(
            reverse("scoring_schema_update", kwargs={"pk": self.comp.id, "ap_id": self.comp_app.id}),
            data={"schema_json": json.dumps(invalid_schema)},
        )

        self.assertEqual(response.status_code, 200)
        bootstrap = response.context["schema_bootstrap"]
        self.assertEqual(bootstrap["schema_initial_source"], "posted_invalid")
        self.assertEqual(bootstrap["schema_initial"], invalid_schema)
        self.assertEqual(bootstrap["schema_raw_invalid_json"], "")
        existing.refresh_from_db()
        self.assertEqual(existing.schema["fields"][0]["code"], "OLD")

    def test_scoring_schema_builder_preserves_raw_invalid_json(self):
        existing = ScoringSchema.objects.create(
            aparell=self.app,
            schema={
                "fields": [
                    {"code": "OLD", "label": "Antic", "type": "number"},
                ],
                "computed": [],
            },
        )
        invalid_raw_json = '{"fields": ['

        response = self.client.post(
            reverse("scoring_schema_update", kwargs={"pk": self.comp.id, "ap_id": self.comp_app.id}),
            data={"schema_json": invalid_raw_json},
        )

        self.assertEqual(response.status_code, 200)
        bootstrap = response.context["schema_bootstrap"]
        self.assertEqual(bootstrap["schema_initial_source"], "raw_invalid_json")
        self.assertEqual(bootstrap["schema_initial"], existing.schema)
        self.assertEqual(bootstrap["schema_raw_invalid_json"], invalid_raw_json)
        existing.refresh_from_db()
        self.assertEqual(existing.schema["fields"][0]["code"], "OLD")

    def test_competicio_aparell_form_uses_current_team_contract_fields(self):
        form = CompeticioAparellForm(
            data={
                "aparell": self.app.id,
                "nombre_exercicis": 1,
            },
            instance=self.comp_app,
            competicio=self.comp,
        )
        self.assertIn("aparell", form.fields)
        self.assertIn("nombre_exercicis", form.fields)
        self.assertNotIn("team_context", form.fields)
        self.assertNotIn("expected_team_size", form.fields)
        self.assertNotIn("team_scoring_mode", form.fields)
        self.assertTrue(form.is_valid())

    def test_scoreable_codes_filter_team_apps_by_tipus_and_context(self):
        individual_app = self._create_aparell("IND", "Individual")
        individual_comp_app = self._create_comp_aparell(self.comp, individual_app, ordre=2)
        ScoringSchema.objects.create(
            aparell=individual_app,
            schema={"fields": [{"code": "TOTAL", "type": "number"}], "computed": []},
        )
        ScoringSchema.objects.create(
            aparell=self.app,
            schema={"fields": [{"code": "TOTAL", "type": "number"}], "computed": []},
        )
        individual_scoreables = _scoreable_codes_by_app_id(self.comp, tipus="individual")
        self.assertIn(individual_comp_app.id, individual_scoreables)
        self.assertNotIn(self.comp_app.id, individual_scoreables)

        team_scoreables = _scoreable_codes_by_app_id(
            self.comp,
            tipus="equips",
            assignment_context_code="altre",
        )
        self.assertNotIn(self.comp_app.id, team_scoreables)


