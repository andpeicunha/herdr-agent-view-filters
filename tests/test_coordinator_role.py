"""Token `role=coordinator` na raiz com filhos (parent= alvo ou raiz de tab com
filhos), em todos os modos; removido quando perde os filhos; sem write redundante."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "bin"))
sys.path.insert(0, HERE)
import agent_view as av  # noqa: E402
from _support import Isolated, FakeHerdr, agent, pane, mocked  # noqa: E402

TABS = [{"tab_id": "t1", "label": "dev"}, {"tab_id": "t2", "label": "ops"}]


def feed_back(h):
    published = h.tokens()
    for p in h.panes:
        p["tokens"] = {k: v for k, v in published.get(p["pane_id"], {}).items()
                       if v is not None}


def roles(h):
    return {pid: t.get("role") for pid, t in h.tokens().items()}


def apply(h, mode="picked"):
    with mocked(h):
        av.apply_mode(mode, [])


class RoleAllModes(Isolated):
    def fake_explicit(self):
        # R coordena C por token (abas diferentes); X solo.
        return FakeHerdr(
            [agent("R", "t1"), agent("C", "t2"), agent("X", "t1")],
            [pane("R", "t1"), pane("C", "t2", parent="R"), pane("X", "t1")],
            tabs=TABS)

    def test_explicit_parent_target_all_modes(self):
        for mode in av.MODES:
            with self.subTest(mode=mode):
                h = self.fake_explicit()
                apply(h, mode)
                r = roles(h)
                self.assertEqual(r["R"], "coordinator")
                self.assertIsNone(r["C"])
                self.assertIsNone(r["X"])

    def test_tab_root_with_children_all_modes(self):
        for mode in av.MODES:
            with self.subTest(mode=mode):
                h = FakeHerdr([agent("R", "t1"), agent("C", "t1")],
                              [pane("R", "t1"), pane("C", "t1")], tabs=TABS)
                apply(h, mode)
                r = roles(h)
                self.assertEqual(r["R"], "coordinator")
                self.assertIsNone(r["C"])

    def test_single_pane_tab_has_no_role(self):
        for mode in av.MODES:
            with self.subTest(mode=mode):
                h = FakeHerdr([agent("A", "t1"), agent("B", "t2")],
                              [pane("A", "t1"), pane("B", "t2")], tabs=TABS)
                apply(h, mode)
                self.assertEqual(roles(h), {"A": None, "B": None})

    def test_grandchild_only_root_gets_role(self):
        h = FakeHerdr(
            [agent("R", "t1"), agent("M", "t2"), agent("G", "t2")],
            [pane("R", "t1"), pane("M", "t2", parent="R"), pane("G", "t2", parent="M")],
            tabs=TABS)
        apply(h)
        self.assertEqual(roles(h), {"R": "coordinator", "M": None, "G": None})

    def test_group_by_tab_off_tab_root_has_no_role(self):
        self.write_config("group_by_tab = false\n")
        h = FakeHerdr([agent("R", "t1"), agent("C", "t1")],
                      [pane("R", "t1"), pane("C", "t1")], tabs=TABS)
        apply(h)
        self.assertEqual(roles(h), {"R": None, "C": None})

    def test_root_choice_unchanged(self):
        # a escolha de raiz (mais antigo) não depende do role
        h = FakeHerdr([agent("A", "t1"), agent("B", "t1")],
                      [pane("A", "t1"), pane("B", "t1")], tabs=TABS)
        apply(h)
        self.assertEqual(av.read_tab_roots(), {"t1": "A"})
        self.assertEqual(roles(h)["A"], "coordinator")


class RoleCleanup(Isolated):
    def test_role_removed_when_children_gone(self):
        h = FakeHerdr([agent("R", "t1"), agent("C", "t1")],
                      [pane("R", "t1"), pane("C", "t1")], tabs=TABS)
        apply(h)
        feed_back(h)
        self.assertEqual(h.panes[0]["tokens"]["role"], "coordinator")
        # C fecha: R fica sozinho na tab
        h.agents = [agent("R", "t1")]
        h.panes = [h.panes[0]]
        before = len(h.calls)
        apply(h)
        sent = [c["params"] for c in h.calls[before:]
                if c["method"] == "pane.report_metadata"]
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]["pane_id"], "R")
        self.assertIsNone(sent[0]["tokens"]["role"])  # None = limpa o token

    def test_role_appears_when_child_arrives(self):
        h = FakeHerdr([agent("R", "t1")], [pane("R", "t1")], tabs=TABS)
        apply(h)
        self.assertIsNone(roles(h)["R"])
        feed_back(h)
        h.agents.append(agent("C", "t1"))
        h.panes.append(pane("C", "t1"))
        apply(h)
        self.assertEqual(roles(h)["R"], "coordinator")


class RoleNoRedundantWrite(Isolated):
    def test_no_report_when_role_already_current(self):
        h = FakeHerdr([agent("R", "t1"), agent("C", "t1")],
                      [pane("R", "t1"), pane("C", "t1")], tabs=TABS)
        apply(h)
        feed_back(h)
        before = len(h.calls)
        apply(h)
        self.assertEqual([c for c in h.calls[before:]
                          if c["method"] == "pane.report_metadata"], [])

    def test_missing_role_is_written_alone(self):
        h = FakeHerdr([agent("R", "t1"), agent("C", "t1")],
                      [pane("R", "t1"), pane("C", "t1")], tabs=TABS)
        apply(h)
        feed_back(h)
        del h.panes[0]["tokens"]["role"]
        before = len(h.calls)
        apply(h)
        written = [c["params"]["pane_id"] for c in h.calls[before:]
                   if c["method"] == "pane.report_metadata"]
        self.assertEqual(written, ["R"])


class TokenPureHelper(unittest.TestCase):
    def test_tokens_current_treats_none_as_absent(self):
        self.assertTrue(av._tokens_current({"role": "coordinator"},
                                           {"role": "coordinator"}))
        self.assertFalse(av._tokens_current({"role": "coordinator"}, {"role": None}))
        self.assertTrue(av._tokens_current({}, {"role": None}))


if __name__ == "__main__":
    unittest.main()
