"""agent-view-filters: cycle the Herdr Agents sidebar between four modes.

Modes:
  active - only agents currently working or blocked
  space  - only agents in the focused space (workspace)
  picked - every agent except spaces / tab groups / root panes the user excluded
  all    - clear the view, show everything (native default)

Filtered modes use ONE stable sort over per-pane tokens (`space_rank`, `order`)
that publish_tokens() refreshes on every sync / mode apply. The sequence is
always: space order (native sidebar workspace order) -> tab order -> root agent
-> its children (layout order). There is no manual ordering. "all" clears the
view and keeps Herdr's native priority order.

Tree marks (the "├ " / "└ " prefixes in `$title`, the `$sub` row) are published
only in `picked` mode. active / space / all publish flat rows: title = tab
(display label when the tab label is empty/numeric), space = workspace, sub
absent.

Grouping: a pane with a live `parent` token is a child of that parent (flattened
to the root; the parent may live in another tab/space). Otherwise, with config
`group_by_tab` (default true), the agent panes of one tab are grouped: the root
is the sticky tab root, the others are its children. An explicit parent token
always wins; a pane alone in its tab is standalone.

pane.list order is NOT a stable layout order (it can follow focus/MRU), so the
plugin never derives root or order from it after first sight. State keeps
`first_seen` (pane_id -> monotonic counter, orders panes inside a tab and the
children of a group) and `tab_roots` (tab_id -> sticky tab-fallback root).
Tab order = tab.list order and space order = workspace `number`; both verified
focus-independent.

Liveness: a pane is dead only when it is absent from pane.list. Per-pane state
(first_seen, tab_roots, parents, seen, excluded) is pruned only for dead panes;
a pane that merely stopped being an agent (agent.list) keeps its state and just
leaves the tree meanwhile. Pruning is skipped when pane.list is empty/failed.

Exclusion (picked): `excluded` holds "space:<workspace_id>" entries,
"tab:<tab_id>" entries (tab-fallback groups: stable when the root pane changes)
and root pane ids (explicit-parent groups / standalone). Hidden = space excluded
OR tab excluded OR root excluded; children follow their root.

State ($HERDR_PLUGIN_STATE_DIR/state.json): `mode`, `excluded`, `seen`,
`first_seen`, `tab_roots`, `parents`, `published_at` (epoch of the last full
token publish). Unknown / old keys (`order`, `space_order`) are dropped; all but
`mode` / `excluded` are optional.
"""
import contextlib
import copy
import fcntl
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time

try:
    import tomllib
except ImportError:  # python < 3.11
    tomllib = None

SOURCE = "plugin:andpeicunha.agent-view-filters"
MODES = ["active", "space", "picked", "all"]
SPACE_PREFIX = "space:"

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

# Single stable order: `space_rank` = 4-digit rank of the pane's space (native
# sidebar order), `order` = 4-digit position inside the space (tab order, root,
# its children in layout order). Both are published by publish_tokens().
SORT = [
    {"field": {"token": "space_rank"}, "order": "asc"},
    {"field": {"token": "order"}, "order": "asc"},
    {"field": "pane_order", "order": "asc"},
]

TOKEN_TTL_MS = 86400000  # server max (24h); renewed on every sync
TOKEN_MAX_LEN = 128
CHILD_PREFIX = "\u2514 "  # "└ " (last child)
MID_PREFIX = "\u251c "  # "├ " (root with children / non-last child)
TAB_PREFIX = "tab:"
FIRST_SEEN_BASE = 10 ** 9  # rank of panes without a stored first_seen
STATE_SUBDIR = "~/.local/state/herdr/plugins/andpeicunha.agent-view-filters"


def state_dir():
    d = os.environ.get("HERDR_PLUGIN_STATE_DIR") or os.path.expanduser(STATE_SUBDIR)
    os.makedirs(d, exist_ok=True)
    return d


def state_path():
    return os.path.join(state_dir(), "state.json")


_lock_depth = 0
_state_cache = None   # state.json / config.toml parsed once per locked invocation
_config_cache = None
CLOSED_COORD_MAX = 20       # closed_coordinators kept in state
COORD_REFRESH_S = 3600      # rewrite a coordinator's last_seen at most this often
ROLE_COORDINATOR = "coordinator"
TOKEN_REFRESH_S = 6 * 3600  # force a token republish this often (TTL is 24h)


@contextlib.contextmanager
def state_lock():
    """Exclusive flock on <state dir>/state.lock around a whole read-modify-write
    cycle of state.json. Reentrant inside one process (only the outermost call
    takes the flock), so sync / apply_mode / picker can nest freely. While held,
    state.json and config.toml are read from disk once (see read_state)."""
    global _lock_depth, _state_cache, _config_cache
    if _lock_depth:
        _lock_depth += 1
        try:
            yield
        finally:
            _lock_depth -= 1
        return
    with open(os.path.join(state_dir(), "state.lock"), "a+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        _lock_depth = 1
        _state_cache = _config_cache = None
        try:
            yield
        finally:
            _lock_depth = 0
            _state_cache = _config_cache = None
            fcntl.flock(f, fcntl.LOCK_UN)


def read_state():
    """state.json as a dict ({} when missing/unreadable/invalid). Cached (as a
    private copy) while state_lock is held; _write_state keeps the cache fresh."""
    global _state_cache
    if _lock_depth and _state_cache is not None:
        return copy.deepcopy(_state_cache)
    d = {}
    try:
        with open(state_path(), encoding="utf-8") as f:
            v = json.load(f)
        if isinstance(v, dict):
            d = v
    except (OSError, ValueError):  # missing, permission, bad JSON / UTF-8
        pass
    if _lock_depth:
        _state_cache = copy.deepcopy(d)
    return d


def write_state(mode, excluded, seen=None, first_seen=None, tab_roots=None,
                parents=None, published_at=None, coordinators=None,
                closed_coordinators=None):
    """Atomic write under state_lock. seen/first_seen/tab_roots/parents/
    published_at/coordinators/closed_coordinators=None keep the stored value
    ({} / [] clear the last two). Old keys (order...) are dropped."""
    with state_lock():
        _write_state(mode, excluded, seen, first_seen, tab_roots, parents,
                     published_at, coordinators, closed_coordinators)


def _write_state(mode, excluded, seen, first_seen, tab_roots, parents,
                 published_at=None, coordinators=None, closed_coordinators=None):
    global _state_cache
    st = read_state()
    if seen is None:
        seen = st.get("seen")
    if first_seen is None:
        first_seen = read_first_seen(st)
    if tab_roots is None:
        tab_roots = read_tab_roots(st)
    if parents is None:
        parents = read_parents(st)
    if published_at is None:
        published_at = read_published_at(st)
    if coordinators is None:
        coordinators = read_coordinators(st)
    if closed_coordinators is None:
        closed_coordinators = read_closed_coordinators(st)
    path = state_path()
    data = {"mode": mode, "excluded": sorted(set(excluded))}
    if isinstance(seen, list):  # absent key = "never initialised" (see apply_new_policy)
        data["seen"] = sorted(set(x for x in seen if isinstance(x, str)))
    if first_seen:
        data["first_seen"] = first_seen
    if tab_roots:
        data["tab_roots"] = tab_roots
    if parents:
        data["parents"] = parents
    if published_at:
        data["published_at"] = published_at
    if coordinators:
        data["coordinators"] = coordinators
    if closed_coordinators:
        data["closed_coordinators"] = closed_coordinators
    fd, tmp = tempfile.mkstemp(dir=state_dir(), prefix="state.json.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
    if _lock_depth:
        _state_cache = copy.deepcopy(data)


def read_published_at(st=None):
    """Epoch of the last full token publish; invalid/missing -> 0."""
    v = (read_state() if st is None else st).get("published_at")
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0.0


def read_first_seen(st=None):
    """Stored `first_seen` (pane_id -> int); invalid/missing -> {}."""
    d = (read_state() if st is None else st).get("first_seen")
    if not isinstance(d, dict):
        return {}
    return {k: v for k, v in d.items()
            if isinstance(k, str) and isinstance(v, int) and not isinstance(v, bool)}


def read_tab_roots(st=None):
    """Stored `tab_roots` (tab_id -> pane_id); invalid/missing -> {}."""
    d = (read_state() if st is None else st).get("tab_roots")
    if not isinstance(d, dict):
        return {}
    return {k: v for k, v in d.items() if isinstance(k, str) and isinstance(v, str)}


def read_parents(st=None):
    """Stored `parents` (child pane_id -> parent pane_id); invalid/missing -> {}."""
    d = (read_state() if st is None else st).get("parents")
    if not isinstance(d, dict):
        return {}
    return {k: v for k, v in d.items() if isinstance(k, str) and isinstance(v, str)}


def read_coordinators(st=None):
    """Stored `coordinators` (pane_id -> info dict); invalid/missing -> {}."""
    d = (read_state() if st is None else st).get("coordinators")
    if not isinstance(d, dict):
        return {}
    return {k: v for k, v in d.items() if isinstance(k, str) and isinstance(v, dict)}


def read_closed_coordinators(st=None):
    """Stored `closed_coordinators` (newest last); invalid/missing -> []."""
    d = (read_state() if st is None else st).get("closed_coordinators")
    if not isinstance(d, list):
        return []
    return [v for v in d if isinstance(v, dict)][-CLOSED_COORD_MAX:]


def read_mode():
    m = read_state().get("mode")
    return m if m in MODES else "active"


def read_excluded():
    ex = read_state().get("excluded")
    if isinstance(ex, list):
        return [x for x in ex if isinstance(x, str)]
    return []


def space_entry(workspace_id):
    """`excluded` entry of a whole space."""
    return SPACE_PREFIX + (workspace_id or "")


def tab_entry(tab_id):
    """`excluded` entry of a tab-fallback group."""
    return TAB_PREFIX + (tab_id or "")


NEW_POLICIES = ("exclude", "include")


def config_path():
    d = os.environ.get("HERDR_PLUGIN_CONFIG_DIR") or os.path.expanduser(
        "~/.config/herdr/plugins/config/andpeicunha.agent-view-filters")
    return os.path.join(d, "config.toml")


def read_config():
    """Plugin config.toml as a dict ({} when missing/invalid or no tomllib)."""
    global _config_cache
    if tomllib is None:
        return {}
    if _lock_depth and _config_cache is not None:
        return _config_cache
    try:
        with open(config_path(), "rb") as f:
            d = tomllib.load(f)
    except (OSError, ValueError):
        d = {}
    d = d if isinstance(d, dict) else {}
    if _lock_depth:
        _config_cache = d
    return d


def read_picked_new():
    """Config `picked_new`: "include" (default) | "exclude". Invalid/missing -> include."""
    v = read_config().get("picked_new")
    return v if v in NEW_POLICIES else "include"


def read_group_by_tab():
    """Config `group_by_tab` (bool, default true). Invalid/missing -> true."""
    v = read_config().get("group_by_tab")
    return v if isinstance(v, bool) else True


def apply_new_policy(live, seen, excluded, policy, children=None, live_spaces=None,
                     tab_roots=None, live_tabs=None, alive=None):
    """Pure. Returns (seen, excluded) after handling never-seen agents.

    live: agent pane ids (tree participants); alive: pane ids that still exist
    (pane.list; default = live). Only dead ids are pruned from seen/excluded, so
    a pane that merely stopped being an agent keeps its entries.
    seen=None means state predates this feature: mark all live as seen WITHOUT
    excluding (keeps today's view). Otherwise, with policy "exclude", live ids
    not in seen join excluded.
    `children` (set of pane ids, or child -> root dict) are never auto-excluded
    and an excluded id that is (or became) a child is DROPPED, never migrated:
    children have no exclusion of their own and migrating would leak into
    another tab's group. `tab_roots` (root pane_id -> tab_id of tab-fallback
    groups, each in its own tab) migrates an excluded root pane id to
    "tab:<id>". "space:<id>" entries are kept (pruned to live_spaces when it is
    given), and so are "tab:<id>" entries (pruned to live_tabs).
    """
    tab_roots = tab_roots or {}
    live = set(live)
    alive = live if alive is None else set(alive) | live
    kids = set(children or ())

    def keep(p):
        if p.startswith(SPACE_PREFIX):
            return live_spaces is None or p[len(SPACE_PREFIX):] in live_spaces
        if p.startswith(TAB_PREFIX):
            return live_tabs is None or p[len(TAB_PREFIX):] in live_tabs
        return p in alive and p not in kids

    def migrate(items):
        return sorted({tab_entry(tab_roots[p]) if p in tab_roots else p for p in items})

    kept_ex = [p for p in excluded if keep(p)]
    kept_seen = live | (set(seen or ()) & alive)
    if seen is None:
        return sorted(live), migrate(kept_ex)
    new = live - set(seen) - kids
    if policy == "exclude":
        kept_ex = sorted(set(kept_ex) | new)
    return sorted(kept_seen), migrate(kept_ex)


def alive_ids(panes, agents=(), *stored):
    """Pure. Pane ids that still exist: pane.list + agent.list ids. When pane.list
    is empty/failed no pane may be declared dead, so every `stored` id (iterables
    of pane ids) counts as alive."""
    ids = {p.get("pane_id") for p in panes or [] if p.get("pane_id")}
    ids |= {a.get("pane_id") for a in agents or [] if a.get("pane_id")}
    if not panes:
        for lst in stored:
            ids |= {x for x in lst if isinstance(x, str)}
    return ids


def sync_new_agents(snap=None):
    """Persist apply_new_policy over the live agents. Skips on listing failure."""
    with state_lock():
        _sync_new_agents(snap or take_snapshot())


def _sync_new_agents(snap):
    agents = snap["agents"]
    if agents is None:
        return
    st = read_state()
    seen = st.get("seen")
    seen = _str_list(seen) if isinstance(seen, list) else None
    live = [a.get("pane_id") for a in agents if isinstance(a.get("pane_id"), str)]
    ex = read_excluded()
    ws, panes, tabs = snap["ws"], snap["panes"], snap["tabs"]
    fs, roots = sync_layout(agents, panes, snap=snap)
    tree, _, fallback = tree_roots_fallback(
        agents, panes, snap["group_by_tab"], fs, roots, read_parents())
    new_seen, new_ex = apply_new_policy(
        live, seen, ex, snap["picked_new"], tree,
        set(ws) if ws else None, tab_fallback_roots(agents, panes, tree, fallback=fallback),
        set(tabs) if tabs else None, alive_ids(panes, agents, seen or (), ex))
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


def build_tree(live, parents):
    """Pure. child_pane_id -> ROOT parent pane_id, for grouped panes only.

    live: pane ids that may take part; parents: pane_id -> raw `parent` token.
    Ignored: non-string/empty parent, parent == self, parent not live, and
    cycles (every pane that reaches a cycle stays standalone). Chains
    (grandchildren) flatten to the root.
    """
    live = set(live)
    direct = {}
    for c, p in (parents or {}).items():
        if c in live and isinstance(p, str) and p and p != c and p in live:
            direct[c] = p
    out = {}
    for c in direct:
        seen = {c}
        cur = direct[c]
        ok = True
        while cur in direct:
            if cur in seen:
                ok = False
                break
            seen.add(cur)
            cur = direct[cur]
        if ok:
            out[c] = cur
    return out


def assign_first_seen(stored, live, alive=None):
    """Pure. Monotonic first-seen counters for `live` pane ids (iterated in
    order). Known ids keep their counter, new ones get max+1..; ids that are not
    in `alive` (default: `live`) are pruned, so a pane that is merely not an
    agent right now keeps its counter when `alive` is given."""
    live = list(dict.fromkeys(live))
    keep = set(live) if alive is None else set(alive) | set(live)
    out = {p: n for p, n in (stored or {}).items() if p in keep}
    nxt = max(out.values(), default=0) + 1
    for p in live:
        if p not in out:
            out[p] = nxt
            nxt += 1
    return out


def seen_key(first_seen):
    """Sort key: oldest first_seen first; unknown ids last (stable: they keep
    the given order until sync_layout assigns them a counter)."""
    fs = first_seen or {}
    return lambda pid: fs.get(pid, float("inf"))


def tab_root_map(panes, skip=(), first_seen=None, stored_roots=None):
    """Pure. tab_id -> root pane_id of the tab fallback.

    panes: (pane_id, tab_id); candidates exclude `skip` and tab-less panes. The
    stored root is sticky while it is still a candidate of that tab; otherwise
    the oldest by first_seen (then pane_id) wins. Without first_seen the given
    order decides.
    """
    skip = set(skip)
    cands = {}
    for pid, tab in panes:
        if tab and pid not in skip:
            cands.setdefault(tab, []).append(pid)
    out = {}
    for tab, lst in cands.items():
        if first_seen:
            lst = sorted(lst, key=seen_key(first_seen))
        stored = (stored_roots or {}).get(tab)
        out[tab] = stored if stored in lst else lst[0]
    return out


def tab_parents(panes, skip=(), first_seen=None, stored_roots=None):
    """Pure. Tab fallback: child -> root, per tab.

    panes: (pane_id, tab_id); the root of each tab is chosen by tab_root_map
    (sticky stored root, else oldest first_seen, else first in given order), the
    rest are its children. Panes in `skip` (already grouped by a parent token)
    and panes without a tab are left out. A pane alone stays standalone.
    """
    skip = set(skip)
    roots = tab_root_map(panes, skip, first_seen, stored_roots)
    return {pid: roots[tab] for pid, tab in panes
            if tab and pid not in skip and roots[tab] != pid}


def effective_excluded(excluded, tree, space_of=None, tab_of=None):
    """Pure. Pane ids hidden by `excluded` (sorted).

    A root is hidden when its id is excluded, its space ("space:<id>", see
    space_of: pane_id -> workspace_id) is excluded, or its tab ("tab:<id>", see
    tab_of: pane_id -> tab_id) is excluded: a tab entry hides EVERY agent pane
    of the tab, group or lone pane. Children follow their root and have no
    exclusion of their own (a legacy child id in `excluded` is ignored).
    """
    ex = set(excluded)
    tree = tree or {}
    space_of = space_of or {}
    tab_of = tab_of or {}
    panes = set(space_of) | set(tree) | {
        p for p in ex if not p.startswith((SPACE_PREFIX, TAB_PREFIX))}
    hidden = set()
    for p in panes:
        root = tree.get(p, p)
        sp = space_of.get(root)
        tb = tab_of.get(root)
        tab_hit = tb is not None and tab_entry(tb) in ex
        if root in ex or tab_hit or (sp is not None and space_entry(sp) in ex):
            hidden.add(p)
    return sorted(hidden)


def clean_label(text):
    """Strip leading emoji/symbols/whitespace (non-alphanumeric) from a label."""
    return re.sub(r"^[\W_]+", "", text or "")


def group_marks(seq, tree):
    """Pure. -> (marks, parents): marks = child pane_id -> "├ " / "└ " (last child
    of its root in `seq` order); parents = roots that have children in `seq`."""
    kids = {}
    for pid in seq:
        if pid in (tree or {}):
            kids.setdefault(tree[pid], []).append(pid)
    marks = {}
    for lst in kids.values():
        for c in lst:
            marks[c] = MID_PREFIX
        marks[lst[-1]] = CHILD_PREFIX
    return marks, set(kids)


def row_tokens(title, space, sub):
    """Pure. Layout D display tokens, truncated; None/empty -> None (absent).
    `group`, `group_space` and `item` are legacy tokens, always cleared."""
    out = {k: ((v or "")[:TOKEN_MAX_LEN] or None)
           for k, v in (("title", title), ("space", space), ("sub", sub))}
    out.update(group=None, group_space=None, item=None)
    return out


def space_sequence(panes, parent_of=None):
    """Pure. panes: iterable of (pane_id, space_key, tab_key, layout_idx).

    Spaces ascending by space_key; inside a space the roots/standalone panes by
    (tab_key, layout_idx, pane_id), each immediately followed by its children
    (parent_of: child -> root, see build_tree) by layout_idx. Children live in
    their root's space; children whose root is not among `panes` stay standalone.
    Returns the full list of pane_ids.
    """
    panes = list(panes)
    present = {p[0] for p in panes}
    po = parent_of or {}
    kids = {c: r for c, r in po.items()
            if c in present and r in present and c != r and r not in po}
    kids_of = {}
    spaces = {}
    for pid, key, tab, lay in panes:
        if pid in kids:
            kids_of.setdefault(kids[pid], []).append((lay, pid))
        else:
            spaces.setdefault(key, []).append((tab, lay, pid))
    seq = []
    for key in sorted(spaces):
        for _, _, pid in sorted(spaces[key]):
            seq.append(pid)
            seq += [c for _, c in sorted(kids_of.get(pid, []))]
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


def write_mode(mode):
    with state_lock():
        write_state(mode, read_excluded())


def write_excluded(excluded):
    with state_lock():
        write_state(read_mode(), excluded)


def socket_path():
    p = os.environ.get("HERDR_SOCKET_PATH")
    if not p:
        sys.stderr.write("agent-view-filters: HERDR_SOCKET_PATH not set\n")
        sys.exit(1)
    return p


def send(req, timeout=5):
    path = socket_path()  # may exit: resolve before any fd exists
    with contextlib.closing(socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)) as s:
        s.settimeout(timeout)
        s.connect(path)
        s.sendall((json.dumps(req) + "\n").encode())
        buf = b""
        while b"\n" not in buf:
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
    return buf.decode().strip()


def list_agents():
    try:
        d = json.loads(send({"id": "avf_list", "method": "agent.list", "params": {}}))
        return d["result"]["agents"]
    except (KeyError, ValueError, OSError):
        return None


def _raw_workspaces():
    """workspace.list entries (sidebar order), or [] on failure."""
    try:
        d = json.loads(send({"id": "avf_ws", "method": "workspace.list", "params": {}}))
        return [w for w in d["result"]["workspaces"] if "workspace_id" in w]
    except (KeyError, ValueError, OSError):
        return []


def workspace_labels(raw):
    """Pure. workspace_id -> label from workspace.list entries."""
    return {w["workspace_id"]: w.get("label", "") for w in raw}


def workspace_positions(raw):
    """Pure. workspace_id -> position in the sidebar (0-based).

    workspace.list comes in sidebar order; `number` (1-based) is that position.
    """
    out = {}
    for i, w in enumerate(raw):
        n = w.get("number")
        out[w["workspace_id"]] = (n - 1) if isinstance(n, int) else i
    return out


def list_workspaces():
    return workspace_labels(_raw_workspaces())


def workspace_index():
    """workspace_id -> position in the sidebar (0-based), or {} on failure."""
    return workspace_positions(_raw_workspaces())


def list_tabs():
    """tab_id -> TabInfo (label, pane_count, ...), or {} on failure."""
    try:
        d = json.loads(send({"id": "avf_tabs", "method": "tab.list", "params": {}}))
        return {t["tab_id"]: t for t in d["result"]["tabs"]}
    except (KeyError, ValueError, OSError):
        return {}


def list_panes(timeout=5):
    """Every pane (not only agents), or [] on failure."""
    try:
        d = json.loads(send({"id": "avf_panes", "method": "pane.list", "params": {}},
                            timeout))
        return d["result"]["panes"]
    except (KeyError, ValueError, OSError):
        return []


def take_snapshot():
    """One fetch of agent.list / pane.list / tab.list / workspace.list plus the
    config values, shared by every step of one sync / mode apply.

    agents is None when agent.list failed (callers skip), panes [] on failure.
    """
    raw = _raw_workspaces()
    return {
        "agents": list_agents(),
        "panes": list_panes(),
        "tabs": list_tabs(),
        "ws": workspace_labels(raw),
        "ws_idx": workspace_positions(raw),
        "group_by_tab": read_group_by_tab(),
        "picked_new": read_picked_new(),
    }


def _explicit_parents(panes):
    parents = {}
    for p in panes or []:
        toks = p.get("tokens")
        if isinstance(toks, dict) and isinstance(toks.get("parent"), str):
            parents[p.get("pane_id")] = toks["parent"]
    return parents


def effective_parents(live, panes, stored=None):
    """Pure. child -> parent relations among `live` agent panes: stored ones
    (both ends alive, not self) overridden by valid explicit `parent` tokens.
    An explicit token whose parent is dead/self is ignored (stored survives)."""
    live = set(live)

    def ok(c, p):
        return c in live and isinstance(p, str) and p in live and p != c

    out = {c: p for c, p in (stored or {}).items() if ok(c, p)}
    out.update({c: p for c, p in _explicit_parents(panes).items() if ok(c, p)})
    return out


def tree_roots_fallback(agents, panes=None, group_by_tab=None, first_seen=None,
                        stored_roots=None, stored_parents=None):
    """-> (child -> root, tab_id -> tab root map, tab-fallback child -> root).

    Explicit `parent` tokens win (the parent may be in another tab/space); for
    agent panes without a live parent, panes of the same tab are grouped when
    `group_by_tab` (default: config, true). The tab root is sticky
    (`stored_roots`, default: state) else the oldest first_seen (default: state;
    pane.list order only for unseen panes). The roots and fallback maps are {}
    when group_by_tab is off. Parent relations come from live tokens, else from
    the stored `parents` (default: state) while both panes are agents.
    The fallback map is the raw per-tab child -> root map BEFORE the final
    re-flatten (see tab_fallback_roots).
    """
    if panes is None:
        panes = list_panes()
    if group_by_tab is None:
        group_by_tab = read_group_by_tab()
    if first_seen is None:
        first_seen = read_first_seen()
    if stored_roots is None:
        stored_roots = read_tab_roots()
    if stored_parents is None:
        stored_parents = read_parents()
    live = [a.get("pane_id") for a in agents or [] if a.get("pane_id")]
    explicit = build_tree(live, effective_parents(live, panes, stored_parents))
    if not group_by_tab:
        return explicit, {}, {}
    tab_of = {a.get("pane_id"): a.get("tab_id") for a in agents or []}
    lay = [p.get("pane_id") for p in panes]
    seen = set(lay)
    order = [pid for pid in lay if pid in tab_of] + [pid for pid in live if pid not in seen]
    pairs = [(pid, tab_of.get(pid)) for pid in order]
    roots = tab_root_map(pairs, explicit, first_seen, stored_roots)
    fallback = tab_parents(pairs, skip=explicit, first_seen=first_seen,
                           stored_roots=stored_roots)
    # Re-flatten: an explicit root may itself be a tab child of another root.
    return build_tree(live, {**fallback, **explicit}), roots, fallback


def tree_and_roots(agents, panes=None, group_by_tab=None, first_seen=None,
                   stored_roots=None, stored_parents=None):
    """-> (child -> root, tab_id -> tab root map); see tree_roots_fallback."""
    return tree_roots_fallback(agents, panes, group_by_tab, first_seen,
                               stored_roots, stored_parents)[:2]


def current_tree(agents, panes=None, group_by_tab=None, first_seen=None,
                 stored_roots=None, stored_parents=None):
    """child -> root among live agent panes (see tree_roots_fallback)."""
    return tree_roots_fallback(agents, panes, group_by_tab, first_seen,
                               stored_roots, stored_parents)[0]


def sync_layout(agents, panes, group_by_tab=None, snap=None):
    """Persist `first_seen`, sticky `tab_roots` and `parents`, pruning only DEAD
    panes (absent from pane.list; a pane that is merely not an agent keeps its
    entries, and a stored tab root that is alive in its tab stays stored even
    while another agent is the effective root). New counters / roots are only
    assigned to agent panes.

    Skips when either listing failed/empty (never wipes state on a glitch).
    Returns (first_seen, tab_roots) as stored/effective.
    """
    with state_lock():
        if group_by_tab is None:
            group_by_tab = snap["group_by_tab"] if snap else read_group_by_tab()
        return _sync_layout(agents, panes, group_by_tab)


def _sync_layout(agents, panes, group_by_tab):
    st = read_state()
    fs, roots = read_first_seen(st), read_tab_roots(st)
    old_parents = read_parents(st)
    if not agents or not panes:
        return fs, roots
    live = [a.get("pane_id") for a in agents if a.get("pane_id")]
    lay = [p.get("pane_id") for p in panes]
    in_live = set(live)
    ordered = [pid for pid in lay if pid in in_live] + [pid for pid in live if pid not in set(lay)]
    alive = alive_ids(panes, agents)
    pane_tab = {p.get("pane_id"): p.get("tab_id") for p in panes}
    new_fs = assign_first_seen(fs, ordered, alive)
    tab_of = {a.get("pane_id"): a.get("tab_id") for a in agents}
    new_roots = roots
    new_parents = effective_parents(alive, panes, old_parents)
    if group_by_tab:
        explicit = build_tree(live, effective_parents(live, panes, old_parents))
        found = tab_root_map([(pid, tab_of.get(pid)) for pid in ordered], explicit,
                             new_fs, roots)
        new_roots = dict(found)
        for tab, root in roots.items():
            # sticky root: alive in its tab (not an agent right now) -> keep stored
            if pane_tab.get(root) == tab and root in alive and root not in explicit:
                new_roots[tab] = root
    if new_fs != fs or new_roots != roots or new_parents != old_parents:
        write_state(read_mode(), read_excluded(), first_seen=new_fs,
                    tab_roots=new_roots, parents=new_parents)
    return new_fs, new_roots


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


def name_context(snap=None):
    """Lookups for agent_name(): (tabs, pane_by_id, n_panes_by_tab).

    Optional data: a listing failure just degrades to the terminal title.
    Reuses the tabs/panes of `snap` when given.
    """
    tabs = snap["tabs"] if snap else list_tabs()
    panes = snap["panes"] if snap else list_panes()
    pane_by_id = {p.get("pane_id"): p for p in panes}
    n_by_tab = {}
    for p in panes:
        t = p.get("tab_id")
        if t:
            n_by_tab[t] = n_by_tab.get(t, 0) + 1
    return tabs, pane_by_id, n_by_tab


def agent_name(a, ctx):
    """Tab/pane display name of an agent dict."""
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


def repo_of(cwd):
    """cwd basename without leading dots ("" when none)."""
    return os.path.basename((cwd or "").rstrip("/")).lstrip(".").strip()


def is_auto_label(label, cwd):
    """Pure. True when a pane label is empty or Herdr's auto label: the cwd
    basename, or "<basename> #N" (dedupe suffix). Case-insensitive, leading
    emoji/symbols and dots stripped."""
    text = clean_label(label).strip()
    if not text:
        return True
    repo = repo_of(cwd)
    if not repo:
        return False
    text = text.casefold()
    repo = repo.casefold()
    return text == repo or re.fullmatch(re.escape(repo) + r" #\d+", text) is not None


def display_label(a, ctx):
    """Display name of an agent (child title / root sub row).

    Priority: manual pane label (cleaned; cwd basename or "<basename> #N" = auto),
    Herdr agent name, terminal title (cleaned), repo (cwd basename without
    leading dots), agent kind. Never empty while any source exists.
    """
    pane = ctx[1].get(a.get("pane_id"), {})
    cwd = (a.get("foreground_cwd") or a.get("cwd") or "").rstrip("/")
    repo = repo_of(cwd)
    manual = clean_label(pane.get("label")).strip()
    if is_auto_label(manual, cwd):
        manual = ""
    for cand in (manual, a.get("name"),
                 clean_label(a.get("terminal_title_stripped") or a.get("terminal_title")),
                 repo, a.get("agent")):
        cand = (cand or "").strip()
        if cand:
            return cand[:TOKEN_MAX_LEN]
    return ""


def row_texts(a, ctx, ws_labels, mark=None, has_children=False):
    """Pure-ish. Layout D texts (title, space, sub) of one agent.

    Herdr indents every row after the first of an agent, so a root with
    children carries its display label in the second row (`$sub`).
    child (mark "├ "/"└ "): title = mark + display label, rest None.
    root with children (has_children): title = tab label (empty/numeric ->
    display label), space = workspace label, sub = "├ " + display label.
    standalone / flat row (no mark, has_children False): title = tab label
    (same fallback), space = workspace label, sub None.
    """
    rl = display_label(a, ctx)
    if mark:
        return mark + rl, None, None
    tab = (ctx[0].get(a.get("tab_id"), {}).get("label") or "").strip()
    name = (rl if (not tab or tab.isdigit()) else tab) or agent_name(a, ctx)
    space = (ws_labels.get(a.get("workspace_id")) or "").strip()
    return name, space, (MID_PREFIX + rl) if (has_children and rl) else None


def tab_fallback_roots(agents, panes, tree, stored_parents=None, fallback=None):
    """root pane_id -> tab_id of tab-fallback groups: final roots of `tree` with at
    least one child that came from the tab fallback (same tab), even when the
    root also has explicit-parent children. `fallback` is the raw tab child ->
    root map of tree_roots_fallback (recomputed from state when omitted)."""
    tree = tree or {}
    if fallback is None:
        fallback = tree_roots_fallback(agents, panes, None, None, None,
                                       stored_parents)[2]
    tab_of = {a.get("pane_id"): a.get("tab_id") for a in agents or []}
    out = {}
    for c, r in fallback.items():
        # r must itself be a final root (not re-flattened under another group)
        if tree.get(c) == r and r not in tree and tab_of.get(r):
            out[r] = tab_of[r]
    return out


def layout_sequence(agents, panes, tabs, ws_idx, tree, first_seen=None):
    """Display sequence of agent pane ids and their space key.

    -> (seq, space_key): seq follows space order (ws_idx) -> tab order (tabs
    insertion order = tab.list) -> root -> children (first_seen order; pane.list
    order only as a fallback for panes without a stored first_seen);
    space_key: pane_id -> (sidebar index, workspace_id), children use their
    root's. Shared by the sidebar tokens and the picker.
    """
    layout = {p.get("pane_id"): i for i, p in enumerate(panes)}
    if first_seen is None:
        first_seen = read_first_seen()
    tab_rank = {t: i for i, t in enumerate(tabs)}
    items = []
    for i, a in enumerate(agents):
        pid = a.get("pane_id")
        if not pid:
            continue
        wid = a.get("workspace_id") or ""
        items.append((pid, (ws_idx.get(wid, len(ws_idx)), wid),
                      tab_rank.get(a.get("tab_id"), len(tab_rank)),
                      first_seen[pid] if pid in first_seen
                      else FIRST_SEEN_BASE + layout.get(pid, len(layout) + i)))
    seq = space_sequence(items, tree)
    space_key = {p[0]: p[1] for p in items}
    for c, r in (tree or {}).items():
        if c in space_key and r in space_key:
            space_key[c] = space_key[r]
    return seq, space_key


def publish_tokens(agents=None, tree=None, snap=None, mode="picked"):
    """Write sort + display tokens on every agent pane (layout D).

    Sort: `space_rank` = 4-digit rank of the pane's space (sidebar order),
    `order` = 4-digit position inside its space (see layout_sequence).
    Display (`$title`/`$space` first row, `$sub` second row, see row_texts):
    in `picked` mode the tree marks are published: root with children -> title =
    tab label (empty/numeric -> display label), space = workspace label, sub =
    "├ label"; child -> title = "├ label" / "└ label" (last child); standalone ->
    title = tab label, space = workspace label. In every other mode the rows are
    flat (title = tab, space = workspace, sub absent). The old `tree_ws`,
    `group`, `group_space`, `item`, `repo` and `name` tokens are cleared.
    Coordinator roots (final roots of `tree` with >=1 child: `parent` target or
    tab root with children) carry `role=coordinator` in EVERY mode; the token is
    cleared once the pane has no children.
    Best effort: a failing/dead pane is skipped, never raised. A pane whose
    published tokens already equal the desired ones is not rewritten, except
    every TOKEN_REFRESH_S so the 24h TTL never lapses. Returns the number of
    panes whose tokens are up to date (written or unchanged).
    """
    if snap is None:
        snap = take_snapshot()
    if agents is None:
        agents = snap["agents"]
    if not agents:
        return 0
    panes = snap["panes"]
    ctx = name_context(snap)
    if tree is None:
        tree = current_tree(agents, panes, snap["group_by_tab"])
    ws_labels = snap["ws"]
    seq, space_key = layout_sequence(agents, panes, ctx[0], snap["ws_idx"], tree)
    order_idx = order_indices(seq, space_key.__getitem__)
    if mode == "picked":
        marks, parents = group_marks(seq, tree)
    else:
        marks, parents = {}, set()
    coords = set((tree or {}).values())  # roots with children, in every mode
    rank = {}
    for pid in seq:
        rank.setdefault(space_key[pid], len(rank))
    current = {p.get("pane_id"): p.get("tokens") for p in panes}
    now = time.time()
    force = now - read_published_at() > TOKEN_REFRESH_S
    n = 0
    for a in agents:
        pane_id = a.get("pane_id")
        if not pane_id:
            continue
        title, space, sub = row_texts(
            a, ctx, ws_labels, marks.get(pane_id) if pane_id in tree else None,
            pane_id in parents)
        tokens = {
            "space_rank": f"{rank[space_key[pane_id]]:04d}" if pane_id in space_key else None,
            "order": f"{order_idx[pane_id]:04d}" if pane_id in order_idx else None,
            "repo": None,
            "name": None,
            "tree_ws": None,
            "role": ROLE_COORDINATOR if pane_id in coords else None,
            **row_tokens(title, space, sub),
        }
        if not force and _tokens_current(current.get(pane_id), tokens):
            n += 1
            continue
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
    if force and n:
        write_state(read_mode(), read_excluded(), published_at=now)
    return n


def _tokens_current(existing, desired):
    """Pure. True when the pane's reported tokens already hold every non-None
    desired value and none of the None (cleared) ones."""
    if not isinstance(existing, dict):
        return False
    return all((existing.get(k) == v) if v is not None else (k not in existing)
               for k, v in desired.items())


_RESUME_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


def resume_command(info):
    """Pure. Suggested resume command of a coordinator entry (claude only)."""
    sess = (info or {}).get("agent_session")
    if not isinstance(sess, dict) or sess.get("agent") != "claude":
        return None
    v = sess.get("value")
    if isinstance(v, str) and _RESUME_ID.match(v):
        return f"claude --resume {v}"
    return None


def coordinator_entry(pid, pane_d, agent_d, prev, now):
    """Pure. Info of one live coordinator: agent_session, label, tab, cwd,
    last_seen (kept while nothing else changed and younger than COORD_REFRESH_S)."""
    pane_d, agent_d, prev = pane_d or {}, agent_d or {}, prev or {}
    sess = pane_d.get("agent_session") or agent_d.get("agent_session")
    if not isinstance(sess, dict) or not sess.get("value"):
        sess = prev.get("agent_session")
    info = {
        "agent_session": sess if isinstance(sess, dict) else None,
        "label": pane_d.get("label") or agent_d.get("label") or prev.get("label"),
        "tab": pane_d.get("tab_id") or agent_d.get("tab_id") or prev.get("tab"),
        "cwd": pane_d.get("cwd") or agent_d.get("cwd") or prev.get("cwd"),
    }
    old_seen = prev.get("last_seen")
    same = all(prev.get(k) == v for k, v in info.items())
    fresh = isinstance(old_seen, (int, float)) and now - old_seen < COORD_REFRESH_S
    info["last_seen"] = old_seen if same and fresh else now
    return info


def record_coordinators(snap, tree, now=None):
    """Persist coord pane_id -> info for every live coordinator root, and move
    one that is no longer a live pane (closed / exited, `drop_closed` already
    removed it from the snapshot) into `closed_coordinators` (newest last, max
    CLOSED_COORD_MAX) with closed_at and a `claude --resume` suggestion. A
    coordinator that is alive but lost its children is just forgotten. Skips
    when agent.list / pane.list failed. Writes only when something changed."""
    agents, panes = snap.get("agents"), snap.get("panes")
    if agents is None or not panes:
        return
    now = time.time() if now is None else now
    with state_lock():
        st = read_state()
        stored, closed = read_coordinators(st), read_closed_coordinators(st)
        by_pane = {p.get("pane_id"): p for p in panes}
        by_agent = {a.get("pane_id"): a for a in agents}
        new = {pid: coordinator_entry(pid, by_pane.get(pid), by_agent.get(pid),
                                      stored.get(pid), now)
               for pid in sorted(set((tree or {}).values()))}
        new_closed = list(closed)
        for pid, info in stored.items():
            if pid not in new and pid not in by_pane:
                entry = {"pane_id": pid, **info, "closed_at": now}
                cmd = resume_command(info)
                if cmd:
                    entry["resume"] = cmd
                new_closed.append(entry)
        new_closed = new_closed[-CLOSED_COORD_MAX:]
        if new != stored or new_closed != closed:
            write_state(read_mode(), read_excluded(), coordinators=new,
                        closed_coordinators=new_closed)


def prune_excluded(snap=None):
    """Drop excluded pane ids / spaces / tabs that no longer exist (a pane is
    dead only when absent from pane.list). Skips on listing failure."""
    with state_lock():
        return _prune_excluded(snap or take_snapshot())


def _prune_excluded(snap):
    ex = read_excluded()
    if not ex:
        return ex
    agents = snap["agents"]
    if agents is None:
        return ex
    alive = alive_ids(snap["panes"], agents, ex)
    ws, tabs = snap["ws"], snap["tabs"]

    def keep(p):
        if p.startswith(SPACE_PREFIX):
            return not ws or p[len(SPACE_PREFIX):] in ws
        if p.startswith(TAB_PREFIX):
            return not tabs or p[len(TAB_PREFIX):] in tabs
        return p in alive

    kept = [p for p in ex if keep(p)]
    if len(kept) != len(ex):
        write_excluded(kept)
    return kept


def apply_mode(mode, excluded=None, snap=None):
    with state_lock():
        return _apply_mode(mode, excluded, snap or take_snapshot())


def _apply_mode(mode, excluded, snap):
    agents = snap["agents"] or []
    panes = snap["panes"]
    fs, roots = sync_layout(agents, panes, snap=snap)
    tree, _, fallback = tree_roots_fallback(
        agents, panes, snap["group_by_tab"], fs, roots, read_parents())
    if mode == "picked":
        if excluded is None:
            excluded = read_excluded()
        space_of = {a.get("pane_id"): a.get("workspace_id") for a in agents}
        tab_of = {a.get("pane_id"): a.get("tab_id") for a in agents}
        eff = effective_excluded(excluded, tree, space_of, tab_of)
        # Empty exclusion -> match-everything view, so the sort still applies.
        flt = {"op": "not", "filter": {"op": "in", "field": "pane_id",
                                       "values": eff or ["__none__"]}}
    record_coordinators(snap, tree)
    publish_tokens(agents, tree=tree, snap=snap, mode=mode)
    if mode == "all":
        req = {"id": "avf_clear", "method": "agent.view.clear", "params": {"source": SOURCE}}
    else:
        if mode != "picked":
            flt = FILTERS[mode]
        req = {
            "id": "avf_set",
            "method": "agent.view.set",
            "params": {
                "source": SOURCE,
                "label": mode,
                "filter": flt,
                "sort": SORT,
            },
        }
    try:
        return send(req)
    except (OSError, ValueError) as e:  # socket gone / timeout: no traceback
        sys.stderr.write(f"agent-view-filters: {req['method']} failed: {e}\n")
        return None


def closed_pane_arg(args):
    """Pane id after `--closed`, or None."""
    if "--closed" in args:
        i = args.index("--closed")
        if i + 1 < len(args) and args[i + 1]:
            return args[i + 1]
    return None


def closed_pane_from_env():
    """pane_id of a pane.closed / pane.exited hook (HERDR_PLUGIN_EVENT_JSON), or
    None."""
    if os.environ.get("HERDR_PLUGIN_EVENT") not in (
        "pane.closed", "pane_closed", "pane.exited", "pane_exited"
    ):
        return None
    try:
        data = json.loads(os.environ.get("HERDR_PLUGIN_EVENT_JSON") or "")
        pid = data["data"]["pane_id"]
    except (KeyError, TypeError, ValueError):
        return None
    return pid if isinstance(pid, str) and pid else None


def drop_closed(snap, closed):
    """Remove a pane that is closing from the snapshot: Herdr emits pane.closed
    before pane.list / agent.list stop returning it."""
    if not closed:
        return snap
    if snap.get("agents") is not None:
        snap["agents"] = [a for a in snap["agents"] if a.get("pane_id") != closed]
    snap["panes"] = [p for p in snap["panes"] if p.get("pane_id") != closed]
    return snap


def run_sync(closed=None):
    with state_lock():
        mode = read_mode()
        snap = drop_closed(take_snapshot(), closed)
        sync_new_agents(snap)
        excluded = prune_excluded(snap)
        apply_mode(mode, excluded, snap)
    print(f"agent-view-filters: synced -> {mode}")


DELAYED_SYNC_S = 0.4


def spawn_delayed_sync():
    """Detached follow-up sync; the hook does not wait for it."""
    try:
        subprocess.Popen([sys.executable, os.path.abspath(__file__), "delayed-sync"],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError as e:
        sys.stderr.write(f"agent-view-filters: delayed sync spawn failed: {e}\n")


def delayed_sync():
    """One pending delayed sync at a time (flock LOCK_NB): a burst of closes
    coalesces into the already-sleeping process. The lock is dropped before
    syncing so a later close can schedule another one."""
    with open(os.path.join(state_dir(), "delayed.lock"), "a+") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return
        time.sleep(DELAYED_SYNC_S)
        fcntl.flock(f, fcntl.LOCK_UN)
    run_sync()


def main():
    action = sys.argv[1] if len(sys.argv) > 1 else "cycle"

    if action in ("sync", "sync-closed"):
        closed = closed_pane_arg(sys.argv[2:])
        if action == "sync-closed":
            closed = closed or closed_pane_from_env()
        run_sync(closed)
        if action == "sync-closed":
            spawn_delayed_sync()
        return

    if action == "delayed-sync":
        delayed_sync()
        return

    if action != "cycle" and action not in MODES:
        sys.stderr.write(f"agent-view-filters: unknown action '{action}'\n")
        sys.exit(2)

    with state_lock():
        if action == "cycle":
            mode = MODES[(MODES.index(read_mode()) + 1) % len(MODES)]
        else:
            mode = action
        snap = take_snapshot()
        excluded = prune_excluded(snap) if mode == "picked" else None
        apply_mode(mode, excluded, snap)
        write_mode(mode)
    print(f"agent-view-filters: mode -> {mode}")


if __name__ == "__main__":
    main()
