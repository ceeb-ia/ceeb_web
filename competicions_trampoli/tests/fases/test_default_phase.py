from django.core.exceptions import ValidationError
from django.test import TestCase

from ..base import _BaseTrampoliDataMixin
from ...models.competicio import Aparell, CompeticioAparell, CompeticioAparellFase
from ...services.fases import (
    DEFAULT_PHASE_CODE,
    DEFAULT_PHASE_NAME,
    ensure_default_phase_for_comp_aparell,
    get_default_phase_for_comp_aparell,
)


class CompeticioAparellFaseTests(_BaseTrampoliDataMixin, TestCase):
    def setUp(self):
        self.competicio = self._create_competicio("Comp fases")
        self.aparell = self._create_aparell("TRA", "Trampoli")

    def _create_comp_app(self, *, nom_local="Trampoli", codi_local="TRA", ordre=1):
        return CompeticioAparell.objects.create(
            competicio=self.competicio,
            aparell=self.aparell,
            nom_local=nom_local,
            codi_local=codi_local,
            ordre=ordre,
        )

    def test_ensure_default_phase_creates_legacy_published_phase(self):
        comp_aparell = self._create_comp_app()

        phase = ensure_default_phase_for_comp_aparell(comp_aparell)

        self.assertEqual(phase.competicio_id, self.competicio.id)
        self.assertEqual(phase.comp_aparell_id, comp_aparell.id)
        self.assertEqual(phase.nom, DEFAULT_PHASE_NAME)
        self.assertEqual(phase.codi, DEFAULT_PHASE_CODE)
        self.assertEqual(phase.estat, CompeticioAparellFase.Estat.PUBLISHED)
        self.assertEqual(phase.config.get("source_mode"), "legacy_default")
        self.assertTrue(phase.config.get("implicit"))

    def test_ensure_default_phase_is_idempotent(self):
        comp_aparell = self._create_comp_app()

        first = ensure_default_phase_for_comp_aparell(comp_aparell)
        second = ensure_default_phase_for_comp_aparell(comp_aparell)

        self.assertEqual(first.id, second.id)
        self.assertEqual(CompeticioAparellFase.objects.filter(comp_aparell=comp_aparell).count(), 1)
        self.assertEqual(get_default_phase_for_comp_aparell(comp_aparell).id, first.id)

    def test_local_apparatus_instances_have_independent_default_phases(self):
        first_app = self._create_comp_app(nom_local="Trampoli masculi", codi_local="TRA-M", ordre=1)
        second_app = self._create_comp_app(nom_local="Trampoli femeni", codi_local="TRA-F", ordre=2)

        first_phase = ensure_default_phase_for_comp_aparell(first_app)
        second_phase = ensure_default_phase_for_comp_aparell(second_app)

        self.assertNotEqual(first_phase.id, second_phase.id)
        self.assertEqual(first_phase.comp_aparell_id, first_app.id)
        self.assertEqual(second_phase.comp_aparell_id, second_app.id)
        self.assertEqual(first_phase.codi, DEFAULT_PHASE_CODE)
        self.assertEqual(second_phase.codi, DEFAULT_PHASE_CODE)

    def test_phase_rejects_comp_aparell_from_other_competition(self):
        other_comp = self._create_competicio("Comp aliena")
        other_app = CompeticioAparell.objects.create(
            competicio=other_comp,
            aparell=self.aparell,
            nom_local="Trampoli alie",
            codi_local="TRA-ALT",
        )

        phase = CompeticioAparellFase(
            competicio=self.competicio,
            comp_aparell=other_app,
            nom="Final",
            codi="FINAL",
        )

        with self.assertRaises(ValidationError) as ctx:
            phase.full_clean()
        self.assertIn("comp_aparell", ctx.exception.message_dict)

    def test_phase_rejects_parent_from_other_local_apparatus(self):
        first_app = self._create_comp_app(nom_local="Trampoli masculi", codi_local="TRA-M", ordre=1)
        second_app = self._create_comp_app(nom_local="Trampoli femeni", codi_local="TRA-F", ordre=2)
        parent = CompeticioAparellFase.objects.create(
            competicio=self.competicio,
            comp_aparell=first_app,
            nom="Preliminar",
            codi="PRE",
        )
        child = CompeticioAparellFase(
            competicio=self.competicio,
            comp_aparell=second_app,
            parent=parent,
            nom="Final",
            codi="FINAL",
        )

        with self.assertRaises(ValidationError) as ctx:
            child.full_clean()
        self.assertIn("parent", ctx.exception.message_dict)

    def test_phase_rejects_non_object_config(self):
        comp_aparell = self._create_comp_app()
        phase = CompeticioAparellFase(
            competicio=self.competicio,
            comp_aparell=comp_aparell,
            nom="Preliminar",
            codi="PRE",
            config=[],
        )

        with self.assertRaises(ValidationError) as ctx:
            phase.full_clean()
        self.assertIn("config", ctx.exception.message_dict)

    def test_default_helper_requires_saved_comp_aparell(self):
        unsaved = CompeticioAparell(
            competicio=self.competicio,
            aparell=Aparell(codi="DMT", nom="DMT", created_by=self._ensure_default_aparell_owner()),
        )

        with self.assertRaises(ValueError):
            ensure_default_phase_for_comp_aparell(unsaved)
