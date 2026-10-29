"""Compact storage in the pipeline (D-57): dual write, compact mode and interrupted baselines.

Mocked and offline (AGENTS rules 5 and 8): fake ATS listings, fake scorer and alert channel from `tests/test_core.py` (`Harness`),
the real CSV state in a temp directory and, where a Sheet is needed, the in-memory Sheets fake of `tests/fake_sheets.py`.
Nothing here touches Google Sheets, Groq or Telegram; the live checks are plan 03-05.
"""

from __future__ import annotations

import csv
import sys
import unittest
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import ledger as lg  # noqa: E402
from test_core import T0, HarnessCase, ago, job  # noqa: E402


def read_csv(case: HarnessCase, name: str) -> list[list[str]]:
    with (case.w.state.dir / f"{name}.csv").open(newline="", encoding="utf-8") as fh:
        return list(csv.reader(fh))


def drop_baseline_events(case: HarnessCase) -> int:
    """Simulate compact storage: the Events tab no longer holds the baseline rows. Returns how many were removed."""
    path = case.w.state.dir / "events.csv"
    rows = read_csv(case, "events")
    keep = [r for r in rows[:1]] + [r for r in rows[1:] if not (r[2] == lg.SEEN and r[4] == lg.BASELINED)]
    with path.open("w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows(keep)
    return len(rows) - len(keep)


class DualWriteTracerTests(HarnessCase):
    def baseline_three(self) -> list[str]:
        self.w.listings[self.board.key] = [job("acme", jid) for jid in ("1", "2", "3")]
        self.w.run(seeds=[self.board])
        return [f"greenhouse|acme|{jid}" for jid in ("1", "2", "3")]

    def test_baseline_writes_events_one_identity_chunk_and_one_tally_row(self) -> None:
        keys = self.baseline_three()
        run_id = self.w.state.load_runs()[-1].run_id
        identity = read_csv(self, "identity")[1:]
        self.assertEqual(len(identity), 1)
        stem, chunk, baselined_at, count, ids = identity[0]
        self.assertEqual((stem, chunk, count), ("greenhouse|acme", "1", "3"))
        self.assertNotEqual(baselined_at, "")
        self.assertEqual(sorted(ids.split(",")), ["b1", "b2", "b3"])
        tally = read_csv(self, "tally")[1:]
        self.assertEqual(len(tally), 1)
        self.assertEqual((tally[0][0], tally[0][2]), (run_id, "3"))
        self.assertEqual(tally[0][3], '{"greenhouse|poll|baseline|baseline|baseline|u":3}')
        self.assertEqual(sorted(e.key for e in self.w.events(kind=lg.SEEN)), keys)  # dual mode: Events still has every baseline row

    def test_a_run_whose_events_lost_the_baseline_rows_still_treats_those_ids_as_seen(self) -> None:
        keys = self.baseline_three()
        self.assertEqual(drop_baseline_events(self), 3)
        self.assertEqual(self.w.events(), [])
        later = T0 + timedelta(minutes=60)
        self.w.listings[self.board.key].append(job("acme", "9", published=ago(minutes=30, base=later)))
        self.w.run(minutes_later=60)
        self.w.run(minutes_later=60)
        seen = [e.key for e in self.w.events(kind=lg.SEEN)]
        self.assertEqual(seen, ["greenhouse|acme|9"])  # the fresh job only: nothing baselined was observed again
        self.assertFalse(set(keys) & set(seen))
        self.assertEqual(len(self.w.events(kind=lg.EVALUATED)), 1)
        self.assertEqual(len(self.w.alerts), 1)  # one alert in total across both runs

    def test_every_run_appends_one_tally_row_even_with_nothing_to_count(self) -> None:
        self.baseline_three()
        self.w.run(minutes_later=60)
        rows = read_csv(self, "tally")[1:]
        self.assertEqual(len(rows), 2)
        self.assertEqual((rows[1][2], rows[1][3]), ("0", "{}"))

    def test_no_job_text_reaches_identity_or_tally(self) -> None:
        self.w.listings[self.board.key] = [job("acme", "1", title="Secret Title ZZQ", published=ago(days=40))]
        self.w.run(seeds=[self.board])
        text = "".join(",".join(r) for name in ("identity", "tally") for r in read_csv(self, name))
        for forbidden in ("Secret Title ZZQ", "http", "Remote"):
            self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
