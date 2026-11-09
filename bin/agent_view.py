#!/usr/bin/env python3
"""agent-view-filters: cycle the Herdr Agents sidebar between four modes.

Modes:
  active - only agents currently working or blocked
  space  - only agents in the focused space (workspace)
  picked - every agent except those the user excluded in the picker popup
  all    - clear the view, show everything (native default)

Filtered modes use a stable sort (native workspace_order = sidebar space order,
repo A-Z, name A-Z, layout), based on per-pane tokens that publish_tokens()
refreshes on every sync / mode apply. Only `picked` honors the manual order
saved by the picker: agent order inside each space and, for this view only, the
order of the spaces themselves (the real sidebar is untouched). Spaces missing
from the saved space order go last; unknown saved spaces are ignored. "all" clears the view and keeps Herdr's native priority order.

State (which mode is "on") persists in $HERDR_PLUGIN_STATE_DIR/state.json so
the workspace.focused hook can re-assert it after space switches / restarts.
"""
import json
import os
import socket
import sys

try:
    import tomllib
except ImportError:  # python < 3.11
    tomllib = None

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

# Stable order for the filtered modes: space order (native, follows manual
# reordering in the sidebar), repo, name (A-Z), then layout.
# "repo"/"name" are per-pane tokens written by publish_tokens().
SORT = [
    {"field": "workspace_order", "order": "asc"},
    {"field": {"token": "repo"}, "order": "asc"},
    {"field": {"token": "name"}, "order": "asc"},
    {"field": "pane_order", "order": "asc"},
]

# Manual order (picker, `picked` mode only): `space` token is the zero-padded
# rank of the pane's space (saved space order, else live sidebar order) and
# `order` the position of the pane INSIDE its space, both published by
# publish_tokens(). repo/name break ties for panes without a manual position.
SORT_MANUAL = [
    {"field": {"token": "space"}, "order": "asc"},
    {"field": {"token": "order"}, "order": "asc"},
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


def write_state(mode, excluded, order=None, space_order=None, seen=None):
    """Atomic write. order/space_order/seen=None keep the stored value; [] clears it."""
    st = read_state()
    if seen is None:
        seen = st.get("seen")
    if order is None:
        order = read_order()
    if space_order is None:
        space_order = read_space_order()
    path = state_path()
    tmp = path + ".tmp"
    data = {"mode": mode, "excluded": sorted(set(excluded)),
            "order": list(order), "space_order": list(space_order)}
    if isinstance(seen, list):  # absent key = "never initialised" (see apply_new_policy)
        data["seen"] = sorted(set(x for x in seen if isinstance(x, str)))
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.replace(tmp, path)


def read_mode():
    m = read_state().get("mode")
    return m if m in MODES else "active"


def read_excluded():
    ex = read_state().get("excluded")
    if isinstance(ex, list):
        return [x for x in ex if isinstance(x, str)]
    return []


def read_order():
    """Manual order: list of pane_ids ([] = follow space order). Old state -> []."""
    return _str_list(read_state().get("order"))


def read_space_order():
    """Manual space order (picked view): list of workspace_ids. Old state -> []."""
    return _str_list(read_state().get("space_order"))


NEW_POLICIES = ("exclude", "include")


def config_path():
    d = os.environ.get("HERDR_PLUGIN_CONFIG_DIR") or os.path.expanduser(
        "~/.config/herdr/plugins/config/andpeicunha.agent-view-filters")
    return os.path.join(d, "config.toml")


def read_picked_new():
    """Config `picked_new`: "exclude" (default) | "include". Invalid/missing -> exclude."""
    if tomllib is None:
        return "exclude"
    try:
        with open(config_path(), "rb") as f:
            v = tomllib.load(f).get("picked_new")
    except (OSError, ValueError):
        return "exclude"
    return v if v in NEW_POLICIES else "exclude"


def apply_new_policy(live, seen, excluded, policy):
    """Pure. Returns (seen, excluded) after handling never-seen agents.

    seen=None means state predates this feature: mark all live as seen WITHOUT
    excluding (keeps today's view). Otherwise, with policy "exclude", live ids
    not in seen join excluded. Both lists are pruned to live ids.
    """
    live = set(live)
    kept_ex = [p for p in excluded if p in live]
    if seen is None:
        return sorted(live), kept_ex
    new = live - set(seen)
    if policy == "exclude":
        kept_ex = sorted(set(kept_ex) | new)
    return sorted(live), kept_ex


def sync_new_agents():
    """Persist apply_new_policy over the live agents. Skips on listing failure."""
    agents = list_agents()
    if agents is None:
        return
    st = read_state()
    seen = st.get("seen")
    seen = _str_list(seen) if isinstance(seen, list) else None
    live = [a.get("pane_id") for a in agents if isinstance(a.get("pane_id"), str)]
    ex = read_excluded()
    new_seen, new_ex = apply_new_policy(live, seen, ex, read_picked_new())
    if new_seen != sorted(set(seen or [])) or seen is None or sorted(set(new_ex)) != sorted(set(ex)):
        write_state(read_mode(), new_ex, seen=new_seen)


def _str_list(od):
    if isinstance(od, list):
        seen = set()
        out = []
        for x in od:
            if isinstance(x, str) and x not in seen:
                seen.add(x)
                out.append(x)
        return out
    return []


def space_sequence(panes, order, space_order=None, space_ids=None):
    """Pure. panes: iterable of (pane_id, space_key, repo, name).

    Spaces ascending by space_key (live sidebar order), unless `space_order`
    (list of space ids; space_ids maps space_key -> id, default key itself)
    is given: listed spaces first in that order, unlisted ones after them by
    space_key, unknown listed ids ignored. Inside each space: ids
    present in `order` first (in that relative order), then the rest (new
    panes) by (repo, name, pane_id). Ids in `order` that are not live are
    ignored. Returns the full list of pane_ids.
    """
    pos = {}
    for p in order:
        if p not in pos:
            pos[p] = len(pos)
    spaces = {}
    for pid, key, repo, name in panes:
        spaces.setdefault(key, []).append((pid, (repo or "").lower(), (name or "").lower()))
    seq = []
    sid = space_ids or {}
    rank = {}
    for x in space_order or []:
        if x not in rank:
            rank[x] = len(rank)

    def skey(k):
        r = rank.get(sid.get(k, k))
        return (0, r, 0) if r is not None else (1, 0, k)

    for key in sorted(spaces, key=skey):
        members = spaces[key]
        manual = sorted((m for m in members if m[0] in pos), key=lambda m: pos[m[0]])
        rest = sorted((m for m in members if m[0] not in pos),
                      key=lambda m: (m[1], m[2], m[0]))
        seq += [m[0] for m in manual + rest]
    return seq


def order_indices(seq, space_of):
    """Pure. pane_id -> index inside its own space, following `seq`."""
    counters = {}
    out = {}
    for pid in seq:
        k = space_of(pid)
        out[pid] = counters.get(k, 0)
        counters[k] = out[pid] + 1
    return out


def move_in_space(items, idx, delta, space_of):
    """Pure. Move items[idx] by delta (+/-1) but only inside its own space.

    items: list of pane_ids (or any key); space_of(item) -> space key.
    -> (new_list, new_idx, moved). At a space boundary / out of range:
    unchanged, moved=False.
    """
    j = idx + delta
    if not (0 <= idx < len(items)) or not (0 <= j < len(items)):
        return list(items), idx, False
    if space_of(items[idx]) != space_of(items[j]):
        return list(items), idx, False
    out = list(items)
    out[idx], out[j] = out[j], out[idx]
    return out, j, True


def move_unit(items, idx, delta, space_of):
    """Pure. Move items[idx] by delta (+/-1).

    Inside its space: swap with the neighbour. At the space edge: the whole
    space block (contiguous run, internal order kept) jumps over the
    neighbouring space block. items is a list of keys grouped by space.
    -> (new_list, new_idx, kind); kind is "item", "space" or "edge"
    (nothing moved: absolute top/bottom or bad idx). new_idx follows the item.
    """
    n = len(items)
    if delta not in (-1, 1) or not 0 <= idx < n:
        return list(items), idx, "edge"
    j = idx + delta
    if not 0 <= j < n:
        return list(items), idx, "edge"
    if space_of(items[idx]) == space_of(items[j]):
        out = list(items)
        out[idx], out[j] = out[j], out[idx]
        return out, j, "item"
    key = space_of(items[idx])
    s = idx
    while s > 0 and space_of(items[s - 1]) == key:
        s -= 1
    e = idx
    while e + 1 < n and space_of(items[e + 1]) == key:
        e += 1
    nkey = space_of(items[j])
    if delta < 0:
        ns = j
        while ns > 0 and space_of(items[ns - 1]) == nkey:
            ns -= 1
        out = items[:ns] + items[s:e + 1] + items[ns:s] + items[e + 1:]
        return out, idx - (s - ns), "space"
    ne = j
    while ne + 1 < n and space_of(items[ne + 1]) == nkey:
        ne += 1
    out = items[:s] + items[e + 1:ne + 1] + items[s:e + 1] + items[ne + 1:]
    return out, idx + (ne - e), "space"


def write_mode(mode):
    write_state(mode, read_excluded())


def write_excluded(excluded):
    write_state(read_mode(), excluded)


def write_order(order):
    write_state(read_mode(), read_excluded(), list(order))


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


def workspace_index():
    """workspace_id -> position in the sidebar (0-based), or {} on failure.

    workspace.list comes in sidebar order; `number` (1-based) is that position.
    """
    try:
        d = json.loads(send({"id": "avf_wsi", "method": "workspace.list", "params": {}}))
        out = {}
        for i, w in enumerate(d["result"]["workspaces"]):
            n = w.get("number")
            out[w["workspace_id"]] = (n - 1) if isinstance(n, int) else i
        return out
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


def publish_tokens(agents=None, with_order=False):
    """Write `repo`, `name` and `order` tokens on every agent pane (for SORT).

    `order` (only with_order=True and a saved manual order) is the 4-digit
    position of the pane inside its space (saved panes first, new panes after
    them in default rank); otherwise null (cleared).

    `space` is the 4-digit rank of the pane's space (saved space order first).
    The old `title` token is cleared (null) so stale ones never linger.
    Best effort: a failing/dead pane is skipped, never raised. Returns the
    number of panes written.
    """
    if agents is None:
        agents = list_agents()
    if not agents:
        return 0
    ctx = name_context()
    manual = read_order() if with_order else []
    sorder = read_space_order() if with_order else []
    order_idx = {}
    space_rank = {}
    if manual or sorder:
        ws_idx = workspace_index()
        space = {}
        space_ids = {}
        panes = []
        for a in agents:
            pid = a.get("pane_id")
            if not pid:
                continue
            cwd = (a.get("foreground_cwd") or a.get("cwd") or "").rstrip("/")
            key = ws_idx.get(a.get("workspace_id"), len(ws_idx))
            space[pid] = key
            space_ids[key] = a.get("workspace_id")
            panes.append((pid, key, os.path.basename(cwd), agent_name(a, ctx)))
        seq = space_sequence(panes, manual, sorder, space_ids)
        order_idx = order_indices(seq, space.__getitem__)
        for pid in seq:
            space_rank.setdefault(space[pid], len(space_rank))
        space_rank = {pid: space_rank[space[pid]] for pid in seq}
    n = 0
    for a in agents:
        pane_id = a.get("pane_id")
        if not pane_id:
            continue
        cwd = (a.get("foreground_cwd") or a.get("cwd") or "").rstrip("/")
        repo = os.path.basename(cwd)
        tokens = {
            "space": f"{space_rank[pane_id]:04d}" if pane_id in space_rank else None,
            "repo": _token_value(repo),
            "name": _token_value(agent_name(a, ctx)),
            "order": f"{order_idx[pane_id]:04d}" if pane_id in order_idx else None,
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


def prune_order():
    """Drop `order` pane_ids that no longer exist. Skips on listing failure.

    New agents are NOT persisted: they sit at the end (via tokens) until the
    user saves the picker again.
    """
    od = read_order()
    if not od:
        return od
    agents = list_agents()
    if agents is None:
        return od
    live = {a.get("pane_id") for a in agents}
    kept = [p for p in od if p in live]
    if len(kept) != len(od):
        write_order(kept)
    return kept


def apply_mode(mode, excluded=None):
    manual = mode == "picked" and bool(read_order() or read_space_order())
    if mode == "picked":
        if excluded is None:
            excluded = read_excluded()
        if not excluded and manual:
            # Keep a (match-everything) view so the manual sort still applies.
            flt = {"op": "not", "filter": {"op": "in", "field": "pane_id",
                                           "values": ["__none__"]}}
        elif not excluded:
            mode = "all"
        else:
            flt = {"op": "not", "filter": {"op": "in", "field": "pane_id", "values": list(excluded)}}
    if mode != "all":
        publish_tokens(with_order=manual)
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
                "sort": SORT_MANUAL if manual else SORT,
            },
        })
    return resp


def main():
    action = sys.argv[1] if len(sys.argv) > 1 else "cycle"

    if action == "sync":
        mode = read_mode()
        sync_new_agents()
        excluded = prune_excluded()
        prune_order()
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
    prune_order()
    apply_mode(mode, excluded)
    write_mode(mode)
    print(f"agent-view-filters: mode -> {mode}")


if __name__ == "__main__":
    main()
