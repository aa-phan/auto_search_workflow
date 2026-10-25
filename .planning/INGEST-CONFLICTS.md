## Conflict Detection Report

Mode: merge. Sources: DECISIONS.md (ADR, locked by manifest), SPEC.md, AGENTS.md, STATUS.md, DEPLOY.md, PILOT_LOG.md, README.md; existing .planning/PROJECT.md, ROADMAP.md, STATE.md, codebase/CONCERNS.md. No UNKNOWN or low-confidence classifications. No PRDs in the set, so no competing acceptance variants. No existing locked CONTEXT.md decisions exist to contradict.

### BLOCKERS (0)

None. No two locked decisions contradict once explicit supersession chains are applied (see INFO), and no ingested decision contradicts an existing locked decision (none exist in .planning/).

### WARNINGS (6)

[WARNING] Reciprocal cross-reference cycles among the DOC sources (reported as a warning, not a blocker; synthesizer rule would otherwise block)
  Found: cross_refs form two cycles. AGENTS.md -> STATUS.md -> AGENTS.md (AGENTS-e4fe5945.json lists STATUS.md; STATUS-2a24e6b0.json lists AGENTS.md). STATUS.md -> PILOT_LOG.md -> STATUS.md (STATUS-2a24e6b0.json lists PILOT_LOG.md; PILOT_LOG-7da75da3.json lists STATUS.md).
  Impact: The synthesizer's cycle rule treats cycles as blockers because synthesis that follows references can loop. These are "see also" links between standalone documents, and extraction here read each document independently without following references, so no loop occurred. Treating them as blockers would exclude STATUS.md, the source of every verification state, and the user's docs are not expected to drop mutual links. Severity was lowered by judgment, not by rule.
  → Confirm the cycles are benign see-also links and approve proceeding, or tell the orchestrator to treat them as blockers and re-run with those references removed from the manifest cross-ref set.

[WARNING] Repository visibility: STATUS.md says public, a locked decision and DEPLOY.md say private
  Found: STATUS.md "Deployment and pilot status" lists "private-then-public repo". DECISIONS.md D-37 says the repository "is meant to be private" because git history still contains three job-search CSVs (scores and verdicts about the candidate). DEPLOY.md section 0 says "Keep the repository private; if you ever make it public, rewrite history first." CONCERNS.md "Repository visibility" says to confirm the intended visibility.
  Impact: Precedence (ADR over DOC) says private, but visibility is a fact about the world, not something precedence can resolve. If the repository is public, the old CSVs in history are exposed and the D-37/DEPLOY precondition (rewrite history first) was not met. This repo's own docs do not record whether history was rewritten.
  → Owner to confirm the current visibility. If public, decide on history rewrite or making it private, and record the outcome in DECISIONS.md (REQ-v2-owner-decisions-record).

[WARNING] Decisions that ask for owner confirmation have no recorded confirmation
  Found: DECISIONS.md D-16 title says "needs your OK" (Groq models deviate from the original request) and D-10 lists it; D-22 asks to confirm slot count and rotation length (since overtaken by D-35); D-30 lists the pool parameters (80/20, 7-day trials, weekly rebalance, 20 replacements, score weights, margin 1.0, two weak cycles, 84 polls) as "initial operating choices, not proven"; D-43 says "Decision requested: none yet" and the pilot ended 2026-10-22 without a recorded decision (CONCERNS.md).
  Impact: All entries are locked by manifest, but their confirmation state is unknown, and D-30 values are now acting on live data (D-45, D-47).
  → Owner to record explicit confirmations or changes in DECISIONS.md. The roadmapper should treat D-30 values as provisional until the first weekly rebalance evidence (due about 2026-10-29) is read.

[WARNING] Candidate v2 scope includes feature or tuning work that AGENTS.md rule 7 and STATUS.md gate
  Found: AGENTS.md rule 7 ("Do not tune scores or add features until freshness and delivery are proven (see STATUS.md)"); STATUS.md closes with "No score tuning or new features until these are read (AGENTS.md rule 7)", referring to the Next milestone items (first weekly rebalance, limits at 700, wider Settings, D-47 follow-up). v2 candidates derived in intel/requirements.md include a daily Telegram digest (feature), a title-gate leak fix (tuning) and structural work.
  Impact: Routing feature or tuning phases ahead of those readings would contradict the agent rules; behaviour-neutral work (tests, refactor, monitoring verification, bug fixes toward the contract) is not obviously gated. Pilot freshness and delivery criteria were met per STATUS, but the gate text was not lifted.
  → Decide whether the gate stays until the 2026-10-29 weekly rebalance is read, and sequence v2 phases accordingly. AGENTS.md rule 1 also requires updating the docs in the same change if the gate is changed deliberately.

[WARNING] Code paths in CONCERNS.md conflict with the SPEC contract; fixing them changes SPEC-visible behaviour
  Found: CONCERNS.md Known Bugs 1 and 2 (pipeline.py alert branch): a job is recorded `alerted` when `send_alert` returns False with no channel configured, and an exception without an HTTP response is retried without bound. Contract: AGENTS.md rule 4 and SPEC.md "State model" (a failure leaves later stages undone and retryable; non-recoverable failures bounded at 5 attempts) and SPEC.md "Definitions" (delivered alert = channel accepted the message). CONCERNS.md itself says the owner should confirm because it changes retry behaviour.
  Impact: Code and contract disagree. Production has Telegram configured (20 of 20 pilot alerts sent), so no live loss is known; the defect matters for a deployment without a channel or on a deterministic formatting error. AGENTS.md rule 1 requires flagging a conflict before changing behaviour.
  → Owner to confirm that the contract (SPEC) is the intended behaviour and approve the fix (REQ-v2-alert-recording-fix, REQ-v2-alert-exception-bound), with tests for both branches.

[WARNING] SmartRecruiters is polled in production against a provider robots.txt request (owner-accepted, D-38), while SPEC.md describes parking as the default
  Found: DECISIONS.md D-38 (owner unparked SmartRecruiters for the pilot; permission from SmartRecruiters unknown and not asked; reversal is deleting two workflow lines). SPEC.md "Provider limits honoured" keeps parking as the default and notes the pilot override. CONCERNS.md lists it as a high-severity compliance item and asks the owner to reconfirm. D-38 says it applied "for the seven-day pilot"; the pilot ended 2026-10-22 and no document records a decision to continue or revert, yet 94 SmartRecruiters boards were among those polled and the override is still in the workflows per CONCERNS.md.
  Impact: The deployed behaviour has outlived the stated scope of its decision. Precedence gives the locked decision force, but its time bound has passed without a new decision.
  → Owner to record whether the override continues past the pilot (new D-number) or to remove the two `ALLOW_SMARTRECRUITERS_BULK` lines; the reversal keeps history.

### INFO (13)

[INFO] Auto-resolved: SmartRecruiters policy chain, latest authoritative D-38 for this deployment
  Note: DECISIONS.md D-13 (park imported boards) -> D-19 (remove Serper exemption) -> D-27 (park monitored boards every run; resolves D-10 and D-22 open items) -> D-38 (unparked for the pilot by explicit owner decision). Later entries amend earlier ones explicitly, so not a contradiction. SPEC.md already reflects the chain (default parked, D-38 override noted).

[INFO] Auto-resolved: activation, pools and rebalance chain, latest authoritative D-47
  Note: DECISIONS.md D-14 (vacancy-only promotion, snapshot relevance) -> D-23 (relevance refreshed by every complete poll) -> D-26 (pools, weekly rebalance, report mode) -> D-32 (oscillation, rotation, slack fixes) -> D-45 (graduation floor 2.0; capacity 700 and mode `on` set by the user in the Sheet, code defaults stay 500 / report) -> D-47 (early release of below-floor trials between cycles). Each states "changes" or "amends" its predecessor. Note that the 500 default in SPEC/README and the 700 in production are both correct: default vs deployed Setting.

[INFO] Auto-resolved: discovery mechanics chain, latest authoritative D-36
  Note: DECISIONS.md D-06 (Serper inside discovery cadence) -> D-18 (rotating, budgeted, 336 slots, about 17 days a pass) -> D-35 (site x role only, 42 slots, about 2 days) -> D-36 (Serper -> Tavily; Google details dropped, rotation/admission/freshness rules unchanged). SPEC.md and README use the Tavily and 42-slot wording. PILOT_LOG.md notes the rotation length changed again on 2026-10-23 (6 sites x 36 roles after the Settings change).

[INFO] Auto-resolved: freshness window, baselining, retry, levels and registry-writer chains
  Note: D-04 -> D-17 (window 4 h -> 12 h; SPEC updated). D-05 -> D-24 (re-entry baseline). D-07 -> D-21 (pending alerts never discarded for age). D-08 -> D-25 (level matching). D-15 -> D-28 -> D-31 -> D-34 (writer ownership, serialization, "compare-and-set" wording corrected) -> D-37 (local production writes refused). D-29 -> D-47 (re-check budget 2,000 -> 5,000). D-44 -> D-46 (header fallback removed; SPEC "Delivery" updated). D-40 -> D-41 (dashboard visuals).

[INFO] Auto-resolved by log order: D-03 versus D-15 on how Boards rows are written
  Note: D-03 says `Boards` is "rewritten atomically in a single request"; D-15 (later) says registry writes are "row-level upserts of only the rows a run changed, never a full rewrite". D-15 does not name D-03 as amended, so this is an implicit supersession. Applied the log convention (later entry authoritative, SPEC "Board registry" and D-28/D-31 assume row-level writes). If the log should be strictly read as two contradicting locked decisions, this would be a blocker; it was judged an implicit amendment. Worth a one-line note in DECISIONS.md.

[INFO] Auto-resolved: SPEC (current) versus an older decision detail
  Note: D-41 says the dashboard data block is columns L:U; SPEC.md "Operational dashboard" says hidden block K:U. SPEC is updated with each change and wins. D-02's list of modules and "hunter.py ~1,400 lines" are historical; AGENTS.md "Layout" and CONCERNS.md (1,981 lines) are current.

[INFO] Auto-resolved: README.md is stale against higher-precedence sources (precedence 6)
  Note: README.md still says the first-run step is to tick "Also search Google for new company job boards" (D-36 replaced Google/Serper with Tavily); says an independent missed-run alert is "planned, not built" (D-42 built the watchdog; only the daily digest is not built); lists three hidden tabs (SPEC lists Boards, Events, Runs, Discovery, Inventory, Lock, Watchdog); calls Telegram variables optional (DEPLOY.md section 4 lists them as required); says "Jobs on boards we poll are detected within one successful hourly poll" and "noticed within about an hour" without the conditions D-34 and SPEC "Honest limits" require; says SmartRecruiters "stay parked whatever the source" without the D-38 deployment override beyond the opening note. D-34, D-36, D-38, D-42, DEPLOY.md and SPEC.md win.

[INFO] Auto-resolved: DEPLOY.md is partly historical (precedence 4) against STATUS.md and PILOT_LOG.md (higher precedence)
  Note: DEPLOY.md opens with "Nothing here has been run on GitHub yet: this repository has no remote" and section 9 says to hold `Rebalance_Mode=report` and the pilot parameters for seven days. STATUS.md and PILOT_LOG.md record the deployment, the completed pilot and the post-pilot Settings changes (700 boards, mode `on`). STATUS.md/PILOT_LOG.md win. DEPLOY.md also says `ALERT_WEBHOOK_URL` is unset; not contradicted.

[INFO] Auto-resolved: STATUS.md contains superseded sections beside current ones
  Note: Older sections still say "blocked" or "not verified" (no Sheet credentials, no GitHub remote, "Rebalancing never ran on the production registry (none exists yet: no Sheet credentials here)", SmartRecruiters imported boards parked, "Prepared, not yet deployed"). The section "Blockers" itself says these were superseded by the 2026-10-15 deployment. The "Pilot week 1 result", "Changes after the pilot" and "Next milestone" sections were used for verification state. The weekly rebalance cycle has still not run live; D-47 early release has.

[INFO] Noted, not a contradiction: SPEC polling cadence versus observed schedule
  Note: SPEC.md "Loops" specifies hourly 24/7 polling. STATUS.md shows the GitHub schedule fired about every 4.4 h (D-42 measured 4.7 h earlier) and the hourly cadence comes from an external trigger (168 `workflow_dispatch:external` runs); SPEC "Honest limits" already states the schedule is best-effort. Recorded in intel/constraints.md.

[INFO] Existing .planning files are superseded history (merge mode)
  Note: ROADMAP.md (one quick-task phase, "in progress", D-01..D-22) and STATE.md (focus "Board slot allocation", 2026-10-14) predate D-23 and omit D-31..D-47 and the pilot; ROADMAP.md says "in progress" while STATE.md says the quick task completed, with STATE.md the later record. Treated as non-locked history. PROJECT.md is consistent with AGENTS.md. REQUIREMENTS.md does not exist. Stale claims in CONCERNS.md: it says SPEC.md ~L41 "describes the default, not the deployed override", but SPEC L41 already cites D-38.

[INFO] Classification notes
  Note: DECISIONS-eddad1ec.json reports `locked: true` with a note that the classifier read only lines 1-50 and that locked status rests on the manifest assertion; the synthesizer read all 289 lines. D-10, D-22 and D-30 are locked entries that contain open items. AGENTS.md, STATUS.md, DEPLOY.md, PILOT_LOG.md and README.md are DOC (context only, no normative requirements were extracted from them except AGENTS.md rules referenced as binding in intel/constraints.md). Classification file names carry hash suffixes as expected.

[INFO] Inputs outside the manifest
  Note: NOTICE.md and CLAUDE.md exist in the repository root but are not in ingest-manifest.yaml and were not ingested; `legacy/` is archived reference only per AGENTS.md. Pointers in DECISIONS.md D-11 to NOTICE.md were left as pointers.
