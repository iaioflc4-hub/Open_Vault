"""Tejer el vault: que las capturas queden conectadas en el gráfico de Obsidian.

Una carpeta de notas sueltas es un archivo muerto: en el gráfico de Obsidian se ve
como una nube de puntos sin una sola línea. Este paso arma la estructura:

- cada captura se enlaza a **notas de tema** (`[[Temas/linux]]`), una por etiqueta;
- cada nota de tema lista las capturas que la usan, así el enlace va y vuelve;
- un `Mapa.md` enlaza todos los temas, que es la puerta de entrada al gráfico.

Se corre después de cada captura (lo hace el sincronizador) y es idempotente: si
no cambió nada, los archivos quedan igual.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

from .enrich import hashtags, tags
from .reclasificar import _campo, es_nota_de_captura

TEMAS_DIR = "Temas"
MAPA = "Mapa del vault.md"
MARCA = "<!-- openvault:temas -->"
CATEGORY_RE = re.compile(r'^category:\s*("?)(.*?)\1\s*$', re.MULTILINE)
MAX_TEMAS_POR_NOTA = 6


def cuerpo_del_contenido(texto: str) -> str:
    """Solo el contenido de la captura, sin las secciones que agrega el programa.

    Es la diferencia entre un gráfico útil y uno lleno de ruido: contando las
    palabras del encabezado y de los títulos de sección, cualquier video quedaba
    conectado a los temas "video" y "transcripción".
    """
    marca = "## Contenido íntegro"
    if marca not in texto:
        return texto
    resto = texto.split(marca, 1)[1]
    return resto.split("> [!quote] Sin resumen", 1)[0]


def etiquetas_de(texto: str, *, palabras: int = 2) -> list[str]:
    """Temas a los que se conecta una captura, en orden de importancia.

    Manda lo que eligió la persona (`#etiqueta`), después el tema clasificado y
    recién al final un par de palabras frecuentes del contenido. El motivo es el
    gráfico: con las diez palabras del encabezado, cinco capturas generan veinte
    temas y el mapa queda ilegible en vez de útil.

    Las palabras se recalculan acá, del contenido, en vez de leer el `tags:` del
    encabezado: ese encabezado se escribió cuando se guardó la nota y no se toca
    después, así que traería las reglas viejas a un mapa nuevo.
    """
    a_mano = hashtags(texto, limit=MAX_TEMAS_POR_NOTA)
    categoria = _campo(texto, CATEGORY_RE).casefold()
    del_contenido = [
        etiqueta.casefold() for etiqueta in tags(cuerpo_del_contenido(texto), limit=palabras + 2)
    ]
    elegidas = list(a_mano)
    if categoria and categoria != "por clasificar":
        elegidas.append(categoria)
    for palabra in del_contenido:
        if len(elegidas) >= len(a_mano) + 1 + palabras:
            break
        elegidas.append(palabra)
    limpias = [re.sub(r"[\[\]|#^]", "", etiqueta).strip() for etiqueta in elegidas]
    return list(dict.fromkeys(etiqueta for etiqueta in limpias if 2 <= len(etiqueta) <= 40))[
        :MAX_TEMAS_POR_NOTA
    ]


def _nombre_tema(etiqueta: str) -> str:
    return f"Temas/{etiqueta}"


def _sin_seccion_temas(texto: str) -> str:
    """Saca la sección de temas anterior.

    Es la última sección siempre: la agrega este módulo al final, después del
    contenido que escribió el guardado.
    """
    indice = texto.find(MARCA)
    if indice == -1:
        return texto.rstrip() + "\n"
    inicio = texto.rfind("\n## ", 0, indice)
    return (texto[:inicio] if inicio != -1 else texto[:indice]).rstrip() + "\n"


def _bloque_temas(etiquetas: list[str]) -> str:
    enlaces = "\n".join(f"- [[{_nombre_tema(etiqueta)}|{etiqueta}]]" for etiqueta in etiquetas)
    return f"\n\n## Temas\n\n{MARCA}\n{enlaces}\n"


def tejer(vault: Path, *, simular: bool = False) -> dict[str, int]:
    """Conecta las capturas con sus temas y rehace el mapa. Idempotente."""
    vault = Path(vault)
    resumen = {"revisadas": 0, "enlazadas": 0, "temas": 0, "sin_cambios": 0, "huerfanos": 0}
    capturas = sorted(p for p in vault.rglob("*.md") if es_nota_de_captura(p, vault))
    if not capturas:
        return resumen

    por_tema: dict[str, list[str]] = {}
    for nota in capturas:
        resumen["revisadas"] += 1
        try:
            texto = nota.read_text(encoding="utf-8")
        except OSError:
            continue
        etiquetas = etiquetas_de(texto)
        for etiqueta in etiquetas:
            por_tema.setdefault(etiqueta, []).append(nota.stem)

        nuevo = _sin_seccion_temas(texto) + _bloque_temas(etiquetas)
        if nuevo == texto:
            resumen["sin_cambios"] += 1
            continue
        resumen["enlazadas"] += 1
        if not simular:
            nota.write_text(nuevo, encoding="utf-8")

    resumen["temas"] = len(por_tema)
    if simular:
        return resumen

    carpeta = vault / TEMAS_DIR
    carpeta.mkdir(parents=True, exist_ok=True)
    for etiqueta, notas in sorted(por_tema.items()):
        (carpeta / f"{etiqueta}.md").write_text(_nota_de_tema(etiqueta, notas), encoding="utf-8")

    # Un tema que se quedó sin capturas se saca del gráfico: si no, el mapa se llena
    # de puntos sueltos ("video", "transcripción") que ya no llevan a ninguna nota.
    # Solo se borran los que armó este programa; una nota de tema escrita a mano no
    # tiene el `type: tema` de acá y se deja como está.
    resumen["huerfanos"] = _limpiar_huerfanos(carpeta, por_tema)

    (vault / MAPA).write_text(_mapa(por_tema), encoding="utf-8")
    return resumen


def _limpiar_huerfanos(carpeta: Path, por_tema: dict[str, list[str]]) -> int:
    borrados = 0
    for archivo in sorted(carpeta.glob("*.md")):
        if archivo.stem in por_tema:
            continue
        try:
            texto = archivo.read_text(encoding="utf-8")
        except OSError:
            continue
        if 'type: "tema"' not in texto:
            continue
        archivo.unlink()
        borrados += 1
    return borrados


def _nota_de_tema(etiqueta: str, notas: list[str]) -> str:
    ordenadas = sorted(set(notas))
    enlaces = "\n".join(f"- [[{nombre}]]" for nombre in ordenadas)
    encabezado = {
        "title": f"Tema: {etiqueta}",
        "type": "tema",
        "tags": ["tema", etiqueta],
    }
    frontmatter = "---\n" + "\n".join(
        f"{clave}: {json.dumps(valor, ensure_ascii=False)}" for clave, valor in encabezado.items()
    ) + "\n---\n"
    return (
        f"{frontmatter}\n# {etiqueta}\n\n"
        f"{len(ordenadas)} capturas con esta etiqueta.\n\n"
        f"## Capturas\n\n{enlaces}\n"
    )


def _mapa(por_tema: dict[str, list[str]]) -> str:
    conteo = Counter({etiqueta: len(set(notas)) for etiqueta, notas in por_tema.items()})
    encabezado = {"title": "Mapa del vault", "type": "mapa"}
    frontmatter = "---\n" + "\n".join(
        f"{clave}: {json.dumps(valor, ensure_ascii=False)}" for clave, valor in encabezado.items()
    ) + "\n---\n"
    filas = "\n".join(
        f"- [[{_nombre_tema(etiqueta)}|{etiqueta}]] · {cantidad}"
        for etiqueta, cantidad in conteo.most_common()
    )
    total = sum(conteo.values())
    return (
        f"{frontmatter}\n# Mapa del vault\n\n"
        f"{len(conteo)} temas, {total} enlaces. Abrí la vista de gráfico para ver la estructura.\n\n"
        f"## Temas\n\n{filas or '- Todavía no hay capturas'}\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Conecta las capturas con notas de tema y rehace el mapa.")
    parser.add_argument("--vault", default="/srv/obsidian/Open_Vault")
    parser.add_argument("--simular", action="store_true", help="Muestra qué haría, sin escribir")
    opciones = parser.parse_args(argv)
    resumen = tejer(Path(opciones.vault), simular=opciones.simular)
    print(
        f"{resumen['revisadas']} capturas, {resumen['enlazadas']} con enlaces nuevos, "
        f"{resumen['temas']} temas, {resumen['sin_cambios']} sin cambios, "
        f"{resumen['huerfanos']} temas huérfanos borrados"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
