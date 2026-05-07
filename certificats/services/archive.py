from pathlib import Path
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile


def create_certificats_zip(result_dir: str | Path, destination_dir: str | Path) -> Path:
    result_path = Path(result_dir)
    if not result_path.is_dir():
        raise ValueError(f"result_dir does not exist or is not a directory: {result_path}")

    destination_path = Path(destination_dir)
    destination_path.mkdir(parents=True, exist_ok=True)

    zip_path = destination_path / f"certificats_generats_{uuid4().hex}.zip"

    with ZipFile(zip_path, "w", compression=ZIP_DEFLATED) as zip_file:
        for item in sorted(result_path.rglob("*")):
            if item.is_file():
                zip_file.write(item, item.relative_to(result_path))

    return zip_path.resolve()
