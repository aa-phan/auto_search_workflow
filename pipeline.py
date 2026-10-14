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

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import freshness as fr
import ledger as lg
from boards import (
    STATUS_ACTIVE, STATUS_DISABLED, BoardId, BoardRecord, JobIdentity, ListedJob, fetch_board,
    poll_boards, upsert_boards, apply_poll_result,
)  # fmt: skip
from state import RunRecord

log = logging.getLogger("hunter")

FLUSH_EVERY = 10
FLOOD_MIN_JOBS = 30  # a baselined board suddenly showing this many unseen IDs is treated as a re-baseline
SUSPICIOUS_EMPTY_AFTER = 3  # an empty listing from a board that had more than this many jobs is a glitch
MAX_SERPER_HYDRATIONS = 20


class FatalRunError(Exception):
    """Stop the whole run (e.g. an invalid API key); already-completed work is still flushed."""


@dataclass(frozen=True)
class SerperJob:
    ident: JobIdentity
    title: str
    url: str


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
    discover: Callable[[], tuple[list[BoardId], list[SerperJob]]] | None = None
    hydrate_listed: Callable[[SerperJob], ListedJob | None] | None = None
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)
    fresh_window: timedelta = timedelta(hours=fr.DEFAULT_FRESH_WINDOW_HOURS)
    max_age_days: int = fr.DEFAULT_MAX_AGE_DAYS
    max_jobs: int = 30
    discovery_every_hours: int = 12
    force_discovery: bool = False
    seeds: list[BoardId] = field(default_factory=list)  # manually registered boards (testing / bootstrap)
    workers: int = 8
    dry_run: bool = False


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


def run_cycle(d: Deps) -> RunRecord:
    now = d.now()
    d.state.ensure()
    boards = d.state.load_boards()
    states = lg.replay(d.state.load_events())
    runs = d.state.load_runs()
    run = RunRecord(lg.stamp(now))
    if runs and (prev := _parse_stamp(runs[-1].run_at, now.tzinfo)):
        run.gap_since_prev_run_min = _minutes(now - prev)
    pending_events: list[lg.Event] = []
    pending_rows: list[dict[str, Any]] = []

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

    try:
        if d.seeds:
            run.boards_added += len(upsert_boards(boards, d.seeds, now=now, source="seed"))

        # ---------------------------------------------------------------- 1. discovery loop
        serper_jobs: list[SerperJob] = []
        if d.discover and (d.force_discovery or discovery_due(runs, now, d.discovery_every_hours)):
            run.discovery = True
            try:
                found, serper_jobs = d.discover()
                run.boards_added += len(upsert_boards(boards, found, now=now, source="serper"))
            except Exception as exc:  # discovery is best-effort; polling must still happen
                log.warning("Discovery failed: %s", exc)
                run.notes += f"discovery failed: {exc}; "

        # ---------------------------------------------------------------- 2. polling loop
        active = [b for b in boards.values() if b.status != STATUS_DISABLED]
        run.boards_total = len(active)
        max_gap: timedelta | None = None
        for res in poll_boards(active, fetch=d.fetch, workers=d.workers):
            was_baselined = bool(res.board.baselined_at)
            if res.ok and not res.jobs and res.board.last_job_count > SUSPICIOUS_EMPTY_AFTER:
                res.ok, res.error = False, "suspicious empty listing (previously had jobs)"
            rec, gap = apply_poll_result(res, now=now)
            boards[rec.key] = rec
            if not res.ok:
                run.boards_failed += 1
                continue
            run.boards_ok += 1
            if gap is not None and (max_gap is None or gap > max_gap):
                max_gap = gap
            unseen = [j for j in res.jobs if not (states.get(j.ident.key) and states[j.ident.key].seen)]
            baseline_pass = not was_baselined
            if was_baselined and len(unseen) >= FLOOD_MIN_JOBS and len(unseen) > len(res.jobs) / 2:
                log.warning("Board %s: %d of %d IDs unseen; treating as a re-baseline", rec.key, len(unseen), len(res.jobs))
                run.notes += f"{rec.key} re-baselined; "
                baseline_pass = True
            obs = lg.Observation(now, gap, was_baselined, baseline_pass, "poll", d.fresh_window, d.max_age_days)
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
            if baseline_pass and not rec.baselined_at:
                rec.baselined_at, rec.status = lg.stamp(now), STATUS_ACTIVE
        run.max_board_gap_min = _minutes(max_gap)

        # Serper-found jobs not on any listing we read: hydrate for an authoritative date first.
        hydrated = 0
        for sj in serper_jobs:
            st = states.get(sj.ident.key)
            if (st and st.seen) or not d.hydrate_listed or hydrated >= MAX_SERPER_HYDRATIONS:
                continue
            if d.title_gate(sj.title) is not None:
                continue  # cheap gate before any fetch; not recorded (cheap to re-skip)
            hydrated += 1
            listed = d.hydrate_listed(sj)
            if listed is None:
                continue
            board = boards.get(sj.ident.board_id.key)
            obs = lg.Observation(now, None, bool(board and board.baselined_at), False, "serper", d.fresh_window, d.max_age_days)
            ev = lg.observe_new(listed, obs, d.title_gate)
            pending_events.append(ev)
            states[ev.key] = lg.replay([ev])[ev.key]
            run.new_jobs += 1
            run.verified_fresh += ev.freshness == fr.VERIFIED_FRESH

        # Rule 1: observations are durable BEFORE the registry says "baselined".
        if not d.dry_run:
            d.state.append_events(pending_events)
            pending_events = []
            d.state.save_boards(boards)
        else:
            pending_events = []

        # ---------------------------------------------------------------- 3. evaluate
        todo = sorted((s for s in states.values() if lg.needs_evaluation(s)), key=lg.priority)
        if len(todo) > d.max_jobs:
            log.info("%d jobs awaiting evaluation; evaluating the %d highest priority", len(todo), d.max_jobs)
        for i, st in enumerate(todo[: d.max_jobs], 1):
            ident = JobIdentity(st.key.split("|")[0], str(st.seen_detail.get("board") or st.key.split("|")[1]), st.key.split("|", 2)[2])
            out = d.evaluate(ident, st)
            if out.kind == "done" and out.payload is not None:
                payload = dict(out.payload, freshness=st.freshness, source=st.seen_detail.get("source", ""), alert=False)
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
                log.warning("Transient failure evaluating %s (will retry): %s", st.key, out.message)
                run.notes += "transient evaluation failures; " if "transient evaluation" not in run.notes else ""
            else:
                pending_events += lg.failure_events(st.key, lg.STAGE_EVALUATE, out.message or out.kind, st, now)
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
            if lg.alert_too_late(st, now):
                pending_events.append(lg.Event(lg.stamp(now), st.key, lg.ABANDONED, detail={"stage": lg.STAGE_ALERT, "reason": "too late to be fresh news"}))
                continue
            try:
                sent = d.send_alert(st.evaluated or {})
            except Exception as exc:
                # Telegram/network trouble is retried on later runs without using up attempts;
                # only a rejected request (a 4xx that will never succeed) is bounded.
                run.alerts_failed += 1
                log.warning("Alert failed for %s (will retry): %s", st.key, exc)
                if getattr(getattr(exc, "response", None), "status_code", 500) < 500 and getattr(getattr(exc, "response", None), "status_code", 429) != 429:
                    pending_events += lg.failure_events(st.key, lg.STAGE_ALERT, str(exc), st, now)
                continue
            pub, _ = fr.parse_instant(st.last_published)
            lag = _minutes(now - pub) if pub else None
            pending_events.append(lg.Event(lg.stamp(now), st.key, lg.ALERTED, detail={"channel": "telegram" if sent else "none", "lag_min": lag}))
            st.alerted = True
            run.alerts_sent += bool(sent)
            if sent and lag is not None and (run.max_alert_lag_min is None or lag > run.max_alert_lag_min):
                run.max_alert_lag_min = lag
            write()  # record the delivery immediately: shrinks the duplicate-alert window
        write()
    finally:
        # Reached on success and on failure. A failing flush must not hide the original error
        # or skip the run record; the run record is what shows the user that something broke.
        try:
            write()
        except Exception as exc:
            log.error("Final state write failed: %s", exc)
            run.notes += f"final write failed: {exc}; "
        if not d.dry_run:
            try:
                d.state.append_run(run)
            except Exception as exc:
                log.error("Could not record the run: %s", exc)
    return run
