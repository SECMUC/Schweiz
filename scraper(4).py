#!/usr/bin/env python3
"""
Polizei-Monitor Schweiz – scraper.py
Analoges Skript zum PP-München-Scraper.
Quellen: polizeinews.ch (RSS) + direkte Kantonspolizei-Feeds
Läuft täglich via GitHub Actions → schreibt incidents.json
"""

import json
import re
import hashlib
import datetime
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError

# ──────────────────────────────────────────────
# KONFIGURATION
# ──────────────────────────────────────────────

OUTPUT_FILE = Path("incidents.json")

# Primärquelle: polizeinews.ch RSS (WordPress, alle Kantone)
PRIMARY_FEEDS = [
    {"url": "https://www.polizeinews.ch/feed/",         "label": "Schweiz (alle Kantone)"},
    {"url": "https://www.polizeinews.ch/region-zuerich/feed/",       "label": "Zürich"},
    {"url": "https://www.polizeinews.ch/espace-mittelland/bern/feed/","label": "Bern"},
    {"url": "https://www.polizeinews.ch/nordwestschweiz/basel-stadt/feed/", "label": "Basel-Stadt"},
    {"url": "https://www.polizeinews.ch/zentralschweiz/luzern/feed/","label": "Luzern"},
]

# Fallback: Direkte Kantonspolizei RSS-Feeds (sofern vorhanden)
DIRECT_FEEDS = [
    {"url": "https://www.kapo.zh.ch/internet/sicherheitsdirektion/kapo/de/aktuell/medienmitteilungen.rss.xml",
     "label": "Kantonspolizei Zürich", "kanton": "ZH"},
    {"url": "https://www.police.be.ch/police/de/index/aktuell/medienmitteilungen.rss.xml",
     "label": "Kantonspolizei Bern", "kanton": "BE"},
    {"url": "https://www.llv.li/inhalt/1137/amtsstellen/medienmitteilungen",
     "label": "Landespolizei Liechtenstein", "kanton": "FL"},
]

# Kategorie-Erkennung (Tags aus Artikeln oder Titeln)
CATEGORIES = {
    "Unfall":        r"unfall|kollision|auffahrt|sturz|überschlag|crash",
    "Einbruch":      r"einbruch|einbrecher|diebstahl|beraubt|raub|überfall",
    "Vermisst":      r"vermisst|abgängig|gesucht|fahndung",
    "Drogen":        r"drogen|betäubungsmittel|kokain|heroin|cannabis|dealer",
    "Betrug":        r"betrug|phishing|cyber|fakeshop|identitätsmissbrauch",
    "Brand":         r"brand|feuer|brandstiftung|verpuffung",
    "Gewalt":        r"gewalt|körperverletzung|schuss|messer|angriff|schlägerei",
    "Verkehr":       r"verkehr|speed|tempoüberschreitung|autobahn|a\d+",
    "Todesfälle":    r"tot|tödlich|leiche|gestorben|opfer",
    "Verhaftung":    r"verhaftet|festgenommen|in haft|verurteilt",
}

# Kanton-Erkennung aus Text/Tags
KANTONE = {
    "ZH": r"\bZürich\b|\bZH\b|\bWinterthur\b|\bKapo ZH\b",
    "BE": r"\bBern\b|\bBE\b|\bThun\b|\bBiel\b",
    "VD": r"\bWaadt\b|\bVD\b|\bLausanne\b",
    "GE": r"\bGenf\b|\bGE\b|\bGenève\b",
    "AG": r"\bAargau\b|\bAG\b|\bAarau\b|\bBaden\b",
    "SO": r"\bSolothurn\b|\bSO\b",
    "BS": r"\bBasel-Stadt\b|\bBS\b|\bBasel\b",
    "BL": r"\bBasel-Landschaft\b|\bBL\b|\bLiestal\b",
    "LU": r"\bLuzern\b|\bLU\b",
    "SG": r"\bSt\.Gallen\b|\bSG\b|\bSt. Gallen\b",
    "TI": r"\bTessin\b|\bTI\b|\bBellinzona\b|\bLugano\b",
    "GR": r"\bGraubünden\b|\bGR\b|\bChur\b",
    "VS": r"\bWallis\b|\bVS\b|\bSitten\b|\bValais\b",
    "SZ": r"\bSchwyz\b|\bSZ\b",
    "ZG": r"\bZug\b|\bZG\b",
    "NW": r"\bNidwalden\b|\bNW\b",
    "OW": r"\bObwalden\b|\bOW\b",
    "UR": r"\bUri\b|\bUR\b|\bAltdorf\b",
    "GL": r"\bGlarus\b|\bGL\b",
    "SH": r"\bSchaffhausen\b|\bSH\b",
    "TG": r"\bThurgau\b|\bTG\b",
    "AR": r"\bAppenzell Ausserrhoden\b|\bAR\b",
    "AI": r"\bAppenzell Innerrhoden\b|\bAI\b",
    "JU": r"\bJura\b|\bJU\b",
    "NE": r"\bNeuenburg\b|\bNE\b|\bNeuchâtel\b",
    "FR": r"\bFreiburg\b|\bFR\b|\bFribourg\b",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; PolizeiMonitorCH/1.0; +https://github.com/BeerSeb)",
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}

# ──────────────────────────────────────────────
# HILFSFUNKTIONEN
# ──────────────────────────────────────────────

def clean_html(text: str) -> str:
    """Entfernt HTML-Tags und normalisiert Whitespace."""
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def detect_categories(text: str) -> list[str]:
    """Gibt alle zutreffenden Kategorien zurück."""
    text_lower = text.lower()
    return [
        cat for cat, pattern in CATEGORIES.items()
        if re.search(pattern, text_lower)
    ] or ["Sonstiges"]


def detect_kanton(text: str) -> str:
    """Versucht den Kanton anhand von Stichwörtern zu erkennen."""
    for kuerzel, pattern in KANTONE.items():
        if re.search(pattern, text, re.IGNORECASE):
            return kuerzel
    return "CH"  # Schweizweit / unbekannt


def make_id(url: str, title: str) -> str:
    """Erzeugt eine stabile ID aus URL + Titel."""
    return hashlib.md5(f"{url}{title}".encode()).hexdigest()[:12]


def parse_date(date_str: str) -> str:
    """Normalisiert RSS-Datumsformate auf ISO 8601."""
    if not date_str:
        return datetime.datetime.now().isoformat()
    for fmt in (
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%Y-%m-%dT%H:%M:%S%z",
    ):
        try:
            return datetime.datetime.strptime(date_str.strip(), fmt).isoformat()
        except ValueError:
            continue
    return date_str


def fetch_feed(url: str) -> str | None:
    """Lädt eine RSS-Feed-URL und gibt den XML-Text zurück."""
    try:
        req = Request(url, headers=HEADERS)
        with urlopen(req, timeout=15) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except URLError as e:
        print(f"  ⚠️  Fehler bei {url}: {e}")
        return None


def parse_rss(xml_text: str, feed_label: str) -> list[dict]:
    """Parst einen RSS-Feed und gibt normalisierte Incident-Objekte zurück."""
    incidents = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        print(f"  ⚠️  XML-Fehler ({feed_label}): {e}")
        return incidents

    ns = {"content": "http://purl.org/rss/1.0/modules/content/"}

    for item in root.findall(".//item"):
        title   = item.findtext("title", "").strip()
        link    = item.findtext("link", "").strip()
        pubdate = item.findtext("pubDate", "")
        desc    = item.findtext("description", "")
        # WordPress fügt oft den vollen Text als content:encoded hinzu
        full    = item.findtext("content:encoded", "", ns)

        full_text = clean_html(full or desc)
        combined  = f"{title} {full_text}"

        # Tags aus <category>-Elementen (WordPress)
        wp_tags = [c.text for c in item.findall("category") if c.text]

        categories = detect_categories(combined)
        kanton     = detect_kanton(combined)

        incidents.append({
            "id":         make_id(link, title),
            "title":      title,
            "url":        link,
            "date":       parse_date(pubdate),
            "summary":    full_text[:500],
            "categories": categories,
            "kanton":     kanton,
            "tags":       wp_tags,
            "source":     feed_label,
            "scraped_at": datetime.datetime.now().isoformat(),
        })

    return incidents


# ──────────────────────────────────────────────
# HAUPTLOGIK
# ──────────────────────────────────────────────

def scrape_all() -> list[dict]:
    all_incidents: list[dict] = []
    seen_ids: set[str] = set()

    all_feeds = PRIMARY_FEEDS + DIRECT_FEEDS

    for feed_cfg in all_feeds:
        url   = feed_cfg["url"]
        label = feed_cfg.get("label", url)
        print(f"→ Scraping: {label}")

        xml_text = fetch_feed(url)
        if not xml_text:
            continue

        items = parse_rss(xml_text, label)
        print(f"   {len(items)} Einträge gefunden")

        for incident in items:
            if incident["id"] not in seen_ids:
                seen_ids.add(incident["id"])
                all_incidents.append(incident)

    # Sortierung: neueste zuerst
    all_incidents.sort(key=lambda x: x["date"], reverse=True)
    return all_incidents


def load_existing() -> list[dict]:
    if OUTPUT_FILE.exists():
        try:
            return json.loads(OUTPUT_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return []


def merge(existing: list[dict], fresh: list[dict]) -> list[dict]:
    """Führt bestehende und neue Einträge zusammen (Deduplizierung per ID)."""
    existing_map = {i["id"]: i for i in existing}
    for incident in fresh:
        existing_map[incident["id"]] = incident  # überschreibt/ergänzt
    merged = list(existing_map.values())
    merged.sort(key=lambda x: x["date"], reverse=True)
    # Maximal 5000 Einträge behalten
    return merged[:5000]


def main():
    print("=" * 50)
    print("Polizei-Monitor Schweiz – Scraper gestartet")
    print(f"Zeitpunkt: {datetime.datetime.now().isoformat()}")
    print("=" * 50)

    existing  = load_existing()
    print(f"Bestehende Einträge: {len(existing)}")

    fresh     = scrape_all()
    print(f"Neu gescrapte Einträge: {len(fresh)}")

    merged    = merge(existing, fresh)
    print(f"Gesamt nach Merge: {len(merged)}")

    OUTPUT_FILE.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"✅ Gespeichert: {OUTPUT_FILE} ({OUTPUT_FILE.stat().st_size // 1024} KB)")

    # Summary für GitHub Actions Step Summary
    summary_path = Path("summary.md")
    lines = [
        "## 🇨🇭 Polizei-Monitor Schweiz – Lauf-Zusammenfassung",
        f"**Datum:** {datetime.date.today()}",
        f"**Neue Einträge:** {len(fresh)}",
        f"**Gesamt im Archiv:** {len(merged)}",
        "",
        "### Kantone (heutige Einträge)",
    ]
    kanton_counts: dict[str, int] = {}
    for inc in fresh:
        k = inc.get("kanton", "CH")
        kanton_counts[k] = kanton_counts.get(k, 0) + 1
    for k, c in sorted(kanton_counts.items(), key=lambda x: -x[1]):
        lines.append(f"- **{k}**: {c}")

    summary_path.write_text("\n".join(lines), encoding="utf-8")
    print("📄 summary.md geschrieben")


if __name__ == "__main__":
    main()
