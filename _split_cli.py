"""T-112 split: extract domain handlers from node_cli.py into cli/ submodules."""
import ast
import pathlib

base = pathlib.Path("nodes/common")
cli_path = base / "node_cli.py"
lines = cli_path.read_text().splitlines()
tree = ast.parse(cli_path.read_text())

def extent(name):
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name == name:
            return n.lineno, n.end_lineno
    return None

def slice_names(names):
    """Return list of (name, start_line, end_line) for the given top-level names."""
    out = []
    for nm in names:
        e = extent(nm)
        if e:
            out.append((nm, e[0], e[1]))
    out.sort(key=lambda x: x[1])
    return out

# Domänen -> Submodul
domains = {
    "cli_task.py": [
        "_parse_stage_arg", "_cmd_task_submit", "_cmd_task_result",
        "_cmd_task_note", "_cmd_task_wait", "_print_task_result",
    ],
    "cli_artifact.py": ["_cmd_artifact_download", "_cmd_artifact_upload"],
    "cli_docs.py": ["_html_to_text", "_cmd_docs"],
    "cli_update.py": ["_cmd_update_check", "_cmd_update_apply"],
    "cli_capabilities.py": [
        "_cmd_capabilities_list", "_cmd_capabilities_validate",
        "_cmd_capabilities_publish", "_cmd_capabilities_diff",
        "_print_cap_diff", "_cmd_capabilities_current",
        "_cmd_capabilities_server", "_cmd_capabilities_info",
    ],
    "cli_node.py": [
        "_cmd_node_list", "_cmd_node_info", "_save_requested_status",
        "_clear_requested_status", "_cmd_node_busy", "_cmd_node_idle",
        "_cmd_node_clear_status", "_cmd_node_status",
    ],
    "cli_ops.py": ["_cmd_status", "_cmd_reload"],
}

# Welche Handler bleiben in node_cli? (with_client, Daemon, daemon control, heartbeat/claim/complete)
keep = {
    "with_client", "Daemon", "_read_pid", "_pid_running", "_daemon_start",
    "_daemon_stop", "_daemon_status", "_daemon_restart", "_daemon_foreground",
    "_daemon_internal", "_cmd_heartbeat", "_cmd_claim", "_cmd_complete",
}

moved = {}
for mod, names in domains.items():
    moved[mod] = slice_names(names)

# Für jedes Submodul: Zeilenbereich (vom ersten bis letzten Funktion, inkl Leerzeilen drumherum)
def block_lines(mod_names):
    items = slice_names(mod_names)
    first = items[0][1]  # 1-indexed start
    last = items[-1][2]  # 1-indexed end
    # expand to include surrounding blank lines
    s = first
    while s > 1 and lines[s-2].strip() == "":
        s -= 1
    e = last
    while e < len(lines) and lines[e].strip() == "":
        e += 1
    return s, e, items

for mod, names in domains.items():
    s, e, items = block_lines(names)
    print(f"{mod}: Z.{s}-{e} ({e-s+1} Z) -> {len(items)} Funktionen")
