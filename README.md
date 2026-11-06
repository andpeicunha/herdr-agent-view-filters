# agent-view-filters

A [Herdr](https://herdr.io) plugin that filters the Agents sidebar by agent
activity, current space, or a hand-picked set, and lets you set your own agent
order. Herdr has no native config for these views.

Requires Herdr >= 0.9.5. Python 3 only; no extra packages.

## Features

- Three filtered views: `active` (working/blocked), `space` (current space) and
  `picked` (everything except the agents you unticked). `all` clears the view
  back to Herdr's native order.
- A picker popup to choose agents and reorder them by hand.
- A stable sort: filtered views follow your space order, so the sidebar no
  longer reshuffles when agent status changes.

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
3. **`picked`** — every agent **except** those you unticked in the picker
   (exclusion model, see below).
4. **`all`** — clears the view; Herdr's native default.

`cycle` rotates `active -> space -> picked -> all -> active -> ...`. Each mode
can also be set directly: `active`, `space`, `picked`, `all`.

## Stable sort (filtered modes only)

`active`, `space` and `picked` sort by **space order (native `workspace_order`,
i.e. the order you set by moving spaces in the sidebar), then repo A-Z, then
name A-Z, then `pane_order`**, so the sidebar follows your space order and no
longer reshuffles when agent status changes. `all` is untouched: it calls
`agent.view.clear` and keeps Herdr's native priority order.

How: the view sort is `[workspace_order, {token: repo}, {token: name}, pane_order]`
(all asc). `workspace_order` is a built-in field, so moving a space reorders the
sidebar on its own (no `workspace.moved` hook needed). `publish_tokens()` writes
two per-pane tokens through `pane.report_metadata` (source
`plugin:andpeicunha.agent-view-filters`, `ttl_ms` = 86400000, the server max of
24h). Lowercase, capped at 128 chars:

- `repo` = basename of `foreground_cwd` (fallback `cwd`)
- `name` = tab/pane name, see "Name rule" below

The old `title` and `space` tokens are no longer used; both are reported as
`null` on every sync so stale ones are cleared.

Tokens are visible in `agent.list` / `pane.get` (`tokens`). They are renewed on
every `sync` and whenever a filtered mode is applied; if nothing syncs for 24h
they expire and the sort falls back to the remaining keys. A dead pane is
skipped, it does not fail the sync.

### Name rule

One rule, shared by the sort token and the picker (`display_name()` /
`agent_name()` in `bin/agent_view.py`):

- tab with 1 pane -> the tab label
- tab with more than 1 pane -> `<tab> › <pane>` (pane label, else terminal title)
- no tab label -> pane label, else the terminal title

Limitations:

- `repo`/`name` tokens only refresh on `sync` (`workspace.focused`, `workspace.renamed`,
  `tab.renamed`, `pane.agent_detected`, `pane.created`, or re-applying a mode).
  A pane rename or a changed terminal title is picked up at the next sync, not
  instantly (no `pane.*renamed` event is used). There is deliberately no hook
  on `pane.agent_status_changed` (it fires constantly).
- Panes without tokens (not yet synced) sort per Herdr's missing-value rule,
  until the next sync.
- The picker orders by space position (see Picker); it does not use tokens.

## Picker (`pick` action, `prefix+p`)

`prefix+p` -> `andpeicunha.agent-view-filters.pick` opens a popup (plugin pane
`picker`, `bin/picker.py`, pure curses) listing all agents. Checked = shown in
the sidebar. Each agent takes two lines:

- line 1: `[x] ● <space>  <repo>` - checkbox, status dot (color only, no status
  text; the legend is in the header), space label, repo (cwd basename) in light
  cyan when checked, dim when unchecked. Without a space label the repo takes
  its place.
- line 2: tab/pane name (see "Name rule"), plus the terminal title as a dim
  suffix when it is not already part of the name.

Keys: `up/down` or `j/k` move, `Shift+up/down` (or `K`/`J`) reorder the item
under the cursor, `r` reset to space order, `space` toggle, `/` search (Enter keeps the
filter, Esc clears), `a` check all (visible rows), `n` uncheck all (visible
rows), `Enter` save + switch to `picked` + close, `q`/`Esc` cancel without
saving. Initial order: the saved manual order (see "Manual order") if any, else space position in the sidebar (`number` from `workspace.list`, which
follows manual reordering), then repo A-Z, then name A-Z. Fixed at open; rows do
not jump while toggling (no "checked first", no status rank).

### Manual order

Build your own agent order in the picker and the sidebar follows it.

- `Shift+up` / `Shift+down` move the item under the cursor one position and the
  cursor follows it. Fallback without shift support: `K` (up) / `J` (down).
  Raw `ESC [ 1 ; 2 A/B` is decoded too when curses does not map it.
- Disabled while a search query is active (footer shows a short notice).
- The header shows `order: manual` or `order: follows spaces`.
- `r` goes back to following the space order (default rank); it clears `order`
  when you press Enter. Moving again re-enables manual order.
- `Enter` saves `excluded` as before and also `order` = the full list of
  pane_ids as displayed (when manual is active), or `order: []` after `r`.
  `q`/`Esc` saves nothing.
- Stored in state.json as `order` (list of pane_id). Empty or missing (old
  state) = no manual order, previous behavior. `excluded` and `order` are
  independent and can coexist.
- Sidebar: with a non-empty `order`, `active`/`space`/`picked` sort by
  `[{token: order}, pane_order]`; `publish_tokens()` writes an `order` token (4
  digits, zero padded) on every agent pane: saved panes get their index, panes
  not in `order` (new agents) get the following indexes in default rank
  (space, repo, name), so **a new agent goes to the end**. Without manual order
  the token is published as `null`. `all` is untouched (native order).
- New agents are not written into `order` automatically; they stay at the end
  (via token) until you save the picker again, which persists them. Trade-off:
  not persisting keeps `order` equal to what you chose, and the position of new
  agents still follows default rank among themselves.
- `sync` prunes pane_ids of dead panes from `order` (like `excluded`).
- `picked` with nothing excluded and a manual order keeps a match-all view
  (instead of clearing like `all`) so the manual sort applies.

Limitations: while manual order is on, moving a space does not move its agents
(the order is per pane, not per space); press `r` in the picker to follow
spaces again. Shift+up/down must reach the popup process; Herdr itself only
binds shift+left/right (tabs) in this setup.

### Exclusion model

`$HERDR_PLUGIN_STATE_DIR/state.json` holds `{"mode": ..., "excluded": [pane_id,...], "order": [pane_id,...]}`.
The `picked` view is `not(pane_id in excluded)`, so a **new agent shows up
automatically**; only unticked ones disappear. With an empty `excluded` the
view is cleared (same as `all`). On every `sync` (workspace focus) and on
`picked`/`cycle` into picked, ids of panes that no longer exist are pruned.
An old state.json without `excluded` or `order` is read as empty.

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
  (`workspace.focused`, `workspace.renamed`, `tab.renamed`, `pane.agent_detected`,
  `pane.created`; no `workspace.moved`/`tab.moved`: space order is native) that re-run
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
