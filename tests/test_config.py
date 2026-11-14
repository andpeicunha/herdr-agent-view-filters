"""Config `picked_new` (default include) e leitura de config.toml."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "bin"))
sys.path.insert(0, HERE)
import agent_view as av  # noqa: E402
from _support import Isolated  # noqa: E402


class PickedNewConfig(Isolated):
    def test_default_is_include_when_missing(self):
        self.assertEqual(av.read_picked_new(), "include")

    def test_valid_values(self):
        self.write_config('picked_new = "include"\n')
        self.assertEqual(av.read_picked_new(), "include")
        self.write_config('picked_new = "exclude"\n')
        self.assertEqual(av.read_picked_new(), "exclude")

    def test_invalid_values_fall_back_to_include(self):
        for text in ('picked_new = "bogus"\n', "picked_new = true\n", "not = = toml"):
            with self.subTest(text=text):
                self.write_config(text)
                self.assertEqual(av.read_picked_new(), "include")

    def test_config_dir_env_is_honored(self):
        self.assertEqual(av.config_path(), os.path.join(self.config_dir, "config.toml"))


@unittest.skipIf(av.tomllib is None, "config.toml needs tomllib (py3.11+)")
class CoordinatorLabelConfig(Isolated):
    def label(self, text):
        self.write_config(text)
        return av.read_coordinator_label()

    def test_default_when_missing(self):
        self.assertEqual(av.read_coordinator_label(), "orch")

    def test_invalid_types_fall_back(self):
        for text in ("coordinator_label = 5\n", "coordinator_label = true\n",
                     "coordinator_label = [1]\n", "not = = toml"):
            with self.subTest(text=text):
                self.assertEqual(self.label(text), "orch")

    def test_string_is_stripped(self):
        self.assertEqual(self.label('coordinator_label = "  boss "\n'), "boss")

    def test_empty_disables(self):
        self.assertEqual(self.label('coordinator_label = ""\n'), "")
        self.assertEqual(self.label('coordinator_label = "  "\n'), "")

    def test_too_long_falls_back(self):
        self.assertEqual(self.label('coordinator_label = "%s"\n' % ("a" * 129)), "orch")
        ok = "a" * av.TOKEN_MAX_LEN
        self.assertEqual(self.label('coordinator_label = "%s"\n' % ok), ok)


if __name__ == "__main__":
    unittest.main()
