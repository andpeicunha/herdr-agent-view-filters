"""Coordenadora exibe sempre '◆ orchestrator'; filhas nunca usam o terminal_title
generico 'orchestrator' (label, senao basename do cwd); nome do grupo = tab."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "bin"))
sys.path.insert(0, HERE)
import agent_view as av  # noqa: E402
from _support import Isolated, FakeHerdr, agent, pane, mocked  # noqa: E402

TABS = [{"tab_id": "t1", "label": "plugins"}]
NUM_TABS = [{"tab_id": "t1", "label": "1"}]
COORD = "◆ orchestrator"


def run(h, mode="picked"):
    with mocked(h):
        av.apply_mode(mode, [])
    return h.tokens()


def fake(tabs=TABS, r_label="agent-view-filters", c_label=None, c_title="orchestrator",
         c_cwd="/work/my-repo"):
    return FakeHerdr(
        [agent("R", "t1", title="orchestrator", cwd="/work/agent-view-filters"),
         agent("C", "t1", title=c_title, cwd=c_cwd)],
        [pane("R", "t1", label=r_label), pane("C", "t1", label=c_label)],
        tabs=tabs)


class CoordinatorDisplay(Isolated):
    def test_picked_sub_is_marker_orchestrator_despite_label(self):
        t = run(fake())
        self.assertEqual((t["R"]["subtree"], t["R"]["coord"]), ("├", COORD))
        self.assertIsNone(t["R"]["sub"])  # nome so em $coord
        self.assertIsNone(t["C"]["coord"])

    def test_other_modes_row_shows_orchestrator_when_title_falls_to_label(self):
        # tab numerica -> o titulo da raiz cai no display label
        for mode in av.MODES:
            if mode == "picked":
                continue
            with self.subTest(mode=mode):
                t = run(fake(tabs=NUM_TABS), mode)
                self.assertEqual(t["R"]["coord"], COORD)
                self.assertNotIn("◆", t["R"]["title"])
                self.assertIsNone(t["R"]["subtree"])

    def test_child_generic_title_uses_label(self):
        t = run(fake(c_label="worker-x"))
        self.assertEqual((t["C"]["tree"], t["C"]["title"]), ("└", "worker-x"))

    def test_child_without_label_uses_cwd_basename(self):
        t = run(fake())
        self.assertEqual((t["C"]["tree"], t["C"]["title"]), ("└", "my-repo"))

    def test_group_name_stays_tab_label(self):
        t = run(fake())
        self.assertEqual(t["R"]["title"], "plugins")


if __name__ == "__main__":
    unittest.main()
