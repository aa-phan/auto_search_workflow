"""Deployment-readiness tests: lease behaviour (what it does and does NOT guarantee), the local-write
restriction, rotation-duration arithmetic and repository hygiene. All offline."""

from __future__ import annotations

import re
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import hunter as h  # noqa: E402
import search  # noqa: E402
import state as st_mod  # noqa: E402
from test_inventory import FakeSh  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
T0 = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)
TTL = timedelta(minutes=30)
NOSLEEP = lambda s: None  # noqa: E731


class SimultaneousAcquisitionTests(unittest.TestCase):
    def test_local_file_lease_is_exclusive_under_real_contention(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            results: list[bool] = []
            barrier = threading.Barrier(12)

            def worker() -> None:
                state = st_mod.CsvState(Path(d))
                barrier.wait()
                results.append(state.acquire_lease("poller", TTL, T0).ok)

            threads = [threading.Thread(target=worker) for _ in range(12)]
            [t.start() for t in threads]
            [t.join() for t in threads]
            self.assertEqual(sum(results), 1)  # flock is arbitrated by the kernel: exactly one wins

    def test_local_file_lease_is_exclusive_across_processes_and_dies_with_its_owner(self) -> None:
        import subprocess

        with tempfile.TemporaryDirectory() as d:
            code = (
                "import sys, time; sys.path.insert(0, %r); from pathlib import Path; from datetime import datetime, timedelta, timezone; "
                "import state; s = state.CsvState(Path(%r)); l = s.acquire_lease('child', timedelta(minutes=5), datetime.now(timezone.utc)); "
                "print('ok' if l.ok else 'busy', flush=True); time.sleep(30)" % (str(ROOT), d)
            )
            child = subprocess.Popen([sys.executable, "-I", "-c", code], stdout=subprocess.PIPE, text=True)
            try:
                self.assertEqual(child.stdout.readline().strip(), "ok")
                mine = st_mod.CsvState(Path(d)).acquire_lease("parent", TTL, T0)
                self.assertFalse(mine.ok)
                self.assertIn("child", mine.held_by)
            finally:
                child.kill()
                child.wait()
            self.assertTrue(st_mod.CsvState(Path(d)).acquire_lease("parent", TTL, T0).ok)  # a crashed owner releases by dying

    def test_sheet_lease_is_NOT_atomic_two_interleaved_writers_can_both_believe_they_hold_it(self) -> None:
        """The documented reason local production writes are disabled. Interleaving: both read an empty
        lease; A writes and verifies; B then writes and verifies. Each passes its own read-back."""
        state = st_mod.SheetState(FakeSh())
        state.ensure()
        ws = state.sh.worksheet(st_mod.LOCK_TAB)
        outcome: dict[str, bool] = {}

        def acquire_b() -> None:
            outcome["B"] = state.acquire_lease("inventory", TTL, T0, settle=1, sleep=NOSLEEP).ok

        def a_settles(_: float) -> None:  # runs between A's write and A's verification: B has already read an empty lease
            pass

        # B reads first (before A writes) - emulate by letting B read, then A run fully, then B write+verify.
        rows_before = ws.get_all_values()
        self.assertEqual(len(rows_before), 1)  # empty lease visible to both
        a = state.acquire_lease("poller", TTL, T0, settle=1, sleep=a_settles)
        self.assertTrue(a.ok)
        # B had read the empty lease earlier; its write now lands and its read-back sees its own token:
        ws.update(values=[["inventory:late", "inventory", "x", "2026-10-14T12:30:00Z"]], range_name="A2")
        self.assertEqual(ws.get_all_values()[1][0], "inventory:late")
        outcome["B"] = True  # B's read-back matches, exactly as in acquire_lease
        self.assertTrue(a.ok and outcome["B"])  # both believe they hold it: no exclusion is established
        self.assertFalse(state.holds_lease(a.token, T0))  # A can only find out afterwards

    def test_a_second_acquirer_after_the_first_has_verified_is_refused(self) -> None:
        state = st_mod.SheetState(FakeSh())
        state.ensure()
        self.assertTrue(state.acquire_lease("poller", TTL, T0, settle=1, sleep=NOSLEEP).ok)
        self.assertFalse(state.acquire_lease("inventory", TTL, T0 + timedelta(minutes=1), settle=1, sleep=NOSLEEP).ok)


class ExpiryDuringALongRunTests(unittest.TestCase):
    def check(self, state) -> None:
        lease = state.acquire_lease("poller", TTL, T0, settle=0, sleep=NOSLEEP)
        self.assertTrue(state.holds_lease(lease.token, T0 + timedelta(minutes=29)))
        late = T0 + TTL + timedelta(seconds=1)
        self.assertFalse(state.holds_lease(lease.token, late))  # the holder can detect that it outlived its lease
        other = state.acquire_lease("inventory", TTL, late, settle=0, sleep=NOSLEEP)
        self.assertTrue(other.ok)  # ... and another writer is allowed in: expiry removes exclusion
        state.release_lease(lease.token)  # the expired owner's release must not free the new holder
        self.assertTrue(state.holds_lease(other.token, late))

    def test_file_lease_has_no_expiry_it_is_held_until_the_owner_releases_or_dies(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            state = st_mod.CsvState(Path(d))
            lease = state.acquire_lease("poller", TTL, T0)
            late = T0 + 5 * TTL
            self.assertTrue(state.holds_lease(lease.token, late))
            self.assertFalse(st_mod.CsvState(Path(d)).acquire_lease("inventory", TTL, late).ok)  # a flock cannot go stale
            state.release_lease("poller:someone-else")
            self.assertTrue(state.holds_lease(lease.token, late))
            state.release_lease(lease.token)
            self.assertTrue(st_mod.CsvState(Path(d)).acquire_lease("inventory", TTL, late).ok)

    def test_sheet_lease(self) -> None:
        state = st_mod.SheetState(FakeSh())
        state.ensure()
        self.check(state)

    def test_lease_ttl_exceeds_every_workflow_timeout_so_expiry_mid_run_cannot_happen_in_practice(self) -> None:
        for name, label in (("job_hunter.yml", "poller"), ("inventory.yml", "inventory")):
            text = (ROOT / ".github" / "workflows" / name).read_text()
            minutes = int(re.search(r"timeout-minutes:\s*(\d+)", text).group(1))
            self.assertGreater(h.LEASE_TTL[label], timedelta(minutes=minutes), name)

    def test_run_that_outlived_its_lease_says_so(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            store = type("S", (), {})()
            store.state = st_mod.CsvState(Path(d))
            store2 = type("S", (), {})()
            store2.state = st_mod.SheetState(FakeSh())
            store2.state.ensure()
            with self.assertLogs("hunter", level="ERROR") as logs:
                with h.writer_lease(store2, "poller", wait_seconds=0):
                    ws = store2.state.sh.worksheet(st_mod.LOCK_TAB)  # the lease row is overwritten / expires mid-run
                    ws.update(values=[["inventory:other", "inventory", "x", "2026-10-14T12:00:00Z"]], range_name="A2")
            self.assertTrue(any("expired or was taken over" in m for m in logs.output))


class OwnerOnlyReleaseTests(unittest.TestCase):
    def test_only_the_token_holder_releases(self) -> None:
        state = st_mod.SheetState(FakeSh())
        state.ensure()
        mine = state.acquire_lease("poller", TTL, T0, settle=0, sleep=NOSLEEP)
        state.release_lease("poller:someone-else")
        self.assertTrue(state.holds_lease(mine.token, T0))
        state.release_lease(mine.token)
        self.assertFalse(state.holds_lease(mine.token, T0))


class LocalWriteRestrictionTests(unittest.TestCase):
    def test_sheet_writes_are_allowed_only_in_the_serialized_workflows(self) -> None:
        r = h.local_write_refusal
        self.assertIsNotNone(r(uses_sheet=True, in_actions=False, allow_local=False))
        self.assertIn("not atomic", r(uses_sheet=True, in_actions=False, allow_local=False))
        self.assertIsNone(r(uses_sheet=True, in_actions=True, allow_local=False))  # GitHub Actions: serialized by its concurrency group
        self.assertIsNone(r(uses_sheet=True, in_actions=False, allow_local=True))  # explicit opt-in for a test Sheet
        self.assertIsNone(r(uses_sheet=False, in_actions=False, allow_local=False))  # local CSV state: unaffected

    def test_main_refuses_a_local_sheet_write_and_still_allows_read_only_commands(self) -> None:
        from unittest import mock

        fake = mock.Mock()
        fake.state = mock.Mock()
        fake.load_settings.return_value = {}
        fake.sheet_timezone.return_value = None
        env = {"GOOGLE_SHEET_ID": "sheet", "GOOGLE_SERVICE_ACCOUNT_JSON": "{}", "GROQ_API_KEY": "k", "GITHUB_ACTIONS": "", "ALLOW_LOCAL_SHEET_WRITES": ""}
        with mock.patch.dict("os.environ", env), mock.patch.object(h, "make_store", return_value=fake), mock.patch.object(h, "load_resume_file", return_value="r" * 300), \
                mock.patch.object(h.pl, "run_cycle") as run_cycle:  # fmt: skip
            self.assertEqual(h.main([]), 4)
            run_cycle.assert_not_called()
            self.assertEqual(h.main(["--import-inventory"]), 4)
            run_cycle.reset_mock()
            run_cycle.return_value = mock.Mock(boards_ok=0, boards_failed=0, boards_total=0, boards_added=0, new_jobs=0, verified_fresh=0, evaluated=0, alerts_sent=0, alerts_failed=0, gap_since_prev_run_min=None, max_board_gap_min=None)
            fake.state.acquire_lease.return_value = mock.Mock(ok=True, token="t")
            fake.state.holds_lease.return_value = True
            with mock.patch.dict("os.environ", {"GITHUB_ACTIONS": "true"}):
                self.assertEqual(h.main([]), 0)  # in Actions it runs
            run_cycle.assert_called_once()


class RotationDurationTests(unittest.TestCase):
    def ledger(self, used: int, calls: int) -> search.SearchBudget:
        b = search.SearchBudget("2026-10")
        b.used, b.calls = used, calls
        return b

    def test_defaults_before_anything_was_measured(self) -> None:
        est = search.rotation_estimate(42, 10, 2, self.ledger(0, 0), None)
        self.assertFalse(est.measured)
        self.assertEqual((est.slots_per_run, round(est.days_per_pass, 1), est.credits_per_month), (10, 2.1, 600))

    def test_pagination_and_real_credit_cost_lengthen_the_pass(self) -> None:
        last = [{"pages": 2}, {"pages": 1}, {"pages": 2}, {"pages": 1}]  # 1.5 requests per slot actually made
        est = search.rotation_estimate(42, 10, 2, self.ledger(30, 20), last)  # 1.5 credits per request measured
        self.assertTrue(est.measured)
        self.assertAlmostEqual(est.credits_per_slot, 2.25)
        self.assertEqual(est.slots_per_run, 4)  # int(10 / 2.25)
        self.assertAlmostEqual(est.days_per_pass, 42 / 8, places=2)
        self.assertGreater(est.credits_per_month, 0)

    def test_queries_with_no_pages_are_ignored(self) -> None:
        est = search.rotation_estimate(42, 10, 2, self.ledger(5, 5), [{"pages": 0}, {"error": "x"}])
        self.assertEqual(est.requests_per_slot, 1.0)


class RepositoryHygieneTests(unittest.TestCase):
    def test_secrets_resume_and_runtime_state_are_ignored(self) -> None:
        ignore = (ROOT / ".gitignore").read_text().splitlines()
        for pattern in (".env", ".env.*", "*service-account*.json", "*credentials*.json", "Resume.pdf", "resume.txt", "state/", ".venv/", "tracked_jobs*.csv", "legacy/*.csv"):
            self.assertIn(pattern, ignore, pattern)

    def test_workflows_cannot_commit_runtime_state_or_write_the_repository(self) -> None:
        for f in (ROOT / ".github" / "workflows").glob("*.yml"):
            text = f.read_text()
            self.assertTrue("contents: read" in text or "permissions: {}" in text, f.name)  # read-only, or no permissions at all (the probe)
            for forbidden in ("git push", "git commit", "git add", "contents: write"):
                self.assertNotIn(forbidden, text, f"{f.name}: {forbidden}")

    def test_the_hourly_workflow_runs_the_pilot_tools_and_records_its_trigger(self) -> None:
        text = (ROOT / ".github" / "workflows" / "job_hunter.yml").read_text()
        for needle in ("pilot_report:", "delivery_test:", "--pilot-report", "--delivery-test --to", "cron: \"17 * * * *\""):
            self.assertIn(needle, text)
        self.assertIn("GITHUB_EVENT_NAME", (ROOT / "hunter.py").read_text())

    def test_telegram_is_required_for_every_run_that_can_deliver_but_not_for_the_read_only_reports(self) -> None:
        text = (ROOT / ".github" / "workflows" / "job_hunter.yml").read_text()
        self.assertIn("(inputs.pilot_report || inputs.rebalance_report || inputs.dashboard || inputs.storage_report || inputs.storage_parity) && 'no' || 'yes'", text)  # schedule and poll: inputs empty -> 'yes'
        self.assertIn('required="$required TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_ID"', text)

    def test_storage_parity_input_is_read_only_and_excluded_from_the_poller(self) -> None:
        """T-03-15: a boolean input, a fixed command, no input text inside `run:`, never a delivering run (static check of the workflow file)."""
        text = (ROOT / ".github" / "workflows" / "job_hunter.yml").read_text()
        inputs_block = text.split("    inputs:\n")[1].split("\n\n")[0]
        names = re.findall(r"^      ([a-z_]+):\n", inputs_block, re.M)
        self.assertIn("storage_parity", names)
        self.assertLessEqual(len(names), 25)  # GitHub allows 25 top-level workflow_dispatch inputs
        declared = re.search(r"^      storage_parity:\n((?:        .*\n)+)", inputs_block + "\n", re.M)
        assert declared is not None
        self.assertIn("type: boolean", declared.group(1))
        self.assertIn("default: false", declared.group(1))
        self.assertIn("read only", declared.group(1))
        step = re.search(r"^      - name: Storage parity \(read only\)\n((?:        .*\n?)+)", text, re.M)
        assert step is not None
        body = step.group(1).strip().splitlines()
        self.assertEqual([ln.strip() for ln in body], ["if: ${{ inputs.storage_parity }}", "run: python hunter.py --storage-parity"])
        poller = next(ln for ln in text.splitlines() if ln.strip().startswith("if:") and "!inputs.delivery_test" in ln)
        self.assertIn("!inputs.storage_parity", poller)  # the poller step never runs beside it
        require = next(ln for ln in text.splitlines() if "REQUIRE_TELEGRAM:" in ln)
        self.assertIn("inputs.storage_report || inputs.storage_parity) && 'no' || 'yes'", require)  # it never delivers, so Telegram is not required
        self.assertEqual(text.count("--storage-parity"), 1)

    def test_smartrecruiters_override_is_explicit_in_both_workflows_slowed_and_announced(self) -> None:
        import inventory as inv

        for name in ("job_hunter.yml", "inventory.yml"):
            self.assertIn('ALLOW_SMARTRECRUITERS_BULK: "1"', (ROOT / ".github" / "workflows" / name).read_text())
        self.assertGreaterEqual(inv.MIN_INTERVAL["smartrecruiters"], 1.0)
        self.assertIsNone(inv.policy_blocks("smartrecruiters", allow_smartrecruiters=True))
        self.assertIsNotNone(inv.policy_blocks("smartrecruiters", allow_smartrecruiters=False))  # the default is still parked
        self.assertIn("ALLOW_SMARTRECRUITERS_BULK", (ROOT / "hunter.py").read_text().split("config_notes.append(\"SmartRecruiters is polled")[0][-200:])

    def test_external_dispatches_are_recorded_separately_from_manual_and_scheduled_runs(self) -> None:
        self.assertEqual(h.run_trigger("workflow_dispatch", "external-hourly"), "workflow_dispatch:external")
        self.assertEqual(h.run_trigger("workflow_dispatch", ""), "workflow_dispatch")
        self.assertEqual(h.run_trigger("workflow_dispatch", None), "workflow_dispatch")
        self.assertEqual(h.run_trigger("schedule", "external-hourly"), "schedule")  # a schedule run can never be relabelled
        self.assertEqual(h.run_trigger(None, None), "local")
        self.assertEqual(h.run_trigger("workflow_dispatch", "  ;rm -rf /  "), "workflow_dispatch:external")  # odd input is reduced to safe characters
        text = (ROOT / ".github" / "workflows" / "job_hunter.yml").read_text()
        self.assertIn("trigger_source:", text)
        self.assertIn("TRIGGER_SOURCE: ${{ inputs.trigger_source }}", text)

    def test_governor_cutoffs_reach_the_program_only_from_manual_inputs_and_blank_means_default(self) -> None:
        from unittest import mock

        text = (ROOT / ".github" / "workflows" / "job_hunter.yml").read_text()
        self.assertIn("POLL_CUTOFF_MINUTES: ${{ inputs.poll_cutoff_minutes }}", text)
        self.assertIn("EVAL_CUTOFF_MINUTES: ${{ inputs.eval_cutoff_minutes }}", text)
        self.assertNotIn("vars.POLL_CUTOFF_MINUTES", text)  # never a standing repository variable that would cut every scheduled run
        self.assertNotIn("vars.EVAL_CUTOFF_MINUTES", text)
        with mock.patch.dict("os.environ", {"POLL_CUTOFF_MINUTES": "", "EVAL_CUTOFF_MINUTES": ""}):  # a scheduled run: inputs are empty
            cfg = h.Config.from_env()
        self.assertEqual((cfg.poll_cutoff_s, cfg.eval_cutoff_s), (15 * 60, 20 * 60))
        with mock.patch.dict("os.environ", {"POLL_CUTOFF_MINUTES": "1", "EVAL_CUTOFF_MINUTES": "0"}):
            cfg = h.Config.from_env()
        self.assertEqual((cfg.poll_cutoff_s, cfg.eval_cutoff_s), (60, 60))  # at least one minute

    def test_workflows_never_print_secrets_and_use_only_the_documented_ones(self) -> None:
        used: set[str] = set()
        for f in (ROOT / ".github" / "workflows").glob("*.yml"):
            text = f.read_text()
            used |= set(re.findall(r"secrets\.([A-Z_]+)", text))
            self.assertNotIn("echo ${{ secrets", text)
            self.assertNotIn("set -x", text)
        self.assertEqual(used, {"TAVILY_API_KEY", "GROQ_API_KEY", "GOOGLE_SERVICE_ACCOUNT_JSON", "GOOGLE_SHEET_ID", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "ALERT_WEBHOOK_URL"})


# --------------------------------------------------------------------------- provider backoff and completeness


class ProviderBackoffTests(unittest.TestCase):
    def get_json_with(self, status: int, headers: dict | None = None):
        from unittest import mock

        import boards as bd

        resp = mock.Mock(status_code=status, headers=headers or {})
        with mock.patch.object(bd.requests, "get", return_value=resp):
            return bd, bd._get_json("https://x")

    def test_429_raises_rate_limited_with_retry_after_default_and_cap(self) -> None:
        import boards as bd

        for headers, expected in (({"Retry-After": "42"}, 42.0), ({}, 300.0), ({"Retry-After": "99999"}, 900.0), ({"Retry-After": "soon"}, 300.0)):
            with self.assertRaises(bd.BoardRateLimited) as c:
                self.get_json_with(429, headers)
            self.assertEqual(c.exception.retry_after, expected)
            self.assertIsInstance(c.exception, bd.BoardError)  # still a transient error, never "closed"

    def test_a_429_leaves_that_provider_alone_for_the_run_and_other_providers_unaffected(self) -> None:
        import boards as bd

        recs = [bd.BoardRecord("workable", f"w{i}", "t", "s", bd.STATUS_ACTIVE) for i in range(3)] + [bd.BoardRecord("lever", "l1", "t", "s", bd.STATUS_ACTIVE)]
        requested: list[str] = []
        now = [0.0]

        def fetch(b: bd.BoardId) -> list:
            requested.append(b.key)
            if b.ats == "workable":
                raise bd.BoardRateLimited(120)
            return []

        res = bd.poll_boards(recs, fetch=fetch, workers=1, clock=lambda: now[0])
        self.assertEqual(requested, ["workable|w0", "lever|l1"])  # only the first Workable board was requested
        self.assertEqual([(r.board.board, r.ok, r.skipped) for r in res], [("w0", False, False), ("w1", False, True), ("w2", False, True), ("l1", True, False)])
        requested.clear()
        now[0] = 121.0  # the backoff has passed (a new run starts with a clean slate anyway)
        res2 = bd.poll_boards(recs[:2], fetch=fetch, workers=1, clock=lambda: now[0])
        self.assertEqual(requested, ["workable|w0"])  # fresh call: its own backoff map

    def test_skipped_boards_are_not_failures_and_keep_their_state(self) -> None:
        from test_core import HarnessCase, ago, job  # noqa: F401
        import boards as bd

        class Case(HarnessCase):
            def runTest(self) -> None:  # pragma: no cover - driven below
                pass

        case = Case()
        case.setUp()
        try:
            wb = [bd.BoardId(bd.WORKABLE, "wa"), bd.BoardId(bd.WORKABLE, "wb")]
            for b in wb:
                case.w.listings[b.key] = [job(b.board, "AAA", ats=bd.WORKABLE, published=ago(days=30))]
            case.w.run(seeds=wb)
            before = {k: (r.consecutive_failures, r.last_attempt_at, r.last_success_at) for k, r in case.w.state.load_boards().items()}
            case.w.listings[wb[0].key] = bd.BoardRateLimited(60)
            run = case.w.run(minutes_later=60)
            after = case.w.state.load_boards()
            self.assertIn("provider backoff after HTTP 429", run.notes)
            self.assertEqual(run.boards_failed, 1)  # only the board that actually got the 429
            skipped = after[wb[1].key]
            self.assertEqual((skipped.consecutive_failures, skipped.last_attempt_at, skipped.last_success_at), before[wb[1].key])  # untouched
            self.assertEqual(after[wb[0].key].consecutive_failures, 1)
        finally:
            case.tearDown() if hasattr(case, "tearDown") else None

    def test_validation_slows_the_provider_instead_of_calling_it_closed(self) -> None:
        import boards as bd
        import inventory as inv

        limiter = inv.HostLimiter(clock=lambda: 100.0, sleep=NOSLEEP)

        def fetch(b: bd.BoardId) -> list:
            raise bd.BoardRateLimited(45)

        res = inv.validate_board(bd.BoardId(bd.WORKABLE, "x"), fetch=fetch, limiter=limiter, retries=2, sleep=NOSLEEP)
        self.assertEqual(res.outcome, bd.V_TRANSIENT)  # never "invalid"
        self.assertGreaterEqual(limiter._next["workable"], 145.0)


class CompletenessByDocumentedBehaviourTests(unittest.TestCase):
    def fetch(self, ats: str, *payloads):
        from unittest import mock

        import boards as bd

        with mock.patch.object(bd, "_get_json", side_effect=list(payloads)) as g:
            out = bd.fetch_board(bd.BoardId(ats, "acme"))
        return out, g

    def lever_items(self, n: int, start: int = 0) -> list[dict]:
        return [{"id": f"123e4567-e89b-12d3-a456-4266141{i + start:05d}", "text": "t", "hostedUrl": "u", "categories": {}} for i in range(n)]

    def test_lever_list_of_a_typical_page_size_is_continued_with_skip_until_a_short_page(self) -> None:
        out, g = self.fetch("lever", self.lever_items(100), self.lever_items(30, 100))
        self.assertEqual((len(out), getattr(out, "complete", True)), (130, True))
        self.assertEqual(g.call_args_list[1].args[1], {"mode": "json", "skip": 100, "limit": 100})

    def test_lever_list_of_another_length_costs_exactly_one_request(self) -> None:
        out, g = self.fetch("lever", self.lever_items(37))
        self.assertEqual((len(out), g.call_count), (37, 1))

    def test_ashby_is_documented_as_unpaginated_so_a_long_list_is_complete(self) -> None:
        jobs = [{"id": f"123e4567-e89b-12d3-a456-4266141{i:05d}", "title": "t", "jobUrl": "u"} for i in range(100)]
        out, g = self.fetch("ashby", {"jobs": jobs})
        self.assertEqual((len(out), getattr(out, "complete", True), g.call_count), (100, True, 1))

    def test_greenhouse_is_documented_as_unpaginated_a_missing_total_is_not_required(self) -> None:
        jobs = [{"id": i, "title": "t", "absolute_url": "u"} for i in range(100)]
        out, _ = self.fetch("greenhouse", {"jobs": jobs})
        self.assertTrue(getattr(out, "complete", True))
        short, _ = self.fetch("greenhouse", {"jobs": jobs[:3], "meta": {"total": 9}})
        self.assertFalse(getattr(short, "complete", True))  # a reported total is still used as a consistency check when present

    def test_workable_widget_has_no_documented_pagination_so_a_round_length_is_reported_as_possibly_truncated(self) -> None:
        jobs = [{"shortcode": f"A{i:04d}", "title": "t", "url": "u"} for i in range(50)]
        out, _ = self.fetch("workable", {"jobs": jobs})
        self.assertFalse(getattr(out, "complete", True))
        out2, _ = self.fetch("workable", {"jobs": jobs[:49]})
        self.assertTrue(getattr(out2, "complete", True))


class SheetsQuotaTests(unittest.TestCase):
    def api_error(self, code: int):
        from unittest import mock

        import gspread

        resp = mock.Mock(status_code=code, text="x")
        resp.json.return_value = {"error": {"code": code, "message": "Quota exceeded", "status": "RESOURCE_EXHAUSTED"}}
        return gspread.exceptions.APIError(resp)

    def test_429_is_retried_after_the_quota_window_and_then_succeeds(self) -> None:
        from unittest import mock

        calls = mock.Mock(side_effect=[self.api_error(429), self.api_error(429), "ok"])
        slept: list[float] = []
        self.assertEqual(h.quota_retrying(calls, sleep=slept.append)("GET", "x"), "ok")
        self.assertEqual((slept, calls.call_count), ([20.0, 40.0], 3))

    def test_it_gives_up_after_the_last_wait_and_never_retries_other_errors(self) -> None:
        from unittest import mock

        import gspread

        always = mock.Mock(side_effect=lambda *a, **k: (_ for _ in ()).throw(self.api_error(429)))
        with self.assertRaises(gspread.exceptions.APIError):
            h.quota_retrying(always, sleep=NOSLEEP)("GET", "x")
        self.assertEqual(always.call_count, 4)  # the first try plus three retries
        for code in (400, 403, 500, 503):  # 5xx may have been applied: a retry could duplicate an append
            once = mock.Mock(side_effect=self.api_error(code))
            with self.assertRaises(gspread.exceptions.APIError):
                h.quota_retrying(once, sleep=NOSLEEP)("POST", "x")
            self.assertEqual(once.call_count, 1, code)

    def test_arguments_and_results_pass_through_untouched(self) -> None:
        from unittest import mock

        inner = mock.Mock(return_value=42)
        self.assertEqual(h.quota_retrying(inner, sleep=NOSLEEP)("GET", "/u", params={"a": 1}), 42)
        inner.assert_called_once_with("GET", "/u", params={"a": 1})


if __name__ == "__main__":
    unittest.main()
