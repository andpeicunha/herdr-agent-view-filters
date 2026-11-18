"""`$sep`: linha que fecha o bloco de cada space (exceto o último)."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "bin"))
import agent_view as av  # noqa: E402


class SpaceSeparators(unittest.TestCase):
    def test_last_pane_of_each_space_but_the_last(self):
        key = {"A": "w1", "B": "w1", "C": "w2", "D": "w3", "E": "w3"}
        self.assertEqual(av.space_separators(["A", "B", "C", "D", "E"], key), {"B", "C"})

    def test_single_space_has_no_separator(self):
        self.assertEqual(av.space_separators(["A", "B"], {"A": "w1", "B": "w1"}), set())

    def test_empty(self):
        self.assertEqual(av.space_separators([], {}), set())

    def test_modes(self):
        self.assertEqual(set(av.SEP_MODES), {"picked", "active"})


if __name__ == "__main__":
    unittest.main()
