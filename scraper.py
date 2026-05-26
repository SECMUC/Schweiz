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
    """Ruft die Artikelseite auf und extrahiert den Haupttext."""
    if not url:
        return ""
    html = fetch_url(url, accept_html=True)
    if not html:
        return ""

    # Versuche den Artikelinhalt zu extrahieren (polizeinews.ch WordPress)
    # Zuerst: entry-content / article-content Block
    for pattern in [
        r'<div[^>]*class="[^"]*entry-content[^"]*"[^>]*>(.*?)</div>\s*(?:<div|</article)',
        r'<div[^>]*class="[^"]*post-content[^"]*"[^>]*>(.*?)</div>\s*(?:<div|</article)',
        r'<article[^>]*>(.*?)</article>',
    ]:
        m = re.search(pattern, html, re.DOTALL | re.IGNORECASE)
        if m:
            raw = m.group(1)
            # Entferne Bilder, Scripts, Links-Wrapper
            raw = re.sub(r'<figure[^>]*>.*?</figure>', '', raw, flags=re.DOTALL)
            raw = re.sub(r'<script[^>]*>.*?</script>', '', raw, flags=re.DOTALL)
            raw = re.sub(r'<style[^>]*>.*?</style>', '', raw, flags=re.DOTALL)
            text = clean_html(raw)
            if len(text) > 100:
                return text

    return ""


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
            "summary":      text,       # RSS-Text (wird später durch Volltext ersetzt)
            "fulltext":     "",         # wird separat gefetcht
            "categories":   detect_categories(combined),
            "kanton":       kanton_kuerzel,
            "kanton_name":  KANTON_NAMEN.get(kanton_kuerzel, kanton_kuerzel),
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
        else:
            inc["fulltext"] = inc["summary"]  # Fallback auf RSS-Text
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
