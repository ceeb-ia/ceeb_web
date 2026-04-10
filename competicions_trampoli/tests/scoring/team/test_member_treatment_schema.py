from ._shared import *  # noqa: F401,F403


class TeamMemberTreatmentSchemaTests(_BaseTrampoliDataMixin, TestCase):
    def setUp(self):
        self.comp = self._create_competicio("Comp member treatment")
        self.app = self._create_aparell("TEAMSC", "Team Schema")
        self.app.competition_unit = Aparell.CompetitionUnit.TEAM
        self.app.save(update_fields=["competition_unit"])
        self.comp_app = self._create_comp_aparell(self.comp, self.app, ordre=1)

    def test_schema_accepts_member_treatment_on_member_number_field(self):
        schema = ScoringSchema(
            aparell=self.app,
            schema={
                "fields": [
                    {"code": "E", "label": "Exec", "type": "number", "scope": "member"},
                ],
                "computed": [
                    {"code": "TOTAL", "label": "Total", "formula": "member_treatment(E, agg='sum')"},
                ],
            },
        )
        schema.full_clean()

    def test_schema_accepts_member_treatment_on_member_scalar_computed(self):
        schema = ScoringSchema(
            aparell=self.app,
            schema={
                "fields": [
                    {
                        "code": "E",
                        "label": "Exec",
                        "type": "matrix",
                        "shape": "judge_x_item",
                        "scope": "member",
                        "judges": {"count": 1},
                        "items": {"count": 2},
                    },
                ],
                "computed": [
                    {
                        "code": "E_MEMBER",
                        "label": "Exec membre",
                        "formula": "row_custom_compute('E', '1 - x', row_select='all', row_agg='sum', col_select='all', col_agg='sum')",
                    },
                    {
                        "code": "TOTAL",
                        "label": "Total",
                        "formula": "member_treatment(E_MEMBER, select='best_n', n=1, agg='sum')",
                    },
                ],
            },
        )
        schema.full_clean()

    def test_schema_rejects_member_treatment_on_unreduced_member_matrix(self):
        schema = ScoringSchema(
            aparell=self.app,
            schema={
                "fields": [
                    {
                        "code": "E",
                        "label": "Exec",
                        "type": "matrix",
                        "shape": "judge_x_item",
                        "scope": "member",
                        "judges": {"count": 2},
                        "items": {"count": 3},
                    },
                ],
                "computed": [
                    {"code": "TOTAL", "label": "Total", "formula": "member_treatment(E, agg='sum')"},
                ],
            },
        )
        with self.assertRaises(ValidationError) as ctx:
            schema.full_clean()
        self.assertIn("member_scalar", str(ctx.exception))

    def test_schema_rejects_member_treatment_on_shared_field(self):
        schema = ScoringSchema(
            aparell=self.app,
            schema={
                "fields": [
                    {"code": "SYNC", "label": "Sync", "type": "number", "scope": "shared"},
                ],
                "computed": [
                    {"code": "TOTAL", "label": "Total", "formula": "member_treatment(SYNC, agg='sum')"},
                ],
            },
        )
        with self.assertRaises(ValidationError) as ctx:
            schema.full_clean()
        self.assertIn("member_scalar", str(ctx.exception))

    def test_schema_rejects_member_treatment_with_invalid_select(self):
        schema = ScoringSchema(
            aparell=self.app,
            schema={
                "fields": [
                    {"code": "E", "label": "Exec", "type": "number", "scope": "member"},
                ],
                "computed": [
                    {"code": "TOTAL", "label": "Total", "formula": "member_treatment(E, select='median_band', agg='sum')"},
                ],
            },
        )
        with self.assertRaises(ValidationError) as ctx:
            schema.full_clean()
        self.assertIn("member_treatment.select invalid", str(ctx.exception))

    def test_schema_rejects_member_treatment_with_invalid_agg(self):
        schema = ScoringSchema(
            aparell=self.app,
            schema={
                "fields": [
                    {"code": "E", "label": "Exec", "type": "number", "scope": "member"},
                ],
                "computed": [
                    {"code": "TOTAL", "label": "Total", "formula": "member_treatment(E, agg='median')"},
                ],
            },
        )
        with self.assertRaises(ValidationError) as ctx:
            schema.full_clean()
        self.assertIn("member_treatment.agg invalid", str(ctx.exception))

    def test_schema_rejects_member_treatment_missing_n_when_selector_requires_it(self):
        schema = ScoringSchema(
            aparell=self.app,
            schema={
                "fields": [
                    {"code": "E", "label": "Exec", "type": "number", "scope": "member"},
                ],
                "computed": [
                    {"code": "TOTAL", "label": "Total", "formula": "member_treatment(E, select='drop_extremes_until_n', agg='sum')"},
                ],
            },
        )
        with self.assertRaises(ValidationError) as ctx:
            schema.full_clean()
        self.assertIn("requereix n", str(ctx.exception))

    def test_schema_rejects_member_treatment_with_n_when_selector_does_not_use_it(self):
        schema = ScoringSchema(
            aparell=self.app,
            schema={
                "fields": [
                    {"code": "E", "label": "Exec", "type": "number", "scope": "member"},
                ],
                "computed": [
                    {"code": "TOTAL", "label": "Total", "formula": "member_treatment(E, select='drop_extremes', n=2, agg='sum')"},
                ],
            },
        )
        with self.assertRaises(ValidationError) as ctx:
            schema.full_clean()
        self.assertIn("no admet n", str(ctx.exception))

    def test_individual_app_rejects_member_treatment(self):
        app = self._create_aparell("INDSC", "Individual Schema")
        schema = ScoringSchema(
            aparell=app,
            schema={
                "fields": [
                    {"code": "E", "label": "Exec", "type": "number"},
                ],
                "computed": [
                    {"code": "TOTAL", "label": "Total", "formula": "member_treatment(E, agg='sum')"},
                ],
            },
        )
        with self.assertRaises(ValidationError) as ctx:
            schema.full_clean()
        self.assertIn("nomes es permes", str(ctx.exception))

    def test_runtime_schema_and_engine_support_member_treatment(self):
        schema = {
            "fields": [
                {"code": "SYNC", "label": "Sync", "type": "number", "scope": "shared"},
                {"code": "E", "label": "Exec", "type": "number", "scope": "member"},
            ],
            "computed": [
                {"code": "BEST_EXEC", "label": "Best exec", "formula": "member_treatment(E, select='best_n', n=1, agg='sum')"},
                {"code": "TOTAL", "label": "Total", "formula": "BEST_EXEC + SYNC"},
            ],
        }
        runtime_schema = runtime_schema_for_comp_aparell(schema, self.comp_app, member_count=2)
        best_exec_formula = next(
            c["formula"] for c in runtime_schema.get("computed", []) if c.get("code") == "BEST_EXEC"
        )
        self.assertIn("member_treatment", best_exec_formula)
        self.assertIn("E__m1", best_exec_formula)
        self.assertIn("E__m2", best_exec_formula)

        result = ScoringEngine(runtime_schema).compute(
            {
                "SYNC": 6.0,
                "E__m1": 8.1,
                "E__m2": 7.9,
            }
        )
        self.assertAlmostEqual(result.outputs["BEST_EXEC"], 8.1)
        self.assertAlmostEqual(result.total, 14.1)

    def test_runtime_member_treatment_wrappers_match_explicit_contract(self):
        schema = {
            "fields": [
                {"code": "E", "label": "Exec", "type": "number", "scope": "member"},
            ],
            "computed": [
                {"code": "SUM_EXPL", "label": "Sum explicit", "formula": "member_treatment(E, agg='sum')"},
                {"code": "SUM_WRAP", "label": "Sum wrap", "formula": "members_sum(E)"},
                {"code": "AVG_EXPL", "label": "Avg explicit", "formula": "member_treatment(E, agg='avg')"},
                {"code": "AVG_WRAP", "label": "Avg wrap", "formula": "members_avg(E)"},
                {"code": "MIN_EXPL", "label": "Min explicit", "formula": "member_treatment(E, agg='min')"},
                {"code": "MIN_WRAP", "label": "Min wrap", "formula": "members_min(E)"},
                {"code": "MAX_EXPL", "label": "Max explicit", "formula": "member_treatment(E, agg='max')"},
                {"code": "MAX_WRAP", "label": "Max wrap", "formula": "members_max(E)"},
                {"code": "COUNT_EXPL", "label": "Count explicit", "formula": "member_treatment(E, agg='count')"},
                {"code": "COUNT_WRAP", "label": "Count wrap", "formula": "members_count(E)"},
            ],
        }
        runtime_schema = runtime_schema_for_comp_aparell(schema, self.comp_app, member_count=3)
        result = ScoringEngine(runtime_schema).compute(
            {
                "E__m1": 8.1,
                "E__m2": 7.4,
                "E__m3": 8.5,
            }
        )
        self.assertAlmostEqual(result.outputs["SUM_EXPL"], result.outputs["SUM_WRAP"])
        self.assertAlmostEqual(result.outputs["AVG_EXPL"], result.outputs["AVG_WRAP"])
        self.assertAlmostEqual(result.outputs["MIN_EXPL"], result.outputs["MIN_WRAP"])
        self.assertAlmostEqual(result.outputs["MAX_EXPL"], result.outputs["MAX_WRAP"])
        self.assertAlmostEqual(result.outputs["COUNT_EXPL"], result.outputs["COUNT_WRAP"])

    def test_runtime_member_treatment_supports_official_advanced_selectors_and_med(self):
        schema = {
            "fields": [
                {"code": "E", "label": "Exec", "type": "number", "scope": "member"},
            ],
            "computed": [
                {"code": "DROP_SUM", "label": "Drop extremes", "formula": "member_treatment(E, select='drop_extremes', agg='sum')"},
                {"code": "ALT_TWO", "label": "Alternating extremes", "formula": "member_treatment(E, select='drop_extremes_until_n', n=2, agg='sum')"},
                {"code": "MEDIAN", "label": "Median", "formula": "member_treatment(E, agg='med')"},
            ],
        }
        runtime_schema = runtime_schema_for_comp_aparell(schema, self.comp_app, member_count=5)
        result = ScoringEngine(runtime_schema).compute(
            {
                "E__m1": 1.0,
                "E__m2": 3.0,
                "E__m3": 5.0,
                "E__m4": 7.0,
                "E__m5": 9.0,
            }
        )
        self.assertAlmostEqual(result.outputs["DROP_SUM"], 15.0)
        self.assertAlmostEqual(result.outputs["ALT_TWO"], 8.0)
        self.assertAlmostEqual(result.outputs["MEDIAN"], 5.0)

    def test_runtime_schema_expands_member_computed_before_member_treatment(self):
        schema = {
            "fields": [
                {
                    "code": "E",
                    "label": "Exec",
                    "type": "matrix",
                    "shape": "judge_x_item",
                    "scope": "member",
                    "judges": {"count": 1},
                    "items": {"count": 2},
                },
            ],
            "computed": [
                {
                    "code": "E_MEMBER",
                    "label": "Exec membre",
                    "formula": "row_custom_compute('E', '1 - x', row_select='all', row_agg='sum', col_select='all', col_agg='sum')",
                },
                {
                    "code": "TOTAL",
                    "label": "Total",
                    "formula": "member_treatment(E_MEMBER, agg='avg')",
                },
            ],
        }
        runtime_schema = runtime_schema_for_comp_aparell(schema, self.comp_app, member_count=2)
        runtime_codes = [c.get("code") for c in runtime_schema.get("computed", [])]
        self.assertIn("E_MEMBER__m1", runtime_codes)
        self.assertIn("E_MEMBER__m2", runtime_codes)

        engine = ScoringEngine(runtime_schema)
        result = engine.compute(
            {
                "E__m1": [[0.1, 0.2]],
                "E__m2": [[0.4, 0.1]],
            }
        )
        self.assertAlmostEqual(result.outputs["E_MEMBER__m1"], 1.7)
        self.assertAlmostEqual(result.outputs["E_MEMBER__m2"], 1.5)
        self.assertAlmostEqual(result.total, 1.6)


