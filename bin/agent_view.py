#!/usr/bin/env python3
"""agent-view-filters: cycle the Herdr Agents sidebar between three modes.

Modes:
  active - only agents currently working or blocked, most-recent-first
  space  - only agents in the focused space (workspace)
  all    - clear the view, show everything (native default)

State (which mode is "on") persists in $HERDR_PLUGIN_STATE_DIR/state.json so
the workspace.focused hook can re-assert it after space switches / restarts.
"""
import json
import os
import socket
import sys

SOURCE = "plugin:andpeicunha.agent-view-filters"
MODES = ["active", "space", "all"]

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

SORT = [
    {"field": "attention", "order": "desc"},
    {"field": "state_change_seq", "order": "desc"},
]


def state_path():
    d = os.environ.get("HERDR_PLUGIN_STATE_DIR") or "."
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "state.json")


def read_mode():
    try:
        with open(state_path()) as f:
            m = json.load(f).get("mode")
            if m in MODES:
                return m
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return "active"


def write_mode(mode):
    with open(state_path(), "w") as f:
        json.dump({"mode": mode}, f)


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


def apply_mode(mode):
    if mode == "all":
        resp = send({"id": "avf_clear", "method": "agent.view.clear", "params": {"source": SOURCE}})
    else:
        resp = send({
            "id": "avf_set",
            "method": "agent.view.set",
            "params": {
                "source": SOURCE,
                "label": mode,
                "filter": FILTERS[mode],
                "sort": SORT,
            },
        })
    return resp


def main():
    action = sys.argv[1] if len(sys.argv) > 1 else "cycle"

    if action == "sync":
        mode = read_mode()
        apply_mode(mode)
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

    apply_mode(mode)
    write_mode(mode)
    print(f"agent-view-filters: mode -> {mode}")


if __name__ == "__main__":
    main()
