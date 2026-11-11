"""herdr-close-child.sh (dotfiles) via subprocess com stub herdr no PATH."""
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from _herdr_stub import Stub, WRAPPER, mk  # noqa: E402


@unittest.skipUnless(os.path.exists(WRAPPER), "wrapper ausente")
class CloseChild(unittest.TestCase):
    def run_w(self, stub, target="C", dry=False):
        env = dict(stub.env)
        if dry:
            env["DRY_RUN"] = "1"
        return subprocess.run(["bash", WRAPPER, target], env=env,
                              capture_output=True, text=True, timeout=20)

    def test_coordinator_by_role_token(self):
        s = Stub([mk("R", role="coordinator"), mk("C", parent="R")])
        r = self.run_w(s, "R")
        self.assertEqual(r.returncode, 3, r.stderr)
        self.assertEqual(s.closes(), [])

    def test_coordinator_by_parent_target(self):
        s = Stub([mk("R"), mk("C", tab="t2", parent="R")])
        self.assertEqual(self.run_w(s, "R").returncode, 3)
        self.assertEqual(s.closes(), [])

    def test_coordinator_by_tab_roots(self):
        s = Stub([mk("R"), mk("C")])
        s.set_state({"tab_roots": {"t1": "R"}})
        self.assertEqual(self.run_w(s, "R").returncode, 3)
        self.assertEqual(s.closes(), [])

    # coordenadora que tambem tem `parent` (nivel intermediario): so as checagens
    # de coordenadora a protegem; sem elas o token parent a liberaria.
    def test_nested_coordinator_by_role_refused(self):
        s = Stub([mk("G", role="coordinator"), mk("R", tab="t2", parent="G", role="coordinator")])
        self.assertEqual(self.run_w(s, "R").returncode, 3)
        self.assertEqual(s.closes(), [])

    def test_nested_coordinator_by_parent_target_refused(self):
        s = Stub([mk("G"), mk("R", tab="t2", parent="G"), mk("C", tab="t3", parent="R")])
        self.assertEqual(self.run_w(s, "R").returncode, 3)
        self.assertEqual(s.closes(), [])

    def test_tab_root_with_parent_token_refused_via_tab_roots(self):
        s = Stub([mk("G"), mk("R", tab="t2", parent="G")])
        s.set_state({"tab_roots": {"t2": "R"}})
        self.assertEqual(self.run_w(s, "R").returncode, 3)
        self.assertEqual(s.closes(), [])

    def test_child_by_parent_token(self):
        s = Stub([mk("R", role="coordinator"), mk("C", tab="t2", parent="R")])
        r = self.run_w(s, "C")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(s.closes(), ["pane close C"])

    def test_child_by_tab_non_root(self):
        s = Stub([mk("R"), mk("C")])
        s.set_state({"tab_roots": {"t1": "R"}})
        r = self.run_w(s, "C")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(s.closes(), ["pane close C"])

    def test_root_without_parent_refused(self):
        s = Stub([mk("R"), mk("C")])  # sem state, sem tokens
        self.assertEqual(self.run_w(s, "R").returncode, 3)
        self.assertEqual(s.closes(), [])

    def test_root_indeterminate_fail_closed(self):
        s = Stub([mk("R"), mk("C")])
        self.assertEqual(self.run_w(s, "C").returncode, 3)
        self.assertEqual(s.closes(), [])

    def test_nonexistent_refused(self):
        s = Stub([mk("R", role="coordinator")])
        self.assertEqual(self.run_w(s, "ZZ").returncode, 3)
        self.assertEqual(s.closes(), [])

    def test_pane_list_failure_fail_closed(self):
        s = Stub([mk("C", parent="R")], fail=True)
        r = self.run_w(s, "C")
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(s.closes(), [])

    def test_no_arg_is_usage_error(self):
        s = Stub([])
        r = subprocess.run(["bash", WRAPPER], env=s.env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)

    def test_dry_run_does_not_close(self):
        s = Stub([mk("R", role="coordinator"), mk("C", parent="R")])
        r = self.run_w(s, "C", dry=True)
        self.assertEqual(r.returncode, 0)
        self.assertIn("would close C", r.stdout)
        self.assertEqual(s.closes(), [])


if __name__ == "__main__":
    unittest.main()
