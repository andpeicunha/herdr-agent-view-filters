"""`$space` / `$sep` (contrato atual, SEP_MODES = picked/active).
- `space_bounds`: `first` = panes que abrem um space (carregam `$space`);
  `last` = panes que fecham um space, exceto o último (carregam `$sep`).
- `fit_space`: `$space` cabe na linha da sidebar sem encurtar o título; some quando
  sobra menos que MIN_SPACE_ROOM colunas.
- `read_sidebar_width`: config `sidebar_width`, default SIDEBAR_WIDTH.
- `hdr` e `pad` são sempre None. Nenhum report passa de HERDR_MAX_TOKENS (16)."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "bin"))
sys.path.insert(0, HERE)
import agent_view as av  # noqa: E402
from _support import (Isolated, FakeHerdr, agent, pane, mocked, WORKSPACES,  # noqa: E402
                      HERDR_MAX_TOKENS)

TABS = [{"tab_id": "t1", "label": "dev"}, {"tab_id": "t2", "label": "ops"}]
WS3 = WORKSPACES + [{"workspace_id": "w3", "label": "Third", "number": 3}]
SEP = "─" * 20
SEP_MODES = ("picked", "active")
ALL_MODES = ("picked", "active", "space", "all")


class SpaceBounds(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(av.space_bounds([], {}), (set(), set()))

    def test_single_pane_is_first_and_not_last(self):
        self.assertEqual(av.space_bounds(["A"], {"A": "w1"}), ({"A"}, set()))

    def test_single_space_has_one_first_and_no_last(self):
        key = {"A": "w1", "B": "w1", "C": "w1"}
        self.assertEqual(av.space_bounds(["A", "B", "C"], key), ({"A"}, set()))

    def test_two_spaces(self):
        key = {"A": "w1", "B": "w1", "C": "w2", "D": "w2"}
        self.assertEqual(av.space_bounds(["A", "B", "C", "D"], key), ({"A", "C"}, {"B"}))

    def test_multiple_spaces_including_single_pane_space(self):
        # C é um space de pane único: é first e last ao mesmo tempo
        key = {"A": "w1", "B": "w1", "C": "w2", "D": "w3", "E": "w3"}
        self.assertEqual(av.space_bounds(list("ABCDE"), key), ({"A", "C", "D"}, {"B", "C"}))

    def test_one_pane_per_space(self):
        key = {"A": "w1", "B": "w2", "C": "w3"}
        self.assertEqual(av.space_bounds(["A", "B", "C"], key), ({"A", "B", "C"}, {"A", "B"}))

    def test_final_space_last_pane_never_in_last(self):
        key = {"A": "w1", "B": "w2", "C": "w3", "D": "w3"}
        first, last = av.space_bounds(["A", "B", "C", "D"], key)
        self.assertNotIn("D", last)
        self.assertEqual((first, last), ({"A", "B", "C"}, {"A", "B"}))


class FitSpace(unittest.TestCase):
    def test_fits_is_unchanged(self):
        self.assertEqual(av.fit_space("Work", "dev"), "Work")

    def test_no_space_gives_none(self):
        self.assertIsNone(av.fit_space(None, "dev"))
        self.assertIsNone(av.fit_space("", "dev"))

    def test_room_without_tree_is_width_minus_fixed_cost(self):
        # 32 - 2 - 0 - len("dev")=3 - len(" · ")=3 = 24
        self.assertEqual(av.fit_space("W" * 24, "dev"), "W" * 24)

    def test_truncates_with_ellipsis_to_room(self):
        out = av.fit_space("W" * 25, "dev")
        self.assertEqual(out, "W" * 23 + "…")
        self.assertEqual(len(out), 24)

    def test_tree_mark_costs_mark_plus_separator(self):
        # "└" custa 1 + len(" · ") = 4 colunas: room cai de 24 para 20
        self.assertEqual(av.fit_space("W" * 20, "dev", "└"), "W" * 20)
        self.assertEqual(av.fit_space("W" * 21, "dev", "└"), "W" * 19 + "…")

    def test_title_is_never_shortened(self):
        # o título só entra no orçamento: fit_space devolve apenas o space
        self.assertEqual(av.fit_space("Work", "t" * 20), "Work")  # room 7

    def test_min_room_boundary_kept_at_six(self):
        # room 6 (title 21) ainda trunca; room 5 (title 22) some
        self.assertEqual(av.fit_space("W" * 9, "t" * 21), "W" * 5 + "…")
        self.assertIsNone(av.fit_space("W" * 9, "t" * 22))

    def test_tree_cost_can_drop_space(self):
        # "├" custa 4: title 17 -> room 6 (mantém); title 18 -> room 5 (some)
        self.assertEqual(av.fit_space("W" * 9, "t" * 17, "├"), "W" * 5 + "…")
        self.assertIsNone(av.fit_space("W" * 9, "t" * 18, "├"))

    def test_custom_width(self):
        self.assertEqual(av.fit_space("W" * 25, "dev", None, 40), "W" * 25)

    def test_missing_title_uses_full_width(self):
        self.assertEqual(av.fit_space("Work", None), "Work")


class SidebarWidthConfig(Isolated):
    def test_default_when_missing(self):
        self.assertEqual(av.read_sidebar_width(), 32)
        self.assertEqual(av.read_sidebar_width(), av.SIDEBAR_WIDTH)

    def test_override(self):
        self.write_config("sidebar_width = 40\n")
        self.assertEqual(av.read_sidebar_width(), 40)

    def test_invalid_falls_back_to_default(self):
        for text in ("sidebar_width = 5\n", 'sidebar_width = "40"\n',
                     "sidebar_width = true\n", "sidebar_width = 31.5\n", "not = = toml"):
            with self.subTest(text=text):
                self.write_config(text)
                self.assertEqual(av.read_sidebar_width(), 32)


def publish(mode, workspaces=WORKSPACES, agents=None, panes=None, tabs=TABS):
    """publish_tokens(mode) com FakeHerdr. Default: A,B em Work (t1), C em Home (t2).
    -> (tokens aceitos pelo Herdr, FakeHerdr)."""
    if agents is None:
        agents = [agent("A", "t1", "w1"), agent("B", "t1", "w1"), agent("C", "t2", "w2")]
        panes = [pane("A", "t1", "w1"), pane("B", "t1", "w1"), pane("C", "t2", "w2")]
    h = FakeHerdr(agents, panes, tabs=tabs, workspaces=workspaces)
    with mocked(h):
        av.publish_tokens(mode=mode)
    return h.tokens(), h


class PublishSeparatorTokens(Isolated):
    def test_sep_on_last_pane_of_space_except_last(self):
        for mode in SEP_MODES:
            with self.subTest(mode=mode):
                tok, _ = publish(mode)
                self.assertEqual(tok["B"]["sep"], SEP)
                self.assertIsNone(tok["A"]["sep"])

    def test_sep_is_twenty_columns(self):
        self.assertEqual(av.SEP_WIDTH, 20)
        self.assertEqual(len(SEP), 20)

    def test_last_space_last_pane_has_no_sep(self):
        for mode in SEP_MODES:
            with self.subTest(mode=mode):
                tok, _ = publish(mode)
                self.assertIsNone(tok["C"]["sep"])

    def test_space_only_on_first_pane_of_each_space(self):
        for mode in SEP_MODES:
            with self.subTest(mode=mode):
                tok, _ = publish(mode)
                self.assertEqual(tok["A"]["space"], "Work")
                self.assertIsNone(tok["B"]["space"])
                self.assertEqual(tok["C"]["space"], "Home")

    def test_three_spaces_each_boundary_has_sep_and_space(self):
        # tabs distintas: um pane por space, sem filhos
        agents = [agent("A", "t1", "w1"), agent("B", "t2", "w2"), agent("C", "t3", "w3")]
        panes = [pane("A", "t1", "w1"), pane("B", "t2", "w2"), pane("C", "t3", "w3")]
        tabs = TABS + [{"tab_id": "t3", "label": "x"}]
        tok, _ = publish("picked", workspaces=WS3, agents=agents, panes=panes, tabs=tabs)
        self.assertEqual((tok["A"]["space"], tok["A"]["sep"]), ("Work", SEP))
        self.assertEqual((tok["B"]["space"], tok["B"]["sep"]), ("Home", SEP))
        self.assertEqual((tok["C"]["space"], tok["C"]["sep"]), ("Third", None))

    def test_sep_lands_on_child_when_child_closes_space(self):
        agents = [agent("R", "t1", "w1"), agent("C", "t1", "w1"), agent("S", "t2", "w2")]
        panes = [pane("R", "t1", "w1"), pane("C", "t1", "w1", parent="R", label="logs"),
                 pane("S", "t2", "w2")]
        tok, _ = publish("picked", agents=agents, panes=panes)
        self.assertEqual(tok["C"]["sep"], SEP)
        self.assertIsNone(tok["R"]["sep"])
        self.assertIsNone(tok["S"]["sep"])
        self.assertEqual((tok["R"]["space"], tok["C"]["space"], tok["S"]["space"]),
                         ("Work", None, "Home"))

    def test_single_space_publishes_no_sep(self):
        agents = [agent("A", "t1", "w1"), agent("B", "t2", "w1")]
        panes = [pane("A", "t1", "w1"), pane("B", "t2", "w1")]
        tok, _ = publish("picked", agents=agents, panes=panes)
        for pid in ("A", "B"):
            self.assertIsNone(tok[pid]["sep"])
        self.assertEqual(tok["A"]["space"], "Work")
        self.assertIsNone(tok["B"]["space"])

    def test_space_truncated_with_ellipsis_when_workspace_label_long(self):
        ws = [{"workspace_id": "w1", "label": "W" * 40},
              {"workspace_id": "w2", "label": "Home"}]
        tok, _ = publish("picked", workspaces=ws)
        self.assertEqual(tok["A"]["space"], "W" * 23 + "…")
        self.assertEqual(tok["A"]["title"], "dev")  # título nunca encurtado

    def test_space_dropped_when_title_leaves_too_little_room(self):
        tabs = [{"tab_id": "t1", "label": "t" * 22}, {"tab_id": "t2", "label": "ops"}]
        tok, _ = publish("picked", tabs=tabs)
        self.assertIsNone(tok["A"]["space"])
        self.assertEqual(tok["A"]["title"], "t" * 22)
        self.assertEqual(tok["B"]["sep"], SEP)  # o sep não depende do space

    def test_publish_uses_configured_sidebar_width(self):
        # width 20 - 2 - 0 - len("dev")=3 - 3 = 12 -> 11 chars + "…"
        self.write_config("sidebar_width = 20\n")
        ws = [{"workspace_id": "w1", "label": "W" * 40},
              {"workspace_id": "w2", "label": "Home"}]
        tok, _ = publish("picked", workspaces=ws)
        self.assertEqual(tok["A"]["space"], "W" * 11 + "…")

    def test_hdr_and_pad_are_always_none(self):
        for mode in ALL_MODES:
            with self.subTest(mode=mode):
                tok, _ = publish(mode)
                for pid in ("A", "B", "C"):
                    self.assertIn("hdr", tok[pid])
                    self.assertIn("pad", tok[pid])
                    self.assertIsNone(tok[pid]["hdr"], f"{pid} hdr em {mode}")
                    self.assertIsNone(tok[pid]["pad"], f"{pid} pad em {mode}")

    def test_space_and_all_modes_publish_full_space_and_no_sep(self):
        for mode in ("space", "all"):
            with self.subTest(mode=mode):
                tok, _ = publish(mode)
                self.assertEqual(tok["B"]["space"], "Work")  # não é só o first pane
                for pid in ("A", "B", "C"):
                    self.assertIsNone(tok[pid]["sep"], f"{pid} sep em {mode}")

    def test_report_never_exceeds_herdr_token_limit(self):
        agents = [agent("A", "t2", "w1"), agent("R", "t1", "w1"),
                  agent("C", "t1", "w1", title="zsh"), agent("D", "t1", "w1", title="vim"),
                  agent("S", "t3", "w2")]
        panes = [pane("A", "t2", "w1"), pane("R", "t1", "w1"),
                 pane("C", "t1", "w1", parent="R", label="logs"),
                 pane("D", "t1", "w1"), pane("S", "t3", "w2")]
        tabs = TABS + [{"tab_id": "t3", "label": "home"}]
        for mode in ALL_MODES:
            with self.subTest(mode=mode):
                tok, h = publish(mode, agents=agents, panes=panes, tabs=tabs)
                for r in h.methods("pane.report_metadata"):
                    self.assertLessEqual(len(r["tokens"]), HERDR_MAX_TOKENS)
                self.assertEqual(set(tok), {"A", "R", "C", "D", "S"})


if __name__ == "__main__":
    unittest.main()
