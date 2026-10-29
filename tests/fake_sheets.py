"""A shared in-memory stand-in for a Google spreadsheet (MOCKED: nothing here touches the Sheets API).

It models what the compact-storage code depends on and what the older per-file fakes leave out:
spreadsheet-level `batch_update` requests (`updateSheetProperties`, `deleteDimension`, `addProtectedRange`), grid sizes in the
metadata, the real limits (a cell over 50,000 characters and a request over 2,000,000 characters are rejected) and fault
injection (`fail_on_write`, `fail_on_write_to`). Like the fake in `tests/test_hunter.py`, a worksheet raises on the destructive
calls the production code must never make (`clear`, `delete_rows`, `batch_clear`, `update_cell`).
"""

from __future__ import annotations

import copy
import json
import re
from typing import Any

CELL_CAP = 50_000  # Google Sheets: characters in one cell
CALL_CAP = 2_000_000  # Google recommends requests of at most 2 MB; the fake rejects what is clearly beyond it

_A1 = re.compile(r"^([A-Z]+)(\d+)")


class WorksheetNotFound(KeyError):
    """What gspread raises for a missing tab."""


def _col_index(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n - 1


def _cell(value: Any) -> str:
    return "" if value is None else str(value)


def _chars(rows: list[list[Any]]) -> int:
    return sum(len(_cell(c)) for r in rows for c in r)


class FakeWorksheet:
    def __init__(self, sh: "FakeSpreadsheet", sheet_id: int, title: str, rows: int, cols: int) -> None:
        self.sh, self.id, self.title = sh, sheet_id, title
        self.values: list[list[str]] = []
        self.row_count, self.col_count = rows, cols
        self.hidden = False
        self.frozen_rows = 0
        self.writes = 0
        self.calls: list[tuple[str, Any]] = []  # ("append", n rows) / ("batch_update", ["A2", ...]) / ("update", "A2")
        self.request_chars: list[int] = []  # cell characters carried by each write call

    # -- reads
    def get_all_values(self) -> list[list[str]]:
        self.sh.reads += 1
        return [list(r) for r in self.values]

    def col_values(self, col: int) -> list[str]:
        self.sh.reads += 1
        return [r[col - 1] if len(r) >= col else "" for r in self.values]

    def row_values(self, n: int) -> list[str]:
        self.sh.reads += 1
        return list(self.values[n - 1]) if len(self.values) >= n else []

    # -- writes
    def _write(self, rows: list[list[Any]]) -> None:
        """Every write call: counts it, injects the fault, enforces the limits. Nothing is applied by the caller before this returns."""
        biggest = max((len(_cell(c)) for r in rows for c in r), default=0)
        self.sh._begin_write(self, _chars(rows), biggest)
        self.writes += 1
        self.request_chars.append(_chars(rows))

    def _put(self, row: int, col: int, values: list[Any]) -> None:
        while len(self.values) < row:
            self.values.append([])
        cur = self.values[row - 1]
        while len(cur) < col + len(values):
            cur.append("")
        for i, v in enumerate(values):
            cur[col + i] = _cell(v)
        self.row_count = max(self.row_count, row)
        self.col_count = max(self.col_count, col + len(values))

    def append_rows(self, rows: list[list[Any]], value_input_option: str | None = None, table_range: str | None = None, **kw: Any) -> None:
        self._write(rows)
        self.calls.append(("append", len(rows)))
        for r in rows:
            self.values.append([_cell(c) for c in r])
        self.row_count = max(self.row_count, len(self.values))
        self.col_count = max([self.col_count] + [len(r) for r in rows])

    def update(self, values: list[list[Any]] | None = None, range_name: str | None = None, value_input_option: str | None = None, **kw: Any) -> None:
        rows = values or []
        self._write(rows)
        m = _A1.match(range_name or "A1")
        assert m, range_name
        self.calls.append(("update", range_name))
        for i, r in enumerate(rows):
            self._put(int(m.group(2)) + i, _col_index(m.group(1)), list(r))

    def batch_update(self, data: list[dict[str, Any]], value_input_option: str | None = None, **kw: Any) -> None:
        self._write([r for d in data for r in d["values"]])
        self.calls.append(("batch_update", [d["range"] for d in data]))
        for d in data:
            m = _A1.match(d["range"])
            assert m, d["range"]
            for i, r in enumerate(d["values"]):
                self._put(int(m.group(2)) + i, _col_index(m.group(1)), list(r))

    # -- cosmetic and grid calls
    def freeze(self, rows: int | None = None, cols: int | None = None) -> None:
        self.frozen_rows = rows or 0

    def hide(self) -> None:
        self.hidden = True

    def add_cols(self, n: int) -> None:
        self.col_count += n

    def add_rows(self, n: int) -> None:
        self.row_count += n

    def __getattr__(self, name: str) -> Any:
        if name in {"clear", "delete_rows", "update_cell", "batch_clear"}:
            raise AssertionError(f"unexpected destructive call {name}()")
        raise AttributeError(name)


class FakeSpreadsheet:
    def __init__(self, titles: list[str] | None = None) -> None:
        self.sheets: dict[str, FakeWorksheet] = {}
        self.protected: dict[int, list[dict[str, Any]]] = {}  # sheet id -> protected ranges
        self.requests: list[dict[str, Any]] = []  # every spreadsheet-level batchUpdate request applied, in order
        self.reads = 0
        self.writes = 0  # write calls of every kind
        self.fail_on_write: int | None = None  # raise on the Nth write call (worksheet append_rows/update/batch_update, spreadsheet batch_update)
        self._fail_on: tuple[str, int] | None = None
        self._next_id = 1
        for title in titles or []:
            self.add_worksheet(title, 1000, 1)

    # -- fault injection
    def fail_on_write_to(self, title: str, nth: int) -> None:
        """Raise on the `nth` write call (counted from now) to the worksheet `title`."""
        self._fail_on = (title, self.sheets[title].writes + nth)

    def _begin_write(self, ws: FakeWorksheet | None, chars: int, biggest_cell: int) -> None:
        self.writes += 1
        if self.fail_on_write is not None and self.writes == self.fail_on_write:
            raise RuntimeError("injected write failure")
        if ws is not None and self._fail_on and self._fail_on[0] == ws.title and ws.writes + 1 == self._fail_on[1]:
            self._fail_on = None
            raise RuntimeError("injected write failure")
        if biggest_cell > CELL_CAP:
            raise ValueError(f"a cell of {biggest_cell} characters exceeds the {CELL_CAP}-character limit")
        if chars > CALL_CAP:
            raise ValueError(f"a request of {chars} characters exceeds {CALL_CAP}")

    # -- spreadsheet
    def worksheets(self) -> list[FakeWorksheet]:
        self.reads += 1
        return list(self.sheets.values())

    def worksheet(self, title: str) -> FakeWorksheet:
        if title not in self.sheets:
            raise WorksheetNotFound(title)
        return self.sheets[title]

    def add_worksheet(self, title: str, rows: int, cols: int) -> FakeWorksheet:
        ws = FakeWorksheet(self, self._next_id, title, rows, cols)
        self._next_id += 1
        self.sheets[title] = ws
        return ws

    def del_worksheet(self, ws: FakeWorksheet) -> None:
        del self.sheets[ws.title]
        self.protected.pop(ws.id, None)

    def _by_id(self, sheet_id: int) -> FakeWorksheet:
        for ws in self.sheets.values():
            if ws.id == sheet_id:
                return ws
        raise ValueError(f"no sheet with id {sheet_id}")

    def batch_update(self, body: dict[str, Any]) -> dict[str, Any]:
        """Apply the requests in order, all or nothing (spreadsheets.batchUpdate is atomic)."""
        self._begin_write(None, len(json.dumps(body)), 0)
        snapshot = {w.id: (w, w.title, copy.deepcopy(w.values), w.row_count, w.hidden) for w in self.sheets.values()}
        protected = copy.deepcopy(self.protected)
        try:
            for req in body["requests"]:
                self._apply(req)
                self.requests.append(req)
        except Exception:
            self.protected = protected
            self.sheets = {}
            for ws, title, values, row_count, hidden in snapshot.values():
                ws.title, ws.values, ws.row_count, ws.hidden = title, values, row_count, hidden
                self.sheets[title] = ws
            raise
        return {"replies": [{} for _ in body["requests"]]}

    def _apply(self, req: dict[str, Any]) -> None:
        if "updateSheetProperties" in req:
            body = req["updateSheetProperties"]
            props, fields = body["properties"], str(body.get("fields", ""))
            ws = self._by_id(props["sheetId"])
            if "title" in fields:
                del self.sheets[ws.title]
                ws.title = props["title"]
                self.sheets[ws.title] = ws
            if "hidden" in fields:
                ws.hidden = bool(props.get("hidden"))
        elif "deleteDimension" in req:
            rng = req["deleteDimension"]["range"]
            assert rng["dimension"] == "ROWS", rng
            ws = self._by_id(rng["sheetId"])
            del ws.values[rng["startIndex"] : rng["endIndex"]]
            ws.row_count = max(0, ws.row_count - (rng["endIndex"] - rng["startIndex"]))
        elif "addProtectedRange" in req:
            pr = dict(req["addProtectedRange"]["protectedRange"])
            ws = self._by_id(pr["range"]["sheetId"])
            pr.setdefault("protectedRangeId", 1000 + sum(len(v) for v in self.protected.values()))
            self.protected.setdefault(ws.id, []).append(pr)
        else:
            raise ValueError(f"unsupported request {sorted(req)}")

    def fetch_sheet_metadata(self) -> dict[str, Any]:
        self.reads += 1
        return {"sheets": [
            {"properties": {"sheetId": w.id, "title": w.title, "hidden": w.hidden,
                            "gridProperties": {"rowCount": w.row_count, "columnCount": w.col_count}},
             "protectedRanges": list(self.protected.get(w.id, []))}
            for w in self.sheets.values()
        ]}
