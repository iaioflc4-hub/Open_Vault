"""Clasificación por tema, con reglas y sin IA paga.

Tres ideas que importan para que sirva en la práctica:

- **El título pesa más que el cuerpo.** Un video que se llama "Qué es Linux" es de
  tecnología aunque su transcripción mencione de paso una empresa. El pie que
  escribe la persona al mandar algo vale como título, así que pesa el triple.
- **Nunca se clasifica por el formato.** Un video no va a "Videos" por ser video:
  va al tema del que habla. El formato ya queda anotado en `type:` del encabezado.
- **Una etiqueta a mano manda.** Si alguien escribió `#huerta`, ese es el tema,
  aunque la palabra no esté en ninguna lista de acá: el vault se ordena con las
  palabras de quien lo usa, no solo con las de este archivo.
"""
from __future__ import annotations

import re

from .enrich import hashtags

CATEGORIES = {
    "Tecnología": (
        "software", "programación", "programar", "tecnología", "linux", "código", "codigo",
        "github", "servidor", "internet", "red", "base de datos", "inteligencia artificial",
        "machine learning", "computación", "computadora", "hardware", "open source",
        "python", "javascript", "aplicación", "datos", "api", "docker", "terminal",
        "technology", "software libre", "automatización",
    ),
    "Seguridad": (
        "seguridad", "ciberseguridad", "hacking", "hacker", "vulnerabilidad", "malware",
        "ataque", "pentest", "ctf", "criptografía", "privacidad", "firewall", "ransomware",
        "phishing", "exploit", "scanner", "osint", "vpn", "contraseña",
    ),
    "Ciencia": (
        "investigación", "estudio", "ciencia", "científico", "física", "química", "biología",
        "astronomía", "paper", "research", "science", "experimento", "hipótesis", "teoría",
    ),
    "Negocios": (
        "empresa", "mercado", "negocio", "finanzas", "inversión", "economía", "business",
        "company", "startup", "ventas", "marketing", "cliente", "facturación", "empleo",
        "moneda", "banco", "criptomoneda",
    ),
    "Educación": (
        "educación", "aprendizaje", "curso", "enseñar", "escuela", "universidad", "tutorial",
        "clase", "alumno", "docente", "education", "learning", "explicado", "guía",
    ),
    "Salud": (
        "salud", "medicina", "clínica", "médico", "paciente", "nutrición", "síntoma",
        "tratamiento", "health", "medical", "ejercicio físico", "sueño",
    ),
    "Cultura": (
        "cultura", "arte", "música", "libro", "cine", "historia", "filosofía", "literatura",
        "documental", "entrevista", "festival", "poesía",
    ),
    "Deportes": (
        "deporte", "fútbol", "partido", "entrenamiento", "gimnasio", "carrera", "atletismo",
        "torneo", "equipo", "copa",
    ),
    "Viajes": ("viaje", "turismo", "ciudad", "vuelo", "hotel", "ruta", "paisaje", "mapa"),
    "Comida": ("receta", "cocina", "comida", "restaurante", "ingredientes", "horno", "plato"),
    "Política": (
        "política", "gobierno", "elecciones", "ley", "congreso", "presidente", "senado",
        "ministerio", "voto",
    ),
    "Derecho": (
        "contrato", "legal", "abogado", "demanda", "licencia", "copyright", "jurídico",
        "tribunal", "normativa",
    ),
}
UNCATEGORIZED = "Por clasificar"


def _detalle(texto: str, peso: int) -> dict[str, tuple[int, int]]:
    """Puntos y primera aparición de cada tema en un texto."""
    normalizado = re.sub(r"\s+", " ", (texto or "").casefold())
    detalle: dict[str, tuple[int, int]] = {}
    for categoria, terminos in CATEGORIES.items():
        encontrados = sorted(
            normalizado.find(termino) for termino in terminos if termino in normalizado
        )
        puntos = peso * sum(normalizado.count(termino) for termino in terminos)
        detalle[categoria] = (puntos, encontrados[0] if encontrados else -1)
    return detalle


def score(text: str, *, title: str = "") -> dict[str, int]:
    """Puntaje por tema. El título cuenta el triple que el cuerpo."""
    del_cuerpo, del_titulo = _detalle(text, 1), _detalle(title, 3)
    return {
        categoria: del_cuerpo[categoria][0] + del_titulo[categoria][0] for categoria in CATEGORIES
    }


def etiqueta_explicita(title: str, text: str = "") -> str:
    """Primera etiqueta escrita a mano (`#algo`), si hay alguna.

    Se mira el título (el pie del mensaje) antes que el cuerpo: si alguien escribió
    el pie a propósito, ahí está su tema. Devuelve el texto listo para usar como
    categoría: `energia-solar` -> `Energia solar`.
    """
    for fuente in (title, text):
        encontradas = hashtags(fuente or "", limit=1)
        if encontradas:
            return re.sub(r"[-_]+", " ", encontradas[0]).strip().capitalize()
    return ""


def classify(text: str, *, title: str = "") -> str:
    """Tema de una captura, o `Por clasificar` si no hay ninguna pista.

    El orden es: primero las listas de temas (con el título pesando el triple),
    después una etiqueta escrita a mano, y solo si no hay nada, `Por clasificar`.
    Nunca se usa el formato del archivo como categoría.

    Los empates se resuelven de forma previsible: primero el que aparece en el
    título, después el que se menciona antes. Si alguien escribió `#seguridad`
    antes que `#linux`, de eso se estaba ocupando, y el resultado no debería
    depender del orden en que están escritas las listas de este archivo.
    """
    del_cuerpo, del_titulo = _detalle(text, 1), _detalle(title, 3)
    elegida = ""
    mejor: tuple[int, int, int, int, int] | None = None
    for indice, categoria in enumerate(CATEGORIES):
        puntos = del_cuerpo[categoria][0] + del_titulo[categoria][0]
        if puntos <= 0:
            continue
        en_titulo = del_titulo[categoria][1] >= 0
        pos_titulo = del_titulo[categoria][1] if en_titulo else 10**6
        pos_cuerpo = del_cuerpo[categoria][1] if del_cuerpo[categoria][1] >= 0 else 10**6
        clave = (puntos, 1 if en_titulo else 0, -pos_titulo, -pos_cuerpo, -indice)
        if mejor is None or clave > mejor:
            mejor, elegida = clave, categoria
    return elegida or etiqueta_explicita(title, text) or UNCATEGORIZED


__all__ = ["CATEGORIES", "UNCATEGORIZED", "classify", "etiqueta_explicita", "score"]
