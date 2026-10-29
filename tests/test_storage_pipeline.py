"""Compact storage in the pipeline (D-57): dual write, compact mode and interrupted baselines.

Mocked and offline (AGENTS rules 5 and 8): fake ATS listings, fake scorer and alert channel from `tests/test_core.py` (`Harness`),
the real CSV state in a temp directory and, where a Sheet is needed, the in-memory Sheets fake of `tests/fake_sheets.py`.
Nothing here touches Google Sheets, Groq or Telegram; the live checks are plan 03-05.
"""

from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import boards as bd  # noqa: E402
import compact  # noqa: E402
import ledger as lg  # noqa: E402
import pipeline as pl  # noqa: E402
import state as stm  # noqa: E402
from fake_sheets import FakeSpreadsheet  # noqa: E402
from test_core import T0, Harness, HarnessCase, ago, job  # noqa: E402


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


def make_compact(case: HarnessCase) -> None:
    """Put the CSV store into compact mode: the Discovery key says so and Events_Legacy exists (the tab swap was done)."""
    case.w.state.save_discovery_state({compact.STORAGE_KEY: '{"mode":"compact"}'}, "2026-10-14T11:00:00Z")
    (case.w.state.dir / "events_legacy.csv").write_text("Time,Job_Key,Event,Freshness,Disposition,Published,Detail\n", encoding="utf-8")


def identity_ids(case: HarnessCase) -> list[str]:
    return [e for r in read_csv(case, "identity")[1:] for e in r[4].split(",") if e]


class CompactModeTests(HarnessCase):
    def test_compact_mode_keeps_baselines_out_of_events_but_not_gated_or_stale_rows(self) -> None:
        make_compact(self)
        self.w.listings[self.board.key] = [job("acme", jid) for jid in ("1", "2", "3")]
        self.w.run(seeds=[self.board])
        self.assertEqual(self.w.events(), [])  # a baseline writes no Events row
        self.assertEqual(sorted(identity_ids(self)), ["b1", "b2", "b3"])
        self.assertEqual(read_csv(self, "tally")[1][3], '{"greenhouse|poll|baseline|baseline|baseline|u":3}')
        later = T0 + timedelta(minutes=60)
        self.w.listings[self.board.key] += [
            job("acme", "10", title="Senior Staff Plumber"),  # the title gate rejects it
            job("acme", "11", published=ago(days=40, base=later)),  # older than the maximum age
            job("acme", "12", published=ago(minutes=20, base=later)),  # fresh and relevant: an operational row
        ]
        self.w.run(minutes_later=60)
        by_key = {e.key: e for e in self.w.events(kind=lg.SEEN)}
        self.assertEqual({k: e.disposition for k, e in by_key.items()},
                         {"greenhouse|acme|10": lg.FILTERED, "greenhouse|acme|11": lg.STALED, "greenhouse|acme|12": lg.PENDING})
        self.assertEqual(sorted(identity_ids(self)), ["b1", "b2", "b3", "f10", "s11"])  # the pending job is operational: never in Identity
        counts = compact.TallyRow.from_row(read_csv(self, "tally")[2])
        assert counts is not None
        self.assertEqual(counts.total, 2)  # filtered and stale are counted; the pending job is not
        self.assertEqual(len(self.w.alerts), 1)

    def test_compact_mode_never_makes_a_seen_job_new_across_runs(self) -> None:
        make_compact(self)
        self.w.listings[self.board.key] = [job("acme", jid) for jid in ("1", "2", "3")]
        self.w.run(seeds=[self.board])
        for _ in range(3):
            self.w.run(minutes_later=60)
        self.assertEqual(self.w.events(), [])
        self.assertEqual(self.w.alerts, [])
        self.assertEqual(len(read_csv(self, "tally")) - 1, 4)  # one Tally row per run

    def test_without_events_legacy_the_run_writes_as_dual(self) -> None:
        self.w.state.save_discovery_state({compact.STORAGE_KEY: '{"mode":"compact"}'}, "2026-10-14T11:00:00Z")  # the key alone is not enough
        self.w.listings[self.board.key] = [job("acme", "1")]
        self.w.run(seeds=[self.board])
        self.assertEqual(len(self.w.events(kind=lg.SEEN)), 1)

    def test_a_mixed_case_lever_board_is_keyed_by_the_lowercase_stem_in_a_run(self) -> None:
        lever = bd.BoardId(bd.LEVER, "Foo")
        self.w.listings[lever.key] = [job("Foo", "AbC1", ats=bd.LEVER), job("Foo", "DeF2", ats=bd.LEVER)]
        self.w.run(seeds=[lever])
        self.assertEqual([r[0] for r in read_csv(self, "identity")[1:]], ["lever|foo"])
        self.assertEqual(self.w.state.load_ledger().identity.keys(), {"lever|foo|abc1", "lever|foo|def2"})
        self.assertEqual(drop_baseline_events(self), 2)
        self.w.run(minutes_later=60)
        self.assertEqual(self.w.events(), [])  # nothing looked new


class SheetHarness(Harness):
    """The same fake world over the in-memory Sheets fake instead of CSV files."""

    def __init__(self, tmp: str) -> None:
        super().__init__(tmp)
        self.sh = FakeSpreadsheet()
        self.state = stm.SheetState(self.sh)
        self.state.ensure()


def ids31(n: int) -> list[str]:
    return [f"{i:031d}" for i in range(n)]


class InterruptedBaselineTests(unittest.TestCase):
    """Success criterion 4: an Identity write cut off after chunk k never leaves a half-recorded board that looks done."""

    board = bd.BoardId(bd.GREENHOUSE, "acme")

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.w = SheetHarness(tmp.name)
        self.w.listings[self.board.key] = [job("acme", jid) for jid in ids31(5050)]
        patch = mock.patch.object(compact, "IDENTITY_REQUEST_CHARS", 45_000)  # one 40,000-character chunk per request
        patch.start()
        self.addCleanup(patch.stop)

    def go_compact(self) -> None:
        self.w.sh.add_worksheet(stm.EVENTS_LEGACY_TAB, 10, 7)
        self.w.sh.worksheet(stm.DISCOVERY_TAB).append_rows([[compact.STORAGE_KEY, '{"mode":"compact"}', ""]])

    def board_baselined(self) -> str:
        rec = self.w.state.load_boards().get(self.board.key)
        return rec.baselined_at if rec else ""

    def test_a_cut_off_compact_baseline_is_a_baseline_pass_again_with_nothing_alerted(self) -> None:
        self.go_compact()
        self.w.sh.fail_on_write_to(stm.IDENTITY_TAB, 3)  # chunks 1 and 2 are written, chunk 3 fails
        with self.assertRaises(RuntimeError):
            self.w.run(seeds=[self.board])
        self.assertEqual(self.board_baselined(), "")  # Boards.Baselined_At was not saved
        part = self.w.state.load_ledger().identity
        self.assertEqual([r.chunk for r in part.rows("greenhouse|acme")], [1, 2])
        self.assertEqual(part.baselined_at("greenhouse|acme"), "")  # no completion marker
        self.w.run(minutes_later=60, seeds=[self.board])  # no fault: the next run baselines the board again
        ledger = self.w.state.load_ledger()
        self.assertEqual([e for e in ledger.events if e.disposition == lg.PENDING], [])
        self.assertEqual(self.w.alerts, [])
        self.assertNotEqual(self.board_baselined(), "")
        identity = ledger.identity
        self.assertEqual(len(identity), 5050)
        self.assertEqual(sum(r.count for r in identity.rows("greenhouse|acme")), 5050)  # each posting ID exactly once
        self.assertEqual(identity.keys(), {f"greenhouse|acme|{i}" for i in ids31(5050)})
        rows = identity.rows("greenhouse|acme")
        self.assertEqual([r.baselined_at != "" for r in rows], [False] * (len(rows) - 1) + [True])  # the marker is on the highest chunk only
        # The interrupted run failed before its Tally write (Events, Identity, Tally, Boards): its 2,424 durable IDs have no count. Only the
        # second run's 2,626 observations are tallied. A count lost is visible to parity (plan 03-02); a posting ID lost would be a flood.
        self.assertEqual([t.total for t in ledger.tally], [5050 - 2 * 1212])

    def test_the_same_fault_in_dual_mode_is_contained_and_events_stays_authoritative(self) -> None:
        self.w.sh.fail_on_write_to(stm.IDENTITY_TAB, 3)
        run = self.w.run(seeds=[self.board])
        self.assertEqual(run.outcome, stm.OUTCOME_DEGRADED)
        self.assertIn("storage", pl.degraded_reason(run))
        self.assertIn("storage write failed", run.notes)
        self.assertNotIn("injected", run.notes)  # the exception type only, never its text
        self.assertEqual(len(self.w.events(kind=lg.SEEN)), 5050)
        self.assertNotEqual(self.board_baselined(), "")
        self.assertEqual(len(self.w.state.load_ledger().tally), 1)

    def test_compact_mode_on_the_sheet_store_writes_identity_and_tally_without_baseline_events(self) -> None:
        self.go_compact()
        self.w.listings[self.board.key] = [job("acme", jid) for jid in ids31(30)]
        run = self.w.run(seeds=[self.board])
        self.assertEqual(run.outcome, stm.OUTCOME_OK)
        ledger = self.w.state.load_ledger()
        self.assertEqual((ledger.events, len(ledger.identity)), ([], 30))
        self.assertEqual((ledger.tally[0].run_id, ledger.tally[0].total), (run.run_id, 30))
        self.assertNotEqual(self.board_baselined(), "")


if __name__ == "__main__":
    unittest.main()
