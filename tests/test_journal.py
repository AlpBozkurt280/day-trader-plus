import datetime
import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout

from _load import load

J = load("trader-journal", "journal")


def fill(at, side, qty, price, sym="TSLA", date="2026-10-19"):
    return {"at": at, "date": date, "status": "filled", "symbol": sym, "side": side,
            "qty": str(qty), "price": price}


class Journal(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.csv = os.path.join(self.d, "journal.csv")

    def tearDown(self):
        shutil.rmtree(self.d)

    def run_cli(self, *args):
        out = io.StringIO()
        with redirect_stdout(out):
            code = J.main(["--journal", self.csv] + list(args))
        return code, out.getvalue()

    def test_log_the_reel_trade(self):
        code, out = self.run_cli("log", "--symbol", "tsla", "--qty", "8", "--entry", "364.18",
                                 "--exit", "370.04", "--stop", "358.32", "--setup", "orb",
                                 "--date", "2026-10-19")
        self.assertEqual(code, 0)
        self.assertIn("P&L $46.88, 1.00R", out)
        row = J.read_rows(self.csv)[0]
        self.assertEqual((row["id"], row["symbol"], row["pnl"], row["r_multiple"]), ("1", "TSLA", "46.88", "1.00"))

    def test_no_stop_means_no_r(self):
        self.run_cli("log", "--symbol", "KO", "--qty", "10", "--entry", "70", "--exit", "69")
        self.assertEqual(J.read_rows(self.csv)[0]["r_multiple"], "")

    def test_unknown_mistake_is_refused(self):
        code, _ = self.run_cli("log", "--symbol", "KO", "--qty", "1", "--entry", "1", "--exit", "2",
                               "--mistake", "bad-luck")
        self.assertEqual(code, 1)
        self.assertFalse(os.path.exists(self.csv))

    def test_round_trips_are_fifo_and_split_partials(self):
        trips = J.round_trips([fill("10:15", "buy", 5, 100), fill("10:20", "buy", 5, 102),
                               fill("11:00", "sell", 7, 105), fill("09:00", "sell", 1, 99, sym="KO")])
        self.assertEqual([(t["qty"], t["entry"]) for t in trips], [(5, 100), (2, 102)])

    def test_import_matches_the_plan_and_is_idempotent(self):
        state = os.path.join(self.d, "broker.json")
        plan = os.path.join(self.d, "plan.json")
        with open(state, "w") as fh:
            json.dump({"orders": [fill("2026-10-19T10:15:00-04:00", "buy", 8, 364.18),
                                  fill("2026-10-19T10:58:00-04:00", "sell", 8, 370.04)]}, fh)
        with open(plan, "w") as fh:
            json.dump({"symbol": "TSLA", "date": "2026-10-19", "stop": 358.32, "setup": "orb"}, fh)
        self.assertEqual(len(J.import_fills(self.csv, state, plan)), 1)
        self.assertEqual(len(J.import_fills(self.csv, state, plan)), 0)
        row = J.read_rows(self.csv)[0]
        self.assertEqual((row["setup"], row["r_multiple"]), ("orb", "1.00"))

    def test_note_adds_tags_once(self):
        self.run_cli("log", "--symbol", "KO", "--qty", "1", "--entry", "1", "--exit", "2")
        self.run_cli("note", "--id", "1", "--mistake", "chased", "--text", "late")
        self.run_cli("note", "--id", "1", "--mistake", "chased")
        self.assertEqual(J.read_rows(self.csv)[0]["mistakes"], "chased")

    def test_summary_numbers_and_window(self):
        rows = []
        for d, e, x, st, m in [("2026-10-19", 100, 110, 95, ""), ("2026-10-20", 100, 95, 95, "chased"),
                               ("2026-10-21", 100, 104, 98, ""), ("2026-09-01", 100, 50, None, "")]:
            rows.append(J.make_row(rows, d, "TSLA", 1, e, x, stop=st, setup="orb", mistakes=m))
        s = J.summarize(rows, days=7, today=datetime.date(2026, 10, 23))
        self.assertEqual(s["trades"], 3)
        self.assertEqual(s["net_pnl"], 9.0)
        self.assertEqual(s["win_rate"], round(2 / 3, 4))
        self.assertEqual(s["profit_factor"], 2.8)
        self.assertEqual(s["mistakes"], {"chased": 1})
        self.assertEqual(s["mistake_pnl"], {"chased": -5.0})
        self.assertEqual(J.summarize(rows)["trades"], 4)


if __name__ == "__main__":
    unittest.main()
