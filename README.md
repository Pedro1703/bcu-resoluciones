# 🏦 BCU · Radar del Sistema Financiero

Convierte las **Resoluciones de la Superintendencia de Servicios Financieros (SSF)**
del Banco Central del Uruguay en un **sitio de inteligencia estratégica** que se
actualiza solo todos los días y se publica en GitHub Pages.

No es un feed de avisos: es un tablero para entender **cómo cambia la estructura del
sistema financiero uruguayo** —quién compra a quién, quién incumple y quién entra o
sale del mercado—.

Fuente: <https://www.bcu.gub.uy/Servicios-Financieros-SSF/Paginas/Resoluciones_SSF.aspx>
(información pública).

## Qué muestra el sitio

- **🗺️ Mapa de poder** — grafo interactivo de propiedad y control: cada nodo es una
  entidad, cada arista una operación de M&A, transferencia de acciones o cambio de
  control. Clic en un nodo → su historia regulatoria.
- **⚖️ Sanciones** — evolución de multas y sanciones, ranking de reincidentes y montos.
- **🔄 Altas y bajas** — entradas (nuevas inscripciones) vs. salidas (cancelaciones /
  revocaciones) del mercado regulado, por año.
- **📰 Informe** — análisis narrativo del momento, redactado por Claude.
- **🔎 Buscador** — las ~4.300 resoluciones, filtrables.

## Cómo funciona (cada día)

1. **`scraper.py`** replica el postback ASP.NET/SharePoint y baja el índice completo.
2. **`extract.py`** elige los candidatos estratégicos (M&A, sanciones, altas/bajas),
   descarga su PDF y los pasa por **Claude con salida estructurada** (`output_config`
   JSON schema): entidad canónica, acción, contraparte, %, monto, resultado, relevancia.
   Cada PDF se procesa **una sola vez** (cache en `data/extracted/<id>.json`), así el
   costo queda acotado. Las nuevas tienen prioridad; el histórico se backfillea de a
   tandas (`MAX_EXTRACT` por corrida).
3. **`aggregate.py`** arma los datasets (grafo, sanciones, altas/bajas, perfiles).
4. **`briefing.py`** redacta el informe con Claude (streaming + thinking adaptativo).
5. **`build_site.py`** escribe `docs/data/*.json`; el sitio (`docs/index.html`) los lee.
6. El workflow commitea `data/` + `docs/`; GitHub Pages publica `docs/`.

Sin `ANTHROPIC_API_KEY` el sistema **igual funciona** con una heurística gratuita
(clasificación por reglas), pero el mapa de relaciones y el informe narrativo necesitan
Claude para tener calidad de analista.

## Setup

1. **Pages:** Settings → Pages → Source = *Deploy from a branch* → `main` / `/docs`.
2. **Permisos:** Settings → Actions → General → Workflow permissions → *Read and write*.
3. **Claude (recomendado):** Settings → Secrets and variables → Actions → secret
   `ANTHROPIC_API_KEY`.
4. **Primera corrida:** Actions → *BCU Resoluciones SSF* → *Run workflow*. Para un
   backfill inicial grande, poné un número en el input *baseline_extract* (ej. `400`).

| Variable | Default | Qué hace |
|---|---|---|
| `BASELINE_EXTRACT` | 120 | Candidatos a extraer en la 1ª corrida (input del workflow) |
| `MAX_EXTRACT` (repo var) | 120 | Candidatos por corrida diaria (backfill) |
| `ANTHROPIC_API_KEY` | — | Activa extracción + informe con Claude |
| `EXTRACT_MODEL` | `claude-opus-4-8` | Modelo de extracción (ej. `claude-haiku-4-5` para abaratar) |

## Datos versionados

| Archivo | Contenido |
|---|---|
| `data/resoluciones.json` | Índice completo |
| `data/text/<id>.txt` | Texto de cada PDF procesado |
| `data/extracted/<id>.json` | Extracción estructurada (cache) |
| `data/state.json` | IDs vistos + extraídos |
| `docs/` | Sitio publicado (GitHub Pages) |

## Costo

Scraping, heurística y sitio: **gratis**. El único costo es Claude (extracción +
informe), acotado por el cache y por `MAX_EXTRACT`. Se puede bajar usando
`EXTRACT_MODEL=claude-haiku-4-5`.
