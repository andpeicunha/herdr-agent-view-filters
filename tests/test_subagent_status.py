"""Dot status: idle/done + subagente ativo (arquivo do hook) => working."""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "bin"))
sys.path.insert(0, HERE)
import agent_view as av  # noqa: E402

NOW = 1_000_000.0


class SubagentStatusTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def write(self, pane, text):
        with open(os.path.join(self.tmp.name, pane), "w") as f:
            f.write(text)

    def status(self, st, pane="p1"):
        return av.effective_status({"pane_id": pane, "agent_status": st},
                                   now=NOW, directory=self.tmp.name)

    def test_idle_with_active_subagent_is_working(self):
        self.write("p1", "a1 %d\n" % (NOW - 60))
        self.assertEqual(self.status("idle"), "working")
        self.assertEqual(self.status("done"), "working")

    def test_expired_entry_keeps_status(self):
        self.write("p1", "a1 %d\n" % (NOW - av.SUBAGENT_TTL_S - 1))
        self.assertEqual(self.status("idle"), "idle")

    def test_missing_file_unchanged(self):
        self.assertEqual(self.status("idle"), "idle")
        self.assertEqual(self.status("done"), "done")

    def test_malformed_lines_ignored(self):
        self.write("p1", "garbage\na1 notanumber\na2 nan\na3 1 2\n\n")
        self.assertEqual(self.status("idle"), "idle")
        self.write("p1", "garbage\na1 %d\n" % (NOW - 5))
        self.assertEqual(self.status("idle"), "working")

    def test_blocked_and_working_untouched(self):
        self.write("p1", "a1 %d\n" % (NOW - 5))
        self.assertEqual(self.status("blocked"), "blocked")
        self.assertEqual(self.status("working"), "working")

    def test_plugin_never_writes(self):
        self.status("idle")
        self.assertEqual(os.listdir(self.tmp.name), [])


if __name__ == "__main__":
    unittest.main()
