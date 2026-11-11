"""Layout B: clean_label, row_tokens, group_marks, row_texts/repo_label e state_path."""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "bin"))
sys.path.insert(0, HERE)
import agent_view as av  # noqa: E402
from _support import agent  # noqa: E402


class CleanLabel(unittest.TestCase):
    def test_leading_emoji_and_symbols_stripped(self):
        self.assertEqual(av.clean_label("🚀 api"), "api")
        self.assertEqual(av.clean_label("● ✨ web-ui"), "web-ui")
        self.assertEqual(av.clean_label("⚙️ infra"), "infra")

    def test_plain_and_empty(self):
        self.assertEqual(av.clean_label("api"), "api")
        self.assertEqual(av.clean_label("123 svc"), "123 svc")
        self.assertEqual(av.clean_label("é-app"), "é-app")
        self.assertEqual(av.clean_label(""), "")
        self.assertEqual(av.clean_label(None), "")

    def test_only_symbols_becomes_empty(self):
        self.assertEqual(av.clean_label("🚀 ✨"), "")


class RowTokens(unittest.TestCase):
    def test_keys_and_values(self):
        self.assertEqual(av.row_tokens("dev", "Work", "├ R"),
                         {"title": "dev", "space": "Work", "sub": "├ R",
                          "tree": None, "subtree": None, "coord": None, "group": None, "group_space": None, "item": None})

    def test_none_and_empty_are_absent(self):
        self.assertEqual(av.row_tokens(None, "", None),
                         {"title": None, "space": None, "sub": None,
                          "tree": None, "subtree": None, "coord": None, "group": None, "group_space": None, "item": None})

    def test_truncated_to_token_max(self):
        out = av.row_tokens("x" * 300, None, "y" * 300)
        self.assertEqual(len(out["title"]), av.TOKEN_MAX_LEN)
        self.assertEqual(len(out["sub"]), av.TOKEN_MAX_LEN)
        self.assertIsNone(out["item"])
        self.assertIsNone(out["space"])


class GroupMarks(unittest.TestCase):
    def test_last_child_gets_corner_others_tee(self):
        marks, parents = av.group_marks(["R", "C1", "C2", "S"], {"C1": "R", "C2": "R"})
        self.assertEqual(marks, {"C1": "├ ", "C2": "└ "})
        self.assertEqual(parents, {"R"})

    def test_single_child_is_last(self):
        marks, parents = av.group_marks(["R", "C"], {"C": "R"})
        self.assertEqual(marks, {"C": "└ "})
        self.assertEqual(parents, {"R"})

    def test_order_follows_seq_not_tree_dict(self):
        marks, _ = av.group_marks(["R", "C2", "C1"], {"C1": "R", "C2": "R"})
        self.assertEqual(marks, {"C2": "├ ", "C1": "└ "})

    def test_two_roots_each_get_own_last_child(self):
        marks, parents = av.group_marks(["A", "a1", "B", "b1", "b2"],
                                        {"a1": "A", "b1": "B", "b2": "B"})
        self.assertEqual(marks, {"a1": "└ ", "b1": "├ ", "b2": "└ "})
        self.assertEqual(parents, {"A", "B"})

    def test_no_tree_no_marks(self):
        self.assertEqual(av.group_marks(["A", "B"], {}), ({}, set()))
        self.assertEqual(av.group_marks(["A", "B"], None), ({}, set()))


class RowTexts(unittest.TestCase):
    """row_texts -> (title, space, sub) conforme README "Sidebar layout"."""
    TABS = {"t1": {"label": "dev"}}
    WS = {"w1": "Work"}

    def ctx(self, panes=None, tabs=None):
        return (self.TABS if tabs is None else tabs, panes or {}, {"t1": 2})

    def test_root_with_children_sub_is_tee_and_repo(self):
        a = agent("R", "t1", "w1", cwd="/x/api")
        self.assertEqual(av.row_texts(a, self.ctx(), self.WS, None, True),
                         ("dev", "Work", "├ api"))

    def test_standalone_root_has_no_item(self):
        a = agent("R", "t1", "w1", cwd="/x/api")
        self.assertEqual(av.row_texts(a, self.ctx(), self.WS, None, False),
                         ("dev", "Work", None))

    def test_child_title_carries_mark_and_no_space_or_item(self):
        a = agent("C", "t1", "w1", cwd="/x/api")
        panes = {"C": {"pane_id": "C", "label": "logs"}}
        self.assertEqual(av.row_texts(a, self.ctx(panes), self.WS, "└ "),
                         ("└ logs", None, None))

    def test_child_mark_prefixes_repo_label_in_title(self):
        a = agent("C", "t1", "w1", cwd="/x/api")
        self.assertEqual(av.row_texts(a, self.ctx(), self.WS, "├ "),
                         ("├ api", None, None))

    def test_numeric_tab_label_falls_back_to_repo_label(self):
        a = agent("R", "t1", "w1", cwd="/x/api")
        for label in ("1", "42"):
            with self.subTest(label=label):
                tabs = {"t1": {"label": label}}
                self.assertEqual(av.row_texts(a, self.ctx(tabs=tabs), self.WS, None, False),
                                 ("api", "Work", None))

    def test_numeric_tab_label_with_children_keeps_sub(self):
        a = agent("R", "t1", "w1", cwd="/x/api")
        tabs = {"t1": {"label": "1"}}
        self.assertEqual(av.row_texts(a, self.ctx(tabs=tabs), self.WS, None, True),
                         ("api", "Work", "├ api"))

    def test_partly_numeric_tab_label_is_kept(self):
        a = agent("R", "t1", "w1", cwd="/x/api")
        tabs = {"t1": {"label": "1a"}}
        self.assertEqual(av.row_texts(a, self.ctx(tabs=tabs), self.WS, None, False)[0], "1a")

    def test_blank_tab_label_falls_back_to_repo_label(self):
        a = agent("R", "t1", "w1", cwd="/x/api")
        tabs = {"t1": {"label": "   "}}
        self.assertEqual(av.row_texts(a, self.ctx(tabs=tabs), self.WS, None, False)[0], "api")

    def test_missing_tab_record_falls_back_to_repo_label(self):
        a = agent("R", "t9", "w1", cwd="/x/api")
        self.assertEqual(av.row_texts(a, ({}, {}, {}), self.WS, None, False),
                         ("api", "Work", None))

    def test_missing_tab_and_cwd_uses_terminal_title(self):
        a = {"pane_id": "R", "tab_id": "t9", "workspace_id": "w1", "agent": "claude",
             "terminal_title": "vim"}
        title, space, item = av.row_texts(a, ({}, {}, {}), self.WS, None, False)
        self.assertEqual((title, space), ("vim", "Work"))

    def test_display_label_pane_label_strips_emoji(self):
        a = agent("R", "t1", "w1", cwd="/x/api")
        panes = {"R": {"pane_id": "R", "label": "🔥 billing"}}
        self.assertEqual(av.display_label(a, self.ctx(panes)), "billing")

    def test_display_label_priority_title_before_cwd(self):
        # Contrato: terminal title (c) vem antes do basename do cwd (d).
        a = agent("R", "t1", "w1", title="zsh", cwd="/home/u/proj/")
        self.assertEqual(av.display_label(a, self.ctx()), "zsh")

    def test_display_label_falls_back_to_title_then_agent(self):
        a = {"pane_id": "Z", "tab_id": "t1", "workspace_id": "w1", "agent": "claude",
             "terminal_title": "🧠 notes", "cwd": ""}
        self.assertEqual(av.display_label(a, self.ctx()), "notes")
        b = {"pane_id": "Y", "tab_id": "t1", "workspace_id": "w1", "agent": "codex", "cwd": ""}
        self.assertEqual(av.display_label(b, self.ctx()), "codex")


class DisplayLabel(unittest.TestCase):
    """display_label(a, ctx): manual (a) > agent name (b) > title (c) > repo (d) > kind (e).
    Testa a função real; só `ctx` é construído à mão (sem socket)."""

    def ctx(self, label=None, pane_id="R"):
        panes = {pane_id: {"pane_id": pane_id, "tab_id": "t1", "label": label}} if label is not None else {}
        return ({"t1": {"label": "dev"}}, panes, {"t1": 2})

    def a(self, **kw):
        base = {"pane_id": "R", "tab_id": "t1", "workspace_id": "w1",
                "agent": "claude", "cwd": "/home/u/proj"}
        base.update(kw)
        return base

    # --- detecção de label automático (manual igual ao basename do cwd) ---
    def test_emoji_label_equal_to_cwd_basename_is_auto(self):
        a = self.a(cwd="/home/u/Apps", terminal_title="zsh")
        self.assertEqual(av.display_label(a, self.ctx("🟡 Apps")), "zsh")

    def test_dotted_cwd_with_emoji_label_is_auto(self):
        a = self.a(cwd="/home/u/.claude", terminal_title="zsh")
        self.assertEqual(av.display_label(a, self.ctx("🟢 .claude")), "zsh")

    def test_auto_detection_is_case_insensitive(self):
        a = self.a(cwd="/x/apps", terminal_title="zsh")
        self.assertEqual(av.display_label(a, self.ctx("APPS")), "zsh")

    def test_trailing_slash_in_cwd_still_detects_auto(self):
        a = self.a(cwd="/home/u/Apps/", terminal_title="zsh")
        self.assertEqual(av.display_label(a, self.ctx("🟡 Apps")), "zsh")

    def test_manual_label_differs_from_cwd_is_kept(self):
        a = self.a(cwd="/home/u/Apps", terminal_title="zsh")
        self.assertEqual(av.display_label(a, self.ctx("troca-dados logs")), "troca-dados logs")

    # --- cadeia de fallback, um degrau por vez ---
    def test_step_a_manual_label_beats_name_title_and_repo(self):
        a = self.a(name="Agent X", terminal_title="zsh", cwd="/x/api")
        self.assertEqual(av.display_label(a, self.ctx("🔥 billing")), "billing")

    def test_step_b_name_beats_title_and_repo(self):
        a = self.a(name="Refactor auth", terminal_title="zsh", cwd="/x/api")
        self.assertEqual(av.display_label(a, self.ctx()), "Refactor auth")

    def test_step_b_name_beats_title_when_manual_is_auto(self):
        a = self.a(name="Refactor auth", terminal_title="zsh", cwd="/home/u/Apps")
        self.assertEqual(av.display_label(a, self.ctx("🟡 Apps")), "Refactor auth")

    def test_step_b_blank_name_is_skipped(self):
        a = self.a(name="   ", terminal_title="zsh", cwd="/x/api")
        self.assertEqual(av.display_label(a, self.ctx()), "zsh")

    def test_step_c_cleaned_terminal_title_beats_repo(self):
        a = self.a(terminal_title="🧠 notes", cwd="/x/api")
        self.assertEqual(av.display_label(a, self.ctx()), "notes")

    def test_step_c_prefers_terminal_title_stripped(self):
        a = self.a(terminal_title_stripped="api", terminal_title="🔥 raw", cwd="/x/other")
        self.assertEqual(av.display_label(a, self.ctx()), "api")

    def test_step_c_emoji_only_title_is_skipped(self):
        a = self.a(terminal_title="🚀 ✨", cwd="/x/api")
        self.assertEqual(av.display_label(a, self.ctx()), "api")

    def test_step_d_repo_basename_without_leading_dots(self):
        a = self.a(cwd="/x/.hidden/")
        self.assertEqual(av.display_label(a, self.ctx()), "hidden")

    def test_step_d_repo_used_when_only_source(self):
        a = self.a(cwd="/x/api")
        self.assertEqual(av.display_label(a, self.ctx()), "api")

    def test_step_e_agent_kind_when_nothing_else(self):
        a = {"pane_id": "R", "tab_id": "t1", "workspace_id": "w1", "agent": "codex", "cwd": ""}
        self.assertEqual(av.display_label(a, self.ctx()), "codex")

    def test_foreground_cwd_preferred_over_cwd_for_repo(self):
        a = self.a(foreground_cwd="/x/fg", cwd="/x/old")
        self.assertEqual(av.display_label(a, self.ctx()), "fg")

    # --- nunca vazio quando existe alguma fonte ---
    def test_never_empty_when_any_single_source_exists(self):
        sources = {
            "manual": (self.a(cwd="", agent=""), self.ctx("billing")),
            "name": (self.a(name="N", cwd="", agent=""), self.ctx()),
            "title": (self.a(terminal_title="vim", cwd="", agent=""), self.ctx()),
            "repo": (self.a(cwd="/x/api", agent=""), self.ctx()),
            "kind": (self.a(cwd="", agent="claude"), self.ctx()),
        }
        for src, (a, ctx) in sources.items():
            with self.subTest(source=src):
                self.assertTrue(av.display_label(a, ctx))

    def test_empty_only_when_no_source_at_all(self):
        a = {"pane_id": "R", "tab_id": "t1", "workspace_id": "w1", "agent": "", "cwd": ""}
        self.assertEqual(av.display_label(a, self.ctx()), "")

    # --- alias e consumidores ---
    def test_display_label_alias_is_removed(self):
        # Alias removido no 0.10.0: consumidores usam display_label.
        self.assertFalse(hasattr(av, "repo_label"))

    def test_child_title_uses_display_label_chain(self):
        a = self.a(terminal_title="vim", cwd="/x/api")
        self.assertEqual(av.row_texts(a, self.ctx(), {"w1": "Work"}, "└ "),
                         ("└ vim", None, None))

    def test_numeric_tab_fallback_uses_display_label_chain(self):
        a = self.a(name="Refactor auth", cwd="/x/api")
        c = ({"t1": {"label": "1"}}, {}, {"t1": 1})
        self.assertEqual(av.row_texts(a, c, {"w1": "Work"}, None, False),
                         ("Refactor auth", "Work", None))


class StatePathFallback(unittest.TestCase):
    """Sem HERDR_PLUGIN_STATE_DIR: ~/.local/state/... (nunca o CWD)."""

    def setUp(self):
        self._env = {k: os.environ.get(k) for k in ("HERDR_PLUGIN_STATE_DIR", "HOME")}
        self._cwd = os.getcwd()
        self.home = tempfile.mkdtemp()
        self.cwd = tempfile.mkdtemp()
        os.environ.pop("HERDR_PLUGIN_STATE_DIR", None)
        os.environ["HOME"] = self.home
        os.chdir(self.cwd)

    def tearDown(self):
        os.chdir(self._cwd)
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_fallback_under_home_local_state(self):
        expected = os.path.join(self.home, ".local", "state", "herdr", "plugins",
                                "andpeicunha.agent-view-filters", "state.json")
        self.assertEqual(av.state_path(), expected)

    def test_never_writes_into_cwd(self):
        self.assertEqual(av.read_state(), {})
        av.write_state("picked", ["R"])
        self.assertEqual(os.listdir(self.cwd), [])
        self.assertTrue(os.path.exists(av.state_path()))

    def test_env_dir_wins_when_set(self):
        d = tempfile.mkdtemp()
        os.environ["HERDR_PLUGIN_STATE_DIR"] = d
        self.assertEqual(av.state_path(), os.path.join(d, "state.json"))


if __name__ == "__main__":
    unittest.main()
