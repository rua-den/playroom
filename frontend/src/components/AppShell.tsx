import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError } from "../api/client";
import type { CampaignCreatePayload, CampaignProjection, CampaignSummary, Owner } from "../api/types";
import { Markdown } from "./Markdown";
import { ProfileEditor } from "./ProfileEditor";
import { MemoryLibrary } from "./MemoryLibrary";
import { SceneEditor } from "./SceneEditor";
import { SettingsPanel } from "./SettingsPanel";
import { GenerationComposer } from "./GenerationComposer";
import { ThemeSelector } from "./ThemeSelector";
import { ChatGptImport } from "./ChatGptImport";

const RECOVERABLE_JOB_STATUSES = new Set(["queued", "running", "cancelling", "interrupted", "candidate"]);
export function recoverableJobCount(jobs: Array<{ status?: string }>) { return jobs.filter((job) => RECOVERABLE_JOB_STATUSES.has(job.status ?? "")).length; }
export function recoverableJobSummary(count: number) { return `Có thể khôi phục trong danh sách (tối đa 20 việc): ${count}`; }

interface AppShellProps { owner: Owner; onLogout: () => void; notice?: string | null; }
type CharacterDraft = { id: string; name: string; aliases: string };
type CreateDraft = { title: string; worldName: string; worldDescription: string; personaName: string; personaDescription: string; characters: CharacterDraft[] };

const blankDraft = (): CreateDraft => ({ title: "", worldName: "", worldDescription: "", personaName: "", personaDescription: "", characters: [] });
let fallbackIdCounter = 0;
const newId = () => {
  if (typeof crypto !== "undefined" && crypto.randomUUID) return crypto.randomUUID();
  const bytes = new Uint8Array(16);
  if (typeof crypto !== "undefined" && crypto.getRandomValues) crypto.getRandomValues(bytes);
  else { const seed = `${Date.now()}-${fallbackIdCounter++}-${Math.random()}`; for (let index = 0; index < bytes.length; index += 1) bytes[index] = seed.charCodeAt(index % seed.length) ^ ((index * 31) & 255); }
  bytes[6] = (bytes[6] & 0x0f) | 0x40; bytes[8] = (bytes[8] & 0x3f) | 0x80;
  return Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("").replace(/(.{8})(.{4})(.{4})(.{4})(.{12})/, "$1-$2-$3-$4-$5");
};

function CampaignForm({ onCreated, onCancel, ariaHidden = false }: { onCreated: (campaign: CampaignSummary) => void; onCancel: () => void; ariaHidden?: boolean }) {
  const [draft, setDraft] = useState<CreateDraft>(blankDraft);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  function update(key: keyof Omit<CreateDraft, "characters">, value: string) { setDraft((current) => ({ ...current, [key]: value })); }
  async function submit(event: FormEvent) {
    const native = event.nativeEvent as SubmitEvent & { isComposing?: boolean };
    event.preventDefault();
    if (native.isComposing) return;
    setPending(true); setError(null);
    const payload: CampaignCreatePayload = { title: draft.title.trim(), world: { name: draft.worldName.trim(), description: draft.worldDescription.trim() }, persona: { name: draft.personaName.trim(), description: draft.personaDescription.trim() }, characters: draft.characters.map((character) => ({ id: character.id, name: character.name.trim(), aliases: character.aliases.split(",").map((alias) => alias.trim()).filter(Boolean) })) };
    try { const created = await api.createCampaign(payload); onCreated({ id: created.id, title: created.title, created_at: new Date().toISOString(), updated_at: new Date().toISOString(), archived_at: null }); }
    catch (cause) { setError(cause instanceof ApiError && cause.status >= 400 ? "Không thể tạo chiến dịch. Kiểm tra thông tin rồi thử lại." : "Không thể kết nối tới Playroom."); }
    finally { setPending(false); }
  }
  return <section className="create-card" aria-labelledby="create-title" aria-hidden={ariaHidden}><div className="section-heading"><div><p className="eyebrow">CHƯƠNG MỚI</p><h2 id="create-title">Tạo chiến dịch</h2></div><button type="button" className="quiet-button touch-target" onClick={onCancel}>Đóng</button></div>{error && <div role="alert" className="form-error">{error}</div>}<form className="campaign-form" onKeyDown={(event) => { if (event.key === "Enter" && (event.nativeEvent.isComposing || event.nativeEvent.keyCode === 229)) event.preventDefault(); }} onSubmit={submit}><label htmlFor="campaign-title">Tên chiến dịch</label><input id="campaign-title" required value={draft.title} onChange={(event) => update("title", event.target.value)} /><fieldset><legend>Thế giới</legend><label htmlFor="world-name">Tên thế giới</label><input id="world-name" required value={draft.worldName} onChange={(event) => update("worldName", event.target.value)} /><label htmlFor="world-description">Mô tả thế giới</label><textarea id="world-description" value={draft.worldDescription} onChange={(event) => update("worldDescription", event.target.value)} /></fieldset><fieldset><legend>Persona người chơi</legend><label htmlFor="persona-name">Tên persona</label><input id="persona-name" required value={draft.personaName} onChange={(event) => update("personaName", event.target.value)} /><label htmlFor="persona-description">Mô tả persona</label><textarea id="persona-description" value={draft.personaDescription} onChange={(event) => update("personaDescription", event.target.value)} /></fieldset><fieldset><legend>Nhân vật</legend>{draft.characters.map((character, index) => <div className="character-row" key={character.id}><div className="character-fields"><label htmlFor={`character-name-${index}`}>Tên nhân vật {index + 1}</label><input id={`character-name-${index}`} required value={character.name} onChange={(event) => setDraft((current) => ({ ...current, characters: current.characters.map((item) => item.id === character.id ? { ...item, name: event.target.value } : item) }))} /><label htmlFor={`character-aliases-${index}`}>Bí danh nhân vật {index + 1}</label><input id={`character-aliases-${index}`} placeholder="Cách nhau bằng dấu phẩy" value={character.aliases} onChange={(event) => setDraft((current) => ({ ...current, characters: current.characters.map((item) => item.id === character.id ? { ...item, aliases: event.target.value } : item) }))} /></div><button type="button" className="quiet-button touch-target" onClick={() => setDraft((current) => ({ ...current, characters: current.characters.filter((item) => item.id !== character.id) }))}>Xóa</button></div>)}<button type="button" className="quiet-button touch-target" onClick={() => setDraft((current) => ({ ...current, characters: [...current.characters, { id: newId(), name: "", aliases: "" }] }))}>Thêm nhân vật</button></fieldset><button type="submit" className="primary-button touch-target" disabled={pending}>{pending ? "Đang lưu…" : "Lưu chiến dịch"}</button></form></section>;
}

export function AppShell({ owner, onLogout, notice }: AppShellProps) {
  const [campaigns, setCampaigns] = useState<CampaignSummary[]>([]); const [selectedId, setSelectedId] = useState<string | null>(null); const [projection, setProjection] = useState<CampaignProjection | null>(null); const [loading, setLoading] = useState(true); const [error, setError] = useState<string | null>(null); const [demoInfo, setDemoInfo] = useState<import("../api/types").DemoInfo | null>(null); const [createOpen, setCreateOpen] = useState(false); const [importOpen, setImportOpen] = useState(false); const [drawerOpen, setDrawerOpen] = useState(false); const [detailsOpen, setDetailsOpen] = useState(false); const [settingsOpen, setSettingsOpen] = useState(false); const [editorTab, setEditorTab] = useState<"profiles" | "memory" | "scene">("profiles");
  const drawerTrigger = useRef<HTMLButtonElement>(null); const drawerClose = useRef<HTMLButtonElement>(null); const detailsTrigger = useRef<HTMLButtonElement>(null); const detailsReturn = useRef<HTMLButtonElement | null>(null); const detailsClose = useRef<HTMLButtonElement>(null); const settingsTrigger = useRef<HTMLButtonElement>(null); const settingsClose = useRef<HTMLButtonElement>(null);
  useEffect(() => { let active = true; setLoading(true); if (import.meta.env.PROD) api.getDemoInfo().then((info) => { if (active) setDemoInfo(info); }).catch(() => undefined); api.listCampaigns().then((items) => { if (active) { const safeItems = Array.isArray(items) ? items : []; setCampaigns(safeItems); if (safeItems[0]) setSelectedId(safeItems[0].id); } }).catch(() => { if (active) setError("Không thể tải danh sách chiến dịch."); }).finally(() => { if (active) setLoading(false); }); return () => { active = false; }; }, []);
  useEffect(() => { if (!selectedId) { setProjection(null); return; } let active = true; setProjection(null); setError(null); api.getCampaign(selectedId).then((detail) => api.getCampaignProjection(selectedId, detail.branch_id)).then((next) => { if (active) setProjection(next); }).catch(() => { if (active) setError("Không thể tải chiến dịch này."); }); return () => { active = false; }; }, [selectedId]);
  function closeDrawer() { setDrawerOpen(false); drawerTrigger.current?.focus(); }
  function openDetails(trigger: HTMLButtonElement) { detailsReturn.current = trigger; setDetailsOpen(true); }
  function closeDetails() { setDetailsOpen(false); (detailsReturn.current ?? detailsTrigger.current)?.focus(); }
  useEffect(() => {
    const dialog = drawerOpen ? drawerClose.current?.closest("[role=dialog]") : detailsOpen ? detailsClose.current?.closest("[role=dialog]") : null;
    const close = drawerOpen ? closeDrawer : detailsOpen ? closeDetails : null;
    if (!dialog || !close) return;
    const closeDialog = close;
    const dialogElement = dialog;
    (drawerOpen ? drawerClose.current : detailsClose.current)?.focus();
    function handleKey(event: KeyboardEvent) {
      if (event.key === "Escape") { event.preventDefault(); closeDialog(); return; }
      if (event.key !== "Tab") return;
      const focusable = Array.from(dialogElement.querySelectorAll<HTMLElement>("button, [href], input, textarea, select, [tabindex]:not([tabindex='-1'])"));
      if (!focusable.length) return;
      const first = focusable[0]; const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
    document.addEventListener("keydown", handleKey); return () => document.removeEventListener("keydown", handleKey);
  }, [drawerOpen, detailsOpen]);
  function closeSettings() { setSettingsOpen(false); settingsTrigger.current?.focus(); }
  useEffect(() => {
    if (!settingsOpen) return;
    const dialog = settingsClose.current?.closest("[role=dialog]");
    if (!dialog) return;
    const dialogElement = dialog;
    settingsClose.current?.focus();
    function handleKey(event: KeyboardEvent) {
      if (event.key === "Escape") { event.preventDefault(); closeSettings(); return; }
      if (event.key !== "Tab") return;
      const focusable = Array.from(dialogElement.querySelectorAll<HTMLElement>("button, [href], input, textarea, select, [tabindex]:not([tabindex='-1'])"));
      if (!focusable.length) return;
      const first = focusable[0]; const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
    document.addEventListener("keydown", handleKey); return () => document.removeEventListener("keydown", handleKey);
  }, [settingsOpen]);
  const selected = useMemo(() => campaigns.find((item) => item.id === selectedId) ?? null, [campaigns, selectedId]);
  async function refreshProjection() { if (!selectedId) return undefined; try { const detail = await api.getCampaign(selectedId); const next = await api.getCampaignProjection(selectedId, detail.branch_id); setProjection(next); return next; } catch { setError("Không thể làm mới chiến dịch."); return undefined; } }
  const editorChanged = () => refreshProjection();
  function created(campaign: CampaignSummary) { setCampaigns((current) => [campaign, ...current]); setCreateOpen(false); setImportOpen(false); setSelectedId(campaign.id); }
  if (loading) return <main className="app-shell loading-screen" role="status">Đang tải phòng truyện…</main>;
  const contextPanel = projection && <ContextPanel projection={projection} editorTab={editorTab} setEditorTab={setEditorTab} editorChanged={editorChanged} />;
  return <main className="app-shell story-app">
    <header className="topbar" aria-hidden={drawerOpen || detailsOpen || settingsOpen}>
      <div className="wordmark"><span className="brand-mark small" aria-hidden="true">✦</span><span>Playroom</span>{demoInfo?.mode === "synthetic" && <span className="demo-badge">{demoInfo.label}</span>}</div>
      {!createOpen && campaigns.length > 0 && <div className="campaign-controls">
        <label htmlFor="campaign-select">Chiến dịch</label>
        <select id="campaign-select" aria-label="Chiến dịch hiện tại" value={selectedId ?? ""} onChange={(event) => setSelectedId(event.target.value)}>{campaigns.map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}</select>
        <button type="button" className="quiet-button touch-target" onClick={() => setCreateOpen(true)}>Mới</button>
        <button type="button" className="quiet-button touch-target" onClick={() => { setCreateOpen(false); setImportOpen(true); }}>Nhập ChatGPT</button>
        {campaigns.length > 1 && <div className="campaign-quick-list" aria-label="Chiến dịch gần đây">{campaigns.map((item) => <button type="button" className="campaign-item" key={`quick-${item.id}`} onClick={() => setSelectedId(item.id)} aria-pressed={item.id === selectedId}>{item.title}</button>)}</div>}
      </div>}
      <div className="account-menu">
        <span className="account-email">{owner.email}</span>
        {projection && !createOpen && <button type="button" className="quiet-button touch-target context-trigger" onClick={(event) => openDetails(event.currentTarget)}>Mở hồ sơ và ký ức</button>}
        <button type="button" className="quiet-button touch-target" onClick={() => setSettingsOpen(true)} ref={settingsTrigger}>Cài đặt</button>
        <button type="button" className="quiet-button touch-target" onClick={onLogout}>Đăng xuất</button>
      </div>
    </header>
    {notice && <div role="alert" className="form-error shell-notice" aria-hidden={settingsOpen}> {notice}</div>}
    {importOpen ? <ChatGptImport onImported={created} onCancel={() => setImportOpen(false)} /> : !campaigns.length && !createOpen && error ? <section className="empty-campaign" aria-hidden={settingsOpen}><h1>Chào mừng trở lại</h1><div role="alert" className="form-error">{error}</div></section> : !campaigns.length && !createOpen ? <section className="empty-campaign" aria-labelledby="empty-campaign-title" aria-hidden={settingsOpen}><p className="eyebrow">PHÒNG VIẾT RIÊNG</p><h1 id="empty-campaign-title">Chào mừng trở lại</h1><p>Thiết lập thế giới và persona trước khi mở chương đầu tiên.</p><button type="button" className="primary-button touch-target" onClick={() => setCreateOpen(true)}>Tạo chiến dịch đầu tiên</button><button type="button" className="quiet-button touch-target" onClick={() => setImportOpen(true)}>Nhập hội thoại ChatGPT</button></section> : createOpen ? <CampaignForm onCreated={created} onCancel={() => setCreateOpen(false)} ariaHidden={settingsOpen} /> : <>
      <div className="mobile-actions" aria-hidden={drawerOpen || detailsOpen || settingsOpen}>
        <button type="button" className="quiet-button touch-target mobile-campaign-trigger" onClick={() => setDrawerOpen(true)} ref={drawerTrigger}>Chiến dịch</button>
        <button type="button" className="quiet-button touch-target" onClick={(event) => openDetails(event.currentTarget)} ref={detailsTrigger}>AI đang nhớ gì</button>
      </div>
      <div className="workspace-grid" aria-hidden={drawerOpen || detailsOpen || settingsOpen}>
        <section className="story-column conversation-column">
          {error && <div role="alert" className="form-error">{error}</div>}
          {projection ? <><h1>{projection.campaign.title}</h1>{projection.transcript.length ? <div className="transcript">{projection.transcript.map((turn) => <article className="story-turn" key={turn.revision_id}>{turn.input_segments?.length ? <div className="input-segments">{turn.input_segments.map((segment, index) => <p className={`input-segment ${segment.kind}`} key={`${turn.revision_id}-input-${index}`}>{segment.text}</p>)}</div> : <p className="turn-action">{turn.action_text}</p>}{turn.output_segments?.length ? <div className="roleplay-segments">{turn.output_segments.map((segment, index) => <div className={`roleplay-segment ${segment.kind}`} key={`${turn.revision_id}-${index}`}>{segment.character_id ? <strong>{projection.profiles[`character:${segment.character_id}`]?.data.name as string ?? segment.character_id}: </strong> : null}<Markdown source={segment.text} /></div>)}</div> : <Markdown source={turn.narrative_text} />}</article>)}</div> : <div className="story-empty"><h2>Chương đầu tiên đang chờ bạn.</h2><p>Thế giới đã sẵn sàng. Bạn có thể tiếp tục thiết lập hồ sơ và ký ức.</p></div>}</> : <div className="loading-story" role="status">Đang mở chiến dịch…</div>}
          {projection && (projection.import_review?.required ? <ImportReviewPanel projection={projection} onApproved={editorChanged} /> : <GenerationComposer ownerId={owner.id} projection={projection} profileId="" onCommitted={editorChanged} />)}
        </section>
      </div>
    </>}
    {drawerOpen && <div className="mobile-overlay"><section className="mobile-drawer" role="dialog" aria-modal="true" aria-labelledby="campaign-drawer-title"><div className="section-heading"><h2 id="campaign-drawer-title">Danh sách chiến dịch</h2><button type="button" className="quiet-button touch-target" onClick={closeDrawer} ref={drawerClose}>Đóng danh sách chiến dịch</button></div>{campaigns.map((item) => <button type="button" className="campaign-item touch-target" key={item.id} aria-pressed={item.id === selectedId} onClick={() => { setSelectedId(item.id); closeDrawer(); }}>{item.title}</button>)}</section></div>}
    {detailsOpen && <div className="mobile-overlay context-overlay"><section className="mobile-sheet context-panel" role="dialog" aria-modal="true" aria-labelledby="details-sheet-title"><div className="section-heading"><h2 id="details-sheet-title">Hồ sơ và ký ức</h2><button type="button" className="quiet-button touch-target" onClick={closeDetails} ref={detailsClose}>Đóng hồ sơ và ký ức</button></div>{contextPanel}</section></div>}
    {settingsOpen && <div className="mobile-overlay"><section className="mobile-sheet" role="dialog" aria-modal="true" aria-labelledby="settings-title"><div className="section-heading"><h2 id="settings-title">Cài đặt</h2><button type="button" className="quiet-button touch-target" onClick={closeSettings} ref={settingsClose}>Đóng cài đặt</button></div><ThemeSelector /><SettingsPanel /></section></div>}
  </main>;
}

export function ImportReviewPanel({ projection, onApproved }: { projection: CampaignProjection; onApproved: () => void }) {
  const [review, setReview] = useState({ persona: false, npc_voice_presence: false, canon_known_by_narrator_only: false, missing_history: false });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [memory, setMemory] = useState<import("../api/types").MemoryVersion[] | null>(null);
  const [scene, setScene] = useState<import("../api/types").SceneResponse | null>(null);
  const [snapshotError, setSnapshotError] = useState<string | null>(null);
  const [snapshotLoading, setSnapshotLoading] = useState(true);
  const checkpointId = projection.branch.checkpoint_id;
  const checkpointRef = useRef(checkpointId);
  const identityRef = useRef(`${projection.campaign.id}:${projection.branch.id}:${checkpointId}`);
  const mountedRef = useRef(true);
  identityRef.current = `${projection.campaign.id}:${projection.branch.id}:${checkpointId}`;
  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);
  useEffect(() => { checkpointRef.current = checkpointId; setReview({ persona: false, npc_voice_presence: false, canon_known_by_narrator_only: false, missing_history: false }); setBusy(false); setError(null); }, [checkpointId]);
  useEffect(() => {
    let active = true;
    setSnapshotLoading(true); setSnapshotError(null); setMemory(null); setScene(null);
    Promise.all([api.listMemory(projection.campaign.id, projection.branch.id), api.getScene(projection.campaign.id, projection.branch.id)])
      .then(([nextMemory, nextScene]) => { if (active) { setMemory(nextMemory); setScene(nextScene); setSnapshotLoading(false); } })
      .catch(() => { if (active) { setSnapshotError("Không thể tải đầy đủ ký ức và cảnh hiện tại. Hãy tải lại rồi kiểm tra lại trước khi duyệt."); setSnapshotLoading(false); } });
    return () => { active = false; };
  }, [projection.campaign.id, projection.branch.id, checkpointId]);
  const submit = async () => {
    if (snapshotLoading || snapshotError || !memory || !scene) return;
    const targetCheckpointId = checkpointId;
    const targetIdentity = `${projection.campaign.id}:${projection.branch.id}:${targetCheckpointId}`;
    if (checkpointRef.current !== targetCheckpointId) return;
    setBusy(true); setError(null);
    try {
      await api.approveChatGptImport(projection.campaign.id, { branch_id: projection.branch.id, checkpoint_id: projection.branch.checkpoint_id, review });
      if (mountedRef.current && checkpointRef.current === targetCheckpointId && identityRef.current === targetIdentity) onApproved();
    } catch (cause) {
      if (mountedRef.current && identityRef.current === targetIdentity) setError(cause instanceof Error ? cause.message : "Không thể lưu duyệt checkpoint.");
    }
    finally {
      if (mountedRef.current && identityRef.current === targetIdentity) setBusy(false);
    }
  };
  const profiles = Object.entries(projection.profiles);
  const persona = projection.profiles.persona?.data;
  const characters = profiles.filter(([key, value]) => key.startsWith("character:") || value.kind === "character");
  const sceneItems = Object.values(scene?.scenes ?? {});
  const warnings = projection.import_review?.warnings ?? [];
  const ready = !snapshotLoading && !snapshotError && !!memory && !!scene;
  return <section className="create-card import-review-panel" aria-labelledby="import-review-title">
    <p className="eyebrow">CẦN DUYỆT RIÊNG</p><h2 id="import-review-title">Kiểm tra checkpoint nhập</h2>
    <p>Chiến dịch đang khóa Send. Hãy kiểm tra dữ liệu thực tế bên dưới, sửa trong Hồ sơ / Cảnh / Ký ức nếu cần, rồi xác nhận từng mục.</p>
    {snapshotLoading && <p role="status">Đang tải snapshot hồ sơ, ký ức và cảnh…</p>}
    {snapshotError && <div role="alert" className="form-error">{snapshotError}</div>}
    {error && <div role="alert" className="form-error">{error}</div>}
    <div className="import-review-snapshot" aria-label="Snapshot checkpoint nhập">
      <section><h3>Persona người chơi</h3><p><strong>{String(persona?.name ?? "Chưa có tên")}</strong></p><p>{String(persona?.description ?? "Chưa có mô tả.")}</p></section>
      <section><h3>NPC, giọng nói và hiện diện</h3>{characters.length ? characters.map(([key, profile]) => <p key={key}><strong>{String(profile.data.name ?? key)}</strong>: {String(profile.data.description ?? "Chưa có mô tả giọng nói.")}</p>) : <p>Chưa có NPC trong hồ sơ.</p>}</section>
      <section><h3>Cảnh hiện tại</h3>{sceneItems.length ? sceneItems.map((item) => <p key={item.id}><strong>{String(item.name ?? "Cảnh chưa đặt tên")}</strong>{item.id === scene?.focus_scene_id ? " · đang diễn ra" : ""} · Có mặt: {item.present_ids.length ? item.present_ids.map((id) => String(projection.profiles[`character:${id}`]?.data.name ?? id)).join(", ") : "chưa ghi nhận"}</p>) : <p>Chưa có cảnh nào được ghi nhận.</p>}</section>
      <section><h3>Ký ức và phạm vi biết</h3>{memory?.length ? memory.map((item) => <p key={`${item.memory_id}-${item.version}`}><strong>{item.knowledge_scope === "narrator_only" ? "Chỉ người kể" : item.knowledge_scope === "known_by" ? `Nhân vật biết: ${(item.known_by ?? []).join(", ") || "chưa ghi rõ"}` : "Công khai"}</strong>: {item.text}</p>) : <p>Chưa có ký ức đã lưu.</p>}</section>
      <section><h3>Lịch sử và nguồn</h3><p>{projection.import_review?.paired_turns ?? projection.transcript.length} cặp lượt đã nhập. Mã hội thoại nguồn: {projection.import_review?.source_conversation_id ?? "không có"}.</p><p>{projection.import_review?.skipped_messages == null ? "Chưa xác định số tin nhắn bị bỏ qua." : `${projection.import_review.skipped_messages} tin nhắn bị bỏ qua vì không đủ dữ liệu nhập.`}</p>{warnings.length ? warnings.map((warning) => <p className="form-error" key={warning}>{warning}</p>) : projection.import_review?.skipped_messages ? <p className="form-error">Có khoảng trống trong lịch sử; hãy xem kỹ trước khi coi nội dung là canon.</p> : <p>Không có cảnh báo nguồn.</p>}</section>
    </div>
    <label><input type="checkbox" checked={review.persona} disabled={!ready} onChange={(event) => setReview((current) => ({ ...current, persona: event.target.checked }))} /> Persona đúng và người chơi vẫn tự quyết định lời nói, hành động.</label>
    <label><input type="checkbox" checked={review.npc_voice_presence} disabled={!ready} onChange={(event) => setReview((current) => ({ ...current, npc_voice_presence: event.target.checked }))} /> Hồ sơ, giọng nói và nhân vật đang có mặt đã đúng.</label>
    <label><input type="checkbox" checked={review.canon_known_by_narrator_only} disabled={!ready} onChange={(event) => setReview((current) => ({ ...current, canon_known_by_narrator_only: event.target.checked }))} /> Ai biết từng thông tin và bí mật của người kể đã được kiểm tra.</label>
    <label><input type="checkbox" checked={review.missing_history} disabled={!ready} onChange={(event) => setReview((current) => ({ ...current, missing_history: event.target.checked }))} /> Lịch sử thiếu và cảnh báo nguồn đã được ghi nhận, không coi là canon.</label>
    <button className="primary-button touch-target" type="button" disabled={!ready || busy || Object.values(review).some((value) => !value)} onClick={() => void submit()}>{busy ? "Đang lưu…" : "Duyệt checkpoint và bật Send"}</button>
  </section>;
}

function ProfileBlock({ title, profile }: { title: string; profile?: { data: Record<string, unknown> } }) { if (!profile) return null; const name = typeof profile.data.name === "string" ? profile.data.name : title; const description = typeof profile.data.description === "string" ? profile.data.description : ""; return <section className="profile-block"><h3>{name}</h3>{description && <p>{description}</p>}</section>; }

function ContextPanel({ projection, editorTab, setEditorTab, editorChanged }: { projection: CampaignProjection; editorTab: "profiles" | "memory" | "scene"; setEditorTab: (tab: "profiles" | "memory" | "scene") => void; editorChanged: () => void }) {
  return <>
    <div className="editor-tabs" aria-label="Nội dung phụ trợ">
      <button type="button" aria-pressed={editorTab === "profiles"} className="quiet-button touch-target" onClick={() => setEditorTab("profiles")}>Hồ sơ</button>
      <button type="button" aria-pressed={editorTab === "memory"} className="quiet-button touch-target" onClick={() => setEditorTab("memory")}>Ký ức</button>
      <button type="button" aria-pressed={editorTab === "scene"} className="quiet-button touch-target" onClick={() => setEditorTab("scene")}>Cảnh</button>
    </div>
    <ProfileBlock title="Thế giới" profile={projection.profiles.world} />
    <ProfileBlock title="Persona" profile={projection.profiles.persona} />
    <p className="details-meta">{recoverableJobSummary(recoverableJobCount(projection.jobs))}</p>
    {editorTab === "profiles" && <ProfileEditor campaignId={projection.campaign.id} branchId={projection.branch.id} stateVersion={projection.branch.state_version} profiles={projection.profiles} onSaved={editorChanged} onConflict={editorChanged} />}
    {editorTab === "memory" && <MemoryLibrary campaignId={projection.campaign.id} branchId={projection.branch.id} stateVersion={projection.branch.state_version} sourceRevisionIds={projection.transcript.map((turn) => turn.revision_id)} retrievalPolicy={projection.checkpoint.retrieval_policy} onChanged={editorChanged} onConflict={editorChanged} />}
    {editorTab === "scene" && <SceneEditor campaignId={projection.campaign.id} branchId={projection.branch.id} stateVersion={projection.branch.state_version} onSaved={editorChanged} onConflict={editorChanged} characters={Object.entries(projection.profiles).filter(([key]) => key.startsWith("character:")).map(([, profile]) => ({ id: String(profile.data.id ?? ""), name: String(profile.data.name ?? "Nhân vật") }))} />}
  </>;
}
