"""I1: pane vivo em pane.list mas ausente de agent.list durante o sync mantém o
estado (first_seen, tab_roots, parents, seen, excluded). Pane ausente de
pane.list é morta e é podada. pane.list vazio não poda nada. Sync real via main()."""
import contextlib
import io
import os
import sys
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "bin"))
sys.path.insert(0, HERE)
import agent_view as av  # noqa: E402
from _support import Isolated, FakeHerdr, agent, pane, mocked  # noqa: E402

TABS = [{"tab_id": "t1"}, {"tab_id": "t2"}]


def run_sync(h):
    out = io.StringIO()
    with mocked(h), mock.patch.object(sys, "argv", ["agent_view.py", "sync"]), \
            contextlib.redirect_stdout(out):
        av.main()
    return out.getvalue()


class _Base(Isolated):
    def seed(self):
        # R (root de t1), X (filho de R por token guardado), S (root de t2, excluída).
        av.write_state("picked", ["S"], seen=["R", "S", "X"],
                       first_seen={"R": 1, "X": 2, "S": 3},
                       tab_roots={"t1": "R", "t2": "S"}, parents={"X": "R"},
                       published_at=time.time())

    def state_no_clock(self):
        st = self.state_file()
        st.pop("published_at", None)
        return st


class PaneAliveButNotAgent(_Base):
    def test_state_kept_while_pane_is_alive(self):
        self.seed()
        # R sumiu de agent.list (processo do agente reiniciou), mas segue em pane.list.
        h = FakeHerdr([agent("X", "t1"), agent("S", "t2")],
                      [pane("R", "t1"), pane("X", "t1"), pane("S", "t2")],
                      tabs=TABS)
        run_sync(h)
        st = self.state_no_clock()
        self.assertEqual(st["first_seen"], {"R": 1, "X": 2, "S": 3})
        self.assertEqual(st["tab_roots"], {"t1": "R", "t2": "S"})
        self.assertEqual(st["parents"], {"X": "R"})
        self.assertEqual(st["excluded"], ["S"])
        self.assertEqual(sorted(st["seen"]), ["R", "S", "X"])

    def test_excluded_pane_alive_but_not_agent_keeps_exclusion(self):
        self.seed()
        h = FakeHerdr([agent("R", "t1")],
                      [pane("R", "t1"), pane("X", "t1"), pane("S", "t2")],
                      tabs=TABS)
        run_sync(h)
        self.assertEqual(av.read_excluded(), ["S"])


class TrulyDeadPanePruned(_Base):
    def test_pane_absent_from_pane_list_is_pruned(self):
        self.seed()
        # S morreu: some de pane.list e de agent.list.
        h = FakeHerdr([agent("R", "t1"), agent("X", "t1")],
                      [pane("R", "t1"), pane("X", "t1")],
                      tabs=TABS)
        run_sync(h)
        st = self.state_no_clock()
        self.assertNotIn("S", st["first_seen"])
        self.assertNotIn("t2", st.get("tab_roots", {}))
        self.assertNotIn("S", st["seen"])
        self.assertEqual(st["excluded"], [])
        self.assertEqual(st["first_seen"], {"R": 1, "X": 2})


class PruneExcludedAlone(_Base):
    """prune_excluded() sozinho (sem sync_new_agents antes): poda sua própria lista."""

    def test_dead_pane_space_and_tab_entries_pruned_without_sync(self):
        av.write_state("picked", ["R", "GONE", "space:zz", "tab:t9", "space:w1", "tab:t1"],
                       seen=["R"])
        h = FakeHerdr([agent("R", "t1")], [pane("R", "t1")], tabs=TABS)
        with mocked(h):
            kept = av.prune_excluded()
        self.assertEqual(kept, ["R", "space:w1", "tab:t1"])
        self.assertEqual(av.read_excluded(), ["R", "space:w1", "tab:t1"])

    def test_pane_list_failure_prunes_nothing(self):
        av.write_state("picked", ["GONE"], seen=["GONE"])
        h = FakeHerdr([agent("R", "t1")], [], tabs=TABS)
        with mocked(h):
            kept = av.prune_excluded()
        self.assertEqual(kept, ["GONE"])


class EmptyPaneListNoPrune(_Base):
    def test_empty_pane_list_prunes_nothing(self):
        self.seed()
        h = FakeHerdr([agent("X", "t1")], [], tabs=TABS)
        run_sync(h)
        st = self.state_no_clock()
        self.assertEqual(st["excluded"], ["S"])
        self.assertEqual(st["first_seen"], {"R": 1, "X": 2, "S": 3})
        self.assertEqual(st["tab_roots"], {"t1": "R", "t2": "S"})
        self.assertEqual(st["parents"], {"X": "R"})
        self.assertEqual(sorted(st["seen"]), ["R", "S", "X"])


if __name__ == "__main__":
    unittest.main()
