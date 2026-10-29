"""Storage parity (D-57, P3-05 and P3-07): the named differences, the repair and the parity clock.

Mocked and offline (AGENTS rules 5 and 8): synthetic Events rows checked with the pure `parity.check_dual`, and the pipeline run
through the `Harness` of `tests/test_core.py` over the real CSV state in a temp directory. Nothing here touches Google Sheets,
Groq or Telegram; the real seed size and the check's seconds at about 200,000 rows are live observations for plan 03-05.
"""

from __future__ import annotations

import contextlib
import csv
import io
import json
import re
import sys
import unittest
from collections import defaultdict
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import compact  # noqa: E402
import freshness as fr  # noqa: E402
import hunter as h  # noqa: E402
import ledger as lg  # noqa: E402
import parity  # noqa: E402
import pipeline as pl  # noqa: E402
import reporting as rp  # noqa: E402
import state as stm  # noqa: E402
from test_core import T0, HarnessCase, ago, job  # noqa: E402
from test_hunter import settings  # noqa: E402
from test_storage_cutover import FOLD_DAY, FoldCase  # noqa: E402
from test_reporting import CHI, UTC, ZONES, compact_world  # noqa: E402
from test_storage_pipeline import history_event, read_csv, storage_of  # noqa: E402

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)


def at(**kw: float) -> str:
    return lg.stamp(NOW - timedelta(**kw))


class Synthetic:
    """A consistent dual-write world built the way the pipeline builds it: per run, `split_observations` gives the Identity
    entries and the Tally counts, so the stored side never comes from the code under test (`repair_plan`, `check_dual`)."""

    def __init__(self) -> None:
        events: list[lg.Event] = []

        def seen(key: str, when: str, disposition: str, run: str = "", **kw: object) -> None:
            events.append(history_event(key, when, disposition, run, **kw))  # type: ignore[arg-type]

        for i in range(1, 6):  # an admission wave: three boards baselined in one run (the mixed-case Lever board is keyed in lower case)
            seen(f"greenhouse|acme|{i}", at(days=9), lg.BASELINED, "wave")
        for i in range(1, 5):
            seen(f"greenhouse|globex|{i}", at(days=9), lg.BASELINED, "wave")
        seen("lever|foo|abc1", at(days=9), lg.BASELINED, "wave")
        seen("lever|foo|def2", at(days=9), lg.BASELINED, "wave")
        for day in (5, 4, 3, 2, 1):  # steady days: one run a day with gated and stale rows and an operational job
            seen(f"greenhouse|acme|f{day}", at(days=day), lg.FILTERED, f"steady-{day}", published=at(days=day, hours=2))
            seen(f"greenhouse|globex|s{day}", at(days=day), lg.STALED, f"steady-{day}", published=at(days=60))
            seen(f"greenhouse|acme|p{day}", at(days=day), lg.PENDING, f"steady-{day}", published=at(days=day, hours=1))
        events.append(lg.Event(at(days=1), "greenhouse|acme|p1", lg.EVALUATED, fr.VERIFIED_FRESH, detail={"status": "To Apply", "alert": True, "run": "steady-1"}))
        events.append(lg.Event(at(days=1), "greenhouse|acme|p2", lg.ERROR, detail={"stage": "evaluate", "attempt": 1, "run": "steady-2"}))
        seen("greenhouse|acme|r1", at(days=2, hours=3), lg.FILTERED, "rehearsal-1")  # a rehearsal run: its rows are ordinary ledger rows
        seen("greenhouse|acme|old1", at(days=12), lg.BASELINED)  # written before run ids existed
        seen("greenhouse|acme|old2", at(days=12), lg.STALED)
        events.sort(key=lambda e: e.time)
        self.events = events
        by_run: dict[tuple[str, str], list[lg.Event]] = defaultdict(list)
        for ev in events:
            by_run[(str(ev.detail.get("run") or ""), ev.time)].append(ev)
        identity = compact.IdentitySet()
        self.tally: list[compact.TallyRow] = []
        for (run_id, run_at), group in sorted(by_run.items(), key=lambda kv: (kv[0][1], kv[0][0])):
            split = compact.split_observations(group, compact.MODE_DUAL)
            identity.apply(identity.plan_additions(split.identity, "2026-10-12T00:00:00Z"))
            if split.tally:
                self.tally.append(compact.TallyRow(run_id, run_at, sum(split.tally.values()), dict(sorted(split.tally.items()))))
        self.rows = identity.all_rows()

    def check(self, *, rows: list[compact.IdentityRow] | None = None, tally: list[compact.TallyRow] | None = None, events: list[lg.Event] | None = None) -> parity.ParityReport:
        events = self.events if events is None else events
        ident = compact.IdentitySet.from_rows(self.rows if rows is None else rows)
        view = compact.Ledger(compact.simulate_compact(events, NOW), [], ident, self.tally if tally is None else tally)
        return parity.check_dual(events, view, now=NOW)

    def row_with(self, entry: str) -> compact.IdentityRow:
        return next(r for r in self.rows if entry in r.entries())

    def with_row(self, old: compact.IdentityRow, new: compact.IdentityRow) -> list[compact.IdentityRow]:
        return [new if r is old else r for r in self.rows]


class MutationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.w = Synthetic()

    def assertOnly(self, report: parity.ParityReport, *kinds: str, ref: str | None = None) -> None:
        """The counted differences of layers 1 to 3 are exactly `kinds`. Layer 4 (plan 03-03) reads the same damage again as a
        figure, so it is looked at in `FigureTests`, not here."""
        counted = [d for d in report.diffs if not d.declared and d.layer < 4]
        self.assertEqual(sorted({d.kind for d in counted}), sorted(kinds), [d.text() for d in counted])
        if ref is not None:
            self.assertIn(ref, [d.ref for d in counted])
        self.assertEqual(report.counted, len([d for d in report.diffs if not d.declared]))

    def test_the_consistent_world_has_zero_counted_differences_and_says_what_it_compared(self) -> None:
        report = self.w.check()
        self.assertEqual((report.counted, report.declared), (0, 0), [d.text() for d in report.diffs])
        self.assertGreater(report.compared["seen_keys"], 25)
        self.assertEqual(report.compared["identity_entries"], 12 + 6 + 6)  # twelve baselines, six gated and six stale entries, each once
        self.assertGreaterEqual(report.compared["tally_groups"], 8)
        self.assertGreater(report.compared["state_counters"], 2)

    def test_one_identity_id_removed(self) -> None:
        row = self.w.row_with("b3")
        kept = [e for e in row.entries() if e != "b3"]
        rows = self.w.with_row(row, replace(row, ids=",".join(kept), count=len(kept)))
        self.assertOnly(self.w.check(rows=rows), "identity_missing", ref="greenhouse|acme|3")

    def test_one_identity_id_added(self) -> None:
        row = self.w.row_with("b3")
        rows = self.w.with_row(row, replace(row, ids=row.ids + ",b999", count=row.count + 1))
        self.assertOnly(self.w.check(rows=rows), "identity_extra", ref="greenhouse|acme|999")

    def test_a_kind_letter_changed(self) -> None:
        row = self.w.row_with("ff5")
        rows = self.w.with_row(row, replace(row, ids=row.ids.replace("ff5", "bf5")))
        self.assertOnly(self.w.check(rows=rows), "identity_kind", ref="greenhouse|acme|f5")

    def test_a_wrong_count(self) -> None:
        row = self.w.row_with("b3")
        rows = self.w.with_row(row, replace(row, count=row.count + 1))
        self.assertOnly(self.w.check(rows=rows), "identity_count", ref=f"{row.stem}#{row.chunk}")

    def test_the_highest_chunks_marker_removed(self) -> None:
        row = self.w.row_with("b3")
        rows = self.w.with_row(row, replace(row, baselined_at=""))
        self.assertOnly(self.w.check(rows=rows), "identity_marker", ref=row.stem)

    def test_a_tally_row_lost(self) -> None:
        lost = self.w.tally[3]
        tally = [t for t in self.w.tally if t is not lost]
        self.assertOnly(self.w.check(tally=tally), "tally_missing", ref=f"{lost.run_id}@{lost.run_at}")

    def test_a_tally_run_id_changed(self) -> None:
        wrong = self.w.tally[3]
        tally = [replace(t, run_id="not-a-run") if t is wrong else t for t in self.w.tally]
        report = self.w.check(tally=tally)
        self.assertOnly(report, "tally_missing", "tally_orphan")
        self.assertIn(f"not-a-run@{wrong.run_at}", [d.ref for d in report.diffs if d.kind == "tally_orphan"])

    def test_a_tally_date_dimension_flipped(self) -> None:
        wrong = next(t for t in self.w.tally if any(dim.endswith("|k") for dim in t.counts))
        dim = next(dim for dim in wrong.counts if dim.endswith("|k"))
        flipped = {(dim[:-1] + "u" if k == dim else k): n for k, n in wrong.counts.items()}
        tally = [replace(t, counts=flipped) if t is wrong else t for t in self.w.tally]
        report = self.w.check(tally=tally)
        self.assertOnly(report, "tally_count")
        self.assertIn(f"{wrong.run_id}@{wrong.run_at} {dim}", [d.ref for d in report.diffs])

    def test_a_key_with_fewer_than_three_segments_is_declared_not_counted(self) -> None:
        unkeyable = history_event("greenhouse|acme", at(days=12, hours=1), lg.STALED, "legacy")
        split = compact.split_observations([unkeyable], compact.MODE_DUAL)
        self.assertEqual((split.identity, sum(split.tally.values())), ({}, 1))  # counted in Tally, never an Identity entry
        events = sorted(self.w.events + [unkeyable], key=lambda e: e.time)
        tally = self.w.tally + [compact.TallyRow("legacy", unkeyable.time, 1, dict(split.tally))]
        view = compact.Ledger(compact.simulate_compact(events, NOW), [], compact.IdentitySet.from_rows(self.w.rows), tally)
        self.assertIn(unkeyable, view.events)  # twelve days old and stale, yet the fold would never delete it
        report = parity.check_dual(events, view, now=NOW)
        self.assertEqual([(d.kind, d.ref, d.declared) for d in report.diffs], [("unkeyable", "greenhouse|acme", True)])
        self.assertEqual((report.counted, report.declared), (0, 1))

    def test_a_second_seen_row_for_one_key_is_declared_not_counted(self) -> None:
        again = history_event("greenhouse|acme|f4", at(hours=5), lg.FILTERED, "steady-0")
        events = self.w.events + [again]
        report = self.w.check(events=events)
        self.assertEqual([(d.kind, d.ref) for d in report.diffs], [("duplicate_seen", "greenhouse|acme|f4")])
        self.assertEqual((report.counted, report.declared), (0, 1))

    def test_a_state_counter_that_differs_between_the_two_views_is_named(self) -> None:
        events = self.w.events
        view = compact.Ledger([ev for ev in compact.simulate_compact(events, NOW) if not (ev.event == lg.ERROR)], [], compact.IdentitySet.from_rows(self.w.rows), self.w.tally)
        report = parity.check_dual(events, view, now=NOW)
        self.assertEqual([(d.kind, d.ref) for d in report.diffs if not d.declared and d.layer < 4], [("state_counts", "error_attempts:evaluate")])
        self.assertTrue(any(d.layer == 4 and d.ref.startswith("failures.") for d in report.diffs))  # the missing error row also changes the reported failures

    def test_no_difference_text_holds_a_title_or_a_url(self) -> None:
        row = self.w.row_with("b3")
        rows = self.w.with_row(row, replace(row, ids=row.ids + ",b999", count=row.count + 1))
        report = self.w.check(rows=rows, tally=self.w.tally[1:])
        self.assertGreater(report.counted, 1)
        text = " ".join(d.text() for d in report.diffs)
        for forbidden in ("http", "t t", "Intern", "Remote"):
            self.assertNotIn(forbidden, text)


class SimulationTests(unittest.TestCase):
    """The pure helpers later plans reuse: the simulated compact view and Tally minus the retained recount."""

    def setUp(self) -> None:
        self.w = Synthetic()

    def test_simulate_compact_drops_baselines_and_week_old_gated_rows_and_keeps_the_rest(self) -> None:
        kept = compact.simulate_compact(self.w.events, NOW)
        seen = [e for e in kept if e.event == lg.SEEN]
        self.assertFalse([e for e in seen if e.disposition == lg.BASELINED])  # every baseline row is gone, whatever its age
        gated = sorted(e.key for e in seen if e.disposition in (lg.FILTERED, lg.STALED))
        self.assertEqual(gated, sorted([f"greenhouse|acme|f{d}" for d in range(1, 6)] + [f"greenhouse|globex|s{d}" for d in range(1, 6)] + ["greenhouse|acme|r1"]))
        self.assertNotIn("greenhouse|acme|old2", gated)  # twelve days old: gone
        self.assertEqual(len([e for e in kept if e.event != lg.SEEN]), 2)  # the evaluated and error rows are operational
        self.assertEqual(len([e for e in seen if e.disposition == lg.PENDING]), 5)

    def test_a_row_exactly_seven_days_old_is_folded_and_one_second_younger_is_kept(self) -> None:
        edge = history_event("greenhouse|acme|edge", lg.stamp(NOW - compact.FOLD_AGE), lg.FILTERED, "r")
        young = history_event("greenhouse|acme|young", lg.stamp(NOW - compact.FOLD_AGE + timedelta(seconds=1)), lg.FILTERED, "r")
        kept = compact.simulate_compact([edge, young], NOW)
        self.assertEqual([e.key for e in kept], ["greenhouse|acme|young"])

    def test_tally_minus_the_retained_recount_is_what_was_folded(self) -> None:
        ledger = compact.Ledger(compact.simulate_compact(self.w.events, NOW), [], compact.IdentitySet.from_rows(self.w.rows), self.w.tally)
        folded = ledger.folded()
        self.assertEqual(sum(f.n for f in folded), 12 + 1)  # the twelve baselines and the one stale row older than seven days
        self.assertEqual(ledger.negative(), [])
        self.assertTrue(all(f.n > 0 for f in folded))
        whole = compact.Ledger(self.w.events, [], compact.IdentitySet.from_rows(self.w.rows), self.w.tally)
        self.assertEqual((whole.folded(), whole.negative()), ([], []))  # dual mode: nothing is folded

    def test_a_lost_tally_count_shows_as_negative(self) -> None:
        tally = [replace(t, counts={}) if t.run_id == "steady-2" else t for t in self.w.tally]
        ledger = compact.Ledger(self.w.events, [], compact.IdentitySet.from_rows(self.w.rows), tally)
        self.assertEqual(sorted((n.run_id, n.n) for n in ledger.negative()), [("steady-2", 1), ("steady-2", 1)])

    def test_parse_dim_reads_what_tally_dim_wrote(self) -> None:
        ev = history_event("greenhouse|acme|f1", at(days=1), lg.FILTERED, "r", published=at(days=1, hours=1))
        self.assertEqual(
            compact.parse_dim(compact.tally_dim(ev)),
            {"ats": "greenhouse", "source": "poll", "disposition": "filtered", "pass": "", "freshness": "recent", "date_known": True},
        )
        self.assertFalse(compact.parse_dim("lever|search|baseline|baseline|baseline|u")["date_known"])

    def test_repair_plan_names_what_is_missing_and_nothing_else(self) -> None:
        empty = compact.Ledger(self.w.events, [], compact.IdentitySet(), [])
        plan = compact.repair_plan(empty)
        self.assertEqual(plan.ids, 12 + 6 + 6)
        self.assertEqual([(t.run_id, t.run_at) for t in plan.tally], [(t.run_id, t.run_at) for t in sorted(self.w.tally, key=lambda t: (t.run_at, t.run_id))])
        done = compact.Ledger(self.w.events, [], compact.IdentitySet.from_rows(self.w.rows), self.w.tally)
        self.assertFalse(compact.repair_plan(done))
        partial = compact.Ledger(self.w.events, [], compact.IdentitySet.from_rows(self.w.rows), self.w.tally[:2])
        self.assertEqual((compact.repair_plan(partial).ids, len(compact.repair_plan(partial).tally)), (0, len(self.w.tally) - 2))


# --------------------------------------------------------------------------- the parity clock


def utc(day: int, hour: int = 0, minute: int = 0, second: int = 0, month: int = 10) -> datetime:
    return datetime(2026, month, day, hour, minute, second, tzinfo=timezone.utc)


def fill(state: compact.StorageState, day: int, runs: int, *, diffs: int = 0, admissions: int = 0, failed: bool = False) -> None:
    """Record `runs` checked runs on October `day`; the first `diffs` of them found a counted difference, the first run saw `admissions`."""
    for i in range(runs):
        state.record_check(
            utc(day, hour=i % 24, minute=5), counted=1 if i < diffs else 0, declared=0,
            admissions=admissions if i == 0 else 0, failed=failed and i < diffs, diffs=["identity_missing greenhouse|acme|1"] if i < diffs else [],
        )  # fmt: skip


def seeded(at: datetime | None = None) -> compact.StorageState:
    return compact.StorageState(seeded_at=lg.stamp(at or utc(1, 10)))


class ClockTests(unittest.TestCase):
    def test_three_clean_complete_days_with_an_admission_meet_the_bar_and_bar_met_at_is_set_once(self) -> None:
        state = seeded()
        for day, admissions in ((2, 0), (3, 1), (4, 0)):
            fill(state, day, 12, admissions=admissions)
        self.assertIsNone(state.bar_met_at)
        bar = state.bar(utc(5, 8))
        self.assertEqual((bar.met, bar.days_counted, bar.admission_seen, bar.streak), (True, 3, True, 3))
        state.record_check(utc(5, 0, 7), counted=0, declared=0, admissions=0)
        self.assertEqual(state.bar_met_at, "2026-10-05T00:07:00Z")  # the first checked run after the third day completed
        state.record_check(utc(5, 6), counted=0, declared=0, admissions=0)
        self.assertEqual(state.bar_met_at, "2026-10-05T00:07:00Z")  # set once

    def test_without_an_admission_in_the_three_days_the_bar_is_not_met(self) -> None:
        state = seeded()
        for day in (2, 3, 4):
            fill(state, day, 12)
        bar = state.bar(utc(5, 8))
        self.assertEqual((bar.met, bar.days_counted, bar.admission_seen), (False, 3, False))
        state.record_check(utc(5, 1), counted=0, declared=0, admissions=0)
        self.assertIsNone(state.bar_met_at)

    def test_an_admission_before_the_three_days_does_not_help(self) -> None:
        state = seeded()
        fill(state, 2, 12, admissions=3)
        for day in (3, 4, 5):
            fill(state, day, 12)
        bar = state.bar(utc(6, 8))
        self.assertEqual((bar.met, bar.admission_seen, bar.streak), (False, False, 4))  # the three most recent days saw none

    def test_eleven_checked_runs_on_a_day_do_not_count_and_twelve_do(self) -> None:
        state = seeded()
        fill(state, 2, 12, admissions=1)
        fill(state, 3, 11)
        fill(state, 4, 12)
        bar = state.bar(utc(5, 8))
        self.assertEqual((bar.met, bar.days_counted, bar.streak), (False, 1, 1))
        state.record_check(utc(3, 23, 30), counted=0, declared=0, admissions=0)  # the twelfth
        self.assertEqual((state.bar(utc(5, 8)).met, state.bar(utc(5, 8)).days_counted), (True, 3))

    def test_the_seed_day_never_counts_however_many_clean_runs_it_has(self) -> None:
        state = seeded(utc(1, 10))
        fill(state, 1, 20, admissions=1)
        fill(state, 2, 12)
        fill(state, 3, 12)
        bar = state.bar(utc(4, 8))
        self.assertEqual((bar.met, bar.days_counted), (False, 2))
        midnight = seeded(utc(1, 0))  # seeded at the first instant of the day: the day did not start AFTER the seed
        fill(midnight, 1, 20, admissions=1)
        fill(midnight, 2, 12)
        fill(midnight, 3, 12)
        self.assertEqual(midnight.bar(utc(4, 8)).days_counted, 2)

    def test_a_difference_on_the_middle_day_means_three_new_clean_complete_days_are_needed(self) -> None:
        state = seeded()
        fill(state, 2, 12, admissions=1)
        fill(state, 3, 12)
        fill(state, 4, 12)
        state.record_check(utc(5, 0, 7), counted=0, declared=0, admissions=0)
        self.assertIsNotNone(state.bar_met_at)
        fill(state, 5, 12, diffs=1)  # a difference on day 4 of the streak clears bar_met_at at once
        self.assertIsNone(state.bar_met_at)
        for day in (6, 7):
            fill(state, day, 12, admissions=1 if day == 6 else 0)
        self.assertFalse(state.bar(utc(8, 8)).met)  # days 5, 6 and 7 are the last three complete days, and day 5 is dirty
        fill(state, 8, 12)
        bar = state.bar(utc(9, 8))
        self.assertEqual((bar.met, bar.streak, bar.admission_seen), (True, 3, True))
        state.record_check(utc(9, 0, 7), counted=0, declared=0, admissions=0)
        self.assertEqual(state.bar_met_at, "2026-10-09T00:07:00Z")

    def test_a_difference_today_blocks_the_bar_even_though_the_three_complete_days_before_it_are_clean(self) -> None:
        state = seeded()
        fill(state, 2, 12, admissions=1)
        fill(state, 3, 12)
        fill(state, 4, 12)
        self.assertTrue(state.bar(utc(5, 8)).met)
        state.record_check(utc(5, 8), counted=2, declared=0, admissions=0, diffs=["identity_missing greenhouse|acme|1"])
        self.assertFalse(state.bar(utc(5, 9)).met)  # P3-07: a difference restarts the clock; today can never be a counted day
        self.assertEqual(state.bar(utc(5, 9)).streak, 3)

    def test_a_run_at_exactly_midnight_utc_belongs_to_the_new_day(self) -> None:
        state = compact.StorageState()
        state.record_check(datetime(2026, 11, 2, 0, 0, 0, tzinfo=timezone.utc), counted=0, declared=0, admissions=0)
        state.record_check(datetime(2026, 11, 1, 23, 59, 59, tzinfo=timezone.utc), counted=0, declared=0, admissions=0)
        state.record_check(datetime(2026, 11, 1, 19, 0, 0, tzinfo=timezone(timedelta(hours=-5))), counted=0, declared=0, admissions=0)  # 00:00:00Z on the 2nd
        self.assertEqual({d: r["runs"] for d, r in state.days.items()}, {"2026-11-01": 1, "2026-11-02": 2})

    def test_the_current_incomplete_utc_day_never_counts(self) -> None:
        state = seeded()
        fill(state, 2, 12, admissions=1)
        fill(state, 3, 12)
        fill(state, 4, 30, admissions=2)  # today, still running
        bar = state.bar(utc(4, 23, 59))
        self.assertEqual((bar.met, bar.days_counted, bar.streak), (False, 2, 2))
        self.assertTrue(state.bar(utc(5, 0, 0)).met)  # a second later the day is complete

    def test_a_failed_check_counts_as_a_difference_and_restarts_the_clock(self) -> None:
        state = seeded()
        fill(state, 2, 12, admissions=1)
        fill(state, 3, 12)
        fill(state, 4, 11)
        state.record_check(utc(4, 23, 50), counted=1, declared=0, admissions=0, failed=True, diffs=["check_failed RuntimeError"])
        day = state.days["2026-10-04"]
        self.assertEqual((day["runs"], day["diff_runs"], day["failed"]), (12, 1, 1))
        self.assertEqual(state.last_diffs, ["check_failed RuntimeError"])
        self.assertEqual(state.bar(utc(5, 8)).streak, 0)  # twelve checked runs, but one of them is a difference

    def test_a_run_that_was_not_checked_is_not_recorded_at_all(self) -> None:
        state = seeded()
        fill(state, 2, 12)
        before = state.to_json()
        # the pipeline skips the check past the cutoff and never calls record_check: nothing about the day changes
        self.assertEqual(state.to_json(), before)
        self.assertEqual(state.days["2026-10-02"]["runs"], 12)

    def test_twenty_days_are_pruned_to_the_last_fourteen(self) -> None:
        state = seeded(utc(1, 0, 0, 1, month=9))
        for day in range(1, 21):
            state.record_check(utc(day, 12), counted=0, declared=0, admissions=0)
        self.assertEqual(sorted(state.days), [f"2026-10-{d:02d}" for d in range(7, 21)])
        self.assertEqual(len(state.days), compact.STORAGE_DAYS_KEPT)

    def test_a_thousand_offered_differences_keep_ten_and_each_text_is_capped(self) -> None:
        state = seeded()
        state.record_check(utc(2, 12), counted=1000, declared=0, admissions=0, diffs=[f"identity_missing greenhouse|acme|{'9' * 400}{i}" for i in range(1000)])
        self.assertEqual(len(state.last_diffs), compact.MAX_LISTED_DIFFS)
        self.assertTrue(all(len(text) <= 200 for text in state.last_diffs))

    def test_the_json_of_a_full_state_stays_far_below_the_discovery_cell_cap(self) -> None:
        state = seeded(utc(1, 0, 0, 1, month=9))
        for day in range(1, 21):
            for i in range(24):
                state.record_check(utc(day, i, 5), counted=1, declared=2, admissions=1, diffs=[f"identity_missing greenhouse|acme|{'x' * 300}"] * 10, compared=190_000, seconds=12.3)
        text = state.to_json()
        self.assertLess(len(text), 10_000)  # the cell cap is 45,000 characters
        again = compact.StorageState.load(text)
        self.assertEqual((again.seeded_at, again.days, again.last_diffs, again.last_check), (state.seeded_at, state.days, state.last_diffs, state.last_check))

    def test_truncated_or_hand_edited_json_gives_a_fresh_state_that_assumes_nothing_met(self) -> None:
        state = seeded()
        for day in (2, 3, 4):
            fill(state, day, 12, admissions=1)
        text = state.to_json()
        for broken in (text[:-25], "", "[]", "null", '{"days": "x", "seeded_at": 5, "bar_met_at": 7, "last_diffs": "no"}'):
            fresh = compact.StorageState.load(broken)
            self.assertIsNone(fresh.seeded_at, broken)
            self.assertEqual((fresh.days, fresh.last_diffs), ({}, []))
            self.assertFalse(fresh.bar(utc(5, 8)).met)
            self.assertIsNone(fresh.bar_met_at)
        kept = compact.StorageState.load(text)
        self.assertEqual(kept.to_json(), text)

    def test_later_plans_fields_survive_a_load_and_save(self) -> None:
        text = '{"cutover":{"at":"2026-11-01T00:00:00Z"},"fold":{"last":"x"},"future":[1,2],"mode":"compact","restore":{"n":1},"seeded_at":"2026-10-01T10:00:00Z"}'
        state = compact.StorageState.load(text)
        state.record_check(utc(5, 8), counted=0, declared=0, admissions=0)
        data = json.loads(state.to_json())
        self.assertEqual((data["cutover"], data["fold"], data["restore"], data["future"], data["mode"]), ({"at": "2026-11-01T00:00:00Z"}, {"last": "x"}, {"n": 1}, [1, 2], "compact"))


# --------------------------------------------------------------------------- the pipeline


def rewrite_identity(case: HarnessCase, drop: str) -> None:
    """Hand-remove one posting ID entry from the Identity file (what a hand edit of the Sheet would do)."""
    path = case.w.state.dir / "identity.csv"
    rows = read_csv(case, "identity")
    for row in rows[1:]:
        entries = [e for e in row[4].split(",") if e != drop]
        row[3], row[4] = str(len(entries)), ",".join(entries)
    with path.open("w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows(rows)


class PipelineDifferenceTests(HarnessCase):
    def baselined(self, *ids: str) -> None:
        self.w.listings[self.board.key] = [job("acme", jid) for jid in ids]
        self.w.run(seeds=[self.board])  # run 1 seeds (an empty ledger) and baselines

    def test_a_missing_identity_id_degrades_the_run_but_never_changes_detection_then_repair_clears_it(self) -> None:
        self.baselined("1", "2", "3")
        self.w.run(minutes_later=60)  # run 2: the first checked run, clean
        self.assertEqual(storage_of(self).last_check["counted"], 0)
        rewrite_identity(self, "b2")
        later = T0 + timedelta(minutes=180)
        self.w.listings[self.board.key] = [job("acme", jid) for jid in ("1", "2", "3")] + [job("acme", "7", published=ago(minutes=10, base=later))]
        run = self.w.run(minutes_later=120)  # run 3 still lists job 2, which Identity no longer knows
        self.assertEqual(run.outcome, stm.OUTCOME_DEGRADED)
        self.assertIn("storage", pl.degraded_reason(run))
        self.assertIn("storage parity: 2 differences (figure 1, identity_missing 1)", run.notes)  # layer 4 sees the lost baseline ID as one figure too
        state = storage_of(self)
        self.assertEqual(state.last_diffs[0], "identity_missing greenhouse|acme|2")
        self.assertEqual(state.last_diffs[1:], ["figure logical.baseline_jobs_per_board.greenhouse|acme (old 3 new 2)"])
        self.assertEqual((state.days["2026-10-14"]["runs"], state.days["2026-10-14"]["diff_runs"]), (2, 1))
        self.assertIsNone(state.bar_met_at)
        seen = [e.key for e in self.w.events(kind=lg.SEEN)]
        self.assertEqual(sorted(seen), ["greenhouse|acme|1", "greenhouse|acme|2", "greenhouse|acme|3", "greenhouse|acme|7"])  # job 2 was not observed again
        self.assertEqual([e.key for e in self.w.events(kind=lg.EVALUATED)], ["greenhouse|acme|7"])  # detection, evaluation and alerts as without the check
        self.assertEqual(len(self.w.alerts), 1)
        self.assertEqual(self.w.state.load_ledger().identity.kind("greenhouse|acme|2"), "b")  # the repair at run start re-added the ID
        clean = self.w.run(minutes_later=60)  # run 4
        self.assertEqual(clean.outcome, stm.OUTCOME_OK)
        state = storage_of(self)
        self.assertEqual((state.last_check["counted"], state.last_diffs), (0, []))
        self.assertEqual((state.days["2026-10-14"]["runs"], state.days["2026-10-14"]["diff_runs"]), (3, 1))
        self.assertEqual(len(self.w.alerts), 1)

    def test_a_check_that_raises_is_a_counted_difference_and_a_failed_day_entry(self) -> None:
        self.baselined("1", "2")
        with mock.patch.object(parity, "check_dual", side_effect=RuntimeError("boom with a secret")):
            run = self.w.run(minutes_later=60)
        self.assertEqual(run.outcome, stm.OUTCOME_DEGRADED)
        self.assertIn("storage", pl.degraded_reason(run))
        self.assertIn("storage check failed: RuntimeError", run.notes)
        stored = self.w.state.load_discovery_state()[compact.STORAGE_KEY]
        for text in (run.notes, stored):
            self.assertNotIn("secret", text)  # the exception type only, never its text
        state = storage_of(self)
        day = state.days["2026-10-14"]
        self.assertEqual((day["runs"], day["diff_runs"], day["failed"]), (1, 1, 1))
        self.assertEqual((state.last_check["counted"], state.last_diffs), (1, ["check_failed RuntimeError"]))
        self.assertEqual(len(self.w.events(kind=lg.SEEN)), 2)  # the run's own work is unaffected
        clean = self.w.run(minutes_later=60)
        self.assertEqual(clean.outcome, stm.OUTCOME_OK)

    def test_a_check_skipped_past_the_cutoff_is_not_recorded_and_does_not_reset_the_clock(self) -> None:
        self.baselined("1")
        self.w.run(minutes_later=60)
        before = storage_of(self)
        self.assertEqual(before.days["2026-10-14"]["runs"], 1)
        late = self.w.run(minutes_later=60, process_t0=0.0, clock=lambda: pl.STORAGE_CHECK_CUTOFF_S + 1.0)
        after = storage_of(self)
        self.assertEqual((after.days, after.last_check, after.bar_met_at), (before.days, before.last_check, before.bar_met_at))
        self.assertNotIn("storage", late.notes)
        self.w.run(minutes_later=60)
        self.assertEqual(storage_of(self).days["2026-10-14"]["runs"], 2)

    def test_the_storage_key_the_notes_and_the_log_never_hold_job_text(self) -> None:
        self.w.listings[self.board.key] = [job("acme", "1", location="Nowhere Land ZZQ"), job("acme", "2", title="Secret Title ZZQ")]
        self.w.run(seeds=[self.board])
        rewrite_identity(self, "b1")
        with self.assertLogs("hunter", level="INFO") as logs:
            run = self.w.run(minutes_later=60)
        stored = self.w.state.load_discovery_state()[compact.STORAGE_KEY]
        text = "\n".join([stored, run.notes, *logs.output])
        for forbidden in ("Secret Title ZZQ", "Nowhere Land ZZQ", "http"):
            self.assertNotIn(forbidden, text)
        self.assertTrue(any(line.startswith("INFO:hunter:Storage: mode=dual, 2 counted") for line in logs.output), logs.output)
        self.assertEqual(sum("Storage" in line for line in logs.output if line.startswith("INFO")), 1)  # one storage line per run
        self.assertIn("0 of 3 complete days toward the bar, admission seen no", "\n".join(logs.output))

    def test_a_tally_row_lost_between_runs_is_repaired_and_named(self) -> None:
        self.baselined("1", "2")
        self.w.run(minutes_later=60)
        path = self.w.state.dir / "tally.csv"
        rows = read_csv(self, "tally")
        self.assertEqual(len(rows), 3)
        with path.open("w", newline="", encoding="utf-8") as fh:
            csv.writer(fh).writerows(rows[:1] + rows[2:])  # the baseline run's row is gone
        run = self.w.run(minutes_later=60)
        self.assertIn("storage parity: ", run.notes)
        self.assertIn("tally_missing", run.notes)
        self.assertEqual(len(read_csv(self, "tally")) - 1, 3 + 0)  # repaired at run start: the group is back exactly once
        self.assertEqual(self.w.run(minutes_later=60).outcome, stm.OUTCOME_OK)


# --------------------------------------------------------------------------- layer 4: the reported figures

FIGURE_TEXT = re.compile(r"^figure [A-Za-z0-9_.:|@?-]+ \(old (?:-?\d+(?:\.\d+)?|none|text) new (?:-?\d+(?:\.\d+)?|none|text)\)$")


def dual_world(events: list[lg.Event]) -> tuple[list[lg.Event], compact.IdentitySet, list[compact.TallyRow]]:
    """The stored side of a dual-write world for these Events rows, built per run through `split_observations`."""
    by_run: dict[tuple[str, str], list[lg.Event]] = defaultdict(list)
    for ev in events:
        by_run[(str(ev.detail.get("run") or ""), ev.time)].append(ev)
    identity, tally = compact.IdentitySet(), []
    for (run_id, run_at), group in sorted(by_run.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        split = compact.split_observations(group, compact.MODE_DUAL)
        identity.apply(identity.plan_additions(split.identity, "2026-10-12T00:00:00Z"))
        if split.tally:
            tally.append(compact.TallyRow(run_id, run_at, sum(split.tally.values()), dict(sorted(split.tally.items()))))
    return sorted(events, key=lambda e: e.time), identity, tally


class FigureTests(unittest.TestCase):
    """Layer 4: the Dashboard, both reconciliation windows and the storage logical counts, computed from all Events rows and again
    from the compact view, must be the same figures. A difference names its dotted path and holds numbers only."""

    def world(self, tz: object = UTC, now: datetime | None = None):  # type: ignore[no-untyped-def]
        now = now or ZONES[0][1]
        world = compact_world(tz, now)
        return world, world.compact_view(now), now

    def figures(self, report: parity.ParityReport) -> list[parity.Diff]:
        return [d for d in report.diffs if d.layer == 4]

    def test_a_consistent_world_has_zero_counted_differences_in_both_time_zones_and_says_what_it_compared(self) -> None:
        for tz, now in ZONES:
            with self.subTest(tz=str(tz)):
                world, view, _ = self.world(tz, now)
                report = parity.check_dual(world.events, view, now=now, tz=tz, runs=world.runs, boards={}, discovery={}, tracker=[])
                self.assertEqual((report.counted, report.declared), (0, 0), [d.text() for d in report.diffs[:5]])
                for name in ("figures_summary", "figures_reconcile_7d", "figures_reconcile_all", "figures_logical"):
                    self.assertGreater(report.compared[name], 10, name)

    def test_a_tally_date_letter_flipped_is_a_counted_figure_difference_named_by_its_path(self) -> None:
        world, view, now = self.world()
        row = next(t for t in world.tally if any("|filtered|" in dim and dim.endswith("|k") for dim in t.counts) and "2026-10-02" <= t.run_at < "2026-10-15")
        dim = next(dim for dim in row.counts if "|filtered|" in dim and dim.endswith("|k"))
        flipped = {(dim[:-1] + "u" if k == dim else k): n for k, n in row.counts.items()}
        view = compact.Ledger(view.events, [], view.identity, [replace(t, counts=flipped) if t is row else t for t in world.tally])
        report = parity.check_dual(world.events, view, now=now)
        figures = self.figures(report)
        self.assertTrue(any(d.kind == "figure" and "new_postings_date" in d.ref and not d.declared for d in figures), [d.text() for d in figures][:8])
        self.assertTrue(any(d.kind == "tally_count" for d in report.diffs))  # layer 2 names the same damage

    def test_a_tally_run_at_moved_back_one_day_names_the_affected_days(self) -> None:
        world, view, now = self.world()
        row = next(t for t in world.tally if t.run_id == world.wave_run)
        moved = lg.stamp(datetime.strptime(row.run_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) - timedelta(days=1))
        view = compact.Ledger(view.events, [], view.identity, [replace(t, run_at=moved) if t is row else t for t in world.tally])
        report = parity.check_dual(world.events, view, now=now)
        refs = {d.ref for d in self.figures(report) if d.kind == "figure"}
        self.assertIn("trend.20.baselined", refs)  # the wave's real day lost its 80 baselines ...
        self.assertIn("trend.21.baselined", refs)  # ... and the day before gained them
        self.assertTrue({d.kind for d in report.diffs} >= {"tally_missing", "tally_orphan"})

    def test_figure_differences_hold_numbers_and_paths_only(self) -> None:
        world, view, now = self.world()
        noisy = lg.Event("2026-10-28T10:00:00Z", "greenhouse|acme|p1-0-0", lg.ERROR, detail={"stage": "evaluate", "message": "SECRET ZZQ Remote title", "attempt": 1, "run": "x"})
        events = sorted([*world.events, noisy], key=lambda e: e.time)
        report = parity.check_dual(events, view, now=now)  # the view lacks the error row: failures, error counts and trend rows differ
        figures = [d for d in self.figures(report) if d.kind == "figure"]
        self.assertGreater(len(figures), 1)
        for d in figures:
            self.assertRegex(d.text(), FIGURE_TEXT, d.text())
            self.assertNotIn("ZZQ", d.text())
        self.assertNotIn("ZZQ", " ".join(report.named(10)))

    def test_compare_figures_names_nested_paths_lists_and_skips_presentation_keys(self) -> None:
        old = {"periods": {"7d": {"results": {"new_postings": 120, "label": "a"}}}, "checks": [], "rows": [{"n": 1}, {"n": 2}], "storage": {"mode": "dual"}}
        new = {"periods": {"7d": {"results": {"new_postings": 118, "label": "b"}}}, "checks": ["x"], "rows": [{"n": 1}, {"n": 3}], "storage": {"mode": "compact"}}
        diffs = parity.compare_figures(old, new)
        self.assertEqual(
            sorted((d.ref, d.detail) for d in diffs),
            [("checks.length", "old 0 new 1"), ("periods.7d.results.label", "old text new text"), ("periods.7d.results.new_postings", "old 120 new 118"), ("rows.1.n", "old 2 new 3")],
        )
        self.assertTrue(all(d.kind == "figure" and d.layer == 4 and not d.declared for d in diffs))
        self.assertEqual(parity.compare_figures(old, old), [])

    def test_a_hand_added_tracker_row_for_a_baseline_job_is_declared_not_counted(self) -> None:
        events, identity, tally = dual_world([
            history_event("greenhouse|acme|3", at(days=9), lg.BASELINED, "wave"),
            history_event("greenhouse|acme|custom1", at(days=9), lg.BASELINED, "wave", url="https://careers.example.org/job/777"),
            history_event("greenhouse|acme|9", at(days=2), lg.PENDING, "steady"),
        ])
        view = compact.Ledger(compact.simulate_compact(events, NOW), [], identity, tally)
        rows = [
            {"Apply_URL": "https://boards.greenhouse.io/acme/jobs/3", "Freshness": "Recent", "My_Status": "To Apply"},  # matches a baseline job by identity
            {"Apply_URL": "https://careers.example.org/job/777", "Freshness": "Recent", "My_Status": "To Apply"},  # matches it only by its exact stored URL
            {"Apply_URL": "https://boards.greenhouse.io/acme/jobs/9", "Freshness": "Verified fresh", "My_Status": "To Apply"},  # an ordinary kept job: stays on both sides
        ]
        report = parity.check_dual(events, view, now=NOW, tracker=rows)
        declared = [(d.kind, d.ref) for d in report.diffs if d.declared]
        self.assertEqual(sorted(declared), [("tracker_identity_job", "greenhouse|acme|3"), ("tracker_identity_job", "greenhouse|acme|custom1")])
        self.assertEqual(report.counted, 0, [d.text() for d in report.diffs])
        without = parity.check_dual(events, view, now=NOW)
        self.assertEqual((without.counted, without.declared), (0, 0))  # nothing declared when the tracker has no such row

    def test_a_duplicate_seen_row_of_a_folded_key_declares_the_row_count_figures_only(self) -> None:
        events, identity, tally = dual_world([
            history_event("greenhouse|acme|3", at(days=9), lg.BASELINED, "wave"),
            history_event("greenhouse|acme|9", at(days=2), lg.PENDING, "steady"),
        ])
        again = history_event("greenhouse|acme|3", at(days=8), lg.FILTERED, "steady")
        events = sorted([*events, again], key=lambda e: e.time)
        view = compact.Ledger(compact.simulate_compact(events, NOW), [], identity, tally)
        report = parity.check_dual(events, view, now=NOW)
        self.assertEqual(report.counted, 0, [d.text() for d in report.diffs if not d.declared])
        self.assertIn(("figure", "source_freshness.ledger_events_read"), [(d.kind, d.ref) for d in report.diffs if d.declared])
        self.assertIn(("duplicate_seen", "greenhouse|acme|3"), [(d.kind, d.ref) for d in report.diffs if d.declared])


class FigurePipelineTests(HarnessCase):
    """Every dual-mode poller run's check includes layer 4 and reads the tracker through `Deps.tracker_rows`."""

    def test_the_check_reads_the_tracker_once_and_compares_the_figures_in_the_display_time_zone(self) -> None:
        self.w.listings[self.board.key] = [job("acme", "1"), job("acme", "2")]
        self.w.run(seeds=[self.board])
        calls: list[int] = []

        def tracker() -> list[dict[str, str]]:
            calls.append(1)
            return [{"Apply_URL": "https://boards.greenhouse.io/acme/jobs/1", "Freshness": "Recent", "My_Status": "To Apply"}]  # a hand-added row for a baseline job

        tz = ZoneInfo("America/Chicago")
        with mock.patch.object(parity, "check_dual", wraps=parity.check_dual) as spy:
            run = self.w.run(minutes_later=60, tracker_rows=tracker, display_tz=tz)
        self.assertEqual(run.outcome, stm.OUTCOME_OK)
        self.assertEqual(len(calls), 1)
        kwargs = spy.call_args.kwargs
        self.assertEqual((kwargs["tz"], len(kwargs["tracker"]), kwargs["boards"] is not None), (tz, 1, True))
        self.assertTrue(kwargs["runs"] is not None and len(kwargs["runs"]) >= 1)
        state = storage_of(self)
        self.assertEqual(state.last_check["counted"], 0)  # the baseline job's tracker row is declared, not a flap of the clock
        self.assertGreaterEqual(state.last_check["declared"], 0)

    def test_a_tracker_that_cannot_be_read_is_compared_as_empty_and_the_check_still_completes(self) -> None:
        self.w.listings[self.board.key] = [job("acme", "1")]
        self.w.run(seeds=[self.board])

        def broken() -> list[dict[str, str]]:
            raise RuntimeError("tracker tab unreadable ZZQ")

        with mock.patch.object(parity, "check_dual", wraps=parity.check_dual) as spy:
            run = self.w.run(minutes_later=60, tracker_rows=broken)
        self.assertEqual(list(spy.call_args.kwargs["tracker"]), [])
        self.assertEqual(run.outcome, stm.OUTCOME_OK)
        self.assertNotIn("ZZQ", run.notes + self.w.state.load_discovery_state()[compact.STORAGE_KEY])
        self.assertEqual(storage_of(self).last_check["counted"], 0)

    def test_without_tracker_rows_the_check_runs_with_an_empty_tracker(self) -> None:
        self.w.listings[self.board.key] = [job("acme", "1")]
        self.w.run(seeds=[self.board])
        with mock.patch.object(parity, "check_dual", wraps=parity.check_dual) as spy:
            self.w.run(minutes_later=60)
        self.assertEqual((list(spy.call_args.kwargs["tracker"]), spy.call_args.kwargs["tz"]), ([], timezone.utc))


# --------------------------------------------------------------------------- compact mode: the integrity check (plan 03-07)


class IntegrityCheckTests(unittest.TestCase):
    """`parity.check_compact` on a compact view (the Events rows a store still holds, with the Identity and Tally the pipeline wrote): pure."""

    def setUp(self) -> None:
        self.w = Synthetic()
        self.events = compact.simulate_compact(self.w.events, NOW)  # no baseline row and no gated row older than 7 days is left

    def ledger(self, *, rows: list[compact.IdentityRow] | None = None, tally: list[compact.TallyRow] | None = None, events: list[lg.Event] | None = None) -> compact.Ledger:
        kept = self.events if events is None else events
        return compact.Ledger(kept, list(range(2, len(kept) + 2)), compact.IdentitySet.from_rows(self.w.rows if rows is None else rows), self.w.tally if tally is None else tally)

    def check(self, **kw: object) -> parity.ParityReport:
        return parity.check_compact(self.ledger(**kw), now=NOW)  # type: ignore[arg-type]

    def kinds(self, report: parity.ParityReport) -> list[str]:
        return sorted(d.kind for d in report.diffs if not d.declared)

    def entry_row(self, entry: str, edit: object) -> list[compact.IdentityRow]:
        row = self.w.row_with(entry)
        return self.w.with_row(row, edit(row))  # type: ignore[operator]

    def test_a_consistent_compact_view_counts_nothing_and_says_what_it_compared(self) -> None:
        report = self.check()
        self.assertEqual((report.counted, report.declared), (0, 0), [d.text() for d in report.diffs])
        self.assertLess(len(self.events), len(self.w.events))  # the baselines and the old gated rows really are gone from Events
        self.assertGreater(report.compared["seen_keys"], 5)
        self.assertEqual(report.compared["identity_entries"], 24)
        self.assertGreaterEqual(report.compared["tally_groups"], 8)

    def test_an_identity_id_removed_for_a_kept_gated_row_is_counted_identity_missing(self) -> None:
        report = self.check(rows=self.entry_row("f2", lambda r: replace(r, ids=",".join(e for e in r.entries() if e != "f2"), count=len(r.entries()) - 1)))
        self.assertEqual(self.kinds(report), ["identity_missing"])
        self.assertEqual([d.ref for d in report.diffs], ["greenhouse|acme|f2"])

    def test_an_id_that_only_identity_holds_cannot_be_compared_and_is_not_counted(self) -> None:
        """A baseline or folded row has no Events row any more: nothing to compare its ID with (a known limit, D-57), so removing it is not seen here."""
        report = self.check(rows=self.entry_row("b3", lambda r: replace(r, ids=",".join(e for e in r.entries() if e != "b3"), count=len(r.entries()) - 1)))
        self.assertEqual(report.counted, 0)

    def test_a_kind_letter_changed_for_a_kept_key_is_counted(self) -> None:
        self.assertEqual(self.kinds(self.check(rows=self.entry_row("f2", lambda r: replace(r, ids=r.ids.replace("f2", "s2"))))), ["identity_kind"])

    def test_the_identity_codec_invariants_are_counted_by_name(self) -> None:
        cases = {
            "identity_count": self.entry_row("f2", lambda r: replace(r, count=r.count + 3)),
            "identity_cell": self.entry_row("f2", lambda r: replace(r, ids=r.ids + "," + "x" * (compact.IDENTITY_CELL_CHARS + 1), count=r.count + 1)),
            "identity_marker": self.entry_row("f2", lambda r: replace(r, baselined_at="")),
            "identity_duplicate": self.entry_row("f2", lambda r: replace(r, ids=r.ids + ",f2", count=r.count + 1)),
            "identity_entry": self.entry_row("f2", lambda r: replace(r, ids=r.ids + ",x9", count=r.count + 1)),  # `x` is no kind letter
        }
        for kind, rows in cases.items():
            with self.subTest(kind):
                self.assertIn(kind, self.kinds(self.check(rows=rows)))

    def test_a_tally_group_below_its_retained_count_is_counted_tally_negative_with_numbers_only(self) -> None:
        lowered = [compact.TallyRow(t.run_id, t.run_at, 0, {}) if t.run_id == "steady-2" else t for t in self.w.tally]
        report = self.check(tally=lowered)
        self.assertEqual(self.kinds(report), ["tally_negative", "tally_negative"])  # the gated and the stale row of that run
        self.assertIn("steady-2@", report.diffs[0].ref)
        self.assertRegex(report.diffs[0].detail, r"^\d+ vs \d+$")

    def test_a_kept_group_missing_in_tally_is_counted_tally_missing_once(self) -> None:
        report = self.check(tally=[t for t in self.w.tally if t.run_id != "steady-2"])
        self.assertEqual(self.kinds(report), ["tally_missing"])

    def test_a_tally_total_that_is_not_the_sum_of_its_counts_is_counted(self) -> None:
        wrong = [replace(t, total=t.total + 5) if t.run_id == "steady-2" else t for t in self.w.tally]
        self.assertEqual(self.kinds(self.check(tally=wrong)), ["tally_count"])

    def test_a_tally_with_more_than_the_events_retain_is_what_a_fold_leaves_and_is_not_a_difference(self) -> None:
        report = parity.check_compact(self.ledger(events=[e for e in self.events if e.key != "greenhouse|acme|f2"]), now=NOW)  # f2's row folded: Tally still counts it
        self.assertEqual(report.counted, 0)

    def test_the_summary_consistency_checks_are_counted_figure_checks(self) -> None:
        with mock.patch.object(rp, "_checks", return_value=["today: job outcomes do not add up to the unique jobs observed"]):
            report = self.check()
        self.assertEqual(self.kinds(report), ["figure_checks"])
        self.assertEqual(report.diffs[0].ref, "checks.today")

    def test_an_unkeyable_kept_row_is_declared_not_counted(self) -> None:
        odd = history_event("greenhouse|acme", at(days=1), lg.FILTERED, "odd-run")
        report = self.check(events=self.events + [odd])
        self.assertEqual((report.counted, report.declared), (1, 1))  # its Tally group is missing: counted; the key cannot be keyed: declared
        self.assertEqual([d.kind for d in report.diffs if d.declared], ["unkeyable"])

    def test_no_difference_text_holds_a_title_or_a_url(self) -> None:
        report = self.check(rows=self.entry_row("f2", lambda r: replace(r, ids="")), tally=self.w.tally[:2])
        text = "\n".join(d.text() for d in report.diffs)
        self.assertTrue(text)
        for forbidden in ("http", "title", "Remote"):
            self.assertNotIn(forbidden, text)


class IntegrityTests(FoldCase):
    """Compact mode in the poller and in `--storage-parity`: after the cutover and the first fold every run still checks that Identity and Tally
    agree with what Events keeps (MOCKED: the Sheets fake; the in-run check is the pure check above on the start-of-run snapshot)."""

    def setUp(self) -> None:
        super().setUp()
        self.seeded_with_met_bar()
        self.assertEqual(self.cutover()[0], 0)
        self.run_at(FOLD_DAY)  # the first fold; every later run of these tests is on the same UTC day, so none folds again
        self.assertEqual(self.storage().fold["rows_total"], 4)
        self.minute = 0

    def next_run(self, **kw: object) -> pl.RunRecord:
        self.minute += 10
        return self.run_at(FOLD_DAY + timedelta(minutes=self.minute), **kw)

    def parity_command(self, now: datetime | None = None) -> tuple[int, str]:
        out = io.StringIO()
        with mock.patch.object(h.fr, "utcnow", return_value=now or FOLD_DAY + timedelta(hours=3)), contextlib.redirect_stdout(out):
            code = h.run_storage_parity(self.store, settings())
        return code, out.getvalue()

    def test_a_clean_compact_state_counts_zero_in_the_run_and_the_command_exits_zero(self) -> None:
        run = self.next_run()
        self.assertEqual(run.outcome, stm.OUTCOME_OK, run.notes)
        last = self.storage().last_check
        self.assertEqual((last["counted"], last["declared"]), (0, 0))
        self.assertGreater(last["compared"], 0)
        code, text = self.parity_command()
        self.assertEqual(code, 0, text)
        self.assertIn("mode compact", text)
        self.assertIn("0 counted differences", text)

    def test_compact_runs_record_a_check_but_no_clock_day_and_never_touch_the_bar(self) -> None:
        before = self.storage()
        days, bar = json.dumps(before.days, sort_keys=True), before.bar_met_at
        checked_at = before.last_check["at"]
        for _ in range(2):
            self.next_run()
        after = self.storage()
        self.assertEqual(json.dumps(after.days, sort_keys=True), days)  # the bar is not used after the cutover
        self.assertEqual(after.bar_met_at, bar)
        self.assertGreater(after.last_check["at"], checked_at)
        self.assertEqual(after.mode, compact.MODE_COMPACT)

    def test_an_identity_id_removed_for_a_kept_gated_row_degrades_the_run_and_the_next_runs_repair_clears_it(self) -> None:
        self.edit_identity("f33")  # job 33 is a kept gated row (one second younger than the 7-day cut)
        run = self.next_run()
        self.assertEqual(run.outcome, stm.OUTCOME_DEGRADED)
        self.assertIn("storage", pl.degraded_reason(run))
        self.assertIn("storage parity: 1 differences (identity_missing 1); ", run.notes)
        self.assertEqual(self.storage().last_diffs, ["identity_missing greenhouse|acme|33"])
        self.assertEqual(self.storage().last_check["counted"], 1)
        self.assertEqual(self.w.state.load_ledger().identity.kind("greenhouse|acme|33"), "f")  # the repair at run start put it back
        clean = self.next_run()
        self.assertEqual(clean.outcome, stm.OUTCOME_OK, clean.notes)
        self.assertEqual((self.storage().last_check["counted"], self.storage().last_diffs), (0, []))

    def test_a_tally_group_lowered_below_its_retained_count_is_counted_tally_negative_until_someone_repairs_it(self) -> None:
        def lower(row: list[str]) -> None:
            row[2], row[3] = "0", "{}"

        self.edit_tally("run-f4", lower)  # job 33's group
        for _ in range(2):  # nothing repairs a lowered count: a lost count is reported on every run
            run = self.next_run()
            self.assertEqual(run.outcome, stm.OUTCOME_DEGRADED)
            self.assertIn("storage parity: 1 differences (tally_negative 1); ", run.notes)
        self.assertTrue(self.storage().last_diffs[0].startswith("tally_negative run-f4@2026-10-12T00:00:01Z "))

    def test_a_kept_group_missing_in_tally_is_counted_and_the_next_run_has_it_back(self) -> None:
        self.sh.sheets[stm.TALLY_TAB].values[:] = [r for r in self.sh.sheets[stm.TALLY_TAB].values if r[0] != "run-f4"]
        run = self.next_run()
        self.assertIn("tally_missing 1", run.notes)
        self.assertEqual(self.next_run().outcome, stm.OUTCOME_OK)

    def test_failing_consistency_checks_of_the_merged_summary_are_counted_figure_checks(self) -> None:
        with mock.patch.object(rp, "_checks", return_value=["7d: periods are not nested"]):
            run = self.next_run()
        self.assertEqual(run.outcome, stm.OUTCOME_DEGRADED)
        self.assertIn("figure_checks 1", run.notes)

    def test_a_check_that_raises_is_a_counted_difference_and_adds_the_failed_note(self) -> None:
        with mock.patch.object(parity, "check_compact", side_effect=RuntimeError("boom with a secret")):
            run = self.next_run()
        self.assertEqual(run.outcome, stm.OUTCOME_DEGRADED)
        self.assertIn("storage check failed: RuntimeError", run.notes)
        self.assertNotIn("secret", run.notes + self.w.state.load_discovery_state()[compact.STORAGE_KEY])
        self.assertEqual((self.storage().last_check["counted"], self.storage().last_diffs), (1, ["check_failed RuntimeError"]))

    def test_a_check_past_the_cutoff_is_skipped_and_not_recorded(self) -> None:
        before = self.storage().last_check
        run = self.next_run(process_t0=0.0, clock=lambda: pl.STORAGE_CHECK_CUTOFF_S + 1.0)
        self.assertEqual(self.storage().last_check, before)
        self.assertNotIn("storage parity", run.notes)

    def test_the_command_in_compact_mode_exits_one_on_a_difference_and_writes_nothing(self) -> None:
        self.edit_identity("f33")
        before = self.snapshot()
        code, text = self.parity_command()
        self.assertEqual(code, 1, text)
        self.assertIn("identity_missing greenhouse|acme|33", text)
        self.assertEqual(self.snapshot(), before)

    def test_the_command_still_refuses_restored_and_unseeded_states_with_exit_two(self) -> None:
        self.set_storage(lambda s: setattr(s, "mode", compact.MODE_RESTORED))
        before = self.snapshot()
        code, text = self.parity_command()
        self.assertEqual((code, self.snapshot()), (2, before), text)
        self.set_storage(lambda s: (setattr(s, "mode", compact.MODE_COMPACT), setattr(s, "seeded_at", None)))
        self.assertEqual(self.parity_command()[0], 2)

    def test_the_notes_the_key_and_the_log_of_a_compact_run_hold_no_job_text(self) -> None:
        self.edit_identity("f33")
        with self.assertLogs("hunter", level="INFO") as logs:
            run = self.next_run()
        text = "\n".join([run.notes, self.w.state.load_discovery_state()[compact.STORAGE_KEY], *logs.output])
        for forbidden in ("Marketing", "http", "Remote"):
            self.assertNotIn(forbidden, text)
        self.assertTrue(any(line.startswith("INFO:hunter:Storage: mode=compact, 1 counted") for line in logs.output), logs.output)


if __name__ == "__main__":
    unittest.main()
