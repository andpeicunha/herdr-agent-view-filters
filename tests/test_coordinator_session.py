"""Captura/persistência de agent_session da coordenadora em state.json e
arquivamento em closed_coordinators no pane.closed / pane.exited."""
import contextlib
import io
import json
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "bin"))
sys.path.insert(0, HERE)
import agent_view as av  # noqa: E402
from _support import Isolated, FakeHerdr, agent, pane, mocked  # noqa: E402

TABS = [{"tab_id": "t1", "label": "dev"}]
SESS = {"agent": "claude", "kind": "id", "source": "herdr:claude",
        "value": "6966aa8e-1111-2222-3333-444455556666"}


def fake(session=SESS, agent_name="claude"):
    r = pane("R", "t1", label="orch")
    if session:
        r["agent_session"] = dict(session)
    ra = agent("R", "t1")
    ra["agent"] = agent_name
    return FakeHerdr([ra, agent("C", "t1")], [r, pane("C", "t1")], tabs=TABS)


def sync(h, event=None, pane_id=None):
    env = {}
    argv = ["agent_view.py", "sync"]
    if event:
        argv = ["agent_view.py", "sync-closed"]
        env = {"HERDR_PLUGIN_EVENT": event,
               "HERDR_PLUGIN_EVENT_JSON": json.dumps(
                   {"event": event.replace(".", "_"), "data": {"pane_id": pane_id}})}
    with mocked(h), mock.patch.object(sys, "argv", argv), \
            mock.patch.dict(os.environ, env), \
            mock.patch.object(av, "spawn_delayed_sync"), \
            contextlib.redirect_stdout(io.StringIO()):
        av.main()


def close_pane(h, pid):
    h.agents = [a for a in h.agents if a["pane_id"] != pid]
    h.panes = [p for p in h.panes if p["pane_id"] != pid]


class Capture(Isolated):
    def test_sync_persists_coordinator_info(self):
        sync(fake())
        c = self.state_file()["coordinators"]
        self.assertEqual(list(c), ["R"])
        self.assertEqual(c["R"]["agent_session"], SESS)
        self.assertEqual(c["R"]["label"], "orch")
        self.assertEqual(c["R"]["tab"], "t1")
        self.assertEqual(c["R"]["cwd"], "/x/R")
        self.assertIsInstance(c["R"]["last_seen"], float)

    def test_child_is_not_recorded(self):
        sync(fake())
        self.assertNotIn("C", self.state_file()["coordinators"])

    def test_session_survives_a_sync_without_session(self):
        h = fake()
        sync(h)
        del h.panes[0]["agent_session"]
        sync(h)
        self.assertEqual(self.state_file()["coordinators"]["R"]["agent_session"], SESS)

    def test_coordinators_survive_other_state_writes(self):
        sync(fake())
        av.write_mode("all")
        av.write_excluded(["x"])
        self.assertIn("R", self.state_file()["coordinators"])

    def test_unchanged_info_is_not_rewritten(self):
        h = fake()
        with mock.patch.object(av.time, "time", return_value=1000.0):
            sync(h)
        before = self.state_file()["coordinators"]["R"]["last_seen"]
        with mock.patch.object(av.time, "time", return_value=1010.0), \
                mock.patch.object(av, "write_state") as w:
            sync(h)
        self.assertEqual(before, 1000.0)
        for call in w.call_args_list:
            self.assertNotIn("coordinators", call.kwargs)

    def test_last_seen_refreshed_after_interval(self):
        h = fake()
        with mock.patch.object(av.time, "time", return_value=1000.0):
            sync(h)
        with mock.patch.object(av.time, "time",
                               return_value=1000.0 + av.COORD_REFRESH_S + 1):
            sync(h)
        self.assertEqual(self.state_file()["coordinators"]["R"]["last_seen"],
                         1000.0 + av.COORD_REFRESH_S + 1)

    def test_listing_failure_does_not_archive(self):
        h = fake()
        sync(h)
        h.panes = []  # pane.list falhou/vazio
        sync(h)
        st = self.state_file()
        self.assertIn("R", st["coordinators"])
        self.assertNotIn("closed_coordinators", st)


class ClosedArchive(Isolated):
    def check_archived(self, event):
        h = fake()
        sync(h)
        close_pane(h, "R")
        sync(h, event, "R")
        st = self.state_file()
        self.assertNotIn("R", st.get("coordinators", {}))
        (e,) = st["closed_coordinators"]
        self.assertEqual(e["pane_id"], "R")
        self.assertEqual(e["agent_session"], SESS)
        self.assertEqual(e["label"], "orch")
        self.assertEqual(e["resume"], f"claude --resume {SESS['value']}")
        self.assertIsInstance(e["closed_at"], float)

    def test_pane_closed(self):
        self.check_archived("pane.closed")

    def test_pane_exited(self):
        self.check_archived("pane.exited")

    def test_event_while_pane_still_listed_is_archived(self):
        # Herdr emite pane.closed antes de pane.list parar de devolver o pane
        h = fake()
        sync(h)
        sync(h, "pane.closed", "R")
        st = self.state_file()
        self.assertEqual([e["pane_id"] for e in st["closed_coordinators"]], ["R"])

    def test_delayed_sync_does_not_duplicate(self):
        h = fake()
        sync(h)
        close_pane(h, "R")
        sync(h, "pane.closed", "R")
        sync(h)  # delayed-sync = run_sync() sem closed
        sync(h)
        self.assertEqual(len(self.state_file()["closed_coordinators"]), 1)

    def test_non_claude_has_no_resume(self):
        h = fake(session={"agent": "codex", "kind": "id", "source": "x", "value": "abc"},
                 agent_name="codex")
        sync(h)
        close_pane(h, "R")
        sync(h, "pane.closed", "R")
        (e,) = self.state_file()["closed_coordinators"]
        self.assertNotIn("resume", e)
        self.assertEqual(e["agent_session"]["value"], "abc")

    def test_unsafe_session_value_gets_no_resume(self):
        self.assertIsNone(av.resume_command(
            {"agent_session": {"agent": "claude", "value": "x; rm -rf /"}}))

    def test_child_close_does_not_archive_coordinator(self):
        h = fake()
        sync(h)
        close_pane(h, "C")
        sync(h, "pane.closed", "C")
        st = self.state_file()
        self.assertNotIn("closed_coordinators", st)
        self.assertNotIn("R", st.get("coordinators", {}))  # sem filhos: esquecida

    def test_list_is_bounded(self):
        for i in range(av.CLOSED_COORD_MAX + 5):
            pid = f"R{i}"
            h = FakeHerdr([agent(pid, "t1"), agent("K", "t1")],
                          [pane(pid, "t1"), pane("K", "t1")], tabs=TABS)
            av.write_state("picked", [], tab_roots={"t1": pid})
            sync(h)
            close_pane(h, pid)
            sync(h, "pane.closed", pid)
        lst = self.state_file()["closed_coordinators"]
        self.assertEqual(len(lst), av.CLOSED_COORD_MAX)
        self.assertEqual(lst[-1]["pane_id"], f"R{av.CLOSED_COORD_MAX + 4}")


class ManifestEvents(unittest.TestCase):
    def test_pane_exited_registered(self):
        text = open(os.path.join(HERE, "..", "herdr-plugin.toml")).read()
        self.assertIn('on = "pane.exited"\ncommand = ["bash", "run.sh", "sync-closed"]',
                      text)

    def test_env_accepts_exited(self):
        env = {"HERDR_PLUGIN_EVENT": "pane.exited",
               "HERDR_PLUGIN_EVENT_JSON": json.dumps({"data": {"pane_id": "P"}})}
        with mock.patch.dict(os.environ, env):
            self.assertEqual(av.closed_pane_from_env(), "P")

    def test_env_accepts_underscore_events(self):
        for name in ("pane_closed", "pane_exited"):
            with self.subTest(event=name):
                env = {"HERDR_PLUGIN_EVENT": name,
                       "HERDR_PLUGIN_EVENT_JSON": json.dumps({"data": {"pane_id": "P"}})}
                with mock.patch.dict(os.environ, env):
                    self.assertEqual(av.closed_pane_from_env(), "P")


if __name__ == "__main__":
    unittest.main()
