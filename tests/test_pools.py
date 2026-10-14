"""Offline tests for board evidence and slot allocation (D-23 .. D-30).

Mocked end to end: fake ATS listings, fake scorer and alert channel, CSV-backed state in a temp
dir (plus a fake Sheet for header widening). Nothing here touched an ATS, Sheets, Groq, Serper or
Telegram.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import boards as bd  # noqa: E402
import discovery as dsc  # noqa: E402
import eligibility as el  # noqa: E402
import freshness as fr  # noqa: E402
import ledger as lg  # noqa: E402
import pipeline as pl  # noqa: E402
import pools  # noqa: E402
import state as st_mod  # noqa: E402
from test_core import T0, EXCLUDED, S, HarnessCase, ago, job  # noqa: E402
from test_inventory import FakeSh  # noqa: E402


def stamp(dt: Any) -> str:
    return lg.stamp(dt)


# --------------------------------------------------------------------------- columns


class BoardColumnsTests(unittest.TestCase):
    def full(self, **kw: Any) -> bd.BoardRecord:
        return bd.BoardRecord("greenhouse", "acme", "2026-10-01T00:00:00Z", "serper", **kw)

    def test_old_18_column_rows_load_with_unknown_evidence(self) -> None:
        row = st_mod.board_to_row(self.full(status=bd.STATUS_ACTIVE, relevant_jobs=4))[:18]
        rec = st_mod.board_from_row(row)
        assert rec is not None
        self.assertEqual((rec.status, rec.relevant_jobs), ("active", 4))
        self.assertEqual((rec.pool, rec.eligible_jobs, rec.new_relevant_7d, rec.new_relevant_30d), ("", None, None, None))
        self.assertEqual((rec.complete_polls, rec.trials, rec.weak_streak, rec.activity_since), (0, 0, 0, ""))

    def test_there_are_31_columns_and_rows_match(self) -> None:
        self.assertEqual(len(st_mod.BOARD_COLUMNS), 31)
        self.assertEqual(len(st_mod.board_to_row(self.full())), 31)
        self.assertEqual(st_mod.BOARD_COLUMNS[18:], [
            "Eligible_Jobs", "Relevance_At", "Activity_Since", "Complete_Polls", "Last_New_Relevant_At",
            "New_Relevant_7d", "New_Relevant_30d", "Pool", "Pool_Since", "Trial_Until", "Trials", "Weak_Streak", "Pool_Reason",
        ])  # fmt: skip

    def test_unknown_and_zero_round_trip_differently(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            s = st_mod.CsvState(Path(d))
            s.ensure()
            unknown = self.full()
            zero = bd.BoardRecord("greenhouse", "zero", "t", "s", eligible_jobs=0, new_relevant_7d=0, new_relevant_30d=0, complete_polls=3)
            full = bd.BoardRecord(
                "lever", "Full", "t", "s", bd.STATUS_NEW, eligible_jobs=2, relevance_at="r", activity_since="a", complete_polls=5,
                last_new_relevant_at="l", new_relevant_7d=1, new_relevant_30d=4, pool=pools.POOL_EXPLORATION if hasattr(pools, "POOL_EXPLORATION") else "exploration",
                pool_since="ps", trial_until="tu", trials=2, weak_streak=1, pool_reason="why",
            )  # fmt: skip
            s.save_boards([unknown, zero, full])
            back = s.load_boards()
            self.assertEqual(back[unknown.key], unknown)
            self.assertIsNone(back[unknown.key].new_relevant_7d)
            self.assertEqual(back[zero.key].new_relevant_7d, 0)
            self.assertEqual(back[zero.key], zero)
            self.assertEqual(back[full.key], full)

    def test_hand_edited_cells_never_raise(self) -> None:
        row = st_mod.board_to_row(self.full())
        row[18], row[23], row[24], row[21], row[28] = "abc", "n/a", "", "x", "?"
        rec = st_mod.board_from_row(row)
        assert rec is not None
        self.assertEqual((rec.eligible_jobs, rec.new_relevant_7d, rec.new_relevant_30d, rec.complete_polls, rec.trials), (None, None, None, 0, 0))

    def test_sheet_header_of_18_names_widens_to_31(self) -> None:
        sh = FakeSh()
        state = st_mod.SheetState(sh)
        state.ensure()
        ws = sh.tabs[st_mod.BOARDS_TAB]
        old = st_mod.board_to_row(self.full(status=bd.STATUS_ACTIVE))[:18]
        ws.values = [st_mod.BOARD_COLUMNS[:18], old]
        state.ensure()
        self.assertEqual(ws.values[0], st_mod.BOARD_COLUMNS)
        rec = state.load_boards()["greenhouse|acme"]
        self.assertEqual((rec.status, rec.pool, rec.eligible_jobs), ("active", "", None))


# --------------------------------------------------------------------------- evidence refresh


def listing(*jobs: bd.ListedJob, complete: bool = True) -> Any:
    return bd.Listing(jobs, complete=complete)


class RelevanceRefreshTests(HarnessCase):
    def row(self) -> bd.BoardRecord:
        return self.w.state.load_boards()[self.board.key]

    def snap(self, rec: bd.BoardRecord) -> tuple:
        return (rec.relevant_jobs, rec.eligible_jobs, rec.relevance_at, rec.complete_polls)

    def mixed(self) -> list[bd.ListedJob]:
        return [
            job("acme", "1", published=ago(days=30)),  # Marketing Intern, Remote
            job("acme", "2", published=ago(days=30), location="London"),  # relevant, not US-eligible
            job("acme", "3", title="Software Engineer", published=ago(days=30)),  # not relevant
        ]

    def test_tracer_complete_poll_refreshes_relevance_from_its_own_listing(self) -> None:
        self.baseline(job("acme", "1", published=ago(days=30)))
        self.w.listings[self.board.key] = self.mixed()
        self.w.run(minutes_later=60)
        rec = self.row()
        self.assertEqual((rec.relevant_jobs, rec.eligible_jobs, rec.relevance_at), (2, 1, stamp(self.w.now)))
        self.assertEqual(rec.complete_polls, 2)  # baseline poll + this one

    def test_partial_listing_failed_poll_and_suspicious_empty_change_no_evidence(self) -> None:
        self.baseline(*[job("acme", str(i), published=ago(days=30)) for i in range(6)])
        before = self.snap(self.row())
        self.assertEqual(before[0], 6)

        partial = listing(*[job("acme", str(i), published=ago(days=30)) for i in range(4)], job("acme", "new1", published=""), complete=False)
        self.w.listings[self.board.key] = partial
        self.w.run(minutes_later=60)
        self.assertEqual(self.snap(self.row()), before)
        self.assertEqual(len(self.w.events(self.key("new1"), lg.SEEN)), 1)  # a new ID on a partial listing is still observed

        self.w.listings[self.board.key] = bd.BoardError("HTTP 503")
        self.w.run(minutes_later=60)
        self.assertEqual(self.snap(self.row()), before)

        self.w.listings[self.board.key] = []  # suspicious empty (board had 6 jobs)
        run = self.w.run(minutes_later=60)
        self.assertEqual((run.boards_failed, self.snap(self.row())), (1, before))

    def test_complete_poll_after_a_partial_one_resumes_counting(self) -> None:
        self.baseline(job("acme", "1", published=ago(days=30)))
        self.w.listings[self.board.key] = listing(job("acme", "1", published=ago(days=30)), complete=False)
        self.w.run(minutes_later=60)
        self.w.listings[self.board.key] = [job("acme", "1", published=ago(days=30)), job("acme", "2", published=ago(days=30))]
        self.w.run(minutes_later=60)
        self.assertEqual((self.row().relevant_jobs, self.row().complete_polls), (2, 2))

    def test_smartrecruiters_listing_cut_at_the_paging_cap_is_marked_incomplete(self) -> None:
        pages = []

        def fake_get(url: str, params: Any = None) -> Any:
            off = (params or {}).get("offset", 0)
            pages.append(off)
            content = [{"id": str(700000000000 + off + i), "name": "Marketing Intern"} for i in range(100)]
            return {"content": content, "totalFound": 9000}

        original = bd._get_json
        bd._get_json = fake_get  # type: ignore[assignment]
        try:
            res = bd.fetch_board(bd.BoardId(bd.SMARTRECRUITERS, "Big"))
        finally:
            bd._get_json = original  # type: ignore[assignment]
        self.assertFalse(getattr(res, "complete", True))
        self.assertLess(len(res), 9000)

    def test_duplicate_listing_rows_count_once(self) -> None:
        self.baseline(job("acme", "1", published=ago(days=30)))
        self.w.listings[self.board.key] = [job("acme", "1", published=ago(days=30)), job("acme", "1", published=ago(days=30))]
        self.w.run(minutes_later=60)
        self.assertEqual(self.row().relevant_jobs, 1)


# --------------------------------------------------------------------------- activity


class ActivityTests(HarnessCase):
    def row(self) -> bd.BoardRecord:
        return self.w.state.load_boards()[self.board.key]

    def pass_of(self, jid: str) -> str:
        return str(self.w.states()[self.key(jid)].seen_detail.get("pass", ""))

    def index(self) -> pools.ActivityIndex:
        return pools.ActivityIndex.from_states(self.w.states())

    def test_first_baseline_pass_starts_a_stint_and_is_not_activity(self) -> None:
        self.baseline(job("acme", "1", published=ago(days=30)), job("acme", "2", published=ago(minutes=30)))
        rec = self.row()
        self.assertEqual((rec.activity_since, rec.complete_polls, rec.baselined_at), (stamp(T0), 1, stamp(T0)))
        self.assertEqual(self.w.states()[self.key("2")].freshness, fr.VERIFIED_FRESH)  # the time-fresh one is still alertable ...
        self.assertEqual((self.pass_of("1"), self.pass_of("2")), ("baseline", "baseline"))  # ... but is baseline-pass, not activity
        self.assertEqual(self.index().times(self.board.key), [])
        self.assertEqual((rec.new_relevant_7d, rec.new_relevant_30d, rec.last_new_relevant_at), (None, None, ""))

    def test_flood_rebaseline_observations_are_not_activity(self) -> None:
        self.baseline(*[job("acme", str(i), published=ago(days=30)) for i in range(5)])
        flood = [job("acme", str(i), published=ago(days=30)) for i in range(5)] + [job("acme", f"n{i}", published="") for i in range(40)]
        self.w.listings[self.board.key] = flood
        self.w.run(minutes_later=60)
        self.assertEqual({self.pass_of(f"n{i}") for i in range(40)}, {"baseline"})
        self.assertEqual(self.index().times(self.board.key), [])

    def test_counts_are_unknown_before_seven_days_and_a_real_zero_after(self) -> None:
        self.baseline(job("acme", "1", published=ago(days=30)))
        self.w.listings[self.board.key].append(job("acme", "9", published=""))
        self.w.run(minutes_later=60)
        seen_at = stamp(self.w.now)
        rec = self.row()
        self.assertEqual((rec.new_relevant_7d, rec.new_relevant_30d, rec.last_new_relevant_at), (None, None, seen_at))  # unknown, not zero
        self.w.run(minutes_later=60 * 24 * 3)
        self.assertIsNone(self.row().new_relevant_7d)  # still a short stint
        self.w.run(minutes_later=60 * 24 * 5)  # 8 days after the baseline, 8 days after the observation
        rec = self.row()
        self.assertEqual((rec.new_relevant_7d, rec.new_relevant_30d), (0, 1))
        self.assertEqual(rec.last_new_relevant_at, seen_at)

    def test_recent_activity_is_counted_in_the_seven_day_window(self) -> None:
        self.baseline(job("acme", "1", published=ago(days=30)))
        self.w.run(minutes_later=60 * 24 * 8)  # stint is now 8 days old
        self.w.listings[self.board.key].append(job("acme", "9", published=""))
        self.w.run(minutes_later=60)
        rec = self.row()
        self.assertEqual((rec.new_relevant_7d, rec.new_relevant_30d), (1, 1))

    def test_filtered_stale_and_search_found_jobs_never_count(self) -> None:
        self.baseline(job("acme", "1", published=ago(days=30)))
        later = T0 + timedelta(minutes=60)
        found = job("acme", "s1", published=ago(minutes=30, base=later))
        self.w.listings[self.board.key] += [
            job("acme", "gated", title="Software Engineer", published=""),
            job("acme", "stale", published=ago(days=40, base=later)),
        ]
        self.w.run(
            minutes_later=60, discover=lambda ctx: dsc.DiscoveryResult(jobs=[pl.SerperJob(found.ident, found.title, found.url)]),
            hydrate_listed=lambda s: found, force_discovery=True,
        )  # fmt: skip
        self.assertEqual(self.w.states()[self.key("s1")].seen_detail["source"], "serper")
        self.w.run(minutes_later=60 * 24 * 8)
        rec = self.row()
        self.assertEqual((rec.new_relevant_7d, rec.new_relevant_30d, rec.last_new_relevant_at), (0, 0, ""))

    def test_legacy_board_starts_its_history_at_its_baseline(self) -> None:
        self.baseline(job("acme", "1", published=ago(days=30)))
        rec = self.row()
        rec.activity_since, rec.complete_polls = "", 0  # a row written before evidence existed
        self.w.state.save_boards([rec])
        self.w.run(minutes_later=60)
        rec = self.row()
        self.assertEqual((rec.activity_since, rec.complete_polls), (rec.baselined_at, 1))


# --------------------------------------------------------------------------- re-entry


class ReentryTests(HarnessCase):
    def setUp(self) -> None:
        super().setUp()
        self.baseline(job("acme", "1", published=ago(days=30)))
        rec = self.w.state.load_boards()[self.board.key]
        rec.status = bd.STATUS_NEW  # as a demotion + promotion leaves it: baseline kept, status new
        self.w.state.save_boards([rec])
        self.later = T0 + timedelta(days=3)

    def row(self) -> bd.BoardRecord:
        return self.w.state.load_boards()[self.board.key]

    def reenter(self, *extra: bd.ListedJob) -> None:
        self.w.listings[self.board.key] = [job("acme", "1", published=ago(days=30)), *extra]
        self.w.run(minutes_later=60 * 24 * 3)

    def test_gap_jobs_are_judged_by_source_evidence_only(self) -> None:
        self.reenter(
            job("acme", "undated", published=""),
            job("acme", "dated", published=ago(days=2, base=self.later)),
            job("acme", "fresh", published=ago(minutes=30, base=self.later)),
        )  # fmt: skip
        st = {j: self.w.states()[self.key(j)] for j in ("undated", "dated", "fresh")}
        self.assertEqual((st["undated"].freshness, st["undated"].disposition), (fr.BASELINE, lg.BASELINED))
        self.assertIn("while the board was not monitored", st["undated"].seen_detail["evidence"])
        self.assertEqual((st["dated"].freshness, st["dated"].disposition), (fr.RECENT, lg.PENDING))
        self.assertEqual((st["fresh"].freshness, st["fresh"].disposition), (fr.VERIFIED_FRESH, lg.PENDING))
        self.assertEqual(self.w.calls[self.key("undated")], 0)  # baseline: never evaluated
        self.assertEqual((self.w.calls[self.key("dated")], self.w.calls[self.key("fresh")]), (1, 1))
        self.assertEqual([a["freshness"] for a in self.w.alerts], [fr.VERIFIED_FRESH])  # only the verified-fresh one is pushed
        self.assertEqual(len(self.w.tracker), 2)  # the recent one reaches the tracker silently

    def test_known_ids_are_not_observed_again_and_the_board_restarts_its_stint(self) -> None:
        self.reenter(job("acme", "undated", published=""))
        self.assertEqual(len(self.w.events(self.key("1"), lg.SEEN)), 1)
        rec = self.row()
        self.assertEqual((rec.status, rec.baselined_at, rec.activity_since), (bd.STATUS_ACTIVE, stamp(self.w.now), stamp(self.w.now)))
        self.assertEqual((rec.complete_polls, rec.new_relevant_7d, rec.new_relevant_30d), (1, None, None))

    def test_reentry_observations_are_not_activity(self) -> None:
        self.reenter(job("acme", "dated", published=ago(days=2, base=self.later)), job("acme", "fresh", published=ago(minutes=30, base=self.later)))
        for jid in ("dated", "fresh"):
            self.assertEqual(self.w.states()[self.key(jid)].seen_detail["pass"], "reentry")
        self.assertEqual(pools.ActivityIndex.from_states(self.w.states()).times(self.board.key), [])
        self.assertEqual(self.row().last_new_relevant_at, "")

    def test_flood_rule_is_not_applied_to_a_reentry_pass(self) -> None:
        many = [job("acme", f"g{i}", published=ago(days=2, base=self.later)) for i in range(35)]
        self.reenter(*many)
        self.assertNotIn("re-baselined", self.w.state.load_runs()[-1].notes)
        by = {self.w.states()[self.key(f"g{i}")].freshness for i in range(35)}
        self.assertEqual(by, {fr.RECENT})  # judged by their own dates, not blanket-baselined

    def test_failed_reentry_poll_leaves_the_board_waiting_to_re_enter(self) -> None:
        self.w.listings[self.board.key] = bd.BoardError("HTTP 503")
        self.w.run(minutes_later=60 * 24 * 3)
        self.assertEqual(self.row().status, bd.STATUS_NEW)
        self.reenter(job("acme", "undated", published=""))
        self.assertEqual(self.row().status, bd.STATUS_ACTIVE)
        self.assertEqual(self.w.states()[self.key("undated")].freshness, fr.BASELINE)


# --------------------------------------------------------------------------- title gate audit (D-25)


class TitleGateVariantTests(unittest.TestCase):
    def gate(self, title: str) -> str | None:
        return el.title_gate(title, S.roles, S.levels, EXCLUDED)

    def test_variants_apply_only_to_levels_the_user_configured(self) -> None:
        self.assertIsNotNone(el.title_gate("Marketing Internship", ["Marketing"], ["Associate"], None))
        self.assertIsNone(el.title_gate("Marketing Internship", ["Marketing"], ["Intern"], None))
        self.assertIsNotNone(el.title_gate("Marketing Jr.", ["Marketing"], ["Intern"], None))
        self.assertIsNone(el.title_gate("Marketing Jr.", ["Marketing"], ["Junior"], None))

    def test_location_rule_is_shared_with_the_hard_gate(self) -> None:
        self.assertIsNone(el.location_blocks(""))
        self.assertIsNone(el.location_blocks("Remote"))
        self.assertIn("outside the US", el.location_blocks("London") or "")
        self.assertIsNone(el.location_blocks("New York; London"))


if __name__ == "__main__":
    unittest.main()
