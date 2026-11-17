#!/usr/bin/env python3
"""Trade journal for trader-journal. Standard library only.

    python3 journal.py log --symbol TSLA --qty 8 --entry 364.18 --exit 370.04 \\
        --date 2026-10-19 --setup orb --stop 358.32 --note "waited for the 5m close"
    python3 journal.py import                      # round trips from trader/state/broker.json fills
    python3 journal.py list [--last 20]
    python3 journal.py summary [--days 7] [--json]
    python3 journal.py note --id 3 --text "chased the entry" --mistake chased

The journal is trader/journal.csv, one row per closed round trip (long only,
like the rest of the pack): entry and exit price, shares, P&L, R multiple
(P&L over the planned risk, when a stop is known), the setup, mistakes and
notes. `import` reads the fills trader-broker logged, pairs each sell with
the oldest open buy of the same ticker (FIFO), and skips trips already in
the journal, so it is safe to run again.

Nothing here places, changes or suggests an order. It only records and counts.
"""

import argparse
import csv
import datetime
import json
import os
import sys

FIELDS = ["id", "date", "symbol", "setup", "qty", "entry", "exit", "stop", "pnl", "r_multiple",
          "mistakes", "note", "source"]
MISTAKES = ("chased", "no-stop", "moved-stop", "oversized", "early-exit", "late-exit",
            "revenge", "off-plan", "news-ignored")


class JournalError(Exception):
    pass


# ---------------------------------------------------------------- csv

def read_rows(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def write_rows(path, rows):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in FIELDS})
    os.replace(tmp, path)


def _num(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _fmt(x, places=2):
    if x is None:
        return ""
    s = ("%." + str(places) + "f") % x
    return s.rstrip("0").rstrip(".") if "." in s else s


def make_row(rows, date, symbol, qty, entry, exit_, stop=None, setup="", mistakes="", note="",
             source="manual"):
    qty, entry, exit_ = float(qty), float(entry), float(exit_)
    if qty <= 0 or entry <= 0 or exit_ <= 0:
        raise JournalError("qty, entry and exit must be positive")
    pnl = round((exit_ - entry) * qty, 2)
    r = None
    if stop is not None:
        risk = (entry - float(stop)) * qty
        if risk > 0:
            r = round(pnl / risk, 2)
    for m in [m for m in mistakes.split(";") if m]:
        if m not in MISTAKES:
            raise JournalError("unknown mistake tag %r (use: %s)" % (m, ", ".join(MISTAKES)))
    next_id = max([int(x["id"]) for x in rows if str(x.get("id", "")).isdigit()] + [0]) + 1
    return {"id": str(next_id), "date": date, "symbol": symbol.upper(), "setup": setup,
            "qty": _fmt(qty, 6), "entry": _fmt(entry, 4), "exit": _fmt(exit_, 4),
            "stop": _fmt(_num(stop), 4) if stop is not None else "", "pnl": "%.2f" % pnl,
            "r_multiple": "" if r is None else "%.2f" % r, "mistakes": mistakes, "note": note,
            "source": source}


# ---------------------------------------------------------------- broker import

def round_trips(fills):
    """Pair filled sells with the oldest open buys of the same ticker (FIFO)."""
    open_lots = {}
    trips = []
    for f in sorted(fills, key=lambda f: f.get("at", "")):
        if f.get("status") != "filled":
            continue
        sym = str(f.get("symbol", "")).upper()
        qty, price = float(f["qty"]), float(f["price"])
        if f.get("side") == "buy":
            open_lots.setdefault(sym, []).append([qty, price, f.get("date", ""), f.get("at", "")])
            continue
        left = qty
        lots = open_lots.get(sym, [])
        while left > 1e-9 and lots:
            lot = lots[0]
            take = min(left, lot[0])
            trips.append({"symbol": sym, "qty": take, "entry": lot[1], "exit": price,
                          "date": f.get("date", ""), "key": "%s|%s|%s" % (sym, lot[3], f.get("at", ""))})
            lot[0] -= take
            left -= take
            if lot[0] <= 1e-9:
                lots.pop(0)
    return trips


def import_fills(journal_path, state_path, plan_path):
    if not os.path.exists(state_path):
        raise JournalError("no %s yet: record fills with trader-broker first" % state_path)
    with open(state_path, encoding="utf-8") as fh:
        state = json.load(fh)
    plan = {}
    if plan_path and os.path.exists(plan_path):
        with open(plan_path, encoding="utf-8") as fh:
            plan = json.load(fh)
    rows = read_rows(journal_path)
    seen = set(r["source"] for r in rows)
    added = []
    for t in round_trips(state.get("orders", [])):
        src = "broker:" + t["key"]
        if src in seen:
            continue
        stop, setup = None, ""
        if str(plan.get("symbol", "")).upper() == t["symbol"] and plan.get("date", "") == t["date"]:
            stop = _num(plan.get("stop"))
            setup = str(plan.get("setup", ""))
        row = make_row(rows, t["date"], t["symbol"], t["qty"], t["entry"], t["exit"], stop=stop,
                       setup=setup, source=src)
        rows.append(row)
        added.append(row)
    write_rows(journal_path, rows)
    return added


# ---------------------------------------------------------------- summary

def summarize(rows, days=None, today=None):
    if days:
        today = today or datetime.date.today()
        cut = (today - datetime.timedelta(days=days - 1)).isoformat()
        rows = [r for r in rows if r.get("date", "") >= cut]
    pnls = [float(r["pnl"]) for r in rows]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    rs = [float(r["r_multiple"]) for r in rows if r.get("r_multiple")]
    mistakes = {}
    mistake_cost = {}
    for r in rows:
        for m in [m for m in r.get("mistakes", "").split(";") if m]:
            mistakes[m] = mistakes.get(m, 0) + 1
            mistake_cost[m] = round(mistake_cost.get(m, 0) + float(r["pnl"]), 2)
    setups = {}
    for r in rows:
        s = r.get("setup") or "(none)"
        e = setups.setdefault(s, {"trades": 0, "pnl": 0.0, "wins": 0})
        e["trades"] += 1
        e["pnl"] = round(e["pnl"] + float(r["pnl"]), 2)
        e["wins"] += 1 if float(r["pnl"]) > 0 else 0
    return {
        "trades": len(rows),
        "net_pnl": round(sum(pnls), 2),
        "win_rate": round(len(wins) / len(rows), 4) if rows else None,
        "avg_win": round(sum(wins) / len(wins), 2) if wins else None,
        "avg_loss": round(sum(losses) / len(losses), 2) if losses else None,
        "profit_factor": round(sum(wins) / -sum(losses), 2) if losses else None,
        "avg_r": round(sum(rs) / len(rs), 2) if rs else None,
        "best": max(pnls) if pnls else None,
        "worst": min(pnls) if pnls else None,
        "by_setup": setups,
        "mistakes": mistakes,
        "mistake_pnl": mistake_cost,
    }


def print_summary(s, days):
    span = "last %d day(s)" % days if days else "all time"
    if not s["trades"]:
        print("No trades in the journal (%s)." % span)
        return
    print("Journal, %s: %d trade(s), net %s" % (span, s["trades"], _money(s["net_pnl"])))
    print("  win rate %.0f %%, avg win %s, avg loss %s, profit factor %s, avg R %s"
          % (s["win_rate"] * 100, _money(s["avg_win"]), _money(s["avg_loss"]),
             "n/a" if s["profit_factor"] is None else s["profit_factor"],
             "n/a" if s["avg_r"] is None else s["avg_r"]))
    print("  best %s, worst %s" % (_money(s["best"]), _money(s["worst"])))
    print("  by setup:")
    for k, v in sorted(s["by_setup"].items(), key=lambda kv: -kv[1]["trades"]):
        print("    %-12s %d trade(s), %d win(s), %s" % (k, v["trades"], v["wins"], _money(v["pnl"])))
    if s["mistakes"]:
        print("  mistakes:")
        for k, v in sorted(s["mistakes"].items(), key=lambda kv: -kv[1]):
            print("    %-12s %d time(s), those trades netted %s" % (k, v, _money(s["mistake_pnl"][k])))
    print("Past results describe what happened, not what will happen. Not financial advice.")


def _money(x):
    if x is None:
        return "n/a"
    return ("-$%.2f" % -x) if x < 0 else ("$%.2f" % x)


# ---------------------------------------------------------------- cli

def main(argv=None):
    p = argparse.ArgumentParser(description="Trade journal: record round trips and review them.")
    p.add_argument("--journal", default="trader/journal.csv")
    sub = p.add_subparsers(dest="cmd")

    lg = sub.add_parser("log", help="add a closed trade by hand")
    lg.add_argument("--symbol", required=True)
    lg.add_argument("--qty", required=True, type=float)
    lg.add_argument("--entry", required=True, type=float)
    lg.add_argument("--exit", required=True, type=float)
    lg.add_argument("--stop", type=float)
    lg.add_argument("--date", default=datetime.date.today().isoformat())
    lg.add_argument("--setup", default="")
    lg.add_argument("--mistake", action="append", default=[])
    lg.add_argument("--note", default="")

    im = sub.add_parser("import", help="pull round trips from trader-broker fills")
    im.add_argument("--state", default="trader/state/broker.json")
    im.add_argument("--plan", default="trader/plan.json")

    ls = sub.add_parser("list")
    ls.add_argument("--last", type=int, default=20)

    sm = sub.add_parser("summary")
    sm.add_argument("--days", type=int)
    sm.add_argument("--today", help="pin today for --days, YYYY-MM-DD")
    sm.add_argument("--json", action="store_true")

    nt = sub.add_parser("note", help="add a note or mistake tag to a trade")
    nt.add_argument("--id", required=True)
    nt.add_argument("--text", default="")
    nt.add_argument("--mistake", action="append", default=[])

    a = p.parse_args(argv)
    try:
        if a.cmd == "log":
            rows = read_rows(a.journal)
            row = make_row(rows, a.date, a.symbol, a.qty, a.entry, a.exit, stop=a.stop, setup=a.setup,
                           mistakes=";".join(a.mistake), note=a.note)
            rows.append(row)
            write_rows(a.journal, rows)
            print("Logged #%s: %s %s %s -> %s, P&L %s%s" % (
                row["id"], row["symbol"], row["qty"], row["entry"], row["exit"], _money(float(row["pnl"])),
                (", %sR" % row["r_multiple"]) if row["r_multiple"] else ""))
        elif a.cmd == "import":
            added = import_fills(a.journal, a.state, a.plan)
            print("Imported %d new round trip(s) into %s." % (len(added), a.journal))
            for r in added:
                print("  #%s %s %s %s x %s -> %s, P&L %s" % (r["id"], r["date"], r["symbol"], r["qty"],
                                                           r["entry"], r["exit"], _money(float(r["pnl"]))))
        elif a.cmd == "list":
            rows = read_rows(a.journal)[-a.last:]
            if not rows:
                print("The journal is empty.")
            for r in rows:
                print("#%s %s %-6s %s x %s -> %s  %s  %s %s" % (
                    r["id"], r["date"], r["symbol"], r["qty"], r["entry"], r["exit"],
                    _money(float(r["pnl"])), r["setup"], ("[" + r["mistakes"] + "]") if r["mistakes"] else ""))
        elif a.cmd == "summary":
            today = datetime.date.fromisoformat(a.today) if a.today else None
            s = summarize(read_rows(a.journal), a.days, today)
            if a.json:
                print(json.dumps(s, indent=2))
            else:
                print_summary(s, a.days)
        elif a.cmd == "note":
            rows = read_rows(a.journal)
            hit = [r for r in rows if r["id"] == str(a.id)]
            if not hit:
                raise JournalError("no trade #%s in %s" % (a.id, a.journal))
            r = hit[0]
            for m in a.mistake:
                if m not in MISTAKES:
                    raise JournalError("unknown mistake tag %r (use: %s)" % (m, ", ".join(MISTAKES)))
            tags = [m for m in r.get("mistakes", "").split(";") if m]
            r["mistakes"] = ";".join(tags + [m for m in a.mistake if m not in tags])
            if a.text:
                r["note"] = (r["note"] + " | " + a.text) if r.get("note") else a.text
            write_rows(a.journal, rows)
            print("Updated #%s." % a.id)
        else:
            p.print_help()
            return 2
    except JournalError as e:
        print("journal: %s" % e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
