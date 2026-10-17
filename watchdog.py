"""Independent missed-run watchdog for the hourly Job Hunter.

Runs as its own workflow (own schedule, own concurrency group, not queued behind the hunter) and watches ONE fact:
when did a production polling run last finish successfully? It reads the `Runs` tab and nothing else of the hunter's
state; it never takes the writer lease, never restarts a workflow and never changes Settings. Its only writes are its
own incident record (a separate `Watchdog` tab) and Telegram messages to the one authorized operational recipient.

Standalone on purpose: it imports nothing from the hunter's modules (`hunter`, `state`, `boards`, ...), so a bad commit
to the hunter cannot also break the thing that is meant to notice it. It needs only `gspread` and `requests`.

Health vocabulary (see `evaluate`):
  healthy      a production run finished successfully within the threshold (default 2 hours)
  running      the last success is overdue, but a run started recently is still in progress: not an outage yet
  outage       overdue and nothing is in progress; `kind` says why: failed (the newest record is a failed run),
               stalled (a run started and never finished), absent (no run started at all)
  unavailable  the health data could not be read or has no usable production record: NOT proof the hunter stopped

Exit codes: 0 handled (healthy, running, or an outage whose notification went out), 3 monitoring unavailable (the
workflow shows as failed so GitHub's own failure e-mail covers a blind monitor), 4 configuration missing,
5 an outage or recovery notification could not be delivered (it is retried on the next run).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

log = logging.getLogger("watchdog")

STAMP = "%Y-%m-%dT%H:%M:%SZ"
RUNS_TAB, STATE_TAB = "Runs", "Watchdog"
DEFAULT_WARN_HOURS = 2.0
STALL_AFTER = timedelta(minutes=35)  # the hunter workflow times out at 25 minutes; a run started longer ago than this is not in progress
SUCCESS_OUTCOMES = {"ok", "degraded", ""}  # "" = a record written before outcomes existed (it finished)
REQUIRED_COLUMNS = ("Run_At",)
EXIT_OK, EXIT_UNAVAILABLE, EXIT_CONFIG, EXIT_NOTIFY = 0, 3, 4, 5


def parse_stamp(value: Any) -> datetime | None:
    try:
        return datetime.strptime(str(value).strip(), STAMP).replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def fmt(dt: datetime | None) -> str:
    return "unknown" if dt is None else dt.strftime("%Y-%m-%d %H:%M UTC")


def fmt_age(td: timedelta) -> str:
    minutes = max(0, int(td.total_seconds() // 60))
    h, m = divmod(minutes, 60)
    return f"{h} h {m:02d} min" if h else f"{m} min"


# --------------------------------------------------------------------------- reading the hunter's health (read only)


@dataclass(frozen=True)
class RunRow:
    run_at: datetime
    finished_at: datetime | None
    outcome: str  # started | ok | degraded | failed | "" (legacy)
    kind: str  # production | rehearsal | "" (unknown: counted as production)
    run_id: str = ""
    trigger: str = ""
    notes: str = ""


class UnreadableHealth(Exception):
    """The health data could not be read or understood: the caller reports 'monitoring unavailable'."""


def parse_runs(values: list[list[str]]) -> list[RunRow]:
    """Rows of the Runs tab (header first) -> RunRow. Columns are found by NAME, so the tab can grow new columns."""
    if not values or not values[0]:
        raise UnreadableHealth("the Runs tab is empty (no header row)")
    header = [h.strip() for h in values[0]]
    missing = [c for c in REQUIRED_COLUMNS if c not in header]
    if missing:
        raise UnreadableHealth(f"the Runs tab has no {', '.join(missing)} column")
    idx = {name: i for i, name in enumerate(header)}

    def cell(row: list[str], name: str) -> str:
        i = idx.get(name)
        return row[i].strip() if i is not None and i < len(row) else ""

    out: list[RunRow] = []
    for row in values[1:]:
        run_at = parse_stamp(cell(row, "Run_At"))
        if run_at is None:
            continue  # a blank or hand-edited row says nothing
        notes = cell(row, "Notes")
        trigger = next((p.split("=", 1)[1] for p in notes.split("; ") if p.startswith("trigger=")), "")
        out.append(RunRow(run_at, parse_stamp(cell(row, "Finished_At")), cell(row, "Outcome").lower(), cell(row, "Run_Kind").lower(), cell(row, "Run_ID"), trigger, notes))
    return out


@dataclass(frozen=True)
class Health:
    status: str  # healthy | running | outage | unavailable
    kind: str = ""  # outage only: failed | stalled | absent
    last_success_at: datetime | None = None
    age: timedelta | None = None  # since the last success
    detail: str = ""
    latest_run_at: datetime | None = None
    latest_outcome: str = ""
    active_run_at: datetime | None = None


def evaluate(rows: list[RunRow], now: datetime, warn: timedelta = timedelta(hours=DEFAULT_WARN_HOURS), stall_after: timedelta = STALL_AFTER) -> Health:
    """Classify the hunter from its run records. Rehearsal runs are ignored; a record whose Run_Kind is blank counts
    (it was written before the kind existed)."""
    prod = [r for r in rows if r.kind != "rehearsal"]
    if not prod:
        return Health("unavailable", detail="no production run is recorded in the Runs tab, so there is nothing to judge")
    prod.sort(key=lambda r: r.run_at)
    successes = [r for r in prod if r.outcome in SUCCESS_OUTCOMES and r.outcome != "started"]
    latest = prod[-1]
    if not successes:
        return Health("unavailable", detail="no production run has finished successfully yet", latest_run_at=latest.run_at, latest_outcome=latest.outcome)
    last = max(successes, key=lambda r: r.finished_at or r.run_at)
    last_at = last.finished_at or last.run_at
    age = now - last_at
    base = dict(last_success_at=last_at, age=age, latest_run_at=latest.run_at, latest_outcome=latest.outcome or "ok")
    if age <= warn:
        return Health("healthy", detail=f"last success {fmt_age(age)} ago", **base)
    after = [r for r in prod if r.run_at > last.run_at]
    active = [r for r in after if r.outcome == "started" and now - r.run_at <= stall_after]
    if active:
        a = max(active, key=lambda r: r.run_at)
        return Health("running", detail=f"a run started {fmt_age(now - a.run_at)} ago is still in progress (last success {fmt_age(age)} ago)", active_run_at=a.run_at, **base)
    if after:
        newest = after[-1]
        if newest.outcome == "started":
            return Health("outage", kind="stalled", detail=f"a run started {fmt_age(now - newest.run_at)} ago and never finished", **base)
        if newest.outcome == "failed":
            return Health("outage", kind="failed", detail=f"the newest run (started {fmt(newest.run_at)}) failed" + (f": {newest.notes[:120]}" if newest.notes else ""), **base)
    return Health("outage", kind="absent", detail=f"no run has started since {fmt(last.run_at)}", **base)


# --------------------------------------------------------------------------- incident state and notifications


class Store(Protocol):
    def read_runs(self) -> list[list[str]]: ...
    def load_state(self) -> dict[str, Any]: ...
    def save_state(self, state: dict[str, Any], now: datetime) -> None: ...


Notifier = Callable[[str], None]  # raises on failure


@dataclass
class Outcome:
    health: Health
    actions: list[str] = field(default_factory=list)  # what was (or, in a dry run, would be) done
    exit_code: int = EXIT_OK


def outage_text(h: Health, warn: timedelta) -> str:
    why = {
        "failed": "the newest polling run failed",
        "stalled": "a polling run started and never finished (timed out, was cancelled or lost its runner)",
        "absent": "no polling run has started (the hourly trigger may have stopped)",
    }.get(h.kind, "polling is overdue")
    return (
        f"Job Hunter: no successful polling run for {fmt_age(h.age or timedelta())} (warning threshold {fmt_age(warn)}).\n"
        f"Cause: {why}.\nLast success: {fmt(h.last_success_at)}. Detail: {h.detail}.\n"
        "Check GitHub Actions > Job Hunter. This is the only outage message for this incident; a recovery message follows when polling resumes."
    )


def recovery_text(h: Health, incident: dict[str, Any], now: datetime) -> str:
    opened = parse_stamp(incident.get("opened_at"))
    last_ok = parse_stamp(incident.get("last_success_at"))
    span = f"; no success between {fmt(last_ok)} and {fmt(h.last_success_at)} ({fmt_age((h.last_success_at or now) - last_ok)})" if last_ok and h.last_success_at else ""
    return (
        f"Job Hunter recovered: a polling run finished at {fmt(h.last_success_at)}.\n"
        f"The outage was flagged at {fmt(opened)}{span}. Jobs published during the gap were not polled live; they are detected on the next poll and labelled by their real age."
    )


def step(store: Store, notify: Notifier, now: datetime, warn: timedelta = timedelta(hours=DEFAULT_WARN_HOURS), *, dry_run: bool = False) -> Outcome:
    """One watchdog check: read health, then move the persisted incident state at most one step.

    One outage message per incident and one recovery message: the incident is saved BEFORE the send, and
    `notified` / `recovery_sent` flip only after the send succeeded, so a failed send is retried next run (never
    lost) and a successful one is never repeated unless the save after it fails (then it is repeated once at most)."""
    try:
        health = evaluate(parse_runs(store.read_runs()), now, warn)
    except UnreadableHealth as exc:
        health = Health("unavailable", detail=str(exc))
    except Exception as exc:  # noqa: BLE001 - any failure to read is "monitoring unavailable", never "the hunter stopped"
        health = Health("unavailable", detail=f"could not read the health data: {type(exc).__name__}: {str(exc)[:160]}")
    out = Outcome(health)
    if health.status == "unavailable":
        out.actions.append("monitoring unavailable: no state changed, no notification sent (this is not evidence that the hunter stopped)")
        out.exit_code = EXIT_UNAVAILABLE
        return out
    try:
        state = store.load_state()
    except Exception as exc:  # noqa: BLE001
        out.health = Health("unavailable", detail=f"could not read the watchdog state: {type(exc).__name__}: {str(exc)[:160]}")
        out.actions.append("monitoring unavailable: the incident state could not be read, so no notification was sent")
        out.exit_code = EXIT_UNAVAILABLE
        return out
    incident = state.get("incident") if isinstance(state.get("incident"), dict) else None
    state["last_checked_at"], state["last_status"] = now.strftime(STAMP), health.status

    def save() -> None:
        if not dry_run:
            store.save_state(state, now)

    def send(text: str, what: str) -> bool:
        if dry_run:
            out.actions.append(f"[dry run] would send the {what} notification")
            return True
        try:
            notify(text)
        except Exception as exc:  # noqa: BLE001
            out.actions.append(f"the {what} notification could not be delivered ({type(exc).__name__}: {str(exc)[:120]}); retried next run")
            out.exit_code = EXIT_NOTIFY
            return False
        out.actions.append(f"sent the {what} notification")
        return True

    if health.status == "outage":
        if incident is None:
            incident = state["incident"] = {"opened_at": now.strftime(STAMP), "kind": health.kind, "notified": False,
                                            "last_success_at": health.last_success_at.strftime(STAMP) if health.last_success_at else ""}  # fmt: skip
            out.actions.append(f"incident opened ({health.kind})")
            save()
        else:
            incident["kind"] = health.kind  # the cause may change while the incident stays one incident
        if not incident.get("notified"):
            if send(outage_text(health, warn), "outage"):
                incident["notified"] = True
                incident["notified_at"] = now.strftime(STAMP)
        else:
            out.actions.append("incident already notified: nothing sent")
        save()
    elif health.status == "healthy":
        if incident is not None:
            if not incident.get("notified"):
                state["incident"] = None  # it recovered before any outage message went out: nothing to recover from
                out.actions.append("incident closed without a notification (the outage message had never been delivered)")
                save()
            elif send(recovery_text(health, incident, now), "recovery"):
                state["incident"] = None
                state["last_incident"] = {**incident, "closed_at": now.strftime(STAMP)}
                save()
        else:
            out.actions.append("healthy")
            save()
    else:  # running: an overdue run is still in progress; neither open nor close anything
        out.actions.append("a run is in progress: nothing changed")
        save()
    return out


# --------------------------------------------------------------------------- real store and Telegram


def load_service_account(value: str) -> dict[str, Any]:
    text = value.strip()
    if text.startswith("{"):
        return json.loads(text, strict=False)
    path = Path(text).expanduser()
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"), strict=False)
    raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON is neither JSON text nor a path to a .json file")


class SheetStore:
    """Reads the hunter's `Runs` tab (read only) and keeps its own incident record in a separate `Watchdog` tab."""

    def __init__(self, sheet_id: str, credentials: str) -> None:
        import gspread

        self.sh = gspread.service_account_from_dict(load_service_account(credentials)).open_by_key(sheet_id)

    def read_runs(self) -> list[list[str]]:
        return self.sh.worksheet(RUNS_TAB).get_all_values()

    def load_state(self) -> dict[str, Any]:
        try:
            ws = self.sh.worksheet(STATE_TAB)
        except Exception as exc:  # a missing tab is the first run; any other failure must not look like "no incident"
            if exc.__class__.__name__ == "WorksheetNotFound":
                return {}
            raise
        rows = ws.get_all_values()
        raw = rows[1][1] if len(rows) > 1 and len(rows[1]) > 1 else ""
        try:
            data = json.loads(raw) if raw else {}
        except ValueError:
            raise RuntimeError("the Watchdog tab holds unreadable state") from None
        return data if isinstance(data, dict) else {}

    def save_state(self, state: dict[str, Any], now: datetime) -> None:
        try:
            ws = self.sh.worksheet(STATE_TAB)
        except Exception as exc:
            if exc.__class__.__name__ != "WorksheetNotFound":
                raise
            ws = self.sh.add_worksheet(title=STATE_TAB, rows=5, cols=3)
            ws.update(values=[["Key", "Value", "Updated_At"]], range_name="A1", value_input_option="RAW")
            try:
                ws.hide()
            except Exception as hide_exc:  # cosmetic
                log.warning("Could not hide the Watchdog tab: %s", hide_exc)
        ws.update(values=[["state", json.dumps(state, separators=(",", ":"), sort_keys=True), now.strftime(STAMP)]], range_name="A2", value_input_option="RAW")


def telegram_notifier(token: str, chat_id: str, post: Callable[..., Any] | None = None) -> Notifier:
    def send(text: str) -> None:
        import requests

        resp = (post or requests.post)(f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True}, timeout=15)
        resp.raise_for_status()

    return send


# --------------------------------------------------------------------------- command line


def main(argv: list[str] | None = None, *, now: datetime | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--dry-run", action="store_true", help="read and report only: no state is written, no notification is sent")
    parser.add_argument("--warn-hours", type=float, default=None, help=f"warning threshold in hours (default {DEFAULT_WARN_HOURS:g}; env WATCHDOG_WARN_HOURS)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        warn_hours = args.warn_hours if args.warn_hours is not None else float(os.getenv("WATCHDOG_WARN_HOURS") or DEFAULT_WARN_HOURS)
        if warn_hours <= 0:
            raise ValueError("must be positive")
    except ValueError as exc:
        log.error("Invalid warning threshold: %s", exc)
        return EXIT_CONFIG
    env = {k: (os.getenv(k) or "").strip() for k in ("GOOGLE_SHEET_ID", "GOOGLE_SERVICE_ACCOUNT_JSON", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")}
    missing = [k for k in env if not env[k] and not (args.dry_run and k.startswith("TELEGRAM"))]
    if missing:
        log.error("Missing configuration (names only): %s", ", ".join(missing))
        return EXIT_CONFIG
    try:
        store = SheetStore(env["GOOGLE_SHEET_ID"], env["GOOGLE_SERVICE_ACCOUNT_JSON"])
    except Exception as exc:  # noqa: BLE001 - cannot even open the Sheet: monitoring is unavailable, not the hunter stopped
        log.error("MONITORING UNAVAILABLE: could not open the Sheet (%s: %s)", type(exc).__name__, str(exc)[:200])
        return EXIT_UNAVAILABLE
    outcome = step(store, telegram_notifier(env["TELEGRAM_BOT_TOKEN"], env["TELEGRAM_CHAT_ID"]), now or datetime.now(timezone.utc),
                   timedelta(hours=warn_hours), dry_run=args.dry_run)  # fmt: skip
    h = outcome.health
    log.info("WATCHDOG %s%s | %s | threshold %s | last success %s | %s", h.status.upper(), f" ({h.kind})" if h.kind else "", h.detail, fmt_age(timedelta(hours=warn_hours)), fmt(h.last_success_at), "; ".join(outcome.actions))
    if outcome.exit_code == EXIT_UNAVAILABLE:
        log.error("MONITORING UNAVAILABLE: %s", h.detail)
    return outcome.exit_code


if __name__ == "__main__":
    sys.exit(main())
