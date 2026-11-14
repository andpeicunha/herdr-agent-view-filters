"""Helpers compartilhados pelos testes. Único mock: `av.send` (socket Herdr)."""
import json
import os
import subprocess
import tempfile
import unittest
from unittest import mock

import agent_view as av

WORKSPACES = [
    {"workspace_id": "w1", "label": "Work", "number": 1},
    {"workspace_id": "w2", "label": "Home", "number": 2},
]


def agent(pid, tab, ws="w1", status="idle", title=None, cwd=None):
    """Agent dict como agent.list devolve (campos usados pelo plugin)."""
    return {
        "pane_id": pid,
        "tab_id": tab,
        "workspace_id": ws,
        "agent": "claude",
        "agent_status": status,
        "terminal_title": title,
        "cwd": cwd or f"/x/{pid}",
    }


def pane(pid, tab, ws="w1", parent=None, label=None):
    """Pane dict como pane.list devolve. `parent` vira token explícito."""
    return {
        "pane_id": pid,
        "tab_id": tab,
        "workspace_id": ws,
        "label": label,
        "tokens": {"parent": parent} if parent else {},
    }


class FakeHerdr:
    """Respostas fixas do socket Herdr. Grava todas as requisições."""

    def __init__(self, agents=(), panes=(), tabs=(), workspaces=WORKSPACES):
        self.agents = list(agents)
        self.panes = list(panes)
        self.tabs = list(tabs)
        self.workspaces = list(workspaces)
        self.calls = []

    def __call__(self, req, timeout=None):  # mesma assinatura de av.send(req, timeout)
        self.calls.append(req)
        m = req["method"]
        if m == "agent.list":
            return json.dumps({"result": {"agents": self.agents}})
        if m == "pane.list":
            return json.dumps({"result": {"panes": self.panes}})
        if m == "tab.list":
            return json.dumps({"result": {"tabs": self.tabs}})
        if m == "workspace.list":
            return json.dumps({"result": {"workspaces": self.workspaces}})
        if m in ("pane.report_metadata", "agent.view.set", "agent.view.clear"):
            return json.dumps({"result": {}})
        raise AssertionError(f"método inesperado: {m}")

    def methods(self, name):
        return [c["params"] for c in self.calls if c["method"] == name]

    def tokens(self):
        """pane_id -> tokens publicados por pane.report_metadata."""
        return {p["pane_id"]: p["tokens"] for p in self.methods("pane.report_metadata")}


def mocked(herdr):
    """Patch só de `av.send` com o fake Herdr."""
    return mock.patch.object(av, "send", side_effect=herdr)


_REAL_RUN = subprocess.run


class Isolated(unittest.TestCase):
    """STATE e CONFIG em tmp: nunca toca state.json real nem config do usuário.
    `herdr pane rename` (renome único de coordinator) é interceptado em
    `self.rename_run` (falha por padrão, ver setUp); qualquer outro subprocess.run segue o real."""

    def setUp(self):
        # Default: herdr "missing" (rename fails, pane stays unmarked/unchanged),
        # so tests unrelated to the rename keep their original labels/tokens.
        self.rename_run = mock.Mock(side_effect=FileNotFoundError("herdr"))

        def run(argv, *a, **kw):
            if list(argv[:3]) == ["herdr", "pane", "rename"]:
                return self.rename_run(argv, *a, **kw)
            return _REAL_RUN(argv, *a, **kw)

        patcher = mock.patch.object(av.subprocess, "run", side_effect=run)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.state_dir = tempfile.mkdtemp()
        self.config_dir = tempfile.mkdtemp()
        self._old = {k: os.environ.get(k)
                     for k in ("HERDR_PLUGIN_STATE_DIR", "HERDR_PLUGIN_CONFIG_DIR")}
        os.environ["HERDR_PLUGIN_STATE_DIR"] = self.state_dir
        os.environ["HERDR_PLUGIN_CONFIG_DIR"] = self.config_dir

    def tearDown(self):
        for k, v in self._old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def write_config(self, text):
        with open(os.path.join(self.config_dir, "config.toml"), "w") as f:
            f.write(text)

    def state_file(self):
        with open(os.path.join(self.state_dir, "state.json")) as f:
            return json.load(f)
