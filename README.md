# 🏦 BCU · Resoluciones SSF — monitor & análisis

Scrapea diariamente las **Resoluciones de la Superintendencia de Servicios
Financieros** del Banco Central del Uruguay, guarda el dataset y el texto de los
PDF, y entrega un reporte con los **insights más relevantes** desde una óptica de
analista financiero / periodista económico.

Fuente: <https://www.bcu.gub.uy/Servicios-Financieros-SSF/Paginas/Resoluciones_SSF.aspx>
(información pública).

## Qué hace cada día

1. **Scrapea el índice completo** de resoluciones. La página es SharePoint +
   ASP.NET y carga la tabla con un postback asíncrono (`UpdatePanel` + `Timer`);
   `scraper.py` replica ese postback y obtiene las ~4.300 resoluciones, cada una
   con año, mes, número, título y su PDF.
2. **Detecta las nuevas** desde la última corrida (estado en `data/state.json`).
3. **Descarga y guarda el texto** de los PDF nuevos en `data/text/<id>.txt`
   (extracción con `pypdf`).
4. **Analiza** (`analysis.py`):
   - *Heurística (siempre, gratis):* clasifica cada resolución — 🚫 Sanción/Multa,
     ❌ Cancelación/Revocación, ✅ Autorización/Inscripción, ⚖️ Recursos,
     📋 Normativa, 📄 Otros —, identifica la entidad y detecta montos (UI, UR, USD, $),
     y puntúa la relevancia periodística (más peso a sanciones, cancelaciones y
     bancos grandes).
   - *Claude (opcional):* si cargás `ANTHROPIC_API_KEY`, redacta un **briefing
     periodístico** de las resoluciones nuevas más relevantes (modelo
     `claude-opus-4-8`).
5. **Reporta**: comenta en un **issue rotativo de GitHub** (asignado a vos → te
   llega por email gratis) y, si configurás SMTP, manda un **email HTML**. Si no
   hay nada nuevo dice "sin novedades". Commitea el dataset y el reporte al repo.

## Dataset generado (se versiona en el repo)

| Archivo | Contenido |
|---|---|
| `data/resoluciones.json` | Índice completo (todas las resoluciones con metadatos + URL del PDF) |
| `data/text/<id>.txt` | Texto extraído de cada PDF procesado |
| `data/state.json` | IDs ya vistos + nº del issue rotativo |
| `reports/<fecha>.md` | Reporte diario archivado |

## Setup (una vez)

```bash
cd ~/bcu-resoluciones
git init && git add . && git commit -m "setup"
gh repo create bcu-resoluciones --private --source=. --push
```

En GitHub: **Settings → Actions → General → Workflow permissions → Read and write**
(necesario para commitear el dataset y abrir el issue). Después, pestaña
**Actions → BCU Resoluciones SSF → Run workflow** para la primera corrida (baseline).

- La **primera corrida** carga las ~4.300 resoluciones, marca todo como visto,
  analiza a fondo las más recientes y da un panorama del catálogo. De ahí en más,
  sólo reporta lo **nuevo**.

### Briefing con Claude (opcional, de pago)

Cargá el secret `ANTHROPIC_API_KEY` (Settings → Secrets and variables → Actions)
y el reporte incluirá un briefing redactado por Claude. Sin ese secret, el sistema
igual funciona 100% gratis con la heurística.

### Email HTML (opcional)

Secrets: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `EMAIL_TO`
(para Gmail, usá un *App Password*).

## Correr local

```bash
pip install -r requirements.txt
BASELINE_ANALYZE=5 python run.py   # analiza sólo 5 PDFs, para probar
```

| Variable | Default | Qué hace |
|---|---|---|
| `BASELINE_ANALYZE` | 12 | Cuántos PDF analizar a fondo en la primera corrida |
| `MAX_ANALYZE` | 30 | Tope de PDF nuevos a analizar por corrida |
| `ANTHROPIC_API_KEY` | — | Activa el briefing de Claude |

## Costo

El scraping y la heurística son **gratis** (Actions + stdlib + pypdf). El único
costo opcional es el briefing de Claude, si lo activás.

## Notas / límites

- El endpoint de carga es un postback interno de la web del BCU (no una API
  pública documentada): si el BCU cambia la página, hay que ajustar `scraper.py`.
- Algunos PDF son escaneados sin capa de texto: en esos casos se reporta igual con
  el título (que ya trae el sujeto y el resultado de la resolución).
