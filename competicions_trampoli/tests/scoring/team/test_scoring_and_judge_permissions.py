from ._shared import *  # noqa: F401,F403


class TeamContextScoringAndJudgePermissionsTests(TeamContextScoringFlowTestBase):
    def test_scoring_save_partial_creates_team_score_entry(self):
        ScoringSchema.objects.create(
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
        team_subject, _subject_meta = self._team_subject()

        response = self.client.post(
            reverse("scoring_save_partial", kwargs={"pk": self.comp.id}),
            data=json.dumps(
                {
                    "comp_aparell_id": self.comp_app.id,
                    "subject_kind": "team_unit",
                    "subject_id": team_subject.id,
                    "exercici": 1,
                    "inputs_patch": {
                        "SYNC": 7.5,
                        "E": {
                            str(team_subject.member_ids[0]): 8.1,
                            str(team_subject.member_ids[1]): 8.2,
                        },
                    },
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["subject_kind"], "team_unit")
        self.assertEqual(payload["subject_id"], team_subject.id)
        self.assertEqual(
            payload["inputs"]["E"],
            {
                str(team_subject.member_ids[0]): 8.1,
                str(team_subject.member_ids[1]): 8.2,
            },
        )

        entry = TeamScoreEntry.objects.get(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            team_subject=team_subject,
            exercici=1,
        )
        self.assertEqual(float(entry.total), 23.8)
        self.assertEqual(entry.inputs["SYNC"], 7.5)
        self.assertEqual(
            entry.inputs["E"],
            {
                str(team_subject.member_ids[0]): 8.1,
                str(team_subject.member_ids[1]): 8.2,
            },
        )

    def test_scoring_save_partial_rejects_runtime_member_keys_for_team_app(self):
        ScoringSchema.objects.create(
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
        team_subject, _subject_meta = self._team_subject()

        response = self.client.post(
            reverse("scoring_save_partial", kwargs={"pk": self.comp.id}),
            data=json.dumps(
                {
                    "comp_aparell_id": self.comp_app.id,
                    "subject_kind": "team_unit",
                    "subject_id": team_subject.id,
                    "exercici": 1,
                    "inputs_patch": {"SYNC": 7.5, "E__m1": 8.1},
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("__mN", response.json()["error"])

    def test_scoring_save_partial_team_1x1_judge_fields_can_be_empty(self):
        ScoringSchema.objects.create(
            aparell=self.app,
            schema={
                "meta": {"subject_mode": "team_context", "expected_team_size": 2},
                "fields": [
                    {
                        "code": "DD",
                        "label": "Dificultat",
                        "type": "matrix",
                        "shape": "judge_x_item",
                        "scope": "shared",
                        "judges": {"count": 1},
                        "items": {"count": 1},
                    },
                    {
                        "code": "S",
                        "label": "Sincronisme",
                        "type": "matrix",
                        "shape": "judge_x_item",
                        "scope": "shared",
                        "judges": {"count": 1},
                        "items": {"count": 1},
                    },
                    {
                        "code": "P",
                        "label": "Penalitzacio",
                        "type": "matrix",
                        "shape": "judge_x_item",
                        "scope": "shared",
                        "judges": {"count": 1},
                        "items": {"count": 1},
                    },
                    {
                        "code": "HD",
                        "label": "Horizontal",
                        "type": "matrix",
                        "shape": "judge_x_item",
                        "scope": "member",
                        "judges": {"count": 1},
                        "items": {"count": 1},
                    },
                ],
                "computed": [
                    {"code": "HD_SCORE", "label": "HD membre", "formula": "row_custom_compute('HD', 'x')"},
                    {"code": "TOTAL", "label": "Total", "formula": "DD + S + P + member_treatment(HD_SCORE, agg='sum')"},
                ],
            },
        )
        team_subject, _subject_meta = self._team_subject()

        response = self.client.post(
            reverse("scoring_save_partial", kwargs={"pk": self.comp.id}),
            data=json.dumps(
                {
                    "comp_aparell_id": self.comp_app.id,
                    "subject_kind": "team_unit",
                    "subject_id": team_subject.id,
                    "exercici": 1,
                    "inputs_patch": {
                        "DD": [[None]],
                        "S": [[None]],
                        "P": [[None]],
                    },
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertEqual(payload["inputs"]["DD"], [[0.0]])
        self.assertEqual(payload["inputs"]["S"], [[0.0]])
        self.assertEqual(payload["inputs"]["P"], [[0.0]])
        self.assertNotIn("__presence__DD", payload["inputs"])
        self.assertEqual(payload["total"], 0.0)

    def test_scoring_save_partial_team_presence_toggle_does_not_delete_member_notes(self):
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
                "computed": [
                    {"code": "E_SCORE", "label": "Exec", "formula": "row_custom_compute('E', 'x')"},
                    {"code": "TOTAL", "label": "Total", "formula": "member_treatment(E_SCORE, agg='sum')"},
                ],
            },
        )
        team_subject, _subject_meta = self._team_subject()
        member_id = str(team_subject.member_ids[0])
        url = reverse("scoring_save_partial", kwargs={"pk": self.comp.id})

        first = self.client.post(
            url,
            data=json.dumps(
                {
                    "comp_aparell_id": self.comp_app.id,
                    "subject_kind": "team_unit",
                    "subject_id": team_subject.id,
                    "exercici": 1,
                    "inputs_patch": {
                        "E": {member_id: [[1, 2], [3, 4]]},
                        "__presence__E": {member_id: [True, True]},
                    },
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(first.status_code, 200, first.content)

        second = self.client.post(
            url,
            data=json.dumps(
                {
                    "comp_aparell_id": self.comp_app.id,
                    "subject_kind": "team_unit",
                    "subject_id": team_subject.id,
                    "exercici": 1,
                    "inputs_patch": {"__presence__E": {member_id: [True, False]}},
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(second.status_code, 200, second.content)
        payload = second.json()
        self.assertEqual(payload["inputs"]["E"][member_id], [[1, 2], [3, 4]])
        self.assertEqual(payload["inputs"]["__presence__E"][member_id], [True, False])

        entry = TeamScoreEntry.objects.get(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            team_subject=team_subject,
            exercici=1,
        )
        self.assertEqual(entry.inputs["E"][member_id], [[1, 2], [3, 4]])
        self.assertEqual(entry.inputs["__presence__E"][member_id], [True, False])

    def test_schema_recalc_for_team_preserves_orphan_inputs(self):
        schema = ScoringSchema.objects.create(
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
        team_subject, _subject_meta = self._team_subject()
        TeamScoreEntry.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            team_subject=team_subject,
            exercici=1,
            inputs={
                "SYNC": 7.5,
                "E": {
                    str(team_subject.member_ids[0]): 8.1,
                    str(team_subject.member_ids[1]): 8.2,
                },
                "OLD_FIELD": 99.0,
            },
            outputs={"TOTAL": 23.8},
            total=23.8,
        )

        response = self.client.post(
            reverse("scoring_schema_update", kwargs={"pk": self.comp.id, "ap_id": self.comp_app.id}),
            data={
                "schema_json": json.dumps(
                    {
                        "meta": {"subject_mode": "team_context", "expected_team_size": 2},
                        "fields": [
                            {"code": "SYNC", "label": "Sincronisme", "type": "number", "scope": "shared"},
                            {"code": "E", "label": "Exec", "type": "number", "scope": "member"},
                            {"code": "BONUS", "label": "Bonus", "type": "number", "scope": "shared"},
                        ],
                        "computed": [
                            {"code": "TOTAL", "label": "Total", "formula": "SYNC + E__m1 + E__m2 + BONUS"},
                        ],
                    }
                )
            },
        )

        self.assertEqual(response.status_code, 302)
        schema.refresh_from_db()
        entry = TeamScoreEntry.objects.get(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            team_subject=team_subject,
            exercici=1,
        )
        self.assertIn("OLD_FIELD", entry.inputs)
        self.assertEqual(entry.inputs["OLD_FIELD"], 99.0)
        self.assertEqual(entry.inputs["SYNC"], 7.5)
        self.assertEqual(entry.inputs["E"][str(team_subject.member_ids[0])], 8.1)
        self.assertEqual(entry.inputs["E"][str(team_subject.member_ids[1])], 8.2)

    def test_scoring_save_rejects_individual_payload_for_team_context_app(self):
        ScoringSchema.objects.create(
            aparell=self.app,
            schema={
                "meta": {"subject_mode": "team_context", "expected_team_size": 2},
                "fields": [{"code": "SYNC", "label": "Sincronisme", "type": "number", "scope": "shared"}],
                "computed": [],
            },
        )

        response = self.client.post(
            reverse("scoring_save", kwargs={"pk": self.comp.id}),
            data=json.dumps(
                {
                    "comp_aparell_id": self.comp_app.id,
                    "inscripcio_id": self.ins1.id,
                    "exercici": 1,
                    "inputs": {"SYNC": 7.5},
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("subject_kind=team_unit", response.json()["error"])

    def test_judge_save_partial_uses_team_subject_and_runtime_member_permission(self):
        ScoringSchema.objects.create(
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
        token = JudgeDeviceToken.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            label="Team Judge",
            permissions=[
                {"field_code": "SYNC", "runtime_field_code": "SYNC", "scope": "shared", "judge_index": 1},
                {"field_code": "E", "runtime_field_code": "E__m2", "scope": "member", "member_slot": 2, "judge_index": 1},
            ],
            is_active=True,
        )
        team_subject, _subject_meta = self._team_subject()

        response = self.client.post(
            reverse("judge_save_partial", kwargs={"token": token.id}),
            data=json.dumps(
                {
                    "subject_kind": "team_unit",
                    "subject_id": team_subject.id,
                    "exercici": 1,
                    "inputs_patch": {"SYNC": 6.4, "E__m2": 7.1},
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["subject_kind"], "team_unit")
        self.assertEqual(payload["subject_id"], team_subject.id)
        self.assertEqual(payload["inputs"]["SYNC"], 6.4)
        self.assertEqual(payload["inputs"]["E__m2"], 7.1)

        entry = TeamScoreEntry.objects.get(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            team_subject=team_subject,
            exercici=1,
        )
        self.assertEqual(entry.inputs["SYNC"], 6.4)
        self.assertEqual(entry.inputs["E"][str(self.ins2.id)], 7.1)
        self.assertEqual(entry.inputs["E"][str(self.ins1.id)], 0.0)

    def test_judge_save_partial_uses_comp_aparell_specific_schema_before_global(self):
        app, comp_aparell = self._create_individual_comp_aparell(codi="TRSAVE", nom="Tramp Save", ordre=10)
        ScoringSchema.objects.create(
            aparell=app,
            schema={
                "fields": [{"code": "SYNC", "label": "Sync", "type": "number"}],
                "computed": [{"code": "TOTAL", "label": "Total", "formula": "SYNC"}],
            },
        )
        ScoringSchema.objects.create(
            comp_aparell=comp_aparell,
            schema={
                "fields": [{"code": "ALT", "label": "Alt", "type": "number"}],
                "computed": [{"code": "TOTAL", "label": "Total", "formula": "ALT"}],
            },
        )
        token = JudgeDeviceToken.objects.create(
            competicio=self.comp,
            comp_aparell=comp_aparell,
            label="Individual override",
            permissions=[{"field_code": "ALT", "runtime_field_code": "ALT", "scope": "shared", "judge_index": 1}],
            is_active=True,
        )

        response = self.client.post(
            reverse("judge_save_partial", kwargs={"token": token.id}),
            data=json.dumps(
                {
                    "subject_kind": "inscripcio",
                    "subject_id": self.ins1.id,
                    "exercici": 1,
                    "inputs_patch": {"ALT": 5.5},
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["inputs"]["ALT"], 5.5)
        entry = ScoreEntry.objects.get(
            competicio=self.comp,
            comp_aparell=comp_aparell,
            inscripcio=self.ins1,
            exercici=1,
        )
        self.assertEqual(entry.inputs["ALT"], 5.5)
        self.assertAlmostEqual(float(entry.total), 5.5)

    def test_permission_runtime_resolution_supports_member_modes_and_legacy_permissions(self):
        all_entries = resolve_permission_runtime_entries(
            {"field_code": "E", "scope": "member", "judge_index": 1, "member_mode": "all"},
            self.comp_app,
            member_count=2,
        )
        self.assertEqual([row["runtime_field_code"] for row in all_entries], ["E__m1", "E__m2"])

        subset_entries = resolve_permission_runtime_entries(
            {"field_code": "E", "scope": "member", "judge_index": 1, "member_mode": "subset", "member_slots": [1, 2]},
            self.comp_app,
            member_count=2,
        )
        self.assertEqual([row["runtime_field_code"] for row in subset_entries], ["E__m1", "E__m2"])
        self.assertEqual(build_permission_label({"field_code": "E", "scope": "member", "member_mode": "subset", "member_slots": [1, 2]}), "E · Individual · M1,M2")

        legacy_entries = resolve_permission_runtime_entries(
            {"field_code": "E", "scope": "member", "judge_index": 1, "runtime_field_code": "E__m2"},
            self.comp_app,
            member_count=2,
        )
        self.assertEqual([row["runtime_field_code"] for row in legacy_entries], ["E__m2"])

        missing_slot_entries = resolve_permission_runtime_entries(
            {"field_code": "E", "scope": "member", "judge_index": 1, "member_mode": "subset", "member_slots": [3]},
            self.comp_app,
            member_count=2,
        )
        self.assertEqual(missing_slot_entries, [])

    def test_member_slot_choices_use_real_max_across_all_context_subjects(self):
        trio_ctx = EquipContext.objects.create(
            competicio=self.comp,
            code="trios",
            nom="Trios",
        )
        CompeticioAparellEquipContextSource.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            context=trio_ctx,
        )
        self._create_team_with_members(
            "Trio 1",
            ["Aina", "Noa", "Judit"],
            context=trio_ctx,
            start_order=40,
        )

        slots = _member_slot_choices(self.comp, self.comp_app)

        self.assertEqual(slots, [1, 2, 3])
        self.assertNotIn(4, slots)

    def test_validate_permission_row_rejects_invalid_member_targeting(self):
        schema_by_code = {
            "E": {"code": "E", "type": "number", "scope": "member", "judges": {"count": 1}},
            "SYNC": {"code": "SYNC", "type": "number", "scope": "shared", "judges": {"count": 1}},
        }

        valid = _validate_permission_row(
            schema_by_code,
            {
                "field_code": "E",
                "scope": "member",
                "judge_index": 1,
                "member_mode": "single",
                "member_slots": "2",
            },
            team_context_mode=True,
        )
        self.assertEqual(valid["member_mode"], "single")
        self.assertEqual(valid["member_slots"], [2])

        with self.assertRaisesMessage(ValueError, "exactament un membre"):
            _validate_permission_row(
                schema_by_code,
                {
                    "field_code": "E",
                    "scope": "member",
                    "judge_index": 1,
                    "member_mode": "single",
                    "member_slots": "1,2",
                },
                team_context_mode=True,
            )

        with self.assertRaisesMessage(ValueError, "almenys un membre"):
            _validate_permission_row(
                schema_by_code,
                {
                    "field_code": "E",
                    "scope": "member",
                    "judge_index": 1,
                    "member_mode": "subset",
                    "member_slots": "",
                },
                team_context_mode=True,
            )

        legacy_individual = _validate_permission_row(
            schema_by_code,
            {
                "field_code": "E",
                "scope": "member",
                "judge_index": 1,
                "member_mode": "all",
            },
            team_context_mode=False,
        )
        self.assertEqual(legacy_individual["scope"], "shared")
        self.assertNotIn("member_mode", legacy_individual)

        with self.assertRaisesMessage(ValueError, "abast compartit"):
            _validate_permission_row(
                schema_by_code,
                {
                    "field_code": "SYNC",
                    "scope": "member",
                    "judge_index": 1,
                    "member_mode": "all",
                },
                team_context_mode=True,
            )

        with self.assertRaisesMessage(ValueError, "abast individual"):
            _validate_permission_row(
                schema_by_code,
                {
                    "field_code": "E",
                    "scope": "shared",
                    "judge_index": 1,
                },
                team_context_mode=True,
            )

    def test_resolve_scoring_schema_for_comp_aparell_prefers_specific_before_global(self):
        global_schema = ScoringSchema.objects.create(
            aparell=self.app,
            schema={"fields": [{"code": "SYNC", "label": "Sync", "type": "number", "scope": "shared"}], "computed": []},
        )
        specific_schema = ScoringSchema.objects.create(
            comp_aparell=self.comp_app,
            schema={"fields": [{"code": "ALT", "label": "Alt", "type": "number", "scope": "shared"}], "computed": []},
        )

        schema_obj, schema = resolve_scoring_schema_for_comp_aparell(self.comp_app)

        self.assertEqual(schema_obj.pk, specific_schema.pk)
        self.assertEqual(schema["fields"][0]["code"], "ALT")
        global_schema.refresh_from_db()
        self.assertEqual(global_schema.schema["fields"][0]["code"], "SYNC")

    def test_resolve_scoring_schema_for_comp_aparell_falls_back_to_global(self):
        global_schema = ScoringSchema.objects.create(
            aparell=self.app,
            schema={"fields": [{"code": "SYNC", "label": "Sync", "type": "number", "scope": "shared"}], "computed": []},
        )

        schema_obj, schema = resolve_scoring_schema_for_comp_aparell(self.comp_app)

        self.assertEqual(schema_obj.pk, global_schema.pk)
        self.assertEqual(schema["fields"][0]["code"], "SYNC")

    def test_judge_admin_create_token_stores_member_targeting(self):
        ScoringSchema.objects.create(
            aparell=self.app,
            schema={
                "meta": {"subject_mode": "team_context", "expected_team_size": 2},
                "fields": [
                    {"code": "SYNC", "label": "Sincronisme", "type": "number", "scope": "shared"},
                    {"code": "E", "label": "Exec", "type": "number", "scope": "member"},
                ],
                "computed": [],
            },
        )

        response = self.client.post(
            f"{reverse('judges_qr_home', kwargs={'competicio_id': self.comp.id})}?comp_aparell={self.comp_app.id}",
            data={
                "action": "create",
                "label": "Judge subset",
                "form-TOTAL_FORMS": "1",
                "form-INITIAL_FORMS": "0",
                "form-MIN_NUM_FORMS": "0",
                "form-MAX_NUM_FORMS": "15",
                "form-0-field_code": "E",
                "form-0-scope": "member",
                "form-0-member_mode": "subset",
                "form-0-member_slots": "1,2",
                "form-0-judge_index": "1",
                "form-0-item_start": "1",
                "form-0-item_count": "",
            },
        )

        self.assertEqual(response.status_code, 302)
        token = JudgeDeviceToken.objects.get(label="Judge subset")
        self.assertEqual(token.permissions[0]["member_mode"], "subset")
        self.assertEqual(token.permissions[0]["member_slots"], [1, 2])

    def test_judge_admin_uses_comp_aparell_specific_schema_before_global(self):
        ScoringSchema.objects.create(
            aparell=self.app,
            schema={
                "fields": [
                    {"code": "SYNC", "label": "Sincronisme", "type": "number", "scope": "shared"},
                ],
                "computed": [],
            },
        )
        ScoringSchema.objects.create(
            comp_aparell=self.comp_app,
            schema={
                "meta": {"subject_mode": "team_context", "expected_team_size": 2},
                "fields": [
                    {"code": "ALT", "label": "Alternatiu", "type": "number", "scope": "shared"},
                ],
                "computed": [],
            },
        )

        response = self.client.get(
            f"{reverse('judges_qr_home', kwargs={'competicio_id': self.comp.id})}?comp_aparell={self.comp_app.id}"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["schema"]["fields"][0]["code"], "ALT")
        self.assertEqual(response.context["schema_field_catalog"][0]["code"], "ALT")

    def test_judge_admin_individual_app_hides_scope_and_tolerates_legacy_member_schema(self):
        app, comp_aparell = self._create_individual_comp_aparell()
        ScoringSchema.objects.create(
            comp_aparell=comp_aparell,
            schema={
                "fields": [
                    {"code": "ALT", "label": "Alternatiu", "type": "number", "scope": "member"},
                ],
                "computed": [
                    {"code": "TOTAL", "label": "Total", "formula": "ALT"},
                ],
            },
        )

        response = self.client.get(
            f"{reverse('judges_qr_home', kwargs={'competicio_id': self.comp.id})}?comp_aparell={comp_aparell.id}"
        )

        self.assertEqual(response.status_code, 200)
        body = response.content.decode("utf-8")
        self.assertNotIn("<th>Abast</th>", body)
        self.assertIn('type="hidden" name="form-0-scope"', body)

        post_response = self.client.post(
            f"{reverse('judges_qr_home', kwargs={'competicio_id': self.comp.id})}?comp_aparell={comp_aparell.id}",
            data={
                "action": "create",
                "label": "Judge individual legacy",
                "form-TOTAL_FORMS": "1",
                "form-INITIAL_FORMS": "0",
                "form-MIN_NUM_FORMS": "0",
                "form-MAX_NUM_FORMS": "15",
                "form-0-field_code": "ALT",
                "form-0-scope": "shared",
                "form-0-member_mode": "all",
                "form-0-member_slots": "",
                "form-0-judge_index": "1",
                "form-0-item_start": "1",
                "form-0-item_count": "",
            },
        )

        self.assertEqual(post_response.status_code, 302)
        token = JudgeDeviceToken.objects.get(label="Judge individual legacy")
        self.assertEqual(token.comp_aparell_id, comp_aparell.id)
        self.assertEqual(token.permissions[0]["field_code"], "ALT")
        self.assertEqual(token.permissions[0]["scope"], "shared")
        self.assertEqual(token.permissions[0]["runtime_field_code"], "ALT")
        self.assertNotIn("member_mode", token.permissions[0])

    def test_judge_admin_team_app_keeps_scope_column_visible(self):
        ScoringSchema.objects.create(
            aparell=self.app,
            schema={
                "meta": {"subject_mode": "team_context", "expected_team_size": 2},
                "fields": [
                    {"code": "SYNC", "label": "Sincronisme", "type": "number", "scope": "shared"},
                ],
                "computed": [],
            },
        )

        response = self.client.get(
            f"{reverse('judges_qr_home', kwargs={'competicio_id': self.comp.id})}?comp_aparell={self.comp_app.id}"
        )

        self.assertEqual(response.status_code, 200)
        body = response.content.decode("utf-8")
        self.assertIn("<th>Abast</th>", body)
        self.assertIn('id="judge-schema-field-catalog"', body)
        self.assertIn('"code": "SYNC"', body)
        self.assertIn('"scope": "shared"', body)

    def test_judge_admin_team_shared_field_ignores_member_targeting(self):
        ScoringSchema.objects.create(
            aparell=self.app,
            schema={
                "meta": {"subject_mode": "team_context", "expected_team_size": 2},
                "fields": [
                    {"code": "SYNC", "label": "Sincronisme", "type": "number", "scope": "shared"},
                    {"code": "E", "label": "Exec", "type": "number", "scope": "member"},
                ],
                "computed": [],
            },
        )

        response = self.client.post(
            f"{reverse('judges_qr_home', kwargs={'competicio_id': self.comp.id})}?comp_aparell={self.comp_app.id}",
            data={
                "action": "create",
                "label": "Judge shared team",
                "form-TOTAL_FORMS": "1",
                "form-INITIAL_FORMS": "0",
                "form-MIN_NUM_FORMS": "0",
                "form-MAX_NUM_FORMS": "15",
                "form-0-field_code": "SYNC",
                "form-0-scope": "shared",
                "form-0-member_mode": "subset",
                "form-0-member_slots": "1,2",
                "form-0-judge_index": "1",
                "form-0-item_start": "1",
                "form-0-item_count": "",
            },
        )

        self.assertEqual(response.status_code, 302)
        token = JudgeDeviceToken.objects.get(label="Judge shared team")
        self.assertEqual(token.permissions[0]["scope"], "shared")
        self.assertNotIn("member_mode", token.permissions[0])
        self.assertNotIn("member_slots", token.permissions[0])

    def test_judge_portal_uses_team_dom_keys_and_member_target_metadata(self):
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
        token = JudgeDeviceToken.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            label="Team portal subset",
            permissions=[
                {"field_code": "E", "scope": "member", "judge_index": 1, "member_mode": "subset", "member_slots": [1, 2]},
            ],
            is_active=True,
        )
        team_subject, _subject_meta = self._team_subject()
        TeamScoreEntry.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            team_subject=team_subject,
            exercici=1,
            inputs={
                "E": {
                    str(self.ins1.id): 8.1,
                    str(self.ins2.id): 8.2,
                }
            },
            outputs={},
            total=0,
        )

        response = self.client.get(reverse("judge_portal", kwargs={"token": token.id}))

        self.assertEqual(response.status_code, 200)
        dom_key = f"team_unit:{team_subject.id}"
        self.assertIn(dom_key, response.context["scores_payload_json"])
        exercise_payload = response.context["scores_payload_json"][dom_key]["exercises"]["1"]["inputs"]
        self.assertEqual(exercise_payload["E__m1"], 8.1)
        self.assertEqual(exercise_payload["E__m2"], 8.2)
        self.assertEqual(response.context["permissions"][0]["member_mode"], "subset")
        self.assertEqual(response.context["permissions"][0]["member_slots"], [1, 2])

    def test_judge_portal_renders_missing_member_slots_as_disabled(self):
        trio_ctx = EquipContext.objects.create(
            competicio=self.comp,
            code="trios_portal",
            nom="Trios Portal",
        )
        CompeticioAparellEquipContextSource.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            context=trio_ctx,
        )
        self._create_team_with_members(
            "Trio 2",
            ["Berta", "Clara", "Nina"],
            context=trio_ctx,
            start_order=50,
        )
        ScoringSchema.objects.create(
            aparell=self.app,
            schema={
                "meta": {"subject_mode": "team_context", "expected_team_size": 3},
                "fields": [
                    {"code": "E", "label": "Exec", "type": "number", "scope": "member"},
                ],
                "computed": [],
            },
        )
        token = JudgeDeviceToken.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            label="Team portal missing slot",
            permissions=[
                {"field_code": "E", "scope": "member", "judge_index": 1, "member_mode": "subset", "member_slots": [1, 3]},
            ],
            is_active=True,
        )

        response = self.client.get(reverse("judge_portal", kwargs={"token": token.id}))

        self.assertEqual(response.status_code, 200)
        body = response.content.decode("utf-8")
        self.assertIn("Membre no disponible per aquest equip. El camp queda desactivat.", body)
        self.assertIn("Membre inexistent", body)

    def test_judge_save_partial_accepts_member_mode_all_permissions(self):
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
        token = JudgeDeviceToken.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            label="Team Judge All Members",
            permissions=[{"field_code": "E", "scope": "member", "judge_index": 1, "member_mode": "all"}],
            is_active=True,
        )
        team_subject, _subject_meta = self._team_subject()

        response = self.client.post(
            reverse("judge_save_partial", kwargs={"token": token.id}),
            data=json.dumps(
                {
                    "subject_kind": "team_unit",
                    "subject_id": team_subject.id,
                    "exercici": 1,
                    "inputs_patch": {"E__m1": 8.4, "E__m2": 8.1},
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["inputs"]["E__m1"], 8.4)
        self.assertEqual(payload["inputs"]["E__m2"], 8.1)

        entry = TeamScoreEntry.objects.get(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            team_subject=team_subject,
            exercici=1,
        )
        self.assertEqual(entry.inputs["E"][str(self.ins1.id)], 8.4)
        self.assertEqual(entry.inputs["E"][str(self.ins2.id)], 8.1)

    def test_judge_save_partial_rejects_individual_payload_for_team_context_app(self):
        ScoringSchema.objects.create(
            aparell=self.app,
            schema={
                "meta": {"subject_mode": "team_context", "expected_team_size": 2},
                "fields": [{"code": "SYNC", "label": "Sincronisme", "type": "number", "scope": "shared"}],
                "computed": [],
            },
        )
        token = JudgeDeviceToken.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            label="Team Judge Reject",
            permissions=[{"field_code": "SYNC", "runtime_field_code": "SYNC", "scope": "shared", "judge_index": 1}],
            is_active=True,
        )

        response = self.client.post(
            reverse("judge_save_partial", kwargs={"token": token.id}),
            data=json.dumps(
                {
                    "inscripcio_id": self.ins1.id,
                    "exercici": 1,
                    "inputs_patch": {"SYNC": 6.4},
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("subject_kind=team_unit", response.json()["error"])

    def test_scoring_media_context_accepts_team_subject(self):
        team_subject, _subject_meta = self._team_subject()
        response = self.client.get(
            reverse("scoring_media_context", kwargs={"pk": self.comp.id}),
            {
                "comp_aparell_id": self.comp_app.id,
                "subject_kind": "team_unit",
                "subject_id": team_subject.id,
                "exercici": 1,
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["subject"]["kind"], "team_unit")
        self.assertEqual(payload["subject"]["id"], team_subject.id)

    def test_judge_video_endpoints_support_team_subjects(self):
        token = JudgeDeviceToken.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            label="Team Video",
            permissions=[{"field_code": "SYNC", "scope": "shared", "judge_index": 1}],
            can_record_video=True,
            is_active=True,
        )
        team_subject, _subject_meta = self._team_subject()
        probe_data = {
            "duration_seconds": 9,
            "mime_type": "video/mp4",
            "format_name": "mp4",
            "video_codec": "h264",
        }

        with patch("competicions_trampoli.views.judge.video._probe_uploaded_video_metadata", return_value=probe_data):
            upload_res = self.client.post(
                reverse("judge_video_upload", kwargs={"token": token.id}),
                data={
                    "subject_kind": "team_unit",
                    "subject_id": team_subject.id,
                    "exercici": 1,
                    "video_file": SimpleUploadedFile("team.mp4", b"\x00" * 1024, content_type="video/mp4"),
                },
            )

        self.assertEqual(upload_res.status_code, 200)
        upload_payload = upload_res.json()
        self.assertTrue(upload_payload["ok"])
        self.assertEqual(upload_payload["subject_kind"], "team_unit")
        self.assertEqual(upload_payload["subject_id"], team_subject.id)

        entry = TeamScoreEntry.objects.get(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            team_subject=team_subject,
            exercici=1,
        )
        self.assertTrue(TeamScoreEntryVideo.objects.filter(team_score_entry=entry).exists())
        self.assertTrue(
            TeamScoreEntryVideoEvent.objects.filter(
                team_score_entry=entry,
                action=TeamScoreEntryVideoEvent.Action.UPLOAD,
                ok=True,
            ).exists()
        )

        status_res = self.client.get(
            reverse("judge_video_status", kwargs={"token": token.id}),
            {"subject_kind": "team_unit", "subject_id": team_subject.id, "exercici": 1},
        )
        self.assertEqual(status_res.status_code, 200)
        self.assertTrue(status_res.json()["has_video"])

        delete_res = self.client.post(
            reverse("judge_video_delete", kwargs={"token": token.id}),
            {"subject_kind": "team_unit", "subject_id": team_subject.id, "exercici": 1},
        )
        self.assertEqual(delete_res.status_code, 200)
        self.assertTrue(delete_res.json()["deleted"])
        self.assertFalse(TeamScoreEntryVideo.objects.filter(team_score_entry=entry).exists())

    def test_scoring_media_context_rejects_ineligible_team_subject(self):
        invalid_team, _members = self._create_team_with_members("Parella incompleta", ["Berta"], start_order=20)
        invalid_team_subject, _invalid_meta = self._team_subject(invalid_team)
        res = self.client.get(
            reverse("scoring_media_context", kwargs={"pk": self.comp.id}),
            {
                "comp_aparell_id": self.comp_app.id,
                "subject_kind": "team_unit",
                "subject_id": invalid_team_subject.id,
                "exercici": 1,
            },
        )
        self.assertEqual(res.status_code, 403)


