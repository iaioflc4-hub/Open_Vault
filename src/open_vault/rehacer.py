"""Rehacer notas de enlaces: volver a leer un link que en su momento no se pudo.

Un link de YouTube o de Instagram guardado antes de que existiera el lector de
enlaces (o cuando el sitio bloqueaba la descarga) quedó como una nota con la URL y
el aviso "Transcripción pendiente". Esa nota no sirve de mucho, pero tampoco hay
que reenviar el link: alcanza con volver a intentar leerlo.

Este paso:

  1. busca las notas de enlaces que quedaron pendientes;
  2. vuelve a pedir el contenido (subtítulos, o el audio para transcribir acá);
  3. escribe lo que encontró —el pie del post, la transcripción— en la misma nota,
     sin tocar lo que ya estaba;
  4. si el título era la URL pelada, le pone el título real del video.

Aunque no haya transcripción, el pie y el título reales ya valen la pena: la nota
se clasifica por su contenido y deja de ser una URL con un aviso.

Después de eso, la reclasificación y el gráfico se encargan del resto (los corre
el sincronizador). Tiene modo `--simular` para ver qué haría antes de tocar nada.
"""
from __future__ import annotations

import argparse
import json
import re
import tempfile
from pathlib import Path

from .extract import validate_public_http_url
from .links import fetch_video_link, transcript_of_link
from .reclasificar import TITLE_RE, _campo, es_nota_de_captura, reclasificar
from .vault import PENDIENTE, completar_nota_video

SOURCE_RE = re.compile(r'^source:\s*"?(?P<url>https?://[^"\n]+?)"?\s*$', re.MULTILINE)


def es_enlace(url: str) -> bool:
    return url.startswith(("http://", "https://"))


def titulo_parece_url(titulo: str) -> bool:
    """Un título que en realidad es la URL: `www.instagram.com/p/…`."""
    limpio = titulo.strip().casefold()
    return es_enlace(limpio) or bool(re.fullmatch(r"(www\.)?[\w.-]+\.[a-z]{2,}(/\S*)?", limpio))


def notas_pendientes(vault: Path) -> list[Path]:
    """Notas de enlaces que quedaron sin transcripción, en orden de nombre."""
    vault = Path(vault)
    pendientes: list[Path] = []
    for nota in sorted(p for p in vault.rglob("*.md") if es_nota_de_captura(p, vault)):
        try:
            texto = nota.read_text(encoding="utf-8")
        except OSError:
            continue
        if PENDIENTE in texto and es_enlace(_campo(texto, SOURCE_RE)):
            pendientes.append(nota)
    return pendientes


def rehacer(
    vault: Path,
    *,
    simular: bool = False,
    limite: int = 0,
    engine: str = "",
    language: str = "",
    model: str = "",
) -> dict[str, int]:
    """Vuelve a leer los enlaces pendientes y completa sus notas."""
    from .config import load_settings

    vault = Path(vault)
    resumen = {
        "pendientes": 0,
        "actualizadas": 0,
        "sin_transcripcion": 0,
        "sin_cambios": 0,
        "errores": 0,
        "reclasificadas": 0,
    }
    lista = notas_pendientes(vault)
    resumen["pendientes"] = len(lista)
    if not lista:
        return resumen

    if not engine:
        try:
            ajustes = load_settings()
        except ValueError:  # noqa: PERF203 - sin .env se usan los valores por defecto
            ajustes = None
        if ajustes is not None:
            engine = ajustes.transcription_engine
            language = language or ajustes.transcription_language
            model = model or ajustes.transcription_model

    for nota in lista[: limite or len(lista)]:
        try:
            texto = nota.read_text(encoding="utf-8")
            url = _campo(texto, SOURCE_RE)
            if not simular:
                validate_public_http_url(url)
            with tempfile.TemporaryDirectory(prefix="openvault-rehacer-") as tmp:
                trabajo = Path(tmp)
                info = fetch_video_link(url, trabajo)
                transcript, origen = transcript_of_link(
                    info, trabajo, engine=engine, language=language, model=model
                )
        except Exception as exc:  # noqa: BLE001 - una nota rota no frena a las demás
            print(f"  error en {nota.name}: {exc}")
            resumen["errores"] += 1
            continue

        # Aunque no haya transcripción, la ficha trae el pie, el autor y el título
        # reales: con eso la nota ya se clasifica por su contenido y deja de ser una
        # URL pelada. Por eso se completa igual.
        titulo_actual = _campo(texto, TITLE_RE)
        nuevo = completar_nota_video(
            texto,
            transcript=transcript,
            transcript_origen=origen,
            description=info.description,
            title=info.title if titulo_parece_url(titulo_actual) else "",
        )
        if not transcript:
            resumen["sin_transcripcion"] += 1
        if nuevo == texto:
            resumen["sin_cambios"] += 1
            print(f"  sin cambios: {nota.name}" + (f" ({info.note})" if info.note else ""))
            continue

        resumen["actualizadas"] += 1
        if not simular:
            nota.write_text(nuevo, encoding="utf-8")
        detalle = f"{len(transcript)} caracteres · {origen}" if transcript else "sin transcripción"
        print(f"  {nota.name}: {detalle}")

    if not simular and resumen["actualizadas"]:
        # Al cambiar el contenido, la categoría de la nota puede ser otra distinta.
        resumen["reclasificadas"] = reclasificar(vault)["movidas"]
    return resumen


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Vuelve a leer las notas de enlaces que quedaron pendientes.")
    parser.add_argument("--vault", default="/srv/obsidian/Open_Vault")
    parser.add_argument("--simular", action="store_true", help="Muestra qué haría, sin tocar los archivos")
    parser.add_argument("--limite", type=int, default=0, help="Cuántas notas como máximo (0 = todas)")
    opciones = parser.parse_args(argv)

    resumen = rehacer(Path(opciones.vault), simular=opciones.simular, limite=opciones.limite)
    accion = "Actualizaría" if opciones.simular else "Actualicé"
    print(
        f"{accion} {resumen['actualizadas']} de {resumen['pendientes']} enlaces pendientes "
        f"({resumen['sin_transcripcion']} sin transcripción, {resumen['sin_cambios']} sin cambios, "
        f"{resumen['errores']} con error)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
