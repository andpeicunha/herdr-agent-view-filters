"""Picker: toggle compartilhado, contagem n/m, largura de display (emoji/CJK),
erro numa linha não aborta as outras, tela vazia. Tela curses é fake (boundary)."""
import curses
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "bin"))
sys.path.insert(0, HERE)
import picker  # noqa: E402


class Screen:
    """Fake stdscr: `frame` = textos do quadro atual; `last` = último refresh."""

    def __init__(self, h=20, w=80, fail_on=(), keys=()):
        self.h, self.w = h, w
        self.fail_on = tuple(fail_on)
        self.frame, self.last = [], []
        self.getch_calls = 0

    def getmaxyx(self):
        return (self.h, self.w)

    def erase(self):
        self.frame = []

    def addnstr(self, y, x, text, n, attr=0):
        if any(f in text for f in self.fail_on):
            raise curses.error("simulated edge/bad row")
        self.frame.append((y, x, text, attr))

    def refresh(self):
        self.last = list(self.frame)

    def keypad(self, on):
        pass

    def getch(self):
        self.getch_calls += 1
        return ord("x")

    def text(self):
        return "\n".join(t for _, _, t, _ in self.last)


def space(sid, label, checked, count=0):
    return {"kind": "space", "id": sid, "label": label, "count": count,
            "checked": checked, "selectable": True}


def root(pid, label, checked, entry=None):
    return {"kind": "root", "pane_id": pid, "entry": entry or pid, "status": "idle",
            "label": label, "checked": checked, "selectable": True}


class Toggle(unittest.TestCase):
    def test_rows_sharing_tab_entry_flip_together(self):
        rows = [root("A", "dev · Work", True, entry="tab:t1"),
                root("B", "ops · Work", True, entry="tab:t1"),
                root("X", "x · Work", True)]
        picker.toggle(rows, 0)
        self.assertEqual([r["checked"] for r in rows], [False, False, True])
        picker.toggle(rows, 1)
        self.assertEqual([r["checked"] for r in rows], [True, True, True])

    def test_space_toggle_does_not_touch_roots(self):
        rows = [space("w1", "Work", True), root("A", "a", True)]
        picker.toggle(rows, 0)
        self.assertFalse(rows[0]["checked"])
        self.assertTrue(rows[1]["checked"])


class CountHeader(unittest.TestCase):
    def test_roots_under_unchecked_space_do_not_count_as_shown(self):
        rows = [space("w1", "Work", True), root("A", "a", True), root("B", "b", False),
                space("w2", "Home", False), root("S", "s", True)]
        scr = Screen()
        with mock.patch.object(picker, "init_colors", return_value=False), \
                mock.patch.object(picker, "getkey", side_effect=[ord("q")]):
            self.assertFalse(picker.run(scr, rows))
        self.assertIn("agents shown: 1/3 roots", scr.text())


class DisplayWidth(unittest.TestCase):
    def test_emoji_counts_two_columns(self):
        self.assertEqual(picker.text_width("\U0001F680a"), 3)
        self.assertEqual(picker.text_width("\u6f22\u5b57"), 4)

    def test_clip_never_splits_wide_char(self):
        self.assertEqual(picker.clip("ab\U0001F680cd", 3), "ab")
        self.assertEqual(picker.clip("\U0001F680\U0001F680", 3), "\U0001F680")
        self.assertEqual(picker.clip("abcdef", 4), "abcd")

    def test_put_clips_by_width_and_returns_width_advance(self):
        scr = Screen()
        nxt = picker.put(scr, 0, 0, "\U0001F680" * 3, 0, 6)  # w-1 = 5 colunas úteis
        self.assertEqual(scr.frame[0][2], "\U0001F680\U0001F680")
        self.assertEqual(nxt, 6)


class RowErrorIsolation(unittest.TestCase):
    def test_bad_row_does_not_abort_other_rows(self):
        rows = [space("w1", "Work", True), root("A", "first", True),
                root("B", "BAD", True), root("C", "last", True)]
        scr = Screen(fail_on=("BAD",))
        with mock.patch.object(picker, "init_colors", return_value=False), \
                mock.patch.object(picker, "getkey", side_effect=[ord("q")]):
            picker.run(scr, rows)
        text = scr.text()
        self.assertIn("first", text)
        self.assertIn("last", text)
        self.assertNotIn("BAD", text)


class EmptyScreen(unittest.TestCase):
    def test_show_empty_message_until_key(self):
        scr = Screen()
        picker.show_empty(scr)
        self.assertIn("no agents", [t for _, _, t, _ in scr.frame])
        self.assertEqual(scr.getch_calls, 1)

    def test_main_without_agents_uses_empty_screen(self):
        with mock.patch.object(picker, "build_rows", return_value=([], {})), \
                mock.patch.object(picker.curses, "wrapper") as wrapper, \
                mock.patch.dict(os.environ, {}):
            picker.main()
        wrapper.assert_called_once_with(picker.show_empty)


if __name__ == "__main__":
    unittest.main()
