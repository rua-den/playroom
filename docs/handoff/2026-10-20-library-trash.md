# Library Trash — 20 October 2026

## Owner request and scope

The owner noticed Library had no delete control and explicitly confirmed that deletion is needed in both the real local app and the theme preview. The three theme previews already demonstrate local confirmation and undo; those previews do not change owner data. The real feature is persistent reversible trash, with confirmation naming the story, an undo toast, and a durable Trash view with Restore.

Implementation starts from `ed0757bec4354f1040f2d46e786157db1285c98c` on `feat/library-trash-20261020` in the existing isolated checkout `D:/stu/worktrees/playroom-import-followup`. Current human routing requires gpt-5.6-luna medium for all implementation/tests and Sol orchestration, review and independent verification. Older Astra coding-owner text does not override that current instruction.

## Data behavior

Trash is nullable campaign metadata, separate from archive. Ordinary catalog/detail and shared branch lookup exclude trashed stories. Explicit owner-scoped routes list and restore trash. Immutable revisions, profiles, memory, scenes, imported sources and checkpoints remain intact. Campaign-wide trash is refused while any branch has outstanding generation work; the feature must not cancel a job, call a provider, or allow a stale preview to dispatch a deleted story.

Deleting the selected story returns to Library and clears its remembered selection. Deleting another story keeps the current selection and draft. Restore and toast Undo acknowledge the backend before changing the displayed result; neither automatically opens a story or sends an action.

## Verification record

Pre-change root baseline: 447 backend passed with one Windows platform skip; 184 frontend passed with three existing skips. Existing React act warnings were present in that frontend baseline.

Backend review is accepted after fixes for exact generation-key replay, terminal-job mutators and a cancellation-event write that initially occurred outside its protected transaction. The final root backend run passed 461 tests with one Windows platform skip in 107.40 seconds. Both guard rows and recoverable-job state are checked across campaign branches, including interrupted/candidate work. Historical terminal-job GET status/content/events remain owner-readable; new effective writes and generation requests for trash are rejected.

Root independently verified the final frontend: 196 passed with three existing skips; TypeScript checking and the Vite production build passed. Final Chromium verification passed all three flows: existing synthetic chat/import/review/toast gates, the new desktop/mobile trash flow, and the real local application assembly with a synthetic provider. The trash flow covers cancel, delete, undo, reload, restore and reopen without any provider calls. Independent whole-branch review accepted the production changes.

The original browser navigation checks used a generic card button locator; adding the new delete action correctly made that locator ambiguous. They now select the existing Open/Continue action explicitly, retaining the navigation and history assertions. Frontend regression tests additionally cover late Trash responses, pending/failed Undo, unrelated drafts, and reopening a story with a pending projection.

Exact pull-request/main CI and local runner release evidence belong in the associated pull request and final task report. This feature does not claim physical-phone or hosted deployment validation.

Tests use disposable synthetic data. The real `.playroom-live` owner database and credentials are not test fixtures. Before updating its runner, check for nonterminal generation, privately back up existing data and verify the new code without deleting an owner story or sending their content to a model.
