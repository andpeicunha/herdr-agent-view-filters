"""Ordem estável única: space -> tab -> root -> filhos (layout).

Este arquivo tinha os testes de ordem manual (move_unit, saved order); foram
substituídos. Nome mantido porque não há como remover arquivo aqui: pode ser
renomeado para test_order.py depois.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "bin"))
sys.path.insert(0, HERE)
import agent_view as av  # noqa: E402
from _support import Isolated, FakeHerdr, agent, pane, mocked  # noqa: E402


class SpaceSequenceTabOrder(unittest.TestCase):
    def test_tab_rank_beats_layout_index(self):
        # (pane_id, space_key, tab_rank, layout_idx)
        self.assertEqual(av.space_sequence([("A", 0, 1, 0), ("B", 0, 0, 5)]), ["B", "A"])

    def test_spaces_sorted_by_key(self):
        self.assertEqual(av.space_sequence([("X", 2, 0, 0), ("Y", 0, 0, 0), ("Z", 1, 0, 0)]),
                         ["Y", "Z", "X"])

    def test_children_follow_root_in_layout_order(self):
        panes = [("R", 0, 0, 0), ("C2", 0, 0, 3), ("C1", 0, 0, 2), ("S", 0, 1, 0)]
        self.assertEqual(av.space_sequence(panes, {"C1": "R", "C2": "R"}),
                         ["R", "C1", "C2", "S"])

    def test_child_in_other_space_key_follows_root(self):
        panes = [("R", 0, 0, 0), ("C", 1, 0, 1), ("S", 1, 0, 2)]
        self.assertEqual(av.space_sequence(panes, {"C": "R"}), ["R", "C", "S"])

    def test_child_without_live_root_is_standalone(self):
        self.assertEqual(av.space_sequence([("C", 0, 0, 0), ("S", 0, 0, 1)], {"C": "GONE"}),
                         ["C", "S"])


class LayoutSequence(unittest.TestCase):
    AGENTS = [agent("A", "t1", "w1"), agent("B", "t2", "w1"), agent("X", "t3", "w2")]
    PANES = [pane("A", "t1", "w1"), pane("B", "t2", "w1"), pane("X", "t3", "w2")]

    def test_tab_order_comes_from_tab_list_not_ids_or_layout(self):
        tabs = {"t2": {}, "t1": {}, "t3": {}}  # tab.list: t2 first
        seq, _ = av.layout_sequence(self.AGENTS, self.PANES, tabs, {"w1": 0, "w2": 1}, {})
        self.assertEqual(seq, ["B", "A", "X"])

    def test_workspace_order_from_sidebar_index(self):
        tabs = {"t1": {}, "t2": {}, "t3": {}}
        seq, _ = av.layout_sequence(self.AGENTS, self.PANES, tabs, {"w2": 0, "w1": 1}, {})
        self.assertEqual(seq, ["X", "A", "B"])

    def test_child_takes_root_space_key_and_follows_it(self):
        tabs = {"t1": {}, "t2": {}, "t3": {}}
        seq, key = av.layout_sequence(self.AGENTS, self.PANES, tabs, {"w1": 0, "w2": 1},
                                      {"A": "B"})
        self.assertEqual(seq, ["B", "A", "X"])
        self.assertEqual(key["A"], key["B"])


class PublishOrderTokens(Isolated):
    """Cenário: layout [A, R, C, D, S]; tab.list t1 (dev), t2 (ops), t3 (home);
    C filho explícito de R; D na mesma tab (fallback)."""

    def scenario(self, group_by_tab):
        agents = [agent("A", "t2", "w1"), agent("R", "t1", "w1"),
                  agent("C", "t1", "w1", title="zsh"), agent("D", "t1", "w1", title="vim"),
                  agent("S", "t3", "w2")]
        panes = [pane("A", "t2", "w1"), pane("R", "t1", "w1"),
                 pane("C", "t1", "w1", parent="R", label="logs"),
                 pane("D", "t1", "w1"), pane("S", "t3", "w2")]
        tabs = [{"tab_id": "t1", "label": "dev"}, {"tab_id": "t2", "label": "ops"},
                {"tab_id": "t3", "label": "home"}]
        self.write_config(f"group_by_tab = {'true' if group_by_tab else 'false'}\n")
        h = FakeHerdr(agents, panes, tabs=tabs)
        with mocked(h):
            n = av.publish_tokens()
        return n, h.tokens()

    def test_group_by_tab_on_order_space_tab_root_children(self):
        n, t = self.scenario(True)
        self.assertEqual(n, 5)
        self.assertEqual({k: (v["space_rank"], v["order"]) for k, v in t.items()}, {
            "R": ("0000", "0000"),
            "C": ("0000", "0001"),
            "D": ("0000", "0002"),
            "A": ("0000", "0003"),
            "S": ("0001", "0000"),
        })
        # layout D: root = (tab, space, sub "├ repo" only with children)
        self.assertEqual({k: (v["title"], v["space"], v["sub"]) for k, v in t.items()}, {
            "R": ("dev", "Work", "├ ◆ orchestrator"),
            "C": ("├ logs", None, None),
            "D": ("└ vim", None, None),
            "A": ("ops", "Work", None),
            "S": ("home", "Home", None),
        })
        self.assertTrue(all(v["tree_ws"] is None for v in t.values()))

    def test_group_by_tab_off_only_explicit_children_move(self):
        _, t = self.scenario(False)
        self.assertEqual({k: v["order"] for k, v in t.items()},
                         {"R": "0000", "C": "0001", "D": "0002", "A": "0003", "S": "0000"})
        # D virou standalone: título = tab, sem item
        self.assertEqual((t["D"]["title"], t["D"]["space"], t["D"]["sub"]),
                         ("dev", "Work", None))
        # R tem filho explícito: sub "├ repo"; C é o único filho -> "└ "
        self.assertEqual((t["R"]["title"], t["R"]["sub"]), ("dev", "├ ◆ orchestrator"))
        self.assertEqual((t["C"]["title"], t["C"]["space"], t["C"]["sub"]),
                         ("└ logs", None, None))
        self.assertTrue(all(v["tree_ws"] is None for v in t.values()))


class ApplyModeSort(Isolated):
    AGENTS = [agent("R", "t1", "w1", status="working"), agent("S", "t2", "w2")]
    PANES = [pane("R", "t1", "w1"), pane("S", "t2", "w2")]
    TABS = [{"tab_id": "t1"}, {"tab_id": "t2"}]

    def apply(self, mode, excluded=None):
        h = FakeHerdr(self.AGENTS, self.PANES, tabs=self.TABS)
        with mocked(h):
            av.apply_mode(mode, excluded)
        return h

    def test_single_sort_for_every_filtered_mode(self):
        for mode in ("active", "space", "picked"):
            with self.subTest(mode=mode):
                h = self.apply(mode, [])
                sets = h.methods("agent.view.set")
                self.assertEqual(len(sets), 1)
                self.assertEqual(sets[0]["sort"], av.SORT)
                self.assertEqual(sets[0]["label"], mode)

    def test_sort_definition(self):
        self.assertEqual(av.SORT, [
            {"field": {"token": "space_rank"}, "order": "asc"},
            {"field": {"token": "order"}, "order": "asc"},
            {"field": "pane_order", "order": "asc"},
        ])

    def test_filters_unchanged(self):
        self.assertEqual(self.apply("active").methods("agent.view.set")[0]["filter"],
                         av.FILTERS["active"])
        self.assertEqual(self.apply("space").methods("agent.view.set")[0]["filter"],
                         av.FILTERS["space"])

    def test_all_clears_view_and_sets_nothing(self):
        h = self.apply("all")
        self.assertEqual(len(h.methods("agent.view.clear")), 1)
        self.assertEqual(h.methods("agent.view.set"), [])

    def test_picked_empty_exclusion_is_match_everything(self):
        flt = self.apply("picked", []).methods("agent.view.set")[0]["filter"]
        self.assertEqual(flt, {"op": "not", "filter": {"op": "in", "field": "pane_id",
                                                       "values": ["__none__"]}})


class ManualOrderRemoved(unittest.TestCase):
    def test_removed_apis_are_gone(self):
        for name in ("move_unit", "move_in_space", "move_grouped", "SORT_MANUAL",
                     "read_order", "read_space_order", "write_order", "prune_order"):
            with self.subTest(name=name):
                self.assertFalse(hasattr(av, name))


if __name__ == "__main__":
    unittest.main()
