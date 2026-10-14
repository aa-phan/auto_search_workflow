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
from test_core import T0, EXCLUDED, S, HarnessCase, ago, done, job  # noqa: E402
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



# --------------------------------------------------------------------------- pure pool helpers


def mk(name: str, pool: str, *, n30: int | None = 0, open_: int = 3, polls: int = 200, fail: int = 0, rel_hours: float = 1.0,
       trial_end_hours: float = -1.0, streak: int = 0, trials: int = 1, stint_days: int = 60, status: str = bd.STATUS_ACTIVE) -> bd.BoardRecord:
    """A monitored board with its evidence set directly. Score = 2 x min(n30 x 7 / 30, 5) + min(open, 5)."""
    return bd.BoardRecord(
        "greenhouse", name, ago(days=90), "s", status, baselined_at=ago(days=60), last_success_at=ago(hours=1), validation=bd.V_VALID,
        relevant_jobs=open_, eligible_jobs=open_, relevance_at=ago(minutes=int(rel_hours * 60)), activity_since=ago(days=stint_days),
        complete_polls=polls, new_relevant_7d=None if n30 is None else 0, new_relevant_30d=n30, pool=pool, pool_since=ago(days=10),
        trial_until=stamp(T0 + timedelta(hours=trial_end_hours)) if pool == pools.POOL_EXPLORATION else "", weak_streak=streak,
        trials=trials, consecutive_failures=fail,
    )  # fmt: skip


def wait(name: str, open_: int = 3, trials: int = 0) -> bd.BoardRecord:
    return bd.BoardRecord(
        "greenhouse", name, ago(days=90), "s", bd.STATUS_VALIDATED, validation=bd.V_VALID, last_validated_at=ago(days=2),
        relevant_jobs=open_, eligible_jobs=open_, trials=trials, pool_since=ago(days=2),
    )  # fmt: skip


def reg(*recs: bd.BoardRecord) -> dict[str, bd.BoardRecord]:
    return {r.key: r for r in recs}


STRONG = {"n30": 30, "open_": 5}  # score 15
WEAK = {"n30": 0, "open_": 1}  # score 1
EST, EXP = pools.POOL_ESTABLISHED, pools.POOL_EXPLORATION


def policy(**kw: Any) -> pools.PoolPolicy:
    base = {"max_active": 100, "exploration_pct": 50, "exploration_days": 7, "rebalance_every_days": 7, "max_replacements": 20, "mode": "on"}
    return pools.PoolPolicy(**{**base, **kw})


def actions(plan: pools.RebalancePlan) -> dict[str, str]:
    return {d.key: d.action for d in plan.decisions}


class PolicyAndScoreTests(unittest.TestCase):
    def test_default_targets_split_the_cap_80_20(self) -> None:
        p = pools.PoolPolicy()
        self.assertEqual((p.max_active, p.exploration_target, p.established_target, p.min_complete_polls), (500, 100, 400, 84))
        self.assertEqual((pools.PoolPolicy(max_active=3, exploration_pct=34).exploration_target, pools.PoolPolicy(max_active=3, exploration_pct=34).established_target), (1, 2))
        self.assertEqual(pools.PoolPolicy(exploration_pct=0).established_target, 500)
        self.assertEqual(pools.PoolPolicy(exploration_pct=100).exploration_target, 500)

    def test_score_formula_and_caps(self) -> None:
        self.assertEqual(pools.score(mk("a", EST, n30=30, open_=5), T0), 15.0)  # rate capped at 5/week, open capped at 5
        self.assertEqual(pools.score(mk("a", EST, n30=300, open_=500), T0), 15.0)  # an aggregator cannot exceed the caps
        self.assertEqual(pools.score(mk("a", EST, n30=0, open_=2), T0), 2.0)
        self.assertIsNone(pools.score(mk("a", EST, n30=None), T0))

    def test_score_has_no_tenure_term(self) -> None:
        young = mk("young", EST, n30=3, open_=4, stint_days=10)  # 3 new in 10 days = 2.1 / week
        old = mk("old", EST, n30=9, open_=4, stint_days=300)  # 9 new in the last 30 days = 2.1 / week
        self.assertEqual(pools.score(young, T0), pools.score(old, T0))

    def test_evidence_problems(self) -> None:
        p = policy()
        self.assertIsNone(pools.evidence_problem(mk("ok", EST), T0, p))
        self.assertIn("stint shorter", pools.evidence_problem(mk("a", EST, n30=None), T0, p) or "")
        self.assertIn("10 complete polls, need 84", pools.evidence_problem(mk("a", EST, polls=10), T0, p) or "")
        self.assertIn("last poll failed", pools.evidence_problem(mk("a", EST, fail=1), T0, p) or "")
        self.assertIn("older than 24 h", pools.evidence_problem(mk("a", EST, rel_hours=30), T0, p) or "")
        blank = mk("a", EST)
        blank.relevance_at = ""
        self.assertIn("older than 24 h", pools.evidence_problem(blank, T0, p) or "")


class PolicyParkingTests(HarnessCase):
    sr = bd.BoardId(bd.SMARTRECRUITERS, "SrCo")

    def seed_monitored_sr(self) -> bd.BoardRecord:
        rec = bd.BoardRecord(
            bd.SMARTRECRUITERS, "SrCo", ago(days=30), "serper", bd.STATUS_ACTIVE, baselined_at=ago(days=20), last_success_at=ago(hours=1),
            validation=bd.V_VALID, last_validated_at=ago(hours=1), relevant_jobs=2, provenance={"serper": {"first": ago(days=30)}},
            pool=EXP, trials=1,
        )  # fmt: skip
        self.w.state.save_boards([rec])
        self.w.state.append_events([lg.Event(ago(days=20), "smartrecruiters|srco|743999000", lg.SEEN, fr.BASELINE, lg.BASELINED, "", {"board": "SrCo", "source": "poll"})])
        self.w.listings[self.sr.key] = [job("SrCo", "743999000", ats=bd.SMARTRECRUITERS, published=ago(days=30))]
        return rec

    def test_monitored_smartrecruiters_board_is_parked_with_history_kept(self) -> None:
        before = self.seed_monitored_sr()
        events_before = self.w.state.load_events()
        run = self.w.run()
        rec = self.w.state.load_boards()[self.sr.key]
        self.assertEqual((rec.status, rec.validation, rec.pool, run.parked_policy), (bd.STATUS_DEFERRED, bd.V_DEFERRED, "", 1))
        self.assertIn("robots.txt", rec.last_error)
        self.assertIn("parked", rec.pool_reason)
        self.assertEqual((rec.baselined_at, rec.last_success_at, rec.provenance, rec.last_validated_at), (before.baselined_at, before.last_success_at, before.provenance, before.last_validated_at))
        self.assertEqual(self.w.state.load_events(), events_before)  # nothing in the ledger changed
        self.assertEqual(run.boards_total, 0)  # not polled in the very run that parked it
        self.assertIn("parked by provider policy", run.notes)

    def test_parked_board_is_not_fetched_in_later_runs(self) -> None:
        self.seed_monitored_sr()
        self.w.run()
        del self.w.listings[self.sr.key]  # a fetch would now raise and count as a failed board
        run = self.w.run(minutes_later=60)
        self.assertEqual((run.boards_total, run.boards_failed, run.parked_policy), (0, 0, 0))

    def test_opted_in_smartrecruiters_stays_monitored(self) -> None:
        self.seed_monitored_sr()
        run = self.w.run(allow_smartrecruiters=True)
        self.assertEqual((self.w.state.load_boards()[self.sr.key].status, run.boards_total, run.parked_policy), (bd.STATUS_ACTIVE, 1, 0))

    def test_waiting_smartrecruiters_board_is_never_activated_while_blocked(self) -> None:
        rec = wait("x")
        rec.ats, rec.board = bd.SMARTRECRUITERS, "SrWait"
        blocked = lambda ats: ats == bd.SMARTRECRUITERS  # noqa: E731
        self.assertEqual(bd.activate_waiting(reg(rec), max_monitored=10, per_run=10, now=T0, blocked=blocked), [])
        self.assertEqual(len(bd.activate_waiting(reg(rec), max_monitored=10, per_run=10, now=T0)), 1)


class AdmissionPoolTests(unittest.TestCase):
    def test_promotion_enters_exploration_on_a_dated_trial_and_never_exceeds_the_caps(self) -> None:
        registry = reg(*[wait(f"w{i}", open_=i + 1) for i in range(10)])
        promoted = bd.activate_waiting(registry, max_monitored=6, per_run=4, now=T0, trial_days=7)
        self.assertEqual(len(promoted), 4)
        for r in promoted:
            self.assertEqual((r.status, r.pool, r.trials, r.trial_until, r.pool_since, r.weak_streak), (bd.STATUS_NEW, EXP, 1, stamp(T0 + timedelta(days=7)), stamp(T0), 0))
            self.assertIn("explore 2026-10-14: trial until 2026-10-21", r.pool_reason)
            self.assertIn("first trial", r.pool_reason)
        bd.activate_waiting(registry, max_monitored=6, per_run=4, now=T0)
        bd.activate_waiting(registry, max_monitored=6, per_run=4, now=T0)
        self.assertEqual(sum(1 for r in registry.values() if r.status in bd.MONITORED), 6)  # hard ceiling

    def test_boards_never_tried_enter_before_boards_that_had_a_trial(self) -> None:
        registry = reg(wait("tried", open_=9, trials=1), wait("fresh1", open_=2), wait("fresh2", open_=3))
        picked = bd.activate_waiting(registry, max_monitored=2, per_run=2, now=T0)
        self.assertEqual([r.board for r in picked], ["fresh2", "fresh1"])  # most open jobs first among the untried
        again = bd.activate_waiting(reg(wait("tried", open_=9, trials=1)), max_monitored=5, per_run=5, now=T0)
        self.assertIn("re-entry, trial 2", again[0].pool_reason)

    def test_board_without_eligible_jobs_waits_even_if_it_has_relevant_ones(self) -> None:
        a = wait("abroad", open_=5)
        a.eligible_jobs = 0  # relevant titles, all outside the US
        unknown = wait("unmeasured", open_=2)
        unknown.eligible_jobs = None  # old row: falls back to the relevant count
        picked = bd.activate_waiting(reg(a, unknown), max_monitored=5, per_run=5, now=T0)
        self.assertEqual([r.board for r in picked], ["unmeasured"])

    def test_legacy_monitored_boards_are_labelled_exploration_trials(self) -> None:
        legacy = mk("legacy", "", n30=None)
        res = pools.sync_pools(reg(legacy), policy(), T0)
        self.assertEqual((legacy.pool, legacy.trials, legacy.trial_until), (EXP, 2, stamp(T0 + timedelta(days=7))))  # mk() already counts one trial
        self.assertEqual(res.migrated, [legacy.key])
        fresh = bd.BoardRecord("greenhouse", "old", "t", "s", bd.STATUS_ACTIVE)
        pools.sync_pools(reg(fresh), policy(), T0)
        self.assertEqual((fresh.pool, fresh.trials), (EXP, 1))
        self.assertIn("migrated 2026-10-14: monitored before pools existed", fresh.pool_reason)

    def test_stale_pool_labels_are_cleared_when_a_board_stops_being_monitored(self) -> None:
        dead = mk("dead", EST, status=bd.STATUS_DISABLED)
        res = pools.sync_pools(reg(dead), policy(), T0)
        self.assertEqual((dead.pool, dead.weak_streak, res.cleared), ("", 0, [dead.key]))
        self.assertIn("left monitoring 2026-10-14: disabled", dead.pool_reason)
        self.assertEqual(dead.baselined_at, ago(days=60))  # history untouched

    def test_sync_is_deterministic_and_idempotent(self) -> None:
        a, b = mk("a", ""), mk("b", "")
        pools.sync_pools(reg(b, a), policy(), T0)
        again = pools.sync_pools(reg(a, b), policy(), T0)
        self.assertEqual(again.changed, {})


class RebalancePlanTests(unittest.TestCase):
    def test_first_weak_cycle_defers_and_nothing_leaves(self) -> None:
        registry = reg(mk("e1", EST, **WEAK), mk("t1", EXP, **STRONG))
        plan = pools.plan_rebalance(registry, policy(max_active=2), T0)
        self.assertEqual(actions(plan), {"greenhouse|t1": "defer"})
        self.assertEqual(plan.streaks, {"greenhouse|e1": 1})
        pools.apply_plan(registry, plan, T0)
        self.assertEqual((registry["greenhouse|e1"].pool, registry["greenhouse|e1"].weak_streak, registry["greenhouse|t1"].pool), (EST, 1, EXP))
        self.assertTrue(registry["greenhouse|t1"].pool_reason.startswith("rebalance 2026-10-14: "))

    def test_second_weak_cycle_replaces(self) -> None:
        registry = reg(mk("e1", EST, streak=1, **WEAK), mk("t1", EXP, **STRONG), wait("w1"))
        plan = pools.plan_rebalance(registry, policy(max_active=2), T0)
        self.assertEqual(plan.decisions[0].action, "replace")
        self.assertEqual((plan.decisions[0].key, plan.decisions[0].partner), ("greenhouse|t1", "greenhouse|e1"))
        changed = pools.apply_plan(registry, plan, T0)
        e1, t1 = registry["greenhouse|e1"], registry["greenhouse|t1"]
        self.assertEqual((t1.pool, t1.trial_until, t1.status), (EST, "", bd.STATUS_ACTIVE))
        self.assertEqual((e1.status, e1.pool, e1.weak_streak, e1.activity_since, e1.complete_polls, e1.new_relevant_30d), (bd.STATUS_VALIDATED, "", 0, "", 0, None))
        self.assertEqual((e1.baselined_at, e1.validation, e1.relevant_jobs, e1.last_success_at), (ago(days=60), bd.V_VALID, 1, ago(hours=1)))  # state kept
        self.assertEqual({r.key for r in changed}, {e1.key, t1.key})

    def test_replacements_are_bounded_per_cycle(self) -> None:
        trials = [mk(f"t{i:02d}", EXP, **STRONG) for i in range(50)]
        weak = [mk(f"e{i:02d}", EST, streak=1, **WEAK) for i in range(60)]
        registry = reg(*trials, *weak)
        plan = pools.plan_rebalance(registry, policy(max_active=200, exploration_pct=70, max_replacements=20), T0)
        self.assertEqual((plan.count("replace"), plan.count("defer"), plan.replacements), (20, 30, 20))
        pools.apply_plan(registry, plan, T0)
        self.assertEqual(sum(1 for r in registry.values() if r.status == bd.STATUS_VALIDATED), 20)  # exactly 20 established boards left
        self.assertEqual(sum(1 for r in registry.values() if r.pool == EST), 60)  # 40 stayed + 20 graduated
        deferred_victims = {d.partner for d in plan.decisions if d.action == "defer"}
        self.assertTrue(all(registry[k].weak_streak == 2 and registry[k].pool == EST for k in deferred_victims))

    def test_running_trials_are_never_touched(self) -> None:
        running = mk("running", EXP, trial_end_hours=48, **STRONG)
        soon = mk("soon", EXP, trial_end_hours=0.5, **STRONG)  # ends within the slack: counts as ended
        thin = mk("thin", EXP, polls=10, **STRONG)  # ended, but only 10 complete polls (need 84)
        registry = reg(running, soon, thin, mk("e1", EST, **WEAK))
        plan = pools.plan_rebalance(registry, policy(max_active=4), T0)
        self.assertNotIn(running.key, actions(plan))
        self.assertEqual(plan.protected_trials, 1)
        self.assertEqual(actions(plan)[thin.key], "extend")
        self.assertIn("10 complete polls, need 84", [d.reason for d in plan.decisions if d.key == thin.key][0])
        self.assertIn(soon.key, actions(plan))
        pools.apply_plan(registry, plan, T0)
        self.assertEqual((thin.pool, thin.trial_until), (EXP, stamp(T0 + timedelta(days=7))))
        self.assertEqual((running.pool, running.trial_until, running.pool_reason), (EXP, stamp(T0 + timedelta(hours=48)), ""))

    def test_thin_evidence_never_demotes_and_resets_the_streak(self) -> None:
        weakish = {"n30": 0, "open_": 1}
        thin = [
            mk("failed", EST, fail=1, streak=1, **weakish), mk("old", EST, rel_hours=30, streak=1, **weakish),
            mk("unknown", EST, n30=None, streak=1, open_=1), mk("few", EST, polls=5, streak=1, **weakish),
        ]  # fmt: skip
        registry = reg(*thin, mk("t1", EXP, **STRONG), wait("w1"))
        plan = pools.plan_rebalance(registry, policy(max_active=5), T0)
        self.assertEqual(plan.unevidenced_established, 4)
        for r in thin:
            self.assertNotIn(r.key, actions(plan))
            self.assertEqual(plan.streaks[r.key], 0)
        self.assertNotIn("replace", actions(plan).values())
        self.assertEqual(actions(plan)["greenhouse|t1"], "defer")  # nothing evidence-backed to compare with: the trial is not thrown away
        pools.apply_plan(registry, plan, T0)
        self.assertTrue(all(r.pool == EST and r.status == bd.STATUS_ACTIVE and r.weak_streak == 0 for r in thin))

    def test_a_margin_of_one_or_less_never_replaces(self) -> None:
        for open_g, expect in ((3, "no replace"), (4, "defer")):
            registry = reg(mk("e1", EST, n30=0, open_=2, streak=1), mk("t1", EXP, n30=0, open_=open_g))  # scores 2.0 vs 3.0 / 4.0
            plan = pools.plan_rebalance(registry, policy(max_active=2), T0)
            if expect == "no replace":
                self.assertNotIn(actions(plan)["greenhouse|t1"], ("replace", "defer"))  # exactly 1.0 apart: not enough
            else:
                self.assertEqual(actions(plan)["greenhouse|t1"], "replace")  # 2.0 apart and a second weak cycle

    def test_free_established_slots_graduate_ended_trials_without_a_victim(self) -> None:
        registry = reg(mk("e1", EST, **STRONG), mk("t1", EXP, **STRONG), mk("t2", EXP, n30=0, open_=1))
        plan = pools.plan_rebalance(registry, policy(max_active=6, exploration_pct=50), T0)  # established target 3, one filled
        self.assertEqual(sorted(actions(plan).values()), ["graduate", "graduate"])
        self.assertEqual(plan.replacements, 0)

    def test_losing_trials_return_only_as_many_as_there_are_waiting_boards_weakest_first(self) -> None:
        trials = [mk(f"t{i}", EXP, n30=0, open_=1 + (i % 2)) for i in range(5)]  # scores 1 and 2: none beats e1 (score 3) by more than 1
        registry = reg(mk("e1", EST, n30=0, open_=3), *trials, wait("w1"), wait("w2"))
        plan = pools.plan_rebalance(registry, policy(max_active=6, exploration_pct=84), T0)  # established target 1, filled
        self.assertEqual((plan.waiting, plan.count("return"), plan.count("keep")), (2, 2, 3))
        returned = sorted(d.score for d in plan.decisions if d.action == "return")
        self.assertEqual(returned, [1.0, 1.0])  # the two weakest go back
        registry2 = reg(mk("e1", EST, n30=0, open_=3), *[mk(f"t{i}", EXP, n30=0, open_=1) for i in range(3)])
        self.assertEqual(pools.plan_rebalance(registry2, policy(max_active=6, exploration_pct=84), T0).count("return"), 0)  # nobody waiting: nobody is freed

    def test_capacity_cut_sheds_lowest_scores_and_never_trials_or_unevidenced_boards(self) -> None:
        registry = reg(
            mk("e1", EST, **STRONG), mk("e2", EST, n30=15, open_=3), mk("e3", EST, **WEAK),
            mk("running", EXP, trial_end_hours=48, **STRONG), mk("endweak", EXP, **WEAK), mk("thin", EXP, polls=3, **STRONG),
        )  # fmt: skip
        plan = pools.plan_rebalance(registry, policy(max_active=3, exploration_pct=34, max_replacements=1), T0)
        shed = {d.key for d in plan.decisions if d.action == "shed"}
        self.assertEqual(shed, {"greenhouse|endweak", "greenhouse|e3"})  # an ended weak trial first, then the weakest established board
        self.assertNotIn("greenhouse|running", actions(plan))
        self.assertEqual(actions(plan)["greenhouse|thin"], "extend")
        self.assertEqual(plan.replacements, 1)  # the established shed counts against the bound; e2 stays although still over the cap
        pools.apply_plan(registry, plan, T0)
        self.assertEqual((registry["greenhouse|e3"].status, registry["greenhouse|endweak"].status), (bd.STATUS_VALIDATED, bd.STATUS_VALIDATED))

    def test_same_registry_in_any_insertion_order_gives_identical_decisions(self) -> None:
        recs = [mk(f"t{i}", EXP, n30=i, open_=2) for i in range(8)] + [mk(f"e{i}", EST, n30=1, open_=1, streak=1) for i in range(8)] + [wait(f"w{i}") for i in range(3)]
        one = pools.plan_rebalance(reg(*recs), policy(max_active=16, exploration_pct=50, max_replacements=3), T0)
        two = pools.plan_rebalance(reg(*reversed(recs)), policy(max_active=16, exploration_pct=50, max_replacements=3), T0)
        self.assertEqual(one, two)
        self.assertEqual(pools.plan_json(one, T0, "on"), pools.plan_json(two, T0, "on"))

    def test_report_mode_and_json_are_compact(self) -> None:
        registry = reg(*[mk(f"t{i:03d}", EXP, **STRONG) for i in range(400)], *[mk(f"e{i:03d}", EST, streak=1, **WEAK) for i in range(400)])
        plan = pools.plan_rebalance(registry, policy(max_active=1000, exploration_pct=50, max_replacements=400), T0)
        text = pools.plan_json(plan, T0, "report")
        self.assertLessEqual(len(text), pools.MAX_REPORT_JSON)
        self.assertIn('"omitted_decisions"', text)  # truncated with a count, never silently

    def test_due_rule_uses_the_record_and_the_rows(self) -> None:
        p = policy()
        self.assertTrue(pools.rebalance_due(None, {}, T0, p))
        self.assertFalse(pools.rebalance_due(f'{{"at":"{ago(hours=1)}"}}', {}, T0, p))
        self.assertTrue(pools.rebalance_due(f'{{"at":"{ago(days=7, hours=-1)}"}}', {}, T0, p))  # an hour of slack
        self.assertTrue(pools.rebalance_due("not json", {}, T0, p))
        marked = mk("m", EST)
        marked.pool_reason, marked.pool_since = "rebalance 2026-10-14: replaced", ago(hours=1)  # no record saved, but rows say it ran
        self.assertFalse(pools.rebalance_due(None, reg(marked), T0, p))
        marked.pool_since = ""
        self.assertFalse(pools.rebalance_due(None, reg(marked), T0, p))  # date-only evidence is still enough within the same day

    def test_established_board_streak_resets_when_not_a_target(self) -> None:
        registry = reg(mk("e1", EST, streak=1, **STRONG), mk("t1", EXP, **WEAK))
        plan = pools.plan_rebalance(registry, policy(max_active=2), T0)
        self.assertEqual(plan.streaks, {"greenhouse|e1": 0})
        pools.apply_plan(registry, plan, T0)
        self.assertEqual(registry["greenhouse|e1"].weak_streak, 0)


class CoverageTests(unittest.TestCase):
    def test_coverage_numbers(self) -> None:
        registry = reg(mk("e1", EST), mk("e2", EST, open_=0), mk("t1", EXP), wait("w1"), wait("w2", open_=0))
        registry["greenhouse|w1"].pool_since = ago(hours=30)
        cov = pools.coverage(registry, T0)
        self.assertEqual((cov["established"], cov["exploration"], cov["waiting"], cov["oldest_waiting_hours"]), (2, 1, 1, 30))
        self.assertEqual(cov["coverage_pct"], round(100 * 2 / 3))  # 2 monitored boards with open jobs, 1 relevant waiting
        self.assertIsNone(pools.coverage({}, T0)["coverage_pct"])


# --------------------------------------------------------------------------- pipeline: rebalance end to end


def rebalance_policy(**kw: Any) -> pools.PoolPolicy:
    base = {"exploration_pct": 50, "exploration_days": 1, "rebalance_every_days": 1, "max_replacements": 1, "mode": "on"}
    return pools.PoolPolicy(**{**base, **kw})


class RebalancePipelineTests(HarnessCase):
    weak = bd.BoardId(bd.GREENHOUSE, "weak")
    strong = bd.BoardId(bd.GREENHOUSE, "strong")

    def setUp(self) -> None:
        super().setUp()
        self.w.listings[self.weak.key] = [job("weak", "w1", published=ago(days=30))]
        self.w.listings[self.strong.key] = [job("strong", "s1", published=ago(days=30))]
        self.kw: dict[str, Any] = {"max_monitored_boards": 2, "pool_policy": rebalance_policy()}

    def mature(self, *, weak_streak: int = 1) -> None:
        """First run admits both boards on trials; then age them: `weak` is an established board that
        already was a replacement target once, `strong` an ended trial with a month of real activity."""
        run = self.w.run(seeds=[self.weak, self.strong], **self.kw)
        self.assertEqual(run.boards_activated, 2)
        self.w.state.save_discovery_state({}, stamp(T0))  # no rebalance has ever been recorded
        rows = self.w.state.load_boards()
        weak, strong = rows[self.weak.key], rows[self.strong.key]
        weak.pool, weak.weak_streak, weak.trial_until, weak.complete_polls, weak.activity_since = EST, weak_streak, "", 200, ago(days=40)
        strong.trial_until, strong.complete_polls, strong.activity_since = ago(hours=1), 200, ago(days=40)
        self.w.state.save_boards([weak, strong])
        events = []
        for i in range(20):  # real poll observations of new relevant jobs on the strong board over the last month
            k = bd.JobIdentity(bd.GREENHOUSE, "strong", f"a{i}").key
            events.append(lg.Event(ago(days=1 + i), k, lg.SEEN, fr.RECENT, lg.PENDING, "", {"source": "poll", "board": "strong", "title": "Marketing Intern"}))
            events.append(lg.Event(ago(days=1 + i), k, lg.EVALUATED, fr.RECENT, "", "", {"status": "Filtered Out", "alert": False, "visible": False}))
        self.w.state.append_events(events)

    def board(self, b: bd.BoardId) -> bd.BoardRecord:
        return self.w.state.load_boards()[b.key]

    def test_report_mode_records_a_plan_and_changes_no_board(self) -> None:
        self.kw["pool_policy"] = rebalance_policy(mode="report")
        self.mature()
        before = {k: (r.status, r.pool, r.weak_streak, r.trial_until) for k, r in self.w.state.load_boards().items()}
        run = self.w.run(minutes_later=60, **self.kw)
        after = {k: (r.status, r.pool, r.trial_until) for k, r in self.w.state.load_boards().items()}
        self.assertEqual(run.rebalance, "report")
        self.assertEqual({k: v[:2] for k, v in before.items()}, {k: v[:2] for k, v in after.items()})  # nobody moved
        disc = self.w.state.load_discovery_state()
        self.assertIn("replace", disc[pools.REBALANCE_REPORT_KEY])
        self.assertIn('"mode":"report"', disc[pools.REBALANCE_KEY])
        self.assertIn("rebalance report", run.notes)
        self.assertEqual((self.board(self.weak).weak_streak, self.board(self.weak).pool), (1, EST))  # streaks only advance when applied
        again = self.w.run(minutes_later=60, **self.kw)
        self.assertEqual(again.rebalance, "")  # one rebalance per interval

    def test_on_mode_replaces_the_weak_established_board_and_logs_the_transition(self) -> None:
        self.mature()
        with self.assertLogs("hunter", level="INFO") as logs:
            run = self.w.run(minutes_later=60, **self.kw)
        self.assertEqual((run.rebalance, run.graduated, run.demoted), ("applied", 1, 1))
        weak, strong = self.board(self.weak), self.board(self.strong)
        self.assertEqual((strong.pool, strong.status, strong.trial_until), (EST, bd.STATUS_ACTIVE, ""))
        self.assertEqual((weak.status, weak.pool), (bd.STATUS_VALIDATED, ""))
        self.assertTrue(weak.pool_reason.startswith("rebalance 2026-10-14: replaced by greenhouse|strong"))
        text = "\n".join(logs.output)
        self.assertIn("Pool greenhouse|strong: exploration -> established", text)
        self.assertIn("Pool greenhouse|weak: established -> waiting", text)
        self.assertEqual((run.pool_established, run.pool_exploration, run.waiting_relevant), (1, 0, 1))

    def test_first_weak_cycle_only_advances_the_streak(self) -> None:
        self.mature(weak_streak=0)
        run = self.w.run(minutes_later=60, **self.kw)
        self.assertEqual((run.demoted, self.board(self.weak).pool, self.board(self.weak).weak_streak, self.board(self.strong).pool), (0, EST, 1, EXP))

    def test_crash_after_saving_boards_does_not_repeat_the_cycle(self) -> None:
        self.mature()
        real = self.w.state.save_discovery_state

        def fail(values: dict[str, str], stamp_: str) -> None:
            raise OSError("discovery tab unavailable")

        self.w.state.save_discovery_state = fail  # type: ignore[method-assign]
        with self.assertRaises(OSError):
            self.w.run(minutes_later=60, **self.kw)
        self.w.state.save_discovery_state = real  # type: ignore[method-assign]
        self.assertEqual(self.board(self.weak).status, bd.STATUS_VALIDATED)  # the boards were saved before the failure
        again = self.w.run(minutes_later=60, **self.kw)
        self.assertEqual(again.rebalance, "")  # not due: the rows say a rebalance already ran

    def test_demotion_keeps_every_delivery_and_a_returning_board_gets_a_new_trial_and_a_reentry_pass(self) -> None:
        self.mature()
        alert_job = job("weak", "wa", published=ago(minutes=10, base=T0 + timedelta(minutes=60)))
        pending_job = job("weak", "wp", published="")
        self.w.listings[self.weak.key] += [alert_job, pending_job]
        self.w.alert_error = ConnectionError("telegram unreachable")
        self.w.plan[self.key("wp", board="weak")] = [pl.EvalOutcome("transient", message="groq 429")]
        weak_before = self.board(self.weak)
        events_before = self.w.state.load_events()

        run = self.w.run(minutes_later=60, **self.kw)  # the weak board is replaced in this very run
        self.assertEqual(self.board(self.weak).status, bd.STATUS_VALIDATED)
        ka, kp = self.key("wa", board="weak"), self.key("wp", board="weak")
        self.assertEqual((run.alerts_failed, len(self.w.events(ka, lg.EVALUATED)), self.w.events(ka, lg.ALERTED), self.w.alerts), (1, 1, [], []))
        self.assertEqual(self.w.state.load_events()[: len(events_before)], events_before)  # nothing already recorded was touched
        kept = self.board(self.weak)
        self.assertEqual((kept.baselined_at, kept.provenance, kept.relevant_jobs), (weak_before.baselined_at, weak_before.provenance, 3))

        # While the board waits (no relevant open job recorded for it, so it is not re-admitted yet):
        kept.eligible_jobs = 0
        self.w.state.save_boards([kept])
        self.w.alert_error = None
        self.w.plan[kp] = [done("Stretch / Review", 55)]
        self.w.run(minutes_later=60, **self.kw)
        self.assertEqual(self.board(self.weak).status, bd.STATUS_VALIDATED)
        self.assertEqual((len(self.w.alerts), len(self.w.events(ka, lg.ALERTED)), len(self.w.events(kp, lg.EVALUATED))), (1, 1, 1))  # delivered once, evaluated, board still waiting
        self.w.run(minutes_later=60, **self.kw)
        self.assertEqual(len(self.w.alerts), 1)  # exactly once

        # The board comes back (something relevant is open again): second trial and a re-entry pass.
        back = self.board(self.weak)
        back.eligible_jobs = 3
        self.w.state.save_boards([back])
        self.w.listings[self.weak.key] += [job("weak", "gap-undated", published="")]
        self.w.run(minutes_later=60 * 14, **self.kw)  # more than the 12 h window since its last successful poll
        again = self.board(self.weak)
        self.assertEqual((again.trials, again.status, again.pool, again.baselined_at, again.activity_since), (2, bd.STATUS_ACTIVE, EXP, stamp(self.w.now), stamp(self.w.now)))
        self.assertIn("re-entry, trial 2", again.pool_reason)
        gap = self.w.states()[self.key("gap-undated", board="weak")]
        self.assertEqual((gap.freshness, gap.disposition, gap.seen_detail["pass"]), (fr.BASELINE, lg.BASELINED, "reentry"))
        self.assertEqual(again.provenance, weak_before.provenance)

    def test_runs_row_records_pool_membership_and_coverage(self) -> None:
        self.mature()
        run = self.w.run(minutes_later=60, **self.kw)
        stored = self.w.state.load_runs()[-1]
        self.assertEqual(
            (stored.pool_established, stored.pool_exploration, stored.waiting_relevant, stored.graduated, stored.demoted, stored.rebalance),
            (run.pool_established, run.pool_exploration, run.waiting_relevant, 1, 1, "applied"),
        )  # fmt: skip
        self.assertEqual(stored.relevant_coverage_pct, run.relevant_coverage_pct)
        self.assertIsNotNone(stored.oldest_waiting_hours)

    def test_runs_columns_and_rows_line_up(self) -> None:
        self.assertEqual(len(st_mod.RunRecord("t").to_row()), len(st_mod.RUN_COLUMNS))
        self.assertEqual(st_mod.RUN_COLUMNS[-9:], [
            "Pool_Established", "Pool_Exploration", "Waiting_Relevant", "Oldest_Waiting_Hours", "Relevant_Coverage_Pct",
            "Graduated", "Demoted", "Parked_Policy", "Rebalance",
        ])  # fmt: skip
        full = st_mod.RunRecord("t", pool_established=3, pool_exploration=1, waiting_relevant=4, oldest_waiting_hours=12, relevant_coverage_pct=60, graduated=2, demoted=1, parked_policy=5, rebalance="report")
        self.assertEqual(st_mod.RunRecord.from_row([str(c) for c in full.to_row()]), full)
        old = st_mod.RunRecord.from_row(["2026-10-14T00:00:00Z", "no", "1", "1", "0", "0", "0", "0", "0", "0", "0", "", "", "", ""])
        assert old is not None
        self.assertEqual((old.pool_established, old.oldest_waiting_hours, old.relevant_coverage_pct, old.rebalance), (0, None, None, ""))

    def test_a_run_with_no_boards_still_records_zero_coverage(self) -> None:
        run = self.w.run(**self.kw)
        self.assertEqual((run.pool_established, run.pool_exploration, run.waiting_relevant, run.relevant_coverage_pct), (0, 0, 0, None))

    def test_pending_work_does_not_depend_on_board_status(self) -> None:
        """An evaluation or alert queued for a job survives its board leaving monitoring entirely (parked here)."""
        sr = bd.BoardId(bd.SMARTRECRUITERS, "SrCo")
        self.w.state.save_boards([bd.BoardRecord(bd.SMARTRECRUITERS, "SrCo", ago(days=3), "s", bd.STATUS_ACTIVE, baselined_at=ago(days=2), last_success_at=ago(hours=2), validation=bd.V_VALID, relevant_jobs=1, pool=EXP)])
        pending = lg.Event(ago(hours=2), "smartrecruiters|srco|743999111", lg.SEEN, fr.OBSERVED_NEW, lg.PENDING, "", {"board": "SrCo", "source": "poll", "title": "Marketing Intern", "url": "https://u"})
        self.w.state.append_events([pending])
        self.w.listings[sr.key] = []
        self.w.run(**self.kw)
        self.assertEqual(self.board(sr).status, bd.STATUS_DEFERRED)
        self.assertEqual(self.w.calls["smartrecruiters|srco|743999111"], 1)  # still evaluated although the board is parked


if __name__ == "__main__":
    unittest.main()
