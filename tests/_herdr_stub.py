"""Stub do binario `herdr` (PATH) para testes de subprocess do wrapper e do hook.
Nunca toca o herdr real. Env: STUB_PANES (json de `pane list`), STUB_FAIL=1
(pane list falha), STUB_PROC (json pane_id -> process_info), STUB_LOG (comandos)."""
import json
import os
import stat
import tempfile
import time

DOTFILES = os.path.expanduser("~/Apps/dotfiles/claude")
WRAPPER = os.path.join(DOTFILES, "scripts", "herdr-close-child.sh")
HOOK = os.path.join(DOTFILES, "hooks", "herdr-guard-coordinator.py")

SCRIPT = r'''#!/usr/bin/env python3
import json, os, sys, time
a = sys.argv[1:]
with open(os.environ["STUB_LOG"], "a") as f:
    f.write(" ".join(a) + "\n")
if a[:2] == ["pane", "list"]:
    if os.environ.get("STUB_FAIL"):
        sys.exit(1)
    print(open(os.environ["STUB_PANES"]).read())
elif a[:2] == ["pane", "process-info"]:
    if os.environ.get("STUB_PROC_SLEEP"):
        time.sleep(float(os.environ["STUB_PROC_SLEEP"]))
    info = json.load(open(os.environ["STUB_PROC"])).get(a[3])
    if info is None:
        sys.exit(1)
    print(json.dumps({"result": {"process_info": info}}))
elif a[:2] == ["pane", "close"]:
    pass
else:
    sys.exit(0)
'''


class Stub:
    def __init__(self, panes, proc=None, fail=False, proc_sleep=None):
        self.dir = tempfile.mkdtemp()
        exe = os.path.join(self.dir, "herdr")
        with open(exe, "w") as f:
            f.write(SCRIPT)
        os.chmod(exe, os.stat(exe).st_mode | stat.S_IXUSR)
        self.log = os.path.join(self.dir, "log")
        open(self.log, "w").close()
        pj = os.path.join(self.dir, "panes.json")
        json.dump({"result": {"panes": panes}}, open(pj, "w"))
        proc_j = os.path.join(self.dir, "proc.json")
        json.dump(proc or {}, open(proc_j, "w"))
        self.state = os.path.join(self.dir, "state.json")
        self.env = {**os.environ, "PATH": self.dir + os.pathsep + os.environ["PATH"],
                    "STUB_PANES": pj, "STUB_PROC": proc_j, "STUB_LOG": self.log,
                    "AVF_STATE": self.state}
        self.env.pop("DRY_RUN", None)
        if fail:
            self.env["STUB_FAIL"] = "1"
        if proc_sleep is not None:
            self.env["STUB_PROC_SLEEP"] = str(proc_sleep)

    def set_state(self, d):
        json.dump(d, open(self.state, "w"))

    def calls(self):
        return [l.strip() for l in open(self.log) if l.strip()]

    def closes(self):
        return [c for c in self.calls() if c.startswith("pane close")]


def mk(pid, tab="t1", parent=None, role=None):
    toks = {}
    if parent:
        toks["parent"] = parent
    if role:
        toks["role"] = role
    return {"pane_id": pid, "tab_id": tab, "tokens": toks}
