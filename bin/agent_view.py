#!/usr/bin/env python3
"""agent-view-filters: cycle the Herdr Agents sidebar between four modes.

Modes:
  active - only agents currently working or blocked
  space  - only agents in the focused space (workspace)
  picked - every agent except those the user excluded in the picker popup
  all    - clear the view, show everything (native default)

Filtered modes use a stable sort (space A-Z, repo A-Z, name A-Z, layout)
based on per-pane tokens that publish_tokens() refreshes on every sync / mode apply. "all"
clears the view and keeps Herdr's native priority order.

State (which mode is "on") persists in $HERDR_PLUGIN_STATE_DIR/state.json so
the workspace.focused hook can re-assert it after space switches / restarts.
"""
import json
import os
import socket
import sys

SOURCE = "plugin:andpeicunha.agent-view-filters"
MODES = ["active", "space", "picked", "all"]

FILTERS = {
    "active": {
        "op": "in",
        "field": "status",
        "values": ["working", "blocked"],
    },
    "space": {
        "op": "eq",
        "field": "workspace_id",
        "value": {"context": "current_workspace_id"},
    },
}

# Stable order for the filtered modes: space, repo, name (all A-Z), then layout.
# "space"/"repo"/"name" are per-pane tokens written by publish_tokens().
SORT = [
    {"field": {"token": "space"}, "order": "asc"},
    {"field": {"token": "repo"}, "order": "asc"},
    {"field": {"token": "name"}, "order": "asc"},
    {"field": "pane_order", "order": "asc"},
]

TOKEN_TTL_MS = 86400000  # server max (24h); renewed on every sync
TOKEN_MAX_LEN = 128


def state_path():
    d = os.environ.get("HERDR_PLUGIN_STATE_DIR") or "."
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "state.json")


def read_state():
    try:
        with open(state_path()) as f:
            d = json.load(f)
            if isinstance(d, dict):
                return d
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return {}


def write_state(mode, excluded):
    path = state_path()
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump({"mode": mode, "excluded": sorted(set(excluded))}, f)
    os.replace(tmp, path)


def read_mode():
    m = read_state().get("mode")
    return m if m in MODES else "active"


def read_excluded():
    ex = read_state().get("excluded")
    if isinstance(ex, list):
        return [x for x in ex if isinstance(x, str)]
    return []


def write_mode(mode):
    write_state(mode, read_excluded())


def write_excluded(excluded):
    write_state(read_mode(), excluded)


def socket_path():
    p = os.environ.get("HERDR_SOCKET_PATH")
    if not p:
        sys.stderr.write("agent-view-filters: HERDR_SOCKET_PATH not set\n")
        sys.exit(1)
    return p


def send(req):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(5)
    s.connect(socket_path())
    s.sendall((json.dumps(req) + "\n").encode())
    buf = b""
    while b"\n" not in buf:
        chunk = s.recv(65536)
        if not chunk:
            break
        buf += chunk
    s.close()
    return buf.decode().strip()


def list_agents():
    try:
        d = json.loads(send({"id": "avf_list", "method": "agent.list", "params": {}}))
        return d["result"]["agents"]
    except (KeyError, ValueError, OSError, TypeError):
        return None


def list_workspaces():
    try:
        d = json.loads(send({"id": "avf_ws", "method": "workspace.list", "params": {}}))
        return {w["workspace_id"]: w.get("label", "") for w in d["result"]["workspaces"]}
    except (KeyError, ValueError, OSError, TypeError):
        return {}


def list_tabs():
    """tab_id -> TabInfo (label, pane_count, ...), or {} on failure."""
    try:
        d = json.loads(send({"id": "avf_tabs", "method": "tab.list", "params": {}}))
        return {t["tab_id"]: t for t in d["result"]["tabs"]}
    except (KeyError, ValueError, OSError, TypeError):
        return {}


def list_panes():
    """Every pane (not only agents), or [] on failure."""
    try:
        d = json.loads(send({"id": "avf_panes", "method": "pane.list", "params": {}}))
        return d["result"]["panes"]
    except (KeyError, ValueError, OSError, TypeError):
        return []


def _token_value(text):
    return (text or "").strip().lower()[:TOKEN_MAX_LEN]


def display_name(tab_label, pane_label, pane_title, n_panes):
    """Nome exibido: tab com 1 pane -> label da tab; com >1 -> "tab › pane".

    Pane sem label usa o título do terminal. Vazio se nada existir.
    """
    tab = (tab_label or "").strip()
    pane = (pane_label or "").strip() or (pane_title or "").strip()
    if n_panes > 1 and tab and pane:
        return f"{tab} › {pane}"
    return tab or pane


def name_context():
    """Lookups for agent_name(): (tabs, pane_by_id, n_panes_by_tab).

    Optional data: a listing failure just degrades to the terminal title.
    """
    tabs = list_tabs()
    panes = list_panes()
    pane_by_id = {p.get("pane_id"): p for p in panes}
    n_by_tab = {}
    for p in panes:
        t = p.get("tab_id")
        if t:
            n_by_tab[t] = n_by_tab.get(t, 0) + 1
    return tabs, pane_by_id, n_by_tab


def agent_name(a, ctx):
    """Tab/pane display name of an agent dict (same rule as the picker)."""
    tabs, pane_by_id, n_by_tab = ctx
    tab_id = a.get("tab_id") or ""
    tab = tabs.get(tab_id, {})
    n_panes = n_by_tab.get(tab_id) or tab.get("pane_count") or 0
    title = a.get("terminal_title_stripped") or a.get("terminal_title") or ""
    return display_name(
        tab.get("label"),
        pane_by_id.get(a.get("pane_id"), {}).get("label"),
        title,
        n_panes,
    )


def publish_tokens(agents=None):
    """Write `space`, `repo` and `name` tokens on every agent pane (for SORT).

    The old `title` token is cleared (null) so a stale one never lingers.
    Best effort: a failing/dead pane is skipped, never raised. Returns the
    number of panes written.
    """
    if agents is None:
        agents = list_agents()
    if not agents:
        return 0
    ws = list_workspaces()
    ctx = name_context()
    n = 0
    for a in agents:
        pane_id = a.get("pane_id")
        if not pane_id:
            continue
        cwd = (a.get("foreground_cwd") or a.get("cwd") or "").rstrip("/")
        repo = os.path.basename(cwd)
        space = ws.get(a.get("workspace_id")) or repo
        tokens = {
            "space": _token_value(space),
            "repo": _token_value(repo),
            "name": _token_value(agent_name(a, ctx)),
            "title": None,
        }
        try:
            resp = json.loads(send({
                "id": "avf_tok",
                "method": "pane.report_metadata",
                "params": {
                    "pane_id": pane_id,
                    "source": SOURCE,
                    "tokens": tokens,
                    "ttl_ms": TOKEN_TTL_MS,
                },
            }))
            if "error" not in resp:
                n += 1
        except (ValueError, OSError):
            continue
    return n


def prune_excluded():
    """Drop excluded pane_ids that no longer exist. Skips on listing failure."""
    ex = read_excluded()
    if not ex:
        return ex
    agents = list_agents()
    if agents is None:
        return ex
    live = {a.get("pane_id") for a in agents}
    kept = [p for p in ex if p in live]
    if len(kept) != len(ex):
        write_excluded(kept)
    return kept


def apply_mode(mode, excluded=None):
    if mode == "picked":
        if excluded is None:
            excluded = read_excluded()
        if not excluded:
            mode = "all"
        else:
            flt = {"op": "not", "filter": {"op": "in", "field": "pane_id", "values": list(excluded)}}
    if mode != "all":
        publish_tokens()
    if mode == "all":
        resp = send({"id": "avf_clear", "method": "agent.view.clear", "params": {"source": SOURCE}})
    else:
        if mode != "picked":
            flt = FILTERS[mode]
        resp = send({
            "id": "avf_set",
            "method": "agent.view.set",
            "params": {
                "source": SOURCE,
                "label": mode,
                "filter": flt,
                "sort": SORT,
            },
        })
    return resp


def main():
    action = sys.argv[1] if len(sys.argv) > 1 else "cycle"

    if action == "sync":
        mode = read_mode()
        excluded = prune_excluded()
        apply_mode(mode, excluded)
        print(f"agent-view-filters: synced -> {mode}")
        return

    if action == "cycle":
        current = read_mode()
        mode = MODES[(MODES.index(current) + 1) % len(MODES)]
    elif action in MODES:
        mode = action
    else:
        sys.stderr.write(f"agent-view-filters: unknown action '{action}'\n")
        sys.exit(2)

    excluded = prune_excluded() if mode == "picked" else None
    apply_mode(mode, excluded)
    write_mode(mode)
    print(f"agent-view-filters: mode -> {mode}")


if __name__ == "__main__":
    main()
