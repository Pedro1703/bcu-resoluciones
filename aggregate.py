"""
Agrega las extracciones estructuradas en los datasets que consume el sitio:

- power_graph : grafo de propiedad/control (nodos = entidades, aristas = M&A)
- ma_timeline : línea de tiempo de operaciones de M&A
- sanciones   : serie temporal, ranking de sancionados y detalle
- altas_bajas : entradas vs. salidas del mercado por año
- entities    : perfil por entidad (su historia regulatoria)
- destacadas  : lo de mayor relevancia estratégica
"""

import re


def _money_key(moneda):
    m = (moneda or "").upper()
    return m if m in ("UI", "UR", "USD", "UYU") else None


def _add_money(acc, valor, moneda):
    k = _money_key(moneda)
    if k and valor:
        acc[k] = acc.get(k, 0) + valor


def _fmt_money(acc):
    if not acc:
        return ""
    return " · ".join(f"{int(v):,}".replace(",", ".") + f" {k}" for k, v in acc.items())


def build(records, catalog):
    """records: lista de extracciones (dicts). catalog: índice completo."""
    records = [r for r in records if r]

    # ---- Grafo de poder (M&A) ------------------------------------------- #
    edges, node_set, node_type = [], {}, {}
    for r in records:
        if not r.get("es_ma"):
            continue
        a = (r.get("entidad_normalizada") or r.get("entidad_principal") or "").strip()
        b = (r.get("contraparte_normalizada") or r.get("contraparte") or "").strip()
        if not a:
            continue
        node_set[a] = node_set.get(a, 0) + 1
        node_type.setdefault(a, r.get("tipo_entidad", "otro"))
        if b:
            node_set[b] = node_set.get(b, 0) + 1
            node_type.setdefault(b, "otro")
        edges.append({
            "source": a, "target": b or a, "accion": r.get("accion", "otro"),
            "pct": r.get("porcentaje"), "year": _year(r), "month": r.get("month", ""),
            "month_num": r.get("month_num", 0), "rid": r["id"], "title": r["title"],
            "url": r["url"], "resumen": r.get("resumen", ""),
        })
    nodes = [
        {"id": n, "type": node_type.get(n, "otro"), "events": c}
        for n, c in sorted(node_set.items(), key=lambda x: -x[1])
    ]
    ma_timeline = sorted(
        edges, key=lambda e: (e["year"], e["month_num"]), reverse=True
    )

    # ---- Sanciones ------------------------------------------------------ #
    sanc_items, sanc_by_year, sanc_by_entity = [], {}, {}
    for r in records:
        if r.get("accion") not in ("sancion", "multa"):
            continue
        y = str(_year(r))
        ent = (r.get("entidad_normalizada") or r.get("entidad_principal") or "—").strip()
        item = {
            "rid": r["id"], "entidad": ent, "year": _year(r), "month": r.get("month", ""),
            "monto_valor": r.get("monto_valor"), "monto_moneda": _money_key(r.get("monto_moneda")),
            "title": r["title"], "url": r["url"], "resumen": r.get("resumen", ""),
            "resultado": r.get("resultado", ""),
        }
        sanc_items.append(item)
        yr = sanc_by_year.setdefault(y, {"count": 0, "montos": {}})
        yr["count"] += 1
        _add_money(yr["montos"], r.get("monto_valor"), r.get("monto_moneda"))
        e = sanc_by_entity.setdefault(ent, {"entidad": ent, "count": 0, "montos": {}, "rids": []})
        e["count"] += 1
        e["rids"].append(r["id"])
        _add_money(e["montos"], r.get("monto_valor"), r.get("monto_moneda"))
    for y in sanc_by_year.values():
        y["montos_fmt"] = _fmt_money(y["montos"])
    ranking = sorted(sanc_by_entity.values(), key=lambda x: (-x["count"], x["entidad"]))
    for e in ranking:
        e["montos_fmt"] = _fmt_money(e["montos"])
    sanc_items.sort(key=lambda x: (x["year"], x.get("monto_valor") or 0), reverse=True)

    # ---- Altas y bajas -------------------------------------------------- #
    altas, bajas, ab_by_year = [], [], {}
    for r in records:
        acc = r.get("accion")
        y = str(_year(r))
        slot = ab_by_year.setdefault(y, {"altas": 0, "bajas": 0})
        rec = {
            "rid": r["id"], "entidad": r.get("entidad_normalizada") or r.get("entidad_principal"),
            "tipo_entidad": r.get("tipo_entidad", "otro"), "year": _year(r),
            "month": r.get("month", ""), "title": r["title"], "url": r["url"],
            "resumen": r.get("resumen", ""),
        }
        if acc == "inscripcion":
            altas.append(rec); slot["altas"] += 1
        elif acc in ("cancelacion", "revocacion"):
            bajas.append(rec); slot["bajas"] += 1
    altas.sort(key=lambda x: x["year"], reverse=True)
    bajas.sort(key=lambda x: x["year"], reverse=True)

    # ---- Perfiles por entidad ------------------------------------------ #
    entities = {}
    for r in records:
        ent = (r.get("entidad_normalizada") or r.get("entidad_principal") or "").strip()
        if not ent:
            continue
        e = entities.setdefault(ent, {
            "entidad": ent, "tipo_entidad": r.get("tipo_entidad", "otro"),
            "n": 0, "sanciones": 0, "ma": 0, "eventos": [],
        })
        e["n"] += 1
        if r.get("accion") in ("sancion", "multa"):
            e["sanciones"] += 1
        if r.get("es_ma"):
            e["ma"] += 1
        e["eventos"].append({
            "rid": r["id"], "year": _year(r), "month": r.get("month", ""),
            "accion": r.get("accion"), "resumen": r.get("resumen", ""),
            "title": r["title"], "url": r["url"],
        })
    for e in entities.values():
        e["eventos"].sort(key=lambda x: x["year"], reverse=True)

    # ---- Destacadas ----------------------------------------------------- #
    rank_rel = {"alta": 3, "media": 2, "baja": 1}
    destacadas = sorted(
        records,
        key=lambda r: (rank_rel.get(r.get("relevancia"), 1), _year(r), r.get("sort", 0)),
        reverse=True,
    )[:25]
    destacadas = [{
        "rid": r["id"], "entidad": r.get("entidad_normalizada"), "accion": r.get("accion"),
        "year": _year(r), "month": r.get("month", ""), "resumen": r.get("resumen", ""),
        "relevancia": r.get("relevancia"), "title": r["title"], "url": r["url"],
        "es_ma": r.get("es_ma", False),
    } for r in destacadas]

    # ---- Meta / catálogo ------------------------------------------------ #
    by_year = {}
    for it in catalog:
        by_year[str(it.get("year"))] = by_year.get(str(it.get("year")), 0) + 1

    return {
        "power_graph": {"nodes": nodes, "edges": edges},
        "ma_timeline": ma_timeline,
        "sanciones": {
            "by_year": sanc_by_year, "ranking": ranking[:40], "items": sanc_items,
            "total": len(sanc_items),
        },
        "altas_bajas": {"by_year": ab_by_year, "altas": altas, "bajas": bajas},
        "entities": entities,
        "destacadas": destacadas,
        "by_year": by_year,
    }


def _year(r):
    try:
        return int(re.sub(r"\D", "", str(r.get("year", "0"))) or 0)
    except (ValueError, TypeError):
        return 0
