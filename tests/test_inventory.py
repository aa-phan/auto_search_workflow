"""Offline tests for the board inventory: importers, merge, validation, activation, persistence.

All mocked: fixtures stand in for the two upstream files and for ATS endpoints. Live numbers
for the real inventories are in STATUS.md.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))  # share helpers with test_core

import boards as bd  # noqa: E402
import freshness as fr  # noqa: E402
import hunter as h  # noqa: E402
import inventory as inv  # noqa: E402
import ledger as lg  # noqa: E402
import pipeline as pl  # noqa: E402
import state as stm  # noqa: E402
from test_core import HarnessCase, T0, ago, done, gate, job  # noqa: E402

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)


def feed_json(gh_live=("alpha", "beta"), gh_empty=("empty1",), lever_live=("lv1",), ashby_live=("as1",), extra: bool = True, as_of: str = "2026-09-03") -> bytes:
    prov: dict[str, Any] = {
        "greenhouse": {"live": [[t, 3] for t in gh_live], "empty": list(gh_empty), "verified": True},
        "lever": {"live": [[t, 2] for t in lever_live], "empty": [], "verified": True},
        "ashby": {"live": [[t, 1] for t in ashby_live], "empty": [], "verified": True},
    }
    if extra:
        prov["breezy"] = {"live": [["bz1", 1], ["bz2", 1]], "empty": ["bz3"], "verified": True}
    return json.dumps({"as_of": as_of, "providers": prov}).encode()


def csv_bytes(slugs: list[str], header: str = "name,slug,url") -> bytes:
    return (header + "\n" + "\n".join(f"Name {s},{s},https://example.com/{s}" for s in slugs) + "\n").encode()


class FakeNet:
    """Stands in for the two upstream repositories."""

    def __init__(self, files: dict[str, Any]) -> None:
        self.files, self.calls = files, []

    def __call__(self, url: str) -> bytes:
        self.calls.append(url)
        v = self.files[url]
        if isinstance(v, Exception):
            raise v
        return v


def standard_net(**kw: Any) -> FakeNet:
    listing = json.dumps([{"name": n} for n in ("greenhouse.csv", "lever.csv", "ashby.csv", "workable.csv", "workday.csv", "README.md")]).encode()
    files = {
        inv.OPEN_ATS_FEED_URL: feed_json(),
        inv.ATS_SCRAPERS_LIST_URL: listing,
        inv.ATS_SCRAPERS_RAW.format(name="greenhouse"): csv_bytes(["alpha", "gamma"]),  # alpha overlaps with the feed
        inv.ATS_SCRAPERS_RAW.format(name="lever"): csv_bytes(["lv1", "LvUpper"]),
        inv.ATS_SCRAPERS_RAW.format(name="ashby"): csv_bytes(["as2"]),
        inv.ATS_SCRAPERS_RAW.format(name="workable"): csv_bytes(["wk1"]),
        inv.ATS_SCRAPERS_RAW.format(name="workday"): csv_bytes(["w1", "w2", "w3"]),
    }
    files.update(kw)
    return FakeNet(files)


# --------------------------------------------------------------------------- identity


class IdentityCasingTests(unittest.TestCase):
    def test_case_sensitive_providers_keep_exact_case_others_do_not(self) -> None:
        self.assertNotEqual(bd.BoardId("lever", "Foo").key, bd.BoardId("lever", "foo").key)
        self.assertNotEqual(bd.BoardId("workable", "Foo").key, bd.BoardId("workable", "foo").key)
        for ats in ("greenhouse", "ashby", "smartrecruiters"):
            self.assertEqual(bd.BoardId(ats, "Foo").key, bd.BoardId(ats, "foo").key)

    def test_region_is_part_of_board_identity_but_default_keys_are_unchanged(self) -> None:
        self.assertEqual(bd.BoardId("greenhouse", "acme").key, "greenhouse|acme")  # same as before this feature
        self.assertEqual(bd.BoardId("lever", "acme", "eu").key, "lever@eu|acme")
        self.assertNotEqual(bd.BoardId("lever", "acme").key, bd.BoardId("lever", "acme", "eu").key)

    def test_job_keys_written_before_this_change_still_match(self) -> None:
        self.assertEqual(bd.JobIdentity("lever", "32Co", "ABC-1").key, "lever|32co|abc-1")  # board part stays lowercase
        self.assertEqual(bd.JobIdentity("greenhouse", "Acme", "7").key, "greenhouse|acme|7")
        self.assertEqual(bd.JobIdentity("lever", "acme", "x", "eu").key, "lever@eu|acme|x")


# --------------------------------------------------------------------------- parsers


class ParserTests(unittest.TestCase):
    def test_open_ats_feed_supported_unsupported_and_rejected(self) -> None:
        raw = json.dumps({"as_of": "2026-09-03", "providers": {
            "greenhouse": {"live": [["ok", 5], ["bad token", 1]], "empty": ["fine"], "verified": True},
            "teamtailor": {"live": [["t1", 1]], "empty": ["t2", "t3"], "verified": True},
        }}).encode()  # fmt: skip
        cands, rep = inv.parse_open_ats_feed(raw)
        self.assertEqual({c.board.board for c in cands}, {"ok", "fine"})
        self.assertEqual((rep.rows_total, rep.rows_supported, rep.rows_rejected, rep.unique_boards), (6, 3, 1, 2))
        self.assertEqual(rep.unsupported, {"teamtailor": 3})
        self.assertEqual((rep.as_of, {c.info["state"] for c in cands}), ("2026-09-03", {"live", "empty"}))

    def test_open_ats_feed_schema_change_is_an_error_not_an_empty_import(self) -> None:
        for bad in (b"not json", b"{}", json.dumps({"providers": {"greenhouse": {"companies": []}}}).encode(), json.dumps({"providers": {}}).encode()):
            with self.assertRaises(inv.InventoryError):
                inv.parse_open_ats_feed(bad)

    def test_ats_scrapers_slug_case_is_preserved_and_bad_rows_rejected(self) -> None:
        raw = b"name,slug,url\nA,LvUpper,https://jobs.lever.co/LvUpper\nB,  lower ,https://x\nC,has space,https://x\nD,,https://x\n"
        cands, rows, rej = inv.parse_ats_scrapers_csv("lever", raw)
        self.assertEqual([c.board.board for c in cands], ["LvUpper", "lower"])
        self.assertEqual((rows, rej), (4, 2))
        self.assertEqual(cands[0].name, "A")

    def test_ats_scrapers_legacy_two_column_shape(self) -> None:
        cands, rows, rej = inv.parse_ats_scrapers_csv("workable", b"name,url\nAcme,acme-co\nBeta,https://apply.workable.com/beta\n")
        self.assertEqual(sorted(c.board.board for c in cands), ["acme-co", "beta"])

    def test_ats_scrapers_header_change_is_an_error(self) -> None:
        with self.assertRaises(inv.InventoryError):
            inv.parse_ats_scrapers_csv("lever", b"company,id\nA,1\n")


# --------------------------------------------------------------------------- loaders + last-known-good


class LoaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.cache = inv.InventoryCache(Path(self._tmp.name))

    def test_both_sources_load_and_report_unsupported_providers(self) -> None:
        net = standard_net()
        feed, frep = inv.load_open_ats_feed(self.cache, get=net)
        scr, srep = inv.load_ats_scrapers(self.cache, get=net)
        self.assertEqual((frep.status, srep.status), ("ok", "ok"))
        self.assertEqual(frep.unsupported, {"breezy": 3})
        self.assertEqual(srep.unsupported, {"workday": 3})
        self.assertEqual({c.board.key for c in scr}, {"greenhouse|alpha", "greenhouse|gamma", "lever|lv1", "lever|LvUpper", "ashby|as2", "workable|wk1"})
        self.assertEqual(len(feed), 5)

    def test_download_failure_falls_back_to_last_known_good(self) -> None:
        inv.load_open_ats_feed(self.cache, get=standard_net())
        down = standard_net(**{inv.OPEN_ATS_FEED_URL: inv.InventoryError("HTTP 503")})
        cands, rep = inv.load_open_ats_feed(self.cache, get=down)
        self.assertEqual((rep.status, len(cands)), ("cached", 5))
        self.assertIn("HTTP 503", rep.note)

    def test_failure_with_no_cache_is_reported_failed_not_empty_success(self) -> None:
        cands, rep = inv.load_open_ats_feed(self.cache, get=standard_net(**{inv.OPEN_ATS_FEED_URL: inv.InventoryError("HTTP 500")}))
        self.assertEqual((cands, rep.status), ([], "failed"))

    def test_schema_change_keeps_last_known_good_and_does_not_overwrite_it(self) -> None:
        inv.load_open_ats_feed(self.cache, get=standard_net())
        before = self.cache.load(inv.OPEN_ATS_FEED, "companies.json")
        cands, rep = inv.load_open_ats_feed(self.cache, get=standard_net(**{inv.OPEN_ATS_FEED_URL: b'{"providers": {"greenhouse": {"companies": []}}}'}))
        self.assertEqual((rep.status, len(cands)), ("cached", 5))
        self.assertEqual(self.cache.load(inv.OPEN_ATS_FEED, "companies.json"), before)

    def test_collapsed_download_is_rejected_by_the_shrink_guard(self) -> None:
        inv.load_open_ats_feed(self.cache, get=standard_net())
        tiny = feed_json(gh_live=(), gh_empty=(), lever_live=("x",), ashby_live=())
        cands, rep = inv.load_open_ats_feed(self.cache, get=standard_net(**{inv.OPEN_ATS_FEED_URL: tiny}))
        self.assertEqual((rep.status, len(cands)), ("cached", 5))
        self.assertIn("fell", rep.note)

    def test_one_bad_ats_scrapers_file_does_not_lose_the_others(self) -> None:
        inv.load_ats_scrapers(self.cache, get=standard_net())
        net = standard_net(**{inv.ATS_SCRAPERS_RAW.format(name="lever"): inv.InventoryError("HTTP 500"), inv.ATS_SCRAPERS_RAW.format(name="ashby"): b"garbage,header\n1,2\n"})
        cands, rep = inv.load_ats_scrapers(self.cache, get=net)
        keys = {c.board.key for c in cands}
        self.assertIn("lever|lv1", keys)  # served from the cache
        self.assertIn("ashby|as2", keys)
        self.assertIn("greenhouse|gamma", keys)
        self.assertEqual(rep.status, "cached")
        self.assertEqual(sorted(rep.from_cache_files), ["ashby.csv", "lever.csv"])

    def test_listing_failure_uses_cached_provider_files_to_keep_reporting_unsupported_ones(self) -> None:
        inv.load_ats_scrapers(self.cache, get=standard_net())
        net = standard_net(**{inv.ATS_SCRAPERS_LIST_URL: inv.InventoryError("HTTP 403")})
        _, rep = inv.load_ats_scrapers(self.cache, get=net)
        self.assertEqual(rep.unsupported, {"workday": 3})
        self.assertIn("cached provider files", rep.note)

    def test_listing_failure_still_imports_the_supported_files(self) -> None:
        net = standard_net(**{inv.ATS_SCRAPERS_LIST_URL: inv.InventoryError("HTTP 403 rate limited")})
        net.files[inv.ATS_SCRAPERS_RAW.format(name="smartrecruiters")] = csv_bytes(["sr1"])
        cands, rep = inv.load_ats_scrapers(self.cache, get=net)
        self.assertEqual(rep.status, "partial")
        self.assertIn("greenhouse|gamma", {c.board.key for c in cands})
        self.assertEqual(rep.unsupported, {})  # could not be enumerated, and the report says so
        self.assertIn("not enumerated", rep.note)

    def test_http_helper_retries_transient_failures_but_not_404(self) -> None:
        resp = lambda code, body=b"": mock.Mock(status_code=code, content=body)  # noqa: E731
        sleeps: list[float] = []
        with mock.patch.object(inv.requests, "get", side_effect=[resp(503), resp(429), resp(200, b"ok")]) as g:
            self.assertEqual(inv.http_get_bytes("u", sleep=sleeps.append), b"ok")
        self.assertEqual((g.call_count, sleeps), (3, [2, 4]))
        with mock.patch.object(inv.requests, "get", return_value=resp(404)) as g, self.assertRaises(inv.InventoryError):
            inv.http_get_bytes("u", sleep=lambda s: None)
        self.assertEqual(g.call_count, 1)


# --------------------------------------------------------------------------- merge + idempotence


def cand(ats: str, board: str, source: str, **kw: Any) -> bd.Candidate:
    return bd.Candidate(bd.BoardId(ats, board), source, **kw)


class MergeTests(unittest.TestCase):
    def test_sources_merge_into_one_row_with_all_provenance(self) -> None:
        reg: dict[str, bd.BoardRecord] = {}
        added, upd = bd.merge_candidates(reg, [cand("greenhouse", "alpha", inv.OPEN_ATS_FEED, info={"state": "live"})], now=NOW, new_status=bd.STATUS_CANDIDATE)
        later = NOW + timedelta(days=7)
        added2, upd2 = bd.merge_candidates(reg, [cand("greenhouse", "Alpha", inv.ATS_SCRAPERS, name="Alpha Inc")], now=later, new_status=bd.STATUS_CANDIDATE)
        self.assertEqual((len(added), len(added2), len(upd2), len(reg)), (1, 0, 1, 1))
        rec = reg["greenhouse|alpha"]
        self.assertEqual(set(rec.provenance), {inv.OPEN_ATS_FEED, inv.ATS_SCRAPERS})
        self.assertEqual(rec.discovered_at, NOW.strftime(bd.STAMP))  # first discovery time survives
        self.assertEqual((rec.source, rec.board, rec.name), (inv.OPEN_ATS_FEED, "alpha", "Alpha Inc"))  # first casing/source kept

    def test_lever_case_variants_are_distinct_boards(self) -> None:
        reg: dict[str, bd.BoardRecord] = {}
        bd.merge_candidates(reg, [cand("lever", "Foo", "a"), cand("lever", "foo", "b")], now=NOW, new_status=bd.STATUS_CANDIDATE)
        self.assertEqual(sorted(r.board for r in reg.values()), ["Foo", "foo"])

    def test_reimport_is_idempotent_and_never_touches_polling_state(self) -> None:
        reg: dict[str, bd.BoardRecord] = {}
        cands = [cand("greenhouse", "alpha", inv.OPEN_ATS_FEED, info={"state": "live"}), cand("lever", "lv1", inv.ATS_SCRAPERS)]
        bd.merge_candidates(reg, cands, now=NOW, new_status=bd.STATUS_CANDIDATE)
        rec = reg["greenhouse|alpha"]
        rec.status, rec.baselined_at, rec.last_success_at, rec.consecutive_failures = bd.STATUS_ACTIVE, "2026-10-01T00:00:00Z", "2026-10-14T11:00:00Z", 2
        rec.validation, rec.last_validated_at, rec.relevant_jobs = bd.V_VALID, "2026-10-14T11:00:00Z", 4
        snapshot = json.dumps({k: v.__dict__ for k, v in reg.items()}, default=str, sort_keys=True)
        added, updated = bd.merge_candidates(reg, cands, now=NOW + timedelta(days=7), new_status=bd.STATUS_CANDIDATE)
        self.assertEqual((added, updated), ([], []))  # nothing to write
        self.assertEqual(json.dumps({k: v.__dict__ for k, v in reg.items()}, default=str, sort_keys=True), snapshot)

    def test_upstream_disappearance_changes_nothing(self) -> None:
        reg: dict[str, bd.BoardRecord] = {}
        bd.merge_candidates(reg, [cand("greenhouse", "gone", inv.OPEN_ATS_FEED), cand("greenhouse", "stays", inv.OPEN_ATS_FEED)], now=NOW, new_status=bd.STATUS_CANDIDATE)
        reg["greenhouse|gone"].status = bd.STATUS_ACTIVE
        bd.merge_candidates(reg, [cand("greenhouse", "stays", inv.OPEN_ATS_FEED)], now=NOW + timedelta(days=7), new_status=bd.STATUS_CANDIDATE)
        self.assertEqual((reg["greenhouse|gone"].status, len(reg)), (bd.STATUS_ACTIVE, 2))

    def test_serper_discoveries_survive_and_gain_inventory_provenance_without_a_status_change(self) -> None:
        reg: dict[str, bd.BoardRecord] = {}
        bd.upsert_boards(reg, [bd.BoardId("greenhouse", "alpha")], now=NOW, source="search")
        self.assertEqual(reg["greenhouse|alpha"].status, bd.STATUS_NEW)  # live-URL discoveries start monitoring as before
        bd.merge_candidates(reg, [cand("greenhouse", "alpha", inv.OPEN_ATS_FEED)], now=NOW + timedelta(days=1), new_status=bd.STATUS_CANDIDATE)
        rec = reg["greenhouse|alpha"]
        self.assertEqual((rec.status, rec.source, set(rec.provenance)), (bd.STATUS_NEW, "search", {"search", inv.OPEN_ATS_FEED}))


class ImportEndToEndTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.cache = inv.InventoryCache(Path(self._tmp.name))
        self.saved: list[list[bd.BoardRecord]] = []

    def do_import(self, reg: dict, net: FakeNet, meta: dict | None = None) -> inv.ImportResult:
        return inv.import_inventories(reg, cache=self.cache, save=self.saved.append, now=NOW, get=net, meta=meta)

    def test_report_numbers_overlap_and_contributions(self) -> None:
        reg: dict[str, bd.BoardRecord] = {}
        bd.upsert_boards(reg, [bd.BoardId("greenhouse", "gamma")], now=NOW, source="search")  # already known from search
        meta: dict[str, dict[str, str]] = {}
        res = self.do_import(reg, standard_net(), meta)
        ov = res.overlap
        feed, scr = ov.per_source[inv.OPEN_ATS_FEED], ov.per_source[inv.ATS_SCRAPERS]
        self.assertEqual((feed.rows_total, feed.rows_supported, feed.unique_boards), (8, 5, 5))  # breezy x3 reported, not imported
        self.assertEqual((scr.rows_total, scr.rows_supported, scr.unique_boards), (9, 6, 6))
        self.assertEqual((ov.overlap, ov.unique_union), (2, 9))  # alpha and lv1 appear in both
        self.assertEqual(ov.only, {inv.OPEN_ATS_FEED: 3, inv.ATS_SCRAPERS: 4})
        self.assertEqual(ov.new_vs_registry, {inv.OPEN_ATS_FEED: 5, inv.ATS_SCRAPERS: 5})  # "gamma" was already known via search
        self.assertEqual(ov.already_known[inv.ATS_SCRAPERS], 1)
        self.assertEqual((res.added, len(reg)), (8, 9))
        self.assertEqual(meta[inv.OPEN_ATS_FEED]["As_Of"], "2026-09-03")
        self.assertEqual(reg["greenhouse|gamma"].status, bd.STATUS_NEW)  # the Serper discovery kept its status
        self.assertTrue(all(r.status == bd.STATUS_CANDIDATE for k, r in reg.items() if k != "greenhouse|gamma"))
        text = inv.format_report(res, None, bd.registry_counts(reg))
        for needle in ("overlap (in both sources): 2", "unique union: 9", "breezy 3", "workday 3"):
            self.assertIn(needle, text)

    def test_second_import_writes_nothing(self) -> None:
        reg: dict[str, bd.BoardRecord] = {}
        self.do_import(reg, standard_net())
        self.saved.clear()
        res = self.do_import(reg, standard_net())
        self.assertEqual((res.added, res.updated, self.saved), (0, 0, []))

    def test_failed_download_imports_nothing_and_keeps_the_registry(self) -> None:
        reg: dict[str, bd.BoardRecord] = {}
        self.do_import(reg, standard_net())
        before = len(reg)
        net = standard_net(**{inv.OPEN_ATS_FEED_URL: inv.InventoryError("HTTP 500"), inv.ATS_SCRAPERS_LIST_URL: inv.InventoryError("HTTP 500")})
        res = self.do_import(reg, net)
        self.assertEqual((len(reg), res.added), (before, 0))  # cached copies re-merge as a no-op


# --------------------------------------------------------------------------- validation


def listed(n: int, title: str = "Marketing Intern") -> list[bd.ListedJob]:
    return [job("b", f"{i}", title=title if i == 0 else "Software Engineer") for i in range(n)]


class ValidateBoardTests(unittest.TestCase):
    board = bd.BoardId("greenhouse", "alpha")

    def run_one(self, outcomes: list[Any], retries: int = 3) -> tuple[inv.ValidationResult, list[float]]:
        sleeps: list[float] = []
        seq = list(outcomes)

        def fetch(b: bd.BoardId) -> list[bd.ListedJob]:
            v = seq.pop(0)
            if isinstance(v, Exception):
                raise v
            return v

        return inv.validate_board(self.board, fetch=fetch, title_gate=gate, retries=retries, sleep=sleeps.append), sleeps

    def test_valid_empty_and_invalid_are_distinct(self) -> None:
        r, _ = self.run_one([listed(3)])
        self.assertEqual((r.outcome, r.jobs, r.relevant), (bd.V_VALID, 3, 1))
        r, _ = self.run_one([[]])
        self.assertEqual((r.outcome, r.jobs), (bd.V_EMPTY, 0))
        r, sleeps = self.run_one([bd.BoardGone("HTTP 404")])
        self.assertEqual((r.outcome, sleeps), (bd.V_INVALID, []))  # a 404 is not retried

    def test_temporary_failures_retry_with_backoff_then_stay_transient(self) -> None:
        r, sleeps = self.run_one([bd.BoardError("HTTP 503")] * 3)
        self.assertEqual((r.outcome, sleeps), (bd.V_TRANSIENT, [1.5, 3.0]))
        r, _ = self.run_one([bd.BoardError("timeout"), bd.BoardError("HTTP 429"), listed(2)])
        self.assertEqual(r.outcome, bd.V_VALID)  # recovered on the third try

    def test_adapter_bug_is_not_evidence_of_a_closed_board(self) -> None:
        r, _ = self.run_one([RuntimeError("parser exploded")])
        self.assertEqual(r.outcome, bd.V_TRANSIENT)


class ApplyValidationTests(unittest.TestCase):
    def rec(self, status: str = bd.STATUS_CANDIDATE) -> bd.BoardRecord:
        return bd.BoardRecord("greenhouse", "alpha", "t", "open-ats-feed", status)

    def test_transient_never_changes_status_and_counts_failures(self) -> None:
        r = self.rec()
        inv.apply_validation(r, inv.ValidationResult(bd.V_TRANSIENT, error="HTTP 503"), NOW)
        self.assertEqual((r.status, r.validation, r.consecutive_failures, r.last_error), (bd.STATUS_CANDIDATE, "", 1, "HTTP 503"))

    def test_outcomes_map_to_statuses(self) -> None:
        r = self.rec()
        inv.apply_validation(r, inv.ValidationResult(bd.V_VALID, jobs=9, relevant=2), NOW)
        self.assertEqual((r.status, r.validation, r.relevant_jobs, r.last_job_count, r.last_validated_at), (bd.STATUS_VALIDATED, "valid", 2, 9, NOW.strftime(bd.STAMP)))
        r = self.rec()
        inv.apply_validation(r, inv.ValidationResult(bd.V_INVALID), NOW)
        self.assertEqual((r.status, r.validation), (bd.STATUS_INVALID, "invalid"))
        r = self.rec()
        inv.apply_validation(r, inv.ValidationResult(bd.V_EMPTY), NOW)
        self.assertEqual((r.status, r.relevant_jobs), (bd.STATUS_VALIDATED, 0))

    def test_rows_owned_by_the_poller_are_never_touched(self) -> None:
        for status in (bd.STATUS_NEW, bd.STATUS_ACTIVE, bd.STATUS_DISABLED):
            r = self.rec(status)
            self.assertFalse(inv.apply_validation(r, inv.ValidationResult(bd.V_INVALID), NOW))
            self.assertEqual((r.status, r.validation), (status, ""))

    def test_when_validation_is_due(self) -> None:
        r = self.rec()
        self.assertTrue(inv.validation_due(r, NOW))  # never attempted
        r.last_attempt_at, r.consecutive_failures = NOW.strftime(bd.STAMP), 3
        self.assertFalse(inv.validation_due(r, NOW + timedelta(hours=7)))  # backing off: 2^3 = 8 h
        self.assertTrue(inv.validation_due(r, NOW + timedelta(hours=8)))
        v = self.rec(bd.STATUS_VALIDATED)
        v.last_validated_at = NOW.strftime(bd.STAMP)
        self.assertFalse(inv.validation_due(v, NOW + timedelta(days=6)))
        self.assertTrue(inv.validation_due(v, NOW + timedelta(days=7)))
        i = self.rec(bd.STATUS_INVALID)
        i.last_attempt_at = NOW.strftime(bd.STAMP)
        self.assertFalse(inv.validation_due(i, NOW + timedelta(days=29)))  # not hammered, but not forgotten either
        self.assertTrue(inv.validation_due(i, NOW + timedelta(days=30)))


class RunValidationTests(unittest.TestCase):
    def registry(self, specs: list[tuple[str, str]]) -> dict[str, bd.BoardRecord]:
        reg: dict[str, bd.BoardRecord] = {}
        bd.merge_candidates(reg, [cand(a, b, inv.OPEN_ATS_FEED) for a, b in specs], now=NOW, new_status=bd.STATUS_CANDIDATE)
        return reg

    def validate(self, reg: dict, fetch: Any, **kw: Any) -> tuple[inv.ValidationSummary, list[list[bd.BoardRecord]]]:
        saves: list[list[bd.BoardRecord]] = []
        kw.setdefault("limiter", inv.HostLimiter(sleep=lambda s: None))
        kw.setdefault("sleep", lambda s: None)
        return inv.run_validation(reg, save=saves.append, now=NOW, fetch=fetch, title_gate=gate, **kw), saves

    def test_bounded_by_count_with_batched_persistence(self) -> None:
        reg = self.registry([("greenhouse", f"b{i}") for i in range(7)])
        summary, saves = self.validate(reg, lambda b: listed(2), max_boards=5, wave=2)
        self.assertEqual((summary.attempted, summary.remaining_due), (5, 2))
        self.assertEqual([len(s) for s in saves], [2, 2, 1])  # progress is saved wave by wave
        self.assertEqual(sum(1 for r in reg.values() if r.status == bd.STATUS_VALIDATED), 5)

    def test_bounded_by_time_and_saves_what_it_finished(self) -> None:
        reg = self.registry([("greenhouse", f"b{i}") for i in range(6)])
        ticks = iter(range(0, 1000, 1))
        summary, saves = self.validate(reg, lambda b: listed(1), max_seconds=2.5, wave=2, clock=lambda: float(next(ticks)))
        self.assertLess(summary.attempted, 6)
        self.assertGreater(summary.remaining_due, 0)

    def test_transient_failures_leave_boards_as_candidates_never_invalid(self) -> None:
        reg = self.registry([("greenhouse", "x"), ("greenhouse", "y")])

        def fetch(b: bd.BoardId) -> list[bd.ListedJob]:
            raise bd.BoardError("HTTP 503")

        summary, _ = self.validate(reg, fetch)
        self.assertEqual(summary.by_outcome, {bd.V_TRANSIENT: 2})
        self.assertEqual({r.status for r in reg.values()}, {bd.STATUS_CANDIDATE})
        self.assertTrue(all(r.consecutive_failures == 1 for r in reg.values()))

    def test_provider_outage_trips_the_breaker_instead_of_hammering(self) -> None:
        reg = self.registry([("greenhouse", f"g{i}") for i in range(30)] + [("ashby", "a1")])
        calls = collections_counter()

        def fetch(b: bd.BoardId) -> list[bd.ListedJob]:
            calls[b.ats] += 1
            if b.ats == "greenhouse":
                raise bd.BoardError("HTTP 500")
            return listed(1)

        summary, _ = self.validate(reg, fetch, breaker_after=5, workers=1, wave=100)
        self.assertEqual(summary.paused, ["greenhouse"])
        self.assertLess(calls["greenhouse"], 30 * 3)  # far fewer than every board x every retry
        self.assertEqual(reg["ashby|a1"].status, bd.STATUS_VALIDATED)  # other providers are unaffected

    def test_smartrecruiters_is_parked_by_policy_unless_explicitly_allowed(self) -> None:
        reg = self.registry([("smartrecruiters", "Sr1"), ("greenhouse", "g1")])
        seen: list[str] = []
        summary, _ = self.validate(reg, lambda b: seen.append(b.ats) or listed(1))
        self.assertEqual((seen, reg["smartrecruiters|sr1"].status, summary.deferred_by_policy), (["greenhouse"], bd.STATUS_DEFERRED, 1))
        self.assertIn("robots.txt", reg["smartrecruiters|sr1"].last_error)
        summary, _ = self.validate(reg, lambda b: seen.append(b.ats) or listed(1), allow_smartrecruiters=True)
        self.assertEqual(reg["smartrecruiters|sr1"].status, bd.STATUS_VALIDATED)  # opted in: validated like the rest

    def test_per_provider_rate_limits_are_enforced(self) -> None:
        now = {"t": 0.0}
        slept: list[float] = []
        lim = inv.HostLimiter(clock=lambda: now["t"], sleep=slept.append)
        for _ in range(3):
            lim.wait("lever")  # Crawl-delay: 1
        self.assertEqual(slept, [1.0, 2.0])
        self.assertEqual(inv.MIN_INTERVAL["lever"], 1.0)

    def test_providers_are_interleaved_so_none_is_starved(self) -> None:
        reg = self.registry([("ashby", f"a{i}") for i in range(6)] + [("greenhouse", f"g{i}") for i in range(2)] + [("lever", "l0")])
        order: list[str] = []
        self.validate(reg, lambda b: order.append(b.ats) or listed(1), workers=1, max_boards=5)
        self.assertEqual(sorted(set(order)), ["ashby", "greenhouse", "lever"])  # all three progress in a capped run
        self.assertEqual(order[:3].count("ashby"), 1)

    def test_validation_priority_prefers_boards_both_sources_vouch_for(self) -> None:
        reg: dict[str, bd.BoardRecord] = {}
        bd.merge_candidates(reg, [cand("greenhouse", "solo", inv.ATS_SCRAPERS), cand("greenhouse", "pair", inv.ATS_SCRAPERS)], now=NOW, new_status=bd.STATUS_CANDIDATE)
        bd.merge_candidates(reg, [cand("greenhouse", "pair", inv.OPEN_ATS_FEED, info={"state": "live"})], now=NOW, new_status=bd.STATUS_CANDIDATE)
        order = []
        self.validate(reg, lambda b: order.append(b.board) or listed(1), workers=1, max_boards=1)
        self.assertEqual(order, ["pair"])


class ValidationQueueTests(unittest.TestCase):
    """Two independently budgeted queues: never-validated candidates and overdue re-checks (D-29)."""

    def registry(self, n_candidates: int, overdue: list[tuple[str, str, int]] = (), **kw: Any) -> dict[str, bd.BoardRecord]:  # type: ignore[assignment]
        reg: dict[str, bd.BoardRecord] = {}
        bd.merge_candidates(reg, [cand("greenhouse", f"c{i:04d}", inv.OPEN_ATS_FEED) for i in range(n_candidates)], now=NOW, new_status=bd.STATUS_CANDIDATE)
        for ats, name, days_over in overdue:  # validated boards whose re-check is `days_over` days late
            r = bd.BoardRecord(ats, name, ago(days=90), inv.OPEN_ATS_FEED, bd.STATUS_VALIDATED, validation=bd.V_VALID, relevant_jobs=1,
                               last_validated_at=(NOW - timedelta(days=7 + days_over)).strftime(bd.STAMP))  # fmt: skip
            reg[r.key] = r
        return reg

    def run_it(self, reg: dict, order: list[str] | None = None, **kw: Any) -> inv.ValidationSummary:
        def fetch(b: bd.BoardId) -> list[bd.ListedJob]:
            if order is not None:
                order.append(b.board)
            return listed(2)

        kw.setdefault("workers", 1)
        return inv.run_validation(reg, save=lambda recs: None, now=NOW, fetch=fetch, title_gate=gate,
                                  limiter=inv.HostLimiter(sleep=lambda s: None), sleep=lambda s: None, **kw)  # fmt: skip

    def test_a_huge_candidate_backlog_cannot_starve_overdue_revalidations(self) -> None:
        overdue = [("greenhouse", f"r{i}", d) for i, d in enumerate((1, 9, 3, 30, 5))]  # r3 is the most overdue, then r1, then r4
        reg = self.registry(1000, overdue)
        order: list[str] = []
        s = self.run_it(reg, order, max_boards=10, max_revalidations=3)
        self.assertEqual((s.attempted_candidates, s.attempted_revalidations, s.attempted), (10, 3, 13))
        self.assertEqual({b for b in order if b.startswith("r")}, {"r3", "r1", "r4"})  # the three MOST overdue, nobody else
        self.assertEqual([b[0] for b in order[:6]], ["r", "c", "r", "c", "r", "c"])  # strict alternation, a re-check first
        self.assertEqual((s.candidates_due, s.revalidations_due, s.remaining_due), (1000, 5, 990 + 2))  # both queues counted

    def test_revalidations_run_oldest_first_within_a_provider(self) -> None:
        reg = self.registry(0, [("greenhouse", f"r{i}", d) for i, d in enumerate((2, 20, 8, 12))])
        invalid = bd.BoardRecord("greenhouse", "inv1", ago(days=90), "s", bd.STATUS_INVALID, validation=bd.V_INVALID, last_attempt_at=(NOW - timedelta(days=60)).strftime(bd.STAMP))
        reg[invalid.key] = invalid  # an invalid board re-checked 30 days after its last attempt: 30 days overdue, so after r1 (20) ... before r3 (12)
        order: list[str] = []
        self.run_it(reg, order, max_boards=0)
        self.assertEqual(order, ["inv1", "r1", "r3", "r2", "r0"])

    def test_boards_without_a_timestamp_are_re_checked_first(self) -> None:
        reg = self.registry(0, [("greenhouse", "dated", 5)])
        blank = bd.BoardRecord("greenhouse", "blank", ago(days=90), "s", bd.STATUS_VALIDATED, validation=bd.V_VALID, relevant_jobs=1)
        reg[blank.key] = blank
        order: list[str] = []
        self.run_it(reg, order, max_boards=0)
        self.assertEqual(order, ["blank", "dated"])

    def test_the_two_budgets_are_independent(self) -> None:
        reg = self.registry(5, [("greenhouse", f"r{i}", 1) for i in range(5)])
        none = self.run_it(reg, max_boards=3, max_revalidations=0)
        self.assertEqual((none.attempted_candidates, none.attempted_revalidations), (3, 0))  # zero re-checks means none
        reg2 = self.registry(5, [("greenhouse", f"r{i}", 1) for i in range(5)])
        only = self.run_it(reg2, max_boards=0, max_revalidations=4)
        self.assertEqual((only.attempted_candidates, only.attempted_revalidations), (0, 4))
        reg3 = self.registry(2, [("greenhouse", "r0", 1)])
        both = self.run_it(reg3, max_boards=500, max_revalidations=500)
        self.assertEqual((both.attempted, both.remaining_due), (3, 0))

    def test_summary_ages_and_report_lines(self) -> None:
        reg = self.registry(2, [("greenhouse", "r0", 3), ("greenhouse", "r1", 10)])
        for r in reg.values():
            if r.status == bd.STATUS_CANDIDATE:
                r.discovered_at = (NOW - timedelta(hours=50)).strftime(bd.STAMP)
        stats = inv.queue_stats(reg, NOW)
        self.assertEqual((stats["candidates_due"], stats["revalidations_due"], stats["oldest_candidate_hours"], stats["oldest_overdue_hours"]), (2, 2, 50, 240))
        s = self.run_it(reg, max_boards=1, max_revalidations=1)
        self.assertEqual((s.oldest_candidate_hours, s.oldest_overdue_hours, s.remaining_due), (50, 240, 2))
        text = inv.format_report(None, s, bd.registry_counts(reg))
        self.assertIn("candidates:    due 2, attempted 1, oldest waiting 50 h", text)
        self.assertIn("revalidations: overdue 2, attempted 1, oldest overdue 240 h", text)

    def test_waiting_smartrecruiters_boards_are_parked_while_blocked(self) -> None:
        reg = self.registry(0, [("smartrecruiters", "SrWait", 1), ("greenhouse", "gh", 1)])
        s = self.run_it(reg)
        parked = reg["smartrecruiters|srwait"]
        self.assertEqual((parked.status, parked.validation, s.deferred_by_policy), (bd.STATUS_DEFERRED, bd.V_DEFERRED, 1))
        self.assertIn("robots.txt", parked.last_error)
        self.assertEqual(reg["greenhouse|gh"].status, bd.STATUS_VALIDATED)
        again = self.registry(0, [("smartrecruiters", "SrWait", 1)])
        self.run_it(again, allow_smartrecruiters=True)
        self.assertEqual(again["smartrecruiters|srwait"].status, bd.STATUS_VALIDATED)  # opted in: re-checked like the rest

    def test_validation_records_eligible_jobs_and_starts_the_waiting_clock_once(self) -> None:
        reg = self.registry(1)
        us, abroad = job("b", "1", location="Remote"), job("b", "2", location="London")
        dup = job("b", "1", location="Remote")  # the same posting listed twice counts once
        other = job("b", "3", title="Software Engineer")

        def fetch(b: bd.BoardId) -> list[bd.ListedJob]:
            return [us, abroad, dup, other]

        inv.run_validation(reg, save=lambda r: None, now=NOW, fetch=fetch, title_gate=gate, workers=1, limiter=inv.HostLimiter(sleep=lambda s: None), sleep=lambda s: None)
        rec = reg["greenhouse|c0000"]
        self.assertEqual((rec.relevant_jobs, rec.eligible_jobs, rec.last_job_count, rec.relevance_at), (2, 1, 3, NOW.strftime(bd.STAMP)))
        self.assertEqual(rec.pool_since, NOW.strftime(bd.STAMP))
        self.assertIn("validated 2026-10-14: waiting for a slot", rec.pool_reason)
        later = NOW + timedelta(days=8)
        inv.run_validation(reg, save=lambda r: None, now=later, fetch=fetch, title_gate=gate, workers=1, limiter=inv.HostLimiter(sleep=lambda s: None), sleep=lambda s: None)
        self.assertEqual((rec.pool_since, rec.last_validated_at), (NOW.strftime(bd.STAMP), later.strftime(bd.STAMP)))  # a re-check does not reset the clock


def collections_counter() -> Any:
    import collections

    return collections.Counter()


# --------------------------------------------------------------------------- activation budget


class ActivationTests(unittest.TestCase):
    def reg(self, n_ready: int, relevant: int = 1, **status_counts: int) -> dict[str, bd.BoardRecord]:
        reg: dict[str, bd.BoardRecord] = {}
        for i in range(n_ready):
            r = bd.BoardRecord("greenhouse", f"ready{i}", "t", "s", bd.STATUS_VALIDATED, validation=bd.V_VALID, relevant_jobs=relevant + i, last_job_count=10)
            reg[r.key] = r
        for status, n in status_counts.items():
            for i in range(n):
                r = bd.BoardRecord("lever", f"{status}{i}", "t", "s", status)
                reg[r.key] = r
        return reg

    def test_never_exceeds_the_polling_budget_or_the_per_run_surge_cap(self) -> None:
        reg = self.reg(100)
        promoted = bd.activate_waiting(reg, max_monitored=30, per_run=10)
        self.assertEqual(len(promoted), 10)
        for _ in range(10):
            bd.activate_waiting(reg, max_monitored=30, per_run=10)
        self.assertEqual(sum(1 for r in reg.values() if r.status in bd.MONITORED), 30)  # hard ceiling
        self.assertEqual(bd.registry_counts(reg)["waiting"], 70)

    def test_existing_monitored_boards_use_up_the_budget_first(self) -> None:
        reg = self.reg(50, active=28, new=1)
        self.assertEqual(len(bd.activate_waiting(reg, max_monitored=30, per_run=50)), 1)
        self.assertEqual(bd.activate_waiting(reg, max_monitored=30, per_run=50), [])

    def test_best_matches_first_and_irrelevant_boards_never_activate(self) -> None:
        reg = self.reg(5)
        reg["greenhouse|ready0"].relevant_jobs = 0  # validated, but nothing for this user
        reg["greenhouse|ready1"].validation = bd.V_EMPTY
        picked = bd.activate_waiting(reg, max_monitored=2, per_run=2)
        self.assertEqual([r.board for r in picked], ["ready4", "ready3"])  # most relevant jobs first
        self.assertEqual(reg["greenhouse|ready0"].status, bd.STATUS_VALIDATED)

    def test_candidates_invalid_and_parked_boards_are_never_activated(self) -> None:
        reg = self.reg(0, candidate=3, invalid=3, deferred=3)
        self.assertEqual(bd.activate_waiting(reg, max_monitored=100, per_run=100), [])

    def test_counts_for_the_report(self) -> None:
        reg = self.reg(2, active=3, candidate=4, invalid=1, deferred=2)
        self.assertEqual(bd.registry_counts(reg), {"discovered": 12, "validated": 2, "monitored": 3, "waiting": 2, "candidates": 4, "invalid": 1, "deferred": 2, "disabled": 0})


# --------------------------------------------------------------------------- pipeline: imported boards


class ImportedBoardPipelineTests(HarnessCase):
    """An imported board must be baselined, not treated as a source of 'just posted' jobs."""

    def seed_validated(self, *boards: bd.BoardId, relevant: int = 2) -> None:
        recs = [bd.BoardRecord(b.ats, b.board, "2026-10-01T00:00:00Z", inv.OPEN_ATS_FEED, bd.STATUS_VALIDATED, validation=bd.V_VALID,
                               relevant_jobs=relevant, last_job_count=5, provenance={inv.OPEN_ATS_FEED: {"first": "2026-10-01T00:00:00Z"}}) for b in boards]  # fmt: skip
        self.w.state.save_boards(recs)

    def test_activation_baselines_existing_jobs_and_alerts_only_on_proven_fresh_ones(self) -> None:
        b = bd.BoardId(bd.GREENHOUSE, "imported")
        self.seed_validated(b)
        self.w.listings[b.key] = [
            job("imported", "1", published=ago(days=2)),  # older, known date
            job("imported", "2", published=""),  # uncertain age
            job("imported", "3", published=ago(days=40)),  # stale
            job("imported", "4", published=ago(minutes=30)),  # provably fresh by the source timestamp
        ]
        run = self.w.run()
        by = {k.split("|")[2]: s for k, s in self.w.states().items()}
        self.assertEqual({k: s.disposition for k, s in by.items()}, {"1": lg.BASELINED, "2": lg.BASELINED, "3": lg.BASELINED, "4": lg.PENDING})
        self.assertEqual([self.w.calls[self.key(k, board="imported")] for k in "1234"], [0, 0, 0, 1])  # no backfill scoring for the backlog
        self.assertEqual(len(self.w.alerts), 1)
        self.assertEqual((run.boards_activated, run.boards_monitored), (1, 1))
        rec = self.w.state.load_boards()[b.key]
        self.assertEqual((rec.status, bool(rec.baselined_at), rec.validation), (bd.STATUS_ACTIVE, True, bd.V_VALID))
        self.assertIn(inv.OPEN_ATS_FEED, rec.provenance)  # provenance survives polling

    def test_a_flood_of_validated_boards_activates_gradually_within_the_budget(self) -> None:
        ids = [bd.BoardId(bd.GREENHOUSE, f"b{i}") for i in range(12)]
        self.seed_validated(*ids)
        for b in ids:
            self.w.listings[b.key] = [job(b.board, "1", published=ago(days=5))]
        r1 = self.w.run(max_monitored_boards=8, max_new_boards_per_run=5)
        self.assertEqual((r1.boards_activated, r1.boards_monitored, r1.boards_discovered, r1.boards_validated), (5, 5, 12, 12))
        r2 = self.w.run(minutes_later=60, max_monitored_boards=8, max_new_boards_per_run=5)
        self.assertEqual((r2.boards_activated, r2.boards_monitored), (3, 8))  # stops at the ceiling
        r3 = self.w.run(minutes_later=60, max_monitored_boards=8, max_new_boards_per_run=5)
        self.assertEqual((r3.boards_activated, r3.boards_monitored, r3.boards_total), (0, 8, 8))
        self.assertEqual(len(self.w.alerts), 0)

    def test_unvalidated_candidates_and_invalid_boards_are_never_polled(self) -> None:
        polled: list[str] = []
        self.w.fetch = lambda b: polled.append(b.key) or []  # type: ignore[method-assign]
        self.w.state.save_boards([bd.BoardRecord("greenhouse", "cand", "t", "s", bd.STATUS_CANDIDATE), bd.BoardRecord("greenhouse", "bad", "t", "s", bd.STATUS_INVALID)])
        self.w.run()
        self.assertEqual(polled, [])

    def test_a_run_writes_back_only_the_rows_it_changed(self) -> None:
        self.seed_validated(bd.BoardId(bd.GREENHOUSE, "mine"))
        self.w.state.save_boards([bd.BoardRecord("greenhouse", "theirs", "t", "open-ats-feed", bd.STATUS_CANDIDATE)])
        self.w.listings["greenhouse|mine"] = [job("mine", "1", published=ago(days=3))]
        saved: list[str] = []
        real = self.w.state.save_boards
        self.w.state.save_boards = lambda recs: (lambda rs: (saved.extend(r.key for r in rs), real(rs)))(list(recs))  # type: ignore[method-assign]
        self.w.run()
        self.assertEqual(saved, ["greenhouse|mine"])  # the importer's candidate row was not rewritten

    def test_polling_never_overwrites_a_concurrent_importers_rows(self) -> None:
        """The importer adds a row while the poller is mid-run; the poller must not erase it."""
        b = bd.BoardId(bd.GREENHOUSE, "mine")
        self.seed_validated(b)
        self.w.listings[b.key] = [job("mine", "1", published=ago(days=3))]
        real_fetch = self.w.fetch

        def fetch_and_import(board: bd.BoardId) -> list[bd.ListedJob]:
            self.w.state.save_boards([bd.BoardRecord("lever", "added-meanwhile", "t", "ats-scrapers", bd.STATUS_CANDIDATE)])
            return real_fetch(board)

        self.w.fetch = fetch_and_import  # type: ignore[method-assign]
        self.w.run()
        keys = set(self.w.state.load_boards())
        self.assertEqual(keys, {"greenhouse|mine", "lever|added-meanwhile"})


# --------------------------------------------------------------------------- Sheet persistence (row-level upsert)


class FakeWs:
    def __init__(self, title: str, values: list[list[Any]] | None = None) -> None:
        self.title, self.values, self.id, self.row_count = title, values or [], 1, 1000
        self.calls: list[str] = []

    def get_all_values(self) -> list[list[str]]:
        return [[str(c) for c in r] for r in self.values]

    def row_values(self, n: int) -> list[str]:
        return [str(c) for c in self.values[n - 1]] if len(self.values) >= n else []

    def col_values(self, col: int) -> list[str]:
        self.calls.append(f"col_values:{col}")
        return [str(r[col - 1]) if len(r) >= col else "" for r in self.values]

    def append_rows(self, rows: list, **kw: Any) -> None:
        self.calls.append("append")
        self.values.extend(list(r) for r in rows)

    def batch_update(self, data: list[dict], **kw: Any) -> None:
        self.calls.append("batch_update")
        for d in data:
            row = int(d["range"][1:])
            while len(self.values) < row:
                self.values.append([])
            self.values[row - 1] = list(d["values"][0])

    def update(self, values: list, range_name: str, **kw: Any) -> None:
        self.calls.append(f"update:{range_name}")
        row = int(range_name[1:])
        while len(self.values) < row - 1 + len(values):
            self.values.append([])
        for i, v in enumerate(values):
            self.values[row - 1 + i] = list(v)

    def add_rows(self, n: int) -> None:
        self.row_count += n

    def freeze(self, **kw: Any) -> None: ...
    def hide(self) -> None: ...

    def clear(self) -> None:
        raise AssertionError("the registry must never be cleared")


class FakeSh:
    def __init__(self) -> None:
        self.tabs: dict[str, FakeWs] = {}

    def worksheets(self) -> list[FakeWs]:
        return list(self.tabs.values())

    def worksheet(self, title: str) -> FakeWs:
        return self.tabs[title]

    def add_worksheet(self, title: str, rows: int, cols: int) -> FakeWs:
        self.tabs[title] = FakeWs(title)
        return self.tabs[title]


class SheetBoardsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sh = FakeSh()
        self.state = stm.SheetState(self.sh)
        self.state.ensure()
        self.ws = self.sh.tabs[stm.BOARDS_TAB]

    def rec(self, ats: str, board: str, **kw: Any) -> bd.BoardRecord:
        return bd.BoardRecord(ats, board, "2026-10-01T00:00:00Z", "search", **kw)

    def test_round_trip_with_provenance_and_validation_fields(self) -> None:
        r = self.rec("lever", "Foo", status=bd.STATUS_VALIDATED, region="", name="Foo Inc", validation=bd.V_VALID, last_validated_at="2026-10-02T00:00:00Z", relevant_jobs=3,
                     provenance={"open-ats-feed": {"first": "2026-10-01T00:00:00Z", "state": "live"}})  # fmt: skip
        self.state.save_boards([r])
        again = self.state.load_boards()
        self.assertEqual(again[r.key], r)
        self.assertEqual(again["lever|Foo"].board, "Foo")  # casing preserved where required

    def test_updates_in_place_and_appends_without_touching_other_rows(self) -> None:
        a, b, c = self.rec("greenhouse", "a"), self.rec("greenhouse", "b"), self.rec("greenhouse", "c")
        self.state.save_boards([a, b, c])
        self.state.load_boards()
        untouched = list(self.ws.values[3])
        b.status, b.last_success_at = bd.STATUS_ACTIVE, "2026-10-14T00:00:00Z"
        self.state.save_boards([b, self.rec("greenhouse", "d")])
        keys = [r[0] for r in self.ws.values[1:]]
        self.assertEqual(keys, ["greenhouse|a", "greenhouse|b", "greenhouse|c", "greenhouse|d"])
        self.assertEqual(self.ws.values[2][3], bd.STATUS_ACTIVE)
        self.assertEqual(self.ws.values[3], untouched)

    def test_concurrently_appended_duplicate_becomes_an_update_not_a_second_row(self) -> None:
        self.state.load_boards()  # this process learned of no rows
        other = stm.SheetState(self.sh)  # another process appends the same board meanwhile
        other.save_boards([self.rec("greenhouse", "x")])
        self.state.save_boards([self.rec("greenhouse", "x", status=bd.STATUS_ACTIVE)])
        self.assertEqual(len([r for r in self.ws.values[1:] if r[0] == "greenhouse|x"]), 1)
        self.assertEqual(self.ws.values[1][3], bd.STATUS_ACTIVE)

    def test_old_registry_rows_and_header_still_load_and_are_widened(self) -> None:
        old_header = stm.BOARD_COLUMNS[:12]
        self.ws.values = [old_header, ["greenhouse|old", "greenhouse", "old", "active", "2026-09-01T00:00:00Z", "search", "2026-09-01T01:00:00Z", "", "2026-10-14T00:00:00Z", 0, 9, ""]]
        self.state.ensure()
        self.assertEqual(self.ws.values[0], stm.BOARD_COLUMNS)
        rec = self.state.load_boards()["greenhouse|old"]
        self.assertEqual((rec.status, rec.provenance, rec.validation, rec.region), ("active", {}, "", ""))

    def test_importer_write_guard_skips_a_row_the_poller_promoted_meanwhile(self) -> None:
        a, b = self.rec("greenhouse", "a", status=bd.STATUS_VALIDATED), self.rec("greenhouse", "b", status=bd.STATUS_VALIDATED)
        self.state.save_boards([a, b])
        importer = stm.SheetState(self.sh)  # the importer loaded both rows as `validated`
        importer.load_boards()
        poller = stm.SheetState(self.sh)
        promoted = poller.load_boards()["greenhouse|a"]
        promoted.status, promoted.pool = bd.STATUS_NEW, "exploration"
        poller.save_boards([promoted])
        a.relevant_jobs, b.relevant_jobs = 99, 77  # the importer's stale view of both
        skipped = importer.save_boards([a, b, self.rec("greenhouse", "c", status=bd.STATUS_CANDIDATE)], skip_if_status=inv.POLLER_OWNED)
        self.assertEqual(skipped, ["greenhouse|a"])
        rows = {r[0]: r for r in self.ws.values[1:]}
        self.assertEqual((rows["greenhouse|a"][3], str(rows["greenhouse|a"][16])), (bd.STATUS_NEW, "0"))  # the promotion survived
        self.assertEqual(str(rows["greenhouse|b"][16]), "77")  # an unpromoted row is written as usual
        self.assertIn("greenhouse|c", rows)  # a new row is appended

    def test_guard_works_without_column_reads_and_without_a_guard_everything_is_written(self) -> None:
        a = self.rec("greenhouse", "a", status=bd.STATUS_ACTIVE)
        self.state.save_boards([a])
        self.ws.col_values = None  # type: ignore[assignment]
        del self.ws.col_values  # a worksheet object offering only get_all_values (the fallback path)
        self.assertEqual(self.state.save_boards([self.rec("greenhouse", "a", status=bd.STATUS_VALIDATED)], skip_if_status=inv.POLLER_OWNED), ["greenhouse|a"])
        self.assertEqual(self.ws.values[1][3], bd.STATUS_ACTIVE)
        self.assertEqual(self.state.save_boards([self.rec("greenhouse", "a", status=bd.STATUS_VALIDATED)]), [])  # no guard requested
        self.assertEqual(self.ws.values[1][3], bd.STATUS_VALIDATED)

    def test_guard_costs_two_column_reads_not_a_full_scan(self) -> None:
        self.state.save_boards([self.rec("greenhouse", f"b{i}") for i in range(30)])
        self.ws.calls.clear()
        self.state.save_boards([self.rec("greenhouse", "b1", status=bd.STATUS_VALIDATED), self.rec("greenhouse", "new1")], skip_if_status=inv.POLLER_OWNED)
        self.assertEqual([c for c in self.ws.calls if c.startswith("col_values")], ["col_values:1", "col_values:4"])

    def test_never_clears_the_registry(self) -> None:
        self.state.save_boards([self.rec("greenhouse", f"b{i}") for i in range(1200)])  # also exercises chunking
        self.assertEqual(len(self.state.load_boards()), 1200)

    def test_inventory_metadata_round_trip(self) -> None:
        meta = {"open-ats-feed": {"Fetched_At": "t", "SHA256": "abc", "Rows": "12916", "As_Of": "2026-09-03", "Status": "ok", "Note": ""}}
        self.state.save_inventory_meta(meta)
        self.assertEqual(self.state.load_inventory_meta()["open-ats-feed"]["Rows"], "12916")


# --------------------------------------------------------------------------- CLI


class CsvWriterGuardTests(unittest.TestCase):
    def test_importer_write_guard_on_the_local_files(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            s = stm.CsvState(Path(d))
            s.ensure()
            a = bd.BoardRecord("greenhouse", "a", "t", "s", bd.STATUS_VALIDATED, relevant_jobs=1)
            b = bd.BoardRecord("greenhouse", "b", "t", "s", bd.STATUS_VALIDATED, relevant_jobs=1)
            s.save_boards([a, b])
            promoted = s.load_boards()["greenhouse|a"]
            promoted.status = bd.STATUS_ACTIVE  # the poller, meanwhile
            s.save_boards([promoted])
            a.relevant_jobs, b.relevant_jobs = 9, 8
            skipped = s.save_boards([a, b], skip_if_status=inv.POLLER_OWNED)
            self.assertEqual(skipped, ["greenhouse|a"])
            rows = s.load_boards()
            self.assertEqual((rows["greenhouse|a"].status, rows["greenhouse|a"].relevant_jobs, rows["greenhouse|b"].relevant_jobs), (bd.STATUS_ACTIVE, 1, 8))
            self.assertEqual(s.save_boards([a], skip_if_status=inv.POLLER_OWNED), ["greenhouse|a"])  # nothing to write: file untouched




class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.store = h.CsvStore(self.dir / "t.csv", self.dir / "state")
        env = mock.patch.dict(os.environ, {"GOOGLE_SHEET_ID": "", "GROQ_API_KEY": "", "SERPER_API_KEY": "", "SEARCH_API_KEY": ""})
        env.start()
        self.addCleanup(env.stop)
        for p in (mock.patch.object(h, "make_store", return_value=self.store), mock.patch.object(h, "load_resume_file", return_value="")):
            p.start()
            self.addCleanup(p.stop)

    def test_inventory_commands_need_no_groq_key_and_offline_import_uses_the_cache(self) -> None:
        cache = inv.InventoryCache(self.dir / "cache")
        inv.load_open_ats_feed(cache, get=standard_net())
        inv.load_ats_scrapers(cache, get=standard_net())
        code = h.main(["--import-inventory", "--offline", "--inventory-cache", str(self.dir / "cache")])
        self.assertEqual(code, 0)
        boards = self.store.state.load_boards()
        self.assertEqual(len(boards), 9)
        self.assertEqual(self.store.state.load_inventory_meta()[inv.OPEN_ATS_FEED]["Status"], "cached")  # offline = cached copies
        self.assertEqual(h.main(["--inventory-report"]), 0)

    def test_dry_run_writes_nothing(self) -> None:
        cache = inv.InventoryCache(self.dir / "cache")
        inv.load_open_ats_feed(cache, get=standard_net())
        h.main(["--import-inventory", "--offline", "--dry-run", "--inventory-cache", str(self.dir / "cache")])
        self.assertEqual((self.store.state.load_boards(), self.store.state.load_inventory_meta()), ({}, {}))

    def test_total_download_failure_exits_nonzero(self) -> None:
        with mock.patch.object(inv, "http_get_bytes", side_effect=inv.InventoryError("down")):
            self.assertEqual(h.main(["--import-inventory", "--inventory-cache", str(self.dir / "empty")]), 1)
        self.assertEqual(self.store.state.load_boards(), {})

    def test_rebalance_report_prints_the_plan_and_writes_nothing(self) -> None:
        import contextlib
        import io

        state = self.store.state
        state.ensure()
        ended = (NOW - timedelta(hours=2)).strftime(bd.STAMP)
        recs = [
            bd.BoardRecord("greenhouse", "est1", "t", "s", bd.STATUS_ACTIVE, baselined_at=ago(days=50), validation=bd.V_VALID, relevant_jobs=1, eligible_jobs=1,
                           pool="established", relevance_at=ago(hours=1), activity_since=ago(days=40), complete_polls=300, new_relevant_30d=0, new_relevant_7d=0),
            bd.BoardRecord("greenhouse", "trial1", "t", "s", bd.STATUS_ACTIVE, baselined_at=ago(days=8), validation=bd.V_VALID, relevant_jobs=5, eligible_jobs=5,
                           pool="exploration", trial_until=ended, relevance_at=ago(hours=1), activity_since=ago(days=8), complete_polls=90, new_relevant_30d=6, new_relevant_7d=6),
            bd.BoardRecord("lever", "legacy", "t", "s", bd.STATUS_ACTIVE, baselined_at=ago(days=50), validation=bd.V_VALID, relevant_jobs=2),
            bd.BoardRecord("smartrecruiters", "SrActive", "t", "s", bd.STATUS_ACTIVE, baselined_at=ago(days=50), validation=bd.V_VALID, relevant_jobs=2),
            bd.BoardRecord("ashby", "waiting1", "t", "s", bd.STATUS_VALIDATED, validation=bd.V_VALID, relevant_jobs=4, eligible_jobs=4, last_validated_at=ago(days=1)),
            bd.BoardRecord("ashby", "cand1", "t", "s", bd.STATUS_CANDIDATE),
        ]
        state.save_boards(recs)
        files = sorted(p for p in (self.dir / "state").glob("*.csv"))
        before = {p.name: p.read_bytes() for p in files}
        out = io.StringIO()
        with contextlib.redirect_stdout(out), mock.patch.object(fr, "utcnow", return_value=NOW):
            code = h.main(["--rebalance-report"])
        self.assertEqual(code, 0)  # no Groq key needed
        text = out.getvalue()
        self.assertIn("BOARD REBALANCE REPORT (dry run)", text)
        self.assertIn("mode: report", text)
        self.assertIn("Max_Active_Boards 500 = established 400 + exploration 100", text)
        self.assertIn("COVERAGE", text)
        self.assertIn("monitored SmartRecruiters boards parked by provider policy: 1", text)
        self.assertIn("boards monitored before pools existed that would start an exploration trial: 1", text)
        self.assertIn("ashby|waiting1", text)  # the waiting list
        self.assertIn("candidates:    due", text)
        self.assertIn("revalidations: overdue", text)
        self.assertRegex(text, r"graduate\s+greenhouse\|trial1")  # the ended trial would graduate into a free established slot
        self.assertIn("dry run: nothing was written", text)
        self.assertEqual({p.name: p.read_bytes() for p in sorted((self.dir / "state").glob("*.csv"))}, before)  # byte-identical

    def test_settings_expose_the_polling_budget(self) -> None:
        with mock.patch.dict(os.environ):
            for k in h.SETTING_DEFAULTS:
                os.environ.pop(k.upper(), None)
            s = h.Settings.from_values({"Max_Active_Boards": "120", "Max_New_Boards_Per_Run": "abc"})
        self.assertEqual((s.max_active_boards, s.max_new_boards_per_run), (120, 50))


if __name__ == "__main__":
    unittest.main()
