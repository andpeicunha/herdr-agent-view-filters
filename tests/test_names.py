"""Naming tool keeps a cross-tab group anchored to its root tab."""

import contextlib
import io
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bin"))
import names  # noqa: E402


SNAP = {
    "agents": [{"pane_id": "root"}, {"pane_id": "child"}],
    "panes": [
        {"pane_id": "root", "tab_id": "task-tab"},
        {"pane_id": "child", "tab_id": "child-tab"},
    ],
    "tabs": [{"tab_id": "task-tab", "label": "Antigo"},
             {"tab_id": "child-tab", "label": "Filho"}],
    "group_by_tab": True,
}


class NamingTests(unittest.TestCase):
    def test_child_group_name_changes_root_tab_and_its_own_label(self):
        with mock.patch.object(names.agent_view, "current_tree",
                               return_value={"child": "root"}):
            operations = names.plan(SNAP, "child", group="  Reserva de aulas  ",
                                    pane="frontend")
        self.assertEqual(operations, [("tab", "task-tab", "reserva-de-aulas"),
                                      ("pane", "child", "frontend")])

    def test_conflicting_group_and_tab_names_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "same tab differently"):
            names.plan(SNAP, "root", group="Reserva", tab="Outra")

    def test_names_are_normalized_and_empty_slugs_rejected(self):
        self.assertEqual(names.label("  Revisão: API & UI  "), "revisao-api-ui")
        with self.assertRaisesRegex(ValueError, "kebab-case"):
            names.label("---")

    def test_preview_never_renames_or_syncs(self):
        output = io.StringIO()
        with mock.patch.object(names, "snapshot", return_value=SNAP), \
             mock.patch.object(names.agent_view, "current_tree",
                               return_value={"child": "root"}), \
             mock.patch.object(names, "apply") as apply, \
             contextlib.redirect_stdout(output):
            self.assertEqual(names.main(["--pane", "child", "--group", "Reserva"]), 0)
        apply.assert_not_called()
        self.assertIn("tab task-tab: Antigo -> reserva", output.getvalue())
        self.assertIn("preview only", output.getvalue())

    def test_apply_uses_herdr_cli_then_refreshes_tokens(self):
        operations = [("tab", "task-tab", "Reserva"),
                      ("pane", "child", "frontend")]
        with mock.patch.object(names.subprocess, "run") as run:
            names.apply(operations)
        self.assertEqual([call.args[0] for call in run.call_args_list], [
            ["herdr", "tab", "rename", "task-tab", "Reserva"],
            ["herdr", "pane", "rename", "child", "frontend"],
            ["herdr", "plugin", "action", "invoke", "sync", "--plugin",
             "andpeicunha.agent-view-filters"],
        ])


if __name__ == "__main__":
    unittest.main()
