from ._shared import *  # noqa: F401,F403


class TeamContextUpdatesAndNotesTests(TeamContextScoringFlowTestBase):
    def test_scoring_updates_include_invalid_team_entries_with_series_state(self):
        invalid_team, _members = self._create_team_with_members("Parella incompleta", ["Berta"], start_order=20)
        team_subject, _subject_meta = self._team_subject()
        invalid_team_subject, _invalid_meta = self._team_subject(invalid_team)
        TeamScoreEntry.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            team_subject=team_subject,
            exercici=1,
            inputs={"SYNC": 5},
            outputs={},
            total=5,
        )
        TeamScoreEntry.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            team_subject=invalid_team_subject,
            exercici=1,
            inputs={"SYNC": 9},
            outputs={},
            total=9,
        )

        res = self.client.get(
            reverse("scoring_updates", kwargs={"pk": self.comp.id}),
            {
                "since": (timezone.now() - timedelta(minutes=10)).isoformat(),
                "comp_aparell_id": self.comp_app.id,
            },
        )
        self.assertEqual(res.status_code, 200)
        updates = res.json().get("updates", [])
        self.assertEqual({u["subject_id"] for u in updates}, {team_subject.id, invalid_team_subject.id})
        by_id = {int(row["subject_id"]): row for row in updates}
        self.assertEqual(by_id[team_subject.id]["series_state"], "unassigned")
        self.assertEqual(by_id[invalid_team_subject.id]["series_state"], "invalid")

    def test_scoring_notes_home_renders_team_schema_without_nameerror(self):
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

        response = self.client.get(reverse("scoring_notes_home", kwargs={"pk": self.comp.id}))

        self.assertEqual(response.status_code, 200)
        schema = response.context["schemas"][str(self.comp_app.id)]
        logical_schema = response.context["logical_schemas"][str(self.comp_app.id)]
        self.assertIn("E__m1", {field["code"] for field in schema["fields"]})
        self.assertIn("E__m2", {field["code"] for field in schema["fields"]})
        self.assertEqual({field["code"] for field in logical_schema["fields"]}, {"SYNC", "E"})

    def test_scoring_notes_home_exposes_scoped_group_apps(self):
        indiv_app = self._create_aparell("IND", "Individual")
        indiv_comp_app = self._create_comp_aparell(self.comp, indiv_app, ordre=2)
        ScoringSchema.objects.create(
            aparell=indiv_app,
            schema={
                "fields": [{"code": "N", "label": "Nota", "type": "number"}],
                "computed": [{"code": "TOTAL", "label": "Total", "formula": "N"}],
            },
        )

        response = self.client.get(reverse("scoring_notes_home", kwargs={"pk": self.comp.id}))

        self.assertEqual(response.status_code, 200)
        groups_render = list(response.context["groups_render"]) + list(response.context["out_of_program_groups_render"])
        individual_groups = [item for item in groups_render if item["kind"] == "individual_group"]
        team_groups = [item for item in groups_render if item["kind"] == "team_bucket"]
        self.assertTrue(any(int(app.id) == indiv_comp_app.id for item in individual_groups for app in item["apps"]))
        self.assertTrue(any(int(app.id) == self.comp_app.id for item in team_groups for app in item["apps"]))
        self.assertFalse(any(int(app.id) == self.comp_app.id for item in individual_groups for app in item["apps"]))

    def test_scoring_notes_home_exposes_canonical_score_keys_and_invalid_teams(self):
        invalid_team, _members = self._create_team_with_members("Parella incompleta", ["Berta"], start_order=20)
        team_subject, _subject_meta = self._team_subject()
        invalid_team_subject, _invalid_meta = self._team_subject(invalid_team)
        TeamScoreEntry.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            team_subject=team_subject,
            exercici=1,
            inputs={"SYNC": 5},
            outputs={},
            total=5,
        )
        response = self.client.get(reverse("scoring_notes_home", kwargs={"pk": self.comp.id}))
        self.assertEqual(response.status_code, 200)
        scores = response.context["scores"]
        self.assertIn(f"team_unit:{team_subject.id}|1|{self.comp_app.id}", scores)
        subjects = {str(item["id"]): item for item in response.context["inscripcions"]}
        self.assertIn(f"team_unit:{invalid_team_subject.id}", subjects)
        self.assertTrue(subjects[f"team_unit:{invalid_team_subject.id}"]["invalid_reasons"])

    def test_scoring_and_judge_updates_include_invalid_team_subjects(self):
        invalid_team, _members = self._create_team_with_members("Parella incompleta", ["Berta"], start_order=20)
        invalid_team_subject, _invalid_meta = self._team_subject(invalid_team)
        TeamScoreEntry.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            team_subject=invalid_team_subject,
            exercici=1,
            inputs={"SYNC": 4.0},
            outputs={},
            total=4.0,
        )

        scoring_res = self.client.get(
            reverse("scoring_updates", kwargs={"pk": self.comp.id}),
            {
                "since": (timezone.now() - timedelta(minutes=10)).isoformat(),
                "comp_aparell_id": self.comp_app.id,
            },
        )
        self.assertEqual(scoring_res.status_code, 200)
        scoring_updates = {int(row["subject_id"]): row for row in scoring_res.json()["updates"]}
        self.assertEqual(scoring_updates[invalid_team_subject.id]["series_state"], "invalid")
        self.assertIsNone(scoring_updates[invalid_team_subject.id]["serie_id"])

        token = JudgeDeviceToken.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            label="Team Judge Invalid Bucket",
            permissions=[{"field_code": "SYNC", "runtime_field_code": "SYNC", "scope": "shared", "judge_index": 1}],
            is_active=True,
        )
        judge_res = self.client.get(
            reverse("judge_updates", kwargs={"token": token.id}),
            {
                "since": (timezone.now() - timedelta(minutes=10)).isoformat(),
                "exercici": 1,
            },
        )
        self.assertEqual(judge_res.status_code, 200)
        judge_updates = {int(row["subject_id"]): row for row in judge_res.json()["updates"]}
        self.assertEqual(judge_updates[invalid_team_subject.id]["series_state"], "invalid")
        self.assertIsNone(judge_updates[invalid_team_subject.id]["serie_id"])

    def test_scoring_updates_without_comp_aparell_id_include_individual_and_team_entries(self):
        ScoringSchema.objects.create(
            aparell=self.app,
            schema={
                "meta": {"subject_mode": "team_context", "expected_team_size": 2},
                "fields": [
                    {"code": "SYNC", "label": "Sync", "type": "number", "scope": "shared"},
                    {"code": "E", "label": "Exec", "type": "number", "scope": "member"},
                ],
                "computed": [
                    {"code": "TOTAL", "label": "Total", "formula": "SYNC"},
                ],
            },
        )
        indiv_app = self._create_aparell("IND-UPD", "Individual updates")
        indiv_comp_app = self._create_comp_aparell(self.comp, indiv_app, ordre=2)
        ScoringSchema.objects.create(
            aparell=indiv_app,
            schema={
                "fields": [{"code": "N", "label": "Nota", "type": "number"}],
                "computed": [{"code": "TOTAL", "label": "Total", "formula": "N"}],
            },
        )

        team_subject, _team_meta = self._team_subject()
        TeamScoreEntry.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            team_subject=team_subject,
            exercici=1,
            inputs={
                "SYNC": 5.0,
                "E": {
                    str(self.ins1.id): 0.2,
                    str(self.ins2.id): 0.3,
                },
            },
            outputs={"TOTAL": 5.0},
            total=5.0,
        )
        ScoreEntry.objects.create(
            competicio=self.comp,
            comp_aparell=indiv_comp_app,
            inscripcio=self.ins1,
            exercici=1,
            inputs={"N": 7.5},
            outputs={"TOTAL": 7.5},
            total=7.5,
        )

        res = self.client.get(
            reverse("scoring_updates", kwargs={"pk": self.comp.id}),
            {"since": (timezone.now() - timedelta(minutes=10)).isoformat()},
        )

        self.assertEqual(res.status_code, 200)
        updates = res.json()["updates"]
        by_kind = {(row["subject_kind"], int(row["subject_id"])): row for row in updates}
        self.assertIn(("inscripcio", self.ins1.id), by_kind)
        self.assertIn(("team_unit", team_subject.id), by_kind)
        self.assertEqual(by_kind[("inscripcio", self.ins1.id)]["comp_aparell_id"], indiv_comp_app.id)
        self.assertEqual(by_kind[("inscripcio", self.ins1.id)]["inputs"], {"N": 7.5})
        self.assertEqual(
            by_kind[("team_unit", team_subject.id)]["inputs"],
            {
                "SYNC": 5.0,
                "E": {
                    str(self.ins1.id): 0.2,
                    str(self.ins2.id): 0.3,
                },
            },
        )
        self.assertEqual(by_kind[("team_unit", team_subject.id)]["comp_aparell_id"], self.comp_app.id)
        self.assertEqual(by_kind[("team_unit", team_subject.id)]["series_state"], "unassigned")

    def test_judge_updates_team_unit_use_after_id_for_same_timestamp(self):
        equip2, _members2 = self._create_team_with_members("Parella 2", ["Nora", "Marta"], start_order=30)
        equip3, _members3 = self._create_team_with_members("Parella 3", ["Jana", "Paula"], start_order=40)
        subject_1, _meta_1 = self._team_subject()
        subject_2, _meta_2 = self._team_subject(equip2)
        subject_3, _meta_3 = self._team_subject(equip3)
        token = JudgeDeviceToken.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            label="Team Judge Cursor",
            permissions=[{"field_code": "SYNC", "runtime_field_code": "SYNC", "scope": "shared", "judge_index": 1}],
            is_active=True,
        )
        base_time = timezone.now()
        e1 = TeamScoreEntry.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            team_subject=subject_1,
            exercici=1,
            inputs={"SYNC": 5},
            outputs={},
            total=5,
        )
        e2 = TeamScoreEntry.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            team_subject=subject_2,
            exercici=1,
            inputs={"SYNC": 6},
            outputs={},
            total=6,
        )
        e3 = TeamScoreEntry.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            team_subject=subject_3,
            exercici=1,
            inputs={"SYNC": 7},
            outputs={},
            total=7,
        )
        TeamScoreEntry.objects.filter(pk__in=[e1.id, e2.id, e3.id]).update(updated_at=base_time)

        url = reverse("judge_updates", kwargs={"token": token.id})
        with patch("competicions_trampoli.views.judge.updates.JUDGE_UPDATES_LIMIT", 2):
            first_res = self.client.get(url, {"since": (base_time - timedelta(seconds=1)).isoformat(), "exercici": 1})
            self.assertEqual(first_res.status_code, 200)
            first_body = first_res.json()
            self.assertTrue(first_body.get("has_more"))
            self.assertEqual(
                [int(row["subject_id"]) for row in first_body.get("updates", [])],
                [subject_1.id, subject_2.id],
            )

            second_res = self.client.get(
                url,
                {
                    "since": first_body.get("next_since"),
                    "after_id": first_body.get("next_after_id"),
                    "exercici": 1,
                },
            )

        self.assertEqual(second_res.status_code, 200)
        self.assertEqual(
            [int(row["subject_id"]) for row in second_res.json().get("updates", [])],
            [subject_3.id],
        )

    def test_scoring_updates_combined_cursor_orders_individual_before_team_for_same_timestamp(self):
        indiv_app = self._create_aparell("IND-CURSOR", "Individual cursor")
        indiv_comp_app = self._create_comp_aparell(self.comp, indiv_app, ordre=2)
        equip2, _members2 = self._create_team_with_members("Parella 2", ["Nora", "Marta"], start_order=30)
        subject_1, _meta_1 = self._team_subject()
        subject_2, _meta_2 = self._team_subject(equip2)
        base_time = timezone.now()
        score_entry = ScoreEntry.objects.create(
            competicio=self.comp,
            comp_aparell=indiv_comp_app,
            inscripcio=self.ins1,
            exercici=1,
            inputs={"N": 7.5},
            outputs={"TOTAL": 7.5},
            total=7.5,
        )
        team_entry_1 = TeamScoreEntry.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            team_subject=subject_1,
            exercici=1,
            inputs={"SYNC": 5},
            outputs={},
            total=5,
        )
        team_entry_2 = TeamScoreEntry.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            team_subject=subject_2,
            exercici=1,
            inputs={"SYNC": 6},
            outputs={},
            total=6,
        )
        ScoreEntry.objects.filter(pk=score_entry.id).update(updated_at=base_time)
        TeamScoreEntry.objects.filter(pk__in=[team_entry_1.id, team_entry_2.id]).update(updated_at=base_time)

        url = reverse("scoring_updates", kwargs={"pk": self.comp.id})
        with patch("competicions_trampoli.views.scoring.updates.SCORING_UPDATES_LIMIT", 2):
            first_res = self.client.get(url, {"since": (base_time - timedelta(seconds=1)).isoformat()})
            self.assertEqual(first_res.status_code, 200)
            first_body = first_res.json()
            self.assertTrue(first_body.get("has_more"))
            self.assertEqual(
                [(row["subject_kind"], int(row["subject_id"])) for row in first_body.get("updates", [])],
                [("inscripcio", self.ins1.id), ("team_unit", subject_1.id)],
            )
            self.assertEqual(first_body.get("next_after_id"), f"team:{team_entry_1.id}")

            second_res = self.client.get(
                url,
                {
                    "since": first_body.get("next_since"),
                    "after_id": first_body.get("next_after_id"),
                },
            )

        self.assertEqual(second_res.status_code, 200)
        self.assertEqual(
            [(row["subject_kind"], int(row["subject_id"])) for row in second_res.json().get("updates", [])],
            [("team_unit", subject_2.id)],
        )

    def test_scoring_updates_group_filter_keeps_team_rows_and_filters_individual_rows(self):
        indiv_app = self._create_aparell("IND-GROUP", "Individual group")
        indiv_comp_app = self._create_comp_aparell(self.comp, indiv_app, ordre=2)
        team_subject, _team_meta = self._team_subject()
        other_group_ins = self._create_inscripcio(self.comp, "Berta grup 2", ordre=50, grup=2)

        TeamScoreEntry.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            team_subject=team_subject,
            exercici=1,
            inputs={"SYNC": 5.0},
            outputs={},
            total=5.0,
        )
        ScoreEntry.objects.create(
            competicio=self.comp,
            comp_aparell=indiv_comp_app,
            inscripcio=self.ins1,
            exercici=1,
            inputs={"N": 7.5},
            outputs={"TOTAL": 7.5},
            total=7.5,
        )
        ScoreEntry.objects.create(
            competicio=self.comp,
            comp_aparell=indiv_comp_app,
            inscripcio=other_group_ins,
            exercici=1,
            inputs={"N": 6.5},
            outputs={"TOTAL": 6.5},
            total=6.5,
        )

        res = self.client.get(
            reverse("scoring_updates", kwargs={"pk": self.comp.id}),
            {
                "since": (timezone.now() - timedelta(minutes=10)).isoformat(),
                "group": self.ins1.grup_competicio_id,
            },
        )

        self.assertEqual(res.status_code, 200)
        updates = {(row["subject_kind"], int(row["subject_id"])): row for row in res.json()["updates"]}
        self.assertIn(("inscripcio", self.ins1.id), updates)
        self.assertNotIn(("inscripcio", other_group_ins.id), updates)
        self.assertIn(("team_unit", team_subject.id), updates)


