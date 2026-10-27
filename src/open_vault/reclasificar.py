"""Reclasificar las notas viejas con las reglas de hoy.

Las reglas de clasificación mejoran con el uso (una palabra que faltaba, un tema
nuevo). Sin esto, todo lo capturado antes se queda en la categoría que le tocó
aquel día y el vault termina mezclado: mitad bien clasificado y mitad no.

Se puede correr cuando se quiera —lo hace solo el sincronizador— y tiene modo
`--simular` para ver qué movería antes de mover nada. Nunca borra el contenido:
solo cambia la carpeta y la línea `category:` del encabezado.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from .classify import UNCATEGORIZED, classify_or
from .vault import folder_for_category

TITLE_RE = re.compile(r'^title:\s*("?)(.*?)\1\s*$', re.MULTILINE)
CATEGORY_RE = re.compile(r'^category:\s*("?)(.*?)\1\s*$', re.MULTILINE)
FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
CATEGORIAS_DIR = "Categorías"


def _campo(texto: str, patron: re.Pattern[str]) -> str:
    match = patron.search(texto)
    return match.group(2).strip() if match else ""


def cuerpo_sin_encabezado(texto: str) -> str:
    """El texto de la nota sin el frontmatter YAML, que no aporta tema."""
    match = FRONTMATTER_RE.match(texto)
    return texto[match.end() :] if match else texto


def es_nota_de_captura(nota: Path, vault: Path) -> bool:
    """Las notas dentro de `Categorías/` son capturas; el resto (mapa, temas) no."""
    try:
        partes = nota.relative_to(vault).parts
    except ValueError:
        return False
    return len(partes) > 1 and partes[0] == CATEGORIAS_DIR


def reclasificar(vault: Path, *, simular: bool = False) -> dict[str, int]:
    """Recorre las capturas y las mueve al tema que les corresponde hoy.

    Devuelve un resumen contable: cuántas revisó, cuántas movió y cuántas dejó.
    """
    vault = Path(vault)
    resumen = {"revisadas": 0, "movidas": 0, "sin_cambios": 0, "errores": 0}
    if not (vault / CATEGORIAS_DIR).is_dir():
        return resumen

    for nota in sorted(p for p in vault.rglob("*.md") if es_nota_de_captura(p, vault)):
        resumen["revisadas"] += 1
        try:
            texto = nota.read_text(encoding="utf-8")
        except OSError:
            resumen["errores"] += 1
            continue
        titulo = _campo(texto, TITLE_RE)
        actual = _campo(texto, CATEGORY_RE) or UNCATEGORIZED
        nueva = classify_or(cuerpo_sin_encabezado(texto), actual, title=titulo)
        if nueva == actual:
            resumen["sin_cambios"] += 1
            continue
        resumen["movidas"] += 1
        if simular:
            print(f"  {nota.parent.name} -> {nueva}: {nota.name}")
            continue
        destino = folder_for_category(vault, nueva) / nota.name
        nuevo_texto = CATEGORY_RE.sub(f"category: {json.dumps(nueva, ensure_ascii=False)}", texto, count=1)
        destino.write_text(nuevo_texto, encoding="utf-8")
        if destino.resolve() != nota.resolve():
            nota.unlink()
    return resumen


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reclasifica las notas del vault con las reglas actuales.")
    parser.add_argument("--vault", default="/srv/obsidian/Open_Vault")
    parser.add_argument("--simular", action="store_true", help="Muestra qué movería, sin tocar los archivos")
    opciones = parser.parse_args(argv)
    resumen = reclasificar(Path(opciones.vault), simular=opciones.simular)
    accion = "Movería" if opciones.simular else "Moví"
    print(
        f"{accion} {resumen['movidas']} de {resumen['revisadas']} notas "
        f"({resumen['sin_cambios']} ya estaban bien, {resumen['errores']} con error)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
