from ._shared import *  # noqa: F401,F403


class TeamContextRotacionsIntegrationTests(TeamContextScoringFlowTestBase):
    def test_rotacions_save_ignores_mixed_program_keys_by_station_mode(self):
        franja = RotacioFranja.objects.create(
            competicio=self.comp,
            hora_inici=timezone.datetime(2025, 1, 1, 9, 0).time(),
            hora_fi=timezone.datetime(2025, 1, 1, 10, 0).time(),
            ordre=1,
            titol="Franja 1",
        )
        team_estacio = RotacioEstacio.objects.create(
            competicio=self.comp,
            tipus="aparell",
            comp_aparell=self.comp_app,
            ordre=1,
        )
        individual_app = self._create_aparell("IND2", "Individual 2")
        individual_comp_app = self._create_comp_aparell(self.comp, individual_app, ordre=3)
        individual_estacio = RotacioEstacio.objects.create(
            competicio=self.comp,
            tipus="aparell",
            comp_aparell=individual_comp_app,
            ordre=2,
        )
        serie = SerieEquip.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            display_num=1,
            nom="Serie Mixta",
        )
        group_id = int(self.ins1.grup_competicio_id)

        save_res = self._post_json(
            "rotacions_save",
            {
                "cells": [
                    {
                        "franja": franja.id,
                        "estacio": team_estacio.id,
                        "items": [f"g:{group_id}", f"s:{serie.id}"],
                    },
                    {
                        "franja": franja.id,
                        "estacio": individual_estacio.id,
                        "items": [f"s:{serie.id}", f"g:{group_id}"],
                    },
                ],
            },
        )
        self.assertEqual(save_res.status_code, 200)

        team_assignacio = RotacioAssignacio.objects.get(competicio=self.comp, franja=franja, estacio=team_estacio)
        individual_assignacio = RotacioAssignacio.objects.get(competicio=self.comp, franja=franja, estacio=individual_estacio)

        self.assertEqual(list(team_assignacio.serie_links.values_list("serie_id", flat=True)), [serie.id])
        self.assertEqual(list(team_assignacio.grup_links.values_list("grup_id", flat=True)), [])
        self.assertEqual(list(individual_assignacio.serie_links.values_list("serie_id", flat=True)), [])
        self.assertEqual(list(individual_assignacio.grup_links.values_list("grup_id", flat=True)), [group_id])

    def test_rotacions_save_filters_team_series_to_matching_comp_aparell(self):
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
        other_app = self._create_aparell("SYNC2", "Sincronitzat 2")
        other_app.competition_unit = Aparell.CompetitionUnit.TEAM
        other_app.save(update_fields=["competition_unit"])
        other_comp_app = self._create_comp_aparell(self.comp, other_app, ordre=2)
        other_ctx = EquipContext.objects.create(competicio=self.comp, code="trios", nom="Trios")
        CompeticioAparellEquipContextSource.objects.create(
            competicio=self.comp,
            comp_aparell=other_comp_app,
            context=other_ctx,
        )
        valid_serie = SerieEquip.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            display_num=1,
            nom="Serie OK",
        )
        foreign_serie = SerieEquip.objects.create(
            competicio=self.comp,
            comp_aparell=other_comp_app,
            display_num=1,
            nom="Serie Fora",
        )

        save_res = self._post_json(
            "rotacions_save",
            {
                "cells": [
                    {
                        "franja": franja.id,
                        "estacio": estacio.id,
                        "items": [f"s:{foreign_serie.id}", f"s:{valid_serie.id}"],
                    }
                ],
            },
        )
        self.assertEqual(save_res.status_code, 200)
        assignacio = RotacioAssignacio.objects.get(competicio=self.comp, franja=franja, estacio=estacio)
        self.assertEqual(list(assignacio.serie_links.values_list("serie_id", flat=True)), [valid_serie.id])

    def test_rotacions_save_keeps_team_and_individual_station_payloads_separated(self):
        franja = RotacioFranja.objects.create(
            competicio=self.comp,
            hora_inici=timezone.datetime(2025, 1, 1, 9, 0).time(),
            hora_fi=timezone.datetime(2025, 1, 1, 10, 0).time(),
            ordre=1,
            titol="Franja 1",
        )
        team_estacio = RotacioEstacio.objects.create(
            competicio=self.comp,
            tipus="aparell",
            comp_aparell=self.comp_app,
            ordre=1,
        )
        team_serie = SerieEquip.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            display_num=1,
            nom="Serie Team",
        )
        individual_app = self._create_aparell("TRA", "Trampolí")
        individual_comp_app = self._create_comp_aparell(self.comp, individual_app, ordre=2)
        individual_estacio = RotacioEstacio.objects.create(
            competicio=self.comp,
            tipus="aparell",
            comp_aparell=individual_comp_app,
            ordre=2,
        )
        group = ensure_group_for_display_num(self.comp, 1, name="Grup 1")

        save_res = self._post_json(
            "rotacions_save",
            {
                "cells": [
                    {
                        "franja": franja.id,
                        "estacio": team_estacio.id,
                        "items": [f"g:{group.id}", f"s:{team_serie.id}"],
                    },
                    {
                        "franja": franja.id,
                        "estacio": individual_estacio.id,
                        "items": [f"g:{group.id}", f"s:{team_serie.id}"],
                    },
                ],
            },
        )
        self.assertEqual(save_res.status_code, 200)

        team_assignacio = RotacioAssignacio.objects.get(competicio=self.comp, franja=franja, estacio=team_estacio)
        individual_assignacio = RotacioAssignacio.objects.get(competicio=self.comp, franja=franja, estacio=individual_estacio)
        self.assertEqual(list(team_assignacio.serie_links.values_list("serie_id", flat=True)), [team_serie.id])
        self.assertEqual(list(team_assignacio.grup_links.values_list("grup_id", flat=True)), [])
        self.assertEqual(list(individual_assignacio.serie_links.values_list("serie_id", flat=True)), [])
        self.assertEqual(list(individual_assignacio.grup_links.values_list("grup_id", flat=True)), [group.id])

    def test_rotacions_save_rejects_duplicate_group_within_same_franja(self):
        franja = RotacioFranja.objects.create(
            competicio=self.comp,
            hora_inici=timezone.datetime(2025, 1, 1, 9, 0).time(),
            hora_fi=timezone.datetime(2025, 1, 1, 10, 0).time(),
            ordre=1,
            titol="Franja 1",
        )
        individual_app = self._create_aparell("TRA_DUP", "Tramp Duplicat")
        comp_app_a = self._create_comp_aparell(self.comp, individual_app, ordre=2)
        comp_app_b = self._create_comp_aparell(self.comp, self._create_aparell("TRA_DUP_2", "Tramp Duplicat 2"), ordre=3)
        estacio_a = RotacioEstacio.objects.create(competicio=self.comp, tipus="aparell", comp_aparell=comp_app_a, ordre=1)
        estacio_b = RotacioEstacio.objects.create(competicio=self.comp, tipus="aparell", comp_aparell=comp_app_b, ordre=2)
        group_id = int(self.ins1.grup_competicio_id)

        save_res = self._post_json(
            "rotacions_save",
            {
                "cells": [
                    {"franja": franja.id, "estacio": estacio_a.id, "items": [f"g:{group_id}"]},
                    {"franja": franja.id, "estacio": estacio_b.id, "items": [f"g:{group_id}"]},
                ],
            },
        )
        self.assertEqual(save_res.status_code, 400)
        self.assertTrue(any("mateixa franja" in err for err in save_res.json().get("errors", [])))

    def test_rotacions_extrapolar_preserves_team_series_links(self):
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
        serie = SerieEquip.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            display_num=1,
            nom="Serie A",
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

        extrapolar_res = self.client.post(
            reverse("rotacions_extrapolar", kwargs={"pk": self.comp.id, "franja_id": franja.id}),
            data=json.dumps({"count": 1}),
            content_type="application/json",
        )
        self.assertEqual(extrapolar_res.status_code, 200)
        new_franja = RotacioFranja.objects.exclude(pk=franja.id).get(competicio=self.comp)
        new_assignacio = RotacioAssignacio.objects.get(competicio=self.comp, franja=new_franja, estacio=estacio)
        self.assertEqual(list(new_assignacio.serie_links.values_list("serie_id", flat=True)), [serie.id])

    def test_rotacions_extrapolar_skips_team_station_when_rotating_individual_groups(self):
        franja = RotacioFranja.objects.create(
            competicio=self.comp,
            hora_inici=timezone.datetime(2025, 1, 1, 9, 0).time(),
            hora_fi=timezone.datetime(2025, 1, 1, 10, 0).time(),
            ordre=1,
            titol="Franja 1",
        )
        individual_app_a = self._create_aparell("IND_SKIP_A", "Individual Skip A")
        comp_app_a = self._create_comp_aparell(self.comp, individual_app_a, ordre=2)
        individual_app_b = self._create_aparell("IND_SKIP_B", "Individual Skip B")
        comp_app_b = self._create_comp_aparell(self.comp, individual_app_b, ordre=3)
        individual_estacio_a = RotacioEstacio.objects.create(
            competicio=self.comp,
            tipus="aparell",
            comp_aparell=comp_app_a,
            ordre=1,
        )
        team_estacio = RotacioEstacio.objects.create(
            competicio=self.comp,
            tipus="aparell",
            comp_aparell=self.comp_app,
            ordre=2,
        )
        individual_estacio_b = RotacioEstacio.objects.create(
            competicio=self.comp,
            tipus="aparell",
            comp_aparell=comp_app_b,
            ordre=3,
        )
        group = ensure_group_for_display_num(self.comp, 1, name="Grup salta team")

        save_res = self._post_json(
            "rotacions_save",
            {
                "cells": [
                    {"franja": franja.id, "estacio": individual_estacio_a.id, "items": [f"g:{group.id}"]},
                ],
            },
        )
        self.assertEqual(save_res.status_code, 200)

        extrapolar_res = self.client.post(
            reverse("rotacions_extrapolar", kwargs={"pk": self.comp.id, "franja_id": franja.id}),
            data=json.dumps({"count": 1}),
            content_type="application/json",
        )
        self.assertEqual(extrapolar_res.status_code, 200)

        new_franja = RotacioFranja.objects.exclude(pk=franja.id).get(competicio=self.comp)
        individual_assignacio = RotacioAssignacio.objects.get(
            competicio=self.comp,
            franja=new_franja,
            estacio=individual_estacio_b,
        )
        team_assignacio = RotacioAssignacio.objects.get(
            competicio=self.comp,
            franja=new_franja,
            estacio=team_estacio,
        )

        self.assertEqual(list(individual_assignacio.grup_links.values_list("grup_id", flat=True)), [group.id])
        self.assertEqual(team_assignacio.grup_links.count(), 0)

    def test_rotacions_extrapolar_preserves_team_series_without_assigning_them_to_individual_station(self):
        franja = RotacioFranja.objects.create(
            competicio=self.comp,
            hora_inici=timezone.datetime(2025, 1, 1, 9, 0).time(),
            hora_fi=timezone.datetime(2025, 1, 1, 10, 0).time(),
            ordre=1,
            titol="Franja 1",
        )
        team_estacio_a = RotacioEstacio.objects.create(
            competicio=self.comp,
            tipus="aparell",
            comp_aparell=self.comp_app,
            ordre=1,
        )
        other_team_app = self._create_aparell("SYNC_ROT", "Sincronitzat Rotacio")
        other_team_app.competition_unit = Aparell.CompetitionUnit.TEAM
        other_team_app.save(update_fields=["competition_unit"])
        other_team_comp_app = self._create_comp_aparell(self.comp, other_team_app, ordre=2)
        CompeticioAparellEquipContextSource.objects.create(
            competicio=self.comp,
            comp_aparell=other_team_comp_app,
            context=self.ctx,
        )
        team_estacio_b = RotacioEstacio.objects.create(
            competicio=self.comp,
            tipus="aparell",
            comp_aparell=other_team_comp_app,
            ordre=2,
        )
        individual_app = self._create_aparell("IND_SKIP_TEAM", "Individual al mig")
        individual_comp_app = self._create_comp_aparell(self.comp, individual_app, ordre=3)
        individual_estacio = RotacioEstacio.objects.create(
            competicio=self.comp,
            tipus="aparell",
            comp_aparell=individual_comp_app,
            ordre=3,
        )
        serie = SerieEquip.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            display_num=1,
            nom="Serie equip A",
        )
        other_serie = SerieEquip.objects.create(
            competicio=self.comp,
            comp_aparell=other_team_comp_app,
            display_num=1,
            nom="Serie equip B",
        )

        save_res = self._post_json(
            "rotacions_save",
            {
                "cells": [
                    {"franja": franja.id, "estacio": team_estacio_a.id, "items": [f"s:{serie.id}"]},
                    {"franja": franja.id, "estacio": team_estacio_b.id, "items": [f"s:{other_serie.id}"]},
                ],
            },
        )
        self.assertEqual(save_res.status_code, 200)

        extrapolar_res = self.client.post(
            reverse("rotacions_extrapolar", kwargs={"pk": self.comp.id, "franja_id": franja.id}),
            data=json.dumps({"count": 1}),
            content_type="application/json",
        )
        self.assertEqual(extrapolar_res.status_code, 200)

        new_franja = RotacioFranja.objects.exclude(pk=franja.id).get(competicio=self.comp)
        moved_assignacio = RotacioAssignacio.objects.get(
            competicio=self.comp,
            franja=new_franja,
            estacio=team_estacio_b,
        )
        original_assignacio = RotacioAssignacio.objects.get(
            competicio=self.comp,
            franja=new_franja,
            estacio=team_estacio_a,
        )
        middle_assignacio = RotacioAssignacio.objects.get(
            competicio=self.comp,
            franja=new_franja,
            estacio=individual_estacio,
        )

        self.assertEqual(list(original_assignacio.serie_links.values_list("serie_id", flat=True)), [serie.id])
        self.assertEqual(list(moved_assignacio.serie_links.values_list("serie_id", flat=True)), [other_serie.id])
        self.assertEqual(middle_assignacio.serie_links.count(), 0)

    def test_rotacions_extrapolar_handles_mixed_team_and_individual_rotations(self):
        franja = RotacioFranja.objects.create(
            competicio=self.comp,
            hora_inici=timezone.datetime(2025, 1, 1, 9, 0).time(),
            hora_fi=timezone.datetime(2025, 1, 1, 10, 0).time(),
            ordre=1,
            titol="Franja 1",
        )
        individual_app_a = self._create_aparell("IND_MIX_A", "Individual Mix A")
        comp_app_a = self._create_comp_aparell(self.comp, individual_app_a, ordre=2)
        individual_app_b = self._create_aparell("IND_MIX_B", "Individual Mix B")
        comp_app_b = self._create_comp_aparell(self.comp, individual_app_b, ordre=3)
        individual_estacio_a = RotacioEstacio.objects.create(
            competicio=self.comp,
            tipus="aparell",
            comp_aparell=comp_app_a,
            ordre=1,
        )
        team_estacio = RotacioEstacio.objects.create(
            competicio=self.comp,
            tipus="aparell",
            comp_aparell=self.comp_app,
            ordre=2,
        )
        individual_estacio_b = RotacioEstacio.objects.create(
            competicio=self.comp,
            tipus="aparell",
            comp_aparell=comp_app_b,
            ordre=3,
        )
        group = ensure_group_for_display_num(self.comp, 1, name="Grup mixte")
        serie = SerieEquip.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            display_num=1,
            nom="Serie mixte",
        )

        save_res = self._post_json(
            "rotacions_save",
            {
                "cells": [
                    {"franja": franja.id, "estacio": individual_estacio_a.id, "items": [f"g:{group.id}"]},
                    {"franja": franja.id, "estacio": team_estacio.id, "items": [f"s:{serie.id}"]},
                ],
            },
        )
        self.assertEqual(save_res.status_code, 200)

        extrapolar_res = self.client.post(
            reverse("rotacions_extrapolar", kwargs={"pk": self.comp.id, "franja_id": franja.id}),
            data=json.dumps({"count": 1}),
            content_type="application/json",
        )
        self.assertEqual(extrapolar_res.status_code, 200)

        new_franja = RotacioFranja.objects.exclude(pk=franja.id).get(competicio=self.comp)
        individual_assignacio = RotacioAssignacio.objects.get(
            competicio=self.comp,
            franja=new_franja,
            estacio=individual_estacio_b,
        )
        team_assignacio = RotacioAssignacio.objects.get(
            competicio=self.comp,
            franja=new_franja,
            estacio=team_estacio,
        )

        self.assertEqual(list(individual_assignacio.grup_links.values_list("grup_id", flat=True)), [group.id])
        self.assertEqual(list(team_assignacio.serie_links.values_list("serie_id", flat=True)), [serie.id])

    def test_rotacions_extrapolar_keeps_single_team_station_series_on_same_station(self):
        franja = RotacioFranja.objects.create(
            competicio=self.comp,
            hora_inici=timezone.datetime(2025, 1, 1, 9, 0).time(),
            hora_fi=timezone.datetime(2025, 1, 1, 10, 0).time(),
            ordre=1,
            titol="Franja 1",
        )
        team_estacio = RotacioEstacio.objects.create(
            competicio=self.comp,
            tipus="aparell",
            comp_aparell=self.comp_app,
            ordre=1,
        )
        serie = SerieEquip.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            display_num=1,
            nom="Serie unica",
        )

        save_res = self._post_json(
            "rotacions_save",
            {
                "cells": [
                    {"franja": franja.id, "estacio": team_estacio.id, "items": [f"s:{serie.id}"]},
                ],
            },
        )
        self.assertEqual(save_res.status_code, 200)

        extrapolar_res = self.client.post(
            reverse("rotacions_extrapolar", kwargs={"pk": self.comp.id, "franja_id": franja.id}),
            data=json.dumps({"count": 1}),
            content_type="application/json",
        )
        self.assertEqual(extrapolar_res.status_code, 200)

        new_franja = RotacioFranja.objects.exclude(pk=franja.id).get(competicio=self.comp)
        team_assignacio = RotacioAssignacio.objects.get(
            competicio=self.comp,
            franja=new_franja,
            estacio=team_estacio,
        )
        self.assertEqual(list(team_assignacio.serie_links.values_list("serie_id", flat=True)), [serie.id])

    def test_rotacions_extrapolar_ignores_break_stations_for_rotation_steps(self):
        franja = RotacioFranja.objects.create(
            competicio=self.comp,
            hora_inici=timezone.datetime(2025, 1, 1, 9, 0).time(),
            hora_fi=timezone.datetime(2025, 1, 1, 10, 0).time(),
            ordre=1,
            titol="Franja 1",
        )
        individual_app_a = self._create_aparell("IND_BREAK_A", "Individual Break A")
        comp_app_a = self._create_comp_aparell(self.comp, individual_app_a, ordre=2)
        individual_app_b = self._create_aparell("IND_BREAK_B", "Individual Break B")
        comp_app_b = self._create_comp_aparell(self.comp, individual_app_b, ordre=3)
        individual_estacio_a = RotacioEstacio.objects.create(
            competicio=self.comp,
            tipus="aparell",
            comp_aparell=comp_app_a,
            ordre=1,
        )
        break_estacio = RotacioEstacio.objects.create(
            competicio=self.comp,
            tipus="descans",
            ordre=2,
        )
        individual_estacio_b = RotacioEstacio.objects.create(
            competicio=self.comp,
            tipus="aparell",
            comp_aparell=comp_app_b,
            ordre=3,
        )
        group = ensure_group_for_display_num(self.comp, 1, name="Grup amb descans")

        save_res = self._post_json(
            "rotacions_save",
            {
                "cells": [
                    {"franja": franja.id, "estacio": individual_estacio_a.id, "items": [f"g:{group.id}"]},
                ],
            },
        )
        self.assertEqual(save_res.status_code, 200)

        extrapolar_res = self.client.post(
            reverse("rotacions_extrapolar", kwargs={"pk": self.comp.id, "franja_id": franja.id}),
            data=json.dumps({"count": 1}),
            content_type="application/json",
        )
        self.assertEqual(extrapolar_res.status_code, 200)

        new_franja = RotacioFranja.objects.exclude(pk=franja.id).get(competicio=self.comp)
        individual_assignacio = RotacioAssignacio.objects.get(
            competicio=self.comp,
            franja=new_franja,
            estacio=individual_estacio_b,
        )
        break_assignacio = RotacioAssignacio.objects.get(
            competicio=self.comp,
            franja=new_franja,
            estacio=break_estacio,
        )

        self.assertEqual(list(individual_assignacio.grup_links.values_list("grup_id", flat=True)), [group.id])
        self.assertEqual(break_assignacio.grup_links.count(), 0)

    def test_rotacions_save_ignores_group_keys_for_team_station(self):
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
        valid_serie = SerieEquip.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            display_num=1,
            nom="Serie OK",
        )

        save_res = self._post_json(
            "rotacions_save",
            {
                "cells": [
                    {
                        "franja": franja.id,
                        "estacio": estacio.id,
                        "items": ["g:1", f"s:{valid_serie.id}"],
                    }
                ],
            },
        )
        self.assertEqual(save_res.status_code, 200)
        assignacio = RotacioAssignacio.objects.get(competicio=self.comp, franja=franja, estacio=estacio)
        self.assertEqual(list(assignacio.serie_links.values_list("serie_id", flat=True)), [valid_serie.id])
        self.assertEqual(assignacio.grup_links.count(), 0)


