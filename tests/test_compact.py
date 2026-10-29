"""Compact storage (D-57): the pure Identity codec, the observation split, Identity persistence in the Sheet store and `ensure()`.

Mocked and offline (AGENTS rules 5 and 8): the Sheet store runs on the in-memory fake of `tests/fake_sheets.py`, the CSV store on
a temp directory. Whether a warning-only protection lets the service account write is a live check (plan 03-05).
"""

from __future__ import annotations

import dataclasses
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import boards as bd  # noqa: E402
import compact  # noqa: E402
import freshness as fr  # noqa: E402
import ledger as lg  # noqa: E402
import state as stm  # noqa: E402
from fake_sheets import FakeSpreadsheet  # noqa: E402

STAMP1, STAMP2 = "2026-10-29T10:00:00Z", "2026-10-29T11:00:00Z"
STEM = "greenhouse|acme"


def entries(n: int, *, width: int = 31, kind: str = "b", start: int = 0) -> list[str]:
    return [compact.encode_entry(kind, f"{i:0{width}d}") for i in range(start, start + n)]


def seen_event(key: str, disposition: str, *, source: str = "poll", pass_kind: str = "", published: str = "", freshness: str = "") -> lg.Event:
    detail = {"source": source, "title": "T", "url": "https://u"}
    if pass_kind:
        detail["pass"] = pass_kind
    return lg.Event("2026-10-29T10:00:00Z", key, lg.SEEN, freshness or (fr.BASELINE if disposition == lg.BASELINED else fr.OBSERVED_NEW), disposition, published, detail)


class IdentityCodecTests(unittest.TestCase):
    AWKWARD = ["a,b", "50%", "%2C", "%25", ",", "0012345678901234567890", "ABC-def", "a|b", "x" * 10]

    def test_escape_round_trip(self) -> None:
        for kind in "bfs":
            for pid in self.AWKWARD:
                entry = compact.encode_entry(kind, pid)
                self.assertEqual(compact.decode_entry(entry), (kind, pid), pid)
                self.assertEqual(entry[0], kind)
                self.assertNotIn(",", entry)  # a comma inside an entry would split it

    def test_percent_is_escaped_before_the_comma(self) -> None:
        self.assertEqual(compact.encode_entry("b", "50%,1"), "b50%25%2C1")

    def test_kinds_map_to_the_three_identity_dispositions(self) -> None:
        self.assertEqual(compact.KIND_OF, {lg.BASELINED: "b", lg.FILTERED: "f", lg.STALED: "s"})
        self.assertEqual(compact.DISPOSITION_OF, {"b": lg.BASELINED, "f": lg.FILTERED, "s": lg.STALED})

    def test_a_large_board_plans_five_chunks_within_the_cell_cap(self) -> None:
        rows = compact.IdentitySet().plan_additions({STEM: entries(5050)}, STAMP1)
        self.assertEqual([r.chunk for r in rows], [1, 2, 3, 4, 5])
        self.assertTrue(all(len(r.ids) <= compact.IDENTITY_CELL_CHARS for r in rows))
        self.assertEqual([r.count for r in rows], [len(r.entries()) for r in rows])
        self.assertEqual(sum(r.count for r in rows), 5050)
        self.assertEqual(len({e for r in rows for e in r.entries()}), 5050)  # each ID exactly once

    def test_the_completion_marker_is_only_on_the_highest_chunk(self) -> None:
        rows = compact.IdentitySet().plan_additions({STEM: entries(5050)}, STAMP1)
        self.assertEqual([r.baselined_at for r in rows], ["", "", "", "", STAMP1])

    def test_a_cell_of_exactly_the_cap_is_kept_and_one_more_entry_opens_a_new_chunk(self) -> None:
        full = entries(4444, width=7) + ["bXYZ"]  # 4444 * 8 + 4 characters plus 4444 commas = 40,000 exactly
        first = compact.IdentitySet().plan_additions({STEM: full}, STAMP1)
        self.assertEqual(len(first), 1)
        self.assertEqual(len(first[0].ids), compact.IDENTITY_CELL_CHARS)
        ids = compact.IdentitySet()
        ids.apply(first)
        more = ids.plan_additions({STEM: ["bQ"]}, STAMP2)
        self.assertEqual([(r.chunk, r.count, r.baselined_at) for r in more], [(2, 1, STAMP2)])  # chunk 1 is untouched
        ids.apply(more)
        self.assertEqual([(r.chunk, r.baselined_at) for r in ids.rows(STEM)], [(1, STAMP1), (2, STAMP2)])
        self.assertEqual(ids.baselined_at(STEM), STAMP2)  # the marker moved to the new highest chunk

    def test_new_ids_extend_the_highest_chunk_in_place(self) -> None:
        ids = compact.IdentitySet()
        first = ids.plan_additions({STEM: entries(3)}, STAMP1)
        ids.apply([dataclasses.replace(r, row_no=7) for r in first])  # the store knows it as row 7
        more = ids.plan_additions({STEM: entries(2, start=10)}, STAMP2)
        self.assertEqual([(r.chunk, r.count, r.baselined_at, r.row_no) for r in more], [(1, 5, STAMP2, 7)])

    def test_planning_the_same_additions_twice_adds_nothing_the_second_time(self) -> None:
        ids = compact.IdentitySet()
        plan = {STEM: entries(5050), "lever|foo": entries(3, kind="f")}
        ids.apply(ids.plan_additions(plan, STAMP1))
        self.assertEqual(ids.plan_additions(plan, STAMP2), [])
        self.assertEqual(len(ids), 5053)

    def test_duplicates_inside_one_addition_are_collapsed(self) -> None:
        rows = compact.IdentitySet().plan_additions({STEM: ["b1", "b1", "f1", "b2"]}, STAMP1)
        self.assertEqual((rows[0].count, rows[0].ids), (2, "b1,b2"))

    def test_the_kind_is_kept_per_id(self) -> None:
        ids = compact.IdentitySet()
        ids.apply(ids.plan_additions({STEM: ["b1", "f2", "s3"]}, STAMP1))
        self.assertEqual([ids.kind(f"{STEM}|{i}") for i in "123"], ["b", "f", "s"])
        self.assertIsNone(ids.kind(f"{STEM}|9"))
        self.assertEqual(ids.keys(), {f"{STEM}|1", f"{STEM}|2", f"{STEM}|3"})

    def test_a_mixed_case_lever_board_is_keyed_by_the_lowercase_stem(self) -> None:
        board = bd.BoardId(bd.LEVER, "Foo")
        self.assertEqual(board.key, "lever|Foo")  # the registry keeps the case ...
        for jid in ("AbC1", "123e4567-E89B-12d3-a456-426614174000"):
            key = bd.JobIdentity(bd.LEVER, "Foo", jid).key
            stem, pid = compact.stem_and_id(key) or ("", "")
            self.assertEqual(stem, "lever|foo")  # ... the job key and Identity do not
            self.assertEqual(f"{stem}|{pid}", key)
        ids = compact.IdentitySet()
        ids.apply(ids.plan_additions({"lever|foo": [compact.encode_entry("b", "abc1")]}, STAMP1))
        self.assertIn(bd.JobIdentity(bd.LEVER, "Foo", "AbC1").key, ids.keys())

    def test_stems_keep_region_and_the_workable_case(self) -> None:
        self.assertEqual(compact.stem_and_id("greenhouse@eu|acme|77"), ("greenhouse@eu|acme", "77"))
        key = bd.JobIdentity(bd.WORKABLE, "Acme", "ab12").key
        self.assertEqual(compact.stem_and_id(key), ("workable|acme", "AB12"))

    def test_an_id_with_a_pipe_still_rebuilds_the_exact_key(self) -> None:
        stem, pid = compact.stem_and_id("ashby|acme|a|b") or ("", "")
        self.assertEqual((stem, pid), ("ashby|acme", "a|b"))

    def test_keys_that_cannot_be_stemmed(self) -> None:
        for key in ("", "greenhouse", "greenhouse|acme", "greenhouse|acme|"):
            self.assertIsNone(compact.stem_and_id(key), key)

    def test_identity_rows_survive_a_round_trip_and_tolerate_damage(self) -> None:
        row = compact.IdentityRow(STEM, 2, STAMP1, 2, "b1,f2", 9)
        self.assertEqual(row.to_row(), [STEM, "2", STAMP1, "2", "b1,f2"])
        self.assertEqual(compact.IdentityRow.from_row(row.to_row(), 9), row)
        self.assertIsNone(compact.IdentityRow.from_row(["", "1", "", "0", ""]))
        self.assertIsNone(compact.IdentityRow.from_row([STEM, "x", "", "0", ""]))
        self.assertEqual(compact.IdentityRow.from_row([STEM, "1"]), compact.IdentityRow(STEM, 1, "", 0, "", 0))
        self.assertEqual(compact.IdentityRow.from_row([STEM, "1", "", "?", "b1,b2"]).count, 2)  # an unreadable count is recomputed

    def test_all_digit_ids_stay_text(self) -> None:
        entry = compact.encode_entry("b", "0012345678901234567890")
        self.assertFalse(entry.isdigit())
        self.assertEqual(compact.decode_entry(entry)[1], "0012345678901234567890")


class TallyTests(unittest.TestCase):
    def test_dimension_key_maps_the_source_like_the_report(self) -> None:
        ev = seen_event("greenhouse|acme|1", lg.BASELINED, source="serper", pass_kind="baseline", published="2026-10-01T10:00:00Z")
        self.assertEqual(compact.tally_dim(ev), "greenhouse|search|baseline|baseline|baseline|k")
        self.assertEqual(compact.tally_dim(seen_event("lever|foo|1", lg.FILTERED, source="")), "lever|unknown|filtered||observed_new|u")
        self.assertEqual(compact.tally_dim(seen_event("ashby@eu|x|1", lg.STALED, source="search", published="not a date", freshness=fr.STALE)), "ashby@eu|search|stale||stale|u")

    def test_a_row_round_trips(self) -> None:
        row = compact.TallyRow("run-1", STAMP1, 5, {"a|b": 3, "c|d": 2})
        self.assertEqual(row.to_row(), ["run-1", STAMP1, "5", '{"a|b":3,"c|d":2}'])
        self.assertEqual(compact.TallyRow.from_row(row.to_row()), row)

    def test_a_zero_count_row_is_a_row(self) -> None:
        self.assertEqual(compact.TallyRow("r", STAMP1, 0, {}).to_row(), ["r", STAMP1, "0", "{}"])

    def test_damaged_rows_are_tolerated(self) -> None:
        self.assertIsNone(compact.TallyRow.from_row(["r", "", "1", "{}"]))  # no run time
        self.assertIsNone(compact.TallyRow.from_row(["r", STAMP1, "1", "[1]"]))  # not an object
        self.assertIsNone(compact.TallyRow.from_row(["r", STAMP1, "1", "{not json"]))
        row = compact.TallyRow.from_row(["r", STAMP1, "?", json.dumps({"a": 2, "b": "x", "c": True, "d": "4"})])
        assert row is not None
        self.assertEqual((row.counts, row.total), ({"a": 2, "d": 4}, 6))  # non-integer values are ignored; an unreadable total is recomputed


class SplitTests(unittest.TestCase):
    def events(self) -> list[lg.Event]:
        return [
            seen_event("greenhouse|acme|1", lg.BASELINED, pass_kind="baseline"),
            seen_event("greenhouse|acme|2", lg.FILTERED),
            seen_event("greenhouse|acme|3", lg.STALED, freshness=fr.STALE),
            seen_event("greenhouse|acme|4", lg.PENDING, freshness=fr.VERIFIED_FRESH),
            lg.Event("t", "greenhouse|acme|4", lg.EVALUATED, detail={"status": "To Apply"}),
            seen_event("weird", lg.BASELINED),  # unkeyable
        ]

    def test_identity_class_only_for_the_three_dispositions_of_seen_events(self) -> None:
        evs = self.events()
        self.assertEqual([compact.identity_class(e) for e in evs], [lg.BASELINED, lg.FILTERED, lg.STALED, None, None, lg.BASELINED])

    def test_dual_mode_keeps_every_event_and_still_collects_identity_and_counts(self) -> None:
        split = compact.split_observations(self.events(), compact.MODE_DUAL)
        self.assertEqual(len(split.events), 6)
        self.assertEqual(split.identity, {"greenhouse|acme": ["b1", "f2", "s3"]})
        self.assertEqual(sum(split.tally.values()), 4)  # the unkeyable row is counted too

    def test_compact_mode_drops_only_keyable_baseline_rows(self) -> None:
        split = compact.split_observations(self.events(), compact.MODE_COMPACT)
        self.assertEqual([(e.key, e.event) for e in split.events],
                         [("greenhouse|acme|2", lg.SEEN), ("greenhouse|acme|3", lg.SEEN), ("greenhouse|acme|4", lg.SEEN), ("greenhouse|acme|4", lg.EVALUATED), ("weird", lg.SEEN)])
        self.assertEqual(split.identity, {"greenhouse|acme": ["b1", "f2", "s3"]})
        self.assertEqual(sum(split.tally.values()), 4)

    def test_an_entry_too_long_for_a_cell_stays_in_events(self) -> None:
        long_key = "greenhouse|acme|" + "9" * (compact.IDENTITY_CELL_CHARS + 1)
        split = compact.split_observations([seen_event(long_key, lg.BASELINED)], compact.MODE_COMPACT)
        self.assertEqual((len(split.events), split.identity), (1, {}))

    def test_nothing_to_split_is_an_empty_split(self) -> None:
        split = compact.split_observations([], compact.MODE_COMPACT)
        self.assertEqual((split.events, split.identity, split.tally), ([], {}, {}))

    def test_the_tally_counts_by_dimension(self) -> None:
        evs = [seen_event(f"greenhouse|acme|{i}", lg.BASELINED, pass_kind="baseline") for i in range(3)] + [seen_event("lever|foo|1", lg.FILTERED)]
        split = compact.split_observations(evs, compact.MODE_DUAL)
        self.assertEqual(split.tally, {"greenhouse|poll|baseline|baseline|baseline|u": 3, "lever|poll|filtered||observed_new|u": 1})


class ModeTests(unittest.TestCase):
    def test_effective_mode(self) -> None:
        compact_json = json.dumps({"mode": "compact"})
        cases = [
            (None, True, "dual"), ("", True, "dual"), ("not json", True, "dual"), ("[1]", True, "dual"), ('{"mode":"dual"}', True, "dual"),
            (compact_json, True, "compact"), (compact_json, False, "dual"),  # compact needs Events_Legacy: otherwise the safe direction
            ('{"mode":"restored"}', False, "restored"), ('{"mode":"bogus"}', True, "dual"),
        ]
        for raw, legacy, want in cases:
            self.assertEqual(compact.effective_mode(raw, legacy_present=legacy), want, (raw, legacy))


class SheetIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sh = FakeSpreadsheet()
        self.state = stm.SheetState(self.sh)
        self.state.ensure()
        self.ws = self.sh.worksheet(stm.IDENTITY_TAB)

    def reload(self) -> compact.Ledger:
        return stm.SheetState(self.sh).load_ledger()

    def test_a_large_board_is_written_and_read_back_identically(self) -> None:
        self.state.load_ledger()
        self.assertEqual(self.state.write_identity({STEM: entries(5050)}, STAMP1), 5)
        data = self.ws.values[1:]
        self.assertEqual([r[1] for r in data], ["1", "2", "3", "4", "5"])
        self.assertTrue(all(len(r[4]) <= 40_000 and int(r[3]) == len(r[4].split(",")) for r in data))
        self.assertEqual([r[2] for r in data], ["", "", "", "", STAMP1])
        loaded = self.reload().identity
        self.assertEqual(loaded.keys(), {f"{STEM}|{i:031d}" for i in range(5050)})
        self.assertEqual(loaded.baselined_at(STEM), STAMP1)

    def test_a_request_never_carries_more_than_the_character_budget(self) -> None:
        self.state.load_ledger()
        plan = {f"greenhouse|board{n:02d}": entries(5050, start=n * 10_000) for n in range(15)}  # about 2.5 million characters
        self.state.write_identity(plan, STAMP1)  # the fake rejects a request over 2,000,000 characters: no error means the budget held
        self.assertGreater(len(self.ws.request_chars), 2)
        self.assertLessEqual(max(self.ws.request_chars), compact.IDENTITY_REQUEST_CHARS)
        self.assertEqual(len(self.reload().identity), 15 * 5050)

    def test_a_stem_is_split_across_requests_only_when_it_alone_exceeds_the_budget(self) -> None:
        self.state.load_ledger()
        with mock.patch.object(compact, "IDENTITY_REQUEST_CHARS", 250_000):
            plan = {f"greenhouse|b{n}": entries(3030, start=n * 10_000) for n in range(3)}  # about 100,000 characters each: chunks of 40k, 40k, 20k
            self.state.write_identity(plan, STAMP1)
        self.assertEqual([c for c in self.ws.calls if c[0] == "append"][1:], [("append", 6), ("append", 3)])  # (the first append is the header) two stems together, then the third
        with mock.patch.object(compact, "IDENTITY_REQUEST_CHARS", 45_000):
            self.state.write_identity({"greenhouse|big": entries(5050)}, STAMP2)
        self.assertEqual([c for c in self.ws.calls if c[0] == "append"][3:], [("append", 1)] * 5)  # one stem over the budget: a request per chunk

    def test_existing_chunks_are_updated_in_place_and_new_chunks_appended(self) -> None:
        self.state.load_ledger()
        self.state.write_identity({STEM: entries(3)}, STAMP1)
        self.assertEqual(len(self.ws.values), 2)
        self.state.write_identity({STEM: entries(2, start=100)}, STAMP2)
        self.assertEqual(len(self.ws.values), 2)  # no new row
        self.assertIn(("batch_update", ["A2"]), self.ws.calls)  # the single-cell anchor of the existing row
        self.assertEqual((self.ws.values[1][2], self.ws.values[1][3]), (STAMP2, "5"))
        self.state.write_identity({STEM: ["b" + "7" * 39_990]}, STAMP2)  # no longer fits: a second chunk
        self.assertEqual([r[1] for r in self.ws.values[1:]], ["1", "2"])
        self.state.write_identity({STEM: ["bq"]}, "2026-10-29T12:00:00Z")  # extends chunk 2, whose row number was learned from the sheet
        self.assertEqual(len(self.ws.values), 3)
        self.assertEqual(self.ws.values[2][3], "2")
        self.assertEqual(self.reload().identity.keys(), {f"{STEM}|{i:031d}" for i in (0, 1, 2, 100, 101)} | {f"{STEM}|{'7' * 39_990}", f"{STEM}|q"})

    def test_a_failed_request_leaves_the_cache_equal_to_what_the_sheet_holds(self) -> None:
        self.state.load_ledger()
        with mock.patch.object(compact, "IDENTITY_REQUEST_CHARS", 45_000):
            self.sh.fail_on_write_to(stm.IDENTITY_TAB, 3)
            with self.assertRaises(RuntimeError):
                self.state.write_identity({STEM: entries(5050)}, STAMP1)
        held = self.reload().identity
        self.assertEqual([r.chunk for r in held.rows(STEM)], [1, 2])
        self.assertEqual(held.baselined_at(STEM), "")  # no marker: the set is incomplete
        self.assertEqual(self.state._identity.keys(), held.keys())  # type: ignore[union-attr]
        # the redo re-derives the rest and is idempotent for what is already there
        self.state.write_identity({STEM: entries(5050)}, STAMP2)
        done = self.reload().identity
        self.assertEqual(len(done), 5050)
        self.assertEqual(done.baselined_at(STEM), STAMP2)

    def test_the_fake_rejects_a_cell_over_fifty_thousand_characters(self) -> None:
        with self.assertRaises(ValueError):
            self.ws.append_rows([[STEM, "1", "", "1", "x" * 50_001]])
        self.ws.append_rows([[STEM, "1", "", "1", "x" * 50_000]])  # the limit itself is allowed

    def test_tally_rows_are_appended_in_chunks_of_the_append_size(self) -> None:
        rows = [compact.TallyRow(f"r{i}", STAMP1, 1, {"a": 1}) for i in range(4500)]
        self.state.append_tally(rows)
        tally = self.sh.worksheet(stm.TALLY_TAB)
        self.assertEqual([c for c in tally.calls if c[0] == "append"][1:], [("append", 2000), ("append", 2000), ("append", 500)])
        self.assertEqual(len(self.reload().tally), 4500)

    def test_event_row_numbers_count_unreadable_rows(self) -> None:
        events = self.sh.worksheet(stm.EVENTS_TAB)
        good = lg.Event(STAMP1, f"{STEM}|1", lg.SEEN, fr.BASELINE, lg.BASELINED).to_row()
        events.append_rows([good, ["", "", ""], good])
        ledger = self.reload()
        self.assertEqual(ledger.event_rows, [2, 4])
        self.assertEqual(len(ledger.events), 2)


class EnsureTests(unittest.TestCase):
    def test_ensure_creates_the_two_tabs_hidden_and_frozen(self) -> None:
        sh = FakeSpreadsheet()
        stm.SheetState(sh).ensure()
        for title, columns in ((stm.IDENTITY_TAB, stm.IDENTITY_COLUMNS), (stm.TALLY_TAB, stm.TALLY_COLUMNS)):
            ws = sh.worksheet(title)
            self.assertEqual((ws.values[0], ws.hidden, ws.frozen_rows), (columns, True, 1), title)
        self.assertEqual(len(stm.IDENTITY_COLUMNS), 5)
        self.assertEqual(len(stm.TALLY_COLUMNS), 4)

    def test_ensure_protects_identity_with_a_warning_only_whole_sheet_range(self) -> None:
        sh = FakeSpreadsheet()
        state = stm.SheetState(sh)
        state.ensure()
        identity = sh.worksheet(stm.IDENTITY_TAB)
        ranges = [pr for prs in sh.protected.values() for pr in prs]
        self.assertEqual(len(ranges), 1)  # one protection in the whole spreadsheet
        self.assertEqual(sh.protected[identity.id][0]["range"], {"sheetId": identity.id})  # the whole sheet: no row or column bounds
        self.assertIs(sh.protected[identity.id][0]["warningOnly"], True)
        state.ensure()  # the tab exists now: no second protection
        self.assertEqual(sum(len(v) for v in sh.protected.values()), 1)

    def test_a_client_without_batch_update_only_logs_a_warning(self) -> None:
        sh = FakeSpreadsheet()
        sh.batch_update = None  # type: ignore[assignment]
        with self.assertLogs("hunter", level="WARNING"):
            stm.SheetState(sh).ensure()
        self.assertIn(stm.IDENTITY_TAB, sh.sheets)

    def test_tab_exists_follows_the_sheet(self) -> None:
        sh = FakeSpreadsheet()
        state = stm.SheetState(sh)
        state.ensure()
        self.assertTrue(state.tab_exists(stm.IDENTITY_TAB))
        self.assertFalse(state.tab_exists(stm.EVENTS_LEGACY_TAB))
        sh.add_worksheet(stm.EVENTS_LEGACY_TAB, 10, 7)
        state.ensure()
        self.assertTrue(state.tab_exists(stm.EVENTS_LEGACY_TAB))

    def refuse_sheet(self, other: str) -> None:
        sh = FakeSpreadsheet([stm.BOARDS_TAB, other])
        with self.assertRaises(RuntimeError) as cm:
            stm.SheetState(sh).ensure()
        self.assertIn("D-57", str(cm.exception))
        self.assertEqual(set(sh.sheets), {stm.BOARDS_TAB, other})  # nothing was created

    def refuse_csv(self, other: str) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / f"{other.lower()}.csv").write_text("Time,Job_Key\n", encoding="utf-8")
            with self.assertRaises(RuntimeError) as cm:
                stm.CsvState(Path(tmp)).ensure()
            self.assertIn("D-57", str(cm.exception))
            self.assertEqual(os.listdir(tmp), [f"{other.lower()}.csv"])  # nothing was created

    def test_ensure_refuses_to_recreate_events_when_events_legacy_exists(self) -> None:
        self.refuse_sheet(stm.EVENTS_LEGACY_TAB)
        self.refuse_csv(stm.EVENTS_LEGACY_TAB)

    def test_ensure_refuses_to_recreate_events_when_events_new_exists(self) -> None:
        self.refuse_sheet(stm.EVENTS_NEW_TAB)
        self.refuse_csv(stm.EVENTS_NEW_TAB)

    def test_ensure_with_events_present_is_unchanged(self) -> None:
        sh = FakeSpreadsheet()
        stm.SheetState(sh).ensure()
        sh.add_worksheet(stm.EVENTS_LEGACY_TAB, 10, 7)
        stm.SheetState(sh).ensure()  # Events exists: Events_Legacy beside it is fine
        with tempfile.TemporaryDirectory() as tmp:
            state = stm.CsvState(Path(tmp))
            state.ensure()
            (Path(tmp) / "events_legacy.csv").write_text("x\n", encoding="utf-8")
            state.ensure()
            self.assertTrue((Path(tmp) / "identity.csv").exists() and (Path(tmp) / "tally.csv").exists())


class CsvLedgerTests(unittest.TestCase):
    def test_identity_survives_a_reload_and_event_rows_count_unreadable_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = stm.CsvState(Path(tmp))
            state.ensure()
            good = lg.Event(STAMP1, f"{STEM}|1", lg.SEEN, fr.BASELINE, lg.BASELINED)
            state.append_events([good])
            with (Path(tmp) / "events.csv").open("a", encoding="utf-8") as fh:
                fh.write(",,\n")
            state.append_events([good])
            state.load_ledger()
            self.assertEqual(state.write_identity({STEM: entries(5050)}, STAMP1), 5)
            self.assertEqual(state.write_identity({STEM: entries(5050)}, STAMP2), 0)  # idempotent
            ledger = stm.CsvState(Path(tmp)).load_ledger()
            self.assertEqual(ledger.event_rows, [2, 4])
            self.assertEqual(len(ledger.identity), 5050)
            self.assertEqual(ledger.identity.baselined_at(STEM), STAMP1)


if __name__ == "__main__":
    unittest.main()
