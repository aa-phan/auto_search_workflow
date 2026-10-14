"""Deterministic eligibility gates applied before resume-fit scoring (SPEC.md "Filtering order").

Two stages, both conservative (reject only on clear, explicit signals; the LLM judges fit):
  title_gate: listing title only, runs before any fetch (most board jobs are irrelevant).
  hard_gate:  hydrated posting (location, minimum years, required language).
Both return a human-readable rejection reason, or None to continue. Ported from the archived
keyword scorer in legacy/ (location, seniority and language rules were reliable; its skill
clusters are not reused).
"""

from __future__ import annotations

import re

HARD_YEARS = 4  # minimum required years that disqualifies an early-career candidate

_EXPERIENCE_RE = re.compile(
    r"\b(\d{1,2})\s*(?:\+|plus)?(?:\s*(?:-|–|—|to)\s*(\d{1,2}))?\s*(?:\+|plus)?\s*years?\b"
    r"[^.\n]{0,40}\b(?:experience|exp|background|track record|in\s+marketing|in\s+social"
    r"|in\s+content|in\s+design|in\s+a\s+similar)\b",
    re.I,
)
_NON_US_RE = re.compile(
    r"\b(uk|united kingdom|london|canada|toronto|vancouver|ontario|latam|brazil|(?<!new )mexico"
    r"|colombia|argentina|emea|europe|germany|berlin|spain|france|india|apac|singapore|australia"
    r"|philippines|pakistan|uae|dubai|türkiye|turkey|poland|romania|portugal|italy|netherlands"
    r"|ireland|nigeria|kenya|south africa|egypt|israel|vietnam|thailand|indonesia|malaysia|taiwan"
    r"|japan|korea|chile|peru|costa rica|austria|sweden|denmark|norway|finland|switzerland|belgium)\b",
    re.I,
)
_US_MARKER_RE = re.compile(
    r"\b(?:US|USA|U\.S\.A?|TX|NY|NYC)\b|\b(?:United States|North America|Austin|San Antonio|Texas|New York)\b", re.I
)
_US_CASE_SENSITIVE = re.compile(r"\b(?:US|USA|U\.S\.A?|TX|NY|NYC)\b")  # avoid the pronoun "us"
_LANGUAGES = "spanish|mandarin|cantonese|french|german|portuguese|japanese|korean|arabic"
_LANG_REQ_RE = re.compile(
    rf"\b(?:bilingual|fluency|fluent|proficiency|proficient)\s+(?:in\s+)?({_LANGUAGES})\b"
    rf"|\b({_LANGUAGES})\s+(?:language\s+)?(?:is\s+)?(?:required|mandatory|a must)\b",
    re.I,
)


# Morphological variants of level words, applied only when the user's own Target_Levels contains
# the word (regex fragments). "Internship" and "Jr." are the same level signal as "Intern" and
# "Junior"; nothing else is widened (D-25).
_LEVEL_VARIANTS = {"intern": [r"internship"], "junior": [r"jr\.?"]}


def _term_pattern(term: str) -> str:
    """One configured term as a regex: inside the term a space and a hyphen are interchangeable
    ("Entry Level" also matches "Entry-Level")."""
    tokens = [re.escape(t) for t in re.split(r"[\s-]+", term.strip()) if t]
    return r"[\s-]+".join(tokens)


def _term_re(terms: list[str], variants: dict[str, list[str]] | None = None) -> re.Pattern[str] | None:
    parts: list[str] = []
    for t in terms:
        if not t.strip():
            continue
        parts.append(_term_pattern(t))
        parts.extend((variants or {}).get(t.strip().lower(), []))
    parts = [p for p in parts if p]
    if not parts:
        return None
    return re.compile(rf"(?<![A-Za-z0-9])(?:{'|'.join(parts)})s?(?![A-Za-z0-9])", re.I)


def title_gate(
    title: str,
    roles: list[str],
    levels: list[str],
    excluded: re.Pattern[str] | None,
    *,
    require_level: bool = True,
) -> str | None:
    """Reject titles that are excluded, or lack a target-role keyword, or lack a level keyword."""
    if excluded and (m := excluded.search(title)):
        return f"excluded title word '{m.group(0)}'"
    role_re, level_re = _term_re(roles), _term_re(levels, _LEVEL_VARIANTS)
    if role_re and not role_re.search(title):
        return "no target role keyword in the title"
    if require_level and level_re and not level_re.search(title):
        return "no target level keyword in the title"
    return None


def min_years_required(text: str) -> int | None:
    """Largest MINIMUM years of experience the text demands (ranges use their lower bound)."""
    best: int | None = None
    for m in _EXPERIENCE_RE.finditer(text):
        lo = int(m.group(1))
        best = lo if best is None else max(best, lo)
    return best


def location_blocks(location: str) -> str | None:
    """The hard gate's non-US location rule on its own (also used to count a board's eligible
    jobs). An empty location is not excluded; a listing naming a US place beside a foreign one is not."""
    loc = location or ""
    if _NON_US_RE.search(loc) and not (_US_CASE_SENSITIVE.search(loc) or re.search(r"United States|North America|Austin|San Antonio|Texas|New York", loc, re.I)):
        return f"location is outside the US ({loc[:60]})"
    return None


def hard_gate(title: str, location: str, text: str, resume: str) -> str | None:
    """Reject only on explicit signals found in the hydrated posting."""
    if blocked := location_blocks(location):
        return blocked
    years = min_years_required(text)
    if years is not None and years >= HARD_YEARS:
        return f"requires {years}+ years of experience"
    if re.search(r"\bbilingual\b", title, re.I) and not re.search(r"\bbilingual\b", resume, re.I):
        return "title requires bilingual ability"
    for m in _LANG_REQ_RE.finditer(f"{title}\n{text}"):
        lang = (m.group(1) or m.group(2) or "").lower()
        if lang and not re.search(rf"\b{lang}\b", resume, re.I):
            return f"requires {lang}, which is not on the resume"
    return None
