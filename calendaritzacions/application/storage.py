"""Storage helpers for calendarization outputs."""

from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path


def finalize_result_path(excel_path, logs: list[str], media_root: str | None = None) -> str:
    """Move/copy a generated result into MEDIA_ROOT using legacy behavior."""
    try:
        if isinstance(excel_path, (str, Path)) and os.path.exists(str(excel_path)):
            media_root = media_root or os.getenv("MEDIA_ROOT", "/data/results")
            os.makedirs(media_root, exist_ok=True)
            basename = os.path.basename(str(excel_path))
            dest_path = os.path.join(media_root, basename)
            if os.path.exists(dest_path):
                name, ext = os.path.splitext(basename)
                suffix = hashlib.sha1(basename.encode()).hexdigest()[:8]
                dest_path = os.path.join(media_root, f"{name}_{suffix}{ext}")
                logs.append(
                    "El fitxer de resultat ja existia a MEDIA_ROOT; "
                    f"s'ha afegit un sufix per evitar sobreescriptura: {os.path.basename(dest_path)}"
                )
            try:
                shutil.move(str(excel_path), dest_path)
                excel_path = dest_path
                logs.append(f"Fitxer de resultat mogut a MEDIA_ROOT: {os.path.basename(dest_path)}")
            except Exception:
                try:
                    shutil.copy(str(excel_path), dest_path)
                    excel_path = dest_path
                    logs.append(f"Fitxer de resultat copiat a MEDIA_ROOT: {os.path.basename(dest_path)}")
                except Exception:
                    excel_path = str(excel_path)
                    logs.append("Warning: no s'ha pogut moure ni copiar el fitxer de resultat a MEDIA_ROOT.")
    except Exception:
        logs.append("Warning: no s'ha pogut moure el fitxer de resultat a MEDIA_ROOT.")
        pass

    return str(excel_path)
