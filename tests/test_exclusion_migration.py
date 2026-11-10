"""I2/I3: migração de exclusões no sync (README 0.10.0, "Exclusion model").
- I2: id excluído que é (ou virou) filho é descartado, nunca migrado para tab:;
  filho explícito de outra tab não vaza para "tab:" da própria tab.
- Root de tab-fallback excluída migra para "tab:<id>".
- I3: root com filhos explícitos + filhos de tab-fallback vira "tab:<id>" e a
  exclusão sobrevive ao fechamento da root. Sync real via main()."""
import contextlib
import io
import os
import sys
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


def hidden_now(agents, panes):
    """Panes escondidas pela exclusão atual, com a árvore e tabs/spaces reais."""
    space_of = {a["pane_id"]: a["workspace_id"] for a in agents}
    tab_of = {a["pane_id"]: a["tab_id"] for a in agents}
    tree = av.current_tree(agents, panes, True)
    return av.effective_excluded(av.read_excluded(), tree, space_of, tab_of)


class LegacyChildAndCrossTab(Isolated):
    def test_legacy_tab_child_id_dropped_not_migrated(self):
        # C é filho de tab-fallback de R; "C" legado em excluded é descartado.
        av.write_state("picked", ["C"], seen=["R", "C"])
        agents = [agent("R", "t1"), agent("C", "t1")]
        panes = [pane("R", "t1"), pane("C", "t1")]
        run_sync(FakeHerdr(agents, panes, tabs=TABS))
        self.assertEqual(av.read_excluded(), [])

    def test_cross_tab_explicit_child_gets_no_tab_entry(self):
        # P era standalone em t2 e excluída; ganha pai explícito R (t1).
        # Não pode virar "tab:t2" nem "tab:t1": é descartada.
        av.write_state("picked", ["P"], seen=["R", "D", "P"])
        agents = [agent("R", "t1"), agent("D", "t1"), agent("P", "t2")]
        run_sync(FakeHerdr(agents, [pane("R", "t1"), pane("D", "t1"), pane("P", "t2")],
                           tabs=TABS))
        self.assertEqual(av.read_excluded(), ["P"])  # ainda standalone: mantida
        agents2 = [agent("R", "t1"), agent("D", "t1"), agent("P", "t2")]
        panes2 = [pane("R", "t1"), pane("D", "t1"), pane("P", "t2", parent="D")]
        run_sync(FakeHerdr(agents2, panes2, tabs=TABS))
        ex = av.read_excluded()
        self.assertEqual(ex, [])
        self.assertFalse(any(e.startswith("tab:") for e in ex))
        self.assertEqual(hidden_now(agents2, panes2), [])

    def test_excluded_tab_fallback_root_migrates_to_tab_entry(self):
        av.write_state("picked", ["R"], seen=["R", "C"])
        agents = [agent("R", "t1"), agent("C", "t1")]
        panes = [pane("R", "t1"), pane("C", "t1")]
        run_sync(FakeHerdr(agents, panes, tabs=TABS))
        self.assertEqual(av.read_excluded(), ["tab:t1"])
        self.assertEqual(hidden_now(agents, panes), ["C", "R"])


class RootWithExplicitAndFallbackChildren(Isolated):
    """t1: R (root), C (filho explícito via token), F (filho de tab-fallback)."""

    def setUp(self):
        super().setUp()
        self.agents = [agent("R", "t1"), agent("C", "t1"), agent("F", "t1")]
        self.panes = [pane("R", "t1"), pane("C", "t1", parent="R"), pane("F", "t1")]
        av.write_state("picked", ["R"], seen=["R", "C", "F"])

    def test_root_with_both_child_kinds_migrates_to_tab_entry(self):
        run_sync(FakeHerdr(self.agents, self.panes, tabs=TABS))
        self.assertEqual(av.read_excluded(), ["tab:t1"])
        self.assertEqual(hidden_now(self.agents, self.panes), ["C", "F", "R"])

    def test_exclusion_survives_root_closing(self):
        run_sync(FakeHerdr(self.agents, self.panes, tabs=TABS))
        # R fecha (sai de agent.list e pane.list); C e F continuam na tab t1.
        agents2 = [agent("C", "t1"), agent("F", "t1")]
        panes2 = [pane("C", "t1"), pane("F", "t1")]
        run_sync(FakeHerdr(agents2, panes2, tabs=TABS))
        self.assertEqual(av.read_excluded(), ["tab:t1"])
        self.assertEqual(hidden_now(agents2, panes2), ["C", "F"])


if __name__ == "__main__":
    unittest.main()
