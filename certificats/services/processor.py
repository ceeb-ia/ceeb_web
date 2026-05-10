from __future__ import annotations

import logging
import re
import shutil
from collections.abc import Callable
from pathlib import Path

from .progress import noop_progress

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[str, int | None], None]

PDF_EXTS = {".pdf"}

try:
    from pdfminer.high_level import extract_text as pdfminer_extract_text
    from pdfminer.layout import LAParams
except Exception:  # pragma: no cover - depends on optional runtime dependency
    pdfminer_extract_text = None
    LAParams = None

try:
    import PyPDF2
except Exception:  # pragma: no cover - depends on optional runtime dependency
    PyPDF2 = None


def processar_certificats(
    input_dir: str | Path,
    output_dir: str | Path,
    on_progress: ProgressCallback | None = None,
) -> Path | None:
    progress = on_progress or noop_progress
    input_path = Path(input_dir)
    output_path = Path(output_dir)

    progress("Iniciant processament de documents...", 20)

    if not input_path.exists() or not input_path.is_dir():
        logger.warning("La ruta d'entrada no existeix o no es un directori: %s", input_path)
        progress("No s'ha trobat cap document.", 100)
        return None

    result_dir = output_path / "Certificats_generats"
    docs = llistar_pdfs(input_path, exclude_dir=result_dir)
    if not docs:
        progress("No s'ha trobat cap document.", 100)
        return None

    result_dir.mkdir(parents=True, exist_ok=True)

    processed = 0
    total = len(docs)
    for index, pdf_path in enumerate(docs, start=1):
        pct = 20 + int((index / total) * 70)
        progress(f"Processant document {index} de {total}...", pct)
        if processar_document(pdf_path, result_dir):
            processed += 1

    if processed == 0:
        progress("No s'ha pogut processar cap certificat.", 100)
        return None

    progress("Certificats generats.", 90)
    return result_dir


def llistar_pdfs(path: Path, exclude_dir: Path | None = None) -> list[Path]:
    exclude_path = exclude_dir.resolve() if exclude_dir is not None and exclude_dir.exists() else None
    return sorted(
        pdf_path
        for pdf_path in path.rglob("*")
        if pdf_path.is_file()
        and pdf_path.suffix.lower() in PDF_EXTS
        and not _is_relative_to(pdf_path, exclude_path)
    )


def _is_relative_to(path: Path, parent: Path | None) -> bool:
    if parent is None:
        return False
    try:
        path.resolve().relative_to(parent)
        return True
    except ValueError:
        return False


def llegir_pdf(ruta_pdf: str | Path) -> str:
    ruta_pdf = Path(ruta_pdf)

    if pdfminer_extract_text is not None and LAParams is not None:
        laparams = LAParams(
            word_margin=0.05,
            char_margin=2.0,
            line_margin=0.5,
        )
        return pdfminer_extract_text(str(ruta_pdf), laparams=laparams) or ""

    if PyPDF2 is None:
        raise RuntimeError("No hi ha cap lector de PDF disponible: cal pdfminer.six o PyPDF2.")

    final_text = ""
    with ruta_pdf.open("rb") as file:
        reader = PyPDF2.PdfReader(file)
        for page in reader.pages:
            final_text += page.extract_text() or ""
    return final_text


def arregla_trencaments_nom(linia: str) -> str:
    return re.sub(
        r"(?<=[\u00c0\u00c1\u00c8\u00c9\u00cc\u00cd\u00d2\u00d3\u00d9\u00da])\s+"
        r"(?=[A-Z\u00d1\u00c7]{2,4}\b)",
        "",
        linia,
    )


def extreure_info(text: str) -> tuple[str, str]:
    lines = [line.strip() for line in text.splitlines()]
    non_empty_lines = [line for line in lines if line]

    nif_name = _nom_abans_de_nif(non_empty_lines)
    especialitat = extreure_especialitat(non_empty_lines)
    if nif_name:
        return nif_name, especialitat or "PA"

    try:
        nom = arregla_trencaments_nom(lines[6].strip())
        especialitat_line = lines[9]
    except IndexError as exc:
        raise ValueError("El PDF no conte prou linies per extreure nom i especialitat.") from exc

    try:
        match = re.search(r":\s*(.+)", especialitat_line)
        if match is None:
            raise ValueError("No s'ha trobat el valor d'especialitat.")
        especialitat = normalitzar_especialitat(match.group(1))
    except Exception:
        try:
            nom = arregla_trencaments_nom(lines[7].strip())
        except IndexError:
            raise ValueError("El PDF no conte prou linies per aplicar el fallback PA.")
        especialitat = "PA"

    if not nom:
        raise ValueError("No s'ha pogut extreure el nom del certificat.")

    return nom, especialitat


def _nom_abans_de_nif(lines: list[str]) -> str | None:
    for index, line in enumerate(lines):
        if re.search(r"\b(NIF|DNI|NIE)\b", line, flags=re.IGNORECASE) and index > 0:
            nom = arregla_trencaments_nom(lines[index - 1].strip())
            return nom or None
    return None


def extreure_especialitat(lines: list[str]) -> str | None:
    for line in lines:
        match = re.search(r"Especialitat\s*:\s*(.+)", line, flags=re.IGNORECASE)
        if match:
            return normalitzar_especialitat(match.group(1))

    text = "\n".join(lines).upper()
    detected = normalitzar_especialitat(text)
    if detected in {"GIO", "AIE", "JIE"}:
        return detected

    if "PRIMERS AUXILIS" in text or "PREVENCI" in text and "SEGURETAT" in text:
        return "PA"
    return None


def normalitzar_especialitat(especialitat: str) -> str:
    especialitat_upper = especialitat.upper()
    if "GESTI" in especialitat_upper:
        return "GIO"
    if "ARBITRATGE" in especialitat_upper:
        return "AIE"
    if "JOC" in especialitat_upper:
        return "JIE"
    return especialitat.strip()


def normalitzar_nom_fitxer(nom: str) -> str:
    filename = nom.replace(" ", "_").replace("-", "_")
    while "__" in filename:
        filename = filename.replace("__", "_")
    filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", filename).strip("._ ")
    return filename or "sense_nom"


def processar_document(pdf_path: Path, result_dir: Path) -> bool:
    try:
        text = llegir_pdf(pdf_path)
        nom, especialitat = extreure_info(text)
        nom_fitxer = normalitzar_nom_fitxer(nom)

        dir_especialitat = result_dir / especialitat
        dir_especialitat.mkdir(parents=True, exist_ok=True)

        nova_ruta = dir_especialitat / f"Certificado_{nom_fitxer}.pdf"
        shutil.copy2(pdf_path, nova_ruta)
        logger.info("Copiat: %s -> %s", pdf_path, nova_ruta)
        return True
    except Exception:
        logger.exception("Error processant %s", pdf_path)
        return False
