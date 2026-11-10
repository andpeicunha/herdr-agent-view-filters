"""state_lock / write_state: lock reentrante e entre processos, escrita sem
clobber (salvar do picker mescla sync concorrente) e tmp sem resíduo.

Único mock: `av.send` (via _support.mocked). Estado isolado em tmp.
"""
import glob
import os
import subprocess
import sys
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
BIN = os.path.join(HERE, "..", "bin")
sys.path.insert(0, BIN)
sys.path.insert(0, HERE)
import agent_view as av  # noqa: E402
import picker  # noqa: E402
from _support import Isolated, FakeHerdr, agent, pane, mocked  # noqa: E402

AGENTS = [agent("R", "t1", "w1"), agent("C", "t1", "w1"), agent("A", "t2", "w1"),
          agent("S", "t3", "w2")]
PANES = [pane("R", "t1", "w1"), pane("C", "t1", "w1", parent="R"),
         pane("A", "t2", "w1"), pane("S", "t3", "w2")]
TABS = [{"tab_id": "t1"}, {"tab_id": "t2"}, {"tab_id": "t3"}]


class LockReentrant(Isolated):
    def test_nested_lock_does_not_deadlock_and_writes(self):
        with av.state_lock():
            with av.state_lock():
                av.write_state("picked", ["R"])
        self.assertEqual(av.read_excluded(), ["R"])

    def test_lock_released_after_exception(self):
        with self.assertRaises(RuntimeError):
            with av.state_lock():
                raise RuntimeError("boom")
        self.assertEqual(av._lock_depth, 0)
        with av.state_lock():  # não pode ficar preso
            pass


class LockAcrossProcesses(Isolated):
    def test_second_process_waits_for_held_lock(self):
        child = "\n".join([
            "import sys, time",
            "sys.path.insert(0, sys.argv[1])",
            "import agent_view as av",
            "with av.state_lock():",
            "    print('locked', flush=True)",
            "    time.sleep(1.0)",
        ])
        p = subprocess.Popen([sys.executable, "-B", "-c", child, BIN],
                             stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(p.stdout.readline().strip(), "locked")
            t0 = time.monotonic()
            with av.state_lock():
                waited = time.monotonic() - t0
        finally:
            p.stdout.close()
            p.wait(timeout=10)
        self.assertGreater(waited, 0.5)


class PickerSaveVsConcurrentSync(Isolated):
    """Picker abre com old=["A"]; um sync grava ["A", "N"] + seen novo antes do save.
    O save precisa manter N (entrada sem linha no picker) e o seen do sync."""

    def test_concurrent_sync_entry_and_seen_survive_picker_save(self):
        av.write_state("picked", ["A"], seen=["R", "C", "A", "S"])
        h = FakeHerdr(AGENTS, PANES, tabs=TABS)

        def wrapper(fn, rows):  # usuário confirma sem mudar nada
            # sync concorrente (outro processo) grava entre abrir e salvar
            av.write_state("picked", ["A", "N"], seen=["R", "C", "A", "S", "N"])
            return True

        with mocked(h), mock.patch.object(picker.curses, "wrapper", side_effect=wrapper):
            picker.main()
        st = self.state_file()
        self.assertEqual(st["excluded"], ["A", "N"])
        self.assertIn("N", st["seen"])


class TmpFile(Isolated):
    """Escrita atômica: tmp único por escrita (mkstemp no diretório do state),
    substituído por os.replace, sem resíduo, removido em erro."""

    def spy_writes(self, fn):
        srcs = []
        real = os.replace

        def spy(src, dst):
            srcs.append(src)
            return real(src, dst)

        with mock.patch.object(av.os, "replace", side_effect=spy):
            fn()
        return srcs

    def test_each_write_uses_a_different_tmp_name(self):
        srcs = self.spy_writes(lambda: (av.write_state("picked", ["R"]),
                                        av.write_state("picked", ["R", "C"])))
        self.assertEqual(len(srcs), 2)
        self.assertNotEqual(srcs[0], srcs[1])

    def test_tmp_lives_in_state_dir_with_prefix_and_suffix(self):
        (src,) = self.spy_writes(lambda: av.write_state("picked", ["R"]))
        self.assertEqual(os.path.dirname(src), self.state_dir)
        base = os.path.basename(src)
        self.assertTrue(base.startswith("state.json."), base)
        self.assertTrue(base.endswith(".tmp"), base)

    def test_tmp_is_gone_after_replace_and_state_is_complete(self):
        real = os.replace
        seen = {}

        def spy(src, dst):
            real(src, dst)
            seen["src_exists"] = os.path.exists(src)
            seen["dst_exists"] = os.path.exists(dst)

        with mock.patch.object(av.os, "replace", side_effect=spy):
            av.write_state("picked", ["R"])
        self.assertEqual(seen, {"src_exists": False, "dst_exists": True})
        self.assertEqual(self.state_file()["excluded"], ["R"])

    def test_no_residue_after_writes(self):
        av.write_state("picked", ["R"])
        av.write_state("picked", ["R", "C"])
        self.assertEqual(glob.glob(os.path.join(self.state_dir, "*.tmp")), [])

    def test_tmp_removed_when_serialization_fails(self):
        av.write_state("picked", ["OLD"])
        with mock.patch.object(av.json, "dump", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                av.write_state("picked", ["NEW"])
        self.assertEqual(glob.glob(os.path.join(self.state_dir, "*.tmp")), [])
        self.assertEqual(self.state_file()["excluded"], ["OLD"])

    def test_tmp_removed_when_replace_fails(self):
        av.write_state("picked", ["OLD"])
        with mock.patch.object(av.os, "replace", side_effect=OSError("disk")):
            with self.assertRaises(OSError):
                av.write_state("picked", ["NEW"])
        self.assertEqual(glob.glob(os.path.join(self.state_dir, "*.tmp")), [])
        self.assertEqual(self.state_file()["excluded"], ["OLD"])


if __name__ == "__main__":
    unittest.main()
