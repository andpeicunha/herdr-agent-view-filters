"""`parents` persistido: token explícito > relação guardada (ambos vivos) > poda.

Único mock: `av.send` (via _support.mocked). Estado isolado em tmp.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "bin"))
sys.path.insert(0, HERE)
import agent_view as av  # noqa: E402
from _support import Isolated, agent, pane  # noqa: E402

# R e C em tabs diferentes: o fallback por tab não liga as duas.
AGENTS = [agent("R", "t1"), agent("C", "t2")]
PANES_NO_TOKEN = [pane("R", "t1"), pane("C", "t2")]


class EffectiveParentsPure(unittest.TestCase):
    def test_stored_used_when_token_absent_and_both_alive(self):
        self.assertEqual(av.effective_parents(["R", "C"], PANES_NO_TOKEN, {"C": "R"}),
                         {"C": "R"})

    def test_token_beats_stored(self):
        panes = [pane("R", "t1"), pane("X", "t3"), pane("C", "t2", parent="X")]
        self.assertEqual(av.effective_parents(["R", "X", "C"], panes, {"C": "R"}),
                         {"C": "X"})

    def test_dead_stored_parent_pruned(self):
        self.assertEqual(av.effective_parents(["C"], [pane("C", "t2")], {"C": "R"}), {})

    def test_invalid_explicit_token_keeps_stored(self):
        # Token aponta para pai morto: ignorado, relação guardada sobrevive.
        panes = [pane("R", "t1"), pane("C", "t2", parent="GONE")]
        self.assertEqual(av.effective_parents(["R", "C"], panes, {"C": "R"}), {"C": "R"})

    def test_self_parent_ignored(self):
        self.assertEqual(av.effective_parents(["C"], [pane("C", "t2")], {"C": "C"}), {})


class ParentsTreeAndPersistence(Isolated):
    def test_stored_parent_used_when_token_expired(self):
        av.write_state("picked", [], parents={"C": "R"})
        self.assertEqual(av.current_tree(AGENTS, PANES_NO_TOKEN), {"C": "R"})

    def test_sync_keeps_stored_relation_while_both_alive(self):
        av.write_state("picked", [], parents={"C": "R"})
        av.sync_layout(AGENTS, PANES_NO_TOKEN)
        self.assertEqual(self.state_file()["parents"], {"C": "R"})

    def test_relation_survives_token_expiry_across_syncs(self):
        # Sync 1: token vivo -> persiste. Sync 2: token expirou -> continua valendo.
        av.sync_layout(AGENTS, [pane("R", "t1"), pane("C", "t2", parent="R")])
        self.assertEqual(self.state_file()["parents"], {"C": "R"})
        av.sync_layout(AGENTS, PANES_NO_TOKEN)
        self.assertEqual(self.state_file()["parents"], {"C": "R"})
        self.assertEqual(av.current_tree(AGENTS, PANES_NO_TOKEN), {"C": "R"})

    def test_dead_parent_pruned_on_sync(self):
        av.write_state("picked", [], parents={"C": "R"})
        av.sync_layout([agent("C", "t2")], [pane("C", "t2")])
        self.assertNotIn("parents", self.state_file())
        self.assertEqual(av.read_parents(), {})

    def test_token_wins_over_stored_and_is_persisted(self):
        av.write_state("picked", [], parents={"C": "R"})
        panes = [pane("R", "t1"), pane("X", "t3"), pane("C", "t2", parent="X")]
        agents = AGENTS + [agent("X", "t3")]
        av.sync_layout(agents, panes)
        self.assertEqual(self.state_file()["parents"], {"C": "X"})


if __name__ == "__main__":
    unittest.main()
