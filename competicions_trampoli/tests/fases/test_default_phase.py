from django.core.exceptions import ValidationError
from django.test import TestCase

from ..base import _BaseTrampoliDataMixin
from ...models.competicio import CompeticioAparell, CompeticioAparellFase


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

    def test_comp_aparell_does_not_create_phase_by_default(self):
        comp_aparell = self._create_comp_app()

        self.assertFalse(CompeticioAparellFase.objects.filter(comp_aparell=comp_aparell).exists())

    def test_default_code_is_reserved_for_implicit_initial_phase(self):
        comp_aparell = self._create_comp_app()
        phase = CompeticioAparellFase(
            competicio=self.competicio,
            comp_aparell=comp_aparell,
            nom="Fase unica",
            codi="DEFAULT",
        )

        with self.assertRaises(ValidationError) as ctx:
            phase.full_clean()
        self.assertIn("codi", ctx.exception.message_dict)

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
