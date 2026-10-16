"""One run of the system: discover -> poll boards -> detect new IDs -> evaluate -> deliver.

All side effects go through `Deps` (state store, tracker, ATS fetch, hydration/scoring, alerts,
clock), so every stage and every failure case can be tested without a network.
Ordering rules that protect correctness (SPEC.md "State model"):
  1. `seen` events are written BEFORE the Boards registry is saved (a baselined board must
     always have its baseline events, or its backlog would later look new).
  2. The tracker row is appended BEFORE the `evaluated` event, guarded by a tracker-key check.
  3. `alerted` is written only after the alert channel accepted the message.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import discovery as dsc
import freshness as fr
import inventory as inv
import ledger as lg
import pools
import search
from meter import METER
from boards import (
    MONITORED, STATUS_ACTIVE, STATUS_CANDIDATE, STATUS_DEFERRED, STATUS_INVALID, STATUS_NEW, STATUS_VALIDATED, BoardId, BoardRecord, JobIdentity, ListedJob,
    activate_waiting, fetch_board, poll_boards, registry_counts, apply_poll_result,
)  # fmt: skip
from discovery import SearchJob  # noqa: F401  (re-exported: hunter and the tests import it from here)
from state import (
    CREDIT_NONE, CREDIT_REPORTED, CREDIT_UNRESOLVED, KIND_PRODUCTION, OUTCOME_DEGRADED, OUTCOME_FAILED, OUTCOME_OK, OUTCOME_STARTED, RunRecord,
)  # fmt: skip

log = logging.getLogger("hunter")

FLUSH_EVERY = 10
FLOOD_MIN_JOBS = 30  # a baselined board suddenly showing this many unseen IDs is treated as a re-baseline
SUSPICIOUS_EMPTY_AFTER = 3  # an empty listing from a board that had more than this many jobs is a glitch
MAX_SEARCH_HYDRATIONS = 20


class FatalRunError(Exception):
    """Stop the whole run (e.g. an invalid API key); already-completed work is still flushed."""


class RetryableHydration(Exception):
    """A search-found job could not be read from its ATS for a temporary reason (timeout, 5xx,
    429). It is kept in a bounded retry queue instead of being dropped. A closed posting is not
    this: the hydrator returns None for it."""


@dataclass
class DiscoveryContext:
    """What a discovery callable may ask about the world, so pagination can stop on repetition."""

    now: datetime
    rotation: dsc.RotationState
    is_new_board: Callable[[BoardId], bool]
    is_unseen_job: Callable[[JobIdentity], bool]
    budget: search.SearchBudget = field(default_factory=lambda: search.SearchBudget("0000-00"))  # the monthly ledger every search path shares
    scheduled: bool = True  # False for a manual --discover / --backfill: may also use the reserve


@dataclass
class EvalOutcome:
    """Result of evaluating one pending job.

    done:      payload holds the final row (status, score, ...); evaluation is complete.
    transient: temporary failure (timeout, 5xx, rate limit); retry next run.
    failed:    permanent-looking failure; retried a bounded number of times, then abandoned.
    """

    kind: str  # "done" | "transient" | "failed"
    payload: dict[str, Any] | None = None
    message: str = ""


@dataclass
class Deps:
    state: Any  # SheetState / CsvState
    tracked_keys: set[str]
    append_tracker: Callable[[list[dict[str, Any]]], None]
    evaluate: Callable[[JobIdentity, lg.JobState], EvalOutcome]
    send_alert: Callable[[dict[str, Any]], bool]
    title_gate: Callable[[str], str | None]
    fetch: Callable[[BoardId], list[ListedJob]] = fetch_board
    discover: Callable[[DiscoveryContext], dsc.DiscoveryResult] | None = None
    hydrate_listed: Callable[[SearchJob], ListedJob | None] | None = None
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)
    fresh_window: timedelta = timedelta(hours=fr.DEFAULT_FRESH_WINDOW_HOURS)
    max_age_days: int = fr.DEFAULT_MAX_AGE_DAYS
    max_jobs: int = 30
    discovery_every_hours: int = 12
    force_discovery: bool = False
    search_monthly_credits: int = search.DEFAULT_MONTHLY_CREDITS
    search_reserve_credits: int = search.DEFAULT_RESERVE_CREDITS
    search_sync: Callable[[search.SearchBudget], None] | None = None  # reads the provider's own usage counter into the ledger (free)
    max_monitored_boards: int = 500  # polling budget: validated boards are only promoted up to this many
    max_new_boards_per_run: int = 50  # each promotion baselines a whole board, so surges are capped
    seeds: list[BoardId] = field(default_factory=list)  # manually registered boards (testing / bootstrap)
    allow_smartrecruiters: bool = False  # ALLOW_SMARTRECRUITERS_BULK: provider policy for EVERY source
    max_inline_validations: int = 40  # boards from one discovery validated in the run; the rest wait as candidates
    rotation_slots: list[dsc.Slot] = field(default_factory=list)  # the rotation the discover callable searched from
    config_notes: list[str] = field(default_factory=list)
    trigger: str = ""  # what started this run: "schedule", "workflow_dispatch" (GitHub) or "local"; recorded in Runs.Notes  # settings problems to surface in the run record
    workers: int = 8
    sleep: Callable[[float], None] = time.sleep  # backoff between validation retries (tests pass a no-op)
    dry_run: bool = False
    run_kind: str = KIND_PRODUCTION  # `rehearsal` for a local run: its run record says so and reports leave it out
    pool_policy: pools.PoolPolicy = field(default_factory=pools.PoolPolicy)  # max_active is always max_monitored_boards


def _parse_stamp(value: str, tz: Any) -> datetime | None:
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=tz)
    except ValueError:
        return None


def discovery_due(runs: list[RunRecord], now: datetime, every_hours: int) -> bool:
    for r in reversed(runs):
        if r.discovery:
            t = _parse_stamp(r.run_at, now.tzinfo)
            return t is None or now - t >= timedelta(hours=every_hours) - timedelta(minutes=5)
    return True


def _minutes(td: timedelta | None) -> int | None:
    return None if td is None else int(td.total_seconds() // 60)


def degraded_reason(run: RunRecord) -> str:
    """Why a run that finished is not plainly `ok` (empty = it is ok). A handful of boards failing is normal and is
    not degradation by itself; discovery or persistence failures, failed alerts, temporary scoring failures or a
    tenth of the boards failing are."""
    reasons = []
    if "discovery failed" in run.notes or "every search request failed" in run.notes or "search stopped" in run.notes:
        reasons.append("discovery")
    if "final write failed" in run.notes or "run-start record not written" in run.notes:
        reasons.append("persistence")
    if run.alerts_failed:
        reasons.append("alerts")
    if run.eval_transient:
        reasons.append("scoring")
    if "provider backoff after HTTP 429" in run.notes:
        reasons.append("provider")
    if run.boards_failed and run.boards_failed >= max(3, run.boards_total // 10):
        reasons.append("boards")
    return ",".join(reasons)


def run_cycle(d: Deps) -> RunRecord:
    now = d.now()
    t_start = time.monotonic()
    meter0 = METER.snapshot()
    d.state.ensure()
    boards = d.state.load_boards()
    events_loaded = d.state.load_events()
    states = lg.replay(events_loaded)
    runs = d.state.load_runs()
    run = RunRecord(lg.stamp(now), run_id=f"{now.strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:6]}", outcome=OUTCOME_STARTED, run_kind=d.run_kind)
    run.load_s, run.events_rows, run.boards_rows = round(time.monotonic() - t_start), len(events_loaded), len(boards)
    t_eval: float | None = None
    # The gap is measured from the previous run that FINISHED: an interrupted run polled nothing that was saved
    # (state is written at the end), so counting its start would hide a real polling gap.
    finished = [r for r in runs if r.completed]
    if finished and (prev := _parse_stamp(finished[-1].run_at, now.tzinfo)):
        run.gap_since_prev_run_min = _minutes(now - prev)
    pending_events: list[lg.Event] = []
    pending_rows: list[dict[str, Any]] = []
    dirty: dict[str, BoardRecord] = {}  # registry rows changed by THIS run (only these are written back)

    def write() -> None:
        """Tracker rows first, then events (rule 2)."""
        nonlocal pending_events, pending_rows
        if d.dry_run:
            pending_events, pending_rows = [], []
            return
        if pending_rows:
            d.append_tracker(pending_rows)
            pending_rows = []
        if pending_events:
            d.state.append_events(pending_events)
            pending_events = []

    if not d.dry_run:
        try:  # instrumentation only: failing to write the start record must never stop the run
            d.state.begin_run(run)
        except Exception as exc:
            log.error("Could not write the run-start record: %s", exc)
            run.notes += f"run-start record not written: {exc}; "
    crashed = True  # cleared only when the body completes: an exception (or a fatal stop) leaves it set
    try:
        def admit(found: list[BoardId], source: str) -> inv.AdmissionResult:
            """The one admission path (inventory import, web search, manual seeds)."""
            adm = inv.admit_boards(
                boards, found, source=source, now=now, fetch=d.fetch, title_gate=d.title_gate,
                allow_smartrecruiters=d.allow_smartrecruiters, max_inline_validations=d.max_inline_validations, sleep=d.sleep,
            )  # fmt: skip
            dirty.update(adm.touched)
            run.boards_added += adm.added
            return adm

        if d.trigger:
            run.notes += f"trigger={d.trigger}; "
        if d.config_notes:
            run.notes += "".join(f"{n}; " for n in d.config_notes)
        if d.seeds:
            admit(d.seeds, "seed")

        t_disc = time.monotonic()
        # ---------------------------------------------------------------- 1. discovery loop
        # Search is candidate retrieval only. Every result is processed twice, independently:
        # its BOARD goes through admission, its JOB (if unseen) through hydration -> pipeline.
        search_jobs: list[SearchJob] = []
        found: dsc.DiscoveryResult | None = None
        found_keys: list[str] = []
        discovery_state = d.state.load_discovery_state()
        rotation = dsc.RotationState.from_json(discovery_state.get(dsc.ROTATION_KEY))
        pending = dsc.load_pending(discovery_state.get(dsc.PENDING_KEY))
        budget = search.SearchBudget.load(
            discovery_state.get(search.BUDGET_KEY), now, cap=d.search_monthly_credits, reserve=d.search_reserve_credits
        )  # fmt: skip
        scheduled = not d.force_discovery
        run_discovery = bool(d.discover and (d.force_discovery or discovery_due(runs, now, d.discovery_every_hours)))
        if run_discovery:
            if d.search_sync:
                try:
                    d.search_sync(budget)
                except Exception as exc:  # best effort: the local ledger still applies
                    log.warning("Could not read the search provider's usage counter: %s", exc)
            if budget.remaining(scheduled=scheduled) <= 0:
                # Out of credits: skip discovery, keep polling. The run is not marked as a discovery run, so
                # the next hourly run asks again and discovery resumes by itself when the month rolls over.
                log.warning("Search discovery skipped, monthly credit budget exhausted: %s", budget.summary())
                run.notes += f"search discovery skipped (budget exhausted: {budget.effective_used} of {budget.effective_cap} credits used this month); "
                run_discovery = False
        if run_discovery:
            run.discovery = True
            if rotation.migrated_from:
                log.warning("Search rotation reset: the cursor saved for %s is not valid for %s; restarting at slot 0", rotation.migrated_from, search.PROVIDER)
                run.notes += f"search rotation reset (state from {rotation.migrated_from} discarded, restarts at slot 0); "
            if budget.rolled_from:
                log.info("Search credit ledger restarted for %s (previous month %s)", budget.month, budget.rolled_from)
            try:
                ctx = DiscoveryContext(
                    now, rotation,
                    is_new_board=lambda b: b.key not in boards,
                    is_unseen_job=lambda i: not (states.get(i.key) and states[i.key].seen),
                    budget=budget, scheduled=scheduled,
                )  # fmt: skip
                found = d.discover(ctx)
                adm = admit(found.boards, search.PROVIDER)
                found_keys = adm.keys
                search_jobs = found.jobs
                run.search_queries, run.search_pages, run.search_credits = len(found.queries), found.pages, found.credits
                run.search_failed = sum(1 for q in found.queries if q.error)
                run.credit_status = CREDIT_UNRESOLVED if run.search_failed else CREDIT_REPORTED
                run.search_repeated, run.new_unique_boards = found.repeated, adm.added
                run.notes += (
                    f"{found.kind} discovery: {len(found.queries)} queries, {found.pages} pages, {found.credits} credits"
                    f"{', stopped: ' + found.stopped if found.stopped else ''}; "
                    f"{adm.parked} boards parked by provider policy, {adm.rejected} rejected; "
                )  # fmt: skip
                if found.all_failed:
                    run.notes += "every search request failed (rotation not advanced); "
                if found.fatal:
                    run.notes += f"search stopped: {found.fatal}; "
                for q in found.queries:
                    log.info(
                        "Query %s [window=%s]: %d pages, %d credits, %d results, %d repeated, %d new boards, %d unseen jobs, %d unparsed, stop=%s%s",
                        q.id, q.window or "none", q.pages, q.credits, q.results, q.repeated, q.new_boards, q.unseen_jobs, q.unparsed, q.stop,
                        f", error={q.error}" if q.error else "",
                    )  # fmt: skip
            except Exception as exc:  # discovery is best-effort; polling must still happen
                log.warning("Discovery failed: %s", exc)
                run.notes += f"discovery failed: {exc}; "
                found = None
                run.credit_status = CREDIT_UNRESOLVED  # requests may have been charged before it failed
            finally:
                # Credits are recorded even when discovery or a dry run stops early: the ledger must never
                # under-count what the provider charged (a dry run that searches still spends credits).
                discovery_state[search.BUDGET_KEY] = budget.to_json()
                try:
                    d.state.save_discovery_state(discovery_state, lg.stamp(now))
                except Exception as exc:
                    log.error("Could not record the search credit ledger: %s", exc)
                    run.notes += f"search ledger not saved: {exc}; "
            run.search_account_used = budget.account_used
            log.info(budget.summary())

        run.discovery_s = round(time.monotonic() - t_disc)
        t_poll = time.monotonic()
        # ---------------------------------------------------------------- 2. polling loop
        # Validated inventory boards enter monitoring only within the polling budget; the poll
        # below then baselines them (their existing jobs never look "just posted").
        policy = dataclasses.replace(d.pool_policy, max_active=d.max_monitored_boards)

        def blocked(ats: str) -> str | None:
            return inv.policy_blocks(ats, allow_smartrecruiters=d.allow_smartrecruiters)

        # Every run, in every mode: provider policy applies to boards that are already monitored,
        # stale pool labels are cleared and boards monitored before pools existed get a trial.
        sync = pools.sync_pools(boards, policy, now, blocked)
        dirty.update(sync.changed)
        run.parked_policy = len(sync.parked)
        for line in sync.lines:
            log.info(line)
        if sync.parked:
            log.warning("%d monitored SmartRecruiters boards parked by provider policy (history kept)", len(sync.parked))
            run.notes += f"{len(sync.parked)} monitored SmartRecruiters boards parked by provider policy (history kept); "
        if sync.migrated:
            run.notes += f"{len(sync.migrated)} boards monitored before pools existed started an exploration trial; "
        promoted_keys: set[str] = set()
        for rec in activate_waiting(
            boards, max_monitored=d.max_monitored_boards, per_run=d.max_new_boards_per_run, now=now,
            trial_days=policy.exploration_days, blocked=blocked, cooldown=policy.cooldown,
        ):  # fmt: skip
            dirty[rec.key] = rec
            promoted_keys.add(rec.key)
            run.boards_activated += 1
            log.info("Pool %s: waiting -> exploration (%s)", rec.key, rec.pool_reason)
        active = [b for b in boards.values() if b.status in MONITORED]
        run.boards_total = len(active)
        max_gap: timedelta | None = None
        skipped_backoff: dict[str, int] = {}
        for res in poll_boards(active, fetch=d.fetch, workers=d.workers):
            was_baselined = bool(res.board.baselined_at)
            # A board that is `new` but already has a baseline came back after leaving monitoring.
            reentry = was_baselined and res.board.status == STATUS_NEW
            if res.ok and not res.jobs and res.board.last_job_count > SUSPICIOUS_EMPTY_AFTER:
                res.ok, res.error = False, "suspicious empty listing (previously had jobs)"
            if res.skipped:  # provider in backoff: this board was not requested, so nothing about it changes
                skipped_backoff[res.board.ats] = skipped_backoff.get(res.board.ats, 0) + 1
                continue
            rec, gap = apply_poll_result(res, now=now)
            boards[rec.key] = rec
            dirty[rec.key] = rec
            if not res.ok:
                run.boards_failed += 1
                continue
            run.boards_ok += 1
            if gap is not None and (max_gap is None or gap > max_gap):
                max_gap = gap
            unseen = [j for j in res.jobs if not (states.get(j.ident.key) and states[j.ident.key].seen)]
            baseline_pass = not was_baselined
            if was_baselined and not reentry and len(unseen) >= FLOOD_MIN_JOBS and len(unseen) > len(res.jobs) / 2:
                log.warning("Board %s: %d of %d IDs unseen; treating as a re-baseline", rec.key, len(unseen), len(res.jobs))
                run.notes += f"{rec.key} re-baselined; "
                baseline_pass = True
            pass_kind = "baseline" if baseline_pass else "reentry" if reentry else ""
            obs = lg.Observation(now, gap, was_baselined, baseline_pass, "poll", d.fresh_window, d.max_age_days, pass_kind, reentry, run.run_id)
            for job in res.jobs:
                st = states.get(job.ident.key)
                if st and st.seen:
                    if st.evaluated is not None:
                        pending_events += lg.observe_known(job, st, now)
                    continue
                ev = lg.observe_new(job, obs, d.title_gate)
                pending_events.append(ev)
                states[ev.key] = lg.replay([ev])[ev.key]
                run.new_jobs += 1
                run.verified_fresh += ev.freshness == fr.VERIFIED_FRESH
            if (baseline_pass and not rec.baselined_at) or reentry:
                # A first baseline or a re-entry pass starts a new continuous monitoring stint.
                rec.baselined_at, rec.status = lg.stamp(now), STATUS_ACTIVE
                pools.start_stint(rec, now)
            elif rec.baselined_at and not rec.activity_since:
                rec.activity_since = rec.baselined_at  # monitored before evidence existed: history starts at its baseline
            if res.complete:
                # Relevance and activity evidence only from a complete listing; a truncated one
                # still gets its new IDs observed above but never changes the board's counts.
                pools.refresh_relevance(rec, res.jobs, d.title_gate, now)
        if skipped_backoff:
            detail = ", ".join(f"{n} {a}" for a, n in sorted(skipped_backoff.items()))
            log.warning("Provider backoff (HTTP 429): %s boards were not polled this run and keep their previous state", detail)
            run.notes += f"provider backoff after HTTP 429: not polled this run: {detail}; "
        run.max_board_gap_min = _minutes(max_gap)
        # New-relevant-posting counts come from the ledger (first observations on ordinary polls
        # only). Every monitored board was polled above, so each row is already being written.
        activity = pools.ActivityIndex.from_states(states)
        for b in boards.values():
            if b.status in MONITORED:
                pools.refresh_activity(b, activity, now)
                dirty[b.key] = b

        # Weekly rebalance: ended trials against the weakest evidence-backed established boards.
        # In "report" mode (the default) only the plan is recorded; "on" applies it. Transitions are
        # made here, inside the hourly poller, and nowhere else (D-28).
        rebalance_values: dict[str, str] = {}
        if pools.rebalance_due(discovery_state.get(pools.REBALANCE_KEY), boards, now, policy):
            plan = pools.plan_rebalance(boards, policy, now, blocked)
            for line in pools.format_plan(plan, pools.coverage(boards, now, blocked, policy.cooldown), policy):
                log.info("Rebalance (%s): %s", policy.mode, line)
            if policy.mode == "on":
                was_pool = {dec.key: boards[dec.key].pool or "-" for dec in plan.decisions if dec.key in boards}
                moved = pools.apply_plan(boards, plan, now)
                dirty.update({b.key: b for b in moved})
                run.graduated = plan.count("graduate") + plan.count("replace")
                run.demoted = plan.count("replace") + plan.count("return") + plan.count("rotate") + plan.count("shed")
                run.rebalance = "applied"
                for dec in plan.decisions:
                    if dec.action in ("graduate", "replace"):
                        log.info("Pool %s: exploration -> established (%s)", dec.key, dec.reason)
                    if dec.action == "replace":
                        log.info("Pool %s: established -> waiting (replaced by %s)", dec.partner, dec.key)
                    if dec.action in ("return", "rotate", "shed"):
                        log.info("Pool %s: %s -> waiting (%s)", dec.key, was_pool.get(dec.key, "-"), dec.reason)
            else:
                run.rebalance = "report"
                run.notes += f"rebalance report ({plan.summary()}; {plan.waiting} relevant boards waiting); "
            rebalance_values[pools.REBALANCE_KEY] = json.dumps(
                {"at": lg.stamp(now), "mode": policy.mode, "graduate": plan.count("graduate"), "replace": plan.count("replace"),
                 "defer": plan.count("defer"), "return": plan.count("return"), "keep": plan.count("keep"),
                 "extend": plan.count("extend"), "rotate": plan.count("rotate"), "shed": plan.count("shed")}, separators=(",", ":"),
            )  # fmt: skip
            rebalance_values[pools.REBALANCE_REPORT_KEY] = pools.plan_json(plan, now, policy.mode)
        cov = pools.coverage(boards, now, blocked, policy.cooldown)
        run.pool_established, run.pool_exploration, run.waiting_relevant = cov["established"], cov["exploration"], cov["waiting"]
        run.oldest_waiting_hours, run.relevant_coverage_pct = cov["oldest_waiting_hours"], cov["coverage_pct"]
        log.info(
            "Pools: established %d/%d, exploration %d/%d, monitored %d/%d, %d relevant boards waiting%s, relevant-board coverage %s%%",
            cov["established"], policy.established_target, cov["exploration"], policy.exploration_target, cov["monitored"], policy.max_active,
            cov["waiting"], f" (oldest {cov['oldest_waiting_hours']} h)" if cov["oldest_waiting_hours"] is not None else "", cov["coverage_pct"],
        )  # fmt: skip
        counts = registry_counts(boards)
        run.boards_discovered, run.boards_validated, run.boards_monitored = counts["discovered"], counts["validated"], counts["monitored"]

        run.poll_s = round(time.monotonic() - t_poll)
        # Search-found jobs not on any listing we read: hydrate for an authoritative date first
        # (Google's window says when a page was indexed, never when the job was published).
        # Temporary read failures are queued and retried on later runs without spending credits.
        candidates: dict[str, SearchJob] = {}
        for key, entry in pending.items():
            if (job := dsc.job_from_pending(entry)) is not None:
                candidates[key] = job
        for sj in search_jobs:
            candidates.setdefault(sj.ident.key, sj)
        hydrated = 0
        pending_changed = False
        skipped_by_policy = 0
        for key, sj in candidates.items():
            st = states.get(key)
            if (st and st.seen) or not d.hydrate_listed:
                if key in pending:
                    pending.pop(key)
                    pending_changed = True  # already observed (e.g. the board poll listed it): nothing to retry
                continue
            if hydrated >= MAX_SEARCH_HYDRATIONS:
                continue  # stays queued (if it was) and is tried next run
            if d.title_gate(sj.title) is not None:
                if pending.pop(key, None) is not None:
                    pending_changed = True
                continue  # cheap gate before any fetch; not recorded (cheap to re-skip)
            if inv.policy_blocks(sj.ident.ats, allow_smartrecruiters=d.allow_smartrecruiters):
                skipped_by_policy += 1  # same provider policy as board admission: no crawling that host
                continue
            hydrated += 1
            try:
                listed = d.hydrate_listed(sj)
            except RetryableHydration as exc:
                prev = pending.get(key) or {}
                attempts = int(prev.get("attempts", 0)) + 1
                pending_changed = True
                if attempts >= dsc.MAX_HYDRATION_ATTEMPTS:
                    pending.pop(key, None)
                    run.notes += f"search-found job {key} unreadable after {attempts} attempts, dropped ({exc}); "
                else:
                    pending[key] = dsc.pending_entry(sj, now, attempts, str(prev.get("first_at", "")))
                continue
            if pending.pop(key, None) is not None:
                pending_changed = True
            if listed is None:
                continue  # closed posting: nothing to observe
            board = boards.get(sj.ident.board_id.key)
            obs = lg.Observation(now, None, bool(board and board.baselined_at), False, "search", d.fresh_window, d.max_age_days, run_id=run.run_id)
            ev = lg.observe_new(listed, obs, d.title_gate)
            pending_events.append(ev)
            states[ev.key] = lg.replay([ev])[ev.key]
            run.new_jobs += 1
            run.verified_fresh += ev.freshness == fr.VERIFIED_FRESH
        if skipped_by_policy:
            run.notes += f"{skipped_by_policy} search-found SmartRecruiters jobs not read (provider policy); "

        if found is not None:
            # Reporting for this discovery: boards that cleared admission, boards promoted into
            # monitoring now, and unique result jobs proven fresh that match the user's titles.
            status_of = [boards[k].status for k in found_keys]
            run.result_boards = len(found_keys)
            run.eligible_boards = sum(1 for st_ in status_of if st_ in {STATUS_VALIDATED, *MONITORED})
            run.result_parked = sum(1 for st_ in status_of if st_ == STATUS_DEFERRED)
            run.result_invalid = sum(1 for st_ in status_of if st_ == STATUS_INVALID)
            run.result_awaiting_validation = sum(1 for st_ in status_of if st_ == STATUS_CANDIDATE)
            run.promoted_boards = sum(1 for k in found_keys if k in promoted_keys)
            run.verified_fresh_matches = sum(
                1 for k in found.job_keys if (st := states.get(k)) and st.freshness == fr.VERIFIED_FRESH and st.disposition == lg.PENDING
            )  # fmt: skip
            log.info(
                "Discovery: %d queries, %d pages, %d credits, %d repeated results | the results named %d unique boards: %d new to the registry + %d already known; "
                "of those %d eligible (validated or monitored, new or known), %d parked by provider policy, %d invalid, %d awaiting validation; "
                "%d of them promoted into monitoring this run | %d unique verified-fresh matches",
                len(found.queries), found.pages, found.credits, found.repeated, run.result_boards, run.new_unique_boards,
                run.result_boards - run.new_unique_boards, run.eligible_boards, run.result_parked, run.result_invalid,
                run.result_awaiting_validation, run.promoted_boards, run.verified_fresh_matches,
            )  # fmt: skip

        # Rule 1: observations are durable BEFORE the registry says "baselined".
        if not d.dry_run:
            d.state.append_events(pending_events)
            pending_events = []
            d.state.save_boards(dirty.values())
            # Rotation moves only after the boards it found are saved: a crash repeats a search
            # (harmless, results are deduplicated) instead of skipping one for a whole cycle.
            save_values = dict(discovery_state)
            if found is not None and not found.all_failed:
                slots_ran = found.slots_used
                if found.kind == dsc.KIND_ROTATION and d.rotation_slots:
                    save_values[dsc.ROTATION_KEY] = dsc.advance(rotation, d.rotation_slots, slots_ran, now).to_json()
                elif found.kind == dsc.KIND_BACKFILL and d.rotation_slots:
                    save_values[dsc.ROTATION_KEY] = dsc.advance_backfill(rotation, d.rotation_slots, slots_ran).to_json()
                save_values[dsc.LAST_RUN_KEY] = json.dumps({"at": lg.stamp(now), "kind": found.kind, "queries": found.summary()}, separators=(",", ":"))
            if pending_changed or pending:
                save_values[dsc.PENDING_KEY] = dsc.dump_pending(pending)
            save_values.update(rebalance_values)
            if save_values != discovery_state:
                d.state.save_discovery_state(save_values, lg.stamp(now))
        else:
            pending_events = []

        t_eval = time.monotonic()
        # ---------------------------------------------------------------- 3. evaluate
        todo = sorted((s for s in states.values() if lg.needs_evaluation(s)), key=lg.priority)
        if len(todo) > d.max_jobs:
            log.info("%d jobs awaiting evaluation; evaluating the %d highest priority", len(todo), d.max_jobs)
        for i, st in enumerate(todo[: d.max_jobs], 1):
            ident = JobIdentity(st.key.split("|")[0], str(st.seen_detail.get("board") or st.key.split("|")[1]), st.key.split("|", 2)[2])
            out = d.evaluate(ident, st)
            run.eval_attempted += 1
            if out.kind == "done" and out.payload is not None:
                payload = dict(out.payload, freshness=st.freshness, source=st.seen_detail.get("source", ""), alert=False, run=run.run_id)
                payload["alert"] = bool(st.freshness in fr.ALERTABLE and payload.get("status") == "To Apply")
                if payload.get("visible") and st.key not in d.tracked_keys:
                    pending_rows.append(payload)
                    d.tracked_keys.add(st.key)
                pending_events.append(lg.Event(lg.stamp(now), st.key, lg.EVALUATED, st.freshness, detail=payload))
                run.evaluated += 1
                states[st.key].evaluated, states[st.key].evaluated_time = payload, lg.stamp(now)
            elif out.kind == "transient":
                # A temporary outage records nothing: it must neither mark the job done nor
                # use up its bounded retry attempts. The next run simply tries again.
                run.eval_transient += 1
                log.warning("Transient failure evaluating %s (will retry): %s", st.key, out.message)
                run.notes += "transient evaluation failures; " if "transient evaluation" not in run.notes else ""
            else:
                run.eval_failed += 1
                pending_events += lg.failure_events(st.key, lg.STAGE_EVALUATE, out.message or out.kind, st, now, run.run_id)
                st.errors[lg.STAGE_EVALUATE] = st.errors.get(lg.STAGE_EVALUATE, 0) + 1
            if i % FLUSH_EVERY == 0:
                write()
        write()

        # ---------------------------------------------------------------- 4. alert
        for st in states.values():
            if not lg.needs_alert(st, now):
                continue
            if d.dry_run:
                log.info("[dry-run] would alert for %s", st.key)
                continue
            try:
                late = lg.alert_delay_note(st, now, d.fresh_window)  # retried past the window: still delivered, labelled
                sent = d.send_alert(dict(st.evaluated or {}, late=late) if late else (st.evaluated or {}))
            except Exception as exc:
                # Telegram/network trouble is retried on later runs without using up attempts;
                # only a rejected request (a 4xx that will never succeed) is bounded.
                run.alerts_failed += 1
                log.warning("Alert failed for %s (will retry): %s", st.key, exc)
                if getattr(getattr(exc, "response", None), "status_code", 500) < 500 and getattr(getattr(exc, "response", None), "status_code", 429) != 429:
                    pending_events += lg.failure_events(st.key, lg.STAGE_ALERT, str(exc), st, now, run.run_id)
                continue
            pub, _ = fr.parse_instant(st.last_published)
            lag = _minutes(now - pub) if pub else None
            pending_events.append(lg.Event(lg.stamp(now), st.key, lg.ALERTED, detail={"channel": "telegram" if sent else "none", "lag_min": lag, "late": bool(late), "run": run.run_id}))
            st.alerted = True
            run.alerts_sent += bool(sent)
            if sent and lag is not None and (run.max_alert_lag_min is None or lag > run.max_alert_lag_min):
                run.max_alert_lag_min = lag
            write()  # record the delivery immediately: shrinks the duplicate-alert window
        write()
        crashed = False
    finally:
        # Reached on success and on failure. A failing flush must not hide the original error
        # or skip the run record; the run record is what shows the user that something broke.
        try:
            write()
        except Exception as exc:
            log.error("Final state write failed: %s", exc)
            run.notes += f"final write failed: {exc}; "
        if t_eval is not None:
            run.evaluate_s = round(time.monotonic() - t_eval)
        used = METER.since(meter0)
        run.duration_s = round(time.monotonic() - t_start)
        run.sheets_reads, run.sheets_writes, run.sheets_429 = (int(used.get(k, 0)) for k in ("sheets_reads", "sheets_writes", "sheets_429"))
        run.ats_requests, run.ats_429, run.ats_seconds = int(used.get("ats_requests", 0)), int(used.get("ats_429", 0)), round(used.get("ats_seconds", 0))
        run.groq_calls, run.groq_429 = int(used.get("groq_calls", 0)), int(used.get("groq_429", 0))
        run.credit_status = run.credit_status or CREDIT_NONE
        run.finished_at = lg.stamp(d.now())
        run.outcome = OUTCOME_FAILED if crashed else OUTCOME_DEGRADED if degraded_reason(run) else OUTCOME_OK
        if not d.dry_run:
            try:
                d.state.finish_run(run)
            except Exception as exc:
                log.error("Could not complete the run record: %s", exc)
                try:  # the start record still says `started`; a second, finished record (same Run_ID) wins in reports
                    d.state.append_run(run)
                except Exception as exc2:
                    log.error("Could not record the run: %s", exc2)
    return run
