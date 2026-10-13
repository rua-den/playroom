# Chat and Story First Implementation Plan

> **For agentic workers:** Use subagent-driven implementation; steps use checkbox syntax so progress can be tracked.

**Goal:** Make Playroom feel like a simple roleplay chat with one Send action, automatic saving of valid narrator replies, and scene-specific non-repetitive narration.

**Architecture:** Keep the durable generation job and candidate validation API. The frontend automatically commits a validated candidate as soon as it observes completion, refreshes the story projection, and presents only one gameplay action in the composer. Strengthen the existing narrator system prompt without changing context selection or output validation.

**Tech Stack:** React, TypeScript, Vitest, Python, pytest, SQLite-backed generation service.

**Spec:** `docs/superpowers/specs/2026-10-13-chat-story-first-design.md`

## Global Constraints

- Interpret player `**...**` spans as action/thought and ordinary text as dialogue.
- Show one gameplay button, Send; Enter submits and Shift+Enter inserts a newline.
- Automatically commit successful, schema-valid narrator replies; do not require per-turn player approval.
- Preserve stable character IDs/profile-version attribution, raw player input, existing persisted fields, and legacy display.
- Keep context selection, canon precedence, memory eligibility, billing, caps, provider configuration, and campaign data behavior unchanged.
- Do not call a real model, deploy, publish, reset, clean, or discard existing worktree changes.
- Leave the current worktree changes unstaged and uncommitted; touch only files listed under each task.

---

## File map

- `frontend/src/components/GenerationComposer.tsx`: composer keyboard behavior, single Send button, completion polling, auto-commit, and compact status handling.
- `frontend/src/components/GenerationComposer.test.tsx`: UI regression coverage for one-button send, IME/keyboard handling, auto-commit, failures, and recovery.
- `frontend/src/styles.css`: composer layout and compact progress/details styling, only if existing styles cannot express the approved layout.
- `backend/playroom/generation.py`: narrator system prompt instructions only.
- `backend/tests/test_generation_durable.py`: prompt content regression test beside the existing validated narrator wire test.

### Task 1: One-button chat composer and automatic reply commit

**Files:**
- Modify: `frontend/src/components/GenerationComposer.tsx`
- Modify: `frontend/src/components/GenerationComposer.test.tsx`
- Modify only if needed: `frontend/src/styles.css`

**Interfaces:**
- Keep the existing `GenerationComposer` props: `ownerId`, `projection`, `profileId`, and `onCommitted`.
- Use existing `api.commitGeneration(jobId)` and `onCommitted()` as the validated commit and projection-refresh path; do not add an endpoint or weaken backend state checks.
- Keep the existing `generationIdentityKey` storage key so an interrupted client can recover a completed candidate and auto-commit it.

- [ ] **Step 1: Write failing tests first**

In `GenerationComposer.test.tsx`, add these behavior tests using the existing `projection`, React Testing Library, and mocked `fetch` pattern:

```tsx
it("submits with Enter, keeps Shift+Enter as a newline, and ignores IME Enter", async () => {
  localStorage.clear();
  const preview = { id: "preview-enter", campaign_id: "campaign-1", branch_id: "branch-1", checkpoint_id: "checkpoint-1", action: "Xin chào\\n", status: "ready", profile_id: "profile-1" };
  const queued = { id: "job-enter", campaign_id: "campaign-1", branch_id: "branch-1", checkpoint_id: "checkpoint-1", status: "queued", draft: "", offset: 0, offset_unit: "utf16_code_units" };
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(new Response(JSON.stringify(preview), { status: 201 }))
    .mockResolvedValueOnce(new Response(JSON.stringify(queued), { status: 201 }));
  vi.stubGlobal("fetch", fetchMock);
  const user = userEvent.setup();
  render(<GenerationComposer ownerId="owner-1" projection={projection} profileId="profile-1" onCommitted={vi.fn()} />);
  const input = screen.getByLabelText("Hành động tiếp theo");
  await user.type(input, "Xin chào");
  await user.keyboard("{Shift>}{Enter}{/Shift}");
  expect(input).toHaveValue("Xin chào\\n");
  expect(fetchMock).not.toHaveBeenCalled();
  fireEvent.keyDown(input, { key: "Enter", keyCode: 229, isComposing: true });
  expect(fetchMock).not.toHaveBeenCalled();
  await user.keyboard("{Enter}");
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
});

it("shows one Send action and no candidate action buttons", () => {
  render(<GenerationComposer ownerId="owner-1" projection={projection} profileId="profile-1" onCommitted={vi.fn()} />);
  expect(screen.getByRole("button", { name: "Gửi" })).toBeEnabled();
  expect(screen.queryByRole("button", { name: /Hủy|Lưu bản nháp|Commit|economy/i })).not.toBeInTheDocument();
});

it("automatically commits a recovered candidate and refreshes the story", async () => {
  localStorage.clear();
  localStorage.setItem(generationIdentityKey("owner-1", "campaign-1", "branch-1"), JSON.stringify({ ownerId: "owner-1", campaignId: "campaign-1", branchId: "branch-1", checkpointId: "checkpoint-1", action: "Ứng viên cũ", previewId: "preview-old", idempotencyKey: "key-old", jobId: "job-10" }));
  const candidate = { id: "job-10", campaign_id: "campaign-1", branch_id: "branch-1", checkpoint_id: "checkpoint-1", status: "candidate", action: "Ứng viên cũ", draft: "Kết quả", offset: 7, offset_unit: "utf16_code_units" };
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(new Response(JSON.stringify(candidate)))
    .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true })));
  vi.stubGlobal("fetch", fetchMock);
  const onCommitted = vi.fn().mockResolvedValue(projection);
  render(<GenerationComposer ownerId="owner-1" projection={projection} profileId="profile-1" onCommitted={onCommitted} />);
  await waitFor(() => expect(onCommitted).toHaveBeenCalledOnce());
  expect(fetchMock).toHaveBeenCalledTimes(2);
  expect(localStorage.getItem(generationIdentityKey("owner-1", "campaign-1", "branch-1"))).toBeNull();
});

it("keeps the player input and re-enables Send when generation fails", async () => {
  localStorage.clear();
  const preview = { id: "preview-error", campaign_id: "campaign-1", branch_id: "branch-1", checkpoint_id: "checkpoint-1", action: "Xin chào", status: "ready", profile_id: "profile-1" };
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(new Response(JSON.stringify(preview), { status: 201 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ message: "provider unavailable" }), { status: 503 }));
  vi.stubGlobal("fetch", fetchMock);
  const user = userEvent.setup();
  render(<GenerationComposer ownerId="owner-1" projection={projection} profileId="profile-1" onCommitted={vi.fn()} />);
  const input = screen.getByLabelText("Hành động tiếp theo");
  await user.type(input, "Xin chào");
  await user.click(screen.getByRole("button", { name: "Gửi" }));
  expect(await screen.findByRole("alert")).toBeInTheDocument();
  expect(input).toHaveValue("Xin chào");
  expect(screen.getByRole("button", { name: "Gửi" })).toBeEnabled();
});
```

The candidate response and localStorage identity match the existing recovered-candidate fixture. While pending or while the job is queued/running/cancelling, the same Send button must be disabled and show progress; do not add a Cancel or alternate retry button.
- [ ] **Step 2: Run the targeted test and verify RED**

Run from `frontend`:

```powershell
rtk npm test -- GenerationComposer.test.tsx
```

Expected: new assertions fail because Enter currently inserts a newline, candidate approval is manual, and extra action buttons render.

- [ ] **Step 3: Implement the smallest frontend change**

Update the existing form to submit on Enter only when Shift is not pressed and the event is not an IME composition. Keep Shift+Enter multiline. Use the existing submit path for exactly one composer button labelled `Gửi`; while work is active, disable that button and show a concise progress label.

When polling, startup recovery, or a generation response reports `status === "candidate"`, call the existing `api.commitGeneration(job.id)` once for that job. After success, await `onCommitted()`, remove the generation identity from localStorage, clear the completed job/draft/action state, and render the refreshed projection. Guard duplicate polling with a ref keyed by job ID. On commit failure, preserve the candidate identity and show an inline error so the same Send flow can retry; do not render candidate action buttons.

Remove visible cancel, save-draft, commit-candidate, commit-and-continue, and economy-retry buttons from the play surface. Preserve the existing free-economy fallback: when a quota error enables that fallback, the next click of the same Send button retries with economy/free-only policy and the inline error explains this. Keep stage counts, usage/cost, and raw generation data inside a collapsed `<details>` disclosure. Preserve the current player input on provider failure so Send can retry. Keep navigation and settings controls outside the composer unchanged.

- [ ] **Step 4: Run focused and frontend verification**

Run from `frontend`:

```powershell
rtk npm test -- GenerationComposer.test.tsx
rtk npm run typecheck
```

Expected: all composer tests pass and TypeScript reports no errors.

### Task 2: Context-specific narrator instructions

**Files:**
- Modify: `backend/playroom/generation.py`
- Modify: `backend/tests/test_generation_durable.py`

**Interfaces:**
- Keep `GenerationService._narrator_request(...)` request shape and `NARRATOR_SCHEMA` unchanged.
- Keep validated director selection, selected-character IDs, and profile-version IDs authoritative.

- [ ] **Step 1: Extend the existing narrator-wire test first**

In `test_quality_narrator_wire_uses_only_validated_director_selection`, after building `wire`, assert that the narrator system message includes all of the following behavior requirements:

```python
system = provider.calls[-1]["messages"][0]["content"]
assert "Respond to the latest player action or dialogue" in system
assert "Avoid generic atmosphere-setting" in system
assert "Advance the scene with a concrete reaction, consequence, or change" in system
assert "Preserve each selected character's established voice and knowledge" in system
assert "Leave the player-controlled character's actions and thoughts to the player" in system
assert "Do not force A/B choices, quests, stats, or other game mechanics" in system
```

- [ ] **Step 2: Run the targeted backend test and verify RED**

Run from the repository root:

```powershell
rtk pytest backend/tests/test_generation_durable.py::test_quality_narrator_wire_uses_only_validated_director_selection -q
```

Expected: fail on missing narrator system-prompt instructions while still confirming the existing wire validation.

- [ ] **Step 3: Add the prompt guidance only**

Append concise instructions to the existing narrator system prompt in `_narrator_request`: respond to the latest action/dialogue using eligible current scene and memory details; advance the scene with a specific supported reaction or consequence; avoid repeated generic openings; preserve selected character voice, knowledge, and plausible presence; leave player actions/thoughts to the player; do not force choices or invent canon. Do not change selected-cast validation, context packing, schema, provider settings, or stored data.

- [ ] **Step 4: Run focused backend verification**

Run from the repository root:

```powershell
rtk pytest backend/tests/test_generation_durable.py -q
```

Expected: the durable generation tests pass, including the new prompt assertion and existing selected-character wire checks.

---

## Final verification

After both tasks are reviewed, run from `frontend`:

```powershell
rtk npm test
rtk npm run build
```

Run from the repository root:

```powershell
rtk pytest -q
```

Report the actual RED and GREEN results, full test totals, and any limits. Do not infer model prose quality from fake-provider tests or call a real model.
