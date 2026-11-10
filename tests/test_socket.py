"""send(): socket_path() antes de criar o socket (sem fd vazado) e list_* deixam
TypeError escapar, mas seguem degradando em OSError/ValueError/KeyError.

Mock de fronteira: socket.socket (fd) e av.send. Nenhuma conexão real.
"""
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

REQ = {"id": "t", "method": "agent.list", "params": {}}


class SocketEnvBase(unittest.TestCase):
    def setUp(self):
        self._old = os.environ.get("HERDR_SOCKET_PATH")

    def tearDown(self):
        if self._old is None:
            os.environ.pop("HERDR_SOCKET_PATH", None)
        else:
            os.environ["HERDR_SOCKET_PATH"] = self._old


class SendFdLeak(SocketEnvBase):
    def test_unset_socket_path_exits_before_any_socket_is_created(self):
        os.environ.pop("HERDR_SOCKET_PATH", None)
        err = io.StringIO()
        with mock.patch.object(av.socket, "socket") as sock, \
                contextlib.redirect_stderr(err):
            with self.assertRaises(SystemExit) as cm:
                av.send(REQ)
        self.assertEqual(cm.exception.code, 1)
        sock.assert_not_called()
        self.assertIn("HERDR_SOCKET_PATH not set", err.getvalue())

    def test_socket_closed_when_connect_fails(self):
        os.environ["HERDR_SOCKET_PATH"] = "/nonexistent/herdr.sock"
        inst = mock.MagicMock()
        inst.connect.side_effect = OSError("refused")
        with mock.patch.object(av.socket, "socket", return_value=inst):
            with self.assertRaises(OSError):
                av.send(REQ)
        inst.close.assert_called_once()

    def test_socket_closed_on_success(self):
        os.environ["HERDR_SOCKET_PATH"] = "/nonexistent/herdr.sock"
        inst = mock.MagicMock()
        inst.recv.return_value = b'{"result": {}}\n'
        with mock.patch.object(av.socket, "socket", return_value=inst):
            out = av.send(REQ)
        self.assertEqual(out, '{"result": {}}')
        inst.close.assert_called_once()


class ListHelpers(unittest.TestCase):
    HELPERS = ("list_agents", "list_workspaces", "workspace_index", "list_tabs", "list_panes")

    def test_type_error_propagates_from_every_list_helper(self):
        for name in self.HELPERS:
            with self.subTest(fn=name), \
                    mock.patch.object(av, "send", side_effect=TypeError("bug")):
                with self.assertRaises(TypeError):
                    getattr(av, name)()

    def test_os_error_still_degrades_to_empty_value(self):
        expected = {"list_agents": None, "list_workspaces": {}, "workspace_index": {},
                    "list_tabs": {}, "list_panes": []}
        for name, default in expected.items():
            with self.subTest(fn=name), \
                    mock.patch.object(av, "send", side_effect=OSError("down")):
                self.assertEqual(getattr(av, name)(), default)


if __name__ == "__main__":
    unittest.main()
