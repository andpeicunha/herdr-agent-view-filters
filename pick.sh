#!/usr/bin/env bash
# Opens the picker popup via the Herdr socket API (CLI has no popup placement).
set -uo pipefail
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
exec python3 - <<'PY'
import json, os, socket, sys
req = {
    "id": "avf_pick",
    "method": "plugin.pane.open",
    "params": {
        "plugin_id": os.environ.get("HERDR_PLUGIN_ID", "andpeicunha.agent-view-filters"),
        "entrypoint": "picker",
        "placement": "popup",
        "width": "70%",
        "height": "60%",
        "focus": True,
    },
}
cwd = os.environ.get("HERDR_PLUGIN_CONTEXT_JSON")
if cwd:
    try:
        c = json.loads(cwd).get("focused_pane_cwd")
        if c:
            req["params"]["cwd"] = c
    except ValueError:
        pass
s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
s.settimeout(5)
s.connect(os.environ["HERDR_SOCKET_PATH"])
s.sendall((json.dumps(req) + "\n").encode())
buf = b""
while b"\n" not in buf:
    c = s.recv(65536)
    if not c:
        break
    buf += c
r = json.loads(buf.decode() or "{}")
if "error" in r:
    sys.stderr.write("agent-view-filters: pick failed: %s\n" % json.dumps(r["error"]))
    sys.exit(1)
print("agent-view-filters: picker opened")
PY
