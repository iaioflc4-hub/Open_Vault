"""Transcripción de audio en la misma máquina (opcional, sin servicios externos).

Motor soportado: **faster-whisper** (libre, corre en CPU). El audio no sale de la
máquina: se convierte a WAV con ffmpeg y se transcribe localmente.

La transcripción corre en un proceso aparte, con tiempo máximo y memoria limitada
(ajustable), para que un video largo no se lleve puesto al resto de los servicios
del servidor.

Se instala a mano, solo si la querés usar:

    pip install faster-whisper

y se enciende en el `.env`:

    TRANSCRIPTION_ENGINE=faster-whisper
    TRANSCRIPTION_MODEL=tiny

Sin `TRANSCRIPTION_ENGINE` el bot no transcribe: guarda el video igual y lo dice.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

ENGINE_ALIASES = {"faster-whisper", "faster_whisper", "whisper"}
CACHE_DIR = os.getenv("TRANSCRIPTION_CACHE", str(Path.home() / ".cache" / "openvault-whisper"))


def engine() -> str:
    """Motor elegido en el `.env`. Vacío = transcripción apagada."""
    return os.getenv("TRANSCRIPTION_ENGINE", "").strip()


def available(name: str | None = None) -> bool:
    """¿Está el motor instalado? Sin motor instalado no se promete transcripción."""
    elegido = (name or engine()).strip().lower()
    if not elegido:
        return False
    if elegido in ENGINE_ALIASES:
        return importlib.util.find_spec("faster_whisper") is not None
    return False


def _limit_memory() -> None:
    """Tope de memoria del proceso hijo. 0 o vacío = sin tope.

    Ojo: las librerías de cálculo reservan mucha memoria *virtual* de entrada, así
    que un tope ajustado puede hacer que el motor ni arranque ("mkl_malloc: failed
    to allocate memory"). Por eso viene apagado: la protección normal es mirar
    cuánta memoria libre hay antes de transcribir.
    """
    import resource

    limite_mb = int(os.getenv("TRANSCRIPTION_MEMORY_MB", "0") or 0)
    if limite_mb <= 0:
        return
    limite = limite_mb * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (limite, limite))


def memoria_libre_mb() -> int | None:
    """Memoria disponible del sistema, o None si no se puede leer."""
    try:
        with open("/proc/meminfo", encoding="ascii") as info:
            for linea in info:
                if linea.startswith("MemAvailable:"):
                    return int(linea.split()[1]) // 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


def _hay_memoria_para_transcribir() -> tuple[bool, int | None]:
    """¿Conviene arrancar ahora? Un modelo de 1 GB de memoria no puede con dos trabajos."""
    minimo = int(os.getenv("TRANSCRIPTION_MIN_FREE_MB", "450"))
    disponible = memoria_libre_mb()
    if disponible is None:
        return True, None
    return disponible >= minimo, disponible


def transcribe(audio_path: Path, *, language: str = "es", model: str = "tiny") -> str:
    """Texto del audio. Se ejecuta en un subproceso para poder limitar la memoria."""
    audio = Path(audio_path)
    if not audio.is_file():
        raise RuntimeError(f"No existe el audio a transcribir: {audio}")
    if not engine():
        raise RuntimeError("TRANSCRIPTION_ENGINE está vacío: la transcripción está apagada")
    if not available():
        raise RuntimeError("El motor de transcripción no está instalado (pip install faster-whisper)")
    hay_memoria, disponible = _hay_memoria_para_transcribir()
    if not hay_memoria:
        raise RuntimeError(
            f"Quedan {disponible} MB de memoria libre y la transcripción necesita unos 450 MB "
            "para no arrastrar al resto de los servicios. Probá de nuevo en un rato."
        )
    resultado = subprocess.run(
        [
            sys.executable,
            "-m",
            "open_vault.transcribe",
            "transcribir",
            str(audio),
            "--model",
            model or "tiny",
            "--language",
            language or "es",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=int(os.getenv("TRANSCRIPTION_TIMEOUT", "1800")),
        preexec_fn=_limit_memory if os.name == "posix" else None,
    )
    if resultado.returncode != 0:
        detalle = (resultado.stderr or resultado.stdout).strip()[-500:]
        raise RuntimeError(f"La transcripción falló: {detalle}")
    return resultado.stdout.strip()


def _leer_wav(audio: Path):
    """Lee el WAV de 16 kHz que genera ffmpeg como muestras float32.

    El motor puede abrir el archivo por su cuenta, pero para eso usa PyAV, y la
    versión nueva de PyAV y la vieja de faster-whisper no se ponen de acuerdo en
    un argumento. Como el audio lo produce ffmpeg con formato fijo, leerlo con la
    librería estándar es más corto y no depende de esa pelea.
    """
    import wave

    import numpy as np

    with wave.open(str(audio), "rb") as wav:
        if wav.getsampwidth() != 2:
            raise RuntimeError("Se esperaba un WAV de 16 bits; lo genera ffmpeg")
        frecuencia = wav.getframerate()
        canales = wav.getnchannels()
        muestras = np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16)
    datos = muestras.astype(np.float32) / 32768.0
    if canales > 1:
        datos = datos.reshape(-1, canales).mean(axis=1)
    if frecuencia != 16000:
        raise RuntimeError(f"Se esperaba un WAV de 16 kHz y llegó de {frecuencia} Hz")
    return datos


def _transcribir_local(audio: Path, model: str, language: str) -> str:
    # El modelo se guarda en una carpeta propia: si nos apoyáramos en el HOME del
    # usuario del servicio (que puede ser de solo lectura, como /opt/openvault) la
    # descarga falla con "Permission denied" la primera vez. Hugging Face usa
    # varias carpetas de caché además de la del modelo, así que se apuntan todas.
    #
    # Esto va ANTES de importar faster_whisper: la librería lee la configuración
    # de caché al importarse, así que si se cambia después ya no sirve.
    cache = Path(CACHE_DIR).expanduser()
    cache.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("HF_HOME", str(cache))
    os.environ.setdefault("HF_HUB_CACHE", str(cache))
    os.environ.setdefault("XDG_CACHE_HOME", str(cache))
    os.environ.setdefault("HF_XET_CACHE", str(cache / "xet"))
    # La descarga normal por HTTP alcanza y sobra para un modelo de 75 MB; el
    # backend xet suma otra caché que en servidores chicos suele ser de solo lectura.
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

    from faster_whisper import WhisperModel

    motor = WhisperModel(model, device="cpu", compute_type="int8", download_root=str(cache))
    segmentos, _ = motor.transcribe(
        _leer_wav(audio), language=language or None, vad_filter=True, beam_size=1
    )
    return " ".join(segmento.text.strip() for segmento in segmentos).strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Transcribe un audio en la misma máquina.")
    parser.add_argument("orden", nargs="?", default="transcribir")
    parser.add_argument("audio")
    parser.add_argument("--model", default=os.getenv("TRANSCRIPTION_MODEL", "tiny"))
    parser.add_argument("--language", default=os.getenv("TRANSCRIPTION_LANGUAGE", "es"))
    opciones = parser.parse_args(argv)
    print(_transcribir_local(Path(opciones.audio), opciones.model, opciones.language))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
