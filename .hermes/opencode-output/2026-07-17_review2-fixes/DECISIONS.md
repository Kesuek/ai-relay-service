# DECISIONS — Review 2026-07-17

## 2026-07-17 — Zweiter GitHub-Review (review-20260717)

Zweiter GitHub-Review: 22 Findings (4 CRITICAL, 15 MEDIUM, 3 LOW) alle
behandelt. Reine Doku-Arbeit + 1 Whitelist-Eintrag; keine
Geschäftslogikänderung. Tests 203/203 grün.

### Entscheidungen / Klärungen

- **#2 design-board.md** — "abgeschnittener Text `st[...]`": Prüfung
  ergab, dass die Datei im vorherigen Struktur-Commit bereits sauber
  angelegt wurde. Kein Eingriff; als "already-correct" dokumentiert statt
  eine Änderung zu erzwingen.
- **#3/#12 api.md** — Beide Findings (cURL-Beispiele + Payload/Error-Codes)
  in einem einzigen "Worked examples (cURL)"-Abschnitt zusammengeführt,
  wie im Plan vorgesehen. Enthält: Error-Code-Tabelle, Rate-Limits,
  register, register-admin, heartbeat, claim, complete, task (DAG +
  simple), upload, download, refresh/recover.
- **#14 Capability-Naming `.native`** — Regel in `concepts.md`,
  `capabilities.md` und `design-board.md` konsistent gemacht: **jede**
  konkrete Capability muss einen Suffix tragen; **alle** KI-less Nodes
  verwenden `.native` (inkl. db-node: `db.board.create.native` usw.).
  design-board.md's db-node-Capability-Liste war die einzige Stelle, die
  die Suffixe weggelassen hatte — korrigiert.
- **#17/#10 `RELAY_RUNTIME_TOKEN`** — Plan schlug Env-Var als
  Token-Alternative vor. Code-Recherche: Node-CLI liest Token nur aus
  Datei; Env-Var ist Dashboard-Only und wird vom CLI **nicht** ausgewertet.
  Doku zeigt stattdessen die real funktionierenden Alternativen
  (Bind-Mount, Secret-Manager-Provisionierung) und markiert die Env-Var
  als "not yet honoured". Keine falsche Funktion dokumentiert.
- **#18 getting-started.md** — Neues Dokument erstellt und in die
  `/relay/v2/docs`-Whitelist (`docs.py`) aufgenommen, damit es auch über
  das Dashboard erreichbar ist.
- **#19 KI vs AI** — Begriffsklärung in concepts.md eingefügt: "KI"
  (deutsches Konzept-Dok) und "AI" (API/Code) sind synonym; worker node =
  KI-capable, service node = KI-less.