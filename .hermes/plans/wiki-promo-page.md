# Plan: Wiki-Promo-Seite

## Ziel
Eine HTML-Promo-Seite erstellen, die das gesamte Wiki-System visuell ansprechend präsentiert — als Übersicht für Ronny und potenziell als Dashboard-Seite.

## Anforderungen
- **HTML + CSS only** (kein JS-Framework, keine externen Abhängigkeiten)
- **Responsive** (Desktop + Mobile)
- **Deutsche Sprache**
- **Dark Mode** (passt zum Hermes-Dashboard-Style)
- **Inhalte aus** `wiki-feature-list.md` übernehmen

## Struktur der Seite

### Hero-Bereich
- Titel: "Wiki-System — Automatischer Memory-Store"
- Subtitle: "Obsidian-kompatibles Markdown-Wiki als Gedächtnis für Hermes"
- Kurze Beschreibung: Kombiniert automatische Befüllung (News, Dreaming) mit manueller Kuration

### Sektionen

1. **Datenquellen** — Karten/Grid mit News-DB, Wikipedia, Memory Provider, Manuelle Einträge
2. **Nächtlicher Datenfluss** — Visuelle Timeline/Flow der Cron-Jobs (03:00–06:35)
3. **Skills** — Die 6 Wiki-Skills als Karten
4. **Wiki-Struktur** — entities/, concepts/, news/ als Verzeichnisbaum
5. **Features** — Automatische News-Integration, Dreaming, Curation, Graph, Entity Maintenance, Wikipedia-Import
6. **Technische Details** — Pfade, DB, Cron, Statistiken

### Footer
- "Built with ❤️ by Felix & Ronny"

## Design-Vorgaben
- **Farben:** #1a1a2e (dunkel), #16213e (dunkler), #0f3460 (akzent), #e94560 (highlight), #ffffff (text)
- **Schrift:** system-ui, sans-serif
- **Icons:** Emoji/Unicode (keine Icon-Library)
- **Karten:** Abgerundete Ecken (12px), sanfte Schatten, Hover-Effekte
- **Timeline:** Vertikale Linie mit Punkten + Karten

## Ausgabe
- Datei: `~/wiki/main/promo.html`
- Soll im Browser direkt geöffnet werden können (kein Server nötig)

## Quellen
- `/home/felix/projects/ai-relay-service/.hermes/plans/wiki-feature-list.md` — vollständige Feature-Liste
