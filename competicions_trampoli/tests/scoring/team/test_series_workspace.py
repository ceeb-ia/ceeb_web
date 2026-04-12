from ._shared import *  # noqa: F401,F403


class TeamSeriesWorkspaceTests(TeamContextScoringFlowTestBase):
    def test_inscripcions_list_exposes_series_panel_navigation(self):
        response = self.client.get(reverse("inscripcions_list", kwargs={"pk": self.comp.id}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-panel-target="series-equips"')
        self.assertContains(response, 'id="panel-series-equips"')
        self.assertContains(response, 'data-panel-lazy="1"')
        self.assertNotContains(response, 'id="series-workspace-shell"')

    def test_series_panel_fragment_renders_workspace_shell_and_inspector(self):
        response = self.client.get(
            reverse("inscripcions_list", kwargs={"pk": self.comp.id}),
            {"__fragments": "panel", "__panel_key": "series-equips"},
        )

        self.assertEqual(response.status_code, 200)
        html = response.json()["fragments"]["panel"]["html"]
        self.assertIn('id="series-workspace-shell"', html)
        self.assertIn("1. Filtra l'univers", html)
        self.assertIn("2. Aplica una operacio", html)
        self.assertIn("3. Revisa l'impacte", html)
        self.assertIn('id="series-right-pane-card"', html)
        self.assertIn('id="btn-series-right-tab-preview"', html)
        self.assertIn('id="series-board-filters-panel"', html)

    def test_series_preview_signature_is_required_for_selection_actions(self):
        equip2, _members2 = self._create_team_with_members("Parella 2", ["Nora", "Marta"], start_order=30)
        subject_1, _meta_1 = self._team_subject()
        subject_2, _meta_2 = self._team_subject(equip2)
        serie = SerieEquip.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            display_num=1,
            nom="Serie A",
        )
        SerieEquipItem.objects.create(serie=serie, team_subject=subject_1, ordre=1)

        preview_res = self._post_json(
            "inscripcions_series_equips_preview",
            {
                "comp_aparell_id": self.comp_app.id,
                "action": "assign",
                "serie_id": serie.id,
                "selected_ids": [subject_2.id],
            },
        )
        self.assertEqual(preview_res.status_code, 200)
        plan_signature = preview_res.json()["preview"]["plan_signature"]

        missing_signature_res = self._post_json(
            "inscripcions_series_equips_assign",
            {
                "comp_aparell_id": self.comp_app.id,
                "serie_id": serie.id,
                "selected_ids": [subject_2.id],
            },
        )
        self.assertEqual(missing_signature_res.status_code, 400)

        stale_signature_res = self._post_json(
            "inscripcions_series_equips_assign",
            {
                "comp_aparell_id": self.comp_app.id,
                "serie_id": serie.id,
                "selected_ids": [subject_2.id],
                "plan_signature": "stale-signature",
            },
        )
        self.assertEqual(stale_signature_res.status_code, 400)

        assign_res = self._post_json(
            "inscripcions_series_equips_assign",
            {
                "comp_aparell_id": self.comp_app.id,
                "serie_id": serie.id,
                "selected_ids": [subject_2.id],
                "plan_signature": plan_signature,
            },
        )
        self.assertEqual(assign_res.status_code, 200)

    def test_series_preview_returns_rich_workspace_payload(self):
        equip2, _members2 = self._create_team_with_members("Parella 2", ["Nora", "Marta"], start_order=30)
        equip3, _members3 = self._create_team_with_members("Parella 3", ["Jana", "Paula"], start_order=40)
        subject_1, _meta_1 = self._team_subject()
        subject_2, _meta_2 = self._team_subject(equip2)
        subject_3, _meta_3 = self._team_subject(equip3)

        serie_a = SerieEquip.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            display_num=1,
            nom="Serie A",
        )
        SerieEquipItem.objects.create(serie=serie_a, team_subject=subject_1, ordre=1)
        empty_serie = SerieEquip.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            display_num=2,
            nom="Serie Buida",
        )

        create_preview = self._post_json(
            "inscripcions_series_equips_preview",
            {
                "comp_aparell_id": self.comp_app.id,
                "action": "create",
                "name": "Serie Nova",
                "selected_ids": [subject_2.id],
            },
        ).json()["preview"]
        self.assertTrue(create_preview["can_run"])
        self.assertFalse(create_preview["blocked"])
        self.assertIn("selection", create_preview)
        self.assertIn("summary", create_preview)
        self.assertIn("existing_series", create_preview)
        self.assertIn("planned_series", create_preview)
        self.assertEqual(create_preview["selection"]["count"], 1)
        self.assertEqual(create_preview["summary"]["planned_series_total"], 1)
        self.assertTrue(create_preview["planned_series"][0]["will_create"])
        self.assertEqual(create_preview["planned_series"][0]["subjects"][0]["subject_kind"], "team_unit")

        assign_preview = self._post_json(
            "inscripcions_series_equips_preview",
            {
                "comp_aparell_id": self.comp_app.id,
                "action": "assign",
                "serie_id": serie_a.id,
                "selected_ids": [subject_2.id],
            },
        ).json()["preview"]
        self.assertTrue(assign_preview["can_run"])
        self.assertFalse(assign_preview["blocked"])
        self.assertEqual(assign_preview["selection"]["count"], 1)
        self.assertEqual(assign_preview["summary"]["existing_series_total"], 1)
        self.assertEqual(assign_preview["planned_series"][0]["id"], serie_a.id)
        self.assertEqual(assign_preview["planned_series"][0]["incoming_count"], 1)

        unassign_preview = self._post_json(
            "inscripcions_series_equips_preview",
            {
                "comp_aparell_id": self.comp_app.id,
                "action": "unassign",
                "selected_ids": [subject_1.id],
            },
        ).json()["preview"]
        self.assertTrue(unassign_preview["can_run"])
        self.assertFalse(unassign_preview["blocked"])
        self.assertEqual(unassign_preview["selection"]["assigned_count"], 1)
        self.assertEqual(unassign_preview["existing_series"][0]["id"], serie_a.id)
        self.assertEqual(unassign_preview["planned_series"][0]["outgoing_count"], 1)

        delete_preview = self._post_json(
            "inscripcions_series_equips_preview",
            {
                "comp_aparell_id": self.comp_app.id,
                "action": "delete",
                "serie_id": empty_serie.id,
                "selected_ids": [subject_3.id],
            },
        ).json()["preview"]
        self.assertTrue(delete_preview["can_run"])
        self.assertFalse(delete_preview["blocked"])
        self.assertEqual(delete_preview["existing_series"][0]["id"], empty_serie.id)
        self.assertTrue(delete_preview["planned_series"][0]["will_delete"])
        self.assertEqual(delete_preview["blocked_reasons"], [])

    def test_series_delete_is_blocked_while_programmed(self):
        serie = SerieEquip.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            display_num=1,
            nom="Serie Buida",
        )
        franja = RotacioFranja.objects.create(
            competicio=self.comp,
            hora_inici=timezone.datetime(2025, 1, 1, 9, 0).time(),
            hora_fi=timezone.datetime(2025, 1, 1, 10, 0).time(),
            ordre=1,
            titol="Franja 1",
        )
        estacio = RotacioEstacio.objects.create(
            competicio=self.comp,
            tipus="aparell",
            comp_aparell=self.comp_app,
            ordre=1,
        )
        assignacio = RotacioAssignacio.objects.create(
            competicio=self.comp,
            franja=franja,
            estacio=estacio,
        )
        RotacioAssignacioSerieEquip.objects.create(assignacio=assignacio, serie=serie, ordre=1)

        preview_res = self._post_json(
            "inscripcions_series_equips_preview",
            {
                "comp_aparell_id": self.comp_app.id,
                "action": "delete",
                "serie_id": serie.id,
            },
        )
        self.assertEqual(preview_res.status_code, 200)
        preview = preview_res.json()["preview"]
        self.assertFalse(preview["can_run"])
        self.assertTrue(preview["blocked"])
        self.assertEqual(preview["reason"], "serie_programmed")
        self.assertTrue(preview["blocked_reasons"])
        self.assertEqual(preview["existing_series"][0]["id"], serie.id)
        self.assertEqual(preview["planned_series"], [])

        ok, reason = safe_deactivate_empty_serie(serie)
        self.assertFalse(ok)
        self.assertEqual(reason, "serie_programmed")

    def test_series_workspace_respects_persistent_order_and_hides_inactive_series(self):
        equip2, _members2 = self._create_team_with_members("Parella 2", ["Nora", "Marta"], start_order=30)
        equip3, _members3 = self._create_team_with_members("Parella 3", ["Jana", "Paula"], start_order=40)
        subject_1, _meta_1 = self._team_subject()
        subject_2, _meta_2 = self._team_subject(equip2)
        subject_3, _meta_3 = self._team_subject(equip3)

        create_preview_res = self._post_json(
            "inscripcions_series_equips_preview",
            {
                "comp_aparell_id": self.comp_app.id,
                "action": "create",
                "name": "Serie Alpha",
                "selected_ids": [subject_1.id, subject_2.id, subject_3.id],
            },
        )
        self.assertEqual(create_preview_res.status_code, 200)
        create_plan_signature = create_preview_res.json()["preview"]["plan_signature"]

        create_res = self._post_json(
            "inscripcions_series_equips_create",
            {
                "comp_aparell_id": self.comp_app.id,
                "name": "Serie Alpha",
                "selected_ids": [subject_1.id, subject_2.id, subject_3.id],
                "plan_signature": create_plan_signature,
            },
        )
        self.assertEqual(create_res.status_code, 200)
        serie = SerieEquip.objects.get(pk=create_res.json()["serie_id"])

        reorder_res = self._post_json(
            "inscripcions_series_equips_reorder",
            {
                "comp_aparell_id": self.comp_app.id,
                "serie_id": serie.id,
                "subject_ids": [subject_3.id, subject_1.id, subject_2.id],
            },
        )
        self.assertEqual(reorder_res.status_code, 200)

        empty_res = self._post_json(
            "inscripcions_series_equips_create",
            {
                "comp_aparell_id": self.comp_app.id,
                "name": "Serie Buida",
                "selected_ids": [],
            },
        )
        self.assertEqual(empty_res.status_code, 200)
        empty_serie_id = empty_res.json()["serie_id"]
        delete_preview_res = self._post_json(
            "inscripcions_series_equips_preview",
            {
                "comp_aparell_id": self.comp_app.id,
                "action": "delete",
                "serie_id": empty_serie_id,
            },
        )
        self.assertEqual(delete_preview_res.status_code, 200)
        delete_plan_signature = delete_preview_res.json()["preview"]["plan_signature"]
        delete_res = self._post_json(
            "inscripcions_series_equips_delete",
            {
                "comp_aparell_id": self.comp_app.id,
                "serie_id": empty_serie_id,
                "plan_signature": delete_plan_signature,
            },
        )
        self.assertEqual(delete_res.status_code, 200)

        workspace_res = self._post_json(
            "inscripcions_series_equips_workspace",
            {"comp_aparell_id": self.comp_app.id},
        )
        self.assertEqual(workspace_res.status_code, 200)
        workspace = workspace_res.json()["workspace"]
        self.assertEqual([row["id"] for row in workspace["series"]], [serie.id])
        self.assertEqual(
            [row["subject_id"] for row in workspace["series"][0]["subjects"]],
            [subject_3.id, subject_1.id, subject_2.id],
        )
        self.assertFalse(SerieEquip.objects.get(pk=empty_serie_id).actiu)

    def test_series_workspace_and_detail_include_compact_fields(self):
        equip2, _members2 = self._create_team_with_members("Parella 2", ["Nora", "Marta"], start_order=30)
        subject_1, _meta_1 = self._team_subject()
        subject_2, _meta_2 = self._team_subject(equip2)
        serie = SerieEquip.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            display_num=1,
            nom="Serie Compacta",
        )
        SerieEquipItem.objects.create(serie=serie, team_subject=subject_2, ordre=1)

        workspace_res = self._post_json(
            "inscripcions_series_equips_workspace",
            {"comp_aparell_id": self.comp_app.id},
        )
        self.assertEqual(workspace_res.status_code, 200)
        workspace = workspace_res.json()["workspace"]

        candidate = next(row for row in workspace["candidates"]["items"] if row["subject_id"] == subject_2.id)
        self.assertEqual(candidate["members_count"], 2)
        self.assertEqual(candidate["members_preview"], "Nora + Marta")
        self.assertIn("2 membres", candidate["compact_meta"])

        serie_row = workspace["series"][0]
        self.assertEqual(serie_row["summary_label"], "Serie Compacta · 1 unitat · no programada")
        self.assertEqual(serie_row["subjects"][0]["members_preview"], "Nora + Marta")
        self.assertEqual(serie_row["subjects"][0]["members_count"], 2)

        detail_res = self._post_json(
            "inscripcions_series_equips_detail",
            {"comp_aparell_id": self.comp_app.id, "serie_id": serie.id},
        )
        self.assertEqual(detail_res.status_code, 200)
        detail = detail_res.json()["serie"]
        self.assertEqual(detail["summary_label"], "Serie Compacta · 1 unitat · no programada")
        self.assertEqual(detail["subjects"][0]["members_preview"], "Nora + Marta")
        self.assertEqual(detail["subjects"][0]["members_count"], 2)

    def test_series_assignment_moves_subject_between_active_series(self):
        subject_1, _meta_1 = self._team_subject()
        serie_a = SerieEquip.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            display_num=1,
            nom="Serie A",
        )
        serie_b = SerieEquip.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            display_num=2,
            nom="Serie B",
        )
        SerieEquipItem.objects.create(serie=serie_a, team_subject=subject_1, ordre=1)

        preview_res = self._post_json(
            "inscripcions_series_equips_preview",
            {
                "comp_aparell_id": self.comp_app.id,
                "action": "assign",
                "serie_id": serie_b.id,
                "selected_ids": [subject_1.id],
            },
        )
        self.assertEqual(preview_res.status_code, 200)
        plan_signature = preview_res.json()["preview"]["plan_signature"]

        assign_res = self._post_json(
            "inscripcions_series_equips_assign",
            {
                "comp_aparell_id": self.comp_app.id,
                "serie_id": serie_b.id,
                "selected_ids": [subject_1.id],
                "plan_signature": plan_signature,
            },
        )
        self.assertEqual(assign_res.status_code, 200)
        self.assertFalse(SerieEquipItem.objects.filter(serie=serie_a, team_subject=subject_1).exists())
        self.assertTrue(SerieEquipItem.objects.filter(serie=serie_b, team_subject=subject_1).exists())
        self.assertEqual(SerieEquipItem.objects.filter(team_subject=subject_1).count(), 1)

    def test_series_preview_updates_and_exports_use_team_unit_contract(self):
        equip2, _members2 = self._create_team_with_members("Parella 2", ["Nora", "Marta"], start_order=30)
        subject_1, _meta_1 = self._team_subject()
        subject_2, _meta_2 = self._team_subject(equip2)
        serie = SerieEquip.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            display_num=1,
            nom="Serie A",
        )
        SerieEquipItem.objects.create(serie=serie, team_subject=subject_1, ordre=1)

        preview_res = self._post_json(
            "inscripcions_series_equips_preview",
            {
                "comp_aparell_id": self.comp_app.id,
                "action": "assign",
                "serie_id": serie.id,
                "selected_ids": [subject_2.id],
            },
        )
        self.assertEqual(preview_res.status_code, 200)
        self.assertTrue(preview_res.json()["preview"]["can_run"])
        self.assertTrue(preview_res.json()["preview"]["plan_signature"])

        TeamScoreEntry.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            team_subject=subject_1,
            exercici=1,
            inputs={"SYNC": 5},
            outputs={},
            total=5,
        )
        TeamScoreEntry.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            team_subject=subject_2,
            exercici=1,
            inputs={"SYNC": 7},
            outputs={},
            total=7,
        )

        scoring_res = self.client.get(
            reverse("scoring_updates", kwargs={"pk": self.comp.id}),
            {
                "since": (timezone.now() - timedelta(minutes=10)).isoformat(),
                "comp_aparell_id": self.comp_app.id,
                "serie_id": serie.id,
            },
        )
        self.assertEqual(scoring_res.status_code, 200)
        scoring_updates = scoring_res.json()["updates"]
        self.assertEqual({row["subject_kind"] for row in scoring_updates}, {"team_unit"})
        self.assertEqual({row["subject_id"] for row in scoring_updates}, {subject_1.id})
        self.assertEqual(scoring_updates[0]["serie_id"], serie.id)
        self.assertEqual(scoring_updates[0]["series_state"], "assigned")

        token = JudgeDeviceToken.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            label="Team Judge Series",
            permissions=[{"field_code": "SYNC", "runtime_field_code": "SYNC", "scope": "shared", "judge_index": 1}],
            is_active=True,
        )
        judge_res = self.client.get(
            reverse("judge_updates", kwargs={"token": token.id}),
            {
                "since": (timezone.now() - timedelta(minutes=10)).isoformat(),
                "exercici": 1,
                "serie_id": serie.id,
            },
        )
        self.assertEqual(judge_res.status_code, 200)
        judge_updates = judge_res.json()["updates"]
        self.assertEqual({row["subject_kind"] for row in judge_updates}, {"team_unit"})
        self.assertEqual({row["subject_id"] for row in judge_updates}, {subject_1.id})
        self.assertEqual(judge_updates[0]["serie_id"], serie.id)
        self.assertEqual(judge_updates[0]["series_state"], "assigned")

        start_list_res = self.client.get(
            reverse("inscripcions_series_equips_start_list_export", kwargs={"pk": self.comp.id}),
            {"comp_aparell_id": self.comp_app.id},
        )
        self.assertEqual(start_list_res.status_code, 200)
        self.assertIn("series_start_list", start_list_res["Content-Disposition"])

        work_sheet_res = self.client.get(
            reverse("inscripcions_series_equips_work_sheet_export", kwargs={"pk": self.comp.id}),
            {"comp_aparell_id": self.comp_app.id, "serie_id": serie.id},
        )
        self.assertEqual(work_sheet_res.status_code, 200)
        self.assertIn("serie_work_sheet", work_sheet_res["Content-Disposition"])
        workbook = load_workbook(BytesIO(work_sheet_res.content))
        ws = workbook.active
        values = [row[1] for row in ws.iter_rows(min_row=4, values_only=True) if row and row[1]]
        self.assertEqual(values[:1], [subject_1.label])

    def test_series_assign_requires_preview_signature(self):
        subject_1, _meta_1 = self._team_subject()
        equip2, _members2 = self._create_team_with_members("Parella 2", ["Nora", "Marta"], start_order=30)
        subject_2, _meta_2 = self._team_subject(equip2)
        serie = SerieEquip.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            display_num=1,
            nom="Serie A",
        )
        SerieEquipItem.objects.create(serie=serie, team_subject=subject_1, ordre=1)

        missing_preview_res = self._post_json(
            "inscripcions_series_equips_assign",
            {
                "comp_aparell_id": self.comp_app.id,
                "serie_id": serie.id,
                "selected_ids": [subject_2.id],
            },
        )
        self.assertEqual(missing_preview_res.status_code, 400)
        self.assertContains(missing_preview_res, "preview required", status_code=400)

        preview_res = self._post_json(
            "inscripcions_series_equips_preview",
            {
                "comp_aparell_id": self.comp_app.id,
                "action": "assign",
                "serie_id": serie.id,
                "selected_ids": [subject_2.id],
            },
        )
        self.assertEqual(preview_res.status_code, 200)
        plan_signature = preview_res.json()["preview"]["plan_signature"]

        assign_res = self._post_json(
            "inscripcions_series_equips_assign",
            {
                "comp_aparell_id": self.comp_app.id,
                "serie_id": serie.id,
                "selected_ids": [subject_2.id],
                "plan_signature": plan_signature,
            },
        )
        self.assertEqual(assign_res.status_code, 200)
        self.assertTrue(SerieEquipItem.objects.filter(serie=serie, team_subject=subject_2).exists())

    def test_series_delete_blocks_programmed_empty_serie(self):
        serie = SerieEquip.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            display_num=1,
            nom="Serie Programada",
        )
        franja = RotacioFranja.objects.create(
            competicio=self.comp,
            hora_inici=timezone.datetime(2025, 1, 1, 9, 0).time(),
            hora_fi=timezone.datetime(2025, 1, 1, 10, 0).time(),
            ordre=1,
            titol="Franja 1",
        )
        estacio = RotacioEstacio.objects.create(
            competicio=self.comp,
            tipus="aparell",
            comp_aparell=self.comp_app,
            ordre=1,
        )
        save_res = self._post_json(
            "rotacions_save",
            {
                "cells": [
                    {
                        "franja": franja.id,
                        "estacio": estacio.id,
                        "items": [f"s:{serie.id}"],
                    }
                ],
            },
        )
        self.assertEqual(save_res.status_code, 200)

        preview_res = self._post_json(
            "inscripcions_series_equips_preview",
            {
                "comp_aparell_id": self.comp_app.id,
                "action": "delete",
                "serie_id": serie.id,
            },
        )
        self.assertEqual(preview_res.status_code, 200)
        preview = preview_res.json()["preview"]
        self.assertFalse(preview["can_run"])
        self.assertEqual(preview["reason"], "serie_programmed")

        delete_res = self._post_json(
            "inscripcions_series_equips_delete",
            {
                "comp_aparell_id": self.comp_app.id,
                "serie_id": serie.id,
                "plan_signature": preview["plan_signature"],
            },
        )
        self.assertEqual(delete_res.status_code, 400)
        self.assertContains(delete_res, "serie programmed", status_code=400)
        self.assertTrue(SerieEquip.objects.get(pk=serie.id).actiu)

    def test_series_delete_empty_deactivates_only_unprogrammed_empty_series(self):
        equip2, _members2 = self._create_team_with_members("Parella 2", ["Nora", "Marta"], start_order=30)
        subject_1, _meta_1 = self._team_subject()
        _subject_2, _meta_2 = self._team_subject(equip2)

        non_empty = SerieEquip.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            display_num=1,
            nom="Serie amb contingut",
        )
        SerieEquipItem.objects.create(serie=non_empty, team_subject=subject_1, ordre=1)

        empty = SerieEquip.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            display_num=2,
            nom="Serie buida",
        )
        programmed_empty = SerieEquip.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            display_num=3,
            nom="Serie programada buida",
        )

        franja = RotacioFranja.objects.create(
            competicio=self.comp,
            hora_inici=timezone.datetime(2025, 1, 1, 9, 0).time(),
            hora_fi=timezone.datetime(2025, 1, 1, 10, 0).time(),
            ordre=1,
            titol="Franja 1",
        )
        estacio = RotacioEstacio.objects.create(
            competicio=self.comp,
            tipus="aparell",
            comp_aparell=self.comp_app,
            ordre=1,
        )
        assignacio = RotacioAssignacio.objects.create(
            competicio=self.comp,
            franja=franja,
            estacio=estacio,
        )
        RotacioAssignacioSerieEquip.objects.create(assignacio=assignacio, serie=programmed_empty, ordre=1)

        response = self._post_json(
            "inscripcions_series_equips_delete_empty",
            {"comp_aparell_id": self.comp_app.id},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data.get("ok"))
        self.assertEqual(data.get("deleted"), 1)
        self.assertIn(programmed_empty.id, data.get("skipped_programmed_ids", []))
        self.assertIn(non_empty.id, data.get("skipped_not_empty_ids", []))

        empty.refresh_from_db()
        programmed_empty.refresh_from_db()
        non_empty.refresh_from_db()
        self.assertFalse(empty.actiu)
        self.assertTrue(programmed_empty.actiu)
        self.assertTrue(non_empty.actiu)

    def test_series_start_list_export_includes_unassigned_bucket_and_persistent_order(self):
        equip2, _members2 = self._create_team_with_members("Parella 2", ["Nora", "Marta"], start_order=30)
        equip3, _members3 = self._create_team_with_members("Parella 3", ["Jana", "Paula"], start_order=40)
        subject_1, meta_1 = self._team_subject()
        subject_2, meta_2 = self._team_subject(equip2)
        subject_3, meta_3 = self._team_subject(equip3)

        create_preview_res = self._post_json(
            "inscripcions_series_equips_preview",
            {
                "comp_aparell_id": self.comp_app.id,
                "action": "create",
                "name": "Serie Export",
                "selected_ids": [subject_1.id, subject_2.id],
            },
        )
        self.assertEqual(create_preview_res.status_code, 200)
        create_plan_signature = create_preview_res.json()["preview"]["plan_signature"]
        create_res = self._post_json(
            "inscripcions_series_equips_create",
            {
                "comp_aparell_id": self.comp_app.id,
                "name": "Serie Export",
                "selected_ids": [subject_1.id, subject_2.id],
                "plan_signature": create_plan_signature,
            },
        )
        self.assertEqual(create_res.status_code, 200)
        serie = SerieEquip.objects.get(pk=create_res.json()["serie_id"])

        reorder_res = self._post_json(
            "inscripcions_series_equips_reorder",
            {
                "comp_aparell_id": self.comp_app.id,
                "serie_id": serie.id,
                "subject_ids": [subject_2.id, subject_1.id],
            },
        )
        self.assertEqual(reorder_res.status_code, 200)

        start_list_res = self.client.get(
            reverse("inscripcions_series_equips_start_list_export", kwargs={"pk": self.comp.id}),
            {"comp_aparell_id": self.comp_app.id},
        )
        self.assertEqual(start_list_res.status_code, 200)
        workbook = load_workbook(BytesIO(start_list_res.content))
        ws = workbook.active
        rows = list(ws.iter_rows(values_only=True))

        serie_title_idx = next(idx for idx, row in enumerate(rows) if row and row[0] == "Serie Export")
        self.assertEqual(rows[serie_title_idx + 2][1], meta_2["name"])
        self.assertEqual(rows[serie_title_idx + 3][1], meta_1["name"])

        unassigned_title_idx = next(idx for idx, row in enumerate(rows) if row and row[0] == "Sense serie")
        self.assertEqual(rows[unassigned_title_idx + 2][1], meta_3["name"])


