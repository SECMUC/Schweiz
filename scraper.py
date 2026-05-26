#!/usr/bin/env python3
"""
Polizei-Monitor Schweiz – scraper.py
Scrapet RSS-Feeds + ruft jeden Artikel auf um den Volltext zu holen.
Läuft täglich via GitHub Actions → schreibt incidents.json ins Root
"""

import json
import re
import hashlib
import datetime
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError
import time

OUTPUT_FILE  = Path("incidents.json")
SUMMARY_FILE = Path("summary.md")

FEEDS = [
    {"url": "https://www.polizeinews.ch/feed/",                                  "label": "Schweiz (alle Kantone)"},
    {"url": "https://www.polizeinews.ch/region-zuerich/feed/",                   "label": "Zürich"},
    {"url": "https://www.polizeinews.ch/espace-mittelland/bern/feed/",           "label": "Bern"},
    {"url": "https://www.polizeinews.ch/nordwestschweiz/basel-stadt/feed/",      "label": "Basel-Stadt"},
    {"url": "https://www.polizeinews.ch/nordwestschweiz/basel-landschaft/feed/", "label": "Basel-Landschaft"},
    {"url": "https://www.polizeinews.ch/zentralschweiz/luzern/feed/",            "label": "Luzern"},
    {"url": "https://www.polizeinews.ch/ostschweiz/st-gallen/feed/",             "label": "St. Gallen"},
    {"url": "https://www.polizeinews.ch/ticino/tessin/feed/",                    "label": "Tessin"},
    {"url": "https://www.polizeinews.ch/nordwestschweiz/aargau/feed/",           "label": "Aargau"},
    {"url": "https://www.polizeinews.ch/espace-mittelland/solothurn/feed/",      "label": "Solothurn"},
    {"url": "https://www.kapo.zh.ch/internet/sicherheitsdirektion/kapo/de/aktuell/medienmitteilungen.rss.xml",
     "label": "Kantonspolizei Zürich"},
]

CATEGORIES = {
    "Unfall":      r"unfall|kollision|auffahrt|sturz|überschlag|crash|prallt|zusammenstoss",
    "Einbruch":    r"einbruch|einbrecher|diebstahl|beraubt|raub|überfall",
    "Vermisst":    r"vermisst|abgängig|gesucht|fahndung",
    "Drogen":      r"drogen|betäubungsmittel|kokain|heroin|cannabis|dealer",
    "Betrug":      r"betrug|phishing|cyber|fakeshop|identitätsmissbrauch",
    "Brand":       r"brand|feuer|brandstiftung|verpuffung",
    "Gewalt":      r"gewalt|körperverletzung|schuss|messer|angriff|schlägerei",
    "Verkehr":     r"verkehr|tempoüberschreitung|autobahn|raserei|a\d+|geschwindigkeit",
    "Todesfälle":  r"tot|tödlich|leiche|gestorben|opfer|verstorben",
    "Verhaftung":  r"verhaftet|festgenommen|in haft|verurteilt|angehalten",
}

# Vollständige Kantonnamen für Anzeige
KANTON_NAMEN = {
    "ZH": "Zürich",        "BE": "Bern",           "VD": "Waadt",
    "GE": "Genf",          "AG": "Aargau",         "SO": "Solothurn",
    "BS": "Basel-Stadt",   "BL": "Basel-Landschaft","LU": "Luzern",
    "SG": "St. Gallen",    "TI": "Tessin",         "GR": "Graubünden",
    "VS": "Wallis",        "SZ": "Schwyz",         "ZG": "Zug",
    "TG": "Thurgau",       "SH": "Schaffhausen",   "FR": "Freiburg",
    "NE": "Neuenburg",     "JU": "Jura",           "GL": "Glarus",
    "NW": "Nidwalden",     "OW": "Obwalden",       "UR": "Uri",
    "AR": "Appenzell AR",  "AI": "Appenzell AI",   "CH": "Schweiz",
    "FL": "Liechtenstein",
}

KANTONE_PATTERN = {
    "ZH": r"\bZürich\b|\bZH\b|\bWinterthur\b|\bKapo ZH\b",
    "BE": r"\bBern\b|\bBE\b|\bThun\b|\bBiel\b",
    "VD": r"\bWaadt\b|\bVD\b|\bLausanne\b",
    "GE": r"\bGenf\b|\bGE\b|\bGenève\b",
    "AG": r"\bAargau\b|\bAG\b|\bAarau\b|\bBaden\b",
    "SO": r"\bSolothurn\b|\bSO\b",
    "BS": r"\bBasel-Stadt\b|\bBS\b",
    "BL": r"\bBasel-Landschaft\b|\bBL\b|\bLiestal\b",
    "LU": r"\bLuzern\b|\bLU\b",
    "SG": r"\bSt\.?Gallen\b|\bSG\b",
    "TI": r"\bTessin\b|\bTI\b|\bBellinzona\b|\bLugano\b",
    "GR": r"\bGraubünden\b|\bGR\b|\bChur\b",
    "VS": r"\bWallis\b|\bVS\b|\bSitten\b|\bValais\b",
    "SZ": r"\bSchwyz\b|\bSZ\b",
    "ZG": r"\bZug\b|\bZG\b",
    "TG": r"\bThurgau\b|\bTG\b",
    "SH": r"\bSchaffhausen\b|\bSH\b",
    "FR": r"\bFreiburg\b|\bFR\b|\bFribourg\b",
    "NE": r"\bNeuenburg\b|\bNE\b|\bNeuchâtel\b",
    "JU": r"\bJura\b|\bJU\b",
    "GL": r"\bGlarus\b|\bGL\b",
    "NW": r"\bNidwalden\b|\bNW\b",
    "OW": r"\bObwalden\b|\bOW\b",
    "UR": r"\bUri\b|\bUR\b|\bAltdorf\b",
    "AR": r"\bAppenzell Ausserrhoden\b|\bAR\b",
    "AI": r"\bAppenzell Innerrhoden\b|\bAI\b",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; PolizeiMonitorCH/1.0)",
    "Accept": "application/rss+xml, application/xml, text/html, */*",
}


def clean_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    return re.sub(r"\s+", " ", text).strip()


def extract_location(title: str, text: str = "") -> str:
    """Extrahiert Ort/Stadtteil aus Titel und Text."""
    combined = f"{title} {text}"

    # Muster 1: "Ort KT:" — z.B. "Wil SG:", "Emmenbrücke LU:"
    m = re.match(
        r'^((?:St\.\s?|Bad\s|La\s|Le\s)?[A-Z\xc0-\xdc][a-z\xe0-\xfc\xc0-\xdcA-Z\.\xe4\xf6\xfc\xc4\xd6\xdc]+'
        r'(?:[\-\s][A-Z\xc0-\xdc][a-z\xe0-\xfc\xc0-\xdcA-Z\.\xe4\xf6\xfc\xc4\xd6\xdc]+)?'
        r'(?:\s(?:bei|am|im|an)\s[A-Z\xc0-\xdc][a-z\xe0-\xfca-z\xe4\xf6\xfc]+)?)'
        r'\s+[A-Z]{2}:', title)
    if m:
        return m.group(1).strip()

    # Muster 2: "Ort:" / "Ort-Stadtteil:"
    m = re.match(
        r'^((?:St\.\s?|Bad\s|La\s|Le\s)?[A-Z\xc0-\xdc][a-z\xe0-\xfcA-Z\.\xe4\xf6\xfc\xc4\xd6\xdc]+'
        r'(?:[\-\s][A-Z\xc0-\xdc][a-z\xe0-\xfcA-Z\.\xe4\xf6\xfc\xc4\xd6\xdc]+)*'
        r'(?:\s(?:bei|am|an)\s[A-Z\xc0-\xdc][a-z\xe0-\xfc\xe4\xf6\xfc]+)?):', title)
    if m:
        loc = m.group(1).strip()
        if not re.match(r'^[A-Z]{2}$', loc) and len(loc) > 2:
            return loc

    # Muster 3: "in Ort" / "bei Ort" im Text
    SKIP = {"der","einem","einer","dem","den","Nacht","Tag","Rahmen","Folge","einem"}
    for pat in [
        r'\bin\s+((?:St\.\s?|Bad\s)?[A-Z\xc0-\xdc\xc4\xd6][a-z\xe0-\xfc\xe4\xf6\xfc]+(?:-[A-Z\xc0-\xdc][a-z\xe0-\xfc\xe4\xf6\xfc]+)?)\b',
        r'\bbei\s+((?:St\.\s?|Bad\s)?[A-Z\xc0-\xdc\xc4\xd6][a-z\xe0-\xfc\xe4\xf6\xfc]{3,})\b',
    ]:
        for hit in re.finditer(pat, combined):
            cand = hit.group(1).strip()
            if cand not in SKIP:
                return cand

    return ""


def detect_categories(text: str) -> list:
    t = text.lower()
    found = [cat for cat, pat in CATEGORIES.items() if re.search(pat, t)]
    return found or ["Sonstiges"]


def detect_kanton(text: str) -> str:
    for kuerzel, pat in KANTONE_PATTERN.items():
        if re.search(pat, text, re.IGNORECASE):
            return kuerzel
    return "CH"


def make_id(url: str, title: str) -> str:
    return hashlib.md5(f"{url}{title}".encode()).hexdigest()[:12]


def parse_date(date_str: str) -> str:
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.datetime.strptime((date_str or "").strip(), fmt).isoformat()
        except ValueError:
            continue
    return datetime.datetime.now().isoformat()


def fetch_url(url: str, accept_html: bool = False) -> str | None:
    try:
        headers = dict(HEADERS)
        if accept_html:
            headers["Accept"] = "text/html,application/xhtml+xml,*/*"
        req = Request(url, headers=headers)
        with urlopen(req, timeout=15) as r:
            return r.read().decode("utf-8", errors="replace")
    except URLError as e:
        print(f"  ⚠️  {url}: {e}")
        return None


def fetch_fulltext(url: str) -> str:
    """Ruft die Artikelseite auf und extrahiert den Volltext absatzweise."""
    if not url:
        return ""
    html = fetch_url(url, accept_html=True)
    if not html:
        return ""

    # Störende Blöcke entfernen
    for tag in ["script", "style", "nav", "footer", "header", "aside",
                "form", "figure", "figcaption", "noscript"]:
        html = re.sub(rf'<{tag}[^>]*>.*?</{tag}>', '', html, flags=re.DOTALL | re.IGNORECASE)

    # entry-content Block (WordPress Standard)
    block = ""
    m = re.search(
        r'class="[^"]*entry-content[^"]*"[^>]*>(.*?)(?=<div[^>]*class="[^"]*(?:sharedaddy|post-footer|related|comments)[^"]*"|</article>)',
        html, re.DOTALL | re.IGNORECASE)
    if m:
        block = m.group(1)
    else:
        m2 = re.search(r'<article[^>]*>(.*?)</article>', html, re.DOTALL | re.IGNORECASE)
        if m2:
            block = m2.group(1)

    if not block:
        return ""

    # Alle <p>-Absätze extrahieren
    paragraphs = re.findall(r'<p[^>]*>(.*?)</p>', block, re.DOTALL | re.IGNORECASE)
    texts = []
    for p in paragraphs:
        t = clean_html(p)
        if len(t) > 30 and not re.search(r'^\d{2}\.\d{2}\.\d{2}|Redaktion|Cookie|Datenschutz|Abonnieren', t):
            texts.append(t)

    result = "\n\n".join(texts)
    if len(result) > 80:
        return result

    return clean_html(block)[:3000]


def parse_feed(xml_text: str, label: str) -> list:
    incidents = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        print(f"  ⚠️  XML-Fehler ({label}): {e}")
        return incidents

    ns = {"content": "http://purl.org/rss/1.0/modules/content/"}
    for item in root.findall(".//item"):
        title   = (item.findtext("title") or "").strip()
        link    = (item.findtext("link")  or "").strip()
        pubdate = item.findtext("pubDate") or ""
        desc    = item.findtext("description") or ""
        full    = item.findtext("content:encoded", "", ns)
        text    = clean_html(full or desc)
        combined = f"{title} {text}"
        tags    = [c.text for c in item.findall("category") if c.text]
        kanton_kuerzel = detect_kanton(combined)

        incidents.append({
            "id":           make_id(link, title),
            "title":        title,
            "url":          link,
            "date":         parse_date(pubdate),
            "summary":      text,
            "fulltext":     "",
            "categories":   detect_categories(combined),
            "kanton":       kanton_kuerzel,
            "kanton_name":  KANTON_NAMEN.get(kanton_kuerzel, kanton_kuerzel),
            "location":     extract_location(title, text),
            "tags":         tags,
            "source":       label,
            "scraped_at":   datetime.datetime.now().isoformat(),
        })
    return incidents


def enrich_with_fulltext(incidents: list, existing_map: dict) -> list:
    """Holt Volltext für neue Einträge (die noch keinen haben)."""
    to_fetch = [i for i in incidents if not existing_map.get(i["id"], {}).get("fulltext")]
    print(f"   Volltext-Fetch für {len(to_fetch)} neue Artikel…")
    for i, inc in enumerate(to_fetch):
        if not inc["url"]:
            continue
        fulltext = fetch_fulltext(inc["url"])
        if fulltext:
            inc["fulltext"] = fulltext
            # Location mit Volltext nachschärfen falls noch leer
            if not inc.get("location"):
                inc["location"] = extract_location(inc["title"], fulltext)
        else:
            inc["fulltext"] = inc["summary"]
        if i > 0 and i % 5 == 0:
            time.sleep(1)  # kurze Pause, Server schonen
    return incidents


def load_existing() -> list:
    if OUTPUT_FILE.exists():
        try:
            return json.loads(OUTPUT_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def merge(existing: list, fresh: list) -> list:
    index = {i["id"]: i for i in existing}
    for inc in fresh:
        # Behalte bestehenden Volltext wenn vorhanden
        if inc["id"] in index and index[inc["id"]].get("fulltext"):
            inc["fulltext"] = index[inc["id"]]["fulltext"]
        index[inc["id"]] = inc
    result = sorted(index.values(), key=lambda x: x["date"], reverse=True)
    return result[:5000]


def main():
    print("=" * 55)
    print(f"Polizei-Monitor Schweiz – {datetime.datetime.now().isoformat()}")
    print("=" * 55)

    existing      = load_existing()
    existing_map  = {i["id"]: i for i in existing}
    print(f"Bestehende Einträge: {len(existing)}")

    fresh = []
    seen  = set()
    for feed in FEEDS:
        print(f"→ {feed['label']}")
        xml = fetch_url(feed["url"])
        if not xml:
            continue
        items = parse_feed(xml, feed["label"])
        print(f"   {len(items)} Einträge im Feed")
        for inc in items:
            if inc["id"] not in seen:
                seen.add(inc["id"])
                fresh.append(inc)

    # Volltext für neue Artikel holen
    fresh = enrich_with_fulltext(fresh, existing_map)

    merged = merge(existing, fresh)
    print(f"\nNeu (dedupliziert): {len(fresh)}")
    print(f"Gesamt nach Merge:  {len(merged)}")

    OUTPUT_FILE.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"✅ incidents.json gespeichert ({OUTPUT_FILE.stat().st_size // 1024} KB)")

    # Kanton-Statistik
    kanton_counts: dict = {}
    for inc in fresh:
        k = inc.get("kanton_name", inc.get("kanton", "CH"))
        kanton_counts[k] = kanton_counts.get(k, 0) + 1

    lines = [
        "## 🇨🇭 Polizei-Monitor Schweiz",
        f"**Datum:** {datetime.date.today()}  ",
        f"**Neue Einträge:** {len(fresh)}  ",
        f"**Gesamt im Archiv:** {len(merged)}",
        "", "### Kantone (heutiger Lauf)",
    ] + [f"- **{k}**: {c}" for k, c in sorted(kanton_counts.items(), key=lambda x: -x[1])]

    SUMMARY_FILE.write_text("\n".join(lines), encoding="utf-8")
    print("📄 summary.md gespeichert")


if __name__ == "__main__":
    main()
