"""name_hint: CLAUDE_CODE_ENTRYPOINT "sdk*" (claude -p / SDK) não emite nada e nem
toca o socket; "cli" ou ausente emite a instrução para label automático."""
import contextlib
import io
import os
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
AUTO = {"pane_id": "P1", "tab_id": "t1", "workspace_id": "w1",
        "label": "canais-front #2", "cwd": CWD, "tokens": {}}


def env_with(value):
    env = {"HERDR_SOCKET_PATH": "/tmp/fake-herdr.sock"}
    if value is not None:
        env["CLAUDE_CODE_ENTRYPOINT"] = value
    return env


class Entrypoint(unittest.TestCase):
    def hint(self, value):
        h = FakeHerdr(panes=[AUTO])
        with mock.patch.dict(os.environ, env_with(value)), \
                mock.patch.dict(os.environ, {}):
            os.environ.pop("CLAUDE_CODE_ENTRYPOINT", None)
            if value is not None:
                os.environ["CLAUDE_CODE_ENTRYPOINT"] = value
            with mocked(h):
                return name_hint.hint_for("P1"), h

    def test_sdk_entrypoints_emit_nothing_and_skip_socket(self):
        for value in ("sdk-py", "sdk-ts", "sdk"):
            with self.subTest(entrypoint=value):
                text, h = self.hint(value)
                self.assertIsNone(text)
                self.assertEqual(h.calls, [])

    def test_cli_entrypoint_emits_instruction(self):
        text, _ = self.hint("cli")
        self.assertIsNotNone(text)
        self.assertIn("P1", text)

    def test_unset_entrypoint_emits_instruction(self):
        text, _ = self.hint(None)
        self.assertIsNotNone(text)

    def test_text_format_sdk_prints_nothing_cli_prints_instruction(self):
        for value, expect in (("sdk-py", ""), ("cli", "herdr pane rename")):
            with self.subTest(entrypoint=value):
                h = FakeHerdr(panes=[AUTO])
                out = io.StringIO()
                with mock.patch.dict(os.environ, env_with(value)), \
                        mock.patch.dict(os.environ, {"HERDR_PANE_ID": "P1"}), \
                        mocked(h), contextlib.redirect_stdout(out):
                    rc = name_hint.main(["--format", "text"])
                self.assertEqual(rc, 0)
                self.assertIn(expect, out.getvalue())
                if not expect:
                    self.assertEqual(out.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
