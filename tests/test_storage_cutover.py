"""Owner-triggered storage cutover and emergency restore (D-57; P3-06, P3-08, P3-14; plan 03-06).

MOCKED and offline (AGENTS rules 5 and 8): the in-memory Sheets fake of `tests/fake_sheets.py` interprets the tab renames, the
protection and the sheet metadata (Google did none of it), the ATS listings, the scorer and the alert channel are the fakes of
`tests/test_core.py`. No Google, Groq or Telegram call is made. The real swap on the real Sheet is plan 03-09.
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import boards as bd  # noqa: E402
import compact  # noqa: E402
import hunter as h  # noqa: E402
import ledger as lg  # noqa: E402
import pipeline as pl  # noqa: E402
import state as stm  # noqa: E402
import storage_report  # noqa: E402
from fake_sheets import FakeSpreadsheet  # noqa: E402
from test_core import Harness, ago, job  # noqa: E402
from test_hunter import settings  # noqa: E402
from test_storage_pipeline import historical_ledger  # noqa: E402

NOW = datetime(2026, 10, 18, 9, 0, tzinfo=timezone.utc)  # the cutover clock; the 7-day cut is 2026-10-11T09:00:00Z
OLD_IDS = ["1", "2", "3", "4", "5", "10", "11", "12", "13", "20", "21"]  # every job of `historical_ledger` that the board lists
GONE = {  # the keys whose `seen` rows leave Events: every baseline, and the stale job 13 (written 2026-10-05, older than 7 days)
    "greenhouse|acme|1", "greenhouse|acme|2", "greenhouse|acme|3", "greenhouse|acme|4", "greenhouse|acme|5", "greenhouse|acme|13", "lever|foo|abc1",
}  # filtered job 10 (2026-10-11T12:00), stale job 11 and filtered job 12 (2026-10-12) are inside the 7 days and stay


class CutoverCase(unittest.TestCase):
    """A dual-mode ledger on the Sheets fake: seeded by a real poller run, checked by a second one, then given a met parity bar."""

    board = bd.BoardId(bd.GREENHOUSE, "acme")

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.w = Harness(tmp.name)
        self.sh = FakeSpreadsheet()
        self.w.state = stm.SheetState(self.sh)
        self.w.state.ensure()
        self.published: list[Any] = []
        self.store = types.SimpleNamespace(state=self.w.state, tracker_rows=lambda: [], display_tz=timezone.utc, publish_dashboard=self.published.append)
        self.batches: list[dict[str, Any]] = []
        real = self.sh.batch_update

        def record(body: dict[str, Any]) -> dict[str, Any]:
            self.batches.append(body)
            return real(body)

        patch = mock.patch.object(self.sh, "batch_update", side_effect=record)
        patch.start()
        self.addCleanup(patch.stop)

    # -- the world
    def seed_dual(self) -> None:
        """The historical ledger, the seed run (which also evaluates and alerts the one pending job) and one checked run."""
        self.w.state.append_events(historical_ledger())
        self.w.listings[self.board.key] = [job("acme", i) for i in OLD_IDS]
        self.w.run(seeds=[self.board])
        self.w.run(minutes_later=60)
        self.assertEqual(len(self.w.alerts), 1)  # the pending job 20 was alerted before the cutover

    def set_storage(self, edit: Any) -> None:
        values = self.w.state.load_discovery_state()
        state = compact.StorageState.load(values.get(compact.STORAGE_KEY))
        edit(state)
        values[compact.STORAGE_KEY] = state.to_json()
        self.w.state.save_discovery_state(values, "2026-10-18T08:00:00Z")

    def met_bar(self) -> None:
        """Three clean complete UTC days with 12 checked runs each (and one admission) before NOW."""
        def edit(state: compact.StorageState) -> None:
            for day, admissions in (("2026-10-15", 0), ("2026-10-16", 1), ("2026-10-17", 0)):
                state.days[day] = {"runs": 12, "diff_runs": 0, "failed": 0, "admissions": admissions}

        self.set_storage(edit)
        self.assertTrue(self.storage().bar(NOW).met)

    def storage(self) -> compact.StorageState:
        return compact.StorageState.load(self.w.state.load_discovery_state().get(compact.STORAGE_KEY))

    def seeded_with_met_bar(self) -> None:
        self.seed_dual()
        self.met_bar()

    # -- the commands
    def cutover(self, *, dry_run: bool = False, now: datetime = NOW) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = h.run_storage_cutover(self.store, settings(), dry_run=dry_run, now=now)
        return code, out.getvalue()

    def snapshot(self) -> tuple[dict[str, list[list[str]]], int, int, int]:
        """Everything a command could change in the spreadsheet: every tab's values, the write counter, the spreadsheet batches, the tab titles."""
        tabs = {t: [list(r) for r in ws.values] for t, ws in self.sh.sheets.items()}
        return tabs, self.sh.writes, len(self.sh.requests), len(self.sh.sheets)

    def renames(self) -> list[dict[str, Any]]:
        return [b for b in self.batches if any("updateSheetProperties" in r for r in b["requests"])]

    def poll_with_one_new_job(self, minutes_later: int = 30) -> pl.RunRecord:
        self.w.now = max(self.w.now, NOW)  # a poller run after the cutover happens after it: the clocks never go back
        later = self.w.now + timedelta(minutes=minutes_later)
        self.w.listings[self.board.key] = [job("acme", i) for i in OLD_IDS] + [job("acme", "99", published=ago(minutes=30, base=later))]
        return self.w.run(minutes_later=minutes_later)


class CutoverTracerTests(CutoverCase):
    """Tracer: the whole cutover on the fake, then a poller run on the swapped state."""

    def setUp(self) -> None:
        super().setUp()
        self.seeded_with_met_bar()
        self.original = [list(r) for r in self.sh.sheets[stm.EVENTS_TAB].values]
        self.events_id = self.sh.sheets[stm.EVENTS_TAB].id
        self.code, self.text = self.cutover()

    def test_the_cutover_exits_zero_and_prints_counts_only(self) -> None:
        self.assertEqual(self.code, 0, self.text)
        self.assertIn("STORAGE CUTOVER done", self.text)
        for forbidden in ("http", "Marketing", "Remote"):
            self.assertNotIn(forbidden, self.text)  # the log is public: counts, never titles or URLs

    def test_one_spreadsheet_batch_renames_events_then_events_new_in_that_order(self) -> None:
        renames = self.renames()
        self.assertEqual(len(renames), 1)  # one batch: the Sheet is never without an Events tab
        requests = renames[0]["requests"]
        self.assertEqual(len(requests), 2)
        first, second = (r["updateSheetProperties"] for r in requests)
        self.assertEqual((first["properties"]["sheetId"], first["properties"]["title"], first["fields"]), (self.events_id, "Events_Legacy", "title"))
        self.assertEqual((second["properties"]["title"], second["fields"]), ("Events", "title"))
        self.assertEqual(second["properties"]["sheetId"], self.sh.sheets[stm.EVENTS_TAB].id)  # the tab that is Events now is the one that was Events_New
        self.assertNotEqual(second["properties"]["sheetId"], self.events_id)

    def test_events_holds_exactly_the_retained_rows_in_their_order(self) -> None:
        expected = [r for r in self.original[1:] if not (r[2] == lg.SEEN and r[1] in GONE)]
        self.assertLess(len(expected), len(self.original) - 1)
        self.assertEqual(self.sh.sheets[stm.EVENTS_TAB].values, [self.original[0]] + expected)
        kept = {r[1] for r in expected if r[2] == lg.SEEN}
        self.assertEqual(kept & GONE, set())
        self.assertTrue({"greenhouse|acme|10", "greenhouse|acme|11", "greenhouse|acme|12", "greenhouse|acme|20", "greenhouse|acme|21"} <= kept)

    def test_events_legacy_keeps_every_original_row_hidden_and_warning_protected(self) -> None:
        legacy = self.sh.sheets[stm.EVENTS_LEGACY_TAB]
        self.assertEqual(legacy.values, self.original)
        self.assertTrue(legacy.hidden)
        self.assertTrue(self.sh.sheets[stm.EVENTS_TAB].hidden)  # the compact copy is hidden like the ledger it replaces
        self.assertTrue(self.sh.protected[legacy.id])
        self.assertTrue(all(p["warningOnly"] and p["range"] == {"sheetId": legacy.id} for p in self.sh.protected[legacy.id]))
        self.assertNotIn(stm.EVENTS_NEW_TAB, self.sh.sheets)

    def test_the_storage_key_says_compact_with_the_cutover_record_and_the_before_snapshot(self) -> None:
        state = self.storage()
        self.assertEqual(state.mode, compact.MODE_COMPACT)
        record = state.cutover
        self.assertEqual(record["at"], lg.stamp(NOW))
        legacy_rows = len(self.original) - 1
        self.assertEqual(record["legacy_rows"], legacy_rows)
        self.assertEqual(record["retained_rows"], len(self.sh.sheets[stm.EVENTS_TAB].values) - 1)
        self.assertRegex(record["checksum"], r"^[0-9a-f]{64}$")
        before = record["before"]
        self.assertEqual(before["events_rows"], legacy_rows)
        self.assertEqual(before["cells"][stm.EVENTS_TAB], 5000 * 7)  # the grid the tab had before the swap
        self.assertEqual(before["cells_total"], sum(before["cells"].values()))
        self.assertEqual(len(self.published), 1)  # the Dashboard was refreshed
        self.assertIsNotNone(state.seeded_at)  # the rewrite kept the seed time and the parity days
        self.assertTrue(state.days)
        self.assertNotIn("Marketing", json.dumps(record))

    def test_a_poller_run_on_the_swapped_state_sees_nothing_old_as_new_and_alerts_once(self) -> None:
        alerts_before = len(self.w.alerts)
        rows_before = len(self.sh.sheets[stm.EVENTS_TAB].values)
        legacy_before = [list(r) for r in self.sh.sheets[stm.EVENTS_LEGACY_TAB].values]
        run = self.poll_with_one_new_job()
        self.assertEqual(run.outcome, stm.OUTCOME_OK, run.notes)
        written = self.sh.sheets[stm.EVENTS_TAB].values[rows_before:]
        self.assertEqual({r[1] for r in written if r[2] == lg.SEEN}, {"greenhouse|acme|99"})  # no old ID was observed again
        self.assertEqual([r[1] for r in written if r[2] == lg.EVALUATED], ["greenhouse|acme|99"])  # nothing old was evaluated
        self.assertEqual(len(self.w.alerts), alerts_before + 1)
        self.assertEqual([r[1] for r in written if r[2] == lg.ALERTED], ["greenhouse|acme|99"])
        self.assertEqual(self.sh.sheets[stm.EVENTS_LEGACY_TAB].values, legacy_before)  # Events_Legacy is never written again
        again = self.poll_with_one_new_job(minutes_later=60)
        self.assertEqual(again.outcome, stm.OUTCOME_OK, again.notes)
        self.assertEqual(len(self.w.alerts), alerts_before + 1)  # and never twice

    def test_no_row_or_tab_of_events_or_events_legacy_was_deleted_or_cleared(self) -> None:
        for batch in self.batches:
            for request in batch["requests"]:
                self.assertNotIn("deleteDimension", request)
                self.assertNotIn("deleteSheet", request)
        self.assertIn(stm.EVENTS_TAB, self.sh.sheets)
        self.assertIn(stm.EVENTS_LEGACY_TAB, self.sh.sheets)


class BeforeSnapshotTests(unittest.TestCase):
    """`storage_report.before_snapshot`: what the owner will compare the compact ledger with (P3-06)."""

    def run_at(self, day: str, hour: int, events_rows: int, load_s: int, outcome: str = stm.OUTCOME_OK, kind: str = stm.KIND_PRODUCTION) -> stm.RunRecord:
        return stm.RunRecord(f"{day}T{hour:02d}:00:00Z", events_rows=events_rows, load_s=load_s, outcome=outcome, run_kind=kind)

    def test_cells_per_tab_and_in_total_come_from_the_grid(self) -> None:
        snap = storage_report.before_snapshot([], {"Events": (5000, 7), "Boards": (1000, 32)}, 4321, NOW)
        self.assertEqual(snap["events_rows"], 4321)
        self.assertEqual(snap["cells"], {"Boards": 32_000, "Events": 35_000})
        self.assertEqual(snap["cells_total"], 67_000)
        self.assertEqual(snap["grid"], {"Boards": [1000, 32], "Events": [5000, 7]})
        self.assertEqual((snap["median_load_s"], snap["median_daily_events_growth"]), (None, None))  # nothing measured is None, never 0

    def test_median_load_is_over_the_last_24_completed_production_runs(self) -> None:
        runs = [self.run_at("2026-10-01", 0, 100, 500)]  # too old: outside the last 24
        runs += [self.run_at("2026-10-02", i % 24, 100, 10 + i) for i in range(24)]  # loads 10..33: median 21.5
        runs.append(self.run_at("2026-10-03", 5, 100, 999, outcome=stm.OUTCOME_STARTED))  # never finished: not completed
        runs.append(self.run_at("2026-10-03", 6, 100, 999, kind=stm.KIND_REHEARSAL))  # a local rehearsal is not production
        self.assertEqual(storage_report.before_snapshot(runs, {}, 0, NOW)["median_load_s"], 21.5)

    def test_median_daily_growth_uses_the_last_events_rows_of_each_complete_utc_day(self) -> None:
        runs = []
        for day, rows in (("2026-10-09", 1000), ("2026-10-10", 1100), ("2026-10-11", 1300), ("2026-10-12", 1350), ("2026-10-13", 1450), ("2026-10-14", 1500), ("2026-10-15", 1550), ("2026-10-16", 1700), ("2026-10-17", 1800)):
            runs += [self.run_at(day, 3, rows - 50, 5), self.run_at(day, 22, rows, 5)]  # the day's last run decides
        runs.append(self.run_at("2026-10-18", 1, 99_999, 5))  # today is not complete: never counted
        snap = storage_report.before_snapshot(runs, {}, 0, NOW)
        # growth of the last 7 complete days (10-11 .. 10-17): 200, 50, 100, 50, 50, 150, 100 -> median 100
        self.assertEqual(snap["median_daily_events_growth"], 100)

    def test_a_gap_in_the_days_gives_no_growth_figure_for_the_day_after_it(self) -> None:
        runs = [self.run_at("2026-10-14", 5, 1000, 5), self.run_at("2026-10-16", 5, 1900, 5), self.run_at("2026-10-17", 5, 2000, 5)]
        self.assertEqual(storage_report.before_snapshot(runs, {}, 0, NOW)["median_daily_events_growth"], 100)  # 10-16 follows a missing day: only 10-17 counts


if __name__ == "__main__":
    unittest.main()
