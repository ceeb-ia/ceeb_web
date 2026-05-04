from django.core.exceptions import ValidationError
from django.test import TestCase

from ..base import _BaseTrampoliDataMixin
from ._contract import get_phase_model


class CompeticioAparellFaseModelContractTests(_BaseTrampoliDataMixin, TestCase):
    def setUp(self):
        self.comp = self._create_competicio("Comp fases")
        self.other_comp = self._create_competicio("Comp fases altra")
        self.aparell = self._create_aparell("TRA", "Trampoli")
        self.comp_aparell = self._create_comp_aparell(
            self.comp,
            self.aparell,
            ordre=1,
        )
        self.other_comp_aparell = self._create_comp_aparell(
            self.other_comp,
            self.aparell,
            ordre=1,
        )

    def test_model_declares_minimal_phase_fields(self):
        Fase = get_phase_model()

        field_names = {field.name for field in Fase._meta.get_fields()}

        self.assertTrue(
            {
                "competicio",
                "comp_aparell",
                "parent",
                "nom",
                "codi",
                "ordre",
                "estat",
                "config",
                "created_at",
                "updated_at",
            }.issubset(field_names)
        )

    def test_phase_is_scoped_to_one_competicio_aparell(self):
        Fase = get_phase_model()

        fase = Fase.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_aparell,
            nom="Preliminar",
            codi="PRE",
            ordre=1,
            estat="planned",
            config={"source_mode": "initial"},
        )

        self.assertEqual(fase.competicio_id, self.comp.id)
        self.assertEqual(fase.comp_aparell_id, self.comp_aparell.id)
        self.assertIsNone(fase.parent_id)
        self.assertEqual(fase.config, {"source_mode": "initial"})

    def test_phase_rejects_comp_aparell_from_another_competition(self):
        Fase = get_phase_model()
        fase = Fase(
            competicio=self.comp,
            comp_aparell=self.other_comp_aparell,
            nom="Fase creuada",
            codi="BAD-COMP",
            ordre=1,
            estat="planned",
            config={},
        )

        with self.assertRaises(ValidationError):
            fase.full_clean()

    def test_parent_must_belong_to_same_competicio_aparell(self):
        Fase = get_phase_model()
        parent = Fase.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_aparell,
            nom="Preliminar",
            codi="PRE",
            ordre=1,
            estat="planned",
            config={},
        )
        child = Fase(
            competicio=self.other_comp,
            comp_aparell=self.other_comp_aparell,
            parent=parent,
            nom="Final",
            codi="FIN",
            ordre=2,
            estat="planned",
            config={},
        )

        with self.assertRaises(ValidationError):
            child.full_clean()

    def test_phase_code_is_unique_inside_competicio_aparell_only(self):
        Fase = get_phase_model()
        Fase.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_aparell,
            nom="Preliminar",
            codi="PRE",
            ordre=1,
            estat="planned",
            config={},
        )

        duplicate_same_app = Fase(
            competicio=self.comp,
            comp_aparell=self.comp_aparell,
            nom="Preliminar duplicada",
            codi="PRE",
            ordre=2,
            estat="planned",
            config={},
        )
        same_code_other_app = Fase(
            competicio=self.other_comp,
            comp_aparell=self.other_comp_aparell,
            nom="Preliminar altra",
            codi="PRE",
            ordre=1,
            estat="planned",
            config={},
        )

        with self.assertRaises(ValidationError):
            duplicate_same_app.full_clean()
        same_code_other_app.full_clean()
