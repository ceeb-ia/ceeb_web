from django.apps import apps


PHASE_MODEL_NAME = "CompeticioAparellFase"


def get_phase_model():
    try:
        return apps.get_model("competicions_trampoli", PHASE_MODEL_NAME)
    except LookupError as exc:
        raise AssertionError(
            "Fase 2 must register model competicions_trampoli.CompeticioAparellFase"
        ) from exc
