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

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import discovery as dsc
import freshness as fr
import inventory as inv
import ledger as lg
from boards import (
    MONITORED, SMARTRECRUITERS, STATUS_ACTIVE, STATUS_VALIDATED, BoardId, BoardRecord, JobIdentity, ListedJob,
    activate_waiting, fetch_board, poll_boards, registry_counts, apply_poll_result,
)  # fmt: skip
from discovery import SerperJob  # noqa: F401  (re-exported: hunter and the tests import it from here)
from state import RunRecord

log = logging.getLogger("hunter")

FLUSH_EVERY = 10
FLOOD_MIN_JOBS = 30  # a baselined board suddenly showing this many unseen IDs is treated as a re-baseline
SUSPICIOUS_EMPTY_AFTER = 3  # an empty listing from a board that had more than this many jobs is a glitch
MAX_SERPER_HYDRATIONS = 20


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
    hydrate_listed: Callable[[SerperJob], ListedJob | None] | None = None
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)
    fresh_window: timedelta = timedelta(hours=fr.DEFAULT_FRESH_WINDOW_HOURS)
    max_age_days: int = fr.DEFAULT_MAX_AGE_DAYS
    max_jobs: int = 30
    discovery_every_hours: int = 12
    force_discovery: bool = False
    max_monitored_boards: int = 500  # polling budget: validated boards are only promoted up to this many
    max_new_boards_per_run: int = 50  # each promotion baselines a whole board, so surges are capped
    seeds: list[BoardId] = field(default_factory=list)  # manually registered boards (testing / bootstrap)
    allow_smartrecruiters: bool = False  # ALLOW_SMARTRECRUITERS_BULK: provider policy for EVERY source
    max_inline_validations: int = 40  # boards from one discovery validated in the run; the rest wait as candidates
    rotation_slots: list[dsc.Slot] = field(default_factory=list)  # the rotation the discover callable searched from
    config_notes: list[str] = field(default_factory=list)  # settings problems to surface in the run record
    workers: int = 8
    sleep: Callable[[float], None] = time.sleep  # backoff between validation retries (tests pass a no-op)
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

    try:
        def admit(found: list[BoardId], source: str) -> inv.AdmissionResult:
            """The one admission path (inventory import, Serper, manual seeds)."""
            adm = inv.admit_boards(
                boards, found, source=source, now=now, fetch=d.fetch, title_gate=d.title_gate,
                allow_smartrecruiters=d.allow_smartrecruiters, max_inline_validations=d.max_inline_validations, sleep=d.sleep,
            )  # fmt: skip
            dirty.update(adm.touched)
            run.boards_added += adm.added
            return adm

        if d.config_notes:
            run.notes += "".join(f"{n}; " for n in d.config_notes)
        if d.seeds:
            admit(d.seeds, "seed")

        # ---------------------------------------------------------------- 1. discovery loop
        # Search is candidate retrieval only. Every result is processed twice, independently:
        # its BOARD goes through admission, its JOB (if unseen) through hydration -> pipeline.
        serper_jobs: list[SerperJob] = []
        found: dsc.DiscoveryResult | None = None
        found_keys: list[str] = []
        discovery_state = d.state.load_discovery_state()
        rotation = dsc.RotationState.from_json(discovery_state.get(dsc.ROTATION_KEY))
        pending = dsc.load_pending(discovery_state.get(dsc.PENDING_KEY))
        if d.discover and (d.force_discovery or discovery_due(runs, now, d.discovery_every_hours)):
            run.discovery = True
            try:
                ctx = DiscoveryContext(
                    now, rotation,
                    is_new_board=lambda b: b.key not in boards,
                    is_unseen_job=lambda i: not (states.get(i.key) and states[i.key].seen),
                )  # fmt: skip
                found = d.discover(ctx)
                adm = admit(found.boards, "serper")
                found_keys = adm.keys
                serper_jobs = found.jobs
                run.search_queries, run.search_pages, run.search_credits = len(found.queries), found.pages, found.credits
                run.search_repeated, run.new_unique_boards = found.repeated, adm.added
                run.notes += (
                    f"{found.kind} discovery: {len(found.queries)} queries, {found.pages} pages, {found.credits} credits"
                    f"{', stopped: ' + found.stopped if found.stopped else ''}; "
                    f"{adm.parked} boards parked by provider policy, {adm.rejected} rejected; "
                )  # fmt: skip
                if found.all_failed:
                    run.notes += "every search request failed (rotation not advanced); "
                for q in found.queries:
                    log.info(
                        "Query %s [tbs=%s]: %d pages, %d credits, %d results, %d repeated, %d new boards, %d unseen jobs, %d unparsed, stop=%s%s",
                        q.id, q.tbs or "none", q.pages, q.credits, q.results, q.repeated, q.new_boards, q.unseen_jobs, q.unparsed, q.stop,
                        f", error={q.error}" if q.error else "",
                    )  # fmt: skip
            except Exception as exc:  # discovery is best-effort; polling must still happen
                log.warning("Discovery failed: %s", exc)
                run.notes += f"discovery failed: {exc}; "
                found = None

        # ---------------------------------------------------------------- 2. polling loop
        # Validated inventory boards enter monitoring only within the polling budget; the poll
        # below then baselines them (their existing jobs never look "just posted").
        promoted_keys: set[str] = set()
        for rec in activate_waiting(boards, max_monitored=d.max_monitored_boards, per_run=d.max_new_boards_per_run):
            dirty[rec.key] = rec
            promoted_keys.add(rec.key)
            run.boards_activated += 1
        parked_monitored = sum(1 for b in boards.values() if b.ats == SMARTRECRUITERS and b.status in MONITORED and not d.allow_smartrecruiters)
        if parked_monitored:
            log.warning("%d SmartRecruiters boards are monitored from before the provider policy; set ALLOW_SMARTRECRUITERS_BULK=1 or park them", parked_monitored)
            run.notes += f"{parked_monitored} SmartRecruiters boards monitored from before the parked policy; "
        active = [b for b in boards.values() if b.status in MONITORED]
        run.boards_total = len(active)
        max_gap: timedelta | None = None
        for res in poll_boards(active, fetch=d.fetch, workers=d.workers):
            was_baselined = bool(res.board.baselined_at)
            if res.ok and not res.jobs and res.board.last_job_count > SUSPICIOUS_EMPTY_AFTER:
                res.ok, res.error = False, "suspicious empty listing (previously had jobs)"
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
        counts = registry_counts(boards)
        run.boards_discovered, run.boards_validated, run.boards_monitored = counts["discovered"], counts["validated"], counts["monitored"]

        # Search-found jobs not on any listing we read: hydrate for an authoritative date first
        # (Google's window says when a page was indexed, never when the job was published).
        # Temporary read failures are queued and retried on later runs without spending credits.
        candidates: dict[str, SerperJob] = {}
        for key, entry in pending.items():
            if (job := dsc.job_from_pending(entry)) is not None:
                candidates[key] = job
        for sj in serper_jobs:
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
            if hydrated >= MAX_SERPER_HYDRATIONS:
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
            obs = lg.Observation(now, None, bool(board and board.baselined_at), False, "serper", d.fresh_window, d.max_age_days)
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
            run.eligible_boards = sum(1 for k in found_keys if boards[k].status in {STATUS_VALIDATED, *MONITORED})
            run.promoted_boards = sum(1 for k in found_keys if k in promoted_keys)
            run.verified_fresh_matches = sum(
                1 for k in found.job_keys if (st := states.get(k)) and st.freshness == fr.VERIFIED_FRESH and st.disposition == lg.PENDING
            )  # fmt: skip
            log.info(
                "Discovery: %d queries, %d pages, %d credits, %d repeated | boards: %d new unique, %d eligible, %d promoted | %d unique verified-fresh matches",
                len(found.queries), found.pages, found.credits, found.repeated, run.new_unique_boards, run.eligible_boards,
                run.promoted_boards, run.verified_fresh_matches,
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
                save_values[dsc.LAST_RUN_KEY] = json.dumps({"at": lg.stamp(now), "kind": found.kind, "queries": found.summary()}, separators=(",", ":"))
            if pending_changed or pending:
                save_values[dsc.PENDING_KEY] = dsc.dump_pending(pending)
            if save_values != discovery_state:
                d.state.save_discovery_state(save_values, lg.stamp(now))
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
            try:
                late = lg.alert_delay_note(st, now, d.fresh_window)  # retried past the window: still delivered, labelled
                sent = d.send_alert(dict(st.evaluated or {}, late=late) if late else (st.evaluated or {}))
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
            pending_events.append(lg.Event(lg.stamp(now), st.key, lg.ALERTED, detail={"channel": "telegram" if sent else "none", "lag_min": lag, "late": bool(late)}))
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
