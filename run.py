#!/usr/bin/env python3
"""
Orquestador: scrapea las Resoluciones de la SSF del BCU, guarda el dataset y el
texto de los PDFs nuevos, los analiza (heurística + Claude opcional) y entrega un
reporte diario con los insights más relevantes (issue rotativo de GitHub + email).
"""

import os
import sys
import json
import smtplib
import html as htmllib
import datetime as dt
import urllib.request
from email.message import EmailMessage

import scraper
import analysis

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
TEXT_DIR = os.path.join(DATA, "text")
REPORTS = os.path.join(HERE, "reports")
STATE_FILE = os.path.join(DATA, "state.json")
CATALOG_FILE = os.path.join(DATA, "resoluciones.json")

BASELINE_ANALYZE = int(os.environ.get("BASELINE_ANALYZE", "12"))
MAX_ANALYZE = int(os.environ.get("MAX_ANALYZE", "30"))
TODAY = dt.datetime.utcnow().date().isoformat()


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def main():
    state = load_json(STATE_FILE, {})
    seen = set(state.get("seen", []))
    first_run = not seen

    print("Scrapeando índice de resoluciones del BCU...")
    catalog = scraper.fetch_index()
    print(f"  {len(catalog)} resoluciones en el catálogo.")
    save_json(CATALOG_FILE, catalog)

    new_items = [it for it in catalog if it["id"] not in seen]
    print(f"  {len(new_items)} nuevas desde la última corrida.")

    # ¿Cuáles analizamos a fondo (bajar PDF + texto)?
    if first_run:
        to_analyze = new_items[:BASELINE_ANALYZE]
    else:
        to_analyze = new_items[:MAX_ANALYZE]

    os.makedirs(TEXT_DIR, exist_ok=True)
    enriched_input = []
    for it in to_analyze:
        print(f"  Descargando PDF {it['id']}...")
        text = scraper.fetch_pdf_text(it["url"])
        if text:
            with open(os.path.join(TEXT_DIR, it["id"] + ".txt"), "w", encoding="utf-8") as f:
                f.write(text)
        enriched_input.append({**it, "text": text})

    enriched = analysis.enrich(enriched_input)
    briefing = analysis.llm_briefing(enriched) if enriched else ""

    # Marcar TODO lo nuevo como visto (aunque no se haya analizado a fondo).
    for it in new_items:
        seen.add(it["id"])
    state["seen"] = sorted(seen)

    total_new = len(new_items)
    md = render_markdown(catalog, new_items, enriched, briefing, first_run, total_new)
    html_email = render_html(catalog, new_items, enriched, briefing, first_run, total_new)

    os.makedirs(REPORTS, exist_ok=True)
    with open(os.path.join(REPORTS, f"{TODAY}.md"), "w", encoding="utf-8") as f:
        f.write(md)
    print("\n" + md[:2000])

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(md)

    notify_github(total_new, md, state)
    send_email(total_new, html_email, md)

    save_json(STATE_FILE, state)


# --------------------------------------------------------------------------- #
# Render
# --------------------------------------------------------------------------- #

def _breakdown(enriched):
    counts = {}
    for it in enriched:
        counts[it["category"]] = counts.get(it["category"], 0) + 1
    return counts


def render_markdown(catalog, new_items, enriched, briefing, first_run, total_new):
    date = TODAY
    if total_new == 0:
        return (f"## ✅ BCU · Resoluciones SSF — {date}\n\n"
                "Sin resoluciones nuevas desde el último reporte. "
                f"Catálogo total: {len(catalog)}.\n")

    counts = _breakdown(enriched)
    brk = " · ".join(f"{k.split(' ',1)[1] if ' ' in k else k}: {v}"
                     for k, v in sorted(counts.items(), key=lambda x: -x[1]))

    out = [f"## 🏦 BCU · Resoluciones SSF — {date}", ""]
    if first_run:
        out.append(f"**Primer reporte (baseline).** Catálogo cargado: "
                   f"**{len(catalog)} resoluciones**. Analizo a fondo las "
                   f"{len(enriched)} más recientes; de acá en más recibís sólo las nuevas.")
    else:
        out.append(f"**{total_new} resolución(es) nueva(s)** · {brk}")
    out.append("")

    if briefing:
        out += ["### 📰 Briefing (analista financiero / periodista)", "", briefing, ""]

    out.append("### 🔎 Lo más relevante")
    out.append("")
    for it in enriched:
        amt = f" · 💰 {', '.join(it['amounts'])}" if it["amounts"] else ""
        out.append(f"**{it['category']} — {it['entity']}**")
        out.append(f"- `{it['id']}` ({it['month']} {it['year']}){amt}")
        out.append(f"- {it['title']}")
        out.append(f"- [PDF]({it['url']})")
        out.append("")

    if first_run:
        by_year, by_cat = analysis.catalog_overview(catalog)
        out.append("### 📊 Panorama del catálogo")
        ys = " · ".join(f"{y}: {n}" for y, n in sorted(by_year.items(), reverse=True)[:6])
        cs = " · ".join(f"{k.split(' ',1)[1] if ' ' in k else k}: {v}"
                        for k, v in sorted(by_cat.items(), key=lambda x: -x[1]))
        out.append(f"- **Por año:** {ys}")
        out.append(f"- **Por tipo (según título):** {cs}")
        out.append("")
    elif total_new > len(enriched):
        out.append(f"_…y {total_new - len(enriched)} resolución(es) nueva(s) más "
                   "(ver dataset `data/resoluciones.json`)._")

    return "\n".join(out)


def _esc(s):
    return htmllib.escape(s or "")


def render_html(catalog, new_items, enriched, briefing, first_run, total_new):
    date = TODAY
    head = (
        '<div style="background:#0a3470;color:#fff;padding:22px 26px;'
        'border-radius:12px 12px 0 0;">'
        '<div style="font-size:21px;font-weight:700;">🏦 BCU · Resoluciones SSF</div>'
        '<div style="margin-top:5px;font-size:13px;color:#b9c7e0;">'
        + _esc(date) + ' &middot; '
        + ('sin novedades' if total_new == 0 else f'{total_new} nueva(s)') + '</div></div>'
    )

    if total_new == 0:
        body = (
            '<div style="background:#fff;border:1px solid #e2e8f0;border-top:none;'
            'border-radius:0 0 12px 12px;padding:44px 26px;text-align:center;">'
            '<div style="font-size:36px;">✅</div>'
            '<div style="font-size:17px;font-weight:700;color:#0a3470;margin-top:10px;">'
            'Sin resoluciones nuevas</div>'
            '<div style="font-size:13px;color:#64748b;margin-top:6px;">'
            f'Catálogo total: {len(catalog)} resoluciones.</div></div>'
        )
        return _wrap(head + body)

    sections = []
    if briefing:
        brief_html = _esc(briefing).replace("\n", "<br>")
        sections.append(
            '<div style="padding:18px 26px;border-top:1px solid #f1f5f9;">'
            '<div style="font-size:13px;font-weight:700;text-transform:uppercase;'
            'letter-spacing:.05em;color:#0a3470;margin-bottom:8px;">📰 Briefing</div>'
            '<div style="font-size:14px;line-height:1.55;color:#1f2937;">'
            + brief_html + '</div></div>'
        )

    cards = []
    for it in enriched:
        amt = ('<span style="background:#fef3c7;color:#92400e;font-size:11px;'
               'font-weight:700;padding:2px 8px;border-radius:5px;margin-left:6px;">💰 '
               + _esc(", ".join(it["amounts"])) + '</span>') if it["amounts"] else ""
        cards.append(
            '<div style="padding:16px 26px;border-top:1px solid #f1f5f9;">'
            '<div style="font-size:12px;font-weight:700;color:#0a3470;">'
            + _esc(it["category"]) + '</div>'
            '<div style="font-size:15px;font-weight:700;color:#0f172a;margin-top:3px;">'
            + _esc(it["entity"]) + amt + '</div>'
            '<div style="font-size:13px;color:#334155;line-height:1.45;margin-top:5px;">'
            + _esc(it["title"]) + '</div>'
            '<div style="font-size:12px;color:#94a3b8;margin-top:6px;">'
            + _esc(f"{it['id']} · {it['month']} {it['year']}") + ' &middot; '
            '<a href="' + _esc(it["url"]) + '" style="color:#2563eb;">PDF</a></div></div>'
        )
    sections.append("".join(cards))

    body = (
        '<div style="background:#fff;border:1px solid #e2e8f0;border-top:none;'
        'border-radius:0 0 12px 12px;overflow:hidden;">' + "".join(sections) + '</div>'
    )
    return _wrap(head + body)


def _wrap(inner):
    footer = (
        '<div style="text-align:center;color:#94a3b8;font-size:12px;margin-top:16px;">'
        'Fuente: Superintendencia de Servicios Financieros · Banco Central del Uruguay'
        '</div>'
    )
    return (
        '<div style="margin:0;padding:24px;background:#eef2f7;">'
        '<div style="max-width:700px;margin:0 auto;'
        'font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial,sans-serif;">'
        + inner + footer + '</div></div>'
    )


# --------------------------------------------------------------------------- #
# Notificaciones (issue rotativo de GitHub + email opcional)
# --------------------------------------------------------------------------- #

def _gh_api(method, path, payload=None):
    token = os.environ["GITHUB_TOKEN"]
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        f"https://api.github.com{path}", data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "bcu-resoluciones",
            "Content-Type": "application/json",
        }, method=method,
    )
    resp = urllib.request.urlopen(req, timeout=30)
    raw = resp.read()
    return resp.status, (json.loads(raw) if raw else {})


def notify_github(total, md_body, state):
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    owner = os.environ.get("GITHUB_REPOSITORY_OWNER")
    if not (token and repo):
        return
    meta = state.setdefault("_meta", {})
    issue = meta.get("issue_number")
    if issue:
        try:
            st, _ = _gh_api("POST", f"/repos/{repo}/issues/{issue}/comments",
                            {"body": md_body})
            if st in (200, 201):
                print(f"Comenté en el issue rotativo #{issue}.")
                return
        except Exception as e:
            print(f"[issue] comentario falló, recreo: {e}", file=sys.stderr)
    payload = {"title": "🏦 BCU · Resoluciones SSF — reporte diario", "body": md_body}
    if owner:
        payload["assignees"] = [owner]
    try:
        st, data = _gh_api("POST", f"/repos/{repo}/issues", payload)
        if st in (200, 201):
            meta["issue_number"] = data.get("number")
            print(f"Abrí el issue rotativo #{data.get('number')}.")
    except Exception as e:
        print(f"[issue] no se pudo abrir el issue: {e}", file=sys.stderr)


def send_email(total, html_body, text_body):
    host = os.environ.get("SMTP_HOST")
    to = os.environ.get("EMAIL_TO")
    if not (host and to):
        return
    subject = (f"🏦 BCU Resoluciones SSF — {TODAY} — "
               + (f"{total} nueva(s)" if total else "sin novedades"))
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = os.environ.get("SMTP_USER", to)
    msg["To"] = to
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")
    try:
        with smtplib.SMTP(host, int(os.environ.get("SMTP_PORT", "587")), timeout=30) as s:
            s.starttls()
            u, p = os.environ.get("SMTP_USER"), os.environ.get("SMTP_PASS")
            if u and p:
                s.login(u, p)
            s.send_message(msg)
        print("Email enviado.")
    except Exception as e:
        print(f"[email] no se pudo enviar: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
