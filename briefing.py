"""
Informe estratégico narrativo, redactado por Claude a partir de los datasets
ya agregados (M&A, sanciones, altas/bajas). Tono de analista financiero /
periodista económico. Si no hay ANTHROPIC_API_KEY, devuelve un informe armado
con la heurística para que el sitio nunca quede sin texto.
"""

import os

MODEL = os.environ.get("BRIEFING_MODEL", "claude-opus-4-8")


def _material(strategic):
    ma = strategic["ma_timeline"][:12]
    sanc = strategic["sanciones"]["items"][:12]
    altas = strategic["altas_bajas"]["altas"][:8]
    bajas = strategic["altas_bajas"]["bajas"][:8]
    rank = strategic["sanciones"]["ranking"][:8]

    def linea_ma(e):
        pct = f" ({e['pct']}%)" if e.get("pct") else ""
        cp = f" → {e['target']}" if e.get("target") and e["target"] != e["source"] else ""
        return f"- [{e['year']}] {e['source']}{cp}{pct} · {e['accion']} · {e.get('resumen','')}"

    def linea_sanc(s):
        monto = f" · {int(s['monto_valor']):,} {s['monto_moneda']}".replace(",", ".") if s.get("monto_valor") and s.get("monto_moneda") else ""
        return f"- [{s['year']}] {s['entidad']}{monto} · {s.get('resumen','')}"

    return (
        "OPERACIONES DE M&A / CAMBIOS DE CONTROL (más recientes):\n"
        + ("\n".join(linea_ma(e) for e in ma) or "—")
        + "\n\nSANCIONES Y MULTAS (más recientes):\n"
        + ("\n".join(linea_sanc(s) for s in sanc) or "—")
        + "\n\nRANKING DE ENTIDADES MÁS SANCIONADAS:\n"
        + ("\n".join(f"- {e['entidad']}: {e['count']} sanciones · {e.get('montos_fmt','')}" for e in rank) or "—")
        + "\n\nALTAS (nuevas inscripciones):\n"
        + ("\n".join(f"- [{a['year']}] {a['entidad']} ({a['tipo_entidad']})" for a in altas) or "—")
        + "\n\nBAJAS (cancelaciones / revocaciones):\n"
        + ("\n".join(f"- [{b['year']}] {b['entidad']}" for b in bajas) or "—")
    )


def _heuristic_brief(strategic):
    ma = strategic["ma_timeline"][:5]
    sanc = strategic["sanciones"]["items"][:5]
    lines = ["## Panorama del sistema financiero — lectura rápida\n"]
    if ma:
        lines.append("### Movimientos de propiedad y control")
        for e in ma:
            cp = f" → {e['target']}" if e.get("target") != e["source"] else ""
            lines.append(f"- **{e['source']}{cp}** ({e['year']}): {e.get('resumen') or e['title']}")
        lines.append("")
    if sanc:
        lines.append("### Sanciones recientes")
        for s in sanc:
            monto = f" — {int(s['monto_valor']):,} {s['monto_moneda']}".replace(",", ".") if s.get("monto_valor") and s.get("monto_moneda") else ""
            lines.append(f"- **{s['entidad']}**{monto} ({s['year']}): {s.get('resumen') or s['title']}")
        lines.append("")
    lines.append("_Informe generado con heurística (sin Claude). Cargá `ANTHROPIC_API_KEY` para el análisis narrativo completo._")
    return "\n".join(lines)


def generate(strategic):
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return _heuristic_brief(strategic)
    try:
        from anthropic import Anthropic
    except ImportError:
        return _heuristic_brief(strategic)

    prompt = (
        "Sos analista financiero y periodista económico especializado en el sistema "
        "financiero uruguayo. A partir de estos datos —extraídos de las resoluciones de "
        "la Superintendencia de Servicios Financieros del BCU— escribí un INFORME "
        "ESTRATÉGICO en español rioplatense, en Markdown, que sirva como lectura de "
        "cabecera para alguien que quiere entender hacia dónde se mueve el mercado.\n\n"
        "Estructura sugerida:\n"
        "## Titular (1 línea con lo más importante del momento)\n"
        "### El mapa de poder se mueve — analizá las operaciones de M&A / cambios de "
        "control: quién compra a quién, qué implica para la concentración del mercado.\n"
        "### Quién incumple — leé el patrón de sanciones: reincidentes, montos, qué tipo "
        "de entidades.\n"
        "### Quién entra y quién sale — altas vs. bajas, qué segmentos crecen.\n"
        "### A seguir — 2-3 cosas para monitorear.\n\n"
        "Reglas: usá SÓLO los datos provistos, no inventes cifras ni nombres. Si algo no "
        "está, decilo. Sé concreto y con criterio noticioso, nada de relleno.\n\n"
        "DATOS:\n\n" + _material(strategic)
    )
    try:
        client = Anthropic()
        with client.messages.stream(
            model=MODEL,
            max_tokens=4000,
            thinking={"type": "adaptive"},
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            msg = stream.get_final_message()
        text = "".join(b.text for b in msg.content if b.type == "text").strip()
        return text or _heuristic_brief(strategic)
    except Exception as e:
        return _heuristic_brief(strategic) + f"\n\n_(Claude no disponible: {e})_"
