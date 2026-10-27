"""Convierte texto crudo en material que se ve bien de un vistazo.

Nada de resumir por IA ni de llamar a un servicio: son reglas deterministas que
sacan la estructura (encabezados), las cifras y las fórmulas que ya estaban en
el texto. Si el texto no trae nada de eso, no se inventa nada.
"""
from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
# Para etiquetas: palabras de 4+ letras (lo corto no etiqueta nada).
WORD_RE = re.compile(r"[0-9A-Za-zÁÉÍÓÚÜÑáéíóúüñ][0-9A-Za-zÁÉÍÓÚÜÑáéíóúüñ'_-]{3,}")
# Para contar de verdad: cualquier palabra, incluidas "con", "una", "más".
ANY_WORD_RE = re.compile(r"[0-9A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+")
SENTENCE_RE = re.compile(r"[.!?…]+(?:\s|$)")

MATH_HINT_RE = re.compile(r"[\\^_=]|\b(?:sum|int|frac|sqrt|alpha|beta|gamma|theta|lambda)\b")
OPERATOR_RE = re.compile(r"[+\-*/×÷]")
LETTER_RE = re.compile(r"[A-Za-z]")


def looks_like_math(candidate: str) -> bool:
    """¿El texto entre dólares es una fórmula y no un precio?

    `\\frac{a}{b}` o `x^2` o `a = b` sí. `5 - 10` (un rango de precios) no,
    porque no hay ninguna variable.
    """
    if MATH_HINT_RE.search(candidate):
        return True
    return bool(OPERATOR_RE.search(candidate) and LETTER_RE.search(candidate))
DISPLAY_MATH_RE = re.compile(r"\$\$(.+?)\$\$", re.DOTALL)
BRACKET_MATH_RE = re.compile(r"\\\[(.+?)\\\]", re.DOTALL)
PAREN_MATH_RE = re.compile(r"\\\((.+?)\\\)", re.DOTALL)
INLINE_MATH_RE = re.compile(r"(?<![\\$\w])\$(?!\s)([^$\n]{1,200}?)\$(?!\w)")

# "Etiqueta: 42 %", "- Ventas: 1.250 millones", "Potencia instalada: 1.250 GW"
# Solo se leen líneas etiquetadas ("algo: número") que terminan ahí: así una hora
# como "10:30 de la mañana" no se toma por un dato.
FIGURED_LINE_RE = re.compile(
    r"^\s*(?:[-*•>]|\d+[.)])?\s*(?P<label>[^:：\n]{3,70}?)\s*[:：]\s*"
    r"(?P<currency>[$€£])?\s*"
    r"(?P<number>\d{1,3}(?:[.\u00a0]\d{3})*(?:,\d+)?|\d+(?:[.,]\d+)?)\s*"
    r"(?P<unit>por ciento|mil millones|millones|millón|mil|[A-Za-z°%€$]{1,12})?\s*$",
    re.MULTILINE,
)
UNIT_FACTORS = {"mil": 1_000, "millones": 1_000_000, "millón": 1_000_000, "mil millones": 1_000_000_000,
                "k": 1_000, "m": 1_000_000}
PERCENT_UNITS = {"%", "por ciento"}

STOPWORDS = {
    "para", "como", "este", "esta", "estos", "estas", "entre", "sobre", "desde", "hasta",
    "cuando", "donde", "porque", "también", "puede", "pueden", "hace", "hacia", "según",
    "todo", "toda", "todos", "todas", "otro", "otra", "otros", "otras", "mismo", "misma",
    "pero", "sino", "aunque", "mientras", "mediante", "cada", "tiene", "tienen", "hacer",
    "será", "serán", "fueron", "haber", "había", "sería", "está", "están", "estaba",
    "more", "that", "with", "this", "from", "have", "will", "your", "their", "there",
    "which", "were", "been", "into", "than", "then", "they", "them", "also", "such",
    "about", "other", "these", "those", "when", "what", "some", "more", "only", "like",
    "https", "http", "www", "com", "org", "net", "html", "para",
}


@dataclass(frozen=True)
class Figure:
    """Un dato con etiqueta: `Cobertura: 87,5 %` -> (Cobertura, 87.5, %)."""

    label: str
    value: float
    unit: str = ""

    @property
    def chart_label(self) -> str:
        return f"{self.label} ({self.unit})" if self.unit else self.label


@dataclass(frozen=True)
class Stats:
    words: int
    characters: int
    reading_minutes: int
    sentences: int


def outline(text: str) -> list[tuple[int, str]]:
    """Encabezados Markdown en orden, como (nivel, título)."""
    return [(len(match.group(1)), match.group(2).strip()) for match in HEADING_RE.finditer(text)]


def _clean_label(value: str) -> str:
    """Saca el ruido de un encabezado para que Mermaid no se atragante."""
    value = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", value)  # enlaces -> texto
    value = re.sub(r"[`*_~]+", "", value)
    value = re.sub(r"[(){}\[\]\"'`|;<>]", "", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip(" -–—:.")[:70]


def mermaid_tree(title: str, headings: list[tuple[int, str]], *, max_nodes: int = 12) -> str | None:
    """Diagrama Mermaid de la estructura del documento.

    Devuelve `None` si no hay estructura suficiente: un diagrama con dos nodos
    sueltos ensucia más de lo que aporta. El tope de nodos es bajo a propósito:
    un documento con sesenta subtítulos produce un mapa ilegible, y para eso ya
    está el índice de la vista web.
    """
    nodes = [(level, _clean_label(text)) for level, text in headings if _clean_label(text)]
    if len(nodes) < 3:
        return None
    # El nodo central es un círculo: un título de 120 caracteres se sale del
    # dibujo. Se recorta, y el título completo sigue en la nota.
    root = _clean_label(title)[:38].strip() or "Nota"
    lines = ["```mermaid", "mindmap", f"  root(({root}))"]
    base_level = min(level for level, _ in nodes)
    kept = 0
    for level, text in nodes:
        depth = level - base_level + 1
        if depth > 3:
            continue
        lines.append("  " * (depth + 1) + text)
        kept += 1
        if kept >= max_nodes:
            break
    lines.append("```")
    return "\n".join(lines)


def _parse_number(raw: str) -> float:
    """Número en formato local: '1.250,5' -> 1250.5 ; '1,250' -> 1250 ; '87,5' -> 87.5."""
    value = raw.replace("\u00a0", "").replace(" ", "")
    if "," in value and "." in value:
        value = value.replace(".", "").replace(",", ".")
    elif "," in value:
        head, _, tail = value.partition(",")
        value = f"{head}.{tail}" if len(tail) != 3 or len(head) > 3 else f"{head}{tail}"
    else:
        head, _, tail = value.partition(".")
        if tail and len(tail) == 3 and len(head) <= 3:
            value = f"{head}{tail}"
    try:
        return float(value)
    except ValueError:
        return 0.0


def key_figures(text: str, *, limit: int = 7, minimum: int = 1) -> list[Figure]:
    """Cifras con etiqueta explícita. Solo lo que está escrito como dato, sin adivinar."""
    found: list[Figure] = []
    seen: set[str] = set()
    for match in FIGURED_LINE_RE.finditer(text):
        label = re.sub(r"\s+", " ", match.group("label")).strip(" -–—*•>")
        label = _clean_label(label)
        if len(label) < 3 or label.lower() in seen:
            continue
        value = _parse_number(match.group("number"))
        unit = (match.group("unit") or "").strip()
        # El multiplicador se busca en minúscula, pero la unidad se muestra tal
        # como venía: "GW" no es "gw".
        value *= UNIT_FACTORS.get(unit.lower(), 1)
        if currency := (match.group("currency") or ""):
            unit = currency if not unit else f"{currency} {unit}"
        elif unit.lower() in PERCENT_UNITS:
            unit = "%"
        if value <= minimum:
            continue
        seen.add(label.lower())
        found.append(Figure(label=label, value=value, unit=unit))
        if len(found) >= limit:
            break
    return found


def math_blocks(text: str, *, limit: int = 8) -> list[str]:
    """Fórmulas ya presentes en el texto, normalizadas a bloques `$$...$$`.

    Solo se acepta `$...$` cuando adentro hay señales de matemática (\\comando,
    ^, _ o =). Así `$5` (plata) no se confunde con una fórmula.
    """
    blocks: list[str] = []
    for pattern in (DISPLAY_MATH_RE, BRACKET_MATH_RE, PAREN_MATH_RE):
        blocks.extend(match.group(1).strip() for match in pattern.finditer(text))
    for match in INLINE_MATH_RE.finditer(text):
        candidate = match.group(1).strip()
        if looks_like_math(candidate):
            blocks.append(candidate)

    unique: list[str] = []
    for block in blocks:
        cleaned = block.strip()
        if cleaned and cleaned not in unique and len(cleaned) < 600:
            unique.append(cleaned)
        if len(unique) >= limit:
            break
    return unique


def _strip_accents(value: str) -> str:
    return "".join(char for char in unicodedata.normalize("NFKD", value) if not unicodedata.combining(char))


HASHTAG_RE = re.compile(r"#([\wáéíóúüñÁÉÍÓÚÜÑ][\wáéíóúüñÁÉÍÓÚÜÑ-]{1,29})", re.UNICODE)


def hashtags(text: str, *, limit: int = 8) -> list[str]:
    """Etiquetas escritas a mano con `#`. Son las que más valen: las eligió alguien."""
    vistas: list[str] = []
    for match in HASHTAG_RE.finditer(text or ""):
        etiqueta = match.group(1).casefold()
        if etiqueta not in vistas:
            vistas.append(etiqueta)
        if len(vistas) >= limit:
            break
    return vistas


def tags(text: str, *, limit: int = 6) -> list[str]:
    """Etiquetas por frecuencia, sin listas negras de temas: solo palabras útiles.

    Las que escribió la persona con `#` van primero y no se repiten.
    """
    counts: dict[str, int] = {}
    order: dict[str, int] = {}
    for index, match in enumerate(WORD_RE.finditer(text)):
        word = match.group(0).strip("'_-").lower()
        if len(word) < 4 or word.isdigit() or word in STOPWORDS or _strip_accents(word) in STOPWORDS:
            continue
        counts[word] = counts.get(word, 0) + 1
        order.setdefault(word, index)
    ranked = sorted(counts.items(), key=lambda item: (-item[1], order[item[0]]))
    elegidas = [word for word, count in ranked[:limit] if count >= 1]
    return list(dict.fromkeys([*hashtags(text, limit=limit), *elegidas]))[: limit + 4]


def stats(text: str) -> Stats:
    words = len(ANY_WORD_RE.findall(text))
    characters = len(text)
    sentences = max(len(SENTENCE_RE.findall(text)), 1)
    return Stats(
        words=words,
        characters=characters,
        reading_minutes=max(1, math.ceil(words / 200)),
        sentences=sentences,
    )
