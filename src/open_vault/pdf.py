"""PDF: el texto que viene adentro y, si es un escaneo, el OCR de las páginas.

Dos caminos porque hay dos clases de PDF y se comportan distinto:

- **Con texto** (lo que exporta cualquier programa): se lee con `pypdf`, es
  instantáneo y sale completo.
- **Escaneado** (fotos de papel): no hay texto que extraer; se convierte cada
  página en imagen con `pdftoppm` (poppler) y se lee con el OCR de siempre.

Nada sale de la máquina: los dos caminos corren local.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

MAX_PAGES_TEXT = int(os.getenv("PDF_MAX_PAGES_TEXT", "300"))
MAX_PAGES_OCR = int(os.getenv("PDF_MAX_PAGES_OCR", "10"))


def pypdf_available() -> bool:
    import importlib.util

    return importlib.util.find_spec("pypdf") is not None


def pdftoppm_available() -> bool:
    return shutil.which("pdftoppm") is not None


def text_of_pdf(path: Path, *, max_pages: int = 0) -> str:
    """Texto seleccionable del PDF, página por página."""
    if not pypdf_available():
        raise RuntimeError("Falta pypdf para leer PDF (pip install pypdf)")
    from pypdf import PdfReader

    lector = PdfReader(str(path))
    tope = max_pages or MAX_PAGES_TEXT
    partes: list[str] = []
    for indice, pagina in enumerate(lector.pages[:tope], start=1):
        try:
            texto = (pagina.extract_text() or "").strip()
        except Exception:  # noqa: BLE001 - una página rota no tira abajo el documento
            texto = ""
        if texto:
            partes.append(f"### Página {indice}\n\n{texto}")
    return "\n\n".join(partes).strip()


def page_count(path: Path) -> int | None:
    if not pypdf_available():
        return None
    from pypdf import PdfReader

    try:
        return len(PdfReader(str(path)).pages)
    except Exception:  # noqa: BLE001
        return None


def pages_as_images(path: Path, folder: Path, *, max_pages: int = 0, dpi: int = 150) -> list[Path]:
    """Convierte las primeras páginas en JPG, para poder leer un escaneo."""
    if not pdftoppm_available():
        return []
    folder.mkdir(parents=True, exist_ok=True)
    tope = max_pages or MAX_PAGES_OCR
    resultado = subprocess.run(
        [
            "pdftoppm",
            "-jpeg",
            "-r",
            str(dpi),
            "-f",
            "1",
            "-l",
            str(tope),
            str(path),
            str(folder / "pagina"),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=600,
    )
    if resultado.returncode != 0:
        return []
    return sorted(folder.glob("pagina*.jpg"))


def read_pdf(path: Path, folder: Path, *, language: str = "spa+eng") -> tuple[str, str, int | None]:
    """Devuelve (texto, texto_ocr, cantidad_de_páginas).

    El OCR solo se intenta cuando el PDF no trajo texto: en un documento normal
    sería tiempo perdido, y en un escaneo es la única forma de leerlo.
    """
    from .media import merge_ocr_texts, ocr_available, ocr_image

    paginas = page_count(path)
    texto = ""
    try:
        texto = text_of_pdf(path)
    except (RuntimeError, ValueError, OSError):
        texto = ""

    if len(texto) >= 200 or not ocr_available() or not pdftoppm_available():
        return texto, "", paginas

    imagenes = pages_as_images(path, folder)
    if not imagenes:
        return texto, "", paginas
    lecturas = []
    for imagen in imagenes:
        try:
            lecturas.append(ocr_image(imagen, language))
        except (RuntimeError, ValueError):
            continue
    return texto, merge_ocr_texts(lecturas), paginas


__all__ = [
    "page_count",
    "pages_as_images",
    "pdf_available",
    "pdftoppm_available",
    "pypdf_available",
    "read_pdf",
    "text_of_pdf",
]


def pdf_available() -> bool:
    """Se puede leer un PDF de alguna de las dos maneras."""
    return pypdf_available() or pdftoppm_available()
