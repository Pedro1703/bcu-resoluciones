"""
Heurística liviana (regex) para clasificar resoluciones por título.

Se usa para: (a) el pre-filtro de candidatos a extracción con Claude, y
(b) el fallback gratuito cuando no hay ANTHROPIC_API_KEY. La clasificación
fina y las relaciones las hace extract.py con Claude.
"""

import re

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


def classify(title, text=""):
    t = title.lower()
    if re.search(r"\brecurso", t):
        return "⚖️ Recursos"
    for label, patterns in CATEGORIES:
        if any(re.search(p, t) for p in patterns):
            return label
    blob = (text or "")[:1500].lower()
    for label, patterns in CATEGORIES:
        if any(re.search(p, blob) for p in patterns):
            return label
    return "📄 Otros"


def extract_entity(title):
    t = title.strip()
    if re.match(r"^\s*recursos?\b", t, re.I):
        return "Recurso administrativo"
    if re.match(r"^\s*(recopilaci[oó]n de normas|reglamentaci[oó]n|circular)\b", t, re.I):
        return "Normativa general"
    head = re.split(r"\s[-–]\s", t, maxsplit=1)[0].strip()
    if len(head) > 90:
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
    seen, uniq = set(), []
    for a in out:
        if a not in seen:
            seen.add(a)
            uniq.append(a)
    return uniq[:4]


def catalog_overview(catalog):
    by_year, by_cat = {}, {}
    for it in catalog:
        by_year[it["year"]] = by_year.get(it["year"], 0) + 1
        cat = classify(it["title"])
        by_cat[cat] = by_cat.get(cat, 0) + 1
    return by_year, by_cat
