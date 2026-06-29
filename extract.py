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


def _heuristic_extract(item, text):
    """Versión degradada sin Claude: usa las reglas de classify.py."""
    title = item["title"]
    cat = classify.classify(title, text)
    entity = classify.extract_entity(title)
    amounts = classify.extract_amounts(text)
    t = title.lower()
    es_ma = bool(re.search(r"transfer|acci[oó]n|fusi[oó]n|adquisic|cambio de control|cambio accionario", t))
    if es_ma:
        accion = "fusion" if "fusi" in t else ("adquisicion" if "adquisic" in t else "transferencia_control")
    elif re.search(r"multa", t):
        accion = "multa"
    elif re.search(r"sanci|apercibi|observaci|suspensi|inhabilit|clausura", t):
        accion = "sancion"
    elif re.search(r"cancela|revoca|cese\b|liquidaci|baja\b", t):
        accion = "cancelacion"
    elif re.search(r"inscrip", t):
        accion = "inscripcion"
    elif re.search(r"autoriza|habilita|apertura", t):
        accion = "autorizacion"
    elif re.search(r"recurso", t):
        accion = "recurso"
    else:
        accion = "otro"
    monto_valor, monto_moneda = None, None
    if amounts:
        m = re.match(r"([\d\.\,]+)\s*(\w+)", amounts[0])
        if m:
            num = m.group(1).replace(".", "").replace(",", ".")
            try:
                monto_valor = float(num)
            except ValueError:
                monto_valor = None
            monto_moneda = m.group(2).upper()
    return {
        "entidad_principal": entity,
        "entidad_normalizada": entity[:50],
        "tipo_entidad": "otro",
        "accion": accion,
        "es_ma": es_ma,
        "contraparte": None,
        "contraparte_normalizada": None,
        "porcentaje": None,
        "monto_valor": monto_valor,
        "monto_moneda": monto_moneda,
        "resultado": "",
        "resumen": title,
        "relevancia": "alta" if cat.startswith(("🚫", "❌")) else "media",
        "_motor": "heuristica",
    }


def extract(item, text):
    """Devuelve el registro estructurado de una resolución (Claude o heurística)."""
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
