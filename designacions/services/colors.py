# designacions_app/services/colors.py
import hashlib

def color_per_tutor(tutor_code: str | None) -> str:
    """
    Color estable per tutor. Si no n'hi ha -> gris.
    """
    if not tutor_code or not str(tutor_code).strip():
        return "#808080"
    h = hashlib.md5(str(tutor_code).encode("utf-8")).hexdigest()
    return "#" + h[:6]
