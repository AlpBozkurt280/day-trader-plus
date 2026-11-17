---
name: trader-journal
description: >-
  Trade Journal. Records every closed trade (entry, exit, shares, P&L, the R
  multiple against the planned stop, the setup, mistakes and notes) in
  trader/journal.csv, pulls round trips straight from the fills trader-broker
  logged so nothing is typed twice, and reviews them: win rate, average win
  and loss, profit factor, average R, results by setup, and which mistakes
  showed up and what those trades netted. Use when the user says "log this
  trade", "journal it", "add to my journal", "how did I do this week", "what
  is my win rate", "review my trades", "what mistakes do I keep making",
  "weekly review", or right after trader-broker records a sell fill.
argument-hint: "[log|import|summary] [ticker]"
---

# trader-journal

The Trade Journal is the memory of the pack. The other skills plan and check
one trade at a time; the journal keeps all of them so the user can see what
actually works for them. It records and counts. It never says what to trade.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/journal.py" import                         # round trips from trader-broker fills
python3 "${CLAUDE_SKILL_DIR}/journal.py" log --symbol TSLA --qty 8 \
    --entry 364.18 --exit 370.04 --stop 358.32 --setup orb --date 2026-10-19
python3 "${CLAUDE_SKILL_DIR}/journal.py" note --id 3 --mistake chased --text "bought the 3rd green bar"
python3 "${CLAUDE_SKILL_DIR}/journal.py" list --last 10
python3 "${CLAUDE_SKILL_DIR}/journal.py" summary --days 7                # the weekly review
python3 "${CLAUDE_SKILL_DIR}/journal.py" summary --json                  # all time, machine readable
```

`--journal PATH` points at a different CSV; `summary --today 2026-10-23`
pins the date for `--days`.

## What it reads and writes

| file | what |
| --- | --- |
| `trader/state/broker.json` | the fills trader-broker logged, for `import` |
| `trader/plan.json` | the plan's stop and setup, matched by ticker and date, so `import` can work out R |
| `trader/journal.csv` | the journal: one row per closed round trip |

## The columns

| column | what |
| --- | --- |
| `id` | 1, 2, 3, ... in the order trades were added |
| `date` | the New York date the trade closed |
| `symbol`, `qty`, `entry`, `exit` | the round trip (long only, like the rest of the pack) |
| `stop` | the planned stop, if known |
| `pnl` | (exit - entry) x qty, in dollars, before fees |
| `r_multiple` | pnl divided by the planned risk (entry - stop) x qty; blank with no stop |
| `setup` | orb, flag, bounce, level, or whatever the user calls it |
| `mistakes` | tags separated by `;` from this list: chased, no-stop, moved-stop, oversized, early-exit, late-exit, revenge, off-plan, news-ignored |
| `note` | free text, in the user's words |
| `source` | `manual`, or `broker:` plus the fill times, so `import` never adds a trip twice |

## Steps

1. After trader-broker records a sell fill, run `import`. It pairs each sell
   with the oldest open buy of the same ticker (first in, first out), and adds
   only trips that are not in the journal yet. Read the new rows back to the user.
2. Ask the user, in one question, whether anything went off plan. If they
   name something, tag it with `note --mistake` using their words in `--text`.
   Never tag a mistake the user did not name.
3. A trade taken outside the pack (another app, another broker) goes in with
   `log`. Ask for the stop if they had one, so R can be worked out.
4. For a review, run `summary --days 7` (or the span they ask for) and report
   it plainly: the numbers first, then the setups, then the mistakes and what
   those trades netted. A small sample is a small sample: under 20 trades,
   say so.

## Example

The reel's TSLA trade, closed at the target:

```
$ python3 journal.py log --symbol TSLA --qty 8 --entry 364.18 --exit 370.04 --stop 358.32 --setup orb --date 2026-10-19
Logged #1: TSLA 8 364.18 -> 370.04, P&L $46.88, 1.00R
```

A week later, `summary --days 7` (illustrative numbers):

```
Journal, last 7 day(s): 4 trade(s), net $35.12
  win rate 50 %, avg win $40.94, avg loss -$23.38, profit factor 1.75, avg R 0.38
  ...
  mistakes:
    chased       1 time(s), those trades netted -$28.40
```

## Rules

- Record what happened, in the user's words. Do not grade the user.
- Say the numbers as facts about the past. Never turn a win rate or a setup's
  results into a forecast or a suggestion to trade more, less or differently.
- P&L is before fees and taxes. Say so if the user asks about real returns.

## What it never does

It never places, cancels or changes an order, never edits trader-broker's
logs, and never says what the user should trade next.

## Safety

- Education and tooling, not financial advice. A journal shows the past, not the future.
- Nothing in this pack places an order except trader-broker, and only with the user's explicit yes for
  that one order, after trader-risk passes it. The journal only reads what already happened.
- Taxes: frequent trading makes wash sales likely, and this journal does not track them. Nothing here
  is tax advice.
