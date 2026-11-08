import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin"))
import agent_view as av  # noqa: E402

SP = {"a1": "A", "a2": "A", "b1": "B", "b2": "B", "b3": "B", "c1": "C"}.get


class MoveUnit(unittest.TestCase):
    items = ["a1", "a2", "b1", "b2", "b3", "c1"]

    def mv(self, items, idx, delta):
        return av.move_unit(items, idx, delta, SP)

    def test_swap_inside_space(self):
        out, i, kind = self.mv(self.items, 3, -1)
        self.assertEqual((out, i, kind), (["a1", "a2", "b2", "b1", "b3", "c1"], 2, "item"))
        out, i, kind = self.mv(self.items, 2, 1)
        self.assertEqual((out, i, kind), (["a1", "a2", "b2", "b1", "b3", "c1"], 3, "item"))

    def test_single_item_space_jumps_up(self):
        out, i, kind = self.mv(self.items, 5, -1)
        self.assertEqual(out, ["a1", "a2", "c1", "b1", "b2", "b3"])
        self.assertEqual((i, kind), (2, "space"))

    def test_space_jumps_up_from_first_item(self):
        out, i, kind = self.mv(self.items, 2, -1)
        self.assertEqual(out, ["b1", "b2", "b3", "a1", "a2", "c1"])
        self.assertEqual((i, kind), (0, "space"))

    def test_space_jumps_up_from_middle_cursor_follows(self):
        # delta only reaches the edge from the first item; check last-item down
        out, i, kind = self.mv(self.items, 4, 1)
        self.assertEqual(out, ["a1", "a2", "b1", "b2", "b3", "c1"][:2] + ["c1", "b1", "b2", "b3"])
        self.assertEqual((i, kind), (5, "space"))
        self.assertEqual(out[i], "b3")

    def test_space_jumps_down_multi_item_neighbour(self):
        out, i, kind = self.mv(self.items, 1, 1)
        self.assertEqual(out, ["b1", "b2", "b3", "a1", "a2", "c1"])
        self.assertEqual((i, kind), (4, "space"))
        self.assertEqual(out[i], "a2")

    def test_plugin_example(self):
        items = ["p1", "p2", "p3", "p4", "p5", "h1"]
        sp = lambda x: x[0]  # noqa: E731
        out, i, kind = av.move_unit(items, 5, -1, sp)
        self.assertEqual(out, ["h1", "p1", "p2", "p3", "p4", "p5"])
        self.assertEqual((i, kind), (0, "space"))

    def test_edges(self):
        for idx, d in ((0, -1), (5, 1)):
            out, i, kind = self.mv(self.items, idx, d)
            self.assertEqual((out, i, kind), (self.items, idx, "edge"))
        self.assertEqual(self.mv([], 0, 1)[2], "edge")
        self.assertEqual(self.mv(self.items, 9, 1)[2], "edge")

    def test_does_not_mutate_input(self):
        src = list(self.items)
        self.mv(src, 2, -1)
        self.assertEqual(src, self.items)


class SpaceSequence(unittest.TestCase):
    panes = [("a1", 0, "r", "x"), ("b1", 1, "r", "x"), ("c1", 2, "r", "x"), ("c2", 2, "r", "y")]
    ids = {0: "A", 1: "B", 2: "C"}

    def test_default_follows_key(self):
        self.assertEqual(av.space_sequence(self.panes, []), ["a1", "b1", "c1", "c2"])

    def test_saved_space_order(self):
        seq = av.space_sequence(self.panes, [], ["C", "A", "B"], self.ids)
        self.assertEqual(seq, ["c1", "c2", "a1", "b1"])

    def test_new_space_goes_last_and_dead_ignored(self):
        seq = av.space_sequence(self.panes, [], ["C", "GONE", "A"], self.ids)
        self.assertEqual(seq, ["c1", "c2", "a1", "b1"])

    def test_agent_order_kept_inside_moved_space(self):
        seq = av.space_sequence(self.panes, ["c2", "c1"], ["C"], self.ids)
        self.assertEqual(seq, ["c2", "c1", "a1", "b1"])


class SpaceOrderState(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.d = tempfile.mkdtemp()
        os.environ["HERDR_PLUGIN_STATE_DIR"] = self.d

    def test_roundtrip_and_old_state(self):
        self.assertEqual(av.read_space_order(), [])
        av.write_state("picked", [], ["p1"], ["B", "A"])
        self.assertEqual(av.read_space_order(), ["B", "A"])
        av.write_order(["p2"])  # keeps space_order
        self.assertEqual(av.read_space_order(), ["B", "A"])
        av.write_state("picked", [], [], [])
        self.assertEqual(av.read_space_order(), [])
        with open(av.state_path(), "w") as f:
            f.write('{"mode": "picked", "excluded": [], "order": ["p1"]}')
        self.assertEqual(av.read_space_order(), [])
        self.assertEqual(av.read_order(), ["p1"])


if __name__ == "__main__":
    unittest.main()
