"""I5: modos não-picked publicam linhas planas (sem tree/subtree/coord).
Só `picked` publica `tree` ("├"/"└" em filha), `subtree` ("├" em root com
filhos) e `coord` (só na coordenadora). title/sub nunca carregam marca."""
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
        self.assertEqual(tok["R"]["subtree"], "\u251c")
        self.assertIsNone(tok["R"]["tree"])
        self.assertEqual(tok["R"]["coord"], "\u25c6 R")
        self.assertIsNone(tok["R"]["sub"])
        self.assertEqual(tok["C"]["tree"], "\u2514")
        self.assertEqual(tok["C"]["title"], "logs")
        self.assertIsNone(tok["C"]["coord"])
        self.assertIsNone(tok["A"]["sub"])
        self.assertIsNone(tok["A"]["tree"])
        self.assertIsNone(tok["A"]["coord"])


def run_publish(agents, panes, tabs=TABS):
    """publish_tokens() (modo picked, config padrão) com FakeHerdr; -> FakeHerdr."""
    h = FakeHerdr(agents, panes, tabs=tabs)
    with mocked(h):
        av.publish_tokens()
    return h


def feed_back(panes, h):
    """Simula o Herdr guardando os tokens publicados: campos None somem."""
    by = h.tokens()
    for p in panes:
        merged = {**p.get("tokens", {}), **by.get(p["pane_id"], {})}
        p["tokens"] = {k: v for k, v in merged.items() if v is not None}


class TreeCoordLifecycle(Isolated):
    def test_two_children_tree_mark_is_tee_then_corner(self):
        agents = [agent("R", "t1", "w1"), agent("C1", "t1", "w1"), agent("C2", "t1", "w1")]
        panes = [pane("R", "t1", "w1"), pane("C1", "t1", "w1", parent="R", label="logs"),
                 pane("C2", "t1", "w1", parent="R", label="vim")]
        tok = run_publish(agents, panes).tokens()
        self.assertEqual(tok["C1"]["tree"], "\u251c")  # não-último: ├
        self.assertEqual(tok["C2"]["tree"], "\u2514")  # último: └
        self.assertEqual((tok["C1"]["title"], tok["C2"]["title"]), ("logs", "vim"))
        self.assertEqual(tok["R"]["subtree"], "\u251c")

    def test_tree_cleared_when_child_becomes_root(self):
        agents = [agent("R", "t1", "w1"), agent("C", "t1", "w1")]
        panes = [pane("R", "t1", "w1"), pane("C", "t1", "w1", parent="R", label="logs")]
        h1 = run_publish(agents, panes)
        self.assertEqual(h1.tokens()["C"]["tree"], "\u2514")
        feed_back(panes, h1)
        # C deixa de ser filha: sem parent e em outra tab (group_by_tab agrupa
        # filhos da mesma tab da raiz, mesmo sem token parent)
        panes[1]["tokens"].pop("parent", None)
        panes[1]["tab_id"] = agents[1]["tab_id"] = "t2"
        h2 = run_publish(agents, panes)
        self.assertIn("C", h2.tokens(), "C não republicou ao perder a marca")
        self.assertIsNone(h2.tokens()["C"]["tree"])
        self.assertIsNone(h2.tokens()["C"]["subtree"])

    def test_coord_cleared_when_coordinator_loses_children_then_not_republished(self):
        agents = [agent("R", "t1", "w1"), agent("C", "t1", "w1")]
        panes = [pane("R", "t1", "w1"), pane("C", "t1", "w1", parent="R", label="logs")]
        h1 = run_publish(agents, panes)
        self.assertEqual(h1.tokens()["R"]["coord"], "\u25c6 R")
        feed_back(panes, h1)
        # R sem filhos: deixa de ser coordenadora
        agents, panes = [agent("R", "t1", "w1")], [pane("R", "t1", "w1")]
        feed_back(panes, h1)
        h2 = run_publish(agents, panes)
        self.assertIn("R", h2.tokens(), "R não republicou ao perder coord")
        self.assertIsNone(h2.tokens()["R"]["coord"])
        self.assertIsNone(h2.tokens()["R"]["subtree"])
        # já limpo: nova sincronização não republica R
        feed_back(panes, h2)
        h3 = run_publish(agents, panes)
        self.assertNotIn("R", h3.tokens())


if __name__ == "__main__":
    unittest.main()
