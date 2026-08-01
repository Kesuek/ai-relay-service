# Wiki-System — Feature-Liste & Architektur

## Überblick

Das Wiki (`~/wiki/main/`) ist ein Obsidian-kompatibles Markdown-Wiki, das als **Memory-Store** für Hermes dient. Es kombiniert automatische Befüllung (News, Dreaming) mit manueller Kuration (Entity-Seiten, Konzepte) und einem interaktiven Graph-Visualizer.

---

## 1. Datenquellen

| Quelle | Beschreibung | Update-Rhythmus |
|--------|-------------|-----------------|
| **News-Monitoring-DB** | SQLite mit Volltexten gescannter Artikel (SearxNG + RSS) | 03:00 + 15:00 |
| **Wikipedia-Import** | Automatischer Import bei Themen-Clustern (≥5 Artikel in 48h) | Wöchentlich (Mo 05:30) |
| **Wiki Memory Provider** | Sammelt Konversations-Fakten während Sessions | Kontinuierlich → pending.json |
| **Manuelle Einträge** | Entity-Seiten, Konzepte, Präferenzen | Bei Bedarf |

## 2. Wiki-Struktur

| Verzeichnis | Inhalt | Anzahl |
|-------------|--------|--------|
| `entities/` | Personen, Server, Dienste (z.B. `ronny.md`, `minecraft-server.md`) | 16 |
| `concepts/` | Themen, News-Kategorien, Setup (z.B. `media-law.md`, `setup-optimierung.md`) | 10 |
| `news/` | Tägliche News-Importe + Daily-Digests | ~25+ |
| `_archive/` | Archivierte/obsolete Seiten | variabel |
| `index.md` | Vollständiger Seitenkatalog | — |
| `SCHEMA.md` | Tag-Taxonomie, Frontmatter-Konventionen, Page-Thresholds | — |
| `log.md` | Append-only Aktions-Log | — |
| `wiki-graph.html` | Interaktiver D3.js Force-Directed Graph | — |
| `wiki-graph.json` | Graph-Daten (Nodes + Links) | — |

## 3. Cron-Jobs (nächtlicher Datenfluss)

```
03:00  ⬤ wiki-dreaming-nightly     — pending.json → Wiki kuratieren
03:00  ⬤ news-scanner-all          — News-DB füllen (SearxNG + RSS)
04:00  ⬤ news-to-wiki-sync         — News-DB → Wiki-Notizen + Konzept-Updates
05:00  ⬤ wiki-graph-regenerate     — Graph neu bauen (D3.js)
05:00  ⬤ news-retention-cleanup    — News >90 Tage löschen (Mo)
05:30  ⬤ wikipedia-concept-import  — Wikipedia bei Themen-Clustern (Mo)
06:00  ⬤ news-daily-digest         — Tageszusammenfassung
06:30  ⬤ morning-briefing-v3       — Persönliches Briefing
06:35  ⬤ daily-digest-to-wiki      — Digest als Wiki-Notiz
01/07/13/19 ⬤ wiki-curator         — Lint, Keywords, Crosslinks, Health
```

## 4. Skills (Hermes-Wissen)

| Skill | Zweck |
|-------|-------|
| **wiki-dreaming** | Nächtliche LLM-gestützte Konsolidierung von pending.json → Wiki |
| **wiki-curation** | Automatisierte Curation-Passes (Lint, Source-Drift, Keywords, Crosslinks) |
| **wiki-knowledge-graph** | News-DB ↔ Wiki-Verknüpfung, Scripte, Mapping |
| **wiki-memory-provider** | MemoryProvider-Plugin: prefetch() + sync_turn() → pending.json |
| **wiki-entity-maintenance** | Entity-Seiten mit Live-System abgleichen |
| **news-wiki-integration** | News-to-Wiki-Pipeline (Keyword-Mapping, Retention) |

## 5. Scripte

| Script | Pfad | Zweck |
|--------|------|-------|
| `news-to-wiki.py` | `~/.hermes/projects/news-wiki-knowledge-graph/` | News-DB → Wiki-Notizen |
| `update-concept-pages.py` | selbes Verzeichnis | News-Notizen → Konzept-Seiten-Updates |
| `daily-digest-to-wiki.py` | selbes Verzeichnis | Digest als Wiki-Notiz |
| `retention-cleanup.py` | selbes Verzeichnis | Löscht News >90 Tage |
| `wikipedia-concept-import.py` | selbes Verzeichnis | Wikipedia-Import bei Themen-Clustern |
| `wiki-graph.py` | `~/.hermes/projects/wiki-knowledge-graph-viz/` | D3.js-Graph-Generator |
| `wiki-http-server.py` | `~/.hermes/scripts/` | HTTP-Server für Graph (Tailscale :8790) |
| `wiki-dreaming.sh` | `~/.hermes/scripts/` | Cron-Wrapper für Dreaming |
| `news-wiki-sync.sh` | `~/.hermes/scripts/` | Cron-Wrapper für Sync |
| `wiki-graph-gen.sh` | `~/.hermes/scripts/` | Cron-Wrapper für Graph |
| `lint-wiki.py` | `~/.hermes/skills/research/llm-wiki/scripts/` | Lint-Scanner |

## 6. Features im Detail

### 6.1 Automatische News-Integration
- News-DB wird 2x täglich gescannt (SearxNG + RSS)
- Relevante Artikel (Score ≥ 0.6) werden als Markdown-Notizen ins Wiki importiert
- Keyword-to-Concept-Mapping (YAML) verknüpft Artikel mit Wiki-Seiten
- Konzept-Seiten erhalten automatisch `## News & Entwicklungen`-Timeline
- Drei-Ebenen-Retention: News-Notizen (90d) → Konzept-Seiten (dauerhaft) → News-DB (für immer)

### 6.2 Wiki Memory Provider (Dreaming)
- Sammelt User + Assistant Nachrichten während Sessions
- Flusht nach jedem Turn in `pending.json`
- Nächtlicher Cron (03:00) analysiert Fakten per LLM und sortiert sie in die richtigen Wiki-Seiten ein
- LLM-gesteuertes Routing: erkennt selbstständig ob ein Fakt zu `entities/ronny.md`, `entities/minecraft-server.md` oder `concepts/auto-facts.md` gehört
- Buffer-Kompression bei >100 Einträgen via lokalem LLM

### 6.3 Curation & Health
- Lint-Scanner prüft: Broken Wikilinks, Orphans, Stale Pages, Frontmatter, Tag-Taxonomie, Source-Drift
- Keyword-Audit: Jede Seite braucht ≥2 Aliase
- Crosslink-Audit: Jede Seite braucht ≥2 ausgehende Wikilinks
- Log-Rotation bei >500 Einträgen
- Health-Status: GREEN/YELLOW/RED

### 6.4 Interaktiver Graph (D3.js)
- Force-Directed Graph mit 430+ Nodes, 500+ Links
- Farbcodierung nach Seitentyp (Entity/Concept/News/Daily)
- Node-Größe proportional zu eingehenden Links
- Suchfeld, Typ-Checkboxen, Tag-Dropdown
- Klick öffnet Wiki-Seite
- HTTP-Server auf Tailscale-IP :8790
- Tägliche Neugenerierung um 05:00

### 6.5 Entity Maintenance
- Regelmäßiger Abgleich Wiki ↔ Live-System (Proxmox, Netzwerk)
- CT-Liste, IPs, RAM/CPU, Dienste
- Klassifizierung: Permanenter Dienst vs. Projekt-Container vs. Host

### 6.6 Wikipedia-Import
- Automatisch bei ≥5 Artikeln zum selben Thema in 48h
- Wöchentlicher Cron (Mo 05:30)
- HTML-Tag-Bereinigung, Begriffsklärungs-Overrides

## 7. Technische Details

- **Speicherort:** `~/wiki/main/`
- **News-DB:** `~/.hermes/shared/news-monitoring/news_monitoring.db` (SQLite, FTS5)
- **Dreaming-Buffer:** `~/.hermes/dreaming/pending.json`
- **Keyword-Mapping:** `~/.hermes/projects/news-wiki-knowledge-graph/mapping.yaml`
- **Graph-HTTP:** Tailscale `100.64.0.9:8790`
- **Wiki-Seiten gesamt:** 51 (16 entities, 10 concepts, 24 news topics, 1 SCHEMA, 1 index, 1 log)
- **Graph-Struktur:** 430+ Nodes, 527 Links
- **Cron-Jobs:** 12 aktive Jobs
- **Skills:** 6 Wiki-bezogene Skills
