# agent-view-filters

Local Herdr plugin that cycles the Agents sidebar between three declarative
views, since Herdr 0.8.2 has no native config for filtering the sidebar by
agent activity or by current space, and no way to bind a sidebar click to a
plugin action (only keybinds, CLI, and link-handlers can trigger actions).

## Modes (cycled by `prefix+f`)

1. **`active`** — only agents currently `working` or `blocked`
   (i.e. doing something now, or waiting on you). Sorted by attention, then
   most recent state transition (`state_change_seq desc`).
2. **`space`** — only agents in the currently focused space/workspace.
3. **`all`** — clears the view; back to Herdr's native default (all agents,
   `ui.agent_panel_sort` ordering).

`cycle` rotates `active -> space -> all -> active -> ...`. Each mode can also
be set directly: `active`, `space`, `all`.

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

- `herdr-plugin.toml` declares 4 actions (`active`, `space`, `all`, `cycle`)
  plus a `workspace.focused` event hook that re-runs `sync` (re-applies
  whichever mode is currently persisted) on every space switch — this is
  what makes the mode "stick" across space changes and keeps it correct
  after a server restart (on first focus).
- `bin/agent_view.py` speaks the Herdr socket API directly
  (`$HERDR_SOCKET_PATH`, newline-delimited JSON) — no external deps, plain
  Python 3. Persists the active mode in
  `$HERDR_PLUGIN_STATE_DIR/state.json`.
- `run.sh` is the manifest entrypoint, dispatches into the Python script.
- `install.sh` copies the plugin into `~/.config/herdr/plugins/agent-view-filters/`.

## Manual testing

```bash
herdr plugin action invoke active --plugin andpeicunha.agent-view-filters
herdr plugin action invoke space  --plugin andpeicunha.agent-view-filters
herdr plugin action invoke all    --plugin andpeicunha.agent-view-filters
herdr plugin action invoke cycle  --plugin andpeicunha.agent-view-filters
herdr plugin log list --plugin andpeicunha.agent-view-filters   # inspect stdout/exit codes
```

## Keybind

`prefix+f` -> `andpeicunha.agent-view-filters.cycle` (see `herdr/config.toml`).

## History

- Superseded `ShankyJS/herdr-space-scoped-agents` (a community plugin that only
  did the `current space / all` toggle) — uninstalled once this plugin's
  `space` mode covered the same behavior plus `active`.
- Built after confirming Herdr has no native `ui.agent_panel_scope` config
  (proposed but not merged — see upstream discussion
  [herdrdev/herdr#1406](https://github.com/herdrdev/herdr/discussions/1406))
  and no native way to filter the sidebar by agent activity/type.
