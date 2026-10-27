"""Vista web del vault: sitio estático para leer las capturas desde el navegador.

No es una aplicación nueva ni un servicio que haya que mantener: es un traductor
entre el Markdown que escribe Open_Vault (adjuntos embebidos, wikilinks y
callouts de Obsidian) y el Markdown que entiende un generador de sitios, más un
`mkdocs build` que ya hace otro: **MkDocs Material** (libre, con búsqueda,
Mermaid y matemática). Escribir un visor propio sería rehacer lo que esta
herramienta ya hace bien.

La salida es una carpeta de HTML estático: la sirve nginx, que ya está corriendo,
sin sumar ningún proceso que consuma RAM.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .enrich import looks_like_math
from .vault import ATTACHMENTS_DIR

EXTENSIONES_VIDEO = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi"}
ARCHIVOS_DE_LA_VISTA = ("config-mathjax.js", "iniciar.js", "estilo.css")

# Se bajan una sola vez y quedan en el repo: el sitio no depende de ningún CDN.
ASSETS_REMOTOS = {
    "mermaid.min.js": "https://cdn.jsdelivr.net/npm/mermaid@11.4.1/dist/mermaid.min.js",
    "tex-mml-chtml.js": "https://cdn.jsdelivr.net/npm/mathjax@3.2.2/es5/tex-mml-chtml.js",
}

EMBED_RE = re.compile(r"!\[\[([^\]|]+?)(?:\|([^\]]+))?\]\]")
WIKILINK_RE = re.compile(r"(?<!!)\[\[([^\]|]+?)(?:\|([^\]]+))?\]\]")
CALLOUT_RE = re.compile(r"^>\s*\[!(\w+)\][+-]?\s*(.*)$")
DISPLAY_MATH_RE = re.compile(r"\$\$(.+?)\$\$", re.DOTALL)
INLINE_MATH_RE = re.compile(r"(?<![\\$\w])\$(?!\s)([^$\n]{1,200}?)\$(?!\w)")
FENCE_RE = re.compile(r"^\s*(```|~~~)")

TIPOS_CALLOUT = {
    "info": "info",
    "note": "note",
    "tip": "tip",
    "hint": "tip",
    "warning": "warning",
    "caution": "warning",
    "danger": "danger",
    "error": "danger",
    "quote": "quote",
    "example": "example",
    "success": "success",
}


@dataclass
class Nota:
    ruta: Path  # relativa al vault, con .md
    titulo: str
    portada: str | None = None

    @property
    def enlace(self) -> str:
        return self.ruta.as_posix()


@dataclass
class ConfiguracionVisor:
    vault: Path
    salida: Path
    assets: Path
    base_url: str = ""
    titulo: str = "Open_Vault"
    indices: dict[str, str] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Traducción del Markdown
# --------------------------------------------------------------------------- #
def _ruta_relativa(destino: str, profundidad: int) -> str:
    """Ruta desde una nota hasta un archivo del vault, subiendo lo necesario.

    Sin codificar a propósito: MkDocs resuelve los enlaces internos comparando la
    ruta real, y un `Categor%C3%ADas` codificado no le coincidiría con el archivo.
    Los nombres que escribe Open_Vault son "slug" sin espacios, así que no hace
    falta escapar nada.
    """
    return "../" * profundidad + destino


def _adjunto(nombre: str, profundidad: int) -> str:
    limpio = nombre.replace("\\", "/").lstrip("/")
    relativo = limpio if limpio.startswith(f"{ATTACHMENTS_DIR}/") else f"{ATTACHMENTS_DIR}/{limpio}"
    return _ruta_relativa(relativo, profundidad)


def convertir_markdown(texto: str, *, profundidad: int = 0, indices: dict[str, str] | None = None) -> str:
    """Convierte una nota del vault al Markdown que entiende el visor.

    - `![[Attachments/x.svg]]` -> imagen real; los videos no se copian al sitio
      (harían pesada cada regeneración) y quedan como aviso.
    - `[[Otra nota]]` -> enlace relativo si la nota está en el vault; si no, texto.
    - `> [!info] Título` -> admonición de MkDocs, que dibuja el recuadro.
    - `$…$` y `$$…$$` -> delimitadores que MathJax reconoce, para que el visor no
      confunda un precio con una fórmula.
    """
    indices = indices or {}
    texto = DISPLAY_MATH_RE.sub(lambda m: f"\n\\[\n{m.group(1).strip()}\n\\]\n", texto)
    texto = INLINE_MATH_RE.sub(
        lambda m: f"\\({m.group(1).strip()}\\)" if looks_like_math(m.group(1)) else m.group(0), texto
    )

    salida: list[str] = []
    callout: list[str] = []
    dentro_de_bloque = False

    def cerrar_callout() -> None:
        if not callout:
            return
        coincidencia = CALLOUT_RE.match(callout[0])
        if coincidencia:
            tipo = TIPOS_CALLOUT.get(coincidencia.group(1).lower(), "note")
            titulo = coincidencia.group(2).strip().replace('"', "'")
            salida.append(f'!!! {tipo} "{titulo}"' if titulo else f"!!! {tipo}")
            salida.extend(f"    {linea.removeprefix('>').strip()}" for linea in callout[1:])
        else:
            salida.extend(callout)
        callout.clear()

    for linea in texto.splitlines():
        if FENCE_RE.match(linea):
            cerrar_callout()
            dentro_de_bloque = not dentro_de_bloque
            salida.append(linea)
            continue
        if dentro_de_bloque:
            salida.append(linea)
            continue
        if CALLOUT_RE.match(linea) or (callout and linea.startswith(">")):
            callout.append(linea)
            continue
        cerrar_callout()
        salida.append(_convertir_enlaces(linea, profundidad, indices))

    cerrar_callout()
    return "\n".join(salida) + "\n"


def _convertir_enlaces(linea: str, profundidad: int, indices: dict[str, str]) -> str:
    def reemplazar_embed(coincidencia: re.Match[str]) -> str:
        nombre, alias = coincidencia.group(1).strip(), (coincidencia.group(2) or "").strip()
        if Path(nombre).suffix.lower() in EXTENSIONES_VIDEO:
            return f"> El video original queda en tu vault (`{nombre}`); no se copia a la vista web."
        enlace = _adjunto(nombre, profundidad)
        return f"![{alias or Path(nombre).stem}]({enlace})"

    def reemplazar_wikilink(coincidencia: re.Match[str]) -> str:
        objetivo, alias = coincidencia.group(1).strip(), (coincidencia.group(2) or "").strip()
        texto = alias or Path(objetivo).stem
        if destino := indices.get(Path(objetivo).stem):
            return f"[{texto}]({_ruta_relativa(destino, profundidad)})"
        if objetivo.startswith(f"{ATTACHMENTS_DIR}/"):
            return f"[{texto}]({_adjunto(objetivo, profundidad)})"
        return texto

    return WIKILINK_RE.sub(reemplazar_wikilink, EMBED_RE.sub(reemplazar_embed, linea))


# --------------------------------------------------------------------------- #
# Armado del sitio
# --------------------------------------------------------------------------- #
def _notas_del_vault(vault: Path) -> list[Path]:
    return sorted(ruta for ruta in vault.rglob("*.md") if ATTACHMENTS_DIR not in ruta.parts)


def _titulo_de_nota(ruta: Path) -> str:
    try:
        for linea in ruta.read_text(encoding="utf-8").splitlines()[:25]:
            if linea.startswith("# "):
                return linea[2:].strip()
    except OSError:
        pass
    return ruta.stem


def _portada(vault: Path, nota: Path) -> str | None:
    ficha = vault / ATTACHMENTS_DIR / f"{nota.stem}-ficha.svg"
    return ficha.name if ficha.is_file() else None


def _inventario(vault: Path) -> list[Nota]:
    return [Nota(ruta=nota.relative_to(vault), titulo=_titulo_de_nota(nota), portada=_portada(vault, nota)) for nota in _notas_del_vault(vault)]


def _copiar_adjuntos(vault: Path, destino: Path) -> int:
    """Copia solo lo liviano: imágenes y SVG. Los videos se quedan en el vault."""
    origen = vault / ATTACHMENTS_DIR
    if not origen.is_dir():
        return 0
    destino.mkdir(parents=True, exist_ok=True)
    copiados = 0
    for archivo in sorted(origen.iterdir()):
        if not archivo.is_file() or archivo.suffix.lower() in EXTENSIONES_VIDEO:
            continue
        shutil.copy2(archivo, destino / archivo.name)
        copiados += 1
    return copiados


def _portada_index(notas: list[Nota], base: str) -> str:
    """Grilla de tarjetas: la ficha SVG de cada nota ya trae su propio diseño."""
    tarjetas = [
        f'  <a class="ov-tarjeta" href="{base}{nota.enlace}">\n'
        f'    <img src="{base}{ATTACHMENTS_DIR}/{nota.portada}" alt="{nota.titulo}" loading="lazy">\n'
        f"  </a>"
        for nota in notas
        if nota.portada
    ]
    if not tarjetas:
        return "_Todavía no hay capturas con ficha._"
    return '<div class="ov-tarjetas">\n' + "\n".join(tarjetas) + "\n</div>"


def _copiar_archivos_de_la_vista(assets: Path, destino: Path) -> None:
    destino.mkdir(parents=True, exist_ok=True)
    for nombre in ARCHIVOS_DE_LA_VISTA:
        origen = assets / nombre
        if origen.is_file():
            shutil.copy2(origen, destino / nombre)


def bajar_assets(destino: Path) -> None:
    """Trae Mermaid y MathJax una sola vez: el sitio queda sin dependencias externas."""
    destino.mkdir(parents=True, exist_ok=True)
    for nombre, url in ASSETS_REMOTOS.items():
        if (destino / nombre).is_file():
            continue
        print(f"  bajando {nombre}...")
        with urllib.request.urlopen(url, timeout=120) as respuesta:  # noqa: S310 - URL fija del proyecto
            (destino / nombre).write_bytes(respuesta.read())


def construir(config: ConfiguracionVisor) -> Path:
    """Genera el sitio completo. Devuelve la carpeta de salida."""
    vault, salida = Path(config.vault), Path(config.salida)
    if not vault.is_dir():
        raise FileNotFoundError(f"No existe el vault: {vault}")
    bajar_assets(config.assets)

    notas = _inventario(vault)
    indices = {nota.ruta.stem: nota.ruta.as_posix() for nota in notas}

    with tempfile.TemporaryDirectory(prefix="openvault-web-") as temporal:
        raiz = Path(temporal)
        docs = raiz / "docs"
        docs.mkdir()
        for nota in notas:
            destino = docs / nota.ruta
            destino.parent.mkdir(parents=True, exist_ok=True)
            origen = vault / nota.ruta
            destino.write_text(
                convertir_markdown(origen.read_text(encoding="utf-8"), profundidad=len(nota.ruta.parts) - 1, indices=indices),
                encoding="utf-8",
            )

        adjuntos_docs = docs / ATTACHMENTS_DIR
        copiados = _copiar_adjuntos(vault, adjuntos_docs)
        _copiar_archivos_de_la_vista(config.assets, adjuntos_docs)

        (docs / "index.md").write_text(
            "# Open_Vault\n\n"
            f"Actualizado el {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC · "
            f"{len(notas)} capturas · {copiados} adjuntos\n\n"
            f"{_portada_index(notas, config.base_url)}\n",
            encoding="utf-8",
        )
        (raiz / "mkdocs.yml").write_text(_configuracion_mkdocs(salida, config), encoding="utf-8")

        resultado = subprocess.run(
            [sys.executable, "-m", "mkdocs", "build", "--config-file", str(raiz / "mkdocs.yml")],
            cwd=raiz,
            capture_output=True,
            text=True,
        )
        if resultado.returncode:
            raise RuntimeError(f"mkdocs falló:\n{resultado.stdout[-1500:]}\n{resultado.stderr[-1500:]}")
    return salida


def _configuracion_mkdocs(salida: Path, config: ConfiguracionVisor) -> str:
    site_url = f"site_url: {config.base_url}\n" if config.base_url else ""
    return f"""site_name: {config.titulo}
docs_dir: docs
site_dir: {salida.as_posix()}
{site_url}use_directory_urls: true
theme:
  name: material
  language: es
  # Sin tipografías de Google: el sitio no debe pedirle nada a un tercero, ni
  # necesitar internet para verse bien.
  font: false
  palette:
    - media: "(prefers-color-scheme: dark)"
      scheme: slate
      primary: teal
      toggle:
        icon: material/weather-sunny
        name: Pasar a claro
    - media: "(prefers-color-scheme: light)"
      scheme: default
      primary: teal
      toggle:
        icon: material/weather-night
        name: Pasar a oscuro
  features:
    - navigation.top
    - search.highlight
    - content.code.copy
plugins:
  - search:
      lang: es
markdown_extensions:
  - meta
  - attr_list
  - tables
  - admonition
  - footnotes
  - toc:
      permalink: true
  - pymdownx.details
  - pymdownx.superfences:
      custom_fences:
        - name: mermaid
          class: mermaid
          format: !!python/name:pymdownx.superfences.fence_code_format
  - pymdownx.arithmatex:
      generic: true
extra_javascript:
  - Attachments/config-mathjax.js
  - Attachments/tex-mml-chtml.js
  - Attachments/mermaid.min.js
  - Attachments/iniciar.js
extra_css:
  - Attachments/estilo.css
extra:
  generator: false
"""


def _hay_cambios(vault: Path, salida: Path) -> bool:
    marca = salida / "index.html"
    if not marca.is_file():
        return True
    momento = marca.stat().st_mtime
    return any(nota.stat().st_mtime > momento for nota in _notas_del_vault(vault))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Genera la vista web del vault de Open_Vault.")
    parser.add_argument("--vault", default=os.getenv("VAULT_PATH", "/srv/obsidian/Open_Vault"))
    parser.add_argument("--salida", default=os.getenv("VISOR_SALIDA", "/var/www/openvault-web"))
    parser.add_argument("--assets", default=os.getenv("VISOR_ASSETS", ""))
    parser.add_argument("--base-url", default=os.getenv("VISOR_BASE_URL", ""))
    parser.add_argument("--forzar", action="store_true", help="Regenera aunque no haya cambios en el vault")
    parser.add_argument("--bajar-assets", action="store_true", help="Solo descarga Mermaid y MathJax")
    opciones = parser.parse_args(argv)

    assets = Path(opciones.assets) if opciones.assets else Path(__file__).resolve().parents[2] / "visor" / "assets"
    if opciones.bajar_assets:
        bajar_assets(assets)
        return 0

    vault, salida = Path(opciones.vault), Path(opciones.salida)
    if not opciones.forzar and not _hay_cambios(vault, salida):
        print("Sin cambios en el vault: no regenero.")
        return 0

    print(f"Generando la vista web de {vault} en {salida}...")
    construir(ConfiguracionVisor(vault=vault, salida=salida, assets=assets, base_url=opciones.base_url))
    print("Listo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
