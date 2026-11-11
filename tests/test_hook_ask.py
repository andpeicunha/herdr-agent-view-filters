"""herdr-guard-coordinator.py (PreToolUse Bash) via subprocess + stdin JSON."""
import json
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from _herdr_stub import Stub, HOOK, mk  # noqa: E402

PANES = [mk("R", role="coordinator"), mk("C", tab="t2", parent="R")]
PROC = {"R": {"shell_pid": 4000, "foreground_process_group_id": 4100,
              "foreground_processes": [{"pid": 4100, "name": "claude"}]},
        "C": {"shell_pid": 5000, "foreground_process_group_id": 5100,
              "foreground_processes": [{"pid": 5100, "name": "claude"}]}}


@unittest.skipUnless(os.path.exists(HOOK), "hook ausente")
class HookAsk(unittest.TestCase):
    def setUp(self):
        self.stub = Stub(PANES, PROC)

    def run_hook(self, cmd, stub=None, tool="Bash"):
        stub = stub or self.stub
        r = subprocess.run([sys.executable, HOOK], env=stub.env, text=True,
                           input=json.dumps({"tool_name": tool,
                                             "tool_input": {"command": cmd}}),
                           capture_output=True, timeout=20)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout) if r.stdout.strip() else None

    def decision(self, cmd, **kw):
        out = self.run_hook(cmd, **kw)
        return out["hookSpecificOutput"]["permissionDecision"] if out else "allow"

    def test_closes_ask(self):
        for c in ["herdr pane close C", "herdr --session x pane close w1:p2",
                  "herdr tab close w1:t1", "herdr workspace close w1",
                  "echo '{\"method\":\"pane.close\"}' | socat - UNIX:$S",
                  "echo '{\"method\":\"tab.close\"}' | nc -U $S",
                  "echo '{\"method\":\"workspace.close\"}' | nc -U $S"]:
            with self.subTest(c=c):
                self.assertEqual(self.decision(c), "ask")

    def test_ask_reason_points_to_wrapper(self):
        out = self.run_hook("herdr pane close C")
        self.assertIn("herdr-close-child.sh",
                      out["hookSpecificOutput"]["permissionDecisionReason"])
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "PreToolUse")

    def test_exit_keys_on_coordinator_ask(self):
        for c in ["herdr pane run R exit", "herdr pane send-keys R ctrl+d",
                  "herdr pane send-keys R C-d", "herdr pane run R /exit"]:
            with self.subTest(c=c):
                self.assertEqual(self.decision(c), "ask")

    def test_exit_keys_on_role_only_coordinator_ask(self):
        # R marcada só por token role=coordinator, sem nenhum pane com parent=R.
        stub = Stub([mk("R", role="coordinator")], PROC)
        for c in ["herdr pane run R exit", "herdr pane send-keys R ctrl+d"]:
            with self.subTest(c=c):
                self.assertEqual(self.decision(c, stub=stub), "ask")

    def test_exit_keys_on_child_allow(self):
        for c in ["herdr pane run C exit", "herdr pane send-keys C ctrl+d"]:
            with self.subTest(c=c):
                self.assertEqual(self.decision(c), "allow")

    def test_non_exit_run_on_coordinator_allow(self):
        self.assertEqual(self.decision("herdr pane run R ls -la"), "allow")

    def test_wrapper_allow(self):
        self.assertEqual(self.decision("~/.claude/scripts/herdr-close-child.sh C"), "allow")
        self.assertEqual(self.decision("DRY_RUN=1 bash herdr-close-child.sh C"), "allow")

    def test_wrapper_chained_with_raw_close_ask(self):
        self.assertEqual(self.decision(
            "~/.claude/scripts/herdr-close-child.sh C; herdr pane close R"), "ask")

    def test_read_commands_allow(self):
        for c in ["herdr pane list", "herdr pane read R", "ls", "git status",
                  "herdr pane process-info --pane R"]:
            with self.subTest(c=c):
                self.assertEqual(self.decision(c), "allow")

    def test_kill_coordinator_pid_ask(self):
        for c in ["kill -9 4100", "kill 4000", "kill -TERM 4100"]:
            with self.subTest(c=c):
                self.assertEqual(self.decision(c), "ask")

    def test_kill_via_process_info_substitution_ask(self):
        self.assertEqual(self.decision(
            "kill -9 $(herdr pane process-info --pane R | jq .result.pid)"), "ask")

    def test_kill_other_pid_allow(self):
        self.assertEqual(self.decision("kill -9 5100"), "allow")  # filho
        self.assertEqual(self.decision("kill 99999"), "allow")

    def test_non_bash_tool_allow(self):
        self.assertEqual(self.decision("herdr pane close R", tool="Read"), "allow")

    def test_invalid_stdin_allow(self):
        r = subprocess.run([sys.executable, HOOK], env=self.stub.env, text=True,
                           input="not json", capture_output=True)
        self.assertEqual((r.returncode, r.stdout), (0, ""))

    def test_herdr_failure_send_keys_warns_never_blocks(self):
        s = Stub(PANES, PROC, fail=True)
        for c in ["herdr pane send-keys R ctrl+d", "herdr pane run R exit"]:
            with self.subTest(c=c):
                out = self.run_hook(c, stub=s)
                self.assertNotIn("hookSpecificOutput", out)
                self.assertIn("systemMessage", out)

    def test_herdr_failure_kill_numeric_asks(self):
        s = Stub(PANES, PROC, fail=True)
        for c in ["kill -9 4100", "kill 5100"]:
            with self.subTest(c=c):
                self.assertEqual(self.decision(c, stub=s), "ask")

    def test_pane_list_fail_kill_ask(self):
        s = Stub(PANES, PROC, fail=True)
        out = self.run_hook("kill -9 5100", stub=s)  # pid do filho: sem falha, seria allow
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "ask")
        self.assertIn("pane list falhou", out["hookSpecificOutput"]["permissionDecisionReason"])

    def test_process_info_fail_one_coordinator_kill_ask(self):
        # R responde; R2 (coordenadora) falha no process-info. kill 5100 nao casa com R,
        # entao sem o ask de falha seria allow.
        panes = PANES + [mk("R2", role="coordinator")]
        s = Stub(panes, {"R": PROC["R"]})
        out = self.run_hook("kill -9 5100", stub=s)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "ask")
        self.assertIn("process-info falhou para R2",
                      out["hookSpecificOutput"]["permissionDecisionReason"])

    def test_budget_exhausted_kill_ask_fast(self):
        import time
        panes = [mk("R1", role="coordinator"), mk("R2", role="coordinator"),
                 mk("R3", role="coordinator")]
        proc = {p: {"shell_pid": 7000 + i, "foreground_process_group_id": 7100 + i,
                    "foreground_processes": []}
                for i, p in enumerate(["R1", "R2", "R3"])}
        s = Stub(panes, proc, proc_sleep=1.5)
        t0 = time.monotonic()
        self.assertEqual(self.decision("kill -9 4100", stub=s), "ask")
        elapsed = time.monotonic() - t0
        self.assertLess(elapsed, 5, f"hook levou {elapsed:.2f}s")
        # orcamento (BUDGET_S=3) deve cortar antes de consultar as 3 coordenadoras
        self.assertLess(len([c for c in s.calls() if c.startswith("pane process-info")]), 3)

    def test_no_herdr_query_for_unrelated_commands(self):
        self.run_hook("ls -la")
        self.run_hook("herdr pane list")
        self.assertEqual(self.stub.calls(), [])


if __name__ == "__main__":
    unittest.main()
