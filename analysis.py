"""
Análisis de las resoluciones de la SSF del BCU desde una óptica de
analista financiero / periodista económico.

Dos capas:
  1. Heurística (siempre, gratis): clasifica cada resolución (sanción, multa,
     autorización, inscripción, cancelación, recurso…), extrae la entidad
     involucrada y montos de multas, y puntúa la "relevancia periodística".
  2. Claude (opcional): si existe ANTHROPIC_API_KEY, redacta un briefing
     narrativo de las resoluciones nuevas más relevantes.
"""

import os
import re

# --------------------------------------------------------------------------- #
# Heurística
# --------------------------------------------------------------------------- #

# Orden importa: la primera categoría que matchea gana. Las más "noticiables"
# van primero para que dominen la clasificación.
CATEGORIES = [
    ("🚫 Sanción / Multa", [
        r"\bmulta", r"\bsanci", r"\bapercibi", r"\bamonesta", r"\bobservaci",
        r"\bsuspensi[oó]n", r"\binhabilit", r"\bclausura", r"\bintervenci[oó]n",
    ]),
    ("❌ Cancelación / Revocación", [
        r"\bcancela", r"\brevoca", r"\bbaja\b", r"\bcese\b", r"\bliquidaci[oó]n",
    ]),
    ("✅ Autorización / Inscripción", [
        r"\bautoriza", r"\binscrip", r"\bhabilita", r"\bregistr", r"\baprueba",
        r"\bapertura", r"\bcapital", r"\bfusi[oó]n", r"\badquisici[oó]n",
    ]),
    ("⚖️ Recursos", [
        r"\brecurso", r"\brevocaci[oó]n y jer[aá]rquico", r"\bjer[aá]rquico",
    ]),
    ("📋 Normativa / Instrucción", [
        r"\binstrucci[oó]n", r"\bcircular", r"\bcomunicaci[oó]n", r"\bnorma",
        r"\bplan de", r"\bcronograma",
    ]),
]

# Peso de relevancia periodística por categoría (mayor = más noticiable).
RELEVANCE = {
    "🚫 Sanción / Multa": 100,
    "❌ Cancelación / Revocación": 90,
    "✅ Autorización / Inscripción": 60,
    "⚖️ Recursos": 50,
    "📋 Normativa / Instrucción": 40,
    "📄 Otros": 20,
}

# Instituciones grandes: si aparecen, suben la relevancia (más impacto público).
BIG_NAMES = [
    "BANCO", "ITAÚ", "ITAU", "SANTANDER", "BBVA", "SCOTIABANK", "HSBC",
    "REPÚBLICA", "REPUBLICA", "BROU", "BHU", "PREX", "MIDINERO", "OCA",
    "AFAP", "REPÚBLICA AFAP", "SURA", "ITAÚ AFAP", "SISTARBANC", "ABITAB",
    "REDPAGOS", "BANRED", "VISA", "MASTERCARD", "BINANCE", "RIPIO",
]


def classify(title, text=""):
    t = title.lower()
    # El título es la señal más confiable. Los recursos se rotulan como tales
    # aunque el cuerpo mencione la multa/sanción recurrida.
    if re.search(r"\brecurso", t):
        return "⚖️ Recursos"
    for label, patterns in CATEGORIES:
        if any(re.search(p, t) for p in patterns):
            return label
    # Recién si el título no alcanza, miramos el cuerpo del PDF.
    blob = (text or "")[:1500].lower()
    for label, patterns in CATEGORIES:
        if any(re.search(p, blob) for p in patterns):
            return label
    return "📄 Otros"


def extract_entity(title):
    """La entidad suele ir al inicio del título, antes del primer ' - '."""
    t = title.strip()
    # Títulos procedimentales que no tienen una entidad al frente.
    if re.match(r"^\s*recursos?\b", t, re.I):
        return "Recurso administrativo"
    if re.match(r"^\s*(recopilaci[oó]n de normas|reglamentaci[oó]n|circular)\b", t, re.I):
        return "Normativa general"
    head = re.split(r"\s[-–]\s", t, maxsplit=1)[0].strip()
    if len(head) > 90:  # título sin guion: tomamos las primeras palabras
        head = " ".join(t.split()[:8])
    return head


_AMOUNT_RE = re.compile(
    r"(\d[\d\.\,]{2,})\s*(UI|unidades\s+indexadas|U\$S|USD|d[oó]lares|UR|pesos|\$)",
    re.I,
)


def extract_amounts(text):
    out = []
    for m in _AMOUNT_RE.finditer(text or ""):
        amount, unit = m.group(1), m.group(2)
        unit = unit.upper().replace("UNIDADES INDEXADAS", "UI").replace("DÓLARES", "USD")
        unit = unit.replace("DOLARES", "USD").replace("U$S", "USD")
        out.append(f"{amount} {unit}")
    # de-dup preservando orden
    seen, uniq = set(), []
    for a in out:
        if a not in seen:
            seen.add(a)
            uniq.append(a)
    return uniq[:4]


def relevance_score(item):
    score = RELEVANCE.get(item["category"], 20)
    blob = (item["title"] + " " + item.get("entity", "")).upper()
    if any(b in blob for b in BIG_NAMES):
        score += 30
    if item.get("amounts"):
        score += 25
    return score


def enrich(items_with_text):
    """items_with_text: lista de dicts con al menos title/url/text. Agrega
    category, entity, amounts, score."""
    out = []
    for it in items_with_text:
        text = it.get("text", "")
        it = dict(it)
        it["category"] = classify(it["title"], text)
        it["entity"] = extract_entity(it["title"])
        it["amounts"] = extract_amounts(text)
        it["score"] = relevance_score(it)
        out.append(it)
    out.sort(key=lambda x: x["score"], reverse=True)
    return out


# --------------------------------------------------------------------------- #
# Briefing con Claude (opcional)
# --------------------------------------------------------------------------- #

def llm_briefing(enriched):
    """Devuelve un briefing periodístico (str) o '' si no hay API key / falla."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return ""
    try:
        from anthropic import Anthropic
    except ImportError:
        return ""

    # Armamos el material: las más relevantes, con texto recortado.
    top = enriched[:15]
    material = []
    for it in top:
        snippet = (it.get("text", "") or "")[:1500]
        material.append(
            f"### {it['id']} — {it['month']} {it['year']}\n"
            f"Título: {it['title']}\n"
            f"Categoría heurística: {it['category']}\n"
            f"Montos detectados: {', '.join(it['amounts']) or '—'}\n"
            f"Extracto del PDF:\n{snippet}\n"
        )
    prompt = (
        "Sos un periodista económico y analista financiero especializado en "
        "regulación bancaria uruguaya. Te paso resoluciones NUEVAS de la "
        "Superintendencia de Servicios Financieros del Banco Central del Uruguay.\n\n"
        "Redactá un briefing en español rioplatense, conciso y con criterio "
        "noticioso, que incluya:\n"
        "1. Un titular general de la tanda (1 línea).\n"
        "2. Las 3–5 resoluciones MÁS relevantes: qué pasó, a qué entidad, por qué "
        "importa, y monto/sanción si lo hay. Tono de nota informativa, sin inventar "
        "datos que no estén en el material.\n"
        "3. Una línea de 'a seguir' con lo que conviene monitorear.\n\n"
        "Si algo no está claro en el material, decilo en vez de especular.\n\n"
        "MATERIAL:\n\n" + "\n".join(material)
    )

    try:
        client = Anthropic()
        with client.messages.stream(
            model="claude-opus-4-8",
            max_tokens=4000,
            thinking={"type": "adaptive"},
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            msg = stream.get_final_message()
        return "".join(b.text for b in msg.content if b.type == "text").strip()
    except Exception as e:
        return f"_(No se pudo generar el briefing con Claude: {e})_"


# --------------------------------------------------------------------------- #
# Resúmenes agregados (para overview de catálogo)
# --------------------------------------------------------------------------- #

def catalog_overview(catalog):
    """Conteos por año y por categoría (clasificación por título, sin PDF)."""
    by_year, by_cat = {}, {}
    for it in catalog:
        by_year[it["year"]] = by_year.get(it["year"], 0) + 1
        cat = classify(it["title"])
        by_cat[cat] = by_cat.get(cat, 0) + 1
    return by_year, by_cat
