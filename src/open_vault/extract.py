"""Lectura de páginas web: texto íntegro, metadatos e imagen principal.

Dos cuidados que importan acá:

  1. **SSRF**: solo se descarga de hosts públicos. Se resuelve el nombre y se
     rechaza cualquier dirección privada, local o reservada; y se valida cada
     salto de redirección, no solo la URL inicial.
  2. **Nada de resúmenes**: trafilatura saca el texto principal completo. Si no
     hay texto legible, se avisa; no se inventa contenido.
"""
from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
import trafilatura

REPO_URL = "https://github.com/iaioflc4-hub/Open_Vault"
USER_AGENT = f"OpenVault/0.1 (+{REPO_URL})"
MAX_REDIRECTS = 5
HTML_TYPES = ("text/html", "application/xhtml")


@dataclass(frozen=True)
class PageContent:
    """Lo que se pudo sacar de una página, sin adornos."""

    url: str
    title: str
    text: str
    site_name: str = ""
    description: str = ""
    image_url: str = ""
    author: str = ""


def validate_public_http_url(url: str) -> str:
    """Rechaza esquemas raros, credenciales embebidas y destinos no públicos."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Only absolute HTTP/HTTPS URLs are supported")
    if parsed.username or parsed.password:
        raise ValueError("URLs containing credentials are not allowed")
    try:
        addresses = socket.getaddrinfo(
            parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM
        )
    except socket.gaierror as exc:
        raise ValueError("Could not resolve URL host") from exc
    if not addresses:
        raise ValueError("URL host resolved to no addresses")
    for result in addresses:
        address = ipaddress.ip_address(result[4][0].split("%", 1)[0])
        if not address.is_global:
            raise ValueError("Private, local, or reserved network addresses are not allowed")
    return url


def _read_body(response: requests.Response, max_bytes: int) -> bytes:
    body = bytearray()
    for chunk in response.iter_content(chunk_size=65536):
        body.extend(chunk)
        if len(body) > max_bytes:
            raise ValueError("La descarga supera el límite configurado")
    return bytes(body)


def fetch_html(url: str, max_bytes: int = 8 * 1024 * 1024) -> tuple[str, str, str]:
    """Descarga HTML siguiendo redirecciones seguras.

    Devuelve `(url_final, html, codificación)`. Cada salto se valida antes de
    seguirlo: una redirección no puede llevarnos a `127.0.0.1`.
    """
    current = validate_public_http_url(url)
    with requests.Session() as session:
        for _ in range(MAX_REDIRECTS + 1):
            with session.get(
                current,
                headers={"User-Agent": USER_AGENT},
                timeout=(5, 20),
                stream=True,
                allow_redirects=False,
            ) as response:
                if response.is_redirect or response.is_permanent_redirect:
                    location = response.headers.get("Location", "")
                    if not location:
                        raise ValueError("Redirección sin destino")
                    current = validate_public_http_url(urljoin(current, location))
                    continue
                response.raise_for_status()
                content_type = response.headers.get("Content-Type", "").lower()
                if not any(kind in content_type for kind in HTML_TYPES):
                    raise ValueError("La URL no devolvió HTML")
                declared = int(response.headers.get("Content-Length", "0") or 0)
                if declared > max_bytes:
                    raise ValueError("La página supera el límite de descarga")
                encoding = response.encoding or "utf-8"
                return current, _read_body(response, max_bytes).decode(encoding, errors="replace"), encoding
        raise ValueError("Demasiadas redirecciones")


def extract_page(url: str, max_bytes: int = 8 * 1024 * 1024) -> PageContent:
    """Texto principal íntegro + metadatos (título, sitio, imagen principal)."""
    final_url, html, _ = fetch_html(url, max_bytes)
    # `output_format="markdown"` conserva los encabezados y las tablas: sin eso, la
    # nota llega sin estructura y no hay diagrama que dibujar.
    text = trafilatura.extract(
        html,
        url=final_url,
        output_format="markdown",
        include_comments=False,
        include_tables=True,
        favor_precision=False,
    )
    if not text or not text.strip():
        raise ValueError("No se pudo extraer texto legible de esta página")
    metadata = trafilatura.extract_metadata(html, default_url=final_url)
    return PageContent(
        url=final_url,
        title=(getattr(metadata, "title", None) or final_url).strip(),
        text=text.strip(),
        site_name=(getattr(metadata, "sitename", None) or urlparse(final_url).netloc).strip(),
        description=(getattr(metadata, "description", None) or "").strip(),
        image_url=(getattr(metadata, "image", None) or "").strip(),
        author=(getattr(metadata, "author", None) or "").strip(),
    )


def extract_article(url: str, max_bytes: int = 8 * 1024 * 1024) -> tuple[str, str]:
    """Compatibilidad: (título, texto)."""
    page = extract_page(url, max_bytes)
    return page.title, page.text


def download_image(url: str, destination: Path, *, max_bytes: int = 3 * 1024 * 1024) -> bool:
    """Baja la imagen principal de una página. Si falla, la captura sigue igual."""
    try:
        current = validate_public_http_url(url)
    except ValueError:
        return False
    try:
        with requests.Session() as session:
            for _ in range(MAX_REDIRECTS + 1):
                with session.get(
                    current,
                    headers={"User-Agent": USER_AGENT},
                    timeout=(5, 20),
                    stream=True,
                    allow_redirects=False,
                ) as response:
                    if response.is_redirect or response.is_permanent_redirect:
                        location = response.headers.get("Location", "")
                        if not location:
                            return False
                        current = validate_public_http_url(urljoin(current, location))
                        continue
                    response.raise_for_status()
                    if not response.headers.get("Content-Type", "").lower().startswith("image/"):
                        return False
                    if int(response.headers.get("Content-Length", "0") or 0) > max_bytes:
                        return False
                    body = _read_body(response, max_bytes)
                    if not body:
                        return False
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(body)
                    return True
    except (requests.RequestException, ValueError, OSError):
        return False
    return False
