"""name_hint: hint_for / claude_output / main. Único mock: av.send (socket Herdr)."""
import contextlib
import io
import json
import os
import subprocess
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "bin"))
sys.path.insert(0, HERE)
import agent_view as av  # noqa: E402
import name_hint  # noqa: E402
from _support import FakeHerdr, mocked  # noqa: E402

CWD = "/home/u/Apps/canais-front"


def pane(pid, label, cwd=CWD):
    return {"pane_id": pid, "tab_id": "t1", "workspace_id": "w1",
            "label": label, "cwd": cwd, "tokens": {}}


class NameHintBase(unittest.TestCase):
    def setUp(self):
        keys = ("HERDR_PANE_ID", "HERDR_SOCKET_PATH", "CLAUDE_CODE_ENTRYPOINT")
        self._old = {k: os.environ.get(k) for k in keys}
        os.environ["HERDR_SOCKET_PATH"] = "/tmp/fake-herdr.sock"  # nunca conectado: send é mockado
        os.environ.pop("CLAUDE_CODE_ENTRYPOINT", None)  # isola do ambiente (cli/sdk)

    def tearDown(self):
        for k, v in self._old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def herdr(self, panes):
        return FakeHerdr(panes=panes)


class HintFor(NameHintBase):
    def test_no_pane_id_returns_none_without_socket_call(self):
        h = self.herdr([pane("P1", "canais-front #2")])
        with mocked(h):
            self.assertIsNone(name_hint.hint_for(None))
            self.assertIsNone(name_hint.hint_for(""))
        self.assertEqual(h.calls, [])

    def test_pane_missing_returns_none(self):
        h = self.herdr([pane("OTHER", "canais-front #2")])
        with mocked(h):
            self.assertIsNone(name_hint.hint_for("P1"))

    def test_manual_label_returns_none(self):
        h = self.herdr([pane("P1", "logs")])
        with mocked(h):
            self.assertIsNone(name_hint.hint_for("P1"))

    def test_auto_label_returns_instruction_with_pane_id(self):
        h = self.herdr([pane("P1", "canais-front #2")])
        with mocked(h):
            text = name_hint.hint_for("P1")
        self.assertIsNotNone(text)
        self.assertIn("P1", text)
        self.assertIn("herdr pane rename", text)

    def test_empty_label_is_auto(self):
        h = self.herdr([pane("P1", None)])
        with mocked(h):
            self.assertIsNotNone(name_hint.hint_for("P1"))

    def test_socket_error_returns_none(self):
        with mock.patch.object(av, "send", side_effect=OSError("socket down")):
            self.assertIsNone(name_hint.hint_for("P1"))

    def test_unset_socket_path_returns_none(self):
        os.environ.pop("HERDR_SOCKET_PATH", None)
        self.assertIsNone(name_hint.hint_for("P1"))


class ClaudeOutput(unittest.TestCase):
    def test_json_shape(self):
        data = json.loads(name_hint.claude_output("oi ç"))
        self.assertEqual(set(data), {"hookSpecificOutput"})
        hso = data["hookSpecificOutput"]
        self.assertEqual(hso["hookEventName"], "UserPromptSubmit")
        self.assertEqual(hso["additionalContext"], "oi ç")


class Main(NameHintBase):
    def run_main(self, argv, h=None):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            if h is None:
                rc = name_hint.main(argv)
            else:
                with mocked(h):
                    rc = name_hint.main(argv)
        return rc, out.getvalue()

    def test_auto_pane_prints_claude_json_by_default(self):
        os.environ["HERDR_PANE_ID"] = "P1"
        rc, out = self.run_main([], self.herdr([pane("P1", "canais-front #2")]))
        self.assertEqual(rc, 0)
        hso = json.loads(out)["hookSpecificOutput"]
        self.assertEqual(hso["hookEventName"], "UserPromptSubmit")
        self.assertIn("P1", hso["additionalContext"])

    def test_text_format_prints_raw_instruction(self):
        os.environ["HERDR_PANE_ID"] = "P1"
        rc, out = self.run_main(["--format", "text"], self.herdr([pane("P1", "canais-front #2")]))
        self.assertEqual(rc, 0)
        self.assertIn("herdr pane rename P1", out)
        with self.assertRaises(ValueError):
            json.loads(out)

    def test_manual_label_prints_nothing(self):
        os.environ["HERDR_PANE_ID"] = "P1"
        rc, out = self.run_main([], self.herdr([pane("P1", "logs")]))
        self.assertEqual((rc, out), (0, ""))

    def test_socket_error_exits_zero_silently(self):
        os.environ["HERDR_PANE_ID"] = "P1"
        out = io.StringIO()
        with contextlib.redirect_stdout(out), \
                mock.patch.object(av, "send", side_effect=OSError("socket down")):
            rc = name_hint.main([])
        self.assertEqual((rc, out.getvalue()), (0, ""))

    def test_unexpected_exception_exits_zero_silently(self):
        os.environ["HERDR_PANE_ID"] = "P1"
        out = io.StringIO()
        with contextlib.redirect_stdout(out), \
                mock.patch.object(name_hint, "hint_for", side_effect=RuntimeError("boom")):
            rc = name_hint.main([])
        self.assertEqual((rc, out.getvalue()), (0, ""))


class UnknownFormat(NameHintBase):
    """Hook safety: formato inválido/ausente -> silencioso, exit 0, sem socket."""

    def run_main(self, argv, h):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), mocked(h):
            rc = name_hint.main(argv)
        return rc, out.getvalue()

    def test_unknown_format_is_silent_and_skips_socket(self):
        os.environ["HERDR_PANE_ID"] = "P1"
        h = self.herdr([pane("P1", "canais-front #2")])
        self.assertEqual(self.run_main(["--format", "yaml"], h), (0, ""))
        self.assertEqual(self.run_main(["--format=yaml"], h), (0, ""))
        self.assertEqual(h.calls, [])

    def test_format_flag_without_value_is_silent(self):
        os.environ["HERDR_PANE_ID"] = "P1"
        h = self.herdr([pane("P1", "canais-front #2")])
        self.assertEqual(self.run_main(["--format"], h), (0, ""))
        self.assertEqual(h.calls, [])

    def test_script_exit_code_is_zero_for_unknown_format(self):
        env = {k: v for k, v in os.environ.items()
               if k not in ("HERDR_PANE_ID", "HERDR_SOCKET_PATH")}
        r = subprocess.run([sys.executable, "-B", os.path.join(HERE, "..", "bin", "name_hint.py"),
                            "--format", "yaml"], capture_output=True, text=True,
                           env=env, timeout=10)
        self.assertEqual((r.returncode, r.stdout), (0, ""))


if __name__ == "__main__":
    unittest.main()
