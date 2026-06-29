"""
Escribe los datos que consume el sitio estático (docs/index.html).
index.html es estático y versionado; acá sólo regeneramos docs/data/*.json.
"""

import os
import json
import datetime

DOCS = os.path.join(os.path.dirname(__file__), "docs")
DATA = os.path.join(DOCS, "data")


def _write(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))


def build(strategic, catalog, informe_md, meta):
    os.makedirs(DATA, exist_ok=True)
    _write(os.path.join(DATA, "strategic.json"), strategic)
    _write(os.path.join(DATA, "catalog.json"), [
        {"id": it["id"], "year": it["year"], "month": it["month"],
         "number": it["number"], "title": it["title"], "url": it["url"]}
        for it in catalog
    ])
    _write(os.path.join(DATA, "informe.json"), {
        "markdown": informe_md,
        "generated": meta.get("generated"),
    })
    _write(os.path.join(DATA, "meta.json"), meta)
    return DATA


def meta(catalog, n_extracted, motor):
    return {
        "generated": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        "fecha": datetime.date.today().isoformat(),
        "total_catalog": len(catalog),
        "total_extracted": n_extracted,
        "motor": motor,
    }
