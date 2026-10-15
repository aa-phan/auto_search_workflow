"""Board inventories: seed the registry from public company lists, validate, and report.

Sources (both MIT-licensed, see NOTICE.md). They are used only as *lists of board identifiers*;
every posting still comes from the ATS's own endpoint:
  open-ats-feed  github.com/veresk06/open-ats-feed   actor/data/companies.json
  ats-scrapers   github.com/kalil0321/ats-scrapers   ats-companies/{ats}.csv

Rules (SPEC.md "Board registry"): imports are additive and idempotent; an upstream
disappearance never deactivates a board; validation outcomes are valid / valid-empty /
invalid / transient (a transient failure is never read as a closed board); validated boards
only enter monitoring through the polling budget (boards.activate_waiting).
"""

from __future__ import annotations

import collections
import csv
import hashlib
import io
import json
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable

import requests

import boards as bd
import eligibility
from boards import (
    ASHBY, GREENHOUSE, LEVER, SMARTRECRUITERS, WORKABLE, BoardGone, BoardError, BoardId, BoardRecord, Candidate,
    STATUS_CANDIDATE, STATUS_DEFERRED, STATUS_DISABLED, STATUS_INVALID, STATUS_VALIDATED, V_DEFERRED, V_EMPTY, V_INVALID,
    V_TRANSIENT, V_VALID, merge_candidates, STAMP,
)  # fmt: skip

log = logging.getLogger("hunter")

OPEN_ATS_FEED = "open-ats-feed"
ATS_SCRAPERS = "ats-scrapers"
SOURCES = (OPEN_ATS_FEED, ATS_SCRAPERS)

OPEN_ATS_FEED_URL = "https://raw.githubusercontent.com/veresk06/open-ats-feed/main/actor/data/companies.json"
ATS_SCRAPERS_LIST_URL = "https://api.github.com/repos/kalil0321/ats-scrapers/contents/ats-companies?ref=main"
ATS_SCRAPERS_RAW = "https://raw.githubusercontent.com/kalil0321/ats-scrapers/main/ats-companies/{name}.csv"
SUPPORTED_ATS = set(bd.ATS_LIST)

# Rows only the hourly poller may write (D-28). The importer's writes skip a row whose CURRENT
# status is one of these (best effort, D-31: not an atomic compare-and-set; the writer lease and the
# shared concurrency group do the real serialization) and merge their provenance instead.
POLLER_OWNED = frozenset({bd.STATUS_NEW, bd.STATUS_ACTIVE, bd.STATUS_DISABLED})

HTTP_TIMEOUT = 40
MAX_DOWNLOAD_BYTES = 40_000_000
USER_AGENT = "job-hunter-inventory/1.0 (+https://github.com/; polite weekly refresh)"
SHRINK_GUARD = 0.5  # a download with under half the cached rows is treated as a bad download
# Identifiers go into API URLs: letters, digits and a few punctuation marks seen in real boards
# (e.g. Lever "1840&Company", "qvest.us"). Anything else (spaces, slashes, %, ?) is rejected.
IDENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._~&+-]{0,98}$")


# --------------------------------------------------------------------------- download + cache


class InventoryError(Exception):
    """A source could not be fetched or its schema changed."""


class InventoryCache:
    """Last-known-good copy of each downloaded file (raw bytes, saved only after it validated)."""

    def __init__(self, directory: Path | None) -> None:
        self.dir = directory

    def path(self, source: str, name: str) -> Path | None:
        return (self.dir / source / name) if self.dir else None

    def load(self, source: str, name: str) -> bytes | None:
        p = self.path(source, name)
        return p.read_bytes() if p and p.exists() else None

    def names(self, source: str) -> list[str]:
        d = self.dir / source if self.dir else None
        return sorted(p.stem for p in d.glob("*.csv")) if d and d.exists() else []

    def save(self, source: str, name: str, data: bytes) -> None:
        p = self.path(source, name)
        if p:
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(p.suffix + ".tmp")
            tmp.write_bytes(data)
            tmp.replace(p)


def http_get_bytes(url: str, *, retries: int = 3, sleep: Callable[[float], None] = time.sleep) -> bytes:
    """GET with timeout, size cap and exponential backoff on transient failures."""
    last: Exception | None = None
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=HTTP_TIMEOUT)
            if resp.status_code >= 400:
                raise InventoryError(f"HTTP {resp.status_code}")  # 4xx (except 429) is not retried below
            if len(resp.content) > MAX_DOWNLOAD_BYTES:
                raise InventoryError("download larger than the safety cap")
            return resp.content
        except (requests.RequestException, InventoryError) as exc:
            last = exc
            if isinstance(exc, InventoryError) and "HTTP 4" in str(exc) and "429" not in str(exc):
                break
            if attempt < retries - 1:
                sleep(2 * 2**attempt)
    raise InventoryError(f"{url}: {last}")


# --------------------------------------------------------------------------- parsing


@dataclass
class SourceReport:
    source: str
    status: str = "ok"  # ok | cached | partial | failed
    note: str = ""
    sha256: str = ""
    as_of: str = ""
    rows_total: int = 0  # every row for every provider in the source
    rows_supported: int = 0  # rows for providers we have adapters for
    rows_rejected: int = 0  # supported-provider rows with an unusable identifier
    unique_boards: int = 0  # after normalization / within-source dedupe
    duplicates: int = 0
    per_ats: dict[str, int] = field(default_factory=dict)  # unique supported boards by ATS
    unsupported: dict[str, int] = field(default_factory=dict)  # provider -> rows (not imported)
    from_cache_files: list[str] = field(default_factory=list)


def _clean_ident(ident: str) -> str | None:
    ident = (ident or "").strip()
    return ident if IDENT_RE.match(ident) else None


def parse_open_ats_feed(raw: bytes) -> tuple[list[Candidate], SourceReport]:
    """actor/data/companies.json -> candidates for providers we support."""
    try:
        d = json.loads(raw)
        providers = d["providers"]
        assert isinstance(providers, dict) and providers
    except Exception as exc:
        raise InventoryError(f"open-ats-feed schema changed ({type(exc).__name__}: {exc})") from exc
    rep = SourceReport(OPEN_ATS_FEED, as_of=str(d.get("as_of", "")), sha256=hashlib.sha256(raw).hexdigest())
    cands: list[Candidate] = []
    for prov, body in providers.items():
        if not isinstance(body, dict) or not isinstance(body.get("live"), list) or not isinstance(body.get("empty"), list):
            raise InventoryError(f"open-ats-feed schema changed: provider {prov!r} lacks live/empty lists")
        entries = [(t[0], "live") for t in body.get("live", []) if isinstance(t, list) and t] + [(t, "empty") for t in body.get("empty", []) if isinstance(t, str)]
        rep.rows_total += len(entries)
        if prov not in SUPPORTED_ATS:
            rep.unsupported[prov] = len(entries)
            continue
        for ident, state in entries:
            rep.rows_supported += 1
            clean = _clean_ident(str(ident))
            if clean is None:
                rep.rows_rejected += 1
                continue
            cands.append(Candidate(BoardId(prov, clean), OPEN_ATS_FEED, info={"state": state}))
    return _dedupe(cands, rep)


def parse_ats_scrapers_csv(ats: str, raw: bytes) -> tuple[list[Candidate], int, int]:
    """One ats-companies/{ats}.csv -> (candidates, rows, rejected). Handles the documented
    legacy two-column shape (`name,url` where url is the bare slug)."""
    try:
        text = raw.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        header = [h.strip() for h in (reader.fieldnames or [])]
        if not header or not ({"slug"} <= set(header) or {"name", "url"} <= set(header)):
            raise InventoryError(f"ats-scrapers {ats}.csv schema changed: header {header}")
        rows = list(reader)
    except InventoryError:
        raise
    except Exception as exc:
        raise InventoryError(f"ats-scrapers {ats}.csv unreadable: {exc}") from exc
    cands, rejected = [], 0
    for r in rows:
        ident = (r.get("slug") or "").strip()
        if not ident:  # legacy shape: the url column holds the bare identifier
            u = (r.get("url") or "").strip()
            ident = u if u and "/" not in u and "." not in u.split(":")[0] else (bd.parse_board_url(u).board if bd.parse_board_url(u) else "")
        clean = _clean_ident(ident)
        if clean is None:
            rejected += 1
            continue
        cands.append(Candidate(BoardId(ats, clean), ATS_SCRAPERS, name=(r.get("name") or "").strip()))
    return cands, len(rows), rejected


def _dedupe(cands: list[Candidate], rep: SourceReport) -> tuple[list[Candidate], SourceReport]:
    seen: dict[str, Candidate] = {}
    for c in cands:
        seen.setdefault(c.board.key, c)
    rep.duplicates = len(cands) - len(seen)
    rep.unique_boards = len(seen)
    rep.per_ats = dict(collections.Counter(c.board.ats for c in seen.values()))
    return list(seen.values()), rep


def _sha(parts: Iterable[bytes]) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p)
    return h.hexdigest()


def load_open_ats_feed(cache: InventoryCache, *, get: Callable[[str], bytes] = http_get_bytes) -> tuple[list[Candidate], SourceReport]:
    name = "companies.json"
    cached = cache.load(OPEN_ATS_FEED, name)
    try:
        raw = get(OPEN_ATS_FEED_URL)
        cands, rep = parse_open_ats_feed(raw)
        if cached:  # shrink guard: a truncated or emptied upstream file must not replace a good copy
            try:
                old = parse_open_ats_feed(cached)[1].rows_supported
            except InventoryError:
                old = 0
            if old and rep.rows_supported < SHRINK_GUARD * old:
                raise InventoryError(f"row count fell {old} -> {rep.rows_supported}; treating the download as bad")
        cache.save(OPEN_ATS_FEED, name, raw)
        return cands, rep
    except InventoryError as exc:
        if cached is None:
            rep = SourceReport(OPEN_ATS_FEED, status="failed", note=str(exc))
            return [], rep
        cands, rep = parse_open_ats_feed(cached)
        rep.status, rep.note, rep.from_cache_files = "cached", f"download rejected, using last-known-good copy: {exc}", [name]
        return cands, rep


def load_ats_scrapers(cache: InventoryCache, *, get: Callable[[str], bytes] = http_get_bytes) -> tuple[list[Candidate], SourceReport]:
    rep = SourceReport(ATS_SCRAPERS)
    try:  # enumerate provider files so unsupported ones can be reported by name
        listing = json.loads(get(ATS_SCRAPERS_LIST_URL))
        files = sorted(f["name"][:-4] for f in listing if isinstance(f, dict) and str(f.get("name", "")).endswith(".csv"))
        if not files:
            raise InventoryError("empty file listing")
    except Exception as exc:  # fall back to the files we can use
        cached_names = cache.names(ATS_SCRAPERS)
        files = sorted(SUPPORTED_ATS | set(cached_names))
        rep.note = f"provider listing unavailable ({exc}); " + ("using the cached provider files. " if cached_names else "unsupported providers not enumerated. ")
        rep.status = "partial" if not cached_names else "cached"
    cands: list[Candidate] = []
    hashes: list[bytes] = []
    for name in files:
        fname = f"{name}.csv"
        cached = cache.load(ATS_SCRAPERS, fname)
        try:
            raw = get(ATS_SCRAPERS_RAW.format(name=name))
            if name in SUPPORTED_ATS:
                got, rows, rej = parse_ats_scrapers_csv(name, raw)
                if cached:
                    old_rows = len(parse_ats_scrapers_csv(name, cached)[0])
                    if old_rows and len(got) < SHRINK_GUARD * old_rows:
                        raise InventoryError(f"{fname}: row count fell {old_rows} -> {len(got)}")
            cache.save(ATS_SCRAPERS, fname, raw)
        except (InventoryError, Exception) as exc:  # noqa: BLE001  (one bad file must not lose the others)
            if cached is None:
                rep.status = "partial"
                rep.note += f"{fname} unavailable ({exc}); "
                continue
            raw = cached
            rep.status = "cached" if rep.status == "ok" else rep.status
            rep.note += f"{fname}: using last-known-good ({exc}); "
            rep.from_cache_files.append(fname)
        hashes.append(raw)
        if name in SUPPORTED_ATS:
            try:
                got, rows, rej = parse_ats_scrapers_csv(name, raw)
            except InventoryError as exc:
                rep.status, rep.note = "partial", rep.note + f"{fname}: {exc}; "
                continue
            rep.rows_total += rows
            rep.rows_supported += rows
            rep.rows_rejected += rej
            cands += got
        else:
            n = max(0, raw.count(b"\n") - 1)  # rows, without parsing providers we do not use
            rep.rows_total += n
            rep.unsupported[name] = n
    if not cands and not rep.from_cache_files:
        rep.status = "failed"
    rep.sha256 = _sha(hashes)
    return _dedupe(cands, rep)


def load_source(source: str, cache: InventoryCache, *, get: Callable[[str], bytes] = http_get_bytes) -> tuple[list[Candidate], SourceReport]:
    return load_open_ats_feed(cache, get=get) if source == OPEN_ATS_FEED else load_ats_scrapers(cache, get=get)


# --------------------------------------------------------------------------- overlap report


@dataclass
class OverlapReport:
    per_source: dict[str, SourceReport]
    unique_union: int
    overlap: int  # boards present in BOTH sources
    only: dict[str, int]  # boards only this source has
    new_vs_registry: dict[str, int]  # boards this source adds beyond what the registry already knew
    already_known: dict[str, int]
    union_by_ats: dict[str, int]
    case_variants: int  # case-sensitive ATSs: identifiers that differ only by case across sources


def overlap_report(by_source: dict[str, list[Candidate]], reports: dict[str, SourceReport], registry_keys: set[str]) -> OverlapReport:
    keys = {s: {c.board.key for c in cs} for s, cs in by_source.items()}
    union = set().union(*keys.values()) if keys else set()
    srcs = list(keys)
    both = set.intersection(*keys.values()) if len(keys) > 1 else set()
    lower = collections.defaultdict(set)
    for k in union:
        ats, _, ident = k.partition("|")
        if ats in {LEVER, WORKABLE}:
            lower[(ats, ident.lower())].add(ident)
    return OverlapReport(
        per_source=reports,
        unique_union=len(union),
        overlap=len(both),
        only={s: len(keys[s] - set().union(*(keys[o] for o in srcs if o != s))) for s in srcs},
        new_vs_registry={s: len(keys[s] - registry_keys) for s in srcs},
        already_known={s: len(keys[s] & registry_keys) for s in srcs},
        union_by_ats=dict(collections.Counter(k.split("|")[0].split("@")[0] for k in union)),
        case_variants=sum(1 for v in lower.values() if len(v) > 1),
    )


# --------------------------------------------------------------------------- validation policy

# Per-provider spacing between requests (seconds). Lever publishes `Crawl-delay: 1`.
MIN_INTERVAL = {LEVER: 1.0, GREENHOUSE: 0.1, ASHBY: 0.1, WORKABLE: 0.25, SMARTRECRUITERS: 0.5}
SR_POLICY = (
    "api.smartrecruiters.com/robots.txt disallows generic crawlers on every path; bulk validation "
    "is off unless ALLOW_SMARTRECRUITERS_BULK=1"
)


def policy_blocks(ats: str, *, allow_smartrecruiters: bool) -> str | None:
    if ats == SMARTRECRUITERS and not allow_smartrecruiters:
        return SR_POLICY
    return None


class HostLimiter:
    """Thread-safe minimum spacing per provider (reservation based: callers queue fairly)."""

    def __init__(self, intervals: dict[str, float] | None = None, *, clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep) -> None:
        self.intervals, self.clock, self.sleep = intervals or MIN_INTERVAL, clock, sleep
        self._next: dict[str, float] = {}
        self._lock = threading.Lock()

    def penalize(self, ats: str, seconds: float) -> None:
        """After HTTP 429: no request to this provider for `seconds` (at most 2 minutes inside a validation run)."""
        with self._lock:
            self._next[ats] = max(self._next.get(ats, 0.0), self.clock() + min(seconds, 120.0))

    def wait(self, ats: str) -> None:
        with self._lock:
            now = self.clock()
            slot = max(now, self._next.get(ats, 0.0))
            self._next[ats] = slot + self.intervals.get(ats, 0.1)
        if slot > now:
            self.sleep(slot - now)


@dataclass
class ValidationResult:
    outcome: str  # V_VALID | V_EMPTY | V_INVALID | V_TRANSIENT | V_DEFERRED
    jobs: int = 0
    relevant: int = 0
    error: str = ""
    eligible: int = 0  # relevant jobs whose listing location is not excluded by the US rule


def validate_board(
    board: BoardId, *, fetch: Callable[[BoardId], list[Any]] = bd.fetch_board, limiter: HostLimiter | None = None,
    title_gate: Callable[[str], str | None] | None = None, retries: int = 3, sleep: Callable[[float], None] = time.sleep,
) -> ValidationResult:  # fmt: skip
    """Ask the ATS adapter. 404/410 => invalid. Timeouts/5xx/429/bad payloads => retry with
    backoff, then TRANSIENT (never "invalid"). 200 with jobs => valid; 200 empty => valid_empty."""
    error = ""
    for attempt in range(retries):
        if limiter:
            limiter.wait(board.ats)
        try:
            jobs = fetch(board)
        except BoardGone as exc:
            return ValidationResult(V_INVALID, error=str(exc))
        except bd.BoardRateLimited as exc:  # 429: slow that provider down for everyone, and never read it as "closed"
            error = str(exc)
            if limiter:
                limiter.penalize(board.ats, exc.retry_after)
            if attempt < retries - 1:
                sleep(1.5 * 2**attempt)
            continue
        except BoardError as exc:
            error = str(exc)
            if attempt < retries - 1:
                sleep(1.5 * 2**attempt)
            continue
        except Exception as exc:  # adapter bug: still not evidence the board is closed
            return ValidationResult(V_TRANSIENT, error=f"{type(exc).__name__}: {exc}")
        unique: dict[str, Any] = {}
        for j in jobs:
            unique.setdefault(j.ident.key, j)  # some boards repeat a posting once per location
        relevant_jobs = [j for j in unique.values() if title_gate is None or title_gate(j.title) is None]
        eligible = sum(1 for j in relevant_jobs if eligibility.location_blocks(j.location) is None)
        return ValidationResult(V_VALID if jobs else V_EMPTY, jobs=len(unique), relevant=len(relevant_jobs), eligible=eligible)
    return ValidationResult(V_TRANSIENT, error=error or "unavailable")


def apply_validation(rec: BoardRecord, res: ValidationResult, now: datetime) -> bool:
    """Write a validation outcome into the registry row. Never touches rows the poller owns
    (monitored or disabled) and never turns a transient failure into a verdict."""
    if rec.status in (bd.STATUS_NEW, bd.STATUS_ACTIVE, STATUS_DISABLED):
        return False
    stamp = now.strftime(STAMP)
    rec.last_attempt_at = stamp
    if res.outcome == V_TRANSIENT:
        rec.consecutive_failures += 1
        rec.last_error = res.error[:200]
        return True
    rec.consecutive_failures, rec.last_error = 0, ""
    rec.validation = res.outcome
    if res.outcome == V_INVALID:
        rec.status, rec.last_error = STATUS_INVALID, "board not found (HTTP 404/410)"
    elif res.outcome == V_DEFERRED:
        rec.status, rec.last_error = STATUS_DEFERRED, res.error[:200]
    else:
        if rec.status != STATUS_VALIDATED and not rec.pool_since:
            rec.pool_since, rec.pool_reason = stamp, f"validated {now:%Y-%m-%d}: waiting for a slot"  # waiting-time clock starts
        rec.status, rec.last_validated_at = STATUS_VALIDATED, stamp
        rec.last_job_count, rec.relevant_jobs = res.jobs, res.relevant
        rec.eligible_jobs, rec.relevance_at = res.eligible, stamp
    return True


REVALIDATE_VALID_AFTER = timedelta(days=7)
REVALIDATE_INVALID_AFTER = timedelta(days=30)


def _age(ts: str, now: datetime) -> timedelta | None:
    try:
        return now - datetime.strptime(ts, STAMP).replace(tzinfo=now.tzinfo)
    except ValueError:
        return None


def validation_due(rec: BoardRecord, now: datetime, *, allow_smartrecruiters: bool = False) -> bool:
    if rec.status == STATUS_CANDIDATE:
        if not rec.last_attempt_at:
            return True
        age = _age(rec.last_attempt_at, now)  # transient failures back off: 2^n hours, capped at 2 days
        return age is None or age >= timedelta(hours=min(2 ** rec.consecutive_failures, 48))
    if rec.status == STATUS_VALIDATED:
        age = _age(rec.last_validated_at, now)
        return age is None or age >= REVALIDATE_VALID_AFTER
    if rec.status == STATUS_INVALID:
        age = _age(rec.last_attempt_at, now)
        return age is None or age >= REVALIDATE_INVALID_AFTER
    if rec.status == STATUS_DEFERRED:
        return policy_blocks(rec.ats, allow_smartrecruiters=allow_smartrecruiters) is None
    return False


def _priority(rec: BoardRecord) -> tuple[int, int, str]:
    """Validate boards both sources vouch for first, then ones known to have open postings."""
    n_sources = len(rec.provenance)
    live = any(p.get("state") == "live" for p in rec.provenance.values())
    return (-n_sources, 0 if live else 1, rec.key)


def interleave_by_ats(ordered: list[BoardRecord]) -> list[BoardRecord]:
    """Round-robin across providers, keeping each provider's own priority order, so every
    provider makes progress each run and Lever's 1 request/s limit cannot stall the others."""
    queues: dict[str, collections.deque[BoardRecord]] = collections.defaultdict(collections.deque)
    for r in ordered:
        queues[r.ats].append(r)
    out: list[BoardRecord] = []
    while queues:
        for ats in list(queues):
            out.append(queues[ats].popleft())
            if not queues[ats]:
                del queues[ats]
    return out


def _due_basis(rec: BoardRecord) -> tuple[str, timedelta]:
    """The timestamp a re-check is measured from and how long it may wait: validated boards from their
    last good listing, invalid boards from the last attempt."""
    if rec.status == STATUS_INVALID:
        return rec.last_attempt_at, REVALIDATE_INVALID_AFTER
    return rec.last_validated_at, REVALIDATE_VALID_AFTER


def revalidation_order(rec: BoardRecord) -> tuple[int, str, str]:
    """Oldest-first: boards with no usable timestamp first (they have never been re-checked), then the
    one whose basis timestamp is earliest. Stamps sort chronologically as strings."""
    basis, _ = _due_basis(rec)
    try:
        datetime.strptime(basis, STAMP)
        parsed = True
    except ValueError:
        parsed = False
    return (1 if parsed else 0, basis if parsed else "", rec.key)


def is_revalidation(rec: BoardRecord) -> bool:
    return rec.status in (STATUS_VALIDATED, STATUS_INVALID)


def queue_stats(registry: dict[str, BoardRecord], now: datetime, *, allow_smartrecruiters: bool = False) -> dict[str, int | None]:
    """Both validation queues: how many boards are due and how long the oldest has waited / is overdue."""
    cands = [r for r in registry.values() if not is_revalidation(r) and validation_due(r, now, allow_smartrecruiters=allow_smartrecruiters)]
    revals = [r for r in registry.values() if is_revalidation(r) and validation_due(r, now, allow_smartrecruiters=allow_smartrecruiters)]
    oldest_c: float | None = None
    for r in cands:
        age = _age(r.discovered_at, now)
        if age is not None:
            oldest_c = age.total_seconds() / 3600 if oldest_c is None else max(oldest_c, age.total_seconds() / 3600)
    oldest_o: float | None = None
    for r in revals:
        basis, limit = _due_basis(r)
        age = _age(basis, now)
        if age is not None:
            over = (age - limit).total_seconds() / 3600
            oldest_o = over if oldest_o is None else max(oldest_o, over)
    return {
        "candidates_due": len(cands), "revalidations_due": len(revals),
        "oldest_candidate_hours": None if oldest_c is None else int(oldest_c),
        "oldest_overdue_hours": None if oldest_o is None else max(0, int(oldest_o)),
    }  # fmt: skip


@dataclass
class ValidationSummary:
    attempted: int = 0
    by_outcome: dict[str, int] = field(default_factory=dict)
    by_ats: dict[str, dict[str, int]] = field(default_factory=dict)
    deferred_by_policy: int = 0
    paused: list[str] = field(default_factory=list)  # providers skipped after a streak of transient failures
    remaining_due: int = 0  # both queues together
    seconds: float = 0.0
    candidates_due: int = 0  # never-validated (or parked) boards due at the start
    revalidations_due: int = 0  # validated / invalid boards past their re-check age at the start
    attempted_candidates: int = 0
    attempted_revalidations: int = 0
    oldest_candidate_hours: int | None = None
    oldest_overdue_hours: int | None = None


def run_validation(
    registry: dict[str, BoardRecord],
    *,
    save: Callable[[list[BoardRecord]], None],
    now: datetime,
    fetch: Callable[[BoardId], list[Any]] = bd.fetch_board,
    title_gate: Callable[[str], str | None] | None = None,
    max_boards: int = 500,
    max_seconds: float = 900.0,
    workers: int = 8,
    wave: int = 200,
    allow_smartrecruiters: bool = False,
    limiter: HostLimiter | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    breaker_after: int = 15,
    max_revalidations: int = 500,
) -> ValidationSummary:
    """Validate due boards in bounded, persisted waves. Bounded by count, time and per-provider
    rate limits; a provider that fails `breaker_after` times in a row is paused for the run.

    Two queues with their OWN budgets: never-validated candidates (`max_boards`) and overdue
    re-checks of validated / invalid boards (`max_revalidations`, oldest first), merged by strict
    alternation, so an enormous candidate backlog can never starve the re-checks (or vice versa)."""
    summary = ValidationSummary()
    started = clock()
    limiter = limiter or HostLimiter(sleep=sleep)
    changed_all: dict[str, BoardRecord] = {}

    # Policy: boards a provider's robots.txt does not allow us to bulk-check are parked, not dropped
    # (waiting boards too: they must not be promoted into polling a disallowed host).
    for rec in registry.values():
        if rec.status in (STATUS_CANDIDATE, STATUS_DEFERRED, STATUS_VALIDATED) and (why := policy_blocks(rec.ats, allow_smartrecruiters=allow_smartrecruiters)):
            if rec.status != STATUS_DEFERRED or rec.validation != V_DEFERRED:
                apply_validation(rec, ValidationResult(V_DEFERRED, error=why), now)
                rec.pool_reason = f"parked {now:%Y-%m-%d}: provider policy (SmartRecruiters robots.txt); history kept"
                changed_all[rec.key] = rec
                summary.deferred_by_policy += 1
    stats = queue_stats(registry, now, allow_smartrecruiters=allow_smartrecruiters)
    summary.candidates_due, summary.revalidations_due = stats["candidates_due"] or 0, stats["revalidations_due"] or 0
    summary.oldest_candidate_hours, summary.oldest_overdue_hours = stats["oldest_candidate_hours"], stats["oldest_overdue_hours"]
    due = [r for r in registry.values() if validation_due(r, now, allow_smartrecruiters=allow_smartrecruiters)]
    cand_queue = interleave_by_ats(sorted((r for r in due if not is_revalidation(r)), key=_priority))[: max(0, max_boards)]
    reval_queue = interleave_by_ats(sorted((r for r in due if is_revalidation(r)), key=revalidation_order))[: max(0, max_revalidations)]
    reval_keys = {r.key for r in reval_queue}
    summary.remaining_due = (summary.candidates_due - len(cand_queue)) + (summary.revalidations_due - len(reval_queue))
    streak: dict[str, int] = collections.defaultdict(int)
    lock = threading.Lock()

    def work(rec: BoardRecord) -> tuple[BoardRecord, ValidationResult | None]:
        if clock() - started > max_seconds:
            return rec, None
        with lock:
            if streak[rec.ats] >= breaker_after:
                return rec, None
        res = validate_board(rec.board_id, fetch=fetch, limiter=limiter, title_gate=title_gate, sleep=sleep)
        with lock:
            streak[rec.ats] = streak[rec.ats] + 1 if res.outcome == V_TRANSIENT else 0
        return rec, res

    todo: list[BoardRecord] = []  # strict alternation starting with a re-check, then whichever queue remains
    for i in range(max(len(cand_queue), len(reval_queue))):
        if i < len(reval_queue):
            todo.append(reval_queue[i])
        if i < len(cand_queue):
            todo.append(cand_queue[i])
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for i in range(0, len(todo), wave):
            if clock() - started > max_seconds:
                break
            changed = []
            for rec, res in pool.map(work, todo[i : i + wave]):
                if res is None:
                    continue
                summary.attempted += 1
                if rec.key in reval_keys:
                    summary.attempted_revalidations += 1
                else:
                    summary.attempted_candidates += 1
                summary.by_outcome[res.outcome] = summary.by_outcome.get(res.outcome, 0) + 1
                summary.by_ats.setdefault(rec.ats, {}).setdefault(res.outcome, 0)
                summary.by_ats[rec.ats][res.outcome] += 1
                if apply_validation(rec, res, now):
                    changed.append(rec)
            if changed:
                save(changed)  # batch persistence: progress survives a timeout
                for r in changed:
                    changed_all.pop(r.key, None)
    summary.paused = sorted(a for a, n in streak.items() if n >= breaker_after)
    if changed_all:
        save(list(changed_all.values()))
    summary.remaining_due += max(0, len(todo) - summary.attempted)
    summary.seconds = clock() - started
    return summary


# --------------------------------------------------------------------------- admission (every source)


@dataclass
class AdmissionResult:
    """What one admission pass did. `touched` rows must be persisted by the caller."""

    submitted: int = 0  # unique boards submitted
    added: int = 0  # not in the registry before
    rejected: int = 0  # identifier cannot be a board id (never registered)
    parked: int = 0  # provider policy blocks checking them (SmartRecruiters)
    validated: int = 0  # validated inline (valid or valid-but-empty)
    invalid: int = 0
    transient: int = 0  # left as candidates; the validation workflow retries with backoff
    touched: dict[str, BoardRecord] = field(default_factory=dict)
    keys: list[str] = field(default_factory=list)  # registry keys of the submitted boards


def admit_boards(
    registry: dict[str, BoardRecord],
    found: Iterable[BoardId],
    *,
    source: str,
    now: datetime,
    fetch: Callable[[BoardId], list[Any]] = bd.fetch_board,
    title_gate: Callable[[str], str | None] | None = None,
    allow_smartrecruiters: bool = False,
    max_inline_validations: int = 40,
    limiter: HostLimiter | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> AdmissionResult:
    """The ONE admission path for boards from any source (inventory import, web search, manual seed).

    Every submitted board gets the same treatment: (1) identifier sanity, (2) registered as an
    unvalidated `candidate` with provenance (an existing board only gains provenance; its status
    and history never change), (3) provider policy (SmartRecruiters is parked unless bulk access
    is allowed), (4) validation through the ATS adapter. Prioritisation and the active-board
    limits are applied afterwards by `boards.activate_waiting`, the only way into monitoring.
    Inline validation is bounded; boards past the bound stay candidates for the validation job."""
    res = AdmissionResult()
    unique: dict[str, BoardId] = {}
    for b in found:
        if not IDENT_RE.match(b.board or "") or b.ats not in SUPPORTED_ATS:
            res.rejected += 1
            continue
        unique.setdefault(b.key, b)
    res.submitted = len(unique)
    added, updated = merge_candidates(registry, (Candidate(b, source) for b in unique.values()), now=now, new_status=STATUS_CANDIDATE)
    res.added = len(added)
    for rec in (*added, *updated):
        res.touched[rec.key] = rec
    res.keys = list(unique)
    mine = [registry[k] for k in unique]

    for rec in mine:  # provider policy: park, do not poll and do not validate
        if rec.status in (STATUS_CANDIDATE, STATUS_DEFERRED) and (why := policy_blocks(rec.ats, allow_smartrecruiters=allow_smartrecruiters)):
            if rec.status != STATUS_DEFERRED or rec.validation != V_DEFERRED:
                apply_validation(rec, ValidationResult(V_DEFERRED, error=why), now)
                res.touched[rec.key] = rec
                res.parked += 1

    due = [r for r in mine if r.status in (STATUS_CANDIDATE, STATUS_DEFERRED) and validation_due(r, now, allow_smartrecruiters=allow_smartrecruiters)]
    due = interleave_by_ats(sorted(due, key=_priority))[:max_inline_validations]
    limiter = limiter or HostLimiter(sleep=sleep)

    def check(rec: BoardRecord) -> tuple[BoardRecord, ValidationResult]:
        return rec, validate_board(rec.board_id, fetch=fetch, limiter=limiter, title_gate=title_gate, retries=2, sleep=sleep)

    if due:
        with ThreadPoolExecutor(max_workers=min(4, len(due))) as pool:
            for rec, vr in pool.map(check, due):
                if apply_validation(rec, vr, now):
                    res.touched[rec.key] = rec
                if vr.outcome == V_INVALID:
                    res.invalid += 1
                elif vr.outcome == V_TRANSIENT:
                    res.transient += 1
                else:
                    res.validated += 1
    return res


# --------------------------------------------------------------------------- orchestration


@dataclass
class ImportResult:
    overlap: OverlapReport
    added: int
    updated: int
    registry_size: int


def import_inventories(
    registry: dict[str, BoardRecord],
    *,
    cache: InventoryCache,
    save: Callable[[list[BoardRecord]], None],
    now: datetime,
    sources: Iterable[str] = SOURCES,
    get: Callable[[str], bytes] = http_get_bytes,
    meta: dict[str, dict[str, str]] | None = None,
) -> ImportResult:
    """Download (or fall back to the last-known-good copy), then merge into the one registry.
    Idempotent: a second import of the same inventory changes no row."""
    by_source: dict[str, list[Candidate]] = {}
    reports: dict[str, SourceReport] = {}
    registry_keys = set(registry)
    for src in sources:
        cands, rep = load_source(src, cache, get=get)
        by_source[src], reports[src] = cands, rep
        if meta is not None:
            meta[src] = {"Fetched_At": now.strftime(STAMP), "SHA256": rep.sha256, "Rows": str(rep.rows_supported),
                         "As_Of": rep.as_of, "Status": rep.status, "Note": rep.note[:400]}  # fmt: skip
    changed: dict[str, BoardRecord] = {}
    added_n = updated_n = 0
    for src, cands in by_source.items():
        added, updated = merge_candidates(registry, cands, now=now, new_status=STATUS_CANDIDATE)
        added_n += len(added)
        updated_n += len(updated)
        for r in (*added, *updated):
            changed[r.key] = r
    if changed:
        save(list(changed.values()))
    return ImportResult(overlap_report(by_source, reports, registry_keys), added_n, updated_n, len(registry))


def format_report(res: ImportResult | None, summary: ValidationSummary | None, counts: dict[str, int]) -> str:
    lines: list[str] = []
    if res is None:
        return _registry_lines(summary, counts)
    ov = res.overlap
    lines += ["INVENTORY IMPORT", ""]
    lines.append(f"{'source':<14}{'status':<8}{'rows(all)':>10}{'rows(ours)':>11}{'rejected':>9}{'unique':>8}{'only here':>10}{'new to registry':>16}")
    for s, rep in ov.per_source.items():
        lines.append(f"{s:<14}{rep.status:<8}{rep.rows_total:>10}{rep.rows_supported:>11}{rep.rows_rejected:>9}{rep.unique_boards:>8}{ov.only.get(s, 0):>10}{ov.new_vs_registry.get(s, 0):>16}")
    lines += ["", f"overlap (in both sources): {ov.overlap} | unique union: {ov.unique_union} | by ATS: {ov.union_by_ats}",
              f"Lever/Workable identifiers differing only by case across sources: {ov.case_variants}",
              f"merged into registry: +{res.added} new boards, {res.updated} provenance updates, registry now {res.registry_size}"]  # fmt: skip
    for s, rep in ov.per_source.items():
        if rep.unsupported:
            top = sorted(rep.unsupported.items(), key=lambda kv: -kv[1])
            lines.append(f"unsupported in {s} (reported, not imported): {sum(rep.unsupported.values())} rows / {len(top)} providers: " + ", ".join(f"{k} {v}" for k, v in top[:12]) + (" ..." if len(top) > 12 else ""))
        if rep.note:
            lines.append(f"note [{s}]: {rep.note.strip()}")
    lines += _registry_lines(summary, counts).split("\n")
    return "\n".join(lines)


def queue_lines(cand_due: int, cand_done: int, cand_oldest: int | None, reval_due: int, reval_done: int, reval_oldest: int | None) -> list[str]:
    """The two validation queues, each with its own budget: how many are due, how many this run did, how long the oldest waits."""
    hours = lambda h: "n/a" if h is None else f"{h} h"  # noqa: E731
    return [
        f"  candidates:    due {cand_due}, attempted {cand_done}, oldest waiting {hours(cand_oldest)}",
        f"  revalidations: overdue {reval_due}, attempted {reval_done}, oldest overdue {hours(reval_oldest)}",
    ]


def _registry_lines(summary: ValidationSummary | None, counts: dict[str, int]) -> str:
    lines: list[str] = []
    if summary:
        lines += ["", f"VALIDATION: attempted {summary.attempted} in {summary.seconds:.0f}s | {summary.by_outcome} | still due: {summary.remaining_due}"
                  + (f" | paused providers: {summary.paused}" if summary.paused else "")
                  + (f" | parked by policy: {summary.deferred_by_policy}" if summary.deferred_by_policy else "")]  # fmt: skip
        for ats, c in sorted(summary.by_ats.items()):
            lines.append(f"  {ats:<16}{c}")
        lines += queue_lines(summary.candidates_due, summary.attempted_candidates, summary.oldest_candidate_hours,
                             summary.revalidations_due, summary.attempted_revalidations, summary.oldest_overdue_hours)  # fmt: skip
    lines += ["", f"REGISTRY: discovered {counts['discovered']} | validated {counts['validated']} | actively monitored {counts['monitored']} | "
              f"waiting for a slot {counts['waiting']} | unvalidated candidates {counts['candidates']} | invalid {counts['invalid']} | parked {counts['deferred']} | disabled {counts['disabled']}"]  # fmt: skip
    return "\n".join(lines)
