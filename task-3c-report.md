# Task3C report

Base: `e6a6c04`

## Finding map

- Critical director lifecycle / required narrator overflow: closed. Quality now serializes and validates the exact required narrator system/user wire before director dispatch. Overflow fails the terminal job, interrupts the queued director attempt, releases the branch guard, and makes zero provider calls.
- Critical economy `ContextRun` atomicity: closed. Economy context insert and guarded `final_context_json` CAS run under one `BEGIN IMMEDIATE` transaction. A lost CAS rolls back the insert.
- Mandatory local HTTP/runtime matrix: existing coverage remains partial and is deferred. Quality SSE disconnects at director, after director completion, and during narration; real-app zero-row cancellation race; and the complete queued/running effective mutation inventory still need targeted tests.
- Mandatory wire/cost threshold matrix: existing coverage remains partial and is deferred. Fractional aggregate rejection, known expensive director exhausting narrator allowance, unknown director reservation retention, and exact emitted-wire/hash/count equality need targeted tests.

## Changes

- `GenerationService._narrator_request(..., required_only=True)` exposes the shared required-wire pack/count path for preflight.
- `_save_context_run` now wraps economy writes atomically while preserving quality's existing outer completion transaction.
- Added regressions in `backend/tests/test_generation_fix4.py` for zero-call required overflow and CAS rollback.

## Verification

- `rtk proxy .venv\\Scripts\\python -m pytest backend\\tests\\test_generation_fix4.py -k "required_narrator_wire_overflow_preflights_before_director or context_run_insert_rolls_back_when_final_context_cas_loses" -q` -> 2 passed
- `rtk proxy .venv\\Scripts\\python -m pytest backend\\tests\\test_generation_fix4.py -q` -> 10 passed
- `rtk proxy .venv\\Scripts\\python -m pytest backend\\tests -q` -> 127 passed
- `rtk proxy .venv\\Scripts\\python -m compileall -q backend` -> passed
- `rtk git diff --check` -> clean

## API and gaps

No public API or wire schema changes. The optional internal `required_only` flag uses the same persisted packer and metadata path. Remaining HTTP/runtime and cost threshold proofs above are intentionally recorded as open for the parent acceptance review.
