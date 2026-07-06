"""
Extracción estructurada de cada resolución de la SSF.

Convierte el texto crudo de un PDF en un registro limpio y comparable:
entidad canónica, tipo de acción (M&A, sanción, alta, baja…), contraparte,
porcentaje, monto, resultado y relevancia. Eso es lo que después alimenta el
mapa de poder, el panel de sanciones y el de altas/bajas.

Dos motores:
  1. Claude (recomendado): lee el PDF y devuelve el registro con calidad de
     analista. Es lo que permite inferir contrapartes y relaciones de control.
  2. Heurística (fallback gratis): si no hay ANTHROPIC_API_KEY, arma una versión
     degradada del mismo registro con reglas. El sitio igual se construye.

Cada extracción se cachea en data/extracted/<id>.json: cada PDF se procesa una
sola vez, así el costo queda acotado y los backfills no se repiten.
"""

import os
import re
import json

import classify

MODEL = os.environ.get("EXTRACT_MODEL", "claude-opus-4-8")
MAX_TEXT = 6000  # chars del PDF que le pasamos a Claude (los hechos van al inicio)

# Vocabulario controlado para que los datos sean agregables.
TIPOS_ENTIDAD = [
    "banco", "casa_financiera", "afap", "aseguradora", "cooperativa",
    "corredor_bolsa", "asesor_inversion", "emisor_valores", "fondo",
    "fintech_pago", "casa_cambio", "persona", "otro",
]
ACCIONES = [
    "transferencia_control", "fusion", "adquisicion", "cambio_accionario",
    "cambio_directorio", "aumento_capital", "sancion", "multa",
    "inscripcion", "autorizacion", "cancelacion", "revocacion",
    "recurso", "normativa", "otro",
]

_SCHEMA = {
    "type": "object",
    "properties": {
        "entidad_principal": {"type": "string", "description": "Nombre tal cual aparece de la entidad o persona involucrada."},
        "entidad_normalizada": {"type": "string", "description": "Nombre canónico corto y consistente (ej. 'HSBC Bank Uruguay', 'Itaú', 'BROU'). Sin tipos societarios (S.A.) salvo que sean parte del nombre de marca."},
        "tipo_entidad": {"type": "string", "enum": TIPOS_ENTIDAD},
        "accion": {"type": "string", "enum": ACCIONES},
        "es_ma": {"type": "boolean", "description": "true si es un evento de M&A / cambio de propiedad o control (transferencia de acciones, fusión, adquisición, cambio accionario o de control). Alimenta el mapa de poder."},
        "contraparte": {"type": ["string", "null"], "description": "Otra parte involucrada (comprador, adquirente, entidad que se fusiona), si la hay. null si no aplica."},
        "contraparte_normalizada": {"type": ["string", "null"], "description": "Nombre canónico corto de la contraparte, o null."},
        "porcentaje": {"type": ["number", "null"], "description": "Porcentaje accionario involucrado (0-100) si se menciona, o null."},
        "monto_valor": {"type": ["number", "null"], "description": "Valor numérico del monto principal (multa/capital) sin separadores, o null."},
        "monto_moneda": {"type": ["string", "null"], "description": "Moneda del monto: una de UI, UR, USD, UYU; o null si no hay monto."},
        "resultado": {"type": "string", "description": "Resultado en pocas palabras: 'autorizado', 'sancionado con multa', 'inscripción aprobada', 'recurso rechazado', etc."},
        "resumen": {"type": "string", "description": "Una o dos frases claras, en español rioplatense, de qué resolvió la SSF y por qué importa."},
        "relevancia": {"type": "string", "enum": ["alta", "media", "baja"], "description": "Relevancia estratégica/periodística: alta para M&A de bancos grandes, sanciones fuertes, salidas del mercado."},
    },
    "required": [
        "entidad_principal", "entidad_normalizada", "tipo_entidad", "accion",
        "es_ma", "contraparte", "contraparte_normalizada", "porcentaje",
        "monto_valor", "monto_moneda", "resultado", "resumen", "relevancia",
    ],
    "additionalProperties": False,
}

_PROMPT = (
    "Sos analista del sistema financiero uruguayo. Te paso una resolución de la "
    "Superintendencia de Servicios Financieros (SSF) del Banco Central del Uruguay: "
    "su título y el texto del PDF. Extraé los datos estructurados según el schema.\n\n"
    "Reglas:\n"
    "- Normalizá nombres de entidades de forma CONSISTENTE para poder agruparlas "
    "entre resoluciones (mismo banco = mismo 'entidad_normalizada' siempre).\n"
    "- es_ma=true SÓLO si hay cambio de propiedad/control (transferencia de acciones, "
    "fusión, adquisición, cambio accionario o de control). Designar directores sin "
    "cambio de dueño NO es M&A.\n"
    "- No inventes datos: si algo no está en el texto, usá null o el valor más neutro.\n\n"
)


def _candidate_keywords(title):
    """Pre-filtro barato: ¿vale la pena extraer esta resolución con Claude?
    Descartamos lo puramente procedimental/rutinario para acotar costo."""
    t = title.lower()
    pats = [
        r"transfer", r"acci[oó]n", r"fusi[oó]n", r"adquisic", r"control",
        r"capital", r"integr", r"directorio", r"designaci", r"presidente",
        r"director", r"multa", r"sanci", r"apercibi", r"observaci",
        r"suspensi", r"inhabilit", r"clausura", r"intervenci", r"revoca",
        r"cancela", r"cese\b", r"liquidaci", r"baja\b", r"inscrip",
        r"autoriza", r"habilita", r"apertura", r"fondo", r"emisi[oó]n",
    ]
    return any(re.search(p, t) for p in pats)


def is_candidate(item):
    return _candidate_keywords(item["title"])


def _normalize_record(rec, item):
    """Asegura tipos y agrega metadatos de la resolución."""
    out = dict(rec)
    out["id"] = item["id"]
    out["year"] = item["year"]
    out["month"] = item["month"]
    out["month_num"] = item.get("month_num", 0)
    out["number"] = item["number"]
    out["title"] = item["title"]
    out["url"] = item["url"]
    out["sort"] = item.get("sort", 0)
    # Coerciones defensivas.
    if out.get("monto_moneda") in ("", "null"):
        out["monto_moneda"] = None
    return out


def _claude_extract(item, text):
    from anthropic import Anthropic
    client = Anthropic()
    content = (
        _PROMPT
        + f"TÍTULO: {item['title']}\n"
        + f"AÑO/MES: {item['month']} {item['year']}\n\n"
        + f"TEXTO DEL PDF (puede estar recortado o vacío si es escaneado):\n{text[:MAX_TEXT]}"
    )
    resp = client.messages.create(
        model=MODEL,
        max_tokens=2000,
        messages=[{"role": "user", "content": content}],
        output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
    )
    raw = next(b.text for b in resp.content if b.type == "text")
    return json.loads(raw)


_RESULTADO = {
    "fusion": "fusión autorizada",
    "adquisicion": "adquisición autorizada",
    "transferencia_control": "transferencia de control autorizada",
    "cambio_accionario": "cambio accionario autorizado",
    "aumento_capital": "aumento de capital aprobado",
    "cambio_directorio": "cambio de directorio",
    "multa": "sancionado con multa",
    "sancion": "sancionado",
    "revocacion": "autorización revocada",
    "cancelacion": "cancelado / dado de baja",
    "inscripcion": "inscripción aprobada",
    "autorizacion": "autorizado",
    "recurso": "recurso resuelto",
    "normativa": "normativa emitida",
    "otro": "",
}

_BIG_ENTITIES = {
    "BROU", "BHU", "Itaú", "Santander", "BBVA", "Scotiabank", "HSBC",
    "Citibank", "Banco Nación Argentina", "Banco de Seguros del Estado",
}


def _accion_from_title(t):
    """t: título en minúsculas y sin acentos. Devuelve (accion, es_ma)."""
    es_ma = bool(re.search(
        r"transferencia[^.]{0,25}accion|cesi[oó]n[^.]{0,25}accion|"
        r"compraventa[^.]{0,25}accion|paquete accionario|cambio accionario|"
        r"cambio de control|transferencia de control|fusi[oó]n|adquisic|"
        r"integraci[oó]n accionaria", t))
    if es_ma:
        if "fusi" in t:
            return "fusion", True
        if "adquisic" in t:
            return "adquisicion", True
        if "cambio accionario" in t or "paquete accionario" in t:
            return "cambio_accionario", True
        return "transferencia_control", True
    if re.search(r"\brecurso", t):  # apelaciones antes que revoca/cancela
        return "recurso", False
    checks = [
        (r"aumento de capital|integraci[oó]n de capital|reducci[oó]n de capital", "aumento_capital"),
        (r"designaci[oó]n|cambio de directorio|integraci[oó]n del directorio|\bpresidente\b|\bdirector(?:es)?\b", "cambio_directorio"),
        (r"\bmulta", "multa"),
        (r"sanci|apercibi|observaci|suspensi|inhabilit|clausura|intervenci", "sancion"),
        (r"revoca", "revocacion"),
        (r"cancela|\bcese\b|liquidaci|\bbaja\b", "cancelacion"),
        (r"inscrip|registr", "inscripcion"),
        (r"autoriza|habilita|apertura|aprueba", "autorizacion"),
        (r"recurso", "recurso"),
        (r"circular|instrucci[oó]n|comunicaci[oó]n|\bnorma|recopilaci[oó]n", "normativa"),
    ]
    for pat, acc in checks:
        if re.search(pat, t):
            return acc, False
    return "otro", False


def _resultado(accion, neg, pos):
    if accion == "recurso":
        return "recurso rechazado" if neg else ("recurso con lugar" if pos else "recurso resuelto")
    if neg and accion in ("autorizacion", "inscripcion", "fusion", "adquisicion",
                          "transferencia_control", "aumento_capital"):
        return "solicitud rechazada"
    return _RESULTADO.get(accion, "")


def _relevancia(accion, es_ma, entidad, tipo, monto_valor, monto_moneda):
    grande = entidad in _BIG_ENTITIES or tipo in ("banco", "aseguradora", "afap")
    if es_ma and grande:
        return "alta"
    if accion in ("revocacion", "cancelacion") and tipo in ("banco", "aseguradora", "afap", "casa_financiera"):
        return "alta"
    if accion in ("sancion", "multa"):
        v = monto_valor or 0
        if (monto_moneda == "USD" and v >= 100_000) or (monto_moneda == "UI" and v >= 1_000_000):
            return "alta"
        return "media"
    if es_ma:
        return "media"
    if accion in ("recurso", "normativa"):
        return "baja"
    return "media"


def _resumen(entidad, accion, resultado, contraparte, porcentaje, monto_valor, monto_moneda, title):
    verbo = resultado or _RESULTADO.get(accion) or accion.replace("_", " ")
    frase = f"{entidad}: {verbo}" if entidad else verbo
    if contraparte:
        pct = f" ({porcentaje:g}%)" if porcentaje else ""
        frase += f" — contraparte {contraparte}{pct}"
    elif porcentaje:
        frase += f" ({porcentaje:g}%)"
    if monto_valor and monto_moneda:
        frase += " por {:,.0f} {}".format(monto_valor, monto_moneda).replace(",", ".")
    return frase.strip() or title


def _heuristic_extract(item, text):
    """Motor gratis (sin API): llena el registro estructurado con reglas."""
    title = item["title"]
    t = classify._strip_accents(title.lower())

    entity_raw = classify.extract_entity(title)
    entidad_norm = classify.normalize_entity(entity_raw)
    tipo_entidad = classify.entity_type(title, entity_raw)

    accion, es_ma = _accion_from_title(t)

    contraparte = classify.extract_counterparty(title) if es_ma else None
    contraparte_norm = classify.normalize_entity(contraparte) if contraparte else None
    porcentaje = classify.extract_percentage(text, title)
    monto_valor, monto_moneda = classify.parse_main_amount(text, title)

    neg = bool(re.search(r"desestim|rechaz|no ha lugar|no hace lugar|deniega|denegar|denieg", t))
    pos = bool(re.search(r"hace lugar|acoge", t))
    resultado = _resultado(accion, neg, pos)
    relevancia = _relevancia(accion, es_ma, entidad_norm, tipo_entidad, monto_valor, monto_moneda)
    resumen = _resumen(entidad_norm, accion, resultado, contraparte_norm,
                       porcentaje, monto_valor, monto_moneda, title)

    return {
        "entidad_principal": entity_raw,
        "entidad_normalizada": entidad_norm or entity_raw[:50],
        "tipo_entidad": tipo_entidad,
        "accion": accion,
        "es_ma": es_ma,
        "contraparte": contraparte,
        "contraparte_normalizada": contraparte_norm,
        "porcentaje": porcentaje,
        "monto_valor": monto_valor,
        "monto_moneda": monto_moneda,
        "resultado": resultado,
        "resumen": resumen,
        "relevancia": relevancia,
        "_motor": "heuristica",
    }


def extract(item, text):
    """Devuelve el registro estructurado de una resolución (Claude o heurística).

    Con FREE_MODE=1 se fuerza la heurística (gratis) aunque haya API key, para que
    el pipeline diario procese documentos nuevos sin gastar en la API.
    """
    if os.environ.get("FREE_MODE") == "1":
        return _normalize_record(_heuristic_extract(item, text), item)
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            rec = _claude_extract(item, text)
            rec["_motor"] = "claude"
            return _normalize_record(rec, item)
        except Exception as e:
            rec = _heuristic_extract(item, text)
            rec["_motor"] = f"heuristica (claude falló: {e})"
            return _normalize_record(rec, item)
    return _normalize_record(_heuristic_extract(item, text), item)
