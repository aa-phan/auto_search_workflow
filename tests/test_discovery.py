"""Offline tests for rotating discovery: rotation persistence, pagination bounds, independent
board/job processing, shared admission, the 12-hour window, baselining and retry preservation.

Everything is mocked (fake search pages, fake ATS listings, fake scorer/alert channel); persistence
is the real CSV-backed state in a temp dir. Nothing here touched Serper, an ATS, Sheets or Telegram.
"""

from __future__ import annotations

import collections
import os
import sys
import unittest
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import boards as bd  # noqa: E402
import discovery as dsc  # noqa: E402
import freshness as fr  # noqa: E402
import hunter as h  # noqa: E402
import inventory as inv  # noqa: E402
import ledger as lg  # noqa: E402
import pipeline as pl  # noqa: E402
import state as st_mod  # noqa: E402
from test_core import T0, HarnessCase, ago, done, job  # noqa: E402

UUID = "123e4567-e89b-12d3-a456-4266141740{:02d}"


def hit(url: str, title: str = "Marketing Intern") -> SimpleNamespace:
    return SimpleNamespace(url=url, title=title)


def gh(board: str, jid: str) -> str:
    return f"https://boards.greenhouse.io/{board}/jobs/{jid}"


def padded(urls: list[Any], title: str = "Marketing Intern", n: int = 10) -> list[SimpleNamespace]:
    """A full results page: the given URLs (or (url, title) pairs) plus non-ATS filler (a short page would end paging)."""
    hits = [hit(*u) if isinstance(u, tuple) else hit(u, title) for u in urls]
    return hits + [hit(f"https://example.com/filler/{i}") for i in range(n - len(hits))]


def engine(pages: dict[str, list[list[Any]]], *, known_boards: set[str] | None = None, seen_jobs: set[str] | None = None, **kw: Any) -> dsc.DiscoveryResult:
    """run_queries with scripted pages: pages[query id][page-1]."""
    calls: list[tuple[str, int]] = []

    def search(q: dsc.Query, page: int) -> list[Any]:
        calls.append((q.id, page))
        script = pages[q.id]
        if page > len(script):
            return padded([])
        out = script[page - 1]
        if isinstance(out, Exception):
            raise out
        return out

    queries = [dsc.Query(qid, f"query {qid}", "qdr:d3") for qid in pages]
    res = dsc.run_queries(
        queries, search, is_new_board=lambda b: b.key not in (known_boards or set()),
        is_unseen_job=lambda i: i.key not in (seen_jobs or set()), **{"budget": 10, **kw},
    )  # fmt: skip
    res.calls = calls  # type: ignore[attr-defined]
    return res


# --------------------------------------------------------------------------- rotation


class RotationTests(unittest.TestCase):
    slots = dsc.make_slots(["a.com", "b.com", "c.com"], ["Marketing", "Design"], ["Austin", "Remote"])

    def test_every_combination_once_sites_varying_fastest(self) -> None:
        self.assertEqual(len(self.slots), 3 * 2 * 2)
        self.assertEqual(len({s.id for s in self.slots}), 12)
        self.assertEqual([s.site for s in self.slots[:3]], ["a.com", "b.com", "c.com"])
        self.assertEqual({(s.role, s.location) for s in self.slots[:3]}, {("Marketing", "Austin")})

    def test_plan_and_advance_wrap_and_count_cycles(self) -> None:
        state = dsc.RotationState()
        seen: list[str] = []
        for _ in range(5):  # 5 runs x 5 slots = 25 searches over 12 slots
            chosen = dsc.plan_slots(state, self.slots, 5)
            seen += [s.id for s in chosen]
            state = dsc.advance(state, self.slots, len(chosen), T0)
        self.assertEqual(seen[:12], [s.id for s in self.slots])  # a full cycle before any repeat
        self.assertEqual(seen[12:24], [s.id for s in self.slots])
        self.assertEqual((state.cursor, state.cycles, state.runs), (1, 2, 5))

    def test_a_run_never_plans_the_same_slot_twice(self) -> None:
        chosen = dsc.plan_slots(dsc.RotationState(cursor=10), self.slots, 50)
        self.assertEqual(len(chosen), 12)
        self.assertEqual(len({s.id for s in chosen}), 12)
        self.assertEqual(chosen[0], self.slots[10])  # starts at the cursor, wraps around

    def test_state_round_trips_and_garbage_resets(self) -> None:
        st = dsc.advance(dsc.RotationState(), self.slots, 7, T0)
        self.assertEqual(dsc.RotationState.from_json(st.to_json()), st)
        self.assertEqual(dsc.RotationState.from_json("not json"), dsc.RotationState())
        self.assertEqual(dsc.RotationState.from_json(None), dsc.RotationState())

    def test_settings_change_keeps_the_position_instead_of_restarting(self) -> None:
        st = dsc.advance(dsc.RotationState(), self.slots, 7, T0)
        fewer = dsc.make_slots(["a.com", "b.com"], ["Marketing"], ["Austin", "Remote"])  # 4 slots now
        self.assertEqual(dsc.plan_slots(st, fewer, 1)[0], fewer[7 % 4])
        st2 = dsc.advance(st, fewer, 1, T0)
        self.assertEqual((st2.cursor, st2.total, st2.fingerprint), (0, 4, dsc.fingerprint(fewer)))


class PersistentRotationTests(HarnessCase):
    """The cursor survives between runs because it lives in the state store, not in memory."""

    slots = dsc.make_slots(["jobs.lever.co", "boards.greenhouse.io"], ["Marketing", "Design"], ["Austin", "Remote"])  # 8 slots

    def discover(self, searched: list[str], per_run: int = 3):
        def run(ctx: pl.DiscoveryContext) -> dsc.DiscoveryResult:
            chosen = dsc.plan_slots(ctx.rotation, self.slots, per_run)
            queries = [dsc.Query(s.id, s.id, "qdr:d3") for s in chosen]

            def search(q: dsc.Query, page: int) -> list[Any]:
                searched.append(q.id)
                return []  # short page: one credit per query

            return dsc.run_queries(queries, search, budget=per_run, is_new_board=ctx.is_new_board, is_unseen_job=ctx.is_unseen_job)

        return run

    def test_cursor_persists_across_runs_and_restarts(self) -> None:
        searched: list[str] = []
        kw: dict[str, Any] = dict(discover=self.discover(searched), rotation_slots=self.slots, force_discovery=True)
        self.w.run(**kw)
        self.w.run(minutes_later=720, **kw)
        stored = dsc.RotationState.from_json(self.w.state.load_discovery_state()[dsc.ROTATION_KEY])
        self.assertEqual((stored.cursor, stored.runs, stored.cycles), (6, 2, 0))
        # a brand-new process (new state object over the same files) continues where the last one stopped
        fresh_state = st_mod.CsvState(self.w.state.dir)
        self.assertEqual(dsc.RotationState.from_json(fresh_state.load_discovery_state()[dsc.ROTATION_KEY]).cursor, 6)
        self.w.run(minutes_later=720, **kw)
        self.assertEqual(searched, [s.id for s in self.slots] + [s.id for s in self.slots[:1]])  # 3+3+3 = 9 searches: one full cycle, then restart
        self.assertEqual(dsc.RotationState.from_json(self.w.state.load_discovery_state()[dsc.ROTATION_KEY]).cycles, 1)

    def test_every_slot_is_searched_once_per_cycle_without_gaps(self) -> None:
        searched: list[str] = []
        for i in range(4):  # 4 runs x 2 slots = exactly one pass over 8 slots
            self.w.run(minutes_later=720 * (i > 0), discover=self.discover(searched, 2), rotation_slots=self.slots, force_discovery=True)
        self.assertEqual(sorted(searched), sorted(s.id for s in self.slots))

    def test_a_run_where_every_request_failed_does_not_advance(self) -> None:
        def broken(ctx: pl.DiscoveryContext) -> dsc.DiscoveryResult:
            chosen = dsc.plan_slots(ctx.rotation, self.slots, 2)

            def search(q: dsc.Query, page: int) -> list[Any]:
                raise ConnectionError("serper down")

            return dsc.run_queries([dsc.Query(s.id, s.id, "qdr:d3") for s in chosen], search, budget=4, is_new_board=ctx.is_new_board, is_unseen_job=ctx.is_unseen_job)

        run = self.w.run(discover=broken, rotation_slots=self.slots, force_discovery=True)
        self.assertIn("every search request failed", run.notes)
        self.assertNotIn(dsc.ROTATION_KEY, self.w.state.load_discovery_state())  # same slots are retried next time

    def test_discovery_is_scheduled_every_twelve_hours_not_every_poll(self) -> None:
        calls: list[int] = []

        def discover(ctx: pl.DiscoveryContext) -> dsc.DiscoveryResult:
            calls.append(1)
            return dsc.DiscoveryResult(slots_used=1)

        for minutes in (0, 60, 60, 60, 60 * 8, 60 * 4):  # 0h, 1h, 2h, 3h, 11h, 15h
            self.w.run(minutes_later=minutes, discover=discover, rotation_slots=self.slots, discovery_every_hours=12)
        self.assertEqual(len(calls), 2)  # the first run, then the first poll at/after the 12 h mark (minus 5 min tolerance)


# --------------------------------------------------------------------------- pagination and budget


class EngineTests(unittest.TestCase):
    def test_paging_stops_after_two_consecutive_pages_with_nothing_new(self) -> None:
        r = engine({"q": [padded([gh("newco", "1")]), padded([gh("newco", "1")]), padded([gh("newco", "1")]), padded([gh("other", "2")])]}, max_pages=5)
        self.assertEqual((r.pages, r.credits, r.queries[0].stop), (3, 3, "stalled"))  # page 4 (which would have found 'other') is never fetched
        self.assertEqual([b.board for b in r.boards], ["newco"])

    def test_a_page_with_only_a_new_board_or_only_an_unseen_job_counts_as_contributing(self) -> None:
        # page 1: board known, job unseen. page 2: nothing. page 3: job seen but board new. page 4+: nothing.
        r = engine(
            {"q": [padded([gh("known", "1")]), padded([gh("known", "1")]), padded([gh("brandnew", "9")]), padded([]), padded([])]},
            known_boards={"greenhouse|known"}, seen_jobs={"greenhouse|brandnew|9"}, max_pages=9,
        )  # fmt: skip
        q = r.queries[0]
        self.assertEqual((q.unseen_jobs, q.new_boards, q.repeated), (1, 1, 1))
        self.assertEqual((q.pages, q.stop), (5, "stalled"))  # the stall counter restarted at page 3

    def test_fixed_budget_is_a_hard_cap_across_queries(self) -> None:
        def fresh_pages(prefix: str) -> list[list[Any]]:
            return [padded([gh(f"{prefix}{p}", "1")]) for p in range(10)]

        r = engine({"q1": fresh_pages("a"), "q2": fresh_pages("b"), "q3": fresh_pages("c")}, budget=5, max_pages=3)
        self.assertEqual((r.credits, r.pages, r.slots_used, r.stopped), (5, 5, 2, "budget"))
        self.assertEqual([q.id for q in r.queries], ["q1", "q2"])  # q3 never started, so the rotation does not skip it
        self.assertEqual(r.queries[1].stop, "budget")

    def test_never_searches_indefinitely_for_something_new(self) -> None:
        r = engine({"q": [padded([gh("a", "1")])] * 50}, max_pages=3, budget=100)
        self.assertLessEqual(r.pages, 3)
        r2 = engine({"q": [padded([]) for _ in range(50)]}, max_pages=50, budget=100)
        self.assertEqual((r2.pages, r2.queries[0].stop), (2, "stalled"))

    def test_short_page_is_the_last_page(self) -> None:
        r = engine({"q": [[hit(gh("a", "1"))]]})
        self.assertEqual((r.pages, r.queries[0].stop), (1, "last_page"))

    def test_one_failing_request_does_not_discard_earlier_results_or_other_queries(self) -> None:
        r = engine({"q1": [padded([gh("a", "1")]), ConnectionError("boom")], "q2": [padded([gh("b", "2")])]})
        self.assertEqual({b.board for b in r.boards}, {"a", "b"})
        self.assertEqual((r.queries[0].stop, r.all_failed), ("error", False))
        self.assertIn("ConnectionError", r.queries[0].error)

    def test_repeated_results_are_counted_once_per_identity_across_queries(self) -> None:
        r = engine({"q1": [padded([gh("a", "1"), gh("a", "2")])], "q2": [padded([gh("a", "1"), "https://jobs.lever.co/solo"])]}, max_pages=1)
        self.assertEqual((r.queries[0].repeated, r.queries[1].repeated, r.repeated), (0, 1, 1))
        self.assertEqual({b.key for b in r.boards}, {"greenhouse|a", "lever|solo"})
        self.assertEqual(r.job_keys, {"greenhouse|a|1", "greenhouse|a|2"})
        self.assertEqual(sum(q.unparsed for q in r.queries), 16)

    def test_backfill_mode_takes_boards_but_no_jobs(self) -> None:
        r = engine({"q": [padded([gh("a", "1")])]}, take_jobs=False, kind=dsc.KIND_BACKFILL)
        self.assertEqual(([b.board for b in r.boards], r.jobs), (["a"], []))


# --------------------------------------------------------------------------- independent processing


class IndependentProcessingTests(HarnessCase):
    def setUp(self) -> None:
        super().setUp()
        self.fetched: collections.Counter[str] = collections.Counter()
        real = self.w.fetch

        def counting(board: bd.BoardId) -> list[bd.ListedJob]:
            self.fetched[board.key] += 1
            return real(board)

        self.w.fetch = counting  # type: ignore[method-assign]

    def search(self, *urls_titles: tuple[str, str]):
        def discover(ctx: pl.DiscoveryContext) -> dsc.DiscoveryResult:
            return dsc.run_queries(
                [dsc.Query("q", "q", "qdr:d3")], lambda q, p: padded(list(urls_titles)) if p == 1 else [],
                budget=10, is_new_board=ctx.is_new_board, is_unseen_job=ctx.is_unseen_job,
            )  # fmt: skip

        return discover

    def test_board_is_submitted_even_when_the_job_is_seen_stale_or_excluded(self) -> None:
        self.baseline(job("acme", "1", published=ago(days=30)))  # job acme/1 is now seen
        seen_url = gh("acme", "1")
        stale_url, excluded_url, fresh_url = gh("staleco", "5"), gh("exclco", "6"), gh("freshco", "7")
        for b in ("staleco", "exclco", "freshco"):
            self.w.listings[bd.BoardId(bd.GREENHOUSE, b).key] = [job(b, "100", published=ago(days=40, base=T0 + timedelta(minutes=60)))]
        titles = {seen_url: "Marketing Intern", stale_url: "Marketing Intern", excluded_url: "Senior Marketing Manager", fresh_url: "Marketing Intern"}
        hydrated: list[str] = []

        def hydrate(sj: dsc.SerperJob) -> bd.ListedJob | None:
            hydrated.append(sj.ident.key)
            age = {"5": ago(days=40, base=T0 + timedelta(minutes=60)), "7": ago(minutes=30, base=T0 + timedelta(minutes=60))}[sj.ident.job_id]
            return job(sj.ident.board, sj.ident.job_id, published=age)

        self.w.listings[self.board.key].append(job("acme", "1", published=ago(days=30)))
        run = self.w.run(
            minutes_later=60, discover=self.search(*[(u, titles[u]) for u in titles]), hydrate_listed=hydrate, force_discovery=True,
        )  # fmt: skip
        registry = self.w.state.load_boards()
        for b in ("staleco", "exclco", "freshco"):
            rec = registry[f"greenhouse|{b}"]
            self.assertIn("serper", rec.provenance, b)  # every result's board reached admission
            self.assertIn(rec.status, {"new", "active"}, b)
        self.assertEqual(len(registry), 4)
        self.assertEqual(sorted(hydrated), ["greenhouse|freshco|7", "greenhouse|staleco|5"])  # seen job skipped, excluded title not fetched
        self.assertEqual(self.w.states()[bd.JobIdentity(bd.GREENHOUSE, "freshco", "7").key].freshness, fr.VERIFIED_FRESH)
        self.assertEqual(self.w.states()[bd.JobIdentity(bd.GREENHOUSE, "staleco", "5").key].freshness, fr.STALE)
        self.assertEqual((run.new_unique_boards, run.search_credits, run.search_pages), (3, 2, 2))

    def test_unseen_job_goes_through_the_normal_pipeline_without_its_board_being_polled(self) -> None:
        board = bd.BoardId(bd.GREENHOUSE, "smallco")
        self.w.listings[board.key] = []  # empty listing: nothing relevant, so the board is NOT promoted
        url = gh("smallco", "42")
        listed = job("smallco", "42", published=ago(minutes=20))
        run = self.w.run(discover=self.search((url, "Marketing Intern")), hydrate_listed=lambda sj: listed, force_discovery=True)
        self.assertEqual(self.w.state.load_boards()[board.key].status, "validated")  # admitted + validated, waiting for a slot
        self.assertEqual(self.w.states()[listed.ident.key].freshness, fr.VERIFIED_FRESH)  # the job path did not need the board path
        self.assertEqual((len(self.w.alerts), run.verified_fresh_matches, run.eligible_boards, run.promoted_boards), (1, 1, 1, 0))
        self.assertEqual(self.w.states()[listed.ident.key].seen_detail["source"], "serper")

    def test_excluded_title_is_not_hydrated_but_its_board_is_still_admitted(self) -> None:
        board = bd.BoardId(bd.GREENHOUSE, "exclco")
        self.w.listings[board.key] = [job("exclco", "1", published=ago(days=30))]
        called: list[Any] = []
        run = self.w.run(
            discover=self.search((gh("exclco", "9"), "Senior Software Engineer")), hydrate_listed=lambda sj: called.append(sj), force_discovery=True
        )  # fmt: skip
        self.assertEqual((called, run.new_unique_boards), ([], 1))
        self.assertIn("greenhouse|exclco", self.w.state.load_boards())

    def test_job_listed_by_the_board_poll_in_the_same_run_is_observed_once(self) -> None:
        board = bd.BoardId(bd.GREENHOUSE, "samerun")
        listed = job("samerun", "7", published=ago(minutes=15))
        self.w.listings[board.key] = [listed]
        self.w.run(discover=self.search((gh("samerun", "7"), "Marketing Intern")), hydrate_listed=lambda sj: listed, force_discovery=True)
        self.assertEqual(len(self.w.events(listed.ident.key, lg.SEEN)), 1)
        self.assertEqual(self.w.states()[listed.ident.key].seen_detail["source"], "poll")  # poll got there first; no double count


# --------------------------------------------------------------------------- shared admission


class AdmissionTests(HarnessCase):
    def lever(self, name: str, n_relevant: int = 1) -> bd.BoardId:
        b = bd.BoardId(bd.LEVER, name)
        self.w.listings[b.key] = [job(name, UUID.format(i), ats=bd.LEVER, published=ago(days=30)) for i in range(n_relevant)]
        return b

    def found(self, *boards: bd.BoardId):
        return lambda ctx: dsc.DiscoveryResult(boards=list(boards))

    def test_serper_cannot_bypass_the_smartrecruiters_parked_policy(self) -> None:
        sr = bd.BoardId(bd.SMARTRECRUITERS, "SrCo")
        fetched: list[str] = []
        self.w.listings[sr.key] = []
        real = self.w.fetch
        self.w.fetch = lambda b: (fetched.append(b.key), real(b))[1]  # type: ignore[method-assign]
        run = self.w.run(discover=self.found(sr), force_discovery=True)
        rec = self.w.state.load_boards()[sr.key]
        self.assertEqual((rec.status, rec.validation), ("deferred", "deferred"))
        self.assertEqual((fetched, run.boards_total, run.boards_added), ([], 0, 1))  # never listed, never polled
        self.assertIn("serper", rec.provenance)  # but the discovery is recorded
        self.assertIn("1 boards parked", run.notes)

    def test_manual_seeds_follow_the_same_smartrecruiters_policy(self) -> None:
        sr = bd.BoardId(bd.SMARTRECRUITERS, "SrSeed")
        self.w.listings[sr.key] = [job("SrSeed", "743999000", ats=bd.SMARTRECRUITERS, published=ago(days=30))]
        self.w.run(seeds=[sr])
        self.assertEqual(self.w.state.load_boards()[sr.key].status, "deferred")

    def test_the_provider_flag_opens_the_same_gate_for_every_source(self) -> None:
        sr = bd.BoardId(bd.SMARTRECRUITERS, "SrOpen")
        self.w.listings[sr.key] = [job("SrOpen", "743999001", ats=bd.SMARTRECRUITERS, published=ago(days=30))]
        self.w.run(discover=self.found(sr), force_discovery=True, allow_smartrecruiters=True)
        self.assertEqual(self.w.state.load_boards()[sr.key].status, "active")

    def test_search_found_smartrecruiters_job_is_not_read_while_the_provider_is_parked(self) -> None:
        sj = dsc.SerperJob(bd.JobIdentity(bd.SMARTRECRUITERS, "SrCo", "743999002"), "Marketing Intern", "https://jobs.smartrecruiters.com/SrCo/743999002")
        called: list[Any] = []
        run = self.w.run(discover=lambda ctx: dsc.DiscoveryResult(jobs=[sj]), hydrate_listed=lambda s: called.append(s), force_discovery=True)
        self.assertEqual(called, [])
        self.assertIn("SmartRecruiters jobs not read", run.notes)

    def test_one_activation_budget_governs_every_source(self) -> None:
        seed, via_search = self.lever("seedco", 2), self.lever("searchco", 5)
        self.w.run(seeds=[seed], discover=self.found(via_search, self.lever("third", 1)), force_discovery=True, max_monitored_boards=2, max_new_boards_per_run=1)
        status = {k.split("|")[1]: r.status for k, r in self.w.state.load_boards().items()}
        # per-run cap of 1: the board with the most matching jobs (search-found, 5) is promoted first, whichever source it came from
        self.assertEqual(status, {"seedco": "validated", "searchco": "active", "third": "validated"})
        self.w.run(minutes_later=60, max_monitored_boards=2, max_new_boards_per_run=1)
        self.w.run(minutes_later=60, max_monitored_boards=2, max_new_boards_per_run=1)
        status = {k.split("|")[1]: r.status for k, r in self.w.state.load_boards().items()}
        self.assertEqual(sorted(status.values()), ["active", "active", "validated"])  # the ceiling of 2 holds across runs and sources
        self.assertEqual(status["third"], "validated")

    def test_active_board_limit_counts_boards_that_were_already_monitored(self) -> None:
        for i in range(3):
            self.lever(f"mon{i}")
        self.w.run(seeds=[bd.BoardId(bd.LEVER, f"mon{i}") for i in range(3)], max_monitored_boards=3, max_new_boards_per_run=10)
        late = self.lever("latecomer", 9)
        run = self.w.run(minutes_later=60, discover=self.found(late), force_discovery=True, max_monitored_boards=3, max_new_boards_per_run=10)
        self.assertEqual((self.w.state.load_boards()[late.key].status, run.boards_activated, run.promoted_boards, run.eligible_boards), ("validated", 0, 0, 1))

    def test_same_board_from_three_sources_is_one_row_polled_once_with_all_provenance(self) -> None:
        b = self.lever("tripleco")
        polls: list[str] = []
        real = self.w.fetch
        self.w.fetch = lambda x: (polls.append(x.key), real(x))[1]  # type: ignore[method-assign]
        rows = {b.key: bd.BoardRecord(b.ats, b.board, "2026-10-01T00:00:00Z", "ats-scrapers", bd.STATUS_CANDIDATE, provenance={"ats-scrapers": {"first": "2026-10-01T00:00:00Z"}})}
        self.w.state.save_boards(rows.values())
        run = self.w.run(seeds=[b], discover=self.found(b, b), force_discovery=True)
        boards = self.w.state.load_boards()
        self.assertEqual(len(boards), 1)
        rec = boards[b.key]
        self.assertEqual(set(rec.provenance), {"ats-scrapers", "seed", "serper"})
        self.assertEqual((rec.source, rec.discovered_at), ("ats-scrapers", "2026-10-01T00:00:00Z"))  # first discoverer and time survive
        self.assertEqual(run.boards_total, 1)
        self.assertEqual(polls.count(b.key), 2)  # one validation (admission) + one poll; the later sources hit the cached validation

    def test_known_board_keeps_its_status_when_search_finds_it_again(self) -> None:
        b = self.lever("knownco")
        self.w.run(seeds=[b])
        before = self.w.state.load_boards()[b.key]
        self.w.run(minutes_later=60, discover=self.found(b), force_discovery=True)
        after = self.w.state.load_boards()[b.key]
        self.assertEqual((after.status, after.baselined_at, after.discovered_at), (before.status, before.baselined_at, before.discovered_at))

    def test_unsupported_or_malformed_identifiers_are_rejected_not_registered(self) -> None:
        reg: dict[str, bd.BoardRecord] = {}
        res = inv.admit_boards(reg, [bd.BoardId(bd.LEVER, "has space"), bd.BoardId("workday", "x"), bd.BoardId(bd.LEVER, "ok-co")], source="serper", now=T0, fetch=lambda b: [])
        self.assertEqual((res.rejected, res.submitted, list(reg)), (2, 1, ["lever|ok-co"]))

    def test_transient_validation_leaves_a_retryable_candidate_not_a_verdict(self) -> None:
        b = bd.BoardId(bd.LEVER, "flaky")
        self.w.listings[b.key] = bd.BoardError("HTTP 503")
        self.w.run(discover=self.found(b), force_discovery=True, sleep=lambda s: None)
        rec = self.w.state.load_boards()[b.key]
        self.assertEqual((rec.status, rec.validation, rec.consecutive_failures), ("candidate", "", 1))

    def test_inline_validation_is_bounded_and_the_rest_stay_candidates(self) -> None:
        many = [self.lever(f"c{i}") for i in range(5)]
        self.w.run(discover=self.found(*many), force_discovery=True, max_inline_validations=2)
        statuses = collections.Counter(r.status for r in self.w.state.load_boards().values())
        self.assertEqual(statuses["candidate"], 3)


# --------------------------------------------------------------------------- the 12-hour window


class TwelveHourTests(HarnessCase):
    def test_default_window_is_twelve_hours_and_independent_of_the_discovery_interval(self) -> None:
        self.assertEqual(fr.DEFAULT_FRESH_WINDOW_HOURS, 12)
        self.assertEqual(pl.Deps.__dataclass_fields__["fresh_window"].default, timedelta(hours=12))
        s = h.Settings.from_values({"Resume_Text": "r" * 300})
        self.assertEqual((s.fresh_window_hours, s.discovery_every_hours, s.discovery_credit_budget), (12, 12, 10))
        s = h.Settings.from_values({"Resume_Text": "r" * 300, "Fresh_Window_Hours": "6", "Discovery_Every_Hours": "24"})
        self.assertEqual((s.fresh_window_hours, s.discovery_every_hours), (6, 24))  # changing one never changes the other
        s = h.Settings.from_values({"Resume_Text": "r" * 300, "Discovery_Every_Hours": "6"})
        self.assertEqual((s.fresh_window_hours, s.discovery_every_hours), (12, 6))

    def test_explicit_four_hours_is_kept_and_flagged_for_migration(self) -> None:
        raw = {"Resume_Text": "r" * 300, "Fresh_Window_Hours": "4"}
        self.assertEqual(h.Settings.from_values(raw).fresh_window_hours, 4)  # never silently rewritten
        notes = h.settings_notes(raw)
        self.assertEqual(len(notes), 1)
        self.assertIn("old default", notes[0])
        with mock.patch.dict(os.environ, {"FRESH_WINDOW_HOURS": "4"}):
            self.assertEqual(len(h.settings_notes({})), 1)  # an environment override is flagged too
        for ok in ("12", "6", "24", ""):
            self.assertEqual(h.settings_notes({"Fresh_Window_Hours": ok}), [], ok)

    def test_the_flag_reaches_the_run_record(self) -> None:
        run = self.w.run(config_notes=["Fresh_Window_Hours is 4 (the old default)"])
        self.assertIn("Fresh_Window_Hours is 4", run.notes)

    def test_new_settings_default_in_the_sheet_template(self) -> None:
        d = {k: v for k, v, _ in h.DEFAULT_SETTINGS}
        self.assertEqual((d["Fresh_Window_Hours"], d["Discovery_Every_Hours"], d["Discovery_Credit_Budget"]), ("12", "12", "10"))

    def poll_one(self, published: str, **kw: Any) -> lg.JobState:
        self.baseline(job("acme", "1", published=ago(days=30)))
        self.w.listings[self.board.key].append(job("acme", "new", published=published))
        self.w.run(minutes_later=60, **kw)
        return self.w.states()[self.key("new")]

    def test_polled_job_at_the_edges_of_the_window(self) -> None:
        later = T0 + timedelta(minutes=60)  # 13:00 -> 12 h earlier is 01:00 (a real time of day, so time precision)
        inside = self.poll_one("2026-10-14T01:00:00Z")
        self.assertEqual((inside.freshness, len(self.w.alerts)), (fr.VERIFIED_FRESH, 1))  # exactly 12 h
        self.assertEqual(ago(minutes=719, base=later), "2026-10-14T01:01:00Z")

    def test_polled_job_just_outside_the_window_is_recent_and_not_alerted(self) -> None:
        outside = self.poll_one("2026-10-14T00:59:00Z")  # 12 h 1 min
        self.assertEqual((outside.freshness, self.w.alerts, len(self.w.tracker)), (fr.RECENT, [], 1))  # tracker only
        self.assertEqual(self.w.calls[self.key("new")], 1)

    def test_a_four_hour_override_is_honoured_everywhere(self) -> None:
        job_age_6h = "2026-10-14T07:00:00Z"
        st = self.poll_one(job_age_6h, fresh_window=timedelta(hours=4))
        self.assertEqual((st.freshness, self.w.alerts), (fr.RECENT, []))

    def test_late_alert_label_uses_the_configured_window(self) -> None:
        st = lg.JobState("k", last_published="2026-10-14T00:00:00Z")
        now = T0 + timedelta(hours=1)
        self.assertEqual(lg.alert_delay_note(st, now, timedelta(hours=13)), "")
        self.assertIn("delivered late", lg.alert_delay_note(st, now, timedelta(hours=12)))
        self.assertEqual(lg.alert_delay_note(lg.JobState("k"), now, timedelta(hours=1)), "")  # no date, no claim


# --------------------------------------------------------------------------- baselining


class BaselineWindowTests(HarnessCase):
    def first_poll(self, *jobs: bd.ListedJob, **kw: Any) -> None:
        self.w.listings[self.board.key] = list(jobs)
        self.w.run(seeds=[self.board], **kw)

    def test_first_poll_evaluates_only_jobs_whose_timestamp_supports_the_window(self) -> None:
        self.first_poll(
            job("acme", "inside", published="2026-10-14T00:01:00Z"),  # 11 h 59 min
            job("acme", "outside", published="2026-10-13T23:59:00Z"),  # 12 h 1 min
            job("acme", "undated", published=""),
            job("acme", "ancient", published=ago(days=30)),
        )  # fmt: skip
        by = {k.split("|")[2]: s for k, s in self.w.states().items()}
        self.assertEqual((by["inside"].freshness, by["inside"].disposition), (fr.VERIFIED_FRESH, lg.PENDING))
        for k in ("outside", "undated", "ancient"):
            self.assertEqual((by[k].freshness, by[k].disposition), (fr.BASELINE, lg.BASELINED), k)  # existing postings are not "new"
        self.assertEqual((self.w.calls[self.key("inside")], self.w.calls[self.key("outside")], len(self.w.alerts)), (1, 0, 1))

    def test_day_precision_postings_on_a_first_poll_stay_baseline(self) -> None:
        wb = bd.BoardId(bd.WORKABLE, "wk")
        self.w.listings[wb.key] = [job("wk", "AAA", ats=bd.WORKABLE, published="2026-10-14", field="published_on")]
        self.w.run(seeds=[wb])
        self.assertEqual(self.w.states()[bd.JobIdentity(bd.WORKABLE, "wk", "AAA").key].freshness, fr.BASELINE)  # a date cannot prove 12 h

    def test_baselined_board_is_never_re_baselined_by_a_later_search_hit(self) -> None:
        self.first_poll(job("acme", "1", published=ago(days=30)))
        baselined_at = self.w.state.load_boards()[self.board.key].baselined_at
        self.w.listings[self.board.key].append(job("acme", "2", published=ago(days=30, base=T0 + timedelta(minutes=60))))
        self.w.run(minutes_later=60, discover=lambda ctx: dsc.DiscoveryResult(boards=[self.board]), force_discovery=True)
        # job 2 appeared after the baseline and is NOT a baseline job: its age (30 days) classifies it stale, not baseline
        self.assertEqual(self.w.states()[self.key("2")].freshness, fr.STALE)
        self.assertEqual(self.w.state.load_boards()[self.board.key].baselined_at, baselined_at)  # the board's baseline time is untouched

    def test_baseline_evaluation_keeps_scoring_and_alert_retries(self) -> None:
        self.w.alert_error = ConnectionError("telegram down")
        self.first_poll(job("acme", "inside", published="2026-10-14T00:01:00Z"), job("acme", "old", published=ago(days=2)))
        k = self.key("inside")
        self.assertEqual((len(self.w.events(k, lg.EVALUATED)), self.w.events(k, lg.ALERTED)), (1, []))
        self.w.alert_error = None
        self.w.run(minutes_later=60)
        self.assertEqual((len(self.w.alerts), self.w.calls[k], self.w.calls[self.key("old")]), (1, 1, 0))


class SheetStateTests(unittest.TestCase):
    def test_discovery_state_round_trips_through_the_hidden_sheet_tab(self) -> None:
        from test_hunter import FakeSpreadsheet, FakeWorksheet

        sh = FakeSpreadsheet([FakeWorksheet("Boards", [st_mod.BOARD_COLUMNS]), FakeWorksheet("Runs", [st_mod.RUN_COLUMNS[:15]])])
        state = st_mod.SheetState(sh)
        state.ensure()
        self.assertTrue(sh.tabs["Discovery"].hidden)
        self.assertEqual(state.load_discovery_state(), {})
        rot = dsc.advance(dsc.RotationState(), dsc.make_slots(["a"], ["r"], ["l1", "l2"]), 1, T0)
        state.save_discovery_state({dsc.ROTATION_KEY: rot.to_json(), dsc.PENDING_KEY: "{}"}, "2026-10-14T12:00:00Z")
        state.save_discovery_state({dsc.ROTATION_KEY: dsc.advance(rot, dsc.make_slots(["a"], ["r"], ["l1", "l2"]), 1, T0).to_json(), dsc.PENDING_KEY: "{}"}, "2026-10-14T13:00:00Z")
        loaded = state.load_discovery_state()
        self.assertEqual(dsc.RotationState.from_json(loaded[dsc.ROTATION_KEY]).cycles, 1)


# --------------------------------------------------------------------------- hydration retry queue


class HydrationRetryTests(HarnessCase):
    def sj(self) -> dsc.SerperJob:
        ident = bd.JobIdentity(bd.GREENHOUSE, "retryco", "55")
        return dsc.SerperJob(ident, "Marketing Intern", ident.url)

    def test_temporary_read_failure_is_queued_and_retried_without_a_search(self) -> None:
        board = bd.BoardId(bd.GREENHOUSE, "retryco")
        self.w.listings[board.key] = []
        listed = job("retryco", "55", published=ago(minutes=10, base=T0 + timedelta(minutes=180)))
        attempts: list[int] = []

        def hydrate(sj: dsc.SerperJob) -> bd.ListedJob | None:
            attempts.append(1)
            if len(attempts) < 3:
                raise pl.RetryableHydration("503")
            return listed

        self.w.run(discover=lambda ctx: dsc.DiscoveryResult(boards=[board], jobs=[self.sj()]), hydrate_listed=hydrate, force_discovery=True)
        self.assertIn(self.sj().ident.key, dsc.load_pending(self.w.state.load_discovery_state()[dsc.PENDING_KEY]))
        self.assertEqual(self.w.events(listed.ident.key, lg.SEEN), [])  # not seen yet: the failure left it undone
        self.w.run(minutes_later=60, hydrate_listed=hydrate)  # an ordinary hourly run, discovery not due
        self.w.run(minutes_later=60, hydrate_listed=hydrate)
        self.assertEqual((len(attempts), len(self.w.events(listed.ident.key, lg.SEEN))), (3, 1))
        self.assertEqual(dsc.load_pending(self.w.state.load_discovery_state()[dsc.PENDING_KEY]), {})

    def test_retries_are_bounded_and_the_drop_is_reported(self) -> None:
        board = bd.BoardId(bd.GREENHOUSE, "retryco")
        self.w.listings[board.key] = []

        def always(sj: dsc.SerperJob) -> bd.ListedJob | None:
            raise pl.RetryableHydration("503")

        self.w.run(discover=lambda ctx: dsc.DiscoveryResult(boards=[board], jobs=[self.sj()]), hydrate_listed=always, force_discovery=True)
        notes = ""
        for _ in range(dsc.MAX_HYDRATION_ATTEMPTS):
            notes += self.w.run(minutes_later=60, hydrate_listed=always).notes
        self.assertIn("dropped", notes)
        self.assertEqual(dsc.load_pending(self.w.state.load_discovery_state()[dsc.PENDING_KEY]), {})

    def test_a_pending_job_that_the_board_poll_found_first_is_not_retried(self) -> None:
        board = bd.BoardId(bd.GREENHOUSE, "retryco")
        listed = job("retryco", "55", published=ago(days=30))
        self.w.listings[board.key] = [listed]
        called: list[Any] = []
        self.w.run(
            discover=lambda ctx: dsc.DiscoveryResult(boards=[board], jobs=[self.sj()]),
            hydrate_listed=lambda s: called.append(s), force_discovery=True,
        )  # fmt: skip
        self.assertEqual((called, len(self.w.events(listed.ident.key, lg.SEEN))), ([], 1))


# --------------------------------------------------------------------------- run record


class RunRecordTests(HarnessCase):
    def test_discovery_metrics_are_logged_per_run_and_per_query(self) -> None:
        fresh = job("goodco", "1", published=ago(minutes=30))
        self.w.listings[bd.BoardId(bd.GREENHOUSE, "goodco").key] = [fresh]
        self.w.listings[bd.BoardId(bd.GREENHOUSE, "dullco").key] = []
        sr = bd.BoardId(bd.SMARTRECRUITERS, "SrCo")
        pages = [padded([gh("goodco", "1"), gh("dullco", "2"), "https://jobs.smartrecruiters.com/SrCo", gh("goodco", "1")])]

        def discover(ctx: pl.DiscoveryContext) -> dsc.DiscoveryResult:
            return dsc.run_queries(
                [dsc.Query("lever|marketing|austin", "q", "qdr:d3")], lambda q, p: pages[0] if p == 1 else padded([]),
                budget=10, is_new_board=ctx.is_new_board, is_unseen_job=ctx.is_unseen_job,
            )  # fmt: skip

        run = self.w.run(discover=discover, hydrate_listed=lambda sj: fresh if sj.ident.board == "goodco" else None, force_discovery=True)
        row = self.w.state.load_runs()[-1]
        self.assertEqual((run.search_queries, run.search_pages, run.search_credits), (1, 3, 3))  # page 1 + two empty pages -> stalled
        self.assertEqual((run.search_repeated, run.new_unique_boards), (1, 3))  # the duplicate goodco hit; goodco + dullco + SrCo
        self.assertEqual((run.eligible_boards, run.promoted_boards), (2, 1))  # SrCo is parked; dullco is valid but empty so it waits
        self.assertEqual(run.verified_fresh_matches, 1)
        self.assertEqual(
            (row.search_queries, row.search_credits, row.new_unique_boards, row.eligible_boards, row.promoted_boards, row.verified_fresh_matches),
            (1, 3, 3, 2, 1, 1),
        )  # fmt: skip
        last = self.w.state.load_discovery_state()[dsc.LAST_RUN_KEY]
        self.assertIn("lever|marketing|austin", last)  # query identity is persisted with its stats
        self.assertIn(sr.key, self.w.state.load_boards())

    def test_runs_tab_header_and_row_stay_in_step(self) -> None:
        self.assertEqual(len(st_mod.RUN_COLUMNS), len(st_mod.RunRecord(run_at="x").to_row()))
        rec = st_mod.RunRecord("2026-10-14T12:00:00Z", search_credits=7, verified_fresh_matches=2)
        again = st_mod.RunRecord.from_row([str(c) for c in rec.to_row()])
        self.assertEqual((again.search_credits, again.verified_fresh_matches), (7, 2))
        old = st_mod.RunRecord.from_row(["2026-10-14T12:00:00Z", "yes", "5"])  # a row written before these columns existed
        self.assertEqual((old.boards_total, old.search_credits), (5, 0))


if __name__ == "__main__":
    unittest.main()
