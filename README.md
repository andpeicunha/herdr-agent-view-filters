# agent-view-filters

A [Herdr](https://herdr.io) plugin that filters the Agents sidebar by agent
activity, current space, or a hand-picked set, and groups agents by task/tab.
Herdr has no native config for these views.

Requires Herdr >= 0.9.5. Python 3 only; no extra packages.

## Features

- Three filtered views: `active` (working/blocked), `space` (current space) and
  `picked` (everything except the agents you unticked). `all` clears the view
  back to Herdr's native order.
- A picker popup that mirrors the sidebar: tick spaces and root agents.
- Grouping: children under their root (parent token, else per tab). The tree
  marks (`├` / `└`) are drawn only in `picked`; the other views are flat.
- A stable sort (space -> tab -> root -> children), so the sidebar no longer
  reshuffles when agent status changes. No manual ordering.

## Installation

```sh
herdr plugin install andpeicunha/herdr-agent-view-filters
```

## Usage

Bind the `cycle` and `pick` actions in `~/.config/herdr/config.toml`:

```toml
[[keys.command]]
key = "prefix+f"
type = "plugin_action"
command = "andpeicunha.agent-view-filters.cycle"
description = "agent-view-filters: cycle view"

[[keys.command]]
key = "prefix+p"
type = "plugin_action"
command = "andpeicunha.agent-view-filters.pick"
description = "agent-view-filters: pick agents"
```

## Modes (cycled by `prefix+f`)

1. **`active`** — only agents currently `working` or `blocked`.
2. **`space`** — only agents in the currently focused space/workspace.
3. **`picked`** — everything **except** the spaces / root agents you unticked
   in the picker (children follow their root; exclusion model, see below).
4. **`all`** — clears the view; Herdr's native default.

`cycle` rotates `active -> space -> picked -> all -> active -> ...`. Each mode
can also be set directly: `active`, `space`, `picked`, `all`.

## Stable sort (filtered modes only)

`active`, `space` and `picked` use ONE sort: **space order (native sidebar
workspace order) -> tab order -> root -> its children (layout order)**. The
sidebar no longer reshuffles when agent status changes. `all` is untouched: it
calls `agent.view.clear` and keeps Herdr's native priority order.

How: the view sort is `[{token: space_rank}, {token: order}, pane_order]` (all asc).
`publish_tokens()` writes per-pane tokens through `pane.report_metadata` (source
`plugin:andpeicunha.agent-view-filters`, `ttl_ms` = 86400000, the server max of
24h), on every sync and mode apply:

- `space_rank` = 4-digit rank of the pane's space (sidebar order; children use the root's)
- `order` = 4-digit position inside the space (tab order from `tab.list`, root,
  children in `pane.list` order = layout order)
- `title` / `space` / `sub` = sidebar display texts, names only (see "Sidebar layout")
- `tree` = `├` / `└` on a child (`picked` only)
- `subtree` = `├` on a root with children (`picked` only, second row)
- `coord` = `◆ orchestrator` on a coordinator row (every mode)
- `role` = `coordinator` on a coordinator root (every mode)
- the old `tree_ws`, `group`, `group_space`, `item`, `repo` and `name` tokens are
  reported as `null` (cleared)

Saved `order` / `space_order` in an old state.json are ignored. A pane whose
tokens are already up to date is not rewritten (a full republish happens at
least every 6h so the 24h TTL never lapses).

Tokens are visible in `agent.list` / `pane.get` (`tokens`). If nothing syncs for
24h they expire and the sort falls back to `pane_order`. A dead pane is skipped,
it does not fail the sync.

### Name rule

One rule, shared by the sort token and the picker (`display_name()` /
`agent_name()` in `bin/agent_view.py`):

- tab with 1 pane -> the tab label
- tab with more than 1 pane -> `<tab> › <pane>` (pane label, else terminal title)
- no tab label -> pane label, else the terminal title

Limitations:

- Tokens only refresh on `sync` (`workspace.focused`, `workspace.renamed`,
  `tab.renamed`, `workspace.moved`, `workspace.reordered`, `tab.moved`,
  `pane.moved`, `pane.agent_detected`, `pane.created`, `pane.closed`, or
  re-applying a mode). A pane rename or a changed terminal title is picked up at
  the next sync (no `pane.*renamed` event is used). There is deliberately no hook
  on `pane.agent_status_changed` (it fires constantly).
- `pane.closed` runs `sync-closed`: Herdr fires the event while `pane.list` /
  `agent.list` may still return the closing pane, so the hook reads its id from
  `HERDR_PLUGIN_EVENT_JSON` (`data.pane_id`; `sync --closed <pane_id>` does the
  same by hand) and drops it from that sync's snapshot, then schedules one
  detached re-sync after ~0.4s (`delayed.lock` flock coalesces bursts) so the
  root loses its stale `├` sub row.
- Panes without tokens (not yet synced) sort per Herdr's missing-value rule,
  until the next sync.

## Picker (`pick` action, `prefix+p`)

`prefix+p` -> `andpeicunha.agent-view-filters.pick` opens a popup (plugin pane
`picker`, `bin/picker.py`, pure curses) that mirrors the sidebar:

```
[x] <space>  (n)            <- space header, checkbox
    [x] ● <tab> · <space>   <- root with children, checkbox for the group
          ● ├ <repo>        <- the root's own repo row, no checkbox
          ● ├ <repo>        <- child, no checkbox
          ● └ <repo>        <- last child
    [x] ● <tab> · <space>   <- standalone agent, checkbox
```

Checked = shown. Unticking a space hides the whole space; unticking a root
hides it and its children. A root under an unticked space is drawn unticked/dim
(derived; the root's own entry is not changed). Children have no checkbox of
their own.

Keys: `up/down` (or `j/k`) navigate (children are skipped), `space` toggle,
`Enter` save + switch to `picked` + close, `q`/`Esc` cancel without saving.
The order is fixed (see "Stable sort"); there is no reorder UI.

### Exclusion model

`$HERDR_PLUGIN_STATE_DIR/state.json` holds `mode`, `excluded`, `seen`,
`first_seen`, `tab_roots`, `parents` and `published_at` (the last four are
bookkeeping; only `mode` and `excluded` are required).
`excluded` has `"space:<workspace_id>"` entries, `"tab:<tab_id>"` entries
(tab-fallback groups, stable when the first pane of the tab changes) and root
pane ids (explicit-parent groups and standalone panes). A pane id that is a
tab-fallback root (a root with at least one tab-fallback child, even if it also
has explicit children) is migrated to `tab:<tab_id>` on `sync`; an excluded id
that is (or became) a child is dropped, never migrated. A `tab:<tab_id>`
entry hides EVERY agent pane of that tab, group or lone pane (e.g. the group
shrinks to one pane: it stays hidden); it is pruned only when the tab dies. In
the picker a lone pane in an excluded tab shows unchecked; toggling it removes
the `tab:` entry. Hidden =
space excluded OR tab excluded OR root excluded; the `picked` view is
`not(pane_id in hidden)`, children follow their root. A legacy child id in
`excluded` is ignored (and dropped on the next sync). With nothing excluded
`picked` keeps a match-everything view (so the sort still applies; it does not
clear like `all`). Dead panes / spaces / tabs are pruned on every `sync` and on
`picked`/`cycle` into picked. A pane is dead only when it is absent from
`pane.list`: a pane that merely stopped being an agent (e.g. the agent process
restarts) keeps its `first_seen`, `tab_roots`, `parents`, `seen` and `excluded`
entries and only leaves the tree meanwhile. Nothing is pruned when `pane.list` is
empty or fails. Old keys (`order`, `space_order`) are ignored.

### Config (`config.toml`)

In `$HERDR_PLUGIN_CONFIG_DIR` (fallback
`~/.config/herdr/plugins/config/andpeicunha.agent-view-filters/config.toml`):

```toml
picked_new   = "include"   # default; or "exclude"
group_by_tab = true        # default; false = only parent tokens group
```

- `picked_new = "include"`: new agents show up in `picked` automatically.
  `"exclude"`: a never-seen root agent is added to `excluded` on `sync`
  (children are never auto-excluded). The first sync after upgrading marks all
  current agents as seen without excluding.
- `group_by_tab`: see "Task grouping".
- Needs Python 3.11+ (`tomllib`); otherwise the defaults are used.

`state.json` lives in `$HERDR_PLUGIN_STATE_DIR`; when unset it falls back to
`~/.local/state/herdr/plugins/andpeicunha.agent-view-filters` (never the CWD).

Concurrency: every read-modify-write of `state.json` (sync, mode apply, picker
save) holds an exclusive `flock` on `state.lock` in the same directory, and the
temp file is unique per write (`tempfile.mkstemp`, `state.json.<random>.tmp`;
fsync, then `os.replace`). The picker
re-reads the state under the lock before saving and only changes `excluded`
(`seen`, `first_seen`, `tab_roots` and `parents` are merged, not overwritten).

### Subagent status

Herdr's status only reflects the main Claude session. The picker dot shows
`working` instead of `idle`/`done` while the pane has an active subagent, read
(never written) from
`${XDG_STATE_HOME:-~/.local/state}/herdr-agents/subagents/<pane_id>`, one
`agent_id epoch_seconds` line per subagent. Entries older than 60 min
(`SUBAGENT_TTL_S` in `bin/agent_view.py`) are ignored; a missing or malformed
file falls back to the Herdr status.

## Upgrading from 0.9.x

0.10.0 changes behavior:

- `picked_new` default is `include` (new agents show up in `picked`). Set
  `picked_new = "exclude"` in `config.toml` to keep the old opt-in behavior.
- Manual ordering is gone (there is no reorder UI); the order is always space ->
  tab -> root -> children.
- The sort token `space` was renamed `space_rank`. The view sort is re-sent on
  every sync, but custom configs / scripts that reference the `space` token must
  switch to `space_rank`.
- The sidebar rows must use the plugin tokens: `$title`, `$space`, `$sub` (see
  "Sidebar layout"). The `repo` / `name` tokens are no longer published.
- Tree marks appear only in `picked`; `active` / `space` / `all` are flat.
- An excluded pane id that is a child (0.9.0 `picked_new = "exclude"`, or a
  cross-tab explicit parent) is dropped on the first sync instead of migrated.
- The spawn script no longer publishes the `task` token.
- New events trigger a sync: `workspace.moved`, `workspace.reordered`,
  `tab.moved`, `pane.moved` (reload the plugin to register them).

## Why not a time window (e.g. "active in the last 12h")?

Checked the Herdr 0.8.2 socket API (`agent.view.set`) and `agent.list`/`agent.get`
payloads directly: neither exposes any wall-clock timestamp for state
changes — only `state_change_seq`, a monotonic sequence number (relative
ordering only, no epoch/duration). A true "last N hours" filter isn't
possible through the declarative view API alone; it would require a
plugin-side background poller recording real timestamps per `pane_id` and
building an `{"op":"in","field":"pane_id","values":[...]}` filter from that.
Not built — the `active` (working/blocked) + recency-sort proxy above was
judged good enough for now. Revisit if Herdr adds a timestamp field to
agent state in a future release.

## How it works

- `herdr-plugin.toml` declares 6 actions (`active`, `space`, `picked`, `all`,
  `cycle`, `pick`), the `picker` popup pane, plus event hooks
  (`workspace.focused`, `workspace.renamed`, `workspace.moved`,
  `workspace.reordered`, `tab.renamed`, `tab.moved`, `pane.moved`,
  `pane.agent_detected`, `pane.created`, `pane.closed`; deliberately no
  `pane.updated`, it fires constantly) that re-run
  `sync` (re-publishes sort tokens and re-applies whichever mode is currently
  persisted) — this keeps the mode "sticky" across space changes, keeps new
  panes sorted, and re-asserts it after a server restart (on first event).
- `bin/agent_view.py` speaks the Herdr socket API directly
  (`$HERDR_SOCKET_PATH`, newline-delimited JSON) — no external deps, plain
  Python 3. Persists the active mode in
  `$HERDR_PLUGIN_STATE_DIR/state.json`.
- `bin/picker.py` imports the socket/state/name helpers from `agent_view.py`.
- `run.sh` is the manifest entrypoint, dispatches into the Python script.
- `pick.sh` opens the popup through the socket (`plugin.pane.open`,
  placement `popup`; the CLI has no popup placement).

## Task grouping

Two sources, in this priority:

1. **Parent token** (explicit): the `parent=<pane_id>` pane token, set by the
   `herdr-claude-agent.sh` spawn script. The parent may live in another tab or
   space: the child is listed under it there. A live parent always wins. Valid relations are persisted in `state.json` (`parents`:
   child pane id -> parent pane id); when the token expires, the stored relation
   keeps the group while both panes are alive (a live token overrides it; dead
   panes are pruned).
2. **Tab fallback** (`group_by_tab = true`, default): agent panes WITHOUT a live
   parent token are grouped per tab. The root is sticky (the oldest
   `first_seen` agent of the tab, kept while it is alive in that tab); the
   others become its children. A pane alone in its tab is standalone.

- Children are listed right after their root, in the root's space, in every
  filtered mode.
- `parent == self`, a parent that is not a live agent and cycles are ignored;
  grandchildren flatten to the root. If the root closes, the next first pane of
  the tab becomes the root.
- `picked`: children are hidden when their root (or its space) is excluded.
- Tree marks (`$tree`, `$subtree`) and the `$sub` row exist only in `picked` (see "Sidebar layout").

## Sidebar layout

The plugin publishes one token per part of the row, so each part can have its
own color. Names are never glued to marks in the token values:

- `$title` / `$space`: tab label and workspace label (flat rows and roots/standalone).
- `$sub`: display label of a root with children (second row). Herdr indents every
  row after the first of an agent by 2 columns. Herdr hides a row when none of its
  tokens has a value.
- `$tree`: `├` / `└` on a child (`└` for the last child), first row. `picked` only.
- `$subtree`: `├` on a root with children, second row. `picked` only.
- `$coord`: `◆ orchestrator` on a coordinator row, in every mode. The coordinator
  name lives only in `$coord`; its `$sub` is absent.

Per pane, `picked`:

| pane (`picked`) | `$tree` | `$title` | `$space` | `$subtree` | `$sub` | `$coord` |
| --- | --- | --- | --- | --- | --- | --- |
| root with children | absent | tab label | workspace label | `├` | display label | absent |
| coordinator root | absent | tab label | workspace label | `├` | absent | `◆ orchestrator` |
| child | `├` / `└` (last child) | display label | absent | absent | absent | absent |
| standalone | absent | tab label | workspace label | absent | absent | absent |

In `active`, `space` and `all` every agent gets a flat row: `$title` = tab label
(display label when the tab label is empty/numeric), `$space` = workspace label,
`$tree` / `$subtree` / `$sub` absent. `$coord` still shows on coordinator rows.
Order still follows the tree, but children carry no mark.

Config and plugin must match: a `[ui.sidebar.agents]` layout without `$tree`,
`$subtree` and `$coord` hides the marks and the coordinator label, even though the
plugin publishes them. Herdr joins adjacent values with " · " and drops missing
ones with their separator.

Title falls back to the display label when the tab label is empty or purely numeric (e.g. `1`).

Display label, first non-empty (128 chars max):

1. manual pane label (leading emoji/symbols stripped) unless it is auto, i.e. equal
   (case-insensitive) to the cwd basename without leading dots (`🟡 Apps` in `~/Apps`)
2. Herdr agent name (`agent.list` `name`)
3. terminal title (cleaned)
4. repo (cwd basename, leading dots stripped)
5. agent kind (`claude`, `codex`, ...)

Absent
tokens are sent as `null`; Herdr hides missing values and rows with no value.

Herdr has no fallback syntax between tokens: custom `$title` / `$space` are
empty until the plugin first syncs (and if the plugin is disabled). Adding the
native `tab` / `workspace` tokens next to them would duplicate the names while the
plugin is active, so the layout below uses the custom tokens only.

```toml
[ui.sidebar.agents]
# $title / $space / $sub / $tree / $subtree / $coord come from the agent-view-filters
# plugin (one token per color). $tree = child mark (row 1), $subtree = root mark
# (row 2), $coord = "◆ orchestrator" (coordinator only). Herdr joins adjacent
# values with " · " (no glue option) and drops missing tokens with their separator.
# No token fallback syntax, so native `tab` / `workspace` are not added (they would
# duplicate the names); rows stay icon-only until the plugin's first sync.
row_gap = 0
rows = [
  ["state_icon", { token = "$tree", fg = "#555a66" }, { token = "$title", fg = "#f8f8f2", bold = true }, { token = "$space", fg = "#6272a4" }],
  [{ token = "$subtree", fg = "#555a66" }, { token = "$sub", fg = "#f8f8f2" }, { token = "$coord", fg = "#bd93f9", bold = true }],
]
```

## Pane naming hook

`bin/name_hint.py` is an agent hook that nudges the agent to give its pane a
fixed, short name (`herdr pane rename`). It does not read stdin. It reads
`$HERDR_PANE_ID` and emits nothing in non-interactive runs
(`CLAUDE_CODE_ENTRYPOINT` starting with `sdk`: `claude -p`, SDK); when the
pane label is auto (empty, the cwd basename or `<basename> #N`, see
`is_auto_label()`) it emits an instruction, otherwise (manual label, no pane id,
socket unreachable) it prints nothing. It always exits 0 and uses a 0.8s socket
timeout. The instruction repeats on each prompt until the pane is renamed.

- `--format claude` (default): `UserPromptSubmit` hook JSON (`additionalContext`).
- `--format text`: raw instruction, for other agents (e.g. Codex).
- Any other `--format` value prints nothing and exits 0 (hook safety).

Claude Code (`~/.claude/settings.json`):

```json
{"hooks": {"UserPromptSubmit": [{"hooks": [{"type": "command",
  "command": "python3 /path/to/bin/name_hint.py", "timeout": 5}]}]}}
```

## Manual testing

```bash
herdr plugin action invoke active --plugin andpeicunha.agent-view-filters
herdr plugin action invoke space  --plugin andpeicunha.agent-view-filters
herdr plugin action invoke picked --plugin andpeicunha.agent-view-filters
herdr plugin action invoke pick   --plugin andpeicunha.agent-view-filters   # opens the popup
herdr plugin action invoke all    --plugin andpeicunha.agent-view-filters
herdr plugin action invoke cycle  --plugin andpeicunha.agent-view-filters
herdr plugin log list --plugin andpeicunha.agent-view-filters   # inspect stdout/exit codes
```

## History

- Built because Herdr has no native `ui.agent_panel_scope` config (proposed,
  not merged: [herdrdev/herdr#1406](https://github.com/herdrdev/herdr/discussions/1406))
  and no native way to filter the sidebar by agent activity or type.
- Replaces the community plugin `ShankyJS/herdr-space-scoped-agents`, whose
  `current space / all` toggle is covered by the `space` mode.

## License

MIT. See [LICENSE](LICENSE).
