# agent-view-filters

Local Herdr plugin (needs Herdr >= 0.9.5) that switches the Agents sidebar
between four declarative views, since Herdr has no native config for filtering
the sidebar by agent activity, current space, or a hand-picked set.

## Modes (cycled by `prefix+f`)

1. **`active`** — only agents currently `working` or `blocked`.
2. **`space`** — only agents in the currently focused space/workspace.
3. **`picked`** — every agent **except** those you unticked in the picker
   (exclusion model, see below).
4. **`all`** — clears the view; Herdr's native default.

`cycle` rotates `active -> space -> picked -> all -> active -> ...`. Each mode
can also be set directly: `active`, `space`, `picked`, `all`.

## Stable sort (filtered modes only)

`active`, `space` and `picked` sort by **space A-Z, then repo A-Z, then name
A-Z, then `pane_order`**, so the sidebar no longer reshuffles when agent status
changes. `all` is untouched: it calls `agent.view.clear` and keeps Herdr's
native priority order.

How: the view sort is `[{token: space}, {token: repo}, {token: name}, pane_order]`
(all asc). `publish_tokens()` writes three per-pane tokens through
`pane.report_metadata` (source `plugin:andpeicunha.agent-view-filters`,
`ttl_ms` = 86400000, the server max of 24h). All lowercase, capped at 128 chars:

- `space` = label of the workspace/space (`workspace.list`; falls back to repo)
- `repo` = basename of `foreground_cwd` (fallback `cwd`)
- `name` = tab/pane name, see "Name rule" below

The old `title` token is no longer used; it is reported as `null` on every sync
so a stale one is cleared.

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

- Tokens only refresh on `sync` (`workspace.focused`, `workspace.renamed`,
  `tab.renamed`, `pane.agent_detected`, `pane.created`, or re-applying a mode).
  A pane rename or a changed terminal title is picked up at the next sync, not
  instantly (no `pane.*renamed` event is used). There is deliberately no hook
  on `pane.agent_status_changed` (it fires constantly).
- Panes without tokens (not yet synced) sort per Herdr's missing-value rule,
  until the next sync.
- The picker keeps its own internal order (unchanged).

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

Keys: `up/down` or `j/k` move, `space` toggle, `/` search (Enter keeps the
filter, Esc clears), `a` check all (visible rows), `n` uncheck all (visible
rows), `Enter` save + switch to `picked` + close, `q`/`Esc` cancel without
saving. Order: checked first, then working/blocked, idle last (fixed at open,
rows do not jump while toggling).

### Exclusion model

`$HERDR_PLUGIN_STATE_DIR/state.json` holds `{"mode": ..., "excluded": [pane_id,...]}`.
The `picked` view is `not(pane_id in excluded)`, so a **new agent shows up
automatically**; only unticked ones disappear. With an empty `excluded` the
view is cleared (same as `all`). On every `sync` (workspace focus) and on
`picked`/`cycle` into picked, ids of panes that no longer exist are pruned.
An old state.json without `excluded` is read as empty.

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
  `pane.created`) that re-run
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
- `install.sh` copies the plugin into `~/.config/herdr/plugins/agent-view-filters/`.

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

## Keybind

`prefix+f` -> `...cycle`, `prefix+p` -> `...pick` (see `herdr/config.toml`).

## History

- Superseded `ShankyJS/herdr-space-scoped-agents` (a community plugin that only
  did the `current space / all` toggle) — uninstalled once this plugin's
  `space` mode covered the same behavior plus `active`.
- Built after confirming Herdr has no native `ui.agent_panel_scope` config
  (proposed but not merged — see upstream discussion
  [herdrdev/herdr#1406](https://github.com/herdrdev/herdr/discussions/1406))
  and no native way to filter the sidebar by agent activity/type.
