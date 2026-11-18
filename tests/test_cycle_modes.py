"""`cycle_modes`: subconjunto de modos visitados pelo `cycle`."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "bin"))
import agent_view as av  # noqa: E402


class NextMode(unittest.TestCase):
    def test_default_cycles_all_modes(self):
        self.assertEqual(av.next_mode("active", av.MODES), "space")
        self.assertEqual(av.next_mode("all", av.MODES), "active")

    def test_subset_toggles(self):
        self.assertEqual(av.next_mode("picked", ["picked", "all"]), "all")
        self.assertEqual(av.next_mode("all", ["picked", "all"]), "picked")

    def test_current_outside_subset(self):
        self.assertEqual(av.next_mode("active", ["picked", "all"]), "picked")


class ReadCycleModes(unittest.TestCase):
    def _with(self, cfg):
        orig = av.read_config
        av.read_config = lambda: cfg
        try:
            return av.read_cycle_modes()
        finally:
            av.read_config = orig

    def test_missing_or_invalid(self):
        self.assertEqual(self._with({}), av.MODES)
        self.assertEqual(self._with({"cycle_modes": "picked"}), av.MODES)
        self.assertEqual(self._with({"cycle_modes": ["bogus"]}), av.MODES)

    def test_subset_in_modes_order(self):
        self.assertEqual(self._with({"cycle_modes": ["all", "picked", "x"]}), ["picked", "all"])


if __name__ == "__main__":
    unittest.main()
