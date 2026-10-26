# Phase 2: Measurement, governors and owner decisions - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-10-25
**Phase:** 2-Measurement, governors and owner decisions
**Areas discussed:** Groq token budget, Run deadline & order, Dashboard yield view, Owner decisions now

---

## Groq token budget

| Option | Description | Selected |
|--------|-------------|----------|
| Settings tab | `Groq_Daily_Token_Budget` row, changeable without deploy | ✓ |
| Env / Actions variable | Next to GROQ_TPM / MAX_JOBS_PER_RUN | |

| Option | Description | Selected |
|--------|-------------|----------|
| 85% of the limit | Room for drift and manual calls | ✓ |
| 90% of the limit | A few more evaluations | |
| 75% of the limit | Most cautious | |

| Option | Description | Selected |
|--------|-------------|----------|
| Separate budget per model | Fallback 20b scores after primary budget is spent | ✓ |
| Primary model only | Fallback on 429 only, as today | |
| One combined budget | Simpler, doesn't match how Groq counts | |

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, keep a reserve | Last ~20% for verified-fresh only | ✓ |
| No, priority order is enough | | |

**Notes:** Budget-driven use of the fallback model is recorded as the owner's OK under D-16; the scoring rule itself is unchanged (rule 7).

---

## Run deadline & order

| Option | Description | Selected |
|--------|-------------|----------|
| Staged cutoffs | Polls stop ~15 min, Groq ~20 min, ~5 min for writes | ✓ |
| Tighter: 12.5 min total | Matches the Phase 5 p95 gate | |
| You decide | From measured phase times | |

| Option | Description | Selected |
|--------|-------------|----------|
| Longest-unpolled first | Skipped boards go first next run | ✓ |
| Best boards first | Weak boards could starve | |

| Option | Description | Selected |
|--------|-------------|----------|
| Split by stage | Poll cut = degraded; eval/budget cut = ok + note | ✓ |
| Always degraded | | |
| Always ok + note | | |

| Option | Description | Selected |
|--------|-------------|----------|
| Keep as a safety cap | MAX_JOBS_PER_RUN 30 stays as a backstop | ✓ |
| Remove it | | |
| You decide | | |

---

## Dashboard yield view

| Option | Description | Selected |
|--------|-------------|----------|
| Day found, your timezone | Date_Found in Settings Timezone | ✓ |
| Day published | | |

| Option | Description | Selected |
|--------|-------------|----------|
| ≤1h · 1-12h · 12-24h · 24-72h · older · unknown | Matches the 12 h and 72 h lines | ✓ |
| ≤12h · 12-72h · older · unknown | | |

| Option | Description | Selected |
|--------|-------------|----------|
| Stacked per day + feedback per cohort | verified-fresh / Recent / other | ✓ |
| Separate totals only | | |

| Option | Description | Selected |
|--------|-------------|----------|
| Top chart with 20-30 target band | Mismatch under Needs attention only when not 0 | ✓ |
| New section below | | |
| You decide | | |

---

## Owner decisions now

| Option | Description | Selected |
|--------|-------------|----------|
| Measure first, then decide | Groq plan chosen with real limits before phase close | ✓ |
| Stay on free tier | | |
| Move to a paid plan | | |

| Option | Description | Selected |
|--------|-------------|----------|
| Park it | SmartRecruiters back to D-19/D-27 | ✓ |
| Keep it unparked | | |
| Decide after the Alphabe check | | |

| Option | Description | Selected |
|--------|-------------|----------|
| Stay public, fix the docs | DEPLOY.md updated | ✓ |
| Make it private | | |

| Option | Description | Selected |
|--------|-------------|----------|
| At Phase 4 | D-05 amendment listed with default "no backfill" | ✓ |
| Approve now | | |

**Notes:** Date-only alerts were already decided by the owner on 2026-10-25 (ADPT-07); not re-asked, only to be recorded.

## Claude's Discretion

- MEAS-05 mechanics (no-channel handling, exception classification), Telegram truncation fix if small
- Exact reserve share and cutoff values; Settings vs constants
- Token budget day boundary (rolling vs calendar), once Groq's reset is measured
- New `Runs` column names; how the Groq limits are captured (page vs headers), with source recorded

## Deferred Ideas

- D-05 amendment (Phase 4), rule-7 lift (Phase 5), per-ATS terms (Phase 6/7), 20b pre-screen / prompt cuts (rule 7, own decision), EVID-01 rebalance read (Phase 5)
