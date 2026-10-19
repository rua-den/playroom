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
import { LegacyImport } from "./LegacyImport";
import { Modal } from "./Modal";
import { ToastProvider, useToast } from "./Toast";

const RECOVERABLE_JOB_STATUSES = new Set(["queued", "running", "cancelling", "interrupted", "candidate"]);
export function recoverableJobCount(jobs: Array<{ status?: string }>) { return jobs.filter((job) => RECOVERABLE_JOB_STATUSES.has(job.status ?? "")).length; }
export function recoverableJobSummary(count: number) { return `Có thể khôi phục trong danh sách (tối đa 20 việc): ${count}`; }

function profileName(profiles: Record<string, { data: Record<string, unknown> }>, id: string) {
  const profile = Object.values(profiles).find((candidate) => candidate.data.id === id);
  const name = profile?.data.name;
  return typeof name === "string" && name ? `${name} (${id})` : id;
}

function safeStructuredValue(value: unknown): string {
  if (typeof value === "string") return value;
  if (value == null) return "—";
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  try { return JSON.stringify(value); } catch { return "[không thể hiển thị]"; }
}

function StructuredFields({ data, profiles, idFields = [] }: { data: Record<string, unknown>; profiles: Record<string, { data: Record<string, unknown> }>; idFields?: string[] }) {
  const entries = Object.entries(data).filter(([key]) => !["name", "description"].includes(key));
  if (!entries.length) return null;
  return <details><summary>Chi tiết cấu trúc</summary><dl>{entries.map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{idFields.includes(key) && Array.isArray(value) ? value.map((id) => <span key={String(id)}>{profileName(profiles, String(id))} </span>) : safeStructuredValue(value)}</dd></div>)}</dl></details>;
}

interface AppShellProps { owner: Owner; onLogout: () => void; notice?: string | null; }
type CharacterDraft = { id: string; name: string; aliases: string };
type CreateDraft = { title: string; worldName: string; worldDescription: string; personaName: string; personaDescription: string; characters: CharacterDraft[] };

const blankDraft = (): CreateDraft => ({ title: "", worldName: "", worldDescription: "", personaName: "", personaDescription: "", characters: [] });
export function lastStoryStorageKey(ownerId: string) { return `playroom:last-story:${ownerId}`; }
function readLastStoryId(ownerId: string): string | null {
  try {
    const value = window.localStorage.getItem(lastStoryStorageKey(ownerId));
    return value && value.length < 256 ? value : null;
  } catch { return null; }
}
function writeLastStoryId(ownerId: string, storyId: string) {
  try { window.localStorage.setItem(lastStoryStorageKey(ownerId), storyId); } catch { /* storage may be blocked */ }
}
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
  const toast = useToast();
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
    try { const created = await api.createCampaign(payload); toast.success("Đã tạo truyện mới."); onCreated({ id: created.id, title: created.title, created_at: new Date().toISOString(), updated_at: new Date().toISOString(), archived_at: null }); }
    catch (cause) { const message = cause instanceof ApiError && cause.status >= 400 ? "Không thể tạo truyện. Kiểm tra thông tin rồi thử lại." : "Không thể kết nối tới Playroom."; setError(message); toast.error(message); }
    finally { setPending(false); }
  }
  return <section className="create-card" aria-labelledby="create-title" aria-hidden={ariaHidden}><div className="section-heading"><div><p className="eyebrow">TRUYỆN MỚI</p><h2 id="create-title">Tạo truyện mới</h2><p className="form-hint">Mỗi truyện có bối cảnh, nhân vật và lịch sử trò chuyện riêng.</p></div><button type="button" className="quiet-button touch-target" onClick={onCancel}>Đóng</button></div>{error && <div role="alert" className="form-error">{error}</div>}<form className="campaign-form" onKeyDown={(event) => { if (event.key === "Enter" && (event.nativeEvent.isComposing || event.nativeEvent.keyCode === 229)) event.preventDefault(); }} onSubmit={submit}><label htmlFor="campaign-title">Tên truyện</label><input id="campaign-title" required value={draft.title} onChange={(event) => update("title", event.target.value)} /><fieldset><legend>Thế giới</legend><label htmlFor="world-name">Tên thế giới</label><input id="world-name" required value={draft.worldName} onChange={(event) => update("worldName", event.target.value)} /><label htmlFor="world-description">Mô tả thế giới</label><textarea id="world-description" value={draft.worldDescription} onChange={(event) => update("worldDescription", event.target.value)} /></fieldset><fieldset><legend>Persona người chơi</legend><label htmlFor="persona-name">Tên persona</label><input id="persona-name" required value={draft.personaName} onChange={(event) => update("personaName", event.target.value)} /><label htmlFor="persona-description">Mô tả persona</label><textarea id="persona-description" value={draft.personaDescription} onChange={(event) => update("personaDescription", event.target.value)} /></fieldset><fieldset><legend>Nhân vật</legend>{draft.characters.map((character, index) => <div className="character-row" key={character.id}><div className="character-fields"><label htmlFor={`character-name-${index}`}>Tên nhân vật {index + 1}</label><input id={`character-name-${index}`} required value={character.name} onChange={(event) => setDraft((current) => ({ ...current, characters: current.characters.map((item) => item.id === character.id ? { ...item, name: event.target.value } : item) }))} /><label htmlFor={`character-aliases-${index}`}>Bí danh nhân vật {index + 1}</label><input id={`character-aliases-${index}`} placeholder="Cách nhau bằng dấu phẩy" value={character.aliases} onChange={(event) => setDraft((current) => ({ ...current, characters: current.characters.map((item) => item.id === character.id ? { ...item, aliases: event.target.value } : item) }))} /></div><button type="button" className="quiet-button touch-target" onClick={() => setDraft((current) => ({ ...current, characters: current.characters.filter((item) => item.id !== character.id) }))}>Xóa</button></div>)}<button type="button" className="quiet-button touch-target" onClick={() => setDraft((current) => ({ ...current, characters: [...current.characters, { id: newId(), name: "", aliases: "" }] }))}>Thêm nhân vật</button></fieldset><button type="submit" className="primary-button touch-target" disabled={pending}>{pending ? "Đang lưu…" : "Lưu truyện"}</button></form></section>;
}

function AppShellContent({ owner, onLogout, notice }: AppShellProps) {
  const [campaigns, setCampaigns] = useState<CampaignSummary[]>([]); const [selectedId, setSelectedId] = useState<string | null>(null); const [projection, setProjection] = useState<CampaignProjection | null>(null); const [loading, setLoading] = useState(true); const [error, setError] = useState<string | null>(null); const [demoInfo, setDemoInfo] = useState<import("../api/types").DemoInfo | null>(null); const [createOpen, setCreateOpen] = useState(false); const [createInstance, setCreateInstance] = useState(0); const [importOpen, setImportOpen] = useState(false); const [importInstance, setImportInstance] = useState(0); const [libraryOpen, setLibraryOpen] = useState(true); const [importMode, setImportMode] = useState<"chatgpt" | "legacy">("chatgpt"); const [drawerOpen, setDrawerOpen] = useState(false); const [detailsOpen, setDetailsOpen] = useState(false); const [settingsOpen, setSettingsOpen] = useState(false); const [editorTab, setEditorTab] = useState<"profiles" | "memory" | "scene">("profiles");
  const selectedIdRef = useRef<string | null>(selectedId); selectedIdRef.current = selectedId;
  const ownerRef = useRef(owner.id);
  useEffect(() => { if (ownerRef.current === owner.id) return; ownerRef.current = owner.id; setCampaigns([]); setSelectedId(null); setProjection(null); setError(null); setLibraryOpen(true); }, [owner.id]);
  const projectionRequest = useRef(0);
  const drawerTrigger = useRef<HTMLButtonElement>(null);
  useEffect(() => { let active = true; setLoading(true); if (import.meta.env.PROD) api.getDemoInfo().then((info) => { if (active) setDemoInfo(info); }).catch(() => undefined); api.listCampaigns().then((items) => { if (active) { const safeItems = Array.isArray(items) ? items : []; const remembered = readLastStoryId(owner.id); const restored = remembered && safeItems.some((item) => item.id === remembered) ? remembered : null; setCampaigns(safeItems); setSelectedId(restored); setLibraryOpen(!restored); } }).catch(() => { if (active) setError("Không thể tải thư viện truyện."); }).finally(() => { if (active) setLoading(false); }); return () => { active = false; }; }, [owner.id]);
  useEffect(() => { if (!selectedId) { setProjection(null); return; } let active = true; setProjection(null); setError(null); api.getCampaign(selectedId).then((detail) => api.getCampaignProjection(selectedId, detail.branch_id)).then((next) => { if (active) setProjection(next); }).catch(() => { if (active) setError("Không thể tải truyện này."); }); return () => { active = false; }; }, [selectedId]);
  useEffect(() => { projectionRequest.current += 1; }, [selectedId]);
  function closeDrawer() { setDrawerOpen(false); }
  function openDetails() { setDetailsOpen(true); }
  function closeDetails() { setDetailsOpen(false); }
  function closeSettings() { setSettingsOpen(false); }
  const selected = useMemo(() => campaigns.find((item) => item.id === selectedId) ?? null, [campaigns, selectedId]);
  async function refreshProjection() { if (!selectedId) return undefined; const targetId = selectedId; const requestId = ++projectionRequest.current; try { const detail = await api.getCampaign(targetId); const next = await api.getCampaignProjection(targetId, detail.branch_id); if (projectionRequest.current !== requestId || selectedIdRef.current !== targetId) return undefined; setProjection(next); return next; } catch { if (projectionRequest.current === requestId && selectedIdRef.current === targetId) setError("Không thể làm mới truyện."); return undefined; } }
  const editorChanged = () => refreshProjection();
  function chooseStory(id: string) { if (id !== selectedIdRef.current) setProjection(null); setSelectedId(id); writeLastStoryId(owner.id, id); setLibraryOpen(false); setCreateOpen(false); setImportOpen(false); }
  function created(campaign: CampaignSummary) { setCampaigns((current) => [campaign, ...current]); setCreateInstance((current) => current + 1); setImportInstance((current) => current + 1); setCreateOpen(false); setImportOpen(false); chooseStory(campaign.id); }
  function openCreate() { setImportOpen(false); setCreateOpen(true); }
  function openImport(mode: "chatgpt" | "legacy") { setCreateOpen(false); setImportMode(mode); setImportOpen(true); }
  const formatStoryDate = (value: string) => { const date = new Date(value); return Number.isNaN(date.valueOf()) ? "" : new Intl.DateTimeFormat("vi-VN", { dateStyle: "medium" }).format(date); };
  const library = <section className="story-library" aria-labelledby="library-title" aria-hidden={settingsOpen || drawerOpen || detailsOpen || createOpen || importOpen}><div className="section-heading"><div><h1 id="library-title">Thư viện truyện</h1><p className="library-intro">Mở lại một câu chuyện đã lưu hoặc bắt đầu một thế giới mới.</p></div>{(!error || campaigns.length > 0) && <button type="button" className="primary-button touch-target" onClick={openCreate}>+ Tạo truyện mới</button>}</div><div className="story-library-grid">{campaigns.map((item) => <article className={`story-card ${item.id === selectedId ? "is-current" : ""}`} key={item.id}><div><p className="story-card-status">{item.id === selectedId ? "Đang đọc" : item.archived_at ? "Đã lưu trữ" : "Đã lưu"}</p><h2>{item.title}</h2><p className="details-meta">Cập nhật {formatStoryDate(item.updated_at)}</p></div><button type="button" className="quiet-button touch-target" onClick={() => chooseStory(item.id)}>{item.id === selectedId ? "Đọc tiếp" : "Mở truyện"}</button></article>)}</div>{(!error || campaigns.length > 0) && <div className="library-import-actions"><button type="button" className="quiet-button touch-target" onClick={() => openImport("chatgpt")}>Nhập hội thoại ChatGPT</button><button type="button" className="quiet-button touch-target" onClick={() => openImport("legacy")}>Nhập Legacy Bundle</button></div>}</section>;
  if (loading) return <main className="app-shell loading-screen" role="status">Đang tải phòng truyện…</main>;
  const contextPanel = projection && <ContextPanel projection={projection} editorTab={editorTab} setEditorTab={setEditorTab} editorChanged={editorChanged} />;
  return <main className={`app-shell story-app ${error && !campaigns.length ? "catalog-failed" : ""}`}>
    <header className="topbar" aria-hidden={drawerOpen || detailsOpen || settingsOpen || createOpen || importOpen}>
      <div className="wordmark"><span className="brand-mark small" aria-hidden="true"><svg viewBox="0 0 24 24" width="19" height="19" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="M4 5.5c3.2-.8 5.9-.1 8 1.9v12c-2.1-2-4.8-2.7-8-1.9z"/><path d="M20 5.5c-3.2-.8-5.9-.1-8 1.9v12c2.1-2 4.8-2.7 8-1.9z"/><path d="M7 9h2M15 9h2M7 12h2M15 12h2"/></svg></span><span>Playroom</span>{demoInfo?.mode === "synthetic" && <span className="demo-badge">{demoInfo.label}</span>}</div>
      <div className="campaign-controls">
        <button type="button" className="quiet-button touch-target library-trigger" onClick={() => { setCreateOpen(false); setImportOpen(false); setLibraryOpen(true); }}>Thư viện truyện</button>
      {!libraryOpen && campaigns.length > 0 && <>
        <label htmlFor="campaign-select">Truyện</label>
        <select id="campaign-select" aria-label="Truyện hiện tại" value={selectedId ?? ""} onChange={(event) => chooseStory(event.target.value)}>{campaigns.map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}</select>
        <button type="button" className="quiet-button touch-target" onClick={openCreate}>Tạo truyện mới</button>
        <button type="button" className="quiet-button touch-target" onClick={() => openImport("chatgpt")}>Nhập ChatGPT</button><button type="button" className="quiet-button touch-target" onClick={() => openImport("legacy")}>Nhập Legacy</button>
        {campaigns.length > 1 && <div className="campaign-quick-list" aria-label="Truyện gần đây">{campaigns.map((item) => <button type="button" className="campaign-item" key={`quick-${item.id}`} onClick={() => chooseStory(item.id)} aria-pressed={item.id === selectedId}>{item.title}</button>)}</div>}
      </>}</div>
      <div className="account-menu">
        <span className="account-email">{owner.email}</span>
        {projection && !libraryOpen && <button type="button" className="quiet-button touch-target context-trigger" onClick={openDetails}>Mở hồ sơ và ký ức</button>}
        <button type="button" className="quiet-button touch-target" onClick={() => setSettingsOpen(true)}>Cài đặt</button>
        <button type="button" className="quiet-button touch-target" onClick={onLogout}>Đăng xuất</button>
      </div>
    </header>
    {notice && <div role="alert" className="form-error shell-notice" aria-hidden={drawerOpen || detailsOpen || settingsOpen || createOpen || importOpen}> {notice}</div>}
    {error && !campaigns.length && <a className="catalog-retry" href="/">Thử lại</a>}
    <>{libraryOpen && library}{error && libraryOpen && <div role="alert" className="form-error shell-notice">{error}</div>}<div className={libraryOpen ? "library-story-hidden" : "story-workspace"} aria-hidden={libraryOpen} hidden={libraryOpen}>
      <div className="mobile-actions" aria-hidden={libraryOpen || drawerOpen || detailsOpen || settingsOpen || createOpen || importOpen}>
        <button type="button" className="quiet-button touch-target mobile-campaign-trigger" onClick={() => setDrawerOpen(true)} ref={drawerTrigger}>Truyện và tác vụ</button>
        <button type="button" className="quiet-button touch-target" onClick={openDetails}>AI đang nhớ gì</button>
      </div>
      <div className="workspace-grid" aria-hidden={libraryOpen || drawerOpen || detailsOpen || settingsOpen || createOpen || importOpen}>
        <section className="story-column conversation-column">
          {error && <div role="alert" className="form-error">{error}</div>}
          {projection && <p className="story-reading-label">Đang đọc</p>}
          {projection ? <><h1>{projection.campaign.title}</h1>{projection.transcript.length ? <div className="transcript">{projection.transcript.map((turn) => <article className="story-turn" key={turn.revision_id}>{turn.input_segments?.length ? <div className="input-segments">{turn.input_segments.map((segment, index) => <p className={`input-segment ${segment.kind}`} key={`${turn.revision_id}-input-${index}`}>{segment.text}</p>)}</div> : <p className="turn-action">{turn.action_text}</p>}{turn.output_segments?.length ? <div className="roleplay-segments">{turn.output_segments.map((segment, index) => <div className={`roleplay-segment ${segment.kind}`} key={`${turn.revision_id}-${index}`}>{segment.character_id ? <strong>{projection.profiles[`character:${segment.character_id}`]?.data.name as string ?? segment.character_id}: </strong> : null}<Markdown source={segment.text} /></div>)}</div> : <Markdown source={turn.narrative_text} />}</article>)}</div> : <div className="story-empty"><h2>Chương đầu tiên đang chờ bạn.</h2><p>Thế giới đã sẵn sàng. Bạn có thể tiếp tục thiết lập hồ sơ và ký ức.</p></div>}</> : <div className="loading-story" role="status">Đang mở truyện…</div>}
          {projection && (projection.import_review?.required ? <ImportReviewPanel projection={projection} onApproved={editorChanged} /> : <GenerationComposer ownerId={owner.id} projection={projection} profileId="" onCommitted={editorChanged} demoMode={demoInfo?.mode === "synthetic"} />)}
        </section>
      </div>
    </div>
    </>
    <Modal open={drawerOpen} title="Danh sách truyện" closeLabel="Đóng danh sách truyện" onClose={closeDrawer}>
      {campaigns.map((item) => <button type="button" className="campaign-item touch-target" key={item.id} aria-pressed={item.id === selectedId} onClick={() => { chooseStory(item.id); closeDrawer(); }}>{item.title}</button>)}
      <div className="story-menu-actions" aria-label="Tác vụ thư viện">
        <button type="button" className="quiet-button touch-target" onClick={() => { closeDrawer(); openCreate(); }}>Tạo truyện mới</button>
        <button type="button" className="quiet-button touch-target" onClick={() => { closeDrawer(); openImport("chatgpt"); }}>Nhập ChatGPT</button>
        <button type="button" className="quiet-button touch-target" onClick={() => { closeDrawer(); openImport("legacy"); }}>Nhập Legacy</button>
      </div>
    </Modal>
    <Modal open={detailsOpen} title="Hồ sơ và ký ức" closeLabel="Đóng hồ sơ và ký ức" onClose={closeDetails} size="wide">{contextPanel}</Modal>
    <Modal open={settingsOpen} title="Cài đặt" closeLabel="Đóng cài đặt" onClose={closeSettings} size="wide">{settingsOpen && <><ThemeSelector /><SettingsPanel demoMode={demoInfo?.mode === "synthetic"} /></>}</Modal>
    <Modal open={createOpen} title="Tạo truyện mới" onClose={() => setCreateOpen(false)}><CampaignForm key={createInstance} onCreated={created} onCancel={() => setCreateOpen(false)} /></Modal>
    <Modal open={importOpen} title={importMode === "legacy" ? "Nhập Legacy Story Bundle" : "Nhập hội thoại ChatGPT"} onClose={() => setImportOpen(false)} size="wide">
      {importMode === "legacy" ? <LegacyImport key={`legacy-${importInstance}`} onImported={created} onCancel={() => setImportOpen(false)} /> : <ChatGptImport key={`chatgpt-${importInstance}`} onImported={created} onCancel={() => setImportOpen(false)} />}
    </Modal>
  </main>;
}

export function AppShell(props: AppShellProps) {
  return <ToastProvider key={props.owner.id} ownerKey={props.owner.id}><AppShellContent {...props} /></ToastProvider>;
}

export function ImportReviewPanel({ projection, onApproved }: { projection: CampaignProjection; onApproved: () => void }) {
  const toast = useToast();
  const [review, setReview] = useState({ persona: false, npc_voice_presence: false, canon_known_by_narrator_only: false, missing_history: false });
  const [dataConsent, setDataConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [memory, setMemory] = useState<import("../api/types").MemoryVersion[] | null>(null);
  const [proposals, setProposals] = useState<import("../api/types").MemoryVersion[] | null>(null);
  const [scene, setScene] = useState<import("../api/types").SceneResponse | null>(null);
  const [snapshotError, setSnapshotError] = useState<string | null>(null);
  const [snapshotLoading, setSnapshotLoading] = useState(true);
  const checkpointId = projection.branch.checkpoint_id;
  const sourceIdentity = `${projection.import_review?.source_kind ?? "unknown"}:${projection.import_review?.source_conversation_id ?? ""}`;
  const reviewIdentity = `${projection.campaign.id}:${projection.branch.id}:${checkpointId}:${sourceIdentity}`;
  const checkpointRef = useRef(checkpointId);
  const identityRef = useRef(reviewIdentity);
  const mountedRef = useRef(true);
  identityRef.current = reviewIdentity;
  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);
  useEffect(() => { checkpointRef.current = checkpointId; setReview({ persona: false, npc_voice_presence: false, canon_known_by_narrator_only: false, missing_history: false }); setDataConsent(false); setBusy(false); setError(null); }, [reviewIdentity, checkpointId]);
  useEffect(() => {
    let active = true;
    const targetIdentity = reviewIdentity;
    setSnapshotLoading(true); setSnapshotError(null); setMemory(null); setScene(null); setProposals(null);
    Promise.all([api.listMemory(projection.campaign.id, projection.branch.id), api.getScene(projection.campaign.id, projection.branch.id), projection.import_review?.source_kind === "legacy_bundle" ? api.listProposals(projection.campaign.id, projection.branch.id) : Promise.resolve([] as import("../api/types").MemoryVersion[])])
      .then(([nextMemory, nextScene, nextProposals]) => { if (active && identityRef.current === targetIdentity) { setMemory(nextMemory); setScene(nextScene); setProposals(nextProposals); setSnapshotLoading(false); } })
      .catch(() => { if (active) { setSnapshotError("Không thể tải đầy đủ ký ức và cảnh hiện tại. Hãy tải lại rồi kiểm tra lại trước khi duyệt."); setSnapshotLoading(false); } });
    return () => { active = false; };
  }, [projection.campaign.id, projection.branch.id, checkpointId, reviewIdentity]);
  const submit = async () => {
    if (snapshotLoading || snapshotError || !memory || !scene) return;
    const targetCheckpointId = checkpointId;
    const targetIdentity = reviewIdentity;
    if (checkpointRef.current !== targetCheckpointId || identityRef.current !== targetIdentity) return;
    setBusy(true); setError(null);
    try {
      await api.approveChatGptImport(projection.campaign.id, { branch_id: projection.branch.id, checkpoint_id: projection.branch.checkpoint_id, review: projection.import_review?.source_kind === "legacy_bundle" ? { ...review, provider_data: dataConsent } : review });
      if (mountedRef.current && checkpointRef.current === targetCheckpointId && identityRef.current === targetIdentity) { toast.success("Đã duyệt dữ liệu truyện nhập."); onApproved(); }
    } catch (cause) {
      if (mountedRef.current && identityRef.current === targetIdentity) { setError(cause instanceof Error ? cause.message : "Không thể lưu duyệt checkpoint."); toast.error("Không thể duyệt dữ liệu truyện nhập."); }
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
  const ready = !snapshotLoading && !snapshotError && !!memory && !!scene && !!proposals;
  return <section className="create-card import-review-panel" aria-labelledby="import-review-title">
    <p className="eyebrow">CẦN DUYỆT RIÊNG</p><h2 id="import-review-title">Kiểm tra checkpoint nhập</h2>
    <p>Chiến dịch đang khóa Send. Hãy kiểm tra dữ liệu thực tế bên dưới, sửa trong Hồ sơ / Cảnh / Ký ức nếu cần, rồi xác nhận từng mục.</p>
    {snapshotLoading && <p role="status">Đang tải snapshot hồ sơ, ký ức và cảnh…</p>}
    {snapshotError && <div role="alert" className="form-error">{snapshotError}</div>}
    {error && <div role="alert" className="form-error">{error}</div>}
    <div className="import-review-snapshot" aria-label="Snapshot checkpoint nhập">
      <section><h3>Persona người chơi</h3><p><strong>{String(persona?.name ?? "Chưa có tên")}</strong>{persona?.id ? ` · ID: ${String(persona.id)}` : ""}</p><p>{String(persona?.description ?? "Chưa có mô tả.")}</p>{persona && <StructuredFields data={persona} profiles={projection.profiles} />}</section>
      <section><h3>NPC, giọng nói và hiện diện</h3>{characters.length ? characters.map(([key, profile]) => <div key={key}><p><strong>{String(profile.data.name ?? key)}</strong>{profile.data.id ? ` · ID: ${String(profile.data.id)}` : ""}: {String(profile.data.description ?? "Chưa có mô tả giọng nói.")}</p><StructuredFields data={profile.data} profiles={projection.profiles} /></div>) : <p>Chưa có NPC trong hồ sơ.</p>}</section>
      <section><h3>Cảnh hiện tại</h3>{sceneItems.length ? sceneItems.map((item) => <div key={item.id}><p><strong>{String(item.name ?? "Cảnh chưa đặt tên")}</strong>{item.id === scene?.focus_scene_id ? " · đang diễn ra" : ""} · Có mặt: {item.present_ids.length ? item.present_ids.map((id) => profileName(projection.profiles, String(id))).join(", ") : "chưa ghi nhận"}</p><StructuredFields data={item} profiles={projection.profiles} idFields={["present_ids", "participant_ids"]} /></div>) : <p>Chưa có cảnh nào được ghi nhận.</p>}</section>
      <section><h3>Ký ức và phạm vi biết</h3>{memory?.length ? memory.map((item) => <div key={`${item.memory_id}-${item.version}`}><p><strong>{item.knowledge_scope === "narrator_only" ? "Chỉ người kể" : item.knowledge_scope === "known_by" ? `Nhân vật biết: ${(item.known_by ?? []).map((id) => profileName(projection.profiles, id)).join(", ") || "chưa ghi rõ"}` : "Công khai"}</strong>: {item.text}</p><p>Entity: {(item.entity_ids ?? []).map((id) => profileName(projection.profiles, id)).join(", ") || "—"} · ID memory: {item.memory_id}</p></div>) : <p>Chưa có ký ức đã lưu.</p>}</section>
      <section><h3>Đề xuất ký ức từ nguồn, chưa xác nhận</h3>{proposals?.length ? <><p className="form-error">{proposals.length} mục nguồn đang chờ duyệt. Nếu bạn xác nhận checkpoint Legacy, các đề xuất import còn chờ sẽ được phê duyệt hàng loạt; hãy rà soát từng mục hoặc từ chối các mục không đúng trước khi duyệt.</p>{proposals.map((item) => <div key={`${item.memory_id}-${item.version}`}><p><strong>{item.kind} / {item.knowledge_scope}</strong>: {item.text}</p><p>Known by: {(item.known_by ?? []).map((id) => profileName(projection.profiles, id)).join(", ") || "—"} · Entity: {(item.entity_ids ?? []).map((id) => profileName(projection.profiles, id)).join(", ") || "—"} · ID: {item.memory_id}</p></div>)}</> : <p>Không có đề xuất nhập nào đang chờ.</p>}</section>
      <section><h3>Lịch sử và nguồn</h3><p>{projection.import_review?.paired_turns ?? projection.transcript.length} cặp lượt đã nhập (Legacy Bundle có 0 cặp vì chỉ là sự kiện/tóm tắt). Mã nguồn: {projection.import_review?.source_conversation_id ?? "không có"}.</p><p>{projection.import_review?.skipped_messages == null ? "Chưa xác định số tin nhắn bị bỏ qua." : `${projection.import_review.skipped_messages} tin nhắn bị bỏ qua vì không đủ dữ liệu nhập.`}</p>{projection.import_review?.source_provenance && <details><summary>Nguồn Legacy và checkpoint tiếp tục</summary><p>{projection.import_review.source_provenance.title ?? "Không có tiêu đề nguồn"} · {projection.import_review.source_provenance.format ?? "Không rõ định dạng"} · schema {projection.import_review.source_provenance.schema_version ?? "?"}</p>{projection.import_review.resume_checkpoint && <p>Đã hoàn tất chương {projection.import_review.resume_checkpoint.chapter_last_completed ?? "?"}; chương tiếp theo {projection.import_review.resume_checkpoint.next_chapter_number ?? "?"}; đã viết: {String(projection.import_review.resume_checkpoint.next_chapter_written ?? false)}.</p>}{projection.import_review.review_queue?.map((item, index) => <p key={`${item.issue ?? "gap"}-${index}`}>Khoảng trống: {item.issue ?? "không mô tả"} · Chính sách: {item.policy ?? "không mô tả"}</p>)}</details>}{warnings.length ? warnings.map((warning) => <p className="form-error" key={warning}>{warning}</p>) : projection.import_review?.skipped_messages ? <p className="form-error">Có khoảng trống trong lịch sử; hãy xem kỹ trước khi coi nội dung là canon.</p> : <p>Không có cảnh báo nguồn.</p>}</section>
    </div>
    <label><input type="checkbox" checked={review.persona} disabled={!ready} onChange={(event) => setReview((current) => ({ ...current, persona: event.target.checked }))} /> Persona đúng và người chơi vẫn tự quyết định lời nói, hành động.</label>
    <label><input type="checkbox" checked={review.npc_voice_presence} disabled={!ready} onChange={(event) => setReview((current) => ({ ...current, npc_voice_presence: event.target.checked }))} /> Hồ sơ, giọng nói và nhân vật đang có mặt đã đúng.</label>
    <label><input type="checkbox" checked={review.canon_known_by_narrator_only} disabled={!ready} onChange={(event) => setReview((current) => ({ ...current, canon_known_by_narrator_only: event.target.checked }))} /> Ai biết từng thông tin và bí mật của người kể đã được kiểm tra.</label>
    <label><input type="checkbox" checked={review.missing_history} disabled={!ready} onChange={(event) => setReview((current) => ({ ...current, missing_history: event.target.checked }))} /> Lịch sử thiếu và cảnh báo nguồn đã được ghi nhận, không coi là canon.</label>
    {projection.import_review?.source_kind === "legacy_bundle" && <label><input type="checkbox" disabled={!ready} checked={dataConsent} onChange={(event) => setDataConsent(event.target.checked)} /> Tôi đồng ý: SAU KHI tôi chủ động nhấn Send, Playroom có thể gửi context riêng của chiến dịch tới provider AI tôi đã cấu hình. Việc nhập / duyệt không tự gửi AI.</label>}
    <button className="primary-button touch-target" type="button" disabled={!ready || busy || Object.values(review).some((value) => !value) || (projection.import_review?.source_kind === "legacy_bundle" && !dataConsent)} onClick={() => void submit()}>{busy ? "Đang lưu…" : "Duyệt checkpoint và bật Send"}</button>
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
