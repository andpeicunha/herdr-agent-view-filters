"""Raiz sticky por tab, first_seen monotônico/poda, compat de state antigo,
sync_layout (no-op com listagem vazia) e sub vazio sem repo.

Único mock: `av.send` (via _support.mocked). Estado isolado em tmp.
"""
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "bin"))
sys.path.insert(0, HERE)
import agent_view as av  # noqa: E402
from _support import Isolated, FakeHerdr, agent, pane, mocked  # noqa: E402


class AssignFirstSeen(unittest.TestCase):
    def test_new_ids_get_counters_in_given_order(self):
        self.assertEqual(av.assign_first_seen({}, ["B", "A", "C"]), {"B": 1, "A": 2, "C": 3})

    def test_known_ids_keep_their_counter(self):
        self.assertEqual(av.assign_first_seen({"A": 5, "B": 2}, ["B", "A"]), {"B": 2, "A": 5})

    def test_new_ids_are_newer_than_every_retained_id(self):
        out = av.assign_first_seen({"A": 1, "B": 7}, ["A", "B", "N1", "N2"])
        self.assertEqual((out["N1"], out["N2"]), (8, 9))

    def test_dead_ids_are_pruned(self):
        self.assertEqual(av.assign_first_seen({"A": 1, "GONE": 2}, ["A"]), {"A": 1})

    def test_duplicate_live_ids_counted_once(self):
        self.assertEqual(av.assign_first_seen({}, ["A", "A", "B"]), {"A": 1, "B": 2})

    def test_monotonic_across_calls_with_deaths(self):
        fs = av.assign_first_seen({}, ["A", "B"])
        fs = av.assign_first_seen(fs, ["B", "C"])  # A morre
        fs = av.assign_first_seen(fs, ["C", "D"])  # B morre
        self.assertEqual(fs, {"C": 3, "D": 4})


class TabRootMap(unittest.TestCase):
    def test_oldest_first_seen_wins_without_stored_root(self):
        self.assertEqual(av.tab_root_map([("B", "t1"), ("A", "t1")],
                                         first_seen={"A": 1, "B": 2}), {"t1": "A"})

    def test_stored_root_is_sticky_under_pane_order_change(self):
        fs = {"A": 1, "B": 2}
        for order in ([("A", "t1"), ("B", "t1")], [("B", "t1"), ("A", "t1")]):
            with self.subTest(order=order):
                self.assertEqual(av.tab_root_map(order, first_seen=fs,
                                                 stored_roots={"t1": "B"}), {"t1": "B"})

    def test_stored_root_sticky_without_first_seen(self):
        self.assertEqual(av.tab_root_map([("A", "t1"), ("B", "t1")],
                                         stored_roots={"t1": "B"}), {"t1": "B"})

    def test_dead_stored_root_replaced_by_oldest_survivor(self):
        fs = {"A": 1, "B": 3, "C": 2}
        self.assertEqual(av.tab_root_map([("B", "t1"), ("C", "t1")], first_seen=fs,
                                         stored_roots={"t1": "A"}), {"t1": "C"})

    def test_skipped_explicit_child_is_never_a_candidate_even_if_stored(self):
        fs = {"X": 1, "A": 2}
        self.assertEqual(av.tab_root_map([("X", "t1"), ("A", "t1")], skip={"X"},
                                         first_seen=fs, stored_roots={"t1": "X"}),
                         {"t1": "A"})

    def test_tab_parents_leave_explicit_children_out(self):
        self.assertEqual(av.tab_parents([("X", "t1"), ("A", "t1"), ("B", "t1")],
                                        skip={"X"}, first_seen={"X": 1, "A": 2, "B": 3}),
                         {"B": "A"})


class TreeAndRootsSticky(Isolated):
    def test_sticky_root_survives_pane_list_reorder(self):
        agents = [agent("A", "t1"), agent("B", "t1")]
        fs, stored = {"A": 1, "B": 2}, {"t1": "B"}
        for panes in ([pane("A", "t1"), pane("B", "t1")],
                      [pane("B", "t1"), pane("A", "t1")]):
            with self.subTest(order=[p["pane_id"] for p in panes]):
                tree, roots = av.tree_and_roots(agents, panes, group_by_tab=True,
                                                first_seen=fs, stored_roots=stored)
                self.assertEqual(tree, {"A": "B"})
                self.assertEqual(roots, {"t1": "B"})

    def test_explicit_child_with_stored_root_never_becomes_tab_root(self):
        agents = [agent("X", "t1"), agent("A", "t1"), agent("Y", "t2")]
        panes = [pane("X", "t1", parent="Y"), pane("A", "t1"), pane("Y", "t2")]
        tree, roots = av.tree_and_roots(agents, panes, group_by_tab=True,
                                        first_seen={"X": 1, "A": 2, "Y": 3},
                                        stored_roots={"t1": "X"})
        self.assertEqual(tree, {"X": "Y"})
        self.assertEqual(roots["t1"], "A")
        self.assertNotIn("X", roots.values())


class SyncLayoutPersistence(Isolated):
    def state_raw(self):
        with open(os.path.join(self.state_dir, "state.json")) as f:
            return f.read()

    def test_sticky_root_persisted_and_kept_across_reorder(self):
        av.write_state("active", [], first_seen={"A": 1, "B": 2}, tab_roots={"t1": "B"})
        av.sync_layout([agent("A", "t1"), agent("B", "t1")],
                       [pane("B", "t1"), pane("A", "t1")])
        st = self.state_file()
        self.assertEqual(st["tab_roots"], {"t1": "B"})
        self.assertEqual(st["first_seen"], {"A": 1, "B": 2})

    def test_root_dies_oldest_survivor_takes_over_and_is_persisted(self):
        av.write_state("active", [], first_seen={"A": 1, "B": 3, "C": 2}, tab_roots={"t1": "A"})
        av.sync_layout([agent("B", "t1"), agent("C", "t1")],
                       [pane("B", "t1"), pane("C", "t1")])
        st = self.state_file()
        self.assertEqual(st["tab_roots"], {"t1": "C"})
        self.assertEqual(st["first_seen"], {"B": 3, "C": 2})

    def test_explicit_child_not_persisted_as_tab_root(self):
        agents = [agent("X", "t1"), agent("A", "t1"), agent("Y", "t2")]
        panes = [pane("X", "t1", parent="Y"), pane("A", "t1"), pane("Y", "t2")]
        av.write_state("active", [], first_seen={"X": 1, "A": 2, "Y": 3}, tab_roots={"t1": "X"})
        _, roots = av.sync_layout(agents, panes)
        self.assertEqual(roots["t1"], "A")
        self.assertEqual(self.state_file()["tab_roots"]["t1"], "A")

    def test_first_seen_monotonic_and_pruned_across_syncs(self):
        av.sync_layout([agent("A", "t1"), agent("B", "t1")], [pane("A", "t1"), pane("B", "t1")])
        av.sync_layout([agent("B", "t1"), agent("C", "t1")], [pane("B", "t1"), pane("C", "t1")])
        self.assertEqual(self.state_file()["first_seen"], {"B": 2, "C": 3})


class OldStateCompat(Isolated):
    def write_raw(self, data):
        with open(os.path.join(self.state_dir, "state.json"), "w") as f:
            json.dump(data, f)

    def test_pre_sticky_state_loads_with_empty_new_keys(self):
        self.write_raw({"mode": "picked", "excluded": ["R"], "seen": ["R"],
                        "order": {"R": ["R"]}, "tree_ws": {"R": "x"}})
        self.assertEqual(av.read_mode(), "picked")
        self.assertEqual(av.read_excluded(), ["R"])
        self.assertEqual(av.read_first_seen(), {})
        self.assertEqual(av.read_tab_roots(), {})

    def test_invalid_new_keys_are_ignored(self):
        self.write_raw({"mode": "active", "first_seen": ["A"], "tab_roots": "t1"})
        self.assertEqual(av.read_first_seen(), {})
        self.assertEqual(av.read_tab_roots(), {})

    def test_first_seen_keeps_only_int_values(self):
        self.write_raw({"first_seen": {"A": 1, "B": "2", "C": True, "D": 3}})
        self.assertEqual(av.read_first_seen(), {"A": 1, "D": 3})

    def test_old_state_upgraded_on_sync_keeping_mode_and_excluded(self):
        self.write_raw({"mode": "picked", "excluded": ["space:w1"], "order": {"x": 1}})
        av.sync_layout([agent("A", "t1")], [pane("A", "t1")])
        st = self.state_file()
        self.assertEqual(st["mode"], "picked")
        self.assertEqual(st["excluded"], ["space:w1"])
        self.assertEqual(st["first_seen"], {"A": 1})
        self.assertEqual(st["tab_roots"], {"t1": "A"})
        self.assertNotIn("order", st)


class SyncLayoutEmptyListing(Isolated):
    def seed(self):
        av.write_state("picked", ["R"], first_seen={"A": 1}, tab_roots={"t1": "A"})
        with open(os.path.join(self.state_dir, "state.json")) as f:
            return f.read()

    def test_empty_agents_is_noop(self):
        before = self.seed()
        self.assertEqual(av.sync_layout([], [pane("A", "t1")]), ({"A": 1}, {"t1": "A"}))
        with open(os.path.join(self.state_dir, "state.json")) as f:
            self.assertEqual(f.read(), before)

    def test_empty_panes_is_noop(self):
        before = self.seed()
        self.assertEqual(av.sync_layout([agent("B", "t1")], []), ({"A": 1}, {"t1": "A"}))
        with open(os.path.join(self.state_dir, "state.json")) as f:
            self.assertEqual(f.read(), before)

    def test_none_listings_is_noop(self):
        before = self.seed()
        av.sync_layout(None, None)
        with open(os.path.join(self.state_dir, "state.json")) as f:
            self.assertEqual(f.read(), before)

    def test_no_state_file_created_on_empty_listing(self):
        av.sync_layout([], [])
        self.assertFalse(os.path.exists(os.path.join(self.state_dir, "state.json")))


class EmptyRepoSub(Isolated):
    TABS = {"t1": {"label": "dev"}}
    WS = {"w1": "Work"}

    def test_root_with_children_and_no_repo_text_has_null_sub(self):
        a = {"pane_id": "R", "tab_id": "t1", "workspace_id": "w1", "agent": "",
             "cwd": "", "agent_status": "idle"}
        self.assertEqual(av.row_texts(a, (self.TABS, {}, {"t1": 2}), self.WS, None, True),
                         ("dev", "Work", None))

    def test_row_tokens_sub_none_for_empty_text(self):
        self.assertIsNone(av.row_tokens("dev", "Work", "")["sub"])

    def test_publish_sends_sub_null_for_root_without_repo(self):
        # R com filho = coordenadora -> subtree "├" + coord "◆ orch" mesmo sem nome (sub None).
        # Z sem filhos (outra tab) = raiz comum -> sub None.
        agents = [{"pane_id": "R", "tab_id": "t1", "workspace_id": "w1", "agent": "",
                   "cwd": "", "agent_status": "idle"},
                  agent("C", "t1", cwd="/x/C"),
                  {"pane_id": "Z", "tab_id": "t2", "workspace_id": "w1", "agent": "",
                   "cwd": "", "agent_status": "idle"}]
        panes = [pane("R", "t1"), pane("C", "t1", parent="R"), pane("Z", "t2")]
        h = FakeHerdr(agents, panes, tabs=[{"tab_id": "t1", "label": "dev"},
                                           {"tab_id": "t2", "label": "ops"}])
        with mocked(h):
            av.publish_tokens()
        self.assertIsNone(h.tokens()["R"]["sub"])
        self.assertEqual(h.tokens()["R"]["subtree"], "\u251c")
        self.assertIsNone(h.tokens()["R"]["tree"])
        self.assertEqual(h.tokens()["R"]["coord"], "\u25c6 orch")
        self.assertEqual(h.tokens()["R"]["title"], "dev")
        self.assertIsNone(h.tokens()["Z"]["sub"])
        self.assertIsNone(h.tokens()["Z"]["tree"])
        self.assertIsNone(h.tokens()["Z"]["coord"])
        self.assertEqual(h.tokens()["Z"]["title"], "ops")


if __name__ == "__main__":
    unittest.main()
