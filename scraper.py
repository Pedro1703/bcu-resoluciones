"""
Scraper de las Resoluciones de la Superintendencia de Servicios Financieros (SSF)
del Banco Central del Uruguay (BCU).

La página (Resoluciones_SSF.aspx) es SharePoint + ASP.NET: la tabla de documentos
se carga con un postback asíncrono (UpdatePanel + Timer). Replicamos ese postback
para obtener el índice completo de resoluciones, cada una con su PDF.

Sólo stdlib para el scraping (urllib). La extracción de texto de PDF usa pypdf.
"""

import re
import ssl
import html
import urllib.request
import urllib.parse
import http.cookiejar

BASE = "https://www.bcu.gub.uy/Servicios-Financieros-SSF"
URL = BASE + "/Paginas/Resoluciones_SSF.aspx"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120 Safari/537.36")

# El servidor del BCU no envía la cadena completa de certificados (le falta el
# intermedio). macOS la completa solo (AIA chasing); OpenSSL en Linux —como el
# runner de GitHub— no, y tira "unable to get local issuer certificate". Como
# sólo leemos información pública, usamos un contexto que no verifica el cert.
SSL_CTX = ssl._create_unverified_context()

# Controles del web part de la lista de SharePoint (GUID en el id).
_PREFIX = "ctl00$ctl66$g_caf7dd5a_176d_4cc4_9b6c_fb039d41a14e$ctl00$"
_TIMER = _PREFIX + "TimerLoadDocs"
_PANEL = _PREFIX + "UpdPanelDocs"

_MONTHS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "setiembre": 9, "septiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}


def _hidden(page, name):
    m = re.search(r'id="' + re.escape(name) + r'"[^>]*value="([^"]*)"', page)
    if not m:
        m = re.search(r'name="' + re.escape(name) + r'"[^>]*value="([^"]*)"', page)
    return m.group(1) if m else ""


def _clean(text):
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def fetch_index(timeout=90):
    """Devuelve la lista completa de resoluciones (índice), de más nueva a más vieja.

    Cada item: {id, year, month, month_num, number, title, url, sort}
    """
    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(cj),
        urllib.request.HTTPSHandler(context=SSL_CTX),
    )

    page = op.open(
        urllib.request.Request(URL, headers={"User-Agent": UA}), timeout=timeout
    ).read().decode("utf-8", "ignore")

    fields = {
        "ctl00$ScriptManager": _PANEL + "|" + _TIMER,
        "__EVENTTARGET": _TIMER,
        "__EVENTARGUMENT": "",
        "__VIEWSTATE": _hidden(page, "__VIEWSTATE"),
        "__VIEWSTATEGENERATOR": _hidden(page, "__VIEWSTATEGENERATOR"),
        "__EVENTVALIDATION": _hidden(page, "__EVENTVALIDATION"),
        "__REQUESTDIGEST": _hidden(page, "__REQUESTDIGEST"),
        "__ASYNCPOST": "true",
    }
    data = urllib.parse.urlencode(fields).encode()
    resp = op.open(
        urllib.request.Request(URL, data=data, headers={
            "User-Agent": UA,
            "X-MicrosoftAjax": "Delta=true",
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
            "Referer": URL,
        }), timeout=timeout
    ).read().decode("utf-8", "ignore")

    items = []
    for tr in re.findall(r"<tr[^>]*data-href=\"([^\"]+)\"[^>]*>(.*?)</tr>", resp, re.S):
        url, inner = tr
        cells = [_clean(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", inner, re.S)]
        # Estructura: [icono, año, mes, número, título]
        if len(cells) < 5:
            continue
        year = cells[1].strip()
        month = cells[2].strip()
        number = cells[3].strip()
        title = cells[4].strip()
        rid = re.sub(r"\.pdf$", "", url.rsplit("/", 1)[-1], flags=re.I)
        try:
            y = int(re.sub(r"\D", "", year) or 0)
            n = int(re.sub(r"\D", "", number) or 0)
        except ValueError:
            y, n = 0, 0
        items.append({
            "id": rid,
            "year": year,
            "month": month,
            "month_num": _MONTHS.get(month.lower(), 0),
            "number": number,
            "title": title,
            "url": url if url.startswith("http") else "https://www.bcu.gub.uy" + url,
            "sort": y * 100000 + n,  # ordena cronológicamente (nº correlativo por año)
        })

    items.sort(key=lambda x: x["sort"], reverse=True)
    return items


def fetch_pdf_text(url, timeout=60, max_chars=20000):
    """Descarga un PDF y devuelve su texto. '' si no se puede extraer (p. ej. escaneado)."""
    try:
        raw = urllib.request.urlopen(
            urllib.request.Request(url, headers={"User-Agent": UA}),
            timeout=timeout, context=SSL_CTX,
        ).read()
    except Exception:
        return ""
    try:
        import io
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(raw))
        parts = []
        for pg in reader.pages:
            parts.append(pg.extract_text() or "")
            if sum(len(p) for p in parts) > max_chars:
                break
        text = re.sub(r"\n{3,}", "\n\n", "\n".join(parts)).strip()
        return text[:max_chars]
    except Exception:
        return ""


if __name__ == "__main__":
    idx = fetch_index()
    print(f"{len(idx)} resoluciones")
    for it in idx[:5]:
        print(f"  {it['id']} | {it['month']} {it['year']} | {it['title'][:70]}")
