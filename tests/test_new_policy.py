import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin"))
import agent_view as av  # noqa: E402


class NewPolicy(unittest.TestCase):
    def test_first_run_marks_seen_without_excluding(self):
        self.assertEqual(av.apply_new_policy(["a", "b"], None, ["a"], "exclude"), (["a", "b"], ["a"]))

    def test_new_agent_excluded(self):
        self.assertEqual(av.apply_new_policy(["a", "b", "c"], ["a", "b"], [], "exclude"),
                         (["a", "b", "c"], ["c"]))

    def test_known_agent_not_reexcluded(self):
        # user ticked "b" in the picker (not excluded, but seen)
        self.assertEqual(av.apply_new_policy(["a", "b"], ["a", "b"], ["a"], "exclude"),
                         (["a", "b"], ["a"]))

    def test_include_policy_keeps_new_visible_but_tracks_seen(self):
        self.assertEqual(av.apply_new_policy(["a", "c"], ["a"], [], "include"), (["a", "c"], []))

    def test_prunes_dead(self):
        self.assertEqual(av.apply_new_policy(["a"], ["a", "x"], ["x"], "exclude"), (["a"], []))

    def test_first_run_prunes_excluded(self):
        self.assertEqual(av.apply_new_policy(["a"], None, ["x"], "exclude"), (["a"], []))


class Config(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.d = tempfile.mkdtemp()
        self.old = os.environ.get("HERDR_PLUGIN_CONFIG_DIR")
        os.environ["HERDR_PLUGIN_CONFIG_DIR"] = self.d

    def tearDown(self):
        if self.old is None:
            os.environ.pop("HERDR_PLUGIN_CONFIG_DIR")
        else:
            os.environ["HERDR_PLUGIN_CONFIG_DIR"] = self.old

    def write(self, text):
        with open(os.path.join(self.d, "config.toml"), "w") as f:
            f.write(text)

    def test_default_missing(self):
        self.assertEqual(av.read_picked_new(), "exclude")

    def test_include(self):
        self.write('picked_new = "include"\n')
        self.assertEqual(av.read_picked_new(), "include")

    def test_invalid_falls_back(self):
        self.write('picked_new = "bogus"\n')
        self.assertEqual(av.read_picked_new(), "exclude")
        self.write("not = = toml")
        self.assertEqual(av.read_picked_new(), "exclude")


if __name__ == "__main__":
    unittest.main()
