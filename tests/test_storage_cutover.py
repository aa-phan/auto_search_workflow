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

    def poll(self, minutes_later: int = 30, *, new_jobs: tuple[str, ...] = (), seeds: list[bd.BoardId] | None = None) -> pl.RunRecord:
        """One poller run on the current state: the board lists every old job plus `new_jobs` (fresh, published 30 minutes before the run)."""
        self.w.now = max(self.w.now, NOW)  # a poller run after the cutover happens after it: the clocks never go back
        later = self.w.now + timedelta(minutes=minutes_later)
        self.w.listings[self.board.key] = [job("acme", i) for i in OLD_IDS] + [job("acme", j, published=ago(minutes=30, base=later)) for j in new_jobs]
        return self.w.run(minutes_later=minutes_later, seeds=seeds)

    def poll_with_one_new_job(self, minutes_later: int = 30) -> pl.RunRecord:
        return self.poll(minutes_later, new_jobs=("99",))


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


class CutoverGateTests(CutoverCase):
    """Every unsafe state is refused with one line naming the unmet condition and without a single write (T-03-23)."""

    def refused(self, *needles: str, now: datetime = NOW) -> str:
        before, renames = self.snapshot(), len(self.renames())
        code, text = self.cutover(now=now)
        self.assertEqual(code, 1, text)
        self.assertEqual(len(text.strip().splitlines()), 1, text)  # one line, naming the unmet condition
        for needle in needles:
            self.assertIn(needle, text)
        self.assertEqual(self.snapshot(), before)  # zero writes: no row, no tab, no Discovery key, no spreadsheet batch
        self.assertEqual(len(self.renames()), renames)
        return text

    def test_the_bar_not_met_refuses(self) -> None:
        self.seed_dual()  # seeded and checked once, but not three clean complete days
        self.refused("parity bar is not met", "0 of 3")

    def test_a_hand_edited_storage_key_alone_never_triggers_the_swap(self) -> None:
        self.seed_dual()
        self.set_storage(lambda s: setattr(s, "bar_met_at", "2026-10-17T00:00:00Z"))  # claims the bar was met; the recorded days say otherwise
        self.refused("parity bar is not met")

    def test_a_bar_that_was_met_but_is_stale_refuses(self) -> None:
        self.seeded_with_met_bar()
        self.refused("parity bar is not met", now=NOW + timedelta(days=1))  # no checked run recorded for yesterday: the three days no longer end yesterday

    def test_stores_that_are_not_seeded_refuse(self) -> None:
        self.refused("not seeded")

    def test_a_fresh_parity_difference_refuses_even_with_the_bar_met(self) -> None:
        self.seeded_with_met_bar()
        row = next(r for r in self.sh.sheets[stm.IDENTITY_TAB].values[1:] if r[0] == "greenhouse|acme")
        row[4] = ",".join(e for e in row[4].split(",") if e != "b1")  # one posting ID is gone from Identity
        self.refused("fresh parity check counted", "identity_missing 1")

    def test_mode_compact_refuses_after_a_cutover(self) -> None:
        self.seeded_with_met_bar()
        self.assertEqual(self.cutover()[0], 0)
        self.refused("already compact")

    def test_mode_restored_refuses_until_a_new_owner_decision(self) -> None:
        self.seeded_with_met_bar()
        self.set_storage(lambda s: setattr(s, "mode", compact.MODE_RESTORED))
        self.refused("restored", "new owner decision")

    def legacy_tab(self, rows: list[list[str]]) -> None:
        self.sh.add_worksheet(stm.EVENTS_LEGACY_TAB, 10, 7).append_rows([lg.EVENT_COLUMNS, *rows], value_input_option="RAW")

    def test_an_empty_events_legacy_tab_is_not_a_finished_swap_and_refuses(self) -> None:
        self.seeded_with_met_bar()
        self.legacy_tab([])
        self.refused("Events_Legacy", "fewer rows")

    def test_an_events_legacy_tab_that_saw_a_job_events_and_identity_do_not_hold_refuses(self) -> None:
        self.seeded_with_met_bar()
        self.legacy_tab([list(r) for r in self.sh.sheets[stm.EVENTS_TAB].values[1:]] + [[lg.stamp(NOW), "greenhouse|ghost|1", lg.SEEN, "baseline", lg.BASELINED, "", "{}"]])
        self.refused("Events_Legacy", "do not hold 1 of")

    def test_an_events_legacy_tab_that_lacks_an_old_events_row_refuses(self) -> None:
        self.seeded_with_met_bar()
        rows = [list(r) for r in self.sh.sheets[stm.EVENTS_TAB].values[1:]]
        del rows[2]  # an old row that Events holds and the tab does not: Events is not the copy of this tab plus newer rows
        self.legacy_tab(rows + [rows[-1]])  # (the tab still has as many rows as any run loaded, so only the age of the missing row refuses it)
        self.refused("Events_Legacy", "older than")

    def test_a_dry_run_with_a_passing_gate_prints_the_plan_and_writes_nothing(self) -> None:
        self.seeded_with_met_bar()
        before = self.snapshot()
        code, text = self.cutover(dry_run=True)
        self.assertEqual(code, 0, text)
        self.assertEqual(self.snapshot(), before)
        self.assertIn("dry run; nothing was written", text)
        self.assertIn("bar met (3 of 3", text)
        self.assertIn("10 of 17 Events rows stay in Events", text)
        self.assertRegex(text, r"checksum of the retained rows: [0-9a-f]{64}")
        self.assertIn("before: 17 Events rows", text)
        self.assertNotIn(stm.EVENTS_NEW_TAB, self.sh.sheets)
        self.assertEqual(self.renames(), [])

    def test_a_dry_run_with_a_failing_gate_exits_one(self) -> None:
        self.seed_dual()
        before = self.snapshot()
        code, text = self.cutover(dry_run=True)
        self.assertEqual((code, self.snapshot()), (1, before), text)

    def test_a_leftover_events_new_from_an_earlier_attempt_is_replaced(self) -> None:
        self.seeded_with_met_bar()
        leftover = self.sh.add_worksheet(stm.EVENTS_NEW_TAB, 10, 7)
        leftover.append_rows([lg.EVENT_COLUMNS, [lg.stamp(NOW), "greenhouse|junk|1", lg.SEEN, "", "", "", "{}"]], value_input_option="RAW")
        original = [list(r) for r in self.sh.sheets[stm.EVENTS_TAB].values]
        code, text = self.cutover()
        self.assertEqual(code, 0, text)
        self.assertNotIn("junk", json.dumps(self.sh.sheets[stm.EVENTS_TAB].values))
        self.assertEqual(self.sh.sheets[stm.EVENTS_LEGACY_TAB].values, original)
        self.assertNotIn(stm.EVENTS_NEW_TAB, self.sh.sheets)

    def test_a_read_back_that_drops_one_row_refuses_with_events_untouched(self) -> None:
        self.seeded_with_met_bar()
        original = [list(r) for r in self.sh.sheets[stm.EVENTS_TAB].values]
        real = self.w.state.build_events_new
        with mock.patch.object(self.w.state, "build_events_new", side_effect=lambda events: real(events)[:-1]):
            code, text = self.cutover()
        self.assertEqual(code, 1, text)
        self.assertIn("read back", text)
        self.assertEqual(self.sh.sheets[stm.EVENTS_TAB].values, original)
        self.assertNotIn(stm.EVENTS_LEGACY_TAB, self.sh.sheets)
        self.assertEqual(self.renames(), [])
        self.assertEqual(self.storage().mode, compact.MODE_DUAL)

    def test_a_read_back_with_the_same_count_but_a_changed_row_refuses_on_the_checksum(self) -> None:
        self.seeded_with_met_bar()
        original = [list(r) for r in self.sh.sheets[stm.EVENTS_TAB].values]
        real = self.w.state.build_events_new

        def altered(events: list[lg.Event]) -> list[lg.Event]:
            back = real(events)
            return back[:-1] + [lg.Event(back[-1].time, back[-1].key + "x", back[-1].event, back[-1].freshness, back[-1].disposition, back[-1].published, back[-1].detail)]

        with mock.patch.object(self.w.state, "build_events_new", side_effect=altered):
            code, text = self.cutover()
        self.assertEqual(code, 1, text)
        self.assertIn("read back", text)
        self.assertIn("checksum", text)
        self.assertEqual(self.sh.sheets[stm.EVENTS_TAB].values, original)
        self.assertEqual(self.renames(), [])

    def test_a_copy_that_would_not_pass_parity_refuses_before_any_rename(self) -> None:
        self.seeded_with_met_bar()
        original = [list(r) for r in self.sh.sheets[stm.EVENTS_TAB].values]
        real = compact.retained_events
        with mock.patch.object(compact, "retained_events", side_effect=lambda ledger, now: [e for e in real(ledger, now) if e.event != lg.ALERTED]):
            code, text = self.cutover()  # the copy and its read-back agree with each other, but it has lost the delivery records
        self.assertEqual(code, 1, text)
        self.assertIn("would-be state", text)
        self.assertEqual(self.sh.sheets[stm.EVENTS_TAB].values, original)
        self.assertEqual(self.renames(), [])

    def test_an_error_at_the_rename_exits_two_with_events_untouched(self) -> None:
        self.seeded_with_met_bar()
        original = [list(r) for r in self.sh.sheets[stm.EVENTS_TAB].values]
        with mock.patch.object(self.w.state, "swap_events", side_effect=RuntimeError("boom")):
            code, text = self.cutover()
        self.assertEqual(code, 2, text)
        self.assertNotIn("boom", text)  # the exception type only: the log is public
        self.assertEqual(self.sh.sheets[stm.EVENTS_TAB].values, original)
        self.assertEqual(self.storage().mode, compact.MODE_DUAL)

    def test_no_events_or_events_legacy_tab_is_ever_deleted(self) -> None:
        self.seeded_with_met_bar()
        self.sh.add_worksheet(stm.EVENTS_NEW_TAB, 10, 7)  # a scratch tab that the cutover may replace
        deleted: list[str] = []
        real = self.sh.del_worksheet
        with mock.patch.object(self.sh, "del_worksheet", side_effect=lambda ws: (deleted.append(ws.title), real(ws))[1]):
            self.assertEqual(self.cutover()[0], 0)
        self.assertEqual(deleted, [stm.EVENTS_NEW_TAB])


class InterruptedCutoverTests(CutoverCase):
    """A cutover interrupted after the rename but before the `storage` key was saved is finished by running it again (T-03-24)."""

    def interrupted(self) -> None:
        self.seeded_with_met_bar()
        self.sh.fail_on_write_to(stm.DISCOVERY_TAB, 1)  # the storage key is the first Discovery write of the command
        code, text = self.cutover()
        self.assertEqual(code, 2, text)
        self.assertIn("after the tab swap", text)
        self.assertIn(stm.EVENTS_LEGACY_TAB, self.sh.sheets)
        self.assertEqual(self.storage().mode, compact.MODE_DUAL)  # the key still says dual

    def test_the_next_poller_run_writes_as_dual_notes_it_is_degraded_and_records_no_check(self) -> None:
        self.interrupted()
        days_before = json.dumps(self.storage().days, sort_keys=True)
        zeta = bd.BoardId(bd.GREENHOUSE, "zeta")
        self.w.listings[zeta.key] = [job("zeta", "1"), job("zeta", "2")]
        run = self.poll(seeds=[zeta])
        self.assertIn("storage cutover incomplete: run storage_cutover again", run.notes)
        self.assertEqual(run.outcome, stm.OUTCOME_DEGRADED)
        self.assertIn("storage", pl.degraded_reason(run).split(","))
        self.assertEqual(json.dumps(self.storage().days, sort_keys=True), days_before)  # no check recorded
        baselined = {r[1] for r in self.sh.sheets[stm.EVENTS_TAB].values if r[2] == lg.SEEN and r[4] == lg.BASELINED}
        self.assertEqual(baselined, {"greenhouse|zeta|1", "greenhouse|zeta|2"})  # written to Events as well, as in dual mode
        self.assertEqual(self.w.state.load_ledger().identity.kind("greenhouse|zeta|1"), "b")

    def test_running_the_cutover_again_completes_the_record_without_copying_again(self) -> None:
        self.interrupted()
        self.poll_with_one_new_job()  # a run in the incomplete state wrote its own rows to the new Events
        events_before = [list(r) for r in self.sh.sheets[stm.EVENTS_TAB].values]
        legacy_before = [list(r) for r in self.sh.sheets[stm.EVENTS_LEGACY_TAB].values]
        batches = len(self.batches)
        code, text = self.cutover(now=self.w.now + timedelta(hours=1))
        self.assertEqual(code, 0, text)
        self.assertEqual(self.sh.sheets[stm.EVENTS_TAB].values, events_before)  # nothing copied or changed
        self.assertEqual(self.sh.sheets[stm.EVENTS_LEGACY_TAB].values, legacy_before)
        self.assertEqual([b for b in self.batches[batches:] if any("updateSheetProperties" in r for r in b["requests"])], [])  # no second rename
        state = self.storage()
        self.assertEqual(state.mode, compact.MODE_COMPACT)
        self.assertEqual(state.cutover["legacy_rows"], len(legacy_before) - 1)
        first_new = min(r[0] for r in events_before[1:] if r[2] == lg.SEEN and r[1] == "greenhouse|acme|99")
        self.assertEqual(state.cutover["at"], first_new)  # bounded by the first row written after the swap
        run = self.poll_with_one_new_job(minutes_later=60)
        self.assertEqual(run.outcome, stm.OUTCOME_OK, run.notes)
        self.assertNotIn("storage cutover incomplete", run.notes)
        self.assertEqual(len(self.w.alerts), 2)  # job 20 before the cutover and job 99; never twice

    def test_a_dry_run_of_the_second_attempt_changes_nothing(self) -> None:
        self.interrupted()
        before = self.snapshot()
        code, text = self.cutover(dry_run=True, now=NOW + timedelta(hours=1))
        self.assertEqual((code, self.snapshot()), (0, before), text)
        self.assertIn("finish the record", text)
        self.assertEqual(self.storage().mode, compact.MODE_DUAL)


class MissingLegacyTests(CutoverCase):
    def test_a_compact_key_without_events_legacy_writes_as_dual_notes_it_and_runs_no_check(self) -> None:
        self.seeded_with_met_bar()
        self.assertEqual(self.cutover()[0], 0)
        del self.sh.sheets[stm.EVENTS_LEGACY_TAB]  # the old tab is gone (renamed or removed by hand)
        days_before = json.dumps(self.storage().days, sort_keys=True)
        zeta = bd.BoardId(bd.GREENHOUSE, "zeta")
        self.w.listings[zeta.key] = [job("zeta", "1")]
        run = self.poll(seeds=[zeta])
        self.assertIn("storage state: compact without Events_Legacy, writing as dual", run.notes)
        self.assertEqual(run.outcome, stm.OUTCOME_DEGRADED)
        self.assertIn("storage", pl.degraded_reason(run).split(","))
        self.assertEqual(json.dumps(self.storage().days, sort_keys=True), days_before)
        self.assertIn("greenhouse|zeta|1", {r[1] for r in self.sh.sheets[stm.EVENTS_TAB].values if r[2] == lg.SEEN})  # the baseline row is in Events again

    def test_the_mode_decision_carries_the_note_and_still_compares_as_a_string(self) -> None:
        compact_json = json.dumps({"mode": "compact"})
        self.assertEqual(compact.effective_mode(compact_json, legacy_present=True), compact.MODE_COMPACT)
        self.assertEqual(compact.effective_mode(compact_json, legacy_present=True).note, "")
        gone = compact.effective_mode(compact_json, legacy_present=False)
        self.assertEqual((str(gone), gone.note), (compact.MODE_DUAL, compact.NOTE_COMPACT_WITHOUT_LEGACY))
        half = compact.effective_mode('{"mode":"dual"}', legacy_present=True)
        self.assertEqual((str(half), half.note), (compact.MODE_DUAL, compact.NOTE_CUTOVER_INCOMPLETE))
        self.assertEqual(compact.effective_mode('{"mode":"dual"}', legacy_present=False).note, "")
        self.assertEqual(compact.effective_mode('{"mode":"restored"}', legacy_present=False).note, "")
        self.assertEqual(compact.effective_mode(None, legacy_present=False), compact.MODE_DUAL)


class RestoreTests(CutoverCase):
    """`--storage-restore`: P3-06's reversibility made concrete. Renaming Events_Legacy back by hand would lose every row written after the cutover."""

    def setUp(self) -> None:
        super().setUp()
        self.seeded_with_met_bar()
        self.assertEqual(self.cutover()[0], 0)
        self.poll_with_one_new_job()  # job 99 is seen, evaluated and alerted after the cutover
        self.after_cutover = [list(r) for r in self.sh.sheets[stm.EVENTS_TAB].values]
        self.legacy = [list(r) for r in self.sh.sheets[stm.EVENTS_LEGACY_TAB].values]
        self.alerts = len(self.w.alerts)

    def restore(self, *, dry_run: bool = False) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = h.run_storage_restore(self.store, settings(), dry_run=dry_run, now=self.w.now + timedelta(minutes=5))
        return code, out.getvalue()

    def refused(self, *needles: str) -> None:
        before = self.snapshot()
        code, text = self.restore()
        self.assertEqual(code, 1, text)
        for needle in needles:
            self.assertIn(needle, text)
        self.assertEqual(self.snapshot(), before)

    def test_a_restore_before_any_fold_keeps_the_old_ledger_and_every_post_cutover_row(self) -> None:
        code, text = self.restore()
        self.assertEqual(code, 0, text)
        post = self.after_cutover[len(self.after_cutover) - 3 :]
        self.assertEqual([r[2] for r in post], [lg.SEEN, lg.EVALUATED, lg.ALERTED])
        self.assertEqual(self.sh.sheets[stm.EVENTS_TAB].values, self.legacy + post)  # the old ledger, then what was written after the cutover
        self.assertEqual(self.sh.sheets[stm.EVENTS_FAILED_TAB].values, self.after_cutover)  # the compact tab is kept
        self.assertNotIn(stm.EVENTS_LEGACY_TAB, self.sh.sheets)
        state = self.storage()
        self.assertEqual(state.mode, compact.MODE_RESTORED)
        self.assertEqual(state.restore["appended_rows"], 3)
        self.assertEqual(state.cutover["legacy_rows"], len(self.legacy) - 1)  # the cutover record stays
        self.assertEqual(len(self.published), 2)  # the Dashboard was refreshed again
        for batch in self.batches:
            for request in batch["requests"]:
                self.assertNotIn("deleteDimension", request)

    def test_after_a_restore_a_poller_run_sees_nothing_old_as_new_and_sends_no_second_alert(self) -> None:
        self.assertEqual(self.restore()[0], 0)
        days_before = json.dumps(self.storage().days, sort_keys=True)
        rows_before = len(self.sh.sheets[stm.EVENTS_TAB].values)
        run = self.poll_with_one_new_job(minutes_later=60)
        self.assertEqual(run.outcome, stm.OUTCOME_OK, run.notes)
        self.assertEqual(len(self.w.alerts), self.alerts)  # job 99 was alerted after the cutover: no second alert
        self.assertEqual(self.sh.sheets[stm.EVENTS_TAB].values[rows_before:], [])  # nothing at all was observed again
        self.assertEqual(json.dumps(self.storage().days, sort_keys=True), days_before)  # restored mode records no check

    def test_in_restored_mode_every_observation_is_written_to_events_again(self) -> None:
        self.assertEqual(self.restore()[0], 0)
        zeta = bd.BoardId(bd.GREENHOUSE, "zeta")
        self.w.listings[zeta.key] = [job("zeta", "1"), job("zeta", "2")]
        run = self.poll(60, new_jobs=("99",), seeds=[zeta])
        self.assertEqual(run.outcome, stm.OUTCOME_OK, run.notes)
        baselined = {r[1] for r in self.sh.sheets[stm.EVENTS_TAB].values if r[2] == lg.SEEN and r[4] == lg.BASELINED}
        self.assertIn("greenhouse|zeta|1", baselined)  # a baseline has its Events row again
        self.assertEqual(self.w.state.load_ledger().identity.kind("greenhouse|zeta|2"), "b")  # and Identity and Tally are still written
        self.assertEqual(self.w.state.load_ledger().tally[-1].total, 2)

    def test_a_restore_after_the_first_fold_refuses_and_says_a_replay_is_needed(self) -> None:
        self.set_storage(lambda s: s.fold.update({"first_day": "2026-10-19", "last_day": "2026-10-19"}))
        self.refused("fold", "replay", "Events_Legacy")

    def test_a_restore_needs_a_finished_cutover(self) -> None:
        self.set_storage(lambda s: setattr(s, "mode", compact.MODE_DUAL))
        self.refused("effective storage mode")
        self.set_storage(lambda s: setattr(s, "mode", compact.MODE_RESTORED))
        self.refused("effective storage mode")

    def test_a_restore_without_events_legacy_refuses(self) -> None:
        del self.sh.sheets[stm.EVENTS_LEGACY_TAB]
        self.refused("effective storage mode", "Events_Legacy")

    def test_a_dry_run_prints_the_plan_and_writes_nothing(self) -> None:
        before = self.snapshot()
        code, text = self.restore(dry_run=True)
        self.assertEqual((code, self.snapshot()), (0, before), text)
        self.assertIn("dry run; nothing was written", text)
        self.assertIn("3 Events rows", text)

    def test_a_restore_interrupted_before_the_rename_is_repeated_without_duplicating_rows(self) -> None:
        with mock.patch.object(self.w.state, "swap_events", side_effect=RuntimeError("boom")):
            code, text = self.restore()
        self.assertEqual(code, 2, text)
        self.assertEqual(self.storage().mode, compact.MODE_COMPACT)
        self.assertEqual(len(self.sh.sheets[stm.EVENTS_LEGACY_TAB].values), len(self.legacy) + 3)  # the rows were appended, nothing renamed
        self.assertEqual(self.sh.sheets[stm.EVENTS_TAB].values, self.after_cutover)
        code, text = self.restore()
        self.assertEqual(code, 0, text)
        self.assertEqual(len(self.sh.sheets[stm.EVENTS_TAB].values), len(self.legacy) + 3)  # the second attempt appended nothing again
        self.assertEqual(self.storage().mode, compact.MODE_RESTORED)

    def test_a_restore_whose_record_was_not_saved_is_finished_by_running_it_again(self) -> None:
        self.sh.fail_on_write_to(stm.DISCOVERY_TAB, 1)
        code, text = self.restore()
        self.assertEqual(code, 2, text)
        self.assertIn("after the tab swap", text)
        self.assertNotIn(stm.EVENTS_LEGACY_TAB, self.sh.sheets)
        self.assertEqual(self.storage().mode, compact.MODE_COMPACT)  # the key still says compact: the next run writes as dual and says so
        events = [list(r) for r in self.sh.sheets[stm.EVENTS_TAB].values]
        code, text = self.restore()
        self.assertEqual(code, 0, text)
        self.assertEqual(self.storage().mode, compact.MODE_RESTORED)
        self.assertEqual(self.sh.sheets[stm.EVENTS_TAB].values, events)  # no rows touched

    def test_a_cutover_refuses_in_restored_mode(self) -> None:
        self.assertEqual(self.restore()[0], 0)
        before = self.snapshot()
        code, text = self.cutover(now=self.w.now + timedelta(hours=1))
        self.assertEqual((code, self.snapshot()), (1, before), text)
        self.assertIn("restored", text)


class DispatchTests(unittest.TestCase):
    """`main` wiring: the poller lease, the local write refusal (D-37) and the flags. Mocked store; nothing is read or written."""

    def run_main(self, argv: list[str], *, actions: bool) -> tuple[int, mock.Mock, mock.Mock, mock.Mock]:
        fake = mock.Mock()
        fake.state = mock.Mock()
        fake.state.acquire_lease.return_value = mock.Mock(ok=True, token="t")
        fake.state.holds_lease.return_value = True
        fake.load_settings.return_value = {}
        fake.sheet_timezone.return_value = None
        env = {"GOOGLE_SHEET_ID": "sheet", "GOOGLE_SERVICE_ACCOUNT_JSON": "{}", "GROQ_API_KEY": "", "GITHUB_ACTIONS": "true" if actions else "", "ALLOW_LOCAL_SHEET_WRITES": ""}
        with mock.patch.dict("os.environ", env), mock.patch.object(h, "make_store", return_value=fake), mock.patch.object(h, "load_resume_file", return_value=""), \
                mock.patch.object(h, "run_storage_cutover", return_value=0) as cutover, mock.patch.object(h, "run_storage_restore", return_value=0) as restore:  # fmt: skip
            code = h.main(argv)
        return code, cutover, restore, fake

    def test_a_local_run_that_writes_is_refused_and_a_local_dry_run_is_not(self) -> None:
        for flag, which in (("--storage-cutover", 1), ("--storage-restore", 2)):
            with self.subTest(flag):
                code, *runners, fake = self.run_main([flag], actions=False)
                self.assertEqual(code, 4)
                for runner in runners:
                    runner.assert_not_called()
                fake.state.acquire_lease.assert_not_called()
                code, *runners, fake = self.run_main([flag, "--dry-run"], actions=False)
                self.assertEqual(code, 0)
                runners[which - 1].assert_called_once()
                self.assertTrue(runners[which - 1].call_args.kwargs["dry_run"])
                fake.state.acquire_lease.assert_not_called()  # a dry run takes no lease

    def test_in_actions_each_command_runs_under_the_poller_lease_without_a_groq_key(self) -> None:
        for flag, which in (("--storage-cutover", 0), ("--storage-restore", 1)):
            with self.subTest(flag):
                code, cutover, restore, fake = self.run_main([flag], actions=True)
                self.assertEqual(code, 0)
                runner = (cutover, restore)[which]
                runner.assert_called_once()
                self.assertFalse(runner.call_args.kwargs["dry_run"])
                self.assertEqual(fake.state.acquire_lease.call_args.args[0], "poller")  # no new LEASE_TTL label
                fake.state.release_lease.assert_called_once_with("t")

    def test_both_flags_together_are_rejected(self) -> None:
        with self.assertRaises(SystemExit) as caught:
            self.run_main(["--storage-cutover", "--storage-restore"], actions=True)
        self.assertEqual(caught.exception.code, 2)

    def test_the_lease_ttl_table_has_no_new_label(self) -> None:
        self.assertEqual(sorted(h.LEASE_TTL), ["inventory", "poller"])


if __name__ == "__main__":
    unittest.main()
