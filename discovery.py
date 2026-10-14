"""Search discovery: rotating, budgeted candidate retrieval (SPEC.md "Discovery loop").

Search only RETRIEVES candidates. Google's date filter says when a page was indexed or changed,
never when a job was published, so nothing here classifies freshness: every result is processed
two independent ways by the pipeline:

  1. its board is submitted to the shared admission process (even if the job is seen / stale /
     excluded), and
  2. its job, if unseen, goes through hydration (authoritative publication evidence), matching,
     scoring and delivery.

Pure and offline: the search call is injected, so rotation, budgets and pagination are testable.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Callable, Iterable, Sequence

from boards import BoardId, JobIdentity, parse_board_url, parse_job_url

PAGE_SIZE = 10  # Serper returns 10 organic results per page unless `num` is set
CREDITS_PER_REQUEST = 1  # one Serper search request (one page of up to 10 results) = 1 credit
DEFAULT_CREDIT_BUDGET = 10  # per discovery run: 2 runs/day = at most 20 credits/day
DEFAULT_MAX_PAGES = 3
DEFAULT_STALL_PAGES = 2  # consecutive pages with nothing new before a query stops paging

KIND_ROTATION, KIND_BACKFILL = "rotation", "backfill"

ROTATION_KEY, PENDING_KEY, LAST_RUN_KEY = "rotation", "pending_jobs", "last_discovery"
MAX_PENDING_JOBS = 60
MAX_HYDRATION_ATTEMPTS = 5


@dataclass(frozen=True)
class SerperJob:
    ident: JobIdentity
    title: str
    url: str


# --------------------------------------------------------------------------- rotation


@dataclass(frozen=True)
class Slot:
    """One rotating search: an ATS site, a role term and a location."""

    site: str
    role: str
    location: str

    @property
    def id(self) -> str:
        return f"{self.site}|{self.role.lower()}|{self.location.lower()}"


def make_slots(sites: Sequence[str], roles: Sequence[str], locations: Sequence[str]) -> list[Slot]:
    """Every site x role x location combination. Sites vary fastest, so consecutive slots cover
    all supported ATSs for one role/location before moving on (a short run still spans providers).
    An empty location list rotates sites and roles only."""
    locs = list(locations) or [""]
    return [Slot(s, r, loc) for loc in locs for r in roles for s in sites]


def fingerprint(slots: Sequence[Slot]) -> str:
    return hashlib.sha1("\n".join(s.id for s in slots).encode()).hexdigest()[:12]


@dataclass
class RotationState:
    """Where the rotation stands. Persisted between runs (hidden Discovery tab / CSV)."""

    cursor: int = 0  # index of the next slot to search
    fingerprint: str = ""  # of the slot list; a Settings change is detected, the cursor is kept
    total: int = 0
    cycles: int = 0  # completed passes through every slot
    runs: int = 0
    last_run_at: str = ""

    def to_json(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"))

    @classmethod
    def from_json(cls, raw: str | None) -> "RotationState":
        try:
            data = json.loads(raw or "")
            return cls(**{k: data[k] for k in cls.__dataclass_fields__ if k in data})
        except (ValueError, TypeError):
            return cls()


def plan_slots(state: RotationState, slots: Sequence[Slot], count: int) -> list[Slot]:
    """The next `count` slots from the persisted cursor (wrapping), never the same slot twice."""
    if not slots or count <= 0:
        return []
    start = state.cursor % len(slots)
    return [slots[(start + i) % len(slots)] for i in range(min(count, len(slots)))]


def advance(state: RotationState, slots: Sequence[Slot], used: int, now: datetime) -> RotationState:
    """Move the cursor past the slots actually started. Editing Settings changes the slot list;
    the cursor then continues modulo the new length instead of restarting at the head."""
    n = len(slots)
    if n == 0:
        return state
    position = (state.cursor % n) + used
    return RotationState(position % n, fingerprint(slots), n, state.cycles + position // n, state.runs + 1, now.strftime("%Y-%m-%dT%H:%M:%SZ"))


# --------------------------------------------------------------------------- engine


@dataclass(frozen=True)
class Query:
    id: str  # query identity for logs and the Discovery tab
    text: str
    tbs: str = ""  # Serper date window; "" = unfiltered (manual backfill only)


@dataclass
class QueryStats:
    id: str
    tbs: str = ""
    pages: int = 0
    credits: int = 0
    results: int = 0
    repeated: int = 0  # result already returned earlier in this run (same board/job identity)
    new_boards: int = 0  # board not in the registry before this run
    unseen_jobs: int = 0  # job identity not in the ledger and not returned earlier this run
    unparsed: int = 0  # result is not a supported ATS board/posting URL
    stop: str = ""  # why paging stopped: stalled | last_page | max_pages | budget | error
    error: str = ""


@dataclass
class DiscoveryResult:
    kind: str = KIND_ROTATION
    boards: list[BoardId] = field(default_factory=list)  # EVERY board found, new or known
    jobs: list[SerperJob] = field(default_factory=list)  # unseen job candidates only
    job_keys: set[str] = field(default_factory=set)  # every job identity returned (for reporting)
    queries: list[QueryStats] = field(default_factory=list)
    slots_used: int = 0  # queries started: the rotation cursor advances by this
    stopped: str = ""  # run-level stop reason (budget / exhausted)
    all_failed: bool = False  # every attempted request failed: do not advance the rotation

    @property
    def credits(self) -> int:
        return sum(q.credits for q in self.queries)

    @property
    def pages(self) -> int:
        return sum(q.pages for q in self.queries)

    @property
    def repeated(self) -> int:
        return sum(q.repeated for q in self.queries)

    @property
    def new_boards(self) -> int:
        return sum(q.new_boards for q in self.queries)

    def summary(self) -> list[dict[str, Any]]:
        return [asdict(q) for q in self.queries]


def run_queries(
    queries: Iterable[Query],
    search_page: Callable[[Query, int], list[Any]],
    *,
    budget: int,
    is_new_board: Callable[[BoardId], bool],
    is_unseen_job: Callable[[JobIdentity], bool],
    max_pages: int = DEFAULT_MAX_PAGES,
    stall_pages: int = DEFAULT_STALL_PAGES,
    kind: str = KIND_ROTATION,
    take_jobs: bool = True,
) -> DiscoveryResult:
    """Run queries page by page within a FIXED credit budget.

    A query stops paging after `stall_pages` consecutive pages that add neither a board candidate
    nor an unseen job candidate, after a short page, or at `max_pages`. The run stops when the
    budget is spent. Nothing here loops until "something new" turns up: all three bounds are hard.

    `search_page(query, page)` returns objects with `.url` and `.title`, and raises on failure."""
    res = DiscoveryResult(kind=kind)
    boards: dict[str, BoardId] = {}
    jobs: dict[str, SerperJob] = {}
    returned: set[str] = set()
    credits = attempted = failed = 0
    for q in queries:
        if credits + CREDITS_PER_REQUEST > budget:
            res.stopped = "budget"
            break
        st = QueryStats(q.id, q.tbs)
        res.queries.append(st)
        res.slots_used += 1
        attempted += 1
        stall = 0
        for page in range(1, max_pages + 1):
            if credits + CREDITS_PER_REQUEST > budget:
                st.stop, res.stopped = "budget", "budget"
                break
            credits += CREDITS_PER_REQUEST
            st.credits += CREDITS_PER_REQUEST
            try:
                hits = search_page(q, page)
            except Exception as exc:  # one failing request must not end discovery or hide earlier pages
                st.error, st.stop = f"{type(exc).__name__}: {exc}"[:200], "error"
                if page == 1:
                    failed += 1
                break
            st.pages += 1
            st.results += len(hits)
            gained = 0
            for hit in hits:
                board = parse_board_url(hit.url)
                ident = parse_job_url(hit.url)
                if board is None and ident is None:
                    st.unparsed += 1
                    continue
                key = ident.key if ident else board.key  # type: ignore[union-attr]
                if key in returned:
                    st.repeated += 1
                    continue
                returned.add(key)
                if ident:
                    res.job_keys.add(ident.key)
                # (1) the board is submitted whatever happens to this particular job
                board = board or ident.board_id  # type: ignore[union-attr]
                if board.key not in boards:
                    boards[board.key] = board
                    if is_new_board(board):
                        st.new_boards += 1
                        gained += 1
                # (2) the job is a candidate only if the ledger has never seen it
                if ident and take_jobs and ident.key not in jobs and is_unseen_job(ident):
                    jobs[ident.key] = SerperJob(ident, getattr(hit, "title", "") or "", hit.url)
                    st.unseen_jobs += 1
                    gained += 1
            if len(hits) < PAGE_SIZE:
                st.stop = "last_page"
                break
            stall = 0 if gained else stall + 1
            if stall >= stall_pages:
                st.stop = "stalled"
                break
        else:
            st.stop = st.stop or "max_pages"
        if not st.stop:
            st.stop = "max_pages"
    res.boards, res.jobs = list(boards.values()), list(jobs.values())
    res.all_failed = bool(attempted) and failed == attempted
    return res


# --------------------------------------------------------------------------- hydration retry queue


def load_pending(raw: str | None) -> dict[str, dict[str, Any]]:
    """Search-found jobs whose ATS read failed temporarily. Retried on later runs (no credits)."""
    try:
        data = json.loads(raw or "{}")
    except ValueError:
        return {}
    return {k: v for k, v in data.items() if isinstance(v, dict)} if isinstance(data, dict) else {}


def dump_pending(pending: dict[str, dict[str, Any]]) -> str:
    newest = sorted(pending.items(), key=lambda kv: kv[1].get("first_at", ""), reverse=True)[:MAX_PENDING_JOBS]
    return json.dumps(dict(newest), separators=(",", ":"))


def pending_entry(job: SerperJob, now: datetime, attempts: int = 1, first_at: str = "") -> dict[str, Any]:
    i = job.ident
    return {
        "ats": i.ats, "board": i.board, "id": i.job_id, "region": i.region, "title": job.title[:200], "url": job.url,
        "attempts": attempts, "first_at": first_at or now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }  # fmt: skip


def job_from_pending(entry: dict[str, Any]) -> SerperJob | None:
    try:
        return SerperJob(JobIdentity(entry["ats"], entry["board"], entry["id"], entry.get("region", "")), entry.get("title", ""), entry.get("url", ""))
    except KeyError:
        return None
