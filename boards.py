"""ATS boards: job identity, list-all-jobs adapters, and the board registry.

Identity is ATS + board + posting ID (SPEC.md). URLs are only a way to *find* an identity.
Adapters read each ATS's public list endpoint (one request per board; SmartRecruiters pages).
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
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


@dataclass(frozen=True)
class BoardId:
    ats: str
    board: str  # as the ATS spells it (case matters for some APIs)

    @property
    def key(self) -> str:
        return f"{self.ats}|{self.board.lower()}"


@dataclass(frozen=True)
class JobIdentity:
    ats: str
    board: str
    job_id: str

    @property
    def board_id(self) -> BoardId:
        return BoardId(self.ats, self.board)

    @property
    def key(self) -> str:
        """The dedupe key. Independent of URL host, slug, case of the board, or tracking params."""
        jid = self.job_id.upper() if self.ats == WORKABLE else self.job_id.lower()
        return f"{self.ats}|{self.board.lower()}|{jid}"

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


def _get_json(url: str, params: dict[str, Any] | None = None) -> Any:
    try:
        resp = requests.get(url, params=params, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}, timeout=HTTP_TIMEOUT)
    except requests.RequestException as exc:
        raise BoardError(str(exc)) from exc
    if resp.status_code in {404, 410}:
        raise BoardGone(f"HTTP {resp.status_code}")
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


def fetch_board(board: BoardId) -> list[ListedJob]:
    """All currently listed jobs on a board. Raises BoardGone (deleted) or BoardError (transient)."""
    url = LIST_APIS[board.ats].format(board=board.board)
    if board.ats == GREENHOUSE:
        return parse_greenhouse(board.board, _get_json(url))
    if board.ats == LEVER:
        return parse_lever(board.board, _get_json(url, {"mode": "json"}))
    if board.ats == ASHBY:
        return parse_ashby(board.board, _get_json(url))
    if board.ats == WORKABLE:
        return parse_workable(board.board, _get_json(url))
    items: list[dict[str, Any]] = []  # SmartRecruiters pages at 100
    offset = 0
    while True:
        page = _get_json(url, {"limit": 100, "offset": offset})
        content = (page or {}).get("content") or []
        items.extend(content)
        offset += len(content)
        if not content or offset >= int((page or {}).get("totalFound") or 0) or offset > 5000:
            break
    return parse_smartrecruiters(board.board, items)


# --------------------------------------------------------------------------- registry

STATUS_NEW, STATUS_ACTIVE, STATUS_DISABLED = "new", "active", "disabled"


@dataclass
class BoardRecord:
    ats: str
    board: str
    discovered_at: str  # ISO UTC
    source: str  # serper | seed
    status: str = STATUS_NEW  # new = not yet baselined
    baselined_at: str = ""
    last_attempt_at: str = ""
    last_success_at: str = ""
    consecutive_failures: int = 0
    last_job_count: int = 0
    last_error: str = ""

    @property
    def board_id(self) -> BoardId:
        return BoardId(self.ats, self.board)

    @property
    def key(self) -> str:
        return self.board_id.key


def upsert_boards(registry: dict[str, BoardRecord], found: Iterable[BoardId], *, now: datetime, source: str) -> list[BoardRecord]:
    """Add every unseen board to the registry (never removes or rewrites existing ones)."""
    added: list[BoardRecord] = []
    for b in found:
        if b.key in registry:
            continue
        rec = BoardRecord(b.ats, b.board, now.strftime("%Y-%m-%dT%H:%M:%SZ"), source)
        registry[b.key] = rec
        added.append(rec)
    return added


@dataclass
class PollResult:
    board: BoardRecord
    jobs: list[ListedJob] = field(default_factory=list)
    ok: bool = False
    gone: bool = False
    error: str = ""


def poll_boards(
    boards: list[BoardRecord],
    *,
    fetch: Callable[[BoardId], list[ListedJob]] = fetch_board,
    workers: int = 8,
) -> list[PollResult]:
    """List every board concurrently. One board failing never affects another."""

    def one(rec: BoardRecord) -> PollResult:
        try:
            return PollResult(rec, fetch(rec.board_id), ok=True)
        except BoardGone as exc:
            return PollResult(rec, gone=True, error=str(exc))
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
            gap = now - datetime.strptime(prev, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=now.tzinfo)
        except ValueError:
            gap = None
    rec.last_attempt_at = stamp
    if res.ok:
        rec.last_success_at, rec.consecutive_failures, rec.last_error = stamp, 0, ""
        rec.last_job_count = len({j.ident.key for j in res.jobs})  # unique IDs (some boards repeat a job per location)
        if rec.status == STATUS_DISABLED:
            rec.status = STATUS_ACTIVE if rec.baselined_at else STATUS_NEW
    else:
        rec.consecutive_failures += 1
        rec.last_error = res.error[:200]
        if rec.consecutive_failures >= DISABLE_AFTER_FAILURES:
            rec.status = STATUS_DISABLED
    return rec, gap
