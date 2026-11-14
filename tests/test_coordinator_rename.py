"""Coordinator pane renamed ONCE to `coordinator_label` (default "orch") by sync.
Mocks: av.send (via _support.mocked) and av.subprocess.run (Isolated.rename_run)."""
import contextlib
import io
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "bin"))
sys.path.insert(0, HERE)
import agent_view as av  # noqa: E402
from _support import Isolated, FakeHerdr, agent, pane, mocked  # noqa: E402

ARGV = ["herdr", "pane", "rename", "R", "orch"]
needs_toml = unittest.skipIf(av.tomllib is None, "config.toml needs tomllib (py3.11+)")


def ok(argv, **kw):
    return subprocess.CompletedProcess(argv, 0, "", "")


def family(label=None, with_child=True):
    agents = [agent("R", "t1")] + ([agent("C", "t1")] if with_child else [])
    panes = [pane("R", "t1", label=label)] + (
        [pane("C", "t1", parent="R")] if with_child else [])
    return FakeHerdr(agents, panes)


class RenameBase(Isolated):
    def setUp(self):
        super().setUp()
        self.rename_run.side_effect = ok

    def sync(self, h, mode="picked"):
        err = io.StringIO()
        with mocked(h), contextlib.redirect_stderr(err):
            av.apply_mode(mode, [])
        self.err = err.getvalue()

    def calls(self):
        return [c.args[0] for c in self.rename_run.call_args_list]


class RenameOnce(RenameBase):
    def test_transition_renames_once_with_exact_argv(self):
        self.sync(family())
        self.assertEqual(self.calls(), [ARGV])
        kw = self.rename_run.call_args.kwargs
        self.assertEqual(kw, dict(check=True, capture_output=True, text=True, timeout=5))
        self.assertEqual(self.state_file()["renamed_coordinators"], ["R"])

    def test_second_sync_makes_no_call(self):
        h = family()
        self.sync(h)
        self.sync(h)
        self.assertEqual(self.calls(), [ARGV])

    def test_coord_token_in_same_sync(self):
        h = family()
        self.sync(h)
        self.assertEqual(h.tokens()["R"]["coord"], "◆ orch")

    def test_already_named_target_no_call_but_marked(self):
        self.sync(family(label="orch"))
        self.assertEqual(self.calls(), [])
        self.assertEqual(self.state_file()["renamed_coordinators"], ["R"])

    def test_already_named_target_with_emoji_prefix(self):
        self.sync(family(label="◆ orch"))
        self.assertEqual(self.calls(), [])

    def test_non_coordinator_never_renamed(self):
        self.sync(family(with_child=False))
        self.assertEqual(self.calls(), [])
        self.assertNotIn("renamed_coordinators", self.state_file())

    def test_every_mode(self):
        for mode in av.MODES:
            with self.subTest(mode=mode):
                self.rename_run.reset_mock()
                av.write_state("picked", [], renamed_coordinators=[])
                h = family()
                self.sync(h, mode)
                self.assertEqual(self.calls(), [ARGV])
                self.assertEqual(h.tokens()["R"]["coord"], "◆ orch")


class ManualRenameKept(RenameBase):
    def test_manual_rename_not_reverted(self):
        h = family()
        self.sync(h)
        h.panes[0]["label"] = "mine"  # user renames after ours
        self.sync(h)
        self.assertEqual(self.calls(), [ARGV])
        self.assertEqual(h.tokens()["R"]["coord"], "◆ mine")

    def test_not_reverted_after_losing_and_regaining_children(self):
        h = family()
        self.sync(h)
        h.panes[0]["label"] = "mine"
        solo = family(label="mine", with_child=False)
        self.sync(solo)  # no longer a coordinator, still alive
        self.assertEqual(self.state_file()["renamed_coordinators"], ["R"])
        h2 = family(label="mine")
        self.sync(h2)  # coordinator again
        self.assertEqual(self.calls(), [ARGV])


class Failures(RenameBase):
    def check(self, exc):
        h = family()
        self.rename_run.side_effect = exc
        self.sync(h)  # must complete
        self.assertEqual(len(h.methods("agent.view.set")), 1)
        self.assertTrue(h.methods("pane.report_metadata"))
        self.assertEqual(len(self.err.strip().splitlines()), 1)
        self.assertIn("rename", self.err)
        self.assertNotIn("renamed_coordinators", self.state_file())
        self.assertNotEqual(h.tokens()["R"]["coord"], "◆ orch")
        self.rename_run.side_effect = ok  # retried next sync
        self.sync(h)
        self.assertEqual(self.calls(), [ARGV, ARGV])
        self.assertEqual(self.state_file()["renamed_coordinators"], ["R"])
        self.assertEqual(h.tokens()["R"]["coord"], "◆ orch")

    def test_called_process_error(self):
        self.check(subprocess.CalledProcessError(1, ARGV, "", "boom"))

    def test_file_not_found(self):
        self.check(FileNotFoundError("herdr"))

    def test_timeout(self):
        self.check(subprocess.TimeoutExpired(ARGV, 5))


@needs_toml
class ConfigDriven(RenameBase):
    def test_disabled_empty_label_no_calls(self):
        for text in ('coordinator_label = ""\n', 'coordinator_label = "   "\n'):
            with self.subTest(text=text):
                self.write_config(text)
                self.sync(family())
                self.assertEqual(self.calls(), [])
                self.assertNotIn("renamed_coordinators", self.state_file())

    def test_custom_label(self):
        self.write_config('coordinator_label = "boss"\n')
        h = family()
        self.sync(h)
        self.assertEqual(self.calls(), [["herdr", "pane", "rename", "R", "boss"]])
        self.assertEqual(h.tokens()["R"]["coord"], "◆ boss")


class Pruning(RenameBase):
    def test_gone_panes_pruned(self):
        av.write_state("picked", [], renamed_coordinators=["R", "GONE"])
        h = family()
        self.sync(h)
        self.assertEqual(self.calls(), [])
        self.assertEqual(self.state_file()["renamed_coordinators"], ["R"])

    def test_pruned_pane_id_is_renamed_again_if_it_returns(self):
        av.write_state("picked", [], renamed_coordinators=["R"])
        self.sync(FakeHerdr([agent("X", "t2")], [pane("X", "t2")]))
        self.assertNotIn("renamed_coordinators", self.state_file())
        self.sync(family())
        self.assertEqual(self.calls(), [ARGV])


if __name__ == "__main__":
    unittest.main()
