"""
Heurística de clasificación y extracción liviana (regex + diccionarios) para
las resoluciones de la SSF.

Se usa para: (a) el pre-filtro de candidatos a extracción, y (b) el motor de
extracción GRATIS (sin API) que llena el mismo registro estructurado que
produciría un LLM, en versión determinista. Cuanto mejor sea esto, más completo
queda el sitio (mapa de poder, sanciones, altas/bajas) sin gastar en API.
"""

import re

# ---------------------------------------------------------------------------
# Categorías (para paneles y para derivar relevancia)
# ---------------------------------------------------------------------------
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


def _strip_accents(s):
    return (s or "").translate(str.maketrans("áéíóúüñÁÉÍÓÚÜÑ", "aeiouunAEIOUUN"))


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


# ---------------------------------------------------------------------------
# Normalización de entidades (clave para agrupar la misma entidad en el mapa)
# ---------------------------------------------------------------------------
# (patrón sin acentos, en minúsculas) -> nombre canónico. Orden = prioridad.
_CANON = [
    (r"banco de la rep|\bb\.?r\.?o\.?u\b|\bbrou\b", "BROU"),
    (r"banco hipotecario|\bbhu\b", "BHU"),
    (r"banco de seguros del estado|\bbse\b", "Banco de Seguros del Estado"),
    (r"ita[uú]", "Itaú"),
    (r"santander", "Santander"),
    (r"\bbbva\b|bilbao vizcaya", "BBVA"),
    (r"scotiabank|scotia", "Scotiabank"),
    (r"\bhsbc\b", "HSBC"),
    (r"citibank|\bciti\b", "Citibank"),
    (r"naci[oó]n argentina|\bbna\b", "Banco Nación Argentina"),
    (r"banque heritage|heritage", "Banque Heritage"),
    (r"bandes", "Banco Bandes"),
    (r"banco comercial", "Banco Comercial"),
    (r"rep[uú]blica afap|republica afap", "República AFAP"),
    (r"integraci[oó]n afap", "Integración AFAP"),
    (r"uni[oó]ncapital|union capital", "UniónCapital AFAP"),
    (r"\bsura\b", "SURA"),
    (r"mapfre", "Mapfre"),
    (r"san crist[oó]bal", "San Cristóbal Seguros"),
    (r"sancor", "Sancor Seguros"),
    (r"porto seguro", "Porto Seguro"),
    (r"\bsurco\b", "Surco"),
    (r"abitab", "Abitab"),
    (r"red\s?pagos", "RedPagos"),
    (r"\bprex\b", "Prex"),
    (r"prosegur", "Prosegur"),
    (r"\bfucac\b", "FUCAC"),
    (r"fucerep", "FUCEREP"),
    (r"\banda\b", "ANDA"),
]

_SUFFIX_RE = re.compile(
    r"\b(s\.?a\.?e\.?c\.?a\.?|s\.?a\.?|s\.?r\.?l\.?|sociedad an[oó]nima|"
    r"ltda\.?|limitada|instituci[oó]n financiera externa|\bi\.?f\.?e\.?\b|"
    r"instituci[oó]n de intermediaci[oó]n financiera|"
    r"administradora de fondos de ahorro previsional|\ba\.?f\.?a\.?p\.?\b)\b",
    re.I,
)


def normalize_entity(name):
    """Nombre canónico consistente para agrupar la misma entidad entre resoluciones."""
    raw = (name or "").strip()
    if not raw:
        return ""
    key = _strip_accents(raw.lower())
    for pat, canon in _CANON:
        if re.search(pat, key):
            return canon
    cleaned = _SUFFIX_RE.sub("", raw)
    cleaned = re.sub(r"\s+[.,]\s+", " ", cleaned)   # puntos huérfanos de sufijos
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    cleaned = cleaned.strip(" ,;.-–—")
    return (cleaned or raw)[:50]


# ---------------------------------------------------------------------------
# Tipo de entidad
# ---------------------------------------------------------------------------
def entity_type(title, entity=""):
    b = _strip_accents((title + " " + (entity or "")).lower())
    if re.search(r"\bafap\b|fondos de ahorro previsional", b):
        return "afap"
    if re.search(r"banco de seguros|\bbse\b|aseguradora|de seguros\b|reaseguro|compan[ií]a de seguros", b):
        return "aseguradora"
    if re.search(r"\bbanco\b|\bbanca\b", b):
        return "banco"
    if re.search(r"casa de cambio|\bcambio\b", b):
        return "casa_cambio"
    if re.search(r"cooperativa", b):
        return "cooperativa"
    if re.search(r"corredor de bolsa|corredor de valores|\bcorredor\b", b):
        return "corredor_bolsa"
    if re.search(r"asesor(?:es)? de inversi[oó]n", b):
        return "asesor_inversion"
    if re.search(r"administradora de fondos|fondo de inversi[oó]n|\bfondo\b", b):
        return "fondo"
    if re.search(r"emisor|emisi[oó]n de valores|oferta p[uú]blica|fideicomiso", b):
        return "emisor_valores"
    if re.search(r"dinero electr[oó]nico|medios? de pago|emisora de dinero", b):
        return "fintech_pago"
    if re.search(r"casa financiera|instituci[oó]n financiera externa|\bife\b", b):
        return "casa_financiera"
    return "otro"


# ---------------------------------------------------------------------------
# Porcentaje accionario
# ---------------------------------------------------------------------------
_PCT_RE = re.compile(r"(\d{1,3}(?:[.,]\d{1,2})?)\s*%")


def extract_percentage(text, title=""):
    for src in (title or "", text or ""):
        m = _PCT_RE.search(src)
        if m:
            try:
                v = float(m.group(1).replace(",", "."))
                if 0 < v <= 100:
                    return v
            except ValueError:
                pass
    return None


# ---------------------------------------------------------------------------
# Contraparte (para operaciones de M&A)
# ---------------------------------------------------------------------------
_CP_PATTERNS = [
    r"a favor de\s+(.+)$",
    r"en favor de\s+(.+)$",
    r"por absorci[oó]n de\s+(.+)$",
    r"fusi[oó]n (?:por absorci[oó]n )?(?:de|con)\s+(.+)$",
    r"transferencia de acciones? a\s+(.+)$",
    r"cesi[oó]n de acciones? a\s+(.+)$",
    r"adquisici[oó]n (?:por|de)\s+(.+)$",
]


def extract_counterparty(title):
    t = title.strip()
    for pat in _CP_PATTERNS:
        m = re.search(pat, t, re.I)
        if m:
            cp = re.split(r"\s[-–]\s", m.group(1).strip())[0]
            cp = cp.strip(" .,-–—")
            if 2 < len(cp) < 80:
                return cp
    return None


# ---------------------------------------------------------------------------
# Montos
# ---------------------------------------------------------------------------
_AMOUNT_RE = re.compile(
    r"(\d[\d\.\,]{2,})\s*(UI|unidades\s+indexadas|U\$S|USD|d[oó]lares|UR|pesos|\$)",
    re.I,
)


def _norm_money(u):
    u = _strip_accents(u.upper())
    if "UI" in u or "INDEXAD" in u:
        return "UI"
    if re.fullmatch(r"UR", u):
        return "UR"
    if "USD" in u or "U$S" in u or "DOLAR" in u:
        return "USD"
    if "PESO" in u or u == "$" or "UYU" in u:
        return "UYU"
    return None


def _to_float(num):
    n = num.strip().replace(".", "").replace(",", ".")
    try:
        return float(n)
    except ValueError:
        return None


def parse_main_amount(text, title=""):
    """Devuelve (valor, moneda) del monto más grande hallado, o (None, None)."""
    found = []
    for src in (text or "", title or ""):
        for m in _AMOUNT_RE.finditer(src):
            val = _to_float(m.group(1))
            unit = _norm_money(m.group(2))
            if val is not None and unit:
                found.append((val, unit))
    if not found:
        return None, None
    return max(found, key=lambda x: x[0])


def extract_amounts(text):
    """(Compat) lista de montos como strings, deduplicada."""
    out, seen = [], set()
    for m in _AMOUNT_RE.finditer(text or ""):
        unit = _norm_money(m.group(2)) or m.group(2).upper()
        a = f"{m.group(1)} {unit}"
        if a not in seen:
            seen.add(a)
            out.append(a)
    return out[:4]


def catalog_overview(catalog):
    by_year, by_cat = {}, {}
    for it in catalog:
        by_year[it["year"]] = by_year.get(it["year"], 0) + 1
        cat = classify(it["title"])
        by_cat[cat] = by_cat.get(cat, 0) + 1
    return by_year, by_cat
