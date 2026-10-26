"""Offline tests for the Groq daily token governor (D-50, MEAS-03).

Mocked end to end: a pure budget object, fake scorer, CSV-backed state in a temp dir. Nothing here touched
Groq, Sheets, an ATS or Telegram.
"""

from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import discovery as dsc  # noqa: E402
import eval_budget as eb  # noqa: E402
import freshness as fr  # noqa: E402
import boards as bd  # noqa: E402
import ledger as lg  # noqa: E402
import pipeline as pl  # noqa: E402
import state as st_mod  # noqa: E402
from test_core import HarnessCase, T0, ago, job  # noqa: E402

D1 = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)


def load(raw: str | None, now: datetime = D1, **kw: Any) -> eb.GroqBudget:
    return eb.GroqBudget.load(raw, now, budgets=kw.pop("budgets", {"m": 1000}), **kw)


class BudgetTests(unittest.TestCase):
    def test_budget_boundary_cap_minus_one_allows_cap_and_above_refuse(self) -> None:
        b = load(None, budgets={"m": 1000})
        for used, allowed in ((999, True), (1000, False), (1001, False)):
            b.used["m"] = used
            self.assertEqual(b.can_spend("m", fresh=True), allowed, f"fresh at used={used}")

    def test_budget_reserve_refuses_non_fresh_at_80_percent_but_not_fresh(self) -> None:
        b = load(None, budgets={"m": 1000})
        b.used["m"] = 799
        self.assertTrue(b.can_spend("m", fresh=False))
        b.used["m"] = 800
        self.assertFalse(b.can_spend("m", fresh=False))
        self.assertTrue(b.can_spend("m", fresh=True))  # the last 20% is for verified-fresh jobs
        b.used["m"] = 1000
        self.assertFalse(b.can_spend("m", fresh=True))

    def test_budget_rolls_over_at_utc_midnight(self) -> None:
        raw = json.dumps({"day": "2026-10-26", "used": {"m": 700}, "exhausted": ["m"]})
        next_day = load(raw, datetime(2026, 10, 27, 0, 0, 0, tzinfo=timezone.utc))
        self.assertEqual((next_day.used, next_day.exhausted, next_day.rolled_from, next_day.day), ({}, set(), "2026-10-26", "2026-10-27"))
        same_day = load(raw, datetime(2026, 10, 26, 23, 59, 59, tzinfo=timezone.utc))
        self.assertEqual((same_day.used, same_day.exhausted, same_day.rolled_from), ({"m": 700}, {"m"}, ""))
        # a clock in another zone still counts the UTC day
        local = datetime(2026, 10, 26, 19, 0, tzinfo=timezone(timedelta(hours=-5)))  # 00:00 UTC on the 27th
        self.assertEqual(eb.day_of(local), "2026-10-27")

    def test_budget_tolerates_blank_invalid_and_foreign_json(self) -> None:
        for raw in (None, "", "   ", "not json", "[1]", "5", '{"day": 5}', '{"day":"2026-10-26","used":{"m":"x"}}', '{"day":"2026-10-26","used":[1],"exhausted":"m"}'):
            with self.subTest(raw=raw):
                b = load(raw)
                self.assertEqual((b.used, b.exhausted), ({}, set()))
                self.assertTrue(b.can_spend("m", fresh=False))
        mixed = load('{"day":"2026-10-26","used":{"m":5,"n":-1,"o":true,"p":1.5},"exhausted":["m",3]}')
        self.assertEqual((mixed.used, mixed.exhausted), ({"m": 5}, {"m"}))

    def test_budget_zero_never_spends(self) -> None:
        b = load(None, budgets={"m": 0})
        self.assertFalse(b.can_spend("m", fresh=True))
        self.assertFalse(b.can_spend("m", fresh=False))
        self.assertFalse(load(None, budgets={"m": -5}).can_spend("m", fresh=True))  # negative settings clamp to zero
        self.assertFalse(b.can_spend("unknown-model", fresh=True))  # a model without a budget never spends

    def test_budget_json_round_trip_keeps_used_and_exhausted(self) -> None:
        b = load(None)
        b.charge("m", 450)
        b.exhaust("n")
        again = load(b.to_json())
        self.assertEqual((again.used, again.exhausted), ({"m": 450}, {"n"}))
        data = json.loads(b.to_json())
        self.assertEqual(set(data), {"day", "used", "exhausted", "budgets"})
        # persisted budgets are ignored on load: the Settings value wins
        self.assertEqual(load(b.to_json(), budgets={"m": 5}).budgets, {"m": 5})
        self.assertEqual(b.charge("m", -10), None)
        self.assertEqual(b.used["m"], 450)  # a negative charge never refunds

    def test_budget_pick_model_order_is_deterministic(self) -> None:
        b = load(None, budgets={"a": 100, "b": 100})
        self.assertEqual(b.pick_model(["a", "b"], fresh=False), "a")
        self.assertEqual(b.pick_model(["b", "a"], fresh=False), "b")
        self.assertEqual(b.pick_model(["a", "b"], fresh=False, unavailable={"a"}), "b")
        b.used["a"] = 80  # a's non-fresh share (80) is spent
        self.assertEqual(b.pick_model(["a", "b"], fresh=False), "b")
        self.assertEqual(b.pick_model(["a", "b"], fresh=True), "a")
        b.exhaust("a")
        self.assertEqual(b.pick_model(["a", "b"], fresh=True), "b")
        b.used["b"] = 100
        self.assertIsNone(b.pick_model(["a", "b"], fresh=True))
        self.assertIsNone(b.pick_model([], fresh=True))

    def test_budget_integer_floor_for_reserve_cap(self) -> None:
        b = load(None, budgets={"m": 999}, reserve_pct=20)
        self.assertEqual(b.cap("m", fresh=False), 799)
        self.assertEqual(b.cap("m", fresh=True), 999)
        self.assertIsInstance(b.cap("m", fresh=False), int)
        self.assertEqual(load(None, budgets={"m": 1000}, reserve_pct=150).reserve_pct, 100)  # clamped to 0..100
        self.assertEqual(load(None, budgets={"m": 1000}, reserve_pct=-1).cap("m", fresh=False), 1000)

    def test_budget_restore_is_in_place_and_keeps_settings(self) -> None:
        b = load(None, budgets={"m": 1000})
        b.charge("m", 10)
        b.restore(json.dumps({"day": "2026-10-26", "used": {"m": 321}}), D1)
        self.assertEqual((b.used, b.budgets), ({"m": 321}, {"m": 1000}))
        b.restore("", D1 + timedelta(days=1))
        self.assertEqual((b.used, b.day), ({}, "2026-10-27"))

    def test_budget_summary_names_the_day_usage_and_reserve(self) -> None:
        b = load(None, budgets={"m": 170000})
        b.charge("m", 45210)
        self.assertEqual(b.summary(), "groq budget 2026-10-26 UTC: m 45210/170000 (last 20% for verified-fresh jobs)")


class ForcedLimitTests(HarnessCase):
    def budgeted(self, n: int) -> tuple[dict[str, Any], eb.GroqBudget]:
        budget = eb.GroqBudget(day="", budgets={"m": n})
        return {"groq_budget": budget, "can_score": lambda st: budget.pick_model(["m"], fresh=st.freshness == fr.VERIFIED_FRESH) is not None}, budget

    def test_forced_limit_budget_zero_leaves_job_pending_with_no_events_and_no_attempts(self) -> None:
        key = self.fresh_setup()
        kw, _ = self.budgeted(0)
        run = self.w.run(minutes_later=60, **kw)
        self.assertEqual((run.outcome, run.eval_budget_skipped, run.evaluated, run.eval_attempted), ("ok", 1, 0, 0))
        self.assertEqual(self.w.calls[key], 0)  # the scorer was never called
        self.assertEqual(self.w.events(key, lg.ERROR), [])
        self.assertEqual(self.w.events(key, lg.EVALUATED), [])
        self.assertIn("groq daily budget reached: 1 jobs wait (no attempt used)", run.notes)
        st = self.w.states()[key]
        self.assertTrue(lg.needs_evaluation(st))
        self.assertEqual(st.errors, {})

    def test_forced_limit_next_utc_day_scores_the_waiting_job(self) -> None:
        key = self.fresh_setup()
        kw, _ = self.budgeted(0)
        self.w.run(minutes_later=60, **kw)
        kw2, _ = self.budgeted(1000)
        run = self.w.run(minutes_later=24 * 60, **kw2)  # T0 + 25 h: the next UTC day, with a budget
        self.assertEqual((run.outcome, run.evaluated, run.eval_budget_skipped), ("ok", 1, 0))
        self.assertEqual(self.w.calls[key], 1)
        self.assertEqual(len(self.w.events(key, lg.EVALUATED)), 1)

    def test_forced_limit_usage_persists_across_runs_in_discovery_tab(self) -> None:
        key = self.fresh_setup()
        kw, budget = self.budgeted(1000)
        original = self.w.evaluate

        def charging(ident: Any, st: lg.JobState) -> pl.EvalOutcome:
            budget.charge("m", 300)
            return original(ident, st)

        self.w.evaluate = charging  # type: ignore[method-assign]
        slots = dsc.make_slots(["boards.greenhouse.io"], ["Marketing"], [])
        self.w.run(minutes_later=60, discover=lambda ctx: dsc.DiscoveryResult(slots_used=1), rotation_slots=slots, force_discovery=True, **kw)
        self.assertEqual(self.w.calls[key], 1)
        stored = self.w.state.load_discovery_state()
        self.assertEqual(json.loads(stored[eb.GROQ_BUDGET_KEY])["used"], {"m": 300})
        # the rotation cursor, written earlier in the same run, is still there next to the budget key
        self.assertIn(dsc.ROTATION_KEY, stored)
        self.assertIn(dsc.LAST_RUN_KEY, stored)
        self.assertIn(eb.GROQ_BUDGET_KEY, stored)
        # a brand-new budget object on the next run restores the first run's usage from the CSV Discovery file
        kw2, budget2 = self.budgeted(1000)
        self.w.run(minutes_later=60, **kw2)
        self.assertEqual(budget2.used, {"m": 300})
        self.assertEqual(budget2.day, eb.day_of(self.w.now))
        self.assertIn(dsc.ROTATION_KEY, self.w.state.load_discovery_state())

    def test_forced_limit_deferred_outcome_records_nothing(self) -> None:
        key = self.fresh_setup()
        self.w.plan[key] = [pl.EvalOutcome("deferred", message="budget")]
        run = self.w.run(minutes_later=60)
        self.assertEqual((run.outcome, run.eval_transient, run.eval_failed, run.eval_attempted, run.eval_budget_skipped, run.evaluated), ("ok", 0, 0, 0, 1, 0))
        self.assertEqual([e for e in self.w.events(key) if e.event in (lg.ERROR, lg.EVALUATED, lg.ABANDONED)], [])
        self.assertTrue(lg.needs_evaluation(self.w.states()[key]))
        del self.w.plan[key]  # the next run scores it: it never used an attempt
        again = self.w.run(minutes_later=60)
        self.assertEqual((again.evaluated, again.eval_attempted), (1, 1))

    def test_forced_limit_crash_before_load_writes_no_discovery_state(self) -> None:
        self.fresh_setup()
        kw, _ = self.budgeted(1000)
        path = self.w.state._path(st_mod.DISCOVERY_TAB)
        before = path.read_bytes()
        with (
            mock.patch.object(self.w.state, "load_discovery_state", side_effect=RuntimeError("sheet unreachable")),
            mock.patch.object(self.w.state, "save_discovery_state") as save,
            self.assertRaises(RuntimeError),
        ):
            self.w.run(minutes_later=60, **kw)
        save.assert_not_called()
        self.assertEqual(path.read_bytes(), before)

    def test_forced_limit_dry_run_never_saves_the_budget(self) -> None:
        self.fresh_setup()
        kw, budget = self.budgeted(1000)
        budget.charge("m", 5)
        before = self.w.state._path(st_mod.DISCOVERY_TAB).read_bytes()
        self.w.run(minutes_later=60, dry_run=True, **kw)
        self.assertEqual(self.w.state._path(st_mod.DISCOVERY_TAB).read_bytes(), before)

    def test_forced_limit_failed_budget_save_never_stops_the_run(self) -> None:
        key = self.fresh_setup()
        kw, _ = self.budgeted(1000)
        with mock.patch.object(self.w.state, "save_discovery_state", side_effect=OSError("disk full")):
            run = self.w.run(minutes_later=60, **kw)
        self.assertEqual(run.evaluated, 1)
        self.assertEqual(self.w.calls[key], 1)
        self.assertIn("groq budget not saved", run.notes)

    def test_forced_limit_reserve_leaves_the_last_share_to_fresh_jobs(self) -> None:
        key = self.fresh_setup()
        # a job whose date proves it is not fresh waits once the non-fresh share (80%) is spent
        self.w.listings[self.board.key].append(job("acme", "8", published="2026-10-10T08:00:00Z"))
        kw, _ = self.budgeted(1000)
        day = eb.day_of(self.w.now + timedelta(minutes=60))
        self.w.state.save_discovery_state({eb.GROQ_BUDGET_KEY: json.dumps({"day": day, "used": {"m": 850}})}, "t")
        run = self.w.run(minutes_later=60, **kw)
        self.assertEqual(self.w.calls[key], 1)  # the verified-fresh job still got scored (850 < 1000)
        self.assertEqual(self.w.calls[self.key("8")], 0)  # the non-fresh job waits (850 >= 800)
        self.assertEqual(run.eval_budget_skipped, 1)

    def test_runs_budget_columns_round_trip_and_old_rows_load(self) -> None:
        self.assertEqual(
            st_mod.RUN_COLUMNS[-11:-4],
            ["Groq_Tokens_Primary", "Groq_Tokens_Fallback", "Groq_Prompt_Tokens", "Groq_Cached_Tokens", "Groq_Completions", "Groq_Limits", "Eval_Budget_Skipped"],
        )
        self.assertEqual(st_mod.RUN_COLUMNS[-4:], ["Eval_Deadline_Skipped", "Eval_Cut", "Boards_Skipped_Deadline", "Alerts_Deferred"])
        self.assertEqual(len(st_mod.RUN_COLUMNS), len(st_mod.RunRecord("t").to_row()))
        rec = st_mod.RunRecord("2026-10-26T12:00:00Z", code_version="abc", groq_tokens_primary=900, groq_tokens_fallback=40, groq_prompt_tokens=700,
                               groq_cached_tokens=400, groq_completions=3, groq_limits='{"m":{"x":"1"}}', eval_budget_skipped=2,
                               eval_deadline_skipped=4, eval_cut=True, boards_skipped_deadline=5, alerts_deferred=6)  # fmt: skip
        back = st_mod.RunRecord.from_row([str(v) for v in rec.to_row()])
        assert back is not None
        self.assertEqual(
            (back.code_version, back.groq_tokens_primary, back.groq_tokens_fallback, back.groq_prompt_tokens, back.groq_cached_tokens, back.groq_completions, back.groq_limits, back.eval_budget_skipped),
            ("abc", 900, 40, 700, 400, 3, '{"m":{"x":"1"}}', 2),
        )
        self.assertEqual((back.eval_deadline_skipped, back.eval_cut, back.boards_skipped_deadline, back.alerts_deferred), (4, True, 5, 6))
        self.assertEqual(rec.to_row()[-2], 5)  # Boards_Skipped_Deadline sits in its own column
        self.assertEqual(st_mod.RunRecord.from_row([str(v) for v in st_mod.RunRecord("t").to_row()]).eval_cut, False)  # type: ignore[union-attr]
        old = [str(v) for v in rec.to_row()][:66]  # a row written before the seven columns existed
        loaded = st_mod.RunRecord.from_row(old)
        assert loaded is not None
        self.assertEqual((loaded.code_version, loaded.groq_tokens_primary, loaded.groq_limits, loaded.eval_budget_skipped), ("abc", 0, "", 0))
        older = [str(v) for v in rec.to_row()][:73]  # a row written before the four deadline columns existed
        loaded2 = st_mod.RunRecord.from_row(older)
        assert loaded2 is not None
        self.assertEqual((loaded2.eval_budget_skipped, loaded2.eval_deadline_skipped, loaded2.eval_cut, loaded2.boards_skipped_deadline, loaded2.alerts_deferred), (2, 0, False, 0, 0))

    def test_run_row_records_the_tokens_the_run_used(self) -> None:
        self.fresh_setup()
        from meter import METER

        original = self.w.evaluate

        def metered(ident: Any, st: lg.JobState) -> pl.EvalOutcome:
            METER.add("groq_tokens_primary", 900)
            METER.add("groq_tokens_fallback", 40)
            METER.add("groq_prompt_tokens", 700)
            METER.add("groq_cached_tokens", 400)
            METER.add("groq_completions")
            return original(ident, st)

        self.w.evaluate = metered  # type: ignore[method-assign]
        run = self.w.run(minutes_later=60, groq_limits=lambda: '{"m":{"x-ratelimit-limit-requests":"1000"}}')
        self.assertEqual((run.groq_tokens_primary, run.groq_tokens_fallback, run.groq_prompt_tokens, run.groq_cached_tokens, run.groq_completions), (900, 40, 700, 400, 1))
        self.assertEqual(run.groq_limits, '{"m":{"x-ratelimit-limit-requests":"1000"}}')
        stored = [r for r in self.w.state.load_runs() if r.run_id == run.run_id][-1]
        self.assertEqual((stored.groq_tokens_primary, stored.eval_budget_skipped), (900, 0))

    def test_groq_limits_callback_failure_leaves_the_column_blank(self) -> None:
        self.fresh_setup()

        def broken() -> str:
            raise ValueError("boom")

        run = self.w.run(minutes_later=60, groq_limits=broken)
        self.assertEqual((run.groq_limits, run.outcome), ("", "ok"))


class FakeClock:
    """A monotonic clock the tests move by hand: callable like `time.monotonic`."""

    def __init__(self, t: float = 0.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def rec(name: str, attempt: str = "") -> bd.BoardRecord:
    return bd.BoardRecord(bd.GREENHOUSE, name, ago(days=30), "seed", bd.STATUS_ACTIVE, baselined_at=ago(days=20), last_attempt_at=attempt, last_success_at=attempt)


class PollCutoffTests(HarnessCase):
    def two_boards(self) -> tuple[str, str]:
        """Two baselined boards; returns their keys (acme sorts before beta)."""
        a, b = bd.BoardId(bd.GREENHOUSE, "acme"), bd.BoardId(bd.GREENHOUSE, "beta")
        self.w.listings[a.key] = [job("acme", "1", published=ago(days=30))]
        self.w.listings[b.key] = [job("beta", "1", published=ago(days=30))]
        self.w.run(seeds=[a, b])
        return a.key, b.key

    def cut_after_each_fetch(self, clock: FakeClock, order: list[str], step: float = 200.0) -> None:
        original = self.w.fetch

        def fetch(board: bd.BoardId) -> list[bd.ListedJob]:
            order.append(board.key)
            clock.advance(step)
            return original(board)

        self.w.fetch = fetch  # type: ignore[method-assign]

    def test_poll_boards_deadline_marks_rest_skipped_deadline_not_skipped(self) -> None:
        clock, fetched = FakeClock(), []

        def fetch(board: bd.BoardId) -> list[bd.ListedJob]:
            fetched.append(board.key)
            clock.advance(60)
            return []

        boards = [rec("a"), rec("b"), rec("c")]
        res = bd.poll_boards(boards, fetch=fetch, workers=1, clock=clock, deadline=90)
        self.assertEqual(fetched, ["greenhouse|a", "greenhouse|b"])  # c starts at t=120, past the deadline
        self.assertEqual([(r.ok, r.skipped, r.skipped_deadline) for r in res], [(True, False, False), (True, False, False), (False, False, True)])
        self.assertEqual(res[2].board, boards[2])
        self.assertNotIn("429", res[2].error)

    def test_poll_boards_without_deadline_polls_everything(self) -> None:
        clock = FakeClock(10_000)
        res = bd.poll_boards([rec("a"), rec("b")], fetch=lambda b: [], workers=1, clock=clock)
        self.assertEqual([r.skipped_deadline for r in res], [False, False])

    def test_poll_order_is_longest_unpolled_first_with_key_tiebreak(self) -> None:
        stamps = {"late": "2026-10-14T10:00:00Z", "early": "2026-10-14T09:00:00Z", "blank": "", "tie_b": "2026-10-14T09:30:00Z", "tie_a": "2026-10-14T09:30:00Z"}
        self.w.state.save_boards([rec(n, t) for n, t in stamps.items()])
        order: list[str] = []
        self.cut_after_each_fetch(FakeClock(), order, 0)
        for n in stamps:
            self.w.listings[f"greenhouse|{n}"] = []
        run = self.w.run(workers=1)
        self.assertEqual(order, [f"greenhouse|{n}" for n in ("blank", "early", "tie_a", "tie_b", "late")])
        self.assertEqual(run.boards_skipped_deadline, 0)

    def test_poll_cutoff_skipped_board_keeps_state_and_goes_first_next_run(self) -> None:
        a, b = self.two_boards()
        before = {x.key: x for x in self.w.state.load_boards().values()}
        self.assertEqual(before[a].last_attempt_at, before[b].last_attempt_at)
        self.w.listings[f"{bd.GREENHOUSE}|beta"].append(job("beta", "2", published=ago(minutes=5, base=T0 + timedelta(minutes=60))))
        clock, order = FakeClock(), []
        self.cut_after_each_fetch(clock, order)
        run = self.w.run(minutes_later=60, clock=clock, process_t0=0, poll_cutoff_s=100, workers=1)
        self.assertEqual(order, [a])  # acme first (stamps tie, key order); the cutoff passes before beta starts
        after = self.w.state.load_boards()
        self.assertGreater(after[a].last_attempt_at, before[a].last_attempt_at)
        for attr in ("last_attempt_at", "consecutive_failures", "baselined_at", "last_success_at", "status", "last_error"):
            self.assertEqual(getattr(after[b], attr), getattr(before[b], attr), attr)
        self.assertEqual(self.w.events(self.key("2", board="beta"), None), [])  # nothing observed for the skipped board's jobs
        self.assertEqual((run.boards_skipped_deadline, run.boards_ok, run.boards_failed), (1, 1, 0))
        order.clear()
        clock.t = 0
        run2 = self.w.run(minutes_later=60, clock=clock, process_t0=0, poll_cutoff_s=100, workers=1)
        self.assertEqual(order, [b])  # beta is now the longest unpolled: first
        self.assertEqual(len(self.w.events(self.key("2", board="beta"), lg.SEEN)), 1)  # its new job is observed once the board is polled
        self.assertEqual(run2.boards_skipped_deadline, 1)  # acme is the one cut now

    def test_outcome_poll_cutoff_makes_run_degraded(self) -> None:
        self.two_boards()
        clock, order = FakeClock(), []
        self.cut_after_each_fetch(clock, order)
        run = self.w.run(minutes_later=60, clock=clock, process_t0=0, poll_cutoff_s=100, workers=1)
        self.assertEqual(run.boards_skipped_deadline, 1)
        self.assertEqual(run.outcome, "degraded")
        self.assertIn("poll cutoff", pl.degraded_reason(run))
        self.assertIn("poll cutoff after", run.notes)
        self.assertNotIn("provider backoff after HTTP 429", run.notes)
        self.assertNotIn("provider", pl.degraded_reason(run))
        stored = [r for r in self.w.state.load_runs() if r.run_id == run.run_id][-1]
        self.assertEqual((stored.boards_skipped_deadline, stored.outcome), (1, "degraded"))

    def test_run_that_polled_every_board_before_the_cutoff_is_ok(self) -> None:
        self.two_boards()
        clock = FakeClock()
        run = self.w.run(minutes_later=60, clock=clock, process_t0=0, poll_cutoff_s=100, workers=1)  # the clock never moves
        self.assertEqual((run.boards_skipped_deadline, run.outcome), (0, "ok"))
        self.assertNotIn("poll cutoff", run.notes)


class EvalCutoffTests(HarnessCase):
    """Evaluation and alert cutoffs (D-51): measured from process start, nothing recorded against a job or alert that was cut."""

    def add_fresh(self, *ids: str) -> list[str]:
        self.baseline(job("acme", "1", published=ago(days=30)))
        for jid in ids:
            self.w.listings[self.board.key].append(job("acme", jid, published=ago(minutes=10, base=T0 + timedelta(minutes=60))))
        return [self.key(jid) for jid in ids]

    def advancing(self, clock: FakeClock, seconds: float, order: list[str] | None = None) -> None:
        """Every evaluation takes `seconds` of the fake clock."""
        original = self.w.evaluate

        def evaluate(ident: Any, st: lg.JobState) -> pl.EvalOutcome:
            if order is not None:
                order.append(st.key)
            out = original(ident, st)
            clock.advance(seconds)
            return out

        self.w.evaluate = evaluate  # type: ignore[method-assign]

    def test_outcome_eval_cutoff_leaves_run_ok_with_counter_and_note(self) -> None:
        first, second = self.add_fresh("7", "8")
        clock, order = FakeClock(), []
        self.advancing(clock, 200, order)
        run = self.w.run(minutes_later=60, clock=clock, process_t0=0, eval_cutoff_s=100)
        self.assertEqual((run.evaluated, run.eval_cut, run.eval_deadline_skipped, run.outcome), (1, True, 1, "ok"))
        self.assertEqual(pl.degraded_reason(run), "")
        self.assertIn("evaluation cutoff", run.notes)
        self.assertEqual(run.eval_attempted, 1)
        waiting = [k for k in (first, second) if k not in order][0]
        self.assertEqual(self.w.events(waiting, lg.EVALUATED), [])
        self.assertEqual(self.w.events(waiting, lg.ERROR), [])
        self.assertEqual(self.w.states()[waiting].errors, {})
        stored = [r for r in self.w.state.load_runs() if r.run_id == run.run_id][-1]
        self.assertEqual((stored.eval_cut, stored.eval_deadline_skipped), (True, 1))
        run2 = self.w.run(minutes_later=60)  # next run: no cutoff pressure, the cut job is scored
        self.assertEqual((run2.evaluated, run2.eval_cut, run2.outcome), (1, False, "ok"))
        self.assertEqual(len(self.w.events(waiting, lg.EVALUATED)), 1)

    def test_eval_cutoff_scores_verified_fresh_first(self) -> None:
        self.baseline(job("acme", "1", published=ago(days=30)))
        self.w.listings[self.board.key] += [
            job("acme", "8", published=ago(days=3, base=T0 + timedelta(minutes=60))),  # recent: not fresh
            job("acme", "7", published=ago(minutes=10, base=T0 + timedelta(minutes=60))),
        ]
        clock, order = FakeClock(), []
        self.advancing(clock, 200, order)
        self.w.run(minutes_later=60, clock=clock, process_t0=0, eval_cutoff_s=100)
        st = self.w.states()
        self.assertEqual((st[self.key("7")].freshness, st[self.key("8")].freshness), (fr.VERIFIED_FRESH, fr.RECENT))
        self.assertEqual(order, [self.key("7")])  # the one evaluation the cutoff allowed went to the verified-fresh job

    def test_late_start_anchors_cutoffs_at_process_start(self) -> None:
        self.add_fresh("7", "8", "9")
        clock, order = FakeClock(600), []  # a 10-minute writer-lease wait happened before run_cycle
        self.advancing(clock, 300, order)
        run = self.w.run(minutes_later=60, clock=clock, process_t0=0)  # default 20-minute evaluation cutoff = 1,200 s
        self.assertEqual(len(order), 2)  # 600 -> 900 -> 1200: the third job is cut at process minute 20, not run minute 20
        self.assertEqual((run.eval_cut, run.eval_deadline_skipped, run.evaluated), (True, 1, 2))

    def test_run_without_process_anchor_counts_from_its_own_start(self) -> None:
        self.add_fresh("7", "8", "9")
        clock, order = FakeClock(600), []
        self.advancing(clock, 300, order)
        run = self.w.run(minutes_later=60, clock=clock)  # no process_t0: anchored at run_cycle start (deadline 1,800 s)
        self.assertEqual((len(order), run.eval_cut), (3, False))

    def test_outcome_groq_deadline_deferral_is_not_transient(self) -> None:
        first, second = self.add_fresh("7", "8")
        for key in (first, second):
            self.w.plan[key] = [pl.EvalOutcome("deferred", message="deadline")]
        run = self.w.run(minutes_later=60)
        self.assertEqual((run.eval_transient, run.eval_cut, run.outcome, run.eval_attempted, run.evaluated), (0, True, "ok", 0, 0))
        self.assertEqual(sum(self.w.calls[k] for k in (first, second)), 1)  # the loop stopped at the first deferral
        self.assertEqual(run.eval_deadline_skipped, 2)  # both jobs wait
        self.assertEqual(run.eval_budget_skipped, 0)
        for key in (first, second):
            self.assertEqual(self.w.events(key, lg.EVALUATED) + self.w.events(key, lg.ERROR), [])
        self.assertNotIn("transient", run.notes)
        self.assertIn("evaluation cutoff", run.notes)

    def test_alert_cutoff_leaves_alert_pending_with_no_attempt(self) -> None:
        (key,) = self.add_fresh("7")
        clock = FakeClock()
        self.advancing(clock, 400)  # scoring ends past the 300 s alert cutoff but before the evaluation cutoff
        run = self.w.run(minutes_later=60, clock=clock, process_t0=0, alert_cutoff_s=300)
        self.assertEqual(self.w.alert_calls, 0)
        self.assertEqual((run.alerts_deferred, run.alerts_sent, run.alerts_failed), (1, 0, 0))
        self.assertEqual(self.w.events(key, lg.ALERTED) + self.w.events(key, lg.ERROR), [])
        self.assertEqual((run.outcome, pl.degraded_reason(run)), ("degraded", "alert cutoff"))
        self.assertIn("alert cutoff after", run.notes)
        self.assertEqual(self.w.states()[key].errors, {})
        run2 = self.w.run(minutes_later=60)
        self.assertEqual((self.w.alert_calls, run2.alerts_sent, run2.alerts_deferred, run2.outcome), (1, 1, 0, "ok"))
        self.assertEqual(len(self.w.events(key, lg.ALERTED)), 1)

    def test_alerts_still_run_after_the_evaluation_cutoff(self) -> None:
        self.add_fresh("7", "8")
        clock = FakeClock()
        self.advancing(clock, 200)  # one job scored, then the 100 s evaluation cutoff; alerts run until the default 22 minutes
        run = self.w.run(minutes_later=60, clock=clock, process_t0=0, eval_cutoff_s=100)
        self.assertEqual((run.eval_cut, run.alerts_sent, run.alerts_deferred, run.outcome), (True, 1, 0, "ok"))


if __name__ == "__main__":
    unittest.main()
