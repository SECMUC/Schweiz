# 🇨🇭 Polizei-Monitor Schweiz

Analoges Projekt zum PP-München-Scraper – OSINT-Tool für Schweizer Polizeimeldungen.

## Struktur

```
polizei-monitor-ch/
├── scraper.py           ← Python-Scraper (RSS-Feeds aller Kantone)
├── incidents.json       ← Output (auto-generiert, von GitHub Actions befüllt)
├── index.html           ← Dashboard (single-page, läuft direkt im Browser)
└── summary.md           ← Lauf-Zusammenfassung (GitHub Actions)
```

Die GitHub-Actions-Workflow-Datei (`scrape-ch.yml`) gehört nach:
```
.github/workflows/scrape-ch.yml
```

## Quellen

| Quelle | URL | Typ |
|--------|-----|-----|
| polizeinews.ch – Schweiz | `https://www.polizeinews.ch/feed/` | RSS (WordPress) |
| polizeinews.ch – Zürich | `https://www.polizeinews.ch/region-zuerich/feed/` | RSS |
| polizeinews.ch – Bern | `https://www.polizeinews.ch/espace-mittelland/bern/feed/` | RSS |
| polizeinews.ch – Basel-Stadt | `https://www.polizeinews.ch/nordwestschweiz/basel-stadt/feed/` | RSS |
| polizeinews.ch – Luzern | `https://www.polizeinews.ch/zentralschweiz/luzern/feed/` | RSS |
| Kantonspolizei Zürich | direkt (XML) | RSS |
| Kantonspolizei Bern | direkt (XML) | RSS |

> Weitere Kantone einfach in `PRIMARY_FEEDS` ergänzen (WordPress-Muster: `/kantons-slug/feed/`).

## Setup

### Lokal testen

```bash
pip install requests  # optional, scraper nutzt nur stdlib
python scraper.py
# → erzeugt incidents.json
python -m http.server 8080
# Browser: http://localhost:8080/index.html
```

### GitHub Pages

1. Repo → Settings → Pages → Branch `main`, Ordner `/polizei-monitor-ch`
2. Workflow-Datei unter `.github/workflows/scrape-ch.yml` ablegen
3. `incidents.json` initial committen (leeres Array `[]`)

### GitHub Actions Secrets

Keine nötig – alle Quellen sind öffentlich.

## Features

- **Alle 26 Kantone** erkannt (automatische Kanton-Erkennung per Regex)
- **Kategorien**: Unfall, Einbruch, Gewalt, Brand, Drogen, Betrug, Vermisst, Verhaftung, Todesfälle
- **Deduplizierung** via MD5-Hash aus URL + Titel
- **Archiv** (max. 5.000 Einträge, älteste fallen raus)
- **Export**: CSV (Excel-kompatibel mit BOM) + JSON
- **Dashboard**: Suche, Kanton-Filter, Kategorie-Filter, Zeitraum-Filter

## Erweiterungsideen

- Telegram-Kanal der Kapos scrapen (wie PP München)
- Alerting per E-Mail / Telegram wenn bestimmte Kantone oder Keywords auftauchen
- Zweite App: Kantonsspezifisches Deep-Dive-Dashboard
