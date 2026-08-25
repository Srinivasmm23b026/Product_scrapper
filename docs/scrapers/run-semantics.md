# Scrape run semantics

Every V1 scrape begins by committing a `running` run record. The adapter then returns a structured
result containing observations, objective expected-count data where available, page failures,
warnings, and a positive completeness signal.

## Status classification

| Outcome | Status |
|---|---|
| Adapter raises before producing a result | `failed` |
| Zero observations and one or more page failures | `failed` |
| Zero observations without page failures | `suspicious_zero` |
| Some observations but failed pages, no completeness signal, or count mismatch | `partial` |
| Nonzero observations, completeness signal, no failed pages, expected count matches | `complete` |
| Previously running record exceeds the recovery threshold | `interrupted` |

A successful HTTP status is not a completeness signal.

## Transactions

- Starting the run is committed separately so crashes remain visible.
- All observations, current-offer updates, absence counters, and terminal run metadata are written
  in one transaction.
- A persistence exception rolls back that entire transaction, then records the run as failed in a
  fresh transaction.
- Every new observation references its run. A null run is reserved for explicitly labeled legacy
  migration data.
- Duplicate observations for one offer in one result are rejected rather than silently appended.

## Product absence

Seen offers reset `consecutive_misses` in complete and partial runs. Missing offers advance their
counter only after a trustworthy `complete` run for that supplier location. Failed, partial,
suspicious-zero, and interrupted runs cannot retire an offer.

The current V1 default retires an offer after three complete-run misses. Retirement means
`active=false` and current availability false; historical observations are never modified.

