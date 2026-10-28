# Deferred items (phase 02)

Out-of-scope discoveries logged here instead of being fixed (scope boundary).

## From plan 02-04

- **`hunter.TokenBudget.wait` can raise `IndexError` (pre-existing, not caused by plan 02-04).** The loop is `if not self.events or self._used(now) + tokens <= self.tpm * 0.9: return`, then `time.sleep(... self.events[0][0] ...)`. `_used()` drops expired events, so when the 60-second window has just emptied and `tokens` alone is above `tpm * 0.9` (the pre-call estimate against a small per-minute limit, default `GROQ_TPM` 8000 so about 7,200 tokens), the `self.events[0]` read hits an empty deque. In production the exception would be caught by the generic handler in `make_evaluator` and recorded as a bounded "AI scoring failed" attempt. Found while writing `GroqDeadlineTests` (the test uses a large `tpm` to avoid it). Not fixed here: it is a behaviour change to the scoring path outside MEAS-04; suggested follow-up is to re-check `if not self.events` after `_used()` (or `return` when the window is empty).

## From plan 02-08 (Task 1)

- **Pilot report `completions per day` is not a daily rate (pre-existing, from plan 02-06).** `pilot.py` computes `groq_completions_per_day` as the sum of `Groq_Completions` over timed runs divided by the whole report span (`span_days`, 7 days), but the Groq columns only exist from 2026-10-26 19:00 UTC, so the figure understates the rate (13.7 reported against about 75 scoring calls on the complete UTC day 2026-10-27, derived from tokens / tokens per call). Not fixed in 02-08 (measurement-display change outside this plan's files). Suggested follow-up: divide by the span of runs that recorded the columns, or print calls per UTC day next to the tokens per UTC day line. 02-08 STATUS uses tokens per UTC day and the derived call count instead.
