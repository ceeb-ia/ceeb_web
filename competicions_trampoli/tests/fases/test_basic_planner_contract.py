from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse

from ...models import CompeticioMembership
from ...models.classificacions import ClassificacioConfig
from ...models.competicio import (
    CompeticioAparellFase,
    FasePartitionState,
    ProgramUnit,
    ProgramUnitSlot,
)
from ...models.rotacions import RotacioAssignacio, RotacioAssignacioProgramUnit, RotacioEstacio, RotacioFranja
from ...models.scoring import ScoreEntry
from ...services.fases import SlotSubject, create_program_unit_from_subjects, create_program_unit_with_empty_slots
from ...services.fases.group_plan import apply_group_plan
from ..base import _BaseTrampoliDataMixin


class FasesBasicPlannerTests(_BaseTrampoliDataMixin, TestCase):
    def setUp(self):
        self.competicio = self._create_competicio("Comp fases planner")
        self.user = self._login_competicio_user(
            self.competicio,
            role=CompeticioMembership.Role.OWNER,
            username_prefix="fases_planner_owner",
        )
        self.aparell = self._create_aparell("TRA_PLAN", "Trampoli", owner=self.user)
        self.comp_aparell = self._create_comp_aparell(self.competicio, self.aparell)

    def _planner_url(self):
        return reverse(
            "trampoli_aparell_fases",
            kwargs={"pk": self.competicio.id, "app_id": self.comp_aparell.id},
        )

    def _common_planner_url(self, comp_aparell=None):
        url = reverse("trampoli_fases", kwargs={"pk": self.competicio.id})
        if comp_aparell is not None:
            url = f"{url}?app={comp_aparell.id}"
        return url

    def _create_phase(self, *, nom="Semifinal", codi="SEMI", parent=None, ordre=2):
        return CompeticioAparellFase.objects.create(
            competicio=self.competicio,
            comp_aparell=self.comp_aparell,
            parent=parent,
            nom=nom,
            codi=codi,
            ordre=ordre,
        )

    def _place_program_unit_in_rotacions(self, unit):
        franja = RotacioFranja.objects.create(
            competicio=self.competicio,
            hora_inici="09:00",
            hora_fi="10:00",
            ordre=1,
            ordre_visual=1,
            titol="Franja 1",
        )
        estacio = RotacioEstacio.objects.create(
            competicio=self.competicio,
            tipus="aparell",
            comp_aparell=self.comp_aparell,
            ordre=1,
        )
        assignacio = RotacioAssignacio.objects.create(
            competicio=self.competicio,
            franja=franja,
            estacio=estacio,
        )
        return RotacioAssignacioProgramUnit.objects.create(
            assignacio=assignacio,
            program_unit=unit,
            ordre=1,
        )

    def test_planner_lists_advanced_phase_and_program_units_without_score_payloads(self):
        fase = self._create_phase()
        create_program_unit_with_empty_slots(
            fase=fase,
            nom="Semifinal Grup 1",
            capacity=2,
            tipus=ProgramUnit.Tipus.BLOCK,
        )
        inscripcio = self._create_inscripcio(self.competicio, "Participant A")
        ScoreEntry.objects.create(
            competicio=self.competicio,
            inscripcio=inscripcio,
            comp_aparell=self.comp_aparell,
            exercici=1,
            inputs={"contract_marker": "score-inputs-must-not-leak"},
            outputs={"total": 9},
            total=9,
        )

        response = self.client.get(f"{self._planner_url()}?phase={fase.id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["competicio"], self.competicio)
        self.assertEqual(response.context["comp_aparell"], self.comp_aparell)
        self.assertIn(fase, list(response.context["phases"]))

    def test_tree_unit_card_groups_operational_actions_under_overflow_menu(self):
        phase = self._create_phase()
        create_program_unit_with_empty_slots(
            fase=phase,
            nom="Semifinal Grup 1",
            capacity=2,
            tipus=ProgramUnit.Tipus.BLOCK,
        )

        response = self.client.get(f"{self._common_planner_url(self.comp_aparell)}&phase={phase.id}")

        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        card_start = html.index('<article class="phase-program-unit-card">')
        card_end = html.index("</article>", card_start)
        card_html = html[card_start:card_end]
        menu_start = card_html.index('<details class="phase-slot-actions phase-unit-actions">')
        menu_end = card_html.index("</details>", menu_start)
        menu_html = card_html[menu_start:menu_end]

        self.assertIn('aria-label="Accions de la unitat"', menu_html)
        self.assertIn('value="preview_qualification_unit"', menu_html)
        self.assertIn('value="apply_qualification_unit"', menu_html)
        self.assertIn('value="confirm_program_unit"', menu_html)
        self.assertNotIn('value="add_extra_program_slot"', menu_html)
        self.assertLess(card_html.index('value="add_extra_program_slot"'), menu_start)
        self.assertGreater(card_html.index('<summary>Editar unitat</summary>'), menu_end)
        body = response.content.decode("utf-8")
        self.assertNotIn("Fase unica", body)
        self.assertIn("DEFAULT reservat", body)
        self.assertIn("Semifinal Grup 1", body)
        self.assertNotIn("score-inputs-must-not-leak", body)
        self.assertNotIn("scores", response.context)
        self.assertNotIn("team_scores", response.context)

    def test_planner_does_not_create_default_phase_on_get(self):
        response = self.client.get(self._planner_url(), follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.redirect_chain)
        self.assertIn(f"app={self.comp_aparell.id}", response.redirect_chain[0][0])
        self.assertIn("phase=base", response.redirect_chain[0][0])
        self.assertEqual(CompeticioAparellFase.objects.filter(comp_aparell=self.comp_aparell).count(), 0)
        self.assertContains(response, "La preliminar/default no es crea aquí")

    def test_aparell_list_links_to_phase_planner(self):
        response = self.client.get(reverse("trampoli_aparells_list", kwargs={"pk": self.competicio.id}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self._common_planner_url(self.comp_aparell))
        self.assertContains(response, "Fases")

    def test_common_planner_shows_all_local_apps_and_selected_app(self):
        second_app = self._create_comp_aparell(self.competicio, self.aparell, ordre=2)
        second_app.nom_local = "Trampoli femeni"
        second_app.codi_local = "TRA-F"
        second_app.save(update_fields=["nom_local", "codi_local"])
        self._create_phase(nom="Final", codi="FIN", ordre=3)

        response = self.client.get(self._common_planner_url(second_app), follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.redirect_chain)
        self.assertIn(f"app={second_app.id}", response.redirect_chain[0][0])
        self.assertIn("phase=base", response.redirect_chain[0][0])
        self.assertEqual(response.context["comp_aparell"], second_app)
        body = response.content.decode("utf-8")
        self.assertIn(self.comp_aparell.display_nom, body)
        self.assertIn("Trampoli femeni", body)
        self.assertIn("Preliminar implicita", body)
        self.assertIn("Arrel visual de l'arbre", body)

    def test_common_planner_marks_programmed_and_pending_units(self):
        fase = self._create_phase()
        programmed = create_program_unit_with_empty_slots(
            fase=fase,
            nom="Semifinal Programada",
            capacity=2,
            tipus=ProgramUnit.Tipus.BLOCK,
        )
        create_program_unit_with_empty_slots(
            fase=fase,
            nom="Semifinal Pendent",
            capacity=2,
            tipus=ProgramUnit.Tipus.BLOCK,
        )
        franja = RotacioFranja.objects.create(
            competicio=self.competicio,
            hora_inici="09:00",
            hora_fi="10:00",
            ordre=1,
            ordre_visual=1,
            titol="Franja 1",
        )
        estacio = RotacioEstacio.objects.create(
            competicio=self.competicio,
            tipus="aparell",
            comp_aparell=self.comp_aparell,
            ordre=1,
        )
        assignacio = RotacioAssignacio.objects.create(
            competicio=self.competicio,
            franja=franja,
            estacio=estacio,
        )
        RotacioAssignacioProgramUnit.objects.create(
            assignacio=assignacio,
            program_unit=programmed,
            ordre=1,
        )

        response = self.client.get(f"{self._common_planner_url(self.comp_aparell)}&phase={fase.id}")

        self.assertEqual(response.status_code, 200)
        body = response.content.decode("utf-8")
        self.assertIn("Semifinal Programada", body)
        self.assertIn("Semifinal Pendent", body)
        self.assertIn("Programat", body)
        self.assertIn("Pendent de programar", body)

    def test_reordered_slots_show_current_place_and_classification_origin(self):
        fase = self._create_phase()
        first = self._create_inscripcio(self.competicio, "Classificat u")
        second = self._create_inscripcio(self.competicio, "Classificat dos")
        unit = create_program_unit_from_subjects(
            fase=fase,
            nom="Final ordre visible",
            subjects=[
                SlotSubject(
                    "inscripcio",
                    first.id,
                    source_position=1,
                    source_particio_key="global",
                    source_row={"participant": "Classificat u", "entitat": "Club A"},
                ),
                SlotSubject(
                    "inscripcio",
                    second.id,
                    source_position=2,
                    source_particio_key="global",
                    source_row={"participant": "Classificat dos", "entitat": "Club B"},
                ),
            ],
        )
        slots = list(unit.slots.order_by("ordre", "slot_index", "id"))

        response = self.client.post(
            self._common_planner_url(self.comp_aparell),
            data={
                "action": "reorder_program_unit_slots",
                "fase_id": fase.id,
                "unit_id": unit.id,
                "slot_order": f"{slots[1].id},{slots[0].id}",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        page = self.client.get(f"{self._common_planner_url(self.comp_aparell)}&phase={fase.id}")
        self.assertEqual(page.status_code, 200)
        selected_phase = page.context["selected_phase"]
        selected_unit = selected_phase.ui_units[0]
        rendered_slots = list(selected_unit.slots.all())
        self.assertEqual([slot.subject_id for slot in rendered_slots], [second.id, first.id])
        self.assertEqual([slot.ui_origin_label for slot in rendered_slots], ["Classificat #2", "Classificat #1"])

    def test_post_create_phase_creates_advanced_phase(self):
        response = self.client.post(
            self._planner_url(),
            data={
                "action": "create_phase",
                "parent": "",
                "nom": "Semifinal",
                "codi": "semi",
                "ordre": 2,
                "estat": CompeticioAparellFase.Estat.PLANNED,
            },
        )

        self.assertEqual(response.status_code, 302)
        phase = CompeticioAparellFase.objects.get(comp_aparell=self.comp_aparell, codi="SEMI")
        self.assertIsNone(phase.parent_id)
        self.assertEqual(phase.nom, "Semifinal")

    def test_post_create_phase_assigns_order_when_missing(self):
        existing = self._create_phase(nom="Semifinal A", codi="SEMIA", ordre=1)

        response = self.client.post(
            self._planner_url(),
            data={
                "action": "create_phase",
                "parent": "",
                "nom": "Semifinal B",
                "codi": "semib",
                "estat": CompeticioAparellFase.Estat.PLANNED,
            },
        )

        self.assertEqual(response.status_code, 302)
        phase = CompeticioAparellFase.objects.get(comp_aparell=self.comp_aparell, codi="SEMIB")
        self.assertIsNone(phase.parent_id)
        self.assertEqual(phase.ordre, existing.ordre + 1)

    def test_post_create_child_phase_assigns_next_sibling_order(self):
        parent = self._create_phase(nom="Semifinal", codi="SEMI", ordre=1)
        first_child = self._create_phase(nom="Final A", codi="FINA", parent=parent, ordre=1)

        response = self.client.post(
            self._planner_url(),
            data={
                "action": "create_phase",
                "parent": parent.id,
                "nom": "Final B",
                "codi": "finb",
                "estat": CompeticioAparellFase.Estat.PLANNED,
            },
        )

        self.assertEqual(response.status_code, 302)
        phase = CompeticioAparellFase.objects.get(comp_aparell=self.comp_aparell, codi="FINB")
        self.assertEqual(phase.parent_id, parent.id)
        self.assertEqual(phase.ordre, first_child.ordre + 1)

    def test_post_configure_source_cut_stores_phase_config(self):
        phase = self._create_phase()
        classificacio = ClassificacioConfig.objects.create(
            competicio=self.competicio,
            nom="Preliminar TRA",
            activa=True,
            ordre=1,
            tipus="individual",
            schema={},
        )

        response = self.client.post(
            self._planner_url(),
            data={
                "action": "configure_source_cut",
                "fase_id": phase.id,
                "classificacio": classificacio.id,
                "cut_mode": "top_n",
                "qualifiers_count": 8,
                "reserve_count": 2,
                "partition_mode": "source_partitions",
                "tie_policy": "manual_decision",
                "unit_capacity": 4,
                "unit_name_template": "{fase} - {particio}",
            },
        )

        self.assertEqual(response.status_code, 302)
        phase.refresh_from_db()
        self.assertEqual(phase.config["source"]["classificacio_id"], classificacio.id)
        self.assertEqual(phase.config["cut"]["qualifiers_count"], 8)
        self.assertEqual(phase.config["cut"]["reserve_count"], 2)
        self.assertEqual(phase.config["cut"]["partition_mode"], "source_partitions")
        self.assertEqual(phase.config["cut"]["tie_policy"], "manual_decision")

        page = self.client.get(f"{self._common_planner_url(self.comp_aparell)}&phase={phase.id}")
        self.assertContains(page, "Preliminar TRA")
        self.assertContains(page, "Top 8 + 2 reserves")

    def test_planner_exposes_qualification_actions(self):
        phase = self._create_phase()

        response = self.client.get(f"{self._common_planner_url(self.comp_aparell)}&phase={phase.id}")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="preview_group_plan"')
        self.assertContains(response, 'value="apply_group_plan"')
        self.assertContains(response, 'value="preview_qualification"')
        self.assertContains(response, 'value="apply_qualification"')
        self.assertNotContains(response, 'value="regenerate_qualification"')
        self.assertContains(response, "Pla de grups")
        self.assertContains(response, "Generar unitats buides")
        self.assertContains(response, "Snapshot de la fase")
        self.assertContains(response, "Congelar snapshot")
        self.assertContains(response, reverse("scoring_schema_update", kwargs={"pk": self.competicio.id, "ap_id": self.comp_aparell.id}))
        self.assertContains(response, 'value="update_phase_scoring_settings"')

    def test_post_preview_group_plan_calls_service_when_available(self):
        phase = self._create_phase()
        preview = SimpleNamespace(
            summary=Mock(
                return_value={
                    "slots": 4,
                    "units": 2,
                }
            ),
            warnings=[],
        )
        service = Mock(return_value=preview)
        serializer = Mock(return_value={"summary": {"slots": 4, "units": 2}, "warnings": []})

        with patch("competicions_trampoli.views.competition.fases.actions.preview_group_plan", service):
            with patch("competicions_trampoli.views.competition.fases.actions.group_plan_as_dict", serializer):
                response = self.client.post(
                    self._planner_url(),
                    data={"action": "preview_group_plan", "fase_id": phase.id},
                    follow=True,
                )

        self.assertEqual(response.status_code, 200)
        service.assert_called_once_with(phase)
        serializer.assert_called_once_with(preview)
        self.assertContains(response, "Pla de grups de")
        self.assertContains(response, "2 unitats buides")
        self.assertContains(response, "4 places")

    def test_post_apply_group_plan_calls_service_when_available(self):
        phase = self._create_phase()
        preview = SimpleNamespace(
            summary=Mock(
                return_value={
                    "slots": 4,
                    "units": 2,
                }
            )
        )
        service = Mock(return_value=preview)

        with patch("competicions_trampoli.views.competition.fases.actions.apply_group_plan", service):
            response = self.client.post(
                self._planner_url(),
                data={"action": "apply_group_plan", "fase_id": phase.id},
                follow=True,
            )

        self.assertEqual(response.status_code, 200)
        service.assert_called_once_with(phase, replace_existing=False, allow_replace_protected=False)
        self.assertContains(response, "Unitats buides generades per")
        self.assertContains(response, "2 unitats")
        self.assertContains(response, "4 places")

    def test_group_plan_badge_reflects_applied_snapshot(self):
        phase = self._create_phase()
        phase.config = {"qualification": {"run_id": 123, "snapshot_hash": ""}}
        phase.save(update_fields=["config", "updated_at"])

        response = self.client.get(f"{self._common_planner_url(self.comp_aparell)}&phase={phase.id}")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Snapshot aplicat")
        self.assertNotContains(response, "Unitats buides</span>")

    def test_draft_phase_can_clear_all_slots_in_unit(self):
        phase = self._create_phase()
        unit = create_program_unit_from_subjects(
            fase=phase,
            nom="Unitat A",
            subjects=[
                SlotSubject("inscripcio", 101, status=ProgramUnitSlot.Status.FILLED, source_row={"name": "A"}),
                SlotSubject("inscripcio", 102, status=ProgramUnitSlot.Status.MANUAL, source_row={"name": "B"}),
            ],
        )

        response = self.client.get(f"{self._common_planner_url(self.comp_aparell)}&phase={phase.id}")
        self.assertContains(response, "Buidar places")
        self.assertContains(response, 'data-phase-confirm-message="Buidar totes les places de la unitat Unitat A?')

        response = self.client.post(
            self._planner_url(),
            data={"action": "clear_program_unit_slots", "fase_id": phase.id, "unit_id": unit.id},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        slots = list(unit.slots.order_by("ordre", "slot_index", "id"))
        for slot in slots:
            slot.refresh_from_db()
            self.assertEqual(slot.status, ProgramUnitSlot.Status.EMPTY)
            self.assertEqual(slot.subject_kind, "")
            self.assertIsNone(slot.subject_id)
            self.assertEqual(slot.source_row, {})
        self.assertContains(response, "2 places buidades")

    def test_clear_all_slots_in_unit_requires_editable_unit(self):
        phase = self._create_phase()
        phase.estat = CompeticioAparellFase.Estat.PUBLISHED
        phase.save(update_fields=["estat", "updated_at"])
        unit = create_program_unit_from_subjects(
            fase=phase,
            nom="Unitat publicada",
            subjects=[SlotSubject("inscripcio", 101, status=ProgramUnitSlot.Status.FILLED)],
            status=ProgramUnit.Status.PUBLISHED,
        )

        response = self.client.post(
            self._planner_url(),
            data={"action": "clear_program_unit_slots", "fase_id": phase.id, "unit_id": unit.id},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        slot = unit.slots.get()
        self.assertEqual(slot.status, ProgramUnitSlot.Status.FILLED)
        self.assertContains(response, "Torna la unitat a esborrany abans de buidar-ne les places.")

    def test_confirmed_unit_can_return_to_draft_without_changing_slots_rotations_or_scores(self):
        phase = self._create_phase()
        phase.estat = CompeticioAparellFase.Estat.PARTIALLY_CONFIRMED
        phase.save(update_fields=["estat", "updated_at"])
        inscripcio = self._create_inscripcio(self.competicio, "Semifinalista")
        unit = create_program_unit_from_subjects(
            fase=phase,
            nom="Semifinal",
            subjects=[SlotSubject("inscripcio", inscripcio.id, status=ProgramUnitSlot.Status.FILLED)],
            status=ProgramUnit.Status.CONFIRMED,
        )
        rotation_link = self._place_program_unit_in_rotacions(unit)
        score = ScoreEntry.objects.create(
            competicio=self.competicio,
            inscripcio=inscripcio,
            comp_aparell=self.comp_aparell,
            fase=phase,
            exercici=1,
            inputs={},
            outputs={"total": 8},
            total=8,
        )
        slot = unit.slots.get()
        slot_snapshot = (slot.status, slot.subject_kind, slot.subject_id)

        page = self.client.get(f"{self._common_planner_url(self.comp_aparell)}&phase={phase.id}")
        self.assertContains(page, "Tornar a esborrany")

        response = self.client.post(
            self._common_planner_url(self.comp_aparell),
            data={
                "action": "reopen_program_unit",
                "fase_id": phase.id,
                "unit_id": unit.id,
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        unit.refresh_from_db()
        slot.refresh_from_db()
        self.assertEqual(unit.status, ProgramUnit.Status.PLANNED)
        self.assertEqual((slot.status, slot.subject_kind, slot.subject_id), slot_snapshot)
        self.assertTrue(RotacioAssignacioProgramUnit.objects.filter(id=rotation_link.id).exists())
        self.assertTrue(ScoreEntry.objects.filter(id=score.id).exists())
        response_messages = [str(message) for message in get_messages(response.wsgi_request)]
        self.assertTrue(any("Places, rotacions i notes s'han conservat." in message for message in response_messages))
        self.assertContains(response, "Buidar places")

        cleared = self.client.post(
            self._common_planner_url(self.comp_aparell),
            data={
                "action": "clear_program_unit_slots",
                "fase_id": phase.id,
                "unit_id": unit.id,
            },
            follow=True,
        )

        self.assertEqual(cleared.status_code, 200)
        slot.refresh_from_db()
        self.assertEqual(slot.status, ProgramUnitSlot.Status.EMPTY)
        self.assertTrue(RotacioAssignacioProgramUnit.objects.filter(id=rotation_link.id).exists())
        self.assertTrue(ScoreEntry.objects.filter(id=score.id).exists())

    def test_group_plan_seeds_expected_classification_positions_on_empty_slots(self):
        phase = self._create_phase()
        cfg = ClassificacioConfig.objects.create(
            competicio=self.competicio,
            nom="Preliminar",
            activa=True,
            ordre=1,
            tipus="individual",
            schema={},
        )
        phase.config = {
            "source": {"classificacio_id": cfg.id, "classificacio_nom": cfg.nom, "tipus": cfg.tipus},
            "cut": {
                "mode": "top_n",
                "qualifiers_count": 4,
                "reserve_count": 0,
                "partition_mode": "global",
                "tie_policy": "classification_order",
                "unit_capacity": 2,
                "unit_name_template": "{fase} - {particio}",
            },
            "group_plan_settings": {
                "split_mode": "by_count",
                "units_per_partition": 2,
                "unit_capacity": 2,
                "formation_strategy": "serpentine",
                "unit_name_template": "{fase} - {particio}",
            },
        }
        phase.save(update_fields=["config", "updated_at"])
        rows = {
            "global": [
                {"posicio": index, "punts": 10 - index, "inscripcio_id": 100 + index, "participant": f"Classificat {index}"}
                for index in range(1, 5)
            ]
        }

        with patch("competicions_trampoli.services.fases.group_plan.compute_classificacio", return_value=rows):
            apply_group_plan(phase)

        units = list(phase.program_units.prefetch_related("slots").order_by("ordre", "id"))
        self.assertEqual(
            [[slot.source_position for slot in unit.slots.order_by("ordre", "slot_index", "id")] for unit in units],
            [[4, 1], [3, 2]],
        )
        self.assertTrue(all(slot.status == ProgramUnitSlot.Status.EMPTY for unit in units for slot in unit.slots.all()))
        self.assertEqual(
            [
                [(slot.source_row or {}).get("phase_seed_position") for slot in unit.slots.order_by("ordre", "slot_index", "id")]
                for unit in units
            ],
            [[4, 1], [3, 2]],
        )
        self.assertTrue(
            all(
                "participant" not in (slot.source_row or {})
                for unit in units
                for slot in unit.slots.all()
            )
        )

        response = self.client.get(f"{self._common_planner_url(self.comp_aparell)}&phase={phase.id}")

        selected_unit = response.context["selected_phase"].ui_units[0]
        self.assertEqual(
            [slot.ui_origin_label for slot in selected_unit.slots.all()],
            ["4t classificat previst", "1r classificat previst"],
        )
        origin_detail = " ".join(slot.ui_origin_detail for slot in selected_unit.slots.all())
        self.assertNotIn("Posicio classificacio", origin_detail)
        self.assertNotIn("Punts:", origin_detail)
        self.assertNotContains(response, "Previst: Classificat 1")

    def test_post_preview_qualification_surfaces_service_validation(self):
        phase = self._create_phase()

        response = self.client.post(
            self._planner_url(),
            data={"action": "preview_qualification", "fase_id": phase.id},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        messages = [str(message) for message in get_messages(response.wsgi_request)]
        self.assertIn("Cal configurar una classificacio origen abans de generar la fase.", messages)

    def test_post_preview_qualification_shows_candidates_in_unit_slots(self):
        phase = self._create_phase()
        unit = create_program_unit_with_empty_slots(
            fase=phase,
            nom="Semifinal Global",
            capacity=2,
            tipus=ProgramUnit.Tipus.BLOCK,
            partition_key="global",
        )
        preview = SimpleNamespace(
            summary=Mock(
                return_value={
                    "candidates": 2,
                    "slots": 2,
                    "units": 1,
                }
            )
        )
        candidate = SimpleNamespace(
            source_particio_key="global",
            source_row={"participant": "Abril Casas", "entitat": "Club A"},
            subject_kind="inscripcio",
            subject_id=101,
            status=ProgramUnitSlot.Status.FILLED,
            source_position=2,
            source_score=9.45,
        )
        reserve = SimpleNamespace(
            source_particio_key="global",
            source_row={"participant": "Reserva Global", "entitat": "Club R"},
            subject_kind="inscripcio",
            subject_id=102,
            status=ProgramUnitSlot.Status.RESERVE,
            source_position=3,
            source_score=8.8,
        )
        serializer = Mock(
            return_value={
                "summary": {"candidates": 2, "slots": 2, "units": 1},
                "warnings": [],
                "units": [
                    {
                        "unit_id": unit.id,
                        "label": unit.nom,
                        "partition_key": "global",
                        "capacity": 2,
                        "candidates": [candidate],
                    }
                ],
                "reserves": {"global": [reserve]},
            }
        )

        with patch("competicions_trampoli.views.competition.fases.actions.record_qualification_preview", return_value=preview):
            with patch("competicions_trampoli.views.competition.fases.actions.preview_as_dict", serializer):
                response = self.client.post(
                    self._planner_url(),
                    data={"action": "preview_qualification", "fase_id": phase.id},
                    follow=True,
                )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Semifinal Global")
        self.assertContains(response, "Vista ampliada")
        self.assertContains(response, f'data-open-unit-preview-modal="unit-preview-modal-{unit.id}"')
        self.assertContains(response, f'form="unit-preview-order-form-{unit.id}"')
        self.assertContains(response, "Desar ordre")
        self.assertNotContains(response, "Ordenar places")
        self.assertContains(response, "Preview")
        self.assertContains(response, "Actual")
        self.assertContains(response, "Abril Casas")
        self.assertContains(response, "#2")
        self.assertContains(response, "Reserves preview")
        self.assertContains(response, "Reserva Global")
        self.assertContains(response, "Confirmar previsualització")

    def test_post_apply_qualification_calls_service_when_available(self):
        phase = self._create_phase()
        preview = SimpleNamespace(
            summary=Mock(
                return_value={
                    "candidates": 3,
                    "slots": 4,
                    "units": 1,
                }
            )
        )
        service = Mock(return_value=preview)

        with patch("competicions_trampoli.views.competition.fases.actions.apply_qualification", service):
            response = self.client.post(
                self._planner_url(),
                data={"action": "apply_qualification", "fase_id": phase.id},
                follow=True,
            )

        self.assertEqual(response.status_code, 200)
        service.assert_called_once_with(
            phase,
            partition_keys=None,
            replace_existing=False,
            allow_replace_protected=False,
        )
        self.assertContains(response, "Snapshot congelat per")
        self.assertContains(response, "slots existents")

    def test_post_preview_qualification_unit_resolves_partition_from_unit(self):
        phase = self._create_phase()
        unit = create_program_unit_with_empty_slots(
            fase=phase,
            nom="Semifinal Infantil F",
            capacity=2,
            tipus=ProgramUnit.Tipus.BLOCK,
            partition_key="categoria=Infantil|subcategoria=F",
        )
        preview = SimpleNamespace(
            summary=Mock(
                return_value={
                    "candidates": 2,
                    "slots": 2,
                    "units": 1,
                }
            )
        )
        service = Mock(return_value=preview)
        serializer = Mock(return_value={"summary": {"candidates": 2, "slots": 2, "units": 1}, "warnings": [], "units": []})

        with patch("competicions_trampoli.views.competition.fases.actions.record_qualification_preview", service):
            with patch("competicions_trampoli.views.competition.fases.actions.preview_as_dict", serializer):
                response = self.client.post(
                    self._planner_url(),
                    data={
                        "action": "preview_qualification_unit",
                        "fase_id": phase.id,
                        "unit_id": unit.id,
                        "partition_key": "malicious-client-value",
                    },
                    follow=True,
                )

        self.assertEqual(response.status_code, 200)
        service.assert_called_once_with(phase, partition_keys=["categoria=Infantil|subcategoria=F"])
        serializer.assert_called_once_with(preview)
        self.assertContains(response, "Snapshot previst de")
        self.assertContains(response, "Semifinal Infantil F")

    def test_post_apply_qualification_unit_resolves_partition_from_unit(self):
        phase = self._create_phase()
        unit = create_program_unit_with_empty_slots(
            fase=phase,
            nom="Semifinal Infantil F",
            capacity=2,
            tipus=ProgramUnit.Tipus.BLOCK,
            partition_key="categoria=Infantil|subcategoria=F",
        )
        preview = SimpleNamespace(
            summary=Mock(
                return_value={
                    "candidates": 2,
                    "slots": 2,
                    "units": 1,
                }
            )
        )
        service = Mock(return_value=preview)

        with patch("competicions_trampoli.views.competition.fases.actions.apply_qualification", service):
            response = self.client.post(
                self._planner_url(),
                data={
                    "action": "apply_qualification_unit",
                    "fase_id": phase.id,
                    "unit_id": unit.id,
                    "partition_key": "malicious-client-value",
                },
                follow=True,
            )

        self.assertEqual(response.status_code, 200)
        service.assert_called_once_with(
            phase,
            partition_keys=["categoria=Infantil|subcategoria=F"],
            replace_existing=False,
            allow_replace_protected=False,
        )
        self.assertContains(response, "Snapshot congelat per")
        self.assertContains(response, "Semifinal Infantil F")

    def test_post_confirm_partition_calls_service_when_available(self):
        phase = self._create_phase()
        unit = create_program_unit_with_empty_slots(
            fase=phase,
            nom="Semifinal Global",
            capacity=2,
            tipus=ProgramUnit.Tipus.BLOCK,
            partition_key="global",
        )
        state = SimpleNamespace(partition_key="global")
        service = Mock(return_value=state)

        with patch("competicions_trampoli.views.competition.fases.actions.confirm_qualification_partition", service):
            response = self.client.post(
                self._planner_url(),
                data={
                    "action": "confirm_partition",
                    "fase_id": phase.id,
                    "unit_id": unit.id,
                    "partition_key": "malicious-client-value",
                },
                follow=True,
            )

        self.assertEqual(response.status_code, 200)
        service.assert_called_once_with(phase, "global")
        messages = [str(message) for message in get_messages(response.wsgi_request)]
        self.assertIn("Partició 'global' confirmada per 'Semifinal'.", messages)

    def test_planner_shows_generated_partition_confirmation_action(self):
        phase = self._create_phase()
        unit = create_program_unit_with_empty_slots(
            fase=phase,
            nom="Semifinal Global",
            capacity=2,
            tipus=ProgramUnit.Tipus.BLOCK,
            partition_key="global",
        )
        FasePartitionState.objects.create(
            fase=phase,
            partition_key="global",
            status=FasePartitionState.Status.GENERATED,
        )

        response = self.client.get(f"{self._common_planner_url(self.comp_aparell)}&phase={phase.id}")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="confirm_partition"')
        self.assertContains(response, f'value="{unit.id}"')
        self.assertContains(response, "Confirmar partició")

    def test_planner_formats_generated_partition_label(self):
        phase = self._create_phase()
        FasePartitionState.objects.create(
            fase=phase,
            partition_key="categoria:PREBENJAMÍ|subcategoria:MASCULÍ",
            status=FasePartitionState.Status.GENERATED,
        )

        response = self.client.get(f"{self._common_planner_url(self.comp_aparell)}&phase={phase.id}")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "PREBENJAMÍ | MASCULÍ")
        self.assertNotContains(response, "<strong>categoria:PREBENJAMÍ")
        self.assertNotContains(response, "<strong>subcategoria:MASCULÍ")

    def test_post_apply_qualification_updates_existing_snapshot_without_checkbox(self):
        phase = self._create_phase()
        phase.config = {
            "qualification": {
                "run_id": 123,
                "snapshot_hash": "old",
            }
        }
        phase.save(update_fields=["config", "updated_at"])
        preview = SimpleNamespace(
            summary=Mock(
                return_value={
                    "candidates": 4,
                    "slots": 4,
                    "units": 2,
                }
            )
        )
        service = Mock(return_value=preview)

        with patch("competicions_trampoli.views.competition.fases.actions.apply_qualification", service):
            response = self.client.post(
                self._planner_url(),
                data={"action": "apply_qualification", "fase_id": phase.id},
                follow=True,
            )

        self.assertEqual(response.status_code, 200)
        service.assert_called_once_with(
            phase,
            partition_keys=None,
            replace_existing=True,
            allow_replace_protected=False,
        )
        self.assertContains(response, "Snapshot actualitzat per")
        self.assertContains(response, "slots existents")

    def test_post_delete_phase_only_removes_empty_leaf_phase(self):
        phase = self._create_phase()

        response = self.client.post(
            self._common_planner_url(self.comp_aparell),
            data={"action": "delete_phase", "fase_id": phase.id},
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(CompeticioAparellFase.objects.filter(pk=phase.id).exists())

    def test_post_delete_phase_branch_removes_descendants_without_rotacions(self):
        phase = self._create_phase()
        child = self._create_phase(nom="Final", codi="FIN", parent=phase, ordre=3)
        parent_unit = create_program_unit_with_empty_slots(
            fase=phase,
            nom="Semifinal pendent",
            capacity=1,
            tipus=ProgramUnit.Tipus.BLOCK,
        )
        child_unit = create_program_unit_with_empty_slots(
            fase=child,
            nom="Final pendent",
            capacity=1,
            tipus=ProgramUnit.Tipus.BLOCK,
        )

        response = self.client.post(
            self._common_planner_url(self.comp_aparell),
            data={
                "action": "delete_phase_branch",
                "fase_id": phase.id,
                "confirm_branch_delete": "1",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(CompeticioAparellFase.objects.filter(pk__in=[phase.id, child.id]).exists())
        self.assertFalse(ProgramUnit.objects.filter(pk__in=[parent_unit.id, child_unit.id]).exists())

    def test_post_delete_phase_branch_requires_confirmation(self):
        phase = self._create_phase()

        response = self.client.post(
            self._common_planner_url(self.comp_aparell),
            data={"action": "delete_phase_branch", "fase_id": phase.id},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(CompeticioAparellFase.objects.filter(pk=phase.id).exists())
        messages = [str(message) for message in get_messages(response.wsgi_request)]
        self.assertTrue(any("Cal confirmar l'eliminació" in message for message in messages))

    def test_post_delete_phase_branch_blocks_programmed_descendant(self):
        phase = self._create_phase()
        child = self._create_phase(nom="Final", codi="FIN", parent=phase, ordre=3)
        child_unit = create_program_unit_with_empty_slots(
            fase=child,
            nom="Final programada",
            capacity=1,
            tipus=ProgramUnit.Tipus.BLOCK,
        )
        self._place_program_unit_in_rotacions(child_unit)

        response = self.client.post(
            self._common_planner_url(self.comp_aparell),
            data={
                "action": "delete_phase_branch",
                "fase_id": phase.id,
                "confirm_branch_delete": "1",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(CompeticioAparellFase.objects.filter(pk=phase.id).exists())
        self.assertTrue(CompeticioAparellFase.objects.filter(pk=child.id).exists())
        messages = [str(message) for message in get_messages(response.wsgi_request)]
        self.assertTrue(any("programades a rotacions" in message for message in messages))

    def test_phase_tree_disables_branch_delete_when_descendant_is_programmed(self):
        phase = self._create_phase()
        child = self._create_phase(nom="Final", codi="FIN", parent=phase, ordre=3)
        child_unit = create_program_unit_with_empty_slots(
            fase=child,
            nom="Final programada",
            capacity=1,
            tipus=ProgramUnit.Tipus.BLOCK,
        )
        self._place_program_unit_in_rotacions(child_unit)

        response = self.client.get(f"{self._common_planner_url(self.comp_aparell)}&phase={phase.id}")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Hi ha unitats d'aquesta branca programades a rotacions.")

    def test_post_update_phase_status_changes_status(self):
        phase = self._create_phase()

        response = self.client.post(
            self._common_planner_url(self.comp_aparell),
            data={
                "action": "update_phase_status",
                "fase_id": phase.id,
                "estat": CompeticioAparellFase.Estat.CLOSED,
            },
        )

        self.assertEqual(response.status_code, 302)
        phase.refresh_from_db()
        self.assertEqual(phase.estat, CompeticioAparellFase.Estat.CLOSED)

    def test_generated_phase_is_shown_as_planned_with_publish_action(self):
        phase = self._create_phase()
        phase.estat = CompeticioAparellFase.Estat.GENERATED
        phase.config = {"qualification": {"run_id": 123, "snapshot_hash": "stable"}}
        phase.save(update_fields=["estat", "config", "updated_at"])
        inscripcio = self._create_inscripcio(self.competicio, "Semifinalista")
        create_program_unit_from_subjects(
            fase=phase,
            nom="Semifinal Global",
            subjects=[SlotSubject("inscripcio", inscripcio.id)],
            tipus=ProgramUnit.Tipus.BLOCK,
        )

        with patch("competicions_trampoli.services.fases.dashboard.qualification_is_stale", Mock(return_value=False)):
            with patch("competicions_trampoli.services.fases.dashboard.qualification_source_changed", Mock(return_value=False)):
                response = self.client.get(f"{self._common_planner_url(self.comp_aparell)}&phase={phase.id}")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Planificada")
        self.assertContains(response, "Publicar")
        self.assertContains(response, 'name="estat" value="published"')
        self.assertNotContains(response, "No es pot publicar encara")

    def test_post_publish_generated_phase_from_card(self):
        phase = self._create_phase()
        phase.estat = CompeticioAparellFase.Estat.GENERATED
        phase.config = {"qualification": {"run_id": 123, "snapshot_hash": "stable"}}
        phase.save(update_fields=["estat", "config", "updated_at"])
        inscripcio = self._create_inscripcio(self.competicio, "Semifinalista")
        unit = create_program_unit_from_subjects(
            fase=phase,
            nom="Semifinal Global",
            subjects=[SlotSubject("inscripcio", inscripcio.id)],
            tipus=ProgramUnit.Tipus.BLOCK,
        )

        response = self.client.post(
            self._common_planner_url(self.comp_aparell),
            data={
                "action": "update_phase_status",
                "fase_id": phase.id,
                "estat": CompeticioAparellFase.Estat.PUBLISHED,
            },
        )

        self.assertEqual(response.status_code, 302)
        phase.refresh_from_db()
        unit.refresh_from_db()
        self.assertEqual(phase.estat, CompeticioAparellFase.Estat.PUBLISHED)
        self.assertEqual(unit.status, ProgramUnit.Status.PUBLISHED)

    def test_source_changed_snapshot_does_not_block_phase_publication(self):
        phase = self._create_phase()
        phase.estat = CompeticioAparellFase.Estat.STALE
        phase.config = {
            "qualification": {
                "run_id": 123,
                "snapshot_hash": "frozen",
                "stale": True,
            }
        }
        phase.save(update_fields=["estat", "config", "updated_at"])
        inscripcio = self._create_inscripcio(self.competicio, "Snapshot estatic")
        unit = create_program_unit_from_subjects(
            fase=phase,
            nom="Final estatica",
            subjects=[SlotSubject("inscripcio", inscripcio.id)],
            tipus=ProgramUnit.Tipus.BLOCK,
            status=ProgramUnit.Status.GENERATED,
        )
        FasePartitionState.objects.create(
            fase=phase,
            partition_key="global",
            status=FasePartitionState.Status.STALE,
            source_snapshot_hash="frozen",
        )

        response = self.client.post(
            self._common_planner_url(self.comp_aparell),
            data={
                "action": "update_phase_status",
                "fase_id": phase.id,
                "estat": CompeticioAparellFase.Estat.PUBLISHED,
            },
        )

        self.assertEqual(response.status_code, 302)
        phase.refresh_from_db()
        unit.refresh_from_db()
        self.assertEqual(phase.estat, CompeticioAparellFase.Estat.PUBLISHED)
        self.assertEqual(unit.status, ProgramUnit.Status.PUBLISHED)

    def test_post_confirm_publish_and_unpublish_program_unit(self):
        phase = self._create_phase()
        phase.estat = CompeticioAparellFase.Estat.GENERATED
        phase.config = {"qualification": {"run_id": 123, "snapshot_hash": "stable"}}
        phase.save(update_fields=["estat", "config", "updated_at"])
        inscripcio = self._create_inscripcio(self.competicio, "Finalista")
        unit = create_program_unit_from_subjects(
            fase=phase,
            nom="Final unitat",
            subjects=[SlotSubject("inscripcio", inscripcio.id)],
            tipus=ProgramUnit.Tipus.BLOCK,
            status=ProgramUnit.Status.GENERATED,
        )

        confirm = self.client.post(
            self._common_planner_url(self.comp_aparell),
            data={
                "action": "confirm_program_unit",
                "fase_id": phase.id,
                "unit_id": unit.id,
            },
        )

        self.assertEqual(confirm.status_code, 302)
        unit.refresh_from_db()
        self.assertEqual(unit.status, ProgramUnit.Status.CONFIRMED)

        publish = self.client.post(
            self._common_planner_url(self.comp_aparell),
            data={
                "action": "publish_program_unit",
                "fase_id": phase.id,
                "unit_id": unit.id,
            },
        )

        self.assertEqual(publish.status_code, 302)
        unit.refresh_from_db()
        self.assertEqual(unit.status, ProgramUnit.Status.PUBLISHED)

        unpublish = self.client.post(
            self._common_planner_url(self.comp_aparell),
            data={
                "action": "unpublish_program_unit",
                "fase_id": phase.id,
                "unit_id": unit.id,
            },
        )

        self.assertEqual(unpublish.status_code, 302)
        unit.refresh_from_db()
        self.assertEqual(unit.status, ProgramUnit.Status.CONFIRMED)

    def test_source_changed_partition_does_not_block_unit_publication(self):
        phase = self._create_phase()
        phase.estat = CompeticioAparellFase.Estat.STALE
        phase.config = {
            "qualification": {
                "run_id": 123,
                "snapshot_hash": "frozen",
                "stale": True,
            }
        }
        phase.save(update_fields=["estat", "config", "updated_at"])
        inscripcio = self._create_inscripcio(self.competicio, "Finalista stale")
        unit = create_program_unit_from_subjects(
            fase=phase,
            nom="Final stale",
            partition_key="categoria:Cadet",
            subjects=[SlotSubject("inscripcio", inscripcio.id)],
            tipus=ProgramUnit.Tipus.BLOCK,
            status=ProgramUnit.Status.GENERATED,
        )
        FasePartitionState.objects.create(
            fase=phase,
            partition_key="categoria:Cadet",
            status=FasePartitionState.Status.STALE,
            source_snapshot_hash="frozen",
        )

        response = self.client.post(
            self._common_planner_url(self.comp_aparell),
            data={
                "action": "publish_program_unit",
                "fase_id": phase.id,
                "unit_id": unit.id,
            },
        )

        self.assertEqual(response.status_code, 302)
        unit.refresh_from_db()
        self.assertEqual(unit.status, ProgramUnit.Status.PUBLISHED)

    def test_post_update_phase_status_rejects_invalid_status(self):
        phase = self._create_phase()

        response = self.client.post(
            self._common_planner_url(self.comp_aparell),
            data={
                "action": "update_phase_status",
                "fase_id": phase.id,
                "estat": "not-a-status",
            },
        )

        self.assertEqual(response.status_code, 302)
        phase.refresh_from_db()
        self.assertEqual(phase.estat, CompeticioAparellFase.Estat.PLANNED)

    def test_post_update_phase_scoring_settings_stores_exercise_override(self):
        phase = self._create_phase()

        response = self.client.post(
            self._common_planner_url(self.comp_aparell),
            data={
                "action": "update_phase_scoring_settings",
                "fase_id": phase.id,
                "nombre_exercicis": 3,
            },
        )

        self.assertEqual(response.status_code, 302)
        phase.refresh_from_db()
        self.assertEqual(phase.config["scoring"]["nombre_exercicis"], 3)

        page = self.client.get(f"{self._common_planner_url(self.comp_aparell)}&phase={phase.id}")
        self.assertContains(page, "3 exercici(s)")

    def test_post_publish_phase_requires_prepared_flow(self):
        phase = self._create_phase()

        response = self.client.post(
            self._common_planner_url(self.comp_aparell),
            data={
                "action": "update_phase_status",
                "fase_id": phase.id,
                "estat": CompeticioAparellFase.Estat.PUBLISHED,
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        phase.refresh_from_db()
        self.assertEqual(phase.estat, CompeticioAparellFase.Estat.PLANNED)
        messages = [str(message) for message in get_messages(response.wsgi_request)]
        self.assertTrue(any("No es pot publicar encara" in message for message in messages))

    def test_post_delete_phase_keeps_phase_with_units(self):
        phase = self._create_phase()
        create_program_unit_with_empty_slots(
            fase=phase,
            nom="Bloc protegit",
            capacity=1,
            tipus=ProgramUnit.Tipus.BLOCK,
        )

        response = self.client.post(
            self._common_planner_url(self.comp_aparell),
            data={"action": "delete_phase", "fase_id": phase.id},
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(CompeticioAparellFase.objects.filter(pk=phase.id).exists())

    def test_changing_structural_cut_marks_existing_group_plan_stale(self):
        phase = self._create_phase()
        cfg = ClassificacioConfig.objects.create(
            competicio=self.competicio,
            nom="Preliminar TRA",
            activa=True,
            ordre=1,
            tipus="individual",
            schema={},
        )
        phase.config = {
            "source": {"classificacio_id": cfg.id, "classificacio_nom": cfg.nom, "tipus": cfg.tipus},
            "cut": {
                "mode": "top_n",
                "qualifiers_count": 8,
                "reserve_count": 0,
                "partition_mode": "global",
                "tie_policy": "classification_order",
                "unit_capacity": 8,
                "unit_name_template": "{fase} - {particio}",
            },
            "group_plan": {"stale": False},
        }
        phase.save(update_fields=["config", "updated_at"])
        create_program_unit_with_empty_slots(
            fase=phase,
            nom="Semifinal Global",
            capacity=8,
            tipus=ProgramUnit.Tipus.BLOCK,
            partition_key="global",
        )

        response = self.client.post(
            self._planner_url(),
            data={
                "action": "configure_source_cut",
                "fase_id": phase.id,
                "classificacio": cfg.id,
                "cut_mode": "top_n",
                "qualifiers_count": 10,
                "reserve_count": 0,
                "partition_mode": "global",
                "tie_policy": "classification_order",
                "unit_capacity": 8,
                "unit_name_template": "{fase} - {particio}",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        phase.refresh_from_db()
        self.assertTrue(phase.config["group_plan"]["stale"])
        self.assertContains(response, "Revisar grups")

    def test_post_update_program_unit_changes_capacity_and_strategy(self):
        phase = self._create_phase()
        unit = create_program_unit_with_empty_slots(
            fase=phase,
            nom="Semifinal Global",
            capacity=2,
            tipus=ProgramUnit.Tipus.BLOCK,
            partition_key="global",
        )

        response = self.client.post(
            self._planner_url(),
            data={
                "action": "update_program_unit",
                "fase_id": phase.id,
                "unit_id": unit.id,
                "nom": "Semifinal Grup A",
                "capacity": 3,
                "formation_strategy": "serpentine",
            },
        )

        self.assertEqual(response.status_code, 302)
        unit.refresh_from_db()
        self.assertEqual(unit.nom, "Semifinal Grup A")
        self.assertEqual(unit.capacity, 3)
        self.assertEqual(unit.metadata["formation_strategy"], "serpentine")
        self.assertEqual(unit.slots.count(), 3)

    def test_post_create_manual_unit_creates_empty_slots(self):
        fase = self._create_phase()
        response = self.client.post(
            self._planner_url(),
            data={
                "action": "create_manual_unit",
                "fase_id": fase.id,
                "nom": "Final Infantil F",
                "capacity": 3,
                "tipus": ProgramUnit.Tipus.CUSTOM,
                "partition_key": "categoria=Infantil|subcategoria=F",
            },
        )

        self.assertEqual(response.status_code, 302)
        unit = ProgramUnit.objects.get(fase=fase, nom="Final Infantil F")
        self.assertEqual(unit.capacity, 3)
        self.assertEqual(unit.slots.count(), 3)
        self.assertEqual(unit.slots.filter(status=ProgramUnitSlot.Status.EMPTY).count(), 3)

    def test_post_partition_unit_creates_partition_slots(self):
        fase = self._create_phase()
        response = self.client.post(
            self._planner_url(),
            data={
                "action": "create_partition_unit",
                "fase_id": fase.id,
                "label": "Infantil F",
                "key": "categoria=Infantil|subcategoria=F",
                "capacity": 4,
            },
        )

        self.assertEqual(response.status_code, 302)
        unit = ProgramUnit.objects.get(fase=fase, nom="Infantil F")
        self.assertEqual(unit.partition_key, "categoria=Infantil|subcategoria=F")
        self.assertEqual(unit.capacity, 4)
        self.assertEqual(unit.slots.count(), 4)
