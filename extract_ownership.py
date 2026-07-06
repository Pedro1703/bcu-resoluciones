"""
Extracción de PROPIEDAD con Claude (opción paga, one-off) para las resoluciones
de M&A / transferencia de acciones de la SSF.

De cada PDF, Claude devuelve la composición accionaria RESULTANTE (la sociedad y
sus dueños con %, clasificados en persona física o empresa). Eso alimenta el mapa
de propiedad. Se cachea en data/ownership/<id>.json — cada PDF se paga una vez.

Corre en GitHub Actions con ANTHROPIC_API_KEY. Límite: env OWN_MAX.
"""

import os
import re
import json
import glob

import scraper

MODEL = os.environ.get("EXTRACT_MODEL", "claude-opus-4-8")
OWN_MAX = int(os.environ.get("OWN_MAX", "200") or "200")
MAX_TEXT = 5000

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")
TEXT = os.path.join(DATA, "text")
EXTRACTED = os.path.join(DATA, "extracted")
OWNERSHIP = os.path.join(DATA, "ownership")
CATALOG = os.path.join(DATA, "resoluciones.json")

TIPOS_EMPRESA = [
    "corredor_bolsa", "casa_cambio", "asesor_inversion", "agente_valores",
    "banco", "aseguradora", "afap", "fondo", "emisor_valores",
    "fintech_pago", "administradora", "otro",
]

_SCHEMA = {
    "type": "object",
    "properties": {
        "empresa": {"type": "string", "description": "Nombre de la sociedad cuyas acciones se transfieren, tal como aparece."},
        "empresa_normalizada": {"type": "string", "description": "Nombre canónico corto y consistente de la sociedad, sin tipos societarios (S.A., S.R.L.) salvo que sean marca."},
        "tipo_empresa": {"type": "string", "enum": TIPOS_EMPRESA},
        "propietarios": {
            "type": "array",
            "description": "Composición accionaria RESULTANTE (después de la transferencia). Cada accionista final con su % de participación.",
            "items": {
                "type": "object",
                "properties": {
                    "nombre": {"type": "string", "description": "Nombre completo del accionista (persona física con nombre y apellidos, o empresa/holding)."},
                    "tipo": {"type": "string", "enum": ["persona", "empresa"], "description": "persona = persona física; empresa = sociedad/holding/fondo."},
                    "porcentaje": {"type": ["number", "null"], "description": "Porcentaje accionario 0-100, o null si no se indica."},
                },
                "required": ["nombre", "tipo", "porcentaje"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["empresa", "empresa_normalizada", "tipo_empresa", "propietarios"],
    "additionalProperties": False,
}

_PROMPT = (
    "Sos analista del sistema financiero uruguayo. Te paso una resolución de la "
    "Superintendencia de Servicios Financieros (SSF) del BCU sobre una transferencia "
    "de acciones / cambio de control. Extraé la composición accionaria RESULTANTE "
    "(la que queda DESPUÉS de la operación autorizada), no la anterior.\n\n"
    "Reglas:\n"
    "- 'propietarios' = los accionistas finales de la sociedad, con su % exacto.\n"
    "- Normalizá 'empresa_normalizada' de forma consistente (mismo nombre canónico "
    "para la misma sociedad).\n"
    "- Clasificá cada accionista: 'persona' (persona física) o 'empresa' (sociedad, "
    "holding, fondo, LLC, Ltd, Inc, S.A.).\n"
    "- Nombres de personas completos (nombre + apellidos), sin invertir apellido/nombre.\n"
    "- No inventes: si un % no está, usá null.\n\n"
)


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
    p = os.path.join(TEXT, item["id"] + ".txt")
    if os.path.exists(p):
        return open(p, encoding="utf-8").read()
    t = scraper.fetch_pdf_text(item["url"]) or ""
    open(p, "w", encoding="utf-8").write(t)
    return t


def _claude(item, text):
    from anthropic import Anthropic
    client = Anthropic()
    content = (
        _PROMPT
        + f"TÍTULO: {item['title']}\n\n"
        + f"TEXTO DEL PDF:\n{text[:MAX_TEXT]}"
    )
    resp = client.messages.create(
        model=MODEL,
        max_tokens=1500,
        messages=[{"role": "user", "content": content}],
        output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
    )
    raw = next(b.text for b in resp.content if b.type == "text")
    rec = json.loads(raw)
    u = resp.usage
    return rec, (u.input_tokens, u.output_tokens)


def main():
    catalog = {it["id"]: it for it in _load(CATALOG, [])}
    # docs de M&A según la extracción existente
    ma_ids = []
    for p in glob.glob(os.path.join(EXTRACTED, "*.json")):
        r = _load(p, {})
        if r.get("es_ma") and r["id"] in catalog:
            ma_ids.append(r["id"])
    # priorizar los que tienen tabla de accionistas en el texto cacheado
    def has_table(i):
        tp = os.path.join(TEXT, i + ".txt")
        return os.path.exists(tp) and re.search(r"Accionista|Nombre.{0,3}[Pp]articip", open(tp, encoding="utf-8").read())
    ma_ids.sort(key=lambda i: (0 if has_table(i) else 1, i))

    os.makedirs(OWNERSHIP, exist_ok=True)
    done = {os.path.splitext(os.path.basename(p))[0] for p in glob.glob(os.path.join(OWNERSHIP, "*.json"))}
    todo = [i for i in ma_ids if i not in done][:OWN_MAX]
    print(f"M&A: {len(ma_ids)} · ya hechos: {len(done)} · a extraer ahora: {len(todo)}")

    tin = tout = 0
    for n, i in enumerate(todo, 1):
        item = catalog[i]
        try:
            rec, (ui, uo) = _claude(item, _text_for(item))
            rec.update({"id": i, "url": item["url"], "year": item.get("year"),
                        "title": item["title"], "_motor": "claude"})
            _save(os.path.join(OWNERSHIP, i + ".json"), rec)
            tin += ui; tout += uo
        except Exception as e:
            print(f"  ! {i}: {e}")
        if n % 10 == 0 or n == len(todo):
            cost = tin / 1e6 * 5 + tout / 1e6 * 25
            print(f"  {n}/{len(todo)} · tokens {tin/1000:.0f}K in / {tout/1000:.0f}K out · ~US$ {cost:.2f}")
    cost = tin / 1e6 * 5 + tout / 1e6 * 25
    print(f"LISTO. Costo estimado de esta corrida: ~US$ {cost:.2f}")


if __name__ == "__main__":
    main()
