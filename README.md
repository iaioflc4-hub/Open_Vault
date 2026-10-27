# Open_Vault

Captura privada, por Telegram, a un vault de Obsidian: mandás un texto, un link,
una imagen o un video, y queda guardado como una nota Markdown **enriquecida**
(con ficha visual, gráficos, diagramas y fórmulas) que se lee de un vistazo.

Todo el procesamiento pasa en tu propia máquina. **No hay servicios de resumen,
no hay costo por uso y no hay API key obligatoria.**

![MIT](https://img.shields.io/badge/licencia-MIT-blue)

## Qué genera

Cada captura se convierte en una nota con esta forma:

```
![[Attachments/2026-10-27-informe-solar-9f2ab31c4d-ficha.svg]]

> [!info] Captura íntegra, sin resumen
> 1.240 palabras · lectura ~7 min · guardado el 2026-10-27 14:02 UTC · tipo `web`

## Estructura del documento
（diagrama Mermaid con los encabezados reales del texto）

## Cifras destacadas
![[Attachments/2026-10-27-informe-solar-9f2ab31c4d-cifras.svg]]
| Dato | Valor |
| --- | --- |
| Cobertura | 87,5 % |

## Fórmulas
$$ E = mc^2 $$

## Contenido íntegro
（el texto completo, tal como se extrajo）

## Adjuntos
![[Attachments/web-4b1c9e0a2f.jpg]]

## Fuente original
https://ejemplo.org/informe
```

De dónde sale cada cosa, sin inventar nada:

| Entrada | Qué se guarda |
| --- | --- |
| Texto suelto | Nota con etiquetas, métricas y estructura |
| Link de una web | Texto principal íntegro (trafilatura), imagen principal, estructura del documento |
| Imagen | El original embebido + el texto extraído con OCR (Tesseract local) |
| Video (archivo) | El original local + una miniatura sacada con ffmpeg |
| Video (link) | La referencia, por dominio, sin subir el archivo a ningún lado |

La **ficha SVG** y el **gráfico de barras** se generan a mano con la librería
estándar de Python: sin dependencias, sin servicios, y el resultado se ve igual
en Obsidian, en un navegador y en la vista previa de GitHub. Las fórmulas van en
LaTeX y los diagramas en Mermaid, que Obsidian ya sabe dibujar: por eso no hace
falta instalar nada parecido a TeX.

## Cómo funciona

```
  Telegram (tú)                     tu servidor                    tu vault
  ─────────────                     ───────────                    ────────
  texto ─┐
  link  ─┤   long polling      ┌──────────────────┐          ┌────────────────────┐
  foto  ─┼──────────────▶  ───▶│ Open_Vault (py)  │ ───────▶ │ Obsidian / Logseq  │
  video ─┘   (sin webhook,      │ + tesseract      │  Markdown│ / Foam / git       │
              sin puertos)      │ + ffmpeg         │  + SVG   └────────────────────┘
                                └──────────────────┘
```

Una sola pieza de software. A propósito **no** usa n8n ni IFTTT: cada servicio
extra que se suma es otro lugar donde se puede romper la privacidad, otra cosa
que mantener y otra cosa que hay que replicar para copiar el proyecto.

## Requisitos

- Linux con Python 3.11 o superior (probado en Debian 13).
- Un token de bot de Telegram (gratis, con [@BotFather](https://t.me/BotFather)).
- Opcional: `tesseract-ocr` para el OCR y `ffmpeg` para las miniaturas.
  `install.sh` los instala si faltan.
- Recursos: anda en un VPS de 1 vCPU y 1 GB de RAM. El vault ya existente en el
  servidor de referencia ocupa menos de 1 MB por cada 100 capturas de texto; las
  imágenes y las miniaturas son lo único que crece.

## Instalación

```bash
git clone https://github.com/iaioflc4-hub/Open_Vault.git
cd Open_Vault
sudo bash install.sh
```

Después, lo único que no se puede automatizar (y es tuyo, nunca se comparte):

```bash
sudo nano /opt/openvault/.env      # pegá BOT_TOKEN de @BotFather
sudo systemctl start open-vault
# escribile /id al bot y poné tu número en ALLOWED_TELEGRAM_USER_IDS
sudo systemctl restart open-vault
```

Para probarlo en tu computadora sin servidor:

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e .
cp .env.example .env && nano .env   # BOT_TOKEN, tu ID y VAULT_PATH local
python -m open_vault.bot
```

## Configuración

| Variable | Por defecto | Para qué |
| --- | --- | --- |
| `BOT_TOKEN` | — | Token de @BotFather (obligatorio) |
| `ALLOWED_TELEGRAM_USER_IDS` | — | IDs autorizados, separados por coma (obligatorio) |
| `VAULT_PATH` | `/srv/obsidian/Open_Vault` | Carpeta del vault |
| `MAX_DOWNLOAD_MB` | `18` | Tamaño máximo por descarga |
| `MAX_IMAGE_MB` | `3` | Tamaño máximo de la imagen principal de una web |
| `OCR_LANGUAGE` | `spa+eng` | Idiomas de Tesseract |
| `FETCH_MAIN_IMAGE` | `true` | Bajar la imagen principal de las páginas |
| `VIDEO_THUMBNAILS` | `true` | Sacar miniatura de los videos (necesita ffmpeg) |

## Uso

- **Texto**: guarda una nota. Si escribís algo con encabezados, cifras como
  `Cobertura: 87,5 %` o fórmulas, la nota sale enriquecida con eso.
- **Link**: guarda el texto íntegro. Si además escribís un comentario junto al
  link, queda como sección `## Comentario propio`.
- **Imagen**: guarda el original y le pega el OCR. El epígrafe que pongas en
  Telegram se usa como título.
- **Video**: si lo mandás como archivo, queda guardado y con miniatura; si es un
  link, queda la referencia. La transcripción está pendiente a propósito: no se
  sube el video a ningún servicio sin que alguien lo configure.
- **`/id`**: muestra tu ID numérico de Telegram.

## Privacidad y límites

- El bot es privado: solo los IDs de `ALLOWED_TELEGRAM_USER_IDS` pueden capturar.
  A cualquier otro le responde que no está autorizado.
- Las URLs se validan contra SSRF: se rechazan direcciones privadas, locales o
  reservadas, y también durante cada redirección.
- Nada se resume ni se reescribe: el texto se guarda completo, tal como se extrajo.
- Nada se envía a terceros. La única excepción sería que configures un proveedor
  de transcripción, que hoy está apagado.
- Límites actuales: la API de bots de Telegram baja archivos de hasta 20 MB, el
  OCR puede tardar unos segundos por imagen en 1 vCPU y los videos se guardan
  completos (si te preocupa el disco, mandalos como link en vez de archivo).

## Pruebas

```bash
python -m unittest discover -s tests -v
```

## Compartir y replicar

El proyecto es chico a propósito: un instalador, un archivo de configuración y
una unidad de systemd. Para que otra persona lo use necesita su propio bot de
Telegram (2 minutos con @BotFather) y su propia carpeta de notas; no hay que
registrarse en ningún servicio ni pagar nada.

Si lo mejorás, un PR con el mismo criterio sirve: **menos dependencias y menos
datos afuera del vault**.

## Hacia dónde puede seguir

- Transcripción de video con un proveedor elegido a conciencia (hoy apagada).
- Etiquetado y categorización con un modelo, **opcional y con clave propia**,
  dejando intacto el funcionamiento sin IA paga.
- Segunda puerta de entrada por correo (IMAP de solo lectura) para reenviar mails.

## Licencia

MIT. Usalo, cambialo y publicalo con libertad.
