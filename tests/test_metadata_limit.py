"""Regressão: o Herdr aceita no máximo 16 tokens por pane.report_metadata.
Com mais tokens recusa o report inteiro (invalid_metadata_token) e o publish
falhava em silêncio em produção."""
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "bin"))
sys.path.insert(0, HERE)
import agent_view as av  # noqa: E402
from _support import Isolated, FakeHerdr, agent, pane, mocked, HERDR_MAX_TOKENS  # noqa: E402


def report(pane_id, n):
    return {"id": "x", "method": "pane.report_metadata",
            "params": {"pane_id": pane_id, "source": "s",
                       "tokens": {f"k{i}": "v" for i in range(n)}}}


class FakeHerdrEnforcesLimit(unittest.TestCase):
    def test_over_limit_is_rejected_and_not_stored(self):
        h = FakeHerdr()
        resp = json.loads(h(report("A", HERDR_MAX_TOKENS + 1)))
        self.assertEqual(resp["error"]["code"], "invalid_metadata_token")
        self.assertEqual(h.tokens(), {})

    def test_at_limit_is_accepted_and_stored(self):
        h = FakeHerdr()
        resp = json.loads(h(report("A", HERDR_MAX_TOKENS)))
        self.assertNotIn("error", resp)
        self.assertEqual(len(h.tokens()["A"]), HERDR_MAX_TOKENS)


class PublishFitsHerdrLimit(Isolated):
    """Cenário com group_by_tab: duas spaces (Work=w1, Home=w2). Sequência de w1:
    R, C (filho de R), D (tab dev) e A (tab ops). O último pane de w1 é A, que
    carrega sep de SEP_WIDTH. R (primeiro de w1) carrega space "Work" e S (primeiro
    de w2) carrega "Home". hdr é sempre None (token aposentado)."""

    def test_publish_reports_within_limit_and_tokens_land(self):
        self.write_config("group_by_tab = true\n")
        agents = [agent("A", "t2", "w1"), agent("R", "t1", "w1"),
                  agent("C", "t1", "w1", title="zsh"), agent("D", "t1", "w1", title="vim"),
                  agent("S", "t3", "w2")]
        panes = [pane("A", "t2", "w1"), pane("R", "t1", "w1"),
                 pane("C", "t1", "w1", parent="R", label="logs"),
                 pane("D", "t1", "w1"), pane("S", "t3", "w2")]
        tabs = [{"tab_id": "t1", "label": "dev"}, {"tab_id": "t2", "label": "ops"},
                {"tab_id": "t3", "label": "home"}]
        h = FakeHerdr(agents, panes, tabs=tabs)
        with mocked(h):
            n = av.publish_tokens()

        reports = h.methods("pane.report_metadata")
        self.assertTrue(reports)
        for r in reports:
            self.assertLessEqual(len(r["tokens"]), HERDR_MAX_TOKENS)

        self.assertEqual(n, len(agents))  # todos aceitos pelo Herdr fake
        landed = h.tokens()
        self.assertEqual(set(landed), {"A", "R", "C", "D", "S"})
        # último pane de Work carrega o separador; hdr aposentado fica None
        self.assertEqual(landed["A"]["sep"], "─" * 20)
        self.assertTrue(all(v["hdr"] is None for v in landed.values()))
        # só o primeiro pane de cada space carrega `space`
        self.assertEqual(landed["R"]["space"], "Work")
        self.assertEqual(landed["S"]["space"], "Home")
        for pid in ("C", "D", "A"):
            self.assertIsNone(landed[pid]["space"], pid)
        # panes que não fecham space não carregam sep
        for pid in ("R", "C", "D", "S"):
            self.assertIsNone(landed[pid]["sep"], pid)
        self.assertTrue(all(v["pad"] is None for v in landed.values()))
