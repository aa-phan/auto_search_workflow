"""Isolated tests for the missed-run watchdog: stale, running, recovered and unreadable states, incident dedupe,
failed-send retry, dry run and independence from the hunter's code. No network, no Sheet, no Telegram: the store and
the notifier are fakes, so nothing here touches production."""

from __future__ import annotations

import ast
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import watchdog as wd  # noqa: E402

NOW = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
HEADER = ["Run_At", "Notes", "Run_ID", "Finished_At", "Outcome", "Run_Kind", "Some_Future_Column"]
WARN = timedelta(hours=2)


def stamp(dt: datetime) -> str:
    return dt.strftime(wd.STAMP)


def row(minutes_ago: float, outcome: str = "ok", *, kind: str = "production", finished: bool = True, notes: str = "trigger=workflow_dispatch:external; ") -> list[str]:
    start = NOW - timedelta(minutes=minutes_ago)
    end = stamp(start + timedelta(minutes=2)) if finished and outcome != "started" else ""
    return [stamp(start), notes, f"id-{minutes_ago}", end, outcome, kind, ""]


class FakeStore:
    def __init__(self, rows: list[list[str]] | None = None, state: dict[str, Any] | None = None) -> None:
        self.rows = [HEADER] + (rows or [])
        self.state = state or {}
        self.read_error: Exception | None = None
        self.state_error: Exception | None = None
        self.saves = 0

    def read_runs(self) -> list[list[str]]:
        if self.read_error:
            raise self.read_error
        return self.rows

    def load_state(self) -> dict[str, Any]:
        if self.state_error:
            raise self.state_error
        return dict(self.state)

    def save_state(self, state: dict[str, Any], now: datetime) -> None:
        self.saves += 1
        self.state = dict(state)


class Notifier:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self.fail = False

    def __call__(self, text: str) -> None:
        if self.fail:
            raise ConnectionError("telegram unreachable")
        self.sent.append(text)


def check(store: FakeStore, notify: Notifier, minutes_later: float = 0, **kw: Any) -> wd.Outcome:
    return wd.step(store, notify, NOW + timedelta(minutes=minutes_later), WARN, **kw)


class EvaluateTests(unittest.TestCase):
    def health(self, rows: list[list[str]], **kw: Any) -> wd.Health:
        return wd.evaluate(wd.parse_runs([HEADER] + rows), NOW, WARN, **kw)

    def test_recent_success_is_healthy_even_after_one_failed_run(self) -> None:
        h = self.health([row(100, "ok"), row(30, "failed")])
        self.assertEqual((h.status, h.last_success_at), ("healthy", NOW - timedelta(minutes=98)))

    def test_threshold_boundary(self) -> None:
        self.assertEqual(self.health([row(118, "ok")]).status, "healthy")  # finished exactly 116 min ago
        self.assertEqual(self.health([row(124, "ok")]).status, "outage")  # finished 122 min ago: past the 2-hour threshold

    def test_stale_with_a_failed_newest_run(self) -> None:
        h = self.health([row(300, "ok"), row(60, "failed", notes="trigger=schedule; final write failed: boom; ")])
        self.assertEqual((h.status, h.kind), ("outage", "failed"))
        self.assertIn("final write failed", h.detail)

    def test_stale_with_a_run_that_never_finished_is_stalled(self) -> None:
        h = self.health([row(300, "ok"), row(90, "started", finished=False)])
        self.assertEqual((h.status, h.kind), ("outage", "stalled"))

    def test_stale_with_nothing_started_is_absent(self) -> None:
        h = self.health([row(300, "ok"), row(200, "ok", kind="rehearsal")])  # a rehearsal run does not count as hunter activity
        self.assertEqual((h.status, h.kind), ("outage", "absent"))

    def test_overdue_but_a_run_is_in_progress_is_running_not_an_outage(self) -> None:
        h = self.health([row(300, "ok"), row(10, "started", finished=False)])
        self.assertEqual((h.status, h.active_run_at), ("running", NOW - timedelta(minutes=10)))

    def test_an_old_started_row_is_not_in_progress(self) -> None:
        self.assertEqual(self.health([row(300, "ok"), row(36, "started", finished=False)]).kind, "stalled")
        self.assertEqual(self.health([row(300, "ok"), row(34, "started", finished=False)]).status, "running")  # inside the stall limit

    def test_legacy_rows_without_outcomes_count_as_finished(self) -> None:
        legacy = [stamp(NOW - timedelta(minutes=30)), "", "", "", "", "", ""]
        self.assertEqual(self.health([legacy]).status, "healthy")

    def test_degraded_runs_are_successful_polls(self) -> None:
        self.assertEqual(self.health([row(40, "degraded")]).status, "healthy")

    def test_rehearsal_runs_never_make_it_healthy(self) -> None:
        self.assertEqual(self.health([row(300, "ok"), row(5, "ok", kind="rehearsal")]).status, "outage")

    def test_no_usable_production_record_is_unavailable_not_an_outage(self) -> None:
        for rows in ([], [row(5, "ok", kind="rehearsal")], [row(60, "failed")], [row(30, "started", finished=False)]):
            self.assertEqual(self.health(rows).status, "unavailable", rows)

    def test_columns_are_found_by_name_and_garbage_rows_are_skipped(self) -> None:
        values = [["Notes", "Run_At", "Brand_New"], ["x", stamp(NOW - timedelta(minutes=5)), "y"], ["bad", "not a date", ""], []]
        self.assertEqual(len(wd.parse_runs(values)), 1)
        with self.assertRaises(wd.UnreadableHealth):
            wd.parse_runs([["Nothing"], ["x"]])
        with self.assertRaises(wd.UnreadableHealth):
            wd.parse_runs([])


class IncidentLifecycleTests(unittest.TestCase):
    def test_one_outage_message_however_many_checks_see_the_outage(self) -> None:
        store, n = FakeStore([row(300, "ok")]), Notifier()
        first = check(store, n)
        self.assertEqual((first.health.status, len(n.sent), first.exit_code), ("outage", 1, 0))
        self.assertIn("no successful polling run for 4 h 58 min", n.sent[0])
        self.assertTrue(store.state["incident"]["notified"])
        for i in range(1, 6):
            again = check(store, n, minutes_later=15 * i)
            self.assertIn("already notified", " ".join(again.actions))
        self.assertEqual(len(n.sent), 1)

    def test_recovery_is_sent_once_and_closes_the_incident(self) -> None:
        store, n = FakeStore([row(300, "ok")]), Notifier()
        check(store, n)
        store.rows.append(row(-45, "ok"))  # a run starting 45 minutes from now finishes 47 minutes from now
        rec = check(store, n, minutes_later=60)
        self.assertEqual((rec.health.status, len(n.sent)), ("healthy", 2))
        self.assertIn("recovered", n.sent[1])
        self.assertIsNone(store.state["incident"])
        self.assertEqual(store.state["last_incident"]["kind"], "absent")
        check(store, n, minutes_later=75)
        check(store, n, minutes_later=90)
        self.assertEqual(len(n.sent), 2)  # nothing more once recovered

    def test_a_new_outage_after_recovery_is_a_new_incident_with_its_own_message(self) -> None:
        store, n = FakeStore([row(300, "ok")]), Notifier()
        check(store, n)
        store.rows.append(row(-60, "ok"))
        check(store, n, minutes_later=70)
        check(store, n, minutes_later=70 + 150)  # the new success is now 2.5 hours old
        self.assertEqual([t.startswith("Job Hunter: no successful") for t in n.sent], [True, False, True])  # outage, recovery, outage

    def test_running_neither_opens_nor_closes_an_incident(self) -> None:
        store, n = FakeStore([row(300, "ok"), row(10, "started", finished=False)]), Notifier()
        r = check(store, n)
        self.assertEqual((r.health.status, n.sent, store.state.get("incident")), ("running", [], None))
        store2 = FakeStore([row(300, "ok")]), Notifier()
        check(*store2)  # opens an incident ...
        store2[0].rows.append(row(10, "started", finished=False))  # ... then a run starts: still unresolved, still one incident
        check(*store2, minutes_later=5)
        self.assertEqual(len(store2[1].sent), 1)
        self.assertIsNotNone(store2[0].state["incident"])

    def test_cause_change_keeps_one_incident(self) -> None:
        store, n = FakeStore([row(300, "ok")]), Notifier()
        check(store, n)
        store.rows.append(row(-100, "failed"))
        check(store, n, minutes_later=130)
        self.assertEqual((len(n.sent), store.state["incident"]["kind"]), (1, "failed"))

    def test_failed_outage_send_is_retried_and_not_lost(self) -> None:
        store, n = FakeStore([row(300, "ok")]), Notifier()
        n.fail = True
        r = check(store, n)
        self.assertEqual((r.exit_code, n.sent, store.state["incident"]["notified"]), (wd.EXIT_NOTIFY, [], False))
        n.fail = False
        r2 = check(store, n, minutes_later=15)
        self.assertEqual((r2.exit_code, len(n.sent), store.state["incident"]["notified"]), (0, 1, True))

    def test_failed_recovery_send_keeps_the_incident_open_for_a_retry(self) -> None:
        store, n = FakeStore([row(300, "ok")]), Notifier()
        check(store, n)
        store.rows.append(row(-45, "ok"))
        n.fail = True
        r = check(store, n, minutes_later=60)
        self.assertEqual((r.exit_code, store.state["incident"] is not None, len(n.sent)), (wd.EXIT_NOTIFY, True, 1))
        n.fail = False
        check(store, n, minutes_later=75)
        self.assertEqual((len(n.sent), store.state["incident"]), (2, None))

    def test_recovery_before_the_outage_message_was_ever_delivered_stays_silent(self) -> None:
        store, n = FakeStore([row(300, "ok")]), Notifier()
        n.fail = True
        check(store, n)
        store.rows.append(row(-45, "ok"))
        n.fail = False
        check(store, n, minutes_later=60)
        self.assertEqual((n.sent, store.state["incident"]), ([], None))  # no "recovered from what?" message

    def test_threshold_is_configurable(self) -> None:
        store, n = FakeStore([row(100, "ok")]), Notifier()
        self.assertEqual(wd.step(store, n, NOW, timedelta(hours=1)).health.status, "outage")
        self.assertEqual(wd.step(FakeStore([row(100, "ok")]), Notifier(), NOW, timedelta(hours=4)).health.status, "healthy")


class UnavailableTests(unittest.TestCase):
    def test_unreadable_health_data_is_monitoring_unavailable_and_changes_nothing(self) -> None:
        store, n = FakeStore([row(300, "ok")], state={"incident": {"opened_at": stamp(NOW), "kind": "absent", "notified": True}}), Notifier()
        store.read_error = TimeoutError("sheets read timed out")
        r = check(store, n)
        self.assertEqual((r.health.status, r.exit_code, n.sent, store.saves), ("unavailable", wd.EXIT_UNAVAILABLE, [], 0))
        self.assertIn("not evidence that the hunter stopped", " ".join(r.actions))
        self.assertTrue(store.state["incident"]["notified"])  # an open incident is neither closed nor re-opened by a blind check

    def test_unreadable_state_blocks_notifications(self) -> None:
        store, n = FakeStore([row(300, "ok")]), Notifier()
        store.state_error = RuntimeError("the Watchdog tab holds unreadable state")
        r = check(store, n)
        self.assertEqual((r.health.status, r.exit_code, n.sent, store.saves), ("unavailable", wd.EXIT_UNAVAILABLE, [], 0))  # could duplicate alerts otherwise

    def test_empty_runs_tab_is_unavailable(self) -> None:
        store, n = FakeStore(), Notifier()
        self.assertEqual(check(store, n).exit_code, wd.EXIT_UNAVAILABLE)
        store.rows = []
        r = check(store, n)
        self.assertEqual((r.health.status, n.sent), ("unavailable", []))


class DryRunAndReadOnlyTests(unittest.TestCase):
    def test_dry_run_reports_what_it_would_do_and_writes_and_sends_nothing(self) -> None:
        store, n = FakeStore([row(300, "ok")]), Notifier()
        r = check(store, n, dry_run=True)
        self.assertEqual((r.health.status, n.sent, store.saves, store.state), ("outage", [], 0, {}))
        self.assertIn("would send the outage notification", " ".join(r.actions))

    def test_the_hunters_runs_data_is_never_written(self) -> None:
        store = FakeStore([row(300, "ok")])
        before = [list(r) for r in store.rows]
        for _ in range(3):
            check(store, Notifier())
        self.assertEqual(store.rows, before)  # the fake exposes only read_runs for the hunter's data; state goes through save_state

    def test_sheet_store_writes_only_its_own_tab(self) -> None:
        class WS:
            def __init__(self, title: str) -> None:
                self.title, self.updates, self.hidden = title, [], False

            def update(self, values: list, range_name: str, **kw: Any) -> None:
                self.updates.append((range_name, values))

            def hide(self) -> None:
                self.hidden = True

        class NotFound(Exception):
            pass

        NotFound.__name__ = "WorksheetNotFound"

        class SH:
            def __init__(self) -> None:
                self.tabs: dict[str, WS] = {"Runs": WS("Runs")}

            def worksheet(self, title: str) -> WS:
                if title not in self.tabs:
                    raise NotFound(title)
                return self.tabs[title]

            def add_worksheet(self, title: str, rows: int, cols: int) -> WS:
                self.tabs[title] = WS(title)
                return self.tabs[title]

        store = wd.SheetStore.__new__(wd.SheetStore)
        store.sh = SH()  # type: ignore[assignment]
        self.assertEqual(store.load_state(), {})  # a missing tab is the very first run, and creates nothing
        self.assertEqual(list(store.sh.tabs), ["Runs"])  # type: ignore[attr-defined]
        store.save_state({"incident": None}, NOW)
        self.assertEqual(sorted(store.sh.tabs), ["Runs", "Watchdog"])  # type: ignore[attr-defined]
        self.assertTrue(store.sh.tabs["Watchdog"].hidden)  # type: ignore[attr-defined]
        self.assertEqual(store.sh.tabs["Runs"].updates, [])  # type: ignore[attr-defined]


class IndependenceTests(unittest.TestCase):
    def test_the_watchdog_imports_nothing_from_the_hunters_modules(self) -> None:
        tree = ast.parse((ROOT / "watchdog.py").read_text())
        imported = {n.names[0].name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import)} | {
            (n.module or "").split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
        }
        hunter = {"hunter", "state", "boards", "ledger", "pipeline", "pools", "inventory", "freshness", "eligibility", "discovery", "search", "reporting", "dashboard", "pilot", "meter"}
        self.assertEqual(imported & hunter, set())

    def test_the_workflow_is_separate_from_the_hunters_queue_and_does_not_write_the_repository(self) -> None:
        text = (ROOT / ".github" / "workflows" / "watchdog.yml").read_text()
        self.assertIn("group: watchdog", text)  # NOT job-hunter-state: it must not queue behind a hunter run
        self.assertNotIn("job-hunter-state", text)
        self.assertIn("cron:", text)
        self.assertIn("contents: read", text)
        for forbidden in ("git push", "git commit", "gh workflow run", "gh run rerun", "workflow_dispatch:\n      - "):
            self.assertNotIn(forbidden, text)  # it never restarts anything


class TelegramTests(unittest.TestCase):
    def test_sends_plain_text_to_the_one_configured_chat(self) -> None:
        calls: list[tuple[str, dict]] = []

        class Resp:
            def raise_for_status(self) -> None:
                pass

        def post(url: str, **kw: Any) -> Resp:
            calls.append((url, kw["json"]))
            return Resp()

        wd.telegram_notifier("TOKEN", "123", post)("hello")
        self.assertEqual(calls, [("https://api.telegram.org/botTOKEN/sendMessage", {"chat_id": "123", "text": "hello", "disable_web_page_preview": True})])


class MainTests(unittest.TestCase):
    def test_missing_configuration_names_only_and_exit_4(self) -> None:
        import os
        from unittest import mock

        with mock.patch.dict(os.environ, {"GOOGLE_SHEET_ID": "", "GOOGLE_SERVICE_ACCOUNT_JSON": "", "TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": ""}):
            self.assertEqual(wd.main([]), wd.EXIT_CONFIG)

    def test_invalid_threshold_is_a_configuration_error(self) -> None:
        self.assertEqual(wd.main(["--warn-hours", "0"]), wd.EXIT_CONFIG)


if __name__ == "__main__":
    unittest.main()
