from ._shared import *  # noqa: F401,F403


class TeamContextBirthPartitionsTests(TeamContextScoringFlowTestBase):
    def test_compute_classificacio_derived_team_birth_partition_uses_oldest_member_and_strict_rule(self):
        self.comp.data = date(2025, 5, 10)
        self.comp.save(update_fields=["data"])
        ind_app = self._create_aparell("TRA", "Tramp")
        comp_ind_app = self._create_comp_aparell(self.comp, ind_app, ordre=2)
        equip_2, members_2 = self._create_team_with_members("Parella 2", ["Nora", "Marta"], start_order=20)

        self.ins1.data_naixement = date(2012, 6, 1)
        self.ins2.data_naixement = date(2016, 6, 1)
        self.ins1.save(update_fields=["data_naixement"])
        self.ins2.save(update_fields=["data_naixement"])
        members_2[0].data_naixement = date(2012, 7, 1)
        members_2[1].data_naixement = date(2013, 7, 1)
        members_2[0].save(update_fields=["data_naixement"])
        members_2[1].save(update_fields=["data_naixement"])

        for ins, total in (
            (self.ins1, 8.0),
            (self.ins2, 7.0),
            (members_2[0], 9.0),
            (members_2[1], 6.0),
        ):
            ScoreEntry.objects.create(
                competicio=self.comp,
                comp_aparell=comp_ind_app,
                inscripcio=ins,
                exercici=1,
                inputs={},
                outputs={},
                total=total,
            )

        schema = {
            **self._birth_range_partition_cfg(compliance_mode="strict"),
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
        }
        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Teams by birth range",
            activa=True,
            ordre=1,
            tipus="equips",
            schema=schema,
        )

        out = compute_classificacio(self.comp, cfg)

        self.assertEqual(out["any_naixement_forquilla:U13"][0]["participant"], "Parella 2")
        self.assertEqual(out["any_naixement_forquilla:Fora de forquilla"][0]["participant"], "Parella 1")

    def test_compute_classificacio_derived_team_birth_partition_allow_outside_n(self):
        self.comp.data = date(2025, 5, 10)
        self.comp.save(update_fields=["data"])
        ind_app = self._create_aparell("DMT", "Dmt")
        comp_ind_app = self._create_comp_aparell(self.comp, ind_app, ordre=2)

        self.ins1.data_naixement = date(2012, 6, 1)
        self.ins2.data_naixement = date(2016, 6, 1)
        self.ins1.save(update_fields=["data_naixement"])
        self.ins2.save(update_fields=["data_naixement"])

        for ins, total in (
            (self.ins1, 8.0),
            (self.ins2, 7.0),
        ):
            ScoreEntry.objects.create(
                competicio=self.comp,
                comp_aparell=comp_ind_app,
                inscripcio=ins,
                exercici=1,
                inputs={},
                outputs={},
                total=total,
            )

        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Teams by birth range allow one outside",
            activa=True,
            ordre=1,
            tipus="equips",
            schema={
                **self._birth_range_partition_cfg(compliance_mode="allow_outside_n", max_outside=1),
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

        out = compute_classificacio(self.comp, cfg)

        self.assertEqual([row["participant"] for row in out["any_naixement_forquilla:U13"]], ["Parella 1"])
        self.assertNotIn("any_naixement_forquilla:Fora de forquilla", out)

    def test_compute_classificacio_native_team_birth_partition_uses_team_members(self):
        self.comp.data = date(2025, 5, 10)
        self.comp.save(update_fields=["data"])
        equip_2, members_2 = self._create_team_with_members("Parella 2", ["Nora", "Marta"], start_order=20)

        self.ins1.data_naixement = date(2012, 6, 1)
        self.ins2.data_naixement = date(2016, 6, 1)
        self.ins1.save(update_fields=["data_naixement"])
        self.ins2.save(update_fields=["data_naixement"])
        members_2[0].data_naixement = date(2012, 7, 1)
        members_2[1].data_naixement = date(2013, 7, 1)
        members_2[0].save(update_fields=["data_naixement"])
        members_2[1].save(update_fields=["data_naixement"])

        team_subject_1, _meta_1 = self._team_subject(self.equip)
        team_subject_2, _meta_2 = self._team_subject(equip_2)
        TeamScoreEntry.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            team_subject=team_subject_1,
            exercici=1,
            inputs={},
            outputs={},
            total=30,
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

        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Native teams by birth range",
            activa=True,
            ordre=1,
            tipus="equips",
            schema={
                **self._birth_range_partition_cfg(compliance_mode="strict"),
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

        out = compute_classificacio(self.comp, cfg)

        self.assertEqual(out["any_naixement_forquilla:U13"][0]["participant"], "Parella 2")
        self.assertEqual(out["any_naixement_forquilla:Fora de forquilla"][0]["participant"], "Parella 1")

    def test_compute_classificacio_native_team_birth_partition_dedupes_member_ids(self):
        self.comp.data = date(2025, 5, 10)
        self.comp.save(update_fields=["data"])
        equip_2, members_2 = self._create_team_with_members("Parella 2", ["Nora", "Marta"], start_order=20)

        self.ins1.data_naixement = date(2012, 6, 1)
        self.ins2.data_naixement = date(2016, 6, 1)
        self.ins1.save(update_fields=["data_naixement"])
        self.ins2.save(update_fields=["data_naixement"])
        members_2[0].data_naixement = date(2012, 7, 1)
        members_2[1].data_naixement = date(2013, 7, 1)
        members_2[0].save(update_fields=["data_naixement"])
        members_2[1].save(update_fields=["data_naixement"])

        team_subject_1, _meta_1 = self._team_subject(self.equip)
        team_subject_2, _meta_2 = self._team_subject(equip_2)
        team_subject_1.member_ids = [self.ins1.id, self.ins2.id, self.ins2.id]
        team_subject_1.save(update_fields=["member_ids"])

        TeamScoreEntry.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            team_subject=team_subject_1,
            exercici=1,
            inputs={},
            outputs={},
            total=30,
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

        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Native teams by birth range deduped members",
            activa=True,
            ordre=1,
            tipus="equips",
            schema={
                **self._birth_range_partition_cfg(compliance_mode="allow_outside_n", max_outside=1),
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

        out = compute_classificacio(self.comp, cfg)

        self.assertEqual(
            [row["participant"] for row in out["any_naixement_forquilla:U13"]],
            ["Parella 1", "Parella 2"],
        )
        self.assertNotIn("any_naixement_forquilla:Fora de forquilla", out)

    def test_classificacio_save_normalizes_legacy_team_age_partition_to_birth_range(self):
        self.comp.data = date(2025, 5, 10)
        self.comp.save(update_fields=["data"])
        ind_app = self._create_aparell("MINI", "Mini")
        comp_ind_app = self._create_comp_aparell(self.comp, ind_app, ordre=2)

        payload = self._classificacio_payload(
            tipus="equips",
            app_ids=[comp_ind_app.id],
            context_code="parelles",
            team_mode="derived_from_individual",
        )
        payload["schema"]["equips"]["particio_edat"] = {
            "activa": True,
            "llindars": [12],
            "sense_data_label": "Sense edat",
        }

        response = self._post_json("classificacio_save", payload)

        self.assertEqual(response.status_code, 200)
        cfg = ClassificacioConfig.objects.get(pk=response.json()["id"])
        part_cfg = ((cfg.schema or {}).get("particions_config") or {}).get("any_naixement_forquilla") or {}
        self.assertIn("any_naixement_forquilla", (cfg.schema or {}).get("particions") or [])
        self.assertTrue(part_cfg.get("ranges"))
        self.assertEqual((part_cfg.get("team_rules") or {}).get("reference_mode"), "oldest_member_birthdate")
        self.assertFalse((((cfg.schema or {}).get("equips") or {}).get("particio_edat") or {}).get("activa", False))


