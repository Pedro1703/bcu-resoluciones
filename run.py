"""
Orquestador del proyecto BCU · Resoluciones SSF.

Cada corrida:
  1. Scrapea el índice completo de resoluciones (data/resoluciones.json).
  2. Elige candidatos estratégicos no procesados (M&A, sanciones, altas/bajas),
     descarga su PDF y los extrae con Claude (cacheado en data/extracted/<id>.json).
     Las nuevas tienen prioridad; el resto del histórico se backfillea de a tandas.
  3. Agrega todo en los datasets estratégicos.
  4. Redacta el informe narrativo (Claude).
  5. Construye el sitio (docs/) que se publica en GitHub Pages.
"""

import os
import json
import glob

import scraper
import extract
import aggregate
import briefing
import build_site

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")
TEXT = os.path.join(DATA, "text")
EXTRACTED = os.path.join(DATA, "extracted")
STATE = os.path.join(DATA, "state.json")
CATALOG = os.path.join(DATA, "resoluciones.json")

def _env_int(name, default):
    v = (os.environ.get(name) or "").strip()
    try:
        return int(v) if v else default
    except ValueError:
        return default


BASELINE_EXTRACT = _env_int("BASELINE_EXTRACT", 120)
MAX_EXTRACT = _env_int("MAX_EXTRACT", 120)


def _load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _save(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=0)


def _text_for(item):
    os.makedirs(TEXT, exist_ok=True)
    path = os.path.join(TEXT, item["id"] + ".txt")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return f.read()
    text = scraper.fetch_pdf_text(item["url"])
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return text


def main():
    print("· Scrapeando índice de resoluciones…")
    catalog = scraper.fetch_index()
    print(f"  {len(catalog)} resoluciones en el catálogo.")
    _save(CATALOG, catalog)

    state = _load(STATE, {})
    seen = set(state.get("seen", []))
    extracted_ids = set(state.get("extracted", []))
    first_run = not seen

    # Candidatos estratégicos aún no extraídos, de más nuevos a más viejos.
    cand = [it for it in catalog
            if extract.is_candidate(it) and it["id"] not in extracted_ids]
    cand.sort(key=lambda x: x.get("sort", 0), reverse=True)
    budget = BASELINE_EXTRACT if first_run else MAX_EXTRACT
    todo = cand[:budget]
    new_count = len([it for it in catalog if it["id"] not in seen])

    print(f"· {new_count} resoluciones nuevas. "
          f"Extrayendo {len(todo)} candidatos (de {len(cand)} pendientes)…")
    os.makedirs(EXTRACTED, exist_ok=True)
    for i, it in enumerate(todo, 1):
        text = _text_for(it)
        rec = extract.extract(it, text)
        _save(os.path.join(EXTRACTED, it["id"] + ".json"), rec)
        extracted_ids.add(it["id"])
        if i % 20 == 0 or i == len(todo):
            print(f"  extraídas {i}/{len(todo)}")

    # Carga TODAS las extracciones cacheadas (histórico acumulado).
    records = []
    for p in glob.glob(os.path.join(EXTRACTED, "*.json")):
        r = _load(p, None)
        if r:
            records.append(r)
    print(f"· {len(records)} extracciones acumuladas. Agregando…")

    strategic = aggregate.build(records, catalog)
    informe = briefing.generate(strategic)

    motor = "claude" if any(r.get("_motor") == "claude" for r in records) else "heurística"
    m = build_site.meta(catalog, len(records), motor)
    out = build_site.build(strategic, catalog, informe, m)
    print(f"· Sitio actualizado en {out} (motor: {motor}).")

    state["seen"] = sorted(set(it["id"] for it in catalog))
    state["extracted"] = sorted(extracted_ids)
    _save(STATE, state)

    print(f"· Listo. M&A: {len(strategic['power_graph']['edges'])} · "
          f"Sanciones: {strategic['sanciones']['total']} · "
          f"Altas: {len(strategic['altas_bajas']['altas'])} · "
          f"Bajas: {len(strategic['altas_bajas']['bajas'])}.")


if __name__ == "__main__":
    main()
