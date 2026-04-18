from django.test import TestCase

from ...models.scoring import ScoringSchema
from ...services.classificacions.validation import validate_schema_for_competicio
from ..base import _BaseTrampoliDataMixin


class PerExerciseScoringFieldsValidationTests(_BaseTrampoliDataMixin, TestCase):
    def setUp(self):
        self.comp = self._create_competicio("Comp per exercise validation")
        self.app_a = self._create_aparell("APP_A", "Aparell A")
        self.app_b = self._create_aparell("APP_B", "Aparell B")
        self.comp_app_a = self._create_comp_aparell(self.comp, self.app_a, ordre=1, actiu=True)
        self.comp_app_b = self._create_comp_aparell(self.comp, self.app_b, ordre=2, actiu=True)

        ScoringSchema.objects.create(
            aparell=self.app_a,
            schema={
                "fields": [
                    {"code": "D", "type": "number"},
                    {"code": "E", "type": "number"},
                    {
                        "code": "M",
                        "type": "matrix",
                        "shape": "judge_x_item",
                        "judges": {"count": 2},
                        "items": {"count": 2},
                    },
                ],
                "computed": [],
            },
        )
        ScoringSchema.objects.create(
            aparell=self.app_b,
            schema={
                "fields": [
                    {"code": "X", "type": "number"},
                ],
                "computed": [],
            },
        )

    def _base_schema(self):
        return {
            "particions": [],
            "filtres": {},
            "puntuacio": {
                "aparells": {"mode": "seleccionar", "ids": [self.comp_app_a.id]},
                "camps_per_aparell": {str(self.comp_app_a.id): ["D"]},
                "agregacio_camps": "sum",
                "exercicis": {"mode": "tots"},
                "exercicis_best_n": 1,
                "agregacio_exercicis": "sum",
                "agregacio_aparells": "sum",
                "ordre": "desc",
                "camp": "total",
                "agregacio": "sum",
                "best_n": 1,
            },
            "desempat": [],
            "presentacio": {"top_n": 0, "mostrar_empats": True},
        }

    def _validate(self, schema):
        _normalized, errors = validate_schema_for_competicio(self.comp, schema, tipus="individual")
        return errors

    def assertHasError(self, errors, fragment):
        self.assertTrue(any(fragment in err for err in errors), msg=f"Missing error '{fragment}' in {errors}")

    def test_accepts_per_exercise_scoring_fields_with_partial_fallback(self):
        schema = self._base_schema()
        schema["puntuacio"]["camps_mode_per_aparell"] = {str(self.comp_app_a.id): "per_exercici"}
        schema["puntuacio"]["camps_per_exercici_per_aparell"] = {
            str(self.comp_app_a.id): {
                "1": ["D"],
                "2": ["E"],
            }
        }
        schema["puntuacio"]["agregacio_camps_per_exercici_per_aparell"] = {
            str(self.comp_app_a.id): {
                "1": "sum",
            }
        }

        errors = self._validate(schema)
        self.assertEqual(errors, [])

    def test_rejects_invalid_mode_value(self):
        schema = self._base_schema()
        schema["puntuacio"]["camps_mode_per_aparell"] = {str(self.comp_app_a.id): "invalid_mode"}

        errors = self._validate(schema)
        self.assertHasError(errors, f"puntuacio.camps_mode_per_aparell[{self.comp_app_a.id}] invalid")

    def test_rejects_non_object_per_exercise_maps_when_mode_requires_them(self):
        schema = self._base_schema()
        schema["puntuacio"]["camps_mode_per_aparell"] = {str(self.comp_app_a.id): "per_exercici"}
        schema["puntuacio"]["camps_per_exercici_per_aparell"] = "broken"
        schema["puntuacio"]["agregacio_camps_per_exercici_per_aparell"] = "broken"

        errors = self._validate(schema)
        self.assertHasError(errors, "puntuacio.camps_per_exercici_per_aparell ha de ser un objecte")
        self.assertHasError(errors, "puntuacio.agregacio_camps_per_exercici_per_aparell ha de ser un objecte")

    def test_rejects_invalid_exercise_keys(self):
        schema = self._base_schema()
        schema["puntuacio"]["camps_mode_per_aparell"] = {str(self.comp_app_a.id): "per_exercici"}
        schema["puntuacio"]["camps_per_exercici_per_aparell"] = {
            str(self.comp_app_a.id): {
                "0": ["D"],
            }
        }
        schema["puntuacio"]["agregacio_camps_per_exercici_per_aparell"] = {
            str(self.comp_app_a.id): {
                "abc": "sum",
            }
        }

        errors = self._validate(schema)
        self.assertHasError(errors, f"puntuacio.camps_per_exercici_per_aparell[{self.comp_app_a.id}]: exercici invalid 0")
        self.assertHasError(
            errors,
            f"puntuacio.agregacio_camps_per_exercici_per_aparell[{self.comp_app_a.id}]: exercici invalid abc",
        )

    def test_rejects_non_scoreable_fields_for_exercise_override(self):
        schema = self._base_schema()
        schema["puntuacio"]["camps_mode_per_aparell"] = {str(self.comp_app_a.id): "per_exercici"}
        schema["puntuacio"]["camps_per_exercici_per_aparell"] = {
            str(self.comp_app_a.id): {
                "1": ["M"],
            }
        }

        errors = self._validate(schema)
        self.assertHasError(
            errors,
            f"puntuacio.camps_per_exercici_per_aparell[{self.comp_app_a.id}][1]: camp 'M' no es puntuable directament",
        )

    def test_rejects_invalid_per_exercise_aggregation_value(self):
        schema = self._base_schema()
        schema["puntuacio"]["camps_mode_per_aparell"] = {str(self.comp_app_a.id): "per_exercici"}
        schema["puntuacio"]["agregacio_camps_per_exercici_per_aparell"] = {
            str(self.comp_app_a.id): {
                "1": "weird",
            }
        }

        errors = self._validate(schema)
        self.assertHasError(
            errors,
            f"puntuacio.agregacio_camps_per_exercici_per_aparell[{self.comp_app_a.id}][1] invalid: weird",
        )

    def test_ignores_per_exercise_maps_when_mode_is_comu(self):
        schema = self._base_schema()
        schema["puntuacio"]["camps_mode_per_aparell"] = {str(self.comp_app_a.id): "comu"}
        schema["puntuacio"]["camps_per_exercici_per_aparell"] = "broken"
        schema["puntuacio"]["agregacio_camps_per_exercici_per_aparell"] = "broken"

        errors = self._validate(schema)
        self.assertEqual(errors, [])

    def test_ignores_per_exercise_maps_in_victories_mode(self):
        schema = self._base_schema()
        schema["puntuacio"]["mode_resultat_aparells"] = "victories"
        schema["puntuacio"]["camps_mode_per_aparell"] = {str(self.comp_app_a.id): "per_exercici"}
        schema["puntuacio"]["camps_per_exercici_per_aparell"] = "broken"
        schema["puntuacio"]["agregacio_camps_per_exercici_per_aparell"] = "broken"

        errors = self._validate(schema)
        self.assertEqual(errors, [])

    def test_base_camps_per_aparell_remains_mandatory(self):
        schema = self._base_schema()
        schema["puntuacio"]["camps_per_aparell"] = {}
        schema["puntuacio"]["camps_mode_per_aparell"] = {str(self.comp_app_a.id): "per_exercici"}
        schema["puntuacio"]["camps_per_exercici_per_aparell"] = {
            str(self.comp_app_a.id): {
                "1": ["D"],
            }
        }

        errors = self._validate(schema)
        self.assertHasError(errors, f"puntuacio.camps_per_aparell[{self.comp_app_a.id}] ha de contenir almenys un camp real.")
