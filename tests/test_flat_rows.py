"""I5: modos não-picked publicam linhas planas (sem marca de árvore, sem $sub).
Só `picked` publica "├ "/"└ " e o $sub do root com filhos."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "bin"))
sys.path.insert(0, HERE)
import agent_view as av  # noqa: E402
from _support import Isolated, FakeHerdr, agent, pane, mocked  # noqa: E402

TABS = [{"tab_id": "t1", "label": "dev"}, {"tab_id": "t2", "label": "ops"}]
MARKS = ("\u251c", "\u2514")  # "├", "└"


def publish(mode):
    """Aplica `mode` com R (root de t1), C (filho explícito de R) e A (standalone t2)."""
    agents = [agent("R", "t1", "w1"), agent("C", "t1", "w1"), agent("A", "t2", "w1")]
    panes = [pane("R", "t1", "w1"), pane("C", "t1", "w1", parent="R", label="logs"),
             pane("A", "t2", "w1")]
    h = FakeHerdr(agents, panes, tabs=TABS)
    with mocked(h):
        av.apply_mode(mode)
    return h.tokens()


def texts(tokens):
    return [v for t in tokens.values() for v in t.values() if isinstance(v, str)]


class FlatInNonPickedModes(Isolated):
    def test_active_space_all_have_no_tree_marks_or_sub(self):
        for mode in ("active", "space", "all"):
            with self.subTest(mode=mode):
                tok = publish(mode)
                for pid in ("R", "C", "A"):
                    self.assertIsNone(tok[pid]["sub"], pid)
                    self.assertFalse(tok[pid]["title"].startswith(MARKS), tok[pid]["title"])
                for v in texts(tok):
                    self.assertFalse(v.startswith(MARKS), v)

    def test_child_row_is_plain_tab_label_in_flat_mode(self):
        tok = publish("active")
        self.assertEqual(tok["C"]["title"], "dev")
        self.assertEqual(tok["C"]["space"], "Work")
        self.assertIsNone(tok["R"]["sub"])


class TreeMarksOnlyInPicked(Isolated):
    def test_picked_publishes_marks_and_sub(self):
        tok = publish("picked")
        self.assertEqual(tok["R"]["sub"], "\u251c R")  # display_label de R: cwd "/x/R"
        self.assertTrue(tok["C"]["title"].startswith("\u2514 "))
        self.assertEqual(tok["C"]["title"], "\u2514 logs")
        self.assertIsNone(tok["A"]["sub"])


if __name__ == "__main__":
    unittest.main()
