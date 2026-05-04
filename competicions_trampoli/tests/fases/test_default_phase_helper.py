from django.test import TestCase

from ..base import _BaseTrampoliDataMixin
from ._contract import get_default_phase_helper, get_phase_model


class DefaultPhaseHelperContractTests(_BaseTrampoliDataMixin, TestCase):
    def setUp(self):
        self.comp = self._create_competicio("Comp fase default")
        self.aparell = self._create_aparell("TRA", "Trampoli")
        self.comp_aparell = self._create_comp_aparell(
            self.comp,
            self.aparell,
            ordre=1,
        )

    def test_ensure_default_phase_creates_single_legacy_phase(self):
        Fase = get_phase_model()
        ensure_default_phase_for_comp_aparell = get_default_phase_helper()

        fase = ensure_default_phase_for_comp_aparell(self.comp_aparell)

        self.assertIsInstance(fase, Fase)
        self.assertEqual(fase.competicio_id, self.comp.id)
        self.assertEqual(fase.comp_aparell_id, self.comp_aparell.id)
        self.assertIsNone(fase.parent_id)
        self.assertEqual(fase.nom, "Fase unica")
        self.assertEqual(fase.codi, "DEFAULT")
        self.assertEqual(fase.ordre, 1)
        self.assertIsInstance(fase.config, dict)
        self.assertEqual(
            Fase.objects.filter(comp_aparell=self.comp_aparell, codi="DEFAULT").count(),
            1,
        )

    def test_ensure_default_phase_is_idempotent(self):
        Fase = get_phase_model()
        ensure_default_phase_for_comp_aparell = get_default_phase_helper()

        first = ensure_default_phase_for_comp_aparell(self.comp_aparell)
        second = ensure_default_phase_for_comp_aparell(self.comp_aparell)

        self.assertEqual(second.id, first.id)
        self.assertEqual(Fase.objects.filter(comp_aparell=self.comp_aparell).count(), 1)

    def test_default_phase_is_separate_for_each_local_aparell_instance(self):
        Fase = get_phase_model()
        ensure_default_phase_for_comp_aparell = get_default_phase_helper()
        second_comp_aparell = self._create_comp_aparell(
            self.comp,
            self.aparell,
            ordre=2,
        )

        first_phase = ensure_default_phase_for_comp_aparell(self.comp_aparell)
        second_phase = ensure_default_phase_for_comp_aparell(second_comp_aparell)

        self.assertNotEqual(first_phase.id, second_phase.id)
        self.assertEqual(
            set(Fase.objects.values_list("comp_aparell_id", flat=True)),
            {self.comp_aparell.id, second_comp_aparell.id},
        )
