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
import freshness as fr  # noqa: E402
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


def history_event(key: str, when: str, disposition: str, run: str = "", published: str = "", **extra: object) -> lg.Event:
    """One `seen` row of a ledger written before the Identity and Tally tabs existed (rows without a run id have `run=""`)."""
    freshness = {lg.BASELINED: fr.BASELINE, lg.STALED: fr.STALE, lg.FILTERED: fr.RECENT}.get(disposition, fr.VERIFIED_FRESH)
    detail: dict[str, object] = {"source": "poll", "board": key.split("|")[1], "title": "t", "url": "u", "evidence": "x", **extra}
    if disposition == lg.BASELINED:
        detail["pass"] = "baseline"
    if run:
        detail["run"] = run
    return lg.Event(when, key, lg.SEEN, freshness, disposition, published, detail)


def historical_ledger() -> list[lg.Event]:
    """Two boards' baselines, filtered and stale rows with run ids, rows without a run id, operational rows and one pending job."""
    d3, d2, d9 = ago(days=3), ago(days=2), ago(days=9)
    return [
        *(history_event(f"greenhouse|acme|{i}", d3, lg.BASELINED, "run-1") for i in ("1", "2", "3")),
        history_event("greenhouse|acme|10", d3, lg.FILTERED, "run-1", published=ago(days=3, hours=1)),
        history_event("lever|foo|abc1", d3, lg.BASELINED, "run-1"),
        history_event("greenhouse|acme|11", d2, lg.STALED, "run-2", published=ago(days=40)),
        history_event("greenhouse|acme|12", d2, lg.FILTERED, "run-2"),
        history_event("greenhouse|acme|4", d9, lg.BASELINED),  # written before run ids existed
        history_event("greenhouse|acme|5", d9, lg.BASELINED),
        history_event("greenhouse|acme|13", d9, lg.STALED),
        history_event("greenhouse|acme|20", ago(days=1), lg.PENDING, "run-3", published=ago(days=1, hours=2)),  # still waiting for its evaluation
        history_event("greenhouse|acme|21", ago(days=1), lg.PENDING, "run-3"),
        lg.Event(ago(days=1), "greenhouse|acme|21", lg.EVALUATED, fr.VERIFIED_FRESH, detail={"status": "To Apply", "alert": True, "run": "run-3"}),
        lg.Event(ago(days=1), "greenhouse|acme|21", lg.ALERTED, detail={"channel": "telegram", "run": "run-3"}),
        lg.Event(ago(days=1), "greenhouse|acme|20", lg.ERROR, detail={"stage": "evaluate", "attempt": 1, "run": "run-3"}),
    ]  # fmt: skip


def storage_of(case: HarnessCase) -> compact.StorageState:
    return compact.StorageState.load(case.w.state.load_discovery_state().get(compact.STORAGE_KEY))


def identity_by_stem(case: HarnessCase) -> dict[str, list[str]]:
    return {r[0]: r[4].split(",") for r in read_csv(case, "identity")[1:]}


def tally_groups(case: HarnessCase) -> list[tuple[str, str]]:
    return [(r[0], r[1]) for r in read_csv(case, "tally")[1:]]


class SeedTests(HarnessCase):
    """P3-09: the first run after deploy builds Identity and the historical Tally from the ledger it already loads."""

    def setUp(self) -> None:
        super().setUp()
        self.w.state.append_events(historical_ledger())

    def test_the_first_run_seeds_identity_and_one_tally_row_per_run_time_group_and_performs_no_check(self) -> None:
        run = self.w.run()
        self.assertEqual(run.outcome, stm.OUTCOME_OK)
        by_stem = identity_by_stem(self)
        self.assertEqual(sorted(by_stem), ["greenhouse|acme", "lever|foo"])
        self.assertEqual(sorted(by_stem["greenhouse|acme"]), sorted(["b1", "b2", "b3", "b4", "b5", "f10", "f12", "s11", "s13"]))
        self.assertEqual(by_stem["lever|foo"], ["babc1"])  # the lower-case stem and ID of the job key
        for pending in ("20", "21"):
            self.assertNotIn(f"greenhouse|acme|{pending}", self.w.state.load_ledger().identity.keys())  # operational rows are never Identity
        groups = tally_groups(self)
        want = {("run-1", ago(days=3)), ("run-2", ago(days=2)), ("", ago(days=9))}
        self.assertEqual(sorted(g for g in groups if g[0] != run.run_id), sorted(want))
        self.assertEqual(len(groups), 4)  # three historical groups and the run's own (empty) row
        by_group = {(t.run_id, t.run_at): t for t in self.w.state.load_ledger().tally}
        self.assertEqual(by_group[("", ago(days=9))].total, 3)  # rows without a run id are grouped by their own time
        self.assertEqual(by_group[("run-1", ago(days=3))].counts["greenhouse|poll|filtered||recent|k"], 1)
        state = storage_of(self)
        self.assertEqual((state.mode, state.seeded_at, state.days), (compact.MODE_DUAL, lg.stamp(T0), {}))  # seeded, nothing checked yet
        self.assertEqual(len(self.w.events(kind=lg.EVALUATED)), 2)  # Events stayed authoritative: the pending job was evaluated as ever
        self.assertEqual(len(self.w.alerts), 1)

    def test_the_next_run_checks_the_previous_writes_and_records_zero_counted_differences(self) -> None:
        self.w.run()
        run = self.w.run(minutes_later=60)
        self.assertEqual(run.outcome, stm.OUTCOME_OK)
        state = storage_of(self)
        day = state.days["2026-10-14"]
        self.assertEqual((day["runs"], day["diff_runs"], day["failed"]), (1, 0, 0))
        self.assertEqual((state.last_check["counted"], state.last_check["declared"]), (0, 0))
        self.assertGreater(state.last_check["compared"], 10)  # it really compared the seed
        self.assertEqual(state.last_diffs, [])
        self.assertNotIn("storage", run.notes)
        self.w.run(minutes_later=60)
        self.assertEqual(storage_of(self).days["2026-10-14"]["runs"], 2)

    def test_a_seed_whose_tally_append_fails_is_completed_by_the_next_run_with_nothing_written_twice(self) -> None:
        real, calls = self.w.state.append_tally, []

        def flaky(rows: list[compact.TallyRow]) -> None:
            calls.append(len(rows))
            if len(calls) == 1:
                raise RuntimeError("tally write interrupted")
            real(rows)

        with mock.patch.object(self.w.state, "append_tally", side_effect=flaky):
            first = self.w.run()
        self.assertEqual(first.outcome, stm.OUTCOME_DEGRADED)
        self.assertIn("storage", pl.degraded_reason(first))
        self.assertIn("storage repair failed: RuntimeError", first.notes)
        self.assertNotIn("interrupted", first.notes)  # the exception type only, never its text
        self.assertNotIn(compact.STORAGE_KEY, self.w.state.load_discovery_state())  # not seeded: the key is saved only after the repair succeeded
        self.assertEqual(len(identity_by_stem(self)["greenhouse|acme"]), 9)  # Identity was written before the failing Tally append
        self.assertEqual(tally_groups(self), [(first.run_id, lg.stamp(T0))])  # only the run's own row made it
        second = self.w.run(minutes_later=60)
        self.assertEqual(second.outcome, stm.OUTCOME_OK)
        state = storage_of(self)
        self.assertEqual(state.seeded_at, lg.stamp(T0 + timedelta(minutes=60)))
        self.assertEqual(state.days, {})  # the run that completed the seed checks nothing
        entries = [e for ids in identity_by_stem(self).values() for e in ids]
        self.assertEqual(len(entries), len(set(entries)), "an ID was written twice")
        self.assertEqual(len(entries), 10)
        groups = tally_groups(self)
        self.assertEqual(len(groups), len(set(groups)), "a Tally group was written twice")
        self.assertEqual(len(groups), 5)  # three historical groups, the first run's row and the second run's row
        self.w.run(minutes_later=60)
        self.assertEqual(storage_of(self).last_check["counted"], 0)

    def test_a_dry_run_neither_seeds_nor_records(self) -> None:
        self.w.run(dry_run=True)
        self.assertNotIn(compact.STORAGE_KEY, self.w.state.load_discovery_state())
        self.assertEqual((identity_by_stem(self), tally_groups(self)), ({}, []))

    def test_an_empty_ledger_counts_as_a_successful_seed(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        fresh = HarnessCase()
        fresh.w = Harness(tmp.name)
        fresh.w.run()
        self.assertIsNotNone(storage_of(fresh).seeded_at)
        self.assertEqual(storage_of(fresh).days, {})
        fresh.w.run(minutes_later=60)
        self.assertEqual(storage_of(fresh).days["2026-10-14"]["runs"], 1)


class SnapshotTests(unittest.TestCase):
    """`load_ledger()` is a snapshot: a later `write_identity` changes the store's cache, never a ledger already returned."""

    def check(self, state: object) -> None:
        loaded = state.load_ledger()  # type: ignore[attr-defined]
        before = loaded.identity.keys()
        state.write_identity({"greenhouse|acme": ["b9"]}, "2026-10-14T12:00:00Z")  # type: ignore[attr-defined]
        self.assertEqual(loaded.identity.keys(), before)
        self.assertEqual(len(loaded.identity), 0)
        self.assertEqual(state.load_ledger().identity.keys(), {"greenhouse|acme|9"})  # type: ignore[attr-defined]

    def test_csv_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = stm.CsvState(Path(tmp) / "state")
            state.ensure()
            self.check(state)

    def test_sheet_store(self) -> None:
        state = stm.SheetState(FakeSpreadsheet())
        state.ensure()
        self.check(state)


if __name__ == "__main__":
    unittest.main()
