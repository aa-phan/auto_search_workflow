# PILOT LOG

Deployment times and material corrections during the seven-day pilot, so the final pilot report can name the periods each one affects. Times are UTC. **Commits are deployed by pushing to `main`** (the workflows run the code on `main`), so a commit's push time is its deployment time; from 2026-10-17 `Runs.Code_Version` records the commit that ran each poll and `--pilot-report` lists the versions seen (an `untagged` version means a run from before that column existed). Update this file in the same change as any deployment that could affect a measurement.

## Pilot parameters held constant (DEPLOY.md section 9)

`Max_Active_Boards` 500 (400 / 100 pools), `Rebalance_Mode` report, scoring and `Min_Alert_Score`, eligibility and title/level rules, discovery strategy and budget. **Nothing in this log changes them.** Changes below are instrumentation, reporting, reliability and documentation unless stated.

## Timeline

| UTC time | Commit | What was deployed | Affects |
|---|---|---|---|
| 2026-10-15 01:47 | (16bbff0 / d8eb44c) | **First production run: the pilot starts here** (the pilot report now measures from this moment) | all windows |
| 2026-10-15 01:53 | 2c75342 | Sheets quota 429 is retried after the quota window; runs wait for a crashed run's lease (the 01:21-01:53 failures, see below) | one failed run at 01:53; none since |
| 2026-10-15 02:12 | 14ba1fa | **SmartRecruiters unparked** for the pilot (D-38): its boards are polled from here, 94 of the 500 monitored today | board polls per run, ATS request counts, jobs found: not comparable before this |
| 2026-10-15 02:25 | 3d0c5e9 | Per-run diagnostics (`Duration_S`, request counts, ...) | limits audit has no data before this |
| 2026-10-15 03:24 - 06:45 | 4c0b7c3, 5cc8916, 6c72154 | Temporary schedule probe added and removed; `trigger_source` input so the external hourly dispatch is recorded as `workflow_dispatch:external` | trigger counts; the 225-minute polling gap (02:55 to 06:40) lies in this period, before the external trigger was recorded |
| 2026-10-15 07:05 | f7e6907 | Re-check flip statistics recorded | none |
| 2026-10-15 20:26 | 8562e99 | Tracker `Rejected` status and row colours | none on measurements |
| 2026-10-16 00:07 | 96ee910 | Dashboard tab, **run-start records, run IDs, outcomes, run kind, credit status**, rejection reason codes on evaluations (D-40) | runs before this have no outcome (counted as successful polls only because they finished, see "unrecorded" in the report); evaluations before this are classified from their verdict text |
| 2026-10-16 20:45 - 20:58 | 919e0b9 .. db55dee | Dashboard charts and layout (D-41) | the Dashboard tab only |
| 2026-10-17 19:30 | 6291a5b | **Missed-run watchdog workflow** (D-42), **pilot-report corrections**, `Code_Version` column, storage report | see "Material corrections" |
| 2026-10-17 19:33 | 3b41c83 | Storage report projections | none |
| 2026-10-19 02:45 | 0447ad0 | Tracker written and read by header name (D-44) | tracker placement only |
| 2026-10-22 01:47 | | **Seven-day pilot window ends** (168 of 168 hourly intervals polled; see STATUS "Pilot week 1 result") | end of the pilot measurement |
| 2026-10-23 20:52 | 76726a6 | Graduation floor (D-45) and tracker header refusal (D-46); Settings changed at the user's request at the same time: `Max_Active_Boards` 700 and `Rebalance_Mode` on | **post-pilot: parameters held constant above change here**; board counts, polls per run, ATS requests and Events growth are not comparable across this point |
| 2026-10-23 21:21 | (Settings only) | Title and location Settings broadened at the user's request (written through the Sheets connector, read back): `Target_Roles` +17 (graphic / visual / motion design, video, editorial, copywriting, paid and planned media, influencer, website), `Target_Levels` +19 (early-career words and unqualified job nouns such as Analyst, Strategist, Designer, Writer, Editor, Producer), `Excluded_Title_Words` +11 (sales, accounting, customer service / support / success, moderation, social worker), `Target_Locations` + US Hybrid, Dallas, Houston | relevant-job counts, board relevance and eligible counts, Groq calls, tracker inflow and the search rotation length (6 sites x 36 roles) are not comparable across this point; the 2026-10-29 rebalance mixes evidence from both rules |

## Material corrections (reporting only; no behaviour changed)

1. **Pilot report denominator (2026-10-17 19:30).** Earlier pilot reports divided runs by a nominal 7 days (168 hourly slots) and printed "82 of 168 (49%)" when the pilot was 65 hours old. It now measures from the first production run and counts distinct hourly intervals with a successful poll (63 of 65, 96.9%). Any figure quoted from an earlier report as a rate over "7 days" is understated.
2. **Coverage populations (same change).** "35%" is boards with an open relevant job that have a slot / all known boards with an open relevant job (the `Runs.Relevant_Coverage_Pct` definition); "500 of 1,332 = 37.5%" counts every monitored board including those with nothing open. Both are now printed with their populations. Neither is coverage of the job market.
3. **Detection latency (same change; dashboard too).** It used to be the verified-fresh subset only (which cannot show a late detection by construction). It is now every relevant new posting with a time-precise publication time (n and unknown-date counts printed); the verified-fresh subset is still shown. Quote latency from before this change as "verified-fresh subset".
4. **Feedback and tracker counts** exclude labelled test fixtures (two rows) in the pilot report as the dashboard already did.
5. **Headline counts reconciled** with explicit windows and populations (see the report's RECONCILIATION section): the dashboard's "24 verified fresh of 30 kept" and the pilot report's "25 alerts" were generated 44 minutes apart (18:02 and 18:46 UTC) over different windows (calendar days in the Sheet's time zone against exact timestamps); at one instant the figures agree (25 alert-eligible fresh jobs, 25 alerted).

## Tracker column move (2026-10-18)

The user moved `My_Feedback` to column D; rows written after the move (rows 38 to 44, Date_Found 2026-10-18 and the night before) were appended one column off because the app wrote by fixed position. **Affected period:** from the first row written after the move until the repair, 2026-10-18 2026-10-19 02:45 UTC. **Effect on measurements:** the pilot report's and dashboard's feedback counts read those seven rows' `My_Feedback` as numeric "other text" and left their real label blank; duplicate-row protection read the wrong column. Ledger-based counts (jobs, alerts, tracker additions) were not affected. Repaired by hand in the Sheet; the code now writes by header name (D-44, deployed 2026-10-19 02:45 UTC in 0447ad0).

## Earlier failed runs (not affecting the pilot window)

Five workflow runs failed between 2026-10-15 01:21 and 01:53 UTC during setup (two missing-secret checks, an empty resume, a Groq key error in the delivery test, and one Sheets read-quota 429). The pilot's first production run is 01:47; the 01:53 failure is the only failed run inside the window, and the 429 retry fix deployed seconds later has held since.

## Watchdog

Deployed 2026-10-17 19:30 (6291a5b). Live dry run at 19:31 against the production Runs tab: `HEALTHY`, last success 29 minutes before, no state written, no message sent. The first real outage or recovery notification has not happened and has not been tested live (see DEPLOY.md "Watchdog" for what remains).

## Tracker header cleared (2026-10-22 to 2026-10-23)

Row 1 of the Job Tracker was cleared between the rows written 10/22 12:04 PM and 10/22 10:03 PM Central (a manual edit; no code writes row 1). The next append filled row 1 with a job, and that row plus the three written on 10/23 went in by fixed position (score under `My_Feedback`). **Effect on measurements:** from then on the pilot report and dashboard keyed tracker rows by that job's values: the 2026-10-23 20:17 UTC report's tracker reconciliation ("0 distinct jobs, 77 without a recognizable job URL") and feedback counts ("unlabelled 77") are wrong; ledger-based counts (jobs, alerts, evaluations) are not affected. **Repaired** 2026-10-23 about 20:50 UTC through the Sheets connector (header restored in the user's order, four rows rewritten at rows 76 to 79); the code now refuses to write without a header (D-46, from its deployment).
