"""is_auto_label (pura) e display_label com label "<repo> #N". Sem socket: só ctx construído à mão."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "bin"))
sys.path.insert(0, HERE)
import agent_view as av  # noqa: E402

CWD = "/home/u/Apps/canais-front"


class IsAutoLabel(unittest.TestCase):
    def test_auto_labels(self):
        cases = [
            ("canais-front #2", CWD),
            ("\U0001F7E1 canais-front #12", CWD),
            ("CANAIS-FRONT #2", CWD),
            (".claude #3", "/home/u/.claude"),
            ("", CWD),
            ("canais-front", CWD),
            (None, CWD),
        ]
        for label, cwd in cases:
            with self.subTest(label=label, cwd=cwd):
                self.assertTrue(av.is_auto_label(label, cwd))

    def test_manual_labels(self):
        for label in ["canais-front #", "canais-front #2x", "canais-front 2",
                      "other #2", "canais-front #2 x"]:
            with self.subTest(label=label):
                self.assertFalse(av.is_auto_label(label, CWD))

    def test_no_cwd_means_only_empty_is_auto(self):
        self.assertTrue(av.is_auto_label("", ""))
        self.assertFalse(av.is_auto_label("anything", ""))


class DisplayLabelAutoSuffix(unittest.TestCase):
    """display_label: "<repo> #N" é auto -> cai para agent name / título / repo."""

    def ctx(self, label, pane_id="R"):
        return ({"t1": {"label": "dev"}},
                {pane_id: {"pane_id": pane_id, "tab_id": "t1", "label": label}},
                {"t1": 2})

    def a(self, **kw):
        base = {"pane_id": "R", "tab_id": "t1", "workspace_id": "w1",
                "agent": "claude", "cwd": CWD}
        base.update(kw)
        return base

    def test_repo_suffix_falls_to_agent_name(self):
        a = self.a(name="Fix login", terminal_title="zsh")
        self.assertEqual(av.display_label(a, self.ctx("canais-front #2")), "Fix login")

    def test_repo_suffix_falls_to_title_without_agent_name(self):
        a = self.a(terminal_title="zsh")
        self.assertEqual(av.display_label(a, self.ctx("canais-front #2")), "zsh")

    def test_repo_suffix_falls_to_repo_when_nothing_else(self):
        a = self.a()
        self.assertEqual(av.display_label(a, self.ctx("canais-front #2")), "canais-front")

    def test_manual_label_wins_over_agent_name(self):
        a = self.a(name="Fix login")
        self.assertEqual(av.display_label(a, self.ctx("logs")), "logs")

    def test_foreground_cwd_decides_auto_not_stored_cwd(self):
        # cwd em foreground é outro repo: "canais-front #2" vira manual aqui.
        a = self.a(foreground_cwd="/home/u/other", name="Fix login")
        self.assertEqual(av.display_label(a, self.ctx("canais-front #2")), "canais-front #2")


if __name__ == "__main__":
    unittest.main()
