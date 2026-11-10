"""Perf do sync: uma chamada por listagem (agent/pane/tab/workspace), report_metadata
pulado quando os tokens já são iguais, e republish forçado após 6h."""
import contextlib
import io
import os
import sys
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "bin"))
sys.path.insert(0, HERE)
import agent_view as av  # noqa: E402
from _support import Isolated, FakeHerdr, agent, pane, mocked  # noqa: E402

TABS = [{"tab_id": "t1", "label": "dev"}, {"tab_id": "t2", "label": "ops"}]


def run_sync(h):
    out = io.StringIO()
    with mocked(h), mock.patch.object(sys, "argv", ["agent_view.py", "sync"]), \
            contextlib.redirect_stdout(out):
        av.main()


def fresh_fake():
    agents = [agent("R", "t1"), agent("C", "t1"), agent("A", "t2")]
    panes = [pane("R", "t1"), pane("C", "t1", parent="R"), pane("A", "t2")]
    return FakeHerdr(agents, panes, tabs=TABS)


def feed_back_tokens(h):
    """Simula o Herdr: os tokens publicados voltam em pane.list (valores None somem)."""
    published = h.tokens()
    for p in h.panes:
        p["tokens"] = {k: v for k, v in published.get(p["pane_id"], {}).items() if v is not None}


def count(h, method, start=0):
    return sum(1 for c in h.calls[start:] if c["method"] == method)


class CallsPerSync(Isolated):
    def test_one_call_per_listing_per_sync(self):
        h = fresh_fake()
        run_sync(h)
        self.assertEqual(count(h, "agent.list"), 1)
        self.assertEqual(count(h, "pane.list"), 1)
        self.assertEqual(count(h, "tab.list"), 1)
        self.assertEqual(count(h, "workspace.list"), 1)


class TokenSkip(Isolated):
    def test_report_metadata_skipped_when_tokens_equal(self):
        h = fresh_fake()
        run_sync(h)
        self.assertEqual(count(h, "pane.report_metadata"), 3)  # 1ª publicação: tudo
        feed_back_tokens(h)
        before = len(h.calls)
        run_sync(h)
        self.assertEqual(count(h, "pane.report_metadata", before), 0)
        self.assertEqual(count(h, "agent.view.set", before), 1)  # view ainda reaplicada

    def test_changed_token_is_rewritten_alone(self):
        h = fresh_fake()
        run_sync(h)
        feed_back_tokens(h)
        h.panes[0]["tokens"]["title"] = "stale"  # só o R divergiu
        before = len(h.calls)
        run_sync(h)
        written = [c["params"]["pane_id"] for c in h.calls[before:]
                   if c["method"] == "pane.report_metadata"]
        self.assertEqual(written, ["R"])


class ForcedRepublish(Isolated):
    def test_full_republish_after_six_hours(self):
        h = fresh_fake()
        run_sync(h)
        feed_back_tokens(h)
        av.write_state("picked", [], published_at=time.time() - 7 * 3600)
        old = av.read_published_at()
        before = len(h.calls)
        run_sync(h)
        self.assertEqual(count(h, "pane.report_metadata", before), 3)
        self.assertGreater(av.read_published_at(), old)


if __name__ == "__main__":
    unittest.main()
