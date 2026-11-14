"""herdr-plugin.toml: versão 0.10.1 e eventos de sync (sem pane.updated)."""
import os
import tomllib
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def load():
    with open(os.path.join(ROOT, "herdr-plugin.toml"), "rb") as f:
        return tomllib.load(f)


class Manifest(unittest.TestCase):
    def setUp(self):
        self.m = load()
        self.events = {e["on"]: e for e in self.m["events"]}

    def test_version(self):
        self.assertEqual(self.m["version"], "0.10.1")

    def test_new_sync_events_registered(self):
        for on in ("workspace.moved", "workspace.reordered", "tab.moved", "pane.moved"):
            with self.subTest(event=on):
                self.assertIn(on, self.events)
                self.assertEqual(self.events[on]["command"], ["bash", "run.sh", "sync"])

    def test_pane_updated_not_registered(self):
        self.assertNotIn("pane.updated", self.events)

    def test_previous_sync_events_still_present(self):
        for on in ("workspace.focused", "workspace.renamed", "tab.renamed",
                   "pane.agent_detected", "pane.created", "pane.closed"):
            with self.subTest(event=on):
                self.assertIn(on, self.events)


if __name__ == "__main__":
    unittest.main()
