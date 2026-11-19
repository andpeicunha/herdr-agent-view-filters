"""`$sep` / `$hdr` (contrato novo): o último pane de cada space, exceto o último
space, carrega `sep` = "─"*HDR_WIDTH e `hdr` = nome do space SEGUINTE (plain,
sem espaços). Só em SEP_MODES (picked/active). `pad` é sempre None."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "bin"))
sys.path.insert(0, HERE)
import agent_view as av  # noqa: E402
from _support import Isolated, FakeHerdr, agent, pane, mocked, WORKSPACES  # noqa: E402

TABS = [{"tab_id": "t1", "label": "dev"}, {"tab_id": "t2", "label": "ops"}]
WS3 = WORKSPACES + [{"workspace_id": "w3", "label": "Third", "number": 3}]
SEP = "─" * 28
ALL_MODES = ("picked", "active", "space", "all")


class SpaceHeaders(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(av.space_headers([], {}), {})

    def test_single_pane(self):
        self.assertEqual(av.space_headers(["A"], {"A": "w1"}), {})

    def test_single_space_has_no_headers(self):
        self.assertEqual(av.space_headers(["A", "B", "C"], {"A": "w1", "B": "w1", "C": "w1"}), {})

    def test_two_spaces_last_pane_of_first_maps_to_second_key(self):
        key = {"A": "w1", "B": "w1", "C": "w2", "D": "w2"}
        self.assertEqual(av.space_headers(["A", "B", "C", "D"], key), {"B": "w2"})

    def test_multiple_spaces_map_to_next_key(self):
        key = {"A": "w1", "B": "w1", "C": "w2", "D": "w3", "E": "w3"}
        self.assertEqual(av.space_headers(["A", "B", "C", "D", "E"], key),
                         {"B": "w2", "C": "w3"})

    def test_first_pane_of_first_space_never_a_key(self):
        key = {"A": "w1", "B": "w1", "C": "w2", "D": "w3"}
        self.assertNotIn("A", av.space_headers(["A", "B", "C", "D"], key))

    def test_last_space_last_pane_never_a_key(self):
        key = {"A": "w1", "B": "w2", "C": "w3", "D": "w3"}
        out = av.space_headers(["A", "B", "C", "D"], key)
        self.assertNotIn("D", out)
        self.assertEqual(out, {"A": "w2", "B": "w3"})

    def test_one_pane_per_space(self):
        self.assertEqual(av.space_headers(["A", "B", "C"], {"A": "w1", "B": "w2", "C": "w3"}),
                         {"A": "w2", "B": "w3"})


def publish(mode, workspaces=WORKSPACES, agents=None, panes=None):
    """publish_tokens(mode) com FakeHerdr. Default: A,B em Work (t1), C em Home (t2)."""
    if agents is None:
        agents = [agent("A", "t1", "w1"), agent("B", "t1", "w1"), agent("C", "t2", "w2")]
        panes = [pane("A", "t1", "w1"), pane("B", "t1", "w1"), pane("C", "t2", "w2")]
    h = FakeHerdr(agents, panes, tabs=TABS, workspaces=workspaces)
    with mocked(h):
        av.publish_tokens(mode=mode)
    return h.tokens()


class PublishSeparatorTokens(Isolated):
    def test_sep_and_next_label_on_last_pane_of_space_except_last(self):
        for mode in ("picked", "active"):
            with self.subTest(mode=mode):
                tok = publish(mode)
                self.assertEqual(tok["B"]["sep"], SEP)
                self.assertEqual(tok["B"]["hdr"], "Home", "hdr = NEXT space, não o atual")

    def test_first_space_first_pane_gets_nothing(self):
        for mode in ("picked", "active"):
            with self.subTest(mode=mode):
                tok = publish(mode)
                self.assertIsNone(tok["A"]["sep"])
                self.assertIsNone(tok["A"]["hdr"])

    def test_last_space_last_pane_gets_nothing(self):
        for mode in ("picked", "active"):
            with self.subTest(mode=mode):
                tok = publish(mode)
                self.assertIsNone(tok["C"]["sep"])
                self.assertIsNone(tok["C"]["hdr"])

    def test_three_spaces_each_boundary_carries_next_label(self):
        # tabs distintas: panes na mesma tab viram filhos (mesmo space que o root)
        agents = [agent("A", "t1", "w1"), agent("B", "t2", "w2"), agent("C", "t3", "w3")]
        panes = [pane("A", "t1", "w1"), pane("B", "t2", "w2"), pane("C", "t3", "w3")]
        tabs = TABS + [{"tab_id": "t3", "label": "x"}]
        h = FakeHerdr(agents, panes, tabs=tabs, workspaces=WS3)
        with mocked(h):
            av.publish_tokens(mode="picked")
        tok = h.tokens()
        self.assertEqual((tok["A"]["hdr"], tok["A"]["sep"]), ("Home", SEP))
        self.assertEqual((tok["B"]["hdr"], tok["B"]["sep"]), ("Third", SEP))
        self.assertIsNone(tok["C"]["hdr"])
        self.assertIsNone(tok["C"]["sep"])

    def test_single_space_publishes_no_sep_or_hdr(self):
        agents = [agent("A", "t1", "w1"), agent("B", "t2", "w1")]
        panes = [pane("A", "t1", "w1"), pane("B", "t2", "w1")]
        tok = publish("picked", agents=agents, panes=panes)
        for pid in ("A", "B"):
            self.assertIsNone(tok[pid]["sep"])
            self.assertIsNone(tok[pid]["hdr"])

    def test_hdr_is_plain_stripped_label(self):
        ws = [{"workspace_id": "w1", "label": "Work"},
              {"workspace_id": "w2", "label": "  Home  "}]
        self.assertEqual(publish("picked", workspaces=ws)["B"]["hdr"], "Home")

    def test_blank_next_label_gives_hdr_none_but_sep_kept(self):
        ws = [{"workspace_id": "w1", "label": "Work"},
              {"workspace_id": "w2", "label": "   "}]
        tok = publish("picked", workspaces=ws)
        self.assertIsNone(tok["B"]["hdr"])
        self.assertEqual(tok["B"]["sep"], SEP)

    def test_no_sep_or_hdr_in_space_and_all_modes(self):
        for mode in ("space", "all"):
            with self.subTest(mode=mode):
                tok = publish(mode)
                for pid in ("A", "B", "C"):
                    self.assertIsNone(tok[pid]["sep"], f"{pid} sep em {mode}")
                    self.assertIsNone(tok[pid]["hdr"], f"{pid} hdr em {mode}")

    def test_pad_always_none(self):
        for mode in ALL_MODES:
            with self.subTest(mode=mode):
                tok = publish(mode)
                for pid in ("A", "B", "C"):
                    self.assertIn("pad", tok[pid])
                    self.assertIsNone(tok[pid]["pad"], f"{pid} pad em {mode}")


if __name__ == "__main__":
    unittest.main()
