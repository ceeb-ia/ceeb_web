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
from ...services.fases import create_program_unit_with_empty_slots
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

        response = self.client.get(self._planner_url())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["competicio"], self.competicio)
        self.assertEqual(response.context["comp_aparell"], self.comp_aparell)
        self.assertIn(fase, list(response.context["phases"]))
        body = response.content.decode("utf-8")
        self.assertNotIn("Fase unica", body)
        self.assertIn("DEFAULT reservat", body)
        self.assertIn("Semifinal Grup 1", body)
        self.assertNotIn("score-inputs-must-not-leak", body)
        self.assertNotIn("scores", response.context)
        self.assertNotIn("team_scores", response.context)

    def test_planner_does_not_create_default_phase_on_get(self):
        response = self.client.get(self._planner_url())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(CompeticioAparellFase.objects.filter(comp_aparell=self.comp_aparell).count(), 0)
        self.assertContains(response, "La preliminar/default no es crea aqui")

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

        response = self.client.get(self._common_planner_url(second_app))

        self.assertEqual(response.status_code, 200)
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

        response = self.client.get(self._common_planner_url(self.comp_aparell))

        self.assertEqual(response.status_code, 200)
        body = response.content.decode("utf-8")
        self.assertIn("Semifinal Programada", body)
        self.assertIn("Semifinal Pendent", body)
        self.assertIn("Programat", body)
        self.assertIn("Pendent de programar", body)

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

        page = self.client.get(self._common_planner_url(self.comp_aparell))
        self.assertContains(page, "Preliminar TRA")
        self.assertContains(page, "Top 8 + 2 reserves")

    def test_planner_exposes_qualification_actions(self):
        self._create_phase()

        response = self.client.get(self._common_planner_url(self.comp_aparell))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="preview_qualification"')
        self.assertContains(response, 'value="apply_qualification"')
        self.assertContains(response, 'value="regenerate_qualification"')
        self.assertContains(response, "Generar unitats")
        self.assertContains(response, "Aplicar tall i crear unitats")

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
        service.assert_called_once_with(phase, replace_existing=False, allow_replace_protected=False)
        self.assertContains(response, "Tall congelat per")

    def test_post_confirm_partition_calls_service_when_available(self):
        phase = self._create_phase()
        state = SimpleNamespace(partition_key="global")
        service = Mock(return_value=state)

        with patch("competicions_trampoli.views.competition.fases.actions.confirm_qualification_partition", service):
            response = self.client.post(
                self._planner_url(),
                data={"action": "confirm_partition", "fase_id": phase.id, "partition_key": "global"},
                follow=True,
            )

        self.assertEqual(response.status_code, 200)
        service.assert_called_once_with(phase, "global")
        messages = [str(message) for message in get_messages(response.wsgi_request)]
        self.assertIn("Particio 'global' confirmada per 'Semifinal'.", messages)

    def test_planner_shows_generated_partition_confirmation_action(self):
        phase = self._create_phase()
        FasePartitionState.objects.create(
            fase=phase,
            partition_key="global",
            status=FasePartitionState.Status.GENERATED,
        )

        response = self.client.get(self._common_planner_url(self.comp_aparell))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="confirm_partition"')
        self.assertContains(response, "Confirmar particio")

    def test_post_regenerate_qualification_requires_explicit_confirmation(self):
        phase = self._create_phase()
        service = Mock()

        with patch("competicions_trampoli.views.competition.fases.actions.apply_qualification", service):
            response = self.client.post(
                self._planner_url(),
                data={"action": "regenerate_qualification", "fase_id": phase.id},
                follow=True,
            )

        self.assertEqual(response.status_code, 200)
        service.assert_not_called()
        messages = [str(message) for message in get_messages(response.wsgi_request)]
        self.assertIn("Cal confirmar explicitament la regeneracio abans de substituir la proposta.", messages)

    def test_post_regenerate_qualification_calls_service_with_replace_existing(self):
        phase = self._create_phase()
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

        with patch("competicions_trampoli.views.competition.fases.actions.qualification_is_stale", Mock(return_value=True)):
            with patch("competicions_trampoli.views.competition.fases.actions.apply_qualification", service):
                response = self.client.post(
                    self._planner_url(),
                    data={
                        "action": "regenerate_qualification",
                        "fase_id": phase.id,
                        "confirm_regeneration": "1",
                    },
                    follow=True,
                )

        self.assertEqual(response.status_code, 200)
        service.assert_called_once_with(phase, replace_existing=True, allow_replace_protected=False)
        self.assertContains(response, "Proposta actualitzada per")

    def test_post_delete_phase_only_removes_empty_leaf_phase(self):
        phase = self._create_phase()

        response = self.client.post(
            self._common_planner_url(self.comp_aparell),
            data={"action": "delete_phase", "fase_id": phase.id},
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(CompeticioAparellFase.objects.filter(pk=phase.id).exists())

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
