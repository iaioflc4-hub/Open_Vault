"""Escritura del vault: una nota Markdown por captura, con su parte visual.

El vault es una carpeta común de Markdown (`/srv/obsidian/Open_Vault` por
defecto): sin base de datos, sin formato propietario. Obsidian, Logseq, Foam o
cualquier editor de texto lo abren igual, y un `git` lo versiona tal cual.

Cada nota queda con:
  - frontmatter YAML (título, fuente, tipo, categoría, etiquetas, métricas);
  - una ficha SVG de portada y, si hay datos, un gráfico de barras;
  - estructura del documento como diagrama Mermaid y fórmulas en LaTeX;
  - el contenido íntegro, sin resumir, y el original adjunto cuando existe.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from .classify import classify
from .enrich import Figure, key_figures, math_blocks, mermaid_tree, outline, stats, tags
from .svg import bars_svg, card_svg, color_for, format_number

ATTACHMENTS_DIR = "Attachments"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".avif"}
VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi"}


def _slug(value: str, limit: int = 72) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", ascii_value).strip("-")[:limit] or "nota"


def _source_id(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:10]


def _relative_attachment(name: str) -> str:
    """Nombre de adjunto normalizado a `Attachments/lo-que-sea`."""
    clean = name.replace("\\", "/").lstrip("/")
    return clean if clean.startswith(f"{ATTACHMENTS_DIR}/") else f"{ATTACHMENTS_DIR}/{clean}"


def render_attachment(name: str) -> str:
    """Embebe imágenes y enlaza lo demás: un video de 15 MB no va embebido."""
    relative = _relative_attachment(name)
    suffix = Path(relative).suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        return f"![[{relative}]]"
    if suffix in VIDEO_SUFFIXES:
        return f"![[{relative}]]"
    return f"[[{relative}]]"


def _write_asset(folder: Path, filename: str, content: str) -> str:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / filename).write_text(content, encoding="utf-8")
    return f"{ATTACHMENTS_DIR}/{filename}"


def _figures_table(figures: list[Figure]) -> str:
    rows = ["| Dato | Valor |", "| --- | --- |"]
    for figure in figures:
        # Mismo formato que el gráfico: "1.250 GW", no "1,250 GW".
        unit = f" {figure.unit}" if figure.unit else ""
        rows.append(f"| {figure.label} | {format_number(figure.value)}{unit} |")
    return "\n".join(rows)


def save_note(
    vault: Path,
    *,
    title: str,
    content: str,
    source: str,
    kind: str,
    category: str | None = None,
    attachments: list[str] | None = None,
    hero: str | None = None,
    note_metadata: dict[str, str] | None = None,
) -> Path:
    """Guarda la captura enriquecida. Devuelve la ruta de la nota."""
    vault = Path(vault)
    vault.mkdir(parents=True, exist_ok=True)
    content = content.strip()
    category = category or classify(f"{title}\n{content}")
    now = datetime.now(timezone.utc)
    attachment_folder = vault / ATTACHMENTS_DIR

    measured = stats(f"{title}\n{content}")
    note_tags = tags(f"{title}\n{content}")
    figures = key_figures(content)
    formulas = math_blocks(content)
    headings = outline(content)

    folder = vault / "Categorías" / _slug(category)
    folder.mkdir(parents=True, exist_ok=True)
    base = f"{now:%Y-%m-%d}-{_slug(title)}-{_source_id(source)}"
    path = folder / f"{base}.md"

    # --- parte visual -----------------------------------------------------
    card = _write_asset(
        attachment_folder,
        f"{base}-ficha.svg",
        card_svg(
            title=title,
            category=category,
            source_host=urlparse(source).netloc,
            captured_at=f"{now:%Y-%m-%d}",
            words=measured.words,
            tags=note_tags,
        ),
    )
    assets = [card]
    chart: str | None = None
    if len(figures) >= 3:
        chart = _write_asset(
            attachment_folder,
            f"{base}-cifras.svg",
            bars_svg(
                items=[(figure.chart_label, figure.value) for figure in figures],
                accent=color_for(category),
            ),
        )
        assets.append(chart)

    # --- frontmatter ------------------------------------------------------
    front = {
        "title": title.strip(),
        "source": source,
        "type": kind,
        "category": category,
        "tags": note_tags,
        "captured_at": now.isoformat(),
        "words": measured.words,
        "reading_minutes": measured.reading_minutes,
    }
    front.update(note_metadata or {})
    frontmatter = "---\n" + "\n".join(
        f"{key}: {json.dumps(value, ensure_ascii=False)}" for key, value in front.items()
    ) + "\n---\n"

    # --- cuerpo -----------------------------------------------------------
    sections: list[str] = [f"![[{card}]]"]
    if hero:
        sections.append(render_attachment(hero))
    sections.append(
        f"> [!info] Captura íntegra, sin resumen\n"
        f"> {measured.words} palabras · lectura ~{measured.reading_minutes} min · "
        f"guardado el {now:%Y-%m-%d %H:%M} UTC · tipo `{kind}`\n"
        f"> Fuente: {source}"
    )

    tree = mermaid_tree(title, headings)
    if tree:
        sections.append(f"## Estructura del documento\n\n{tree}")

    if figures:
        blocks = []
        if chart:
            blocks.append(f"![[{chart}]]")
        blocks.append(_figures_table(figures))
        sections.append("## Cifras destacadas\n\n" + "\n\n".join(blocks))

    if formulas:
        formatted = "\n\n".join(f"$$\n{formula}\n$$" for formula in formulas)
        sections.append(f"## Fórmulas\n\n{formatted}")

    sections.append(
        f"## Contenido íntegro\n\n{content}\n\n"
        "> [!quote] Sin resumen\n"
        "> El texto de arriba se guarda tal como se extrajo. Open_Vault no lo resume ni lo reescribe."
    )

    attachment_lines = [render_attachment(name) for name in (attachments or [])]
    if assets:
        attachment_lines.extend(f"![[{asset}]]" for asset in assets)
    sections.append("## Adjuntos\n\n" + ("\n\n".join(attachment_lines) if attachment_lines else "- Ninguno"))

    sections.append(f"## Fuente original\n\n{source}")

    path.write_text(frontmatter + "\n" + "\n\n".join(sections) + "\n", encoding="utf-8")
    return path


def _duracion_texto(seconds: float) -> str:
    if seconds >= 60:
        return f"{int(seconds // 60)} min {int(seconds % 60)} s"
    return f"{seconds:.1f} s"


def save_video_reference(
    vault: Path,
    *,
    title: str,
    source: str,
    thumbnail: str | None = None,
    local_file: str | None = None,
    transcript: str | None = None,
    on_screen_text: str | None = None,
    duration: float | None = None,
) -> Path:
    """Video: referencia, miniatura si hay ffmpeg y lo que se pudo leer del contenido.

    `transcript` viene de la transcripción local del audio y `on_screen_text` del
    OCR de los cuadros. No se envía el video a ningún servicio externo: eso solo
    pasaría si alguien configura un proveedor de transcripción a propósito.
    """
    host = urlparse(source).netloc
    lineas = [
        "## Referencia del video",
        "",
        f"- URL original: {source}",
        f"- Plataforma/dominio: {host}",
    ]
    if local_file:
        lineas.append(f"- Archivo local: {local_file}")
    if duration:
        lineas.append(f"- Duración: {_duracion_texto(duration)}")
    lineas.append("")
    if transcript:
        lineas += ["## Transcripción", "", transcript, ""]
    else:
        lineas += [
            "## Transcripción pendiente",
            "",
            "Pendiente de configurar el proveedor de transcripción. "
            "El video no se envió a ningún servicio externo.",
            "",
        ]
    if on_screen_text:
        lineas += ["## Texto en pantalla (leído de los cuadros)", "", on_screen_text, ""]
    lineas += [
        "## Notas",
        "",
        "Escribí acá lo que te interesa del video. Para que la transcripción sea "
        "automática, activá `TRANSCRIPTION_ENGINE` en el `.env`.",
    ]
    content = "\n".join(lineas)
    attachments = [name for name in (thumbnail, local_file) if name]
    metadata = {"platform": host}
    if duration:
        metadata["duration_seconds"] = round(duration, 1)
    return save_note(
        vault,
        title=title,
        content=content,
        source=source,
        kind="video",
        category="Videos",
        attachments=attachments,
        hero=thumbnail,
        note_metadata=metadata,
    )


def save_text_note(vault: Path, *, title: str, content: str, source: str) -> Path:
    """Nota escrita a mano desde el chat: mismo enriquecido que todo lo demás."""
    return save_note(vault, title=title, content=content, source=source, kind="texto")


__all__ = [
    "ATTACHMENTS_DIR",
    "render_attachment",
    "save_note",
    "save_text_note",
    "save_video_reference",
]
