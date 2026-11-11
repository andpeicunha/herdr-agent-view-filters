"""pane.closed -> sync-closed: drop_closed, closed_pane_from_env, closed_pane_arg,
run_sync(closed), delayed_sync (flock coalescing), main(["sync-closed"]), manifest
and run.sh argument forwarding. Único mock de socket: av.send (via _support.mocked)."""
import contextlib
import fcntl
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, os.path.join(ROOT, "bin"))
sys.path.insert(0, HERE)
import agent_view as av  # noqa: E402
from _support import Isolated, FakeHerdr, agent, pane, mocked  # noqa: E402

TABS = [{"tab_id": "t1", "label": "dev"}, {"tab_id": "t2", "label": "ops"}]


def event_env(event, pane_id=None, raw=None):
    env = {"HERDR_PLUGIN_EVENT": event}
    if raw is not None:
        env["HERDR_PLUGIN_EVENT_JSON"] = raw
    else:
        env["HERDR_PLUGIN_EVENT_JSON"] = json.dumps(
            {"event": "pane_closed", "data": {"pane_id": pane_id}})
    return env


def copy_of(snap):
    return json.loads(json.dumps(snap))


class DropClosed(unittest.TestCase):
    def test_removes_from_agents_and_panes(self):
        snap = {"agents": [agent("R", "t1"), agent("C", "t1")],
                "panes": [pane("R", "t1"), pane("C", "t1", parent="R")]}
        out = av.drop_closed(snap, "C")
        self.assertEqual([a["pane_id"] for a in out["agents"]], ["R"])
        self.assertEqual([p["pane_id"] for p in out["panes"]], ["R"])

    def test_agents_none_is_kept_none(self):
        snap = {"agents": None, "panes": [pane("R", "t1"), pane("C", "t1")]}
        out = av.drop_closed(snap, "C")
        self.assertIsNone(out["agents"])
        self.assertEqual([p["pane_id"] for p in out["panes"]], ["R"])

    def test_closed_none_is_noop(self):
        snap = {"agents": [agent("R", "t1")], "panes": [pane("R", "t1")]}
        out = av.drop_closed(copy_of(snap), None)
        self.assertEqual(out, snap)

    def test_unknown_id_is_noop(self):
        snap = {"agents": [agent("R", "t1")], "panes": [pane("R", "t1")]}
        out = av.drop_closed(copy_of(snap), "ZZ")
        self.assertEqual(out, snap)


class ClosedPaneFromEnv(unittest.TestCase):
    def run_env(self, env):
        with mock.patch.dict(os.environ, env, clear=False):
            for k in ("HERDR_PLUGIN_EVENT", "HERDR_PLUGIN_EVENT_JSON"):
                if k not in env:
                    os.environ.pop(k, None)
            return av.closed_pane_from_env()

    def test_valid_pane_closed_returns_id(self):
        self.assertEqual(self.run_env(event_env("pane.closed", "P1")), "P1")

    def test_other_event_returns_none(self):
        self.assertIsNone(self.run_env(event_env("pane.created", "P1")))

    def test_missing_event_returns_none(self):
        self.assertIsNone(self.run_env({"HERDR_PLUGIN_EVENT_JSON":
                                        json.dumps({"data": {"pane_id": "P1"}})}))

    def test_bad_json_returns_none(self):
        self.assertIsNone(self.run_env(event_env("pane.closed", raw="{not json")))

    def test_empty_json_returns_none(self):
        self.assertIsNone(self.run_env(event_env("pane.closed", raw="")))

    def test_missing_pane_id_returns_none(self):
        self.assertIsNone(self.run_env(event_env("pane.closed", raw='{"data": {}}')))

    def test_missing_data_returns_none(self):
        self.assertIsNone(self.run_env(event_env("pane.closed", raw='{"event": "x"}')))

    def test_empty_or_non_string_pane_id_returns_none(self):
        for bad in ("", None, 7, ["P1"]):
            with self.subTest(pane_id=bad):
                raw = json.dumps({"data": {"pane_id": bad}})
                self.assertIsNone(self.run_env(event_env("pane.closed", raw=raw)))


class ClosedPaneArg(unittest.TestCase):
    def test_id_after_flag(self):
        self.assertEqual(av.closed_pane_arg(["--closed", "P1"]), "P1")

    def test_flag_among_other_args(self):
        self.assertEqual(av.closed_pane_arg(["x", "--closed", "P2"]), "P2")

    def test_no_flag(self):
        self.assertIsNone(av.closed_pane_arg([]))

    def test_flag_without_value(self):
        self.assertIsNone(av.closed_pane_arg(["--closed"]))
        self.assertIsNone(av.closed_pane_arg(["--closed", ""]))


class RunSyncClosed(Isolated):
    """Listagens (agent.list / pane.list) ainda contêm o pane fechado."""

    def fake(self):
        agents = [agent("R", "t1"), agent("C", "t1"), agent("A", "t2")]
        panes = [pane("R", "t1"), pane("C", "t1", parent="R"), pane("A", "t2")]
        return FakeHerdr(agents, panes, tabs=TABS)

    def seed(self):
        av.write_state("picked", [], seen=["R", "C", "A"],
                       first_seen={"R": 1, "C": 2, "A": 3},
                       tab_roots={"t1": "R", "t2": "A"}, parents={"C": "R"},
                       published_at=time.time())

    def test_root_publishes_no_sub_row_and_closed_pane_is_forgotten(self):
        self.seed()
        h = self.fake()
        with mocked(h), contextlib.redirect_stdout(io.StringIO()):
            av.run_sync("C")
        last_r = [p for p in h.methods("pane.report_metadata") if p["pane_id"] == "R"]
        self.assertTrue(last_r, "root não publicou tokens")
        for p in last_r:
            self.assertIsNone(p["tokens"].get("subtree"),
                             f"root ainda publica sub de filho fechado: {p['tokens']}")
        st = self.state_file()
        self.assertNotIn("C", st.get("seen", []))
        self.assertNotIn("C", st.get("first_seen", {}))
        self.assertIn("R", st.get("seen", []))
        self.assertIn("A", st.get("seen", []))

    def test_control_without_closed_arg_child_still_grouped(self):
        self.seed()
        h = self.fake()
        with mocked(h), contextlib.redirect_stdout(io.StringIO()):
            av.run_sync(None)
        last_r = [p for p in h.methods("pane.report_metadata") if p["pane_id"] == "R"]
        self.assertTrue(any(p["tokens"].get("subtree") == "├" for p in last_r))


class DelayedSync(Isolated):
    def lock_path(self):
        return os.path.join(self.state_dir, "delayed.lock")

    def test_lock_held_by_other_fd_returns_without_sync(self):
        holder = open(self.lock_path(), "a+")
        try:
            fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with mock.patch.object(av, "run_sync") as rs, \
                    mock.patch.object(av.time, "sleep") as sl:
                av.delayed_sync()
            rs.assert_not_called()
            sl.assert_not_called()
        finally:
            holder.close()

    def test_free_lock_sleeps_then_syncs_once(self):
        with mock.patch.object(av, "run_sync") as rs, \
                mock.patch.object(av.time, "sleep") as sl:
            av.delayed_sync()
        sl.assert_called_once_with(av.DELAYED_SYNC_S)
        self.assertEqual(av.DELAYED_SYNC_S, 0.4)
        rs.assert_called_once_with()

    def test_lock_released_before_run_sync(self):
        seen = {}

        def probe():
            with open(self.lock_path(), "a+") as f:
                try:
                    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    seen["free"] = True
                    fcntl.flock(f, fcntl.LOCK_UN)
                except OSError:
                    seen["free"] = False

        with mock.patch.object(av, "run_sync", side_effect=probe), \
                mock.patch.object(av.time, "sleep"):
            av.delayed_sync()
        self.assertEqual(seen, {"free": True})

    def test_lock_held_during_sleep(self):
        seen = {}

        def probe_sleep(_s):
            with open(self.lock_path(), "a+") as f:
                try:
                    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    seen["free"] = True
                except OSError:
                    seen["free"] = False

        with mock.patch.object(av, "run_sync"), \
                mock.patch.object(av.time, "sleep", side_effect=probe_sleep):
            av.delayed_sync()
        self.assertEqual(seen, {"free": False})


class MainSyncClosed(Isolated):
    def test_main_runs_sync_and_spawns_delayed(self):
        agents = [agent("R", "t1"), agent("C", "t1")]
        panes = [pane("R", "t1"), pane("C", "t1", parent="R")]
        h = FakeHerdr(agents, panes, tabs=TABS)
        env = event_env("pane.closed", "C")
        with mock.patch.dict(os.environ, env), \
                mock.patch.object(sys, "argv", ["agent_view.py", "sync-closed"]), \
                mock.patch.object(av.subprocess, "Popen") as popen, \
                mocked(h), contextlib.redirect_stdout(io.StringIO()):
            av.main()
        popen.assert_called_once()
        args, kwargs = popen.call_args
        self.assertEqual(args[0][1:], [os.path.abspath(av.__file__), "delayed-sync"])
        self.assertTrue(kwargs.get("start_new_session"))
        for p in h.methods("pane.report_metadata"):
            if p["pane_id"] == "R":
                self.assertIsNone(p["tokens"].get("subtree"))

    def test_main_with_closed_flag_argument(self):
        with mock.patch.object(sys, "argv", ["agent_view.py", "sync-closed", "--closed", "R"]), \
                mock.patch.object(av, "run_sync") as rs, \
                mock.patch.object(av, "spawn_delayed_sync") as sp:
            av.main()
        rs.assert_called_once_with("R")
        sp.assert_called_once_with()


class Manifest(unittest.TestCase):
    def test_pane_closed_runs_sync_closed(self):
        import tomllib
        with open(os.path.join(ROOT, "herdr-plugin.toml"), "rb") as f:
            events = {e["on"]: e for e in tomllib.load(f)["events"]}
        self.assertEqual(events["pane.closed"]["command"], ["bash", "run.sh", "sync-closed"])


class RunShForwarding(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.dir, "bin"))
        shutil.copy(os.path.join(ROOT, "run.sh"), self.dir)
        with open(os.path.join(self.dir, "bin", "agent_view.py"), "w") as f:
            f.write("import sys\nprint('|'.join(sys.argv[1:]))\n")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def call(self, *args):
        r = subprocess.run(["bash", os.path.join(self.dir, "run.sh"), *args],
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.strip()

    def test_forwards_all_args(self):
        self.assertEqual(self.call("sync-closed", "--closed", "P 1"), "sync-closed|--closed|P 1")

    def test_default_is_cycle(self):
        self.assertEqual(self.call(), "cycle")


if __name__ == "__main__":
    unittest.main()
