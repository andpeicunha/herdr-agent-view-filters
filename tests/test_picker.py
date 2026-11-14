"""Picker: make_rows, collect_excluded, move_cursor, draw_row (puras) + build_rows com send mockado."""
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "bin"))
sys.path.insert(0, HERE)
import curses  # noqa: E402
import agent_view as av  # noqa: E402
import picker  # noqa: E402
from _support import Isolated, FakeHerdr, agent, pane, mocked  # noqa: E402

# Cenário: w1 "Work" (idx 0) tem dev (R + filho C) e ops (A); w2 "Home" tem home (S).
AGENTS = [
    agent("R", "t1", "w1", status="idle"),
    agent("C", "t1", "w1", status="done", title="zsh"),
    agent("A", "t2", "w1", status="working"),
    agent("S", "t3", "w2", status="idle"),
]
PANES = [
    pane("R", "t1", "w1"),
    pane("C", "t1", "w1", parent="R", label="logs"),
    pane("A", "t2", "w1"),
    pane("S", "t3", "w2"),
]
TABS = {"t1": {"label": "dev"}, "t2": {"label": "ops"}, "t3": {"label": "home"}}
WS = {"w1": "Work", "w2": "Home"}
WS_IDX = {"w1": 0, "w2": 1}
TREE = {"C": "R"}


def ctx():
    return (TABS, {p["pane_id"]: p for p in PANES}, {"t1": 2, "t2": 1, "t3": 1})


def rows_for(excluded=()):
    return picker.make_rows(AGENTS, ctx(), WS, WS_IDX, list(excluded), TREE)


def find(rows, kind, pane_id=None, label=None):
    """Row lookup by content (not index), so layout changes do not break tests."""
    for r in rows:
        if r["kind"] != kind:
            continue
        if pane_id is not None and r.get("pane_id") != pane_id:
            continue
        if label is not None and r.get("label") != label:
            continue
        return r
    raise AssertionError(f"row {kind} {pane_id} not found")


def space(rows, wid):
    return next(r for r in rows if r["kind"] == "space" and r["id"] == wid)


def summary(rows):
    out = []
    for r in rows:
        if r["kind"] == "space":
            out.append(("space", r["id"], r["count"], r["checked"]))
        elif r["kind"] == "root":
            out.append(("root", r["pane_id"], r["label"], r["checked"]))
        elif r["kind"] == "item":
            out.append(("item", r["label"]))
        else:
            out.append(("child", r["pane_id"], r["label"]))
    return out


class MakeRows(unittest.TestCase):
    def test_sidebar_like_order_and_shape(self):
        self.assertEqual(summary(rows_for()), [
            ("space", "w1", 3, True),
            ("root", "R", "dev · Work", True),
            ("item", "├ ◆ R"),
            ("child", "C", "└ logs"),
            ("root", "A", "ops · Work", True),
            ("space", "w2", 1, True),
            ("root", "S", "home · Home", True),
        ])

    def test_child_has_no_checkbox_and_is_not_selectable(self):
        child = find(rows_for(), "child", "C")
        self.assertFalse(child["selectable"])
        self.assertNotIn("checked", child)
        self.assertEqual(child["status"], "done")

    def test_item_rows_are_not_selectable_and_have_no_pane(self):
        for r in rows_for():
            if r["kind"] == "item":
                with self.subTest(label=r["label"]):
                    self.assertFalse(r["selectable"])
                    self.assertNotIn("pane_id", r)

    def test_excluded_space_and_root_unchecked(self):
        rows = rows_for(["space:w1", "A"])
        self.assertFalse(space(rows, "w1")["checked"])
        self.assertFalse(find(rows, "root", "A")["checked"])
        self.assertTrue(space(rows, "w2")["checked"])
        self.assertTrue(find(rows, "root", "S")["checked"])

    def test_child_id_in_excluded_has_no_effect_on_rows(self):
        rows = rows_for(["C"])
        self.assertEqual([r["checked"] for r in rows if r["kind"] == "root"], [True, True, True])

    def test_root_label_uses_title_before_repo_without_tab_label(self):
        # Contrato: display_label -> terminal title (c) antes do repo (d).
        c = ({}, {"R": {"pane_id": "R", "tab_id": "t1"}}, {"t1": 1})
        rows = picker.make_rows([agent("R", "t1", "w1", title="vim")], c, WS, WS_IDX, [], {})
        self.assertEqual(find(rows, "root", "R")["label"], "vim · Work")

    def test_root_label_falls_back_to_repo_without_title_or_tab_label(self):
        c = ({}, {"R": {"pane_id": "R", "tab_id": "t1"}}, {"t1": 1})
        rows = picker.make_rows([agent("R", "t1", "w1", cwd="/x/api")], c, WS, WS_IDX, [], {})
        self.assertEqual(find(rows, "root", "R")["label"], "api · Work")

    def test_numeric_tab_label_uses_repo_label_in_root_label(self):
        agents = [agent("R", "t1", "w1", cwd="/x/api")]
        c = ({"t1": {"label": "1"}}, {"R": {"pane_id": "R", "tab_id": "t1"}}, {"t1": 1})
        rows = picker.make_rows(agents, c, WS, WS_IDX, [], {})
        self.assertEqual(find(rows, "root", "R")["label"], "api · Work")

    def test_standalone_root_emits_no_item_row(self):
        rows = rows_for()
        i = next(k for k, r in enumerate(rows) if r["kind"] == "root" and r["pane_id"] == "A")
        self.assertEqual(rows[i + 1]["kind"], "space")

    def test_coordinator_item_row_present_even_without_repo_text(self):
        # Coordenadora (root com filho) sem nome: item usa o fallback '◆ orch'.
        agents = [{"pane_id": "R", "tab_id": "t1", "workspace_id": "w1",
                   "agent": "", "cwd": "", "agent_status": "idle"},
                  agent("C", "t1", "w1", cwd="/x/C")]
        panes = [pane("R", "t1", "w1"), pane("C", "t1", "w1", parent="R")]
        c = (TABS, {p["pane_id"]: p for p in panes}, {"t1": 2})
        rows = picker.make_rows(agents, c, WS, WS_IDX, [], {"C": "R"})
        self.assertEqual([r["kind"] for r in rows], ["space", "root", "item", "child"])
        self.assertEqual([r["label"] for r in rows if r["kind"] == "item"], ["├ ◆ orch"])
        self.assertEqual(find(rows, "child", "C")["label"], "└ C")

    def test_root_label_last_resort_is_pane_id(self):
        c = ({}, {"R": {"pane_id": "R"}}, {})
        rows = picker.make_rows([agent("R", "t9", "w1")], c, WS, WS_IDX, [], {})
        self.assertEqual(find(rows, "root", "R")["label"], "R · Work")

    def test_tab_fallback_root_entry_is_tab_token(self):
        # Sem parent token: R e C na mesma tab -> C é filho por fallback; entry = "tab:t1".
        agents = [agent("R", "t1", "w1"), agent("C", "t1", "w1")]
        panes = [pane("R", "t1", "w1"), pane("C", "t1", "w1")]
        tree = av.current_tree(agents, panes, group_by_tab=True)
        self.assertEqual(tree, {"C": "R"})
        c = (TABS, {p["pane_id"]: p for p in panes}, {"t1": 2})  # sem parent token
        rows = picker.make_rows(agents, c, WS, WS_IDX, [], tree)
        self.assertEqual(find(rows, "root", "R")["entry"], "tab:t1")
        self.assertEqual(find(rows, "root", "R")["label"], "dev · Work")


class CollectExcluded(unittest.TestCase):
    def test_unchecked_space_and_root_only(self):
        rows = rows_for()
        space(rows, "w1")["checked"] = False
        find(rows, "root", "A")["checked"] = False
        self.assertEqual(picker.collect_excluded(rows), ["space:w1", "A"])

    def test_nothing_unchecked_is_empty(self):
        self.assertEqual(picker.collect_excluded(rows_for()), [])

    def test_child_never_collected(self):
        rows = rows_for()
        find(rows, "child", "C")["checked"] = False  # sem checkbox: não pode vazar
        self.assertEqual(picker.collect_excluded(rows), [])

    def test_unchecked_tab_root_saved_as_tab_entry(self):
        rows = [dict(r) for r in rows_for()]
        r = find(rows, "root", "R")
        r["entry"] = "tab:t1"
        r["checked"] = False
        self.assertEqual(picker.collect_excluded(rows), ["tab:t1"])

    def test_round_trip_through_make_rows(self):
        rows = rows_for(["space:w2", "R"])
        self.assertEqual(sorted(picker.collect_excluded(rows)), ["R", "space:w2"])


class CollectExcludedExisting(unittest.TestCase):
    """collect_excluded(rows, existing): space:/tab: sem linha no picker são mantidos."""

    def test_space_and_tab_entries_without_row_are_kept(self):
        self.assertEqual(picker.collect_excluded(rows_for(), ["space:w9", "tab:t9", "A"]),
                         ["space:w9", "tab:t9"])

    def test_pane_id_entries_are_not_carried_over(self):
        # "A" tem linha (checada): não volta por `existing`.
        self.assertEqual(picker.collect_excluded(rows_for(), ["A"]), [])

    def test_existing_space_with_row_not_duplicated(self):
        rows = rows_for()
        space(rows, "w1")["checked"] = False
        self.assertEqual(picker.collect_excluded(rows, ["space:w1", "space:w9"]),
                         ["space:w9", "space:w1"])

    def test_checked_row_drops_existing_entry(self):
        # space:w1 tem linha e está marcada: a linha manda, `existing` não reabre.
        self.assertEqual(picker.collect_excluded(rows_for(), ["space:w1"]), [])

    def test_tab_entry_without_row_kept_when_root_shown_by_pane_id(self):
        # R é mostrada pelo pane id (não é tab-fallback root): "tab:t1" sem linha.
        self.assertEqual(picker.collect_excluded(rows_for(), ["tab:t1"]), ["tab:t1"])


class MoveCursor(unittest.TestCase):
    def setUp(self):
        # 0 space w1, 1 root R, 2 item, 3 child C, 4 root A (standalone: no item),
        # 5 space w2, 6 root S (standalone: no item)
        self.rows = rows_for()
        self.assertEqual([r["kind"] for r in self.rows],
                         ["space", "root", "item", "child", "root", "space", "root"])

    def test_start_is_first_selectable(self):
        self.assertEqual(picker.move_cursor(self.rows, -1, 1), 0)

    def test_down_skips_item_and_child(self):
        self.assertEqual(picker.move_cursor(self.rows, 1, 1), 4)

    def test_up_skips_item_and_child(self):
        self.assertEqual(picker.move_cursor(self.rows, 4, -1), 1)

    def test_edges_stay_put(self):
        self.assertEqual(picker.move_cursor(self.rows, 0, -1), 0)
        self.assertEqual(picker.move_cursor(self.rows, 6, 1), 6)

    def test_end_home_style_jumps(self):
        self.assertEqual(picker.move_cursor(self.rows, len(self.rows), -1), 6)
        self.assertEqual(picker.move_cursor(self.rows, -1, 1), 0)

    def test_no_selectable_rows_returns_cur(self):
        self.assertEqual(picker.move_cursor([{"selectable": False}], -1, 1), -1)


class FakeScreen:
    """Boundary de tela (curses): registra addnstr(y, x, text, n, attr)."""

    def __init__(self):
        self.out = []

    def addnstr(self, y, x, text, n, attr=0):
        self.out.append((y, x, text, attr))


class DrawRowDerivedDim(unittest.TestCase):
    """Root sob space desmarcado: desenhado desmarcado/dim, sem mudar o checkbox."""

    def draw(self, r, space_on):
        scr = FakeScreen()
        picker.draw_row(scr, 0, r, 0, space_on, False, 80)
        return "".join(t for _, _, t, _ in scr.out), scr.out

    def root(self, checked):
        return {"kind": "root", "pane_id": "R", "entry": "R", "status": "idle",
                "label": "dev · Work", "checked": checked, "selectable": True}

    def test_root_checked_under_checked_space_shows_x(self):
        text, _ = self.draw(self.root(True), True)
        self.assertIn("[x]", text)

    def test_root_checked_under_unchecked_space_is_drawn_unticked_and_dim(self):
        text, out = self.draw(self.root(True), False)
        self.assertIn("[ ]", text)
        self.assertNotIn("[x]", text)
        self.assertTrue(all(attr & curses.A_DIM for _, _, t, attr in out if t.strip() == "[ ]"))

    def test_item_row_text(self):
        text, _ = self.draw({"kind": "item", "label": "├ R", "selectable": False}, True)
        self.assertIn("├ R", text)


class BuildRowsWiring(Isolated):
    def test_build_rows_uses_parent_token_and_saved_exclusions(self):
        av.write_state("picked", ["space:w2"])
        tabs = [{"tab_id": "t1", "label": "dev"}, {"tab_id": "t2", "label": "ops"},
                {"tab_id": "t3", "label": "home"}]
        h = FakeHerdr(AGENTS, PANES, tabs=tabs)
        with mocked(h):
            rows, excluded = picker.build_rows()
        self.assertEqual(excluded, ["space:w2"])
        self.assertEqual([r["kind"] for r in rows],
                         ["space", "root", "item", "child", "root", "space", "root"])
        self.assertFalse(space(rows, "w2")["checked"])
        self.assertEqual(find(rows, "child", "C")["label"], "└ logs")


class RemovedPickerApis(unittest.TestCase):
    def test_manual_order_helpers_gone(self):
        for name in ("resort", "displayed_space_order"):
            with self.subTest(name=name):
                self.assertFalse(hasattr(picker, name))


class LoneTabToggle(Isolated):
    """Root sozinha em tab excluída: linha com entry "tab:<id>", desmarcada;
    marcar remove a entrada da tab e a root aparece."""

    def test_lone_root_row_uses_tab_entry_and_starts_unchecked(self):
        rows = rows_for(["tab:t2"])
        r = find(rows, "root", "A")
        self.assertEqual((r["entry"], r["checked"]), ("tab:t2", False))

    def test_checking_lone_root_removes_tab_entry(self):
        rows = rows_for(["tab:t2"])
        find(rows, "root", "A")["checked"] = True
        self.assertEqual(picker.collect_excluded(rows, ["tab:t2"]), [])

    def test_unchecking_lone_root_saves_tab_entry(self):
        rows = rows_for()
        find(rows, "root", "A")["checked"] = False
        self.assertEqual(picker.collect_excluded(rows), ["A"])  # sem tab excluída: id
        rows = rows_for(["tab:t2"])
        find(rows, "root", "A")["checked"] = False
        self.assertEqual(picker.collect_excluded(rows), ["tab:t2"])

    def test_end_to_end_save_reveals_lone_root(self):
        av.write_state("picked", ["tab:t2"])
        h = FakeHerdr(AGENTS, PANES, tabs=[{"tab_id": "t1"}, {"tab_id": "t2"}, {"tab_id": "t3"}])

        def wrapper(fn, rows):  # usuário marca A e confirma
            find(rows, "root", "A")["checked"] = True
            return True

        with mocked(h), mock.patch.object(picker.curses, "wrapper", side_effect=wrapper):
            picker.main()
        self.assertEqual(self.state_file()["excluded"], [])
        values = h.methods("agent.view.set")[-1]["filter"]["filter"]["values"]
        self.assertNotIn("A", values)

    def test_two_lone_roots_in_one_tab_toggle_one_reveals_it(self):
        # group_by_tab=false: duas roots sozinhas na mesma tab compartilham "tab:t2".
        # Marcar uma e salvar NÃO pode re-esconder: a outra linha desmarcada re-adiciona
        # a entrada. Este teste FALHA com o código atual (achado).
        agents = [agent("A", "t2"), agent("B", "t2")]
        panes = [pane("A", "t2"), pane("B", "t2")]
        ctx2 = ({"t2": {"label": "ops"}}, {p["pane_id"]: p for p in panes}, {"t2": 2})
        rows = picker.make_rows(agents, ctx2, WS, WS_IDX, ["tab:t2"], {})
        find(rows, "root", "A")["checked"] = True
        self.assertNotIn("tab:t2", picker.collect_excluded(rows, ["tab:t2"]))


class MergeExcluded(unittest.TestCase):
    """merge_excluded: a lista salva = linhas do picker + entradas concorrentes sem linha."""

    def test_concurrent_entries_without_row_are_kept(self):
        rows = rows_for(["A"])
        self.assertEqual(sorted(picker.merge_excluded(rows, ["A"], ["A", "N", "space:w9"])),
                         ["A", "N", "space:w9"])

    def test_entry_removed_in_picker_is_not_resurrected(self):
        rows = rows_for()  # A marcada
        self.assertEqual(picker.merge_excluded(rows, ["A"], ["A"]), [])

    def test_stale_entry_without_row_already_in_old_is_dropped(self):
        # "X" estava no picker (old) e já não existe: não volta pelo fresh.
        self.assertEqual(picker.merge_excluded(rows_for(), ["X"], ["X"]), [])


if __name__ == "__main__":
    unittest.main()
