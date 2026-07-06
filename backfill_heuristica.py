"""
Backfill GRATIS (sin API): genera la extracción heurística mejorada para todas
las resoluciones candidatas que aún no fueron extraídas, y las cachea igual que
run.py. Las que ya tienen extracción con Claude NO se tocan.

Uso: python backfill_heuristica.py
"""

import os
import json
import glob

import extract

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")
TEXT = os.path.join(DATA, "text")
EXTRACTED = os.path.join(DATA, "extracted")
STATE = os.path.join(DATA, "state.json")
CATALOG = os.path.join(DATA, "resoluciones.json")


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


def _cached_text(item):
    p = os.path.join(TEXT, item["id"] + ".txt")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return f.read()
    return ""  # sin descargar nada: título-only, gratis


def main():
    catalog = _load(CATALOG, [])
    state = _load(STATE, {})
    extracted_ids = set(state.get("extracted", []))
    heuristic_ids = set(state.get("heuristic", []))

    # Preservamos las extracciones hechas con Claude (mayor calidad, ya pagadas);
    # regeneramos el resto (heurística vieja + nunca procesadas) con la nueva.
    claude_ids = extracted_ids - heuristic_ids
    cands = [it for it in catalog if extract.is_candidate(it)]
    targets = [it for it in cands if it["id"] not in claude_ids]
    print(f"{len(cands)} candidatos · {len(claude_ids)} Claude (se preservan) · "
          f"{len(targets)} a (re)generar con heurística mejorada.")

    os.makedirs(EXTRACTED, exist_ok=True)
    for i, it in enumerate(targets, 1):
        rec = extract._heuristic_extract(it, _cached_text(it))
        rec = extract._normalize_record(rec, it)
        _save(os.path.join(EXTRACTED, it["id"] + ".json"), rec)
        extracted_ids.add(it["id"])
        heuristic_ids.add(it["id"])  # marcadas como heurística → upgradeables a Claude
        if i % 500 == 0 or i == len(targets):
            print(f"  {i}/{len(targets)}")

    state["extracted"] = sorted(extracted_ids)
    state["heuristic"] = sorted(heuristic_ids)
    _save(STATE, state)

    total = len(glob.glob(os.path.join(EXTRACTED, "*.json")))
    print(f"Listo. {total} extracciones cacheadas en total (0 llamadas a API).")


if __name__ == "__main__":
    main()
