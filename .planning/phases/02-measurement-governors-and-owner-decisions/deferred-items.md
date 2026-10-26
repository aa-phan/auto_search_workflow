# Deferred items (phase 02)

Out-of-scope discoveries logged here instead of being fixed (scope boundary).

## From plan 02-04

- **`hunter.TokenBudget.wait` can raise `IndexError` (pre-existing, not caused by plan 02-04).** The loop is `if not self.events or self._used(now) + tokens <= self.tpm * 0.9: return`, then `time.sleep(... self.events[0][0] ...)`. `_used()` drops expired events, so when the 60-second window has just emptied and `tokens` alone is above `tpm * 0.9` (the pre-call estimate against a small per-minute limit, default `GROQ_TPM` 8000 so about 7,200 tokens), the `self.events[0]` read hits an empty deque. In production the exception would be caught by the generic handler in `make_evaluator` and recorded as a bounded "AI scoring failed" attempt. Found while writing `GroqDeadlineTests` (the test uses a large `tpm` to avoid it). Not fixed here: it is a behaviour change to the scoring path outside MEAS-04; suggested follow-up is to re-check `if not self.events` after `_used()` (or `return` when the window is empty).
