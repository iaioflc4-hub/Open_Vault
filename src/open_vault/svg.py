"""Generación de SVG sin dependencias.

Todo lo "visualmente rico" del vault sale de acá: la ficha de portada de cada
nota y los gráficos de barras de las cifras destacadas.

Por qué SVG escrito a mano y no una librería de gráficos: cero dependencias,
cero servicios externos, cero costo, y el mismo archivo se ve bien en Obsidian,
en un navegador y en la vista previa de GitHub. El SVG es texto plano, así que
también entra en el control de versiones como cualquier nota.
"""
from __future__ import annotations

from html import escape
from textwrap import wrap

FONT = "system-ui, -apple-system, 'Segoe UI', Roboto, Ubuntu, sans-serif"

BACKGROUND = "#0d1117"
FOREGROUND = "#e6edf3"
MUTED = "#8b949e"
ACCENT_LINK = "#58a6ff"
TRACK = "#21262d"

# Un color estable por categoría: la ficha de una nota de Ciencia siempre se ve
# igual, aunque se regenere.
CATEGORY_COLORS = {
    "Tecnología": "#4c8dff",
    "Ciencia": "#3fb950",
    "Negocios": "#d29922",
    "Salud": "#f778ba",
    "Educación": "#a371f7",
    "Videos": "#ff7b72",
}
DEFAULT_COLOR = "#8b949e"


def color_for(category: str) -> str:
    return CATEGORY_COLORS.get(category, DEFAULT_COLOR)


def _esc(value: object) -> str:
    """Escapa para XML: un título con `<` o `&` no puede romper el SVG."""
    return escape(str(value), quote=True)


def _wrap_lines(text: str, width: int, limit: int) -> list[str]:
    """Envuelve el texto y recorta a `limit` líneas agregando puntos suspensivos."""
    lines = wrap(text.strip() or " ", width=width) or [" "]
    if len(lines) > limit:
        lines = lines[:limit]
        lines[-1] = lines[-1][: max(width - 1, 1)].rstrip() + "…"
    return lines


def format_number(value: float) -> str:
    """1234.5 -> '1.234,5' (formato local, sin depender del locale del sistema)."""
    if value == int(value):
        return f"{int(value):,}".replace(",", ".")
    decimals = f"{value:,.2f}".rstrip("0").rstrip(".")
    return decimals.replace(",", "\u00a0").replace(".", ",").replace("\u00a0", ".")


def card_svg(
    *,
    title: str,
    category: str,
    source_host: str = "",
    captured_at: str = "",
    words: int = 0,
    tags: tuple[str, ...] | list[str] = (),
    width: int = 880,
) -> str:
    """Ficha de portada: la nota abre con algo que se entiende de un vistazo."""
    accent = color_for(category)
    title_lines = _wrap_lines(title or "Sin título", 44, 3)
    height = 190 + 38 * len(title_lines)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}" role="img" '
        f'aria-label="{_esc(title or "Sin título")}">',
        f'<rect width="{width}" height="{height}" rx="18" fill="{BACKGROUND}"/>',
        f'<rect x="0" y="0" width="12" height="{height}" rx="6" fill="{accent}"/>',
        f'<text x="56" y="58" font-family="{FONT}" font-size="15" font-weight="600" '
        f'fill="{accent}" letter-spacing="2">{_esc(category.upper())}</text>',
    ]

    y = 110
    for line in title_lines:
        parts.append(
            f'<text x="56" y="{y}" font-family="{FONT}" font-size="31" font-weight="700" '
            f'fill="{FOREGROUND}">{_esc(line)}</text>'
        )
        y += 38

    meta = " · ".join(
        piece for piece in (source_host, captured_at, f"{words} palabras" if words else "") if piece
    )
    parts.append(
        f'<text x="56" y="{y + 16}" font-family="{FONT}" font-size="16" '
        f'fill="{MUTED}">{_esc(meta)}</text>'
    )

    if tags:
        tag_line = "  ".join(f"#{tag}" for tag in list(tags)[:6])
        parts.append(
            f'<text x="56" y="{y + 52}" font-family="{FONT}" font-size="15" '
            f'fill="{ACCENT_LINK}">{_esc(tag_line)}</text>'
        )

    parts.append("</svg>")
    return "\n".join(parts)


def bars_svg(
    *,
    items: list[tuple[str, float]],
    title: str = "Cifras destacadas",
    accent: str = ACCENT_LINK,
    width: int = 880,
    max_items: int = 7,
) -> str:
    """Barras horizontales: sirve para cualquier dato con etiqueta y número."""
    rows = [(label, value) for label, value in items if value > 0][:max_items]
    label_width = 320
    right_margin = 110
    top = 66
    row_height = 40
    height = top + row_height * len(rows) + 14
    plot = max(width - label_width - right_margin, 40)
    maximum = max((value for _, value in rows), default=1)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}" role="img" aria-label="{_esc(title)}">',
        f'<rect width="{width}" height="{height}" rx="18" fill="{BACKGROUND}"/>',
        f'<text x="32" y="40" font-family="{FONT}" font-size="19" font-weight="600" '
        f'fill="{FOREGROUND}">{_esc(title)}</text>',
    ]

    for index, (label, value) in enumerate(rows):
        y = top + index * row_height
        bar = max(plot * (value / maximum), 3)
        short_label = _wrap_lines(label, 38, 1)[0]
        parts.append(
            f'<text x="32" y="{y + 16}" font-family="{FONT}" font-size="15" '
            f'fill="{FOREGROUND}">{_esc(short_label)}</text>'
        )
        parts.append(
            f'<rect x="{label_width}" y="{y}" width="{plot}" height="20" rx="6" fill="{TRACK}"/>'
        )
        parts.append(
            f'<rect x="{label_width}" y="{y}" width="{bar:.1f}" height="20" rx="6" fill="{accent}"/>'
        )
        parts.append(
            f'<text x="{label_width + plot + 14}" y="{y + 16}" font-family="{FONT}" '
            f'font-size="15" font-weight="600" fill="{MUTED}">{_esc(format_number(value))}</text>'
        )

    parts.append("</svg>")
    return "\n".join(parts)
