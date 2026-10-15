"""ATS boards: job identity, list-all-jobs adapters, and the board registry.

Identity is ATS + board + posting ID (SPEC.md). URLs are only a way to *find* an identity.
Adapters read each ATS's public list endpoint (one request per board; SmartRecruiters pages).
"""

from __future__ import annotations

import collections
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable
from urllib.parse import parse_qs, urlsplit

import requests

GREENHOUSE, LEVER, ASHBY, WORKABLE, SMARTRECRUITERS = "greenhouse", "lever", "ashby", "workable", "smartrecruiters"
ATS_LIST = (GREENHOUSE, LEVER, ASHBY, WORKABLE, SMARTRECRUITERS)

LIST_APIS = {
    GREENHOUSE: "https://boards-api.greenhouse.io/v1/boards/{board}/jobs",
    LEVER: "https://api.lever.co/v0/postings/{board}",
    ASHBY: "https://api.ashbyhq.com/posting-api/job-board/{board}",
    WORKABLE: "https://apply.workable.com/api/v1/widget/accounts/{board}",
    SMARTRECRUITERS: "https://api.smartrecruiters.com/v1/companies/{board}/postings",
}
HTTP_TIMEOUT = 25
USER_AGENT = "Mozilla/5.0 (compatible; job-hunter/2.0)"
DISABLE_AFTER_FAILURES = 72  # ~3 days of hourly failures

_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_GH_HOSTS = {"boards.greenhouse.io", "job-boards.greenhouse.io"}
_RESERVED_SEGMENTS = {"embed", "api", "static", "assets", "v1", "robots.txt", "favicon.ico"}


# --------------------------------------------------------------------------- identity


# Identifier casing is real data: Lever and Workable APIs 404 on a wrongly cased slug, while
# Greenhouse, Ashby and SmartRecruiters ignore case (verified live). Board identity follows that.
CASE_SENSITIVE_ATS = frozenset({LEVER, WORKABLE})


def _prefix(ats: str, region: str) -> str:
    """Provider plus region/API host. Empty region = the default (US) host, so keys for every
    board we already track are unchanged."""
    return f"{ats}@{region.lower()}" if region else ats


@dataclass(frozen=True)
class BoardId:
    ats: str
    board: str  # as the ATS spells it; this exact string is what API calls use
    region: str = ""  # "" = default host; e.g. "eu" for a regional API host

    @property
    def key(self) -> str:
        ident = self.board if self.ats in CASE_SENSITIVE_ATS else self.board.lower()
        return f"{_prefix(self.ats, self.region)}|{ident}"


@dataclass(frozen=True)
class JobIdentity:
    ats: str
    board: str
    job_id: str
    region: str = ""

    @property
    def board_id(self) -> BoardId:
        return BoardId(self.ats, self.board, self.region)

    @property
    def key(self) -> str:
        """The dedupe key. Independent of URL host, slug, case of the board, or tracking params.
        The board part stays lowercase for every ATS (job IDs are globally unique per ATS), so
        keys written before region/casing support remain valid."""
        jid = self.job_id.upper() if self.ats == WORKABLE else self.job_id.lower()
        return f"{_prefix(self.ats, self.region)}|{self.board.lower()}|{jid}"

    @property
    def url(self) -> str:
        """Canonical apply URL, used when the ATS payload gives none."""
        if self.ats == GREENHOUSE:
            return f"https://job-boards.greenhouse.io/{self.board}/jobs/{self.job_id}"
        if self.ats == LEVER:
            return f"https://jobs.lever.co/{self.board}/{self.job_id}"
        if self.ats == ASHBY:
            return f"https://jobs.ashbyhq.com/{self.board}/{self.job_id}"
        if self.ats == WORKABLE:
            return f"https://apply.workable.com/{self.board}/j/{self.job_id}/"
        return f"https://jobs.smartrecruiters.com/{self.board}/{self.job_id}"


def parse_job_url(url: str) -> JobIdentity | None:
    """Identity of a single posting, or None. Identity-bearing query parameters are honoured
    (Greenhouse embed `for`/`token`, `gh_jid`); tracking parameters are ignored."""
    try:
        parts = urlsplit((url or "").strip())
    except ValueError:
        return None
    host, path = parts.netloc.lower(), re.sub(r"/+$", "", parts.path)
    query = {k.lower(): v[0] for k, v in parse_qs(parts.query).items() if v}
    segs = [s for s in path.split("/") if s]

    if host in _GH_HOSTS:
        if segs[:2] == ["embed", "job_app"] and query.get("for") and (query.get("token") or "").isdigit():
            return JobIdentity(GREENHOUSE, query["for"], query["token"])
        if len(segs) == 3 and segs[1] == "jobs" and segs[2].isdigit() and segs[0] not in _RESERVED_SEGMENTS:
            return JobIdentity(GREENHOUSE, segs[0], segs[2])
        if len(segs) == 1 and segs[0] not in _RESERVED_SEGMENTS and (query.get("gh_jid") or "").isdigit():
            return JobIdentity(GREENHOUSE, segs[0], query["gh_jid"])
        return None
    if host == "jobs.lever.co" and 2 <= len(segs) <= 3 and re.fullmatch(_UUID, segs[1], re.I):
        if len(segs) == 2 or segs[2] == "apply":
            return JobIdentity(LEVER, segs[0], segs[1].lower())
    if host == "jobs.ashbyhq.com" and 2 <= len(segs) <= 3 and re.fullmatch(_UUID, segs[1], re.I):
        if len(segs) == 2 or segs[2] == "application":
            return JobIdentity(ASHBY, segs[0], segs[1].lower())
    if host == "apply.workable.com" and len(segs) in (3, 4) and segs[1] == "j" and re.fullmatch(r"[A-Za-z0-9]+", segs[2]):
        if len(segs) == 3 or segs[3] == "apply":
            return JobIdentity(WORKABLE, segs[0], segs[2].upper())
    if host == "jobs.smartrecruiters.com" and len(segs) == 2:
        if m := re.match(r"(\d{6,})(?:-.*)?$", segs[1]):
            return JobIdentity(SMARTRECRUITERS, segs[0], m.group(1))
    return None


def parse_board_url(url: str) -> BoardId | None:
    """The board a URL belongs to: from a posting identity or from a board listing page."""
    ident = parse_job_url(url)
    if ident:
        return ident.board_id
    try:
        parts = urlsplit((url or "").strip())
    except ValueError:
        return None
    host = parts.netloc.lower()
    segs = [s for s in re.sub(r"/+$", "", parts.path).split("/") if s]
    query = {k.lower(): v[0] for k, v in parse_qs(parts.query).items() if v}
    if host in _GH_HOSTS:
        if segs[:1] == ["embed"] and query.get("for"):
            return BoardId(GREENHOUSE, query["for"])
        if len(segs) == 1 and segs[0] not in _RESERVED_SEGMENTS:
            return BoardId(GREENHOUSE, segs[0])
    elif host in {"jobs.lever.co", "jobs.ashbyhq.com", "jobs.smartrecruiters.com", "apply.workable.com"}:
        if len(segs) == 1 and segs[0] not in _RESERVED_SEGMENTS:
            ats = {"jobs.lever.co": LEVER, "jobs.ashbyhq.com": ASHBY, "jobs.smartrecruiters.com": SMARTRECRUITERS, "apply.workable.com": WORKABLE}[host]
            return BoardId(ats, segs[0])
    return None


# --------------------------------------------------------------------------- listing


@dataclass(frozen=True)
class ListedJob:
    ident: JobIdentity
    title: str
    url: str
    location: str = ""
    published: str = ""  # raw source publication value (ISO / date); "" if the list has none
    published_field: str = ""  # which source field it came from
    updated: str = ""  # source last-modified, if any (never a publication time)
    department: str = ""


class BoardGone(Exception):
    """The board no longer exists (HTTP 404/410)."""


class BoardError(Exception):
    """Temporary failure listing a board (timeout, 5xx, 429, bad payload): retry next poll."""


RATE_LIMIT_DEFAULT_BACKOFF = 300.0  # seconds a provider is left alone after HTTP 429 without a Retry-After
RATE_LIMIT_MAX_BACKOFF = 900.0


class BoardRateLimited(BoardError):
    """HTTP 429. The provider asked us to slow down: stop sending it requests for `retry_after` seconds."""

    def __init__(self, retry_after: float = RATE_LIMIT_DEFAULT_BACKOFF) -> None:
        super().__init__(f"HTTP 429 (provider backoff {retry_after:.0f}s)")
        self.retry_after = retry_after


def _retry_after(resp: Any) -> float:
    try:
        return max(1.0, min(RATE_LIMIT_MAX_BACKOFF, float(resp.headers.get("Retry-After"))))
    except (TypeError, ValueError, AttributeError):
        return RATE_LIMIT_DEFAULT_BACKOFF


def _get_json(url: str, params: dict[str, Any] | None = None) -> Any:
    try:
        resp = requests.get(url, params=params, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}, timeout=HTTP_TIMEOUT)
    except requests.RequestException as exc:
        raise BoardError(str(exc)) from exc
    if resp.status_code in {404, 410}:
        raise BoardGone(f"HTTP {resp.status_code}")
    if resp.status_code == 429:
        raise BoardRateLimited(_retry_after(resp))
    if resp.status_code >= 400:
        raise BoardError(f"HTTP {resp.status_code}")
    try:
        return resp.json()
    except ValueError as exc:
        raise BoardError("response was not JSON") from exc


def _places(*items: Any) -> str:
    return ", ".join(dict.fromkeys(str(i).strip() for i in items if i and str(i).strip()))


def parse_greenhouse(board: str, data: Any) -> list[ListedJob]:
    out = []
    for j in (data or {}).get("jobs", []):
        if j.get("id") is None:
            continue
        ident = JobIdentity(GREENHOUSE, board, str(j["id"]))
        first = j.get("first_published") or ""
        out.append(ListedJob(
            ident, j.get("title") or "", j.get("absolute_url") or ident.url, (j.get("location") or {}).get("name") or "",
            first, "first_published" if first else "", j.get("updated_at") or "",
        ))  # fmt: skip
    return out


def parse_lever(board: str, data: Any) -> list[ListedJob]:
    out = []
    for j in data if isinstance(data, list) else []:
        if not j.get("id"):
            continue
        ident = JobIdentity(LEVER, board, str(j["id"]).lower())
        cats = j.get("categories") or {}
        created = j.get("createdAt")
        out.append(ListedJob(
            ident, j.get("text") or "", j.get("hostedUrl") or ident.url,
            _places(cats.get("location"), *(cats.get("allLocations") or []), j.get("workplaceType")),
            str(created) if created else "", "createdAt" if created else "", "", cats.get("department") or "",
        ))  # fmt: skip
    return out


def parse_ashby(board: str, data: Any) -> list[ListedJob]:
    out = []
    for j in (data or {}).get("jobs", []):
        if not j.get("id") or j.get("isListed") is False:
            continue
        ident = JobIdentity(ASHBY, board, str(j["id"]).lower())
        pub = j.get("publishedAt") or j.get("publishedDate") or ""
        secondary = [s.get("location", "") if isinstance(s, dict) else s for s in j.get("secondaryLocations") or []]
        remote = "Remote" if str(j.get("workplaceType") or "").lower() == "remote" else ""
        out.append(ListedJob(
            ident, j.get("title") or "", j.get("jobUrl") or ident.url, _places(j.get("location"), *secondary, remote),
            pub, "publishedAt" if pub else "", "", j.get("department") or "",
        ))  # fmt: skip
    return out


def parse_workable(board: str, data: Any) -> list[ListedJob]:
    out = []
    for j in (data or {}).get("jobs", []):
        if not j.get("shortcode"):
            continue
        ident = JobIdentity(WORKABLE, board, str(j["shortcode"]).upper())
        pub = j.get("published_on") or j.get("created_at") or ""  # date only
        out.append(ListedJob(
            ident, j.get("title") or "", j.get("url") or j.get("shortlink") or ident.url,
            _places(j.get("city"), j.get("state"), j.get("country"), "Remote" if j.get("telecommuting") else ""),
            pub, "published_on" if j.get("published_on") else ("created_at" if pub else ""), "", j.get("department") or "",
        ))  # fmt: skip
    return out


def parse_smartrecruiters(board: str, items: list[dict[str, Any]]) -> list[ListedJob]:
    out = []
    for j in items:
        if not j.get("id"):
            continue
        ident = JobIdentity(SMARTRECRUITERS, board, str(j["id"]))
        loc = j.get("location") or {}
        released = j.get("releasedDate") or ""
        dept = j.get("department")
        out.append(ListedJob(
            ident, j.get("name") or "", ident.url,
            _places(loc.get("fullLocation") or _places(loc.get("city"), loc.get("region"), str(loc.get("country") or "").upper()),
                    "Remote" if loc.get("remote") else "", "Hybrid" if loc.get("hybrid") else ""),
            released, "releasedDate" if released else "", "", (dept.get("label") if isinstance(dept, dict) else "") or "",
        ))  # fmt: skip
    return out


class Listing(list):
    """A board listing that knows whether it is the WHOLE listing. `complete` is False only when
    an adapter had to stop early (SmartRecruiters past its paging cap), so counts derived from it
    must not be treated as the board's real totals. A plain list counts as complete."""

    def __init__(self, items: Iterable[Any] = (), *, complete: bool = True) -> None:
        super().__init__(items)
        self.complete = complete


CAP_SIZES = frozenset({10, 20, 25, 50, 100, 200, 250, 500, 1000})


def looks_capped(n: int) -> bool:
    """A listing whose length is exactly a typical page size is suspicious: a server-side cap would produce
    this. Used only where the provider documents no pagination behaviour (Lever's default, Workable's widget)."""
    return n in CAP_SIZES


def fetch_board(board: BoardId) -> list[ListedJob]:
    """All currently listed jobs on a board. Raises BoardGone (deleted) or BoardError (transient)."""
    url = LIST_APIS[board.ats].format(board=board.board)
    if board.ats == GREENHOUSE:
        data = _get_json(url)
        parsed = parse_greenhouse(board.board, data)
        total = ((data or {}).get("meta") or {}).get("total") if isinstance(data, dict) else None
        # Greenhouse reports how many jobs the board has: a shorter list is a truncated listing.
        return Listing(parsed, complete=False) if isinstance(total, int) and len(parsed) < total else parsed
    if board.ats == LEVER:
        # Lever documents `skip` and `limit` but not what an unpaged request returns; observed live, it returns the
        # whole board. Defence against an undocumented cap: a list whose length is a typical page size is
        # continued with `skip` until a short page.
        items = list(_get_json(url, {"mode": "json"}) or [])
        pages = 0
        while looks_capped(len(items)) and pages < 20:
            more = _get_json(url, {"mode": "json", "skip": len(items), "limit": 100}) or []
            items.extend(more)
            pages += 1
            if len(more) < 100:
                break
        return parse_lever(board.board, items)
    if board.ats == ASHBY:
        return parse_ashby(board.board, _get_json(url))
    if board.ats == WORKABLE:
        # The widget endpoint is undocumented (no pagination parameter is known), so a list that stops at a typical
        # page size cannot be continued: it is reported as possibly truncated rather than assumed complete.
        parsed = parse_workable(board.board, _get_json(url))
        return Listing(parsed, complete=False) if looks_capped(len(parsed)) else parsed
    items: list[dict[str, Any]] = []  # SmartRecruiters pages at 100
    offset = total = 0
    while True:
        page = _get_json(url, {"limit": 100, "offset": offset})
        content = (page or {}).get("content") or []
        items.extend(content)
        offset += len(content)
        total = int((page or {}).get("totalFound") or 0)
        if not content or offset >= total or offset > 5000:
            break
    parsed = parse_smartrecruiters(board.board, items)
    return parsed if offset >= total else Listing(parsed, complete=False)  # stopped at the paging cap: a truncated listing


# --------------------------------------------------------------------------- registry

# Registry statuses.
#   candidate  imported from an inventory, not validated yet (never polled)
#   validated  validated OK (valid, possibly empty) and waiting for a monitoring slot
#   new        activated, not yet baselined: the next poll baselines it
#   active     baselined and polled every run
#   invalid    validation proved the board does not exist (kept, never auto-deleted)
#   deferred   validation blocked by policy (see inventory.HOST_POLICY); kept, not polled
#   disabled   a monitored board that kept failing; polling stopped
STATUS_CANDIDATE, STATUS_VALIDATED, STATUS_NEW, STATUS_ACTIVE = "candidate", "validated", "new", "active"
STATUS_INVALID, STATUS_DEFERRED, STATUS_DISABLED = "invalid", "deferred", "disabled"
MONITORED = frozenset({STATUS_NEW, STATUS_ACTIVE})

# Pools inside the monitored set (pools.py explains the policy).
POOL_ESTABLISHED, POOL_EXPLORATION = "established", "exploration"

# Validation outcomes.
V_VALID, V_EMPTY, V_INVALID, V_TRANSIENT, V_DEFERRED = "valid", "valid_empty", "invalid", "transient", "deferred"

STAMP = "%Y-%m-%dT%H:%M:%SZ"


@dataclass
class BoardRecord:
    ats: str
    board: str
    discovered_at: str  # ISO UTC: first time ANY source told us about this board
    source: str  # the source that discovered it first
    status: str = STATUS_NEW
    baselined_at: str = ""
    last_attempt_at: str = ""
    last_success_at: str = ""  # last successful list of the board (poll or validation)
    consecutive_failures: int = 0
    last_job_count: int = 0
    last_error: str = ""
    region: str = ""
    name: str = ""  # display name from an inventory, if any
    validation: str = ""  # one of V_*; "" = never validated
    last_validated_at: str = ""  # last time the board's adapter call succeeded
    relevant_jobs: int = 0  # listed jobs passing the title gate at the last validation
    provenance: dict[str, Any] = field(default_factory=dict)  # source -> {"first": ts, ...}
    # Evidence and pool state (D-23, D-26). None = never measured / unknown; 0 = measured zero.
    eligible_jobs: int | None = None  # relevant listed jobs whose location is not excluded by the US rule
    relevance_at: str = ""  # when relevant_jobs / eligible_jobs were last measured (complete poll or validation)
    activity_since: str = ""  # start of the current continuous monitoring stint ("" = no observation history)
    complete_polls: int = 0  # complete successful polls since activity_since
    last_new_relevant_at: str = ""  # first observation of the board's latest new relevant posting
    new_relevant_7d: int | None = None  # new relevant postings first observed in the last 7 days; None = unknown
    new_relevant_30d: int | None = None  # the same over min(30 days, stint length)
    pool: str = ""  # "established" | "exploration" | "" (not monitored)
    pool_since: str = ""  # when it entered its pool, or became waiting / left monitoring
    trial_until: str = ""  # end of the exploration trial
    trials: int = 0  # exploration trials started
    weak_streak: int = 0  # consecutive rebalance cycles as a replacement target (established boards)
    pool_reason: str = ""  # last admission / graduation / demotion / park reason (max 200 chars)
    outages: list[list[str]] = field(default_factory=list)  # [[start, end], ...] holes in the complete-poll record, last 30 days

    @property
    def board_id(self) -> BoardId:
        return BoardId(self.ats, self.board, self.region)

    @property
    def key(self) -> str:
        return self.board_id.key


@dataclass(frozen=True)
class Candidate:
    """A board an inventory or search says exists. Nothing more is assumed."""

    board: BoardId
    source: str
    name: str = ""
    info: dict[str, Any] = field(default_factory=dict)  # source-specific facts (kept as provenance)


def add_provenance(rec: BoardRecord, source: str, now: datetime, info: dict[str, Any] | None = None) -> bool:
    """Record that `source` knows this board. Idempotent: returns True only if something changed."""
    entry = rec.provenance.get(source)
    if entry is None:
        rec.provenance[source] = {"first": now.strftime(STAMP), **(info or {})}
        return True
    changed = False
    for k, v in (info or {}).items():
        if k != "first" and entry.get(k) != v:
            entry[k] = v
            changed = True
    return changed


def merge_candidates(
    registry: dict[str, BoardRecord], candidates: Iterable[Candidate], *, now: datetime, new_status: str
) -> tuple[list[BoardRecord], list[BoardRecord]]:
    """Merge discoveries into the one registry. Returns (added, updated).

    Only provenance, name and the discovery-time facts of an EXISTING board may change here.
    Status, polling history and validation state are never touched, so re-importing an inventory
    cannot reset, deactivate or delete anything. A board an upstream list later drops is simply
    not mentioned again."""
    added: list[BoardRecord] = []
    updated: dict[str, BoardRecord] = {}
    for c in candidates:
        rec = registry.get(c.board.key)
        if rec is None:
            rec = BoardRecord(
                c.board.ats, c.board.board, now.strftime(STAMP), c.source, new_status, region=c.board.region, name=c.name
            )
            add_provenance(rec, c.source, now, c.info)
            registry[rec.key] = rec
            added.append(rec)
            continue
        changed = add_provenance(rec, c.source, now, c.info)
        if c.name and not rec.name:
            rec.name, changed = c.name, True
        if changed and rec not in added:
            updated[rec.key] = rec
    return added, list(updated.values())


def upsert_boards(registry: dict[str, BoardRecord], found: Iterable[BoardId], *, now: datetime, source: str) -> list[BoardRecord]:
    """Search-style discovery: boards found through live job/board URLs are activated for
    monitoring straight away (status `new`: the next poll baselines them). Returns new boards only."""
    added, _ = merge_candidates(registry, (Candidate(b, source) for b in found), now=now, new_status=STATUS_NEW)
    return added


def registry_counts(registry: dict[str, BoardRecord]) -> dict[str, int]:
    """discovered / validated / monitored, for the Runs log and the import report."""
    by_status = collections.Counter(r.status for r in registry.values())
    return {
        "discovered": len(registry),
        "validated": sum(1 for r in registry.values() if r.validation in (V_VALID, V_EMPTY)),
        "monitored": sum(by_status[s] for s in MONITORED),
        "waiting": by_status[STATUS_VALIDATED],
        "candidates": by_status[STATUS_CANDIDATE],
        "invalid": by_status[STATUS_INVALID],
        "deferred": by_status[STATUS_DEFERRED],
        "disabled": by_status[STATUS_DISABLED],
    }


def open_jobs(rec: BoardRecord) -> int:
    """Open relevant jobs a board lists right now (uncapped): the location-eligible count when it
    has been measured, else the relevant count. Used to decide whether a board is worth a slot."""
    return rec.eligible_jobs if rec.eligible_jobs is not None else rec.relevant_jobs


def merge_provenance(current: BoardRecord, incoming: BoardRecord) -> bool:
    """Fold `incoming`'s provenance and display name into `current` (the row as it is stored NOW).
    Used when a writer may not overwrite a row another writer owns, so its discovery facts are
    reconciled instead of lost. Only adds: existing entries and every other field stay as stored."""
    changed = False
    for source, entry in incoming.provenance.items():
        if source not in current.provenance:
            current.provenance[source] = entry
            changed = True
        elif isinstance(entry, dict) and isinstance(current.provenance[source], dict):
            for k, v in entry.items():
                if k not in current.provenance[source]:
                    current.provenance[source][k] = v
                    changed = True
    if incoming.name and not current.name:
        current.name, changed = incoming.name, True
    return changed


def cooling_down(rec: BoardRecord, now: datetime | None, cooldown: timedelta | None) -> bool:
    """A board that already had a monitoring stint and left it (lost a trial, was replaced) is not
    offered another slot until `cooldown` has passed. Without this a board returned to the waiting
    list would immediately count as "waiting" again, justify returning the next loser, and be
    re-admitted next hour: the same few boards would be re-baselined every week."""
    if now is None or not cooldown or rec.trials <= 0:
        return False
    try:
        since = datetime.strptime(rec.pool_since, STAMP).replace(tzinfo=now.tzinfo)
    except ValueError:
        return False
    return now - since < cooldown


def is_waiting_candidate(
    rec: BoardRecord, blocked: Callable[[str], Any] | None = None, *, now: datetime | None = None, cooldown: timedelta | None = None
) -> bool:
    """A validated board with something open for the user's targets that no provider policy blocks
    and that is not cooling down after a previous stint."""
    return (
        rec.status == STATUS_VALIDATED and rec.validation == V_VALID and open_jobs(rec) > 0
        and not (blocked and blocked(rec.ats)) and not cooling_down(rec, now, cooldown)
    )  # fmt: skip


def admission_order(
    registry: dict[str, BoardRecord], blocked: Callable[[str], Any] | None = None, *, now: datetime | None = None, cooldown: timedelta | None = None
) -> list[BoardRecord]:
    """Waiting boards in the order they would be promoted: boards never tried before first (the fair
    route in for boards with no observation history), then the most open eligible jobs."""
    ready = [r for r in registry.values() if is_waiting_candidate(r, blocked, now=now, cooldown=cooldown)]
    ready.sort(key=lambda r: (r.trials > 0, -open_jobs(r), -r.relevant_jobs, r.last_job_count, r.key))
    return ready


def activate_waiting(
    registry: dict[str, BoardRecord],
    *,
    max_monitored: int,
    per_run: int,
    now: datetime | None = None,
    trial_days: int = 7,
    blocked: Callable[[str], Any] | None = None,
    cooldown: timedelta | None = None,
) -> list[BoardRecord]:
    """Promote validated boards into monitoring without ever exceeding the polling budget.

    At most `per_run` boards are promoted at once (each promotion baselines a whole board) and
    never beyond `max_monitored` in total. Every promoted board enters the EXPLORATION pool on a
    `trial_days` trial. Boards never tried before go first (the fair route in for boards with no
    observation history), then the most open eligible jobs; a board with nothing open right now,
    or whose provider is blocked by policy, keeps waiting."""
    now = now or datetime.now(timezone.utc)
    room = min(per_run, max(0, max_monitored - sum(1 for r in registry.values() if r.status in MONITORED)))
    if room <= 0:
        return []
    promoted = admission_order(registry, blocked, now=now, cooldown=cooldown)[:room]
    until = now + timedelta(days=trial_days)
    for r in promoted:
        eligible = "unknown" if r.eligible_jobs is None else r.eligible_jobs
        r.status, r.pool, r.weak_streak = STATUS_NEW, POOL_EXPLORATION, 0
        r.trials += 1
        r.pool_since, r.trial_until = now.strftime(STAMP), until.strftime(STAMP)
        r.pool_reason = (
            f"explore {now:%Y-%m-%d}: trial until {until:%Y-%m-%d}; {eligible} eligible / {r.relevant_jobs} relevant open jobs "
            f"({'first trial' if r.trials == 1 else f're-entry, trial {r.trials}'})"
        )[:200]
    return promoted


@dataclass
class PollResult:
    board: BoardRecord
    jobs: list[ListedJob] = field(default_factory=list)
    ok: bool = False
    gone: bool = False
    error: str = ""
    complete: bool = True  # False when the adapter truncated the listing: counts are not the board's totals
    skipped: bool = False  # not requested at all: the provider is in backoff after a 429 (not a failure of this board)


def poll_boards(
    boards: list[BoardRecord],
    *,
    fetch: Callable[[BoardId], list[ListedJob]] = fetch_board,
    workers: int = 8,
    clock: Callable[[], float] = time.monotonic,
) -> list[PollResult]:
    """List every board concurrently. One board failing never affects another. A provider that answers
    HTTP 429 is left alone for its Retry-After (default 5 minutes, at most 15) for the rest of the run: its
    remaining boards are `skipped` (not requested, not counted as failures) and retried next run."""
    backoff: dict[str, float] = {}
    lock = threading.Lock()

    def one(rec: BoardRecord) -> PollResult:
        with lock:
            until = backoff.get(rec.ats, 0.0)
        if until > clock():
            return PollResult(rec, skipped=True, error=f"provider backoff after HTTP 429 ({rec.ats})")
        try:
            jobs = fetch(rec.board_id)
            return PollResult(rec, jobs, ok=True, complete=getattr(jobs, "complete", True))
        except BoardGone as exc:
            return PollResult(rec, gone=True, error=str(exc))
        except BoardRateLimited as exc:
            with lock:
                backoff[rec.ats] = max(backoff.get(rec.ats, 0.0), clock() + exc.retry_after)
            return PollResult(rec, error=str(exc))
        except BoardError as exc:
            return PollResult(rec, error=str(exc))
        except Exception as exc:  # defensive: an adapter bug must not stop other boards
            return PollResult(rec, error=f"{type(exc).__name__}: {exc}")

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        return list(pool.map(one, boards))


def apply_poll_result(res: PollResult, *, now: datetime) -> tuple[BoardRecord, timedelta | None]:
    """Update the board record from a poll. Returns (new record, gap since previous success).

    The gap is read BEFORE it is overwritten: it bounds how long a newly listed job could
    have been public (it was not on the board at the previous successful poll)."""
    rec = replace(res.board)
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    prev = rec.last_success_at
    gap: timedelta | None = None
    if prev:
        try:
            gap = now - datetime.strptime(prev, STAMP).replace(tzinfo=now.tzinfo)
        except ValueError:
            gap = None
    rec.last_attempt_at = stamp
    if res.ok:
        rec.last_success_at, rec.consecutive_failures, rec.last_error = stamp, 0, ""
        rec.last_job_count = len({j.ident.key for j in res.jobs})  # unique IDs (some boards repeat a job per location)
        rec.validation, rec.last_validated_at = (V_VALID if res.jobs else V_EMPTY), stamp  # a good poll is a validation
        if rec.status == STATUS_DISABLED:
            rec.status = STATUS_ACTIVE if rec.baselined_at else STATUS_NEW
    else:
        rec.consecutive_failures += 1
        rec.last_error = res.error[:200]
        if rec.consecutive_failures >= DISABLE_AFTER_FAILURES:
            rec.status = STATUS_DISABLED
    return rec, gap
