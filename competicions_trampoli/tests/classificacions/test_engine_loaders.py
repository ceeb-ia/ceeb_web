from decimal import Decimal

from django.test import TestCase

from ...models.competicio import Aparell, EquipContext
from ...models.scoring import ScoreEntry, TeamCompetitiveSubject, TeamScoreEntry
from ...services.classificacions.engine.loaders import load_engine_orm_data
from ..base import _BaseTrampoliDataMixin


class EngineLoadersTests(_BaseTrampoliDataMixin, TestCase):
    def setUp(self):
        self.comp = self._create_competicio("Comp Engine Loaders")

    def test_load_engine_orm_data_builds_individual_indexes_from_filtered_scores(self):
        app_a = self._create_aparell("LOAD_A", "Load A")
        app_b = self._create_aparell("LOAD_B", "Load B")
        app_inactive = self._create_aparell("LOAD_X", "Load X")
        comp_app_a = self._create_comp_aparell(self.comp, app_a, ordre=1, actiu=True)
        comp_app_b = self._create_comp_aparell(self.comp, app_b, ordre=2, actiu=True)
        comp_app_inactive = self._create_comp_aparell(self.comp, app_inactive, ordre=3, actiu=False)

        ins_a = self._create_inscripcio(self.comp, "Participant A", ordre=1, grup=1)
        ins_b = self._create_inscripcio(self.comp, "Participant B", ordre=2, grup=1)
        ins_a.categoria = "Senior"
        ins_b.categoria = "Junior"
        ins_a.save(update_fields=["categoria"])
        ins_b.save(update_fields=["categoria"])

        ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=ins_a,
            comp_aparell=comp_app_a,
            exercici=1,
            total=Decimal("11.250"),
        )
        ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=ins_a,
            comp_aparell=comp_app_b,
            exercici=1,
            total=Decimal("14.100"),
        )
        ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=ins_a,
            comp_aparell=comp_app_b,
            exercici=2,
            total=Decimal("15.200"),
        )
        ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=ins_b,
            comp_aparell=comp_app_a,
            exercici=1,
            total=Decimal("99.999"),
        )
        ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=ins_a,
            comp_aparell=comp_app_inactive,
            exercici=1,
            total=Decimal("77.777"),
        )

        data = load_engine_orm_data(
            self.comp,
            punt={
                "aparells": {
                    "mode": "seleccionar",
                    "ids": [comp_app_b.id, comp_app_inactive.id, comp_app_a.id],
                }
            },
            tipus="individual",
            filtres={"categories_in": ["Senior"]},
        )

        self.assertEqual([app.id for app in data.aparells], [comp_app_a.id, comp_app_b.id])
        self.assertEqual(set(data.all_ins_by_id), {ins_a.id, ins_b.id})
        self.assertEqual(set(data.ins_by_id), {ins_a.id})
        self.assertEqual(len(data.notes), 3)
        self.assertEqual(sorted(data.notes_by_app), [comp_app_a.id, comp_app_b.id])
        self.assertEqual(data.notes_by_key[(ins_a.id, comp_app_a.id, 1)].total, Decimal("11.250"))
        self.assertEqual(data.notes_by_key[(ins_a.id, comp_app_b.id, 2)].total, Decimal("15.200"))
        self.assertEqual(data.ins_ids_by_app[comp_app_a.id], {ins_a.id})
        self.assertEqual(data.ins_ids_by_app[comp_app_b.id], {ins_a.id})
        self.assertEqual(data.team_notes, [])
        self.assertEqual(dict(data.team_notes_by_app), {})
        self.assertEqual(data.team_notes_by_key, {})
        self.assertEqual(dict(data.team_ids_by_app), {})

    def test_load_engine_orm_data_builds_native_team_indexes_filtered_by_context(self):
        team_app = self._create_aparell("TEAM_LOAD", "Team Load")
        team_app.competition_unit = Aparell.CompetitionUnit.TEAM
        team_app.save(update_fields=["competition_unit"])
        comp_team_app = self._create_comp_aparell(self.comp, team_app, ordre=1, actiu=True)

        ctx_match = EquipContext.objects.create(competicio=self.comp, code="parelles", nom="Parelles")
        ctx_other = EquipContext.objects.create(competicio=self.comp, code="altres", nom="Altres")
        equip_match = self._create_equip(self.comp, "Parella 1", context=ctx_match)
        equip_other = self._create_equip(self.comp, "Parella 2", context=ctx_other)

        subject_match = TeamCompetitiveSubject.objects.create(
            competicio=self.comp,
            comp_aparell=comp_team_app,
            context=ctx_match,
            equip=equip_match,
        )
        subject_other = TeamCompetitiveSubject.objects.create(
            competicio=self.comp,
            comp_aparell=comp_team_app,
            context=ctx_other,
            equip=equip_other,
        )

        TeamScoreEntry.objects.create(
            competicio=self.comp,
            team_subject=subject_match,
            comp_aparell=comp_team_app,
            exercici=1,
            total=Decimal("21.000"),
        )
        TeamScoreEntry.objects.create(
            competicio=self.comp,
            team_subject=subject_match,
            comp_aparell=comp_team_app,
            exercici=2,
            total=Decimal("22.000"),
        )
        TeamScoreEntry.objects.create(
            competicio=self.comp,
            team_subject=subject_other,
            comp_aparell=comp_team_app,
            exercici=1,
            total=Decimal("99.000"),
        )

        data = load_engine_orm_data(
            self.comp,
            punt={"aparells": {"mode": "seleccionar", "ids": [comp_team_app.id]}},
            tipus="equips",
            equips_cfg={"context_code": "parelles"},
        )

        self.assertEqual(data.team_mode, "native_team")
        self.assertEqual([app.id for app in data.team_apps], [comp_team_app.id])
        self.assertEqual(len(data.notes), 0)
        self.assertEqual(len(data.team_notes), 3)
        self.assertEqual(len(data.team_notes_by_app[comp_team_app.id]), 2)
        self.assertEqual(
            data.team_notes_by_key[(equip_match.id, comp_team_app.id, 1)].total,
            Decimal("21.000"),
        )
        self.assertEqual(
            data.team_notes_by_key[(equip_match.id, comp_team_app.id, 2)].total,
            Decimal("22.000"),
        )
        self.assertNotIn((equip_other.id, comp_team_app.id, 1), data.team_notes_by_key)
        self.assertEqual(data.team_ids_by_app[comp_team_app.id], {equip_match.id})
