"""Agrupamento (parent token + fallback por tab), exclusão `space:` e tree_ws."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "bin"))
sys.path.insert(0, HERE)
import agent_view as av  # noqa: E402
from _support import Isolated, FakeHerdr, agent, pane, mocked  # noqa: E402


# ---- build_tree (parent token explícito) ----------------------------------

class BuildTree(unittest.TestCase):
    def test_direct_child(self):
        self.assertEqual(av.build_tree(["r", "c"], {"c": "r"}), {"c": "r"})

    def test_dead_parent_means_standalone(self):
        self.assertEqual(av.build_tree(["c"], {"c": "GONE"}), {})

    def test_invalid_tokens_ignored(self):
        self.assertEqual(av.build_tree(["r", "c"], {"c": 5}), {})
        self.assertEqual(av.build_tree(["r", "c"], {"c": ""}), {})
        self.assertEqual(av.build_tree(["r", "c"], {"c": "c"}), {})
        self.assertEqual(av.build_tree(["a"], None), {})

    def test_grandchild_flattens_to_root(self):
        self.assertEqual(av.build_tree(["a", "b", "c"], {"c": "b", "b": "a"}),
                         {"c": "a", "b": "a"})

    def test_dead_middle_makes_child_point_to_middle(self):
        self.assertEqual(av.build_tree(["a", "b"], {"a": "b", "b": "GONE"}), {"a": "b"})

    def test_cycles_stay_standalone(self):
        self.assertEqual(av.build_tree(["a", "b"], {"a": "b", "b": "a"}), {})
        self.assertEqual(av.build_tree(["a", "b", "c"], {"a": "b", "b": "c", "c": "b"}), {})


# ---- tab_parents (fallback por tab, pura) ---------------------------------

class TabParents(unittest.TestCase):
    def test_first_pane_of_each_tab_is_root(self):
        self.assertEqual(av.tab_parents([("A", "t1"), ("B", "t1"), ("C", "t2"), ("D", "t2")]),
                         {"B": "A", "D": "C"})

    def test_layout_order_decides_root(self):
        self.assertEqual(av.tab_parents([("B", "t1"), ("A", "t1")]), {"A": "B"})

    def test_alone_in_tab_is_standalone(self):
        self.assertEqual(av.tab_parents([("A", "t1"), ("B", "t2")]), {})

    def test_pane_without_tab_is_left_out(self):
        self.assertEqual(av.tab_parents([("A", None), ("B", None), ("C", "t")]), {})

    def test_explicit_child_skipped_never_becomes_root(self):
        self.assertEqual(av.tab_parents([("A", "t1"), ("B", "t1"), ("C", "t1")], skip={"A"}),
                         {"C": "B"})


# ---- current_tree: on/off, explícito vence tab ----------------------------

class CurrentTree(Isolated):
    def test_tab_fallback_on_groups_per_tab(self):
        agents = [agent("A", "t1"), agent("B", "t1"), agent("C", "t2")]
        panes = [pane("A", "t1"), pane("B", "t1"), pane("C", "t2")]
        self.assertEqual(av.current_tree(agents, panes, group_by_tab=True), {"B": "A"})

    def test_tab_fallback_off_groups_nothing(self):
        agents = [agent("A", "t1"), agent("B", "t1"), agent("C", "t2")]
        panes = [pane("A", "t1"), pane("B", "t1"), pane("C", "t2")]
        self.assertEqual(av.current_tree(agents, panes, group_by_tab=False), {})

    def test_config_drives_default_group_by_tab(self):
        agents = [agent("A", "t1"), agent("B", "t1")]
        panes = [pane("A", "t1"), pane("B", "t1")]
        self.write_config("group_by_tab = false\n")
        self.assertEqual(av.current_tree(agents, panes), {})
        self.write_config("")
        self.assertEqual(av.current_tree(agents, panes), {"B": "A"})

    def test_explicit_parent_beats_tab_on_and_off(self):
        agents = [agent("A", "t1"), agent("B", "t1"), agent("X", "t2")]
        panes = [pane("A", "t1"), pane("B", "t1", parent="X"), pane("X", "t2")]
        self.assertEqual(av.current_tree(agents, panes, group_by_tab=True), {"B": "X"})
        self.assertEqual(av.current_tree(agents, panes, group_by_tab=False), {"B": "X"})

    def test_explicit_parent_in_same_tab_keeps_tab_root(self):
        agents = [agent("A", "t1"), agent("B", "t1"), agent("C", "t1")]
        panes = [pane("A", "t1"), pane("B", "t1", parent="A"), pane("C", "t1")]
        self.assertEqual(av.current_tree(agents, panes, group_by_tab=True),
                         {"B": "A", "C": "A"})
        self.assertEqual(av.current_tree(agents, panes, group_by_tab=False), {"B": "A"})

    def test_explicit_parent_that_is_tab_child_flattens_to_tab_root(self):
        # B -> C (explicit), C is a tab child of A (first pane of t1).
        agents = [agent("B", "t1"), agent("A", "t1"), agent("C", "t1")]
        panes = [pane("B", "t1", parent="C"), pane("A", "t1"), pane("C", "t1")]
        self.assertEqual(av.current_tree(agents, panes, group_by_tab=True),
                         {"B": "A", "C": "A"})
        self.assertEqual(av.current_tree(agents, panes, group_by_tab=False), {"B": "C"})

    def test_dead_explicit_parent_falls_back_to_tab(self):
        agents = [agent("A", "t1"), agent("B", "t1")]
        panes = [pane("A", "t1"), pane("B", "t1", parent="GONE")]
        self.assertEqual(av.current_tree(agents, panes, group_by_tab=True), {"B": "A"})
        self.assertEqual(av.current_tree(agents, panes, group_by_tab=False), {})

    def test_root_closed_next_pane_of_tab_becomes_root(self):
        agents = [agent("B", "t1"), agent("C", "t1")]
        panes = [pane("B", "t1"), pane("C", "t1")]
        self.assertEqual(av.current_tree(agents, panes, group_by_tab=True), {"C": "B"})

    def test_agent_without_tab_is_standalone(self):
        agents = [agent("A", "t1"), agent("N", None)]
        panes = [pane("A", "t1"), pane("N", None)]
        self.assertEqual(av.current_tree(agents, panes, group_by_tab=True), {})


# ---- read_group_by_tab (config) -------------------------------------------

class ReadGroupByTab(Isolated):
    def test_default_true_when_missing(self):
        self.assertTrue(av.read_group_by_tab())

    def test_false_and_true(self):
        self.write_config("group_by_tab = false\n")
        self.assertFalse(av.read_group_by_tab())
        self.write_config("group_by_tab = true\n")
        self.assertTrue(av.read_group_by_tab())

    def test_invalid_values_fall_back_to_true(self):
        for text in ('group_by_tab = "false"\n', "group_by_tab = 0\n", "group_by_tab = \n",
                     "not = = toml"):
            with self.subTest(text=text):
                self.write_config(text)
                self.assertTrue(av.read_group_by_tab())


# ---- effective_excluded: root, space:, filho legado -----------------------

class EffectiveExcluded(unittest.TestCase):
    def test_root_excluded_hides_children(self):
        self.assertEqual(av.effective_excluded(["R"], {"C": "R"}, {"R": "w1", "C": "w1"}),
                         ["C", "R"])

    def test_child_id_in_excluded_is_ignored(self):
        self.assertEqual(av.effective_excluded(["C"], {"C": "R"}, {"R": "w1", "C": "w1"}), [])

    def test_space_hides_roots_and_their_children(self):
        self.assertEqual(
            av.effective_excluded(["space:w1"], {"C": "R"}, {"R": "w1", "C": "w1", "S": "w2"}),
            ["C", "R"])

    def test_space_entry_of_child_workspace_does_not_hide_child(self):
        # C lives in w2 (child cell), but follows its root R in w1.
        self.assertEqual(
            av.effective_excluded(["space:w2"], {"C": "R"}, {"R": "w1", "C": "w2", "S": "w2"}),
            ["S"])

    def test_space_and_root_combined(self):
        self.assertEqual(
            av.effective_excluded(["space:w2", "R"], {"C": "R"},
                                  {"R": "w1", "C": "w1", "S": "w2", "T": "w1"}),
            ["C", "R", "S"])

    def test_no_tree_passthrough(self):
        self.assertEqual(av.effective_excluded(["x"], None), ["x"])
        self.assertEqual(av.effective_excluded([], {"c": "r"}), [])


# ---- exclusão via apply_mode (só `send` mockado) --------------------------

class PickedExclusionWiring(Isolated):
    def test_space_exclusion_hides_root_and_child_in_filter(self):
        agents = [agent("R", "t1", "w1"), agent("C", "t1", "w2"), agent("S", "t2", "w2")]
        panes = [pane("R", "t1", "w1"), pane("C", "t1", "w2", parent="R"), pane("S", "t2", "w2")]
        h = FakeHerdr(agents, panes, tabs=[{"tab_id": "t1"}, {"tab_id": "t2"}])
        with mocked(h):
            av.apply_mode("picked", ["space:w1"])
        flt = h.methods("agent.view.set")[0]["filter"]
        self.assertEqual(flt["filter"]["values"], ["C", "R"])

    def test_child_exclusion_does_not_hide_child(self):
        agents = [agent("R", "t1"), agent("C", "t1")]
        panes = [pane("R", "t1"), pane("C", "t1", parent="R")]
        h = FakeHerdr(agents, panes, tabs=[{"tab_id": "t1"}])
        with mocked(h):
            av.apply_mode("picked", ["C"])
        flt = h.methods("agent.view.set")[0]["filter"]
        self.assertEqual(flt["filter"]["values"], ["__none__"])


# ---- effective_excluded: "tab:<id>" (só roots de grupo por tab) ----------

class EffectiveExcludedTab(unittest.TestCase):
    def test_tab_entry_hides_group_root_and_children(self):
        self.assertEqual(
            av.effective_excluded(["tab:t1"], {"C": "R"}, {"R": "w1", "C": "w1"},
                                  {"R": "t1", "C": "t1"}),
            ["C", "R"])

    def test_tab_entry_hides_lone_root_in_tab(self):
        # Regra de tab excluída: esconde TODO agente da tab, inclusive root sozinha.
        self.assertEqual(
            av.effective_excluded(["tab:t1"], {}, {"R": "w1"}, {"R": "t1"}), ["R"])

    def test_other_tab_entry_hides_nothing(self):
        self.assertEqual(
            av.effective_excluded(["tab:t9"], {"C": "R"}, {"R": "w1", "C": "w1"},
                                  {"R": "t1", "C": "t1"}),
            [])

    def test_child_in_other_tab_follows_root_not_its_own_tab(self):
        # C (filho explícito) está na tab t2, mas segue a root R (tab t1).
        self.assertEqual(
            av.effective_excluded(["tab:t2"], {"C": "R"}, {"R": "w1", "C": "w1"},
                                  {"R": "t1", "C": "t2"}),
            [])

    def test_tab_and_space_entries_combined(self):
        self.assertEqual(
            av.effective_excluded(["tab:t1", "space:w2"], {"C": "R"},
                                  {"R": "w1", "C": "w1", "S": "w2", "T": "w1"},
                                  {"R": "t1", "C": "t1", "S": "t3", "T": "t4"}),
            ["C", "R", "S"])


if __name__ == "__main__":
    unittest.main()
