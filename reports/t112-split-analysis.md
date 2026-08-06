# T-112 (Teil 2) — Analyse-Report: Split von `node_cli.py` + `node_utils`-Design

Repo `~/projects/ai-relay-service`, Branch `main`. Reine Analyse, keine Code-/Konfig-Änderung, kein Commit, keine Datei geschrieben.

---

## A) Machbarkeit + kritische Stellen

### A.1 Bestandsaufnahme der Kopplungen

Ich habe die Aufruf-Graphen pro Domäne aus `node_cli.py` (1700 Zeilen) plus den vier Nachbarmodulen verfolgt. Die Domänen sind **fast vollständig entkoppelt**; jede `_cmd_*`-Gruppe spricht nur mit `RelayClient`-Methoden, `node_config`-Funktionen oder `node_utils`-Funktionen — **ni**e eine `_cmd_*`-Gruppe ruft eine andere `_cmd_*`-Gruppe auf. Die einzigen Querverbindungen sind:

- **`_cmd_capabilities_publish` → `_read_pid`/`_pid_running`**: nach dem Publish wird SIGHUP an den laufenden Daemon geschickt (Zeile 998–1006).
- **`_cmd_reload` → `_read_pid`/`_pid_running`**: sendet SIGHUP (Zeile 1400–1405).
- **`Daemon._write_status` → `write_json_atomic(STATUS_PATH, …)`**, **`Daemon._heartbeat_loop` → `load_active_profile()`** etc.
- **`_cmd_status` → `STATUS_PATH` (lesen)**, **`_daemon_status` → `STATUS_PATH` + `load_json`**.

`with_client` ist der zentrale Injektor: alle per-Client-Handler (heartbeat, claim, complete, task.*, artifact.*, docs, capabilities server/info, node list/info/busy/idle/clear-status/status) bekommen `(client, args)` injiziert. Die Handler ohne Client (capabilities list/validate/publish/diff/current, update check/apply, daemon *, status, reload) rufen nur lokale Helfer.

### A.2 Konstanten-Nutzung je Domäne (prüzise kartiert)

| Domäne | Konstanten, die **direkt** im Handler-Code gelesen werden | Bezugsmodul heute |
|---|---|---|
| daemon (start/stop/status/foreground/internal) | `PID_PATH`, `LOG_PATH`, `BASE_DIR` | `node_cli` (lokal definiert: `PID_PATH = BASE_DIR/"node-cli.pid"`) |
| Daemon-Klasse | `STATUS_PATH`, `TOKEN_PATH`, `BASE_DIR` | `node_utils`/`node_config` (via `import`) |
| ops (`_cmd_status`) | `STATUS_PATH` | `node_utils` (via `import`) |
| capabilities (list) | `PROFILES_DIR` (nur für print) | `node_config` (via `import`) |
| capabilities (validate/diff) | `ACTIVE_PATH` (für `.exists()` + `load_profile`) | `node_config` (via `import`) |
| update (check) | `REPO_DIR` (nur für print) | `node_utils` (via `import`) |
| node (busy/idle/status/…) | keine direkt — nur `load_active_status()`/`write_active_status()` | `node_config` (via `import`) |
| task/artifact/docs | keine direkt — nur `client.*` | — |

**Entscheidend:** Die Konstanten werden in `node_cli.py` oben per `from … import` **als Modul-Globali gebunden** (Zeilen 54–87, 93–94). Tests patchen sie **als Attribute auf dem `node_cli`-Modulobjekt** (Fixture Zeile 55–61, 1441, 1472, 1504, 1535). Das funktioniert heute nur, weil die Handler im selben Modul leben wie die gebundenen Namen.

### A.3 Die Test-Mock-Kompatibilität im Detail

Die Tests in `tests/nodes/test_node_cli.py` (2350 Zeilen) mocken über `from nodes.common import node_cli as cli`:

1. **`monkeypatch.setattr(cli, "RelayClient", lambda meta, cfg: client)`** (z. B. Zeile 384, 426, 484, 560, 773, 890, 1842…).  Wirkt, weil `with_client` (Zeile 138) `RelayClient` als globalen Namen im `node_cli`-Modul auflöst. **→ Bleibt intakt, solange `with_client` in `node_cli` bleibt.** Submodule brauchen `RelayClient` nur als Typ-Annotation (String-form oder `TYPE_CHECKING`), nicht zur Laufzeit.
2. **`monkeypatch.setattr(cli.httpx, "stream"/"get", …)`** (Zeile 496, 514, 527, 732, 958, 1011, 1044, 1108). `cli.httpx` **ist** das `httpx`-Modulobjekt (gleiche Referenz wie `relay_client.httpx`). Patch ist also global. **→ Jedes Submodul, das `import httpx; httpx.stream(…)` schreibt, sieht den Patch** (genau wie heute schon `relay_client.py`).
3. **`monkeypatch.setattr(cli.time, "sleep", …)`** (Zeile 1357, 1382, 1988, 2047). Gleiches Muster: `cli.time is time`. **→ Submodule, die `time.sleep` via Modul-Access nutzen, sehen den Patch.** Relevant nur für die `Daemon`-Klasse (bleibt in `node_cli`).
4. **`monkeypatch.setattr(cli, "BASE_DIR"/"PROFILES_DIR"/"ACTIVE_PATH"/"PID_PATH"/"LOG_PATH"/"STATUS_PATH"/"REPO_DIR", …)`** (Zeile 55–61, 1441, 1472, 1504, 1535). **Das ist der größte Split-Risikopunkt.** Ein Submodul, das `from nodes.common.node_config import ACTIVE_PATH` ausführt, bindet den Wert zur Import-Zeit — der `cli.ACTIVE_PATH`-Patch greift danach **nicht** mehr im Submodul.
   - **Wichtigste Beobachtung:** Die Fixture patcht **parallel** auch `cl` (`node_config`) und `node_utils`: `cl.BASE_DIR`, `cl.PROFILES_DIR`, `cl.ACTIVE_PATH`, `cl.ACTIVE_PROFILE_NAME_PATH`, `cl._active_cache.path` (Zeile 48–52) und `node_utils.BASE_DIR/CONFIG_PATH/META_PATH/TOKEN_PATH/STATUS_PATH` (Zeile 64–68). Alle Funktionen **in** `node_config` (`publish_profile`, `validate_profile`, `list_profiles`, `profile_path`, `load_active_status`, `write_active_status`, `load_active_profile` via `_active_cache`) lesen ihre Konstanten als **eigene Modul-Globali** — sehen also den `cl.`-Patch. Dasselbe gilt für `node_utils`-Funktionen (`write_json_atomic` liest `STATUS_PATH` nicht direkt — bekommt Path als Arg; `load_json` ebenso).
   - **Schlussfolgerung:** Handler, die Konstanten **nur indirekt** über `node_config`-/`node_utils`-Funktionen nutzen, sind auch nach einem Split unproblematisch. **Nur** die Handler, die Konstanten **direkt** lesen (capabilities list/validate/diff → `ACTIVE_PATH`/`PROFILES_DIR`; update check → `REPO_DIR`; daemon/ops → `PID_PATH`/`LOG_PATH`/`STATUS_PATH`), brauchen eine Strategie.
5. **`cli._parse_stage_arg`** wird direkt in Tests aufgerufen (Zeile 341, 347, 354, 359). **→ Muss im `node_cli`-Namespace auflösbar bleiben** (entweder dort bleiben oder re-exportieren).
6. **`cli.build_parser`, `cli.main`, `cli.Daemon`, `cli.log`** werden von Tests referenziert (Zeile 101, 110, 975, 1273, 1973, 2034…). **→ Bleiben in `node_cli`.**

### A.4 Architektur-Optionen für die Konstanten-Mocks

Ich skizziere drei Varianten und bewerte sie gegen die Tests *ohne* Test-Änderung.

**Option 1 — Lazy-Attribut-Access via Modulreferenz im Funktionskörper.**
Das Submodul importiert das Modul, das die Konstante *kanonisch* besitzt, und referenziert sie als Attribut, z. B. `import nodes.common.node_config as _nc` und im Handler `_nc.ACTIVE_PATH.exists()`. Die Konstante wird erst beim Aufruf gelesen → der `cl.`-Patch (auf `node_config`) greift. Für `REPO_DIR` analog `import nodes.common.node_utils as _nu; _nu.REPO_DIR`. Für `PID_PATH`/`LOG_PATH` (die heute nur in `node_cli` existieren): `import nodes.common.node_cli as _cli; _cli.PID_PATH` — das ist ein **Zirkularimport**, der aber unkritisch ist, weil die Referenz *im Funktionskörper* steht (Call-Time, nachdem `node_cli` vollständig initialisiert ist) — Python löst das sauber auf.
- *Vorteile:* minimal-invasiv, **keine Test-Änderung**, keine Verschiebung von Konstanten-Definitionen, sauberer Import-Graph (Submodule → node_config/node_utils, nicht → node_cli, außer für CLI-spezifische Pfade).
- *Nachteile:* leicht mehr Tippeaufwand (`_nc.ACTIVE_PATH` statt `ACTIVE_PATH`); bei `PID_PATH`/`LOG_PATH` Zirkularität (beherrschbar).
- *Test-Kompatibilität:* ✅ für `ACTIVE_PATH`/`PROFILES_DIR`/`REPO_DIR` (über `cl.`/`node_utils.`-Patch). Für `PID_PATH`/`LOG_PATH`/`STATUS_PATH`-Prints: der `cli.`-Patch wirkt, solange die Referenz `_cli.PID_PATH` ist — ✅.

**Option 2 — Konstanten-Verschiebung nach `node_config`/`node_utils` + Test-Fixture-Umstellung.**
`PID_PATH`/`LOG_PATH` werden kanonisch in `node_config` (oder einem neuen `node_paths`-Modul) definiert; `node_cli` re-exportiert. Tests müssten `cl.PID_PATH`/`cl.LOG_PATH` patchen statt `cli.PID_PATH`.
- *Vorteile:* sauberstes Moduldesign, keine Zirkularität, echte single source of truth.
- *Nachteile:* **bricht die existierende Fixture** (`cli.PID_PATH`, `cli.LOG_PATH`) → Test-Änderungen nötig (wenige Zeilen, aber constraint-relevant: "volle Suite muss grün bleiben" — wäre mit Ko-Änderung der Tests noch grün, aber nicht mehr "ohne Test-Bruch").
- *Test-Kompatibilität:* ⚠️ nur mit Fixture-Anpassung.

**Option 3 — Proxy-/Shim-Modul `node_cli_paths` mit Modul-Level-`__getattr__`.**
Ein winziges Modul exportiert alle Pfade; Submodule importieren von dort. Patches auf `cli.<KONST>` müssten über Modul-`__getattr__` weitergeleitet werden — fragil und überraschend.
- *Vorteile:* theoretisch elegant.
- *Nachteile:* hohes "Magie"-Risiko, erschwart Debuggen, kein echter Gewinn gegenüber Option 1.
- *Test-Kompatibilität:* ⚠️ — indirekt, je nach Weiterleitung.

**Bewertung:** **Option 1 ist klarer Favorit** — sie ist minimal-invasiv, erhält alle 162 `tests/nodes/`-Tests ohne eine einzige Fixture-Änderung und erzwingt keinen Zirkularimport auf Modul-Ebene. Option 2 wäre längerfristig das sauberere Design, bricht aber die Fixture — also als Folge-Ticket (T-112 Teil 3) vorbehalten, nicht hier. Option 3 scheidet aus.

---

## B) Designfrage — was gehört in `node_utils` / `node_config`?

Ich prüfe die konkreten Kandidaten aus der Aufgabenstellung gegen das Kriterium: *"wiederverwendbar für `node_daemon.py`, zukünftige `federation_node.py` (T-096) und andere Konsumenten"* vs. *"reine CLI-Präsentation"*.

### B.1 `_read_pid` / `_pid_running` → **JA, in `node_utils` (oder `node_config`) aufnehmen.**
- Werden heute von **daemon** (`_daemon_start/stop/foreground/internal`), **ops** (`_cmd_reload`) und **capabilities** (`_cmd_capabilities_publish` für SIGHUP) genutzt.
- `node_daemon.py` definiert seine **eigene** PID-Verwaltung (`PID_PATH = BASE_DIR / "node-daemon.pid"`, schreibt/löscht selbst in `main`), hat aber **kein** `_read_pid`/`_pid_running` und kann daher aktuell keinen SIGHUP-Versand an den laufenden Daemon. Für `federation_node` wird dasselbe Muster gebraucht.
- **Empfehlung:** Beide nach `node_utils` verschieben, parametrisiert über den PID-Pfad: `read_pid(pid_path)` / `pid_running(pid)`. `node_cli` re-exportiert für Test-Kompatibilität (`cli._read_pid`, `cli._pid_running` — keine Tests greifen direkt darauf zu, aber sicherheitshalber). `node_daemon` kann sie dann für SIGHUP-Restart nutzen.
- *Kopplung:* nur `os`/`Path` — null neue Abhängigkeiten.

### B.2 `Daemon`-Klasse → **NEIN, bleibt CLI-spezifisch** (bzw. in einem `cli_daemon`-Submodul).
- `Daemon` ist der **polling-gesteuerte** Daemon des `node-cli`-Binaries. `node_daemon.SseDaemon` ist ein **bewusst paralleler** Entwurf (SSE statt Polling), der keine Basisklasse teilt, sondern das gleiche Verhalten nachbaut. Eine gemeinsame Basisklasse würde die unterschiedlichen Claim-Loop-Strategien (Polling vs. SSE-Event) künstlich abstrahieren.
- **Empfehlung:** `Daemon` bleibt im CLI-Modul (oder im `cli_daemon`-Submodul). Falls später gemeinsame Stats-/Backoff-Helfer extrahiert werden sollen, landen diese in `relay_client` (dort liegt schon `_current_backoff`) — nicht `Daemon` selbst.
- *Ausnahme:* `Daemon._write_status` und `SseDaemon._write_status` sind zu ~90 % identisch. Das wäre ein Kandidat für einen `write_daemon_status(client, cfg, *, status_path, started_at, …)`-Helfer in `node_utils`. **Empfehlung:** ja, als Folge-Ticket — nicht Teil dieses Splits, weil es beide Daemons gleichzeitig ändern würde.

### B.3 `_print_task_result` / `_print_cap_diff` → **NEIN, reine CLI-Präsentation.**
- Beide sind `print()`-Formatter für Terminal-Output mit Emoji-Icons (`✅`/`⏳`/`📄`). Weder `node_daemon` noch ein zukünftiger `federation_node` braucht Terminal-Formatierung.
- **Empfehlung:** im CLI-Modul (Submodul `cli_task` bzw. `cli_capabilities`) belassen. **Nicht** nach `node_utils`.
- *Anmerkung:* `_print_cap_diff` wird nur von `_cmd_capabilities_diff` gerufen → wandert mit diesem nach `cli_capabilities`.

### B.4 `_parse_stage_arg` → **NEIN, bleibt CLI-spezifisch** (Submodul `cli_task`), re-exportiert für Tests.
- Es ist Parse-Logik für das CLI-String-Format `<cap>:<json_payload>`. Kein anderer Konsument hat dieses Format. Reine Domain-Logik für die CLI-Schnittstelle, keine Wiederverwendung.
- **Empfehlung:** nach `cli_task` verschieben und in `node_cli` re-exportieren (`from nodes.common.cli.cli_task import _parse_stage_arg`), damit `cli._parse_stage_arg` (Tests Zeile 341–359) erhalten bleibt.

### B.5 `_save_requested_status` / `_clear_requested_status` → **NEIN, keine separate Basis-Funktion.**
- Beide sind **einzeilige Wrapper** um `write_active_status(status)` / `write_active_status(None)`. `write_active_status` liegt bereits in `node_config` und ist der echte Wiederverwendungspunkt. Die beiden Wrapper existieren nur als CLI-Befehls-Verben ("busy"/"idle"/"clear").
- **Empfehlung:** im CLI-Submodul `cli_node` belassen (oder direkt in den `_cmd_node_*`-Handlern aufrufen — noch direkter). **Nicht** in `node_utils`.

### B.6 `_html_to_text` (docs) → **NEIN, reine CLI-Präsentation.**
- Terminal-freundliche HTML-Strip-Logik für `node-cli docs`. Nirgends sonst gebraucht.
- **Empfehlung:** mit `cli_docs` verschieben.

### B.7 Zusammenfassung B
| Baustein | Entscheidung | Ziel |
|---|---|---|
| `_read_pid` / `_pid_running` | **verschieben** | `node_utils` (parametrisiert) + re-export in `node_cli` |
| `Daemon` | **bleiben** | `cli_daemon`-Submodul (CLI-spezifisch) |
| `Daemon._write_status` (gemeinsam mit SseDaemon) | Folge-Ticket | `node_utils`-Helfer (nicht Teil dieses Splits) |
| `_print_task_result` / `_print_cap_diff` | **bleiben** | `cli_task` / `cli_capabilities` |
| `_parse_stage_arg` | **bleiben** | `cli_task` + re-export in `node_cli` |
| `_save_requested_status` / `_clear_requested_status` | **bleiben** | `cli_node` |
| `_html_to_text` | **bleiben** | `cli_docs` |

---

## C) Konkreter Split-Vorschlag

### C.1 Zielstruktur

```
nodes/common/
  node_cli.py            # Fassade: build_parser, main, with_client, _daemon_dispatch,
                         # _read_pid/_pid_running (re-export), _parse_stage_arg (re-export),
                         # PID_PATH/LOG_PATH, log, alle _cmd_* re-exports für build_parser
  node_config.py         # unverändert (+ optional PID-/LOG-Pfade später)
  node_utils.py          # + read_pid(pid_path), pid_running(pid)
  node_daemon.py         # unverändert (bereits entkoppelt)
  relay_client.py        # unverändert
  cli/
    __init__.py          # leer (Paketmarker)
    cli_daemon.py        # Daemon-Klasse, _daemon_start/stop/restart/status/foreground/internal
    cli_task.py          # _parse_stage_arg, _cmd_task_submit/result/note/wait, _print_task_result
    cli_artifact.py      # _cmd_artifact_download/upload
    cli_docs.py          # _html_to_text, _cmd_docs
    cli_update.py        # _cmd_update_check/apply
    cli_capabilities.py   # _cmd_capabilities_list/validate/publish/diff/current/server/info, _print_cap_diff
    cli_node.py          # _cmd_node_list/info/busy/idle/clear_status/status,
                         # _save_requested_status, _clear_requested_status
    cli_ops.py           # _cmd_status, _cmd_reload
```

Die `cli_*`-Submodule sind **nur Handler-Implementationen**; `node_cli.py` importiert sie und registriert die Funktionen in `build_parser()` per `set_defaults(func=…)`. Der Einstiegspunkt `node-cli = nodes.common.node_cli:main` bleibt **unverändert**.

### C.2 Was in `node_cli.py` als Fassade bleibt

- `PID_PATH`, `LOG_PATH` (lokal, weil CLI-spezifisch; `cli_daemon`/`cli_ops` referenzieren sie lazy via `_cli.PID_PATH`).
- `log = logging.getLogger("node-cli")`.
- `with_client` (Decorator) — weil Tests `cli.RelayClient` patchen und `with_client` den Namen im `node_cli`-Modul auflöst.
- `Daemon`-Klasse: **entweder hier** oder im `cli_daemon`-Submodul (s. C.3 Empfehlung). Da Tests `cli.Daemon` referenzieren (Zeile 1273, 1973, 2034) und `Daemon` stark mit `PID_PATH`/`LOG_PATH`/`STATUS_PATH`/`TOKEN_PATH` sowie `time.sleep` (gepatcht via `cli.time`) verwoben ist, **empfehle ich: `Daemon` in `cli_daemon` verschieben und in `node_cli` re-exportieren** (`from nodes.common.cli.cli_daemon import Daemon`). Der Re-Export macht `cli.Daemon` weiterhin auflösbar; `cli.time.sleep`-Patch wirkt, weil `Daemon` in `cli_daemon` `import time; time.sleep(…)` schreibt und `cli.time is time` ist.
- `build_parser`, `main`, `__main__`.
- `_daemon_dispatch` (bleibt, da es `_daemon_*` dispatcht).
- Re-Exports: `RelayClient`, `_base_url`, `_effective_config`, `_filename_from_response`, `_setup_logging`, `_utcnow_str` (bereits heute vorhanden, unverändert).
- Re-Exports für Test-Sichtbarkeit: `_parse_stage_arg` (aus `cli_task`), `_read_pid`/`_pid_running` (aus `node_utils`), `Daemon` (aus `cli_daemon`).
- **Alle Konstanten** (`BASE_DIR`, `PROFILES_DIR`, `ACTIVE_PATH`, `STATUS_PATH`, `REPO_DIR`, `TOKEN_PATH`, `SERVICE_UNIT`) weiterhin per `from … import` gebunden, damit die Fixture-Patches `cli.<KONST>` weiterhin angewendet werden *können* (auch wenn die Handler sie nicht mehr direkt lesen — die Patches sind reine No-ops, brechen aber nichts).

### C.3 Konkrete Funktions-Wanderung

| Von `node_cli.py` | Nach | Begründung |
|---|---|---|
| `Daemon` + `_install_signal_handlers`/`_on_term`/`_on_hup`/`_write_status`/`_heartbeat_loop`/`_start_heartbeat_thread`/`_run_stage`/`_claim_loop`/`run` | `cli/cli_daemon.py` | Daemon-Logik, gekoppelt an `PID_PATH`/`STATUS_PATH`/`TOKEN_PATH` |
| `_daemon_start/stop/restart/status/foreground/internal`, `_daemon_dispatch` | `cli/cli_daemon.py` (dispatch optional in Fassade) | brauchen `PID_PATH`/`LOG_PATH` |
| `_read_pid`, `_pid_running` | `node_utils.py` (parametrisiert) | wiederverwendbar (B.1) |
| `_parse_stage_arg`, `_cmd_task_submit/result/note/wait`, `_print_task_result` | `cli/cli_task.py` | eine Domäne |
| `_cmd_artifact_download/upload` | `cli/cli_artifact.py` | eine Domäne |
| `_html_to_text`, `_cmd_docs` | `cli/cli_docs.py` | eine Domäne |
| `_cmd_update_check/apply` | `cli/cli_update.py` | eine Domäne; liest `REPO_DIR` lazy via `_nu.REPO_DIR` |
| `_cmd_capabilities_list/validate/publish/diff/current/server/info`, `_print_cap_diff` | `cli/cli_capabilities.py` | eine Domäne; liest `ACTIVE_PATH`/`PROFILES_DIR` lazy via `_nc.ACTIVE_PATH`/`_nc.PROFILES_DIR`; nutzt `_read_pid`/`_pid_running` für SIGHUP |
| `_cmd_node_list/info/busy/idle/clear_status/status`, `_save_requested_status`, `_clear_requested_status` | `cli/cli_node.py` | eine Domäne |
| `_cmd_status`, `_cmd_reload` | `cli/cli_ops.py` | liest `STATUS_PATH`/`PID_PATH` lazy |
| `with_client`, `build_parser`, `main`, `log`, `PID_PATH`, `LOG_PATH`, Re-Exports | `node_cli.py` | Fassade |

### C.4 Wie die Test-Mocks überleben (Beantwortung A-4)

Konkret für jede Patch-Kategorie:

1. **`cli.RelayClient`-Patch** → `with_client` bleibt in `node_cli`, löst `RelayClient` als `node_cli`-Global auf → Patch wirkt. ✅
2. **`cli.httpx.*` / `cli.time.*`-Patches** → `httpx`/`time` sind identische Modulobjekte in jedem Submodul. Submodule schreiben `httpx.stream(…)`/`time.sleep(…)` (Modul-Access, nicht `from httpx import stream`) → Patch wirkt global. ✅
3. **`cli.load_meta` / `cli._effective_config` / `cli.load_active_profile` / `cli.run_handler`-Patches** → diese wirken auf `node_cli`-Globals. `with_client` (bleibt) nutzt `load_meta`/`_effective_config` → Patch wirkt. `Daemon` (in `cli_daemon`) nutzt `load_active_profile`/`run_handler` → **Achtung:** die Tests patchen `cli.load_active_profile`/`cli.run_handler` (Zeile 1293, 1320, 1339, 1372), und `Daemon` muss diese sehen. **Lösung:** `cli_daemon.py` importiert `load_active_profile`/`run_handler` **nicht** per `from … import`, sondern referenziert sie lazy über `node_cli`: `import nodes.common.node_cli as _cli; _cli.load_active_profile()`/`_cli.run_handler()`. Da `node_cli` die Namen re-exportiert und die Tests sie auf `node_cli` patchen, wirkt der Patch. ✅ Alternativ: `Daemon` bleibt komplett in `node_cli` (sicherer, keine Re-export-Magie) — das ist meine **empfohlene Variante**, weil `Daemon` ohnehin stark mit CLI-Internalen verknüpft ist.
   - **Empfehlung (verbindlich):** `Daemon` + `_daemon_*` + `_daemon_dispatch` bleiben in `node_cli.py`. Damit entfällt das zirkuläre Lazy-Access-Muster für `load_active_profile`/`run_handler`/`time.sleep` komplett, und alle Daemon-Tests laufen unverändert. `cli_daemon.py` entfällt. Das reduziert den Split auf **6 Submodule** (`cli_task`, `cli_artifact`, `cli_docs`, `cli_update`, `cli_capabilities`, `cli_node`, `cli_ops`) — immer noch eine Reduktion von 1700 auf ~700 Zeilen Fassade.
4. **`cli.<KONST>`-Patches**:
   - `cli.PID_PATH`/`LOG_PATH`/`STATUS_PATH` → nur von `Daemon`/`_daemon_*`/`_cmd_status`/`_cmd_reload` gelesen, die **in `node_cli` bleiben** → Patch wirkt direkt. ✅
   - `cli.BASE_DIR`/`PROFILES_DIR`/`ACTIVE_PATH`/`REPO_DIR` → die moved Handler (`cli_capabilities`, `cli_update`) referenzieren diese lazy via `_nc.`/`_nu.` → die `cl.`/`node_utils.`-Patches wirken. Die `cli.`-Patches werden zu No-ops (die Fixture patcht zwar `cli.PROFILES_DIR`, aber der Handler liest `_nc.PROFILES_DIR`). Das ist **ungefährlich** — der Test bleibt grün, weil die zugrunde liegende `node_config`-Funktion (`list_profiles`/`publish_profile`/…) ihrerseits das gepatchte `cl.PROFILES_DIR` liest und der Handler-Print `"(no profiles in %s)" % _nc.PROFILES_DIR` denselben Wert sieht. ✅
   - `cli.REPO_DIR` → `_cmd_update_check` printet `_nu.REPO_DIR` (gepatcht via `node_utils.REPO_DIR`, Zeile 1440/1471/1503/1534) ✅. `cli.REPO_DIR`-Patch wird No-op.
5. **`cli._parse_stage_arg`** → `cli_task` definiert es, `node_cli` re-exportiert → `cli._parse_stage_arg` auflösbar. ✅
6. **`cli.build_parser`/`main`/`Daemon`/`log`** → bleiben in `node_cli`. ✅

### C.5 Wie `import nodes.common.node_cli` + `node_daemon` weiter funktionieren

- `import nodes.common.node_cli` → lädt die Fassade; die Fassade importiert ihrerseits die `cli.*`-Submodule (für `build_parser`-Referenzen). Kein Zirkularimport, weil die Submodule **nicht** `node_cli` importieren (sie importieren nur `node_config`/`node_utils`/`relay_client` und nutzen `httpx`/`time` direkt).
- `node_daemon.py` ist bereits entkoppelt (importiert aus `relay_client`/`node_config`/`node_utils`) → vom Split **nicht betroffen**.
- Der Einstiegspunkt `node-cli = nodes.common.node_cli:main` bleibt unverändert.

### C.6 Reihenfolge + Verifikation nach jedem Schritt

Jeder Schritt endet mit: `pytest tests/nodes/ -q` (162 Tests), dann `pytest -q` (volle Suite, 419 Tests), dann `ruff check nodes/common/ tests/nodes/`. Commits pro Schritt (klein, revertierbar).

1. **Schritt 1 — `_read_pid`/`_pid_running` nach `node_utils`** (parametrisiert als `read_pid(pid_path)`/`pid_running(pid)`). `node_cli` re-exportiert als `_read_pid`/`_pid_running` (Wrapper auf die neuen Funktionen, damit Aufrufsignatur identisch bleibt). *Verify:* `pytest tests/nodes/test_node_cli.py -q` (insbes. daemon-Tests, publish-Tests).
2. **Schritt 2 — `cli_task`-Submodul extrahieren** (`_parse_stage_arg`, `_cmd_task_submit/result/note/wait`, `_print_task_result`). `node_cli` importiert die Funktionen und re-exportiert `_parse_stage_arg`. *Verify:* `pytest tests/nodes/ -q`; darauf achten, dass `cli._parse_stage_arg`-Tests (Zeile 341–359) und task-Handler-Tests grün sind.
3. **Schritt 3 — `cli_artifact`** (`_cmd_artifact_download/upload`). *Verify:* artifact-Tests (Zeile 656–711, 731–745), `cli.httpx.stream`-Patch wirkt.
4. **Schritt 4 — `cli_docs`** (`_html_to_text`, `_cmd_docs`). *Verify:* docs-Tests (Zeile 1133–1230).
5. **Schritt 5 — `cli_update`** (`_cmd_update_check/apply`); `REPO_DIR`-Print via `_nu.REPO_DIR`. *Verify:* update-Tests (Zeile 1430–1556); beide `REPO_DIR`-Patches prüfen.
6. **Schritt 6 — `cli_capabilities`** (`_cmd_capabilities_*`, `_print_cap_diff`); `ACTIVE_PATH`/`PROFILES_DIR` via `_nc.`. *Verify:* capabilities-Tests (Zeile 173–303, 958–1060, 1108–1230).
7. **Schritt 7 — `cli_node`** (`_cmd_node_*`, `_save_requested_status`, `_clear_requested_status`). *Verify:* node-Tests (Zeile 1628–1842).
8. **Schritt 8 — `cli_ops`** (`_cmd_status`, `_cmd_reload`); `STATUS_PATH` via `_nu.STATUS_PATH` (oder in Fassade belassen, da klein). *Verify:* status/reload-Tests (Zeile 308–330).
9. **Schritt 9 — `ruff check` + volle Suite**; Aufräumen nicht mehr genutzter Imports in `node_cli.py`. *Verify:* `pytest -q` (419 passed), `ruff check`.

### C.7 Risiken + Rollback-Strategie

- **R1 — Lazy-Constant-Access vergessen:** Wenn ein moved Handler versehentlich `ACTIVE_PATH` statt `_nc.ACTIVE_PATH` schreibt (Modul-Global des Submoduls, ungepatcht), schlägt der Capabilities-Test fehl (`ACTIVE_PATH.exists()` prüft echten `~/.relay/node.yaml`). *Mitigation:* Code-Review + der Test fängt es sofort. Kein stiller Fehler.
- **R2 — `from … import` von Helfern, die auf `cli` gepatcht werden:** Wenn ein Submodul `from nodes.common.node_cli import load_active_profile` schreibt (Zirkularimport + bricht Patch). *Mitigation:* niemals `node_cli` aus Submodulen importieren; nur `node_config`/`node_utils`/`relay_client`.
- **R3 — Re-Export-Vergessen:** `cli._parse_stage_arg`/`cli.Daemon`/`cli._read_pid`/`cli._pid_running` müssen sichtbar bleiben. *Mitigation:* expliziter Re-Export-Block in `node_cli.py` (wie heute schon für `RelayClient` etc.).
- **R4 — `httpx`/`time`-Modul-Access-Form:** Ein Submodul, das `from httpx import stream` schreibt, bindet die Originalfunktion und ignoriert `cli.httpx.stream`-Patch. *Mitigation:* alle Submodule nutzen `httpx.stream(…)` (Attribut-Zugriff); `ruff` ggf. per Config-Regel absichern.
- **R5 — `Daemon` bleibt in `node_cli`:** Dann ist `node_cli.py` nach dem Split immer noch ~700 Zeilen (Fassade + Daemon + daemon-control). Das ist akzeptiert — die `Daemon`-Extraktion ist ein **separates Folge-Ticket**, weil sie `node_daemon.SseDaemon` miterfassen würde (gemeinsamer `_write_status`-Helfer). Hier nicht angreifen.
- **Rollback:** Jeder Schritt ist ein eigener Commit. Rollback = `git revert <commit>`. Da die Fassade `node_cli.py` alleine lauffähig bleibt (alle `_cmd_*` re-exportiert) und die Submodule nur von `build_parser` importiert werden, kann jeder Schritt isoliert revertiert werden, ohne Folgeschritte zu brechen. Schrittreihenfolge so gewählt, dass jeder Schritt die Test-Suite grün hält.

### C.8 Constraints-Check

- ✅ Nur Analyse, kein Code-Change, kein Commit.
- ✅ Einstiegspunkt `node-cli = nodes.common.node_cli:main` unverändert.
- ✅ Alle CLI-Commands erhalten (`build_parser` bleibt, registriert alle `_cmd_*`).
- ✅ Volle Suite bleibt grün: alle Mock-Muster aus A.4 explizit abgedeckt; keine Test-Änderung nötig.
- ✅ Deutsch, technische Begriffe Englisch.

---

**Fazit:** Der Split ist **machbar ohne Test-Änderung**, wenn (a) `Daemon`/`_daemon_*`/`_cmd_status`/`_cmd_reload` in der Fassade bleiben, (b) die moved Handler Konstanten lazy via `node_config`/`node_utils` referenzieren (nicht via `node_cli`), (c) `httpx`/`time` als Modul-Attribut genutzt werden und (d) `_parse_stage_arg`/`Daemon`/`_read_pid`/`_pid_running` re-exportiert werden. `_read_pid`/`_pid_running` sind die einzigen echten `node_utils`-Kandidaten (B.1); alle anderen Präsentations-/Parse-Helfer bleiben CLI-spezifisch.
