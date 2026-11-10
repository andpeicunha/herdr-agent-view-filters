"""Política de agentes novos (`picked_new`): função pura + sync com send mockado."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "bin"))
sys.path.insert(0, HERE)
import agent_view as av  # noqa: E402
from _support import Isolated, FakeHerdr, agent, pane, mocked  # noqa: E402


class ApplyNewPolicy(unittest.TestCase):
    def test_first_run_marks_seen_without_excluding(self):
        self.assertEqual(av.apply_new_policy(["a", "b"], None, ["a"], "exclude"), (["a", "b"], ["a"]))

    def test_first_run_prunes_excluded(self):
        self.assertEqual(av.apply_new_policy(["a"], None, ["x"], "exclude"), (["a"], []))

    def test_new_agent_excluded_under_exclude(self):
        self.assertEqual(av.apply_new_policy(["a", "b", "c"], ["a", "b"], [], "exclude"),
                         (["a", "b", "c"], ["c"]))

    def test_known_agent_not_reexcluded(self):
        self.assertEqual(av.apply_new_policy(["a", "b"], ["a", "b"], ["a"], "exclude"),
                         (["a", "b"], ["a"]))

    def test_include_keeps_new_visible_but_tracks_seen(self):
        self.assertEqual(av.apply_new_policy(["a", "c"], ["a"], [], "include"), (["a", "c"], []))

    def test_prunes_dead(self):
        self.assertEqual(av.apply_new_policy(["a"], ["a", "x"], ["x"], "exclude"), (["a"], []))

    def test_new_child_never_excluded(self):
        self.assertEqual(av.apply_new_policy(["r", "c"], ["r"], [], "exclude", {"c"}),
                         (["c", "r"], []))

    def test_new_root_still_excluded_next_to_child(self):
        self.assertEqual(av.apply_new_policy(["r", "c", "n"], ["r"], [], "exclude", {"c"}),
                         (["c", "n", "r"], ["n"]))

    def test_legacy_child_id_dropped_from_excluded(self):
        self.assertEqual(av.apply_new_policy(["r", "c"], ["r", "c"], ["c"], "exclude", {"c"}),
                         (["c", "r"], []))

    def test_space_entries_pruned_to_live_spaces(self):
        self.assertEqual(av.apply_new_policy(["a"], ["a"], ["space:w1", "space:gone"], "include",
                                             set(), {"w1"}),
                         (["a"], ["space:w1"]))


class SyncPolicy(Isolated):
    def sync(self, agents, panes):
        h = FakeHerdr(agents, panes, tabs=[{"tab_id": "t1"}, {"tab_id": "t2"}])
        with mocked(h):
            av.sync_new_agents()
            av.prune_excluded()
        return h

    def test_first_sync_marks_seen_without_excluding(self):
        self.write_config('picked_new = "exclude"\n')
        self.sync([agent("R", "t1"), agent("N", "t2")], [pane("R", "t1"), pane("N", "t2")])
        st = self.state_file()
        self.assertEqual(st["excluded"], [])
        self.assertEqual(st["seen"], ["N", "R"])

    def test_default_include_keeps_new_root_visible(self):
        av.write_state("picked", [], seen=["R"])
        self.sync([agent("R", "t1"), agent("N", "t2")], [pane("R", "t1"), pane("N", "t2")])
        self.assertEqual(av.read_excluded(), [])
        self.assertEqual(self.state_file()["seen"], ["N", "R"])

    def test_exclude_policy_excludes_new_root(self):
        self.write_config('picked_new = "exclude"\n')
        av.write_state("picked", [], seen=["R"])
        self.sync([agent("R", "t1"), agent("N", "t2")], [pane("R", "t1"), pane("N", "t2")])
        self.assertEqual(av.read_excluded(), ["N"])

    def test_exclude_policy_never_excludes_new_explicit_child(self):
        self.write_config('picked_new = "exclude"\n')
        av.write_state("picked", [], seen=["R"])
        self.sync([agent("R", "t1"), agent("C", "t1")],
                  [pane("R", "t1"), pane("C", "t1", parent="R")])
        self.assertEqual(av.read_excluded(), [])

    def test_exclude_policy_never_excludes_new_tab_child(self):
        self.write_config('picked_new = "exclude"\n')
        av.write_state("picked", [], seen=["R"])
        self.sync([agent("R", "t1"), agent("D", "t1")], [pane("R", "t1"), pane("D", "t1")])
        self.assertEqual(av.read_excluded(), [])

    def test_legacy_child_id_dropped_on_sync(self):
        av.write_state("picked", ["C"], seen=["R", "C"])
        self.sync([agent("R", "t1"), agent("C", "t1")],
                  [pane("R", "t1"), pane("C", "t1", parent="R")])
        self.assertEqual(av.read_excluded(), [])

    def test_dead_pane_and_unknown_space_pruned(self):
        av.write_state("picked", ["R", "GONE", "space:zz"], seen=["R"])
        self.sync([agent("R", "t1")], [pane("R", "t1")])
        self.assertEqual(av.read_excluded(), ["R"])

    def test_exclusion_dropped_when_excluded_root_becomes_child(self):
        # R excluída (standalone) e única na tab. N aparece antes de R no layout,
        # vira root e R vira filho. Filho não migra: a exclusão de R é descartada
        # (README 0.10.0), N segue visível e nada vira "tab:t1".
        self.write_config('picked_new = "include"\n')
        av.write_state("picked", ["R"], seen=["R"])
        agents = [agent("N", "t1"), agent("R", "t1")]
        panes = [pane("N", "t1"), pane("R", "t1")]
        self.sync(agents, panes)
        self.assertEqual(av.read_excluded(), [])
        hidden = av.effective_excluded(av.read_excluded(), {"R": "N"},
                                       {"N": "w1", "R": "w1"}, {"N": "t1", "R": "t1"})
        self.assertEqual(hidden, [])


class TabEntryMigration(unittest.TestCase):
    """Pure apply_new_policy: "tab:<id>" entries and migration of a root pane id."""

    def test_tab_root_pane_id_migrates_to_tab_entry(self):
        self.assertEqual(
            av.apply_new_policy(["r", "c"], ["r", "c"], ["r"], "include", {"c"}, None, {"r": "t1"}, None),
            (["c", "r"], ["tab:t1"]))

    def test_standalone_pane_id_is_not_migrated(self):
        self.assertEqual(
            av.apply_new_policy(["r"], ["r"], ["r"], "include", set(), None, {}, None),
            (["r"], ["r"]))

    def test_migration_dedupes_with_existing_tab_entry(self):
        self.assertEqual(
            av.apply_new_policy(["r", "c"], ["r", "c"], ["r", "tab:t1"], "include", {"c"},
                                None, {"r": "t1"}, {"t1"}),
            (["c", "r"], ["tab:t1"]))

    def test_tab_entry_kept_while_tab_live_and_dead_one_pruned(self):
        self.assertEqual(
            av.apply_new_policy(["a"], ["a"], ["tab:t1", "tab:gone"], "include", set(), None, {}, {"t1"}),
            (["a"], ["tab:t1"]))

    def test_tab_entries_kept_when_live_tabs_unknown(self):
        self.assertEqual(
            av.apply_new_policy(["a"], ["a"], ["tab:t1", "tab:gone"], "include", set(), None, {}, None),
            (["a"], ["tab:gone", "tab:t1"]))


class TabMigrationSync(Isolated):
    """Sync real (send mockado): R com filho C na mesma tab, sem parent token."""

    def sync(self, agents, panes, tabs=("t1",)):
        h = FakeHerdr(agents, panes, tabs=[{"tab_id": t} for t in tabs])
        with mocked(h):
            av.sync_new_agents()
            av.prune_excluded()
        return h

    def group(self):
        return [agent("R", "t1"), agent("C", "t1")], [pane("R", "t1"), pane("C", "t1")]

    def test_excluded_group_root_migrates_to_tab_entry_on_sync(self):
        av.write_state("picked", ["R"], seen=["R", "C"])
        self.sync(*self.group())
        self.assertEqual(av.read_excluded(), ["tab:t1"])

    def test_tab_entry_survives_sync_while_tab_alive(self):
        av.write_state("picked", ["tab:t1"], seen=["R", "C"])
        self.sync(*self.group())
        self.assertEqual(av.read_excluded(), ["tab:t1"])

    def test_dead_tab_entry_pruned_on_sync(self):
        av.write_state("picked", ["tab:gone"], seen=["R", "C"])
        self.sync(*self.group())
        self.assertEqual(av.read_excluded(), [])

    def test_lone_root_left_in_excluded_tab_stays_hidden(self):
        # Regra: "tab:<id>" esconde todo agente da tab, grupo ou root sozinha.
        # Após o filho fechar, R segue escondida pela entrada da tab.
        av.write_state("picked", ["tab:t1"], seen=["R"])
        agents, panes = [agent("R", "t1")], [pane("R", "t1")]
        self.sync(agents, panes)
        h = FakeHerdr(agents, panes, tabs=[{"tab_id": "t1"}])
        with mocked(h):
            av.apply_mode("picked", av.read_excluded())
        values = h.methods("agent.view.set")[0]["filter"]["filter"]["values"]
        self.assertIn("R", values)


if __name__ == "__main__":
    unittest.main()
