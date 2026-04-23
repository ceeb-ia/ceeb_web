from datetime import date
from types import SimpleNamespace

from django.test import SimpleTestCase

from ...services.classificacions.engine.teams import (
    _build_resolved_team_by_ins_id,
    _build_team_grouped,
    _build_team_grouped_and_rows,
    _build_team_rows,
)


class EngineTeamRuntimeTests(SimpleTestCase):
    def test_build_resolved_team_by_ins_id_applies_native_fallback_for_derived_mode(self):
        inscripcio = SimpleNamespace(
            id=11,
            equip=None,
            equip_id=7,
            equip__nom="  Falcons  ",
        )

        resolved = _build_resolved_team_by_ins_id(
            [inscripcio],
            team_mode="derived_from_individual",
            team_context_code="parelles",
            assignment_fallback="native",
            team_assignment_map={},
        )

        self.assertEqual(resolved[11].id, 7)
        self.assertEqual(resolved[11].nom, "Falcons")

    def test_build_team_grouped_and_rows_for_derived_mode_keeps_partition_and_team_pool_hooks(self):
        equip = SimpleNamespace(id=10, nom=" Falcons ")
        inscripcio_a = SimpleNamespace(
            id=1,
            categoria="Base",
            data_naixement=date(2014, 1, 1),
            ordre_competicio=2,
            equip=None,
            equip_id=None,
        )
        inscripcio_b = SimpleNamespace(
            id=2,
            categoria="Base",
            data_naixement=date(2015, 1, 1),
            ordre_competicio=1,
            equip=None,
            equip_id=None,
        )
        equips_cfg = {
            "assignment_source": {"mode": "context", "context_code": "ctx", "fallback": "native"},
            "particions_manuals": [{"label": "Final", "equip_ids": [10]}],
            "particio_edat": {"activa": True, "llindars": [12], "sense_data_label": "Sense edat"},
            "combinar_manual_i_edat": True,
            "incloure_sense_equip": False,
        }
        assignment_map = {
            1: SimpleNamespace(equip=equip),
            2: SimpleNamespace(equip=equip),
        }
        team_pool_calls = []

        def get_selected_rows_agg_for_derived_team(cache_key, member_ids):
            team_pool_calls.append((cache_key, list(member_ids)))
            return {
                101: [{"value": 13.0}],
                102: [{"value": 7.0}, {"value": 5.0}],
            }

        resolved = _build_resolved_team_by_ins_id(
            [inscripcio_a, inscripcio_b],
            team_mode="derived_from_individual",
            team_context_code="ctx",
            assignment_fallback="native",
            team_assignment_map=assignment_map,
        )

        grouped, rows = _build_team_grouped_and_rows(
            ins_list=[inscripcio_a, inscripcio_b],
            team_mode="derived_from_individual",
            equips_cfg=equips_cfg,
            aparells=[
                SimpleNamespace(id=101, is_team_competition_unit=False),
                SimpleNamespace(id=102, is_team_competition_unit=False),
            ],
            part_entries=[{"code": "categoria"}],
            part_custom_idx={},
            particions_config={},
            team_context_code="ctx",
            team_assignment_map=assignment_map,
            resolved_team_by_ins_id=resolved,
            competicio=SimpleNamespace(data=date(2026, 4, 21)),
            agg_aparells="sum",
            exercise_selection_scope="team_pool",
            get_selected_rows_agg_for_derived_team=get_selected_rows_agg_for_derived_team,
            resolve_agregacio_exercicis_for_app=lambda app_id: "sum",
        )

        self.assertEqual(sorted(grouped.keys()), ["categoria:Base"])
        self.assertEqual(sorted(grouped["categoria:Base"].keys()), [10])
        self.assertEqual(
            [member.id for member, _resolved_equip in grouped["categoria:Base"][10]],
            [1, 2],
        )

        final_key = "categoria:Base|manual:Final|edat:<=12"
        self.assertIn(final_key, rows)
        self.assertEqual(len(rows[final_key]), 1)
        row = rows[final_key][0]
        self.assertEqual(row["equip_id"], 10)
        self.assertEqual(row["nom"], "Falcons")
        self.assertEqual(row["score"], 25.0)
        self.assertEqual(row["participants"], 2)
        self.assertEqual(row["_member_ids"], [2, 1])
        self.assertEqual(row["_team_mode"], "derived_from_individual")
        self.assertEqual(
            team_pool_calls,
            [("equip:10", [2, 1]), ("equip:10", [2, 1])],
        )

    def test_build_team_grouped_and_rows_for_native_mode_dedupes_team_subject_members(self):
        equip = SimpleNamespace(id=21, nom=" Delta ")
        member_a = SimpleNamespace(
            id=31,
            categoria="Base",
            entitat="Club A",
            subcategoria="S1",
            grup=1,
            grup_competicio=None,
            ordre_competicio=2,
        )
        member_b = SimpleNamespace(
            id=32,
            categoria="Base",
            entitat="Club A",
            subcategoria="S1",
            grup=1,
            grup_competicio=None,
            ordre_competicio=1,
        )
        note = SimpleNamespace(
            team_subject=SimpleNamespace(
                equip=equip,
                member_ids=[31, 32, 31, "32"],
            )
        )

        grouped = _build_team_grouped(
            ins_list=[],
            team_mode="native_team",
            equips_cfg={},
            aparells=[
                SimpleNamespace(id=201, is_team_competition_unit=True),
                SimpleNamespace(id=101, is_team_competition_unit=False),
            ],
            team_notes_by_app={201: [note]},
            all_ins_by_id={31: member_a, 32: member_b},
            filtres={"entitats_in": ["club a"], "categories_in": ["base"]},
            part_entries=[],
            part_custom_idx={},
            particions_config={},
        )

        self.assertEqual(sorted(grouped.keys()), ["global"])
        self.assertEqual(sorted(grouped["global"].keys()), [21])
        self.assertEqual(
            [member.id for member, _resolved_equip in grouped["global"][21]],
            [31, 32],
        )

        rows = _build_team_rows(
            grouped,
            team_mode="native_team",
            aparells=[
                SimpleNamespace(id=201, is_team_competition_unit=True),
                SimpleNamespace(id=101, is_team_competition_unit=False),
            ],
            equips_cfg={},
            part_entries=[],
            part_custom_idx={},
            particions_config={},
            agg_aparells="sum",
            get_main_selected_rows_agg_for_team=lambda equip_id: {
                201: [{"value": 18.0}, {"value": 20.0}]
            }
            if equip_id == 21
            else {},
            resolve_agregacio_exercicis_for_app=lambda app_id: "max",
        )

        self.assertIn("global", rows)
        self.assertEqual(len(rows["global"]), 1)
        row = rows["global"][0]
        self.assertEqual(row["equip_id"], 21)
        self.assertEqual(row["nom"], "Delta")
        self.assertEqual(row["score"], 20.0)
        self.assertEqual(row["participants"], 2)
        self.assertEqual(row["_member_ids"], [32, 31])
        self.assertEqual(row["_team_mode"], "native_team")
