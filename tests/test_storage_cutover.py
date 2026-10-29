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
import freshness as fr  # noqa: E402
import hunter as h  # noqa: E402
import ledger as lg  # noqa: E402
import parity  # noqa: E402
import pipeline as pl  # noqa: E402
import reporting as rp  # noqa: E402
import state as stm  # noqa: E402
import storage_report  # noqa: E402
from fake_sheets import FakeSpreadsheet  # noqa: E402
from test_core import Harness, ago, job  # noqa: E402
from test_hunter import settings  # noqa: E402
from test_storage_pipeline import historical_ledger, history_event  # noqa: E402

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
    def ledger(self) -> list[lg.Event]:
        return historical_ledger()

    def seed_dual(self) -> None:
        """The historical ledger, the seed run (which also evaluates and alerts the one pending job) and one checked run."""
        self.w.state.append_events(self.ledger())
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


FOLD_DAY = datetime(2026, 10, 19, 0, 0, 0, tzinfo=timezone.utc)  # the first UTC day after the cutover's (2026-10-18): the 7-day cut is 2026-10-12T00:00:00Z
FOLDED = {"greenhouse|acme|10", "greenhouse|acme|30", "greenhouse|acme|31", "greenhouse|acme|32"}  # at or before the cut on FOLD_DAY (job 10: 2026-10-11T12:00)


def fold_ledger() -> list[lg.Event]:
    """The historical ledger plus gated and operational rows around the 7-day boundary of FOLD_DAY (the ledger spans 2026-09-28 .. 2026-10-14)."""
    old = "2026-10-11T10:00:00Z"
    return historical_ledger() + [
        history_event("greenhouse|acme|40", "2026-09-28T08:00:00Z", lg.FILTERED, "run-f0"),  # 20 days before the cutover: already gone at the cutover
        history_event("greenhouse|acme|30", old, lg.FILTERED, "run-f1", published="2026-10-11T08:00:00Z"),
        history_event("greenhouse|acme|31", "2026-10-11T23:59:59Z", lg.STALED, "run-f2", published="2026-08-01T00:00:00Z"),
        history_event("greenhouse|acme|32", "2026-10-12T00:00:00Z", lg.FILTERED, "run-f3"),  # exactly 7 x 24 h before FOLD_DAY
        history_event("greenhouse|acme|33", "2026-10-12T00:00:01Z", lg.FILTERED, "run-f4"),  # one second younger
        history_event("greenhouse|acme|34", old, lg.PENDING, "run-f1"),  # an operational job older than 7 days, finished: never folded
        lg.Event(old, "greenhouse|acme|34", lg.EVALUATED, fr.VERIFIED_FRESH, detail={"status": "To Apply", "alert": True, "run": "run-f1"}),
        lg.Event(old, "greenhouse|acme|34", lg.ALERTED, detail={"channel": "telegram", "run": "run-f1"}),
    ]  # fmt: skip


def ledger_of(events: list[lg.Event], rows: list[int] | None = None) -> compact.Ledger:
    """A Ledger whose Identity and Tally hold exactly what the seed would write for these Events rows (pure: no store)."""
    numbers = rows or list(range(2, len(events) + 2))
    plan = compact.repair_plan(compact.Ledger(events, numbers, compact.IdentitySet(), []))
    identity = compact.IdentitySet()
    identity.apply(identity.plan_additions(plan.identity, "2026-10-10T00:00:00Z"))
    return compact.Ledger(events, numbers, identity, plan.tally)


class FoldPlanTests(unittest.TestCase):
    """`compact.fold_plan`, `delete_ranges`, `fold_record` and `StorageState.fold_due`: pure (P3-03)."""

    NOW = datetime(2026, 10, 19, 0, 0, 0, tzinfo=timezone.utc)

    def rows(self, ledger: compact.Ledger) -> list[int]:
        return compact.fold_plan(ledger, self.NOW).rows

    def test_a_gated_row_exactly_seven_days_old_is_selected_and_one_a_second_younger_is_not(self) -> None:
        ledger = ledger_of([
            history_event("greenhouse|a|1", "2026-10-12T00:00:00Z", lg.FILTERED, "r1"),
            history_event("greenhouse|a|2", "2026-10-12T00:00:01Z", lg.FILTERED, "r2"),
            history_event("greenhouse|a|3", "2026-10-11T23:59:59Z", lg.STALED, "r3"),
        ])  # fmt: skip
        self.assertEqual(self.rows(ledger), [2, 4])

    def test_baselines_operational_rows_and_unkeyable_rows_are_never_selected(self) -> None:
        old = "2026-09-01T00:00:00Z"
        ledger = ledger_of([
            history_event("greenhouse|a|1", old, lg.BASELINED, "r1"),
            history_event("greenhouse|a|2", old, lg.PENDING, "r1"),
            history_event("greenhouse|a", old, lg.FILTERED, "r1"),  # fewer than three segments: always stays
            lg.Event(old, "greenhouse|a|2", lg.ALERTED, detail={"run": "r1"}),
        ])  # fmt: skip
        plan = compact.fold_plan(ledger, self.NOW)
        self.assertEqual((plan.rows, plan.skipped), ([], 0))

    def test_every_seen_row_of_a_selected_key_goes_and_the_other_rows_of_the_key_stay(self) -> None:
        old = "2026-10-01T00:00:00Z"
        ledger = ledger_of([
            history_event("greenhouse|a|1", old, lg.FILTERED, "r1"),
            lg.Event(old, "greenhouse|a|1", lg.ERROR, detail={"stage": "evaluate", "run": "r1"}),
            history_event("greenhouse|a|1", "2026-10-02T00:00:00Z", lg.FILTERED, "r2"),  # a duplicate seen row
        ])  # fmt: skip
        self.assertEqual(self.rows(ledger), [2, 4])

    def test_rows_are_sheet_row_numbers_and_an_unreadable_row_advances_the_count(self) -> None:
        old = "2026-10-01T00:00:00Z"
        events = [history_event("greenhouse|a|1", old, lg.FILTERED, "r1"), history_event("greenhouse|a|2", old, lg.FILTERED, "r1")]
        plan = compact.fold_plan(ledger_of(events, [2, 5]), self.NOW)  # sheet rows 3 and 4 hold rows no reader parses
        self.assertEqual((plan.rows, plan.row_keys), ([2, 5], {2: "greenhouse|a|1", 5: "greenhouse|a|2"}))

    def test_a_posting_id_missing_from_identity_keeps_its_rows_and_is_counted(self) -> None:
        old = "2026-10-01T00:00:00Z"
        events = [history_event("greenhouse|a|1", old, lg.FILTERED, "r1"), history_event("greenhouse|a|2", old, lg.FILTERED, "r1")]
        full = ledger_of(events)
        identity = compact.IdentitySet()
        identity.apply(identity.plan_additions({"greenhouse|a": [compact.encode_entry("f", "2")]}, "2026-10-10T00:00:00Z"))
        plan = compact.fold_plan(compact.Ledger(events, full.event_rows, identity, full.tally), self.NOW)
        self.assertEqual((plan.rows, plan.skipped_not_in_identity, plan.skipped_no_tally), ([3], 1, 0))

    def test_a_missing_or_short_tally_group_keeps_the_rows_and_is_counted(self) -> None:
        old = "2026-10-01T00:00:00Z"
        events = [history_event("greenhouse|a|1", old, lg.FILTERED, "r1"), history_event("greenhouse|a|2", old, lg.FILTERED, "r2")]
        full = ledger_of(events)
        missing = compact.Ledger(events, full.event_rows, full.identity, [t for t in full.tally if t.run_id != "r1"])
        self.assertEqual((compact.fold_plan(missing, self.NOW).rows, compact.fold_plan(missing, self.NOW).skipped_no_tally), ([3], 1))
        short = compact.Ledger(events, full.event_rows, full.identity, [compact.TallyRow(t.run_id, t.run_at, 0, {}) if t.run_id == "r2" else t for t in full.tally])
        plan = compact.fold_plan(short, self.NOW)
        self.assertEqual((plan.rows, plan.skipped_no_tally), ([2], 1))

    def test_a_ledger_without_row_numbers_is_refused(self) -> None:
        events = [history_event("greenhouse|a|1", "2026-10-01T00:00:00Z", lg.FILTERED, "r1")]
        with self.assertRaises(ValueError):
            compact.fold_plan(compact.Ledger(events, [], compact.IdentitySet(), []), self.NOW)

    def test_delete_ranges_are_contiguous_inclusive_and_highest_first(self) -> None:
        self.assertEqual(compact.delete_ranges([]), [])
        self.assertEqual(compact.delete_ranges([5]), [(5, 5)])
        self.assertEqual(compact.delete_ranges([2, 3, 4, 9, 10, 20]), [(20, 20), (9, 10), (2, 4)])
        self.assertEqual(compact.delete_ranges([10, 3, 9, 3, 2]), [(9, 10), (2, 3)])  # unsorted and repeated input

    def test_the_fold_record_sets_first_day_once_and_only_when_a_row_went(self) -> None:
        one = compact.fold_record({}, datetime(2026, 10, 19, 5, tzinfo=timezone.utc), rows=0, skipped=2)
        self.assertEqual(one, {"last_day": "2026-10-19", "last_rows": 0, "last_skipped": 2, "rows_total": 0})  # nothing deleted: the restore stays possible
        two = compact.fold_record(one, datetime(2026, 10, 20, 5, tzinfo=timezone.utc), rows=7, skipped=0)
        self.assertEqual(two, {"first_day": "2026-10-20", "last_day": "2026-10-20", "last_rows": 7, "last_skipped": 0, "rows_total": 7})
        three = compact.fold_record(two, datetime(2026, 10, 21, 5, tzinfo=timezone.utc), rows=3, skipped=1)
        self.assertEqual((three["first_day"], three["rows_total"]), ("2026-10-20", 10))

    def test_a_fold_is_due_only_in_compact_mode_after_the_cutover_day_and_once_a_day(self) -> None:
        state = compact.StorageState(mode=compact.MODE_COMPACT, cutover={"at": "2026-10-18T09:00:00Z"})
        self.assertFalse(state.fold_due(datetime(2026, 10, 18, 23, 59, 59, tzinfo=timezone.utc)))  # the cutover's own UTC day
        self.assertTrue(state.fold_due(datetime(2026, 10, 19, 0, 0, 0, tzinfo=timezone.utc)))
        state.fold = {"last_day": "2026-10-19"}
        self.assertFalse(state.fold_due(datetime(2026, 10, 19, 23, 0, 0, tzinfo=timezone.utc)))
        self.assertTrue(state.fold_due(datetime(2026, 10, 20, 0, 0, 0, tzinfo=timezone.utc)))
        for mode in (compact.MODE_DUAL, compact.MODE_RESTORED):
            self.assertFalse(compact.StorageState(mode=mode, cutover={"at": "2026-10-18T09:00:00Z"}).fold_due(FOLD_DAY + timedelta(days=3)))
        self.assertFalse(compact.StorageState(mode=compact.MODE_COMPACT).fold_due(FOLD_DAY))  # no cutover time: never


class FoldStoreTests(unittest.TestCase):
    """`fold_events` in the Sheet store (descending `deleteDimension` batches of at most 500 requests) and in the local file store."""

    def sheet_with(self, n: int) -> tuple[FakeSpreadsheet, stm.SheetState, list[dict[str, Any]]]:
        sh = FakeSpreadsheet()
        state = stm.SheetState(sh)
        state.ensure()
        state.append_events([lg.Event(f"2026-10-01T00:{i // 60:02d}:{i % 60:02d}Z", f"greenhouse|a|{i}", lg.SEEN if i % 2 else lg.ALERTED) for i in range(n)])
        batches: list[dict[str, Any]] = []
        real = sh.batch_update
        sh.batch_update = lambda body: (batches.append(body), real(body))[1]  # type: ignore[method-assign]
        return sh, state, batches

    def test_ranges_go_out_highest_first_in_batches_of_at_most_500_requests(self) -> None:
        sh, state, batches = self.sheet_with(2603)
        seen_rows = [r for r in range(2, 2605) if sh.sheets[stm.EVENTS_TAB].values[r - 1][2] == lg.SEEN]  # every other row: 1,301 single-row ranges
        before = [list(r) for r in sh.sheets[stm.EVENTS_TAB].values]
        self.assertEqual(state.fold_events(seen_rows, {n: before[n - 1][1] for n in seen_rows}), len(seen_rows))
        self.assertEqual([len(b["requests"]) for b in batches], [500, 500, len(seen_rows) - 1000])
        starts = [r["deleteDimension"]["range"]["startIndex"] for b in batches for r in b["requests"]]
        self.assertEqual(starts, sorted(starts, reverse=True))
        self.assertTrue(all(r["deleteDimension"]["range"]["sheetId"] == sh.sheets[stm.EVENTS_TAB].id for b in batches for r in b["requests"]))
        self.assertEqual(sh.sheets[stm.EVENTS_TAB].values, [row for n, row in enumerate(before, start=1) if n not in set(seen_rows)])

    def test_a_row_that_no_longer_holds_the_planned_key_refuses_before_any_delete(self) -> None:
        sh, state, batches = self.sheet_with(10)
        before = [list(r) for r in sh.sheets[stm.EVENTS_TAB].values]
        writes = sh.writes
        wrong = {3: before[2][1], 5: "greenhouse|a|999"}  # row 5 was shifted: it holds another key
        with self.assertRaises(RuntimeError):
            state.fold_events([3, 5], wrong)
        self.assertEqual((sh.sheets[stm.EVENTS_TAB].values, sh.writes, batches), (before, writes, []))
        with self.assertRaises(RuntimeError):  # a planned `seen` row that is now another kind of row
            state.fold_events([2], {2: before[1][1]})
        self.assertEqual(batches, [])

    def test_nothing_to_fold_sends_nothing(self) -> None:
        sh, state, batches = self.sheet_with(4)
        self.assertEqual(state.fold_events([]), 0)
        self.assertEqual(batches, [])

    def test_the_csv_store_rewrites_events_without_the_rows_and_checks_them_first(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = stm.CsvState(Path(tmp) / "state")
            state.ensure()
            state.append_events([lg.Event(f"2026-10-01T00:00:{i:02d}Z", f"greenhouse|a|{i}", lg.SEEN) for i in range(6)])
            keep = [list(r) for r in state._rows(stm.EVENTS_TAB)]
            with self.assertRaises(RuntimeError):
                state.fold_events([3, 5], {3: "greenhouse|a|1", 5: "greenhouse|a|WRONG"})
            self.assertEqual(state._rows(stm.EVENTS_TAB), keep)
            self.assertEqual(state.fold_events([3, 5], {3: "greenhouse|a|1", 5: "greenhouse|a|3"}), 2)
            self.assertEqual([r[1] for r in state._rows(stm.EVENTS_TAB)], ["greenhouse|a|0", "greenhouse|a|2", "greenhouse|a|4", "greenhouse|a|5"])
            self.assertEqual(len(list(Path(tmp, "state").glob("*.tmp"))), 0)


class FoldCase(CutoverCase):
    """A dual-mode state seeded from `fold_ledger()` (gated and operational rows around the 7-day boundary of FOLD_DAY) and the helpers to read it."""

    def ledger(self) -> list[lg.Event]:
        return fold_ledger()

    def events(self) -> list[list[str]]:
        return [list(r) for r in self.sh.sheets[stm.EVENTS_TAB].values]

    # -- helpers
    def run_at(self, at: datetime, **kw: Any) -> pl.RunRecord:
        """One poller run whose clock reads exactly `at` (the board lists the old jobs and nothing new)."""
        self.w.now = at
        self.w.listings[self.board.key] = [job("acme", i) for i in OLD_IDS]
        return self.w.run(**kw)

    def deletes(self, since: int = 0) -> list[dict[str, Any]]:
        return [b for b in self.batches[since:] if any("deleteDimension" in r for r in b["requests"])]

    def rows_of(self, values: list[list[str]], keys: set[str]) -> list[int]:
        return [n for n, r in enumerate(values, start=1) if n > 1 and r[2] == lg.SEEN and r[1] in keys]

    def seen_keys(self) -> set[str]:
        return {r[1] for r in self.sh.sheets[stm.EVENTS_TAB].values[1:] if r[2] == lg.SEEN}

    def edit_identity(self, drop: str) -> None:
        row = next(r for r in self.sh.sheets[stm.IDENTITY_TAB].values[1:] if r[0] == "greenhouse|acme")
        kept = [e for e in row[4].split(",") if e != drop]
        row[3], row[4] = str(len(kept)), ",".join(kept)  # the Count column follows, as it would after a clean removal

    def edit_tally(self, run_id: str, edit: Any) -> None:
        for row in self.sh.sheets[stm.TALLY_TAB].values[1:]:
            if row[0] == run_id:
                edit(row)


class FoldBeforeCutoverTests(FoldCase):
    """P3-03: before the cutover nothing is ever deleted (dual mode keeps every row, however old)."""

    def test_in_dual_mode_nothing_is_ever_deleted_however_old_the_rows_are(self) -> None:
        self.seeded_with_met_bar()
        before = self.events()
        self.assertIn("greenhouse|acme|40", {r[1] for r in before[1:]})  # a 20-day-old gated row is still a row of Events
        for day in range(1, 4):
            run = self.run_at(NOW + timedelta(days=day))
            self.assertNotIn("storage fold", run.notes)
        self.assertEqual(self.deletes(), [])
        self.assertEqual(self.events()[: len(before)], before)
        self.assertEqual(self.storage().fold, {})


class FoldTests(FoldCase):
    """The tracer (plan 03-07): the first compact-mode run of the UTC day after the cutover folds the week-old gated rows that are durable in
    Identity and Tally with one descending batch, and every figure stays the same. MOCKED: the Sheets fake interprets `deleteDimension`."""

    def setUp(self) -> None:
        super().setUp()
        self.seeded_with_met_bar()
        self.assertEqual(self.cutover()[0], 0)
        self.legacy = [list(r) for r in self.sh.sheets[stm.EVENTS_LEGACY_TAB].values]
        self.before = self.events()

    # -- the tracer
    def test_the_ledger_has_the_rows_the_fold_cases_need(self) -> None:
        for key in sorted(FOLDED | {"greenhouse|acme|33", "greenhouse|acme|34"}):
            self.assertIn(key, {r[1] for r in self.before[1:]}, key)
        self.assertNotIn("greenhouse|acme|40", self.seen_keys())  # 20 days old at the cutover: left Events then, not now

    def test_a_run_on_the_cutover_day_folds_nothing_even_at_the_last_second(self) -> None:
        for at in (NOW + timedelta(minutes=30), datetime(2026, 10, 18, 23, 59, 59, tzinfo=timezone.utc)):
            run = self.run_at(at)
            self.assertEqual(run.outcome, stm.OUTCOME_OK, run.notes)
            self.assertNotIn("storage fold", run.notes)
        self.assertEqual(self.deletes(), [])
        self.assertEqual(self.events()[: len(self.before)], self.before)
        self.assertEqual(self.storage().fold, {})

    def test_the_first_run_of_the_next_utc_day_deletes_exactly_the_old_gated_rows_in_one_descending_batch(self) -> None:
        expected = self.rows_of(self.before, FOLDED)
        self.assertEqual(len(expected), 4)
        batches = len(self.batches)
        run = self.run_at(FOLD_DAY)  # 00:00:00 UTC on the day after the cutover
        self.assertEqual(run.outcome, stm.OUTCOME_OK, run.notes)
        sent = self.batches[batches:]
        self.assertEqual([b for b in sent if not all("deleteDimension" in r for r in b["requests"])], [])  # nothing but the delete batch: no rename, no protection
        self.assertEqual(len(sent), 1)  # one spreadsheet batch
        ranges = [r["deleteDimension"]["range"] for r in sent[0]["requests"]]
        self.assertGreaterEqual(len(ranges), 2)  # more than one range, so the order matters
        self.assertTrue(all(r["dimension"] == "ROWS" and r["sheetId"] == self.sh.sheets[stm.EVENTS_TAB].id for r in ranges))
        self.assertEqual([r["startIndex"] for r in ranges], sorted((r["startIndex"] for r in ranges), reverse=True))  # descending
        self.assertEqual(sorted(n for r in ranges for n in range(r["startIndex"] + 1, r["endIndex"] + 1)), expected)
        kept = [r for n, r in enumerate(self.before, start=1) if n not in set(expected)]
        self.assertEqual(self.events()[: len(kept)], kept)  # everything else, in its order: operational rows included
        self.assertEqual(self.sh.sheets[stm.EVENTS_LEGACY_TAB].values, self.legacy)  # the old ledger is never touched
        self.assertTrue({"greenhouse|acme|34"} <= {r[1] for r in self.sh.sheets[stm.EVENTS_TAB].values if r[2] == lg.ALERTED})
        self.assertIn("storage fold: 4 rows (0 kept: not durable yet); ", run.notes)

    def test_the_fold_record_is_saved_and_a_second_run_the_same_day_does_not_fold(self) -> None:
        self.run_at(FOLD_DAY)
        self.assertEqual(self.storage().fold, {"first_day": "2026-10-19", "last_day": "2026-10-19", "last_rows": 4, "last_skipped": 0, "rows_total": 4})
        batches = len(self.batches)
        after_first = self.events()
        run = self.run_at(FOLD_DAY + timedelta(hours=11, minutes=59))
        self.assertEqual(self.deletes(batches), [])
        self.assertNotIn("storage fold", run.notes)
        self.assertEqual(self.events()[: len(after_first)], after_first)
        self.assertEqual(self.storage().fold["rows_total"], 4)
        self.run_at(FOLD_DAY + timedelta(days=1))  # the next UTC day folds again: the cut moved to 2026-10-13T00:00:00Z, so jobs 11, 12 and 33 are old enough
        self.assertEqual(len(self.deletes(batches)), 1)
        self.assertEqual(self.storage().fold, {"first_day": "2026-10-19", "last_day": "2026-10-20", "last_rows": 3, "last_skipped": 0, "rows_total": 7})
        self.assertEqual({"greenhouse|acme|11", "greenhouse|acme|12", "greenhouse|acme|33"} & self.seen_keys(), set())

    def test_a_filtered_row_exactly_seven_days_old_is_folded_and_one_a_second_younger_is_kept(self) -> None:
        self.run_at(FOLD_DAY)
        keys = self.seen_keys()
        self.assertNotIn("greenhouse|acme|32", keys)  # 2026-10-12T00:00:00Z: exactly 7 x 24 h before 2026-10-19T00:00:00Z
        self.assertIn("greenhouse|acme|33", keys)  # 2026-10-12T00:00:01Z
        self.assertTrue({"greenhouse|acme|11", "greenhouse|acme|12"} <= keys)  # the two jobs of 2026-10-12T12:00 stay

    def test_the_folded_ids_stay_in_identity_and_their_counts_stay_in_tally(self) -> None:
        tally = [list(r) for r in self.sh.sheets[stm.TALLY_TAB].values]
        identity = [list(r) for r in self.sh.sheets[stm.IDENTITY_TAB].values]
        self.run_at(FOLD_DAY)
        self.assertEqual(self.sh.sheets[stm.TALLY_TAB].values[: len(tally)], tally)  # nothing of Tally was touched (the run only appended its own row)
        self.assertEqual(self.sh.sheets[stm.IDENTITY_TAB].values[: len(identity)], identity)
        ledger = self.w.state.load_ledger()
        self.assertTrue(FOLDED <= ledger.identity.keys())
        folded = {f.run_id for f in ledger.folded()}
        self.assertTrue({"run-f1", "run-f2", "run-f3"} <= folded)  # their counts are now served from Tally
        self.assertNotIn("run-f4", folded)  # job 33 is still a row of Events: nothing is counted twice

    def test_every_dashboard_figure_is_the_same_before_and_after_the_fold(self) -> None:
        runs, boards, discovery = self.w.state.load_runs(), self.w.state.load_boards(), self.w.state.load_discovery_state()
        at = FOLD_DAY + timedelta(hours=1)

        def figures() -> tuple[dict[str, Any], dict[str, Any], int]:
            ledger = self.w.state.load_ledger()
            summary = rp.build_summary(now=at, runs=runs, events=ledger.events, folded=ledger.folded(), boards=boards, discovery=discovery, tracker=[])
            logical = storage_report.logical_counts(ledger.events, folded=ledger.folded(), identity=ledger.identity)
            return summary, logical, sum(f.n for f in ledger.folded())

        summary, logical, folded = figures()
        self.run_at(FOLD_DAY)
        summary2, logical2, folded2 = figures()
        self.assertEqual(folded2, folded + 4)  # the four jobs are now counted from Tally
        self.assertEqual(parity.compare_figures(summary, summary2), [])
        self.assertEqual(parity.compare_figures(logical, logical2, skip=()), [])

    def test_a_half_folded_run_counts_each_job_once_and_the_next_run_finishes_it(self) -> None:
        runs, boards, discovery = self.w.state.load_runs(), self.w.state.load_boards(), self.w.state.load_discovery_state()
        at = FOLD_DAY + timedelta(hours=1)

        def figures() -> dict[str, Any]:
            ledger = self.w.state.load_ledger()
            return rp.build_summary(now=at, runs=runs, events=ledger.events, folded=ledger.folded(), boards=boards, discovery=discovery, tracker=[])

        whole = figures()
        real, calls = self.sh.batch_update, []

        def flaky(body: dict[str, Any]) -> dict[str, Any]:
            if any("deleteDimension" in r for r in body["requests"]):
                calls.append(body)
                if len(calls) == 2:
                    raise RuntimeError("injected failure after the first delete batch")
            return real(body)

        with mock.patch.object(compact, "FOLD_REQUESTS_PER_BATCH", 1), mock.patch.object(self.sh, "batch_update", side_effect=flaky):
            run = self.run_at(FOLD_DAY)
        self.assertEqual(len(calls), 2)
        self.assertIn("storage fold failed: RuntimeError; ", run.notes)
        self.assertEqual(run.outcome, stm.OUTCOME_DEGRADED)
        self.assertEqual(self.storage().fold, {})  # last_day unset: the next run tries again
        gone = FOLDED - self.seen_keys()
        self.assertTrue(0 < len(gone) < 4, gone)  # half of it happened
        self.assertEqual(parity.compare_figures(whole, figures()), [])  # each job still counted once
        batches = len(self.batches)
        run = self.run_at(FOLD_DAY)  # the same instant: the cut has not moved, so the plan is what is left of the same four jobs
        self.assertEqual(run.outcome, stm.OUTCOME_OK, run.notes)
        self.assertEqual(FOLDED & self.seen_keys(), set())
        self.assertEqual(len(self.deletes(batches)), 1)
        self.assertEqual(self.storage().fold["rows_total"], 4 - len(gone))
        self.assertEqual(parity.compare_figures(whole, figures()), [])

    # -- durability: a row is deleted only when its ID is in Identity and its count is in Tally, both as read at run start
    def test_a_row_whose_id_was_removed_from_identity_is_kept_and_counted_then_folded_the_next_day(self) -> None:
        self.edit_identity("f30")
        run = self.run_at(FOLD_DAY)
        self.assertIn("greenhouse|acme|30", self.seen_keys())  # kept: the start-of-run Identity did not hold it
        self.assertEqual(FOLDED - {"greenhouse|acme|30"}, FOLDED - self.seen_keys() - {"greenhouse|acme|30"})
        self.assertIn("storage fold: 3 rows (1 kept: not durable yet); ", run.notes)
        self.assertEqual((self.storage().fold["last_rows"], self.storage().fold["last_skipped"]), (3, 1))
        self.assertEqual(self.w.state.load_ledger().identity.kind("greenhouse|acme|30"), "f")  # the run's repair put it back, so tomorrow it is durable
        self.run_at(FOLD_DAY + timedelta(days=1))
        self.assertNotIn("greenhouse|acme|30", self.seen_keys())
        self.assertEqual(self.storage().fold["rows_total"], 3 + 4)  # day 1: three rows; day 2: job 30 and (the cut moved) jobs 11, 12 and 33

    def test_a_row_whose_tally_group_was_removed_is_kept_and_counted_then_folded_the_next_day(self) -> None:
        self.sh.sheets[stm.TALLY_TAB].values[:] = [r for r in self.sh.sheets[stm.TALLY_TAB].values if r[0] != "run-f2"]
        run = self.run_at(FOLD_DAY)
        self.assertIn("greenhouse|acme|31", self.seen_keys())
        self.assertIn("storage fold: 3 rows (1 kept: not durable yet); ", run.notes)
        self.run_at(FOLD_DAY + timedelta(days=1))  # the repair re-added the group at the start of the first run
        self.assertNotIn("greenhouse|acme|31", self.seen_keys())

    def test_a_row_whose_tally_count_is_below_what_events_retains_is_kept_every_day(self) -> None:
        def lower(row: list[str]) -> None:
            row[2], row[3] = "0", "{}"

        self.edit_tally("run-f1", lower)
        for day in range(2):
            run = self.run_at(FOLD_DAY + timedelta(days=day))
            self.assertIn("greenhouse|acme|30", self.seen_keys())
        self.assertEqual(self.storage().fold["last_skipped"], 1)

    # -- failures and deadlines
    def test_a_failed_fold_adds_the_note_degrades_the_run_leaves_last_day_unset_and_is_retried(self) -> None:
        with mock.patch.object(self.w.state, "fold_events", side_effect=RuntimeError("boom")):
            run = self.run_at(FOLD_DAY)
        self.assertIn("storage fold failed: RuntimeError; ", run.notes)
        self.assertNotIn("boom", run.notes)
        self.assertEqual(run.outcome, stm.OUTCOME_DEGRADED)
        self.assertEqual(stm.RunRecord.from_row(self.sh.sheets[stm.RUNS_TAB].values[-1]).outcome, stm.OUTCOME_DEGRADED)
        self.assertEqual(self.storage().fold, {})
        self.assertEqual(FOLDED - self.seen_keys(), set())
        run = self.run_at(FOLD_DAY)  # the same UTC day (and instant): it is still due
        self.assertEqual(run.outcome, stm.OUTCOME_OK, run.notes)
        self.assertEqual(self.storage().fold["rows_total"], 4)

    def test_a_run_past_the_fold_cutoff_skips_the_fold_and_leaves_last_day_unset(self) -> None:
        run = self.run_at(FOLD_DAY, clock=lambda: float(pl.FOLD_CUTOFF_S), process_t0=0.0)
        self.assertEqual(self.deletes(), [])
        self.assertNotIn("storage fold", run.notes)
        self.assertEqual(self.storage().fold, {})
        self.run_at(FOLD_DAY, clock=lambda: float(pl.FOLD_CUTOFF_S - 1), process_t0=0.0)  # a second before the cutoff
        self.assertEqual(self.storage().fold["rows_total"], 4)
        self.assertEqual(pl.FOLD_CUTOFF_S, 20 * 60)

    def test_a_dry_run_folds_nothing(self) -> None:
        self.run_at(FOLD_DAY, dry_run=True)
        self.assertEqual(self.deletes(), [])
        self.assertEqual(self.events(), self.before)

    # -- the modes: no fold in dual or restored mode, none for an unfinished state
    def test_in_restored_mode_nothing_is_ever_deleted(self) -> None:
        code = h.run_storage_restore(self.store, settings(), dry_run=False, now=NOW + timedelta(hours=2))
        self.assertEqual(code, 0)
        self.assertEqual(self.storage().mode, compact.MODE_RESTORED)
        before = self.events()
        for day in range(3):
            self.run_at(FOLD_DAY + timedelta(days=day))
        self.assertEqual(self.deletes(), [])
        self.assertEqual(self.events()[: len(before)], before)
        self.assertEqual(self.storage().fold, {})

    def test_a_compact_key_without_events_legacy_writes_as_dual_and_never_folds(self) -> None:
        del self.sh.sheets[stm.EVENTS_LEGACY_TAB]
        run = self.run_at(FOLD_DAY)
        self.assertIn(compact.NOTE_COMPACT_WITHOUT_LEGACY, run.notes)
        self.assertEqual(self.deletes(), [])
        self.assertEqual(self.storage().fold, {})

    def test_the_fold_notes_and_log_carry_counts_only(self) -> None:
        with self.assertLogs("hunter", level="INFO") as logs:
            run = self.run_at(FOLD_DAY)
        text = run.notes + "\n".join(logs.output)
        self.assertIn("Storage fold: 4 rows deleted", text)
        for forbidden in ("greenhouse|acme", "http", "Marketing"):
            self.assertNotIn(forbidden, run.notes + "\n".join(m for m in logs.output if "Storage fold" in m))


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
